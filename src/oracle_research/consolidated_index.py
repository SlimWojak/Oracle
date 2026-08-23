"""Median-of-three consolidated label index per decision D-022.

An index minute exists iff at least ``min_members`` member venues have a bar.
Open, high, low, and close are componentwise medians of the available members
(the median of two is their midpoint). Volume is the sum of available members
and is diagnostic only. No member is ever forward-filled across its gaps.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from oracle_research.binance_klines import KlineArrays

_FIELDS = ("open", "high", "low", "close")


@dataclass(frozen=True, slots=True)
class IndexBars:
    """Consolidated index bars plus per-bar member availability."""

    klines: KlineArrays
    venue_count: np.ndarray

    def __post_init__(self) -> None:
        if self.venue_count.shape != self.klines.timestamp.shape:
            raise ValueError("venue_count must align with the index bars")
        if self.venue_count.dtype != np.int8:
            raise ValueError("venue_count must be int8")


def _presence_indices(member_ts: np.ndarray, grid_ts: np.ndarray) -> np.ndarray:
    """Index of each grid timestamp in the member arrays, or -1 when absent."""

    position = np.searchsorted(member_ts, grid_ts)
    position_clipped = np.minimum(position, member_ts.size - 1)
    present = member_ts[position_clipped] == grid_ts
    return np.where(present, position_clipped, -1)


def build_median_index(members: list[KlineArrays], *, min_members: int = 2) -> IndexBars:
    """Build the D-022 componentwise-median index over the member union grid."""

    if len(members) < 2:
        raise ValueError("an index needs at least two members")
    if not 1 <= min_members <= len(members):
        raise ValueError("min_members must be between 1 and the member count")

    grid = np.unique(np.concatenate([member.timestamp for member in members]))
    indices = [_presence_indices(member.timestamp, grid) for member in members]
    count = np.zeros(grid.size, dtype=np.int8)
    for member_index in indices:
        count += (member_index >= 0).astype(np.int8)
    keep = count >= min_members
    if not bool(keep.any()):
        raise ValueError("no index minute satisfies the availability rule")
    grid = grid[keep]
    count = count[keep]
    indices = [member_index[keep] for member_index in indices]

    columns: dict[str, np.ndarray] = {}
    stacks = {
        field: np.full((len(members), grid.size), np.nan) for field in (*_FIELDS, "volume")
    }
    for row, (member, member_index) in enumerate(zip(members, indices, strict=True)):
        present = member_index >= 0
        source_rows = member_index[present]
        for field in (*_FIELDS, "volume"):
            stacks[field][row, present] = getattr(member, field)[source_rows]
    with np.errstate(invalid="ignore"):
        for field in _FIELDS:
            columns[field] = np.nanmedian(stacks[field], axis=0)
    volume = np.nansum(stacks["volume"], axis=0)

    klines = KlineArrays(
        timestamp=np.ascontiguousarray(grid, dtype=np.int64),
        open=np.ascontiguousarray(columns["open"]),
        high=np.ascontiguousarray(columns["high"]),
        low=np.ascontiguousarray(columns["low"]),
        close=np.ascontiguousarray(columns["close"]),
        volume=np.ascontiguousarray(volume),
        n_rows=int(grid.size),
    )
    return IndexBars(klines=klines, venue_count=np.ascontiguousarray(count, dtype=np.int8))
