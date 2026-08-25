from __future__ import annotations

import json
import unittest
from collections.abc import Mapping, Sequence
from dataclasses import asdict, is_dataclass
from enum import Enum
from pathlib import Path

import numpy as np

from oracle_research.binance_klines import KlineArrays
from oracle_research.clusters import PositiveAnchor, cluster_positive_anchors
from oracle_research.consolidated_index import build_median_index
from oracle_research.hl_fills_parquet import fills_parquet_schema
from oracle_research.hl_liquidations import (
    event_to_dict,
    extract_btc_liquidation_events,
    stratify_event,
)
from oracle_research.hyperliquid_fills import HlFill
from oracle_research.labels import Bar, Direction, first_passage

GOLDEN_DIR = Path(__file__).parent / "fixtures" / "golden"


def _jsonable(value: object) -> object:
    if is_dataclass(value):
        return _jsonable(asdict(value))
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, np.ndarray):
        return _jsonable(value.tolist())
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray):
        return [_jsonable(item) for item in value]
    return value


def _canonical_json_bytes(value: object) -> bytes:
    return json.dumps(
        _jsonable(value),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")


def _kline_arrays(
    timestamp: list[int],
    open_: list[float],
    high: list[float],
    low: list[float],
    close: list[float],
    volume: list[float],
) -> KlineArrays:
    return KlineArrays(
        timestamp=np.asarray(timestamp, dtype=np.int64),
        open=np.asarray(open_, dtype=np.float64),
        high=np.asarray(high, dtype=np.float64),
        low=np.asarray(low, dtype=np.float64),
        close=np.asarray(close, dtype=np.float64),
        volume=np.asarray(volume, dtype=np.float64),
        n_rows=len(timestamp),
    )


def _fill(
    *,
    user: str,
    tid: int,
    coin: str = "BTC",
    time_ms: int = 1_700_000_000_000,
    px: str = "50000",
    sz: str = "0.1",
    side: str = "A",
    start_position: str = "0.1",
    direction: str = "Liquidated Cross Long",
    method: str = "market",
    liquidated_user: str | None = None,
) -> HlFill:
    if liquidated_user is None:
        liquidated_user = user
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
        fee="1.0",
        fee_token="USDC",
        liquidation={
            "liquidatedUser": liquidated_user,
            "markPx": "50100",
            "method": method,
        },
    )


