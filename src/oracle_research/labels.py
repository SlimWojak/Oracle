"""Causal first-passage labelling primitives.

This module owns mechanics only. Event clustering, volatility-normalized barriers,
and consolidated-index construction remain configurable research decisions.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from math import isfinite


class Direction(StrEnum):
    """First barrier reached after an anchor."""

    UP = "up"
    DOWN = "down"
    NONE = "none"
    AMBIGUOUS = "ambiguous"


@dataclass(frozen=True, slots=True)
class Bar:
    """Minimal consolidated-index bar required for barrier labelling."""

    timestamp: int
    high: float
    low: float
    close: float

    def __post_init__(self) -> None:
        values = (self.high, self.low, self.close)
        if not all(isfinite(value) and value > 0 for value in values):
            raise ValueError("bar prices must be finite and positive")
        if self.low > self.high:
            raise ValueError("bar low cannot exceed bar high")
        if not self.low <= self.close <= self.high:
            raise ValueError("bar close must lie within [low, high]")


@dataclass(frozen=True, slots=True)
class FirstPassage:
    """Outcome observed strictly after one anchor bar."""

    anchor_index: int
    anchor_timestamp: int
    anchor_price: float
    threshold_fraction: float
    horizon_bars: int
    direction: Direction
    passage_index: int | None
    passage_timestamp: int | None
    elapsed_bars: int | None


def first_passage(
    bars: Sequence[Bar],
    *,
    anchor_index: int,
    horizon_bars: int,
    threshold_fraction: float,
) -> FirstPassage:
    """Label the first fixed barrier reached after ``anchor_index``.

    The anchor bar is excluded because its high/low occurred before the decision at
    its close. When both barriers are reached in one future bar, OHLC data cannot
    establish ordering and the result is ``AMBIGUOUS``.
    """

    if not bars:
        raise ValueError("bars cannot be empty")
    if not 0 <= anchor_index < len(bars):
        raise IndexError("anchor_index is outside bars")
    if horizon_bars <= 0:
        raise ValueError("horizon_bars must be positive")
    if not isfinite(threshold_fraction) or not 0 < threshold_fraction < 1:
        raise ValueError("threshold_fraction must be finite and between 0 and 1")

    anchor = bars[anchor_index]
    upper = anchor.close * (1 + threshold_fraction)
    lower = anchor.close * (1 - threshold_fraction)
    stop = min(len(bars), anchor_index + horizon_bars + 1)

    for passage_index in range(anchor_index + 1, stop):
        bar = bars[passage_index]
        hit_up = bar.high >= upper
        hit_down = bar.low <= lower

        if hit_up and hit_down:
            direction = Direction.AMBIGUOUS
        elif hit_up:
            direction = Direction.UP
        elif hit_down:
            direction = Direction.DOWN
        else:
            continue

        return FirstPassage(
            anchor_index=anchor_index,
            anchor_timestamp=anchor.timestamp,
            anchor_price=anchor.close,
            threshold_fraction=threshold_fraction,
            horizon_bars=horizon_bars,
            direction=direction,
            passage_index=passage_index,
            passage_timestamp=bar.timestamp,
            elapsed_bars=passage_index - anchor_index,
        )

    return FirstPassage(
        anchor_index=anchor_index,
        anchor_timestamp=anchor.timestamp,
        anchor_price=anchor.close,
        threshold_fraction=threshold_fraction,
        horizon_bars=horizon_bars,
        direction=Direction.NONE,
        passage_index=None,
        passage_timestamp=None,
        elapsed_bars=None,
    )

