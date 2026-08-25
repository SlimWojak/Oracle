#!/usr/bin/env python3
"""Run the one authorized frozen EXP-004 M0 rung under D-032/D-033.

Development mode is an effect firewall and cannot construct a timestamp or
outcome at or after 2024-01-01.  Full mode is fail-closed: it requires a clean
checkout at an explicit immutable SHA and consumes a one-shot local receipt
before any OOS outcome is constructed.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import numpy as np

from oracle_research.binance_klines import load_kline_dir
from oracle_research.coinbase_candles import load_candle_dir
from oracle_research.consolidated_index import build_median_index
from oracle_research.exp004_m0_evaluation import evaluate_m0, fit_m0
from oracle_research.exp004_m0_model import BOOTSTRAP_DRAWS, BOOTSTRAP_SEED
from oracle_research.exp004_m0_population import (
    HORIZONS,
    LABEL_FAMILIES,
    M0_COLUMNS,
    build_population,
)
from oracle_research.kraken_klines import load_kraken_csvs
from oracle_research.provenance import (
    build_provenance,
    canonical_config_sha256,
    sha256_file,
    write_provenance_sidecar,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
SOURCE_MANIFEST = REPO_ROOT / "reports/exp000/index_catalogue.provenance.json"
FIXED_CLUSTERS = REPO_ROOT / "reports/exp000/index_clusters.json"
CONFIG_PATH = REPO_ROOT / "configs/v0.yaml"
P5_BRIEF = REPO_ROOT / "docs/briefs/2026-08-25-p5-eval-unit.md"
P6_BRIEF = REPO_ROOT / "docs/briefs/2026-08-25-p6-implementation-freeze.md"
SPOT_SUBDIR = "raw/binance_vision/spot/monthly/klines/BTCUSDT/1m"
COINBASE_SUBDIR = "raw/coinbase/candles/BTC-USD/1m"
KRAKEN_FILES = (
    "raw/kraken/ohlcvt/XBTUSD_1.csv",
    "raw/kraken/ohlcvt/XBTUSD_1_Q1_2026.csv",
    "derived/kraken/XBTUSD_1_2026AprJul_from_trades_v2.csv",
)
INDEX_START_TIMESTAMP = int(
    datetime.fromisoformat("2020-01-01T00:00:00+00:00").timestamp()
)


def _utc_now() -> str:
    return datetime.now(tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _git(*args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def require_frozen_checkout(expected_sha: str) -> None:
    """Reject any nonexact or dirty full-run checkout."""

    if len(expected_sha) != 40 or any(
        character not in "0123456789abcdef" for character in expected_sha
    ):
        raise RuntimeError("--expected-sha must be a full lowercase Git SHA")
    actual = _git("rev-parse", "HEAD")
    if actual != expected_sha:
        raise RuntimeError(f"HEAD {actual} does not match frozen SHA {expected_sha}")
    if _git("status", "--porcelain", "--untracked-files=all"):
        raise RuntimeError("full OOS run requires a clean frozen checkout")


def verify_source_manifest(data_root: Path) -> dict[str, object]:
    """Stream-verify every D-022 source input against its committed D-019 manifest."""

    payload = json.loads(SOURCE_MANIFEST.read_text(encoding="utf-8"))
    entries = payload.get("inputs")
    if not isinstance(entries, list) or not entries:
        raise RuntimeError("D-022 source manifest has no input entries")
    total_bytes = 0
    for entry in entries:
        if not isinstance(entry, dict):
            raise RuntimeError("D-022 source manifest entry is invalid")
        relative = Path(str(entry["path"]))
        if relative.is_absolute() or ".." in relative.parts:
            raise RuntimeError("D-022 source manifest contains an unsafe path")
        path = data_root / relative
        if not path.is_file():
            raise RuntimeError(f"D-022 source input is missing: {relative}")
        expected_bytes = int(entry["bytes"])
        if path.stat().st_size != expected_bytes:
            raise RuntimeError(f"D-022 source input size mismatch: {relative}")
        if sha256_file(path) != str(entry["sha256"]):
            raise RuntimeError(f"D-022 source input hash mismatch: {relative}")
        total_bytes += expected_bytes
    outputs = payload.get("outputs")
    if not isinstance(outputs, list) or not outputs:
        raise RuntimeError("D-022 source manifest has no output entries")
    for entry in outputs:
        if not isinstance(entry, dict):
            raise RuntimeError("D-022 output manifest entry is invalid")
        path = SOURCE_MANIFEST.parent / str(entry["path"])
        if not path.is_file() or path.stat().st_size != int(entry["bytes"]):
            raise RuntimeError(f"D-022 committed output mismatch: {entry['path']}")
        if sha256_file(path) != str(entry["sha256"]):
            raise RuntimeError(f"D-022 committed output hash mismatch: {entry['path']}")
    return {
        "manifest": str(SOURCE_MANIFEST.relative_to(REPO_ROOT)),
        "manifest_sha256": sha256_file(SOURCE_MANIFEST),
        "manifest_repo_commit": payload.get("repo_commit"),
        "verified_input_count": len(entries),
        "verified_input_bytes": total_bytes,
        "verified_output_count": len(outputs),
        "all_entries_verified": True,
    }


def load_d022_index(data_root: Path):
    """Rebuild the exact D-022 median index from the verified source files."""

    binance = load_kline_dir(data_root / SPOT_SUBDIR)
    kraken = load_kraken_csvs(
        [data_root / relative for relative in KRAKEN_FILES],
        start_ts=INDEX_START_TIMESTAMP,
    )
    coinbase = load_candle_dir(
        data_root / COINBASE_SUBDIR,
        start_ts=INDEX_START_TIMESTAMP,
    )
    return build_median_index([binance, kraken, coinbase], min_members=2)


def _runtime() -> dict[str, str]:
    import scipy

    return {
        "python": platform.python_version(),
        "numpy": np.__version__,
        "scipy": scipy.__version__,
        "platform_machine": platform.machine(),
    }


def _frozen_config(stage: str, implementation_sha: str | None) -> dict[str, object]:
    return {
        "experiment": "EXP-004",
        "rung": "M0",
        "stage": stage,
        "implementation_sha": implementation_sha,
        "risk_clock": "exact_utc_hour_interval_end",
        "periods": ["development", "validation", "test_2025", "test_2026"],
        "horizons_seconds": list(HORIZONS),
        "label_families": list(LABEL_FAMILIES),
        "m0_columns_ordered": list(M0_COLUMNS),
        "estimator": "frozen_baseline_category_multinomial_lbfgsb",
        "bootstrap": {"draws": BOOTSTRAP_DRAWS, "seed": BOOTSTRAP_SEED},
        "m1": "BLOCKED_ASOF",
        "later_rungs": "UNAUTHORIZED",
        "contracts": [
            str(P5_BRIEF.relative_to(REPO_ROOT)),
            str(P6_BRIEF.relative_to(REPO_ROOT)),
        ],
    }


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _create_one_shot_receipt(directory: Path, implementation_sha: str) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    receipt = directory / f"exp004_m0_oos_{implementation_sha}.json"
    payload = {
        "experiment": "EXP-004",
        "rung": "M0",
        "implementation_sha": implementation_sha,
        "started_at_utc": _utc_now(),
        "status": "STARTED_CONSUMED",
    }
    descriptor = os.open(receipt, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.write("\n")
    return receipt


def _finish_receipt(receipt: Path, *, status: str, disposition: str | None = None) -> None:
    payload = json.loads(receipt.read_text(encoding="utf-8"))
    payload["finished_at_utc"] = _utc_now()
    payload["status"] = status
    if disposition is not None:
        payload["disposition"] = disposition
    _write_json(receipt, payload)


def _render_result(payload: dict[str, object]) -> str:
    evaluation = payload["evaluation"]
    assert isinstance(evaluation, dict)
    periods = evaluation["periods"]
    assert isinstance(periods, dict)
    lines = [
        "# EXP-004 frozen M0 result",
        "",
        f"**Mechanical disposition:** `{evaluation['disposition']}`",
        "",
        f"- Pre-OOS implementation SHA: `{payload['pre_oos_implementation_sha']}`",
        "- OOS execution: one consumed run from the exact clean SHA above",
        f"- Kappa (six decimals): `{payload['frozen_state']['kappa_six_decimals']}`",
        "- M1: `BLOCKED_ASOF` (not implemented or scored)",
        "- M2+ / later rungs: unauthorized",
        "- News slice: `NEWS_NOT_AVAILABLE` (non-gating)",
        "",
        "## Family results",
        "",
        "| Period | Label | family Brier skill | bootstrap 95% interval |",
        "|---|---|---:|---:|",
    ]
    period_labels = {
        "validation": "validation-2024",
        "test_2025": "test-2025",
        "test_2026": "test-2026-01..07",
    }

    def number(value: object) -> str:
        return "undefined" if value is None else f"{float(value):.6f}"

    for period_key in ("validation", "test_2025", "test_2026"):
        period = periods[period_key]
        for label_family in LABEL_FAMILIES:
            family = period[label_family]
            interval = family["family_skill_bootstrap"]["percentile_95_interval"]
            lines.append(
                f"| {period_labels[period_key]} | {label_family} | "
                f"{family['family_relative_brier_skill']:.6f} | "
                f"[{interval[0]:.6f}, {interval[1]:.6f}] |"
            )
    lines.extend(
        [
            "",
            "## Primary cells",
            "",
            "| Period | Label | Cell | rows | base rate | Brier skill | episodes | "
            "precision | clusters | recall | median lead s |",
            "|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for period_key in ("validation", "test_2025", "test_2026"):
        period = periods[period_key]
        for label_family in LABEL_FAMILIES:
            cells = period[label_family]["cells"]
            for cell_key in ("1h_up", "1h_down", "4h_up", "4h_down"):
                cell = cells[cell_key]
                lead = cell["median_lead_seconds"]
                lead_text = "undefined" if lead is None else f"{lead:.1f}"
                lines.append(
                    f"| {period_labels[period_key]} | {label_family} | {cell_key} | "
                    f"{cell['count']} | "
                    f"{cell['event_rate']:.6f} | {cell['relative_brier_skill']:.6f} | "
                    f"{cell['alert_episode_count']} | {number(cell['episode_precision'])} | "
                    f"{cell['eligible_cluster_count']} | {number(cell['cluster_recall'])} | "
                    f"{lead_text} |"
                )
    lines.extend(
        [
            "",
            "The disposition is the frozen D-033 mechanical rule. There is no pooled-period,",
            "fixed-only, or descriptive-slice rescue and no post-OOS retuning.",
            "",
        ]
    )
    return "\n".join(lines)


def _render_blocked(payload: dict[str, object]) -> str:
    evaluation = payload["evaluation"]
    assert isinstance(evaluation, dict)
    return "\n".join(
        [
            "# EXP-004 frozen M0 result",
            "",
            "**Mechanical disposition:** `BLOCKED`",
            "",
            f"- Pre-OOS implementation SHA: `{payload['pre_oos_implementation_sha']}`",
            f"- Integrity class: `{evaluation['blocked_exception_class']}`",
            f"- Reason: {evaluation['blocked_reason']}",
            "- The one-shot OOS authorization was consumed; no retry is permitted.",
            "- M1 remains `BLOCKED_ASOF` and was not implemented or scored.",
            "",
        ]
    )


def _development_run(args: argparse.Namespace) -> int:
    source_verification = verify_source_manifest(args.data_root)
    index = load_d022_index(args.data_root)
    clusters = json.loads(FIXED_CLUSTERS.read_text(encoding="utf-8"))
    population = build_population(
        end_timestamps=index.klines.timestamp + 60,
        close=index.klines.close,
        high=index.klines.high,
        low=index.klines.low,
        fixed_cluster_payload=clusters,
        stage="development",
    )
    state = fit_m0(population)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "status": "DEVELOPMENT_ONLY_INTEGRITY_PASS",
        "oos_constructed_or_scored": False,
        "source_verification": source_verification,
        "runtime": _runtime(),
        "population_inventory": population.inventory,
        "frozen_state": state.to_dict(),
    }
    state_path = args.out_dir / "m0_development_integrity.json"
    _write_json(state_path, payload)
    print(
        json.dumps(
            {
                "status": payload["status"],
                "artifact": str(state_path),
                "config_sha256": canonical_config_sha256(_frozen_config("development", None)),
            }
        ),
        flush=True,
    )
    return 0


def _full_run(args: argparse.Namespace) -> int:
    assert args.expected_sha is not None
    require_frozen_checkout(args.expected_sha)
    source_verification = verify_source_manifest(args.data_root)
    index = load_d022_index(args.data_root)
    receipt = _create_one_shot_receipt(
        args.data_root / "manifests" / "exp004_m0_one_shot",
        args.expected_sha,
    )
    config = _frozen_config("full", args.expected_sha)
    try:
        clusters = json.loads(FIXED_CLUSTERS.read_text(encoding="utf-8"))
        population = build_population(
            end_timestamps=index.klines.timestamp + 60,
            close=index.klines.close,
            high=index.klines.high,
            low=index.klines.low,
            fixed_cluster_payload=clusters,
            stage="full",
        )
        state = fit_m0(population)
        evaluation = evaluate_m0(population, state)
        payload = {
            "experiment": "EXP-004",
            "rung": "M0",
            "run_status": "COMPLETE_VALID",
            "pre_oos_implementation_sha": args.expected_sha,
            "m1_status": "BLOCKED_ASOF",
            "later_rungs": "UNAUTHORIZED",
            "source_verification": source_verification,
            "runtime": _runtime(),
            "population_inventory": population.inventory,
            "frozen_state": state.to_dict(),
            "evaluation": evaluation,
            "config_sha256": canonical_config_sha256(config),
        }
        args.out_dir.mkdir(parents=True, exist_ok=True)
        state_path = args.out_dir / "m0_frozen_state.json"
        result_path = args.out_dir / "m0_result.json"
        markdown_path = args.out_dir / "m0_result.md"
        _write_json(state_path, state.to_dict())
        _write_json(result_path, payload)
        markdown_path.write_text(_render_result(payload), encoding="utf-8")
        provenance = build_provenance(
            repo_root=REPO_ROOT,
            config=config,
            inputs=[SOURCE_MANIFEST, FIXED_CLUSTERS, CONFIG_PATH, P5_BRIEF, P6_BRIEF],
            outputs=[state_path, result_path, markdown_path],
            input_base=REPO_ROOT,
            output_base=args.out_dir,
        )
        provenance.update(
            {
                "pre_oos_implementation_sha": args.expected_sha,
                "source_manifest_verification": source_verification,
                "runtime": _runtime(),
                "one_shot_oos_execution": True,
                "receipt": "LOCAL_UNCOMMITTED_CONSUMPTION_RECORD",
            }
        )
        write_provenance_sidecar(args.out_dir, "m0_result", provenance)
        _finish_receipt(
            receipt,
            status="COMPLETE_CONSUMED",
            disposition=str(evaluation["disposition"]),
        )
    except Exception as error:
        args.out_dir.mkdir(parents=True, exist_ok=True)
        result_path = args.out_dir / "m0_result.json"
        markdown_path = args.out_dir / "m0_result.md"
        payload = {
            "experiment": "EXP-004",
            "rung": "M0",
            "run_status": "COMPLETE_BLOCKED",
            "pre_oos_implementation_sha": args.expected_sha,
            "m1_status": "BLOCKED_ASOF",
            "later_rungs": "UNAUTHORIZED",
            "source_verification": source_verification,
            "runtime": _runtime(),
            "evaluation": {
                "disposition": "BLOCKED",
                "blocked_exception_class": type(error).__name__,
                "blocked_reason": str(error),
            },
            "config_sha256": canonical_config_sha256(config),
        }
        _write_json(result_path, payload)
        markdown_path.write_text(_render_blocked(payload), encoding="utf-8")
        provenance = build_provenance(
            repo_root=REPO_ROOT,
            config=config,
            inputs=[SOURCE_MANIFEST, FIXED_CLUSTERS, CONFIG_PATH, P5_BRIEF, P6_BRIEF],
            outputs=[result_path, markdown_path],
            input_base=REPO_ROOT,
            output_base=args.out_dir,
        )
        provenance.update(
            {
                "pre_oos_implementation_sha": args.expected_sha,
                "source_manifest_verification": source_verification,
                "runtime": _runtime(),
                "one_shot_oos_execution": True,
                "receipt": "LOCAL_UNCOMMITTED_CONSUMPTION_RECORD",
                "blocked_exception_class": type(error).__name__,
            }
        )
        write_provenance_sidecar(args.out_dir, "m0_result", provenance)
        _finish_receipt(receipt, status="BLOCKED_CONSUMED", disposition="BLOCKED")
        print(
            json.dumps(
                {
                    "status": "COMPLETE_BLOCKED",
                    "disposition": "BLOCKED",
                    "pre_oos_implementation_sha": args.expected_sha,
                    "out_dir": str(args.out_dir),
                }
            ),
            flush=True,
        )
        return 2
    print(
        json.dumps(
            {
                "status": "COMPLETE_VALID",
                "disposition": evaluation["disposition"],
                "pre_oos_implementation_sha": args.expected_sha,
                "out_dir": str(args.out_dir),
            }
        ),
        flush=True,
    )
    return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", required=True, type=Path)
    parser.add_argument("--stage", required=True, choices=("development", "full"))
    parser.add_argument("--out-dir", required=True, type=Path)
    parser.add_argument("--expected-sha")
    args = parser.parse_args(argv)
    if args.stage == "full" and args.expected_sha is None:
        parser.error("full stage requires --expected-sha")
    if args.stage == "development" and args.expected_sha is not None:
        parser.error("development stage rejects --expected-sha")
    return args


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    return _development_run(args) if args.stage == "development" else _full_run(args)


if __name__ == "__main__":
    sys.exit(main())