class GoldenPinTests(unittest.TestCase):
    def assert_matches_golden(self, filename: str, value: object) -> None:
        expected = (
            (GOLDEN_DIR / filename)
            .read_text(encoding="ascii")
            .strip()
            .encode("utf-8")
        )
        self.assertEqual(_canonical_json_bytes(value), expected)

    def test_first_passage_golden(self) -> None:
        bars = [
            Bar(timestamp=1_700_000_000, high=100.5, low=99.5, close=100.0),
            Bar(timestamp=1_700_000_060, high=101.0, low=99.0, close=100.0),
            Bar(timestamp=1_700_000_120, high=101.5, low=99.2, close=100.5),
            Bar(timestamp=1_700_000_180, high=103.0, low=100.1, close=102.5),
            Bar(timestamp=1_700_000_240, high=98.0, low=97.0, close=97.5),
        ]

        result = first_passage(
            bars,
            anchor_index=1,
            horizon_bars=3,
            threshold_fraction=0.02,
        )

        self.assert_matches_golden("first_passage.json", result)

    def test_cluster_positive_anchors_golden(self) -> None:
        anchors = [
            PositiveAnchor(
                anchor_timestamp=1_000,
                passage_timestamp=2_000,
                direction=Direction.DOWN,
            ),
            PositiveAnchor(
                anchor_timestamp=4_000,
                passage_timestamp=5_000,
                direction=Direction.UP,
            ),
            PositiveAnchor(
                anchor_timestamp=20_000,
                passage_timestamp=20_100,
                direction=Direction.DOWN,
            ),
        ]

        clusters = cluster_positive_anchors(anchors, horizon_seconds=3_600)

        self.assert_matches_golden("event_clusters.json", clusters)

    def test_build_median_index_golden(self) -> None:
        members = [
            _kline_arrays(
                [0, 60, 120],
                [100, 110, 120],
                [105, 115, 125],
                [95, 105, 115],
                [102, 112, 122],
                [1, 2, 3],
            ),
            _kline_arrays(
                [0, 120, 180],
                [102, 122, 132],
                [106, 126, 136],
                [96, 116, 126],
                [101, 121, 131],
                [10, 20, 30],
            ),
            _kline_arrays(
                [0, 60, 180],
                [98, 108, 130],
                [104, 114, 134],
                [94, 104, 124],
                [99, 111, 129],
                [100, 200, 300],
            ),
        ]
        index = build_median_index(members)
        payload = {
            "timestamp": index.klines.timestamp,
            "open": index.klines.open,
            "high": index.klines.high,
            "low": index.klines.low,
            "close": index.klines.close,
            "volume": index.klines.volume,
            "venue_count": index.venue_count,
        }

        self.assert_matches_golden("median_index.json", payload)

    def test_hl_liquidation_events_and_strata_golden(self) -> None:
        isolated = "0x00000000000000000000000000000000000000a1"
        cross = "0x00000000000000000000000000000000000000b2"
        market = "0x00000000000000000000000000000000000000c3"
        backstop = "0x00000000000000000000000000000000000000d4"
        cross_asset = "0x00000000000000000000000000000000000000e5"
        counterparty = "0x00000000000000000000000000000000000000ff"
        fills = [
            _fill(
                user=isolated,
                tid=201,
                direction="Liquidated Isolated Long",
                px="50000",
                sz="0.1",
                start_position="0.1",
            ),
            _fill(
                user=counterparty,
                tid=201,
                direction="Liquidated Isolated Long",
                px="50000",
                sz="0.1",
                liquidated_user=isolated,
            ),
            _fill(
                user=cross,
                tid=202,
                time_ms=1_700_000_000_060,
                direction="Liquidated Cross Short",
                px="50010",
                sz="0.2",
                start_position="-0.2",
            ),
            _fill(
                user=market,
                tid=203,
                time_ms=1_700_000_000_120,
                direction="Close Long",
                px="50020",
                sz="0.3",
                start_position="0.3",
            ),
            _fill(
                user=backstop,
                tid=204,
                time_ms=1_700_000_000_180,
                direction="Liquidated Cross Long",
                method="backstop",
                px="50030",
                sz="0.4",
                start_position="0.4",
            ),
            _fill(
                user=cross_asset,
                tid=205,
                time_ms=1_700_000_000_240,
                direction="Liquidated Isolated Short",
                px="50040",
                sz="0.5",
                start_position="-0.5",
            ),
            _fill(
                user=isolated,
                tid=206,
                coin="ETH",
                time_ms=1_700_000_000_300,
                direction="Liquidated Cross Long",
                px="2500",
                sz="1.0",
            ),
        ]
        btc_only_by_user = {
            isolated: True,
            cross: True,
            market: True,
            backstop: True,
            cross_asset: False,
        }
        events = extract_btc_liquidation_events(fills)
        payload = [
            {
                "event": event_to_dict(event),
                "stratum": stratify_event(
                    event,
                    is_btc_only=btc_only_by_user[event.liquidated_user],
                ),
            }
            for event in events
        ]

        self.assert_matches_golden("hl_liquidation_events.json", payload)

    def test_hl_fills_parquet_schema_golden(self) -> None:
        try:
            schema = fills_parquet_schema()
        except ImportError as exc:
            self.skipTest(str(exc))
        payload = [[field.name, str(field.type)] for field in schema]

        self.assert_matches_golden("hl_fills_parquet_schema.json", payload)


if __name__ == "__main__":
    unittest.main()
