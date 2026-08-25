"""EXP-002 construct-gate scoring for the four primary P3 fuel cells."""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

import numpy as np

from oracle_research.cex_fuel import ClusterFuelRow, HlTargetSummary
from oracle_research.labels import Direction

PRIMARY_CELL_DIRECTIONS: tuple[Direction, ...] = (Direction.UP, Direction.DOWN)
PRIMARY_CELL_BANDS: tuple[str, ...] = ("(0,1%)", "[1,2%)")
STATIC_BAND_WEIGHTS: dict[str, float] = {"(0,1%)": 0.75, "[1,2%)": 0.25}
BOOTSTRAP_SEED = 20_250_825
BOOTSTRAP_DRAWS = 1_000
FLOOR_MINIMUM = 0.10


@dataclass(frozen=True, slots=True)
class GateWindow:
    """UTC half-open construct-gate window."""

    key: str
    label: str
    start_timestamp: int
    end_timestamp: int
    min_cell_count: int


def _utc_timestamp(year: int, month: int, day: int) -> int:
    return int(datetime(year, month, day, tzinfo=UTC).timestamp())


CONSTRUCT_DEV = GateWindow(
    key="construct_dev",
    label="construct-dev",
    start_timestamp=_utc_timestamp(2025, 5, 25),
    end_timestamp=_utc_timestamp(2025, 9, 1),
    min_cell_count=10,
)
CONSTRUCT_VAL = GateWindow(
    key="construct_val",
    label="construct-val",
    start_timestamp=_utc_timestamp(2025, 9, 1),
    end_timestamp=_utc_timestamp(2026, 1, 1),
    min_cell_count=15,
)
STABILITY_SEP_OCT = GateWindow(
    key="stability_sep_oct",
    label="stability Sep-Oct",
    start_timestamp=_utc_timestamp(2025, 9, 1),
    end_timestamp=_utc_timestamp(2025, 11, 1),
    min_cell_count=10,
)
STABILITY_NOV_DEC = GateWindow(
    key="stability_nov_dec",
    label="stability Nov-Dec",
    start_timestamp=_utc_timestamp(2025, 11, 1),
    end_timestamp=_utc_timestamp(2026, 1, 1),
    min_cell_count=10,
)
ALL_WINDOWS: tuple[GateWindow, ...] = (
    CONSTRUCT_DEV,
    CONSTRUCT_VAL,
    STABILITY_SEP_OCT,
    STABILITY_NOV_DEC,
)


