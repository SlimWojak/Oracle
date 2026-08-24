#!/usr/bin/env python3
"""EXP-001 Phase 1: full-tape BTC liquidation stratification census."""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from oracle_research.hl_liquidations import MARKET_CLOSE_DIRS, end_position_after_fill
from oracle_research.provenance import build_provenance, write_provenance_sidecar

REPO_ROOT = Path(__file__).resolve().parent.parent
CROSS_ASSET_EPS = 1e-8
EARLY_DEMOTION_THRESHOLD = 0.20
PARTIAL_VIABILITY_THRESHOLD = 0.50

ISOLATED_DIR_RE = re.compile(r"^Liquidated Isolated ")
CROSS_DIR_RE = re.compile(r"^Liquidated Cross ")


@dataclass
class CoinPosition:
    time_ms: int
    end_position: float


@dataclass
class PositionTracker:
    """Last known post-fill net position per user and coin (monotonic in time per key)."""

    _by_user: dict[str, dict[str, CoinPosition]] = field(default_factory=dict)

    def snapshot_cross_asset(self, user: str, event_time_ms: int) -> bool:
        for coin, pos in self._by_user.get(user, {}).items():
            if coin == "BTC":
                continue
            if pos.time_ms <= event_time_ms and abs(pos.end_position) >= CROSS_ASSET_EPS:
                return True
        return False

    def apply_fill(
        self,
        user: str,
        coin: str,
        time_ms: int,
        start_position: str | float,
        side: str,
        sz: str | float,
    ) -> None:
        end_position = end_position_after_fill(start_position, side, sz)
        user_coins = self._by_user.setdefault(user, {})
        current = user_coins.get(coin)
        if current is None or time_ms >= current.time_ms:
            user_coins[coin] = CoinPosition(time_ms=time_ms, end_position=end_position)


@dataclass
class AggregationBuckets:
    event_count: int = 0
    notional_usd: float = 0.0


def empty_nested_counter() -> defaultdict[str, defaultdict[str, int]]:
    return defaultdict(lambda: defaultdict(int))


def empty_nested_buckets() -> defaultdict[str, defaultdict[str, AggregationBuckets]]:
    return defaultdict(lambda: defaultdict(AggregationBuckets))


def classify_stratum(*, cross_asset: bool, direction: str, method: str) -> str:
    if cross_asset:
        return "c_cross_asset"
    if ISOLATED_DIR_RE.match(direction):
        return "a_btc_only_isolated"
    if CROSS_DIR_RE.match(direction):
        return "b_btc_only_cross"
    if method == "market" and direction in MARKET_CLOSE_DIRS:
        return "b_btc_only_cross"
    return "other"


def parse_usd_notional(px: str | float, sz: str | float) -> float:
    return float(px) * float(sz)


def _decompress_lz4(payload: bytes) -> bytes:
    import lz4.frame

    return lz4.frame.decompress(payload)


def iter_hourly_lz4_paths(data_root: Path) -> list[Path]:
    prefixes = (
        data_root / "raw/hyperliquid/node_fills/hourly",
        data_root / "raw/hyperliquid/node_fills_by_block/hourly",
    )
    paths: list[Path] = []
    for prefix in prefixes:
        if prefix.is_dir():
            paths.extend(prefix.rglob("*.lz4"))
    return sorted(paths, key=lambda p: str(p))


def iter_fills_from_bytes(raw: bytes) -> Iterator[tuple[str, dict[str, Any]]]:
    text = raw.decode("utf-8")
    for line in text.splitlines():
        if not line.strip():
            continue
        record = json.loads(line)
        if isinstance(record, list) and len(record) == 2:
            user, fill = record
            if isinstance(user, str) and isinstance(fill, dict):
                yield user, fill
            continue
        if isinstance(record, dict):
            events = record.get("events")
            if isinstance(events, list):
                for event in events:
                    if (
                        isinstance(event, list)
                        and len(event) == 2
                        and isinstance(event[0], str)
                        and isinstance(event[1], dict)
                    ):
                        yield event[0], event[1]


def extract_btc_liquidation_event(
    user: str,
    fill: dict[str, Any],
    *,
    seen_keys: set[tuple[str, int]],
) -> dict[str, Any] | None:
    if fill.get("coin") != "BTC":
        return None
    liquidation = fill.get("liquidation")
    if not isinstance(liquidation, dict):
        return None
    liquidated_user = liquidation.get("liquidatedUser")
    if not isinstance(liquidated_user, str) or user != liquidated_user:
        return None
    tid = fill.get("tid")
    if not isinstance(tid, int):
        return None
    key = (liquidated_user, tid)
    if key in seen_keys:
        return None
    seen_keys.add(key)
    method = liquidation.get("method")
    if method not in ("market", "backstop"):
        method = str(method) if method is not None else "unknown"
    return {
        "liquidated_user": liquidated_user,
        "tid": tid,
        "time_ms": int(fill["time"]),
        "dir": str(fill.get("dir", "")),
        "method": method,
        "notional_usd": parse_usd_notional(fill["px"], fill["sz"]),
    }


