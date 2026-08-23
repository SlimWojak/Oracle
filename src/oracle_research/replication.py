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

from oracle_research.batch_labels import (
    DIR_AMBIGUOUS,
    DIR_DOWN,
    DIR_UP,
    batch_first_passage_time,
)
from oracle_research.binance_klines import KlineArrays

STEP_SECONDS = 60

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

    Thin wrapper over :func:`batch_first_passage_time`. Anchors whose window
    extends beyond the venue's bar history are insufficient there and yield
    no anchor; the cluster-level ``pending_bars`` verdict covers that edge.
    """

    labels = batch_first_passage_time(
        klines.timestamp,
        klines.high,
        klines.low,
        klines.close,
        horizon_seconds=horizon_bars * STEP_SECONDS,
        threshold_fraction=threshold_fraction,
        step_seconds=STEP_SECONDS,
    )
    positive = np.nonzero(
        (labels.direction == DIR_UP)
        | (labels.direction == DIR_DOWN)
        | (labels.direction == DIR_AMBIGUOUS)
    )[0]
    return VenueAnchors(
        anchor_timestamp=klines.timestamp[positive] + STEP_SECONDS,
        direction=labels.direction[positive],
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
