"""CEX-inferred directional fuel path for ``cex_oi_cohort_v0``.

This module implements the frozen P2 measurement mechanics only. It does not
score EXP-002, compute model statistics, or materialize full-tape outputs.
"""

from __future__ import annotations

import csv
import json
import math
import zipfile
from bisect import bisect_left, bisect_right
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from io import StringIO
from pathlib import Path
from typing import Any

import numpy as np

from oracle_research.hl_fills_parquet import stable_source_id
from oracle_research.hyperliquid_fills import HlFill
from oracle_research.labels import Bar, Direction

try:
    import duckdb
except ImportError:  # optional dependency group ``analytics``
    duckdb = None  # type: ignore[assignment]

METRICS_INTERVAL_SECONDS = 300
KLINE_INTERVAL_SECONDS = 60
MAX_METRICS_GAP_SECONDS = 900
DEFAULT_BURN_IN_END = int(datetime(2025, 5, 24, 23, 59, tzinfo=UTC).timestamp())
CONSERVATION_REL_TOL = 1e-6
HORIZON_4H_SECONDS = 14_400
TRAILING_PATH_SECONDS = 14_400

DOWN_LIQUIDATION_DIRS = frozenset(
    {"Close Long", "Liquidated Isolated Long", "Liquidated Cross Long"}
)
UP_LIQUIDATION_DIRS = frozenset(
    {"Close Short", "Liquidated Isolated Short", "Liquidated Cross Short"}
)

METRICS_REQUIRED_COLUMNS = frozenset(
    {
        "create_time",
        "sum_open_interest",
        "sum_open_interest_value",
        "sum_toptrader_long_short_ratio",
    }
)
FORBIDDEN_LSR_COLUMNS = frozenset(
    {
        "count_toptrader_long_short_ratio",
        "count_taker_long_short_vol_ratio",
        "sum_taker_long_short_vol_ratio",
    }
)


@dataclass(frozen=True, slots=True)
class FuelBand:
    """Primary adverse-entry distance band."""

    name: str
    lower: float
    upper: float
    lower_closed: bool

    def contains(self, distance: float) -> bool:
        if not math.isfinite(distance):
            return False
        lower_ok = distance >= self.lower if self.lower_closed else distance > self.lower
        return lower_ok and distance < self.upper


# Lower edge is open for (0,1%): profitable cohorts map to zero and are excluded.
# The names intentionally omit any parked [2,4%) band.
BAND_0_1 = FuelBand(name="(0,1%)", lower=0.0, upper=0.01, lower_closed=False)
BAND_1_2 = FuelBand(name="[1,2%)", lower=0.01, upper=0.02, lower_closed=True)
PRIMARY_BANDS = (BAND_0_1, BAND_1_2)


@dataclass(frozen=True, slots=True)
class BinanceMetricsRow:
    """One Binance Vision UM metrics row.

    ``interval_end`` is the raw ``create_time`` normalized to epoch seconds.
    Binance metrics stamp the interval end, not the interval start.
    """

    interval_end: int
    sum_open_interest: float
    sum_open_interest_value: float
    sum_toptrader_long_short_ratio: float | None


@dataclass(frozen=True, slots=True)
class BinanceMetricsArrays:
    """Column-aligned Binance UM metrics arrays."""

    interval_end: np.ndarray
    sum_open_interest: np.ndarray
    sum_open_interest_value: np.ndarray
    sum_toptrader_long_short_ratio: np.ndarray
    n_rows: int

    def __post_init__(self) -> None:
        arrays = (
            self.interval_end,
            self.sum_open_interest,
            self.sum_open_interest_value,
            self.sum_toptrader_long_short_ratio,
        )
        if any(getattr(array, "ndim", None) != 1 for array in arrays):
            raise ValueError("metrics columns must be one-dimensional")
        lengths = {int(array.shape[0]) for array in arrays}
        if len(lengths) != 1:
            raise ValueError("metrics columns must have equal length")
        n_rows = lengths.pop()
        if n_rows == 0:
            raise ValueError("metrics arrays cannot be empty")
        if n_rows != self.n_rows:
            raise ValueError("n_rows does not match column length")
        if self.interval_end.dtype != np.int64:
            raise ValueError("interval_end must be int64 epoch seconds")
        if n_rows > 1 and not bool(np.all(np.diff(self.interval_end) > 0)):
            raise ValueError("metrics interval_end values must be strictly increasing")
        if not bool(np.all(np.isfinite(self.sum_open_interest) & (self.sum_open_interest >= 0))):
            raise ValueError("sum_open_interest must be finite and non-negative")
        if not bool(
            np.all(np.isfinite(self.sum_open_interest_value) & (self.sum_open_interest_value >= 0))
        ):
            raise ValueError("sum_open_interest_value must be finite and non-negative")

    def rows(self) -> list[BinanceMetricsRow]:
        return [
            BinanceMetricsRow(
                interval_end=int(self.interval_end[index]),
                sum_open_interest=float(self.sum_open_interest[index]),
                sum_open_interest_value=float(self.sum_open_interest_value[index]),
                sum_toptrader_long_short_ratio=(
                    None
                    if np.isnan(self.sum_toptrader_long_short_ratio[index])
                    else float(self.sum_toptrader_long_short_ratio[index])
                ),
            )
            for index in range(self.n_rows)
        ]


