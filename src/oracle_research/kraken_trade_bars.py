"""Kraken public Trades page aggregation into 1-minute OHLCVT bars.

Input pages are raw Kraken Trades API JSON objects. Aggregation follows the
official downloadable OHLCVT convention: minute buckets stamped at interval
start, no row for minutes with zero trades.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class Trade:
    """One deduplicated Kraken trade."""

    price: float
    volume: float
    time: float
    trade_id: int


@dataclass(frozen=True, slots=True)
class OhlcvtBar:
    """One 1-minute OHLCVT row matching the official Kraken CSV layout."""

    timestamp: int
    open: float
    high: float
    low: float
    close: float
    volume: float
    trades: int


def minute_bucket(time_s: float) -> int:
    """Return the interval-start unix second for a trade timestamp."""
    return int(time_s // 60) * 60


def parse_trades_page(page: dict[str, Any]) -> list[Trade]:
    """Parse a raw Kraken Trades JSON page into trade tuples."""
    errors = page.get("error") or []
    if not isinstance(errors, list):
        errors = [errors]
    if errors:
        joined = " ".join(str(item) for item in errors)
        raise ValueError(f"trades page returned errors: {joined}")

    result = page.get("result")
    if not isinstance(result, dict):
        raise ValueError("trades page missing result object")

    pair_key = next((key for key in result if key != "last"), None)
    raw_trades = result.get(pair_key) if pair_key else []
    if raw_trades is None:
        raw_trades = []
    if not isinstance(raw_trades, list):
        raise ValueError("trades page has a non-list trade array")

    trades: list[Trade] = []
    for row in raw_trades:
        if not isinstance(row, list) or len(row) < 7:
            raise ValueError(f"malformed trade row: {row!r}")
        trades.append(
            Trade(
                price=float(row[0]),
                volume=float(row[1]),
                time=float(row[2]),
                trade_id=int(row[6]),
            )
        )
    return trades


def dedupe_and_sort_trades(trades: Iterable[Trade]) -> list[Trade]:
    """Deduplicate by trade_id and sort by (time, trade_id)."""
    by_id: dict[int, Trade] = {}
    for trade in trades:
        by_id.setdefault(trade.trade_id, trade)
    return sorted(by_id.values(), key=lambda item: (item.time, item.trade_id))


def aggregate_trades(
    trades: Iterable[Trade],
    *,
    start_ts: int | None = None,
    end_ts: int | None = None,
) -> list[OhlcvtBar]:
    """Aggregate sorted, deduplicated trades into ascending 1-minute OHLCVT bars."""
    ordered = dedupe_and_sort_trades(trades)
    bars: list[OhlcvtBar] = []
    current_bucket: int | None = None
    bucket_trades: list[Trade] = []

    def flush() -> None:
        nonlocal current_bucket, bucket_trades
        if current_bucket is None or not bucket_trades:
            bucket_trades = []
            return
        prices = [trade.price for trade in bucket_trades]
        bars.append(
            OhlcvtBar(
                timestamp=current_bucket,
                open=bucket_trades[0].price,
                high=max(prices),
                low=min(prices),
                close=bucket_trades[-1].price,
                volume=sum(trade.volume for trade in bucket_trades),
                trades=len(bucket_trades),
            )
        )
        bucket_trades = []

    for trade in ordered:
        bucket = minute_bucket(trade.time)
        if start_ts is not None and bucket < start_ts:
            continue
        if end_ts is not None and bucket >= end_ts:
            continue
        if current_bucket is not None and bucket != current_bucket:
            flush()
        current_bucket = bucket
        bucket_trades.append(trade)

    flush()
    return bars


def iter_bars_csv_lines(bars: Iterable[OhlcvtBar]) -> Iterator[str]:
    """Yield headerless CSV lines for OHLCVT bars."""
    for bar in bars:
        yield (
            f"{bar.timestamp},{bar.open},{bar.high},{bar.low},"
            f"{bar.close},{bar.volume},{bar.trades}"
        )


def write_bars_csv(bars: Iterable[OhlcvtBar], path: Path) -> int:
    """Write OHLCVT bars to a headerless CSV; return the row count."""
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = list(iter_bars_csv_lines(bars))
    path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
    return len(lines)
