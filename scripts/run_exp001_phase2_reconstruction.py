#!/usr/bin/env python3
"""EXP-001 Phase 2: tractable-stratum liquidation price reconstruction."""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from oracle_research.hl_liq_reconstruction import (
    BtcMarginConstants,
    EpisodeState,
    apply_btc_fill_to_episode,
    implied_liquidation_price_cross,
    implied_liquidation_price_isolated,
    is_within_tolerance,
    relative_error,
)
from oracle_research.hl_liquidations import (
    BtcLiquidationEvent,
    PositionTracker,
    btc_only_at_time,
    extract_btc_liquidation_events,
    stratify_event,
)
from oracle_research.hyperliquid_asset_ctxs import AssetCtxStore, load_btc_minutes_for_days
from oracle_research.hyperliquid_fills import HlFill, iter_fills_from_lz4
from oracle_research.provenance import build_provenance, write_provenance_sidecar

REPO_ROOT = Path(__file__).resolve().parent.parent
TOLERANCE = 0.01

HELD_OUT_WINDOWS: tuple[tuple[str, str, str], ...] = (
    ("20250715_12", "2025-07-15T12:00:00Z", "2025-07-15T13:00:00Z"),
    ("20251010_21", "2025-10-10T21:00:00Z", "2025-10-10T22:00:00Z"),
    ("20250805_14", "2025-08-05T14:00:00Z", "2025-08-05T15:00:00Z"),
)


@dataclass(frozen=True, slots=True)
class HeldOutWindow:
    label: str
    start_ms: int
    end_ms: int

    def contains(self, time_ms: int) -> bool:
        return self.start_ms <= time_ms < self.end_ms


def parse_window(label: str, start_iso: str, end_iso: str) -> HeldOutWindow:
    start_ms = int(datetime.fromisoformat(start_iso.replace("Z", "+00:00")).timestamp() * 1000)
    end_ms = int(datetime.fromisoformat(end_iso.replace("Z", "+00:00")).timestamp() * 1000)
    return HeldOutWindow(label=label, start_ms=start_ms, end_ms=end_ms)


def iter_hourly_lz4_paths(data_root: Path) -> list[Path]:
    prefixes = (
        data_root / "raw/hyperliquid/node_fills/hourly",
        data_root / "raw/hyperliquid/node_fills_by_block/hourly",
    )
    paths: list[Path] = []
    for prefix in prefixes:
        if prefix.is_dir():
            paths.extend(prefix.rglob("*.lz4"))
    return sorted(paths, key=lambda item: str(item))


def window_for_time(windows: list[HeldOutWindow], time_ms: int) -> HeldOutWindow | None:
    for window in windows:
        if window.contains(time_ms):
            return window
    return None


def dates_for_windows(windows: list[HeldOutWindow]) -> list[date]:
    days: set[date] = set()
    for window in windows:
        for boundary_ms in (window.start_ms, window.end_ms - 1):
            day = datetime.fromtimestamp(boundary_ms / 1000, tz=UTC).date()
            days.add(day)
    return sorted(days)


@dataclass
class EvaluationRecord:
    window_label: str
    stratum: str
    method: str
    time_ms: int
    tid: int
    liquidated_user: str
    observed_mark_px: float
    mark_px_used: float | None
    implied_liq_px: float | None
    relative_error: float | None
    within_tolerance: bool | None
    notional_usd: float
    skip_reason: str | None = None


def evaluate_event(
    event: BtcLiquidationEvent,
    *,
    window: HeldOutWindow,
    stratum: str,
    pre_state: EpisodeState,
    mark_px: float | None,
    constants: BtcMarginConstants,
) -> EvaluationRecord:
    observed = float(event.mark_px)
    notional = event.usd_notional

    if mark_px is None:
        return EvaluationRecord(
            window_label=window.label,
            stratum=stratum,
            method=event.method,
            time_ms=event.time_ms,
            tid=event.tid,
            liquidated_user=event.liquidated_user,
            observed_mark_px=observed,
            mark_px_used=None,
            implied_liq_px=None,
            relative_error=None,
            within_tolerance=None,
            notional_usd=notional,
            skip_reason="mark_px_missing",
        )

    implied: float | None
    skip_reason: str | None = None

    if stratum == "a":
        implied = implied_liquidation_price_isolated(
            pre_state.position,
            pre_state.entry_vwap,
            mark_px,
            pre_state.isolated_collateral,
            constants,
        )
        if implied is None:
            skip_reason = "isolated_implied_unavailable"
    else:
        cross = implied_liquidation_price_cross(
            pre_state.position,
            pre_state.entry_vwap,
            mark_px,
        )
        implied = cross.implied_price
        skip_reason = cross.reason

    rel_err: float | None = None
    within: bool | None = None
    if implied is not None:
        rel_err = relative_error(implied, observed)
        within = is_within_tolerance(implied, observed, TOLERANCE)

    return EvaluationRecord(
        window_label=window.label,
        stratum=stratum,
        method=event.method,
        time_ms=event.time_ms,
        tid=event.tid,
        liquidated_user=event.liquidated_user,
        observed_mark_px=observed,
        mark_px_used=mark_px,
        implied_liq_px=implied,
        relative_error=rel_err,
        within_tolerance=within,
        notional_usd=notional,
        skip_reason=skip_reason,
    )