@dataclass(frozen=True, slots=True)
class PricedCohort:
    """Surviving quantity with a causal entry price."""

    quantity: float
    entry_price: float


@dataclass(frozen=True, slots=True)
class SideCohorts:
    """Unallocated opening stock plus priced cohorts for one side."""

    unallocated: float
    priced: tuple[PricedCohort, ...]

    @property
    def priced_quantity(self) -> float:
        return sum(cohort.quantity for cohort in self.priced)

    @property
    def total_quantity(self) -> float:
        return self.unallocated + self.priced_quantity


@dataclass(frozen=True, slots=True)
class CohortSnapshot:
    """State of the CEX OI cohort machine after one metrics row."""

    timestamp: int
    sum_open_interest: float
    sum_open_interest_value: float
    lsr: float | None
    inferred_long: float | None
    inferred_short: float | None
    long_side: SideCohorts
    short_side: SideCohorts
    valid: bool
    after_burn_in: bool
    conservation_relative_residual: float | None
    clipped: bool
    gap_skipped: bool
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class DecisionFuel:
    """Feature values attached at one decision timestamp."""

    decision_timestamp: int
    metrics_timestamp: int
    direction: Direction
    band: str
    price: float
    fuel_usd: float
    oi_only_usd: float
    trailing_price_path_4h: float | None


@dataclass(frozen=True, slots=True)
class ClusterFuelRow:
    """One P2 row per pure 4h cluster, direction, and primary band."""

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


@dataclass(frozen=True, slots=True)
class HlTargetSummary:
    """Realized HL liquidation mass in the same side and distance band."""

    book_hitting_usd: float
    backstop_usd: float
    book_hitting_count: int
    backstop_count: int


def _parse_create_time(value: str) -> int:
    text = str(value).strip()
    if not text:
        raise ValueError("create_time cannot be empty")
    try:
        raw = float(text)
    except ValueError:
        normalized = text.replace("Z", "+00:00")
        parsed = datetime.fromisoformat(normalized)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return int(parsed.timestamp())
    integer = int(raw)
    if integer >= 1_000_000_000_000_000:
        return integer // 1_000_000
    if integer >= 1_000_000_000_000:
        return integer // 1_000
    return integer


def _parse_float(value: str, *, field: str, nullable_lsr: bool = False) -> float:
    text = str(value).strip()
    if not text:
        if nullable_lsr:
            return math.nan
        raise ValueError(f"{field} cannot be empty")
    parsed = float(text)
    if not math.isfinite(parsed):
        if nullable_lsr:
            return math.nan
        raise ValueError(f"{field} must be finite")
    if nullable_lsr and parsed <= 0:
        return math.nan
    return parsed


def _read_metrics_csv_text(text: str, *, path: Path) -> BinanceMetricsArrays:
    rows = [line for line in text.splitlines() if line.strip()]
    if not rows:
        raise ValueError(f"{path} CSV is empty")
    reader = csv.DictReader(StringIO("\n".join(rows)))
    if reader.fieldnames is None:
        raise ValueError(f"{path} CSV missing header")
    columns = {field.strip() for field in reader.fieldnames}
    missing = METRICS_REQUIRED_COLUMNS - columns
    if missing:
        forbidden_present = sorted(FORBIDDEN_LSR_COLUMNS & columns)
        suffix = ""
        if forbidden_present:
            suffix = f"; forbidden count/volume ratio columns present: {forbidden_present}"
        raise ValueError(f"{path} missing required metrics columns: {sorted(missing)}{suffix}")

    interval_end: list[int] = []
    sum_oi: list[float] = []
    sum_oi_value: list[float] = []
    lsr: list[float] = []
    for line_number, row in enumerate(reader, start=2):
        try:
            interval_end.append(_parse_create_time(str(row["create_time"])))
            sum_oi.append(_parse_float(str(row["sum_open_interest"]), field="sum_open_interest"))
            sum_oi_value.append(
                _parse_float(str(row["sum_open_interest_value"]), field="sum_open_interest_value")
            )
            lsr.append(
                _parse_float(
                    str(row["sum_toptrader_long_short_ratio"]),
                    field="sum_toptrader_long_short_ratio",
                    nullable_lsr=True,
                )
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"{path} invalid metrics row {line_number}") from exc

    order = np.argsort(np.asarray(interval_end, dtype=np.int64), kind="stable")
    return BinanceMetricsArrays(
        interval_end=np.asarray(interval_end, dtype=np.int64)[order],
        sum_open_interest=np.asarray(sum_oi, dtype=np.float64)[order],
        sum_open_interest_value=np.asarray(sum_oi_value, dtype=np.float64)[order],
        sum_toptrader_long_short_ratio=np.asarray(lsr, dtype=np.float64)[order],
        n_rows=len(interval_end),
    )


