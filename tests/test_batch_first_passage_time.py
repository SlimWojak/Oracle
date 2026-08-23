import unittest

import numpy as np

from oracle_research.batch_labels import (
    DIR_AMBIGUOUS,
    DIR_DOWN,
    DIR_INSUFFICIENT,
    DIR_NONE,
    DIR_UP,
    batch_first_passage,
    batch_first_passage_time,
)

BASE = 1_700_000_000


def series(n_bars: int, *, drop: set[int] | None = None):
    rows = [index for index in range(n_bars) if index not in (drop or set())]
    ts = np.asarray([BASE + 60 * index for index in rows], dtype=np.int64)
    close = np.full(len(rows), 100.0)
    high = np.full(len(rows), 100.5)
    low = np.full(len(rows), 99.5)
    return rows, ts, high, low, close


class AgreementOnCompleteGridTests(unittest.TestCase):
    def test_matches_bar_count_labeller_when_contiguous(self) -> None:
        rows, ts, high, low, close = series(50)
        high[20] = 103.0
        low[35] = 97.0
        time_labels = batch_first_passage_time(
            ts, high, low, close, horizon_seconds=300, threshold_fraction=0.02
        )
        bar_labels = batch_first_passage(
            high, low, close, horizon_bars=5, threshold_fraction=0.02
        )
        np.testing.assert_array_equal(time_labels.direction, bar_labels.direction)
        np.testing.assert_array_equal(time_labels.passage_index, bar_labels.passage_index)
        np.testing.assert_array_equal(time_labels.elapsed_bars, bar_labels.elapsed_bars)


class GapSemanticsTests(unittest.TestCase):
    def test_passage_found_across_gap_within_deadline(self) -> None:
        rows, ts, high, low, close = series(60, drop={16, 17, 18, 19})
        high[rows.index(20)] = 103.0
        labels = batch_first_passage_time(
            ts, high, low, close, horizon_seconds=300, threshold_fraction=0.02
        )
        anchor = rows.index(15)
        self.assertEqual(int(labels.direction[anchor]), int(DIR_UP))
        self.assertEqual(int(ts[labels.passage_index[anchor]]), BASE + 60 * 20)

    def test_deadline_not_stretched_by_gap(self) -> None:
        rows, ts, high, low, close = series(60, drop={16, 17, 18, 19})
        high[rows.index(20)] = 103.0
        labels = batch_first_passage_time(
            ts, high, low, close, horizon_seconds=240, threshold_fraction=0.02
        )
        anchor = rows.index(15)
        self.assertEqual(int(labels.direction[anchor]), int(DIR_NONE))

    def test_tail_is_insufficient_even_with_visible_hit(self) -> None:
        rows, ts, high, low, close = series(20)
        high[19] = 103.0
        labels = batch_first_passage_time(
            ts, high, low, close, horizon_seconds=600, threshold_fraction=0.02
        )
        # Bar 18 sees the hit at 19 but its 10-minute window is truncated.
        self.assertEqual(int(labels.direction[18]), int(DIR_INSUFFICIENT))

    def test_same_bar_tie_is_ambiguous(self) -> None:
        rows, ts, high, low, close = series(20)
        high[10] = 103.0
        low[10] = 97.0
        labels = batch_first_passage_time(
            ts, high, low, close, horizon_seconds=300, threshold_fraction=0.02
        )
        self.assertEqual(int(labels.direction[9]), int(DIR_AMBIGUOUS))

    def test_down_passage(self) -> None:
        rows, ts, high, low, close = series(20)
        low[10] = 97.0
        labels = batch_first_passage_time(
            ts, high, low, close, horizon_seconds=300, threshold_fraction=0.02
        )
        self.assertEqual(int(labels.direction[9]), int(DIR_DOWN))

    def test_off_grid_timestamps_raise(self) -> None:
        ts = np.asarray([BASE, BASE + 60, BASE + 90], dtype=np.int64)
        flat = np.full(3, 100.0)
        with self.assertRaises(ValueError):
            batch_first_passage_time(
                ts, flat, flat, flat, horizon_seconds=300, threshold_fraction=0.02
            )


if __name__ == "__main__":
    unittest.main()
