import tempfile
import unittest
from pathlib import Path

from oracle_research.kraken_klines import load_kraken_csv, load_kraken_csvs

BASE = 1_700_000_000


def write_csv(directory: Path, name: str, rows: list[tuple[int, float]]) -> Path:
    path = directory / name
    lines = [
        f"{timestamp},{price},{price + 0.5},{price - 0.5},{price},1.5,3"
        for timestamp, price in rows
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


class LoadKrakenCsvTests(unittest.TestCase):
    def test_loads_headerless_columns(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = write_csv(Path(tmp), "a.csv", [(BASE, 100.0), (BASE + 60, 101.0)])
            klines = load_kraken_csv(path)
        self.assertEqual(klines.n_rows, 2)
        self.assertEqual(int(klines.timestamp[0]), BASE)
        self.assertEqual(float(klines.close[1]), 101.0)
        self.assertEqual(float(klines.high[0]), 100.5)
        self.assertEqual(float(klines.volume[0]), 1.5)

    def test_gaps_are_preserved(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = write_csv(Path(tmp), "a.csv", [(BASE, 100.0), (BASE + 300, 101.0)])
            klines = load_kraken_csv(path)
        self.assertEqual(int(klines.timestamp[1]) - int(klines.timestamp[0]), 300)


class LoadKrakenCsvsTests(unittest.TestCase):
    def test_concatenates_in_order(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            first = write_csv(Path(tmp), "a.csv", [(BASE, 100.0), (BASE + 60, 100.0)])
            second = write_csv(Path(tmp), "b.csv", [(BASE + 120, 100.0)])
            klines = load_kraken_csvs([first, second])
        self.assertEqual(klines.n_rows, 3)
        self.assertEqual(int(klines.timestamp[-1]), BASE + 120)

    def test_out_of_order_files_raise(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            first = write_csv(Path(tmp), "a.csv", [(BASE + 120, 100.0)])
            second = write_csv(Path(tmp), "b.csv", [(BASE, 100.0)])
            with self.assertRaises(ValueError):
                load_kraken_csvs([first, second])

    def test_start_ts_drops_early_bars(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = write_csv(
                Path(tmp),
                "a.csv",
                [(BASE, 100.0), (BASE + 60, 100.0), (BASE + 120, 100.0)],
            )
            klines = load_kraken_csvs([path], start_ts=BASE + 60)
        self.assertEqual(klines.n_rows, 2)
        self.assertEqual(int(klines.timestamp[0]), BASE + 60)


if __name__ == "__main__":
    unittest.main()
