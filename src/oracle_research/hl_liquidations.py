"""BTC liquidation extraction and stratification from normalized Hyperliquid fills."""

from __future__ import annotations

from bisect import bisect_right
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal

from oracle_research.hyperliquid_fills import HlFill

Stratum = Literal["a", "b", "c"]
POSITION_EPSILON = 1e-8
MARKET_CLOSE_DIRS = frozenset({"Close Long", "Close Short"})


def end_position_after_fill(start_position: str | float, side: str, sz: str | float) -> float:
    """Infer signed net position after one fill from pre-fill startPosition."""
    start = float(start_position)
    delta = float(sz)
    return start + delta if side == "B" else start - delta


@dataclass(frozen=True, slots=True)
class BtcLiquidationEvent:
    """One deduplicated BTC liquidation on the liquidated-user leg."""

    liquidated_user: str
    tid: int
    time_ms: int
    px: str
    sz: str
    usd_notional: float
    mark_px: str
    method: str
    dir: str
    start_position: str
    user: str
    coin: str = "BTC"


def extract_btc_liquidation_events(fills: Iterable[HlFill]) -> list[BtcLiquidationEvent]:
    """Return deduplicated BTC liquidation events (liquidated-user leg only)."""
    seen: set[tuple[str, int]] = set()
    events: list[BtcLiquidationEvent] = []

    for fill in fills:
        if fill.coin != "BTC" or fill.liquidation is None:
            continue

        liquidated_user = str(fill.liquidation.get("liquidatedUser", ""))
        if not liquidated_user or fill.user != liquidated_user:
            continue

        key = (liquidated_user, fill.tid)
        if key in seen:
            continue
        seen.add(key)

        px = float(fill.px)
        sz = float(fill.sz)
        events.append(
            BtcLiquidationEvent(
                liquidated_user=liquidated_user,
                tid=fill.tid,
                time_ms=fill.time_ms,
                px=fill.px,
                sz=fill.sz,
                usd_notional=px * sz,
                mark_px=str(fill.liquidation.get("markPx", "")),
                method=str(fill.liquidation.get("method", "")),
                dir=fill.dir,
                start_position=fill.start_position,
                user=fill.user,
            )
        )

    events.sort(key=lambda item: (item.time_ms, item.tid))
    return events


class PositionTracker:
    """Track per-user coin startPosition history from fill tape updates."""

    def __init__(self) -> None:
        self._history: dict[tuple[str, str], list[tuple[int, str]]] = {}

    def update(self, fill: HlFill) -> None:
        key = (fill.user.lower(), fill.coin)
        end_position = end_position_after_fill(fill.start_position, fill.side, fill.sz)
        series = self._history.setdefault(key, [])
        if series and series[-1][0] == fill.time_ms:
            series[-1] = (fill.time_ms, str(end_position))
            return
        series.append((fill.time_ms, str(end_position)))

    def start_position_at(self, user: str, coin: str, time_ms: int) -> str | None:
        series = self._history.get((user.lower(), coin))
        if not series:
            return None
        timestamps = [item[0] for item in series]
        index = bisect_right(timestamps, time_ms) - 1
        if index < 0:
            return None
        return series[index][1]

    def coin_positions_at(self, user: str, time_ms: int) -> dict[str, str]:
        normalized_user = user.lower()
        positions: dict[str, str] = {}
        for (tracked_user, coin), _series in self._history.items():
            if tracked_user != normalized_user:
                continue
            position = self.start_position_at(tracked_user, coin, time_ms)
            if position is not None:
                positions[coin] = position
        return positions


def btc_only_at_time(_user: str, _time_ms: int, coin_positions: dict[str, str]) -> bool:
    """Return True when no non-BTC coin has material exposure at ``time_ms``."""
    for coin, position in coin_positions.items():
        if coin == "BTC":
            continue
        if abs(float(position)) >= POSITION_EPSILON:
            return False
    return True


def stratify_event(event: BtcLiquidationEvent, *, is_btc_only: bool) -> Stratum:
    """Classify one deduped BTC liquidation event into strata a/b/c."""
    if not is_btc_only:
        return "c"
    if event.dir.startswith("Liquidated Isolated"):
        return "a"
    if event.dir.startswith("Liquidated Cross"):
        return "b"
    if event.method == "market" and event.dir in MARKET_CLOSE_DIRS:
        return "b"
    return "c"


def event_to_dict(event: BtcLiquidationEvent) -> dict[str, object]:
    """Serialize one liquidation event for JSONL output."""
    return {
        "liquidated_user": event.liquidated_user,
        "tid": event.tid,
        "time_ms": event.time_ms,
        "px": event.px,
        "sz": event.sz,
        "usd_notional": event.usd_notional,
        "mark_px": event.mark_px,
        "method": event.method,
        "dir": event.dir,
        "start_position": event.start_position,
        "user": event.user,
        "coin": event.coin,
    }
