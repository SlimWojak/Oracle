from __future__ import annotations

import math
import unittest

import numpy as np

from oracle_research.batch_labels import (
    DIR_AMBIGUOUS,
    DIR_DOWN,
    DIR_INSUFFICIENT,
    DIR_NONE,
    DIR_UP,
    batch_first_passage,
)
from oracle_research.labels import Bar, Direction, first_passage

_DIRECTION_TO_CODE = {
    Direction.NONE: int(DIR_NONE),
    Direction.UP: int(DIR_UP),
    Direction.DOWN: int(DIR_DOWN),
    Direction.AMBIGUOUS: int(DIR_AMBIGUOUS),
}


def _random_ohlc(seed: int) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    rng = np.random.default_rng(seed)
    n_bars = int(rng.integers(500, 2001))
    shocks = rng.normal(0.0, 0.0015, size=n_bars - 1)
    close = np.empty(n_bars, dtype=np.float64)
    close[0] = 100.0
    close[1:] = 100.0 * np.exp(np.cumsum(shocks))
    close = np.maximum(close, 1.0)
    open_ = np.empty(n_bars, dtype=np.float64)
    open_[0] = close[0]
    open_[1:] = close[:-1]
    span = np.maximum(open_, close)
    trough = np.minimum(open_, close)
    high = span * (1.0 + rng.uniform(0.0, 0.004, size=n_bars))
    low = trough * (1.0 - rng.uniform(0.0, 0.004, size=n_bars))
    return open_, high, low, close


def _bars_from_ohlc(
    high: np.ndarray,
    low: np.ndarray,
    close: np.ndarray,
) -> list[Bar]:
    return [
        Bar(
            timestamp=int(index) * 60,
            high=float(high[index]),
            low=float(low[index]),
            close=float(close[index]),
        )
        for index in range(close.size)
    ]


