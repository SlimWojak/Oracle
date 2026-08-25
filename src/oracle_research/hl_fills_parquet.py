"""Parquet materialization helpers for normalized Hyperliquid fill rows."""

from __future__ import annotations

import hashlib
import json
import shutil
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from oracle_research.hyperliquid_fills import HlFill
from oracle_research.provenance import git_commit, sha256_file

try:
    import pyarrow as pa
    import pyarrow.parquet as pq
except ImportError:  # optional dependency group ``analytics``
    pa = None  # type: ignore[assignment]
    pq = None  # type: ignore[assignment]

BUILDER_VERSION = "hl_fills_parquet_v1"
DATASET_VERSION = "v1"
DEFAULT_COMPRESSION = "zstd"
DEFAULT_CHUNK_ROWS = 50_000

REQUIRED_COLUMNS: tuple[str, ...] = (
    "user",
    "coin",
    "px",
    "sz",
    "side",
    "time_ms",
    "start_position",
    "dir",
    "hash",
    "oid",
    "crossed",
    "tid",
    "fee",
    "fee_token",
    "liquidation_liquidated_user",
    "liquidation_mark_px",
    "liquidation_method",
    "block_time",
    "local_time",
    "block_number",
    "source_format",
    "source_path",
    "builder_version",
)

EXTRA_COLUMNS: tuple[str, ...] = (
    "source_row_number",
    "event_date",
    "event_hour",
)


def _schema():
    if pa is None:
        msg = "pyarrow is required; install with pip install oracle-btc-research[analytics]"
        raise ImportError(msg)
    return pa.schema(
        [
            ("user", pa.string()),
            ("coin", pa.string()),
            ("px", pa.string()),
            ("sz", pa.string()),
            ("side", pa.string()),
            ("time_ms", pa.int64()),
            ("start_position", pa.string()),
            ("dir", pa.string()),
            ("hash", pa.string()),
            ("oid", pa.int64()),
            ("crossed", pa.bool_()),
            ("tid", pa.int64()),
            ("fee", pa.string()),
            ("fee_token", pa.string()),
            ("liquidation_liquidated_user", pa.string()),
            ("liquidation_mark_px", pa.string()),
            ("liquidation_method", pa.string()),
            ("block_time", pa.int64()),
            ("local_time", pa.int64()),
            ("block_number", pa.int64()),
            ("source_format", pa.string()),
            ("source_path", pa.string()),
            ("builder_version", pa.string()),
            ("source_row_number", pa.int64()),
            ("event_date", pa.string()),
            ("event_hour", pa.int64()),
        ]
    )


fills_parquet_schema = _schema


@dataclass(frozen=True, slots=True)
class ParquetWriteResult:
    """Metadata for one Parquet output file."""

    path: Path
    rows: int
    partition_date: str
    partition_hour: int
    sha256: str
    bytes: int


def dataset_root(data_root: Path) -> Path:
    """Return the D-012 HL fills derived dataset root for ``data_root``."""

    return Path(data_root) / "derived" / "hyperliquid" / "fills" / DATASET_VERSION


def all_fills_root(data_root: Path) -> Path:
    """Return the primary all-fills Parquet table root."""

    return dataset_root(data_root) / "all_fills"


def raw_root(data_root: Path) -> Path:
    """Return the raw root used for relative source paths."""

    return Path(data_root) / "raw"


def hyperliquid_hourly_files(data_root: Path) -> list[Path]:
    """Return sorted Hyperliquid hourly fill files from both raw source formats."""

    base = raw_root(data_root) / "hyperliquid"
    prefixes = (
        base / "node_fills" / "hourly",
        base / "node_fills_by_block" / "hourly",
    )
    paths: list[Path] = []
    for prefix in prefixes:
        if prefix.is_dir():
            paths.extend(prefix.rglob("*.lz4"))
    return sorted(paths, key=lambda item: str(item))


def source_format_for_path(path: Path, data_root: Path) -> str:
    """Return the raw source format label for one hourly fill path."""

    relative = Path(path).relative_to(raw_root(data_root))
    if "node_fills_by_block" in relative.parts:
        return "by_block"
    if "node_fills" in relative.parts:
        return "old_hourly"
    raise ValueError(f"unrecognized Hyperliquid fill path: {path}")


def relative_source_path(path: Path, data_root: Path) -> str:
    """Return ``path`` relative to ``{data_root}/raw`` using POSIX separators."""

    return Path(path).relative_to(raw_root(data_root)).as_posix()


def utc_partition(time_ms: int) -> tuple[str, int]:
    """Return the UTC date and hour partition for an event timestamp in ms."""

    instant = datetime.fromtimestamp(time_ms / 1000, tz=UTC)
    return instant.strftime("%Y-%m-%d"), instant.hour


