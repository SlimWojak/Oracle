from __future__ import annotations

import math
import unittest
from datetime import UTC, datetime

import numpy as np

from oracle_research.construct_gate import (
    CONSTRUCT_DEV,
    CONSTRUCT_VAL,
    PRIMARY_CELL_BANDS,
    PRIMARY_CELL_DIRECTIONS,
    STABILITY_NOV_DEC,
    STABILITY_SEP_OCT,
    TargetedFuelRow,
    average_ranks,
    lock_floor,
    score_construct_gate,
    score_shape,
    score_window,
    spearman,
    static_usd_by_row,
    weekly_bootstrap,
)
from oracle_research.labels import Direction


def ts(year: int, month: int, day: int) -> int:
    return int(datetime(year, month, day, tzinfo=UTC).timestamp())


def row(
    *,
    cluster_index: int,
    cluster_start_timestamp: int,
    direction: Direction,
    band: str,
    fuel_usd: float,
    oi_only_usd: float,
    target: float,
    trailing_path: float | None = None,
    week_start_timestamp: int | None = None,
) -> TargetedFuelRow:
    return TargetedFuelRow(
        cluster_index=cluster_index,
        cluster_start_timestamp=cluster_start_timestamp,
        cluster_end_timestamp=cluster_start_timestamp,
        direction=direction,
        band=band,
        decision_timestamp=cluster_start_timestamp,
        week_start_timestamp=(
            cluster_start_timestamp if week_start_timestamp is None else week_start_timestamp
        ),
        price=100.0,
        fuel_usd=fuel_usd,
        oi_only_usd=oi_only_usd,
        trailing_price_path_4h=trailing_path if trailing_path is not None else oi_only_usd,
        metrics_timestamp=cluster_start_timestamp,
        book_hitting_usd=target,
        backstop_usd=target * 2.0,
        book_hitting_count=1,
        backstop_count=1,
    )


def add_cell_rows(
    rows: list[TargetedFuelRow],
    *,
    start_timestamp: int,
    count: int,
    week_start_timestamp: int,
    first_cluster_index: int,
    target_descending: bool = False,
) -> int:
    cluster_index = first_cluster_index
    for direction_index, direction in enumerate(PRIMARY_CELL_DIRECTIONS):
        for band_index, band in enumerate(PRIMARY_CELL_BANDS):
            for offset in range(count):
                value = float(offset + 1)
                target = float(count - offset if target_descending else offset + 1)
                rows.append(
                    row(
                        cluster_index=cluster_index,
                        cluster_start_timestamp=start_timestamp + cluster_index * 60,
                        direction=direction,
                        band=band,
                        fuel_usd=value + band_index * 0.01 + direction_index * 0.001,
                        oi_only_usd=float(count - offset),
                        target=target,
                        trailing_path=float(count - offset),
                        week_start_timestamp=week_start_timestamp,
                    )
                )
                cluster_index += 1
    return cluster_index


class SpearmanTests(unittest.TestCase):
    def test_defined_with_average_tie_ranks(self) -> None:
        self.assertEqual(average_ranks([1.0, 2.0, 2.0, 4.0]).tolist(), [0.0, 1.5, 1.5, 3.0])
        rho = spearman([1.0, 2.0, 2.0, 4.0, 5.0], [5.0, 4.0, 4.0, 2.0, 1.0])
        self.assertAlmostEqual(rho or 0.0, -1.0)

    def test_undefined_when_short_constant_or_nonfinite(self) -> None:
        self.assertIsNone(spearman([1, 2, 3, 4], [1, 2, 3, 4]))
        self.assertIsNone(spearman([1, 1, 1, 1, 1], [1, 2, 3, 4, 5]))
        self.assertIsNone(spearman([1, 2, 3, 4, math.nan], [1, 2, 3, 4, 5]))


class StaticControlTests(unittest.TestCase):
    def test_lumped_static_is_not_oi_times_constant_rank(self) -> None:
        rows: list[TargetedFuelRow] = []
        for index in range(5):
            start = ts(2025, 9, 1) + index * 60
            rows.append(
                row(
                    cluster_index=index,
                    cluster_start_timestamp=start,
                    direction=Direction.UP,
                    band="(0,1%)",
                    fuel_usd=float(index + 1),
                    oi_only_usd=float(index + 1),
                    target=float(index + 1),
                )
            )
            rows.append(
                row(
                    cluster_index=index,
                    cluster_start_timestamp=start,
                    direction=Direction.UP,
                    band="[1,2%)",
                    fuel_usd=100.0 if index % 2 == 0 else 0.0,
                    oi_only_usd=float(index + 1),
                    target=float(index + 1),
                )
            )

        static = static_usd_by_row(rows)
        band_0_static = [static[index * 2] for index in range(5)]

        self.assertNotEqual(
            average_ranks(band_0_static).tolist(),
            average_ranks([1.0, 2.0, 3.0, 4.0, 5.0]).tolist(),
        )


