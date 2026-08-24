from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

from oracle_research.hl_fills_parquet import (
    BUILDER_VERSION,
    REQUIRED_COLUMNS,
    fill_to_parquet_row,
    write_partitioned_chunk,
)
from oracle_research.hyperliquid_fills import HlFill

try:
    import duckdb  # noqa: F401
    import pyarrow.parquet as pq
except ImportError:
    HAS_ANALYTICS = False
else:
    HAS_ANALYTICS = True

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = REPO_ROOT / "scripts"
LIQUIDATED = "0xaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
COUNTERPARTY = "0xbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"


def _load_parity_module():
    if str(SCRIPTS_DIR) not in sys.path:
        sys.path.insert(0, str(SCRIPTS_DIR))
    spec = importlib.util.spec_from_file_location(
        "hl_parquet_parity",
        SCRIPTS_DIR / "run_hl_parquet_census_parity.py",
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["hl_parquet_parity"] = module
    spec.loader.exec_module(module)
    return module


def make_fill(
    *,
    user: str = LIQUIDATED,
    coin: str = "BTC",
    px: str = "100",
    sz: str = "1",
    side: str = "B",
    time_ms: int = 1_700_000_000_000,
    start_position: str = "0",
    direction: str = "Open Long",
    tid: int = 1,
    liquidation: dict[str, str] | None = None,
) -> HlFill:
    return HlFill(
        user=user,
        coin=coin,
        px=px,
        sz=sz,
        side=side,
        time_ms=time_ms,
        start_position=start_position,
        dir=direction,
        hash=f"0x{tid:x}",
        oid=tid,
        crossed=True,
        tid=tid,
        fee="0.01",
        fee_token="USDC",
        liquidation=liquidation,
        block_time=time_ms - 10,
        local_time=time_ms + 10,
        block_number=1000 + tid,
    )


def make_liquidation(method: str = "market") -> dict[str, str]:
    return {
        "liquidatedUser": LIQUIDATED,
        "markPx": "100",
        "method": method,
    }


class HlFillsParquetTests(unittest.TestCase):
    @unittest.skipUnless(HAS_ANALYTICS, "pyarrow and duckdb are optional analytics deps")
    def test_partitioned_parquet_round_trip_schema(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output_root = Path(tmp) / "all_fills"
            rows = [
                fill_to_parquet_row(
                    make_fill(coin="ETH", tid=1),
                    source_format="by_block",
                    source_path="hyperliquid/node_fills_by_block/hourly/fixture.lz4",
                    source_row_number=1,
                    builder_version=BUILDER_VERSION,
                ),
                fill_to_parquet_row(
                    make_fill(
                        tid=2,
                        direction="Liquidated Cross Long",
                        liquidation=make_liquidation(),
                    ),
                    source_format="by_block",
                    source_path="hyperliquid/node_fills_by_block/hourly/fixture.lz4",
                    source_row_number=2,
                    builder_version=BUILDER_VERSION,
                ),
            ]
            results = write_partitioned_chunk(
                rows,
                output_root=output_root,
                source_path="hyperliquid/node_fills_by_block/hourly/fixture.lz4",
                chunk_index=0,
                compression="zstd",
            )

            self.assertEqual(sum(result.rows for result in results), 2)
            table = pq.read_table(results[0].path)
            self.assertTrue(set(REQUIRED_COLUMNS).issubset(set(table.schema.names)))
            self.assertIn("source_row_number", table.schema.names)
            self.assertEqual(table.num_rows, 2)

    @unittest.skipUnless(HAS_ANALYTICS, "pyarrow and duckdb are optional analytics deps")
    def test_duckdb_census_replay_from_parquet_fixture(self) -> None:
        parity = _load_parity_module()
        source_path = "hyperliquid/node_fills_by_block/hourly/fixture.lz4"
        fills = [
            make_fill(coin="ETH", start_position="0", side="B", sz="1", time_ms=1000, tid=1),
            make_fill(
                px="100",
                sz="2",
                side="A",
                time_ms=2000,
                start_position="0",
                direction="Close Long",
                tid=2,
                liquidation=make_liquidation(),
            ),
            make_fill(coin="ETH", start_position="1", side="A", sz="1", time_ms=2500, tid=3),
            make_fill(
                px="50",
                sz="2",
                side="A",
                time_ms=3000,
                start_position="0",
                direction="Liquidated Cross Long",
                tid=4,
                liquidation=make_liquidation(),
            ),
            make_fill(
                user=COUNTERPARTY,
                px="50",
                sz="2",
                side="B",
                time_ms=3000,
                start_position="0",
                direction="Liquidated Cross Long",
                tid=4,
                liquidation=make_liquidation(),
            ),
        ]

        with tempfile.TemporaryDirectory() as tmp:
            table_root = Path(tmp) / "all_fills"
            rows = [
                fill_to_parquet_row(
                    fill,
                    source_format="by_block",
                    source_path=source_path,
                    source_row_number=index,
                    builder_version=BUILDER_VERSION,
                )
                for index, fill in enumerate(fills, start=1)
            ]
            write_partitioned_chunk(
                rows,
                output_root=table_root,
                source_path=source_path,
                chunk_index=0,
                compression="zstd",
            )

            summary = parity.run_census_from_parquet(table_root, batch_rows=2)

        self.assertEqual(summary["total_btc_liquidation_events"], 2)
        self.assertEqual(summary["total_btc_liquidation_notional_usd"], 300.0)
        self.assertEqual(
            summary["counts_by_stratum"],
            {"b_btc_only_cross": 1, "c_cross_asset": 1},
        )
        self.assertEqual(summary["counts_by_method"], {"market": 2})


if __name__ == "__main__":
    unittest.main()
