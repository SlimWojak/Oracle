"""Tests for EXP-001 stratification census aggregation logic."""

from __future__ import annotations

import importlib.util
import sys
import unittest
from collections import defaultdict
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SCRIPT = _REPO_ROOT / "scripts" / "run_exp001_stratification_census.py"


def _load_census_module():
    spec = importlib.util.spec_from_file_location("exp001_census", _SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["exp001_census"] = module
    spec.loader.exec_module(module)
    return module


census = _load_census_module()


class Exp001StratificationTests(unittest.TestCase):
    def test_classify_strata(self) -> None:
        self.assertEqual(
            census.classify_stratum(
                cross_asset=True,
                direction="Liquidated Cross Long",
                method="market",
            ),
            "c_cross_asset",
        )
        self.assertEqual(
            census.classify_stratum(
                cross_asset=False,
                direction="Liquidated Isolated Short",
                method="backstop",
            ),
            "a_btc_only_isolated",
        )
        self.assertEqual(
            census.classify_stratum(
                cross_asset=False,
                direction="Liquidated Cross Long",
                method="backstop",
            ),
            "b_btc_only_cross",
        )
        self.assertEqual(
            census.classify_stratum(
                cross_asset=False,
                direction="Close Long",
                method="market",
            ),
            "b_btc_only_cross",
        )
        self.assertEqual(
            census.classify_stratum(
                cross_asset=False,
                direction="Auto-Deleveraging",
                method="market",
            ),
            "other",
        )

    def test_dedupe_and_cross_asset_stratum(self) -> None:
        tracker = census.PositionTracker()
        tracker.apply_fill("0xuser", "ETH", 1000, "1.5", "B", "0.1")
        seen: set[tuple[str, int]] = set()

        counts_by_stratum: defaultdict[str, int] = defaultdict(int)
        counts_by_method: defaultdict[str, int] = defaultdict(int)
        counts_by_dir: defaultdict[str, int] = defaultdict(int)
        notional_by_stratum: defaultdict[str, float] = defaultdict(float)
        notional_by_method: defaultdict[str, float] = defaultdict(float)
        cross_by_method: defaultdict[str, census.AggregationBuckets] = defaultdict(
            census.AggregationBuckets
        )
        stratum_method_counts = census.empty_nested_counter()
        stratum_method_notional = census.empty_nested_counter()

        def liq_fill(*, tid: int, px: str, sz: str, direction: str) -> tuple[str, dict]:
            return (
                "0xuser",
                {
                    "coin": "BTC",
                    "px": px,
                    "sz": sz,
                    "side": "A",
                    "time": 2000,
                    "startPosition": "0.0",
                    "dir": direction,
                    "tid": tid,
                    "liquidation": {
                        "liquidatedUser": "0xuser",
                        "markPx": px,
                        "method": "market",
                    },
                },
            )

        fills = [
            liq_fill(tid=1, px="100", sz="1", direction="Liquidated Isolated Long"),
            liq_fill(tid=1, px="100", sz="1", direction="Liquidated Isolated Long"),
            liq_fill(tid=2, px="200", sz="0.5", direction="Liquidated Cross Long"),
        ]

        added = census.process_fill_stream(
            iter(fills),
            tracker=tracker,
            seen_keys=seen,
            counts_by_stratum=counts_by_stratum,
            counts_by_method=counts_by_method,
            counts_by_dir=counts_by_dir,
            notional_by_stratum=notional_by_stratum,
            notional_by_method=notional_by_method,
            cross_by_method=cross_by_method,
            stratum_method_counts=stratum_method_counts,
            stratum_method_notional=stratum_method_notional,
        )

        self.assertEqual(added, 2)
        self.assertEqual(counts_by_stratum["c_cross_asset"], 2)
        self.assertEqual(notional_by_stratum["c_cross_asset"], 200.0)


if __name__ == "__main__":
    unittest.main()
