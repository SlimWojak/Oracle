#!/usr/bin/env python3
"""D-022 rule-6 sensitivity report: Binance-only vs consolidated-index catalogue.

Cluster inventories are disjoint, time-ordered intervals, so churn is computed
with an interval sweep. An old cluster is RETAINED when at least one index
cluster overlaps it with a compatible direction (directions are compatible when
their direction sets intersect; mixed contains both), DIRECTION_CHANGED when
overlapped only by incompatible directions, and REMOVED when nothing overlaps
it. Index clusters overlapping no old cluster are ADDED. Timing shift is the
start-timestamp delta against the maximum-overlap match.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import numpy as np

from oracle_research.provenance import build_provenance, write_provenance_sidecar

REPO_ROOT = Path(__file__).resolve().parent.parent

_DIRECTION_SETS = {"up": {"up"}, "down": {"down"}, "mixed": {"up", "down"}}


def compatible(direction_a: str, direction_b: str) -> bool:
    return bool(_DIRECTION_SETS[direction_a] & _DIRECTION_SETS[direction_b])


def overlap_seconds(a: dict[str, object], b: dict[str, object]) -> int:
    lo = max(int(a["start_timestamp"]), int(b["start_timestamp"]))
    hi = min(int(a["end_timestamp"]), int(b["end_timestamp"]))
    return max(0, hi - lo)


def match_clusters(
    old: list[dict[str, object]],
    new: list[dict[str, object]],
) -> dict[str, object]:
    """Sweep two disjoint, time-ordered interval lists and classify churn."""

    overlapped_new: set[int] = set()
    retained = direction_changed = removed = 0
    start_deltas: list[int] = []
    pure_to_mixed = mixed_to_pure = 0
    removed_by_year: dict[str, int] = {}
    j = 0
    for cluster in old:
        end = int(cluster["end_timestamp"])
        while j < len(new) and int(new[j]["end_timestamp"]) < int(cluster["start_timestamp"]):
            j += 1
        matches = []
        k = j
        while k < len(new) and int(new[k]["start_timestamp"]) <= end:
            if overlap_seconds(cluster, new[k]) > 0:
                matches.append(k)
            k += 1
        if not matches:
            removed += 1
            year = str(datetime.fromtimestamp(int(cluster["start_timestamp"]), tz=UTC).year)
            removed_by_year[year] = removed_by_year.get(year, 0) + 1
            continue
        overlapped_new.update(matches)
        best = max(matches, key=lambda index: overlap_seconds(cluster, new[index]))
        best_cluster = new[best]
        if compatible(str(cluster["direction"]), str(best_cluster["direction"])):
            retained += 1
        else:
            direction_changed += 1
        start_deltas.append(
            int(best_cluster["start_timestamp"]) - int(cluster["start_timestamp"])
        )
        old_mixed = cluster["direction"] == "mixed"
        new_mixed = best_cluster["direction"] == "mixed"
        pure_to_mixed += int(not old_mixed and new_mixed)
        mixed_to_pure += int(old_mixed and not new_mixed)

    added_clusters = [c for index, c in enumerate(new) if index not in overlapped_new]
    added_by_year: dict[str, int] = {}
    for cluster in added_clusters:
        year = str(datetime.fromtimestamp(int(cluster["start_timestamp"]), tz=UTC).year)
        added_by_year[year] = added_by_year.get(year, 0) + 1
    deltas = np.asarray(start_deltas, dtype=np.float64)
    return {
        "old_total": len(old),
        "new_total": len(new),
        "retained": retained,
        "direction_changed": direction_changed,
        "removed": removed,
        "added": len(added_clusters),
        "pure_to_mixed": pure_to_mixed,
        "mixed_to_pure": mixed_to_pure,
        "start_delta_seconds": {
            "median_abs": float(np.median(np.abs(deltas))) if deltas.size else None,
            "p90_abs": float(np.percentile(np.abs(deltas), 90)) if deltas.size else None,
            "max_abs": float(np.max(np.abs(deltas))) if deltas.size else None,
        },
        "removed_by_year": dict(sorted(removed_by_year.items())),
        "added_by_year": dict(sorted(added_by_year.items())),
    }


def render_markdown(payload: dict[str, object]) -> str:
    lines = [
        "# EXP-000 label sensitivity: Binance-only vs consolidated index (D-022)",
        "",
        f"- old inventory: {payload['old_source']}",
        f"- new inventory: {payload['new_source']}",
        "",
    ]
    for horizon in payload["horizons"]:
        churn = horizon["churn"]
        deltas = churn["start_delta_seconds"]
        lines.extend(
            [
                f"## Horizon {horizon['horizon_bars']} bars",
                "",
                f"- clusters: {churn['old_total']} old vs {churn['new_total']} new",
                f"- retained (overlap, compatible direction): {churn['retained']}",
                f"- direction changed: {churn['direction_changed']}",
                f"- removed: {churn['removed']} (by year: "
                + (", ".join(f"{y}: {n}" for y, n in churn["removed_by_year"].items()) or "none")
                + ")",
                f"- added: {churn['added']} (by year: "
                + (", ".join(f"{y}: {n}" for y, n in churn["added_by_year"].items()) or "none")
                + ")",
                f"- pure->mixed: {churn['pure_to_mixed']}, mixed->pure: {churn['mixed_to_pure']}",
                "- |start shift| seconds (median/p90/max): "
                f"{deltas['median_abs']} / {deltas['p90_abs']} / {deltas['max_abs']}",
                "",
            ]
        )
    return "\n".join(lines)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--old", default=Path("reports/exp000/clusters.json"), type=Path)
    parser.add_argument("--new", default=Path("reports/exp000/index_clusters.json"), type=Path)
    parser.add_argument("--out-dir", default=Path("reports/exp000"), type=Path)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    old_payload = json.loads(args.old.read_text(encoding="utf-8"))
    new_payload = json.loads(args.new.read_text(encoding="utf-8"))
    old_by_bars = {int(h["horizon_bars"]): h["clusters"] for h in old_payload["horizons"]}
    new_by_bars = {int(h["horizon_bars"]): h["clusters"] for h in new_payload["horizons"]}
    horizons = []
    for horizon_bars in sorted(old_by_bars):
        if horizon_bars not in new_by_bars:
            raise ValueError(f"horizon {horizon_bars} missing from the new inventory")
        horizons.append(
            {
                "horizon_bars": horizon_bars,
                "churn": match_clusters(old_by_bars[horizon_bars], new_by_bars[horizon_bars]),
            }
        )
    payload = {
        "old_source": str(args.old),
        "new_source": str(args.new),
        "horizons": horizons,
    }
    args.out_dir.mkdir(parents=True, exist_ok=True)
    json_path = args.out_dir / "sensitivity.json"
    md_path = args.out_dir / "SENSITIVITY.md"
    json_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    md_path.write_text(render_markdown(payload), encoding="utf-8")
    sidecar = write_provenance_sidecar(
        args.out_dir,
        "sensitivity",
        build_provenance(
            repo_root=REPO_ROOT,
            config={"matching": "interval_overlap_max", "direction_rule": "set_intersection"},
            inputs=[args.old.resolve(), args.new.resolve()],
            outputs=[json_path, md_path],
            input_base=REPO_ROOT,
            output_base=args.out_dir,
        ),
    )
    for horizon in horizons:
        churn = horizon["churn"]
        print(
            f"horizon {horizon['horizon_bars']}: {churn['old_total']}->{churn['new_total']} "
            f"clusters; retained {churn['retained']}, changed {churn['direction_changed']}, "
            f"removed {churn['removed']}, added {churn['added']}"
        )
    print(f"Wrote {json_path}, {md_path}")
    print(f"Wrote {sidecar}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
