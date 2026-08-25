from __future__ import annotations

import math
import unittest
from datetime import UTC, datetime

import numpy as np

from oracle_research.exp005_flow import (
    DETREND_POINTS,
    M0_COLUMNS,
    RESIDUAL_POINTS,
    FlowMinute,
    HourlyPeriod,
    availability_report,
    build_flow_compression,
    build_m0_features,
    checkpoint_a_disposition,
    ordered_timestamp_sha256,
)


def utc_timestamp(text: str) -> int:
    return int(datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp())


def flow_minutes_for_q(timestamp: int, q_values: list[float]) -> list[FlowMinute]:
    first_block_end = timestamp - 595 * 60
    rows: list[FlowMinute] = []
    for block_index, q_value in enumerate(q_values):
        block_end = first_block_end + block_index * 300
        ratio = math.exp(q_value)
        quote_per_minute = 20.0
        buy_per_minute = quote_per_minute * ratio / (1.0 + ratio)
        for offset in (-240, -180, -120, -60, 0):
            rows.append(
                FlowMinute(
                    interval_end=block_end + offset,
                    quote_volume=quote_per_minute,
                    taker_buy_quote_volume=buy_per_minute,
                )
            )
    return rows


def exact_q_series() -> list[float]:
    return [
        0.17 * math.sin(index / 4.0) + 0.03 * math.cos(index / 11.0) + index * 0.0007
        for index in range(DETREND_POINTS + RESIDUAL_POINTS - 1)
    ]


