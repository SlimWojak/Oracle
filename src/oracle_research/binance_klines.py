"""Binance Vision monthly spot kline zip loader.

Kline ``open_time`` is the interval start. Newer monthly files may include a
header and use epoch microseconds; older files have no header and use epoch
milliseconds. All timestamps are normalized to integer epoch seconds (floor).
Gaps are preserved.
"""

from __future__ import annotations

import zipfile
from dataclasses import dataclass
from io import StringIO
from pathlib import Path

import numpy as np

_HEADER_OPEN_TIME = "open_time"
_MICROSECOND_THRESHOLD = 1e14
_USECOLS = (0, 1, 2, 3, 4, 5)


@dataclass(frozen=True, slots=True)
class KlineArrays:
    """Column-aligned 1m kline arrays. ``timestamp`` is interval-start epoch seconds."""

    timestamp: np.ndarray
    open: np.ndarray
    high: np.ndarray
    low: np.ndarray
    close: np.ndarray
    volume: np.ndarray
    n_rows: int

    def __post_init__(self) -> None:
        arrays = (
            self.timestamp,
            self.open,
            self.high,
            self.low,
            self.close,
            self.volume,
        )
        if any(getattr(arr, "ndim", None) != 1 for arr in arrays):
            raise ValueError("kline columns must be one-dimensional")
        lengths = {int(arr.shape[0]) for arr in arrays}
        if len(lengths) != 1:
            raise ValueError("kline columns must have equal length")
        n_rows = lengths.pop()
        if n_rows == 0:
            raise ValueError("kline arrays cannot be empty")
        if n_rows != self.n_rows:
            raise ValueError("n_rows does not match column length")
        if self.timestamp.dtype != np.int64:
            raise ValueError("timestamp must be int64 epoch seconds")
        if n_rows > 1 and not bool(np.all(np.diff(self.timestamp) > 0)):
            raise ValueError("kline timestamps must be strictly increasing")
        for name in ("open", "high", "low", "close"):
            prices = getattr(self, name)
            if not bool(np.all(np.isfinite(prices) & (prices > 0))):
                raise ValueError(f"{name} prices must be finite and positive")
        if not bool(np.all(self.low <= self.high)):
            raise ValueError("low cannot exceed high")
        if not bool(np.all(np.isfinite(self.volume) & (self.volume >= 0))):
            raise ValueError("volume must be finite and non-negative")


def _is_header_field(field: str) -> bool:
    cleaned = field.strip().lstrip("\ufeff")
    if cleaned.lower() == _HEADER_OPEN_TIME:
        return True
    try:
        float(cleaned)
    except ValueError:
        return True
    return False


def _open_time_to_seconds(raw: np.ndarray) -> np.ndarray:
    """Normalize per-row ms/us epoch values to integer epoch seconds (floor)."""

    values = np.floor(raw).astype(np.int64, copy=False)
    microseconds = values > _MICROSECOND_THRESHOLD
    seconds = np.empty(values.shape, dtype=np.int64)
    seconds[microseconds] = values[microseconds] // 1_000_000
    seconds[~microseconds] = values[~microseconds] // 1_000
    return seconds


def _csv_member_name(archive: zipfile.ZipFile, path: Path) -> str:
    names = [
        name
        for name in archive.namelist()
        if name.lower().endswith(".csv") and not name.endswith("/")
    ]
    if len(names) != 1:
        raise ValueError(f"{path} must contain exactly one CSV, found {names!r}")
    return names[0]


def load_kline_zip(path: Path) -> KlineArrays:
    """Load one Binance Vision monthly kline zip into column arrays."""

    path = Path(path)
    with zipfile.ZipFile(path) as archive:
        raw = archive.read(_csv_member_name(archive, path))
    text = raw.decode("utf-8-sig")
    lines = [line for line in text.splitlines() if line.strip()]
    if not lines:
        raise ValueError(f"{path} CSV is empty")
    start = 1 if _is_header_field(lines[0].split(",", 1)[0]) else 0
    if start >= len(lines):
        raise ValueError(f"{path} CSV has a header but no rows")
    body = "\n".join(lines[start:])
    data = np.loadtxt(StringIO(body), delimiter=",", usecols=_USECOLS, dtype=np.float64, ndmin=2)
    timestamp = _open_time_to_seconds(data[:, 0])
    return KlineArrays(
        timestamp=np.ascontiguousarray(timestamp, dtype=np.int64),
        open=np.ascontiguousarray(data[:, 1], dtype=np.float64),
        high=np.ascontiguousarray(data[:, 2], dtype=np.float64),
        low=np.ascontiguousarray(data[:, 3], dtype=np.float64),
        close=np.ascontiguousarray(data[:, 4], dtype=np.float64),
        volume=np.ascontiguousarray(data[:, 5], dtype=np.float64),
        n_rows=int(data.shape[0]),
    )


def load_kline_dir(dir: Path) -> KlineArrays:
    """Load every ``*.zip`` in ``dir`` in filename order and concatenate months."""

    directory = Path(dir)
    zips = sorted(path for path in directory.glob("*.zip") if path.is_file())
    if not zips:
        raise FileNotFoundError(f"no kline zip files in {directory}")
    parts = [load_kline_zip(path) for path in zips]
    for index in range(1, len(parts)):
        previous = parts[index - 1]
        current = parts[index]
        if int(current.timestamp[0]) <= int(previous.timestamp[-1]):
            raise ValueError(
                "kline timestamps must be strictly increasing across files: "
                f"{zips[index - 1].name} ends at {int(previous.timestamp[-1])}, "
                f"{zips[index].name} starts at {int(current.timestamp[0])}"
            )
    return KlineArrays(
        timestamp=np.concatenate([part.timestamp for part in parts]),
        open=np.concatenate([part.open for part in parts]),
        high=np.concatenate([part.high for part in parts]),
        low=np.concatenate([part.low for part in parts]),
        close=np.concatenate([part.close for part in parts]),
        volume=np.concatenate([part.volume for part in parts]),
        n_rows=sum(part.n_rows for part in parts),
    )


def contiguous_segments(
    timestamps: np.ndarray,
    step_seconds: int = 60,
) -> list[tuple[int, int]]:
    """Return ``[start, end)`` index ranges whose consecutive steps equal ``step_seconds``."""

    if step_seconds <= 0:
        raise ValueError("step_seconds must be positive")
    values = np.asarray(timestamps)
    if values.ndim != 1:
        raise ValueError("timestamps must be one-dimensional")
    n_rows = int(values.size)
    if n_rows == 0:
        return []
    if n_rows == 1:
        return [(0, 1)]
    breaks = np.nonzero(np.diff(values) != step_seconds)[0]
    segments: list[tuple[int, int]] = []
    start = 0
    for break_at in breaks:
        end = int(break_at) + 1
        segments.append((start, end))
        start = end
    segments.append((start, n_rows))
    return segments
