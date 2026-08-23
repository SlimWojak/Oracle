"""Vectorized first-passage labels aligned to ``labels.first_passage``.

Every bar in a contiguous segment is an anchor. The anchor bar is excluded.
Anchors whose full horizon does not fit inside the segment are
``insufficient_horizon`` and are never labelled as a negative (none).

``batch_first_passage_time`` is the wall-clock twin for gappy minute grids
(D-021 correction, D-022 rule 5): each anchor's window is the time span
``(t, t + horizon_seconds]`` evaluated over whatever bars exist there; absent
minutes contribute no evidence. On a complete grid the two labellers agree.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite

import numpy as np
from numpy.lib.stride_tricks import sliding_window_view

DIR_INSUFFICIENT = np.int8(-1)
DIR_NONE = np.int8(0)
DIR_UP = np.int8(1)
DIR_DOWN = np.int8(2)
DIR_AMBIGUOUS = np.int8(3)

CHUNK_SIZE = 65_536


@dataclass(frozen=True, slots=True)
class BatchLabels:
    """Per-anchor first-passage outcomes aligned to the segment's bar index."""

    direction: np.ndarray
    passage_index: np.ndarray
    elapsed_bars: np.ndarray

    def __post_init__(self) -> None:
        if self.direction.dtype != np.int8:
            raise ValueError("direction must be int8")
        if self.passage_index.dtype != np.int64:
            raise ValueError("passage_index must be int64")
        if self.elapsed_bars.dtype != np.int64:
            raise ValueError("elapsed_bars must be int64")
        if not (self.direction.shape == self.passage_index.shape == self.elapsed_bars.shape):
            raise ValueError("batch label columns must have equal length")
        if self.direction.ndim != 1:
            raise ValueError("batch label columns must be one-dimensional")


def _validate_inputs(
    high: np.ndarray,
    low: np.ndarray,
    close: np.ndarray,
    *,
    horizon_bars: int,
    threshold_fraction: float,
    segment: tuple[int, int] | None,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, int, int]:
    if horizon_bars <= 0:
        raise ValueError("horizon_bars must be positive")
    if not isfinite(threshold_fraction) or not 0 < threshold_fraction < 1:
        raise ValueError("threshold_fraction must be finite and between 0 and 1")
    high_arr = np.asarray(high, dtype=np.float64)
    low_arr = np.asarray(low, dtype=np.float64)
    close_arr = np.asarray(close, dtype=np.float64)
    if high_arr.ndim != 1 or low_arr.ndim != 1 or close_arr.ndim != 1:
        raise ValueError("high, low, and close must be one-dimensional")
    if not (high_arr.shape == low_arr.shape == close_arr.shape):
        raise ValueError("high, low, and close must have the same length")
    n_rows = int(high_arr.size)
    if segment is None:
        start, end = 0, n_rows
    else:
        start, end = segment
        if not 0 <= start < end <= n_rows:
            raise ValueError("segment must satisfy 0 <= start < end <= n")
    return high_arr, low_arr, close_arr, start, end


def _label_chunk(
    high: np.ndarray,
    low: np.ndarray,
    close: np.ndarray,
    *,
    abs_start: int,
    n_chunk: int,
    horizon_bars: int,
    upper_scale: float,
    lower_scale: float,
    direction_out: np.ndarray,
    passage_out: np.ndarray,
    elapsed_out: np.ndarray,
) -> None:
    window_stop = abs_start + n_chunk + horizon_bars
    high_windows = sliding_window_view(high[abs_start + 1 : window_stop], horizon_bars)
    low_windows = sliding_window_view(low[abs_start + 1 : window_stop], horizon_bars)
    anchor_close = close[abs_start : abs_start + n_chunk]
    upper = anchor_close * upper_scale
    lower = anchor_close * lower_scale
    hit_up = high_windows >= upper[:, np.newaxis]
    hit_down = low_windows <= lower[:, np.newaxis]
    any_up = hit_up.any(axis=1)
    any_down = hit_down.any(axis=1)
    first_up = hit_up.argmax(axis=1)
    first_down = hit_down.argmax(axis=1)

    offset = np.full(n_chunk, -1, dtype=np.int64)
    direction = np.zeros(n_chunk, dtype=np.int8)

    only_up = any_up & ~any_down
    only_down = any_down & ~any_up
    both = any_up & any_down
    up_wins = both & (first_up < first_down)
    down_wins = both & (first_down < first_up)
    tie = both & (first_up == first_down)

    direction[only_up] = DIR_UP
    offset[only_up] = first_up[only_up]
    direction[only_down] = DIR_DOWN
    offset[only_down] = first_down[only_down]
    direction[up_wins] = DIR_UP
    offset[up_wins] = first_up[up_wins]
    direction[down_wins] = DIR_DOWN
    offset[down_wins] = first_down[down_wins]
    direction[tie] = DIR_AMBIGUOUS
    offset[tie] = first_up[tie]

    local = np.arange(n_chunk, dtype=np.int64)
    hit = offset >= 0
    direction_out[:] = direction
    passage_out[:] = -1
    elapsed_out[:] = -1
    passage_out[hit] = abs_start + local[hit] + 1 + offset[hit]
    elapsed_out[hit] = 1 + offset[hit]