class FlowCompressionTests(unittest.TestCase):
    def test_exact_96_point_detrend_and_24_residual_population_variance(self) -> None:
        timestamp = utc_timestamp("2024-02-12T12:00:00Z")
        q_values = exact_q_series()
        result = build_flow_compression(flow_minutes_for_q(timestamp, q_values), [timestamp])

        residuals = []
        for index in range(DETREND_POINTS - 1, len(q_values)):
            residuals.append(
                q_values[index]
                - math.fsum(q_values[index - DETREND_POINTS + 1 : index + 1])
                / DETREND_POINTS
            )
        self.assertEqual(len(residuals), RESIDUAL_POINTS)
        residual_mean = math.fsum(residuals) / RESIDUAL_POINTS
        expected_variance = (
            math.fsum((value - residual_mean) ** 2 for value in residuals)
            / RESIDUAL_POINTS
        )
        self.assertAlmostEqual(result.values[timestamp], -math.log(expected_variance), places=13)
        self.assertEqual(result.aligned_five_minute_census["candidate_blocks"], 119)
        self.assertEqual(result.aligned_five_minute_census["q_valid_blocks"], 119)
        self.assertEqual(result.hourly_feature_census["newest_block_lag_seconds"], 300)
        self.assertEqual(result.hourly_feature_census["variance_ddof"], 0)

    def test_post_t_rows_cannot_influence_feature_and_newest_block_is_t_minus_5m(self) -> None:
        timestamp = utc_timestamp("2024-02-12T12:00:00Z")
        base_rows = flow_minutes_for_q(timestamp, exact_q_series())
        expected = build_flow_compression(base_rows, [timestamp]).values[timestamp]
        after_t = [
            FlowMinute(timestamp + offset, 1e100, 1e-100)
            for offset in (60, 120, 180, 240, 300, 600)
        ]
        actual = build_flow_compression(base_rows + after_t, [timestamp]).values[timestamp]
        self.assertEqual(actual, expected)

        newest_required = timestamp - 300
        without_newest = [row for row in base_rows if row.interval_end != newest_required]
        missing = build_flow_compression(without_newest, [timestamp])
        self.assertNotIn(timestamp, missing.values)

    def test_no_partial_window_forward_fill_or_off_grid_rounding(self) -> None:
        timestamp = utc_timestamp("2024-02-12T12:00:00Z")
        rows = flow_minutes_for_q(timestamp, exact_q_series())
        removed_timestamp = timestamp - 599 * 60
        rows = [row for row in rows if row.interval_end != removed_timestamp]
        rows.append(FlowMinute(removed_timestamp + 1, 20.0, 9.0))
        result = build_flow_compression(rows, [timestamp])
        self.assertNotIn(timestamp, result.values)
        self.assertEqual(
            result.aligned_five_minute_census["reason_counts"]["MISSING_MINUTE"], 1
        )
        self.assertEqual(
            result.hourly_feature_census["reasons"]["INCOMPLETE_24_RESIDUAL_WINDOW"], 1
        )

    def test_buy_and_sell_must_be_strictly_positive_without_epsilon(self) -> None:
        timestamp = utc_timestamp("2024-02-12T12:00:00Z")
        rows = flow_minutes_for_q(timestamp, exact_q_series())
        first_block = timestamp - 595 * 60
        buy_zero = [
            FlowMinute(row.interval_end, row.quote_volume, 0.0)
            if first_block - 240 <= row.interval_end <= first_block
            else row
            for row in rows
        ]
        result = build_flow_compression(buy_zero, [timestamp])
        self.assertNotIn(timestamp, result.values)
        self.assertEqual(result.aligned_five_minute_census["reason_counts"]["NONPOSITIVE_BUY"], 1)

        sell_zero = [
            FlowMinute(row.interval_end, 20.0, 20.0)
            if first_block - 240 <= row.interval_end <= first_block
            else row
            for row in rows
        ]
        result = build_flow_compression(sell_zero, [timestamp])
        self.assertNotIn(timestamp, result.values)
        self.assertEqual(
            result.aligned_five_minute_census["reason_counts"]["NONPOSITIVE_SELL"], 1
        )

    def test_conflict_and_noncausal_close_are_missing(self) -> None:
        timestamp = utc_timestamp("2024-02-12T12:00:00Z")
        rows = flow_minutes_for_q(timestamp, exact_q_series())
        conflict_time = timestamp - 599 * 60
        rows = [
            FlowMinute(
                row.interval_end,
                row.quote_volume,
                row.taker_buy_quote_volume,
                conflict=True,
            )
            if row.interval_end == conflict_time
            else row
            for row in rows
        ]
        conflict = build_flow_compression(rows, [timestamp])
        self.assertNotIn(timestamp, conflict.values)
        self.assertEqual(
            conflict.aligned_five_minute_census["reason_counts"]["CONFLICT_MINUTE"], 1
        )

        rows = flow_minutes_for_q(timestamp, exact_q_series())
        rows = [
            FlowMinute(
                row.interval_end,
                row.quote_volume,
                row.taker_buy_quote_volume,
                timing_valid=False,
            )
            if row.interval_end == conflict_time
            else row
            for row in rows
        ]
        noncausal = build_flow_compression(rows, [timestamp])
        self.assertNotIn(timestamp, noncausal.values)
        self.assertEqual(
            noncausal.aligned_five_minute_census["reason_counts"]["NONCAUSAL_CLOSE"], 1
        )


