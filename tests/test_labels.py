import math
import unittest

from oracle_research.labels import Bar, Direction, first_passage


def bar(
    timestamp: int,
    close: float,
    *,
    high: float | None = None,
    low: float | None = None,
) -> Bar:
    return Bar(
        timestamp=timestamp,
        high=close if high is None else high,
        low=close if low is None else low,
        close=close,
    )


class FirstPassageTests(unittest.TestCase):
    def test_up_barrier_reached_first(self) -> None:
        bars = [bar(0, 100), bar(60, 101), bar(120, 102.1)]

        result = first_passage(
            bars,
            anchor_index=0,
            horizon_bars=2,
            threshold_fraction=0.02,
        )

        self.assertIs(result.direction, Direction.UP)
        self.assertEqual(result.passage_index, 2)
        self.assertEqual(result.elapsed_bars, 2)

    def test_down_barrier_reached_first(self) -> None:
        bars = [bar(0, 100), bar(60, 99), bar(120, 97.9)]

        result = first_passage(
            bars,
            anchor_index=0,
            horizon_bars=2,
            threshold_fraction=0.02,
        )

        self.assertIs(result.direction, Direction.DOWN)
        self.assertEqual(result.passage_timestamp, 120)

    def test_anchor_bar_is_not_used_as_future_information(self) -> None:
        bars = [Bar(timestamp=0, high=103, low=97, close=100), bar(60, 100)]

        result = first_passage(
            bars,
            anchor_index=0,
            horizon_bars=1,
            threshold_fraction=0.02,
        )

        self.assertIs(result.direction, Direction.NONE)

    def test_same_bar_double_touch_is_ambiguous(self) -> None:
        bars = [bar(0, 100), Bar(timestamp=60, high=103, low=97, close=101)]

        result = first_passage(
            bars,
            anchor_index=0,
            horizon_bars=1,
            threshold_fraction=0.02,
        )

        self.assertIs(result.direction, Direction.AMBIGUOUS)

    def test_horizon_is_respected(self) -> None:
        bars = [bar(0, 100), bar(60, 100), bar(120, 103)]

        result = first_passage(
            bars,
            anchor_index=0,
            horizon_bars=1,
            threshold_fraction=0.02,
        )

        self.assertIs(result.direction, Direction.NONE)

    def test_invalid_threshold_rejected(self) -> None:
        for threshold in (0, -0.01, 1, math.nan):
            with self.subTest(threshold=threshold), self.assertRaises(ValueError):
                first_passage(
                    [bar(0, 100)],
                    anchor_index=0,
                    horizon_bars=1,
                    threshold_fraction=threshold,
                )

    def test_invalid_bar_rejected(self) -> None:
        with self.assertRaises(ValueError):
            Bar(timestamp=0, high=99, low=101, close=100)


if __name__ == "__main__":
    unittest.main()
