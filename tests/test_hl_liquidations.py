import unittest

from oracle_research.hl_liquidations import (
    PositionTracker,
    btc_only_at_time,
    extract_btc_liquidation_events,
    stratify_event,
)
from oracle_research.hyperliquid_fills import HlFill

LIQUIDATED = "0xaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
COUNTERPARTY = "0xbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
LIQ = {
    "liquidatedUser": LIQUIDATED,
    "markPx": "50000.0",
    "method": "market",
}


def make_fill(
    *,
    user: str = LIQUIDATED,
    tid: int = 100,
    coin: str = "BTC",
    time_ms: int = 1_000,
    start_position: str = "-0.5",
    dir: str = "Liquidated Cross Short",
    side: str = "A",
    sz: str = "0.2",
    liquidation: dict[str, str] | None = LIQ,
) -> HlFill:
    return HlFill(
        user=user,
        coin=coin,
        px="50000.0",
        sz=sz,
        side=side,
        time_ms=time_ms,
        start_position=start_position,
        dir=dir,
        hash="0xabc",
        oid=1,
        crossed=True,
        tid=tid,
        fee="1.0",
        fee_token="USDC",
        liquidation=liquidation,
    )


class ExtractBtcLiquidationEventsTests(unittest.TestCase):
    def test_dedupes_liquidated_user_leg_only(self) -> None:
        fills = [
            make_fill(user=LIQUIDATED, tid=42),
            make_fill(user=COUNTERPARTY, tid=42, side="B"),
            make_fill(user=LIQUIDATED, tid=43, dir="Liquidated Isolated Long"),
        ]
        events = extract_btc_liquidation_events(fills)
        self.assertEqual(len(events), 2)
        self.assertEqual({event.tid for event in events}, {42, 43})
        self.assertTrue(all(event.user == event.liquidated_user for event in events))
        self.assertEqual(events[0].usd_notional, 10_000.0)

    def test_ignores_non_btc_and_non_liquidation_fills(self) -> None:
        fills = [
            make_fill(user=LIQUIDATED, coin="ETH"),
            make_fill(user=LIQUIDATED, liquidation=None),
        ]
        self.assertEqual(extract_btc_liquidation_events(fills), [])


class PositionTrackerTests(unittest.TestCase):
    def test_tracks_last_end_position_at_or_before_time(self) -> None:
        tracker = PositionTracker()
        tracker.update(
            make_fill(user=LIQUIDATED, coin="ETH", start_position="1.0", time_ms=100, side="B")
        )
        tracker.update(
            make_fill(user=LIQUIDATED, coin="ETH", start_position="1.5", time_ms=200, side="B")
        )
        self.assertEqual(tracker.start_position_at(LIQUIDATED, "ETH", 150), "1.2")
        self.assertEqual(tracker.start_position_at(LIQUIDATED, "ETH", 200), "1.7")
        self.assertIsNone(tracker.start_position_at(LIQUIDATED, "ETH", 50))

    def test_btc_only_requires_no_other_coin_exposure(self) -> None:
        tracker = PositionTracker()
        tracker.update(make_fill(user=LIQUIDATED, coin="BTC", start_position="-1", time_ms=100))
        tracker.update(
            make_fill(
                user=LIQUIDATED,
                coin="ETH",
                start_position="0.000000001",
                time_ms=100,
                side="A",
                sz="0.000000001",
                liquidation=None,
            )
        )
        positions = tracker.coin_positions_at(LIQUIDATED, 100)
        self.assertTrue(btc_only_at_time(LIQUIDATED, 100, positions))

        tracker.update(make_fill(user=LIQUIDATED, coin="ETH", start_position="0.1", time_ms=200))
        positions = tracker.coin_positions_at(LIQUIDATED, 300)
        self.assertFalse(btc_only_at_time(LIQUIDATED, 300, positions))


class StratifyEventTests(unittest.TestCase):
    def test_stratum_a_isolated_btc_only(self) -> None:
        event = extract_btc_liquidation_events(
            [make_fill(dir="Liquidated Isolated Long", tid=1)]
        )[0]
        self.assertEqual(stratify_event(event, is_btc_only=True), "a")

    def test_stratum_b_cross_btc_only(self) -> None:
        event = extract_btc_liquidation_events([make_fill(tid=2)])[0]
        self.assertEqual(stratify_event(event, is_btc_only=True), "b")

    def test_stratum_b_market_close_btc_only(self) -> None:
        event = extract_btc_liquidation_events(
            [make_fill(dir="Close Long", tid=4, side="A")]
        )[0]
        self.assertEqual(stratify_event(event, is_btc_only=True), "b")

    def test_stratum_c_non_btc_only(self) -> None:
        event = extract_btc_liquidation_events([make_fill(tid=3)])[0]
        self.assertEqual(stratify_event(event, is_btc_only=False), "c")

    def test_end_to_end_stratification_with_tracker(self) -> None:
        tracker = PositionTracker()
        tracker.update(make_fill(user=LIQUIDATED, coin="BTC", time_ms=900, tid=10))
        tracker.update(
            make_fill(
                user=LIQUIDATED,
                coin="ETH",
                time_ms=950,
                start_position="2.0",
                tid=11,
                liquidation=None,
            )
        )
        isolated = extract_btc_liquidation_events(
            [make_fill(time_ms=1000, dir="Liquidated Isolated Short", tid=12)]
        )[0]
        cross = extract_btc_liquidation_events([make_fill(time_ms=1000, tid=13)])[0]

        self.assertEqual(
            stratify_event(
                isolated,
                is_btc_only=btc_only_at_time(
                    LIQUIDATED,
                    1000,
                    tracker.coin_positions_at(LIQUIDATED, 1000),
                ),
            ),
            "c",
        )
        tracker.update(
            make_fill(
                user=LIQUIDATED,
                coin="ETH",
                time_ms=980,
                start_position="2.0",
                side="A",
                sz="2.0",
                tid=14,
                liquidation=None,
            )
        )
        positions = tracker.coin_positions_at(LIQUIDATED, 1000)
        is_btc_only = btc_only_at_time(LIQUIDATED, 1000, positions)
        self.assertEqual(stratify_event(isolated, is_btc_only=is_btc_only), "a")
        self.assertEqual(stratify_event(cross, is_btc_only=is_btc_only), "b")


if __name__ == "__main__":
    unittest.main()
