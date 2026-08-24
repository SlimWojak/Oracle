import unittest

from oracle_research.hl_liq_reconstruction import (
    BtcMarginConstants,
    EpisodeState,
    apply_btc_fill_to_episode,
    implied_liquidation_price_cross,
    implied_liquidation_price_isolated,
    is_within_tolerance,
    relative_error,
)
from oracle_research.hyperliquid_fills import HlFill

USER = "0xaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"


def make_fill(
    *,
    user: str = USER,
    coin: str = "BTC",
    px: str = "50000.0",
    sz: str = "0.1",
    side: str = "B",
    time_ms: int = 1_000,
    start_position: str = "0",
    dir: str = "Open Long",
) -> HlFill:
    return HlFill(
        user=user,
        coin=coin,
        px=px,
        sz=sz,
        side=side,
        time_ms=time_ms,
        start_position=start_position,
        dir=dir,
        hash="0xabc",
        oid=1,
        crossed=True,
        tid=1,
        fee="0",
        fee_token="USDC",
    )


class BtcMarginConstantsTests(unittest.TestCase):
    def test_tier0_rates(self) -> None:
        cfg = BtcMarginConstants()
        self.assertEqual(cfg.max_leverage, 40.0)
        self.assertEqual(cfg.initial_margin_rate, 0.025)
        self.assertEqual(cfg.maintenance_margin_rate, 0.0125)
        self.assertAlmostEqual(cfg.l_factor, 1.0 / 80.0)


class EpisodeStateTests(unittest.TestCase):
    def test_open_from_zero_allocates_collateral_and_vwap(self) -> None:
        state = EpisodeState()
        apply_btc_fill_to_episode(
            state,
            make_fill(start_position="0", side="B"),
            BtcMarginConstants(),
        )
        self.assertAlmostEqual(state.position, 0.1)
        self.assertAlmostEqual(state.entry_vwap, 50000.0)
        self.assertAlmostEqual(state.isolated_collateral, 0.1 * 50000.0 / 40.0)

    def test_increase_updates_vwap(self) -> None:
        state = EpisodeState(position=0.1, entry_vwap=50000.0, isolated_collateral=125.0)
        apply_btc_fill_to_episode(
            state,
            make_fill(start_position="0.1", px="51000.0", sz="0.1", side="B"),
            BtcMarginConstants(),
        )
        self.assertAlmostEqual(state.position, 0.2)
        self.assertAlmostEqual(state.entry_vwap, 50500.0)

    def test_flat_position_resets_episode(self) -> None:
        state = EpisodeState(position=0.1, entry_vwap=50000.0, isolated_collateral=125.0)
        apply_btc_fill_to_episode(
            state,
            make_fill(start_position="0.1", sz="0.1", side="A"),
            BtcMarginConstants(),
        )
        self.assertEqual(state.position, 0.0)
        self.assertEqual(state.entry_vwap, 0.0)
        self.assertEqual(state.isolated_collateral, 0.0)


class ImpliedLiquidationPriceTests(unittest.TestCase):
    def test_isolated_long_matches_formula(self) -> None:
        cfg = BtcMarginConstants()
        position = 1.0
        entry = 50000.0
        mark = 50000.0
        collateral = position * entry / cfg.max_leverage
        implied = implied_liquidation_price_isolated(position, entry, mark, collateral, cfg)
        self.assertIsNotNone(implied)
        side = 1
        margin_available = collateral - abs(position) * mark * cfg.maintenance_margin_rate
        expected = mark - side * margin_available / abs(position) / (1 - cfg.l_factor * side)
        self.assertAlmostEqual(implied, expected)

    def test_cross_returns_unobserved(self) -> None:
        result = implied_liquidation_price_cross(1.0, 50000.0, 50000.0)
        self.assertIsNone(result.implied_price)
        self.assertEqual(result.reason, "account_value_unobserved")


class ErrorMetricTests(unittest.TestCase):
    def test_relative_error_and_tolerance(self) -> None:
        self.assertAlmostEqual(relative_error(100.5, 100.0), 0.005)
        self.assertTrue(is_within_tolerance(100.5, 100.0))
        self.assertFalse(is_within_tolerance(102.0, 100.0))


if __name__ == "__main__":
    unittest.main()