def summarize_records(records: list[EvaluationRecord]) -> dict[str, Any]:
    by_stratum: dict[str, dict[str, Any]] = {}
    for stratum in ("a", "b"):
        stratum_records = [record for record in records if record.stratum == stratum]
        evaluated = [record for record in stratum_records if record.implied_liq_px is not None]
        within = [record for record in evaluated if record.within_tolerance]
        tractable_notional = sum(record.notional_usd for record in stratum_records)
        evaluated_notional = sum(record.notional_usd for record in evaluated)
        within_notional = sum(record.notional_usd for record in within)
        by_stratum[stratum] = {
            "event_count": len(stratum_records),
            "tractable_notional_usd": tractable_notional,
            "evaluated_event_count": len(evaluated),
            "evaluated_notional_usd": evaluated_notional,
            "within_tolerance_event_count": len(within),
            "within_tolerance_notional_usd": within_notional,
            "coverage_weighted_accuracy": (
                within_notional / evaluated_notional if evaluated_notional > 0 else None
            ),
            "unobserved_event_count": sum(
                1 for record in stratum_records if record.implied_liq_px is None
            ),
        }

    all_evaluated = [record for record in records if record.implied_liq_px is not None]
    all_within = [record for record in all_evaluated if record.within_tolerance]
    evaluated_notional = sum(record.notional_usd for record in all_evaluated)
    within_notional = sum(record.notional_usd for record in all_within)

    return {
        "event_count": len(records),
        "tractable_notional_usd": sum(record.notional_usd for record in records),
        "evaluated_event_count": len(all_evaluated),
        "evaluated_notional_usd": evaluated_notional,
        "within_tolerance_event_count": len(all_within),
        "within_tolerance_notional_usd": within_notional,
        "coverage_weighted_accuracy": (
            within_notional / evaluated_notional if evaluated_notional > 0 else None
        ),
        "tolerance_relative": TOLERANCE,
        "by_stratum": by_stratum,
    }


def record_to_dict(record: EvaluationRecord) -> dict[str, Any]:
    return {
        "window_label": record.window_label,
        "stratum": record.stratum,
        "method": record.method,
        "time_ms": record.time_ms,
        "tid": record.tid,
        "liquidated_user": record.liquidated_user,
        "observed_mark_px": record.observed_mark_px,
        "mark_px_used": record.mark_px_used,
        "implied_liq_px": record.implied_liq_px,
        "relative_error": record.relative_error,
        "within_tolerance": record.within_tolerance,
        "notional_usd": record.notional_usd,
        "skip_reason": record.skip_reason,
    }


def render_window_markdown(window: HeldOutWindow, summary: dict[str, Any]) -> str:
    lines = [
        f"# EXP-001 Phase 2 — reconstruction ({window.label})",
        "",
        f"- Window UTC: {window.start_ms} .. {window.end_ms} (ms, end exclusive)",
        f"- Tractable events: {summary['event_count']}",
        f"- Tractable notional: ${summary['tractable_notional_usd']:,.2f}",
        f"- Evaluated notional: ${summary['evaluated_notional_usd']:,.2f}",
        (
            "- Coverage-weighted accuracy: "
            f"{summary['coverage_weighted_accuracy']:.4%}"
            if summary["coverage_weighted_accuracy"] is not None
            else "- Coverage-weighted accuracy: n/a"
        ),
        f"- Tolerance: {summary['tolerance_relative']:.2%} relative error",
        "",
        "## By stratum",
        "",
    ]
    for stratum, stats in summary["by_stratum"].items():
        label = "isolated" if stratum == "a" else "cross-margin"
        accuracy = stats["coverage_weighted_accuracy"]
        accuracy_text = f"{accuracy:.4%}" if accuracy is not None else "n/a"
        lines.append(
            f"- ({stratum}) {label}: {stats['event_count']} events, "
            f"${stats['tractable_notional_usd']:,.2f} notional, "
            f"accuracy={accuracy_text}, "
            f"unobserved={stats['unobserved_event_count']}"
        )
    lines.append("")
    return "\n".join(lines)