class BootstrapTests(unittest.TestCase):
    def test_family_wide_week_draw_carries_both_bands(self) -> None:
        rows: list[TargetedFuelRow] = []
        next_index = add_cell_rows(
            rows,
            start_timestamp=CONSTRUCT_DEV.start_timestamp,
            count=5,
            week_start_timestamp=ts(2025, 5, 26),
            first_cluster_index=0,
        )
        add_cell_rows(
            rows,
            start_timestamp=CONSTRUCT_DEV.start_timestamp + 7 * 86_400,
            count=5,
            week_start_timestamp=ts(2025, 6, 2),
            first_cluster_index=next_index,
        )
        bootstrap = weekly_bootstrap(rows, CONSTRUCT_DEV, draws=1, seed=4)
        weeks = sorted({item.week_start_timestamp for item in rows})
        sampled = np.random.default_rng(4).choice(np.asarray(weeks, dtype=np.int64), size=2, replace=True)
        sampled_rows = [item for week in sampled.tolist() for item in rows if item.week_start_timestamp == week]

        for week in sampled.tolist():
            self.assertEqual(
                {item.band for item in sampled_rows if item.week_start_timestamp == week},
                set(PRIMARY_CELL_BANDS),
            )
        self.assertEqual(bootstrap.values[0], score_window(sampled_rows, CONSTRUCT_DEV).family.f_vs_oi)

    def test_seeded_bootstrap_reproducibility_and_floor_recipe(self) -> None:
        rows: list[TargetedFuelRow] = []
        add_cell_rows(
            rows,
            start_timestamp=CONSTRUCT_DEV.start_timestamp,
            count=10,
            week_start_timestamp=ts(2025, 5, 26),
            first_cluster_index=0,
        )
        first = weekly_bootstrap(rows, CONSTRUCT_DEV, draws=5, seed=99)
        second = weekly_bootstrap(rows, CONSTRUCT_DEV, draws=5, seed=99)
        dev_score = score_window(rows, CONSTRUCT_DEV)
        floor = lock_floor(dev_score, first)

        self.assertEqual(first.values, second.values)
        self.assertTrue(floor.locked)
        self.assertEqual(floor.floor, round(max(0.10, 2.0 * (first.se or 0.0)), 6))


class ShapeTests(unittest.TestCase):
    def test_tercile_edges_at_n_15_are_five_each(self) -> None:
        rows: list[TargetedFuelRow] = []
        add_cell_rows(
            rows,
            start_timestamp=CONSTRUCT_VAL.start_timestamp,
            count=15,
            week_start_timestamp=ts(2025, 9, 1),
            first_cluster_index=0,
        )

        shape = score_shape(rows)

        self.assertTrue(shape.integrity_ok)
        for cell in shape.cells:
            self.assertEqual(cell.tercile_counts, (5, 5, 5))

    def test_hard_flip_fails_shape_gate(self) -> None:
        rows: list[TargetedFuelRow] = []
        cluster_index = 0
        for direction in PRIMARY_CELL_DIRECTIONS:
            for band in PRIMARY_CELL_BANDS:
                for offset in range(15):
                    flipped_cell = direction is Direction.UP and band == "(0,1%)"
                    target = 100.0 if flipped_cell and offset < 5 else float(offset + 1)
                    if flipped_cell and offset >= 10:
                        target = 50.0
                    rows.append(
                        row(
                            cluster_index=cluster_index,
                            cluster_start_timestamp=CONSTRUCT_VAL.start_timestamp + cluster_index * 60,
                            direction=direction,
                            band=band,
                            fuel_usd=float(offset + 1),
                            oi_only_usd=float(15 - offset),
                            target=target,
                            week_start_timestamp=ts(2025, 9, 1),
                        )
                    )
                    cluster_index += 1

        shape = score_shape(rows)

        self.assertEqual(shape.hard_flips, 1)
        self.assertFalse(shape.passed)


class HarnessStatusTests(unittest.TestCase):
    def test_stability_integrity_failure_is_fail_not_null_when_main_integrity_holds(self) -> None:
        rows: list[TargetedFuelRow] = []
        next_index = add_cell_rows(
            rows,
            start_timestamp=CONSTRUCT_DEV.start_timestamp,
            count=10,
            week_start_timestamp=ts(2025, 5, 26),
            first_cluster_index=0,
        )
        next_index = add_cell_rows(
            rows,
            start_timestamp=STABILITY_SEP_OCT.start_timestamp,
            count=5,
            week_start_timestamp=ts(2025, 9, 1),
            first_cluster_index=next_index,
        )
        add_cell_rows(
            rows,
            start_timestamp=STABILITY_NOV_DEC.start_timestamp,
            count=10,
            week_start_timestamp=ts(2025, 11, 3),
            first_cluster_index=next_index,
        )

        result = score_construct_gate(rows, bootstrap_draws=5)

        self.assertEqual(result.harness_status, "FAIL")
        self.assertFalse(result.stability_blocks[0].passed)
        self.assertNotIn("stability", " ".join(result.null_reasons))


if __name__ == "__main__":
    unittest.main()