def fill_to_parquet_row(
    fill: HlFill,
    *,
    source_format: str,
    source_path: str,
    source_row_number: int,
    builder_version: str,
) -> dict[str, Any]:
    """Convert one normalized ``HlFill`` into the stable Parquet row schema."""

    event_date, event_hour = utc_partition(fill.time_ms)
    liquidation = fill.liquidation or {}
    return {
        "user": fill.user,
        "coin": fill.coin,
        "px": fill.px,
        "sz": fill.sz,
        "side": fill.side,
        "time_ms": fill.time_ms,
        "start_position": fill.start_position,
        "dir": fill.dir,
        "hash": fill.hash,
        "oid": fill.oid,
        "crossed": fill.crossed,
        "tid": fill.tid,
        "fee": fill.fee,
        "fee_token": fill.fee_token,
        "liquidation_liquidated_user": liquidation.get("liquidatedUser"),
        "liquidation_mark_px": liquidation.get("markPx"),
        "liquidation_method": liquidation.get("method"),
        "block_time": fill.block_time,
        "local_time": fill.local_time,
        "block_number": fill.block_number,
        "source_format": source_format,
        "source_path": source_path,
        "builder_version": builder_version,
        "source_row_number": source_row_number,
        "event_date": event_date,
        "event_hour": event_hour,
    }


def prepare_output_root(output_root: Path, *, overwrite: bool) -> None:
    """Create or replace the output table root."""

    if output_root.exists():
        has_files = any(output_root.iterdir())
        if has_files and not overwrite:
            raise FileExistsError(f"{output_root} is not empty; pass --overwrite to rebuild")
        if overwrite:
            shutil.rmtree(output_root)
    output_root.mkdir(parents=True, exist_ok=True)


def stable_source_id(source_path: str) -> str:
    """Return a short deterministic identifier for output file naming."""

    return hashlib.sha256(source_path.encode("utf-8")).hexdigest()[:16]


def write_partitioned_chunk(
    rows: Iterable[dict[str, Any]],
    *,
    output_root: Path,
    source_path: str,
    chunk_index: int,
    compression: str,
) -> list[ParquetWriteResult]:
    """Write a bounded chunk of rows into UTC hour Hive partitions."""

    if pq is None:
        msg = "pyarrow is required; install with pip install oracle-btc-research[analytics]"
        raise ImportError(msg)

    by_partition: dict[tuple[str, int], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_partition[(str(row["event_date"]), int(row["event_hour"]))].append(row)

    results: list[ParquetWriteResult] = []
    source_id = stable_source_id(source_path)
    for partition_index, ((event_date, event_hour), partition_rows) in enumerate(
        sorted(by_partition.items()),
    ):
        partition_dir = output_root / f"date={event_date}" / f"hour={event_hour:02d}"
        partition_dir.mkdir(parents=True, exist_ok=True)
        out_path = (
            partition_dir
            / f"part-{source_id}-{chunk_index:05d}-{partition_index:02d}.parquet"
        )
        table = pa.Table.from_pylist(partition_rows, schema=_schema())
        pq.write_table(table, out_path, compression=compression)
        digest = sha256_file(out_path)
        results.append(
            ParquetWriteResult(
                path=out_path,
                rows=len(partition_rows),
                partition_date=event_date,
                partition_hour=event_hour,
                sha256=digest,
                bytes=out_path.stat().st_size,
            )
        )
    return results


def partition_digest(entries: Iterable[dict[str, Any]]) -> str:
    """Return a deterministic digest across output file manifest entries."""

    digest = hashlib.sha256()
    for entry in sorted(entries, key=lambda item: str(item["path"])):
        payload = {
            "path": entry["path"],
            "bytes": entry["bytes"],
            "sha256": entry["sha256"],
            "rows": entry["rows"],
        }
        digest.update(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode())
        digest.update(b"\n")
    return digest.hexdigest()


def make_output_entry(result: ParquetWriteResult, *, base: Path) -> dict[str, Any]:
    """Serialize one Parquet output-file manifest entry."""

    return {
        "path": result.path.relative_to(base).as_posix(),
        "bytes": result.bytes,
        "sha256": result.sha256,
        "rows": result.rows,
        "partition_date": result.partition_date,
        "partition_hour": result.partition_hour,
    }


def build_manifest(
    *,
    repo_root: Path,
    data_root: Path,
    output_root: Path,
    started_at_utc: str,
    ended_at_utc: str,
    builder_version: str,
    compression: str,
    chunk_rows: int,
    input_manifest_ids: list[str],
    input_file_counts: dict[str, int],
    row_counts: dict[str, int],
    output_entries: list[dict[str, Any]],
) -> dict[str, Any]:
    """Assemble the rebuild manifest for the derived HL fills table."""

    return {
        "dataset": "hyperliquid_fills",
        "dataset_version": DATASET_VERSION,
        "builder_version": builder_version,
        "repo_commit": git_commit(repo_root),
        "started_at_utc": started_at_utc,
        "ended_at_utc": ended_at_utc,
        "data_root": str(Path(data_root)),
        "raw_root": str(raw_root(data_root)),
        "output_root": str(output_root),
        "primary_table": "all_fills",
        "partitioning": "Hive UTC date/hour: date=YYYY-MM-DD/hour=HH",
        "compression": compression,
        "chunk_rows": chunk_rows,
        "required_columns": list(REQUIRED_COLUMNS),
        "extra_columns": list(EXTRA_COLUMNS),
        "input_raw_manifest_ids": input_manifest_ids,
        "input_file_counts": input_file_counts,
        "row_counts": row_counts,
        "output_file_count": len(output_entries),
        "output_files": output_entries,
        "hive_partition_digest": partition_digest(output_entries),
    }
