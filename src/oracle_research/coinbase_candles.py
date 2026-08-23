"""Coinbase Exchange public candles loader.

Raw acquisition files are verbatim API responses: JSON arrays of
``[time, low, high, open, close, volume]`` buckets, newest first within each
file, ``time`` = unix seconds UTC marking the interval START. Buckets where no
trades occurred are absent: gaps are structural and preserved. Reuses
:class:`KlineArrays` so the labelling stack stays venue-agnostic.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from oracle_research.binance_klines import KlineArrays


def load_candle_file(path: Path) -> list[list[float]]:
    """Parse one verbatim response file into bucket rows (may be empty)."""

    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError(f"{path} is not a JSON array of candle buckets")
    for row in payload:
        if not isinstance(row, list) or len(row) < 6:
            raise ValueError(f"{path} has a malformed bucket: {row!r}")
    return payload


def load_candle_dir(directory: Path, *, start_ts: int | None = None) -> KlineArrays:
    """Load every ``candles_*.json`` in ``directory`` into ascending arrays.

    Duplicate timestamps are rejected: the acquisition tiling guarantees
    non-overlapping windows, so a duplicate indicates corrupt data.
    """

    paths = sorted(Path(directory).glob("candles_*.json"))
    if not paths:
        raise FileNotFoundError(f"no candle files in {directory}")
    rows: list[list[float]] = []
    for path in paths:
        rows.extend(load_candle_file(path))
    if not rows:
        raise ValueError(f"candle files in {directory} contain no buckets")
    data = np.asarray(rows, dtype=np.float64)
    order = np.argsort(data[:, 0], kind="stable")
    data = data[order]
    timestamp = data[:, 0].astype(np.int64)
    if timestamp.size > 1 and not bool(np.all(np.diff(timestamp) > 0)):
        raise ValueError(f"duplicate candle timestamps in {directory}")
    keep = slice(None)
    if start_ts is not None:
        first = int(np.searchsorted(timestamp, start_ts, side="left"))
        if first >= timestamp.size:
            raise ValueError("start_ts is beyond the last candle")
        keep = slice(first, None)
    return KlineArrays(
        timestamp=np.ascontiguousarray(timestamp[keep]),
        open=np.ascontiguousarray(data[keep, 3]),
        high=np.ascontiguousarray(data[keep, 2]),
        low=np.ascontiguousarray(data[keep, 1]),
        close=np.ascontiguousarray(data[keep, 4]),
        volume=np.ascontiguousarray(data[keep, 5]),
        n_rows=int(timestamp[keep].size),
    )
