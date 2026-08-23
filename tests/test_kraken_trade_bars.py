import tempfile
import unittest
from pathlib import Path

from oracle_research.kraken_trade_bars import (
    OhlcvtBar,
    Trade,
    aggregate_trades,
    dedupe_and_sort_trades,
    minute_bucket,
    parse_trades_page,
    write_bars_csv,
)

BASE = 1_704_067_200  # 2024-01-01T00:00:00Z


def make_page(trades: list[list[object]], *, pair: str = "XXBTZUSD") -> dict[str, object]:
    return {
        "error": [],
        "result": {
            pair: trades,
            "last": "1704067200000000000",
        },
    }


def trade_row(
    price: str,
    volume: str,
    time_s: float,
    trade_id: int,
) -> list[object]:
    return [price, volume, time_s, "b", "m", "", trade_id]


class ParseTradesPageTests(unittest.TestCase):
    def test_parses_trade_fields(self) -> None:
        page = make_page([trade_row("100.5", "0.25", float(BASE), 1)])
        trades = parse_trades_page(page)
        self.assertEqual(len(trades), 1)
        self.assertEqual(trades[0].price, 100.5)
        self.assertEqual(trades[0].volume, 0.25)
        self.assertEqual(trades[0].time, float(BASE))
        self.assertEqual(trades[0].trade_id, 1)


class DedupeAndSortTests(unittest.TestCase):
    def test_dedupes_overlapping_pages(self) -> None:
        page_a = parse_trades_page(
            make_page(
                [
                    trade_row("100", "1", float(BASE), 1),
                    trade_row("101", "1", float(BASE + 1), 2),
                ]
            )
        )
        page_b = parse_trades_page(
            make_page(
                [
                    trade_row("101", "1", float(BASE + 1), 2),
                    trade_row("102", "1", float(BASE + 2), 3),
                ]
            )
        )
        ordered = dedupe_and_sort_trades([*page_a, *page_b])
        self.assertEqual([trade.trade_id for trade in ordered], [1, 2, 3])


class AggregateTradesTests(unittest.TestCase):
    def test_trade_at_exact_minute_start_stays_in_that_bucket(self) -> None:
        trades = [
            Trade(price=100.0, volume=1.0, time=float(BASE), trade_id=1),
            Trade(price=101.0, volume=1.0, time=float(BASE + 59.999), trade_id=2),
            Trade(price=102.0, volume=1.0, time=float(BASE + 60), trade_id=3),
        ]
        bars = aggregate_trades(trades)
        self.assertEqual(len(bars), 2)
        self.assertEqual(bars[0].timestamp, BASE)
        self.assertEqual(bars[0].open, 100.0)
        self.assertEqual(bars[0].close, 101.0)
        self.assertEqual(bars[0].trades, 2)
        self.assertEqual(bars[1].timestamp, BASE + 60)
        self.assertEqual(bars[1].open, 102.0)
        self.assertEqual(bars[1].trades, 1)

    def test_equal_timestamps_use_trade_id_for_open_close(self) -> None:
        trades = [
            Trade(price=99.0, volume=1.0, time=float(BASE + 30), trade_id=10),
            Trade(price=100.0, volume=2.0, time=float(BASE + 30), trade_id=20),
            Trade(price=101.0, volume=3.0, time=float(BASE + 30), trade_id=30),
        ]
        bars = aggregate_trades(trades)
        self.assertEqual(len(bars), 1)
        bar = bars[0]
        self.assertEqual(bar.open, 99.0)
        self.assertEqual(bar.close, 101.0)
        self.assertEqual(bar.high, 101.0)
        self.assertEqual(bar.low, 99.0)
        self.assertEqual(bar.volume, 6.0)
        self.assertEqual(bar.trades, 3)

    def test_empty_minutes_are_omitted(self) -> None:
        trades = [
            Trade(price=100.0, volume=1.0, time=float(BASE), trade_id=1),
            Trade(price=101.0, volume=1.0, time=float(BASE + 120), trade_id=2),
        ]
        bars = aggregate_trades(trades)
        self.assertEqual([bar.timestamp for bar in bars], [BASE, BASE + 120])

    def test_start_end_filter_on_bucket_timestamps(self) -> None:
        trades = [
            Trade(price=100.0, volume=1.0, time=float(BASE), trade_id=1),
            Trade(price=101.0, volume=1.0, time=float(BASE + 60), trade_id=2),
            Trade(price=102.0, volume=1.0, time=float(BASE + 120), trade_id=3),
        ]
        bars = aggregate_trades(trades, start_ts=BASE + 60, end_ts=BASE + 120)
        self.assertEqual(len(bars), 1)
        self.assertEqual(bars[0].timestamp, BASE + 60)

    def test_dedupes_inside_aggregate(self) -> None:
        trades = [
            Trade(price=100.0, volume=1.0, time=float(BASE), trade_id=1),
            Trade(price=999.0, volume=9.0, time=float(BASE), trade_id=1),
        ]
        bars = aggregate_trades(trades)
        self.assertEqual(len(bars), 1)
        self.assertEqual(bars[0].volume, 1.0)
        self.assertEqual(bars[0].trades, 1)


class WriteBarsCsvTests(unittest.TestCase):
    def test_writes_headerless_official_format(self) -> None:
        bars = [
            OhlcvtBar(
                timestamp=BASE,
                open=100.0,
                high=101.0,
                low=99.5,
                close=100.5,
                volume=2.5,
                trades=3,
            )
        ]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bars.csv"
            row_count = write_bars_csv(bars, path)
            text = path.read_text(encoding="utf-8")
        self.assertEqual(row_count, 1)
        self.assertEqual(text, f"{BASE},100.0,101.0,99.5,100.5,2.5,3\n")

    def test_end_to_end_from_json_pages(self) -> None:
        page_one = make_page(
            [
                trade_row("100", "1", float(BASE), 1),
                trade_row("101", "2", float(BASE + 30), 2),
            ]
        )
        page_two = make_page(
            [
                trade_row("101", "2", float(BASE + 30), 2),
                trade_row("102", "3", float(BASE + 60), 3),
            ]
        )
        trades = [*parse_trades_page(page_one), *parse_trades_page(page_two)]
        bars = aggregate_trades(trades, start_ts=BASE, end_ts=BASE + 120)
        self.assertEqual(len(bars), 2)
        self.assertEqual(minute_bucket(BASE), BASE)
        self.assertEqual(minute_bucket(BASE + 60), BASE + 60)


if __name__ == "__main__":
    unittest.main()
