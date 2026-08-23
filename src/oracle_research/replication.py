"""Venue-replication check for labelled event clusters per decision D-021.

Each Binance-labelled cluster is re-checked against a second venue's 1m bars
using the same first-passage semantics (threshold, wall-clock horizon,
interval-end decision timestamps) on that venue's own price series. The venue
labeller is time-aware rather than bar-count-based: the replication venue
omits no-trade minutes structurally, so a fixed bar-count window is undefined
across gaps and a segment-restricted labeller under-detects passages in
gap-dense years (D-021 correction note).

Verdict precedence follows the frozen decision text: ``pending_bars`` (check
window extends beyond the venue's bar history), then ``kraken_sparse``
(coverage below the floor; excluded from the disagreement denominator), then
``replicated`` / ``venue_disputed``. Sparse clusters additionally record
whether a matching anchor existed anyway.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from numpy.lib.stride_tricks import sliding_window_view

from oracle_research.batch_labels import DIR_AMBIGUOUS, DIR_DOWN, DIR_UP
from oracle_research.binance_klines import KlineArrays

STEP_SECONDS = 60
CHUNK_SIZE = 65_536

VERDICT_REPLICATED = "replicated"
VERDICT_DISPUTED = "venue_disputed"
VERDICT_SPARSE = "kraken_sparse"
VERDICT_PENDING = "pending_bars"

# An ambiguous venue anchor crossed both barriers, so it supports any direction.
_ALLOWED_CODES = {
    "up": (int(DIR_UP), int(DIR_AMBIGUOUS)),
    "down": (int(DIR_DOWN), int(DIR_AMBIGUOUS)),
    "mixed": (int(DIR_UP), int(DIR_DOWN), int(DIR_AMBIGUOUS)),
}


@dataclass(frozen=True, slots=True)
class VenueAnchors:
    """Positive first-passage anchors on the replication venue, time-sorted."""

    anchor_timestamp: np.ndarray
    direction: np.ndarray

    def __post_init__(self) -> None:
        if self.anchor_timestamp.shape != self.direction.shape:
            raise ValueError("anchor arrays must have equal length")
        if self.anchor_timestamp.size > 1 and not bool(
            np.all(np.diff(self.anchor_timestamp) > 0)
        ):
            raise ValueError("anchor timestamps must be strictly increasing")


@dataclass(frozen=True, slots=True)
class ReplicationCheck:
    """Per-cluster replication outcome."""

    start_timestamp: int
    end_timestamp: int
    direction: str
    verdict: str
    coverage: float
    matching_anchors: int


def venue_positive_anchors(
    klines: KlineArrays,
    *,
    horizon_bars: int,
    threshold_fraction: float,
) -> VenueAnchors:
    """Time-aware first passage over gappy venue bars; anchors at bar close.

    Every bar is an anchor. Its passage window is the wall-clock span
    ``(ts, ts + horizon_bars * 60]`` evaluated over whatever bars exist there;
    absent minutes contribute no evidence. Because consecutive bars are at
    least 60s apart, at most ``horizon_bars`` bars can fall in the window, so
    a fixed-width bar window with a per-element time mask is exact.
    """

    n_rows = klines.n_rows
    horizon_seconds = horizon_bars * STEP_SECONDS
    pad_ts = np.full(horizon_bars, np.iinfo(np.int64).max, dtype=np.int64)
    pad_price = np.full(horizon_bars, np.nan)
    ts_padded = np.concatenate([klines.timestamp, pad_ts])
    high_padded = np.concatenate([klines.high, pad_price])
    low_padded = np.concatenate([klines.low, pad_price])

    ts_windows = sliding_window_view(ts_padded[1:], horizon_bars)
    high_windows = sliding_window_view(high_padded[1:], horizon_bars)
    low_windows = sliding_window_view(low_padded[1:], horizon_bars)

    anchor_ts: list[np.ndarray] = []
    codes: list[np.ndarray] = []
    upper_scale = 1.0 + threshold_fraction
    lower_scale = 1.0 - threshold_fraction
    for chunk0 in range(0, n_rows, CHUNK_SIZE):
        chunk1 = min(chunk0 + CHUNK_SIZE, n_rows)
        chunk = slice(chunk0, chunk1)
        deadline = (klines.timestamp[chunk] + horizon_seconds)[:, np.newaxis]
        in_window = ts_windows[chunk] <= deadline
        with np.errstate(invalid="ignore"):
            hit_up = (high_windows[chunk] >= (klines.close[chunk] * upper_scale)[:, np.newaxis])
            hit_down = (low_windows[chunk] <= (klines.close[chunk] * lower_scale)[:, np.newaxis])
        hit_up &= in_window
        hit_down &= in_window
        any_up = hit_up.any(axis=1)
        any_down = hit_down.any(axis=1)
        positive = np.nonzero(any_up | any_down)[0]
        if positive.size == 0:
            continue
        first_up = hit_up[positive].argmax(axis=1)
        first_down = hit_down[positive].argmax(axis=1)
        pos_up = any_up[positive]
        pos_down = any_down[positive]
        direction = np.where(pos_up & ~pos_down, DIR_UP, DIR_DOWN).astype(np.int8)
        both = pos_up & pos_down
        direction[both & (first_up < first_down)] = DIR_UP
        direction[both & (first_down < first_up)] = DIR_DOWN
        direction[both & (first_up == first_down)] = DIR_AMBIGUOUS
        anchor_ts.append(klines.timestamp[chunk0 + positive] + STEP_SECONDS)
        codes.append(direction)
    if not anchor_ts:
        empty_ts = np.empty(0, dtype=np.int64)
        return VenueAnchors(anchor_timestamp=empty_ts, direction=np.empty(0, dtype=np.int8))
    return VenueAnchors(
        anchor_timestamp=np.concatenate(anchor_ts),
        direction=np.concatenate(codes),
    )


def _matching_anchor_count(
    anchors: VenueAnchors,
    *,
    window_lo: int,
    window_hi: int,
    allowed_codes: tuple[int, ...],
) -> int:
    lo = int(np.searchsorted(anchors.anchor_timestamp, window_lo, side="left"))
    hi = int(np.searchsorted(anchors.anchor_timestamp, window_hi, side="right"))
    if hi <= lo:
        return 0
    window = anchors.direction[lo:hi]
    return int(sum(int(np.count_nonzero(window == code)) for code in allowed_codes))


def check_cluster(
    cluster: dict[str, object],
    *,
    anchors: VenueAnchors,
    decision_timestamps: np.ndarray,
    horizon_bars: int,
    coverage_floor: float,
    last_decision_timestamp: int,
) -> ReplicationCheck:
    """Apply the D-021 rules to one cluster record from the committed inventory."""

    start = int(cluster["start_timestamp"])
    end = int(cluster["end_timestamp"])
    direction = str(cluster["direction"])
    horizon_seconds = horizon_bars * STEP_SECONDS

    match_lo = start - horizon_seconds
    match_hi = end
    coverage_lo = start - horizon_seconds
    coverage_hi = end + horizon_seconds

    expected = (coverage_hi - coverage_lo) // STEP_SECONDS + 1
    lo = int(np.searchsorted(decision_timestamps, coverage_lo, side="left"))
    hi = int(np.searchsorted(decision_timestamps, coverage_hi, side="right"))
    coverage = (hi - lo) / expected if expected > 0 else 0.0

    matches = _matching_anchor_count(
        anchors,
        window_lo=match_lo,
        window_hi=match_hi,
        allowed_codes=_ALLOWED_CODES[direction],
    )

    if coverage_hi > last_decision_timestamp:
        verdict = VERDICT_PENDING
    elif coverage < coverage_floor:
        verdict = VERDICT_SPARSE
    elif matches > 0:
        verdict = VERDICT_REPLICATED
    else:
        verdict = VERDICT_DISPUTED
    return ReplicationCheck(
        start_timestamp=start,
        end_timestamp=end,
        direction=direction,
        verdict=verdict,
        coverage=float(coverage),
        matching_anchors=matches,
    )


def check_clusters(
    klines: KlineArrays,
    clusters: list[dict[str, object]],
    *,
    horizon_bars: int,
    threshold_fraction: float,
    coverage_floor: float = 0.9,
) -> list[ReplicationCheck]:
    """Run the D-021 check for every cluster record against the venue bars."""

    anchors = venue_positive_anchors(
        klines,
        horizon_bars=horizon_bars,
        threshold_fraction=threshold_fraction,
    )
    decision_timestamps = klines.timestamp + STEP_SECONDS
    last_decision = int(decision_timestamps[-1])
    return [
        check_cluster(
            cluster,
            anchors=anchors,
            decision_timestamps=decision_timestamps,
            horizon_bars=horizon_bars,
            coverage_floor=coverage_floor,
            last_decision_timestamp=last_decision,
        )
        for cluster in clusters
    ]
