#!/usr/bin/env python3
"""Build normalized BTC liquidation JSONL from Hyperliquid node_fills hourly files."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from oracle_research.hl_liquidations import event_to_dict, extract_btc_liquidation_events
from oracle_research.hyperliquid_fills import iter_fills_from_lz4
from oracle_research.provenance import build_provenance, write_provenance_sidecar

REPO_ROOT = Path(__file__).resolve().parent.parent

HOURLY_SUBDIRS = (
    "node_fills/hourly",
    "node_fills_by_block/hourly",
)


def hyperliquid_hourly_files(data_root: Path) -> list[Path]:
    """Return sorted lz4 hourly fill files from both node_fills trees."""
    paths: list[Path] = []
    base = data_root / "raw" / "hyperliquid"
    for subdir in HOURLY_SUBDIRS:
        hourly_dir = base / subdir
        if hourly_dir.is_dir():
            paths.extend(sorted(hourly_dir.rglob("*.lz4")))
    return sorted(paths)


def write_jsonl(events: list[object], path: Path) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps(item, separators=(",", ":")) for item in events]
    path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
    return len(lines)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--data-root",
        type=Path,
        required=True,
        help="External immutable raw-data root.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        required=True,
        help="Derived JSONL (or .parquet path placeholder) output file.",
    )
    parser.add_argument(
        "--hour-limit",
        type=int,
        default=None,
        help="Process at most this many hourly lz4 files (for testing).",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.output.suffix == ".parquet":
        print("parquet output is not implemented; use .jsonl", file=sys.stderr)
        return 2

    hourly_files = hyperliquid_hourly_files(args.data_root)
    if args.hour_limit is not None:
        hourly_files = hourly_files[: args.hour_limit]
    if not hourly_files:
        print(
            f"no hourly lz4 files under {args.data_root}/raw/hyperliquid",
            file=sys.stderr,
        )
        return 2

    all_events: list[object] = []
    for path in hourly_files:
        fills = iter_fills_from_lz4(path)
        events = extract_btc_liquidation_events(fills)
        all_events.extend(event_to_dict(event) for event in events)

    row_count = write_jsonl(all_events, args.output)
    provenance = build_provenance(
        repo_root=REPO_ROOT,
        config={
            "hour_limit": args.hour_limit,
            "hourly_files": len(hourly_files),
            "event_count": row_count,
        },
        inputs=hourly_files,
        outputs=[args.output],
        input_base=args.data_root,
        output_base=args.output.parent,
    )
    sidecar = write_provenance_sidecar(args.output.parent, args.output.stem, provenance)
    print(
        f"files={len(hourly_files)} events={row_count} "
        f"out={args.output} provenance={sidecar}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
