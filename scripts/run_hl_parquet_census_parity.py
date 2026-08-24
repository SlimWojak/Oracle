#!/usr/bin/env python3
"""Reproduce the EXP-001 stratification census from D-012 Parquet fills."""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from run_exp001_stratification_census import (
    EARLY_DEMOTION_THRESHOLD,
    PARTIAL_VIABILITY_THRESHOLD,
    AggregationBuckets,
    PositionTracker,
    empty_nested_counter,
    process_fill_stream,
)

from oracle_research.hl_fills_parquet import all_fills_root, stable_source_id
from oracle_research.provenance import build_provenance, write_provenance_sidecar

try:
    import duckdb
except ImportError:  # optional dependency group ``analytics``
    duckdb = None  # type: ignore[assignment]

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_EXPECTED = REPO_ROOT / "reports" / "exp001" / "stratification_census.json"
DEFAULT_OUTPUT_DIR = REPO_ROOT / "reports" / "infra_hl_parquet_v1"

REL_TOLERANCE = 1e-9
TRACTABLE_SHARE_ABS_TOLERANCE = 1e-12
DEFAULT_DUCKDB_MEMORY_LIMIT = "48GB"
DEFAULT_PROGRESS_EVERY_SOURCES = 100
DEFAULT_PROGRESS_EVERY_ROWS = 1_000_000

SELECT_COLUMNS = (
    "user",
    "coin",
    "px",
    "sz",
    "side",
    "time_ms",
    "start_position",
    "dir",
    "tid",
    "liquidation_liquidated_user",
    "liquidation_mark_px",
    "liquidation_method",
)


def _sql_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def parquet_glob(table_root: Path) -> str:
    return (Path(table_root) / "**" / "*.parquet").as_posix()


def parquet_source_glob(table_root: Path, source_path: str) -> str:
    source_id = stable_source_id(source_path)
    return (Path(table_root) / "**" / f"part-{source_id}-*.parquet").as_posix()


def manifest_path_for_table(table_root: Path) -> Path:
    return dataset_root_from_table(table_root) / "manifest.json"


def parquet_table_exists(table_root: Path) -> bool:
    root = Path(table_root)
    if not root.is_dir():
        return False

    manifest_path = manifest_path_for_table(root)
    if manifest_path.exists():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            manifest = {}
        for entry in manifest.get("output_files", []):
            relative = entry.get("path") if isinstance(entry, dict) else None
            if isinstance(relative, str) and (root.parent / relative).exists():
                return True

    for pattern in ("*.parquet", "date=*/hour=*/*.parquet", "*/*/*.parquet"):
        if next(root.glob(pattern), None) is not None:
            return True
    return False


def source_paths_from_manifest(table_root: Path) -> list[str]:
    manifest_path = manifest_path_for_table(table_root)
    if not manifest_path.exists():
        return []
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for key in ("source_paths", "input_source_paths", "source_path_order"):
        values = manifest.get(key)
        if isinstance(values, list) and all(isinstance(value, str) for value in values):
            return sorted(set(values))
    return []


def discover_source_paths(
    conn: duckdb.DuckDBPyConnection,
    *,
    table_root: Path,
) -> list[str]:
    manifest_sources = source_paths_from_manifest(table_root)
    if manifest_sources:
        return manifest_sources

    query = (
        "SELECT DISTINCT source_path "
        f"FROM read_parquet({_sql_literal(parquet_glob(table_root))}, "
        "hive_partitioning=true) "
        "WHERE source_path IS NOT NULL"
    )
    return sorted(str(row[0]) for row in conn.execute(query).fetchall())


def configure_duckdb(
    conn: duckdb.DuckDBPyConnection,
    *,
    memory_limit: str,
    temp_directory: Path,
) -> None:
    temp_directory.mkdir(parents=True, exist_ok=True)
    conn.execute(f"SET memory_limit = {_sql_literal(memory_limit)}")
    conn.execute(f"SET temp_directory = {_sql_literal(str(temp_directory))}")


def print_progress(message: str) -> None:
    print(message, file=sys.stderr, flush=True)


def display_path(path: Path) -> str:
    """Return repo-relative paths for committed reports when possible."""

    resolved = Path(path).resolve()
    try:
        return resolved.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return str(resolved)


