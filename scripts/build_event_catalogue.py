#!/usr/bin/env python3
"""EXP-000 event catalogue: 1m first-passage labels clustered per D-014."""

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
    BatchLabels,
    batch_first_passage,
)
from oracle_research.binance_klines import KlineArrays, contiguous_segments, load_kline_dir
from oracle_research.clusters import EventCluster, PositiveAnchor, cluster_positive_anchors
from oracle_research.labels import Direction

STEP_SECONDS = 60


def iso_utc(timestamp: int) -> str:
    return datetime.fromtimestamp(int(timestamp), tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def decision_timestamp(open_timestamp: int) -> int:
    """Bar-anchored labels use the close, knowable only at interval end (D-017)."""
    return int(open_timestamp) + STEP_SECONDS


def collect_positive_anchors(
    klines: KlineArrays,
    labels: BatchLabels,
    segment_start: int,
) -> list[PositiveAnchor]:
    """Positive anchors for one labelled segment, stamped at bar close (D-017)."""
    positive_local = np.nonzero((labels.direction == DIR_UP) | (labels.direction == DIR_DOWN))[0]
    anchors: list[PositiveAnchor] = []
    for local_index in positive_local:
        abs_index = segment_start + int(local_index)
        code = int(labels.direction[local_index])
        passage = int(labels.passage_index[local_index])
        anchors.append(
            PositiveAnchor(
                anchor_timestamp=decision_timestamp(int(klines.timestamp[abs_index])),
                passage_timestamp=decision_timestamp(int(klines.timestamp[passage])),
                direction=Direction.UP if code == DIR_UP else Direction.DOWN,
            )
        )
    return anchors


def parse_horizons(text: str) -> list[int]:
    parts = [part.strip() for part in text.split(",") if part.strip()]
    try:
        values = [int(part) for part in parts]
    except ValueError as exc:
        raise argparse.ArgumentTypeError("horizons-bars must be integers") from exc
    if not values or any(value <= 0 for value in values):
        raise argparse.ArgumentTypeError("horizons-bars must be positive integers")
    return values


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", required=True, type=Path)
    parser.add_argument(
        "--spot-subdir",
        default="raw/binance_vision/spot/monthly/klines/BTCUSDT/1m",
    )
    parser.add_argument("--threshold", default=0.02, type=float)
    parser.add_argument("--horizons-bars", default="60,240", type=parse_horizons)
    parser.add_argument("--out-dir", default="reports/exp000", type=Path)
    return parser.parse_args(argv)


def _percentile_stats(values: np.ndarray) -> dict[str, float | None]:
    if values.size == 0:
        return {"median": None, "p90": None, "max": None}
    return {
        "median": float(np.median(values)),
        "p90": float(np.percentile(values, 90)),
        "max": float(np.max(values)),
    }


def _coverage(klines: KlineArrays, segments: list[tuple[int, int]]) -> dict[str, object]:
    timestamps = klines.timestamp
    gaps: list[dict[str, object]] = []
    total_missing_minutes = 0.0
    for index in range(len(segments) - 1):
        _, end = segments[index]
        start_next, _ = segments[index + 1]
        last_ts = int(timestamps[end - 1])
        next_ts = int(timestamps[start_next])
        missing_minutes = (next_ts - last_ts - STEP_SECONDS) / 60.0
        total_missing_minutes += missing_minutes
        gaps.append(
            {
                "start": iso_utc(last_ts),
                "end": iso_utc(next_ts),
                "missing_minutes": missing_minutes,
            }
        )
    gaps.sort(key=lambda item: float(item["missing_minutes"]), reverse=True)
    return {
        "total_bars": int(klines.n_rows),
        "first_timestamp": iso_utc(int(timestamps[0])),
        "last_timestamp": iso_utc(int(timestamps[-1])),
        "segment_count": len(segments),
        "gap_count": max(len(segments) - 1, 0),
        "total_missing_minutes": total_missing_minutes,
        "largest_gaps": gaps[:10],
    }


def _cluster_stats(clusters: list[EventCluster]) -> dict[str, object]:
    up = sum(1 for cluster in clusters if cluster.up_count > 0 and cluster.down_count == 0)
    down = sum(1 for cluster in clusters if cluster.down_count > 0 and cluster.up_count == 0)
    mixed = sum(1 for cluster in clusters if cluster.mixed)
    durations = np.asarray(
        [(cluster.end_timestamp - cluster.start_timestamp) / 60.0 for cluster in clusters],
        dtype=np.float64,
    )
    anchors = np.asarray([cluster.anchor_count for cluster in clusters], dtype=np.float64)
    year_counts: dict[str, int] = {}
    for cluster in clusters:
        year = str(datetime.fromtimestamp(cluster.start_timestamp, tz=UTC).year)
        year_counts[year] = year_counts.get(year, 0) + 1
    return {
        "total": len(clusters),
        "up": up,
        "down": down,
        "mixed": mixed,
        "duration_minutes": _percentile_stats(durations),
        "anchors_per_cluster": _percentile_stats(anchors),
        "per_year": dict(sorted(year_counts.items())),
    }


def _cluster_record(cluster: EventCluster) -> dict[str, object]:
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


def _label_horizon(
    klines: KlineArrays,
    segments: list[tuple[int, int]],
    *,
    horizon_bars: int,
    threshold: float,
) -> tuple[dict[str, object], list[dict[str, object]]]:
    up = down = ambiguous = insufficient = none = 0
    positives: list[PositiveAnchor] = []
    for start, end in segments:
        labels = batch_first_passage(
            klines.high,
            klines.low,
            klines.close,
            horizon_bars=horizon_bars,
            threshold_fraction=threshold,
            segment=(start, end),
        )
        up += int(np.count_nonzero(labels.direction == DIR_UP))
        down += int(np.count_nonzero(labels.direction == DIR_DOWN))
        ambiguous += int(np.count_nonzero(labels.direction == DIR_AMBIGUOUS))
        insufficient += int(np.count_nonzero(labels.direction == DIR_INSUFFICIENT))
        none += int(np.count_nonzero(labels.direction == DIR_NONE))
        positives.extend(collect_positive_anchors(klines, labels, start))
    total = up + down + ambiguous + insufficient + none
    positive = up + down
    clusters = cluster_positive_anchors(positives, horizon_seconds=horizon_bars * STEP_SECONDS)
    summary = {
        "horizon_bars": horizon_bars,
        "horizon_seconds": horizon_bars * STEP_SECONDS,
        "total_anchors": total,
        "up_count": up,
        "down_count": down,
        "positive_count": positive,
        "ambiguous_count": ambiguous,
        "insufficient_horizon_count": insufficient,
        "none_count": none,
        "positive_rate": (positive / total) if total else 0.0,
        "clusters": _cluster_stats(clusters),
    }
    return summary, [_cluster_record(cluster) for cluster in clusters]


def _format_optional(value: float | None, digits: int = 2) -> str:
    if value is None:
        return "n/a"
    return f"{value:.{digits}f}"


def render_summary(payload: dict[str, object]) -> str:
    parameters = payload["parameters"]
    coverage = payload["coverage"]
    lines = [
        "# EXP-000 event catalogue",
        "",
        "## Parameters",
        f"- threshold: {parameters['threshold']}",
        f"- horizons_bars: {', '.join(str(h) for h in parameters['horizons_bars'])}",
        f"- step_seconds: {parameters['step_seconds']}",
        f"- decision_clock: {parameters['decision_clock']}",
        f"- kline_open_time: {parameters['kline_open_time']}",
        f"- anchor_timestamp: {parameters['anchor_timestamp']}",
        f"- spot_subdir: {parameters['spot_subdir']}",
        "",
        "## Coverage",
        f"- total bars: {coverage['total_bars']}",
        f"- range: {coverage['first_timestamp']} to {coverage['last_timestamp']}",
        f"- segments: {coverage['segment_count']}",
        (
            f"- gaps: {coverage['gap_count']} "
            f"({coverage['total_missing_minutes']:.1f} missing minutes)"
        ),
        "- largest gaps:",
    ]
    largest = coverage["largest_gaps"]
    if not largest:
        lines.append("  - none")
    else:
        for gap in largest:
            lines.append(
                f"  - {gap['start']} to {gap['end']} ({gap['missing_minutes']:.1f} missing minutes)"
            )
    for horizon in payload["horizons"]:
        clusters = horizon["clusters"]
        duration = clusters["duration_minutes"]
        anchors = clusters["anchors_per_cluster"]
        lines.extend(
            [
                "",
                (
                    f"## Horizon {horizon['horizon_bars']} bars "
                    f"({horizon['horizon_seconds'] // 60} minutes)"
                ),
                "",
                "### Labels",
                f"- total anchors: {horizon['total_anchors']}",
                f"- up: {horizon['up_count']}",
                f"- down: {horizon['down_count']}",
                f"- positive: {horizon['positive_count']}",
                f"- ambiguous: {horizon['ambiguous_count']}",
                f"- insufficient_horizon: {horizon['insufficient_horizon_count']}",
                f"- none: {horizon['none_count']}",
                f"- positive rate: {horizon['positive_rate']:.6f}",
                "",
                "### Clusters",
                f"- total: {clusters['total']}",
                f"- up: {clusters['up']}",
                f"- down: {clusters['down']}",
                f"- mixed: {clusters['mixed']}",
                "- duration minutes "
                f"(median/p90/max): {_format_optional(duration['median'])} / "
                f"{_format_optional(duration['p90'])} / {_format_optional(duration['max'])}",
                "- anchors per cluster "
                f"(median/p90/max): {_format_optional(anchors['median'])} / "
                f"{_format_optional(anchors['p90'])} / {_format_optional(anchors['max'])}",
                "- per-year cluster counts:",
            ]
        )
        if clusters["per_year"]:
            for year, count in clusters["per_year"].items():
                lines.append(f"  - {year}: {count}")
        else:
            lines.append("  - none")
    lines.append("")
    return "\n".join(lines)


def print_stdout_summary(payload: dict[str, object], out_dir: Path) -> None:
    coverage = payload["coverage"]
    print(
        f"Loaded {coverage['total_bars']} bars from {coverage['first_timestamp']} "
        f"to {coverage['last_timestamp']} ({coverage['segment_count']} segments, "
        f"{coverage['gap_count']} gaps, {coverage['total_missing_minutes']:.1f} missing minutes)"
    )
    for horizon in payload["horizons"]:
        clusters = horizon["clusters"]
        print(
            f"horizon {horizon['horizon_bars']}: {horizon['up_count']} up, "
            f"{horizon['down_count']} down, {horizon['ambiguous_count']} ambiguous, "
            f"{horizon['none_count']} none, {horizon['insufficient_horizon_count']} "
            f"insufficient; {clusters['total']} clusters "
            f"({clusters['up']} up, {clusters['down']} down, {clusters['mixed']} mixed)"
        )
    print(
        f"Wrote {out_dir / 'catalogue.json'}, {out_dir / 'clusters.json'}, "
        f"and {out_dir / 'SUMMARY.md'}"
    )


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    kline_dir = args.data_root / args.spot_subdir
    klines = load_kline_dir(kline_dir)
    segments = contiguous_segments(klines.timestamp, step_seconds=STEP_SECONDS)
    results = [
        _label_horizon(
            klines,
            segments,
            horizon_bars=horizon_bars,
            threshold=args.threshold,
        )
        for horizon_bars in args.horizons_bars
    ]
    parameters = {
        "spot_subdir": args.spot_subdir,
        "threshold": args.threshold,
        "horizons_bars": list(args.horizons_bars),
        "step_seconds": STEP_SECONDS,
        "decision_clock": "60s",
        "kline_open_time": "interval_start",
        "anchor_timestamp": "interval_end",
    }
    payload = {
        "parameters": parameters,
        "coverage": _coverage(klines, segments),
        "horizons": [summary for summary, _ in results],
    }
    clusters_payload = {
        "parameters": parameters,
        "horizons": [
            {
                "horizon_bars": summary["horizon_bars"],
                "horizon_seconds": summary["horizon_seconds"],
                "clusters": records,
            }
            for summary, records in results
        ],
    }
    out_dir = args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "catalogue.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    (out_dir / "clusters.json").write_text(
        json.dumps(clusters_payload, indent=2) + "\n", encoding="utf-8"
    )
    (out_dir / "SUMMARY.md").write_text(render_summary(payload), encoding="utf-8")
    print_stdout_summary(payload, out_dir)
    return 0


if __name__ == "__main__":
    sys.exit(main())