class BatchFirstPassageUnitTests(unittest.TestCase):
    def test_same_bar_double_touch_is_ambiguous(self) -> None:
        high = np.asarray([100.0, 103.0], dtype=np.float64)
        low = np.asarray([100.0, 97.0], dtype=np.float64)
        close = np.asarray([100.0, 101.0], dtype=np.float64)

        labels = batch_first_passage(
            high,
            low,
            close,
            horizon_bars=1,
            threshold_fraction=0.02,
        )

        self.assertEqual(int(labels.direction[0]), int(DIR_AMBIGUOUS))
        self.assertEqual(int(labels.passage_index[0]), 1)
        self.assertEqual(int(labels.elapsed_bars[0]), 1)
        self.assertEqual(int(labels.direction[1]), int(DIR_INSUFFICIENT))
        self.assertEqual(int(labels.passage_index[1]), -1)
        self.assertEqual(int(labels.elapsed_bars[1]), -1)

    def test_insufficient_horizon_is_not_none(self) -> None:
        n_bars = 10
        horizon = 4
        close = np.full(n_bars, 100.0, dtype=np.float64)
        high = close.copy()
        low = close.copy()

        labels = batch_first_passage(
            high,
            low,
            close,
            horizon_bars=horizon,
            threshold_fraction=0.02,
        )

        n_valid = n_bars - horizon
        self.assertTrue(np.all(labels.direction[:n_valid] == DIR_NONE))
        self.assertTrue(np.all(labels.direction[n_valid:] == DIR_INSUFFICIENT))
        self.assertTrue(np.all(labels.passage_index[n_valid:] == -1))
        self.assertTrue(np.all(labels.elapsed_bars[n_valid:] == -1))

    def test_segment_end_truncation_ignores_later_bars(self) -> None:
        close = np.asarray([100.0, 100.0, 100.0, 100.0, 103.0], dtype=np.float64)
        high = close.copy()
        low = close.copy()

        labels = batch_first_passage(
            high,
            low,
            close,
            horizon_bars=2,
            threshold_fraction=0.02,
            segment=(0, 3),
        )

        self.assertEqual(labels.direction.size, 3)
        self.assertEqual(int(labels.direction[0]), int(DIR_NONE))
        self.assertEqual(int(labels.direction[1]), int(DIR_INSUFFICIENT))
        self.assertEqual(int(labels.direction[2]), int(DIR_INSUFFICIENT))

    def test_anchor_bar_is_excluded(self) -> None:
        high = np.asarray([103.0, 100.0], dtype=np.float64)
        low = np.asarray([97.0, 100.0], dtype=np.float64)
        close = np.asarray([100.0, 100.0], dtype=np.float64)

        labels = batch_first_passage(
            high,
            low,
            close,
            horizon_bars=1,
            threshold_fraction=0.02,
        )

        self.assertEqual(int(labels.direction[0]), int(DIR_NONE))

    def test_up_and_down_first_hit(self) -> None:
        high = np.asarray([100.0, 101.0, 102.1], dtype=np.float64)
        low = np.asarray([100.0, 99.0, 99.0], dtype=np.float64)
        close = np.asarray([100.0, 101.0, 102.1], dtype=np.float64)
        labels = batch_first_passage(
            high,
            low,
            close,
            horizon_bars=2,
            threshold_fraction=0.02,
        )
        self.assertEqual(int(labels.direction[0]), int(DIR_UP))
        self.assertEqual(int(labels.passage_index[0]), 2)
        self.assertEqual(int(labels.elapsed_bars[0]), 2)

        high = np.asarray([100.0, 99.0, 99.0], dtype=np.float64)
        low = np.asarray([100.0, 99.0, 97.9], dtype=np.float64)
        close = np.asarray([100.0, 99.0, 97.9], dtype=np.float64)
        labels = batch_first_passage(
            high,
            low,
            close,
            horizon_bars=2,
            threshold_fraction=0.02,
        )
        self.assertEqual(int(labels.direction[0]), int(DIR_DOWN))
        self.assertEqual(int(labels.passage_index[0]), 2)

    def test_invalid_threshold_rejected(self) -> None:
        close = np.asarray([100.0, 100.0], dtype=np.float64)
        for threshold in (0, -0.01, 1, math.nan):
            with self.subTest(threshold=threshold), self.assertRaises(ValueError):
                batch_first_passage(
                    close,
                    close,
                    close,
                    horizon_bars=1,
                    threshold_fraction=threshold,
                )


class BatchFirstPassagePropertyTests(unittest.TestCase):
    def test_matches_scalar_first_passage(self) -> None:
        seeds = (0, 1, 2, 3, 4)
        thresholds = (0.005, 0.02)
        horizons = (5, 60)
        for seed in seeds:
            for threshold in thresholds:
                for horizon in horizons:
                    with self.subTest(seed=seed, threshold=threshold, horizon=horizon):
                        self._assert_matches(seed, threshold, horizon)

    def _assert_matches(self, seed: int, threshold: float, horizon: int) -> None:
        _, high, low, close = _random_ohlc(seed)
        labels = batch_first_passage(
            high,
            low,
            close,
            horizon_bars=horizon,
            threshold_fraction=threshold,
        )
        bars = _bars_from_ohlc(high, low, close)
        n_valid = close.size - horizon
        self.assertGreater(n_valid, 0)
        self.assertTrue(np.all(labels.direction[n_valid:] == DIR_INSUFFICIENT))
        for anchor_index in range(n_valid):
            expected = first_passage(
                bars,
                anchor_index=anchor_index,
                horizon_bars=horizon,
                threshold_fraction=threshold,
            )
            self.assertEqual(
                int(labels.direction[anchor_index]),
                _DIRECTION_TO_CODE[expected.direction],
            )
            if expected.direction is Direction.NONE:
                self.assertEqual(int(labels.passage_index[anchor_index]), -1)
                self.assertEqual(int(labels.elapsed_bars[anchor_index]), -1)
            else:
                self.assertEqual(int(labels.passage_index[anchor_index]), expected.passage_index)
                self.assertEqual(int(labels.elapsed_bars[anchor_index]), expected.elapsed_bars)


if __name__ == "__main__":
    unittest.main()
