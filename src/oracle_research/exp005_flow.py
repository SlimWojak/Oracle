"""Outcome-free source/support primitives for EXP-005 Checkpoint A.

This module contains only causal feature-availability mechanics.  It does not
import or call Oracle's labels, outcomes, clusters, estimators, or scorers.
All timestamps are integer UTC epoch seconds denoting interval ends.
"""

from __future__ import annotations

import hashlib
import math
from collections import Counter
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import numpy as np

MINUTE_SECONDS = 60
FIVE_MINUTE_SECONDS = 300
HOUR_SECONDS = 3_600
BOUNDARY_PURGE_SECONDS = 14_400
DETREND_POINTS = 96
RESIDUAL_POINTS = 24
NEWEST_BLOCK_LAG_SECONDS = 300
RAW_LOOKBACK_SECONDS = 599 * MINUTE_SECONDS
MIN_RV_RETURNS = 720
FLOW_FLOOR = 0.90
JOINT_FLOOR = 0.85

M0_COLUMNS = (
    "trend_4h",
    "range_4h",
    "rv_24h",
    "hour_sin",
    "hour_cos",
    "weekday_sin",
    "weekday_cos",
)
M0_FLOW_COLUMNS = (*M0_COLUMNS, "flow_compression_T")

_MINUTE_MISSING = np.uint8(0)
_MINUTE_PRESENT = np.uint8(1)
_MINUTE_CONFLICT = np.uint8(2)
_MINUTE_NONCAUSAL_CLOSE = np.uint8(3)
_SUPPORT_HASH_PREFIX = b"oracle-exp005-ordered-utc-epoch-seconds-v1\n"


@dataclass(frozen=True, slots=True)
class FlowMinute:
    """One normalized USD-M kline minute used by the flow construct.

    ``interval_end`` must be the exact normalized ``open_time + 60s``.  A
    conflict represents differing raw rows at the same normalized open time;
    it is deliberately unusable.  Nonfinite volume fields are retained as
    missing inputs instead of being coerced.
    """

    interval_end: int
    quote_volume: float | None
    taker_buy_quote_volume: float | None
    timing_valid: bool = True
    conflict: bool = False


@dataclass(frozen=True, slots=True)
class HourlyPeriod:
    """Inclusive exact-UTC-hour bounds used by the source audit."""

    name: str
    start: datetime
    end: datetime

    def __post_init__(self) -> None:
        if self.start.tzinfo is None or self.end.tzinfo is None:
            raise ValueError("period bounds must be timezone-aware")
        normalized = (self.start.astimezone(UTC), self.end.astimezone(UTC))
        if normalized[0] > normalized[1]:
            raise ValueError("period start must not exceed period end")
        if any(value.minute or value.second or value.microsecond for value in normalized):
            raise ValueError("period bounds must be exact UTC hours")

    @property
    def start_timestamp(self) -> int:
        return int(self.start.astimezone(UTC).timestamp())

    @property
    def end_timestamp(self) -> int:
        return int(self.end.astimezone(UTC).timestamp())

    @property
    def end_exclusive_timestamp(self) -> int:
        return self.end_timestamp + HOUR_SECONDS

    def hours(self) -> Iterator[int]:
        current = self.start.astimezone(UTC)
        end = self.end.astimezone(UTC)
        while current <= end:
            yield int(current.timestamp())
            current += timedelta(hours=1)


@dataclass(frozen=True, slots=True)
class FlowFeatureResult:
    """Exact flow values and effect-blind construction accounting."""

    values: Mapping[int, float]
    aligned_five_minute_census: Mapping[str, object]
    hourly_feature_census: Mapping[str, object]


@dataclass(frozen=True, slots=True)
class M0FeatureResult:
    """Exact seven-column M0 values and source-only availability reasons."""

    values: Mapping[int, tuple[float, ...]]
    reason_counts: Mapping[str, int]


