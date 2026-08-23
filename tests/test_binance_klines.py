from __future__ import annotations

import csv
import io
import tempfile
import unittest
import zipfile
from pathlib import Path

import numpy as np

from oracle_research.binance_klines import (
    contiguous_segments,
    load_kline_dir,
    load_kline_zip,
)

HEADER = [
    "open_time",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "close_time",
    "quote_asset_volume",
    "number_of_trades",
    "taker_buy_base",
    "taker_buy_quote",
    "ignore",
]


def _row(
    open_time: int,
    close: float = 100.0,
    *,
    high: float | None = None,
    low: float | None = None,
    volume: float = 1.0,
) -> list[object]:
    high_px = close if high is None else high
    low_px = close if low is None else low
    return [
        open_time,
        close,
        high_px,
        low_px,
        close,
        volume,
        open_time + 59_999,
        0.0,
        1,
        0.0,
        0.0,
        0,
    ]


def write_kline_zip(path: Path, rows: list[list[object]], *, header: bool) -> None:
    buf = io.StringIO()
    writer = csv.writer(buf)
    if header:
        writer.writerow(HEADER)
    writer.writerows(rows)
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(f"{path.stem}.csv", buf.getvalue())


class LoadKlineZipTests(unittest.TestCase):
    def test_header_milliseconds_and_no_header_microseconds(self) -> None:
        start_s = 1_704_067_200  # 2024-01-01T00:00:00Z
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ms_path = root / "BTCUSDT-1m-2024-12.zip"
            us_path = root / "BTCUSDT-1m-2025-01.zip"
            write_kline_zip(
                ms_path,
                [_row(start_s * 1000), _row((start_s + 60) * 1000, 101.0)],
                header=False,
            )
            write_kline_zip(
                us_path,
                [
                    _row((start_s + 120) * 1_000_000, 102.0),
                    _row((start_s + 180) * 1_000_000, 103.0),
                ],
                header=True,
            )

            ms = load_kline_zip(ms_path)
            us = load_kline_zip(us_path)

            np.testing.assert_array_equal(ms.timestamp, [start_s, start_s + 60])
            np.testing.assert_array_equal(us.timestamp, [start_s + 120, start_s + 180])
            self.assertEqual(ms.n_rows, 2)
            self.assertEqual(us.n_rows, 2)
            self.assertEqual(ms.timestamp.dtype, np.int64)
            self.assertEqual(us.close.dtype, np.float64)

    def test_mixed_units_in_one_file(self) -> None:
        start_s = 1_704_067_200
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "mixed.zip"
            write_kline_zip(
                path,
                [
                    _row(start_s * 1000, 100.0),
                    _row((start_s + 60) * 1_000_000, 100.5),
                ],
                header=True,
            )
            loaded = load_kline_zip(path)
            np.testing.assert_array_equal(loaded.timestamp, [start_s, start_s + 60])

    def test_within_file_disorder_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "disorder.zip"
            write_kline_zip(
                path,
                [_row(1_704_067_260_000), _row(1_704_067_200_000)],
                header=False,
            )
            with self.assertRaises(ValueError):
                load_kline_zip(path)

    def test_duplicate_timestamp_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "dup.zip"
            write_kline_zip(
                path,
                [_row(1_704_067_200_000), _row(1_704_067_200_000)],
                header=False,
            )
            with self.assertRaises(ValueError):
                load_kline_zip(path)

    def test_invalid_prices_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad-price.zip"
            write_kline_zip(
                path,
                [_row(1_704_067_200_000, close=100.0, high=99.0, low=101.0)],
                header=False,
            )
            with self.assertRaises(ValueError):
                load_kline_zip(path)


class LoadKlineDirTests(unittest.TestCase):
    def test_concatenates_in_filename_order(self) -> None:
        start_s = 1_704_067_200
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_kline_zip(
                root / "BTCUSDT-1m-2025-02.zip",
                [_row((start_s + 120) * 1_000_000, 102.0)],
                header=True,
            )
            write_kline_zip(
                root / "BTCUSDT-1m-2025-01.zip",
                [
                    _row(start_s * 1000, 100.0),
                    _row((start_s + 60) * 1000, 101.0),
                ],
                header=False,
            )
            loaded = load_kline_dir(root)
            np.testing.assert_array_equal(
                loaded.timestamp,
                [start_s, start_s + 60, start_s + 120],
            )
            np.testing.assert_array_equal(loaded.close, [100.0, 101.0, 102.0])
            self.assertEqual(loaded.n_rows, 3)

    def test_cross_file_disorder_rejected(self) -> None:
        start_s = 1_704_067_200
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_kline_zip(
                root / "a.zip",
                [_row(start_s * 1000), _row((start_s + 60) * 1000)],
                header=False,
            )
            write_kline_zip(
                root / "b.zip",
                [_row(start_s * 1000)],
                header=False,
            )
            with self.assertRaises(ValueError):
                load_kline_dir(root)

    def test_empty_directory_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, self.assertRaises(FileNotFoundError):
            load_kline_dir(Path(tmp))


class ContiguousSegmentTests(unittest.TestCase):
    def test_gap_splits_segments(self) -> None:
        timestamps = np.asarray([0, 60, 120, 300, 360], dtype=np.int64)
        self.assertEqual(contiguous_segments(timestamps), [(0, 3), (3, 5)])

    def test_single_contiguous_block(self) -> None:
        timestamps = np.arange(0, 300, 60, dtype=np.int64)
        self.assertEqual(contiguous_segments(timestamps), [(0, 5)])

    def test_empty_and_singleton(self) -> None:
        self.assertEqual(contiguous_segments(np.asarray([], dtype=np.int64)), [])
        self.assertEqual(contiguous_segments(np.asarray([10], dtype=np.int64)), [(0, 1)])


if __name__ == "__main__":
    unittest.main()