def row_to_census_fill(row: tuple[Any, ...]) -> tuple[str, dict[str, Any]]:
    (
        user,
        coin,
        px,
        sz,
        side,
        time_ms,
        start_position,
        direction,
        tid,
        liquidated_user,
        mark_px,
        method,
    ) = row
    liquidation = None
    if liquidated_user is not None or mark_px is not None or method is not None:
        liquidation = {
            "liquidatedUser": liquidated_user,
            "markPx": mark_px,
            "method": method,
        }
    fill = {
        "coin": coin,
        "px": px,
        "sz": sz,
        "side": side,
        "time": int(time_ms),
        "startPosition": start_position,
        "dir": direction,
        "tid": int(tid),
        "liquidation": liquidation,
    }
    return str(user), fill


def iter_census_fills_from_duckdb(
    conn: duckdb.DuckDBPyConnection,
    *,
    table_root: Path,
    batch_rows: int,
    progress_every_sources: int = 0,
    progress_every_rows: int = 0,
) -> Iterator[tuple[str, dict[str, Any]]]:
    """Yield fills from Parquet in raw source order for EXP-001 census logic."""

    columns = ", ".join(SELECT_COLUMNS)
    source_paths = discover_source_paths(conn, table_root=table_root)
    total_sources = len(source_paths)
    total_rows = 0
    next_row_progress = progress_every_rows if progress_every_rows > 0 else None
    progress_enabled = progress_every_sources > 0 or progress_every_rows > 0
    if progress_enabled and total_sources:
        print_progress(f"discovered {total_sources} source_path values")

    for source_index, source_path in enumerate(source_paths, start=1):
        if progress_every_sources > 0 and (
            source_index == 1 or source_index % progress_every_sources == 0
        ):
            print_progress(
                f"streaming source {source_index}/{total_sources}; rows_read={total_rows}; "
                f"source_path={source_path}"
            )
        query = (
            f"SELECT {columns} "
            "FROM read_parquet("
            f"{_sql_literal(parquet_source_glob(table_root, source_path))}, "
            "hive_partitioning=true) "
            "WHERE source_path = ? "
            "ORDER BY source_row_number"
        )
        cursor = conn.execute(query, [source_path])
        while rows := cursor.fetchmany(batch_rows):
            total_rows += len(rows)
            while next_row_progress is not None and total_rows >= next_row_progress:
                print_progress(
                    f"streamed {total_rows} rows from "
                    f"{source_index}/{total_sources} sources"
                )
                next_row_progress += progress_every_rows
            for row in rows:
                yield row_to_census_fill(row)

    if progress_enabled and total_sources:
        print_progress(f"streamed {total_rows} rows from {total_sources} sources")


