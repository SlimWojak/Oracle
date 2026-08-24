import json
import unittest

from oracle_research.hyperliquid_fills import HlFill, iter_fills_from_json_lines

LIQUIDATED = "0xaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
COUNTERPARTY = "0xbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"


def _base_fill(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "coin": "BTC",
        "px": "50000.0",
        "sz": "0.1",
        "side": "A",
        "time": 1_700_000_000_000,
        "startPosition": "-0.1",
        "dir": "Liquidated Cross Short",
        "hash": "0xdeadbeef",
        "oid": 123,
        "crossed": True,
        "tid": 999,
        "fee": "1.0",
        "feeToken": "USDC",
    }
    payload.update(overrides)
    return payload


class IterFillsFromJsonLinesTests(unittest.TestCase):
    def test_old_format_pair(self) -> None:
        line = json.dumps([LIQUIDATED, _base_fill()])
        fills = list(iter_fills_from_json_lines(line.encode("utf-8")))
        self.assertEqual(len(fills), 1)
        fill = fills[0]
        self.assertEqual(fill.user, LIQUIDATED)
        self.assertEqual(fill.coin, "BTC")
        self.assertEqual(fill.px, "50000.0")
        self.assertEqual(fill.time_ms, 1_700_000_000_000)
        self.assertIsNone(fill.block_time)
        self.assertIsNone(fill.local_time)
        self.assertIsNone(fill.block_number)

    def test_by_block_format(self) -> None:
        record = {
            "local_time": 1_700_000_000_100,
            "block_time": 1_700_000_000_050,
            "block_number": 42,
            "events": [
                [LIQUIDATED, _base_fill()],
                [COUNTERPARTY, _base_fill(tid=1000, side="B")],
            ],
        }
        raw = json.dumps(record).encode("utf-8")
        fills = list(iter_fills_from_json_lines(raw))
        self.assertEqual(len(fills), 2)
        self.assertEqual(fills[0].block_time, 1_700_000_000_050)
        self.assertEqual(fills[0].local_time, 1_700_000_000_100)
        self.assertEqual(fills[0].block_number, 42)
        self.assertEqual(fills[1].user, COUNTERPARTY)

    def test_by_block_iso_timestamps(self) -> None:
        record = {
            "local_time": "2025-07-27T09:59:59.900000000Z",
            "block_time": "2025-07-27T09:59:59.857100152Z",
            "block_number": 42,
            "events": [[LIQUIDATED, _base_fill()]],
        }
        fill = next(iter_fills_from_json_lines(json.dumps(record).encode("utf-8")))
        self.assertIsNotNone(fill.block_time)
        self.assertIsNotNone(fill.local_time)

    def test_mixed_old_format_lines(self) -> None:
        by_block = {
            "local_time": 10,
            "block_time": 9,
            "block_number": 1,
            "events": [[LIQUIDATED, _base_fill(tid=1)]],
        }
        pair = [COUNTERPARTY, _base_fill(tid=2)]
        raw = (json.dumps(by_block) + "\n" + json.dumps(pair)).encode("utf-8")
        fills = list(iter_fills_from_json_lines(raw))
        self.assertEqual([fill.tid for fill in fills], [1, 2])

    def test_liquidation_object_preserved(self) -> None:
        liquidation = {
            "liquidatedUser": LIQUIDATED,
            "markPx": "49900.0",
            "method": "market",
        }
        line = json.dumps([LIQUIDATED, _base_fill(liquidation=liquidation)])
        fill = next(iter_fills_from_json_lines(line.encode("utf-8")))
        self.assertEqual(fill.liquidation, liquidation)

    def test_rejects_unknown_line_shape(self) -> None:
        with self.assertRaises(ValueError):
            list(iter_fills_from_json_lines(json.dumps({"coin": "BTC"}).encode("utf-8")))


class HlFillDataclassTests(unittest.TestCase):
    def test_frozen_slots(self) -> None:
        fill = HlFill(
            user=LIQUIDATED,
            coin="BTC",
            px="1",
            sz="1",
            side="B",
            time_ms=1,
            start_position="0",
            dir="Open Long",
            hash="0x1",
            oid=1,
            crossed=False,
            tid=1,
            fee="0",
            fee_token="USDC",
        )
        with self.assertRaises(AttributeError):
            fill.coin = "ETH"  # type: ignore[misc]


if __name__ == "__main__":
    unittest.main()
