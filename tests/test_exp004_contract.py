"""Regression checks for the frozen EXP-004 contract.

These tests intentionally use only the standard library.  They validate the
small, deterministic YAML subset in ``configs/v0.yaml`` without making PyYAML a
test dependency.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONFIG = (ROOT / "configs" / "v0.yaml").read_text(encoding="utf-8")
P5_BRIEF = (
    ROOT / "docs" / "briefs" / "2026-08-25-p5-eval-unit.md"
).read_text(encoding="utf-8")
P6_BRIEF = (
    ROOT / "docs" / "briefs" / "2026-08-25-p6-implementation-freeze.md"
).read_text(encoding="utf-8")
P4_BRIEF = (
    ROOT / "docs" / "briefs" / "2026-08-25-p1-impact-construct.md"
).read_text(encoding="utf-8")
P4_SOURCE_REPORT = (
    ROOT / "reports" / "exp003" / "source_readiness.json"
).read_text(encoding="utf-8")


def _mapping_value(text: str, path: tuple[str, ...]) -> str:
    """Return a scalar from the indentation-based mapping subset used here."""
    parents: list[tuple[int, str]] = []
    for raw_line in text.splitlines():
        match = re.fullmatch(r"( *)([A-Za-z0-9_]+):(?: +(.*))?", raw_line)
        if match is None:
            continue
        indent = len(match.group(1))
        while parents and parents[-1][0] >= indent:
            parents.pop()
        key = match.group(2)
        value = match.group(3)
        current_path = tuple(item[1] for item in parents) + (key,)
        if current_path == path:
            if value is None:
                raise AssertionError(f"{'.'.join(path)} is not a scalar")
            return value
        if value is None:
            parents.append((indent, key))
    raise AssertionError(f"missing config path: {'.'.join(path)}")


def _list_items(text: str, path: tuple[str, ...]) -> list[str]:
    """Return scalar list items directly below a mapping path."""
    lines = text.splitlines()
    parents: list[tuple[int, str]] = []
    for index, raw_line in enumerate(lines):
        match = re.fullmatch(r"( *)([A-Za-z0-9_]+):(?: +(.*))?", raw_line)
        if match is None:
            continue
        indent = len(match.group(1))
        while parents and parents[-1][0] >= indent:
            parents.pop()
        key = match.group(2)
        value = match.group(3)
        current_path = tuple(item[1] for item in parents) + (key,)
        if current_path == path:
            if value is not None:
                raise AssertionError(f"{'.'.join(path)} is not a block list")
            item_indent = indent + 2
            items: list[str] = []
            for candidate in lines[index + 1 :]:
                if not candidate.strip():
                    continue
                candidate_indent = len(candidate) - len(candidate.lstrip(" "))
                if candidate_indent <= indent:
                    break
                item_match = re.fullmatch(
                    rf" {{{item_indent}}}- +([^#]+?)(?: +#.*)?", candidate
                )
                if item_match is not None:
                    items.append(item_match.group(1).strip())
            return items
        if value is None:
            parents.append((indent, key))
    raise AssertionError(f"missing config path: {'.'.join(path)}")


class Exp004ContractTest(unittest.TestCase):
    def assert_config(self, path: tuple[str, ...], expected: str) -> None:
        self.assertEqual(_mapping_value(CONFIG, path), expected)

    def test_source_grid_and_prospective_risk_clock_stay_distinct(self) -> None:
        self.assert_config(("labels", "source_grid_seconds"), "60")
        self.assert_config(("sampling", "risk_clock_seconds"), "3600")
        self.assert_config(("sampling", "risk_clock_phase"), "utc_hour_end")
        self.assertIn("at every\n  UTC clock hour", P5_BRIEF)
        self.assertIn("not the EXP-004 sampling frame", P5_BRIEF)

    def test_twin_impulse_and_competing_risks_are_frozen(self) -> None:
        self.assert_config(
            ("labels", "volatility_normalized", "status"), "accepted_d032"
        )
        self.assert_config(
            ("labels", "volatility_normalized", "common_support_with_fixed"),
            "true",
        )
        self.assert_config(
            ("sampling", "precondition_impulse", "lookback_seconds"), "900"
        )
        self.assert_config(
            ("sampling", "precondition_impulse", "rule"),
            "abs_log_close_return_strictly_below",
        )
        self.assert_config(
            ("sampling", "precondition_impulse", "threshold"), "log_1.005"
        )
        self.assertIn("i_T < log(1.005)", P5_BRIEF)
        self.assertIn("Equality is excluded", P5_BRIEF)
        self.assertIn("`{UP, DOWN, NONE}`", P6_BRIEF)
        self.assertIn("competing event, not censoring", P6_BRIEF)
        self.assert_config(
            ("labels", "fixed_first_passage", "outcome"),
            "competing_first_cause_up_down_none",
        )

    def test_historical_stop_is_retained_and_m0_execution_is_consumed(self) -> None:
        self.assert_config(("exp004", "status"), "m0_complete_null_m1_blocked_asof")
        self.assert_config(("exp004", "implementation_authorized"), "true")
        self.assert_config(("exp004", "execution_authorization_consumed"), "true")
        self.assert_config(("exp004", "authorized_rung"), "none_m0_completed")
        self.assert_config(("exp004", "later_rungs_authorized"), "false")
        self.assert_config(("exp004", "m0", "status"), "complete_null")
        self.assert_config(
            ("exp004", "m0", "pre_oos_implementation_sha"),
            "680f2af101f88b55e761945390f6da020c9e9a71",
        )
        self.assertIn("P6 is not\nauthorized", P5_BRIEF)
        self.assertIn("EXP-004 remains PLANNED and unscored", P6_BRIEF)
        self.assertIn("No fitting. No scoring.", P5_BRIEF)
        self.assertIn("Do not implement or score EXP-004 / P6.", P5_BRIEF)
        self.assertIn("Do not fit a probability model or alert threshold.", P5_BRIEF)
        self.assertIn("Do not implement feature builders", P6_BRIEF)

    def test_exact_m0_and_m1_feature_identifiers(self) -> None:
        self.assertEqual(
            _list_items(CONFIG, ("exp004", "m0", "features")),
            [
                "trailing_4h_signed_log_return",
                "trailing_4h_log_high_low_range",
                "causal_24h_realized_volatility",
                "utc_hour_sin",
                "utc_hour_cos",
                "utc_weekday_sin",
                "utc_weekday_cos",
            ],
        )
        self.assertEqual(
            _list_items(CONFIG, ("exp004", "m1", "features")),
            [
                "binance_um_oi_notional_log_level_lag_5m",
                "binance_um_realized_funding_24h_sum_lag_5m",
                "binance_um_vs_spot_log_close_premium",
                "binance_um_taker_flow_variance_compression",
            ],
        )
        self.assert_config(
            ("exp004", "m1", "status"), "blocked_asof_no_publication_time"
        )
        self.assert_config(("exp004", "m1", "complete_family_required"), "true")

    def test_estimator_and_disposition_thresholds_are_fixed(self) -> None:
        self.assert_config(
            ("exp004", "estimator", "family"),
            "baseline_category_multinomial_logistic",
        )
        self.assert_config(("exp004", "estimator", "reference_cause"), "none")
        self.assert_config(("exp004", "estimator", "l2_lambda"), "0.0001")
        expected = {
            "family_relative_brier_skill_pass": "0.01",
            "family_relative_brier_skill_fail": "-0.01",
            "precision_multiple_of_cell_base_rate": "2.0",
            "cluster_recall": "0.10",
            "median_lead_seconds_1h": "900",
            "median_lead_seconds_4h": "3600",
            "minimum_primary_cell_clusters_for_pass": "30",
            "periods_and_label_families_must_all_pass": "true",
        }
        for key, value in expected.items():
            with self.subTest(key=key):
                self.assert_config(("evaluation", "dispositions", key), value)
        self.assertIn("There is no pooled-period rescue", P6_BRIEF)
        self.assertIn("EXP-004 receives none of these model", P6_BRIEF)

    def test_news_and_challenger_dispositions_do_not_regress(self) -> None:
        self.assert_config(
            ("exp004", "slices", "news"),
            "news_not_available_non_gating_m0_m1",
        )
        self.assertIn("This is non-gating for M0/M1 only", P6_BRIEF)
        self.assert_config(
            (
                "feature_families",
                "fuel",
                "challengers",
                "hyperliquid_observed",
                "status",
            ),
            "demoted_realized_mass_only",
        )
        self.assert_config(
            (
                "feature_families",
                "fuel",
                "challengers",
                "cex_oi_cohort_v0",
                "status",
            ),
            "parked_null_no_retry",
        )
        self.assert_config(
            (
                "feature_families",
                "fuel",
                "challengers",
                "vendor_model",
                "status",
            ),
            "unavailable_no_verified_asof_history",
        )

    def test_blocked_impact_work_and_stale_config_forms_are_rejected(self) -> None:
        self.assert_config(
            ("feature_families", "impact_susceptibility", "status"),
            "exp003_blocked_source_pre_effect",
        )
        self.assert_config(
            ("feature_families", "ignition", "status"), "unauthorized"
        )
        self.assertIn("EXP-003 / P4 remains deferred", P5_BRIEF)
        self.assertIn("implementation freeze v4", P4_BRIEF)
        self.assertIn('"status": "BLOCKED_SOURCE"', P4_SOURCE_REPORT)
        self.assertIn('"eligibility_census": "NOT_RUN_SOURCE_BLOCK"', P4_SOURCE_REPORT)
        self.assertIn('"correlations_calculated": false', P4_SOURCE_REPORT)
        self.assertNotIn("decision_required", CONFIG)
        self.assertNotIn("status: provisional", CONFIG)
        self.assertNotRegex(CONFIG, r"(?m)^\s+challengers:\s*\n\s+- ")


if __name__ == "__main__":
    unittest.main()
