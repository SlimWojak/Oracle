"""Event clustering of positive first-passage anchors per decision D-014.

Two positive anchors belong to one cluster when their decision timestamps are
within the closure window of each other or their passage windows overlap. The
closure window is the maximum of the label horizon and four hours, so clusters
close only after a full 4h stretch without a positive anchor. Direction is
recorded per anchor; clusters containing both directions are marked mixed.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from oracle_research.labels import Direction

CLUSTER_CLOSE_SECONDS = 14_400


@dataclass(frozen=True, slots=True)
class PositiveAnchor:
    """A positive first-passage label reduced to what clustering needs."""

    anchor_timestamp: int
    passage_timestamp: int
    direction: Direction

    def __post_init__(self) -> None:
        if self.direction not in (Direction.UP, Direction.DOWN):
            raise ValueError("cluster anchors must have a directional passage")
        if self.passage_timestamp < self.anchor_timestamp:
            raise ValueError("passage cannot precede its anchor")


@dataclass(frozen=True, slots=True)
class EventCluster:
    """A maximal chain of positive anchors representing one market move."""

    start_timestamp: int
    end_timestamp: int
    anchor_count: int
    up_count: int
    down_count: int

    @property
    def mixed(self) -> bool:
        return self.up_count > 0 and self.down_count > 0

    @property
    def direction(self) -> Direction:
        if self.mixed:
            raise ValueError("mixed cluster has no single direction")
        return Direction.UP if self.up_count > 0 else Direction.DOWN


def cluster_positive_anchors(
    anchors: Sequence[PositiveAnchor],
    *,
    horizon_seconds: int,
) -> list[EventCluster]:
    """Group time-ordered positive anchors into independent event clusters.

    Consecutive anchors chain when their decision timestamps are within
    ``max(horizon_seconds, CLUSTER_CLOSE_SECONDS)`` or the later anchor's
    decision time falls inside the earlier anchor's passage window. Chaining
    is transitive; the cluster end extends to the latest passage timestamp.
    """

    if horizon_seconds <= 0:
        raise ValueError("horizon_seconds must be positive")
    timestamps = [anchor.anchor_timestamp for anchor in anchors]
    if timestamps != sorted(timestamps):
        raise ValueError("anchors must be ordered by anchor_timestamp")

    close_window = max(horizon_seconds, CLUSTER_CLOSE_SECONDS)
    clusters: list[EventCluster] = []
    current: list[PositiveAnchor] = []
    current_max_passage = 0

    def flush() -> None:
        if not current:
            return
        clusters.append(
            EventCluster(
                start_timestamp=current[0].anchor_timestamp,
                end_timestamp=max(a.passage_timestamp for a in current),
                anchor_count=len(current),
                up_count=sum(1 for a in current if a.direction is Direction.UP),
                down_count=sum(1 for a in current if a.direction is Direction.DOWN),
            )
        )

    for anchor in anchors:
        if current:
            gap = anchor.anchor_timestamp - current[-1].anchor_timestamp
            chained = gap <= close_window or anchor.anchor_timestamp <= current_max_passage
            if not chained:
                flush()
                current = []
                current_max_passage = 0
        current.append(anchor)
        current_max_passage = max(current_max_passage, anchor.passage_timestamp)
    flush()
    return clusters
