import hashlib
import importlib.util
import tempfile
import unittest
from pathlib import Path


def load_fetch_module():
    script_path = Path(__file__).resolve().parents[1] / "scripts" / "fetch_binance_public.py"
    spec = importlib.util.spec_from_file_location("fetch_binance_public", script_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"unable to load module from {script_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


fetch = load_fetch_module()


class MonthRangeTests(unittest.TestCase):
    def test_single_month(self) -> None:
        self.assertEqual(fetch.month_range("2020-01", "2020-01"), ["2020-01"])

    def test_inclusive_end_with_year_rollover(self) -> None:
        self.assertEqual(
            fetch.month_range("2020-11", "2021-02"),
            ["2020-11", "2020-12", "2021-01", "2021-02"],
        )

    def test_default_spot_range_count(self) -> None:
        months = fetch.month_range("2020-01", "2026-07")
        self.assertEqual(len(months), 79)
        self.assertEqual(months[0], "2020-01")
        self.assertEqual(months[-1], "2026-07")


class DayRangeTests(unittest.TestCase):
    def test_single_day(self) -> None:
        self.assertEqual(fetch.day_range("2021-12-01", "2021-12-01"), ["2021-12-01"])

    def test_inclusive_end_with_year_rollover(self) -> None:
        self.assertEqual(
            fetch.day_range("2021-12-30", "2022-01-02"),
            ["2021-12-30", "2021-12-31", "2022-01-01", "2022-01-02"],
        )

    def test_reversed_range_is_empty(self) -> None:
        self.assertEqual(fetch.day_range("2022-01-02", "2022-01-01"), [])

    def test_default_metrics_range_count(self) -> None:
        days = fetch.day_range("2021-12-01", "2026-08-21")
        self.assertEqual(len(days), 1725)
        self.assertEqual(days[0], "2021-12-01")
        self.assertEqual(days[-1], "2026-08-21")


class ParseChecksumLineTests(unittest.TestCase):
    def test_realistic_line(self) -> None:
        digest = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
        line = f"{digest}  BTCUSDT-1m-2020-01.zip"
        self.assertEqual(fetch.parse_checksum_line(line), digest)

    def test_malformed_line_raises(self) -> None:
        with self.assertRaises(ValueError):
            fetch.parse_checksum_line("not-a-valid-line")

    def test_empty_line_raises(self) -> None:
        with self.assertRaises(ValueError):
            fetch.parse_checksum_line("   ")


class DatasetUrlsTests(unittest.TestCase):
    def test_spot_klines_first_and_last(self) -> None:
        urls = fetch.dataset_urls("spot_klines_1m")
        self.assertEqual(
            urls[0],
            "https://data.binance.vision/data/spot/monthly/klines/BTCUSDT/1m/"
            "BTCUSDT-1m-2020-01.zip",
        )
        self.assertEqual(
            urls[-1],
            "https://data.binance.vision/data/spot/monthly/klines/BTCUSDT/1m/"
            "BTCUSDT-1m-2026-07.zip",
        )

    def test_um_metrics_first_and_last(self) -> None:
        urls = fetch.dataset_urls("um_metrics")
        self.assertEqual(
            urls[0],
            "https://data.binance.vision/data/futures/um/daily/metrics/BTCUSDT/"
            "BTCUSDT-metrics-2021-12-01.zip",
        )
        self.assertEqual(
            urls[-1],
            "https://data.binance.vision/data/futures/um/daily/metrics/BTCUSDT/"
            "BTCUSDT-metrics-2026-08-21.zip",
        )


class Sha256FileTests(unittest.TestCase):
    def test_sha256_file_matches_hashlib(self) -> None:
        payload = b"oracle binance checksum verification"
        with tempfile.NamedTemporaryFile(delete=False) as handle:
            handle.write(payload)
            temp_path = Path(handle.name)

        try:
            expected = hashlib.sha256(payload).hexdigest()
            self.assertEqual(fetch.sha256_file(temp_path), expected)
        finally:
            temp_path.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
