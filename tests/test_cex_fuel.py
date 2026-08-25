from __future__ import annotations

import math
import unittest
import zipfile
from pathlib import Path
from tempfile import TemporaryDirectory

from oracle_research.cex_fuel import (
    BAND_0_1,
    BAND_1_2,
    BinanceMetricsRow,
    ClusterFuelRow,
    FuelBand,
    adverse_entry_distance,
    asof_snapshot,
    build_cluster_fuel_rows,
    far_edge_reached,
    fuel_usd_for_band,
    hl_target_for_cluster_row,
    join_metrics_to_kline_start_grid,
    load_metrics_dir,
    load_metrics_zip,
    run_cex_oi_cohort_v0,
    run_cex_oi_cohort_v0_asof,
)
from oracle_research.hyperliquid_fills import HlFill
from oracle_research.labels import Bar, Direction


def metric(ts: int, q: float, lsr: float, value: float | None = None) -> BinanceMetricsRow:
    return BinanceMetricsRow(
        interval_end=ts,
        sum_open_interest=q,
        sum_open_interest_value=q * 100 if value is None else value,
        sum_toptrader_long_short_ratio=lsr,
    )


def fill(
    *,
    tid: int,
    user: str = "liq",
    liquidated_user: str = "liq",
    px: str = "99",
    sz: str = "2",
    time_ms: int = 1_000,
    direction: str = "Liquidated Cross Long",
    method: str = "market",
) -> HlFill:
    return HlFill(
        user=user,
        coin="BTC",
        px=px,
        sz=sz,
        side="A",
        time_ms=time_ms,
        start_position="1",
        dir=direction,
        hash=f"0x{tid:x}",
        oid=tid,
        crossed=True,
        tid=tid,
        fee="0",
        fee_token="USDC",
        liquidation={
            "liquidatedUser": liquidated_user,
            "markPx": px,
            "method": method,
        },
    )