def _csv_member_name(archive: zipfile.ZipFile, path: Path) -> str:
    names = [
        name
        for name in archive.namelist()
        if name.lower().endswith(".csv") and not name.endswith("/")
    ]
    if len(names) != 1:
        raise ValueError(f"{path} must contain exactly one CSV, found {names!r}")
    return names[0]


def load_metrics_zip(path: Path) -> BinanceMetricsArrays:
    """Load one Binance Vision daily UM metrics zip.

    Only the frozen P2 fields are parsed. ``sum_toptrader_long_short_ratio`` is
    the required position LSR; count-ratio and taker-volume ratio fields are not
    substitutes and never enter this loader.
    """

    resolved = Path(path)
    with zipfile.ZipFile(resolved) as archive:
        raw = archive.read(_csv_member_name(archive, resolved))
    return _read_metrics_csv_text(raw.decode("utf-8-sig"), path=resolved)


def load_metrics_dir(directory: Path) -> BinanceMetricsArrays:
    """Load every Binance Vision metrics ``*.zip`` in filename order."""

    root = Path(directory)
    paths = sorted(path for path in root.glob("*.zip") if path.is_file())
    if not paths:
        raise FileNotFoundError(f"no metrics zip files in {root}")
    parts = [load_metrics_zip(path) for path in paths]
    return BinanceMetricsArrays(
        interval_end=np.concatenate([part.interval_end for part in parts]),
        sum_open_interest=np.concatenate([part.sum_open_interest for part in parts]),
        sum_open_interest_value=np.concatenate([part.sum_open_interest_value for part in parts]),
        sum_toptrader_long_short_ratio=np.concatenate(
            [part.sum_toptrader_long_short_ratio for part in parts]
        ),
        n_rows=sum(part.n_rows for part in parts),
    )


def metrics_rows_from_arrays(metrics: BinanceMetricsArrays) -> list[BinanceMetricsRow]:
    """Return row objects for state-machine consumers."""

    return metrics.rows()


def realign_metric_end_to_interval_start(interval_end: int) -> int:
    """Return the Binance metrics interval-start stamp for kline-start joins."""

    return int(interval_end) - METRICS_INTERVAL_SECONDS


def join_metrics_to_kline_start_grid(
    metrics: Sequence[BinanceMetricsRow],
    kline_interval_start_timestamps: Sequence[int],
) -> dict[int, BinanceMetricsRow]:
    """Join metrics to a Binance kline interval-start grid with the required lag.

    Binance metrics ``create_time`` is the 5-minute interval end while kline
    timestamps are interval starts. This helper asserts the explicit
    ``create_time - 5 minutes`` realignment before producing exact start-stamp
    matches. It is separate from decision as-of joins, which use interval end.
    """

    kline_starts = {int(timestamp) for timestamp in kline_interval_start_timestamps}
    joined: dict[int, BinanceMetricsRow] = {}
    for row in metrics:
        interval_start = realign_metric_end_to_interval_start(row.interval_end)
        if row.interval_end - interval_start != METRICS_INTERVAL_SECONDS:
            raise AssertionError("metrics realignment must subtract exactly 5 minutes")
        if interval_start % KLINE_INTERVAL_SECONDS != 0:
            raise AssertionError("realigned metrics timestamp must lie on the 1m kline grid")
        if interval_start in kline_starts:
            joined[interval_start] = row
    return joined


def _valid_lsr(value: float | None) -> bool:
    return value is not None and math.isfinite(value) and value > 0


def _side_stocks(row: BinanceMetricsRow) -> tuple[float, float] | None:
    lsr = row.sum_toptrader_long_short_ratio
    if not _valid_lsr(lsr):
        return None
    assert lsr is not None
    denominator = 1.0 + lsr
    return row.sum_open_interest * lsr / denominator, row.sum_open_interest / denominator