@dataclass(frozen=True, slots=True)
class TargetedFuelRow:
    """P2 cluster fuel row plus the P3 realized liquidation target."""

    cluster_index: int
    cluster_start_timestamp: int
    cluster_end_timestamp: int
    direction: Direction
    band: str
    decision_timestamp: int
    week_start_timestamp: int
    price: float
    fuel_usd: float
    oi_only_usd: float
    trailing_price_path_4h: float | None
    metrics_timestamp: int
    book_hitting_usd: float
    backstop_usd: float
    book_hitting_count: int
    backstop_count: int

    @classmethod
    def from_p2(
        cls,
        row: ClusterFuelRow,
        target: HlTargetSummary,
    ) -> TargetedFuelRow:
        """Attach a P2 HL target summary to a cluster fuel row."""

        return cls(
            cluster_index=row.cluster_index,
            cluster_start_timestamp=row.cluster_start_timestamp,
            cluster_end_timestamp=row.cluster_end_timestamp,
            direction=row.direction,
            band=row.band,
            decision_timestamp=row.decision_timestamp,
            week_start_timestamp=row.week_start_timestamp,
            price=row.price,
            fuel_usd=row.fuel_usd,
            oi_only_usd=row.oi_only_usd,
            trailing_price_path_4h=row.trailing_price_path_4h,
            metrics_timestamp=row.metrics_timestamp,
            book_hitting_usd=target.book_hitting_usd,
            backstop_usd=target.backstop_usd,
            book_hitting_count=target.book_hitting_count,
            backstop_count=target.backstop_count,
        )

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-serializable row representation."""

        return {
            "cluster_index": self.cluster_index,
            "cluster_start_timestamp": self.cluster_start_timestamp,
            "cluster_end_timestamp": self.cluster_end_timestamp,
            "direction": self.direction.value,
            "band": self.band,
            "decision_timestamp": self.decision_timestamp,
            "week_start_timestamp": self.week_start_timestamp,
            "price": self.price,
            "fuel_usd": self.fuel_usd,
            "oi_only_usd": self.oi_only_usd,
            "trailing_price_path_4h": self.trailing_price_path_4h,
            "metrics_timestamp": self.metrics_timestamp,
            "book_hitting_usd": self.book_hitting_usd,
            "backstop_usd": self.backstop_usd,
            "book_hitting_count": self.book_hitting_count,
            "backstop_count": self.backstop_count,
        }


@dataclass(frozen=True, slots=True)
class CellScore:
    """Per-cell Spearman scores for one window."""

    direction: Direction
    band: str
    n: int
    min_n: int
    rho_c: float | None
    rho_oi: float | None
    rho_path: float | None
    rho_static: float | None

    @property
    def count_ok(self) -> bool:
        return self.n >= self.min_n

    def required_defined(self, required: Iterable[str]) -> bool:
        values = {
            "fuel": self.rho_c,
            "oi": self.rho_oi,
            "path": self.rho_path,
            "static": self.rho_static,
        }
        return all(values[name] is not None for name in required)

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-serializable cell score."""

        return {
            "direction": self.direction.value,
            "band": self.band,
            "n": self.n,
            "min_n": self.min_n,
            "count_ok": self.count_ok,
            "rho_c": self.rho_c,
            "rho_oi": self.rho_oi,
            "rho_path": self.rho_path,
            "rho_static": self.rho_static,
        }


@dataclass(frozen=True, slots=True)
class FamilyStats:
    """Equal-weight four-cell family statistics."""

    f_vs_oi: float | None
    f_vs_path: float | None
    f_static: float | None

    def to_dict(self) -> dict[str, float | None]:
        return {
            "F_vs_oi": self.f_vs_oi,
            "F_vs_path": self.f_vs_path,
            "F_static": self.f_static,
        }


@dataclass(frozen=True, slots=True)
class WindowScore:
    """Score bundle for one construct-gate window."""

    window: GateWindow
    row_count: int
    cells: tuple[CellScore, ...]
    family: FamilyStats
    required_metrics: tuple[str, ...]

    @property
    def counts_ok(self) -> bool:
        return all(cell.count_ok for cell in self.cells)

    @property
    def required_spearman_defined(self) -> bool:
        return all(cell.required_defined(self.required_metrics) for cell in self.cells)

    @property
    def integrity_ok(self) -> bool:
        return self.counts_ok and self.required_spearman_defined

    def to_dict(self) -> dict[str, object]:
        return {
            "window": self.window.label,
            "start_timestamp": self.window.start_timestamp,
            "end_timestamp": self.window.end_timestamp,
            "min_cell_count": self.window.min_cell_count,
            "row_count": self.row_count,
            "required_metrics": list(self.required_metrics),
            "counts_ok": self.counts_ok,
            "required_spearman_defined": self.required_spearman_defined,
            "integrity_ok": self.integrity_ok,
            "cells": [cell.to_dict() for cell in self.cells],
            "family": self.family.to_dict(),
        }


@dataclass(frozen=True, slots=True)
class BootstrapResult:
    """Family-wide weekly bootstrap result for one F statistic."""

    statistic: Literal["F_vs_oi", "F_vs_path"]
    seed: int
    draws: int
    week_count: int
    values: tuple[float | None, ...]
    undefined_draws: int
    se: float | None
    ci95: tuple[float, float] | None

    @property
    def finite(self) -> bool:
        return self.se is not None and self.ci95 is not None and self.undefined_draws == 0

    @property
    def ci95_excludes_zero(self) -> bool:
        if self.ci95 is None:
            return False
        low, high = self.ci95
        return low > 0.0 or high < 0.0

    def to_dict(self, *, include_values: bool = False) -> dict[str, object]:
        payload: dict[str, object] = {
            "statistic": self.statistic,
            "seed": self.seed,
            "draws": self.draws,
            "week_count": self.week_count,
            "undefined_draws": self.undefined_draws,
            "se": self.se,
            "ci95": None if self.ci95 is None else list(self.ci95),
            "ci95_excludes_zero": self.ci95_excludes_zero,
        }
        if include_values:
            payload["values"] = list(self.values)
        return payload


