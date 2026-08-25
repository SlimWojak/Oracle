"""Regression checks for the sealed EXP-005 contract.

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
RESEARCH_CONTRACT = (ROOT / "RESEARCH_CONTRACT.md").read_text(encoding="utf-8")
DECISIONS = (ROOT / "docs" / "DECISIONS.md").read_text(encoding="utf-8")
LEDGER = (ROOT / "EXPERIMENT_LEDGER.md").read_text(encoding="utf-8")
GLIDE_PATH = (ROOT / "docs" / "glide_path.md").read_text(encoding="utf-8")
BRIEF = (
    ROOT / "docs" / "briefs" / "2026-08-25-exp005-flow-compression-replication.md"
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


def _markdown_section(text: str, heading: str) -> str:
    """Return one level-two Markdown section, including its heading."""
    start = text.index(heading)
    end = text.find("\n## ", start + len(heading))
    return text[start:] if end == -1 else text[start:end]


def _one_line(text: str) -> str:
    """Collapse Markdown wrapping so contract prose can be checked exactly."""
    return re.sub(r"\s+", " ", text).strip()


D037 = _markdown_section(
    DECISIONS,
    "## D-037 — Exact D-033 flow compression receives one standalone replication",
)
EXP005_LEDGER = _markdown_section(
    LEDGER,
    "## EXP-005 — Taker-flow variance-compression replication",
)


class Exp005ContractTest(unittest.TestCase):
    def assert_config(self, path: tuple[str, ...], expected: str) -> None:
        self.assertEqual(_mapping_value(CONFIG, path), expected)

    def test_closed_null_status_and_consumed_execution_are_sealed(self) -> None:
        self.assert_config(("evaluation", "status"), "exp005_complete_null")
        self.assert_config(
            ("exp005", "status"),
            "complete_null",
        )
        self.assert_config(("exp005", "decision"), "D-037")
        self.assert_config(("exp005", "exact_d033_feature"), "true")
        self.assert_config(
            ("exp005", "development_only_firewall_authorized"),
            "true",
        )
        self.assert_config(
            ("exp005", "development_only_firewall_completed"),
            "true",
        )
        self.assert_config(
            ("exp005", "oos_effect_inspection_authorized"),
            "false",
        )
        self.assertNotIn("label_effect_inspection_authorized:", CONFIG)
        self.assertIn(
            "Checkpoint A may read causal price/source inputs and availability "
            "metadata. It must not construct or inspect labels, future outcomes, "
            "validation/test scores, feature-outcome relationships, or model effects.",
            _one_line(BRIEF),
        )
        self.assertIn("NULL (closed 2026-08-25", EXP005_LEDGER)
        self.assertIn("before label/effect inspection", _one_line(D037))
        for record in (D037, EXP005_LEDGER, GLIDE_PATH):
            with self.subTest(record=record[:40]):
                self.assertIn("79851be", record)
                self.assertIn("CLEARED_CHECKPOINT_A", record)
                self.assertIn("7fa0709", record)
                self.assertIn("7ab09aa", record)
                self.assertIn("NULL", record)

    def test_exact_d033_flow_fields_windows_and_cutoff_are_sealed(self) -> None:
        expected = {
            "source": "binance_um_btcusdt_1m_klines",
            "quote_volume_field": "quote_volume",
            "taker_buy_quote_volume_field": "taker_buy_quote_volume",
            "block_minutes": "5",
            "detrend_points": "96",
            "detrend_hours": "8",
            "variance_residuals": "24",
            "variance_hours": "2",
            "variance_ddof": "0",
            "newest_block_lag_minutes": "5",
            "epsilon": "none",
            "partial_windows": "false",
            "forward_fill": "false",
        }
        for key, value in expected.items():
            with self.subTest(key=key):
                self.assert_config(("exp005", "flow_compression", key), value)

        brief = _one_line(BRIEF)
        self.assertIn("Q_s = sum(quote_volume)", brief)
        self.assertIn("B_s = sum(taker_buy_quote_volume)", brief)
        self.assertIn("S_s = Q_s - B_s", brief)
        self.assertIn("q_s = log(B_s / S_s)", brief)
        self.assertIn("96 points / 8h", brief)
        self.assertIn("24 points / 2h", brief)
        self.assertIn("population variance (`ddof=0`)", brief)
        self.assertIn("The newest block ends at `T-5m`", brief)
        self.assertIn("bar ending at `T-599m`", brief)
        self.assertIn("No epsilon, partial window, forward fill", brief)

    def test_m1_block_and_paired_common_support_cannot_regress(self) -> None:
        self.assert_config(("exp005", "m1_unchanged_blocked_asof"), "true")
        self.assert_config(
            ("exp004", "m1", "status"),
            "blocked_asof_no_publication_time",
        )
        self.assert_config(("exp004", "m1", "complete_family_required"), "true")
        self.assert_config(
            ("exp005", "rungs", "common"),
            "m0_common_exact_seven_columns",
        )
        self.assert_config(
            ("exp005", "rungs", "challenger"),
            "m0_flow_add_only_flow_compression",
        )
        self.assert_config(
            ("exp005", "rungs", "identical_timestamp_support_required"),
            "true",
        )
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

        brief = _one_line(BRIEF)
        self.assertIn("`M0_FLOW`: those same seven columns plus only", brief)
        self.assertIn("both rungs must fit on the exact same development", brief)
        self.assertIn("Any mismatch is `BLOCKED_SUPPORT`", brief)
        self.assertIn("M1 remains complete and `BLOCKED_ASOF`", brief)
        self.assertIn("does not remove flow compression from M1", RESEARCH_CONTRACT)
        self.assertIn("shrink or unblock it", _one_line(EXP005_LEDGER))

    def test_source_gates_and_execution_authority_are_frozen(self) -> None:
        self.assert_config(
            ("exp005", "source_audit", "flow_availability_floor"),
            "0.90",
        )
        self.assert_config(
            ("exp005", "source_audit", "m0_flow_joint_availability_floor"),
            "0.85",
        )
        self.assert_config(
            ("exp005", "source_audit", "zero_joint_month_allowed"),
            "false",
        )
        self.assert_config(("exp005", "one_shot_execution_consumed"), "true")
        self.assert_config(("exp005", "later_rungs_authorized"), "false")
        self.assert_config(
            ("exp005", "pre_oos_implementation_sha"),
            "7fa0709011f451d0fc5ef95b5f4b5e7baf8152ed",
        )

        for record in (BRIEF, D037, EXP005_LEDGER):
            normalized = _one_line(record)
            with self.subTest(record=record[:40]):
                self.assertRegex(normalized, r"(?:90%|0\.90).*(?:85%|0\.85)")
                self.assertRegex(
                    normalized,
                    r"no (?:zero-coverage calendar month|complete calendar month has zero)",
                )
        decision = _one_line(D037)
        self.assertIn("one exact-SHA OOS execution consumes one local receipt", decision)
        self.assertIn("does not unblock M1, authorize M2+", decision)

    def test_bounded_replication_and_mechanical_dispositions_are_preserved(
        self,
    ) -> None:
        self.assertIn("bounded operational replication", _one_line(BRIEF))
        self.assertIn("one bounded question", _one_line(D037))
        self.assertIn("operational replication", _one_line(D037))
        self.assertIn("bounded operational replication", _one_line(EXP005_LEDGER))
        self.assertIn("PASS/FAIL/NULL/BLOCKED is mechanical", _one_line(D037))

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

        brief = _one_line(BRIEF)
        ledger = _one_line(EXP005_LEDGER)
        for disposition in ("PASS", "FAIL", "NULL", "BLOCKED"):
            with self.subTest(disposition=disposition):
                self.assertIn(f"{disposition}:", brief)
                self.assertIn(disposition, ledger)
        for record in (brief, ledger):
            with self.subTest(record=record[:40]):
                self.assertIn("family relative Brier skill", record)
                self.assertRegex(record, r">=\s*(?:0\.01|1%)")
                self.assertRegex(record, r"<=\s*(?:-0\.01|-1%)")
                self.assertRegex(record, r">=\s*2x")
                self.assertRegex(record, r">=\s*(?:0\.10|10%)")
                self.assertIn("30 eligible clusters", record)
        self.assertIn("There is no pooled-period, fixed-only", brief)


if __name__ == "__main__":
    unittest.main()
