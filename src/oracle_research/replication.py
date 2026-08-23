"""Venue-replication check for labelled event clusters per decision D-021.

Each Binance-labelled cluster is re-checked against a second venue's 1m bars
using the identical first-passage code on that venue's own price series.
Verdict precedence follows the frozen decision text: ``pending_bars`` (check
window extends beyond the venue's bar history), then ``kraken_sparse``
(coverage below the floor; excluded from the disagreement denominator), then
``replicated`` / ``venue_disputed``. Sparse clusters additionally record
whether a matching anchor existed anyway.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from oracle_research.batch_labels import DIR_DOWN, DIR_UP, batch_first_passage
from oracle_research.binance_klines import KlineArrays, contiguous_segments

STEP_SECONDS = 60

VERDICT_REPLICATED = "replicated"
VERDICT_DISPUTED = "venue_disputed"
VERDICT_SPARSE = "kraken_sparse"
VERDICT_PENDING = "pending_bars"

_ALLOWED_CODES = {
    "up": (int(DIR_UP),),
    "down": (int(DIR_DOWN),),
    "mixed": (int(DIR_UP), int(DIR_DOWN)),
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
    """Label every contiguous venue segment; return positive anchors at bar close."""

    anchor_ts: list[np.ndarray] = []
    codes: list[np.ndarray] = []
    for start, end in contiguous_segments(klines.timestamp, step_seconds=STEP_SECONDS):
        labels = batch_first_passage(
            klines.high,
            klines.low,
            klines.close,
            horizon_bars=horizon_bars,
            threshold_fraction=threshold_fraction,
            segment=(start, end),
        )
        positive = np.nonzero((labels.direction == DIR_UP) | (labels.direction == DIR_DOWN))[0]
        if positive.size == 0:
            continue
        anchor_ts.append(klines.timestamp[start + positive] + STEP_SECONDS)
        codes.append(labels.direction[positive])
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