def ordered_timestamp_sha256(timestamps: Iterable[int]) -> str:
    """Hash a strictly increasing ordered timestamp support deterministically."""

    digest = hashlib.sha256()
    digest.update(_SUPPORT_HASH_PREFIX)
    previous: int | None = None
    for raw_timestamp in timestamps:
        timestamp = int(raw_timestamp)
        if previous is not None and timestamp <= previous:
            raise ValueError("support timestamps must be strictly increasing")
        digest.update(f"{timestamp}\n".encode("ascii"))
        previous = timestamp
    return digest.hexdigest()


def _finite_or_none(value: float | None) -> float | None:
    if value is None:
        return None
    parsed = float(value)
    return parsed if math.isfinite(parsed) else None


def build_flow_compression(
    minutes: Iterable[FlowMinute],
    candidate_hours: Sequence[int],
) -> FlowFeatureResult:
    """Build exact D-033 flow compression at the requested UTC hours.

    The newest five-minute block ends at ``T-5m``.  Every residual uses exactly
    96 consecutive aligned q-points and every feature uses exactly 24 residuals
    with population variance.  Missing inputs are never filled and no epsilon
    is applied.
    """

    hours = tuple(sorted({int(timestamp) for timestamp in candidate_hours}))
    if not hours:
        return FlowFeatureResult(
            values={},
            aligned_five_minute_census={
                "candidate_blocks": 0,
                "structurally_valid_blocks": 0,
                "q_valid_blocks": 0,
                "reason_counts": {},
            },
            hourly_feature_census={"candidate_hours": 0, "valid_hours": 0, "reasons": {}},
        )
    if any(timestamp % HOUR_SECONDS for timestamp in hours):
        raise ValueError("candidate feature timestamps must be exact UTC hours")

    first_minute_end = hours[0] - RAW_LOOKBACK_SECONDS
    last_minute_end = hours[-1] - NEWEST_BLOCK_LAG_SECONDS
    minute_count = (last_minute_end - first_minute_end) // MINUTE_SECONDS + 1
    minute_state = np.full(minute_count, _MINUTE_MISSING, dtype=np.uint8)
    quote = np.full(minute_count, np.nan, dtype=np.float64)
    buy = np.full(minute_count, np.nan, dtype=np.float64)

    for row in minutes:
        interval_end = int(row.interval_end)
        if interval_end < first_minute_end or interval_end > last_minute_end:
            continue
        if interval_end % MINUTE_SECONDS:
            continue
        position = (interval_end - first_minute_end) // MINUTE_SECONDS
        if minute_state[position] != _MINUTE_MISSING:
            raise ValueError("flow minutes must be unique after duplicate resolution")
        if row.conflict:
            minute_state[position] = _MINUTE_CONFLICT
            continue
        if not row.timing_valid:
            minute_state[position] = _MINUTE_NONCAUSAL_CLOSE
            continue
        minute_state[position] = _MINUTE_PRESENT
        quote_value = _finite_or_none(row.quote_volume)
        buy_value = _finite_or_none(row.taker_buy_quote_volume)
        if quote_value is not None:
            quote[position] = quote_value
        if buy_value is not None:
            buy[position] = buy_value

    first_block_end = hours[0] - 595 * MINUTE_SECONDS
    last_block_end = hours[-1] - NEWEST_BLOCK_LAG_SECONDS
    block_ends = np.arange(
        first_block_end,
        last_block_end + FIVE_MINUTE_SECONDS,
        FIVE_MINUTE_SECONDS,
        dtype=np.int64,
    )
    q_values = np.full(block_ends.size, np.nan, dtype=np.float64)
    block_reasons: Counter[str] = Counter()
    structurally_valid = 0

    for block_index, block_end_raw in enumerate(block_ends):
        block_end = int(block_end_raw)
        first = (block_end - 4 * MINUTE_SECONDS - first_minute_end) // MINUTE_SECONDS
        states = minute_state[first : first + 5]
        if bool(np.any(states == _MINUTE_CONFLICT)):
            block_reasons["CONFLICT_MINUTE"] += 1
            continue
        if bool(np.any(states == _MINUTE_NONCAUSAL_CLOSE)):
            block_reasons["NONCAUSAL_CLOSE"] += 1
            continue
        if states.size != 5 or bool(np.any(states == _MINUTE_MISSING)):
            block_reasons["MISSING_MINUTE"] += 1
            continue
        structurally_valid += 1
        block_quote = quote[first : first + 5]
        block_buy = buy[first : first + 5]
        if not bool(np.all(np.isfinite(block_quote))):
            block_reasons["NONFINITE_QUOTE_VOLUME"] += 1
            continue
        if not bool(np.all(np.isfinite(block_buy))):
            block_reasons["NONFINITE_TAKER_BUY_QUOTE_VOLUME"] += 1
            continue
        quote_sum = math.fsum(float(value) for value in block_quote)
        buy_sum = math.fsum(float(value) for value in block_buy)
        sell_sum = quote_sum - buy_sum
        if not math.isfinite(quote_sum) or not math.isfinite(buy_sum):
            block_reasons["NONFINITE_BLOCK_SUM"] += 1
            continue
        if buy_sum <= 0.0:
            block_reasons["NONPOSITIVE_BUY"] += 1
            continue
        if sell_sum <= 0.0:
            block_reasons["NONPOSITIVE_SELL"] += 1
            continue
        q_value = math.log(buy_sum / sell_sum)
        if not math.isfinite(q_value):
            block_reasons["NONFINITE_LOG_RATIO"] += 1
            continue
        q_values[block_index] = q_value
        block_reasons["VALID_Q"] += 1

    residuals = np.full(q_values.size, np.nan, dtype=np.float64)
    for index in range(DETREND_POINTS - 1, q_values.size):
        window = q_values[index - DETREND_POINTS + 1 : index + 1]
        if not bool(np.all(np.isfinite(window))):
            continue
        mean_q = math.fsum(float(value) for value in window) / DETREND_POINTS
        residual = float(q_values[index]) - mean_q
        if math.isfinite(residual):
            residuals[index] = residual

    block_start = int(block_ends[0])
    flow_values: dict[int, float] = {}
    feature_reasons: Counter[str] = Counter()
    for timestamp in hours:
        last_residual_end = timestamp - NEWEST_BLOCK_LAG_SECONDS
        last = (last_residual_end - block_start) // FIVE_MINUTE_SECONDS
        window = residuals[last - RESIDUAL_POINTS + 1 : last + 1]
        if window.size != RESIDUAL_POINTS or not bool(np.all(np.isfinite(window))):
            feature_reasons["INCOMPLETE_24_RESIDUAL_WINDOW"] += 1
            continue
        mean_residual = math.fsum(float(value) for value in window) / RESIDUAL_POINTS
        variance = (
            math.fsum((float(value) - mean_residual) ** 2 for value in window)
            / RESIDUAL_POINTS
        )
        if not math.isfinite(variance):
            feature_reasons["NONFINITE_VARIANCE"] += 1
            continue
        if variance <= 0.0:
            feature_reasons["NONPOSITIVE_VARIANCE"] += 1
            continue
        feature = -math.log(variance)
        if not math.isfinite(feature):
            feature_reasons["NONFINITE_FEATURE"] += 1
            continue
        flow_values[timestamp] = feature
        feature_reasons["VALID"] += 1

    return FlowFeatureResult(
        values=flow_values,
        aligned_five_minute_census={
            "candidate_blocks": int(block_ends.size),
            "structurally_valid_blocks": structurally_valid,
            "q_valid_blocks": int(np.count_nonzero(np.isfinite(q_values))),
            "reason_counts": dict(sorted(block_reasons.items())),
            "membership": "five exact 1m interval ends in (s-5m,s]",
        },
        hourly_feature_census={
            "candidate_hours": len(hours),
            "valid_hours": len(flow_values),
            "reasons": dict(sorted(feature_reasons.items())),
            "newest_block_lag_seconds": NEWEST_BLOCK_LAG_SECONDS,
            "raw_lookback_seconds": RAW_LOOKBACK_SECONDS,
            "detrend_points": DETREND_POINTS,
            "residual_points": RESIDUAL_POINTS,
            "variance_ddof": 0,
        },
    )


