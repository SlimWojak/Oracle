#!/usr/bin/env python3
"""Run EXP-002/P3 construct-gate scoring.

Phase A provides this harness but does not require running the full tape. When
the external data root is absent, the script writes a MISSING_DATA note instead
of inventing construct-gate numbers.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

from oracle_research.binance_klines import load_kline_dir
from oracle_research.cex_fuel import (
    bars_from_kline_arrays,
    build_cluster_fuel_rows,
    hl_target_for_cluster_row,
    load_cluster_payload,
    load_metrics_dir,
    metrics_rows_from_arrays,
    run_cex_oi_cohort_v0,
)
from oracle_research.coinbase_candles import load_candle_dir
from oracle_research.consolidated_index import build_median_index
from oracle_research.construct_gate import (
    ALL_WINDOWS,
    BOOTSTRAP_DRAWS,
    BOOTSTRAP_SEED,
    CONSTRUCT_DEV,
    CONSTRUCT_VAL,
    PRIMARY_CELL_BANDS,
    PRIMARY_CELL_DIRECTIONS,
    TargetedFuelRow,
    score_construct_gate,
)
from oracle_research.hl_fills_parquet import all_fills_root
from oracle_research.kraken_klines import load_kraken_csvs
from oracle_research.provenance import build_provenance, write_provenance_sidecar

REPO_ROOT = Path(__file__).resolve().parent.parent
SPOT_SUBDIR = "raw/binance_vision/spot/monthly/klines/BTCUSDT/1m"
METRICS_SUBDIR = "raw/binance_vision/futures/um/daily/metrics/BTCUSDT"
KRAKEN_CSVS = (
    "raw/kraken/ohlcvt/XBTUSD_1.csv",
    "raw/kraken/ohlcvt/XBTUSD_1_Q1_2026.csv",
    "derived/kraken/XBTUSD_1_2026AprJul_from_trades_v2.csv",
)
COINBASE_DIR = "raw/coinbase/candles/BTC-USD/1m"


def load_index(data_root: Path):
    """Build the D-022 median index exactly as the P1 eligibility census does."""

    binance = load_kline_dir(data_root / SPOT_SUBDIR)
    kraken = load_kraken_csvs(tuple(data_root / path for path in KRAKEN_CSVS))
    coinbase = load_candle_dir(data_root / COINBASE_DIR)
    return build_median_index([binance, kraken, coinbase])


def _config(args: argparse.Namespace) -> dict[str, object]:
    return {
        "gate": "exp002_p3_construct_gate_phase_a",
        "script": "scripts/run_p3_construct_gate.py",
        "data_root": str(args.data_root),
        "clusters": str(args.clusters),
        "metrics_dir": str(args.data_root / METRICS_SUBDIR),
        "hl_fills_root": str(all_fills_root(args.data_root)),
        "primary_cells": {
            "horizon_seconds": 14_400,
            "directions": [direction.value for direction in PRIMARY_CELL_DIRECTIONS],
            "bands": list(PRIMARY_CELL_BANDS),
        },
        "windows": [
            {
                "key": window.key,
                "label": window.label,
                "start_timestamp": window.start_timestamp,
                "end_timestamp": window.end_timestamp,
                "min_cell_count": window.min_cell_count,
            }
            for window in ALL_WINDOWS
        ],
        "bootstrap": {"seed": BOOTSTRAP_SEED, "draws": args.bootstrap_draws},
        "target": "book_hitting_usd",
        "backstop_policy": "reported only; never enters Spearman",
    }


def _config_hash(config: dict[str, object]) -> str:
    encoded = json.dumps(config, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _write_report(
    *,
    out_dir: Path,
    payload: dict[str, object],
    markdown: str,
    config: dict[str, object],
    inputs: list[Path],
) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "construct_gate.json"
    md_path = out_dir / "construct_gate.md"
    json_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    md_path.write_text(markdown, encoding="utf-8")
    provenance = build_provenance(
        repo_root=REPO_ROOT,
        config={**config, "config_sha256": _config_hash(config)},
        inputs=inputs,
        outputs=[json_path, md_path],
        input_base=REPO_ROOT,
        output_base=out_dir,
    )
    provenance["config_sha256"] = _config_hash(config)
    provenance["input_manifest_identifiers"] = {
        "data_root": config["data_root"],
        "metrics_dir": config["metrics_dir"],
        "hl_fills_root": config["hl_fills_root"],
        "clusters": config["clusters"],
    }
    write_provenance_sidecar(out_dir, "construct_gate", provenance)


def _missing_paths(args: argparse.Namespace) -> list[Path]:
    candidates = [
        args.data_root,
        args.data_root / SPOT_SUBDIR,
        args.data_root / METRICS_SUBDIR,
        args.data_root / COINBASE_DIR,
        all_fills_root(args.data_root),
        args.clusters,
    ]
    candidates.extend(args.data_root / path for path in KRAKEN_CSVS)
    return [path for path in candidates if not path.exists()]


def _render_missing(payload: dict[str, object]) -> str:
    missing = "\n".join(f"- `{path}`" for path in payload["missing_paths"])
    return "\n".join(
        [
            "# EXP-002 construct gate",
            "",
            "**Status:** MISSING_DATA",
            "",
            "Phase A did not run the full tape. Required external data paths are absent:",
            "",
            missing,
            "",
            "No PASS/FAIL numbers were produced.",
            "",
        ]
    )


def _render_scored(payload: dict[str, object]) -> str:
    result = payload["result"]
    assert isinstance(result, dict)
    lines = [
        "# EXP-002 construct gate",
        "",
        f"**Harness status:** {payload['harness_status']}",
        "",
        "Mechanical harness output only; this is not a ledger verdict.",
        "",
        f"- Target: `{payload['target']}`",
        "- Backstop mass is reported only and never enters Spearman.",
        f"- Target-attached rows: {payload['targeted_row_count']}",
        "",
        "## Family statistics",
        "",
        "| Window | F_vs_oi | F_vs_path | F_static | integrity |",
        "|---|---:|---:|---:|---|",
    ]
    for key in ("construct_dev", "construct_val"):
        block = result[key]
        family = block["family"]
        lines.append(
            f"| {block['window']} | {family['F_vs_oi']} | {family['F_vs_path']} "
            f"| {family['F_static']} | {block['integrity_ok']} |"
        )
    floor_lock = result["floor_lock"]
    lines.extend(
        [
            "",
            "## Floor",
            "",
            f"- Locked: `{floor_lock['locked']}`",
            f"- Floor: `{floor_lock['floor']}`",
            "",
            "## PASS clauses",
            "",
        ]
    )
    for name, passed in result["pass_clauses"].items():
        lines.append(f"- `{name}`: {passed}")
    if result["null_reasons"]:
        lines.extend(["", "## NULL reasons", ""])
        for reason in result["null_reasons"]:
            lines.append(f"- {reason}")
    lines.append("")
    return "\n".join(lines)


def _attach_targets(rows, table_root: Path) -> list[TargetedFuelRow]:
    targeted: list[TargetedFuelRow] = []
    for index, row in enumerate(rows, start=1):
        print(f"attaching HL target {index}/{len(rows)}", flush=True)
        target = hl_target_for_cluster_row(row, table_root=table_root)
        targeted.append(TargetedFuelRow.from_p2(row, target))
    return targeted


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", required=True, type=Path)
    parser.add_argument(
        "--clusters",
        type=Path,
        default=Path("reports/exp000/index_clusters.json"),
    )
    parser.add_argument("--out-dir", type=Path, default=Path("reports/exp002"))
    parser.add_argument("--bootstrap-draws", type=int, default=BOOTSTRAP_DRAWS)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    config = _config(args)
    script_path = Path(__file__).resolve()
    inputs = [path for path in [args.clusters.resolve(), script_path] if path.exists()]
    missing = _missing_paths(args)
    if missing:
        payload = {
            "status": "MISSING_DATA",
            "harness_status": "NULL",
            "note": (
                "Phase A dry-run note; full tape was not run and no PASS numbers "
                "were invented."
            ),
            "missing_paths": [str(path) for path in missing],
            "config": config,
        }
        _write_report(
            out_dir=args.out_dir,
            payload=payload,
            markdown=_render_missing(payload),
            config=config,
            inputs=inputs,
        )
        print(json.dumps({"status": "MISSING_DATA", "out_dir": str(args.out_dir)}), flush=True)
        return 0

    print("building D-022 median index", flush=True)
    index = load_index(args.data_root)
    bars = bars_from_kline_arrays(
        index.klines.timestamp,
        index.klines.high,
        index.klines.low,
        index.klines.close,
    )
    price_by_timestamp = {bar.timestamp: bar.close for bar in bars}

    print("loading Binance UM metrics", flush=True)
    metrics = load_metrics_dir(args.data_root / METRICS_SUBDIR)
    snapshots = run_cex_oi_cohort_v0(metrics_rows_from_arrays(metrics), price_by_timestamp)

    print("building P2 cluster fuel rows", flush=True)
    clusters_payload = load_cluster_payload(args.clusters)
    fuel_rows = build_cluster_fuel_rows(clusters_payload, bars, snapshots)
    print(f"cluster fuel rows={len(fuel_rows)}", flush=True)

    print("attaching Hyperliquid book/backstop targets", flush=True)
    targeted_rows = _attach_targets(fuel_rows, all_fills_root(args.data_root))
    result = score_construct_gate(targeted_rows, bootstrap_draws=args.bootstrap_draws)

    payload = {
        "status": "SCORED",
        "harness_status": result.harness_status,
        "note": "Mechanical harness output only; not a ledger verdict.",
        "target": "book_hitting_usd",
        "targeted_row_count": len(targeted_rows),
        "construct_dev_window": CONSTRUCT_DEV.label,
        "construct_val_window": CONSTRUCT_VAL.label,
        "config": config,
        "result": result.to_dict(),
        "rows": [row.to_dict() for row in targeted_rows],
    }
    _write_report(
        out_dir=args.out_dir,
        payload=payload,
        markdown=_render_scored(payload),
        config=config,
        inputs=inputs,
    )
    print(
        json.dumps(
            {
                "status": "SCORED",
                "harness_status": result.harness_status,
                "out_dir": str(args.out_dir),
            }
        ),
        flush=True,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
