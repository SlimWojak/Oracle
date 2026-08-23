"""Tests for D-014 event clustering semantics."""

from __future__ import annotations

import unittest

from oracle_research.clusters import (
    CLUSTER_CLOSE_SECONDS,
    EventCluster,
    PositiveAnchor,
    cluster_positive_anchors,
)
from oracle_research.labels import Direction


def anchor(ts: int, passage: int, direction: Direction = Direction.DOWN) -> PositiveAnchor:
    return PositiveAnchor(anchor_timestamp=ts, passage_timestamp=passage, direction=direction)


class ClusterTests(unittest.TestCase):
    def test_empty_input(self) -> None:
        self.assertEqual(cluster_positive_anchors([], horizon_seconds=3600), [])

    def test_single_anchor(self) -> None:
        clusters = cluster_positive_anchors([anchor(100, 200)], horizon_seconds=3600)
        self.assertEqual(len(clusters), 1)
        self.assertEqual(clusters[0].start_timestamp, 100)
        self.assertEqual(clusters[0].end_timestamp, 200)
        self.assertEqual(clusters[0].anchor_count, 1)

    def test_anchors_within_close_window_chain(self) -> None:
        second_ts = CLUSTER_CLOSE_SECONDS  # gap exactly equal to the window chains
        clusters = cluster_positive_anchors(
            [anchor(0, 60), anchor(second_ts, second_ts + 60)],
            horizon_seconds=3600,
        )
        self.assertEqual(len(clusters), 1)
        self.assertEqual(clusters[0].anchor_count, 2)

    def test_anchors_beyond_close_window_split(self) -> None:
        second_ts = CLUSTER_CLOSE_SECONDS + 1
        clusters = cluster_positive_anchors(
            [anchor(0, 60), anchor(second_ts, second_ts + 60)],
            horizon_seconds=3600,
        )
        self.assertEqual(len(clusters), 2)

    def test_four_hour_closure_dominates_short_horizon(self) -> None:
        # 1h horizon still uses the 4h closure window per D-014.
        clusters = cluster_positive_anchors(
            [anchor(0, 60), anchor(10_000, 10_060)],
            horizon_seconds=3600,
        )
        self.assertEqual(len(clusters), 1)

    def test_passage_overlap_chains(self) -> None:
        # Second anchor starts inside the first anchor's passage window.
        clusters = cluster_positive_anchors(
            [anchor(0, 20_000), anchor(15_000, 15_060)],
            horizon_seconds=3600,
        )
        self.assertEqual(len(clusters), 1)
        self.assertEqual(clusters[0].end_timestamp, 20_000)

    def test_transitive_chaining(self) -> None:
        step = CLUSTER_CLOSE_SECONDS
        anchors = [anchor(i * step, i * step + 60) for i in range(5)]
        clusters = cluster_positive_anchors(anchors, horizon_seconds=3600)
        self.assertEqual(len(clusters), 1)
        self.assertEqual(clusters[0].anchor_count, 5)

    def test_mixed_direction_flag(self) -> None:
        clusters = cluster_positive_anchors(
            [anchor(0, 60, Direction.DOWN), anchor(100, 160, Direction.UP)],
            horizon_seconds=3600,
        )
        self.assertEqual(len(clusters), 1)
        self.assertTrue(clusters[0].mixed)
        with self.assertRaises(ValueError):
            _ = clusters[0].direction

    def test_pure_cluster_direction(self) -> None:
        cluster = EventCluster(
            start_timestamp=0,
            end_timestamp=60,
            anchor_count=1,
            up_count=0,
            down_count=1,
        )
        self.assertIs(cluster.direction, Direction.DOWN)
        self.assertFalse(cluster.mixed)

    def test_unordered_anchors_rejected(self) -> None:
        with self.assertRaises(ValueError):
            cluster_positive_anchors(
                [anchor(100, 160), anchor(0, 60)],
                horizon_seconds=3600,
            )

    def test_non_directional_anchor_rejected(self) -> None:
        with self.assertRaises(ValueError):
            anchor(0, 60, Direction.NONE)

    def test_passage_before_anchor_rejected(self) -> None:
        with self.assertRaises(ValueError):
            anchor(100, 50)

    def test_invalid_horizon_rejected(self) -> None:
        with self.assertRaises(ValueError):
            cluster_positive_anchors([], horizon_seconds=0)


if __name__ == "__main__":
    unittest.main()