def process_fill_stream(
    fills: Iterator[tuple[str, dict[str, Any]]],
    *,
    tracker: PositionTracker,
    seen_keys: set[tuple[str, int]],
    counts_by_stratum: defaultdict[str, int],
    counts_by_method: defaultdict[str, int],
    counts_by_dir: defaultdict[str, int],
    notional_by_stratum: defaultdict[str, float],
    notional_by_method: defaultdict[str, float],
    cross_by_method: defaultdict[str, AggregationBuckets],
    stratum_method_counts: defaultdict[str, defaultdict[str, int]],
    stratum_method_notional: defaultdict[str, defaultdict[str, float]],
) -> int:
    events = 0
    for user, fill in fills:
        coin = fill.get("coin")
        time_ms = fill.get("time")
        start_position = fill.get("startPosition")
        if isinstance(coin, str) and isinstance(time_ms, int) and start_position is not None:
            event = extract_btc_liquidation_event(user, fill, seen_keys=seen_keys)
            if event is not None:
                cross_asset = tracker.snapshot_cross_asset(
                    event["liquidated_user"],
                    event["time_ms"],
                )
                method = event["method"]
                stratum = classify_stratum(
                    cross_asset=cross_asset,
                    direction=event["dir"],
                    method=method,
                )
                notional = event["notional_usd"]
                counts_by_stratum[stratum] += 1
                counts_by_method[method] += 1
                counts_by_dir[event["dir"]] += 1
                notional_by_stratum[stratum] += notional
                notional_by_method[method] += notional
                stratum_method_counts[stratum][method] += 1
                stratum_method_notional[stratum][method] += notional
                if stratum == "c_cross_asset":
                    bucket = cross_by_method[method]
                    bucket.event_count += 1
                    bucket.notional_usd += notional
                events += 1
            tracker.apply_fill(
                user,
                coin,
                time_ms,
                start_position,
                fill.get("side", ""),
                fill.get("sz", 0),
            )
    return events


def run_census(
    data_root: Path,
    *,
    max_files: int | None = None,
    progress_every: int = 100,
) -> dict[str, Any]:
    paths = iter_hourly_lz4_paths(data_root)
    if max_files is not None:
        paths = paths[:max_files]

    tracker = PositionTracker()
    seen_keys: set[tuple[str, int]] = set()
    counts_by_stratum: defaultdict[str, int] = defaultdict(int)
    counts_by_method: defaultdict[str, int] = defaultdict(int)
    counts_by_dir: defaultdict[str, int] = defaultdict(int)
    notional_by_stratum: defaultdict[str, float] = defaultdict(float)
    notional_by_method: defaultdict[str, float] = defaultdict(float)
    cross_by_method: defaultdict[str, AggregationBuckets] = defaultdict(AggregationBuckets)
    stratum_method_counts = empty_nested_counter()
    stratum_method_notional = empty_nested_counter()

    for index, path in enumerate(paths, start=1):
        raw = _decompress_lz4(path.read_bytes())
        process_fill_stream(
            iter_fills_from_bytes(raw),
            tracker=tracker,
            seen_keys=seen_keys,
            counts_by_stratum=counts_by_stratum,
            counts_by_method=counts_by_method,
            counts_by_dir=counts_by_dir,
            notional_by_stratum=notional_by_stratum,
            notional_by_method=notional_by_method,
            cross_by_method=cross_by_method,
            stratum_method_counts=stratum_method_counts,
            stratum_method_notional=stratum_method_notional,
        )
        if progress_every and index % progress_every == 0:
            print(f"processed {index}/{len(paths)} files", file=sys.stderr)

    total_events = sum(counts_by_stratum.values())
    total_notional = sum(notional_by_stratum.values())
    tractable_notional = (
        notional_by_stratum.get("a_btc_only_isolated", 0.0)
        + notional_by_stratum.get("b_btc_only_cross", 0.0)
    )
    tractable_share = tractable_notional / total_notional if total_notional > 0 else 0.0

    early_demotion = tractable_share < EARLY_DEMOTION_THRESHOLD
    partial_viability = tractable_share >= PARTIAL_VIABILITY_THRESHOLD

    return {
        "experiment": "EXP-001",
        "phase": "stratification_census",
        "data_root": str(data_root),
        "files_processed": len(paths),
        "dedupe_key": ["liquidatedUser", "tid"],
        "liquidated_leg_only": True,
        "total_btc_liquidation_events": total_events,
        "total_btc_liquidation_notional_usd": total_notional,
        "tractable_notional_usd": tractable_notional,
        "tractable_share": tractable_share,
        "early_demotion_triggered": early_demotion,
        "early_demotion_threshold": EARLY_DEMOTION_THRESHOLD,
        "partial_viability_threshold": PARTIAL_VIABILITY_THRESHOLD,
        "partial_viability_met": partial_viability,
        "counts_by_stratum": dict(sorted(counts_by_stratum.items())),
        "notional_usd_by_stratum": {
            key: notional_by_stratum[key] for key in sorted(notional_by_stratum)
        },
        "counts_by_method": dict(sorted(counts_by_method.items())),
        "notional_usd_by_method": {
            key: notional_by_method[key] for key in sorted(notional_by_method)
        },
        "counts_by_dir": dict(sorted(counts_by_dir.items(), key=lambda item: (-item[1], item[0]))),
        "counts_by_stratum_and_method": {
            stratum: dict(sorted(methods.items()))
            for stratum, methods in sorted(stratum_method_counts.items())
        },
        "notional_usd_by_stratum_and_method": {
            stratum: dict(sorted(methods.items()))
            for stratum, methods in sorted(stratum_method_notional.items())
        },
        "cross_asset_by_method": {
            method: {
                "event_count": bucket.event_count,
                "notional_usd": bucket.notional_usd,
            }
            for method, bucket in sorted(cross_by_method.items())
        },
    }