@dataclass(frozen=True, slots=True)
class FloorLock:
    """Construct-dev bootstrap floor lock."""

    locked: bool
    floor: float | None
    bootstrap: BootstrapResult | None

    def to_dict(self) -> dict[str, object]:
        return {
            "locked": self.locked,
            "floor": self.floor,
            "bootstrap": None if self.bootstrap is None else self.bootstrap.to_dict(),
        }


@dataclass(frozen=True, slots=True)
class ShapeCell:
    """Validation-cell monotonic shape summary."""

    direction: Direction
    band: str
    n: int
    tercile_counts: tuple[int, int, int]
    tercile_means: tuple[float | None, float | None, float | None]
    integrity_ok: bool
    m3_ge_m1: bool
    hard_flip: bool

    def to_dict(self) -> dict[str, object]:
        return {
            "direction": self.direction.value,
            "band": self.band,
            "n": self.n,
            "tercile_counts": list(self.tercile_counts),
            "tercile_means": list(self.tercile_means),
            "integrity_ok": self.integrity_ok,
            "m3_ge_m1": self.m3_ge_m1,
            "hard_flip": self.hard_flip,
        }


@dataclass(frozen=True, slots=True)
class ShapeScore:
    """Construct-val shape gate result."""

    cells: tuple[ShapeCell, ...]
    integrity_ok: bool
    cells_m3_ge_m1: int
    hard_flips: int
    passed: bool

    def to_dict(self) -> dict[str, object]:
        return {
            "integrity_ok": self.integrity_ok,
            "cells_m3_ge_m1": self.cells_m3_ge_m1,
            "hard_flips": self.hard_flips,
            "passed": self.passed,
            "cells": [cell.to_dict() for cell in self.cells],
        }


@dataclass(frozen=True, slots=True)
class StabilityBlock:
    """Stability-window F_vs_oi gate result."""

    score: WindowScore
    passed: bool

    def to_dict(self) -> dict[str, object]:
        f_vs_oi = self.score.family.f_vs_oi
        return {
            "window": self.score.window.label,
            "passed": self.passed,
            "integrity_ok": self.score.integrity_ok,
            "F_vs_oi": f_vs_oi,
            "positive_F_vs_oi": f_vs_oi is not None and f_vs_oi > 0.0,
            "score": self.score.to_dict(),
        }


@dataclass(frozen=True, slots=True)
class ConstructGateResult:
    """Full mechanical P3 construct-gate score."""

    harness_status: Literal["PASS", "FAIL", "NULL"]
    construct_dev: WindowScore
    floor_lock: FloorLock
    construct_val: WindowScore
    val_bootstrap_oi: BootstrapResult | None
    val_bootstrap_path: BootstrapResult | None
    shape: ShapeScore | None
    stability_blocks: tuple[StabilityBlock, StabilityBlock]
    pass_clauses: dict[str, bool]
    null_reasons: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "harness_status": self.harness_status,
            "primary_cells": {
                "horizon_seconds": 14_400,
                "directions": [direction.value for direction in PRIMARY_CELL_DIRECTIONS],
                "bands": list(PRIMARY_CELL_BANDS),
            },
            "construct_dev": self.construct_dev.to_dict(),
            "floor_lock": self.floor_lock.to_dict(),
            "construct_val": self.construct_val.to_dict(),
            "val_bootstrap": {
                "F_vs_oi": None
                if self.val_bootstrap_oi is None
                else self.val_bootstrap_oi.to_dict(),
                "F_vs_path": None
                if self.val_bootstrap_path is None
                else self.val_bootstrap_path.to_dict(),
            },
            "shape": None if self.shape is None else self.shape.to_dict(),
            "stability_blocks": [block.to_dict() for block in self.stability_blocks],
            "pass_clauses": self.pass_clauses,
            "null_reasons": list(self.null_reasons),
        }