def batch_first_passage(
    high: np.ndarray,
    low: np.ndarray,
    close: np.ndarray,
    *,
    horizon_bars: int,
    threshold_fraction: float,
    segment: tuple[int, int] | None = None,
) -> BatchLabels:
    """Label every anchor in ``segment`` (or the full series) with a fixed horizon.

    ``passage_index`` is an index into the input arrays. Output length equals the
    number of bars in the segment. Codes: 0 none, 1 up, 2 down, 3 ambiguous,
    -1 insufficient_horizon.
    """

    high, low, close, start, end = _validate_inputs(
        high,
        low,
        close,
        horizon_bars=horizon_bars,
        threshold_fraction=threshold_fraction,
        segment=segment,
    )
    length = end - start
    direction = np.full(length, DIR_INSUFFICIENT, dtype=np.int8)
    passage_index = np.full(length, -1, dtype=np.int64)
    elapsed_bars = np.full(length, -1, dtype=np.int64)
    n_valid = length - horizon_bars
    if n_valid <= 0:
        return BatchLabels(
            direction=direction,
            passage_index=passage_index,
            elapsed_bars=elapsed_bars,
        )

    upper_scale = 1.0 + threshold_fraction
    lower_scale = 1.0 - threshold_fraction
    for chunk0 in range(0, n_valid, CHUNK_SIZE):
        chunk1 = min(chunk0 + CHUNK_SIZE, n_valid)
        _label_chunk(
            high,
            low,
            close,
            abs_start=start + chunk0,
            n_chunk=chunk1 - chunk0,
            horizon_bars=horizon_bars,
            upper_scale=upper_scale,
            lower_scale=lower_scale,
            direction_out=direction[chunk0:chunk1],
            passage_out=passage_index[chunk0:chunk1],
            elapsed_out=elapsed_bars[chunk0:chunk1],
        )
    return BatchLabels(
        direction=direction,
        passage_index=passage_index,
        elapsed_bars=elapsed_bars,
    )


