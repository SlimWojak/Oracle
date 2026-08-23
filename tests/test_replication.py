import unittest

import numpy as np

from oracle_research.binance_klines import KlineArrays
from oracle_research.replication import (
    VERDICT_DISPUTED,
    VERDICT_PENDING,
    VERDICT_REPLICATED,
    VERDICT_SPARSE,
    check_clusters,
    venue_positive_anchors,
)

BASE = 1_700_000_000
HORIZON = 5
THRESHOLD = 0.02


def make_klines(
    n_bars: int,
    *,
    spike_up_at: int | None = None,
    drop_indices: set[int] | None = None,
) -> KlineArrays:
    drop = drop_indices or set()
    rows = [index for index in range(n_bars) if index not in drop]
    timestamps = np.asarray([BASE + 60 * index for index in rows], dtype=np.int64)
    close = np.full(len(rows), 100.0)
    high = np.full(len(rows), 100.5)
    low = np.full(len(rows), 99.5)
    if spike_up_at is not None and spike_up_at in rows:
        high[rows.index(spike_up_at)] = 103.0
    return KlineArrays(
        timestamp=timestamps,
        open=close.copy(),
        high=high,
        low=low,
        close=close.copy(),
        volume=np.zeros(len(rows)),
        n_rows=len(rows),
    )


def cluster(start_index: int, end_index: int, direction: str) -> dict[str, object]:
    return {
        "start_timestamp": BASE + 60 * start_index + 60,
        "end_timestamp": BASE + 60 * end_index + 60,
        "direction": direction,
    }


class VenueAnchorTests(unittest.TestCase):
    def test_up_spike_produces_up_anchors_at_bar_close(self) -> None:
        klines = make_klines(200, spike_up_at=50)
        anchors = venue_positive_anchors(
            klines, horizon_bars=HORIZON, threshold_fraction=THRESHOLD
        )
        # Bars 45..49 see the spike within 5 bars.
        self.assertEqual(anchors.anchor_timestamp.size, HORIZON)
        self.assertEqual(int(anchors.anchor_timestamp[0]), BASE + 60 * 45 + 60)

    def test_flat_series_has_no_anchors(self) -> None:
        klines = make_klines(100)
        anchors = venue_positive_anchors(
            klines, horizon_bars=HORIZON, threshold_fraction=THRESHOLD
        )
        self.assertEqual(anchors.anchor_timestamp.size, 0)


class CheckClustersTests(unittest.TestCase):
    def test_replicated_when_matching_anchor_in_window(self) -> None:
        klines = make_klines(200, spike_up_at=50)
        checks = check_clusters(
            klines,
            [cluster(46, 50, "up")],
            horizon_bars=HORIZON,
            threshold_fraction=THRESHOLD,
        )
        self.assertEqual(checks[0].verdict, VERDICT_REPLICATED)
        self.assertGreater(checks[0].matching_anchors, 0)

    def test_mixed_cluster_matches_either_direction(self) -> None:
        klines = make_klines(200, spike_up_at=50)
        checks = check_clusters(
            klines,
            [cluster(46, 50, "mixed")],
            horizon_bars=HORIZON,
            threshold_fraction=THRESHOLD,
        )
        self.assertEqual(checks[0].verdict, VERDICT_REPLICATED)

    def test_direction_mismatch_is_disputed(self) -> None:
        klines = make_klines(200, spike_up_at=50)
        checks = check_clusters(
            klines,
            [cluster(46, 50, "down")],
            horizon_bars=HORIZON,
            threshold_fraction=THRESHOLD,
        )
        self.assertEqual(checks[0].verdict, VERDICT_DISPUTED)

    def test_flat_venue_with_full_coverage_is_disputed(self) -> None:
        klines = make_klines(200)
        checks = check_clusters(
            klines,
            [cluster(50, 55, "up")],
            horizon_bars=HORIZON,
            threshold_fraction=THRESHOLD,
        )
        self.assertEqual(checks[0].verdict, VERDICT_DISPUTED)
        self.assertEqual(checks[0].coverage, 1.0)

    def test_sparse_coverage_flags_kraken_sparse(self) -> None:
        # Remove most bars around the cluster window.
        klines = make_klines(200, drop_indices=set(range(45, 58)))
        checks = check_clusters(
            klines,
            [cluster(50, 55, "up")],
            horizon_bars=HORIZON,
            threshold_fraction=THRESHOLD,
        )
        self.assertEqual(checks[0].verdict, VERDICT_SPARSE)
        self.assertLess(checks[0].coverage, 0.9)

    def test_window_beyond_bar_history_is_pending(self) -> None:
        klines = make_klines(60)
        checks = check_clusters(
            klines,
            [cluster(56, 58, "up")],
            horizon_bars=HORIZON,
            threshold_fraction=THRESHOLD,
        )
        self.assertEqual(checks[0].verdict, VERDICT_PENDING)


if __name__ == "__main__":
    unittest.main()
