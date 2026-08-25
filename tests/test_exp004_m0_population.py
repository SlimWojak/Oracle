from __future__ import annotations

import math
import unittest
from datetime import datetime

import numpy as np

from oracle_research.exp004_m0_population import (
    BOUNDARY_PURGE_SECONDS,
    IMPULSE_LIMIT,
    BaseStatus,
    Cause,
    ClusterRecord,
    Period,
    attach_fixed_passage_inventory,
    build_population,
    causal_rv24h,
    cluster_crosses_period,
    cluster_hourly_anchors,
    first_cause,
    m0_features,
    period_horizon_eligible,
)


def ts(text: str) -> int:
    return int(datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp())


class ExactOutcomeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.anchor = ts("2024-06-03T12:00:00Z")
        self.timestamps = np.arange(
            self.anchor - 90_000,
            self.anchor + 14_400 + 60,
            60,
            dtype=np.int64,
        )
        self.close = np.full(self.timestamps.size, 100.0)
        self.high = np.full(self.timestamps.size, 100.5)
        self.low = np.full(self.timestamps.size, 99.5)

    def row(self, seconds_after: int) -> int:
        return int(np.searchsorted(self.timestamps, self.anchor + seconds_after))

    def test_opposite_first_is_a_competing_cause(self) -> None:
        self.low[self.row(60)] = 97.0
        self.high[self.row(120)] = 103.0
        outcome = first_cause(
            self.timestamps,
            self.close,
            self.high,
            self.low,
            timestamp=self.anchor,
            horizon_seconds=3_600,
            barrier_fraction=0.02,
        )
        self.assertEqual(outcome.cause, Cause.DOWN)
        self.assertEqual(outcome.passage_timestamp, self.anchor + 60)

    def test_same_first_bar_is_ambiguous(self) -> None:
        self.high[self.row(60)] = 103.0
        self.low[self.row(60)] = 97.0
        outcome = first_cause(
            self.timestamps,
            self.close,
            self.high,
            self.low,
            timestamp=self.anchor,
            horizon_seconds=3_600,
            barrier_fraction=0.02,
        )
        self.assertEqual(outcome.cause, Cause.AMBIGUOUS)

    def test_any_future_gap_censors_even_after_visible_hit(self) -> None:
        self.high[self.row(60)] = 103.0
        missing = self.row(600)
        arrays = [
            np.delete(values, missing)
            for values in (self.timestamps, self.close, self.high, self.low)
        ]
        outcome = first_cause(
            arrays[0],
            arrays[1],
            arrays[2],
            arrays[3],
            timestamp=self.anchor,
            horizon_seconds=3_600,
            barrier_fraction=0.02,
        )
        self.assertEqual(outcome.cause, Cause.CENSORED_GAP)


class FeatureTests(unittest.TestCase):
    def setUp(self) -> None:
        self.anchor = ts("2024-06-03T12:00:00Z")  # Monday noon UTC
        self.timestamps = np.arange(self.anchor - 90_000, self.anchor + 60, 60, dtype=np.int64)
        steps = np.arange(self.timestamps.size, dtype=np.float64)
        self.close = 100.0 * np.exp(steps * 0.00001)
        self.high = self.close * 1.001
        self.low = self.close * 0.999

    def test_rv_counts_only_exact_pairs_and_seven_columns_are_ordered(self) -> None:
        sigma, count = causal_rv24h(self.timestamps, self.close, self.anchor)
        self.assertEqual(count, 1_440)
        self.assertIsNotNone(sigma)
        features, reasons = m0_features(
            self.timestamps,
            self.close,
            self.high,
            self.low,
            self.anchor,
            sigma or 0.0,
        )
        self.assertEqual(reasons, ())
        assert features is not None
        self.assertEqual(len(features), 7)
        self.assertAlmostEqual(features[0], 240 * 0.00001)
        self.assertAlmostEqual(features[3], 0.0, places=12)
        self.assertAlmostEqual(features[4], -1.0, places=12)
        self.assertAlmostEqual(features[5], 0.0, places=12)
        self.assertAlmostEqual(features[6], 1.0, places=12)

    def test_range_requires_all_240_exact_bars(self) -> None:
        missing = int(np.searchsorted(self.timestamps, self.anchor - 120))
        arrays = [
            np.delete(values, missing)
            for values in (self.timestamps, self.close, self.high, self.low)
        ]
        sigma, _ = causal_rv24h(arrays[0], arrays[1], self.anchor)
        features, reasons = m0_features(*arrays, self.anchor, sigma or 0.0)
        self.assertIsNone(features)
        self.assertIn("MISSING_RANGE_BAR", reasons)

    def test_impulse_threshold_constant_is_exact_log(self) -> None:
        self.assertEqual(IMPULSE_LIMIT, math.log(1.005))


class SplitAndClusterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.period = Period(
            "x",
            ts("2024-01-01T00:00:00Z"),
            ts("2025-01-01T00:00:00Z"),
        )

    def test_boundary_equality_is_purged_and_period_end_is_exclusive(self) -> None:
        self.assertFalse(
            period_horizon_eligible(
                self.period.start_timestamp + BOUNDARY_PURGE_SECONDS,
                3_600,
                self.period,
            )
        )
        self.assertTrue(
            period_horizon_eligible(
                self.period.start_timestamp + BOUNDARY_PURGE_SECONDS + 3_600,
                14_400,
                self.period,
            )
        )
        self.assertFalse(
            period_horizon_eligible(
                self.period.end_timestamp - BOUNDARY_PURGE_SECONDS,
                3_600,
                self.period,
            )
        )

    def test_padded_cluster_straddle(self) -> None:
        cluster = ClusterRecord(
            "fixed:3600:0",
            "fixed",
            3_600,
            self.period.start_timestamp + 60,
            self.period.start_timestamp + 120,
            1,
            0,
        )
        self.assertTrue(cluster_crosses_period(cluster, self.period))

    def test_twin_chaining_retains_mixed_membership(self) -> None:
        start = self.period.start_timestamp + 86_400
        anchors = [
            (start, start + 60, Cause.UP),
            (start + 14_400, start + 14_460, Cause.DOWN),
            (start + 28_860, start + 28_920, Cause.UP),
        ]
        clusters, membership = cluster_hourly_anchors(
            anchors,
            label_family="twin",
            horizon_seconds=3_600,
        )
        self.assertEqual(len(clusters), 2)
        self.assertEqual(clusters[0].morphology, "MIXED")
        self.assertEqual(membership[(start, Cause.UP)].cluster_id, clusters[0].cluster_id)
        self.assertEqual(
            membership[(start + 14_400, Cause.DOWN)].cluster_id,
            clusters[0].cluster_id,
        )

    def test_fixed_passage_reconstruction_attaches_and_checks_counts(self) -> None:
        anchor = self.period.start_timestamp + 86_400
        timestamps = np.arange(anchor, anchor + 3_600 + 60, 60, dtype=np.int64)
        close = np.full(timestamps.size, 100.0)
        high = np.full(timestamps.size, 100.5)
        low = np.full(timestamps.size, 99.5)
        high[1] = 103.0
        payload = {
            3_600: [
                ClusterRecord(
                    "fixed:3600:0",
                    "fixed",
                    3_600,
                    anchor,
                    anchor + 60,
                    1,
                    0,
                )
            ],
            14_400: [],
        }
        attached = attach_fixed_passage_inventory(
            fixed_by_horizon=payload,
            timestamps=timestamps,
            close=close,
            high=high,
            low=low,
        )
        self.assertEqual(attached[3_600][0].up_passage_timestamps, (anchor + 60,))
        payload[3_600][0] = ClusterRecord(
            "fixed:3600:0",
            "fixed",
            3_600,
            anchor,
            anchor + 60,
            2,
            0,
        )
        with self.assertRaises(ValueError):
            attach_fixed_passage_inventory(
                fixed_by_horizon=payload,
                timestamps=timestamps,
                close=close,
                high=high,
                low=low,
            )


class SyntheticPopulationTests(unittest.TestCase):
    def test_development_population_locks_kappa_and_common_support(self) -> None:
        start = ts("2022-01-10T00:00:00Z")
        end = start + 10 * 86_400
        timestamps = np.arange(start - 86_400, end + 14_400 + 60, 60, dtype=np.int64)
        phase = np.arange(timestamps.size, dtype=np.float64)
        close = 100.0 * np.exp(0.0005 * np.sin(phase / 120.0))
        high = close * 1.0001
        low = close * 0.9999
        cluster_payload = {
            "parameters": {
                "min_members": 2,
                "construction": "componentwise_median",
                "label_semantics": "wall_clock_first_passage",
                "threshold": 0.02,
                "horizons_seconds": [3_600, 14_400],
                "decision_timestamp": "interval_end",
            },
            "horizons": [
                {"horizon_seconds": 3_600, "clusters": []},
                {"horizon_seconds": 14_400, "clusters": []},
            ],
        }
        population = build_population(
            end_timestamps=timestamps,
            close=close,
            high=high,
            low=low,
            fixed_cluster_payload=cluster_payload,
            periods=(Period("development", start, end),),
            stage="development",
        )
        eligible_sigmas = [
            row.sigma
            for row in population.rows
            if row.base_status is BaseStatus.ELIGIBLE and row.sigma is not None
        ]
        self.assertEqual(
            population.kappa,
            round(0.02 / float(np.median(eligible_sigmas)), 6),
        )
        self.assertTrue(any(row.scoreable[3_600] for row in population.rows))
        for row in population.rows:
            if row.scoreable.get(3_600, False):
                self.assertEqual(row.outcomes[("fixed", 3_600)].cause, Cause.NONE)
                self.assertEqual(row.outcomes[("twin", 3_600)].cause, Cause.NONE)
        self.assertLess(max(row.timestamp for row in population.rows), end)


if __name__ == "__main__":
    unittest.main()