def run_census_from_parquet(
    table_root: Path,
    *,
    batch_rows: int = 100_000,
    duckdb_memory_limit: str = DEFAULT_DUCKDB_MEMORY_LIMIT,
    duckdb_temp_directory: Path | None = None,
    progress_every_sources: int = DEFAULT_PROGRESS_EVERY_SOURCES,
    progress_every_rows: int = DEFAULT_PROGRESS_EVERY_ROWS,
) -> dict[str, Any]:
    if duckdb is None:
        msg = "duckdb is required; install with pip install oracle-btc-research[analytics]"
        raise ImportError(msg)
    if not parquet_table_exists(table_root):
        raise FileNotFoundError(f"no Parquet files found under {table_root}")

    temp_directory = duckdb_temp_directory
    if temp_directory is None:
        temp_directory = dataset_root_from_table(table_root) / "staging" / "d012_duckdb_tmp"
    tracker = PositionTracker()
    seen_keys: set[tuple[str, int]] = set()
    counts_by_stratum: defaultdict[str, int] = defaultdict(int)
    counts_by_method: defaultdict[str, int] = defaultdict(int)
    counts_by_dir: defaultdict[str, int] = defaultdict(int)
    notional_by_stratum: defaultdict[str, float] = defaultdict(float)
    notional_by_method: defaultdict[str, float] = defaultdict(float)
    cross_by_method: defaultdict[str, AggregationBuckets] = defaultdict(AggregationBuckets)
    stratum_method_counts = empty_nested_counter()
    stratum_method_notional = empty_nested_counter()

    conn = duckdb.connect(database=":memory:", read_only=False)
    try:
        configure_duckdb(
            conn,
            memory_limit=duckdb_memory_limit,
            temp_directory=temp_directory,
        )
        process_fill_stream(
            iter_census_fills_from_duckdb(
                conn,
                table_root=table_root,
                batch_rows=batch_rows,
                progress_every_sources=progress_every_sources,
                progress_every_rows=progress_every_rows,
            ),
            tracker=tracker,
            seen_keys=seen_keys,
            counts_by_stratum=counts_by_stratum,
            counts_by_method=counts_by_method,
            counts_by_dir=counts_by_dir,
            notional_by_stratum=notional_by_stratum,
            notional_by_method=notional_by_method,
            cross_by_method=cross_by_method,
            stratum_method_counts=stratum_method_counts,
            stratum_method_notional=stratum_method_notional,
        )
    finally:
        conn.close()

    total_events = sum(counts_by_stratum.values())
    total_notional = sum(notional_by_stratum.values())
    tractable_notional = (
        notional_by_stratum.get("a_btc_only_isolated", 0.0)
        + notional_by_stratum.get("b_btc_only_cross", 0.0)
    )
    tractable_share = tractable_notional / total_notional if total_notional > 0 else 0.0

    return {
        "experiment": "EXP-001",
        "phase": "stratification_census_from_hl_parquet_v1",
        "parquet_table_root": str(table_root),
        "dedupe_key": ["liquidatedUser", "tid"],
        "liquidated_leg_only": True,
        "total_btc_liquidation_events": total_events,
        "total_btc_liquidation_notional_usd": total_notional,
        "tractable_notional_usd": tractable_notional,
        "tractable_share": tractable_share,
        "early_demotion_triggered": tractable_share < EARLY_DEMOTION_THRESHOLD,
        "early_demotion_threshold": EARLY_DEMOTION_THRESHOLD,
        "partial_viability_threshold": PARTIAL_VIABILITY_THRESHOLD,
        "partial_viability_met": tractable_share >= PARTIAL_VIABILITY_THRESHOLD,
        "counts_by_stratum": dict(sorted(counts_by_stratum.items())),
        "notional_usd_by_stratum": {
            key: notional_by_stratum[key] for key in sorted(notional_by_stratum)
        },
        "counts_by_method": dict(sorted(counts_by_method.items())),
        "notional_usd_by_method": {
            key: notional_by_method[key] for key in sorted(notional_by_method)
        },
        "counts_by_dir": dict(sorted(counts_by_dir.items(), key=lambda item: (-item[1], item[0]))),
        "counts_by_stratum_and_method": {
            stratum: dict(sorted(methods.items()))
            for stratum, methods in sorted(stratum_method_counts.items())
        },
        "notional_usd_by_stratum_and_method": {
            stratum: dict(sorted(methods.items()))
            for stratum, methods in sorted(stratum_method_notional.items())
        },
        "cross_asset_by_method": {
            method: {
                "event_count": bucket.event_count,
                "notional_usd": bucket.notional_usd,
            }
            for method, bucket in sorted(cross_by_method.items())
        },
    }


def compare_int(name: str, actual: int, expected: int) -> dict[str, Any]:
    return {
        "field": name,
        "actual": actual,
        "expected": expected,
        "passed": actual == expected,
        "difference": actual - expected,
    }


def compare_float(
    name: str,
    actual: float,
    expected: float,
    *,
    rel_tolerance: float | None = None,
    abs_tolerance: float | None = None,
) -> dict[str, Any]:
    difference = actual - expected
    if abs_tolerance is not None:
        passed = abs(difference) <= abs_tolerance
        tolerance = abs_tolerance
        tolerance_type = "absolute"
    else:
        denominator = abs(expected) if expected != 0 else 1.0
        relative = abs(difference) / denominator
        passed = relative <= (rel_tolerance or 0.0)
        tolerance = rel_tolerance
        tolerance_type = "relative"
    return {
        "field": name,
        "actual": actual,
        "expected": expected,
        "passed": passed,
        "difference": difference,
        "tolerance": tolerance,
        "tolerance_type": tolerance_type,
    }


def compare_mapping_counts(
    name: str,
    actual: dict[str, int],
    expected: dict[str, int],
) -> list[dict]:
    keys = sorted(set(actual) | set(expected))
    return [compare_int(f"{name}.{key}", actual.get(key, 0), expected.get(key, 0)) for key in keys]


