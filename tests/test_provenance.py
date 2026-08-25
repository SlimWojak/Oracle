from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from oracle_research import provenance

REPO_ROOT = Path(__file__).resolve().parents[1]
KNOWN_SHA256 = "2c26b46b68ffc68ff99b453c1d30413413422d706483bfa0f98a5e886266e7ae"  # "foo"


class Sha256FileTests(unittest.TestCase):
    def test_known_digest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sample.bin"
            path.write_bytes(b"foo")
            self.assertEqual(provenance.sha256_file(path), KNOWN_SHA256)


class CanonicalConfigSha256Tests(unittest.TestCase):
    def test_digest_is_stable_across_mapping_order(self) -> None:
        first = {"threshold": 0.02, "nested": {"z": 1, "a": [2, 3]}}
        reordered = {"nested": {"a": [2, 3], "z": 1}, "threshold": 0.02}
        self.assertEqual(
            provenance.canonical_config_sha256(first),
            provenance.canonical_config_sha256(reordered),
        )
        self.assertEqual(len(provenance.canonical_config_sha256(first)), 64)


class FileEntryTests(unittest.TestCase):
    def test_name_only_without_base(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "nested" / "input.json"
            path.parent.mkdir()
            path.write_text('{"a": 1}\n', encoding="utf-8")
            entry = provenance.file_entry(path)
            self.assertEqual(entry["path"], "input.json")
            self.assertEqual(entry["bytes"], path.stat().st_size)
            self.assertEqual(len(entry["sha256"]), 64)

    def test_relative_path_with_base(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            path = base / "raw" / "data.csv"
            path.parent.mkdir()
            path.write_text("x\n", encoding="utf-8")
            entry = provenance.file_entry(path, base=base)
            self.assertEqual(entry["path"], "raw/data.csv")


class BuildProvenanceTests(unittest.TestCase):
    @patch.object(provenance, "git_commit", return_value="abc123deadbeef")
    @patch.object(provenance, "datetime")
    def test_structure(self, mock_datetime: unittest.mock.MagicMock, _mock_git: object) -> None:
        from datetime import UTC, datetime

        mock_datetime.now.return_value = datetime(2026, 8, 23, 12, 0, 0, tzinfo=UTC)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            input_path = root / "in.txt"
            output_path = root / "out.txt"
            input_path.write_text("in\n", encoding="utf-8")
            output_path.write_text("out\n", encoding="utf-8")
            record = provenance.build_provenance(
                repo_root=REPO_ROOT,
                config={"threshold": 0.02},
                inputs=[input_path],
                outputs=[output_path],
                output_base=root,
            )
            self.assertEqual(record["repo_commit"], "abc123deadbeef")
            self.assertEqual(record["generated_at_utc"], "2026-08-23T12:00:00Z")
            self.assertEqual(record["config"], {"threshold": 0.02})
            self.assertEqual(
                record["config_sha256"],
                provenance.canonical_config_sha256({"threshold": 0.02}),
            )
            self.assertEqual(len(record["inputs"]), 1)
            self.assertEqual(record["inputs"][0]["path"], "in.txt")
            self.assertEqual(record["outputs"][0]["path"], "out.txt")


class WriteProvenanceSidecarTests(unittest.TestCase):
    def test_filename_and_json_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            artifact_dir = Path(tmp)
            payload = {
                "repo_commit": "deadbeef",
                "generated_at_utc": "2026-08-23T12:00:00Z",
                "config": {"k": "v"},
                "inputs": [],
                "outputs": [],
            }
            sidecar = provenance.write_provenance_sidecar(artifact_dir, "catalogue", payload)
            self.assertEqual(sidecar.name, "catalogue.provenance.json")
            text = sidecar.read_text(encoding="utf-8")
            self.assertTrue(text.endswith("\n"))
            self.assertEqual(json.loads(text), payload)


if __name__ == "__main__":
    unittest.main()