def _increase_side(side: SideCohorts, quantity: float, entry_price: float) -> SideCohorts:
    if quantity <= 0:
        return side
    return SideCohorts(
        unallocated=side.unallocated,
        priced=(*side.priced, PricedCohort(quantity=quantity, entry_price=entry_price)),
    )


def _reduce_side(side: SideCohorts, quantity: float) -> tuple[SideCohorts, bool]:
    if quantity <= 0:
        return side, False
    total = side.total_quantity
    if total <= 0:
        return SideCohorts(unallocated=0.0, priced=()), True
    if quantity >= total:
        clipped = quantity > total * (1.0 + 1e-12)
        return SideCohorts(unallocated=0.0, priced=()), clipped
    scale = (total - quantity) / total
    priced = tuple(
        PricedCohort(quantity=cohort.quantity * scale, entry_price=cohort.entry_price)
        for cohort in side.priced
        if cohort.quantity * scale > 0
    )
    return SideCohorts(unallocated=side.unallocated * scale, priced=priced), False


def _apply_delta(side: SideCohorts, delta: float, entry_price: float) -> tuple[SideCohorts, bool]:
    if delta > 0:
        return _increase_side(side, delta, entry_price), False
    if delta < 0:
        return _reduce_side(side, -delta)
    return side, False


def _relative_residual(actual: float, expected: float) -> float:
    return abs(actual - expected) / max(abs(expected), 1.0)


def _max_conservation_residual(
    long_side: SideCohorts,
    short_side: SideCohorts,
    inferred_long: float,
    inferred_short: float,
) -> float:
    return max(
        _relative_residual(long_side.total_quantity, inferred_long),
        _relative_residual(short_side.total_quantity, inferred_short),
    )