def compare_mapping_notional(
    name: str,
    actual: dict[str, float],
    expected: dict[str, float],
) -> list[dict]:
    keys = sorted(set(actual) | set(expected))
    return [
        compare_float(
            f"{name}.{key}",
            float(actual.get(key, 0.0)),
            float(expected.get(key, 0.0)),
            rel_tolerance=REL_TOLERANCE,
        )
        for key in keys
    ]


def compare_to_expected(actual: dict[str, Any], expected: dict[str, Any]) -> list[dict[str, Any]]:
    comparisons: list[dict[str, Any]] = [
        compare_int(
            "total_btc_liquidation_events",
            int(actual["total_btc_liquidation_events"]),
            int(expected["total_btc_liquidation_events"]),
        ),
        compare_float(
            "total_btc_liquidation_notional_usd",
            float(actual["total_btc_liquidation_notional_usd"]),
            float(expected["total_btc_liquidation_notional_usd"]),
            rel_tolerance=REL_TOLERANCE,
        ),
        compare_float(
            "tractable_share",
            float(actual["tractable_share"]),
            float(expected["tractable_share"]),
            abs_tolerance=TRACTABLE_SHARE_ABS_TOLERANCE,
        ),
    ]
    comparisons.extend(
        compare_mapping_counts(
            "counts_by_stratum",
            actual["counts_by_stratum"],
            expected["counts_by_stratum"],
        )
    )
    comparisons.extend(
        compare_mapping_notional(
            "notional_usd_by_stratum",
            actual["notional_usd_by_stratum"],
            expected["notional_usd_by_stratum"],
        )
    )
    comparisons.extend(
        compare_mapping_counts(
            "counts_by_method",
            actual["counts_by_method"],
            expected["counts_by_method"],
        )
    )
    comparisons.extend(
        compare_mapping_notional(
            "notional_usd_by_method",
            actual["notional_usd_by_method"],
            expected["notional_usd_by_method"],
        )
    )
    return comparisons


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# HL Parquet v1 parity gate",
        "",
        f"- Status: **{report['status']}**",
        f"- Parquet table: `{report['parquet_table_root']}`",
        f"- Expected census: `{report['expected_path']}`",
        "",
    ]
    if report["status"] == "MISSING_DATA":
        lines.extend(
            [
                "The Parquet dataset was not present in this environment.",
                "Run the builder on the data host, then rerun this gate.",
                "",
            ]
        )
        return "\n".join(lines)

    lines.extend(
        [
            "| Check | Actual | Expected | Pass |",
            "|---|---:|---:|---|",
        ]
    )
    for check in report["comparisons"]:
        passed = "yes" if check["passed"] else "NO"
        lines.append(
            f"| `{check['field']}` | {check['actual']} | {check['expected']} | {passed} |"
        )
    lines.append("")
    return "\n".join(lines)


def missing_data_report(table_root: Path, expected_path: Path) -> dict[str, Any]:
    return {
        "status": "MISSING_DATA",
        "parquet_table_root": str(table_root),
        "expected_path": display_path(expected_path),
        "note": "No Parquet files found; run the D-012 builder on the data host.",
        "tolerances": {
            "notional_relative": REL_TOLERANCE,
            "tractable_share_absolute": TRACTABLE_SHARE_ABS_TOLERANCE,
        },
        "comparisons": [],
    }