def average_ranks(values: Sequence[float]) -> np.ndarray:
    """Return zero-based average ranks, assigning tie groups their mean rank."""

    array = np.asarray(values, dtype=np.float64)
    if array.ndim != 1:
        raise ValueError("values must be one-dimensional")
    if not bool(np.all(np.isfinite(array))):
        raise ValueError("values must be finite")
    order = np.argsort(array, kind="stable")
    ranks = np.empty(array.shape[0], dtype=np.float64)
    start = 0
    while start < order.shape[0]:
        end = start + 1
        value = array[order[start]]
        while end < order.shape[0] and array[order[end]] == value:
            end += 1
        ranks[order[start:end]] = (start + end - 1) / 2.0
        start = end
    return ranks


def spearman(x_values: Sequence[float], y_values: Sequence[float]) -> float | None:
    """Return Spearman rho with average ranks, or ``None`` when undefined."""

    x = np.asarray(x_values, dtype=np.float64)
    y = np.asarray(y_values, dtype=np.float64)
    if x.ndim != 1 or y.ndim != 1 or x.shape != y.shape:
        raise ValueError("x and y must be one-dimensional arrays with equal length")
    if x.shape[0] < 5:
        return None
    if not bool(np.all(np.isfinite(x)) and np.all(np.isfinite(y))):
        return None
    if not (float(np.var(x)) > 0.0 and float(np.var(y)) > 0.0):
        return None
    x_rank = average_ranks(x)
    y_rank = average_ranks(y)
    x_centered = x_rank - float(np.mean(x_rank))
    y_centered = y_rank - float(np.mean(y_rank))
    denominator = math.sqrt(
        float(np.sum(x_centered * x_centered) * np.sum(y_centered * y_centered))
    )
    if not math.isfinite(denominator) or denominator <= 0.0:
        return None
    rho = float(np.sum(x_centered * y_centered) / denominator)
    return max(-1.0, min(1.0, rho))


def rows_for_window(rows: Sequence[TargetedFuelRow], window: GateWindow) -> list[TargetedFuelRow]:
    """Select rows by cluster-start timestamp in a frozen half-open window."""

    if window.end_timestamp > CONSTRUCT_VAL.end_timestamp:
        raise ValueError("construct gate must not score windows ending after 2026-01-01")
    return [
        row
        for row in rows
        if window.start_timestamp <= row.cluster_start_timestamp < window.end_timestamp
    ]


def static_usd_by_row(rows: Sequence[TargetedFuelRow]) -> dict[int, float]:
    """Return the two-band lumped static control for each row index."""

    fuel_by_key: dict[tuple[int, Direction, int, str], float] = {}
    for row in rows:
        key = (row.cluster_index, row.direction, row.decision_timestamp, row.band)
        fuel_by_key[key] = row.fuel_usd

    static: dict[int, float] = {}
    for index, row in enumerate(rows):
        if row.band not in STATIC_BAND_WEIGHTS:
            raise ValueError(f"unsupported primary band: {row.band}")
        total = sum(
            fuel_by_key.get((row.cluster_index, row.direction, row.decision_timestamp, band), 0.0)
            for band in PRIMARY_CELL_BANDS
        )
        static[index] = STATIC_BAND_WEIGHTS[row.band] * total
    return static


def _cell_rows(
    rows: Sequence[TargetedFuelRow],
    *,
    direction: Direction,
    band: str,
) -> list[tuple[int, TargetedFuelRow]]:
    return [
        (index, row)
        for index, row in enumerate(rows)
        if row.direction is direction and row.band == band
    ]