def run_cex_oi_cohort_v0(
    metrics: Sequence[BinanceMetricsRow],
    price_by_timestamp: Mapping[int, float],
    *,
    burn_in_end: int = DEFAULT_BURN_IN_END,
) -> list[CohortSnapshot]:
    """Run the frozen P1 v5 quantity-cohort state machine.

    Gaps over 15 minutes and invalid LSR rows produce invalid snapshots. A gap
    resynchronizes the side stock into unallocated buckets only, so no priced
    cohort is invented across missing metrics intervals.
    """

    ordered = sorted(metrics, key=lambda row: row.interval_end)
    if len({row.interval_end for row in ordered}) != len(ordered):
        raise ValueError("metrics interval_end values must be unique")

    snapshots: list[CohortSnapshot] = []
    long_side = SideCohorts(unallocated=0.0, priced=())
    short_side = SideCohorts(unallocated=0.0, priced=())
    previous_long: float | None = None
    previous_short: float | None = None
    previous_timestamp: int | None = None

    for row in ordered:
        after_burn_in = row.interval_end > burn_in_end
        stocks = _side_stocks(row)
        price = price_by_timestamp.get(row.interval_end)
        if stocks is None:
            snapshots.append(
                CohortSnapshot(
                    timestamp=row.interval_end,
                    sum_open_interest=row.sum_open_interest,
                    sum_open_interest_value=row.sum_open_interest_value,
                    lsr=row.sum_toptrader_long_short_ratio,
                    inferred_long=None,
                    inferred_short=None,
                    long_side=long_side,
                    short_side=short_side,
                    valid=False,
                    after_burn_in=after_burn_in,
                    conservation_relative_residual=None,
                    clipped=False,
                    gap_skipped=False,
                    reason="invalid_lsr",
                )
            )
            continue
        if price is None or not math.isfinite(price) or price <= 0:
            inferred_long, inferred_short = stocks
            snapshots.append(
                CohortSnapshot(
                    timestamp=row.interval_end,
                    sum_open_interest=row.sum_open_interest,
                    sum_open_interest_value=row.sum_open_interest_value,
                    lsr=row.sum_toptrader_long_short_ratio,
                    inferred_long=inferred_long,
                    inferred_short=inferred_short,
                    long_side=long_side,
                    short_side=short_side,
                    valid=False,
                    after_burn_in=after_burn_in,
                    conservation_relative_residual=None,
                    clipped=False,
                    gap_skipped=False,
                    reason="missing_price",
                )
            )
            continue

        inferred_long, inferred_short = stocks
        if previous_timestamp is None:
            long_side = SideCohorts(unallocated=inferred_long, priced=())
            short_side = SideCohorts(unallocated=inferred_short, priced=())
            residual = _max_conservation_residual(
                long_side, short_side, inferred_long, inferred_short
            )
            snapshots.append(
                CohortSnapshot(
                    timestamp=row.interval_end,
                    sum_open_interest=row.sum_open_interest,
                    sum_open_interest_value=row.sum_open_interest_value,
                    lsr=row.sum_toptrader_long_short_ratio,
                    inferred_long=inferred_long,
                    inferred_short=inferred_short,
                    long_side=long_side,
                    short_side=short_side,
                    valid=True,
                    after_burn_in=after_burn_in,
                    conservation_relative_residual=residual,
                    clipped=False,
                    gap_skipped=False,
                )
            )
            previous_long = inferred_long
            previous_short = inferred_short
            previous_timestamp = row.interval_end
            continue

        assert previous_long is not None and previous_short is not None
        gap = row.interval_end - previous_timestamp
        if gap > MAX_METRICS_GAP_SECONDS:
            long_side = SideCohorts(unallocated=inferred_long, priced=())
            short_side = SideCohorts(unallocated=inferred_short, priced=())
            residual = _max_conservation_residual(
                long_side, short_side, inferred_long, inferred_short
            )
            snapshots.append(
                CohortSnapshot(
                    timestamp=row.interval_end,
                    sum_open_interest=row.sum_open_interest,
                    sum_open_interest_value=row.sum_open_interest_value,
                    lsr=row.sum_toptrader_long_short_ratio,
                    inferred_long=inferred_long,
                    inferred_short=inferred_short,
                    long_side=long_side,
                    short_side=short_side,
                    valid=False,
                    after_burn_in=after_burn_in,
                    conservation_relative_residual=residual,
                    clipped=False,
                    gap_skipped=True,
                    reason="metrics_gap",
                )
            )
            previous_long = inferred_long
            previous_short = inferred_short
            previous_timestamp = row.interval_end
            continue

        long_side, long_clipped = _apply_delta(long_side, inferred_long - previous_long, price)
        short_side, short_clipped = _apply_delta(short_side, inferred_short - previous_short, price)
        clipped = long_clipped or short_clipped
        residual = _max_conservation_residual(long_side, short_side, inferred_long, inferred_short)
        valid = not (after_burn_in and residual > CONSERVATION_REL_TOL and not clipped)
        snapshots.append(
            CohortSnapshot(
                timestamp=row.interval_end,
                sum_open_interest=row.sum_open_interest,
                sum_open_interest_value=row.sum_open_interest_value,
                lsr=row.sum_toptrader_long_short_ratio,
                inferred_long=inferred_long,
                inferred_short=inferred_short,
                long_side=long_side,
                short_side=short_side,
                valid=valid,
                after_burn_in=after_burn_in,
                conservation_relative_residual=residual,
                clipped=clipped,
                gap_skipped=False,
                reason=None if valid else "conservation_break",
            )
        )
        previous_long = inferred_long
        previous_short = inferred_short
        previous_timestamp = row.interval_end

    return snapshots


def asof_snapshot(
    snapshots: Sequence[CohortSnapshot],
    decision_timestamp: int,
) -> CohortSnapshot | None:
    """Return the last metrics snapshot with interval end ``<= T``."""

    timestamps = [snapshot.timestamp for snapshot in snapshots]
    index = bisect_right(timestamps, int(decision_timestamp)) - 1
    if index < 0:
        return None
    return snapshots[index]


def adverse_entry_distance(direction: Direction, entry_price: float, price: float) -> float:
    """Return the frozen adverse-entry distance for one surviving cohort."""

    if direction is Direction.DOWN:
        return max(entry_price / price - 1.0, 0.0)
    if direction is Direction.UP:
        return max(price / entry_price - 1.0, 0.0)
    raise ValueError(f"unsupported direction: {direction}")


def fuel_usd_for_band(
    snapshot: CohortSnapshot,
    *,
    direction: Direction,
    band: FuelBand,
    price: float,
) -> float:
    """Value surviving priced quantities in one adverse-entry band at ``P_T``."""

    side = snapshot.long_side if direction is Direction.DOWN else snapshot.short_side
    quantity = 0.0
    for cohort in side.priced:
        distance = adverse_entry_distance(direction, cohort.entry_price, price)
        if band.contains(distance):
            quantity += cohort.quantity
    return quantity * price


