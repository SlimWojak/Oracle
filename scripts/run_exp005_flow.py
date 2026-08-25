#!/usr/bin/env python3
"""Run the frozen two-stage EXP-005 flow-compression replication.

Development writes only to an external state directory. Full execution replays
all pre-effect identities, consumes one immutable local receipt, then builds
and scores OOS outcomes exactly once.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import importlib.util
import json
import os
import platform
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType
from typing import Any

import numpy as np

from oracle_research.exp004_m0_model import (
    BOOTSTRAP_DRAWS,
    BOOTSTRAP_SEED,
    FINAL_GRADIENT_TOLERANCE,
    OPTIMIZER_FTOL,
    OPTIMIZER_GTOL,
    OPTIMIZER_MAXITER,
    RIDGE_PENALTY,
)
from oracle_research.exp004_m0_population import (
    HORIZONS,
    LABEL_FAMILIES,
    M0_COLUMNS,
    build_population,
)
from oracle_research.exp005_flow import (
    M0_FLOW_COLUMNS,
    availability_report,
    build_m0_features,
    ordered_timestamp_sha256,
)
from oracle_research.exp005_flow_evaluation import (
    FAIL_SKILL,
    LEAD_GATES,
    MIN_CLUSTERS,
    PASS_RECALL,
    PASS_SKILL,
    PRECISION_MULTIPLE,
    FrozenFlowState,
    evaluate_flow_models,
    fit_flow_models,
)
from oracle_research.exp005_flow_population import build_flow_population
from oracle_research.provenance import canonical_config_sha256, file_entry, sha256_file

REPO_ROOT = Path(__file__).resolve().parent.parent
AUDIT_SCRIPT = REPO_ROOT / "scripts" / "audit_exp005_source.py"
AUDIT_REPORT = REPO_ROOT / "reports" / "exp005" / "source_readiness.json"
AUDIT_PROVENANCE = REPO_ROOT / "reports" / "exp005" / "source_readiness.provenance.json"
FIXED_CLUSTERS = REPO_ROOT / "reports" / "exp000" / "index_clusters.json"
CONFIG_PATH = REPO_ROOT / "configs" / "v0.yaml"
BRIEF_PATH = REPO_ROOT / "docs" / "briefs" / "2026-08-25-exp005-flow-compression-replication.md"

DEVELOPMENT_CUTOFF = int(datetime(2024, 1, 1, tzinfo=UTC).timestamp())
STATE_FILENAME = "exp005_development_state.json"
RECEIPT_DIRECTORY = Path("manifests/exp005_one_shot")
RECEIPT_FILENAME = "EXP-005.receipt.json"
COMPLETION_FILENAME = "EXP-005.completion.json"
REPORT_FILENAMES = ("frozen_state.json", "result.json", "result.md", "result.provenance.json")
SCHEMA_VERSION = "exp005_one_shot_v1"


class RunIntegrityError(RuntimeError):
    """A fail-closed EXP-005 lifecycle or provenance error."""


def _utc_now() -> str:
    return datetime.now(tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _canonical_json(payload: object) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _payload_sha256(payload: object) -> str:
    return hashlib.sha256(_canonical_json(payload).encode()).hexdigest()


def _pretty_json(payload: object) -> str:
    return json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n"


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise RunIntegrityError(f"invalid required JSON artifact: {path.name}") from error
    if not isinstance(payload, dict):
        raise RunIntegrityError(f"required JSON artifact is not an object: {path.name}")
    return payload


def _exclusive_write(path: Path, text: str) -> None:
    """Create one file with O_EXCL; never overwrite evidence or receipts."""

    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
    except Exception:
        with contextlib.suppress(OSError):
            path.unlink(missing_ok=True)
        raise


def _exclusive_json(path: Path, payload: object) -> None:
    _exclusive_write(path, _pretty_json(payload))


def _git(*args: str, repo_root: Path = REPO_ROOT) -> str:
    try:
        result = subprocess.run(
            ["git", *args], cwd=repo_root, check=True, capture_output=True, text=True
        )
    except subprocess.CalledProcessError as error:
        raise RunIntegrityError(f"git integrity check failed: {' '.join(args)}") from error
    return result.stdout.strip()


def checkout_snapshot(*, require_clean: bool = True) -> dict[str, object]:
    head = _git("rev-parse", "HEAD")
    tree = _git("rev-parse", "HEAD^{tree}")
    clean = not _git("status", "--porcelain=v1", "--untracked-files=all")
    if require_clean and not clean:
        raise RunIntegrityError("EXP-005 requires a completely clean checkout")
    return {"commit": head, "tree": tree, "clean": clean}


def require_sealed_checkout(expected_sha: str, envelope: dict[str, Any]) -> dict[str, object]:
    """Require an empty seal immediately above the development implementation."""

    snapshot = checkout_snapshot(require_clean=True)
    if snapshot["commit"] != expected_sha:
        raise RunIntegrityError("HEAD does not equal the exact pre-OOS seal SHA")
    development = envelope.get("development_implementation")
    if not isinstance(development, dict):
        raise RunIntegrityError("development implementation identity is missing")
    parent = _git("rev-parse", f"{expected_sha}^")
    if parent != development.get("commit"):
        raise RunIntegrityError("pre-OOS seal is not the child of the development SHA")
    if snapshot["tree"] != development.get("tree"):
        raise RunIntegrityError("pre-OOS seal tree differs from the development tree")
    if _git("diff", "--name-only", parent, expected_sha):
        raise RunIntegrityError("pre-OOS seal commit is not tree-empty")
    return snapshot


def _load_audit_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("oracle_exp005_source_audit", AUDIT_SCRIPT)
    if spec is None or spec.loader is None:
        raise RunIntegrityError("cannot load the banked EXP-005 source auditor")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _runtime() -> dict[str, object]:
    try:
        import scipy

        scipy_version = scipy.__version__
    except ImportError:
        scipy_version = "NOT_AVAILABLE"
    return {
        "python": platform.python_version(),
        "numpy": np.__version__,
        "scipy": scipy_version,
        "platform_system": platform.system(),
        "platform_machine": platform.machine(),
        "execution_host_role": "REMOTE_HEADLESS_DATA_HOST",
    }


def banked_checkpoint_identity() -> dict[str, object]:
    """Validate and freeze the committed Checkpoint A identity."""

    report = _read_json(AUDIT_REPORT)
    provenance = _read_json(AUDIT_PROVENANCE)
    if (
        report.get("experiment") != "EXP-005"
        or report.get("checkpoint_a_disposition") != "CLEARED_CHECKPOINT_A"
        or report.get("effect_inspection_performed") is not False
        or report.get("source_integrity_clear") is not True
    ):
        raise RunIntegrityError("banked Checkpoint A is not a cleared pre-effect audit")
    if provenance.get("checkpoint_a_disposition") != "CLEARED_CHECKPOINT_A":
        raise RunIntegrityError("Checkpoint A provenance disposition changed")
    audit_config_sha = str(report.get("audit_config_sha256"))
    if provenance.get("config_sha256") != audit_config_sha:
        raise RunIntegrityError("Checkpoint A config identities disagree")
    ordered_hashes = provenance.get("ordered_support_hashes")
    expected_periods = {"development", "validation_2024", "test_2025", "test_2026_01_07"}
    if not isinstance(ordered_hashes, dict) or set(ordered_hashes) != expected_periods:
        raise RunIntegrityError("Checkpoint A ordered feature-support family changed")
    return {
        "report_sha256": sha256_file(AUDIT_REPORT),
        "provenance_sha256": sha256_file(AUDIT_PROVENANCE),
        "audit_config_sha256": audit_config_sha,
        "config_file_sha256": sha256_file(CONFIG_PATH),
        "brief_sha256": sha256_file(BRIEF_PATH),
        "fixed_cluster_artifact_sha256": sha256_file(FIXED_CLUSTERS),
        "selected_um_archive_identities_sha256": report["manifest"][
            "selected_archive_identities_sha256"
        ],
        "um_manifest_sha256": report["manifest"]["sha256"],
        "d022_manifest_sha256": report["d022_source_inputs"]["sha256"],
        "d022_ordered_input_identity_sha256": report["d022_source_inputs"][
            "ordered_input_identity_sha256"
        ],
        "ordered_feature_support_hashes": ordered_hashes,
    }


def _index_summary(index: object, end_timestamps: np.ndarray) -> dict[str, object]:
    venue_count = np.asarray(index.venue_count)
    return {
        "rows": int(index.klines.n_rows),
        "rows_3_of_3": int(np.count_nonzero(venue_count == 3)),
        "rows_2_of_3": int(np.count_nonzero(venue_count == 2)),
        "interval_end_support_sha256": ordered_timestamp_sha256(end_timestamps),
    }


def replay_pre_effect_sources(data_root: Path, banked: dict[str, object]) -> dict[str, object]:
    """Rebuild source-only flow/M0 masks and match every banked support hash."""

    audit = _load_audit_module()
    identities = tuple(audit.expected_um_archive_identities())
    periods = tuple(audit.DEFAULT_PERIODS)
    config = audit.audit_config(identities, periods)
    if canonical_config_sha256(config) != banked["audit_config_sha256"]:
        raise RunIntegrityError("replayed Checkpoint A configuration differs")
    hours = tuple(hour for period in periods for hour in period.hours())
    manifest, paths = audit.verify_um_manifest(data_root=data_root, identities=identities)
    flow, source_report = audit.audit_um_archives(paths, hours)
    d022 = audit.verify_d022_source_inputs(data_root=data_root, repo_root=REPO_ROOT)
    if not audit._um_source_integrity_clear(  # noqa: SLF001 - frozen banked auditor
        manifest=manifest, archive_paths=paths, source_report=source_report
    ):
        raise RunIntegrityError("replayed UM source integrity did not clear")
    if d022.get("all_inputs_verified") is not True:
        raise RunIntegrityError("replayed D-022 source integrity did not clear")
    if (
        manifest.get("selected_archive_identities_sha256")
        != banked["selected_um_archive_identities_sha256"]
        or manifest.get("sha256") != banked["um_manifest_sha256"]
        or d022.get("sha256") != banked["d022_manifest_sha256"]
        or d022.get("ordered_input_identity_sha256") != banked["d022_ordered_input_identity_sha256"]
    ):
        raise RunIntegrityError("replayed source identities differ from Checkpoint A")

    index = audit.load_d022_index(data_root)
    end_timestamps = np.asarray(index.klines.timestamp, dtype=np.int64) + 60
    m0 = build_m0_features(
        end_timestamps=end_timestamps,
        close=index.klines.close,
        high=index.klines.high,
        low=index.klines.low,
        candidate_hours=hours,
    )
    availability = availability_report(
        periods=periods, flow_values=flow.values, m0_values=m0.values
    )
    replayed_hashes = {
        period.name: {
            "candidate": availability["periods"][period.name]["candidate_support_sha256"],
            "flow": availability["periods"][period.name]["flow"]["ordered_support_sha256"],
            "m0": availability["periods"][period.name]["m0_exact_seven_columns"][
                "ordered_support_sha256"
            ],
            "joint": availability["periods"][period.name]["m0_flow_joint"][
                "ordered_support_sha256"
            ],
            "d023_four_hour_boundary_purge": availability["periods"][period.name][
                "d023_four_hour_boundary_purge"
            ]["ordered_support_sha256"],
        }
        for period in periods
    }
    if replayed_hashes != banked["ordered_feature_support_hashes"]:
        raise RunIntegrityError("replayed pre-effect feature-support masks changed")
    banked_report = _read_json(AUDIT_REPORT)
    if (
        manifest != banked_report.get("manifest")
        or source_report != banked_report.get("um_kline_source")
        or flow.aligned_five_minute_census != banked_report.get("aligned_five_minute_census")
        or flow.hourly_feature_census != banked_report.get("hourly_flow_feature_census")
        or availability != banked_report.get("availability")
        or d022 != banked_report.get("d022_source_inputs")
    ):
        raise RunIntegrityError("replayed Checkpoint A census differs from banked evidence")
    index_summary = _index_summary(index, end_timestamps)
    for key, value in index_summary.items():
        if banked_report["d022_index"].get(key) != value:
            raise RunIntegrityError(f"replayed D-022 index field changed: {key}")
    return {
        "flow_values": dict(flow.values),
        "index": index,
        "end_timestamps": end_timestamps,
        "summary": {
            "source_integrity_clear": True,
            "coverage_clearance": availability["coverage_clearance"],
            "selected_um_archives": manifest["selected_integrity_valid"],
            "d022_verified_inputs": d022["verified_input_count"],
            "index": index_summary,
            "ordered_feature_support_hashes": replayed_hashes,
        },
    }


def filter_development_clusters(
    payload: dict[str, object], *, cutoff: int = DEVELOPMENT_CUTOFF
) -> tuple[dict[str, object], dict[str, object]]:
    """Retain only the chronological cluster prefix wholly before the cutoff."""

    parameters = payload.get("parameters")
    horizons = payload.get("horizons")
    if not isinstance(parameters, dict) or not isinstance(horizons, list):
        raise RunIntegrityError("fixed cluster artifact has an invalid shape")
    filtered_blocks: list[dict[str, object]] = []
    counts: dict[str, object] = {}
    for raw_block in horizons:
        if not isinstance(raw_block, dict) or not isinstance(raw_block.get("clusters"), list):
            raise RunIntegrityError("fixed cluster horizon block is invalid")
        retained: list[dict[str, object]] = []
        for raw_cluster in raw_block["clusters"]:
            if not isinstance(raw_cluster, dict):
                raise RunIntegrityError("fixed cluster record is invalid")
            start = int(raw_cluster["start_timestamp"])
            end = int(raw_cluster["end_timestamp"])
            if start < cutoff and end < cutoff:
                retained.append(dict(raw_cluster))
        block = {key: value for key, value in raw_block.items() if key != "clusters"}
        block["clusters"] = retained
        filtered_blocks.append(block)
        horizon = str(int(raw_block["horizon_seconds"]))
        counts[horizon] = {
            "retained": len(retained),
            "max_start_timestamp": max(
                (int(record["start_timestamp"]) for record in retained), default=None
            ),
            "max_end_timestamp": max(
                (int(record["end_timestamp"]) for record in retained), default=None
            ),
        }
    return {"parameters": dict(parameters), "horizons": filtered_blocks}, counts


def development_firewall(
    *,
    end_timestamps: np.ndarray,
    flow_values: dict[int, float],
    population: object,
    cutoff: int = DEVELOPMENT_CUTOFF,
) -> dict[str, object]:
    """Prove every constructed development object is strictly pre-cutoff."""

    timestamps = np.asarray(end_timestamps, dtype=np.int64)
    if timestamps.size == 0 or int(np.max(timestamps)) >= cutoff:
        raise RunIntegrityError("development source arrays reach the OOS cutoff")
    if not flow_values or max(flow_values) >= cutoff:
        raise RunIntegrityError("development flow mapping reaches the OOS cutoff")
    if not population.rows or any(row.timestamp >= cutoff for row in population.rows):
        raise RunIntegrityError("development population rows reach the OOS cutoff")
    if {row.period for row in population.rows} != {"development"}:
        raise RunIntegrityError("development population contains an OOS period")
    passages = [
        outcome.passage_timestamp
        for row in population.rows
        for outcome in row.outcomes.values()
        if outcome.passage_timestamp is not None
    ]
    if passages and max(passages) >= cutoff:
        raise RunIntegrityError("development outcome passage reaches the OOS cutoff")
    if any(
        cluster.start_timestamp >= cutoff or cluster.end_timestamp >= cutoff
        for cluster in population.clusters
    ):
        raise RunIntegrityError("development cluster reaches the OOS cutoff")
    return {
        "cutoff_exclusive": cutoff,
        "oos_outcomes_or_effects_constructed": False,
        "source_row_count": int(timestamps.size),
        "source_max_interval_end": int(np.max(timestamps)),
        "flow_value_count": len(flow_values),
        "flow_max_timestamp": max(flow_values),
        "population_row_count": len(population.rows),
        "population_max_timestamp": max(row.timestamp for row in population.rows),
        "passage_count": len(passages),
        "passage_max_timestamp": max(passages, default=None),
        "cluster_count": len(population.clusters),
        "cluster_max_end_timestamp": max(
            (c.end_timestamp for c in population.clusters), default=None
        ),
    }


def load_frozen_envelope(state_dir: Path) -> tuple[dict[str, Any], FrozenFlowState, str]:
    path = state_dir / STATE_FILENAME
    envelope = _read_json(path)
    if envelope.get("schema_version") != SCHEMA_VERSION or envelope.get("experiment") != "EXP-005":
        raise RunIntegrityError("external development envelope identity changed")
    state_payload = envelope.get("frozen_state")
    if not isinstance(state_payload, dict):
        raise RunIntegrityError("external development envelope has no frozen state")
    state = FrozenFlowState.from_dict(state_payload)
    if state.sha256 != envelope.get("frozen_state_sha256"):
        raise RunIntegrityError("external frozen-state SHA changed")
    unsigned = {k: v for k, v in envelope.items() if k != "envelope_payload_sha256"}
    if envelope.get("envelope_payload_sha256") != _payload_sha256(unsigned):
        raise RunIntegrityError("external development envelope was modified")
    return envelope, state, sha256_file(path)


def _development_run(args: argparse.Namespace) -> int:
    checkout = checkout_snapshot(require_clean=True)
    banked = banked_checkpoint_identity()
    replay = replay_pre_effect_sources(args.data_root, banked)
    index = replay["index"]
    all_ends = replay["end_timestamps"]
    keep = all_ends < DEVELOPMENT_CUTOFF
    end_timestamps = all_ends[keep]
    close = np.asarray(index.klines.close)[keep]
    high = np.asarray(index.klines.high)[keep]
    low = np.asarray(index.klines.low)[keep]
    flow_values = {t: v for t, v in replay["flow_values"].items() if t < DEVELOPMENT_CUTOFF}
    cluster_payload, cluster_firewall = filter_development_clusters(_read_json(FIXED_CLUSTERS))
    population = build_population(
        end_timestamps=end_timestamps,
        close=close,
        high=high,
        low=low,
        fixed_cluster_payload=cluster_payload,
        stage="development",
    )
    firewall = development_firewall(
        end_timestamps=end_timestamps, flow_values=flow_values, population=population
    )
    paired = build_flow_population(population, flow_values)
    state = fit_flow_models(paired)
    state.validate()
    envelope: dict[str, object] = {
        "schema_version": SCHEMA_VERSION,
        "experiment": "EXP-005",
        "stage": "DEVELOPMENT_ONLY_FIREWALL",
        "created_at_utc": _utc_now(),
        "development_implementation": checkout,
        "banked_checkpoint_a": banked,
        "replayed_pre_effect_sources": replay["summary"],
        "development_firewall": {**firewall, "fixed_clusters": cluster_firewall},
        "column_orders": {"M0_COMMON": list(M0_COLUMNS), "M0_FLOW": list(M0_FLOW_COLUMNS)},
        "model_bundle_count": len(state.bundles),
        "fresh_model_count": 2 * len(state.bundles),
        "development_support_identifiers": [s.to_dict() for s in state.support_identifiers],
        "runtime": _runtime(),
        "frozen_state_sha256": state.sha256,
        "frozen_state": state.to_dict(),
        "oos_score_support_identifiers_frozen": False,
        "oos_constructed_or_scored": False,
    }
    envelope["envelope_payload_sha256"] = _payload_sha256(envelope)
    state_path = args.state_dir / STATE_FILENAME
    _exclusive_json(state_path, envelope)
    print(
        _canonical_json(
            {
                "status": "DEVELOPMENT_ONLY_FIREWALL_PASS",
                "development_sha": checkout["commit"],
                "tree": checkout["tree"],
                "frozen_state_sha256": state.sha256,
                "envelope_sha256": sha256_file(state_path),
            }
        ),
        flush=True,
    )
    return 0


def create_consumption_receipt(
    data_root: Path,
    *,
    expected_sha: str,
    tree: str,
    development_sha: str,
    frozen_state_sha256: str,
    envelope_sha256: str,
) -> Path:
    """Consume the single experiment-wide OOS authorization atomically."""

    receipt = data_root / RECEIPT_DIRECTORY / RECEIPT_FILENAME
    _exclusive_json(
        receipt,
        {
            "schema_version": SCHEMA_VERSION,
            "experiment": "EXP-005",
            "status": "STARTED_CONSUMED",
            "consumed_at_utc": _utc_now(),
            "pre_oos_sha": expected_sha,
            "pre_oos_tree": tree,
            "development_sha": development_sha,
            "frozen_state_sha256": frozen_state_sha256,
            "development_envelope_sha256": envelope_sha256,
        },
    )
    return receipt


def _sanitize_error(error: Exception, *, data_root: Path) -> str:
    text = str(error).replace(str(data_root), "<data_root>").replace(str(REPO_ROOT), "<repo>")
    return " ".join(text.split())[:1000]


def _render_result(payload: dict[str, object]) -> str:
    evaluation = payload["evaluation"]
    periods = evaluation.get("periods", {})
    lines = [
        "# EXP-005 — taker-flow variance-compression replication",
        "",
        f"- Run status: `{payload['run_status']}`",
        f"- Mechanical disposition: **{evaluation['disposition']}**",
        f"- Pre-OOS implementation SHA: `{payload['pre_oos_implementation_sha']}`",
        f"- Frozen development-state SHA-256: `{payload['frozen_state_sha256']}`",
        "- Comparison: `M0_FLOW` versus freshly fitted `M0_COMMON` on identical rows.",
        "- OOS refit: no.",
        "- News: `NEWS_NOT_AVAILABLE` (non-gating).",
        "",
        "## Family relative Brier skill",
        "",
        "| Period | Fixed | Twin |",
        "|---|---:|---:|",
    ]
    for period in ("validation", "test_2025", "test_2026"):
        row = periods.get(period, {})
        fixed = row.get("fixed", {}).get("family_relative_brier_skill")
        twin = row.get("twin", {}).get("family_relative_brier_skill")
        fixed_text = "n/a" if fixed is None else f"{float(fixed):.6f}"
        twin_text = "n/a" if twin is None else f"{float(twin):.6f}"
        lines.append(f"| {period} | {fixed_text} | {twin_text} |")
    lines.extend(
        [
            "",
            "The frozen all-period/all-family rule is mechanical; no rescue is permitted.",
            "M1 remains `BLOCKED_ASOF`; no later rung is authorized.",
            "",
        ]
    )
    return "\n".join(lines)


def _render_blocked(payload: dict[str, object]) -> str:
    evaluation = payload["evaluation"]
    return "\n".join(
        [
            "# EXP-005 — consumed execution block",
            "",
            "- Run status: `BLOCKED_CONSUMED`",
            "- Mechanical disposition: **BLOCKED**",
            f"- Integrity class: `{evaluation['blocked_exception_class']}`",
            f"- Reason: {evaluation['blocked_reason']}",
            "- The one-shot receipt remains consumed; no retry is authorized.",
            "- M1 remains `BLOCKED_ASOF`; no later rung is authorized.",
            "",
        ]
    )


def _run_config(expected_sha: str, tree: str) -> dict[str, object]:
    return {
        "schema_version": SCHEMA_VERSION,
        "experiment": "EXP-005",
        "stage": "ONE_SHOT_FULL",
        "pre_oos_sha": expected_sha,
        "pre_oos_tree": tree,
        "comparison": ["M0_COMMON", "M0_FLOW"],
        "m0_common_columns": list(M0_COLUMNS),
        "m0_flow_columns": list(M0_FLOW_COLUMNS),
        "horizons_seconds": list(HORIZONS),
        "label_families": list(LABEL_FAMILIES),
        "oos_periods": ["validation", "test_2025", "test_2026"],
        "oos_refit": False,
        "one_shot_receipt": True,
        "flow_compression": {
            "five_minute_bars": 5,
            "detrend_points": 96,
            "residual_points": 24,
            "variance_ddof": 0,
            "newest_block_lag_seconds": 300,
            "epsilon": None,
            "partial_windows": False,
            "forward_fill": False,
        },
        "estimator": {
            "none_reference": True,
            "development_population_sd_ddof": 0,
            "ridge_slopes_only": RIDGE_PENALTY,
            "optimizer": "L-BFGS-B_ZERO_START",
            "maxiter": OPTIMIZER_MAXITER,
            "ftol": OPTIMIZER_FTOL,
            "gtol": OPTIMIZER_GTOL,
            "final_gradient_infinity_norm_max": FINAL_GRADIENT_TOLERANCE,
        },
        "bootstrap": {
            "block": "UTC_WEEK_FAMILY_WIDE_ONE_DRAW_ALL_LINKED_OBJECTS_AND_RUNGS",
            "draws": BOOTSTRAP_DRAWS,
            "seed": BOOTSTRAP_SEED,
        },
        "mechanical_gates": {
            "pass_family_skill_min": PASS_SKILL,
            "fail_family_skill_max": FAIL_SKILL,
            "precision_multiple": PRECISION_MULTIPLE,
            "cluster_recall_min": PASS_RECALL,
            "lead_seconds_by_horizon": {str(k): v for k, v in LEAD_GATES.items()},
            "eligible_clusters_min": MIN_CLUSTERS,
        },
    }


def _provenance_payload(
    *,
    config: dict[str, object],
    banked: dict[str, object],
    replay_summary: dict[str, object],
    envelope: dict[str, Any],
    envelope_sha256: str,
    checkout: dict[str, object],
    receipt_sha256: str,
    outputs: list[Path],
    out_dir: Path,
    disposition: str,
    fixed_cluster_sha256: str,
) -> dict[str, object]:
    return {
        "repo_commit": checkout["commit"],
        "repo_tree": checkout["tree"],
        "generated_at_utc": _utc_now(),
        "experiment": "EXP-005",
        "disposition": disposition,
        "config": config,
        "config_sha256": canonical_config_sha256(config),
        "inputs": [
            file_entry(p, REPO_ROOT)
            for p in (AUDIT_REPORT, AUDIT_PROVENANCE, CONFIG_PATH, BRIEF_PATH, FIXED_CLUSTERS)
        ],
        "outputs": [file_entry(p, out_dir) for p in outputs],
        "banked_checkpoint_a": banked,
        "replayed_pre_effect_sources": replay_summary,
        "development_implementation": envelope["development_implementation"],
        "development_firewall": envelope["development_firewall"],
        "development_support_identifiers": envelope["development_support_identifiers"],
        "development_envelope_sha256": envelope_sha256,
        "frozen_state_sha256": envelope["frozen_state_sha256"],
        "fixed_cluster_artifact_sha256": fixed_cluster_sha256,
        "one_shot_receipt": {
            "status": "STARTED_CONSUMED_IMMUTABLE",
            "sha256": receipt_sha256,
            "path_recorded_in_committed_evidence": False,
        },
        "runtime": _runtime(),
        "oos_refit": False,
        "news": "NEWS_NOT_AVAILABLE",
    }


def _finish_consumed(data_root: Path, *, disposition: str, result_sha256: str | None) -> None:
    _exclusive_json(
        data_root / RECEIPT_DIRECTORY / COMPLETION_FILENAME,
        {
            "schema_version": SCHEMA_VERSION,
            "experiment": "EXP-005",
            "status": "COMPLETE_CONSUMED" if disposition != "BLOCKED" else "BLOCKED_CONSUMED",
            "completed_at_utc": _utc_now(),
            "disposition": disposition,
            "result_sha256": result_sha256,
        },
    )


def _write_evidence(
    *,
    out_dir: Path,
    state: FrozenFlowState,
    result: dict[str, object],
    markdown: str,
    provenance_context: dict[str, object],
) -> Path:
    if any((out_dir / name).exists() for name in REPORT_FILENAMES):
        raise RunIntegrityError("EXP-005 result output already exists")
    out_dir.mkdir(parents=True, exist_ok=True)
    state_path, result_path = out_dir / "frozen_state.json", out_dir / "result.json"
    markdown_path, provenance_path = out_dir / "result.md", out_dir / "result.provenance.json"
    _exclusive_json(state_path, state.to_dict())
    _exclusive_json(result_path, result)
    _exclusive_write(markdown_path, markdown)
    outputs = [state_path, result_path, markdown_path]
    provenance = _provenance_payload(outputs=outputs, out_dir=out_dir, **provenance_context)
    _exclusive_json(provenance_path, provenance)
    return result_path


def _full_run(args: argparse.Namespace) -> int:
    assert (
        args.expected_sha is not None
        and args.expected_envelope_sha is not None
        and args.out_dir is not None
    )
    envelope, state, envelope_sha = load_frozen_envelope(args.state_dir)
    if envelope_sha != args.expected_envelope_sha:
        raise RunIntegrityError("development envelope SHA does not equal the sealed value")
    checkout = require_sealed_checkout(args.expected_sha, envelope)
    if envelope.get("runtime") != _runtime():
        raise RunIntegrityError("full-stage runtime differs from frozen development runtime")
    banked = banked_checkpoint_identity()
    if envelope.get("banked_checkpoint_a") != banked:
        raise RunIntegrityError("banked Checkpoint A identity differs from development")
    replay = replay_pre_effect_sources(args.data_root, banked)
    if envelope.get("replayed_pre_effect_sources") != replay["summary"]:
        raise RunIntegrityError("pre-effect replay differs from development envelope")
    if any((args.out_dir / name).exists() for name in REPORT_FILENAMES):
        raise RunIntegrityError("EXP-005 result output already exists before receipt")
    receipt = create_consumption_receipt(
        args.data_root,
        expected_sha=args.expected_sha,
        tree=str(checkout["tree"]),
        development_sha=str(envelope["development_implementation"]["commit"]),
        frozen_state_sha256=state.sha256,
        envelope_sha256=envelope_sha,
    )
    receipt_sha = sha256_file(receipt)
    config = _run_config(args.expected_sha, str(checkout["tree"]))
    context: dict[str, object] = {
        "config": config,
        "banked": banked,
        "replay_summary": replay["summary"],
        "envelope": envelope,
        "envelope_sha256": envelope_sha,
        "checkout": checkout,
        "receipt_sha256": receipt_sha,
        "disposition": "BLOCKED",
        "fixed_cluster_sha256": sha256_file(FIXED_CLUSTERS),
    }
    try:
        # First full fixed-cluster outcome read occurs only after receipt consumption.
        clusters = _read_json(FIXED_CLUSTERS)
        index = replay["index"]
        population = build_population(
            end_timestamps=replay["end_timestamps"],
            close=index.klines.close,
            high=index.klines.high,
            low=index.klines.low,
            fixed_cluster_payload=clusters,
            stage="full",
        )
        paired = build_flow_population(population, replay["flow_values"])
        evaluation = evaluate_flow_models(paired, state)
        disposition = str(evaluation["disposition"])
        result: dict[str, object] = {
            "schema_version": SCHEMA_VERSION,
            "experiment": "EXP-005",
            "run_status": "COMPLETE_VALID",
            "pre_oos_implementation_sha": args.expected_sha,
            "pre_oos_tree": checkout["tree"],
            "development_implementation_sha": envelope["development_implementation"]["commit"],
            "frozen_state_sha256": state.sha256,
            "development_envelope_sha256": envelope_sha,
            "config_sha256": canonical_config_sha256(config),
            "one_shot_receipt_consumed": True,
            "oos_refit": False,
            "m1_status": "BLOCKED_ASOF",
            "later_rungs": "UNAUTHORIZED",
            "evaluation": evaluation,
        }
        context["disposition"] = disposition
        result_path = _write_evidence(
            out_dir=args.out_dir,
            state=state,
            result=result,
            markdown=_render_result(result),
            provenance_context=context,
        )
        _finish_consumed(
            args.data_root, disposition=disposition, result_sha256=sha256_file(result_path)
        )
        print(
            _canonical_json(
                {
                    "status": "COMPLETE_VALID",
                    "disposition": disposition,
                    "pre_oos_sha": args.expected_sha,
                }
            ),
            flush=True,
        )
        return 0
    except Exception as error:
        result = {
            "schema_version": SCHEMA_VERSION,
            "experiment": "EXP-005",
            "run_status": "BLOCKED_CONSUMED",
            "pre_oos_implementation_sha": args.expected_sha,
            "pre_oos_tree": checkout["tree"],
            "frozen_state_sha256": state.sha256,
            "development_envelope_sha256": envelope_sha,
            "config_sha256": canonical_config_sha256(config),
            "one_shot_receipt_consumed": True,
            "oos_refit": False,
            "m1_status": "BLOCKED_ASOF",
            "later_rungs": "UNAUTHORIZED",
            "evaluation": {
                "disposition": "BLOCKED",
                "blocked_exception_class": type(error).__name__,
                "blocked_reason": _sanitize_error(error, data_root=args.data_root),
            },
        }
        result_path: Path | None = None
        try:
            result_path = _write_evidence(
                out_dir=args.out_dir,
                state=state,
                result=result,
                markdown=_render_blocked(result),
                provenance_context=context,
            )
        finally:
            _finish_consumed(
                args.data_root,
                disposition="BLOCKED",
                result_sha256=sha256_file(result_path) if result_path else None,
            )
        print(
            _canonical_json(
                {
                    "status": "BLOCKED_CONSUMED",
                    "disposition": "BLOCKED",
                    "pre_oos_sha": args.expected_sha,
                }
            ),
            flush=True,
        )
        return 2


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", required=True, choices=("development", "full"))
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--state-dir", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path)
    parser.add_argument("--expected-sha")
    parser.add_argument("--expected-envelope-sha")
    args = parser.parse_args(argv)
    if args.stage == "development":
        if (
            args.expected_sha is not None
            or args.expected_envelope_sha is not None
            or args.out_dir is not None
        ):
            parser.error(
                "development stage rejects --expected-sha, --expected-envelope-sha, and --out-dir"
            )
    elif args.expected_sha is None or args.expected_envelope_sha is None or args.out_dir is None:
        parser.error("full stage requires --expected-sha, --expected-envelope-sha, and --out-dir")
    return args


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    return _development_run(args) if args.stage == "development" else _full_run(args)


if __name__ == "__main__":
    sys.exit(main())
