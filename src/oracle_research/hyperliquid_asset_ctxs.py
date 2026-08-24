"""Hyperliquid per-minute asset context loader (mark, funding, oracle)."""

from __future__ import annotations

import csv
import io
from bisect import bisect_right
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path

try:
    import lz4.frame
except ImportError:  # optional dependency group ``hyperliquid``
    lz4 = None  # type: ignore[misc, assignment]

MS_PER_MINUTE = 60_000

_TIME_COLUMNS = frozenset({"time_ms", "time", "timestamp", "ts"})
_COIN_COLUMNS = frozenset({"coin", "symbol", "asset"})
_MARK_COLUMNS = frozenset({"mark_px", "markpx", "mark"})
_FUNDING_COLUMNS = frozenset({"funding", "funding_rate"})
_ORACLE_COLUMNS = frozenset({"oracle_px", "oraclepx", "oracle"})


@dataclass(frozen=True, slots=True)
class AssetCtxMinute:
    """One per-minute asset context observation."""

    time_ms: int
    coin: str
    mark_px: float
    funding: float
    oracle_px: float


def floor_to_minute(time_ms: int) -> int:
    """Align ``time_ms`` to the containing minute boundary (floor)."""

    return (time_ms // MS_PER_MINUTE) * MS_PER_MINUTE


def _require_lz4() -> None:
    if lz4 is None:
        msg = "lz4 is required; install with pip install oracle-btc-research[hyperliquid]"
        raise ImportError(msg)


def _normalize_header(name: str) -> str:
    return name.strip().lower().replace("-", "_")


def _pick_column(fieldnames: Iterable[str], candidates: frozenset[str]) -> str | None:
    for raw in fieldnames:
        if _normalize_header(raw) in candidates:
            return raw
    return None


def _parse_time_ms(raw_time: str) -> int:
    text = raw_time.strip()
    if not text:
        raise ValueError("empty time field")
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


def _parse_float(value: str) -> float:
    text = value.strip()
    if not text:
        raise ValueError("empty numeric field")
    return float(text)


def _iter_csv_rows(text: str) -> Iterator[AssetCtxMinute]:
    reader = csv.DictReader(io.StringIO(text))
    if reader.fieldnames is None:
        raise ValueError("asset_ctxs CSV missing header row")

    time_col = _pick_column(reader.fieldnames, _TIME_COLUMNS)
    coin_col = _pick_column(reader.fieldnames, _COIN_COLUMNS)
    mark_col = _pick_column(reader.fieldnames, _MARK_COLUMNS)
    funding_col = _pick_column(reader.fieldnames, _FUNDING_COLUMNS)
    oracle_col = _pick_column(reader.fieldnames, _ORACLE_COLUMNS)
    missing = [
        name
        for name, col in (
            ("time", time_col),
            ("coin", coin_col),
            ("mark_px", mark_col),
            ("funding", funding_col),
            ("oracle_px", oracle_col),
        )
        if col is None
    ]
    if missing:
        raise ValueError(f"asset_ctxs CSV missing required columns: {', '.join(missing)}")

    assert time_col is not None
    assert coin_col is not None
    assert mark_col is not None
    assert funding_col is not None
    assert oracle_col is not None

    for row in reader:
        time_ms = _parse_time_ms(row[time_col])
        yield AssetCtxMinute(
            time_ms=time_ms,
            coin=row[coin_col].strip(),
            mark_px=_parse_float(row[mark_col]),
            funding=_parse_float(row[funding_col]),
            oracle_px=_parse_float(row[oracle_col]),
        )


def load_asset_ctx_day(path: Path) -> list[AssetCtxMinute]:
    """Load one daily ``asset_ctxs/YYYYMMDD.csv.lz4`` file."""

    _require_lz4()
    resolved = Path(path)
    with lz4.frame.open(resolved, mode="rb") as handle:
        raw = handle.read()
    return list(_iter_csv_rows(raw.decode("utf-8")))


def asset_ctx_day_path(data_root: Path, day: date) -> Path:
    """Return the canonical daily asset_ctxs path under ``data_root``."""

    filename = f"{day:%Y%m%d}.csv.lz4"
    candidates = (
        data_root / "asset_ctxs" / filename,
        data_root / "raw" / "hyperliquid" / "asset_ctxs" / filename,
    )
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return candidates[0]


class AssetCtxStore:
    """Minute-indexed mark lookup for one coin."""

    def __init__(self, rows: Iterable[AssetCtxMinute], *, coin: str = "BTC") -> None:
        filtered = [row for row in rows if row.coin == coin]
        filtered.sort(key=lambda item: item.time_ms)
        self._times = [row.time_ms for row in filtered]
        self._marks = [row.mark_px for row in filtered]
        self._by_minute = {row.time_ms: row.mark_px for row in filtered}

    def get_mark_px(self, coin: str, time_ms: int) -> float | None:
        """Return mark price at ``time_ms`` (minute floor) for ``coin``."""

        if coin != "BTC" or not self._times:
            return None
        minute_ms = floor_to_minute(time_ms)
        exact = self._by_minute.get(minute_ms)
        if exact is not None:
            return exact
        index = bisect_right(self._times, minute_ms) - 1
        if index < 0:
            return None
        return self._marks[index]

    @property
    def minute_count(self) -> int:
        return len(self._times)


def load_btc_minutes_for_days(data_root: Path, dates: Iterable[date]) -> AssetCtxStore:
    """Load and index BTC mark minutes for the given UTC calendar days."""

    rows: list[AssetCtxMinute] = []
    for day in dates:
        path = asset_ctx_day_path(data_root, day)
        if path.is_file():
            rows.extend(load_asset_ctx_day(path))
    return AssetCtxStore(rows, coin="BTC")
