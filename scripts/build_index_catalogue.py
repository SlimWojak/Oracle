#!/usr/bin/env python3
"""EXP-000 consolidated-index event catalogue per D-022.

Builds the median-of-three index (Binance BTCUSDT, Kraken XBTUSD, Coinbase
BTC-USD), labels it with wall-clock first-passage horizons, clusters positive
anchors per D-014, and writes ``index_catalogue.json``, ``index_clusters.json``
and ``INDEX_SUMMARY.md`` with a D-019 provenance sidecar.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import numpy as np

from oracle_research.batch_labels import (
    DIR_AMBIGUOUS,
    DIR_DOWN,
    DIR_INSUFFICIENT,
    DIR_NONE,
    DIR_UP,
    batch_first_passage_time,
)
from oracle_research.binance_klines import load_kline_dir
from oracle_research.clusters import PositiveAnchor, cluster_positive_anchors
from oracle_research.coinbase_candles import load_candle_dir
from oracle_research.consolidated_index import IndexBars, build_median_index
from oracle_research.kraken_klines import load_kraken_csvs
from oracle_research.labels import Direction
from oracle_research.provenance import build_provenance, write_provenance_sidecar

REPO_ROOT = Path(__file__).resolve().parent.parent
STEP_SECONDS = 60

SPOT_SUBDIR = "raw/binance_vision/spot/monthly/klines/BTCUSDT/1m"
KRAKEN_CSVS = (
    "raw/kraken/ohlcvt/XBTUSD_1.csv",
    "raw/kraken/ohlcvt/XBTUSD_1_Q1_2026.csv",
    "derived/kraken/XBTUSD_1_2026AprJul_from_trades_v2.csv",
)
COINBASE_DIR = "raw/coinbase/candles/BTC-USD/1m"


def iso_utc(timestamp: int) -> str:
    return datetime.fromtimestamp(int(timestamp), tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_horizons(text: str) -> list[int]:
    values = [int(part) for part in text.split(",") if part.strip()]
    if not values or any(value <= 0 for value in values):
        raise argparse.ArgumentTypeError("horizons-seconds must be positive integers")
    return values


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", required=True, type=Path)
    parser.add_argument("--threshold", default=0.02, type=float)
    parser.add_argument("--horizons-seconds", default="3600,14400", type=parse_horizons)
    parser.add_argument("--bars-start", default="2019-11-01T00:00:00Z")
    parser.add_argument("--out-dir", default=Path("reports/exp000"), type=Path)
    return parser.parse_args(argv)


def _cluster_record(cluster) -> dict[str, object]:
    direction = "mixed" if cluster.mixed else cluster.direction.name.lower()
    return {
        "start_timestamp": cluster.start_timestamp,
        "end_timestamp": cluster.end_timestamp,
        "start": iso_utc(cluster.start_timestamp),
        "end": iso_utc(cluster.end_timestamp),
        "direction": direction,
        "anchor_count": cluster.anchor_count,
        "up_count": cluster.up_count,
        "down_count": cluster.down_count,
    }


def _per_year(clusters) -> dict[str, int]:
    counts: dict[str, int] = {}
    for cluster in clusters:
        year = str(datetime.fromtimestamp(cluster.start_timestamp, tz=UTC).year)
        counts[year] = counts.get(year, 0) + 1
    return dict(sorted(counts.items()))


def label_horizon(index: IndexBars, *, horizon_seconds: int, threshold: float) -> tuple:
    klines = index.klines
    labels = batch_first_passage_time(
        klines.timestamp,
        klines.high,
        klines.low,
        klines.close,
        horizon_seconds=horizon_seconds,
        threshold_fraction=threshold,
        step_seconds=STEP_SECONDS,
    )
    positive_mask = (labels.direction == DIR_UP) | (labels.direction == DIR_DOWN)
    positive_rows = np.nonzero(positive_mask)[0]
    anchors = [
        PositiveAnchor(
            anchor_timestamp=int(klines.timestamp[row]) + STEP_SECONDS,
            passage_timestamp=int(klines.timestamp[labels.passage_index[row]]) + STEP_SECONDS,
            direction=Direction.UP if labels.direction[row] == DIR_UP else Direction.DOWN,
        )
        for row in positive_rows
    ]
    clusters = cluster_positive_anchors(anchors, horizon_seconds=max(horizon_seconds, 1))
    two_of_three = int(np.count_nonzero(index.venue_count[positive_rows] == 2))
    summary = {
        "horizon_seconds": horizon_seconds,
        "total_anchors": int(labels.direction.size),
        "up_count": int(np.count_nonzero(labels.direction == DIR_UP)),
        "down_count": int(np.count_nonzero(labels.direction == DIR_DOWN)),
        "positive_count": int(positive_rows.size),
        "ambiguous_count": int(np.count_nonzero(labels.direction == DIR_AMBIGUOUS)),
        "insufficient_horizon_count": int(np.count_nonzero(labels.direction == DIR_INSUFFICIENT)),
        "none_count": int(np.count_nonzero(labels.direction == DIR_NONE)),
        "positive_anchors_on_2of3_bars": two_of_three,
        "positive_anchors_on_2of3_share": (
            two_of_three / positive_rows.size if positive_rows.size else 0.0
        ),
        "clusters": {
            "total": len(clusters),
            "up": sum(1 for c in clusters if c.up_count > 0 and c.down_count == 0),
            "down": sum(1 for c in clusters if c.down_count > 0 and c.up_count == 0),
            "mixed": sum(1 for c in clusters if c.mixed),
            "per_year": _per_year(clusters),
        },
    }
    return summary, [_cluster_record(cluster) for cluster in clusters]


def render_summary(payload: dict[str, object]) -> str:
    coverage = payload["coverage"]
    lines = [
        "# EXP-000 consolidated-index catalogue (D-022)",
        "",
        "## Index grid",
        f"- bars: {coverage['bars']}",
        f"- range: {coverage['first']} to {coverage['last']}",
        f"- 3-of-3 bars: {coverage['bars_3of3']}",
        f"- 2-of-3 bars: {coverage['bars_2of3']}",
        f"- minutes vs calendar (missing): {coverage['missing_minutes']}",
    ]
    for horizon in payload["horizons"]:
        clusters = horizon["clusters"]
        lines.extend(
            [
                "",
                f"## Horizon {horizon['horizon_seconds'] // 60} minutes",
                "",
                f"- positive anchors: {horizon['positive_count']} "
                f"(up {horizon['up_count']}, down {horizon['down_count']})",
                f"- ambiguous: {horizon['ambiguous_count']}",
                f"- insufficient: {horizon['insufficient_horizon_count']}",
                f"- positive anchors on 2-of-3 bars: "
                f"{horizon['positive_anchors_on_2of3_bars']} "
                f"({horizon['positive_anchors_on_2of3_share']:.4%})",
                f"- clusters: {clusters['total']} "
                f"(up {clusters['up']}, down {clusters['down']}, mixed {clusters['mixed']})",
                "- per-year clusters: "
                + ", ".join(f"{y}: {n}" for y, n in clusters["per_year"].items()),
            ]
        )
    lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    bars_start = int(
        datetime.fromisoformat(args.bars_start.replace("Z", "+00:00")).timestamp()
    )
    binance = load_kline_dir(args.data_root / SPOT_SUBDIR)
    kraken_paths = [args.data_root / rel for rel in KRAKEN_CSVS]
    kraken = load_kraken_csvs(kraken_paths, start_ts=bars_start)
    coinbase = load_candle_dir(args.data_root / COINBASE_DIR, start_ts=bars_start)
    index = build_median_index([binance, kraken, coinbase], min_members=2)

    klines = index.klines
    first_ts, last_ts = int(klines.timestamp[0]), int(klines.timestamp[-1])
    calendar_minutes = (last_ts - first_ts) // STEP_SECONDS + 1
    coverage = {
        "bars": int(klines.n_rows),
        "first": iso_utc(first_ts),
        "last": iso_utc(last_ts),
        "bars_3of3": int(np.count_nonzero(index.venue_count == 3)),
        "bars_2of3": int(np.count_nonzero(index.venue_count == 2)),
        "missing_minutes": int(calendar_minutes - klines.n_rows),
    }
    parameters = {
        "members": ["binance_btcusdt_spot", "kraken_xbtusd_spot", "coinbase_btcusd_spot"],
        "min_members": 2,
        "construction": "componentwise_median",
        "label_semantics": "wall_clock_first_passage",
        "threshold": args.threshold,
        "horizons_seconds": list(args.horizons_seconds),
        "decision_timestamp": "interval_end",
        "bars_start": args.bars_start,
        "kraken_csvs": list(KRAKEN_CSVS),
    }
    results = [
        label_horizon(index, horizon_seconds=horizon, threshold=args.threshold)
        for horizon in args.horizons_seconds
    ]
    payload = {
        "parameters": parameters,
        "coverage": coverage,
        "horizons": [summary for summary, _ in results],
    }
    clusters_payload = {
        "parameters": parameters,
        "horizons": [
            {
                "horizon_seconds": summary["horizon_seconds"],
                "horizon_bars": summary["horizon_seconds"] // STEP_SECONDS,
                "clusters": records,
            }
            for summary, records in results
        ],
    }
    out_dir = args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    catalogue_path = out_dir / "index_catalogue.json"
    clusters_path = out_dir / "index_clusters.json"
    summary_path = out_dir / "INDEX_SUMMARY.md"
    catalogue_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    clusters_path.write_text(json.dumps(clusters_payload, indent=2) + "\n", encoding="utf-8")
    summary_path.write_text(render_summary(payload), encoding="utf-8")
    input_files = (
        sorted((args.data_root / SPOT_SUBDIR).glob("*.zip"))
        + kraken_paths
        + sorted((args.data_root / COINBASE_DIR).glob("candles_*.json"))
    )
    sidecar = write_provenance_sidecar(
        out_dir,
        "index_catalogue",
        build_provenance(
            repo_root=REPO_ROOT,
            config=parameters,
            inputs=input_files,
            outputs=[catalogue_path, clusters_path, summary_path],
            input_base=args.data_root,
            output_base=out_dir,
        ),
    )
    for summary, _ in results:
        clusters = summary["clusters"]
        print(
            f"horizon {summary['horizon_seconds'] // 60}m: "
            f"{summary['positive_count']} positive anchors, "
            f"{clusters['total']} clusters "
            f"(up {clusters['up']}, down {clusters['down']}, mixed {clusters['mixed']})"
        )
    print(f"Wrote {catalogue_path}, {clusters_path}, {summary_path}")
    print(f"Wrote {sidecar}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