def render_summary_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# EXP-001 Phase 2 — reconstruction summary",
        "",
        f"- Held-out windows: {len(payload['windows'])}",
        f"- Total tractable events: {payload['total_event_count']}",
        f"- Total tractable notional: ${payload['total_tractable_notional_usd']:,.2f}",
        (
            "- Combined coverage-weighted accuracy: "
            f"{payload['combined_coverage_weighted_accuracy']:.4%}"
            if payload["combined_coverage_weighted_accuracy"] is not None
            else "- Combined coverage-weighted accuracy: n/a"
        ),
        "",
        "## Per window",
        "",
    ]
    for window in payload["windows"]:
        accuracy = window["coverage_weighted_accuracy"]
        accuracy_text = f"{accuracy:.4%}" if accuracy is not None else "n/a"
        lines.append(
            f"- {window['label']}: {window['event_count']} events, accuracy={accuracy_text}"
        )
    lines.append("")
    return "\n".join(lines)


def process_fill_stream(
    fills: Iterator[HlFill],
    *,
    windows: list[HeldOutWindow],
    asset_ctxs: AssetCtxStore,
    constants: BtcMarginConstants,
) -> list[EvaluationRecord]:
    tracker = PositionTracker()
    episodes: dict[str, EpisodeState] = defaultdict(EpisodeState)
    records: list[EvaluationRecord] = []

    for fill in fills:
        if fill.coin == "BTC" and fill.liquidation is not None:
            for event in extract_btc_liquidation_events([fill]):
                window = window_for_time(windows, event.time_ms)
                if window is None:
                    continue
                positions = tracker.coin_positions_at(event.liquidated_user, event.time_ms)
                is_btc_only = btc_only_at_time(event.liquidated_user, event.time_ms, positions)
                stratum = stratify_event(event, is_btc_only=is_btc_only)
                if stratum not in ("a", "b"):
                    continue
                user_key = event.liquidated_user.lower()
                pre_state = episodes[user_key].snapshot()
                mark_px = asset_ctxs.get_mark_px("BTC", event.time_ms)
                records.append(
                    evaluate_event(
                        event,
                        window=window,
                        stratum=stratum,
                        pre_state=pre_state,
                        mark_px=mark_px,
                        constants=constants,
                    )
                )

        tracker.update(fill)
        if fill.coin == "BTC":
            user_key = fill.user.lower()
            apply_btc_fill_to_episode(episodes[user_key], fill, constants)

    return records


def run_reconstruction(
    data_root: Path,
    *,
    max_files: int | None = None,
    progress_every: int = 100,
) -> tuple[dict[str, Any], dict[str, list[EvaluationRecord]]]:
    windows = [parse_window(*spec) for spec in HELD_OUT_WINDOWS]
    asset_ctxs = load_btc_minutes_for_days(data_root, dates_for_windows(windows))
    paths = iter_hourly_lz4_paths(data_root)
    if max_files is not None:
        paths = paths[:max_files]

    records_by_window: dict[str, list[EvaluationRecord]] = {window.label: [] for window in windows}
    constants = BtcMarginConstants()

    for index, path in enumerate(paths, start=1):
        fills = iter_fills_from_lz4(path)
        file_records = process_fill_stream(
            fills,
            windows=windows,
            asset_ctxs=asset_ctxs,
            constants=constants,
        )
        for record in file_records:
            records_by_window[record.window_label].append(record)
        if progress_every and index % progress_every == 0:
            print(f"processed {index}/{len(paths)} files", file=sys.stderr)

    window_summaries: dict[str, dict[str, Any]] = {}
    for window in windows:
        summary = summarize_records(records_by_window[window.label])
        summary["label"] = window.label
        summary["start_ms"] = window.start_ms
        summary["end_ms"] = window.end_ms
        window_summaries[window.label] = summary

    all_records = [record for records in records_by_window.values() for record in records]
    combined = summarize_records(all_records)
    combined_evaluated = combined["evaluated_notional_usd"]
    combined_within = combined["within_tolerance_notional_usd"]

    payload = {
        "experiment": "EXP-001",
        "phase": "reconstruction",
        "data_root": str(data_root),
        "files_processed": len(paths),
        "held_out_windows": [
            {"label": window.label, "start_ms": window.start_ms, "end_ms": window.end_ms}
            for window in windows
        ],
        "asset_ctx_minutes_loaded": asset_ctxs.minute_count,
        "total_event_count": combined["event_count"],
        "total_tractable_notional_usd": combined["tractable_notional_usd"],
        "combined_coverage_weighted_accuracy": combined["coverage_weighted_accuracy"],
        "combined_evaluated_notional_usd": combined_evaluated,
        "combined_within_tolerance_notional_usd": combined_within,
        "tolerance_relative": TOLERANCE,
        "windows": list(window_summaries.values()),
    }
    return payload, records_by_window


