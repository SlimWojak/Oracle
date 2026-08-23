"""Kraken official OHLCVT CSV loader.

The downloadable export is a headerless CSV with columns
``timestamp, open, high, low, close, volume, trades`` where ``timestamp`` is
unix seconds UTC marking the interval START. Minutes with zero trades have no
row: gaps are structural and are preserved. Reuses :class:`KlineArrays` so the
labelling stack is venue-agnostic.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from oracle_research.binance_klines import KlineArrays

_USECOLS = (0, 1, 2, 3, 4, 5)


def load_kraken_csv(path: Path) -> KlineArrays:
    """Load one Kraken OHLCVT CSV into column arrays."""

    data = np.loadtxt(Path(path), delimiter=",", usecols=_USECOLS, dtype=np.float64, ndmin=2)
    return KlineArrays(
        timestamp=np.ascontiguousarray(data[:, 0].astype(np.int64)),
        open=np.ascontiguousarray(data[:, 1]),
        high=np.ascontiguousarray(data[:, 2]),
        low=np.ascontiguousarray(data[:, 3]),
        close=np.ascontiguousarray(data[:, 4]),
        volume=np.ascontiguousarray(data[:, 5]),
        n_rows=int(data.shape[0]),
    )


def load_kraken_csvs(paths: list[Path], *, start_ts: int | None = None) -> KlineArrays:
    """Load and concatenate CSVs in the given order; enforce strict time order.

    ``start_ts`` optionally drops bars whose interval start precedes it (the
    export reaches back to 2013; earlier history is irrelevant to the v0
    catalogue window and costs memory).
    """

    if not paths:
        raise ValueError("at least one CSV path is required")
    parts = [load_kraken_csv(path) for path in paths]
    for index in range(1, len(parts)):
        previous, current = parts[index - 1], parts[index]
        if int(current.timestamp[0]) <= int(previous.timestamp[-1]):
            raise ValueError(
                "kraken timestamps must be strictly increasing across files: "
                f"{Path(paths[index - 1]).name} ends at {int(previous.timestamp[-1])}, "
                f"{Path(paths[index]).name} starts at {int(current.timestamp[0])}"
            )
    timestamp = np.concatenate([part.timestamp for part in parts])
    keep = slice(None)
    if start_ts is not None:
        first = int(np.searchsorted(timestamp, start_ts, side="left"))
        if first >= timestamp.size:
            raise ValueError("start_ts is beyond the last kraken bar")
        keep = slice(first, None)
    columns = {
        name: np.concatenate([getattr(part, name) for part in parts])[keep]
        for name in ("timestamp", "open", "high", "low", "close", "volume")
    }
    return KlineArrays(n_rows=int(columns["timestamp"].size), **columns)
