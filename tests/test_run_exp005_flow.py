from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import patch


def _load_runner() -> ModuleType:
    script = Path(__file__).resolve().parents[1] / "scripts" / "run_exp005_flow.py"
    spec = importlib.util.spec_from_file_location("test_subject_run_exp005_flow", script)
    if spec is None or spec.loader is None:
        raise RuntimeError("could not load EXP-005 runner")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


runner = _load_runner()


def _state(sha256: str = "state-sha") -> SimpleNamespace:
    return SimpleNamespace(sha256=sha256, to_dict=lambda: {"sha256": sha256})


def _population(cutoff: int) -> SimpleNamespace:
    row = SimpleNamespace(
        timestamp=cutoff - 3,
        period="development",
        outcomes={"fixed": SimpleNamespace(passage_timestamp=cutoff - 2)},
    )
    cluster = SimpleNamespace(start_timestamp=cutoff - 4, end_timestamp=cutoff - 1)
    return SimpleNamespace(rows=[row], clusters=[cluster])


def _full_fixture(root: Path) -> tuple[SimpleNamespace, dict[str, object], object, dict]:
    args = SimpleNamespace(
        expected_sha="seal-sha",
        expected_envelope_sha="envelope-sha",
        out_dir=root / "out",
        state_dir=root / "state",
        data_root=root / "data",
    )
    envelope = {
        "development_implementation": {"commit": "development-sha", "tree": "tree-sha"},
        "banked_checkpoint_a": {"checkpoint": "banked"},
        "replayed_pre_effect_sources": {"support": "same"},
        "frozen_state_sha256": "state-sha",
        "runtime": runner._runtime(),
    }
    index = SimpleNamespace(
        klines=SimpleNamespace(close=[1.0], high=[1.0], low=[1.0])
    )
    replay = {
        "summary": {"support": "same"},
        "index": index,
        "end_timestamps": runner.np.asarray([1], dtype=runner.np.int64),
        "flow_values": {1: 0.1},
    }
    return args, envelope, _state(), replay


class ArgumentTests(unittest.TestCase):
    def test_stage_arguments_are_mutually_constrained(self) -> None:
        development = runner.parse_args(
            ["--stage", "development", "--data-root", "data", "--state-dir", "state"]
        )
        self.assertEqual(development.stage, "development")
        self.assertIsNone(development.expected_sha)
        self.assertIsNone(development.out_dir)

        full = runner.parse_args(
            [
                "--stage",
                "full",
                "--data-root",
                "data",
                "--state-dir",
                "state",
                "--out-dir",
                "out",
                "--expected-sha",
                "seal-sha",
                "--expected-envelope-sha",
                "envelope-sha",
            ]
        )
        self.assertEqual(full.stage, "full")

        invalid = (
            [
                "--stage",
                "development",
                "--data-root",
                "data",
                "--state-dir",
                "state",
                "--expected-sha",
                "seal-sha",
            ],
            [
                "--stage",
                "full",
                "--data-root",
                "data",
                "--state-dir",
                "state",
                "--out-dir",
                "out",
            ],
        )
        for argv in invalid:
            with (
                self.subTest(argv=argv),
                contextlib.redirect_stderr(io.StringIO()),
                self.assertRaises(SystemExit),
            ):
                runner.parse_args(argv)


class DevelopmentFirewallTests(unittest.TestCase):
    def test_cluster_filter_is_strict_and_preserves_payload_order(self) -> None:
        cutoff = 100
        parameters = {"link_gap_seconds": 42, "directions": ["UP", "DOWN"]}
        payload = {
            "parameters": parameters,
            "horizons": [
                {
                    "horizon_seconds": 7_200,
                    "name": "first",
                    "clusters": [
                        {"id": "keep-a", "start_timestamp": 1, "end_timestamp": 2},
                        {"id": "drop-start", "start_timestamp": cutoff, "end_timestamp": 2},
                        {
                            "id": "drop-end",
                            "start_timestamp": cutoff - 1,
                            "end_timestamp": cutoff,
                        },
                        {"id": "keep-b", "start_timestamp": 3, "end_timestamp": 4},
                    ],
                },
                {
                    "horizon_seconds": 3_600,
                    "name": "second",
                    "clusters": [],
                },
            ],
        }

        filtered, counts = runner.filter_development_clusters(payload, cutoff=cutoff)

        self.assertEqual(filtered["parameters"], parameters)
        self.assertIsNot(filtered["parameters"], parameters)
        self.assertEqual(
            [block["horizon_seconds"] for block in filtered["horizons"]],
            [7_200, 3_600],
        )
        self.assertEqual(
            [cluster["id"] for cluster in filtered["horizons"][0]["clusters"]],
            ["keep-a", "keep-b"],
        )
        self.assertEqual(filtered["horizons"][0]["name"], "first")
        self.assertEqual(counts["7200"]["retained"], 2)

    def test_all_development_objects_must_be_strictly_before_cutoff(self) -> None:
        cutoff = 100
        report = runner.development_firewall(
            end_timestamps=runner.np.asarray([cutoff - 5, cutoff - 1]),
            flow_values={cutoff - 1: 0.1},
            population=_population(cutoff),
            cutoff=cutoff,
        )
        self.assertEqual(report["cutoff_exclusive"], cutoff)
        self.assertFalse(report["oos_outcomes_or_effects_constructed"])

        for boundary in ("source", "flow", "row", "passage", "cluster-start", "cluster-end"):
            population = _population(cutoff)
            timestamps = runner.np.asarray([cutoff - 1])
            flow_values = {cutoff - 1: 0.1}
            if boundary == "source":
                timestamps = runner.np.asarray([cutoff])
            elif boundary == "flow":
                flow_values = {cutoff: 0.1}
            elif boundary == "row":
                population.rows[0].timestamp = cutoff
            elif boundary == "passage":
                population.rows[0].outcomes["fixed"].passage_timestamp = cutoff
            elif boundary == "cluster-start":
                population.clusters[0].start_timestamp = cutoff
            else:
                population.clusters[0].end_timestamp = cutoff
            with self.subTest(boundary=boundary), self.assertRaises(runner.RunIntegrityError):
                runner.development_firewall(
                    end_timestamps=timestamps,
                    flow_values=flow_values,
                    population=population,
                    cutoff=cutoff,
                )