def oi_only_usd_baseline(snapshot: CohortSnapshot, *, direction: Direction) -> float:
    """Return ``sum_open_interest_value * side_share`` at the metrics as-of row."""

    if snapshot.sum_open_interest <= 0:
        return 0.0
    if direction is Direction.DOWN:
        stock = snapshot.inferred_long
    elif direction is Direction.UP:
        stock = snapshot.inferred_short
    else:
        raise ValueError(f"unsupported direction: {direction}")
    if stock is None:
        return math.nan
    return snapshot.sum_open_interest_value * stock / snapshot.sum_open_interest


def _bars_arrays(bars: Sequence[Bar]) -> tuple[list[int], list[float], list[float], list[float]]:
    ordered = sorted(bars, key=lambda bar: bar.timestamp)
    timestamps = [int(bar.timestamp) for bar in ordered]
    if len(set(timestamps)) != len(timestamps):
        raise ValueError("bar timestamps must be unique")
    return (
        timestamps,
        [float(bar.high) for bar in ordered],
        [float(bar.low) for bar in ordered],
        [float(bar.close) for bar in ordered],
    )


def trailing_price_path_4h(
    bars: Sequence[Bar],
    *,
    decision_timestamp: int,
    direction: Direction,
) -> float | None:
    """Causal 4h trailing adverse path baseline at ``T``.

    Downside uses ``max(close[T-4h:T]) / P_T - 1``; upside uses
    ``P_T / min(close[T-4h:T]) - 1``. The current decision close is included,
    and no future bars are read.
    """

    timestamps, _high, _low, close = _bars_arrays(bars)
    right = bisect_right(timestamps, int(decision_timestamp))
    if right == 0 or timestamps[right - 1] != decision_timestamp:
        return None
    left = bisect_left(timestamps, int(decision_timestamp) - TRAILING_PATH_SECONDS)
    window = close[left:right]
    if not window:
        return None
    price = close[right - 1]
    if direction is Direction.DOWN:
        return max(max(window) / price - 1.0, 0.0)
    if direction is Direction.UP:
        return max(price / min(window) - 1.0, 0.0)
    raise ValueError(f"unsupported direction: {direction}")


def decision_fuel(
    snapshots: Sequence[CohortSnapshot],
    bars: Sequence[Bar],
    *,
    decision_timestamp: int,
    direction: Direction,
    band: FuelBand,
) -> DecisionFuel | None:
    """Attach P2 CEX fuel and baselines at one decision timestamp."""

    snapshot = asof_snapshot(snapshots, decision_timestamp)
    if snapshot is None or not snapshot.valid:
        return None
    bar_by_timestamp = {int(bar.timestamp): bar for bar in bars}
    bar = bar_by_timestamp.get(int(decision_timestamp))
    if bar is None:
        return None
    price = float(bar.close)
    return DecisionFuel(
        decision_timestamp=int(decision_timestamp),
        metrics_timestamp=snapshot.timestamp,
        direction=direction,
        band=band.name,
        price=price,
        fuel_usd=fuel_usd_for_band(snapshot, direction=direction, band=band, price=price),
        oi_only_usd=oi_only_usd_baseline(snapshot, direction=direction),
        trailing_price_path_4h=trailing_price_path_4h(
            bars, decision_timestamp=decision_timestamp, direction=direction
        ),
    )


def far_edge_reached(
    bars: Sequence[Bar],
    *,
    decision_timestamp: int,
    direction: Direction,
    far_edge_fraction: float,
    horizon_seconds: int = HORIZON_4H_SECONDS,
) -> bool:
    """Return whether the index path reaches the band's far edge on ``(T,T+4h]``."""

    timestamps, high, low, close = _bars_arrays(bars)
    index = bisect_left(timestamps, int(decision_timestamp))
    if index >= len(timestamps) or timestamps[index] != decision_timestamp:
        return False
    price = close[index]
    left = index + 1
    right = bisect_right(timestamps, int(decision_timestamp) + horizon_seconds)
    if left >= right:
        return False
    if direction is Direction.DOWN:
        return min(low[left:right]) <= price * (1.0 - far_edge_fraction)
    if direction is Direction.UP:
        return max(high[left:right]) >= price * (1.0 + far_edge_fraction)
    raise ValueError(f"unsupported direction: {direction}")


def _direction_from_text(value: str) -> Direction | None:
    if value == Direction.UP.value:
        return Direction.UP
    if value == Direction.DOWN.value:
        return Direction.DOWN
    return None


def _week_start(timestamp: int) -> int:
    dt = datetime.fromtimestamp(timestamp, tz=UTC)
    week = dt - timedelta(days=dt.weekday(), hours=dt.hour, minutes=dt.minute, seconds=dt.second)
    return int(week.replace(microsecond=0).timestamp())


