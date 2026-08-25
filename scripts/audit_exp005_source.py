#!/usr/bin/env python3
"""Run the EXP-005 Checkpoint A source/support audit without reading effects.

The audit is deliberately restricted to source archives, the D-022 source
manifest and median-index reconstruction, causal M0/flow features, and support
availability.  It never imports or calls label, outcome, cluster, estimator, or
scoring code.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
import platform
import sys
import zipfile
from collections import Counter
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, TypeVar

import numpy as np

from oracle_research.binance_klines import load_kline_dir
from oracle_research.coinbase_candles import load_candle_dir
from oracle_research.consolidated_index import build_median_index
from oracle_research.exp005_flow import (
    FLOW_FLOOR,
    JOINT_FLOOR,
    M0_COLUMNS,
    FlowMinute,
    HourlyPeriod,
    availability_report,
    build_flow_compression,
    build_m0_features,
    checkpoint_a_disposition,
    ordered_timestamp_sha256,
)
from oracle_research.kraken_klines import load_kraken_csvs
from oracle_research.provenance import (
    build_provenance,
    canonical_config_sha256,
    sha256_file,
    write_provenance_sidecar,
)

AUDIT_VERSION = "exp005_source_readiness_v1"
CONTRACT_COMMIT = "613b2106ddce63cc8c94cf81eb7b0a65f9f96b15"
MANIFEST_IDENTIFIER = "manifests/binance_vision_fetch.jsonl"
D022_MANIFEST_IDENTIFIER = "reports/exp000/index_catalogue.provenance.json"
VERIFIED_MANIFEST_STATUSES = frozenset({"downloaded", "verified_existing"})
REPO_ROOT = Path(__file__).resolve().parent.parent
SPOT_SUBDIR = "raw/binance_vision/spot/monthly/klines/BTCUSDT/1m"
COINBASE_SUBDIR = "raw/coinbase/candles/BTC-USD/1m"
KRAKEN_FILES = (
    "raw/kraken/ohlcvt/XBTUSD_1.csv",
    "raw/kraken/ohlcvt/XBTUSD_1_Q1_2026.csv",
    "derived/kraken/XBTUSD_1_2026AprJul_from_trades_v2.csv",
)
INDEX_START_TIMESTAMP = int(datetime(2020, 1, 1, tzinfo=UTC).timestamp())

KLINE_FIELDS = (
    "open_time",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "close_time",
    "quote_volume",
    "trade_count",
    "taker_buy_volume",
    "taker_buy_quote_volume",
    "ignore",
)

DEFAULT_PERIODS = (
    HourlyPeriod(
        "development",
        datetime(2020, 1, 1, tzinfo=UTC),
        datetime(2023, 12, 31, 23, tzinfo=UTC),
    ),
    HourlyPeriod(
        "validation_2024",
        datetime(2024, 1, 1, tzinfo=UTC),
        datetime(2024, 12, 31, 23, tzinfo=UTC),
    ),
    HourlyPeriod(
        "test_2025",
        datetime(2025, 1, 1, tzinfo=UTC),
        datetime(2025, 12, 31, 23, tzinfo=UTC),
    ),
    HourlyPeriod(
        "test_2026_01_07",
        datetime(2026, 1, 1, tzinfo=UTC),
        datetime(2026, 7, 31, 23, tzinfo=UTC),
    ),
)

RowT = TypeVar("RowT")


@dataclass(frozen=True, slots=True)
class ArchiveIdentity:
    relative_path: str


@dataclass(frozen=True, slots=True)
class RawKlineRow:
    open_time_us: int
    open_time_unit: str
    close_time_us: int | None
    close_time_unit: str | None
    quote_volume: float | None
    taker_buy_quote_volume: float | None
    fingerprint: tuple[str, ...]

    @property
    def interval_start(self) -> int | None:
        if self.open_time_us % 1_000_000:
            return None
        return self.open_time_us // 1_000_000

    @property
    def interval_end(self) -> int | None:
        start = self.interval_start
        return None if start is None else start + 60

    @property
    def on_minute_grid(self) -> bool:
        start = self.interval_start
        return start is not None and start % 60 == 0

    @property
    def close_is_causal(self) -> bool:
        return (
            self.close_time_us is not None
            and self.open_time_us <= self.close_time_us <= self.open_time_us + 60_000_000
        )


@dataclass(slots=True)
class SourceStats:
    rows: int = 0
    archives_read: int = 0
    archive_errors: list[dict[str, str]] = field(default_factory=list)
    headers: Counter[str] = field(default_factory=Counter)
    headerless_archives: int = 0
    schema_valid_rows: int = 0
    schema_invalid_rows: int = 0
    timestamp_units: Counter[str] = field(default_factory=Counter)
    timestamp_min_us: int | None = None
    timestamp_max_us: int | None = None
    off_grid_rows: int = 0
    out_of_order_rows: int = 0
    duplicate_rows: int = 0
    conflicting_timestamps: int = 0
    identical_duplicate_timestamps: int = 0
    gap_runs: int = 0
    missing_minutes: int = 0
    fields: dict[str, Counter[str]] = field(default_factory=dict)
    close_time: Counter[str] = field(default_factory=Counter)

    def field(self, name: str) -> Counter[str]:
        return self.fields.setdefault(name, Counter())

    def observe_timestamp(self, timestamp_us: int, unit: str) -> None:
        self.timestamp_units[unit] += 1
        self.timestamp_min_us = (
            timestamp_us
            if self.timestamp_min_us is None
            else min(self.timestamp_min_us, timestamp_us)
        )
        self.timestamp_max_us = (
            timestamp_us
            if self.timestamp_max_us is None
            else max(self.timestamp_max_us, timestamp_us)
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "rows": self.rows,
            "archives_read": self.archives_read,
            "archive_errors": sorted(
                self.archive_errors, key=lambda item: (item["archive"], item["reason"])
            ),
            "schema": {
                "ordered_positions": list(KLINE_FIELDS),
                "expected_positions": 12,
                "valid_rows": self.schema_valid_rows,
                "invalid_rows": self.schema_invalid_rows,
                "headers": dict(sorted(self.headers.items())),
                "headerless_archives": self.headerless_archives,
            },
            "epoch_units": dict(sorted(self.timestamp_units.items())),
            "expected_open_time_epoch_unit": "epoch_ms",
            "epoch_unit_contract_pass": set(self.timestamp_units) == {"epoch_ms"},
            "normalized_open_time_range": {
                "first": _format_epoch_us(self.timestamp_min_us),
                "last": _format_epoch_us(self.timestamp_max_us),
            },
            "interval_semantics": {
                "raw_open_time": "interval_start",
                "causal_interval_end": "normalized open_time + 60s",
                "latest_feature_block": "T-5m",
                "complete_before_use": True,
                "off_grid_rows": self.off_grid_rows,
            },
            "raw_close_time": {
                key: self.close_time.get(key, 0)
                for key in (
                    "standard_offset",
                    "nonstandard_offset",
                    "before_open",
                    "after_nominal_end",
                    "causal",
                    "unparseable",
                )
            },
            "duplicates": {
                "duplicate_rows": self.duplicate_rows,
                "identical_duplicate_timestamps": self.identical_duplicate_timestamps,
                "conflicting_timestamps": self.conflicting_timestamps,
                "handling": "identical raw rows collapse once; differing rows are missing",
            },
            "ordering_and_gaps": {
                "raw_out_of_order_rows": self.out_of_order_rows,
                "normalized_gap_runs": self.gap_runs,
                "normalized_missing_minutes": self.missing_minutes,
                "no_fill": True,
            },
            "field_audit": {
                name: {
                    key: counter.get(key, 0)
                    for key in ("finite", "null", "nonfinite", "zero", "negative")
                }
                for name, counter in sorted(self.fields.items())
            },
        }


def _month_range(start: str, end: str) -> Iterator[str]:
    year, month = map(int, start.split("-"))
    end_year, end_month = map(int, end.split("-"))
    while (year, month) <= (end_year, end_month):
        yield f"{year:04d}-{month:02d}"
        month += 1
        if month == 13:
            year += 1
            month = 1


def expected_um_archive_identities() -> tuple[ArchiveIdentity, ...]:
    """Return only the frozen 79 Binance USD-M BTCUSDT 1m identities."""

    return tuple(
        ArchiveIdentity(
            "futures/um/monthly/klines/BTCUSDT/1m/"
            f"BTCUSDT-1m-{month}.zip"
        )
        for month in _month_range("2020-01", "2026-07")
    )


def _parse_integer(text: str, *, field_name: str) -> int:
    value = text.strip()
    if not value:
        raise ValueError(f"{field_name} is empty")
    try:
        decimal = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError(f"{field_name} is not numeric") from exc
    integral = decimal.to_integral_value()
    if decimal != integral:
        raise ValueError(f"{field_name} is fractional")
    return int(integral)


def parse_epoch_us_exact(text: str, *, field_name: str) -> tuple[int, str]:
    """Normalize exact epoch seconds, milliseconds, or microseconds without flooring."""

    raw = _parse_integer(text, field_name=field_name)
    magnitude = abs(raw)
    if magnitude >= 1_000_000_000_000_000:
        return raw, "epoch_us"
    if magnitude >= 1_000_000_000_000:
        return raw * 1_000, "epoch_ms"
    return raw * 1_000_000, "epoch_s"


def _parse_float(text: str, counter: Counter[str]) -> float | None:
    value = text.strip()
    if not value:
        counter["null"] += 1
        return None
    try:
        parsed = float(value)
    except ValueError:
        counter["nonfinite"] += 1
        return None
    if not math.isfinite(parsed):
        counter["nonfinite"] += 1
        return None
    counter["finite"] += 1
    if parsed == 0.0:
        counter["zero"] += 1
    if parsed < 0.0:
        counter["negative"] += 1
    return parsed


def _format_epoch_us(value: int | None) -> str | None:
    if value is None:
        return None
    seconds, microseconds = divmod(value, 1_000_000)
    return (
        datetime.fromtimestamp(seconds, tz=UTC)
        .replace(microsecond=microseconds)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _read_jsonl(path: Path) -> tuple[list[dict[str, Any]], list[dict[str, object]]]:
    records: list[dict[str, Any]] = []
    errors: list[dict[str, object]] = []
    try:
        handle = path.open("r", encoding="utf-8")
    except OSError as exc:
        reason = str(exc).replace(str(path), path.name)
        return [], [{"line": 0, "reason": f"open_error:{reason}"}]
    with handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                errors.append({"line": line_number, "reason": f"invalid_json:{exc.msg}"})
                continue
            if not isinstance(record, dict):
                errors.append({"line": line_number, "reason": "record_not_object"})
                continue
            records.append(record)
    return records, errors


def _valid_sha256(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value.lower())
    )


def verify_um_manifest(
    *,
    data_root: Path,
    identities: Sequence[ArchiveIdentity],
) -> tuple[dict[str, object], list[Path]]:
    """Select and reverify only the frozen UM identity set from the full manifest."""

    manifest_path = data_root / MANIFEST_IDENTIFIER
    records, parse_errors = _read_jsonl(manifest_path)
    expected_paths = tuple(identity.relative_path for identity in identities)
    if len(set(expected_paths)) != len(expected_paths):
        raise ValueError("expected UM archive identities must be unique")
    records_by_path: dict[str, list[dict[str, Any]]] = {}
    for record in records:
        relative_path = record.get("relative_path")
        if isinstance(relative_path, str):
            records_by_path.setdefault(relative_path, []).append(record)

    failures: list[dict[str, str]] = []
    selected: list[dict[str, object]] = []
    archive_paths: list[Path] = []
    retrieval_times: list[str] = []
    duplicate_manifest_records = 0
    for relative_path in expected_paths:
        matching = records_by_path.get(relative_path, [])
        if not matching:
            failures.append({"archive": relative_path, "reason": "missing_manifest_record"})
            continue
        duplicate_manifest_records += max(0, len(matching) - 1)
        verified = [
            record
            for record in matching
            if record.get("status") in VERIFIED_MANIFEST_STATUSES
            and isinstance(record.get("size_bytes"), int)
            and int(record["size_bytes"]) > 0
            and _valid_sha256(record.get("sha256"))
        ]
        if not verified:
            failures.append({"archive": relative_path, "reason": "no_valid_manifest_record"})
            continue
        signatures = {
            (int(record["size_bytes"]), str(record["sha256"]).lower()) for record in verified
        }
        if len(signatures) != 1:
            failures.append({"archive": relative_path, "reason": "conflicting_manifest_records"})
            continue
        record = verified[-1]
        retrieved_at = record.get("retrieved_at")
        if isinstance(retrieved_at, str):
            retrieval_times.append(retrieved_at)
        disk_path = data_root / "raw" / "binance_vision" / relative_path
        expected_bytes, expected_sha = next(iter(signatures))
        if not disk_path.is_file():
            failures.append({"archive": relative_path, "reason": "missing_on_disk"})
            continue
        if disk_path.stat().st_size != expected_bytes:
            failures.append({"archive": relative_path, "reason": "size_mismatch"})
            continue
        actual_sha = sha256_file(disk_path)
        if actual_sha != expected_sha:
            failures.append({"archive": relative_path, "reason": "sha256_mismatch"})
            continue
        archive_paths.append(disk_path)
        selected.append(
            {
                "relative_path": relative_path,
                "bytes": expected_bytes,
                "sha256": expected_sha,
                "retrieved_at": retrieved_at,
            }
        )

    selected_hash = hashlib.sha256()
    selected_hash.update(b"oracle-exp005-selected-um-archive-identities-v1\n")
    for relative_path in expected_paths:
        selected_hash.update(f"{relative_path}\n".encode())
    selected_records = sum(len(records_by_path.get(path, [])) for path in expected_paths)
    summary = {
        "identifier": MANIFEST_IDENTIFIER,
        "bytes": manifest_path.stat().st_size if manifest_path.is_file() else None,
        "sha256": sha256_file(manifest_path) if manifest_path.is_file() else None,
        "full_manifest_records": len(records),
        "parse_errors": parse_errors,
        "selection": "only Binance USD-M BTCUSDT monthly 1m klines, 2020-01..2026-07",
        "expected_selected_identities": len(expected_paths),
        "selected_manifest_records": selected_records,
        "duplicate_selected_manifest_records": duplicate_manifest_records,
        "nonselected_manifest_records_ignored": len(records) - selected_records,
        "selected_integrity_valid": len(selected),
        "selected_archive_identities_sha256": selected_hash.hexdigest(),
        "retrieval_range": {
            "first": min(retrieval_times) if retrieval_times else None,
            "last": max(retrieval_times) if retrieval_times else None,
        },
        "selected_archives": selected,
        "failures": sorted(failures, key=lambda item: (item["archive"], item["reason"])),
        "exact_selected_identity_set": (
            len(expected_paths) == 79
            and len(selected) == len(expected_paths)
            and not parse_errors
            and not failures
        ),
    }
    return summary, archive_paths


def _looks_numeric(text: str) -> bool:
    try:
        Decimal(text.strip().lstrip("\ufeff"))
    except InvalidOperation:
        return False
    return True


def _header_positions(header: Sequence[str]) -> dict[str, int]:
    normalized = {name.strip().lower(): index for index, name in enumerate(header)}
    aliases = {
        "quote_volume": ("quote_volume", "quote_asset_volume"),
        "trade_count": ("trade_count", "number_of_trades", "count"),
        "taker_buy_volume": (
            "taker_buy_volume",
            "taker_buy_base",
            "taker_buy_base_volume",
        ),
        "taker_buy_quote_volume": ("taker_buy_quote_volume", "taker_buy_quote"),
    }
    positions: dict[str, int] = {}
    for field_name in KLINE_FIELDS:
        candidates = aliases.get(field_name, (field_name,))
        position = next((normalized[name] for name in candidates if name in normalized), None)
        if position is None:
            raise ValueError(f"missing_field:{field_name}")
        positions[field_name] = position
    return positions


def _csv_rows(path: Path, stats: SourceStats) -> Iterator[tuple[list[str], tuple[str, ...] | None]]:
    try:
        with zipfile.ZipFile(path) as archive:
            members = sorted(
                name
                for name in archive.namelist()
                if name.lower().endswith(".csv") and not name.endswith("/")
            )
            if len(members) != 1:
                raise ValueError(f"expected_one_csv_found_{len(members)}")
            stats.archives_read += 1
            with archive.open(members[0]) as binary:
                reader = csv.reader(io.TextIOWrapper(binary, encoding="utf-8-sig", newline=""))
                try:
                    first = next(reader)
                except StopIteration:
                    raise ValueError("empty_csv") from None
                has_header = not first or not _looks_numeric(first[0])
                header: tuple[str, ...] | None = None
                if has_header:
                    header = tuple(value.strip() for value in first)
                    stats.headers[",".join(header)] += 1
                else:
                    stats.headerless_archives += 1
                    yield first, None
                for values in reader:
                    if values and any(value.strip() for value in values):
                        yield values, header
    except (OSError, ValueError, zipfile.BadZipFile) as exc:
        stats.archive_errors.append({"archive": path.name, "reason": str(exc)})


def _parse_archive(path: Path, stats: SourceStats) -> list[RawKlineRow]:
    rows: list[RawKlineRow] = []
    previous_raw: int | None = None
    for values, header in _csv_rows(path, stats):
        stats.rows += 1
        try:
            if len(values) != 12 or (header is not None and len(header) != 12):
                raise ValueError(f"schema_not_12_positions:{len(values)}")
            positions = (
                {name: index for index, name in enumerate(KLINE_FIELDS)}
                if header is None
                else _header_positions(header)
            )
            open_time_us, open_unit = parse_epoch_us_exact(
                values[positions["open_time"]], field_name="open_time"
            )
            if previous_raw is not None and open_time_us < previous_raw:
                stats.out_of_order_rows += 1
            previous_raw = open_time_us
            stats.observe_timestamp(open_time_us, open_unit)
            if open_time_us % 1_000_000 or (open_time_us // 1_000_000) % 60:
                stats.off_grid_rows += 1
            quote = _parse_float(values[positions["quote_volume"]], stats.field("quote_volume"))
            buy = _parse_float(
                values[positions["taker_buy_quote_volume"]],
                stats.field("taker_buy_quote_volume"),
            )
            try:
                close_time_us, close_unit = parse_epoch_us_exact(
                    values[positions["close_time"]], field_name="close_time"
                )
            except ValueError:
                close_time_us, close_unit = None, None
                stats.close_time["unparseable"] += 1
            if close_time_us is not None:
                expected_offset = {
                    "epoch_ms": 59_999_000,
                    "epoch_us": 59_999_999,
                }.get(open_unit)
                if close_unit == open_unit and close_time_us - open_time_us == expected_offset:
                    stats.close_time["standard_offset"] += 1
                else:
                    stats.close_time["nonstandard_offset"] += 1
                if close_time_us < open_time_us:
                    stats.close_time["before_open"] += 1
                elif close_time_us > open_time_us + 60_000_000:
                    stats.close_time["after_nominal_end"] += 1
                else:
                    stats.close_time["causal"] += 1
            stats.schema_valid_rows += 1
            rows.append(
                RawKlineRow(
                    open_time_us=open_time_us,
                    open_time_unit=open_unit,
                    close_time_us=close_time_us,
                    close_time_unit=close_unit,
                    quote_volume=quote,
                    taker_buy_quote_volume=buy,
                    fingerprint=tuple(values),
                )
            )
        except (IndexError, ValueError) as exc:
            stats.schema_invalid_rows += 1
            stats.archive_errors.append({"archive": path.name, "reason": f"row_error:{exc}"})
    return sorted(rows, key=lambda row: row.open_time_us)


def _group_rows(
    rows: Iterable[RawKlineRow], stats: SourceStats
) -> Iterator[tuple[int, RawKlineRow | None]]:
    timestamp: int | None = None
    pending: list[RawKlineRow] = []
    previous_resolved: int | None = None

    def resolve() -> tuple[int, RawKlineRow | None] | None:
        nonlocal previous_resolved
        if timestamp is None:
            return None
        if len(pending) > 1:
            stats.duplicate_rows += len(pending) - 1
        fingerprints = {row.fingerprint for row in pending}
        if len(fingerprints) > 1:
            stats.conflicting_timestamps += 1
            resolved = None
        else:
            resolved = pending[0]
            if len(pending) > 1:
                stats.identical_duplicate_timestamps += 1
        if previous_resolved is not None and timestamp > previous_resolved + 60_000_000:
            stats.gap_runs += 1
            stats.missing_minutes += (timestamp - previous_resolved) // 60_000_000 - 1
        previous_resolved = timestamp
        return timestamp, resolved

    for row in rows:
        if timestamp is None or row.open_time_us == timestamp:
            timestamp = row.open_time_us
            pending.append(row)
            continue
        resolved = resolve()
        if resolved is not None:
            yield resolved
        timestamp = row.open_time_us
        pending = [row]
    resolved = resolve()
    if resolved is not None:
        yield resolved


def audit_um_archives(
    paths: Sequence[Path], candidate_hours: Sequence[int]
) -> tuple[object, dict[str, object]]:
    """Parse raw UM archives, resolve duplicates, and build exact flow availability."""

    stats = SourceStats()

    def parsed_rows() -> Iterator[RawKlineRow]:
        for path in paths:
            yield from _parse_archive(path, stats)

    def normalized_minutes() -> Iterator[FlowMinute]:
        for timestamp_us, row in _group_rows(parsed_rows(), stats):
            if timestamp_us % 1_000_000 or (timestamp_us // 1_000_000) % 60:
                continue
            interval_end = timestamp_us // 1_000_000 + 60
            if row is None:
                yield FlowMinute(interval_end, None, None, conflict=True)
                continue
            yield FlowMinute(
                interval_end=interval_end,
                quote_volume=row.quote_volume,
                taker_buy_quote_volume=row.taker_buy_quote_volume,
                timing_valid=row.close_is_causal,
            )

    flow = build_flow_compression(normalized_minutes(), candidate_hours)
    return flow, stats.as_dict()


def _safe_relative_path(value: object) -> Path | None:
    if not isinstance(value, str):
        return None
    path = Path(value)
    if path.is_absolute() or ".." in path.parts:
        return None
    return path


def verify_d022_source_inputs(
    *,
    data_root: Path,
    repo_root: Path,
    enforce_loader_identity: bool = True,
) -> dict[str, object]:
    """Reverify only D-022 source inputs; committed effect artifacts are not read."""

    manifest_path = repo_root / D022_MANIFEST_IDENTIFIER
    failures: list[dict[str, str]] = []
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        reason = str(exc).replace(str(manifest_path), D022_MANIFEST_IDENTIFIER)
        return {
            "identifier": D022_MANIFEST_IDENTIFIER,
            "all_inputs_verified": False,
            "failures": [{"input": D022_MANIFEST_IDENTIFIER, "reason": reason}],
        }
    config = payload.get("config")
    expected_config = {
        "members": [
            "binance_btcusdt_spot",
            "kraken_xbtusd_spot",
            "coinbase_btcusd_spot",
        ],
        "min_members": 2,
        "construction": "componentwise_median",
        "decision_timestamp": "interval_end",
        "bars_start": "2020-01-01T00:00:00Z",
        "kraken_csvs": list(KRAKEN_FILES),
    }
    config_pass = isinstance(config, dict) and all(
        config.get(key) == value for key, value in expected_config.items()
    )
    if not config_pass:
        failures.append({"input": D022_MANIFEST_IDENTIFIER, "reason": "config_mismatch"})
    entries = payload.get("inputs")
    verified_count = 0
    total_bytes = 0
    relative_paths: list[str] = []
    if not isinstance(entries, list) or not entries:
        failures.append({"input": D022_MANIFEST_IDENTIFIER, "reason": "missing_inputs"})
        entries = []
    for entry in entries:
        if not isinstance(entry, dict):
            failures.append({"input": "<record>", "reason": "record_not_object"})
            continue
        relative = _safe_relative_path(entry.get("path"))
        expected_sha = entry.get("sha256")
        expected_bytes = entry.get("bytes")
        if (
            relative is None
            or not _valid_sha256(expected_sha)
            or not isinstance(expected_bytes, int)
            or expected_bytes <= 0
        ):
            failures.append({"input": str(entry.get("path")), "reason": "invalid_record"})
            continue
        relative_text = str(relative)
        relative_paths.append(relative_text)
        path = data_root / relative
        if not path.is_file():
            failures.append({"input": relative_text, "reason": "missing_on_disk"})
            continue
        if path.stat().st_size != expected_bytes:
            failures.append({"input": relative_text, "reason": "size_mismatch"})
            continue
        if sha256_file(path) != str(expected_sha).lower():
            failures.append({"input": relative_text, "reason": "sha256_mismatch"})
            continue
        verified_count += 1
        total_bytes += expected_bytes
    duplicate_inputs = len(relative_paths) - len(set(relative_paths))
    if duplicate_inputs:
        failures.append({"input": D022_MANIFEST_IDENTIFIER, "reason": "duplicate_input_paths"})
    loader_identity_pass = True
    if enforce_loader_identity:
        actual_loader_paths = {
            str(path.relative_to(data_root))
            for path in (data_root / SPOT_SUBDIR).glob("*.zip")
            if path.is_file()
        }
        actual_loader_paths.update(
            str(path.relative_to(data_root))
            for path in (data_root / COINBASE_SUBDIR).glob("candles_*.json")
            if path.is_file()
        )
        actual_loader_paths.update(KRAKEN_FILES)
        loader_identity_pass = actual_loader_paths == set(relative_paths)
        if not loader_identity_pass:
            failures.append(
                {
                    "input": D022_MANIFEST_IDENTIFIER,
                    "reason": "loader_identity_set_differs_from_verified_manifest_inputs",
                }
            )
    support_hash = hashlib.sha256()
    support_hash.update(b"oracle-exp005-ordered-d022-source-inputs-v1\n")
    for relative_path in relative_paths:
        support_hash.update(f"{relative_path}\n".encode())
    return {
        "identifier": D022_MANIFEST_IDENTIFIER,
        "bytes": manifest_path.stat().st_size,
        "sha256": sha256_file(manifest_path),
        "manifest_repo_commit": payload.get("repo_commit"),
        "config_verified": config_pass,
        "effect_artifact_outputs_read": False,
        "expected_input_count": len(entries),
        "verified_input_count": verified_count,
        "verified_input_bytes": total_bytes,
        "duplicate_input_paths": duplicate_inputs,
        "loader_identity_set_exact": loader_identity_pass,
        "ordered_input_identity_sha256": support_hash.hexdigest(),
        "failures": sorted(failures, key=lambda item: (item["input"], item["reason"])),
        "all_inputs_verified": verified_count == len(entries) and not failures,
    }


def load_d022_index(data_root: Path):
    """Rebuild the exact median-of-three index from source-only loaders."""

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


def _um_source_integrity_clear(
    *,
    manifest: dict[str, object],
    archive_paths: Sequence[Path],
    source_report: dict[str, object],
) -> bool:
    """Apply the fail-closed source identity, schema, and epoch checks."""

    schema = source_report.get("schema")
    if not isinstance(schema, dict):
        return False
    rows = source_report.get("rows")
    archives_read = source_report.get("archives_read")
    return bool(
        manifest.get("exact_selected_identity_set")
        and manifest.get("selected_integrity_valid") == 79
        and len(archive_paths) == 79
        and archives_read == 79
        and isinstance(rows, int)
        and rows > 0
        and schema.get("valid_rows") == rows
        and schema.get("invalid_rows") == 0
        and source_report.get("epoch_units") == {"epoch_ms": rows}
        and source_report.get("epoch_unit_contract_pass") is True
        and not source_report.get("archive_errors")
    )


def _period_config(periods: Sequence[HourlyPeriod]) -> list[dict[str, str]]:
    return [
        {
            "name": period.name,
            "start": period.start.astimezone(UTC).isoformat().replace("+00:00", "Z"),
            "end": period.end.astimezone(UTC).isoformat().replace("+00:00", "Z"),
        }
        for period in periods
    ]


def audit_config(
    identities: Sequence[ArchiveIdentity], periods: Sequence[HourlyPeriod]
) -> dict[str, object]:
    return {
        "experiment": "EXP-005",
        "checkpoint": "A_PRE_EFFECT",
        "audit_version": AUDIT_VERSION,
        "contract_commit": CONTRACT_COMMIT,
        "contracts": [
            "D-037",
            "docs/briefs/2026-08-25-exp005-flow-compression-replication.md",
        ],
        "selected_manifest_identifier": MANIFEST_IDENTIFIER,
        "selected_um_archive_count": len(identities),
        "selected_um_archive_identities_sha256": hashlib.sha256(
            "\n".join(identity.relative_path for identity in identities).encode()
        ).hexdigest(),
        "d022_source_manifest_identifier": D022_MANIFEST_IDENTIFIER,
        "periods": _period_config(periods),
        "flow_coverage_floor": FLOW_FLOOR,
        "m0_flow_joint_coverage_floor": JOINT_FLOOR,
        "zero_joint_full_month_allowed": False,
        "m0_columns_ordered": list(M0_COLUMNS),
        "flow": {
            "block_minutes": 5,
            "detrend_points": 96,
            "residual_points": 24,
            "variance_ddof": 0,
            "newest_block_lag_minutes": 5,
            "epsilon": None,
            "partial_windows": False,
            "forward_fill": False,
        },
        "forbidden_reads": ["labels", "outcomes", "clusters", "fits", "effects", "scores"],
    }


def build_audit_payload(
    *,
    data_root: Path,
    repo_root: Path = REPO_ROOT,
    identities: Sequence[ArchiveIdentity] | None = None,
    periods: Sequence[HourlyPeriod] = DEFAULT_PERIODS,
) -> tuple[dict[str, object], dict[str, object]]:
    """Build one complete Checkpoint A report without reading future effects."""

    selected_identities = tuple(identities or expected_um_archive_identities())
    config = audit_config(selected_identities, periods)
    candidate_hours = tuple(hour for period in periods for hour in period.hours())
    manifest, archive_paths = verify_um_manifest(
        data_root=data_root,
        identities=selected_identities,
    )
    flow, source_report = audit_um_archives(archive_paths, candidate_hours)
    d022_inputs = verify_d022_source_inputs(data_root=data_root, repo_root=repo_root)

    m0_values: dict[int, tuple[float, ...]] = {}
    m0_reasons: dict[str, int] = {"D022_INPUT_VERIFICATION_FAILED": len(candidate_hours)}
    index_report: dict[str, object] = {
        "reconstructed": False,
        "source_timestamp_semantics": "member timestamps are interval starts; +60s for M0",
    }
    index_error: str | None = None
    if d022_inputs.get("all_inputs_verified"):
        try:
            index = load_d022_index(data_root)
            klines = index.klines
            end_timestamps = np.asarray(klines.timestamp, dtype=np.int64) + 60
            m0 = build_m0_features(
                end_timestamps=end_timestamps,
                close=klines.close,
                high=klines.high,
                low=klines.low,
                candidate_hours=candidate_hours,
            )
            m0_values = dict(m0.values)
            m0_reasons = dict(m0.reason_counts)
            index_report = {
                "reconstructed": True,
                "construction": "D-022 componentwise median, >=2 of 3, no fill",
                "source_timestamp_semantics": (
                    "member timestamps are interval starts; M0 decision timestamps are +60s"
                ),
                "rows": int(klines.n_rows),
                "rows_3_of_3": int(np.count_nonzero(index.venue_count == 3)),
                "rows_2_of_3": int(np.count_nonzero(index.venue_count == 2)),
                "interval_start_range": {
                    "first": datetime.fromtimestamp(int(klines.timestamp[0]), tz=UTC)
                    .isoformat()
                    .replace("+00:00", "Z"),
                    "last": datetime.fromtimestamp(int(klines.timestamp[-1]), tz=UTC)
                    .isoformat()
                    .replace("+00:00", "Z"),
                },
                "interval_end_support_sha256": ordered_timestamp_sha256(end_timestamps),
                "m0_columns_ordered": list(M0_COLUMNS),
                "m0_feature_reason_counts": m0_reasons,
            }
        except (OSError, ValueError) as exc:
            index_error = (
                str(exc)
                .replace(str(data_root), "<data_root>")
                .replace(str(repo_root), "<repo_root>")
            )
            index_report["error"] = index_error

    availability = availability_report(
        periods=periods,
        flow_values=flow.values,
        m0_values=m0_values,
    )
    um_source_clear = _um_source_integrity_clear(
        manifest=manifest,
        archive_paths=archive_paths,
        source_report=source_report,
    )
    source_integrity_clear = bool(
        um_source_clear
        and d022_inputs.get("all_inputs_verified")
        and index_report.get("reconstructed")
        and index_error is None
    )
    disposition = checkpoint_a_disposition(
        source_integrity_clear=source_integrity_clear,
        coverage_clear=bool(availability["coverage_clearance"]),
    )
    payload = {
        "experiment": "EXP-005",
        "checkpoint": "A_PRE_EFFECT",
        "audit_version": AUDIT_VERSION,
        "scope": (
            "source/support only; no labels, outcomes, clusters, fits, effects, or scores"
        ),
        "contract_commit": CONTRACT_COMMIT,
        "audit_config_sha256": canonical_config_sha256(config),
        "manifest": manifest,
        "um_kline_source": source_report,
        "aligned_five_minute_census": flow.aligned_five_minute_census,
        "hourly_flow_feature_census": flow.hourly_feature_census,
        "d022_source_inputs": d022_inputs,
        "d022_index": index_report,
        "availability": availability,
        "causal_ruling": {
            "source_rows_are_interval_bars": True,
            "raw_open_time_is_interval_start": True,
            "causal_interval_end_is_open_time_plus_60s": True,
            "five_minute_blocks_complete_before_use": True,
            "latest_block_ends_at_t_minus_5m": True,
            "post_t_inputs_permitted": False,
            "forward_fill": False,
            "partial_windows": False,
            "epsilon": None,
        },
        "source_integrity_clear": source_integrity_clear,
        "um_source_integrity_clear": um_source_clear,
        "checkpoint_a_disposition": disposition,
        "effect_inspection_performed": False,
    }
    return payload, config


def render_markdown(payload: dict[str, object]) -> str:
    manifest = payload["manifest"]
    source = payload["um_kline_source"]
    block = payload["aligned_five_minute_census"]
    availability = payload["availability"]
    d022 = payload["d022_source_inputs"]
    index = payload["d022_index"]
    lines = [
        "# EXP-005 Checkpoint A source readiness",
        "",
        f"**Disposition:** `{payload['checkpoint_a_disposition']}`",
        "",
        str(payload["scope"]) + ".",
        "",
        "## Selected source manifest",
        "",
        f"- Identifier: `{manifest['identifier']}`",
        f"- Selected identities: {manifest['selected_integrity_valid']} / "
        f"{manifest['expected_selected_identities']}",
        f"- Exact selected identity set: {manifest['exact_selected_identity_set']}",
        f"- Non-selected full-manifest records ignored: "
        f"{manifest['nonselected_manifest_records_ignored']}",
        "",
        "## USD-M kline and block audit",
        "",
        f"- Archives read: {source['archives_read']}",
        f"- Rows: {source['rows']}",
        f"- Epoch units: `{source['epoch_units']}`",
        f"- Raw close-time audit: `{source['raw_close_time']}`",
        f"- Duplicate handling: `{source['duplicates']}`",
        f"- Aligned 5m candidates: {block['candidate_blocks']}",
        f"- Structurally valid 5m blocks: {block['structurally_valid_blocks']}",
        f"- q-valid 5m blocks: {block['q_valid_blocks']}",
        f"- 5m reason census: `{block['reason_counts']}`",
        "",
        "## D-022 source/index and exact M0 verification",
        "",
        f"- D-022 source inputs verified: {d022.get('verified_input_count', 0)} / "
        f"{d022.get('expected_input_count', 0)}",
        f"- D-022 verified source bytes: {d022.get('verified_input_bytes', 0)}",
        f"- Median index reconstructed: {index.get('reconstructed', False)}",
        f"- Median index rows: {index.get('rows', 0)}",
        f"- 3-of-3 / 2-of-3 rows: {index.get('rows_3_of_3', 0)} / "
        f"{index.get('rows_2_of_3', 0)}",
        f"- Exact M0 columns: `{index.get('m0_columns_ordered', [])}`",
        f"- M0 availability reasons: `{index.get('m0_feature_reason_counts', {})}`",
        "",
        "## Source-only hourly support",
        "",
        "| Period | Flow | Flow rate | Joint seven-M0+flow | Joint rate | Zero months |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for period_name, period in availability["periods"].items():
        flow = period["flow"]
        joint = period["m0_flow_joint"]
        lines.append(
            f"| {period_name} | {flow['available_hours']} / {period['candidate_hours']} | "
            f"{flow['coverage_fraction']:.6f} | {joint['available_hours']} / "
            f"{period['candidate_hours']} | {joint['coverage_fraction']:.6f} | "
            f"{len(period['zero_joint_full_months'])} |"
        )
    lines.extend(
        [
            "",
            f"Coverage clearance: {availability['coverage_clearance']}",
            "",
            "Every period also records ordered candidate, flow, M0, joint paired-rung, "
            "and D-023 four-hour clock-purge support hashes in the JSON artifact.",
            "",
            "## Causal ruling",
            "",
            "USD-M source rows are interval bars; `open_time` is interval start and the "
            "causal end is `open_time + 60s`. Every five-minute block requires all five "
            "exact minutes. The newest block ends at `T-5m`. No partial window, epsilon, "
            "rounding, forward fill, post-T input, or alternate field is used.",
            "",
            "D-023 boundary purge reporting is clock-only. No cluster-straddle or future "
            "window was read at Checkpoint A.",
        ]
    )
    return "\n".join(lines).rstrip() + "\n"


def _provenance_inputs(data_root: Path, repo_root: Path) -> list[dict[str, object]]:
    inputs: list[dict[str, object]] = []
    for identifier, path in (
        (MANIFEST_IDENTIFIER, data_root / MANIFEST_IDENTIFIER),
        (D022_MANIFEST_IDENTIFIER, repo_root / D022_MANIFEST_IDENTIFIER),
    ):
        inputs.append(
            {
                "path": identifier,
                "bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            }
        )
    return inputs


def write_audit(
    *,
    data_root: Path,
    output_dir: Path,
    repo_root: Path = REPO_ROOT,
    identities: Sequence[ArchiveIdentity] | None = None,
    periods: Sequence[HourlyPeriod] = DEFAULT_PERIODS,
) -> tuple[Path, Path, Path]:
    payload, config = build_audit_payload(
        data_root=data_root,
        repo_root=repo_root,
        identities=identities,
        periods=periods,
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "source_readiness.json"
    markdown_path = output_dir / "source_readiness.md"
    json_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    markdown_path.write_text(render_markdown(payload), encoding="utf-8")
    provenance = build_provenance(
        repo_root=repo_root,
        config=config,
        inputs=[],
        outputs=[json_path, markdown_path],
        output_base=output_dir,
    )
    provenance["inputs"] = _provenance_inputs(data_root, repo_root)
    provenance["selected_um_archive_identities_sha256"] = payload["manifest"][
        "selected_archive_identities_sha256"
    ]
    provenance["d022_ordered_input_identity_sha256"] = payload["d022_source_inputs"].get(
        "ordered_input_identity_sha256"
    )
    provenance["ordered_support_hashes"] = {
        period_name: {
            "candidate": period["candidate_support_sha256"],
            "flow": period["flow"]["ordered_support_sha256"],
            "m0": period["m0_exact_seven_columns"]["ordered_support_sha256"],
            "joint": period["m0_flow_joint"]["ordered_support_sha256"],
            "d023_four_hour_boundary_purge": period["d023_four_hour_boundary_purge"][
                "ordered_support_sha256"
            ],
        }
        for period_name, period in payload["availability"]["periods"].items()
    }
    provenance["checkpoint_a_disposition"] = payload["checkpoint_a_disposition"]
    provenance_path = write_provenance_sidecar(output_dir, "source_readiness", provenance)
    return json_path, markdown_path, provenance_path


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, default=Path("reports/exp005"))
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    repo_root = args.repo_root.resolve()
    output_dir = args.output_dir
    if not output_dir.is_absolute():
        output_dir = repo_root / output_dir
    try:
        outputs = write_audit(
            data_root=args.data_root.resolve(),
            output_dir=output_dir,
            repo_root=repo_root,
        )
    except (OSError, ValueError) as exc:
        print(f"EXP-005 source audit failed: {exc}", file=sys.stderr)
        return 1
    print(
        f"runtime python={platform.python_version()} numpy={np.__version__}",
        file=sys.stderr,
    )
    for path in outputs:
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
