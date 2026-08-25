from __future__ import annotations

import unittest

import numpy as np

from oracle_research.exp004_m0_evaluation import (
    _session,
    _volatility_slice,
    alert_episodes,
    evaluate_m0,
    fit_m0,
)
from oracle_research.exp004_m0_population import (
    HORIZONS,
    LABEL_FAMILIES,
    PERIOD_BY_KEY,
    BaseStatus,
    Cause,
    ClusterRecord,
    M0RiskRow,
    Outcome,
    PopulationResult,
)


class EpisodeTests(unittest.TestCase):
    def test_strictly_adjacent_alerts_chain_and_missing_hour_closes(self) -> None:
        timestamps = np.asarray([0, 3_600, 10_800, 14_400], dtype=np.int64)
        episodes = alert_episodes(
            timestamps,
            np.asarray([True, True, True, False]),
            np.asarray([0, 1, 0, 0]),
        )
        self.assertEqual(len(episodes), 2)
        self.assertEqual((episodes[0].start_timestamp, episodes[0].end_timestamp), (0, 3_600))
        self.assertTrue(episodes[0].contains_target)
        self.assertEqual(episodes[1].start_timestamp, 10_800)


class SliceTests(unittest.TestCase):
    def test_sessions_are_half_open(self) -> None:
        self.assertEqual(_session(0), "ASIA")
        self.assertEqual(_session(8 * 3_600), "EUROPE")
        self.assertEqual(_session(16 * 3_600), "AMERICAS")

    def test_volatility_edges_are_assigned_once(self) -> None:
        cuts = (1.0, 2.0)
        self.assertEqual(_volatility_slice(1.0, cuts), "LOW")
        self.assertEqual(_volatility_slice(1.5, cuts), "MID")
        self.assertEqual(_volatility_slice(2.0, cuts), "MID")
        self.assertEqual(_volatility_slice(3.0, cuts), "HIGH")


class SyntheticEndToEndTests(unittest.TestCase):
    def test_all_periods_families_and_cells_run_without_effect_data(self) -> None:
        rows: list[M0RiskRow] = []
        clusters: list[ClusterRecord] = []
        for period_offset, period_key in enumerate(
            ("development", "validation", "test_2025", "test_2026")
        ):
            start = PERIOD_BY_KEY[period_key].start_timestamp + 10 * 86_400
            for index in range(120):
                timestamp = start + index * 3_600
                angle = 2.0 * np.pi * index / 24.0
                features = (
                    0.001 * ((index % 11) - 5),
                    0.01 + 0.0001 * (index % 17),
                    0.02 + 0.0002 * (index % 19),
                    float(np.sin(angle)),
                    float(np.cos(angle)),
                    float(np.sin(2.0 * np.pi * index / 7.0)),
                    float(np.cos(2.0 * np.pi * index / 7.0)),
                )
                cause = (Cause.UP, Cause.DOWN, Cause.NONE)[
                    (index + period_offset) % 3
                ]
                row = M0RiskRow(
                    timestamp=timestamp,
                    period=period_key,
                    base_status=BaseStatus.ELIGIBLE,
                    sigma=features[2],
                    impulse=0.0,
                    features=features,
                    twin_barrier=0.02,
                )
                for horizon in HORIZONS:
                    row.scoreable[horizon] = True
                    row.exclusion_reasons[horizon] = ()
                    for label_family in LABEL_FAMILIES:
                        passage = timestamp + 60 if cause in {Cause.UP, Cause.DOWN} else None
                        row.outcomes[(label_family, horizon)] = Outcome(cause, passage)
                        if cause in {Cause.UP, Cause.DOWN}:
                            cluster_id = (
                                f"{label_family}:{horizon}:{period_key}:{index}"
                            )
                            row.cluster_ids[(label_family, horizon)] = cluster_id
                            row.cluster_morphology[(label_family, horizon)] = "ONE_WAY"
                            clusters.append(
                                ClusterRecord(
                                    cluster_id=cluster_id,
                                    label_family=label_family,
                                    horizon_seconds=horizon,
                                    start_timestamp=timestamp,
                                    end_timestamp=timestamp + 60,
                                    up_count=int(cause is Cause.UP),
                                    down_count=int(cause is Cause.DOWN),
                                    up_passage_timestamps=(timestamp + 60,)
                                    if cause is Cause.UP
                                    else (),
                                    down_passage_timestamps=(timestamp + 60,)
                                    if cause is Cause.DOWN
                                    else (),
                                )
                            )
                rows.append(row)
        population = PopulationResult(
            rows=tuple(rows),
            clusters=tuple(clusters),
            kappa=1.0,
            inventory={"stage": "full"},
        )
        state = fit_m0(population)
        report = evaluate_m0(population, state, bootstrap_draws=7, bootstrap_seed=9)
        self.assertIn(report["disposition"], {"PASS", "FAIL", "NULL"})
        self.assertEqual(
            set(report["periods"]),
            {"validation", "test_2025", "test_2026"},
        )
        self.assertEqual(
            set(report["periods"]["validation"]),
            {"fixed", "twin"},
        )


if __name__ == "__main__":
    unittest.main()
