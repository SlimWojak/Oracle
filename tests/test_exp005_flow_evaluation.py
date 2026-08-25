from __future__ import annotations

import math
import unittest
from unittest.mock import patch

import numpy as np

from oracle_research.exp004_m0_population import (
    HORIZONS,
    LABEL_FAMILIES,
    OOS_PERIOD_KEYS,
    PERIOD_BY_KEY,
    BaseStatus,
    Cause,
    ClusterRecord,
    M0RiskRow,
    Outcome,
    PopulationResult,
)
from oracle_research.exp005_flow import M0_FLOW_COLUMNS
from oracle_research.exp005_flow_evaluation import (
    FrozenFlowState,
    evaluate_flow_models,
    fit_flow_models,
    mechanical_disposition,
    paired_brier_skill_draws,
)
from oracle_research.exp005_flow_population import build_flow_population


def synthetic_population(*, stage: str = "full") -> PopulationResult:
    rows: list[M0RiskRow] = []
    clusters: list[ClusterRecord] = []
    periods = ("development",) if stage == "development" else (
        "development",
        "validation",
        "test_2025",
        "test_2026",
    )
    for period_offset, period in enumerate(periods):
        start = PERIOD_BY_KEY[period].start_timestamp + 10 * 86_400
        for index in range(96):
            timestamp = start + index * 3_600
            angle = 2.0 * math.pi * index / 24.0
            features = (
                0.001 * ((index % 11) - 5),
                0.01 + 0.0001 * (index % 17),
                0.02 + 0.0002 * (index % 19),
                math.sin(angle),
                math.cos(angle),
                math.sin(2.0 * math.pi * index / 7.0),
                math.cos(2.0 * math.pi * index / 7.0),
            )
            cause = (Cause.UP, Cause.DOWN, Cause.NONE)[
                (index + period_offset) % 3
            ]
            row = M0RiskRow(
                timestamp=timestamp,
                period=period,
                base_status=BaseStatus.ELIGIBLE,
                sigma=features[2],
                impulse=0.0,
                features=features,
                twin_barrier=0.02,
            )
            for horizon in HORIZONS:
                row.scoreable[horizon] = True
                row.exclusion_reasons[horizon] = ()
                for family in LABEL_FAMILIES:
                    passage = timestamp + 60 if cause in {Cause.UP, Cause.DOWN} else None
                    row.outcomes[(family, horizon)] = Outcome(cause, passage)
                    if passage is None:
                        continue
                    cluster_id = f"{family}:{horizon}:{period}:{index}"
                    row.cluster_ids[(family, horizon)] = cluster_id
                    row.cluster_morphology[(family, horizon)] = "ONE_WAY"
                    clusters.append(
                        ClusterRecord(
                            cluster_id=cluster_id,
                            label_family=family,
                            horizon_seconds=horizon,
                            start_timestamp=timestamp,
                            end_timestamp=passage,
                            up_count=int(cause is Cause.UP),
                            down_count=int(cause is Cause.DOWN),
                            up_passage_timestamps=(passage,) if cause is Cause.UP else (),
                            down_passage_timestamps=(passage,) if cause is Cause.DOWN else (),
                        )
                    )
            rows.append(row)
    return PopulationResult(
        rows=tuple(rows),
        clusters=tuple(clusters),
        kappa=0.771724,
        inventory={"stage": stage},
    )


def flow_mapping(population: PopulationResult) -> dict[int, float]:
    return {
        row.timestamp: 0.05 * ((index % 13) - 6) + 0.001 * index
        for index, row in enumerate(population.rows)
    }


def disposition_inputs(skill: float = 0.02):
    skills = {
        (period, family): skill
        for period in OOS_PERIOD_KEYS
        for family in LABEL_FAMILIES
    }
    cells = {
        (period, family, horizon, direction.value): {
            "event_rate": 0.01,
            "episode_precision": 0.10,
            "cluster_recall": 0.20,
            "median_lead_seconds": 900.0 if horizon == 3_600 else 3_600.0,
            "eligible_cluster_count": 30,
        }
        for period in OOS_PERIOD_KEYS
        for family in LABEL_FAMILIES
        for horizon in HORIZONS
        for direction in (Cause.UP, Cause.DOWN)
    }
    return skills, cells


