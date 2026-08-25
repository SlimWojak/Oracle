#!/usr/bin/env python3
"""EXP-000 per-challenger usable history table (D-016 common support).

Reads the committed D-022 consolidated-index cluster inventory
(``reports/exp000/index_clusters.json``)
and reports, for each fuel challenger / feature family, how many independent
event clusters fall inside its usable point-in-time history. A cluster counts
toward a window only when its start timestamp is at or after the window start:
a straddling cluster's early anchors would lack the family's features.

Window starts are raw acquisition starts. Effective starts move later once
feature lookbacks are frozen; that adjustment is deliberately not applied here.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from oracle_research.provenance import build_provenance, write_provenance_sidecar

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CLUSTERS = Path("reports/exp000/index_clusters.json")
DEFAULT_SOURCE = "reports/exp000/index_clusters.json"


@dataclass(frozen=True, slots=True)
class ChallengerWindow:
    key: str
    label: str
    start: str  # ISO date, UTC midnight
    note: str


# Raw acquisition starts verified in EXPERIMENT_LEDGER.md / docs/HANDOVER.md.
WINDOWS: tuple[ChallengerWindow, ...] = (
    ChallengerWindow(
        key="price_controls",
        label="Price-only controls (M0)",
        start="2020-01-01",
        note=(
            "D-022 consolidated BTC spot index 1m bars; context baseline, "
            "never a comparable score (D-016)."
        ),
    ),
    ChallengerWindow(
        key="cex_inferred",
        label="CEX-inferred challenger (M1+, Binance UM metrics)",
        start="2021-12-01",
        note="OI/taker metrics dumps begin 2021-12; funding alone reaches back to 2020-01.",
    ),
    ChallengerWindow(
        key="hl_impact_context",
        label="HL impact-context challenger (asset_ctxs)",
        start="2023-05-20",
        note="Per-minute quoted impact prices, OI, premium.",
    ),
    ChallengerWindow(
        key="hl_fills",
        label="HL fill tape (no predictive ladder this cycle, D-020)",
        start="2025-05-25",
        note="Construct validation and EXP-001 only; observed-fuel status gated by D-018.",
    ),
)

VENDOR_NOTE = (
    "Vendor/model challenger: no as-of point-in-time history acquired or verified; "
    "no usable window. Reconstructing history from a current vendor view is "
    "prohibited (DATA_CONTRACT)."
)


def _epoch(date_text: str) -> int:
    return int(datetime.strptime(date_text, "%Y-%m-%d").replace(tzinfo=UTC).timestamp())


def _window_stats(clusters: list[dict[str, object]], start_epoch: int) -> dict[str, object]:
    selected = [c for c in clusters if int(c["start_timestamp"]) >= start_epoch]
    per_year: dict[str, int] = {}
    for cluster in selected:
        year = str(datetime.fromtimestamp(int(cluster["start_timestamp"]), tz=UTC).year)
        per_year[year] = per_year.get(year, 0) + 1
    return {
        "total": len(selected),
        "up": sum(1 for c in selected if c["direction"] == "up"),
        "down": sum(1 for c in selected if c["direction"] == "down"),
        "mixed": sum(1 for c in selected if c["direction"] == "mixed"),
        "first_cluster": selected[0]["start"] if selected else None,
        "last_cluster": selected[-1]["start"] if selected else None,
        "per_year": dict(sorted(per_year.items())),
    }


def build_payload(
    clusters_payload: dict[str, object], source: str = DEFAULT_SOURCE
) -> dict[str, object]:
    horizons_out = []
    for horizon in clusters_payload["horizons"]:
        clusters = horizon["clusters"]
        horizons_out.append(
            {
                "horizon_bars": horizon["horizon_bars"],
                "windows": {
                    window.key: _window_stats(clusters, _epoch(window.start))
                    for window in WINDOWS
                },
            }
        )
    return {
        "source": source,
        "membership_rule": "cluster start_timestamp >= window start (straddlers excluded)",
        "windows": [
            {"key": w.key, "label": w.label, "start": w.start, "note": w.note} for w in WINDOWS
        ],
        "vendor_note": VENDOR_NOTE,
        "horizons": horizons_out,
    }


def render_markdown(payload: dict[str, object]) -> str:
    lines = [
        "# EXP-000 per-fuel-challenger usable history",
        "",
        f"Source inventory: `{payload['source']}` (D-022 consolidated BTC spot index).",
        "",
        f"Membership rule: {payload['membership_rule']}. Window starts are raw",
        "acquisition starts; effective starts move later once feature lookbacks",
        "are frozen. Head-to-head and incremental-lift comparisons run only on",
        "common intersections per D-016.",
        "",
        "## Windows",
        "",
    ]
    for window in payload["windows"]:
        lines.append(f"- **{window['label']}** — from {window['start']}. {window['note']}")
    lines.extend(["", f"- **Vendor/model challenger** — {payload['vendor_note']}", ""])
    for horizon in payload["horizons"]:
        lines.extend(
            [
                f"## Horizon {horizon['horizon_bars']} bars",
                "",
                "| Challenger window | from | clusters | up | down | mixed | per-year |",
                "|---|---|---|---|---|---|---|",
            ]
        )
        for window in payload["windows"]:
            stats = horizon["windows"][window["key"]]
            per_year = ", ".join(f"{y}: {n}" for y, n in stats["per_year"].items())
            lines.append(
                f"| {window['label']} | {window['start']} | {stats['total']} "
                f"| {stats['up']} | {stats['down']} | {stats['mixed']} | {per_year} |"
            )
        lines.append("")
    return "\n".join(lines)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--clusters", default=DEFAULT_CLUSTERS, type=Path)
    parser.add_argument("--out-dir", default=Path("reports/exp000"), type=Path)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    clusters_path = args.clusters.resolve()
    clusters_payload = json.loads(clusters_path.read_text(encoding="utf-8"))
    source = str(clusters_path.relative_to(REPO_ROOT))
    payload = build_payload(clusters_payload, source=source)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    json_path = args.out_dir / "challenger_history.json"
    md_path = args.out_dir / "challenger_history.md"
    json_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    md_path.write_text(render_markdown(payload), encoding="utf-8")
    config = {
        "windows": [
            {"key": window.key, "label": window.label, "start": window.start, "note": window.note}
            for window in WINDOWS
        ],
        "membership_rule": payload["membership_rule"],
    }
    sidecar = write_provenance_sidecar(
        args.out_dir,
        "challenger_history",
        build_provenance(
            repo_root=REPO_ROOT,
            config=config,
            inputs=[clusters_path],
            outputs=[json_path, md_path],
            input_base=REPO_ROOT,
            output_base=args.out_dir,
        ),
    )
    print(f"Wrote {args.out_dir / 'challenger_history.json'} and challenger_history.md")
    print(f"Wrote {sidecar}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
