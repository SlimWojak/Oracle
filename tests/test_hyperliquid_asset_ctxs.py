import tempfile
import unittest
from datetime import date
from pathlib import Path

from oracle_research.hyperliquid_asset_ctxs import (
    AssetCtxMinute,
    AssetCtxStore,
    floor_to_minute,
    load_asset_ctx_day,
    load_btc_minutes_for_days,
)

try:
    import lz4.frame
except ImportError:
    lz4 = None


SAMPLE_CSV = """time_ms,coin,mark_px,funding,oracle_px
1752580800000,BTC,50000.0,-0.0001,50010.0
1752580920000,BTC,50100.0,-0.0001,50110.0
1752580800000,ETH,3000.0,0.0,3001.0
"""


class FloorToMinuteTests(unittest.TestCase):
    def test_floors_to_minute_boundary(self) -> None:
        self.assertEqual(floor_to_minute(1_752_580_865_432), 1_752_580_860_000)


class AssetCtxStoreTests(unittest.TestCase):
    def test_exact_and_prior_minute_lookup(self) -> None:
        rows = [
            AssetCtxMinute(1_752_580_860_000, "BTC", 50000.0, -0.0001, 50010.0),
            AssetCtxMinute(1_752_580_920_000, "BTC", 50100.0, -0.0001, 50110.0),
        ]
        store = AssetCtxStore(rows)
        self.assertEqual(store.get_mark_px("BTC", 1_752_580_865_000), 50000.0)
        self.assertEqual(store.get_mark_px("BTC", 1_752_580_920_000), 50100.0)
        self.assertEqual(store.get_mark_px("BTC", 1_752_580_925_000), 50100.0)
        self.assertIsNone(store.get_mark_px("ETH", 1_752_580_865_000))


@unittest.skipIf(lz4 is None, "lz4 not installed")
class LoadAssetCtxDayTests(unittest.TestCase):
    def test_load_lz4_csv_day(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "20250715.csv.lz4"
            with lz4.frame.open(path, mode="wb") as handle:
                handle.write(SAMPLE_CSV.encode("utf-8"))
            rows = load_asset_ctx_day(path)
            self.assertEqual(len(rows), 3)
            self.assertEqual(rows[0].coin, "BTC")
            self.assertAlmostEqual(rows[0].mark_px, 50000.0)

    def test_parse_iso_time_column(self) -> None:
        iso_csv = """time,coin,mark_px,funding,oracle_px
2025-07-15T12:00:00Z,BTC,50000.0,-0.0001,50010.0
"""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "20250715.csv.lz4"
            with lz4.frame.open(path, mode="wb") as handle:
                handle.write(iso_csv.encode("utf-8"))
            rows = load_asset_ctx_day(path)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0].coin, "BTC")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            day_dir = root / "asset_ctxs"
            day_dir.mkdir()
            path = day_dir / "20250715.csv.lz4"
            with lz4.frame.open(path, mode="wb") as handle:
                handle.write(SAMPLE_CSV.encode("utf-8"))
            store = load_btc_minutes_for_days(root, [date(2025, 7, 15)])
            self.assertEqual(store.minute_count, 2)
            self.assertEqual(store.get_mark_px("BTC", 1_752_580_865_000), 50000.0)


if __name__ == "__main__":
    unittest.main()
