from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import run_exp004_m0


class ArgumentTests(unittest.TestCase):
    def test_development_rejects_oos_arguments(self) -> None:
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            run_exp004_m0.parse_args(
                [
                    "--data-root",
                    "/tmp/data",
                    "--stage",
                    "development",
                    "--out-dir",
                    "/tmp/out",
                    "--expected-sha",
                    "0" * 40,
                ]
            )

    def test_full_requires_sha(self) -> None:
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            run_exp004_m0.parse_args(
                [
                    "--data-root",
                    "/tmp/data",
                    "--stage",
                    "full",
                    "--out-dir",
                    "/tmp/out",
                ]
            )


class FrozenCheckoutTests(unittest.TestCase):
    @patch.object(run_exp004_m0, "_git")
    def test_exact_clean_sha_is_required(self, git) -> None:
        sha = "a" * 40
        git.side_effect = [sha, ""]
        run_exp004_m0.require_frozen_checkout(sha)
        git.assert_any_call("status", "--porcelain", "--untracked-files=all")

    @patch.object(run_exp004_m0, "_git", return_value="b" * 40)
    def test_mismatched_sha_blocks(self, _git) -> None:
        with self.assertRaises(RuntimeError):
            run_exp004_m0.require_frozen_checkout("a" * 40)


class OneShotTests(unittest.TestCase):
    def test_receipt_creation_is_exclusive(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            receipt = run_exp004_m0._create_one_shot_receipt(directory, "a" * 40)
            payload = json.loads(receipt.read_text(encoding="utf-8"))
            self.assertEqual(payload["status"], "STARTED_CONSUMED")
            with self.assertRaises(FileExistsError):
                run_exp004_m0._create_one_shot_receipt(directory, "a" * 40)


if __name__ == "__main__":
    unittest.main()