def score_window(
    rows: Sequence[TargetedFuelRow],
    window: GateWindow,
    *,
    required_metrics: Sequence[str] = ("fuel", "oi", "path", "static"),
) -> WindowScore:
    """Score all four primary cells in one frozen window."""

    window_rows = rows_for_window(rows, window)
    static_values = static_usd_by_row(window_rows)
    cells: list[CellScore] = []
    for direction in PRIMARY_CELL_DIRECTIONS:
        for band in PRIMARY_CELL_BANDS:
            indexed_rows = _cell_rows(window_rows, direction=direction, band=band)
            x_fuel = [row.fuel_usd for _index, row in indexed_rows]
            y_target = [row.book_hitting_usd for _index, row in indexed_rows]
            x_oi = [row.oi_only_usd for _index, row in indexed_rows]
            x_path = [
                math.nan if row.trailing_price_path_4h is None else row.trailing_price_path_4h
                for _index, row in indexed_rows
            ]
            x_static = [static_values[index] for index, _row in indexed_rows]
            cells.append(
                CellScore(
                    direction=direction,
                    band=band,
                    n=len(indexed_rows),
                    min_n=window.min_cell_count,
                    rho_c=spearman(x_fuel, y_target),
                    rho_oi=spearman(x_oi, y_target),
                    rho_path=spearman(x_path, y_target),
                    rho_static=spearman(x_static, y_target),
                )
            )
    return WindowScore(
        window=window,
        row_count=len(window_rows),
        cells=tuple(cells),
        family=family_stats(cells),
        required_metrics=tuple(required_metrics),
    )


def family_stats(cells: Sequence[CellScore]) -> FamilyStats:
    """Compute equal-weight family statistics when all needed cell rhos exist."""

    def mean_delta(left_name: str, right_name: str) -> float | None:
        deltas: list[float] = []
        for cell in cells:
            left = getattr(cell, left_name)
            right = getattr(cell, right_name)
            if left is None or right is None:
                return None
            deltas.append(float(left) - float(right))
        return float(np.mean(np.asarray(deltas, dtype=np.float64)))

    return FamilyStats(
        f_vs_oi=mean_delta("rho_c", "rho_oi"),
        f_vs_path=mean_delta("rho_c", "rho_path"),
        f_static=mean_delta("rho_static", "rho_oi"),
    )


def _statistic_value(
    score: WindowScore,
    statistic: Literal["F_vs_oi", "F_vs_path"],
) -> float | None:
    if statistic == "F_vs_oi":
        return score.family.f_vs_oi
    if statistic == "F_vs_path":
        return score.family.f_vs_path
    raise ValueError(f"unsupported statistic: {statistic}")


def weekly_bootstrap(
    rows: Sequence[TargetedFuelRow],
    window: GateWindow,
    *,
    statistic: Literal["F_vs_oi", "F_vs_path"] = "F_vs_oi",
    seed: int = BOOTSTRAP_SEED,
    draws: int = BOOTSTRAP_DRAWS,
) -> BootstrapResult:
    """Run the frozen family-wide weekly draw bootstrap for one F statistic."""

    window_rows = rows_for_window(rows, window)
    week_groups: dict[int, list[TargetedFuelRow]] = defaultdict(list)
    for row in window_rows:
        week_groups[row.week_start_timestamp].append(row)
    weeks = sorted(week_groups)
    if not weeks:
        return BootstrapResult(
            statistic=statistic,
            seed=seed,
            draws=draws,
            week_count=0,
            values=(),
            undefined_draws=draws,
            se=None,
            ci95=None,
        )

    rng = np.random.default_rng(seed)
    values: list[float | None] = []
    for _draw_index in range(draws):
        sampled = rng.choice(np.asarray(weeks, dtype=np.int64), size=len(weeks), replace=True)
        sampled_rows: list[TargetedFuelRow] = []
        for week in sampled.tolist():
            sampled_rows.extend(week_groups[int(week)])
        score = score_window(
            sampled_rows,
            GateWindow(
                key=window.key,
                label=window.label,
                start_timestamp=min(row.cluster_start_timestamp for row in sampled_rows),
                end_timestamp=max(row.cluster_start_timestamp for row in sampled_rows) + 1,
                min_cell_count=5,
            ),
            required_metrics=("fuel", "oi") if statistic == "F_vs_oi" else ("fuel", "path"),
        )
        values.append(_statistic_value(score, statistic))

    undefined = sum(1 for value in values if value is None or not math.isfinite(value))
    if undefined:
        return BootstrapResult(
            statistic=statistic,
            seed=seed,
            draws=draws,
            week_count=len(weeks),
            values=tuple(values),
            undefined_draws=undefined,
            se=None,
            ci95=None,
        )
    array = np.asarray(values, dtype=np.float64)
    se = float(np.std(array, ddof=1)) if array.shape[0] > 1 else None
    ci95 = (
        float(np.percentile(array, 2.5)),
        float(np.percentile(array, 97.5)),
    )
    return BootstrapResult(
        statistic=statistic,
        seed=seed,
        draws=draws,
        week_count=len(weeks),
        values=tuple(float(value) for value in array.tolist()),
        undefined_draws=0,
        se=se,
        ci95=ci95,
    )


