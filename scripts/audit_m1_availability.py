#!/usr/bin/env python3
"""Label-blind source-availability audit for the frozen EXP-004 M1 inputs.

The runner reads and hashes the external Binance Vision inventory. It never reads
the D-022 index, labels, clusters, model inputs, outcomes, or scores.
"""

from __future__ import annotations

import argparse
import bisect
import csv
import hashlib
import io
import json
import math
import sys
import zipfile
from collections import Counter, deque
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, TypeVar

from oracle_research.provenance import (
    build_provenance,
    canonical_config_sha256,
    sha256_file,
    write_provenance_sidecar,
)

AUDIT_VERSION = "exp004_m1_availability_v1"
MANIFEST_IDENTIFIER = "manifests/binance_vision_fetch.jsonl"
VERIFIED_MANIFEST_STATUSES = frozenset({"downloaded", "verified_existing"})
FAMILY_FLOOR = 0.90
JOINT_FLOOR = 0.85
RowT = TypeVar("RowT")

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
METRICS_REQUIRED_FIELDS = ("create_time", "symbol", "sum_open_interest_value")
FUNDING_REQUIRED_FIELDS = ("calc_time", "funding_interval_hours", "last_funding_rate")

PUBLICATION_EVIDENCE = {
    "funding": "BLOCKED_ASOF_NO_PUBLICATION_TIME",
    "open_interest": "BLOCKED_ASOF_NO_PUBLICATION_TIME",
    "perpetual_premium": "CLEARED_INTERVAL_END",
    "taker_flow_variance_compression": "CLEARED_INTERVAL_END",
}


@dataclass(frozen=True, slots=True)
class ArchiveIdentity:
    source: str
    relative_path: str


@dataclass(frozen=True, slots=True)
class AuditPeriod:
    name: str
    start: datetime
    end: datetime

    def __post_init__(self) -> None:
        if self.start.tzinfo is None or self.end.tzinfo is None:
            raise ValueError("audit periods must be timezone-aware")
        if self.start > self.end:
            raise ValueError("audit period start must not exceed end")
        if any(
            value.minute or value.second or value.microsecond
            for value in (self.start.astimezone(UTC), self.end.astimezone(UTC))
        ):
            raise ValueError("audit period bounds must be exact UTC hours")

    def hours(self) -> Iterator[int]:
        current = self.start.astimezone(UTC)
        end = self.end.astimezone(UTC)
        while current <= end:
            yield int(current.timestamp())
            current += timedelta(hours=1)


DEFAULT_PERIODS = (
    AuditPeriod(
        "M1_DEV",
        datetime(2021, 12, 1, 1, tzinfo=UTC),
        datetime(2023, 12, 31, 23, tzinfo=UTC),
    ),
    AuditPeriod(
        "VALIDATION",
        datetime(2024, 1, 1, tzinfo=UTC),
        datetime(2024, 12, 31, 23, tzinfo=UTC),
    ),
    AuditPeriod(
        "TEST_2025",
        datetime(2025, 1, 1, tzinfo=UTC),
        datetime(2025, 12, 31, 23, tzinfo=UTC),
    ),
    AuditPeriod(
        "TEST_2026",
        datetime(2026, 1, 1, tzinfo=UTC),
        datetime(2026, 7, 31, 23, tzinfo=UTC),
    ),
)


@dataclass(frozen=True, slots=True)
class KlineRow:
    open_time_us: int
    raw_open_time: str
    close: float | None
    quote_volume: float | None
    taker_buy_quote_volume: float | None
    raw_close_time: str
    close_time_us: int | None
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
    def timing_valid(self) -> bool:
        return (
            self.interval_start is not None
            and self.close_time_us is not None
            and self.open_time_us <= self.close_time_us <= self.open_time_us + 60_000_000
        )


@dataclass(frozen=True, slots=True)
class MetricsRow:
    create_time_us: int
    value: float | None
    fingerprint: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class FundingRow:
    calc_time_ms: int
    interval_hours: int | None
    rate: float | None
    fingerprint: tuple[str, ...]


