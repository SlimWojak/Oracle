#!/usr/bin/env python3
"""Build the D-012 Hyperliquid all-fills Parquet dataset."""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path

from oracle_research.hl_fills_parquet import (
    BUILDER_VERSION,
    DEFAULT_CHUNK_ROWS,
    DEFAULT_COMPRESSION,
    all_fills_root,
    build_manifest,
    fill_to_parquet_row,
    hyperliquid_hourly_files,
    make_output_entry,
    prepare_output_root,
    relative_source_path,
    source_format_for_path,
    write_partitioned_chunk,
)
from oracle_research.hyperliquid_fills import iter_fills_from_lz4
from oracle_research.provenance import build_provenance, write_provenance_sidecar

REPO_ROOT = Path(__file__).resolve().parent.parent


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--data-root",
        type=Path,
        required=True,
        help="External immutable raw-data root.",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=None,
        help=(
            "Primary all-fills Parquet table root. Defaults to "
            "{data_root}/derived/hyperliquid/fills/v1/all_fills."
        ),
    )
    parser.add_argument(
        "--hour-limit",
        type=int,
        default=None,
        help="Process at most this many hourly lz4 files (for testing).",
    )
    parser.add_argument(
        "--chunk-rows",
        type=int,
        default=DEFAULT_CHUNK_ROWS,
        help="Maximum rows buffered before writing a Parquet chunk.",
    )
    parser.add_argument(
        "--compression",
        choices=("snappy", "zstd"),
        default=DEFAULT_COMPRESSION,
        help="Parquet compression codec recorded in the manifest.",
    )
    parser.add_argument(
        "--builder-version",
        default=BUILDER_VERSION,
        help="Transformation version written on every row and into the manifest.",
    )
    parser.add_argument(
        "--input-manifest-id",
        action="append",
        default=[],
        help="Optional raw manifest identifier/path to record in the derived manifest.",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Replace an existing all_fills table root before rebuilding.",
    )
    parser.add_argument(
        "--progress-every",
        type=int,
        default=100,
        help="Print progress every N input files (0 to disable).",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.chunk_rows <= 0:
        print("--chunk-rows must be positive", file=sys.stderr)
        return 2

    data_root = args.data_root.resolve()
    output_root = args.output_root.resolve() if args.output_root else all_fills_root(data_root)
    manifest_dir = output_root.parent
    manifest_path = manifest_dir / "manifest.json"

    hourly_files = hyperliquid_hourly_files(data_root)
    if args.hour_limit is not None:
        hourly_files = hourly_files[: args.hour_limit]
    if not hourly_files:
        print(
            f"no hourly lz4 files under {data_root}/raw/hyperliquid",
            file=sys.stderr,
        )
        return 2

    try:
        prepare_output_root(output_root, overwrite=args.overwrite)
    except FileExistsError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    started_at = datetime.now(tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    input_file_counts: defaultdict[str, int] = defaultdict(int)
    row_counts: defaultdict[str, int] = defaultdict(int)
    output_entries: list[dict[str, object]] = []
    total_rows = 0

    for file_index, path in enumerate(hourly_files, start=1):
        source_format = source_format_for_path(path, data_root)
        source_path = relative_source_path(path, data_root)
        input_file_counts[source_format] += 1
        chunk: list[dict[str, object]] = []
        chunk_index = 0

        for row_number, fill in enumerate(iter_fills_from_lz4(path), start=1):
            chunk.append(
                fill_to_parquet_row(
                    fill,
                    source_format=source_format,
                    source_path=source_path,
                    source_row_number=row_number,
                    builder_version=args.builder_version,
                )
            )
            if len(chunk) >= args.chunk_rows:
                for result in write_partitioned_chunk(
                    chunk,
                    output_root=output_root,
                    source_path=source_path,
                    chunk_index=chunk_index,
                    compression=args.compression,
                ):
                    output_entries.append(make_output_entry(result, base=output_root.parent))
                row_counts[source_format] += len(chunk)
                total_rows += len(chunk)
                chunk = []
                chunk_index += 1

        if chunk:
            for result in write_partitioned_chunk(
                chunk,
                output_root=output_root,
                source_path=source_path,
                chunk_index=chunk_index,
                compression=args.compression,
            ):
                output_entries.append(make_output_entry(result, base=output_root.parent))
            row_counts[source_format] += len(chunk)
            total_rows += len(chunk)

        if args.progress_every and file_index % args.progress_every == 0:
            print(
                f"processed {file_index}/{len(hourly_files)} files; rows={total_rows}",
                file=sys.stderr,
            )

    ended_at = datetime.now(tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    input_file_counts["total"] = len(hourly_files)
    row_counts["total"] = total_rows

    manifest_dir.mkdir(parents=True, exist_ok=True)
    manifest = build_manifest(
        repo_root=REPO_ROOT,
        data_root=data_root,
        output_root=output_root,
        started_at_utc=started_at,
        ended_at_utc=ended_at,
        builder_version=args.builder_version,
        compression=args.compression,
        chunk_rows=args.chunk_rows,
        input_manifest_ids=list(args.input_manifest_id),
        input_file_counts=dict(sorted(input_file_counts.items())),
        row_counts=dict(sorted(row_counts.items())),
        output_entries=[dict(entry) for entry in output_entries],
    )
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    provenance = build_provenance(
        repo_root=REPO_ROOT,
        config={
            "dataset": "hyperliquid_fills",
            "dataset_version": manifest["dataset_version"],
            "builder_version": args.builder_version,
            "data_root": str(data_root),
            "output_root": str(output_root),
            "hourly_files": len(hourly_files),
            "hour_limit": args.hour_limit,
            "chunk_rows": args.chunk_rows,
            "compression": args.compression,
            "row_count": total_rows,
        },
        inputs=[],
        outputs=[manifest_path],
        output_base=manifest_dir,
    )
    sidecar = write_provenance_sidecar(manifest_dir, "manifest", provenance)
    print(
        f"files={len(hourly_files)} rows={total_rows} out={output_root} "
        f"manifest={manifest_path} provenance={sidecar}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
