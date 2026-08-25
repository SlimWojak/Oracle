from __future__ import annotations

import ast
import csv
import hashlib
import importlib.util
import io
import json
import math
import sys
import tempfile
import unittest
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np

from oracle_research.exp005_flow import FlowFeatureResult, HourlyPeriod


def load_audit_module():
    script_path = Path(__file__).resolve().parents[1] / "scripts" / "audit_exp005_source.py"
    spec = importlib.util.spec_from_file_location("audit_exp005_source", script_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"unable to load module from {script_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


audit = load_audit_module()


def timestamp(text: str) -> int:
    return int(datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp())


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_zip(path: Path, rows: list[list[object]], *, header: bool = False) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    if header:
        writer.writerow(audit.KLINE_FIELDS)
    writer.writerows(rows)
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(f"{path.stem}.csv", buffer.getvalue())
    return path


def kline_row(interval_end: int, q_value: float) -> list[object]:
    quote = 20.0
    ratio = math.exp(q_value)
    buy = quote * ratio / (1.0 + ratio)
    open_time_ms = (interval_end - 60) * 1_000
    return [
        open_time_ms,
        100.0,
        101.0,
        99.0,
        100.0,
        1.0,
        interval_end * 1_000 - 1,
        quote,
        1,
        buy / 100.0,
        buy,
        0,
    ]


def complete_flow_rows(decision_timestamp: int) -> list[list[object]]:
    rows: list[list[object]] = []
    first_block_end = decision_timestamp - 595 * 60
    for block_index in range(119):
        q_value = 0.2 * math.sin(block_index / 5.0) + block_index * 0.0003
        block_end = first_block_end + block_index * 300
        for offset in (-240, -180, -120, -60, 0):
            rows.append(kline_row(block_end + offset, q_value))
    return rows


class ManifestSelectionTests(unittest.TestCase):
    def test_production_identity_set_is_exactly_79_um_months(self) -> None:
        identities = audit.expected_um_archive_identities()
        self.assertEqual(len(identities), 79)
        self.assertTrue(
            all("futures/um/monthly/klines/BTCUSDT/1m" in row.relative_path for row in identities)
        )
        self.assertTrue(identities[0].relative_path.endswith("2020-01.zip"))
        self.assertTrue(identities[-1].relative_path.endswith("2026-07.zip"))

    def test_nonselected_full_manifest_records_are_ignored_but_selected_hash_is_verified(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            relative = "futures/um/monthly/klines/BTCUSDT/1m/selected.zip"
            archive_path = write_zip(
                root / "raw" / "binance_vision" / relative,
                [kline_row(timestamp("2024-02-01T00:01:00Z"), 0.1)],
            )
            manifest_path = root / audit.MANIFEST_IDENTIFIER
            manifest_path.parent.mkdir(parents=True, exist_ok=True)
            selected = {
                "relative_path": relative,
                "status": "downloaded",
                "size_bytes": archive_path.stat().st_size,
                "sha256": sha256(archive_path),
                "retrieved_at": "2026-08-25T00:00:00Z",
            }
            unrelated = {
                "relative_path": "spot/monthly/klines/BTCUSDT/1m/unrelated.zip",
                "status": "downloaded",
                "size_bytes": 123,
                "sha256": "0" * 64,
                "retrieved_at": "2026-08-25T00:00:00Z",
            }
            manifest_path.write_text(
                json.dumps(selected) + "\n" + json.dumps(unrelated) + "\n",
                encoding="utf-8",
            )
            report, paths = audit.verify_um_manifest(
                data_root=root,
                identities=[audit.ArchiveIdentity(relative)],
            )
            self.assertEqual(paths, [archive_path])
            self.assertEqual(report["selected_integrity_valid"], 1)
            self.assertEqual(report["nonselected_manifest_records_ignored"], 1)
            self.assertFalse(report["exact_selected_identity_set"])

            archive_path.write_bytes(b"changed")
            failed, _ = audit.verify_um_manifest(
                data_root=root,
                identities=[audit.ArchiveIdentity(relative)],
            )
            self.assertEqual(failed["failures"][0]["reason"], "size_mismatch")


class RawSourceAuditTests(unittest.TestCase):
    def test_identical_duplicate_collapses_and_conflicting_duplicate_is_missing(self) -> None:
        decision = timestamp("2024-02-12T12:00:00Z")
        base_rows = complete_flow_rows(decision)
        duplicate = list(base_rows[20])
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            identical_path = write_zip(root / "identical.zip", base_rows + [duplicate])
            result, report = audit.audit_um_archives([identical_path], [decision])
            self.assertIn(decision, result.values)
            self.assertEqual(report["duplicates"]["duplicate_rows"], 1)
            self.assertEqual(report["duplicates"]["identical_duplicate_timestamps"], 1)
            self.assertEqual(report["duplicates"]["conflicting_timestamps"], 0)

            conflict = list(duplicate)
            conflict[10] = float(conflict[10]) + 0.25
            conflict_path = write_zip(root / "conflict.zip", base_rows + [conflict])
            conflicted, report = audit.audit_um_archives([conflict_path], [decision])
            self.assertNotIn(decision, conflicted.values)
            self.assertEqual(report["duplicates"]["conflicting_timestamps"], 1)
            self.assertEqual(
                conflicted.aligned_five_minute_census["reason_counts"]["CONFLICT_MINUTE"],
                1,
            )

            whitespace = list(duplicate)
            whitespace[7] = f" {whitespace[7]}"
            whitespace_path = write_zip(root / "whitespace.zip", base_rows + [whitespace])
            whitespace_result, report = audit.audit_um_archives(
                [whitespace_path], [decision]
            )
            self.assertNotIn(decision, whitespace_result.values)
            self.assertEqual(report["duplicates"]["conflicting_timestamps"], 1)

    def test_schema_epoch_interval_and_noncausal_close_are_reported_exactly(self) -> None:
        decision = timestamp("2024-02-12T12:00:00Z")
        rows = complete_flow_rows(decision)
        rows[-1][6] = decision * 1_000 + 1
        with tempfile.TemporaryDirectory() as tmp:
            path = write_zip(Path(tmp) / "with_header.zip", rows, header=True)
            result, report = audit.audit_um_archives([path], [decision])
        self.assertNotIn(decision, result.values)
        self.assertEqual(report["schema"]["valid_rows"], 595)
        self.assertEqual(report["schema"]["invalid_rows"], 0)
        self.assertEqual(report["epoch_units"], {"epoch_ms": 595})
        self.assertTrue(report["epoch_unit_contract_pass"])
        self.assertEqual(report["raw_close_time"]["after_nominal_end"], 1)


class D022SourceVerificationTests(unittest.TestCase):
    def test_source_inputs_are_verified_without_reading_manifest_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = root / "repo"
            data = root / "data"
            source = data / "raw" / "one.bin"
            source.parent.mkdir(parents=True, exist_ok=True)
            source.write_bytes(b"source-only")
            manifest = repo / audit.D022_MANIFEST_IDENTIFIER
            manifest.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                "repo_commit": "abc123",
                "config": {
                    "members": [
                        "binance_btcusdt_spot",
                        "kraken_xbtusd_spot",
                        "coinbase_btcusd_spot",
                    ],
                    "min_members": 2,
                    "construction": "componentwise_median",
                    "decision_timestamp": "interval_end",
                    "bars_start": "2020-01-01T00:00:00Z",
                    "kraken_csvs": list(audit.KRAKEN_FILES),
                },
                "inputs": [
                    {
                        "path": "raw/one.bin",
                        "bytes": source.stat().st_size,
                        "sha256": sha256(source),
                    }
                ],
                "outputs": [
                    {
                        "path": "forbidden_future_effect.json",
                        "bytes": 999,
                        "sha256": "f" * 64,
                    }
                ],
            }
            manifest.write_text(json.dumps(payload), encoding="utf-8")
            report = audit.verify_d022_source_inputs(
                data_root=data,
                repo_root=repo,
                enforce_loader_identity=False,
            )
        self.assertTrue(report["all_inputs_verified"])
        self.assertFalse(report["effect_artifact_outputs_read"])
        self.assertEqual(report["verified_input_count"], 1)


class WriterAndFirewallTests(unittest.TestCase):
    def synthetic_index(self, decision: int):
        starts = np.arange(decision - 86_400 - 60, decision, 60, dtype=np.int64)
        phase = np.arange(starts.size, dtype=np.float64)
        close = 100.0 * np.exp(phase * 0.00001 + 0.0002 * np.sin(phase / 17.0))
        klines = SimpleNamespace(
            timestamp=starts,
            close=close,
            high=close * 1.001,
            low=close * 0.999,
            n_rows=starts.size,
        )
        return SimpleNamespace(klines=klines, venue_count=np.full(starts.size, 3, dtype=np.int8))

    def test_build_and_writer_emit_support_hashes_and_d019_outputs(self) -> None:
        decision = timestamp("2024-02-12T12:00:00Z")
        period = HourlyPeriod(
            "SYNTHETIC",
            datetime.fromtimestamp(decision, tz=UTC),
            datetime.fromtimestamp(decision, tz=UTC),
        )
        flow = FlowFeatureResult(
            values={decision: 1.25},
            aligned_five_minute_census={
                "candidate_blocks": 119,
                "structurally_valid_blocks": 119,
                "q_valid_blocks": 119,
                "reason_counts": {"VALID_Q": 119},
            },
            hourly_feature_census={"candidate_hours": 1, "valid_hours": 1, "reasons": {}},
        )
        source_report = audit.SourceStats()
        source_report.archives_read = 79
        source_report.rows = 1
        source_report.schema_valid_rows = 1
        source_report.timestamp_units["epoch_ms"] = 1
        source_dict = source_report.as_dict()
        manifest_report = {
            "identifier": audit.MANIFEST_IDENTIFIER,
            "selected_integrity_valid": 79,
            "expected_selected_identities": 79,
            "exact_selected_identity_set": True,
            "nonselected_manifest_records_ignored": 1883,
            "selected_archive_identities_sha256": "a" * 64,
        }
        d022_report = {
            "all_inputs_verified": True,
            "ordered_input_identity_sha256": "b" * 64,
        }
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            data = root / "data"
            repo = root / "repo"
            output = root / "reports" / "exp005"
            (data / audit.MANIFEST_IDENTIFIER).parent.mkdir(parents=True, exist_ok=True)
            (data / audit.MANIFEST_IDENTIFIER).write_text("{}\n", encoding="utf-8")
            (repo / audit.D022_MANIFEST_IDENTIFIER).parent.mkdir(parents=True, exist_ok=True)
            (repo / audit.D022_MANIFEST_IDENTIFIER).write_text("{}", encoding="utf-8")
            with (
                patch.object(
                    audit,
                    "verify_um_manifest",
                    return_value=(
                        manifest_report,
                        [Path(f"archive-{index}") for index in range(79)],
                    ),
                ),
                patch.object(audit, "audit_um_archives", return_value=(flow, source_dict)),
                patch.object(audit, "verify_d022_source_inputs", return_value=d022_report),
                patch.object(audit, "load_d022_index", return_value=self.synthetic_index(decision)),
                patch("oracle_research.provenance.git_commit", return_value="c" * 40),
            ):
                json_path, markdown_path, provenance_path = audit.write_audit(
                    data_root=data,
                    output_dir=output,
                    repo_root=repo,
                    identities=audit.expected_um_archive_identities(),
                    periods=[period],
                )
            payload = json.loads(json_path.read_text(encoding="utf-8"))
            provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
            markdown = markdown_path.read_text(encoding="utf-8")
        self.assertEqual(payload["checkpoint_a_disposition"], "CLEARED_CHECKPOINT_A")
        paired = payload["availability"]["periods"]["SYNTHETIC"]["paired_rung_support"]
        self.assertTrue(paired["identical"])
        self.assertEqual(len(paired["m0_common_ordered_support_sha256"]), 64)
        self.assertEqual(
            {entry["path"] for entry in provenance["outputs"]},
            {json_path.name, markdown_path.name},
        )
        self.assertEqual(len(provenance["ordered_support_hashes"]["SYNTHETIC"]["joint"]), 64)
        self.assertNotIn(str(data), json.dumps(provenance))
        self.assertIn("D-022 source/index and exact M0 verification", markdown)
        self.assertIn("Exact M0 columns", markdown)

    def test_um_integrity_requires_nonempty_exact_79_ms_archives_and_rows(self) -> None:
        manifest = {
            "exact_selected_identity_set": True,
            "selected_integrity_valid": 79,
        }
        paths = [Path(f"archive-{index}") for index in range(79)]
        empty = audit.SourceStats().as_dict()
        self.assertFalse(
            audit._um_source_integrity_clear(  # noqa: SLF001 - pure audit gate
                manifest=manifest,
                archive_paths=paths,
                source_report=empty,
            )
        )
        stats = audit.SourceStats()
        stats.archives_read = 79
        stats.rows = 1
        stats.schema_valid_rows = 1
        stats.timestamp_units["epoch_ms"] = 1
        self.assertTrue(
            audit._um_source_integrity_clear(  # noqa: SLF001 - pure audit gate
                manifest=manifest,
                archive_paths=paths,
                source_report=stats.as_dict(),
            )
        )
        self.assertFalse(
            audit._um_source_integrity_clear(  # noqa: SLF001 - pure audit gate
                manifest=manifest,
                archive_paths=paths[:-1],
                source_report=stats.as_dict(),
            )
        )

    def test_auditor_has_no_forbidden_research_imports_or_calls(self) -> None:
        repo = Path(__file__).resolve().parents[1]
        forbidden_modules = {
            "oracle_research.batch_labels",
            "oracle_research.labels",
            "oracle_research.exp004_m0_population",
            "oracle_research.exp004_m0_model",
            "oracle_research.exp004_m0_evaluation",
            "oracle_research.clusters",
        }
        for relative in (
            "src/oracle_research/exp005_flow.py",
            "scripts/audit_exp005_source.py",
        ):
            tree = ast.parse((repo / relative).read_text(encoding="utf-8"))
            imported: set[str] = set()
            called: set[str] = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and node.module:
                    imported.add(node.module)
                elif isinstance(node, ast.Import):
                    imported.update(alias.name for alias in node.names)
                elif isinstance(node, ast.Call):
                    if isinstance(node.func, ast.Name):
                        called.add(node.func.id)
                    elif isinstance(node.func, ast.Attribute):
                        called.add(node.func.attr)
            self.assertTrue(imported.isdisjoint(forbidden_modules), relative)
            self.assertTrue(
                called.isdisjoint({"build_population", "first_cause", "fit_m0", "evaluate_m0"}),
                relative,
            )


if __name__ == "__main__":
    unittest.main()