@dataclass(slots=True)
class SourceStats:
    source: str
    cadence_seconds: int | None
    rows: int = 0
    archives_read: int = 0
    archive_errors: list[dict[str, str]] = field(default_factory=list)
    header_counts: Counter[str] = field(default_factory=Counter)
    headerless_archives: int = 0
    timestamp_unit_counts: Counter[str] = field(default_factory=Counter)
    timestamp_min_us: int | None = None
    timestamp_max_us: int | None = None
    duplicate_rows: int = 0
    conflicting_duplicate_timestamps: int = 0
    off_grid_rows: int = 0
    out_of_order_rows: int = 0
    gap_count: int = 0
    missing_intervals: int = 0
    field_audit: dict[str, Counter[str]] = field(default_factory=dict)
    close_time_audit: Counter[str] = field(default_factory=Counter)

    def field_counter(self, name: str) -> Counter[str]:
        return self.field_audit.setdefault(name, Counter())

    def observe_timestamp(self, timestamp_us: int, unit: str) -> None:
        self.timestamp_unit_counts[unit] += 1
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

    def observe_resolved_timestamp(self, timestamp_us: int, previous_us: int | None) -> None:
        if previous_us is None:
            return
        if timestamp_us < previous_us:
            self.out_of_order_rows += 1
            return
        if self.cadence_seconds is None or timestamp_us == previous_us:
            return
        cadence_us = self.cadence_seconds * 1_000_000
        delta = timestamp_us - previous_us
        if delta > cadence_us:
            self.gap_count += 1
            self.missing_intervals += max(0, delta // cadence_us - 1)

    def as_dict(self) -> dict[str, Any]:
        field_keys = ("finite", "null", "nonfinite", "zero", "negative", "nonpositive")
        return {
            "rows": self.rows,
            "archives_read": self.archives_read,
            "archive_errors": sorted(
                self.archive_errors, key=lambda item: (item["archive"], item["reason"])
            ),
            "headers": dict(sorted(self.header_counts.items())),
            "headerless_archives": self.headerless_archives,
            "timestamp_units": dict(sorted(self.timestamp_unit_counts.items())),
            "normalized_timestamp_range": {
                "first": _format_epoch_us(self.timestamp_min_us),
                "last": _format_epoch_us(self.timestamp_max_us),
            },
            "duplicates": {
                "duplicate_rows": self.duplicate_rows,
                "conflicting_timestamps": self.conflicting_duplicate_timestamps,
                "out_of_order_rows": self.out_of_order_rows,
            },
            "off_grid_rows": self.off_grid_rows,
            "raw_timestamp_gaps": {
                "gap_count": self.gap_count,
                "missing_intervals": self.missing_intervals,
                "semantics": (
                    "consecutive raw normalized timestamp deltas; off-grid rows are "
                    "reported separately"
                ),
            },
            "field_audit": {
                name: {
                    key: counter.get(key, 0)
                    for key in sorted(set(field_keys) | set(counter))
                }
                for name, counter in sorted(self.field_audit.items())
            },
            "close_time_audit": {
                key: self.close_time_audit.get(key, 0)
                for key in (
                    "after_interval_end",
                    "at_or_before_interval_end",
                    "before_interval_start",
                    "nonstandard_offset",
                    "standard_offset",
                    "unparseable",
                )
            },
        }


def _month_range(start: str, end: str) -> list[str]:
    start_year, start_month = map(int, start.split("-"))
    end_year, end_month = map(int, end.split("-"))
    result: list[str] = []
    year, month = start_year, start_month
    while (year, month) <= (end_year, end_month):
        result.append(f"{year:04d}-{month:02d}")
        month += 1
        if month == 13:
            year += 1
            month = 1
    return result


def _day_range(start: str, end: str) -> list[str]:
    current = date.fromisoformat(start)
    last = date.fromisoformat(end)
    result: list[str] = []
    while current <= last:
        result.append(current.isoformat())
        current += timedelta(days=1)
    return result


def expected_archive_identities() -> tuple[ArchiveIdentity, ...]:
    identities: list[ArchiveIdentity] = []
    for month in _month_range("2020-01", "2026-07"):
        identities.extend(
            (
                ArchiveIdentity(
                    "spot_klines_1m",
                    f"spot/monthly/klines/BTCUSDT/1m/BTCUSDT-1m-{month}.zip",
                ),
                ArchiveIdentity(
                    "um_klines_1m",
                    f"futures/um/monthly/klines/BTCUSDT/1m/BTCUSDT-1m-{month}.zip",
                ),
                ArchiveIdentity(
                    "funding",
                    "futures/um/monthly/fundingRate/BTCUSDT/"
                    f"BTCUSDT-fundingRate-{month}.zip",
                ),
            )
        )
    for day in _day_range("2021-12-01", "2026-08-21"):
        identities.append(
            ArchiveIdentity(
                "metrics",
                f"futures/um/daily/metrics/BTCUSDT/BTCUSDT-metrics-{day}.zip",
            )
        )
    return tuple(identities)


def _parse_integer_text(text: str, *, field_name: str) -> int:
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


def _datetime_to_epoch_us(value: datetime) -> int:
    normalized = value.astimezone(UTC)
    epoch = datetime(1970, 1, 1, tzinfo=UTC)
    delta = normalized - epoch
    return ((delta.days * 86_400 + delta.seconds) * 1_000_000) + delta.microseconds


def parse_epoch_us_exact(text: str, *, field_name: str) -> tuple[int, str]:
    """Parse epoch seconds/milliseconds/microseconds or ISO text without flooring."""

    value = text.strip()
    try:
        raw = _parse_integer_text(value, field_name=field_name)
    except ValueError:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError(f"{field_name} is neither an exact epoch nor ISO timestamp") from exc
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return _datetime_to_epoch_us(parsed), "iso"
    magnitude = abs(raw)
    if magnitude >= 1_000_000_000_000_000:
        return raw, "epoch_us"
    if magnitude >= 1_000_000_000_000:
        return raw * 1_000, "epoch_ms"
    return raw * 1_000_000, "epoch_s"


def parse_funding_calc_time_ms_exact(text: str) -> int:
    """Parse the raw funding millisecond event stamp without rounding or flooring."""

    raw = _parse_integer_text(text, field_name="calc_time")
    if abs(raw) < 1_000_000_000_000:
        raise ValueError("calc_time is not a millisecond epoch stamp")
    if abs(raw) >= 1_000_000_000_000_000:
        raise ValueError("calc_time must remain in raw milliseconds")
    return raw


def _parse_float(text: str, counter: Counter[str], *, positive: bool = False) -> float | None:
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
    if parsed == 0:
        counter["zero"] += 1
    if parsed < 0:
        counter["negative"] += 1
    if positive and parsed <= 0:
        counter["nonpositive"] += 1
        return None
    return parsed


def _format_epoch_us(value: int | None) -> str | None:
    if value is None:
        return None
    seconds, micros = divmod(value, 1_000_000)
    timestamp = datetime.fromtimestamp(seconds, tz=UTC).replace(microsecond=micros)
    return timestamp.isoformat().replace("+00:00", "Z")


def _sha256_stream(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _read_manifest(path: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    records: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
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


def _manifest_and_archives(
    *,
    data_root: Path,
    identities: Sequence[ArchiveIdentity],
) -> tuple[dict[str, Any], dict[str, list[Path]]]:
    manifest_path = data_root / MANIFEST_IDENTIFIER
    records, parse_errors = _read_manifest(manifest_path)
    records_by_path: dict[str, list[dict[str, Any]]] = {}
    for record in records:
        relative_path = record.get("relative_path")
        if isinstance(relative_path, str):
            records_by_path.setdefault(relative_path, []).append(record)

    expected_by_path = {identity.relative_path: identity for identity in identities}
    archive_paths: dict[str, list[Path]] = {
        source: [] for source in sorted({identity.source for identity in identities})
    }
    source_summary: dict[str, Counter[str]] = {
        source: Counter() for source in sorted(archive_paths)
    }
    retrieval_times: list[str] = []
    failures: list[dict[str, str]] = []

    for identity in identities:
        summary = source_summary[identity.source]
        summary["expected"] += 1
        matching = records_by_path.get(identity.relative_path, [])
        if not matching:
            summary["missing_manifest"] += 1
            failures.append(
                {"archive": identity.relative_path, "reason": "missing_manifest_record"}
            )
            continue
        summary["manifest_present"] += 1
        if len(matching) > 1:
            summary["duplicate_manifest_records"] += len(matching) - 1
        record = matching[-1]
        retrieved_at = record.get("retrieved_at")
        if isinstance(retrieved_at, str):
            retrieval_times.append(retrieved_at)
        status = record.get("status")
        size = record.get("size_bytes")
        expected_sha = record.get("sha256")
        valid_record = (
            status in VERIFIED_MANIFEST_STATUSES
            and isinstance(size, int)
            and size > 0
            and isinstance(expected_sha, str)
            and len(expected_sha) == 64
            and all(character in "0123456789abcdef" for character in expected_sha.lower())
        )
        if not valid_record:
            summary["invalid_manifest_record"] += 1
            failures.append(
                {"archive": identity.relative_path, "reason": "invalid_manifest_record"}
            )
            continue
        summary["manifest_valid"] += 1
        disk_path = data_root / "raw" / "binance_vision" / identity.relative_path
        if not disk_path.is_file():
            summary["missing_on_disk"] += 1
            failures.append({"archive": identity.relative_path, "reason": "missing_on_disk"})
            continue
        summary["on_disk"] += 1
        if disk_path.stat().st_size != size:
            summary["size_mismatch"] += 1
            failures.append({"archive": identity.relative_path, "reason": "size_mismatch"})
            continue
        actual_sha = _sha256_stream(disk_path)
        if actual_sha != expected_sha.lower():
            summary["sha256_mismatch"] += 1
            failures.append({"archive": identity.relative_path, "reason": "sha256_mismatch"})
            continue
        summary["integrity_valid"] += 1
        archive_paths[identity.source].append(disk_path)

    unexpected = sorted(set(records_by_path) - set(expected_by_path))
    manifest_summary = {
        "identifier": MANIFEST_IDENTIFIER,
        "sha256": sha256_file(manifest_path),
        "bytes": manifest_path.stat().st_size,
        "records": len(records),
        "unique_archive_identities": len(records_by_path),
        "retrieval_range": {
            "first": min(retrieval_times) if retrieval_times else None,
            "last": max(retrieval_times) if retrieval_times else None,
        },
        "parse_errors": parse_errors,
        "unexpected_archive_identities": unexpected,
        "sources": {
            source: dict(sorted(summary.items()))
            for source, summary in sorted(source_summary.items())
        },
        "failures": sorted(failures, key=lambda item: (item["archive"], item["reason"])),
        "exact_identity_set": not parse_errors and not unexpected and not failures,
    }
    return manifest_summary, archive_paths


def _csv_rows(path: Path, stats: SourceStats, *, header_required: bool) -> Iterator[dict[str, Any]]:
    relative_name = path.name
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
                text = io.TextIOWrapper(binary, encoding="utf-8-sig", newline="")
                reader = csv.reader(text)
                try:
                    first = next(reader)
                except StopIteration:
                    raise ValueError("empty_csv") from None
                has_header = not first or not _looks_numeric(first[0])
                if header_required and not has_header:
                    raise ValueError("missing_required_header")
                header: tuple[str, ...] | None
                if has_header:
                    header = tuple(value.strip() for value in first)
                    stats.header_counts[",".join(header)] += 1
                else:
                    header = None
                    stats.headerless_archives += 1
                    yield {"values": first, "header": None, "archive": relative_name}
                for values in reader:
                    if values and any(value.strip() for value in values):
                        yield {"values": values, "header": header, "archive": relative_name}
    except (OSError, ValueError, zipfile.BadZipFile) as exc:
        stats.archive_errors.append({"archive": relative_name, "reason": str(exc)})


def _looks_numeric(text: str) -> bool:
    try:
        Decimal(text.strip())
    except InvalidOperation:
        return False
    return True


def _header_index(header: tuple[str, ...], required: Sequence[str]) -> dict[str, int]:
    normalized = {name.strip().lower(): index for index, name in enumerate(header)}
    aliases = {
        "quote_volume": ("quote_volume", "quote_asset_volume"),
        "taker_buy_quote_volume": ("taker_buy_quote_volume", "taker_buy_quote"),
        "trade_count": ("trade_count", "number_of_trades", "count"),
        "taker_buy_volume": ("taker_buy_volume", "taker_buy_base", "taker_buy_base_volume"),
    }
    result: dict[str, int] = {}
    for field_name in required:
        candidates = aliases.get(field_name, (field_name,))
        index = next((normalized[name] for name in candidates if name in normalized), None)
        if index is None:
            raise ValueError(f"missing_field:{field_name}")
        result[field_name] = index
    return result


def _group_rows(
    rows: Iterable[RowT],
    *,
    timestamp: Any,
    fingerprint: Any,
    stats: SourceStats,
    reject_any_duplicate: bool = False,
) -> Iterator[tuple[int, RowT | None]]:
    pending_timestamp: int | None = None
    pending: list[RowT] = []
    previous_resolved: int | None = None

    def resolve() -> tuple[int, RowT | None] | None:
        nonlocal previous_resolved
        if pending_timestamp is None:
            return None
        if len(pending) > 1:
            stats.duplicate_rows += len(pending) - 1
        fingerprints = {fingerprint(row) for row in pending}
        resolved: RowT | None = pending[0]
        if len(fingerprints) > 1 or (reject_any_duplicate and len(pending) > 1):
            stats.conflicting_duplicate_timestamps += 1
            resolved = None
        stats.observe_resolved_timestamp(pending_timestamp, previous_resolved)
        previous_resolved = pending_timestamp
        return pending_timestamp, resolved

    for row in rows:
        row_timestamp = int(timestamp(row))
        if pending_timestamp is None or row_timestamp == pending_timestamp:
            pending_timestamp = row_timestamp
            pending.append(row)
            continue
        resolved_group = resolve()
        if resolved_group is not None:
            yield resolved_group
        pending_timestamp = row_timestamp
        pending = [row]
    resolved_group = resolve()
    if resolved_group is not None:
        yield resolved_group


def _parse_kline_rows(paths: Sequence[Path], stats: SourceStats) -> Iterator[KlineRow]:
    for path in paths:
        for payload in _csv_rows(path, stats, header_required=False):
            values = payload["values"]
            header = payload["header"]
            stats.rows += 1
            try:
                if header is None:
                    if len(values) != 12:
                        raise ValueError(f"expected_12_columns_found_{len(values)}")
                    positions = {name: index for index, name in enumerate(KLINE_FIELDS)}
                else:
                    if len(values) != 12 or len(header) != 12:
                        raise ValueError("kline_schema_not_12_positions")
                    positions = _header_index(header, KLINE_FIELDS)
                open_time_us, unit = parse_epoch_us_exact(
                    values[positions["open_time"]], field_name="open_time"
                )
                stats.observe_timestamp(open_time_us, unit)
                if open_time_us % 1_000_000 or (open_time_us // 1_000_000) % 60:
                    stats.off_grid_rows += 1
                close = _parse_float(
                    values[positions["close"]], stats.field_counter("close"), positive=True
                )
                quote_volume = _parse_float(
                    values[positions["quote_volume"]],
                    stats.field_counter("quote_volume"),
                )
                taker_buy_quote = _parse_float(
                    values[positions["taker_buy_quote_volume"]],
                    stats.field_counter("taker_buy_quote_volume"),
                )
                raw_close_time = values[positions["close_time"]].strip()
                try:
                    close_time_us, close_unit = parse_epoch_us_exact(
                        raw_close_time, field_name="close_time"
                    )
                except ValueError:
                    close_time_us = None
                    stats.close_time_audit["unparseable"] += 1
                if close_time_us is not None:
                    expected_offset = {
                        "epoch_ms": 59_999_000,
                        "epoch_us": 59_999_999,
                    }.get(unit)
                    if close_unit != unit or (
                        expected_offset is not None
                        and close_time_us - open_time_us != expected_offset
                    ):
                        stats.close_time_audit["nonstandard_offset"] += 1
                    else:
                        stats.close_time_audit["standard_offset"] += 1
                    if close_time_us < open_time_us:
                        stats.close_time_audit["before_interval_start"] += 1
                    if close_time_us > open_time_us + 60_000_000:
                        stats.close_time_audit["after_interval_end"] += 1
                    else:
                        stats.close_time_audit["at_or_before_interval_end"] += 1
                yield KlineRow(
                    open_time_us=open_time_us,
                    raw_open_time=values[positions["open_time"]].strip(),
                    close=close,
                    quote_volume=quote_volume,
                    taker_buy_quote_volume=taker_buy_quote,
                    raw_close_time=raw_close_time,
                    close_time_us=close_time_us,
                    fingerprint=tuple(value.strip() for value in values),
                )
            except (IndexError, ValueError) as exc:
                stats.archive_errors.append(
                    {"archive": payload["archive"], "reason": f"row_error:{exc}"}
                )


def _parse_metrics_rows(paths: Sequence[Path], stats: SourceStats) -> Iterator[MetricsRow]:
    for path in paths:
        for payload in _csv_rows(path, stats, header_required=True):
            values = payload["values"]
            header = payload["header"]
            assert header is not None
            stats.rows += 1
            try:
                positions = _header_index(header, METRICS_REQUIRED_FIELDS)
                create_time_us, unit = parse_epoch_us_exact(
                    values[positions["create_time"]], field_name="create_time"
                )
                stats.observe_timestamp(create_time_us, unit)
                if create_time_us % (300 * 1_000_000):
                    stats.off_grid_rows += 1
                symbol = values[positions["symbol"]].strip()
                symbol_counter = stats.field_counter("symbol")
                symbol_counter["BTCUSDT" if symbol == "BTCUSDT" else "other"] += 1
                if symbol != "BTCUSDT":
                    raise ValueError(f"unexpected_symbol:{symbol}")
                value = _parse_float(
                    values[positions["sum_open_interest_value"]],
                    stats.field_counter("sum_open_interest_value"),
                    positive=True,
                )
                yield MetricsRow(
                    create_time_us=create_time_us,
                    value=value,
                    fingerprint=tuple(value.strip() for value in values),
                )
            except (IndexError, ValueError) as exc:
                stats.archive_errors.append(
                    {"archive": payload["archive"], "reason": f"row_error:{exc}"}
                )


def _parse_funding_rows(paths: Sequence[Path], stats: SourceStats) -> Iterator[FundingRow]:
    for path in paths:
        for payload in _csv_rows(path, stats, header_required=True):
            values = payload["values"]
            header = payload["header"]
            assert header is not None
            stats.rows += 1
            try:
                positions = _header_index(header, FUNDING_REQUIRED_FIELDS)
                calc_time_ms = parse_funding_calc_time_ms_exact(values[positions["calc_time"]])
                stats.observe_timestamp(calc_time_ms * 1_000, "epoch_ms")
                if calc_time_ms % 1_000:
                    stats.off_grid_rows += 1
                interval_counter = stats.field_counter("funding_interval_hours")
                try:
                    interval_hours = _parse_integer_text(
                        values[positions["funding_interval_hours"]],
                        field_name="funding_interval_hours",
                    )
                except ValueError:
                    interval_counter["null_or_invalid"] += 1
                    interval_hours = None
                else:
                    interval_counter["valid"] += 1
                    if interval_hours != 8:
                        interval_counter["not_8"] += 1
                rate = _parse_float(
                    values[positions["last_funding_rate"]],
                    stats.field_counter("last_funding_rate"),
                )
                yield FundingRow(
                    calc_time_ms=calc_time_ms,
                    interval_hours=interval_hours,
                    rate=rate,
                    fingerprint=tuple(value.strip() for value in values),
                )
            except (IndexError, ValueError) as exc:
                stats.archive_errors.append(
                    {"archive": payload["archive"], "reason": f"row_error:{exc}"}
                )


def _all_candidate_hours(periods: Sequence[AuditPeriod]) -> set[int]:
    return {hour for period in periods for hour in period.hours()}


def _audit_spot(
    paths: Sequence[Path], candidate_hours: set[int]
) -> tuple[dict[int, float], dict[str, Any]]:
    stats = SourceStats("spot_klines_1m", 60)
    hourly_closes: dict[int, float] = {}
    groups = _group_rows(
        _parse_kline_rows(paths, stats),
        timestamp=lambda row: row.open_time_us,
        fingerprint=lambda row: row.fingerprint,
        stats=stats,
    )
    for _, row in groups:
        if (
            row is None
            or not row.timing_valid
            or row.interval_end not in candidate_hours
            or row.close is None
        ):
            continue
        hourly_closes[row.interval_end] = row.close
    result = stats.as_dict()
    result.update(_source_contract("spot_klines_1m"))
    return hourly_closes, result


def _flow_feature_hours(
    groups: Iterable[tuple[int, KlineRow | None]], candidate_hours: set[int]
) -> tuple[dict[int, float], dict[int, float]]:
    hourly_perp_closes: dict[int, float] = {}
    flow_hours: dict[int, float] = {}
    minute_window: deque[KlineRow] = deque(maxlen=5)
    q_window: deque[tuple[int, float]] = deque(maxlen=96)
    residual_window: deque[tuple[int, float]] = deque(maxlen=24)

    for _, row in groups:
        if row is None or row.interval_end is None or not row.timing_valid:
            minute_window.clear()
            q_window.clear()
            residual_window.clear()
            continue
        interval_end = row.interval_end
        if interval_end in candidate_hours and row.close is not None:
            hourly_perp_closes[interval_end] = row.close
        minute_window.append(row)
        if interval_end % 300:
            continue
        expected_ends = [interval_end - 240 + 60 * index for index in range(5)]
        actual_ends = [item.interval_end for item in minute_window]
        q_value: float | None = None
        if actual_ends == expected_ends and all(
            item.quote_volume is not None and item.taker_buy_quote_volume is not None
            for item in minute_window
        ):
            quote = math.fsum(item.quote_volume or 0.0 for item in minute_window)
            buys = math.fsum(item.taker_buy_quote_volume or 0.0 for item in minute_window)
            sells = quote - buys
            if buys > 0 and sells > 0 and math.isfinite(quote):
                q_value = math.log(buys / sells)
        if q_value is None:
            q_window.clear()
            residual_window.clear()
            continue
        if q_window and interval_end - q_window[-1][0] != 300:
            q_window.clear()
            residual_window.clear()
        q_window.append((interval_end, q_value))
        residual: float | None = None
        if len(q_window) == 96 and interval_end - q_window[0][0] == 475 * 60:
            mean_q = math.fsum(value for _, value in q_window) / 96
            residual = q_value - mean_q
        if residual is None or not math.isfinite(residual):
            residual_window.clear()
            continue
        if residual_window and interval_end - residual_window[-1][0] != 300:
            residual_window.clear()
        residual_window.append((interval_end, residual))
        feature_time = interval_end + 300
        if (
            feature_time in candidate_hours
            and len(residual_window) == 24
            and interval_end - residual_window[0][0] == 115 * 60
        ):
            mean_residual = math.fsum(value for _, value in residual_window) / 24
            variance = (
                math.fsum((value - mean_residual) ** 2 for _, value in residual_window) / 24
            )
            if variance > 0 and math.isfinite(variance):
                flow_hours[feature_time] = -math.log(variance)
    return hourly_perp_closes, flow_hours


def _audit_um(
    paths: Sequence[Path], candidate_hours: set[int]
) -> tuple[dict[int, float], set[int], dict[str, Any]]:
    stats = SourceStats("um_klines_1m", 60)
    groups = _group_rows(
        _parse_kline_rows(paths, stats),
        timestamp=lambda row: row.open_time_us,
        fingerprint=lambda row: row.fingerprint,
        stats=stats,
    )
    hourly_closes, flow_values = _flow_feature_hours(groups, candidate_hours)
    result = stats.as_dict()
    result.update(_source_contract("um_klines_1m"))
    return hourly_closes, set(flow_values), result


def _audit_metrics(
    paths: Sequence[Path], candidate_hours: set[int]
) -> tuple[set[int], dict[str, Any]]:
    stats = SourceStats("metrics", 300)
    available: set[int] = set()
    groups = _group_rows(
        _parse_metrics_rows(paths, stats),
        timestamp=lambda row: row.create_time_us,
        fingerprint=lambda row: row.fingerprint,
        stats=stats,
    )
    for timestamp_us, row in groups:
        if row is None or row.value is None or timestamp_us % 1_000_000:
            continue
        decision_hour = timestamp_us // 1_000_000 + 300
        if decision_hour in candidate_hours:
            available.add(decision_hour)
    result = stats.as_dict()
    result.update(_source_contract("metrics"))
    return available, result


def _audit_funding(
    paths: Sequence[Path], candidate_hours: set[int]
) -> tuple[set[int], dict[str, Any]]:
    stats = SourceStats("funding", None)
    previous_ms: int | None = None
    raw_gap_count = 0
    delta_min: int | None = None
    delta_max: int | None = None
    groups = _group_rows(
        _parse_funding_rows(paths, stats),
        timestamp=lambda row: row.calc_time_ms * 1_000,
        fingerprint=lambda row: row.fingerprint,
        stats=stats,
        reject_any_duplicate=True,
    )
    event_times: list[int] = []
    event_valid: list[bool] = []
    for timestamp_us, row in groups:
        timestamp_ms = timestamp_us // 1_000
        if previous_ms is not None:
            delta = timestamp_ms - previous_ms
            delta_min = delta if delta_min is None else min(delta_min, delta)
            delta_max = delta if delta_max is None else max(delta_max, delta)
            if delta > 8 * 60 * 60 * 1_000:
                raw_gap_count += 1
        previous_ms = timestamp_ms
        is_valid = row is not None and row.interval_hours == 8 and row.rate is not None
        event_times.append(timestamp_ms)
        event_valid.append(is_valid)

    available: set[int] = set()
    for hour in sorted(candidate_hours):
        end_ms = (hour - 300) * 1_000
        start_ms = (hour - 24 * 60 * 60 - 300) * 1_000
        left = bisect.bisect_right(event_times, start_ms)
        right = bisect.bisect_right(event_times, end_ms)
        if right - left == 3 and all(event_valid[left:right]):
            available.add(hour)
    result = stats.as_dict()
    result.update(_source_contract("funding"))
    result["raw_settlement_delta_ms"] = {
        "minimum": delta_min,
        "maximum": delta_max,
        "greater_than_8h_count": raw_gap_count,
        "nominal_grid_rounding_applied": False,
    }
    return available, result


def _source_contract(source: str) -> dict[str, Any]:
    contracts: dict[str, dict[str, Any]] = {
        "spot_klines_1m": {
            "path": "raw/binance_vision/spot/monthly/klines/BTCUSDT/1m",
            "schema": list(KLINE_FIELDS),
            "field_units": {"close": "USDT per BTC"},
            "timestamp_semantics": "open_time is interval start; interval end is +60s",
        },
        "um_klines_1m": {
            "path": "raw/binance_vision/futures/um/monthly/klines/BTCUSDT/1m",
            "schema": list(KLINE_FIELDS),
            "field_units": {
                "close": "USDT per BTC",
                "quote_volume": "USDT",
                "taker_buy_quote_volume": "USDT",
            },
            "timestamp_semantics": "open_time is interval start; interval end is +60s",
        },
        "metrics": {
            "path": "raw/binance_vision/futures/um/daily/metrics/BTCUSDT",
            "schema": list(METRICS_REQUIRED_FIELDS),
            "field_units": {"sum_open_interest_value": "USDT quote notional"},
            "timestamp_semantics": "raw create_time candidate interval end; never floored",
        },
        "funding": {
            "path": "raw/binance_vision/futures/um/monthly/fundingRate/BTCUSDT",
            "schema": list(FUNDING_REQUIRED_FIELDS),
            "field_units": {
                "last_funding_rate": "dimensionless settlement rate",
                "funding_interval_hours": "hours",
            },
            "timestamp_semantics": "raw calc_time millisecond event stamp; never rounded",
        },
    }
    return contracts[source]


def _candidate_contracts() -> dict[str, Any]:
    return {
        "open_interest": {
            "source": "Binance USD-M BTCUSDT five-minute metrics",
            "field_unit": "sum_open_interest_value, USDT quote notional",
            "timestamp": "raw create_time; candidate interval end; off-grid rows unusable",
            "as_of": "exact raw row at T-5m",
            "transform": "oi_level_T = log(sum_open_interest_value[T-5m])",
            "missingness": (
                "missing, conflicted, off-grid, nonfinite, or nonpositive row => missing"
            ),
            "effective_raw_start": "2021-12-01",
            "publication_evidence": PUBLICATION_EVIDENCE["open_interest"],
        },
        "funding": {
            "source": "Binance USD-M BTCUSDT monthly funding history",
            "field_unit": "last_funding_rate, dimensionless realized settlement rate",
            "timestamp": "raw millisecond calc_time event stamp; never rounded or floored",
            "as_of": "exactly three rows in (T-24h-5m, T-5m], each interval=8h",
            "transform": "funding_24h_T = sum(last_funding_rate)",
            "missingness": "not exactly three unique finite 8h settlements => missing",
            "effective_raw_start": "2020-01",
            "publication_evidence": PUBLICATION_EVIDENCE["funding"],
        },
        "perpetual_premium": {
            "source": "Binance USD-M and spot BTCUSDT one-minute klines",
            "field_unit": "perpetual and spot close, USDT per BTC",
            "timestamp": "open_time interval start; decision-time interval end = open_time+60s",
            "as_of": "both exact one-minute bars ending at T",
            "transform": "premium_T = log(perp_close_T / spot_close_T)",
            "missingness": "either exact bar missing/conflicted/nonfinite/nonpositive => missing",
            "effective_raw_start": "2020-01",
            "publication_evidence": PUBLICATION_EVIDENCE["perpetual_premium"],
        },
        "taker_flow_variance_compression": {
            "source": "Binance USD-M BTCUSDT one-minute kline quote-volume fields",
            "field_unit": "quote_volume and taker_buy_quote_volume, USDT",
            "timestamp": "five complete 1m bars per UTC-aligned block; newest block ends T-5m",
            "as_of": (
                "96 complete q points per 8h residual and 24 complete residuals per 2h variance"
            ),
            "transform": "q=log(B/(Q-B)); 8h mean residual; -log(population variance over 2h)",
            "missingness": "any absent/nonfinite input, B<=0, S<=0, or variance<=0 => missing",
            "effective_raw_start": "2020-01 plus frozen lookbacks",
            "publication_evidence": PUBLICATION_EVIDENCE[
                "taker_flow_variance_compression"
            ],
        },
    }


def _period_config(periods: Sequence[AuditPeriod]) -> list[dict[str, str]]:
    return [
        {
            "name": period.name,
            "start": period.start.astimezone(UTC).isoformat().replace("+00:00", "Z"),
            "end": period.end.astimezone(UTC).isoformat().replace("+00:00", "Z"),
        }
        for period in periods
    ]


def audit_config(
    identities: Sequence[ArchiveIdentity], periods: Sequence[AuditPeriod]
) -> dict[str, Any]:
    expected_counts = Counter(identity.source for identity in identities)
    return {
        "audit_version": AUDIT_VERSION,
        "manifest_identifier": MANIFEST_IDENTIFIER,
        "expected_archive_counts": dict(sorted(expected_counts.items())),
        "expected_archive_identities_sha256": hashlib.sha256(
            "\n".join(sorted(identity.relative_path for identity in identities)).encode()
        ).hexdigest(),
        "periods": _period_config(periods),
        "family_coverage_floor": FAMILY_FLOOR,
        "joint_coverage_floor": JOINT_FLOOR,
        "publication_evidence": PUBLICATION_EVIDENCE,
        "overall_m1_status": "BLOCKED_ASOF",
    }


def _month_bounds(month: str) -> tuple[int, int]:
    year, month_number = map(int, month.split("-"))
    start = datetime(year, month_number, 1, tzinfo=UTC)
    if month_number == 12:
        next_month = datetime(year + 1, 1, 1, tzinfo=UTC)
    else:
        next_month = datetime(year, month_number + 1, 1, tzinfo=UTC)
    return int(start.timestamp()), int(next_month.timestamp())


def _availability_report(
    *,
    periods: Sequence[AuditPeriod],
    families: dict[str, set[int]],
) -> dict[str, Any]:
    period_reports: dict[str, Any] = {}
    all_zero_full_months: list[str] = []
    coverage_pass = True
    for period in periods:
        hours = list(period.hours())
        hour_set = set(hours)
        family_report: dict[str, Any] = {}
        available_sets: list[set[int]] = []
        for family_name, available in sorted(families.items()):
            count = len(hour_set & available)
            fraction = count / len(hours) if hours else 0.0
            passed = fraction >= FAMILY_FLOOR
            coverage_pass &= passed
            family_report[family_name] = {
                "available_hours": count,
                "candidate_hours": len(hours),
                "coverage_fraction": fraction,
                "floor": FAMILY_FLOOR,
                "floor_pass": passed,
            }
            available_sets.append(available)
        joint = hour_set.intersection(*available_sets) if available_sets else set()
        joint_fraction = len(joint) / len(hours) if hours else 0.0
        joint_pass = joint_fraction >= JOINT_FLOOR
        coverage_pass &= joint_pass

        months: dict[str, dict[str, Any]] = {}
        for hour in hours:
            month = datetime.fromtimestamp(hour, tz=UTC).strftime("%Y-%m")
            entry = months.setdefault(month, {"candidate_hours": 0, "joint_hours": 0})
            entry["candidate_hours"] += 1
            if hour in joint:
                entry["joint_hours"] += 1
        zero_full_months: list[str] = []
        for month, entry in months.items():
            start, next_month = _month_bounds(month)
            full_hours = (next_month - start) // 3600
            entry["full_calendar_month"] = entry["candidate_hours"] == full_hours
            if entry["full_calendar_month"] and entry["joint_hours"] == 0:
                zero_full_months.append(month)
        coverage_pass &= not zero_full_months
        all_zero_full_months.extend(zero_full_months)
        period_reports[period.name] = {
            "candidate_hours": len(hours),
            "families": family_report,
            "joint": {
                "available_hours": len(joint),
                "coverage_fraction": joint_fraction,
                "floor": JOINT_FLOOR,
                "floor_pass": joint_pass,
            },
            "monthly_joint": dict(sorted(months.items())),
            "zero_joint_full_months": zero_full_months,
        }
    return {
        "periods": period_reports,
        "coverage_clearance": coverage_pass,
        "zero_joint_full_months": sorted(all_zero_full_months),
        "coverage_cannot_override_publication_gate": True,
    }


def build_audit_payload(
    *,
    data_root: Path,
    identities: Sequence[ArchiveIdentity] | None = None,
    periods: Sequence[AuditPeriod] = DEFAULT_PERIODS,
) -> tuple[dict[str, Any], dict[str, Any]]:
    selected_identities = tuple(identities or expected_archive_identities())
    config = audit_config(selected_identities, periods)
    manifest, archive_paths = _manifest_and_archives(
        data_root=data_root,
        identities=selected_identities,
    )
    candidate_hours = _all_candidate_hours(periods)

    spot_closes, spot_report = _audit_spot(
        archive_paths.get("spot_klines_1m", []), candidate_hours
    )
    perp_closes, flow_hours, um_report = _audit_um(
        archive_paths.get("um_klines_1m", []), candidate_hours
    )
    oi_hours, metrics_report = _audit_metrics(
        archive_paths.get("metrics", []), candidate_hours
    )
    funding_hours, funding_report = _audit_funding(
        archive_paths.get("funding", []), candidate_hours
    )
    premium_hours = {
        hour
        for hour in candidate_hours & set(spot_closes) & set(perp_closes)
        if spot_closes[hour] > 0
        and perp_closes[hour] > 0
        and math.isfinite(math.log(perp_closes[hour] / spot_closes[hour]))
    }
    availability = _availability_report(
        periods=periods,
        families={
            "funding": funding_hours,
            "open_interest": oi_hours,
            "perpetual_premium": premium_hours,
            "taker_flow_variance_compression": flow_hours,
        },
    )
    payload = {
        "audit_version": AUDIT_VERSION,
        "scope": "source-only; no D-022, labels, clusters, outcomes, fits, effects, or scores",
        "audit_config_sha256": canonical_config_sha256(config),
        "manifest": manifest,
        "sources": {
            "funding": funding_report,
            "metrics": metrics_report,
            "spot_klines_1m": spot_report,
            "um_klines_1m": um_report,
        },
        "candidate_contracts": _candidate_contracts(),
        "availability": availability,
        "publication_evidence": PUBLICATION_EVIDENCE,
        "overall_m1_status": "BLOCKED_ASOF",
        "overall_reason": (
            "OI and funding lack historical publication/receive-time evidence; "
            "coverage cannot clear the as-of gate"
        ),
    }
    return payload, config


def render_markdown(payload: dict[str, Any]) -> str:
    manifest = payload["manifest"]
    lines = [
        "# EXP-004 M1 source-availability audit",
        "",
        f"Overall M1 status: **{payload['overall_m1_status']}**.",
        "",
        payload["scope"] + ".",
        "",
        "## Manifest",
        "",
        f"- Identifier: `{manifest['identifier']}`",
        f"- SHA-256: `{manifest['sha256']}`",
        f"- Bytes: {manifest['bytes']}",
        (
            "- Retrieval range: "
            f"{manifest['retrieval_range']['first']} .. {manifest['retrieval_range']['last']}"
        ),
        f"- Exact expected identity set: {manifest['exact_identity_set']}",
        "",
        "## Publication evidence",
        "",
        "| Family | Status |",
        "|---|---|",
    ]
    for family, status in sorted(payload["publication_evidence"].items()):
        lines.append(f"| {family} | {status} |")
    lines.extend(
        [
            "",
            "## Source audit",
            "",
            "| Source | Archives | Rows | First timestamp | Last timestamp | Gaps | "
            "Duplicate rows | Conflicts | Off-grid |",
            "|---|---:|---:|---|---|---:|---:|---:|---:|",
        ]
    )
    for source, report in sorted(payload["sources"].items()):
        source_manifest = manifest["sources"].get(source, {})
        lines.append(
            f"| {source} | {source_manifest.get('integrity_valid', 0)} | {report['rows']} | "
            f"{report['normalized_timestamp_range']['first']} | "
            f"{report['normalized_timestamp_range']['last']} | "
            f"{report['raw_timestamp_gaps']['gap_count']} | "
            f"{report['duplicates']['duplicate_rows']} | "
            f"{report['duplicates']['conflicting_timestamps']} | {report['off_grid_rows']} |"
        )
    lines.extend(
        [
            "",
            "## Source-only hourly availability",
            "",
            "| Period | Family | Available / candidate | Coverage | Floor pass |",
            "|---|---|---:|---:|---|",
        ]
    )
    for period_name, period in payload["availability"]["periods"].items():
        for family, report in period["families"].items():
            lines.append(
                f"| {period_name} | {family} | {report['available_hours']} / "
                f"{report['candidate_hours']} | {report['coverage_fraction']:.6f} | "
                f"{report['floor_pass']} |"
            )
        joint = period["joint"]
        lines.append(
            f"| {period_name} | **four-family joint** | {joint['available_hours']} / "
            f"{period['candidate_hours']} | {joint['coverage_fraction']:.6f} | "
            f"{joint['floor_pass']} |"
        )
    zero_months = payload["availability"]["zero_joint_full_months"]
    lines.extend(
        [
            "",
            f"Coverage clearance: {payload['availability']['coverage_clearance']}",
            "",
            "Zero-joint full calendar months: "
            + (", ".join(zero_months) if zero_months else "none"),
            "",
            "Coverage cannot override the publication-evidence gate.",
            "",
            "## Frozen candidate transformations",
            "",
        ]
    )
    for family, contract in payload["candidate_contracts"].items():
        lines.extend(
            [
                f"### {family}",
                "",
                f"- Source: {contract['source']}",
                f"- Field/unit: {contract['field_unit']}",
                f"- Timestamp: {contract['timestamp']}",
                f"- As-of: {contract['as_of']}",
                f"- Transform: `{contract['transform']}`",
                f"- Missingness: {contract['missingness']}",
                f"- Effective raw start: {contract['effective_raw_start']}",
                f"- Publication evidence: {contract['publication_evidence']}",
                "",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"


def write_audit(
    *,
    data_root: Path,
    output_dir: Path,
    repo_root: Path,
    identities: Sequence[ArchiveIdentity] | None = None,
    periods: Sequence[AuditPeriod] = DEFAULT_PERIODS,
) -> tuple[Path, Path, Path]:
    payload, config = build_audit_payload(
        data_root=data_root,
        identities=identities,
        periods=periods,
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "m1_availability.json"
    md_path = output_dir / "m1_availability.md"
    json_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    md_path.write_text(render_markdown(payload), encoding="utf-8")
    provenance = build_provenance(
        repo_root=repo_root,
        config=config,
        inputs=[data_root / MANIFEST_IDENTIFIER],
        outputs=[json_path, md_path],
        input_base=data_root,
        output_base=output_dir,
    )
    manifest_entry = provenance["inputs"][0]
    provenance["input_manifest_identifier"] = manifest_entry["path"]
    provenance["input_manifest_sha256"] = manifest_entry["sha256"]
    provenance["input_manifest_bytes"] = manifest_entry["bytes"]
    provenance_path = write_provenance_sidecar(output_dir, "m1_availability", provenance)
    return json_path, md_path, provenance_path


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    default_repo = Path(__file__).resolve().parent.parent
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, default=Path("reports/exp004"))
    parser.add_argument("--repo-root", type=Path, default=default_repo)
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
        print(f"M1 availability audit failed: {exc}", file=sys.stderr)
        return 1
    for path in outputs:
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
