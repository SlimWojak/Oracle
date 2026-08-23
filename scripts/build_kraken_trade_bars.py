#!/usr/bin/env python3
"""Build 1-minute Kraken OHLCVT bars from raw public Trades JSON pages."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

from oracle_research.kraken_trade_bars import (
    Trade,
    aggregate_trades,
    parse_trades_page,
    write_bars_csv,
)


def parse_iso_utc(value: str) -> datetime:
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def iso_utc(timestamp_s: int) -> str:
    return datetime.fromtimestamp(timestamp_s, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def trades_pages_dir(data_root: Path, pair: str) -> Path:
    return data_root / "raw" / "kraken" / "trades" / pair


def load_trades_from_pages(paths: list[Path]) -> tuple[list[Trade], dict[str, int]]:
    """Load and parse all trade pages; return trades and parse stats."""
    all_trades: list[Trade] = []
    stats = {"pages": 0, "parse_failures": 0, "raw_trades": 0}
    for path in paths:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            page_trades = parse_trades_page(payload)
        except (OSError, json.JSONDecodeError, ValueError, TypeError):
            stats["parse_failures"] += 1
            continue
        stats["pages"] += 1
        stats["raw_trades"] += len(page_trades)
        all_trades.extend(page_trades)
    return all_trades, stats


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Aggregate raw Kraken Trades JSON pages into 1-minute OHLCVT CSV.",
    )
    parser.add_argument(
        "--data-root",
        type=Path,
        required=True,
        help="External immutable raw-data root.",
    )
    parser.add_argument("--pair", default="XBTUSD", help="Kraken pair code (default: XBTUSD).")
    parser.add_argument(
        "--glob",
        default="*.json",
        help="Glob under raw/kraken/trades/<pair>/ (default: *.json).",
    )
    parser.add_argument(
        "--out",
        type=Path,
        required=True,
        help="Output headerless OHLCVT CSV path.",
    )
    parser.add_argument(
        "--start",
        default=None,
        help="Inclusive UTC bucket start (ISO, e.g. 2026-01-01T00:00:00Z).",
    )
    parser.add_argument(
        "--end",
        default=None,
        help="Exclusive UTC bucket end (ISO, e.g. 2026-04-01T00:00:00Z).",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    page_dir = trades_pages_dir(args.data_root, args.pair)
    if not page_dir.is_dir():
        print(f"missing trades directory: {page_dir}", file=sys.stderr)
        return 2

    paths = sorted(page_dir.glob(args.glob))
    if not paths:
        print(f"no pages matched {args.glob!r} under {page_dir}", file=sys.stderr)
        return 2

    start_ts = int(parse_iso_utc(args.start).timestamp()) if args.start else None
    end_ts = int(parse_iso_utc(args.end).timestamp()) if args.end else None

    all_trades, stats = load_trades_from_pages(paths)
    bars = aggregate_trades(all_trades, start_ts=start_ts, end_ts=end_ts)
    row_count = write_bars_csv(bars, args.out)

    first_ts = iso_utc(bars[0].timestamp) if bars else "n/a"
    last_ts = iso_utc(bars[-1].timestamp) if bars else "n/a"
    print(
        f"pages={stats['pages']} parse_failures={stats['parse_failures']} "
        f"raw_trades={stats['raw_trades']} rows={row_count} "
        f"first={first_ts} last={last_ts} out={args.out}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
