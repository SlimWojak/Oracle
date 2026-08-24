"""Hyperliquid node_fills normalization for old and by-block hourly formats."""

from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

try:
    import lz4.frame
except ImportError:  # optional dependency group ``hyperliquid``
    lz4 = None  # type: ignore[misc, assignment]


def _parse_optional_time_ms(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, int):
        return value if value >= 1_000_000_000_000 else value * 1000
    text = str(value).strip()
    if not text:
        return None
    if text.isdigit():
        time_ms = int(text)
        if time_ms < 1_000_000_000_000:
            time_ms *= 1000
        return time_ms
    normalized = text.replace("Z", "+00:00")
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return int(parsed.timestamp() * 1000)


@dataclass(frozen=True, slots=True)
class HlFill:
    """One normalized Hyperliquid fill record."""

    user: str
    coin: str
    px: str
    sz: str
    side: str
    time_ms: int
    start_position: str
    dir: str
    hash: str
    oid: int
    crossed: bool
    tid: int
    fee: str
    fee_token: str
    liquidation: dict[str, Any] | None = None
    block_time: int | None = None
    local_time: int | None = None
    block_number: int | None = None


def _normalize_fill(
    user: str,
    fill: dict[str, Any],
    *,
    block_time: int | None = None,
    local_time: int | None = None,
    block_number: int | None = None,
) -> HlFill:
    liquidation = fill.get("liquidation")
    if liquidation is not None and not isinstance(liquidation, dict):
        raise ValueError(f"malformed liquidation object: {liquidation!r}")

    return HlFill(
        user=user,
        coin=str(fill["coin"]),
        px=str(fill["px"]),
        sz=str(fill["sz"]),
        side=str(fill["side"]),
        time_ms=int(fill["time"]),
        start_position=str(fill.get("startPosition", "0")),
        dir=str(fill.get("dir", "")),
        hash=str(fill["hash"]),
        oid=int(fill["oid"]),
        crossed=bool(fill["crossed"]),
        tid=int(fill["tid"]),
        fee=str(fill.get("fee", "0")),
        fee_token=str(fill.get("feeToken", "")),
        liquidation=liquidation,
        block_time=block_time,
        local_time=local_time,
        block_number=block_number,
    )


def _iter_block_record(record: dict[str, Any]) -> Iterator[HlFill]:
    events = record.get("events")
    if not isinstance(events, list):
        raise ValueError("by-block record missing events list")

    block_time = record.get("block_time")
    local_time = record.get("local_time")
    block_number = record.get("block_number")
    parsed_block_time = _parse_optional_time_ms(block_time)
    parsed_local_time = _parse_optional_time_ms(local_time)
    parsed_block_number = int(block_number) if block_number is not None else None

    for event in events:
        if not isinstance(event, list) or len(event) != 2:
            raise ValueError(f"malformed by-block event: {event!r}")
        user_address, fill_dict = event
        if not isinstance(user_address, str) or not isinstance(fill_dict, dict):
            raise ValueError(f"malformed by-block event pair: {event!r}")
        yield _normalize_fill(
            user_address,
            fill_dict,
            block_time=parsed_block_time,
            local_time=parsed_local_time,
            block_number=parsed_block_number,
        )


def _iter_parsed_line(parsed: Any) -> Iterator[HlFill]:
    if isinstance(parsed, dict) and "events" in parsed:
        yield from _iter_block_record(parsed)
        return

    if (
        isinstance(parsed, list)
        and len(parsed) == 2
        and isinstance(parsed[0], str)
        and isinstance(parsed[1], dict)
    ):
        yield _normalize_fill(parsed[0], parsed[1])
        return

    raise ValueError(f"unsupported fill line shape: {type(parsed).__name__}")


def iter_fills_from_json_line_bytes(lines: Iterator[bytes]) -> Iterator[HlFill]:
    """Parse newline-delimited JSON fill payloads from a byte-line iterator."""
    for line_number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid JSON on line {line_number}") from exc
        yield from _iter_parsed_line(parsed)


def iter_fills_from_json_lines(raw: bytes) -> Iterator[HlFill]:
    """Parse newline-delimited JSON fill payloads (decompressed hourly files)."""
    yield from iter_fills_from_json_line_bytes(iter(raw.splitlines()))


def iter_fills_from_lz4(path: Path) -> Iterator[HlFill]:
    """Stream normalized fills from one lz4-compressed hourly node_fills file."""
    if lz4 is None:
        msg = "lz4 is required; install with pip install oracle-btc-research[hyperliquid]"
        raise ImportError(msg)

    with lz4.frame.open(Path(path), mode="rb") as handle:
        yield from iter_fills_from_json_line_bytes(handle)
