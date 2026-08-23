import importlib.util
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path


def load_fetch_module():
    script_path = Path(__file__).resolve().parents[1] / "scripts" / "fetch_coinbase_public.py"
    spec = importlib.util.spec_from_file_location("fetch_coinbase_public", script_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"unable to load module from {script_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


fetch = load_fetch_module()


def utc(year: int, month: int, day: int, hour: int = 0, minute: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=UTC)


class WindowTilingTests(unittest.TestCase):
    def test_two_adjacent_windows_have_no_gap_or_overlap(self) -> None:
        starts = fetch.window_starts(
            utc(2019, 12, 1, 0, 0),
            utc(2019, 12, 1, 10, 0),
        )
        self.assertEqual(starts, [1575158400, 1575176400])
        range_end = int(utc(2019, 12, 1, 10, 0).timestamp())
        first_end = fetch.request_end_unix(starts[0], range_end=range_end)
        second_end = fetch.request_end_unix(starts[1], range_end=range_end)
        self.assertEqual(first_end, starts[0] + 299 * 60)
        self.assertEqual(first_end + 60, starts[1])
        self.assertEqual(second_end + 60, range_end)

    def test_default_range_tiles_without_gaps_or_boundary_overlap(self) -> None:
        range_start = fetch.parse_iso_utc(fetch.DEFAULT_START)
        range_end = fetch.parse_iso_utc(fetch.DEFAULT_END)
        starts = fetch.window_starts(range_start, range_end)
        range_end_s = int(range_end.timestamp())
        self.assertEqual(starts[0], int(range_start.timestamp()))
        self.assertEqual(starts[-1] + 300 * 60, range_end_s)
        self.assertEqual(len(starts), 11_688)

        step = 300 * 60
        for prev, nxt in zip(starts[:-1], starts[1:], strict=True):
            self.assertEqual(nxt - prev, step)
            prev_end = fetch.request_end_unix(prev, range_end=range_end_s)
            self.assertEqual(prev_end + 60, nxt)

        last_end = fetch.request_end_unix(starts[-1], range_end=range_end_s)
        self.assertEqual(last_end, range_end_s - 60)
        self.assertEqual(
            fetch.iso_utc_from_unix(last_end),
            "2026-07-31T23:59:00Z",
        )
        self.assertNotIn(range_end_s, starts)

    def test_request_end_clips_to_last_minute_before_range_end(self) -> None:
        range_end = int(utc(2019, 12, 1, 1, 0).timestamp())
        window_start = int(utc(2019, 12, 1, 0, 0).timestamp())
        self.assertEqual(
            fetch.request_end_unix(window_start, range_end=range_end),
            window_start + 59 * 60,
        )


class UrlConstructionTests(unittest.TestCase):
    def test_candles_url(self) -> None:
        url = fetch.candles_url(
            product="BTC-USD",
            start="2019-12-01T00:00:00Z",
            end="2019-12-01T04:59:00Z",
        )
        self.assertEqual(
            url,
            "https://api.exchange.coinbase.com/products/BTC-USD/candles"
            "?granularity=60&start=2019-12-01T00%3A00%3A00Z"
            "&end=2019-12-01T04%3A59%3A00Z",
        )

    def test_window_path(self) -> None:
        path = fetch.window_path(Path("/data"), "BTC-USD", 1575158400)
        self.assertEqual(
            path,
            Path("/data/raw/coinbase/candles/BTC-USD/1m/candles_1575158400.json"),
        )


class ResumeSkipTests(unittest.TestCase):
    def test_missing_file_is_not_skipped(self) -> None:
        missing = Path("/tmp/oracle-coinbase-missing-window.json")
        if missing.exists():
            missing.unlink()
        self.assertFalse(fetch.should_skip_existing(missing))

    def test_existing_file_is_skipped_and_write_does_not_clobber(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "candles_1575158400.json"
            dest.write_text("[]", encoding="utf-8")
            self.assertTrue(fetch.should_skip_existing(dest))
            fetch.write_verbatim(dest, "[[1,2,3,4,5,6]]")
            self.assertEqual(dest.read_text(encoding="utf-8"), "[]")


if __name__ == "__main__":
    unittest.main()
