"""EXP-001 Phase 2: isolated/cross liquidation price reconstruction helpers."""

from __future__ import annotations

from dataclasses import dataclass

from oracle_research.hl_liquidations import POSITION_EPSILON, end_position_after_fill
from oracle_research.hyperliquid_fills import HlFill

CROSS_ACCOUNT_VALUE_REASON = "account_value_unobserved"


@dataclass(frozen=True, slots=True)
class BtcMarginConstants:
    """BTC tier-0 margin constants (40x max leverage)."""

    max_leverage: float = 40.0
    initial_margin_rate: float = 0.025
    maintenance_margin_rate: float = 0.0125
    maintenance_leverage: float = 80.0

    @property
    def l_factor(self) -> float:
        return 1.0 / self.maintenance_leverage


@dataclass
class EpisodeState:
    """Tracked BTC isolated episode state for one user."""

    position: float = 0.0
    entry_vwap: float = 0.0
    isolated_collateral: float = 0.0

    def snapshot(self) -> EpisodeState:
        return EpisodeState(
            position=self.position,
            entry_vwap=self.entry_vwap,
            isolated_collateral=self.isolated_collateral,
        )


def _position_side(position: float) -> int:
    if position > POSITION_EPSILON:
        return 1
    if position < -POSITION_EPSILON:
        return -1
    return 0


def apply_btc_fill_to_episode(
    state: EpisodeState,
    fill: HlFill,
    constants: BtcMarginConstants,
) -> None:
    """Update episode state from one BTC fill (post-fill semantics)."""

    if fill.coin != "BTC":
        return

    start = float(fill.start_position)
    end = end_position_after_fill(fill.start_position, fill.side, fill.sz)
    px = float(fill.px)

    if abs(start) < POSITION_EPSILON and abs(end) >= POSITION_EPSILON:
        state.isolated_collateral += abs(end) * px / constants.max_leverage

    if abs(end) > abs(start) + POSITION_EPSILON:
        same_direction = start == 0.0 or (start > 0) == (end > 0)
        if same_direction:
            added = abs(end) - abs(start)
            if abs(start) < POSITION_EPSILON:
                state.entry_vwap = px
            else:
                state.entry_vwap = (state.entry_vwap * abs(start) + px * added) / abs(end)

    state.position = end

    if abs(end) < POSITION_EPSILON:
        state.position = 0.0
        state.entry_vwap = 0.0
        state.isolated_collateral = 0.0


def implied_liquidation_price_isolated(
    position: float,
    entry_vwap: float,
    mark: float,
    isolated_collateral: float,
    constants: BtcMarginConstants | None = None,
) -> float | None:
    """Return implied isolated liquidation price at ``mark``."""

    cfg = constants or BtcMarginConstants()
    side = _position_side(position)
    if side == 0:
        return None

    position_size = abs(position)
    unrealized_pnl = position * (mark - entry_vwap)
    equity = isolated_collateral + unrealized_pnl
    maintenance_required = position_size * mark * cfg.maintenance_margin_rate
    margin_available = equity - maintenance_required

    denominator = 1.0 - cfg.l_factor * side
    if abs(denominator) < POSITION_EPSILON:
        return None

    return mark - side * margin_available / position_size / denominator


@dataclass(frozen=True, slots=True)
class CrossImpliedResult:
    implied_price: float | None
    reason: str | None = None


def implied_liquidation_price_cross(
    position: float,
    entry_vwap: float,
    mark: float,
    account_value: float | None = None,
    constants: BtcMarginConstants | None = None,
) -> CrossImpliedResult:
    """Cross-margin reconstruction requires unobserved account value."""

    del position, entry_vwap, mark, constants
    if account_value is None:
        return CrossImpliedResult(None, CROSS_ACCOUNT_VALUE_REASON)
    return CrossImpliedResult(None, CROSS_ACCOUNT_VALUE_REASON)


def relative_error(implied: float, observed_mark_px: float) -> float:
    """Relative absolute error against observed ``markPx``."""

    if observed_mark_px == 0:
        raise ValueError("observed mark price must be non-zero")
    return abs(implied - observed_mark_px) / abs(observed_mark_px)


def is_within_tolerance(implied: float, observed: float, tol: float = 0.01) -> bool:
    """Return True when relative error is at or below ``tol``."""

    return relative_error(implied, observed) <= tol