def _validate_index_arrays(
    end_timestamps: np.ndarray,
    close: np.ndarray,
    high: np.ndarray,
    low: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    timestamps = np.asarray(end_timestamps, dtype=np.int64)
    close_values = np.asarray(close, dtype=np.float64)
    high_values = np.asarray(high, dtype=np.float64)
    low_values = np.asarray(low, dtype=np.float64)
    arrays = (timestamps, close_values, high_values, low_values)
    if any(values.ndim != 1 for values in arrays):
        raise ValueError("index columns must be one-dimensional")
    if len({values.size for values in arrays}) != 1:
        raise ValueError("index columns must align")
    if timestamps.size == 0 or not bool(np.all(np.diff(timestamps) > 0)):
        raise ValueError("index timestamps must be nonempty and strictly increasing")
    for name, values in (("close", close_values), ("high", high_values), ("low", low_values)):
        if not bool(np.all(np.isfinite(values) & (values > 0.0))):
            raise ValueError(f"{name} must be positive and finite")
    if not bool(np.all(low_values <= high_values)):
        raise ValueError("low cannot exceed high")
    return timestamps, close_values, high_values, low_values


def _exact_row(timestamps: np.ndarray, timestamp: int) -> int | None:
    index = int(np.searchsorted(timestamps, timestamp))
    if index >= timestamps.size or int(timestamps[index]) != timestamp:
        return None
    return index


def _causal_rv24h(
    timestamps: np.ndarray,
    close: np.ndarray,
    timestamp: int,
) -> tuple[float | None, int]:
    left = int(np.searchsorted(timestamps, timestamp - 86_400, side="left"))
    right = int(np.searchsorted(timestamps, timestamp, side="right"))
    window_ts = timestamps[left:right]
    window_close = close[left:right]
    if window_ts.size < 2:
        return None, 0
    consecutive = np.diff(window_ts) == MINUTE_SECONDS
    returns = np.log(window_close[1:] / window_close[:-1])
    in_window = window_ts[1:] > timestamp - 86_400
    valid = consecutive & in_window & np.isfinite(returns)
    count = int(np.count_nonzero(valid))
    if count < MIN_RV_RETURNS:
        return None, count
    sigma = float(np.sqrt(np.sum(np.square(returns[valid]))))
    if not math.isfinite(sigma) or sigma <= 0.0:
        return None, count
    return sigma, count


def _m0_vector(
    timestamps: np.ndarray,
    close: np.ndarray,
    high: np.ndarray,
    low: np.ndarray,
    timestamp: int,
    sigma: float,
) -> tuple[tuple[float, ...] | None, tuple[str, ...]]:
    reasons: list[str] = []
    now = _exact_row(timestamps, timestamp)
    past = _exact_row(timestamps, timestamp - BOUNDARY_PURGE_SECONDS)
    trend = math.nan
    if now is None or past is None:
        reasons.append("MISSING_TREND_ENDPOINT")
    else:
        trend = float(math.log(close[now] / close[past]))

    first_range = timestamp - BOUNDARY_PURGE_SECONDS + MINUTE_SECONDS
    range_left = int(np.searchsorted(timestamps, first_range, side="left"))
    range_right = range_left + 240
    expected = np.arange(first_range, timestamp + 1, MINUTE_SECONDS, dtype=np.int64)
    range_value = math.nan
    if range_right > timestamps.size or not np.array_equal(
        timestamps[range_left:range_right], expected
    ):
        reasons.append("MISSING_RANGE_BAR")
    else:
        window_high = high[range_left:range_right]
        window_low = low[range_left:range_right]
        if not bool(
            np.all(np.isfinite(window_high) & (window_high > 0.0))
            and np.all(np.isfinite(window_low) & (window_low > 0.0))
        ):
            reasons.append("INVALID_RANGE_BAR")
        else:
            range_value = float(math.log(float(np.max(window_high)) / float(np.min(window_low))))
    if not math.isfinite(sigma) or sigma <= 0.0:
        reasons.append("INVALID_RV")

    decision_time = datetime.fromtimestamp(timestamp, tz=UTC)
    hour_angle = 2.0 * math.pi * decision_time.hour / 24.0
    weekday_angle = 2.0 * math.pi * decision_time.weekday() / 7.0
    features = (
        trend,
        range_value,
        float(sigma),
        math.sin(hour_angle),
        math.cos(hour_angle),
        math.sin(weekday_angle),
        math.cos(weekday_angle),
    )
    if reasons or not all(math.isfinite(value) for value in features):
        return None, tuple(reasons or ("NONFINITE_FEATURE",))
    return features, ()


def build_m0_features(
    *,
    end_timestamps: np.ndarray,
    close: np.ndarray,
    high: np.ndarray,
    low: np.ndarray,
    candidate_hours: Sequence[int],
) -> M0FeatureResult:
    """Reconstruct the exact ordered seven D-033 M0 columns without outcomes."""

    timestamps, close_values, high_values, low_values = _validate_index_arrays(
        end_timestamps, close, high, low
    )
    hours = tuple(sorted({int(timestamp) for timestamp in candidate_hours}))
    if any(timestamp % HOUR_SECONDS for timestamp in hours):
        raise ValueError("M0 candidate timestamps must be exact UTC hours")
    values: dict[int, tuple[float, ...]] = {}
    reasons: Counter[str] = Counter()
    for timestamp in hours:
        sigma, _ = _causal_rv24h(timestamps, close_values, timestamp)
        if sigma is None:
            reasons["MISSING_RV"] += 1
            continue
        vector, missing_reasons = _m0_vector(
            timestamps,
            close_values,
            high_values,
            low_values,
            timestamp,
            sigma,
        )
        if vector is None:
            for reason in missing_reasons:
                reasons[reason] += 1
            continue
        if len(vector) != len(M0_COLUMNS):
            raise AssertionError("M0 vector is not seven columns")
        values[timestamp] = vector
        reasons["VALID"] += 1
    return M0FeatureResult(values=values, reason_counts=dict(sorted(reasons.items())))


def _month_bounds(month: str) -> tuple[int, int]:
    year, month_number = map(int, month.split("-"))
    start = datetime(year, month_number, 1, tzinfo=UTC)
    if month_number == 12:
        next_month = datetime(year + 1, 1, 1, tzinfo=UTC)
    else:
        next_month = datetime(year, month_number + 1, 1, tzinfo=UTC)
    return int(start.timestamp()), int(next_month.timestamp())


def availability_report(
    *,
    periods: Sequence[HourlyPeriod],
    flow_values: Mapping[int, float],
    m0_values: Mapping[int, tuple[float, ...]],
) -> dict[str, object]:
    """Report exact UTC-hour flow and seven-M0-plus-flow support and gates."""

    reports: dict[str, object] = {}
    overall_clear = True
    all_zero_months: list[str] = []
    flow_keys = set(flow_values)
    m0_keys = set(m0_values)
    for period in periods:
        candidate = tuple(period.hours())
        candidate_set = set(candidate)
        flow_support = tuple(sorted(candidate_set & flow_keys))
        m0_support = tuple(sorted(candidate_set & m0_keys))
        joint_support = tuple(sorted(set(flow_support) & set(m0_support)))
        flow_rate = len(flow_support) / len(candidate) if candidate else 0.0
        joint_rate = len(joint_support) / len(candidate) if candidate else 0.0
        flow_pass = flow_rate >= FLOW_FLOOR
        joint_pass = joint_rate >= JOINT_FLOOR

        monthly: dict[str, dict[str, object]] = {}
        joint_set = set(joint_support)
        for timestamp in candidate:
            month = datetime.fromtimestamp(timestamp, tz=UTC).strftime("%Y-%m")
            row = monthly.setdefault(month, {"candidate_hours": 0, "joint_hours": 0})
            row["candidate_hours"] = int(row["candidate_hours"]) + 1
            if timestamp in joint_set:
                row["joint_hours"] = int(row["joint_hours"]) + 1
        zero_full_months: list[str] = []
        for month, row in monthly.items():
            month_start, month_end = _month_bounds(month)
            full_hours = (month_end - month_start) // HOUR_SECONDS
            row["full_calendar_month"] = row["candidate_hours"] == full_hours
            if row["full_calendar_month"] and row["joint_hours"] == 0:
                zero_full_months.append(month)

        purge = tuple(
            timestamp
            for timestamp in candidate
            if timestamp - period.start_timestamp <= BOUNDARY_PURGE_SECONDS
            or period.end_exclusive_timestamp - timestamp <= BOUNDARY_PURGE_SECONDS
        )
        candidate_hash = ordered_timestamp_sha256(candidate)
        flow_hash = ordered_timestamp_sha256(flow_support)
        m0_hash = ordered_timestamp_sha256(m0_support)
        joint_hash = ordered_timestamp_sha256(joint_support)
        period_clear = flow_pass and joint_pass and not zero_full_months
        overall_clear &= period_clear
        all_zero_months.extend(zero_full_months)
        reports[period.name] = {
            "candidate_hours": len(candidate),
            "candidate_support_sha256": candidate_hash,
            "flow": {
                "available_hours": len(flow_support),
                "coverage_fraction": flow_rate,
                "floor": FLOW_FLOOR,
                "floor_pass": flow_pass,
                "ordered_support_sha256": flow_hash,
            },
            "m0_exact_seven_columns": {
                "available_hours": len(m0_support),
                "ordered_columns": list(M0_COLUMNS),
                "ordered_support_sha256": m0_hash,
            },
            "m0_flow_joint": {
                "available_hours": len(joint_support),
                "coverage_fraction": joint_rate,
                "floor": JOINT_FLOOR,
                "floor_pass": joint_pass,
                "ordered_columns": list(M0_FLOW_COLUMNS),
                "ordered_support_sha256": joint_hash,
            },
            "paired_rung_support": {
                "m0_common_ordered_support_sha256": joint_hash,
                "m0_flow_ordered_support_sha256": joint_hash,
                "identical": True,
            },
            "monthly_joint": dict(sorted(monthly.items())),
            "zero_joint_full_months": zero_full_months,
            "d023_four_hour_boundary_purge": {
                "seconds": BOUNDARY_PURGE_SECONDS,
                "excluded_candidate_hours": len(purge),
                "ordered_support_sha256": ordered_timestamp_sha256(purge),
                "semantics": "clock-only report; no labels, outcomes, or cluster straddles read",
            },
            "coverage_clearance": period_clear,
        }
    return {
        "periods": reports,
        "coverage_clearance": overall_clear,
        "zero_joint_full_months": sorted(all_zero_months),
        "support_hash_encoding": _SUPPORT_HASH_PREFIX.decode("ascii").strip()
        + " followed by newline-delimited integer epoch seconds",
    }


def checkpoint_a_disposition(*, source_integrity_clear: bool, coverage_clear: bool) -> str:
    """Apply only the frozen pre-effect Checkpoint A disposition."""

    if not source_integrity_clear:
        return "BLOCKED_SOURCE"
    if not coverage_clear:
        return "NULL_COVERAGE"
    return "CLEARED_CHECKPOINT_A"