class CexFuelStateMachineTests(unittest.TestCase):
    def test_metrics_loader_keeps_position_lsr_and_nulls_non_positive_lsr(self) -> None:
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "BTCUSDT-metrics-2021-12-01.zip"
            csv_text = "\n".join(
                [
                    (
                        "create_time,sum_open_interest,sum_open_interest_value,"
                        "sum_toptrader_long_short_ratio,count_toptrader_long_short_ratio"
                    ),
                    "1609459500000,100,10000,1.5,9.9",
                    "1609459800000,110,11000,0,8.8",
                ]
            )
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr("BTCUSDT-metrics-2021-12-01.csv", csv_text)

            loaded = load_metrics_zip(path)

        self.assertEqual(loaded.interval_end.tolist(), [1_609_459_500, 1_609_459_800])
        self.assertEqual(loaded.sum_open_interest.tolist(), [100.0, 110.0])
        self.assertEqual(loaded.sum_toptrader_long_short_ratio[0], 1.5)
        self.assertTrue(math.isnan(loaded.sum_toptrader_long_short_ratio[1]))

    def test_metrics_dir_keeps_later_file_row_for_overlapping_interval_end(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            first = root / "BTCUSDT-metrics-2024-04-07.zip"
            second = root / "BTCUSDT-metrics-2024-04-08.zip"
            header = (
                "create_time,sum_open_interest,sum_open_interest_value,"
                "sum_toptrader_long_short_ratio"
            )
            with zipfile.ZipFile(first, "w") as archive:
                archive.writestr(
                    "BTCUSDT-metrics-2024-04-07.csv",
                    "\n".join([header, "1712534100,100,10000,1", "1712534400,101,10100,1"]),
                )
            with zipfile.ZipFile(second, "w") as archive:
                archive.writestr(
                    "BTCUSDT-metrics-2024-04-08.csv",
                    "\n".join([header, "1712534400,202,20200,2", "1712534700,203,20300,2"]),
                )

            loaded = load_metrics_dir(root)

        self.assertEqual(
            loaded.interval_end.tolist(),
            [1_712_534_100, 1_712_534_400, 1_712_534_700],
        )
        self.assertEqual(loaded.sum_open_interest.tolist(), [100.0, 202.0, 203.0])
        self.assertEqual(loaded.sum_toptrader_long_short_ratio.tolist(), [1.0, 2.0, 2.0])

    def test_conservation_after_add_and_pro_rata_reduction(self) -> None:
        rows = [metric(0, 100, 1), metric(300, 120, 1), metric(600, 100, 1)]
        snapshots = run_cex_oi_cohort_v0(
            rows,
            {0: 100, 300: 105, 600: 100},
            burn_in_end=-1,
        )

        self.assertTrue(all(snapshot.valid for snapshot in snapshots))
        final = snapshots[-1]
        self.assertAlmostEqual(final.long_side.total_quantity, final.inferred_long)
        self.assertAlmostEqual(final.short_side.total_quantity, final.inferred_short)
        self.assertLessEqual(final.conservation_relative_residual or 0.0, 1e-6)

    def test_unallocated_opening_stock_never_enters_band(self) -> None:
        snapshots = run_cex_oi_cohort_v0([metric(0, 100, 1)], {0: 100}, burn_in_end=-1)

        fuel = fuel_usd_for_band(
            snapshots[0],
            direction=Direction.DOWN,
            band=BAND_0_1,
            price=99.5,
        )

        self.assertEqual(fuel, 0.0)
        self.assertEqual(snapshots[0].long_side.priced, ())

    def test_lsr_only_delta_at_flat_open_interest_creates_priced_cohort(self) -> None:
        rows = [metric(0, 100, 1), metric(300, 100, 3)]
        snapshots = run_cex_oi_cohort_v0(rows, {0: 100, 300: 101}, burn_in_end=-1)

        second = snapshots[-1]
        self.assertAlmostEqual(second.inferred_long or 0.0, 75.0)
        self.assertAlmostEqual(second.long_side.priced_quantity, 25.0)
        self.assertAlmostEqual(second.short_side.total_quantity, 25.0)

    def test_clip_at_zero_does_not_leave_negative_side_quantity(self) -> None:
        rows = [metric(0, 100, 1), metric(300, 0, 1)]
        snapshots = run_cex_oi_cohort_v0(rows, {0: 100, 300: 100}, burn_in_end=-1)

        final = snapshots[-1]
        self.assertEqual(final.long_side.total_quantity, 0.0)
        self.assertEqual(final.short_side.total_quantity, 0.0)
        self.assertGreaterEqual(final.long_side.unallocated, 0.0)
        self.assertGreaterEqual(final.short_side.unallocated, 0.0)


class CexFuelJoinAndBandTests(unittest.TestCase):
    def test_asof_join_uses_interval_end_without_lookahead(self) -> None:
        snapshots = run_cex_oi_cohort_v0(
            [metric(300, 100, 1), metric(600, 120, 1)],
            {300: 100, 600: 100},
            burn_in_end=-1,
        )

        self.assertIsNone(asof_snapshot(snapshots, 299))
        self.assertEqual(asof_snapshot(snapshots, 300).timestamp, 300)  # type: ignore[union-attr]
        self.assertEqual(asof_snapshot(snapshots, 599).timestamp, 300)  # type: ignore[union-attr]
        self.assertEqual(asof_snapshot(snapshots, 600).timestamp, 600)  # type: ignore[union-attr]

        joined = join_metrics_to_kline_start_grid([metric(300, 100, 1)], [0, 60, 120])
        self.assertEqual(joined[0].interval_end, 300)

    def test_streaming_asof_walk_matches_full_walk_at_requested_timestamps(self) -> None:
        rows = [
            metric(300, 100, 1),
            metric(600, 120, 1),
            metric(900, 110, 2),
            metric(1200, 130, 2),
        ]
        prices = {300: 100, 600: 105, 900: 102, 1200: 106}
        requested = [299, 300, 599, 600, 750, 1199, 1200, 1500]
        full_walk = run_cex_oi_cohort_v0(rows, prices, burn_in_end=-1)
        streamed = run_cex_oi_cohort_v0_asof(rows, prices, requested, burn_in_end=-1)

        for timestamp in requested:
            expected = asof_snapshot(full_walk, timestamp)
            if expected is None:
                self.assertNotIn(timestamp, streamed)
            else:
                self.assertEqual(streamed[timestamp], expected)

    def test_profitable_cohort_maps_to_zero_and_misses_open_lower_band(self) -> None:
        self.assertEqual(adverse_entry_distance(Direction.DOWN, entry_price=99, price=100), 0.0)
        self.assertEqual(adverse_entry_distance(Direction.UP, entry_price=101, price=100), 0.0)
        self.assertFalse(BAND_0_1.contains(0.0))

    def test_adverse_entry_bands_use_open_then_closed_lower_edges(self) -> None:
        self.assertTrue(BAND_0_1.contains(0.005))
        self.assertFalse(BAND_0_1.contains(0.01))
        self.assertTrue(BAND_1_2.contains(0.01))
        self.assertFalse(BAND_1_2.contains(0.02))


class CexFuelClusterTests(unittest.TestCase):
    def test_far_edge_eligibility_uses_strict_future_path(self) -> None:
        bars = [
            Bar(timestamp=0, high=100, low=100, close=100),
            Bar(timestamp=60, high=100, low=99.5, close=100),
            Bar(timestamp=120, high=100, low=99.0, close=99.5),
        ]

        self.assertTrue(
            far_edge_reached(
                bars,
                decision_timestamp=0,
                direction=Direction.DOWN,
                far_edge_fraction=0.01,
                horizon_seconds=120,
            )
        )
        self.assertFalse(
            far_edge_reached(
                bars,
                decision_timestamp=120,
                direction=Direction.DOWN,
                far_edge_fraction=0.01,
                horizon_seconds=120,
            )
        )

    def test_cluster_row_reduction_skips_mixed_and_keeps_earliest_eligible_t(self) -> None:
        bars = [
            Bar(timestamp=0, high=100, low=100, close=100),
            Bar(timestamp=60, high=110, low=110, close=110),
            Bar(timestamp=120, high=111, low=108.8, close=110),
            Bar(timestamp=180, high=111, low=108.7, close=110),
        ]
        snapshots = run_cex_oi_cohort_v0(
            [metric(0, 100, 1), metric(60, 120, 1)],
            {0: 100, 60: 110},
            burn_in_end=-1,
        )
        payload = {
            "horizons": [
                {
                    "horizon_seconds": 14_400,
                    "clusters": [
                        {
                            "start_timestamp": 0,
                            "end_timestamp": 120,
                            "direction": "down",
                        },
                        {
                            "start_timestamp": 180,
                            "end_timestamp": 180,
                            "direction": "mixed",
                        },
                    ],
                }
            ]
        }

        rows = build_cluster_fuel_rows(
            payload,
            bars,
            snapshots,
            bands=(FuelBand("(0,1%)", 0.0, 0.01, False),),
        )

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].cluster_index, 0)
        self.assertEqual(rows[0].direction, Direction.DOWN)
        self.assertEqual(rows[0].decision_timestamp, 60)