def batch_first_passage_time(
    timestamp: np.ndarray,
    high: np.ndarray,
    low: np.ndarray,
    close: np.ndarray,
    *,
    horizon_seconds: int,
    threshold_fraction: float,
    step_seconds: int = 60,
) -> BatchLabels:
    """Wall-clock first-passage labels over a gappy minute grid.

    Every bar is an anchor; its window is ``(t, t + horizon_seconds]``
    evaluated over the bars that exist in it. Anchors whose window extends
    beyond the last bar are ``insufficient_horizon`` regardless of visible
    hits, mirroring the bar-count labeller's tail semantics.
    ``passage_index`` indexes the input arrays; ``elapsed_bars`` counts bars,
    not minutes, on a gappy grid.
    """

    if horizon_seconds <= 0 or horizon_seconds % step_seconds != 0:
        raise ValueError("horizon_seconds must be a positive multiple of step_seconds")
    if not isfinite(threshold_fraction) or not 0 < threshold_fraction < 1:
        raise ValueError("threshold_fraction must be finite and between 0 and 1")
    ts = np.asarray(timestamp, dtype=np.int64)
    high_arr = np.asarray(high, dtype=np.float64)
    low_arr = np.asarray(low, dtype=np.float64)
    close_arr = np.asarray(close, dtype=np.float64)
    if not (ts.shape == high_arr.shape == low_arr.shape == close_arr.shape) or ts.ndim != 1:
        raise ValueError("inputs must be one-dimensional arrays of equal length")
    n_rows = int(ts.size)
    if n_rows == 0:
        raise ValueError("inputs cannot be empty")
    diffs = np.diff(ts)
    if diffs.size and (not bool(np.all(diffs > 0)) or not bool(np.all(diffs % step_seconds == 0))):
        raise ValueError("timestamps must be strictly increasing on the step grid")

    window_bars = horizon_seconds // step_seconds
    pad_ts = np.full(window_bars, np.iinfo(np.int64).max, dtype=np.int64)
    pad_price = np.full(window_bars, np.nan)
    ts_padded = np.concatenate([ts, pad_ts])
    high_padded = np.concatenate([high_arr, pad_price])
    low_padded = np.concatenate([low_arr, pad_price])
    ts_windows = sliding_window_view(ts_padded[1:], window_bars)
    high_windows = sliding_window_view(high_padded[1:], window_bars)
    low_windows = sliding_window_view(low_padded[1:], window_bars)

    direction = np.zeros(n_rows, dtype=np.int8)
    passage_index = np.full(n_rows, -1, dtype=np.int64)
    elapsed_bars = np.full(n_rows, -1, dtype=np.int64)
    upper_scale = 1.0 + threshold_fraction
    lower_scale = 1.0 - threshold_fraction
    last_ts = int(ts[-1])

    for chunk0 in range(0, n_rows, CHUNK_SIZE):
        chunk1 = min(chunk0 + CHUNK_SIZE, n_rows)
        chunk = slice(chunk0, chunk1)
        deadline = (ts[chunk] + horizon_seconds)[:, np.newaxis]
        in_window = ts_windows[chunk] <= deadline
        with np.errstate(invalid="ignore"):
            hit_up = high_windows[chunk] >= (close_arr[chunk] * upper_scale)[:, np.newaxis]
            hit_down = low_windows[chunk] <= (close_arr[chunk] * lower_scale)[:, np.newaxis]
        hit_up &= in_window
        hit_down &= in_window
        any_up = hit_up.any(axis=1)
        any_down = hit_down.any(axis=1)
        first_up = hit_up.argmax(axis=1)
        first_down = hit_down.argmax(axis=1)

        n_chunk = chunk1 - chunk0
        offset = np.full(n_chunk, -1, dtype=np.int64)
        chunk_direction = np.zeros(n_chunk, dtype=np.int8)
        only_up = any_up & ~any_down
        only_down = any_down & ~any_up
        both = any_up & any_down
        up_wins = both & (first_up < first_down)
        down_wins = both & (first_down < first_up)
        tie = both & (first_up == first_down)
        chunk_direction[only_up] = DIR_UP
        offset[only_up] = first_up[only_up]
        chunk_direction[only_down] = DIR_DOWN
        offset[only_down] = first_down[only_down]
        chunk_direction[up_wins] = DIR_UP
        offset[up_wins] = first_up[up_wins]
        chunk_direction[down_wins] = DIR_DOWN
        offset[down_wins] = first_down[down_wins]
        chunk_direction[tie] = DIR_AMBIGUOUS
        offset[tie] = first_up[tie]

        local = np.arange(n_chunk, dtype=np.int64)
        hit = offset >= 0
        direction[chunk] = chunk_direction
        passage_index[chunk0:chunk1][hit] = chunk0 + local[hit] + 1 + offset[hit]
        elapsed_bars[chunk0:chunk1][hit] = 1 + offset[hit]

    insufficient = ts + horizon_seconds > last_ts
    direction[insufficient] = DIR_INSUFFICIENT
    passage_index[insufficient] = -1
    elapsed_bars[insufficient] = -1
    return BatchLabels(
        direction=direction,
        passage_index=passage_index,
        elapsed_bars=elapsed_bars,
    )