def lock_floor(dev_score: WindowScore, dev_bootstrap: BootstrapResult | None) -> FloorLock:
    """Lock the construct-dev floor from F_vs_oi bootstrap SE."""

    if not dev_score.integrity_ok or dev_score.family.f_vs_oi is None:
        return FloorLock(locked=False, floor=None, bootstrap=dev_bootstrap)
    if dev_bootstrap is None or not dev_bootstrap.finite or dev_bootstrap.se is None:
        return FloorLock(locked=False, floor=None, bootstrap=dev_bootstrap)
    floor = round(max(FLOOR_MINIMUM, 2.0 * dev_bootstrap.se), 6)
    return FloorLock(locked=True, floor=floor, bootstrap=dev_bootstrap)


def score_shape(rows: Sequence[TargetedFuelRow], window: GateWindow = CONSTRUCT_VAL) -> ShapeScore:
    """Score the construct-val monotonic shape gate."""

    window_rows = rows_for_window(rows, window)
    cells: list[ShapeCell] = []
    for direction in PRIMARY_CELL_DIRECTIONS:
        for band in PRIMARY_CELL_BANDS:
            selected = [
                row
                for row in window_rows
                if row.direction is direction and row.band == band
            ]
            ordered = sorted(
                selected,
                key=lambda row: (row.fuel_usd, row.cluster_index, row.decision_timestamp),
            )
            buckets: list[list[float]] = [[], [], []]
            n = len(ordered)
            for rank, row in enumerate(ordered):
                tercile = min(2, math.floor(3 * rank / n)) if n else 0
                buckets[tercile].append(row.book_hitting_usd)
            counts = tuple(len(bucket) for bucket in buckets)
            means = tuple(
                None if not bucket else float(np.mean(np.asarray(bucket, dtype=np.float64)))
                for bucket in buckets
            )
            integrity_ok = all(count >= 5 for count in counts)
            m1 = means[0]
            m3 = means[2]
            m3_ge_m1 = bool(integrity_ok and m1 is not None and m3 is not None and m3 >= m1)
            hard_flip = bool(
                integrity_ok
                and m1 is not None
                and m3 is not None
                and ((m3 < 0.8 * m1) if m1 > 0.0 else (m3 < m1))
            )
            cells.append(
                ShapeCell(
                    direction=direction,
                    band=band,
                    n=n,
                    tercile_counts=counts,
                    tercile_means=means,
                    integrity_ok=integrity_ok,
                    m3_ge_m1=m3_ge_m1,
                    hard_flip=hard_flip,
                )
            )
    integrity_ok = all(cell.integrity_ok for cell in cells)
    cells_m3_ge_m1 = sum(1 for cell in cells if cell.m3_ge_m1)
    hard_flips = sum(1 for cell in cells if cell.hard_flip)
    return ShapeScore(
        cells=tuple(cells),
        integrity_ok=integrity_ok,
        cells_m3_ge_m1=cells_m3_ge_m1,
        hard_flips=hard_flips,
        passed=integrity_ok and cells_m3_ge_m1 >= 3 and hard_flips == 0,
    )


def score_stability_block(rows: Sequence[TargetedFuelRow], window: GateWindow) -> StabilityBlock:
    """Score one stability block; integrity failures are block failures."""

    score = score_window(rows, window, required_metrics=("fuel", "oi"))
    f_vs_oi = score.family.f_vs_oi
    return StabilityBlock(
        score=score,
        passed=score.integrity_ok and f_vs_oi is not None and f_vs_oi > 0.0,
    )