def _horizon_4h_block(clusters_payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    for block in clusters_payload.get("horizons", []):
        if int(block.get("horizon_seconds", 0)) == HORIZON_4H_SECONDS:
            clusters = block.get("clusters")
            if isinstance(clusters, list):
                return clusters
    raise ValueError("clusters payload does not contain a 4h horizon block")


def load_cluster_payload(path: Path) -> dict[str, Any]:
    """Load an EXP-000 cluster inventory JSON payload."""

    return json.loads(Path(path).read_text(encoding="utf-8"))


def build_cluster_fuel_rows(
    clusters_payload: Mapping[str, Any],
    bars: Sequence[Bar],
    snapshots: Sequence[CohortSnapshot],
    *,
    bands: Sequence[FuelBand] = PRIMARY_BANDS,
) -> list[ClusterFuelRow]:
    """Build the P2 pure-direction 4h cluster-row table.

    Mixed clusters are skipped. For each primary band, the earliest eligible
    one-minute decision timestamp in the cluster span is retained.
    """

    rows: list[ClusterFuelRow] = []
    clusters = _horizon_4h_block(clusters_payload)
    bar_timestamps = {int(bar.timestamp) for bar in bars}
    for cluster_index, cluster in enumerate(clusters):
        direction = _direction_from_text(str(cluster.get("direction", "")))
        if direction is None:
            continue
        start = int(cluster["start_timestamp"])
        end = int(cluster["end_timestamp"])
        for band in bands:
            eligible_t: int | None = None
            t = start
            while t <= end:
                if t in bar_timestamps and far_edge_reached(
                    bars,
                    decision_timestamp=t,
                    direction=direction,
                    far_edge_fraction=band.upper,
                ):
                    eligible_t = t
                    break
                t += KLINE_INTERVAL_SECONDS
            if eligible_t is None:
                continue
            features = decision_fuel(
                snapshots,
                bars,
                decision_timestamp=eligible_t,
                direction=direction,
                band=band,
            )
            if features is None:
                continue
            rows.append(
                ClusterFuelRow(
                    cluster_index=cluster_index,
                    cluster_start_timestamp=start,
                    cluster_end_timestamp=end,
                    direction=direction,
                    band=band.name,
                    decision_timestamp=eligible_t,
                    week_start_timestamp=_week_start(start),
                    price=features.price,
                    fuel_usd=features.fuel_usd,
                    oi_only_usd=features.oi_only_usd,
                    trailing_price_path_4h=features.trailing_price_path_4h,
                    metrics_timestamp=features.metrics_timestamp,
                )
            )
    return rows


def bars_from_kline_arrays(
    timestamps: Sequence[int],
    high: Sequence[float],
    low: Sequence[float],
    close: Sequence[float],
    *,
    timestamp_semantics: str = "interval_start",
) -> list[Bar]:
    """Build decision-timestamp bars from 1m kline arrays.

    Binance and consolidated-index kline arrays use interval-start stamps, so
    the default adds 60 seconds to produce D-017 decision timestamps.
    """

    if not (len(timestamps) == len(high) == len(low) == len(close)):
        raise ValueError("bar arrays must have equal length")
    if timestamp_semantics not in {"interval_start", "decision"}:
        raise ValueError("timestamp_semantics must be 'interval_start' or 'decision'")
    offset = KLINE_INTERVAL_SECONDS if timestamp_semantics == "interval_start" else 0
    return [
        Bar(
            timestamp=int(timestamp) + offset,
            high=float(hi),
            low=float(lo),
            close=float(cl),
        )
        for timestamp, hi, lo, cl in zip(timestamps, high, low, close, strict=True)
    ]


def _sql_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _parquet_glob(table_root: Path) -> str:
    return (Path(table_root) / "**" / "*.parquet").as_posix()


def _parquet_source_glob(table_root: Path, source_path: str) -> str:
    source_id = stable_source_id(source_path)
    return (Path(table_root) / "**" / f"part-{source_id}-*.parquet").as_posix()


def _discover_source_paths(conn: Any, table_root: Path, start_ms: int, end_ms: int) -> list[str]:
    query = (
        "SELECT DISTINCT source_path "
        f"FROM read_parquet({_sql_literal(_parquet_glob(table_root))}, hive_partitioning=true) "
        "WHERE time_ms > ? AND time_ms <= ? AND source_path IS NOT NULL"
    )
    return sorted(str(row[0]) for row in conn.execute(query, [start_ms, end_ms]).fetchall())


def iter_hl_fills_from_parquet_window(
    table_root: Path,
    *,
    start_timestamp: int,
    end_timestamp: int,
    batch_rows: int = 100_000,
) -> Iterator[dict[str, Any]]:
    """Yield Parquet fill rows from ``(start_timestamp, end_timestamp]`` per source.

    The query streams one ``source_path`` at a time and orders only by
    ``source_row_number`` within that source. It deliberately avoids a global
    order over the derived fill tape.
    """

    if duckdb is None:
        msg = "duckdb is required; install with pip install oracle-btc-research[analytics]"
        raise ImportError(msg)
    start_ms = int(start_timestamp) * 1000
    end_ms = int(end_timestamp) * 1000
    conn = duckdb.connect(database=":memory:", read_only=False)
    try:
        source_paths = _discover_source_paths(conn, Path(table_root), start_ms, end_ms)
        columns = (
            "user, coin, px, sz, time_ms, dir, tid, liquidation_liquidated_user, "
            "liquidation_method, source_path, source_row_number"
        )
        for source_path in source_paths:
            query = (
                f"SELECT {columns} "
                "FROM read_parquet("
                f"{_sql_literal(_parquet_source_glob(Path(table_root), source_path))}, "
                "hive_partitioning=true) "
                "WHERE source_path = ? AND time_ms > ? AND time_ms <= ? "
                "ORDER BY source_row_number"
            )
            cursor = conn.execute(query, [source_path, start_ms, end_ms])
            names = [description[0] for description in cursor.description]
            while records := cursor.fetchmany(batch_rows):
                for record in records:
                    yield dict(zip(names, record, strict=True))
    finally:
        conn.close()


def _fill_field(fill: HlFill | Mapping[str, Any], name: str) -> Any:
    if isinstance(fill, HlFill):
        if name == "time_ms":
            return fill.time_ms
        if name == "liquidation_liquidated_user":
            return None if fill.liquidation is None else fill.liquidation.get("liquidatedUser")
        if name == "liquidation_method":
            return None if fill.liquidation is None else fill.liquidation.get("method")
        return getattr(fill, name)
    return fill.get(name)


def hl_target_for_cluster_row(
    row: ClusterFuelRow,
    *,
    table_root: Path | None = None,
    fills: Iterable[HlFill | Mapping[str, Any]] | None = None,
) -> HlTargetSummary:
    """Compute the unscored HL target hook for one cluster-row.

    Tests may pass ``fills`` directly. Production callers pass the D-012
    ``all_fills`` Parquet root; rows are streamed per source.
    """

    if fills is None:
        if table_root is None:
            raise ValueError("either fills or table_root must be provided")
        fills = iter_hl_fills_from_parquet_window(
            table_root,
            start_timestamp=row.decision_timestamp,
            end_timestamp=row.decision_timestamp + HORIZON_4H_SECONDS,
        )

    allowed_dirs = DOWN_LIQUIDATION_DIRS if row.direction is Direction.DOWN else UP_LIQUIDATION_DIRS
    band = next((candidate for candidate in PRIMARY_BANDS if candidate.name == row.band), None)
    if band is None:
        raise ValueError(f"unsupported primary band: {row.band}")

    seen_tids: set[int] = set()
    book_usd = 0.0
    backstop_usd = 0.0
    book_count = 0
    backstop_count = 0
    start_ms = row.decision_timestamp * 1000
    end_ms = (row.decision_timestamp + HORIZON_4H_SECONDS) * 1000

    for fill in fills:
        if str(_fill_field(fill, "coin")) != "BTC":
            continue
        time_ms = int(_fill_field(fill, "time_ms"))
        if not start_ms < time_ms <= end_ms:
            continue
        direction_text = str(_fill_field(fill, "dir"))
        if direction_text not in allowed_dirs:
            continue
        liquidated_user = _fill_field(fill, "liquidation_liquidated_user")
        user = _fill_field(fill, "user")
        if liquidated_user is not None and user is not None and str(user) != str(liquidated_user):
            continue
        tid = int(_fill_field(fill, "tid"))
        if tid in seen_tids:
            continue
        px = float(_fill_field(fill, "px"))
        sz = float(_fill_field(fill, "sz"))
        distance = (
            1.0 - px / row.price
            if row.direction is Direction.DOWN
            else px / row.price - 1.0
        )
        if not band.contains(distance):
            continue
        method = str(_fill_field(fill, "liquidation_method"))
        notional = px * sz
        seen_tids.add(tid)
        if method == "market":
            book_usd += notional
            book_count += 1
        elif method == "backstop":
            backstop_usd += notional
            backstop_count += 1

    return HlTargetSummary(
        book_hitting_usd=book_usd,
        backstop_usd=backstop_usd,
        book_hitting_count=book_count,
        backstop_count=backstop_count,
    )
