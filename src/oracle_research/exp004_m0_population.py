"""Frozen prospective population and outcome mechanics for EXP-004 M0.

This module implements only the D-032/D-033 price-only population.  All input
bar timestamps are canonical D-022 *interval-end* timestamps.  Gaps are never
compressed, filled, or interpreted as negative outcomes.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from enum import StrEnum

import numpy as np

from oracle_research.batch_labels import DIR_DOWN, DIR_UP, batch_first_passage_time
from oracle_research.clusters import CLUSTER_CLOSE_SECONDS

MINUTE_SECONDS = 60
HOUR_SECONDS = 3_600
BOUNDARY_PURGE_SECONDS = 14_400
FIXED_BARRIER = 0.02
IMPULSE_LIMIT = math.log(1.005)
MIN_RV_RETURNS = 720
M0_COLUMNS = (
    "trend_4h",
    "range_4h",
    "rv_24h",
    "hour_sin",
    "hour_cos",
    "weekday_sin",
    "weekday_cos",
)


class Cause(StrEnum):
    """D-032 competing first cause, including the two unscored outcomes."""

    UP = "UP"
    DOWN = "DOWN"
    NONE = "NONE"
    AMBIGUOUS = "AMBIGUOUS"
    CENSORED_GAP = "CENSORED_GAP"


SCOREABLE_CAUSES = frozenset((Cause.UP, Cause.DOWN, Cause.NONE))
POSITIVE_CAUSES = frozenset((Cause.UP, Cause.DOWN))


class BaseStatus(StrEnum):
    """Inventory disposition before any outcome is read."""

    ELIGIBLE = "ELIGIBLE"
    MISSING_PRECONDITION = "MISSING_PRECONDITION"
    IMPULSE_EXCLUDED = "IMPULSE_EXCLUDED"
    MISSING_RV = "MISSING_RV"


@dataclass(frozen=True, slots=True)
class Period:
    """Half-open UTC evaluation period."""

    key: str
    start_timestamp: int
    end_timestamp: int

    def contains(self, timestamp: int) -> bool:
        return self.start_timestamp <= timestamp < self.end_timestamp


def _utc_timestamp(text: str) -> int:
    return int(datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp())


PERIODS = (
    Period(
        "development",
        _utc_timestamp("2020-01-01T00:00:00Z"),
        _utc_timestamp("2024-01-01T00:00:00Z"),
    ),
    Period(
        "validation",
        _utc_timestamp("2024-01-01T00:00:00Z"),
        _utc_timestamp("2025-01-01T00:00:00Z"),
    ),
    Period(
        "test_2025",
        _utc_timestamp("2025-01-01T00:00:00Z"),
        _utc_timestamp("2026-01-01T00:00:00Z"),
    ),
    Period(
        "test_2026",
        _utc_timestamp("2026-01-01T00:00:00Z"),
        _utc_timestamp("2026-08-01T00:00:00Z"),
    ),
)
PERIOD_BY_KEY = {period.key: period for period in PERIODS}
OOS_PERIOD_KEYS = ("validation", "test_2025", "test_2026")
HORIZONS = (3_600, 14_400)
LABEL_FAMILIES = ("fixed", "twin")


@dataclass(frozen=True, slots=True)
class Outcome:
    """One categorical first cause at one decision timestamp."""

    cause: Cause
    passage_timestamp: int | None = None

    def __post_init__(self) -> None:
        if self.cause in POSITIVE_CAUSES and self.passage_timestamp is None:
            raise ValueError("positive outcomes require a passage timestamp")
        if self.cause not in POSITIVE_CAUSES and self.passage_timestamp is not None:
            raise ValueError("only positive outcomes have passage timestamps")


@dataclass(slots=True)
class M0RiskRow:
    """One prospective hourly state with linked horizons and label families."""

    timestamp: int
    period: str
    base_status: BaseStatus
    sigma: float | None = None
    impulse: float | None = None
    features: tuple[float, ...] | None = None
    feature_missing_reasons: tuple[str, ...] = ()
    twin_barrier: float | None = None
    outcomes: dict[tuple[str, int], Outcome] = field(default_factory=dict)
    cluster_ids: dict[tuple[str, int], str] = field(default_factory=dict)
    cluster_morphology: dict[tuple[str, int], str] = field(default_factory=dict)
    scoreable: dict[int, bool] = field(default_factory=dict)
    exclusion_reasons: dict[int, tuple[str, ...]] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ClusterRecord:
    """One D-014 event cluster with a stable family/horizon identifier."""

    cluster_id: str
    label_family: str
    horizon_seconds: int
    start_timestamp: int
    end_timestamp: int
    up_count: int
    down_count: int
    up_passage_timestamps: tuple[int, ...] = ()
    down_passage_timestamps: tuple[int, ...] = ()

    @property
    def morphology(self) -> str:
        return "MIXED" if self.up_count and self.down_count else "ONE_WAY"

    def contains_direction(self, cause: Cause) -> bool:
        if cause is Cause.UP:
            return self.up_count > 0
        if cause is Cause.DOWN:
            return self.down_count > 0
        return False


@dataclass(frozen=True, slots=True)
class PopulationResult:
    """Frozen M0 population plus deterministic inventory accounting."""

    rows: tuple[M0RiskRow, ...]
    clusters: tuple[ClusterRecord, ...]
    kappa: float
    inventory: dict[str, object]


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
    if any(values.ndim != 1 for values in (timestamps, close_values, high_values, low_values)):
        raise ValueError("index columns must be one-dimensional")
    if len({values.size for values in (timestamps, close_values, high_values, low_values)}) != 1:
        raise ValueError("index columns must align")
    if timestamps.size == 0 or not bool(np.all(np.diff(timestamps) > 0)):
        raise ValueError("index timestamps must be nonempty and strictly increasing")
    for name, values in (("close", close_values), ("high", high_values), ("low", low_values)):
        if not bool(np.all(np.isfinite(values) & (values > 0.0))):
            raise ValueError(f"{name} must be positive and finite")
    if not bool(np.all(low_values <= high_values)):
        raise ValueError("low cannot exceed high")
    return timestamps, close_values, high_values, low_values


def exact_row(timestamps: np.ndarray, timestamp: int) -> int | None:
    """Return the exact row for ``timestamp`` or ``None`` without flooring."""

    index = int(np.searchsorted(timestamps, timestamp))
    if index >= timestamps.size or int(timestamps[index]) != timestamp:
        return None
    return index


def causal_rv24h(
    timestamps: np.ndarray,
    close: np.ndarray,
    timestamp: int,
    *,
    min_returns: int = MIN_RV_RETURNS,
) -> tuple[float | None, int]:
    """Return D-032 sigma and the count of exact consecutive-minute returns."""

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
    if count < min_returns:
        return None, count
    sigma = float(np.sqrt(np.sum(np.square(returns[valid]))))
    if not math.isfinite(sigma) or sigma <= 0.0:
        return None, count
    return sigma, count


def m0_features(
    timestamps: np.ndarray,
    close: np.ndarray,
    high: np.ndarray,
    low: np.ndarray,
    timestamp: int,
    sigma: float,
) -> tuple[tuple[float, ...] | None, tuple[str, ...]]:
    """Build the exact ordered seven-column M0 vector at ``timestamp``."""

    reasons: list[str] = []
    now = exact_row(timestamps, timestamp)
    past = exact_row(timestamps, timestamp - BOUNDARY_PURGE_SECONDS)
    trend = math.nan
    if now is None or past is None:
        reasons.append("MISSING_TREND_ENDPOINT")
    else:
        trend = float(math.log(close[now] / close[past]))

    first_range = timestamp - BOUNDARY_PURGE_SECONDS + MINUTE_SECONDS
    range_left = int(np.searchsorted(timestamps, first_range, side="left"))
    range_right = range_left + 240
    expected_range = np.arange(first_range, timestamp + 1, MINUTE_SECONDS, dtype=np.int64)
    range_value = math.nan
    if (
        range_right > timestamps.size
        or not np.array_equal(timestamps[range_left:range_right], expected_range)
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

    dt = datetime.fromtimestamp(timestamp, tz=UTC)
    hour_angle = 2.0 * math.pi * dt.hour / 24.0
    weekday_angle = 2.0 * math.pi * dt.weekday() / 7.0
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


def first_cause(
    timestamps: np.ndarray,
    close: np.ndarray,
    high: np.ndarray,
    low: np.ndarray,
    *,
    timestamp: int,
    horizon_seconds: int,
    barrier_fraction: float,
) -> Outcome:
    """Evaluate the strict D-032 gap-aware competing-risk outcome."""

    if horizon_seconds <= 0 or horizon_seconds % MINUTE_SECONDS:
        raise ValueError("horizon must be a positive whole number of minutes")
    if not math.isfinite(barrier_fraction) or not 0.0 < barrier_fraction < 1.0:
        raise ValueError("barrier fraction must be finite and in (0, 1)")
    anchor_row = exact_row(timestamps, timestamp)
    if anchor_row is None:
        raise ValueError("anchor close is missing")
    expected = np.arange(
        timestamp + MINUTE_SECONDS,
        timestamp + horizon_seconds + 1,
        MINUTE_SECONDS,
        dtype=np.int64,
    )
    left = int(np.searchsorted(timestamps, expected[0], side="left"))
    right = left + expected.size
    if right > timestamps.size or not np.array_equal(timestamps[left:right], expected):
        return Outcome(Cause.CENSORED_GAP)
    anchor = float(close[anchor_row])
    upper = anchor * (1.0 + barrier_fraction)
    lower = anchor * (1.0 - barrier_fraction)
    up_rows = np.flatnonzero(high[left:right] >= upper)
    down_rows = np.flatnonzero(low[left:right] <= lower)
    first_up = int(up_rows[0]) if up_rows.size else None
    first_down = int(down_rows[0]) if down_rows.size else None
    if first_up is None and first_down is None:
        return Outcome(Cause.NONE)
    if first_up is not None and first_down is not None and first_up == first_down:
        return Outcome(Cause.AMBIGUOUS)
    if first_down is None or (first_up is not None and first_up < first_down):
        assert first_up is not None
        return Outcome(Cause.UP, int(expected[first_up]))
    assert first_down is not None
    return Outcome(Cause.DOWN, int(expected[first_down]))


def period_for_timestamp(timestamp: int, periods: Sequence[Period] = PERIODS) -> Period | None:
    """Return the unique frozen period containing ``timestamp``."""

    matches = [period for period in periods if period.contains(timestamp)]
    if len(matches) > 1:
        raise ValueError("evaluation periods overlap")
    return matches[0] if matches else None


def period_horizon_eligible(
    timestamp: int,
    horizon_seconds: int,
    period: Period,
    *,
    purge_seconds: int = BOUNDARY_PURGE_SECONDS,
) -> bool:
    """Apply the D-023 four-hour purge and half-open full-window rule."""

    if not period.contains(timestamp):
        return False
    if timestamp - period.start_timestamp <= purge_seconds:
        return False
    if period.end_timestamp - timestamp <= purge_seconds:
        return False
    return timestamp + horizon_seconds < period.end_timestamp


def cluster_crosses_period(
    cluster: ClusterRecord,
    period: Period,
    *,
    padding_seconds: int = BOUNDARY_PURGE_SECONDS,
) -> bool:
    """Return whether the padded closed cluster reaches outside a half-open period."""

    return (
        cluster.start_timestamp - padding_seconds < period.start_timestamp
        or cluster.end_timestamp + padding_seconds >= period.end_timestamp
    )


def load_fixed_clusters(payload: dict[str, object]) -> dict[int, list[ClusterRecord]]:
    """Parse the committed D-014 fixed-barrier cluster inventory."""

    parameters = payload.get("parameters")
    if not isinstance(parameters, dict):
        raise ValueError("cluster payload is missing parameters")
    required_parameters = {
        "min_members": 2,
        "construction": "componentwise_median",
        "label_semantics": "wall_clock_first_passage",
        "threshold": FIXED_BARRIER,
        "horizons_seconds": list(HORIZONS),
        "decision_timestamp": "interval_end",
    }
    for key, expected in required_parameters.items():
        if parameters.get(key) != expected:
            raise ValueError(f"fixed cluster parameter {key!r} is not frozen D-022/D-032")
    result: dict[int, list[ClusterRecord]] = {}
    horizons = payload.get("horizons")
    if not isinstance(horizons, list):
        raise ValueError("cluster payload is missing horizons")
    for horizon_block in horizons:
        if not isinstance(horizon_block, dict):
            raise ValueError("invalid horizon block")
        horizon = int(horizon_block["horizon_seconds"])
        records: list[ClusterRecord] = []
        raw_clusters = horizon_block.get("clusters")
        if not isinstance(raw_clusters, list):
            raise ValueError("horizon block is missing clusters")
        for index, raw in enumerate(raw_clusters):
            if not isinstance(raw, dict):
                raise ValueError("invalid cluster record")
            start_timestamp = int(raw["start_timestamp"])
            end_timestamp = int(raw["end_timestamp"])
            up_count = int(raw["up_count"])
            down_count = int(raw["down_count"])
            anchor_count = int(raw["anchor_count"])
            if start_timestamp > end_timestamp:
                raise ValueError("fixed cluster start exceeds end")
            if up_count < 0 or down_count < 0 or anchor_count != up_count + down_count:
                raise ValueError("fixed cluster directional counts are invalid")
            expected_direction = (
                "mixed"
                if up_count and down_count
                else "up"
                if up_count
                else "down"
            )
            if raw.get("direction") != expected_direction:
                raise ValueError("fixed cluster direction is inconsistent with counts")
            records.append(
                ClusterRecord(
                    cluster_id=f"fixed:{horizon}:{index}",
                    label_family="fixed",
                    horizon_seconds=horizon,
                    start_timestamp=start_timestamp,
                    end_timestamp=end_timestamp,
                    up_count=up_count,
                    down_count=down_count,
                )
            )
        if any(
            records[index].start_timestamp <= records[index - 1].start_timestamp
            for index in range(1, len(records))
        ):
            raise ValueError("fixed clusters must have strictly increasing starts")
        if any(
            records[index].start_timestamp <= records[index - 1].end_timestamp
            for index in range(1, len(records))
        ):
            raise ValueError("fixed cluster intervals overlap")
        result[horizon] = records
    if set(result) != set(HORIZONS):
        raise ValueError("fixed inventory must contain exactly the linked horizons")
    return result


def attach_fixed_passage_inventory(
    *,
    fixed_by_horizon: dict[int, list[ClusterRecord]],
    timestamps: np.ndarray,
    close: np.ndarray,
    high: np.ndarray,
    low: np.ndarray,
) -> dict[int, list[ClusterRecord]]:
    """Reconstruct the committed D-014 minute-anchor passage inventory.

    The committed fixed cluster artifact stores aggregate counts but not member
    passage times.  Exact lead therefore reconstructs the same D-014 input
    labels from the verified D-022 bars and requires every aggregate count to
    match before attaching direction-specific passage timestamps.
    """

    result: dict[int, list[ClusterRecord]] = {}
    for horizon in HORIZONS:
        clusters = fixed_by_horizon[horizon]
        starts = np.fromiter(
            (cluster.start_timestamp for cluster in clusters),
            dtype=np.int64,
            count=len(clusters),
        )
        passages: dict[str, dict[Cause, list[int]]] = {
            cluster.cluster_id: {Cause.UP: [], Cause.DOWN: []} for cluster in clusters
        }
        labels = batch_first_passage_time(
            timestamps,
            high,
            low,
            close,
            horizon_seconds=horizon,
            threshold_fraction=FIXED_BARRIER,
            step_seconds=MINUTE_SECONDS,
        )
        positive_rows = np.flatnonzero(
            (labels.direction == DIR_UP) | (labels.direction == DIR_DOWN)
        )
        for row_index in positive_rows.tolist():
            anchor_timestamp = int(timestamps[row_index])
            cause = Cause.UP if labels.direction[row_index] == DIR_UP else Cause.DOWN
            position = int(np.searchsorted(starts, anchor_timestamp, side="right")) - 1
            if position < 0 or position >= len(clusters):
                raise ValueError("reconstructed fixed anchor falls outside cluster inventory")
            cluster = clusters[position]
            if not (
                cluster.start_timestamp <= anchor_timestamp <= cluster.end_timestamp
                and cluster.contains_direction(cause)
            ):
                raise ValueError("reconstructed fixed anchor does not match D-014 cluster")
            passage_index = int(labels.passage_index[row_index])
            if passage_index < 0:
                raise ValueError("positive reconstructed fixed anchor has no passage index")
            passages[cluster.cluster_id][cause].append(int(timestamps[passage_index]))
        attached: list[ClusterRecord] = []
        for cluster in clusters:
            up = tuple(passages[cluster.cluster_id][Cause.UP])
            down = tuple(passages[cluster.cluster_id][Cause.DOWN])
            if len(up) != cluster.up_count or len(down) != cluster.down_count:
                raise ValueError(
                    f"fixed cluster count mismatch for {cluster.cluster_id}: "
                    f"expected {cluster.up_count}/{cluster.down_count}, got "
                    f"{len(up)}/{len(down)}"
                )
            attached.append(
                replace(
                    cluster,
                    up_passage_timestamps=up,
                    down_passage_timestamps=down,
                )
            )
        result[horizon] = attached
    return result


def map_fixed_cluster(
    clusters: Sequence[ClusterRecord],
    *,
    anchor_timestamp: int,
    cause: Cause,
) -> ClusterRecord:
    """Map a positive hourly fixed outcome to its unique D-014 cluster."""

    starts = np.fromiter((cluster.start_timestamp for cluster in clusters), dtype=np.int64)
    position = int(np.searchsorted(starts, anchor_timestamp, side="right")) - 1
    candidates: list[ClusterRecord] = []
    for index in (position - 1, position, position + 1):
        if 0 <= index < len(clusters):
            cluster = clusters[index]
            if (
                cluster.start_timestamp <= anchor_timestamp <= cluster.end_timestamp
                and cluster.contains_direction(cause)
            ):
                candidates.append(cluster)
    unique = {cluster.cluster_id: cluster for cluster in candidates}
    if len(unique) != 1:
        raise ValueError(
            f"positive fixed anchor {anchor_timestamp}/{cause.value} maps to {len(unique)} clusters"
        )
    return next(iter(unique.values()))


def cluster_hourly_anchors(
    anchors: Sequence[tuple[int, int, Cause]],
    *,
    label_family: str,
    horizon_seconds: int,
) -> tuple[list[ClusterRecord], dict[tuple[int, Cause], ClusterRecord]]:
    """Cluster twin hourly anchors with D-014 chaining and retain membership."""

    if label_family != "twin":
        raise ValueError("hourly reconstruction is reserved for twin clusters")
    ordered = list(anchors)
    if ordered != sorted(ordered, key=lambda item: item[0]):
        raise ValueError("anchors must be ordered by decision timestamp")
    if any(cause not in POSITIVE_CAUSES for _, _, cause in ordered):
        raise ValueError("only positive anchors may be clustered")
    close_window = max(horizon_seconds, CLUSTER_CLOSE_SECONDS)
    groups: list[list[tuple[int, int, Cause]]] = []
    current: list[tuple[int, int, Cause]] = []
    current_max_passage = 0
    for anchor in ordered:
        timestamp, passage, _ = anchor
        if passage < timestamp:
            raise ValueError("passage cannot precede anchor")
        if current:
            gap = timestamp - current[-1][0]
            if gap > close_window and timestamp > current_max_passage:
                groups.append(current)
                current = []
                current_max_passage = 0
        current.append(anchor)
        current_max_passage = max(current_max_passage, passage)
    if current:
        groups.append(current)

    records: list[ClusterRecord] = []
    membership: dict[tuple[int, Cause], ClusterRecord] = {}
    for index, group in enumerate(groups):
        record = ClusterRecord(
            cluster_id=f"{label_family}:{horizon_seconds}:{index}",
            label_family=label_family,
            horizon_seconds=horizon_seconds,
            start_timestamp=group[0][0],
            end_timestamp=max(item[1] for item in group),
            up_count=sum(item[2] is Cause.UP for item in group),
            down_count=sum(item[2] is Cause.DOWN for item in group),
            up_passage_timestamps=tuple(
                passage for _, passage, cause in group if cause is Cause.UP
            ),
            down_passage_timestamps=tuple(
                passage for _, passage, cause in group if cause is Cause.DOWN
            ),
        )
        records.append(record)
        for timestamp, _, cause in group:
            key = (timestamp, cause)
            if key in membership:
                raise ValueError("duplicate hourly twin anchor")
            membership[key] = record
    return records, membership


def support_identifier(
    *,
    label_family: str,
    horizon_seconds: int,
    period: str,
    timestamps: Iterable[int],
) -> str:
    """Hash an ordered score support without serializing it into reports."""

    payload = {
        "label_family": label_family,
        "horizon_seconds": horizon_seconds,
        "period": period,
        "timestamps": [int(timestamp) for timestamp in timestamps],
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def build_population(
    *,
    end_timestamps: np.ndarray,
    close: np.ndarray,
    high: np.ndarray,
    low: np.ndarray,
    fixed_cluster_payload: dict[str, object],
    periods: Sequence[Period] = PERIODS,
    stage: str = "full",
) -> PopulationResult:
    """Build the frozen hourly M0 population without fitting or scoring.

    ``stage='development'`` is a hard effect firewall: no candidate, feature,
    or outcome at or after the development end is constructed.
    """

    if stage not in {"development", "full"}:
        raise ValueError("stage must be 'development' or 'full'")
    timestamps, close_values, high_values, low_values = _validate_index_arrays(
        end_timestamps, close, high, low
    )
    selected_periods = tuple(
        period for period in periods if stage == "full" or period.key == "development"
    )
    if not selected_periods or selected_periods[0].key != "development":
        raise ValueError("development period is required to lock kappa")
    stage_end = selected_periods[-1].end_timestamp
    if stage == "development":
        keep = timestamps < stage_end
        timestamps = timestamps[keep]
        close_values = close_values[keep]
        high_values = high_values[keep]
        low_values = low_values[keep]

    rows: list[M0RiskRow] = []
    for period in selected_periods:
        for timestamp in range(period.start_timestamp, period.end_timestamp, HOUR_SECONDS):
            now = exact_row(timestamps, timestamp)
            before = exact_row(timestamps, timestamp - 900)
            if now is None or before is None:
                rows.append(M0RiskRow(timestamp, period.key, BaseStatus.MISSING_PRECONDITION))
                continue
            impulse = float(abs(math.log(close_values[now] / close_values[before])))
            if not math.isfinite(impulse) or not impulse < IMPULSE_LIMIT:
                rows.append(
                    M0RiskRow(
                        timestamp,
                        period.key,
                        BaseStatus.IMPULSE_EXCLUDED,
                        impulse=impulse,
                    )
                )
                continue
            sigma, _ = causal_rv24h(timestamps, close_values, timestamp)
            if sigma is None:
                rows.append(
                    M0RiskRow(
                        timestamp,
                        period.key,
                        BaseStatus.MISSING_RV,
                        impulse=impulse,
                    )
                )
                continue
            features, feature_reasons = m0_features(
                timestamps, close_values, high_values, low_values, timestamp, sigma
            )
            rows.append(
                M0RiskRow(
                    timestamp,
                    period.key,
                    BaseStatus.ELIGIBLE,
                    sigma=sigma,
                    impulse=impulse,
                    features=features,
                    feature_missing_reasons=feature_reasons,
                )
            )

    dev_sigmas = np.asarray(
        [
            row.sigma
            for row in rows
            if row.period == "development"
            and row.base_status is BaseStatus.ELIGIBLE
            and row.sigma is not None
        ],
        dtype=np.float64,
    )
    if dev_sigmas.size == 0 or not bool(np.all(np.isfinite(dev_sigmas) & (dev_sigmas > 0.0))):
        raise ValueError("development sigma support is empty or invalid")
    kappa = round(float(FIXED_BARRIER / np.median(dev_sigmas)), 6)
    if not math.isfinite(kappa) or kappa <= 0.0:
        raise ValueError("locked kappa is invalid")

    for row in rows:
        if row.base_status is not BaseStatus.ELIGIBLE:
            continue
        assert row.sigma is not None
        twin_barrier = kappa * row.sigma
        if not math.isfinite(twin_barrier) or not 0.0 < twin_barrier < 1.0:
            row.exclusion_reasons = {horizon: ("INVALID_TWIN_BARRIER",) for horizon in HORIZONS}
            continue
        row.twin_barrier = twin_barrier
        for horizon in HORIZONS:
            row.outcomes[("fixed", horizon)] = first_cause(
                timestamps,
                close_values,
                high_values,
                low_values,
                timestamp=row.timestamp,
                horizon_seconds=horizon,
                barrier_fraction=FIXED_BARRIER,
            )
            row.outcomes[("twin", horizon)] = first_cause(
                timestamps,
                close_values,
                high_values,
                low_values,
                timestamp=row.timestamp,
                horizon_seconds=horizon,
                barrier_fraction=twin_barrier,
            )

    fixed_by_horizon = load_fixed_clusters(fixed_cluster_payload)
    if stage == "full":
        fixed_by_horizon = attach_fixed_passage_inventory(
            fixed_by_horizon=fixed_by_horizon,
            timestamps=timestamps,
            close=close_values,
            high=high_values,
            low=low_values,
        )
    all_clusters: list[ClusterRecord] = []
    all_clusters.extend(cluster for records in fixed_by_horizon.values() for cluster in records)
    cluster_lookup: dict[str, ClusterRecord] = {
        cluster.cluster_id: cluster for cluster in all_clusters
    }

    for horizon in HORIZONS:
        for row in rows:
            outcome = row.outcomes.get(("fixed", horizon))
            if outcome is None or outcome.cause not in POSITIVE_CAUSES:
                continue
            cluster = map_fixed_cluster(
                fixed_by_horizon[horizon],
                anchor_timestamp=row.timestamp,
                cause=outcome.cause,
            )
            row.cluster_ids[("fixed", horizon)] = cluster.cluster_id
            row.cluster_morphology[("fixed", horizon)] = cluster.morphology

        twin_anchors = []
        for row in rows:
            outcome = row.outcomes.get(("twin", horizon))
            if outcome is not None and outcome.cause in POSITIVE_CAUSES:
                assert outcome.passage_timestamp is not None
                twin_anchors.append((row.timestamp, outcome.passage_timestamp, outcome.cause))
        twin_clusters, membership = cluster_hourly_anchors(
            twin_anchors,
            label_family="twin",
            horizon_seconds=horizon,
        )
        all_clusters.extend(twin_clusters)
        cluster_lookup.update({cluster.cluster_id: cluster for cluster in twin_clusters})
        for row in rows:
            outcome = row.outcomes.get(("twin", horizon))
            if outcome is None or outcome.cause not in POSITIVE_CAUSES:
                continue
            cluster = membership[(row.timestamp, outcome.cause)]
            row.cluster_ids[("twin", horizon)] = cluster.cluster_id
            row.cluster_morphology[("twin", horizon)] = cluster.morphology

    for row in rows:
        period = next(period for period in selected_periods if period.key == row.period)
        for horizon in HORIZONS:
            reasons: list[str] = []
            if row.base_status is not BaseStatus.ELIGIBLE:
                reasons.append(row.base_status.value)
            if not period_horizon_eligible(row.timestamp, horizon, period):
                reasons.append("D023_PERIOD_OR_PURGE")
            if row.features is None:
                reasons.extend(row.feature_missing_reasons or ("M0_INCOMPLETE",))
            for label_family in LABEL_FAMILIES:
                outcome = row.outcomes.get((label_family, horizon))
                if outcome is None:
                    reasons.append(f"{label_family.upper()}_MISSING")
                    continue
                if outcome.cause not in SCOREABLE_CAUSES:
                    reasons.append(f"{label_family.upper()}_{outcome.cause.value}")
                if outcome.cause in POSITIVE_CAUSES:
                    cluster_id = row.cluster_ids.get((label_family, horizon))
                    if cluster_id is None:
                        reasons.append(f"{label_family.upper()}_CLUSTER_MISSING")
                    elif cluster_crosses_period(cluster_lookup[cluster_id], period):
                        reasons.append(f"{label_family.upper()}_CLUSTER_STRADDLE")
            row.exclusion_reasons[horizon] = tuple(dict.fromkeys(reasons))
            row.scoreable[horizon] = not reasons

    inventory: dict[str, object] = {
        "stage": stage,
        "candidate_rows": len(rows),
        "kappa_support_count": int(dev_sigmas.size),
        "kappa": kappa,
        "periods": {},
    }
    periods_inventory: dict[str, object] = {}
    for period in selected_periods:
        period_rows = [row for row in rows if row.period == period.key]
        base_counts = {
            status.value: sum(row.base_status is status for row in period_rows)
            for status in BaseStatus
        }
        horizon_counts: dict[str, object] = {}
        for horizon in HORIZONS:
            causes: dict[str, dict[str, int]] = {}
            for label_family in LABEL_FAMILIES:
                causes[label_family] = {
                    cause.value: sum(
                        row.outcomes.get((label_family, horizon), Outcome(Cause.CENSORED_GAP)).cause
                        is cause
                        for row in period_rows
                        if (label_family, horizon) in row.outcomes
                    )
                    for cause in Cause
                }
            exclusion_counts: dict[str, int] = {}
            for row in period_rows:
                for reason in row.exclusion_reasons.get(horizon, ()):
                    exclusion_counts[reason] = exclusion_counts.get(reason, 0) + 1
            horizon_counts[str(horizon)] = {
                "common_scoreable_rows": sum(
                    row.scoreable.get(horizon, False) for row in period_rows
                ),
                "outcomes": causes,
                "exclusions": dict(sorted(exclusion_counts.items())),
            }
        periods_inventory[period.key] = {
            "candidate_rows": len(period_rows),
            "base_status": base_counts,
            "horizons": horizon_counts,
        }
    inventory["periods"] = periods_inventory
    return PopulationResult(tuple(rows), tuple(all_clusters), kappa, inventory)