def score_construct_gate(
    rows: Sequence[TargetedFuelRow],
    *,
    bootstrap_draws: int = BOOTSTRAP_DRAWS,
    bootstrap_seed: int = BOOTSTRAP_SEED,
) -> ConstructGateResult:
    """Score Phase-A/P3 construct gate rows and emit mechanical harness status."""

    dev_score = score_window(rows, CONSTRUCT_DEV)
    dev_bootstrap = (
        weekly_bootstrap(
            rows,
            CONSTRUCT_DEV,
            statistic="F_vs_oi",
            seed=bootstrap_seed,
            draws=bootstrap_draws,
        )
        if dev_score.integrity_ok
        else None
    )
    floor_lock = lock_floor(dev_score, dev_bootstrap)
    val_score = score_window(rows, CONSTRUCT_VAL)
    val_bootstrap_oi = (
        weekly_bootstrap(
            rows,
            CONSTRUCT_VAL,
            statistic="F_vs_oi",
            seed=bootstrap_seed,
            draws=bootstrap_draws,
        )
        if val_score.integrity_ok
        else None
    )
    val_bootstrap_path = (
        weekly_bootstrap(
            rows,
            CONSTRUCT_VAL,
            statistic="F_vs_path",
            seed=bootstrap_seed,
            draws=bootstrap_draws,
        )
        if val_score.integrity_ok
        else None
    )
    shape = score_shape(rows, CONSTRUCT_VAL) if val_score.counts_ok else None
    stability_blocks = (
        score_stability_block(rows, STABILITY_SEP_OCT),
        score_stability_block(rows, STABILITY_NOV_DEC),
    )

    null_reasons: list[str] = []
    if not dev_score.counts_ok:
        null_reasons.append("construct-dev primary cell below floor")
    if dev_score.counts_ok and not dev_score.required_spearman_defined:
        null_reasons.append("construct-dev required Spearman undefined")
    if not floor_lock.locked:
        null_reasons.append("construct-dev floor not locked")
    if not val_score.counts_ok:
        null_reasons.append("construct-val primary cell below floor")
    if val_score.counts_ok and not val_score.required_spearman_defined:
        null_reasons.append("construct-val required Spearman undefined")
    if shape is not None and not shape.integrity_ok:
        null_reasons.append("construct-val shape tercile below 5 rows")

    floor = floor_lock.floor
    pass_clauses = {
        "construct_val_F_vs_oi_ge_floor": bool(
            floor is not None
            and val_score.family.f_vs_oi is not None
            and val_score.family.f_vs_oi >= floor
        ),
        "construct_val_F_vs_oi_ci95_excludes_zero": bool(
            val_bootstrap_oi is not None and val_bootstrap_oi.ci95_excludes_zero
        ),
        "construct_val_F_vs_path_ge_floor": bool(
            floor is not None
            and val_score.family.f_vs_path is not None
            and val_score.family.f_vs_path >= floor
        ),
        "construct_val_F_vs_path_ci95_excludes_zero": bool(
            val_bootstrap_path is not None and val_bootstrap_path.ci95_excludes_zero
        ),
        "shape_gate": bool(shape is not None and shape.passed),
        "stability_sep_oct": stability_blocks[0].passed,
        "stability_nov_dec": stability_blocks[1].passed,
        "F_static_not_above_F_vs_oi": bool(
            val_score.family.f_static is not None
            and val_score.family.f_vs_oi is not None
            and val_score.family.f_static <= val_score.family.f_vs_oi
        ),
    }
    if null_reasons:
        status: Literal["PASS", "FAIL", "NULL"] = "NULL"
    elif all(pass_clauses.values()):
        status = "PASS"
    else:
        status = "FAIL"

    return ConstructGateResult(
        harness_status=status,
        construct_dev=dev_score,
        floor_lock=floor_lock,
        construct_val=val_score,
        val_bootstrap_oi=val_bootstrap_oi,
        val_bootstrap_path=val_bootstrap_path,
        shape=shape,
        stability_blocks=stability_blocks,
        pass_clauses=pass_clauses,
        null_reasons=tuple(null_reasons),
    )
