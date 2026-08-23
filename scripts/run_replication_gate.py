#!/usr/bin/env python3
"""D-013/D-021 venue-replication gate: re-check EXP-000 clusters on Kraken bars.

Reads the committed per-cluster inventory and the Kraken official OHLCVT CSVs,
applies the frozen D-021 semantics per horizon, and writes
``replication_gate.json`` and ``REPLICATION.md`` to the report directory.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

from oracle_research.kraken_klines import load_kraken_csvs
from oracle_research.replication import (
    VERDICT_DISPUTED,
    VERDICT_PENDING,
    VERDICT_REPLICATED,
    VERDICT_SPARSE,
    ReplicationCheck,
    check_clusters,
)

DEFAULT_CSVS = ("XBTUSD_1.csv", "XBTUSD_1_Q1_2026.csv")
ESCALATION_RATE = 0.02


def iso_utc(timestamp: int) -> str:
    return datetime.fromtimestamp(int(timestamp), tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", required=True, type=Path)
    parser.add_argument("--clusters", default=Path("reports/exp000/clusters.json"), type=Path)
    parser.add_argument("--out-dir", default=Path("reports/exp000"), type=Path)
    parser.add_argument("--coverage-floor", default=0.9, type=float)
    parser.add_argument(
        "--bars-start",
        default="2019-11-01T00:00:00Z",
        help="Drop Kraken bars before this UTC instant (memory guard only).",
    )
    return parser.parse_args(argv)


def _check_record(check: ReplicationCheck) -> dict[str, object]:
    return {
        "start": iso_utc(check.start_timestamp),
        "end": iso_utc(check.end_timestamp),
        "start_timestamp": check.start_timestamp,
        "end_timestamp": check.end_timestamp,
        "direction": check.direction,
        "verdict": check.verdict,
        "coverage": round(check.coverage, 4),
        "matching_anchors": check.matching_anchors,
    }


def summarize_horizon(
    horizon_bars: int,
    threshold: float,
    checks: list[ReplicationCheck],
) -> dict[str, object]:
    by_verdict = {
        verdict: [c for c in checks if c.verdict == verdict]
        for verdict in (VERDICT_REPLICATED, VERDICT_DISPUTED, VERDICT_SPARSE, VERDICT_PENDING)
    }
    replicated = len(by_verdict[VERDICT_REPLICATED])
    disputed = len(by_verdict[VERDICT_DISPUTED])
    well_covered = replicated + disputed
    rate = (disputed / well_covered) if well_covered else 0.0
    disputed_by_year: dict[str, int] = {}
    for check in by_verdict[VERDICT_DISPUTED]:
        year = str(datetime.fromtimestamp(check.start_timestamp, tz=UTC).year)
        disputed_by_year[year] = disputed_by_year.get(year, 0) + 1
    return {
        "horizon_bars": horizon_bars,
        "threshold": threshold,
        "total_clusters": len(checks),
        "replicated": replicated,
        "venue_disputed": disputed,
        "kraken_sparse": len(by_verdict[VERDICT_SPARSE]),
        "sparse_replicated_anyway": sum(
            1 for c in by_verdict[VERDICT_SPARSE] if c.matching_anchors > 0
        ),
        "pending_bars": len(by_verdict[VERDICT_PENDING]),
        "disagreement_rate": rate,
        "escalation_threshold": ESCALATION_RATE,
        "escalation_triggered": rate > ESCALATION_RATE,
        "disputed_by_year": dict(sorted(disputed_by_year.items())),
        "disputed_clusters": [_check_record(c) for c in by_verdict[VERDICT_DISPUTED]],
        "pending_clusters": [_check_record(c) for c in by_verdict[VERDICT_PENDING]],
    }


def render_markdown(payload: dict[str, object]) -> str:
    lines = [
        "# EXP-000 venue-replication gate (D-013 / D-021)",
        "",
        f"- kraken bars: {payload['kraken_bars']} rows,"
        f" {payload['kraken_first']} to {payload['kraken_last']}",
        f"- coverage floor: {payload['coverage_floor']}",
        f"- clusters source: {payload['clusters_source']}",
        "",
    ]
    for horizon in payload["horizons"]:
        lines.extend(
            [
                f"## Horizon {horizon['horizon_bars']} bars",
                "",
                f"- clusters: {horizon['total_clusters']}",
                f"- replicated: {horizon['replicated']}",
                f"- venue_disputed: {horizon['venue_disputed']}",
                f"- kraken_sparse: {horizon['kraken_sparse']}"
                f" (of which matched anyway: {horizon['sparse_replicated_anyway']})",
                f"- pending_bars: {horizon['pending_bars']}",
                f"- disagreement rate (well-covered): {horizon['disagreement_rate']:.4%}",
                f"- escalation (> {horizon['escalation_threshold']:.0%}):"
                f" {'TRIGGERED' if horizon['escalation_triggered'] else 'not triggered'}",
                "- disputed by year: "
                + (
                    ", ".join(f"{y}: {n}" for y, n in horizon["disputed_by_year"].items())
                    or "none"
                ),
                "",
            ]
        )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    clusters_payload = json.loads(args.clusters.read_text(encoding="utf-8"))
    threshold = float(clusters_payload["parameters"]["threshold"])
    csv_dir = args.data_root / "raw" / "kraken" / "ohlcvt"
    csv_paths = [csv_dir / name for name in DEFAULT_CSVS if (csv_dir / name).exists()]
    if not csv_paths:
        raise FileNotFoundError(f"no Kraken OHLCVT CSVs found in {csv_dir}")
    bars_start = int(
        datetime.fromisoformat(args.bars_start.replace("Z", "+00:00")).timestamp()
    )
    klines = load_kraken_csvs(csv_paths, start_ts=bars_start)

    horizons = []
    for horizon in clusters_payload["horizons"]:
        checks = check_clusters(
            klines,
            horizon["clusters"],
            horizon_bars=int(horizon["horizon_bars"]),
            threshold_fraction=threshold,
            coverage_floor=args.coverage_floor,
        )
        horizons.append(summarize_horizon(int(horizon["horizon_bars"]), threshold, checks))

    payload = {
        "clusters_source": str(args.clusters),
        "kraken_csvs": [path.name for path in csv_paths],
        "kraken_bars": int(klines.n_rows),
        "kraken_first": iso_utc(int(klines.timestamp[0])),
        "kraken_last": iso_utc(int(klines.timestamp[-1])),
        "coverage_floor": args.coverage_floor,
        "horizons": horizons,
    }
    args.out_dir.mkdir(parents=True, exist_ok=True)
    (args.out_dir / "replication_gate.json").write_text(
        json.dumps(payload, indent=2) + "\n", encoding="utf-8"
    )
    (args.out_dir / "REPLICATION.md").write_text(render_markdown(payload), encoding="utf-8")
    for horizon in horizons:
        print(
            f"horizon {horizon['horizon_bars']}: {horizon['replicated']} replicated, "
            f"{horizon['venue_disputed']} disputed, {horizon['kraken_sparse']} sparse, "
            f"{horizon['pending_bars']} pending; rate {horizon['disagreement_rate']:.4%} "
            f"({'ESCALATION' if horizon['escalation_triggered'] else 'ok'})"
        )
    print(f"Wrote {args.out_dir / 'replication_gate.json'} and REPLICATION.md")
    return 0


if __name__ == "__main__":
    sys.exit(main())