class M0SourceOnlyTests(unittest.TestCase):
    def test_exact_seven_columns_and_no_post_t_influence(self) -> None:
        timestamp = utc_timestamp("2024-02-12T12:00:00Z")
        times = np.arange(timestamp - 86_400, timestamp + 60, 60, dtype=np.int64)
        phase = np.arange(times.size, dtype=np.float64)
        close = 100.0 * np.exp(0.00002 * phase + 0.0003 * np.sin(phase / 17.0))
        high = close * (1.001 + 0.0001 * np.cos(phase / 13.0))
        low = close * (0.999 - 0.0001 * np.sin(phase / 19.0))
        base = build_m0_features(
            end_timestamps=times,
            close=close,
            high=high,
            low=low,
            candidate_hours=[timestamp],
        )
        self.assertEqual(len(base.values[timestamp]), 7)
        self.assertEqual(len(M0_COLUMNS), 7)

        future_times = np.arange(timestamp + 60, timestamp + 3_660, 60, dtype=np.int64)
        augmented = build_m0_features(
            end_timestamps=np.concatenate((times, future_times)),
            close=np.concatenate((close, np.full(future_times.size, 1e9))),
            high=np.concatenate((high, np.full(future_times.size, 2e9))),
            low=np.concatenate((low, np.full(future_times.size, 5e8))),
            candidate_hours=[timestamp],
        )
        self.assertEqual(augmented.values[timestamp], base.values[timestamp])

    def test_missing_range_bar_is_not_filled(self) -> None:
        timestamp = utc_timestamp("2024-02-12T12:00:00Z")
        times = np.arange(timestamp - 86_400, timestamp + 60, 60, dtype=np.int64)
        keep = times != timestamp - 120
        times = times[keep]
        phase = np.arange(times.size, dtype=np.float64)
        close = 100.0 * np.exp(0.00001 * phase + 0.0002 * np.sin(phase / 11.0))
        result = build_m0_features(
            end_timestamps=times,
            close=close,
            high=close * 1.001,
            low=close * 0.999,
            candidate_hours=[timestamp],
        )
        self.assertNotIn(timestamp, result.values)
        self.assertEqual(result.reason_counts["MISSING_RANGE_BAR"], 1)


class SupportAndGateTests(unittest.TestCase):
    def test_exact_ordered_support_identity_and_paired_rungs(self) -> None:
        period = HourlyPeriod(
            "ONE_DAY",
            datetime(2024, 2, 1, tzinfo=UTC),
            datetime(2024, 2, 1, 23, tzinfo=UTC),
        )
        hours = tuple(period.hours())
        flow = {timestamp: 1.0 for timestamp in hours}
        m0 = {timestamp: (1.0,) * 7 for timestamp in hours}
        report = availability_report(periods=[period], flow_values=flow, m0_values=m0)
        row = report["periods"]["ONE_DAY"]
        paired = row["paired_rung_support"]
        self.assertTrue(paired["identical"])
        self.assertEqual(
            paired["m0_common_ordered_support_sha256"],
            paired["m0_flow_ordered_support_sha256"],
        )
        self.assertEqual(
            paired["m0_common_ordered_support_sha256"], ordered_timestamp_sha256(hours)
        )
        with self.assertRaises(ValueError):
            ordered_timestamp_sha256(reversed(hours))

    def test_zero_full_month_and_floors_apply_mechanically(self) -> None:
        february = HourlyPeriod(
            "FEBRUARY",
            datetime(2024, 2, 1, tzinfo=UTC),
            datetime(2024, 2, 29, 23, tzinfo=UTC),
        )
        hours = tuple(february.hours())
        empty = availability_report(periods=[february], flow_values={}, m0_values={})
        self.assertFalse(empty["coverage_clearance"])
        self.assertEqual(empty["zero_joint_full_months"], ["2024-02"])
        self.assertEqual(
            checkpoint_a_disposition(source_integrity_clear=True, coverage_clear=False),
            "NULL_COVERAGE",
        )
        self.assertEqual(
            checkpoint_a_disposition(source_integrity_clear=False, coverage_clear=True),
            "BLOCKED_SOURCE",
        )

        ninety_percent = math.ceil(len(hours) * 0.90)
        eighty_five_percent = math.ceil(len(hours) * 0.85)
        flow = {timestamp: 1.0 for timestamp in hours[:ninety_percent]}
        m0 = {timestamp: (1.0,) * 7 for timestamp in hours[:eighty_five_percent]}
        passed = availability_report(periods=[february], flow_values=flow, m0_values=m0)
        self.assertTrue(passed["coverage_clearance"])
        self.assertEqual(
            checkpoint_a_disposition(source_integrity_clear=True, coverage_clear=True),
            "CLEARED_CHECKPOINT_A",
        )


if __name__ == "__main__":
    unittest.main()
