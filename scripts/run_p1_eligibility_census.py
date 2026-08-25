#!/usr/bin/env python3
"""P1 path-only eligibility census. No fuel values, no HL mass."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import numpy as np

from oracle_research.batch_labels import DIR_DOWN, DIR_UP, batch_first_passage_time
from oracle_research.binance_klines import load_kline_dir
from oracle_research.coinbase_candles import load_candle_dir
from oracle_research.consolidated_index import build_median_index
from oracle_research.kraken_klines import load_kraken_csvs

SPOT_SUBDIR = "raw/binance_vision/spot/monthly/klines/BTCUSDT/1m"
KRAKEN_CSVS = (
    "raw/kraken/ohlcvt/XBTUSD_1.csv",
    "raw/kraken/ohlcvt/XBTUSD_1_Q1_2026.csv",
    "derived/kraken/XBTUSD_1_2026AprJul_from_trades_v2.csv",
)
COINBASE_DIR = "raw/coinbase/candles/BTC-USD/1m"

BANDS = (
    ("(0,1%)", 0.01),
    ("[1,2%)", 0.02),
    ("[2,4%)", 0.04),
)
WINDOWS = {
    "construct_dev": (datetime(2025, 5, 25, tzinfo=UTC), datetime(2025, 9, 1, tzinfo=UTC)),
    "construct_val": (datetime(2025, 9, 1, tzinfo=UTC), datetime(2026, 1, 1, tzinfo=UTC)),
}


def ts(dt: datetime) -> int:
    return int(dt.timestamp())


def load_index(data_root: Path):
    binance = load_kline_dir(data_root / SPOT_SUBDIR)
    kraken = load_kraken_csvs(tuple(data_root / p for p in KRAKEN_CSVS))
    coinbase = load_candle_dir(data_root / COINBASE_DIR)
    return build_median_index([binance, kraken, coinbase])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", required=True, type=Path)
    parser.add_argument(
        "--clusters",
        type=Path,
        default=Path("reports/exp000/index_clusters.json"),
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("reports/p1_eligibility_census.json"),
    )
    args = parser.parse_args()

    print("loading clusters", flush=True)
    payload = json.loads(args.clusters.read_text())
    print("building median index (one-time)", flush=True)
    index = load_index(args.data_root)
    ts_arr = np.asarray(index.klines.timestamp, dtype=np.int64)
    high = np.asarray(index.klines.high, dtype=np.float64)
    low = np.asarray(index.klines.low, dtype=np.float64)
    close = np.asarray(index.klines.close, dtype=np.float64)
    print(f"index bars={len(ts_arr)} {datetime.fromtimestamp(int(ts_arr[0]), UTC)} .. {datetime.fromtimestamp(int(ts_arr[-1]), UTC)}", flush=True)

    labels_by_key: dict[tuple[int, float], np.ndarray] = {}
    for horizon in (3600, 14400):
        for _name, far_edge in BANDS:
            print(f"labelling H={horizon} far={far_edge}", flush=True)
            lab = batch_first_passage_time(
                ts_arr,
                high,
                low,
                close,
                horizon_seconds=horizon,
                threshold_fraction=far_edge,
            )
            labels_by_key[(horizon, far_edge)] = lab.direction

    ts_to_idx = {int(t): i for i, t in enumerate(ts_arr.tolist())}

    cells: dict[str, dict[str, int]] = {}
    detail: list[dict[str, object]] = []
    for horizon_block in payload["horizons"]:
        horizon = int(horizon_block["horizon_seconds"])
        for window_name, (w0, w1) in WINDOWS.items():
            w0i, w1i = ts(w0), ts(w1)
            pure = [
                c
                for c in horizon_block["clusters"]
                if c["direction"] in {"up", "down"}
                and w0i <= int(c["start_timestamp"]) < w1i
            ]
            for direction in ("down", "up"):
                want = DIR_DOWN if direction == "down" else DIR_UP
                subset = [c for c in pure if c["direction"] == direction]
                for band_name, far_edge in BANDS:
                    direction_arr = labels_by_key[(horizon, far_edge)]
                    n = 0
                    for cluster in subset:
                        start_t = int(cluster["start_timestamp"])
                        end_t = int(cluster["end_timestamp"])
                        t = start_t
                        hit = False
                        while t <= end_t:
                            idx = ts_to_idx.get(t)
                            if idx is not None and direction_arr[idx] == want:
                                hit = True
                                break
                            t += 60
                        if hit:
                            n += 1
                    key = f"{window_name}|{direction}|{band_name}|{horizon}s"
                    cells[key] = {
                        "window": window_name,
                        "direction": direction,
                        "band": band_name,
                        "horizon_seconds": horizon,
                        "pure_clusters_in_window": len(subset),
                        "eligible_clusters": n,
                        "below_15": n < 15,
                    }
                    detail.append(cells[key])
                    print(f"{key} pure={len(subset)} eligible={n}", flush=True)

    any_below = any(row["below_15"] for row in detail)
    report = {
        "status": "SPARSE" if any_below else "COVERED",
        "rule": "pure-direction clusters; earliest T in [start,end] with far-edge first-passage in that direction; no fuel; no HL mass",
        "bands": [b[0] for b in BANDS],
        "any_cell_below_15": any_below,
        "cells": detail,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"status": report["status"], "any_cell_below_15": any_below, "out": str(args.out)}), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
