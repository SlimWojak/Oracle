from __future__ import annotations

import copy
import math
import unittest
from dataclasses import replace

from oracle_research.exp004_m0_population import (
    HORIZONS,
    LABEL_FAMILIES,
    BaseStatus,
    Cause,
    M0RiskRow,
    Outcome,
    PopulationResult,
)
from oracle_research.exp005_flow import M0_FLOW_COLUMNS
from oracle_research.exp005_flow_population import (
    BlockedSupportError,
    assert_ordered_support_identity,
    build_flow_population,
)


def synthetic_population() -> PopulationResult:
    rows: list[M0RiskRow] = []
    for period_index, period in enumerate(
        ("development", "validation", "test_2025", "test_2026")
    ):
        for index in range(4):
            timestamp = (period_index * 10 + index + 1) * 3_600
            row = M0RiskRow(
                timestamp=timestamp,
                period=period,
                base_status=BaseStatus.ELIGIBLE,
                sigma=0.01 + index * 0.001,
                impulse=0.0,
                features=(
                    index * 0.01,
                    0.02 + index * 0.001,
                    0.03 + index * 0.001,
                    0.1 + index,
                    0.2 + index,
                    0.3 + index,
                    0.4 + index,
                ),
                twin_barrier=0.02,
            )
            for horizon in HORIZONS:
                row.scoreable[horizon] = True
                row.exclusion_reasons[horizon] = ()
                for family in LABEL_FAMILIES:
                    row.outcomes[(family, horizon)] = Outcome(Cause.NONE)
            rows.append(row)
    return PopulationResult(
        rows=tuple(rows),
        clusters=(),
        kappa=0.771724,
        inventory={"stage": "full", "sentinel": {"unchanged": True}},
    )


class FlowPopulationTests(unittest.TestCase):
    def test_one_finite_mask_pairs_rungs_without_mutating_base_rows(self) -> None:
        population = synthetic_population()
        snapshot = copy.deepcopy(population)
        flow = {row.timestamp: float(index) for index, row in enumerate(population.rows)}
        flow[population.rows[2].timestamp] = math.nan

        paired = build_flow_population(population, flow)

        self.assertEqual(population, snapshot)
        self.assertEqual(paired.kappa, population.kappa)
        self.assertEqual(len(paired.rows), len(population.rows) - 1)
        self.assertIs(paired.rows[0].base_row, population.rows[0])
        self.assertEqual(M0_FLOW_COLUMNS[-1], "flow_compression_T")
        self.assertEqual(
            paired.rows[0].m0_flow_features[:-1],
            paired.rows[0].m0_common_features,
        )
        self.assertEqual(len(paired.rows[0].m0_flow_features), 8)
        for support in paired.supports:
            self.assertEqual(
                support.m0_common_timestamps,
                support.m0_flow_timestamps,
            )
            self.assertEqual(
                support.m0_common_support_identifier,
                support.m0_flow_support_identifier,
            )

    def test_support_mismatch_is_blocked_exactly(self) -> None:
        with self.assertRaisesRegex(BlockedSupportError, "BLOCKED_SUPPORT"):
            assert_ordered_support_identity((1, 2), (1, 3), context="synthetic")

        paired = build_flow_population(
            synthetic_population(),
            {row.timestamp: 1.0 for row in synthetic_population().rows},
        )
        first = paired.supports[0]
        broken = replace(first, m0_flow_timestamps=first.m0_flow_timestamps[:-1])
        with self.assertRaisesRegex(BlockedSupportError, "BLOCKED_SUPPORT"):
            broken.validate()


if __name__ == "__main__":
    unittest.main()