class EnvelopeAndReceiptTests(unittest.TestCase):
    def test_receipt_is_one_constant_exclusive_path_across_shas(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data_root = Path(tmp)
            receipt = runner.create_consumption_receipt(
                data_root,
                expected_sha="first-sha",
                tree="first-tree",
                development_sha="development-sha",
                frozen_state_sha256="state-sha",
                envelope_sha256="envelope-sha",
            )
            with self.assertRaises(FileExistsError):
                runner.create_consumption_receipt(
                    data_root,
                    expected_sha="different-sha",
                    tree="different-tree",
                    development_sha="different-development",
                    frozen_state_sha256="different-state",
                    envelope_sha256="different-envelope",
                )

            payload = json.loads(receipt.read_text(encoding="utf-8"))
            self.assertEqual(receipt.name, runner.RECEIPT_FILENAME)
            self.assertEqual(payload["pre_oos_sha"], "first-sha")

    def test_envelope_load_rejects_any_unsigned_tamper(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state_dir = Path(tmp)
            envelope = {
                "schema_version": runner.SCHEMA_VERSION,
                "experiment": "EXP-005",
                "stage": "DEVELOPMENT_ONLY_FIREWALL",
                "frozen_state_sha256": "state-sha",
                "frozen_state": {"small": "synthetic"},
            }
            envelope["envelope_payload_sha256"] = runner._payload_sha256(envelope)
            path = state_dir / runner.STATE_FILENAME
            path.write_text(runner._pretty_json(envelope), encoding="utf-8")

            with patch.object(runner.FrozenFlowState, "from_dict", return_value=_state()):
                loaded, state, file_sha = runner.load_frozen_envelope(state_dir)
                self.assertEqual(loaded, envelope)
                self.assertEqual(state.sha256, "state-sha")
                self.assertEqual(file_sha, runner.sha256_file(path))

                envelope["stage"] = "TAMPERED"
                path.write_text(runner._pretty_json(envelope), encoding="utf-8")
                with self.assertRaises(runner.RunIntegrityError):
                    runner.load_frozen_envelope(state_dir)


class SealedCheckoutTests(unittest.TestCase):
    @staticmethod
    def _git(values: dict[str, str]):
        def fake_git(*args: str, **_kwargs) -> str:
            key = " ".join(args)
            return values[key]

        return fake_git

    def test_exact_parent_tree_empty_commit_and_clean_checkout_are_required(self) -> None:
        base = {
            "rev-parse HEAD": "seal-sha",
            "rev-parse HEAD^{tree}": "tree-sha",
            "status --porcelain=v1 --untracked-files=all": "",
            "rev-parse seal-sha^": "development-sha",
            "diff --name-only development-sha seal-sha": "",
        }
        envelope = {
            "development_implementation": {
                "commit": "development-sha",
                "tree": "tree-sha",
            }
        }
        with patch.object(runner, "_git", side_effect=self._git(base)):
            snapshot = runner.require_sealed_checkout("seal-sha", envelope)
        self.assertEqual(snapshot, {"commit": "seal-sha", "tree": "tree-sha", "clean": True})

        failures = {
            "exact-sha": {"rev-parse HEAD": "other-sha"},
            "clean": {"status --porcelain=v1 --untracked-files=all": "?? untracked"},
            "parent": {"rev-parse seal-sha^": "other-parent"},
            "tree": {"rev-parse HEAD^{tree}": "other-tree"},
            "empty": {"diff --name-only development-sha seal-sha": "changed.py"},
        }
        for condition, changes in failures.items():
            values = {**base, **changes}
            with self.subTest(condition=condition), patch.object(
                runner, "_git", side_effect=self._git(values)
            ), self.assertRaises(runner.RunIntegrityError):
                runner.require_sealed_checkout("seal-sha", envelope)


class FullRunOrderingTests(unittest.TestCase):
    def test_pre_effect_replay_mismatch_precedes_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            args, envelope, state, replay = _full_fixture(Path(tmp))
            replay["summary"] = {"support": "mismatch"}
            with (
                patch.object(
                    runner, "load_frozen_envelope", return_value=(envelope, state, "envelope-sha")
                ),
                patch.object(
                    runner,
                    "require_sealed_checkout",
                    return_value={"commit": "seal-sha", "tree": "tree-sha", "clean": True},
                ),
                patch.object(
                    runner,
                    "banked_checkpoint_identity",
                    return_value={"checkpoint": "banked"},
                ),
                patch.object(runner, "replay_pre_effect_sources", return_value=replay),
                patch.object(runner, "create_consumption_receipt") as receipt,
                self.assertRaises(runner.RunIntegrityError),
            ):
                runner._full_run(args)
            receipt.assert_not_called()

    def test_full_success_consumes_before_population_and_evaluates_without_fit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            args, envelope, state, replay = _full_fixture(root)
            events: list[str] = []

            def consume(*_args, **_kwargs):
                events.append("receipt")
                return root / "receipt.json"

            def build(*_args, **_kwargs):
                events.append("population")
                return "population"

            def evaluate(*_args, **_kwargs):
                events.append("evaluate")
                return {"disposition": "NULL", "periods": {}}

            with (
                patch.object(
                    runner, "load_frozen_envelope", return_value=(envelope, state, "envelope-sha")
                ),
                patch.object(
                    runner,
                    "require_sealed_checkout",
                    return_value={"commit": "seal-sha", "tree": "tree-sha", "clean": True},
                ),
                patch.object(
                    runner,
                    "banked_checkpoint_identity",
                    return_value={"checkpoint": "banked"},
                ),
                patch.object(runner, "replay_pre_effect_sources", return_value=replay),
                patch.object(runner, "create_consumption_receipt", side_effect=consume),
                patch.object(runner, "sha256_file", return_value="artifact-sha"),
                patch.object(runner, "_read_json", return_value={"clusters": "synthetic"}),
                patch.object(runner, "build_population", side_effect=build),
                patch.object(runner, "build_flow_population", return_value="paired"),
                patch.object(runner, "evaluate_flow_models", side_effect=evaluate) as evaluation,
                patch.object(runner, "fit_flow_models") as fit,
                patch.object(runner, "_write_evidence", return_value=root / "result.json"),
                patch.object(runner, "_finish_consumed") as finish,
                contextlib.redirect_stdout(io.StringIO()),
            ):
                status = runner._full_run(args)

            self.assertEqual(status, 0)
            self.assertLess(events.index("receipt"), events.index("population"))
            self.assertLess(events.index("population"), events.index("evaluate"))
            evaluation.assert_called_once_with("paired", state)
            fit.assert_not_called()
            finish.assert_called_once()

    def test_post_receipt_failure_is_consumed_and_cannot_retry(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            args, envelope, state, replay = _full_fixture(root)
            with (
                patch.object(
                    runner, "load_frozen_envelope", return_value=(envelope, state, "envelope-sha")
                ),
                patch.object(
                    runner,
                    "require_sealed_checkout",
                    return_value={"commit": "seal-sha", "tree": "tree-sha", "clean": True},
                ),
                patch.object(
                    runner,
                    "banked_checkpoint_identity",
                    return_value={"checkpoint": "banked"},
                ),
                patch.object(runner, "replay_pre_effect_sources", return_value=replay),
                patch.object(runner, "sha256_file", return_value="artifact-sha"),
                patch.object(
                    runner,
                    "_read_json",
                    side_effect=runner.RunIntegrityError("synthetic post-receipt failure"),
                ) as read_clusters,
                patch.object(runner, "_write_evidence", return_value=root / "result.json"),
                patch.object(runner, "_finish_consumed") as finish,
                contextlib.redirect_stdout(io.StringIO()),
            ):
                self.assertEqual(runner._full_run(args), 2)
                receipt = args.data_root / runner.RECEIPT_DIRECTORY / runner.RECEIPT_FILENAME
                self.assertTrue(receipt.exists())
                with self.assertRaises(FileExistsError):
                    runner._full_run(args)

            read_clusters.assert_called_once()
            finish.assert_called_once()


if __name__ == "__main__":
    unittest.main()