class HlTargetHookTests(unittest.TestCase):
    def test_hl_target_hook_splits_book_and_backstop_deduping_liquidated_leg(self) -> None:
        row = ClusterFuelRow(
            cluster_index=0,
            cluster_start_timestamp=0,
            cluster_end_timestamp=0,
            direction=Direction.DOWN,
            band="(0,1%)",
            decision_timestamp=0,
            week_start_timestamp=0,
            price=100.0,
            fuel_usd=0.0,
            oi_only_usd=0.0,
            trailing_price_path_4h=0.0,
            metrics_timestamp=0,
        )
        fills = [
            fill(tid=1, px="99.5", sz="2", method="market"),
            fill(tid=1, user="other", liquidated_user="liq", px="99.5", sz="2", method="market"),
            fill(tid=2, px="99.2", sz="3", method="backstop"),
            fill(tid=3, px="98.5", sz="5", method="market"),
            fill(tid=4, px="99.5", sz="1", direction="Auto-Deleveraging", method="market"),
            fill(tid=5, px="99.5", sz="1", direction="Liquidated Cross Short", method="market"),
        ]

        summary = hl_target_for_cluster_row(row, fills=fills)

        self.assertAlmostEqual(summary.book_hitting_usd, 199.0)
        self.assertAlmostEqual(summary.backstop_usd, 297.6)
        self.assertEqual(summary.book_hitting_count, 1)
        self.assertEqual(summary.backstop_count, 1)


if __name__ == "__main__":
    unittest.main()
