import unittest

import numpy as np

from oracle_research.binance_klines import KlineArrays
from oracle_research.consolidated_index import build_median_index

BASE = 1_700_000_000


def venue(rows: dict[int, float], *, spread: float = 0.5) -> KlineArrays:
    indices = sorted(rows)
    ts = np.asarray([BASE + 60 * index for index in indices], dtype=np.int64)
    close = np.asarray([rows[index] for index in indices], dtype=np.float64)
    return KlineArrays(
        timestamp=ts,
        open=close.copy(),
        high=close + spread,
        low=close - spread,
        close=close.copy(),
        volume=np.ones(len(indices)),
        n_rows=len(indices),
    )


class BuildMedianIndexTests(unittest.TestCase):
    def test_three_member_median(self) -> None:
        members = [
            venue({0: 100.0, 1: 100.0}),
            venue({0: 101.0, 1: 103.0}),
            venue({0: 102.0, 1: 101.0}),
        ]
        index = build_median_index(members)
        self.assertEqual(index.klines.n_rows, 2)
        self.assertEqual(float(index.klines.close[0]), 101.0)
        self.assertEqual(float(index.klines.close[1]), 101.0)
        self.assertEqual(index.venue_count.tolist(), [3, 3])
        self.assertEqual(float(index.klines.volume[0]), 3.0)

    def test_two_member_minute_is_midpoint_and_flagged(self) -> None:
        members = [
            venue({0: 100.0, 1: 100.0}),
            venue({0: 102.0}),  # absent at minute 1
            venue({0: 104.0, 1: 106.0}),
        ]
        index = build_median_index(members)
        self.assertEqual(index.klines.n_rows, 2)
        self.assertEqual(float(index.klines.close[0]), 102.0)
        self.assertEqual(float(index.klines.close[1]), 103.0)
        self.assertEqual(index.venue_count.tolist(), [3, 2])

    def test_single_member_minute_is_excluded(self) -> None:
        members = [
            venue({0: 100.0, 2: 100.0}),
            venue({0: 101.0}),
            venue({0: 102.0}),
        ]
        index = build_median_index(members)
        self.assertEqual(index.klines.n_rows, 1)
        self.assertEqual(int(index.klines.timestamp[0]), BASE)

    def test_no_forward_fill(self) -> None:
        # Venue 2's minute-1 absence must not be filled from its minute 0.
        members = [
            venue({0: 100.0, 1: 200.0}),
            venue({0: 100.0, 1: 200.0}),
            venue({0: 100.0}),
        ]
        index = build_median_index(members)
        self.assertEqual(float(index.klines.close[1]), 200.0)

    def test_high_low_ordering_preserved(self) -> None:
        members = [
            venue({0: 100.0}, spread=0.1),
            venue({0: 105.0}, spread=2.0),
            venue({0: 95.0}, spread=1.0),
        ]
        index = build_median_index(members)
        self.assertLessEqual(float(index.klines.low[0]), float(index.klines.high[0]))


if __name__ == "__main__":
    unittest.main()