def write_report(
    report: dict[str, Any],
    output_dir: Path,
    expected_path: Path,
) -> tuple[Path, Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "parity.json"
    md_path = output_dir / "parity.md"
    json_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    md_path.write_text(render_markdown(report), encoding="utf-8")

    provenance_inputs = [expected_path]
    manifest_path = dataset_root_from_table(Path(report["parquet_table_root"])) / "manifest.json"
    if manifest_path.exists():
        provenance_inputs.append(manifest_path)

    sidecar = write_provenance_sidecar(
        output_dir,
        "parity",
        build_provenance(
            repo_root=REPO_ROOT,
            config={
                "gate": "hl_parquet_v1_exp001_census_parity",
                "status": report["status"],
                "parquet_table_root": report["parquet_table_root"],
                "expected_path": display_path(expected_path),
                "tolerances": report["tolerances"],
            },
            inputs=provenance_inputs,
            outputs=[json_path, md_path],
            output_base=output_dir,
        ),
    )
    return json_path, md_path, sidecar


def dataset_root_from_table(table_root: Path) -> Path:
    if table_root.name == "all_fills":
        return table_root.parent
    return table_root


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--data-root",
        type=Path,
        required=True,
        help="Oracle data root containing derived/hyperliquid/fills/v1/all_fills.",
    )
    parser.add_argument(
        "--parquet-root",
        type=Path,
        default=None,
        help="Override the all-fills Parquet table root.",
    )
    parser.add_argument(
        "--expected",
        type=Path,
        default=DEFAULT_EXPECTED,
        help="Banked EXP-001 stratification_census.json.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="Directory for parity.{json,md} and D-019 sidecar.",
    )
    parser.add_argument(
        "--batch-rows",
        type=int,
        default=100_000,
        help="DuckDB fetch batch size for streaming census replay.",
    )
    parser.add_argument(
        "--duckdb-memory-limit",
        default=DEFAULT_DUCKDB_MEMORY_LIMIT,
        help="DuckDB memory_limit setting for parity replay.",
    )
    parser.add_argument(
        "--duckdb-temp-directory",
        type=Path,
        default=None,
        help=(
            "DuckDB spill directory. Defaults to "
            "{data_root}/staging/d012_duckdb_tmp."
        ),
    )
    parser.add_argument(
        "--progress-every-sources",
        type=int,
        default=DEFAULT_PROGRESS_EVERY_SOURCES,
        help="Print progress every N source_path values (0 to disable).",
    )
    parser.add_argument(
        "--progress-every-rows",
        type=int,
        default=DEFAULT_PROGRESS_EVERY_ROWS,
        help="Print progress every N streamed rows (0 to disable).",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.batch_rows <= 0:
        print("--batch-rows must be positive", file=sys.stderr)
        return 2
    if args.progress_every_sources < 0:
        print("--progress-every-sources must be non-negative", file=sys.stderr)
        return 2
    if args.progress_every_rows < 0:
        print("--progress-every-rows must be non-negative", file=sys.stderr)
        return 2
    if not args.duckdb_memory_limit:
        print("--duckdb-memory-limit must be non-empty", file=sys.stderr)
        return 2

    data_root = args.data_root.resolve()
    table_root = args.parquet_root.resolve() if args.parquet_root else all_fills_root(data_root)
    expected_path = args.expected.resolve()
    output_dir = args.output_dir.resolve()
    duckdb_temp_directory = (
        args.duckdb_temp_directory.resolve()
        if args.duckdb_temp_directory
        else data_root / "staging" / "d012_duckdb_tmp"
    )

    if not expected_path.exists():
        print(f"expected census missing: {expected_path}", file=sys.stderr)
        return 2

    if not parquet_table_exists(table_root):
        report = missing_data_report(table_root, expected_path)
        json_path, md_path, sidecar = write_report(report, output_dir, expected_path)
        print(f"missing parquet data; wrote {json_path}, {md_path}, {sidecar}", file=sys.stderr)
        return 2

    with expected_path.open("r", encoding="utf-8") as handle:
        expected = json.load(handle)
    actual = run_census_from_parquet(
        table_root,
        batch_rows=args.batch_rows,
        duckdb_memory_limit=args.duckdb_memory_limit,
        duckdb_temp_directory=duckdb_temp_directory,
        progress_every_sources=args.progress_every_sources,
        progress_every_rows=args.progress_every_rows,
    )
    comparisons = compare_to_expected(actual, expected)
    passed = all(check["passed"] for check in comparisons)
    report = {
        "status": "PASS" if passed else "FAIL",
        "parquet_table_root": str(table_root),
        "expected_path": display_path(expected_path),
        "tolerances": {
            "notional_relative": REL_TOLERANCE,
            "tractable_share_absolute": TRACTABLE_SHARE_ABS_TOLERANCE,
        },
        "actual": actual,
        "expected": expected,
        "comparisons": comparisons,
    }
    json_path, md_path, sidecar = write_report(report, output_dir, expected_path)
    print(f"status={report['status']} wrote {json_path}, {md_path}, {sidecar}")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
