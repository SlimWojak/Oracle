import json
import tempfile
import unittest
from pathlib import Path

from oracle_research.coinbase_candles import load_candle_dir

BASE = 1_700_000_000


def bucket(index: int, price: float = 100.0) -> list[float]:
    # [time, low, high, open, close, volume], as served by the API.
    return [BASE + 60 * index, price - 0.5, price + 0.5, price, price, 2.0]


def write_window(directory: Path, start_index: int, indices: list[int]) -> None:
    # Responses are newest-first; store them that way to mirror the raw files.
    rows = [bucket(i) for i in sorted(indices, reverse=True)]
    path = directory / f"candles_{BASE + 60 * start_index}.json"
    path.write_text(json.dumps(rows), encoding="utf-8")


class LoadCandleDirTests(unittest.TestCase):
    def test_loads_and_sorts_across_windows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            write_window(directory, 5, [5, 6, 7])
            write_window(directory, 0, [0, 1, 2])
            klines = load_candle_dir(directory)
        self.assertEqual(klines.n_rows, 6)
        self.assertEqual(int(klines.timestamp[0]), BASE)
        self.assertEqual(int(klines.timestamp[-1]), BASE + 60 * 7)
        self.assertEqual(float(klines.high[0]), 100.5)
        self.assertEqual(float(klines.low[0]), 99.5)

    def test_gaps_preserved_and_empty_windows_ok(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            write_window(directory, 0, [0, 3])
            (directory / f"candles_{BASE + 60 * 5}.json").write_text("[]", encoding="utf-8")
            write_window(directory, 10, [10])
            klines = load_candle_dir(directory)
        self.assertEqual(klines.n_rows, 3)
        self.assertEqual(int(klines.timestamp[1]) - int(klines.timestamp[0]), 180)

    def test_duplicate_timestamps_raise(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            write_window(directory, 0, [0, 1])
            write_window(directory, 1, [1, 2])
            with self.assertRaises(ValueError):
                load_candle_dir(directory)

    def test_start_ts_filter(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            write_window(directory, 0, [0, 1, 2, 3])
            klines = load_candle_dir(directory, start_ts=BASE + 120)
        self.assertEqual(klines.n_rows, 2)
        self.assertEqual(int(klines.timestamp[0]), BASE + 120)


if __name__ == "__main__":
    unittest.main()