class FrozenFitTests(unittest.TestCase):
    def test_fresh_common_fit_flow_last_kappa_and_exact_state_round_trip(self) -> None:
        base = synthetic_population(stage="development")
        paired = build_flow_population(base, flow_mapping(base))

        from oracle_research import exp005_flow_evaluation as module

        actual_fit = module.fit_frozen_multinomial
        calls: list[tuple[str, ...]] = []

        def recording_fit(*args, **kwargs):
            calls.append(tuple(kwargs["column_names"]))
            return actual_fit(*args, **kwargs)

        with patch.object(module, "fit_frozen_multinomial", side_effect=recording_fit):
            state = fit_flow_models(paired)

        self.assertEqual(calls.count(tuple(M0_FLOW_COLUMNS)), 4)
        self.assertEqual(len(calls), 8)
        self.assertEqual(state.kappa, base.kappa)
        self.assertEqual(
            {support.period for support in state.support_identifiers},
            {"development"},
        )
        restored = FrozenFlowState.from_json(state.to_json())
        self.assertEqual(restored.to_dict(), state.to_dict())
        self.assertEqual(restored.sha256, state.sha256)

    def test_evaluation_uses_frozen_state_without_refit(self) -> None:
        dev_base = synthetic_population(stage="development")
        state = fit_flow_models(
            build_flow_population(dev_base, flow_mapping(dev_base))
        )
        full_base = synthetic_population(stage="full")
        full = build_flow_population(full_base, flow_mapping(full_base))

        with patch(
            "oracle_research.exp005_flow_evaluation.fit_frozen_multinomial"
        ) as fit_mock:
            report = evaluate_flow_models(
                full,
                state,
                bootstrap_draws=3,
                bootstrap_seed=7,
            )

        fit_mock.assert_not_called()
        self.assertIn(report["disposition"], {"PASS", "FAIL", "NULL"})
        self.assertEqual(report["news"], "NEWS_NOT_AVAILABLE")
        cell = report["periods"]["validation"]["fixed"]["cells"]["1h_up"]
        self.assertIn("M0_COMMON", cell)
        self.assertIn("M0_FLOW", cell)
        self.assertEqual(
            report["bootstrap"]["paired_skill_formula"],
            "1 - BS_M0_FLOW / BS_M0_COMMON per draw",
        )


class BootstrapAndDispositionTests(unittest.TestCase):
    def test_paired_bootstrap_uses_ratio_per_draw(self) -> None:
        common = np.asarray([0.20, 0.10, 0.25])
        flow = np.asarray([0.10, 0.12, 0.20])
        np.testing.assert_allclose(
            paired_brier_skill_draws(common, flow),
            1.0 - flow / common,
        )

    def test_mechanical_disposition_edges(self) -> None:
        skills, cells = disposition_inputs()
        self.assertEqual(mechanical_disposition(skills, cells), "PASS")

        adverse, adverse_cells = disposition_inputs(-0.01)
        self.assertEqual(mechanical_disposition(adverse, adverse_cells), "FAIL")

        missed, missed_cells = disposition_inputs()
        first_key = next(iter(missed_cells))
        missed_cells[first_key] = {**missed_cells[first_key], "cluster_recall": 0.099}
        self.assertEqual(mechanical_disposition(missed, missed_cells), "NULL")

        self.assertEqual(
            mechanical_disposition(skills, cells, integrity_failures=("support",)),
            "BLOCKED",
        )
        incomplete = dict(skills)
        incomplete.pop(next(iter(incomplete)))
        self.assertEqual(mechanical_disposition(incomplete, cells), "BLOCKED")


if __name__ == "__main__":
    unittest.main()