def main() -> int:
    parser = argparse.ArgumentParser(description="EXP-001 Phase 2 reconstruction")
    parser.add_argument(
        "--data-root",
        type=Path,
        required=True,
        help="Oracle data root (contains raw/hyperliquid/... and asset_ctxs/)",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=REPO_ROOT / "reports/exp001",
        help="Directory for reconstruction artifacts",
    )
    parser.add_argument(
        "--max-files",
        type=int,
        default=None,
        help="Process only the first N hourly fill files (sorted path order)",
    )
    parser.add_argument(
        "--progress-every",
        type=int,
        default=100,
        help="Print progress every N files (0 to disable)",
    )
    args = parser.parse_args()

    payload, records_by_window = run_reconstruction(
        args.data_root.resolve(),
        max_files=args.max_files,
        progress_every=args.progress_every,
    )

    args.output_dir.mkdir(parents=True, exist_ok=True)
    output_paths: list[Path] = []
    sidecar_names: list[str] = []

    for window_payload in payload["windows"]:
        label = window_payload["label"]
        json_path = args.output_dir / f"reconstruction_{label}.json"
        md_path = args.output_dir / f"reconstruction_{label}.md"
        detail = {
            **window_payload,
            "events": [record_to_dict(record) for record in records_by_window[label]],
        }
        json_path.write_text(json.dumps(detail, indent=2) + "\n", encoding="utf-8")
        window = parse_window(
            label,
            next(start for lbl, start, _ in HELD_OUT_WINDOWS if lbl == label),
            next(end for lbl, _, end in HELD_OUT_WINDOWS if lbl == label),
        )
        md_path.write_text(render_window_markdown(window, window_payload), encoding="utf-8")
        output_paths.extend([json_path, md_path])
        sidecar_names.append(f"reconstruction_{label}")

    summary_path = args.output_dir / "reconstruction_summary.json"
    summary_md_path = args.output_dir / "reconstruction_summary.md"
    summary_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    summary_md_path.write_text(render_summary_markdown(payload), encoding="utf-8")
    output_paths.extend([summary_path, summary_md_path])

    for name in sidecar_names:
        write_provenance_sidecar(
            args.output_dir,
            name,
            build_provenance(
                repo_root=REPO_ROOT,
                config={
                    "experiment": "EXP-001",
                    "phase": "reconstruction",
                    "data_root": str(args.data_root.resolve()),
                    "max_files": args.max_files,
                    "artifact": name,
                },
                inputs=[],
                outputs=[
                    args.output_dir / f"{name}.json",
                    args.output_dir / f"{name}.md",
                ],
                output_base=args.output_dir,
            ),
        )

    summary_sidecar = write_provenance_sidecar(
        args.output_dir,
        "reconstruction_summary",
        build_provenance(
            repo_root=REPO_ROOT,
            config={
                "experiment": "EXP-001",
                "phase": "reconstruction_summary",
                "data_root": str(args.data_root.resolve()),
                "max_files": args.max_files,
                "files_processed": payload["files_processed"],
            },
            inputs=[],
            outputs=[summary_path, summary_md_path],
            output_base=args.output_dir,
        ),
    )

    accuracy = payload["combined_coverage_weighted_accuracy"]
    accuracy_text = f"{accuracy:.6f}" if accuracy is not None else "n/a"
    print(f"combined_coverage_weighted_accuracy={accuracy_text}")
    print(f"Wrote {len(output_paths)} artifacts under {args.output_dir} (+ provenance)")
    print(f"summary_provenance={summary_sidecar}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