def render_markdown(summary: dict[str, Any]) -> str:
    lines = [
        "# EXP-001 Phase 1 — stratification census",
        "",
        f"- Files processed: {summary['files_processed']}",
        f"- Total deduped BTC liquidation events: {summary['total_btc_liquidation_events']}",
        f"- Total USD notional: {summary['total_btc_liquidation_notional_usd']:,.2f}",
        f"- Tractable notional (a+b): {summary['tractable_notional_usd']:,.2f}",
        f"- Tractable share: {summary['tractable_share']:.4%}",
        f"- Early demotion (<20%): {'YES' if summary['early_demotion_triggered'] else 'no'}",
        "",
        "## Counts by stratum",
        "",
    ]
    for stratum, count in summary["counts_by_stratum"].items():
        notional = summary["notional_usd_by_stratum"].get(stratum, 0.0)
        lines.append(f"- {stratum}: {count} events, ${notional:,.2f}")
    lines.extend(["", "## Counts by method", ""])
    for method, count in summary["counts_by_method"].items():
        notional = summary["notional_usd_by_method"].get(method, 0.0)
        lines.append(f"- {method}: {count} events, ${notional:,.2f}")
    lines.extend(["", "## Direction tags (top counts)", ""])
    for direction, count in list(summary["counts_by_dir"].items())[:20]:
        lines.append(f"- {direction}: {count}")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="EXP-001 stratification census")
    parser.add_argument(
        "--data-root",
        type=Path,
        required=True,
        help="Oracle data root (contains raw/hyperliquid/...)",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=REPO_ROOT / "reports/exp001",
        help="Directory for census artifacts",
    )
    parser.add_argument(
        "--max-files",
        type=int,
        default=None,
        help="Process only the first N hourly files (sorted path order)",
    )
    parser.add_argument(
        "--progress-every",
        type=int,
        default=100,
        help="Print progress every N files (0 to disable)",
    )
    args = parser.parse_args()

    summary = run_census(
        args.data_root.resolve(),
        max_files=args.max_files,
        progress_every=args.progress_every,
    )

    args.output_dir.mkdir(parents=True, exist_ok=True)
    json_path = args.output_dir / "stratification_census.json"
    md_path = args.output_dir / "stratification_census.md"
    json_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    md_path.write_text(render_markdown(summary), encoding="utf-8")

    sidecar = write_provenance_sidecar(
        args.output_dir,
        "stratification_census",
        build_provenance(
            repo_root=REPO_ROOT,
            config={
                "experiment": "EXP-001",
                "phase": "stratification_census",
                "data_root": str(args.data_root.resolve()),
                "files_processed": summary["files_processed"],
                "max_files": args.max_files,
            },
            inputs=[],
            outputs=[json_path, md_path],
            output_base=args.output_dir,
        ),
    )

    print(f"tractable_share={summary['tractable_share']:.6f}")
    print(f"early_demotion={summary['early_demotion_triggered']}")
    print(f"Wrote {json_path}, {md_path}, {sidecar}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
