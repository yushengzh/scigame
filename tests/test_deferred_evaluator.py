"""Collect API trajectories first, then judge their sealed logs independently."""

import contextlib
import io
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest import mock

from experiments import postevaluate_science as post
from experiments import run_case_matrix as matrix
from role_benchmark import GenerationResponse, load_run_log
from role_benchmark.structured_actions import structured_action_to_payload
import test_postevaluation_pipeline as judge_fixtures
import test_unlimited_adaptive as action_fixtures


class DeferredEvaluatorTests(unittest.TestCase):
    def setUp(self):
        self.actions = action_fixtures.UnlimitedAdaptiveTests()
        self.actions.setUp()

    def args(self, directory, *, workers=1, repeats=1, deferred=True):
        arguments = [
            "--output-dir", str(directory), "--experiment-id", "EXP-DEFERRED-TEST",
            "--case-pack", "historical", "--family", "pendulum",
            "--condition", "historical", "--task-setting", "discovery",
            "--evaluation-method", "fixed experimental design (4 observations)",
            "--repeats", str(repeats), "--workers", str(workers),
            "--player-provider", "openai", "--player-model", "player-model",
            "--player-endpoint", "https://player.invalid/v1/responses",
            "--player-api-key-env", "PLAYER_TEST_KEY",
            "--evaluator-provider", "gemini", "--evaluator-model", "unused-judge",
            "--evaluator-api-key-env", "ABSENT_EVALUATOR_TEST_KEY",
        ]
        if deferred:
            arguments.append("--defer-evaluator")
        return matrix._parser().parse_args(arguments)

    def player(self, barrier=None):
        response = GenerationResponse(
            text=json.dumps(structured_action_to_payload(self.actions.final())),
            provider="openai", model="player-model", finish_reason="stop",
        )
        backend = mock.Mock(supports_strict_action_schema=True)

        def answer(request):
            if barrier is not None:
                barrier.wait(timeout=5)
            return response

        backend.generate.side_effect = answer
        return backend

    def collect(self, args, player):
        def credential(options, role):
            self.assertEqual(role, "player", "Collection must not request a Judge key")
            self.assertEqual(options.player_api_key_env, "PLAYER_TEST_KEY")
            return "synthetic-player-key"

        def build(runtime, key, **kwargs):
            self.assertEqual(runtime.role, "player", "Collection must not initialize a Judge")
            self.assertEqual(key, "synthetic-player-key")
            return player

        with contextlib.redirect_stdout(io.StringIO()), \
                mock.patch.object(matrix, "_resolve_api_key", side_effect=credential) as keys, \
                mock.patch.object(matrix, "_build_backend", side_effect=build) as builders, \
                mock.patch.object(matrix, "_run_evaluator", side_effect=AssertionError("No Judge calls")):
            rows = matrix.run_matrix(args)
        self.assertEqual(keys.call_count, 1)
        self.assertEqual(builders.call_count, 1)
        return rows

    @staticmethod
    def source_bytes(directory):
        return {str(path.relative_to(directory)): path.read_bytes()
                for path in directory.rglob("*") if path.is_file()}

    def test_collection_is_explicit_and_resume_needs_no_generation_serial_or_parallel(self):
        for workers in (1, 2):
            with self.subTest(workers=workers), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                args = self.args(root, workers=workers, repeats=2)
                # A barrier also detects accidental serial execution of the parallel mode.
                player = self.player(threading.Barrier(2) if workers == 2 else None)
                rows = self.collect(args, player)
                self.assertEqual(len(rows), 2)
                self.assertEqual(player.generate.call_count, 2)
                self.assertEqual(list((root / "evaluations").glob("*.evaluation.json")), [])
                config = json.loads((root / "config.json").read_text())
                self.assertEqual(config["evaluator_generation"], {"mode": "deferred", "llm_calls": 0})
                self.assertEqual(config["execution"]["role_concurrency_limits"]["evaluator"], 0)
                for row in rows:
                    self.assertEqual(row["status"], "evaluated")
                    self.assertTrue(row["active_pass"])
                    self.assertEqual(row["formula_consistency"]["status"], "equivalent")
                    self.assertEqual(row["evaluator_mode"], "deferred")
                    self.assertEqual(row["llm_evaluation_status"], "deferred")
                    self.assertIsNone(row["evaluator_model"])
                    self.assertFalse(row["metrics_complete"])
                    self.assertIsNone(row["science_postevaluation"]["understanding"])
                    path = Path(row["log_path"])
                    path = path if path.is_absolute() else root / path
                    self.assertTrue(load_run_log(str(path)).complete)
                before = self.source_bytes(root)
                with contextlib.redirect_stdout(io.StringIO()), \
                        mock.patch.object(matrix, "_resolve_api_key", side_effect=AssertionError("No keys on resume")), \
                        mock.patch.object(matrix, "load_role_backend", side_effect=AssertionError("No backends on resume")), \
                        mock.patch.object(matrix, "_run_one_episode", side_effect=AssertionError("No Player rerun")), \
                        mock.patch.object(matrix, "_run_evaluator", side_effect=AssertionError("No Judge retry")):
                    repeated = matrix.run_matrix(args)
                self.assertEqual(repeated, rows)
                self.assertEqual(self.source_bytes(root), before)

    def test_later_api_judge_uses_independent_settings_and_preserves_source(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, output = root / "source", root / "post"
            original = self.collect(self.args(source), self.player())[0]
            source_before = self.source_bytes(source)
            options = post._parser().parse_args([
                "--run-dir", str(source), "--output-dir", str(output), "--judge",
                "--evaluator-provider", "ifm", "--evaluator-model", "separate-judge",
                "--evaluator-endpoint", "https://judge.invalid/v1/chat/completions",
                "--evaluator-api-key-env", "SEPARATE_JUDGE_KEY",
                "--evaluator-reasoning-effort", "medium",
                "--evaluator-max-output-tokens", "4096", "--evaluator-timeout-s", "45",
            ])
            judge = mock.Mock()
            judge.generate.side_effect = judge_fixtures.scientific_answer

            def credential(args, role):
                self.assertEqual(role, "evaluator")
                self.assertEqual(args.evaluator_api_key_env, "SEPARATE_JUDGE_KEY")
                self.assertEqual(args.evaluator_max_output_tokens, 4096)
                return "synthetic-judge-key"

            def build(runtime, key, **kwargs):
                self.assertEqual(runtime.role, "evaluator")
                self.assertEqual(runtime.provider, "ifm")
                self.assertEqual(runtime.model, "separate-judge")
                self.assertEqual(runtime.endpoint, "https://judge.invalid/v1/chat/completions")
                self.assertEqual(runtime.reasoning_effort, "medium")
                self.assertEqual(runtime.timeout_s, 45)
                self.assertEqual(key, "synthetic-judge-key")
                return judge

            with mock.patch.object(matrix, "_resolve_api_key", side_effect=credential) as keys, \
                    mock.patch.object(matrix, "_build_backend", side_effect=build) as builders, \
                    mock.patch.object(matrix, "_run_one_episode", side_effect=AssertionError("Reuse the source log")):
                rows = post.run_postevaluation(options)
            self.assertEqual(keys.call_count, 1)
            self.assertEqual(builders.call_count, 1)
            self.assertEqual(judge.generate.call_count, 1)
            self.assertEqual(rows[0]["run_id"], original["run_id"])
            self.assertEqual(rows[0]["active_pass"], original["active_pass"])
            self.assertEqual(rows[0]["source_evaluator_mode"], "deferred")
            self.assertEqual(rows[0]["llm_evaluation_status"], "evaluated")
            self.assertEqual(rows[0]["evaluator_provider"], "ifm")
            self.assertEqual(rows[0]["evaluator_model"], "separate-judge")
            self.assertTrue(rows[0]["metrics_complete"], rows[0])
            self.assertEqual(self.source_bytes(source), source_before)
            with mock.patch.object(matrix, "_resolve_api_key", side_effect=AssertionError("No key on Judge resume")), \
                    mock.patch.object(matrix, "load_role_backend", side_effect=AssertionError("No Judge regeneration")):
                repeated = post.run_postevaluation(options)
            self.assertEqual(repeated[0]["science_postevaluation"], rows[0]["science_postevaluation"])
            self.assertEqual(self.source_bytes(source), source_before)

    def test_deferred_judge_keeps_semantic_oracle_calls_during_collection(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            args = self.args(root)
            args.evaluation_method = [matrix.ADAPTIVE_EXPERIMENTAL_DESIGN]
            args.oracle_mode = matrix.LLM_SEMANTIC_ORACLE
            args.oracle_provider, args.oracle_model = "gemini", "oracle-model"
            player = mock.Mock(supports_strict_action_schema=True)
            player.generate.side_effect = [GenerationResponse(
                text=json.dumps(structured_action_to_payload(action)),
                provider="openai", model="player-model", finish_reason="stop",
            ) for action in (self.actions.experiment(), self.actions.final())]
            oracle = mock.Mock()
            oracle.generate.return_value = GenerationResponse(
                text=json.dumps({"status": "VALID", "reason": "", "constraint_ids": []}),
                provider="gemini", model="oracle-model", finish_reason="stop",
            )

            def credential(options, role):
                self.assertIn(role, ("player", "oracle"))
                return "synthetic-" + role + "-key"

            def build(runtime, key, **kwargs):
                self.assertIn(runtime.role, ("player", "oracle"))
                self.assertEqual(key, "synthetic-" + runtime.role + "-key")
                return {"player": player, "oracle": oracle}[runtime.role]

            with contextlib.redirect_stdout(io.StringIO()), \
                    mock.patch.object(matrix, "_resolve_api_key", side_effect=credential) as keys, \
                    mock.patch.object(matrix, "_build_backend", side_effect=build) as builders, \
                    mock.patch.object(matrix, "_run_evaluator", side_effect=AssertionError("No Judge calls")):
                rows = matrix.run_matrix(args)
            self.assertEqual({call.args[1] for call in keys.call_args_list}, {"player", "oracle"})
            self.assertEqual({call.args[0].role for call in builders.call_args_list}, {"player", "oracle"})
            self.assertEqual(player.generate.call_count, 2)
            self.assertEqual(oracle.generate.call_count, 1)
            request = oracle.generate.call_args.args[0]
            self.assertEqual(request.metadata["purpose"], "validate_experiment")
            self.assertTrue(rows[0]["active_pass"], rows[0])
            self.assertEqual(rows[0]["attempts_used"], 1)
            self.assertEqual(rows[0]["oracle_llm_stats"]["generation_calls"], 1)
            self.assertEqual(rows[0]["llm_evaluation_status"], "deferred")
            self.assertEqual(list((root / "evaluations").glob("*.evaluation.json")), [])

    def test_completed_generation_failure_without_final_can_be_judged_later(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            player = mock.Mock(supports_strict_action_schema=True)
            player.generate.return_value = GenerationResponse(
                text="malformed response", provider="openai", model="player-model",
                finish_reason="stop",
            )
            original = self.collect(self.args(source), player)[0]
            self.assertEqual(original["status"], "evaluated")
            self.assertFalse(original["active_pass"])
            self.assertEqual(original["formula_consistency"]["status"], "unavailable")
            self.assertEqual(original["llm_evaluation_status"], "deferred")
            before = self.source_bytes(source)
            options = post._parser().parse_args([
                "--run-dir", str(source), "--output-dir", str(root / "post"), "--judge",
            ])
            judge = mock.Mock()
            judge.generate.side_effect = judge_fixtures.scientific_answer
            with mock.patch.object(matrix, "_run_one_episode", side_effect=AssertionError("Do not repair Player output")):
                rows = post.run_postevaluation(options, evaluator_backend_loader=lambda: judge)
            self.assertEqual(judge.generate.call_count, 1)
            self.assertEqual(rows[0]["run_id"], original["run_id"])
            self.assertFalse(rows[0]["active_pass"])
            self.assertEqual(rows[0]["llm_evaluation_status"], "evaluated", rows[0])
            understanding = rows[0]["science_postevaluation"]["understanding"]
            self.assertEqual(understanding["status"], "unmeasured")
            self.assertIsNone(understanding["before_score"])
            self.assertIsNone(understanding["after_score"])
            self.assertEqual(self.source_bytes(source), before)

    def test_deferred_collection_does_not_hide_formula_infrastructure_failure(self):
        for workers in (1, 2):
            with self.subTest(workers=workers), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                args = self.args(root, workers=workers)
                with mock.patch.object(matrix, "_formula_result", return_value={
                        "status": "infrastructure_failed", "error_type": "FixtureFormulaError"}):
                    with self.assertRaises(RuntimeError):
                        self.collect(args, self.player())
                rows = matrix.load_episode_results(root)
                self.assertEqual(len(rows), 1)
                self.assertEqual(rows[0]["status"], "evaluated")
                self.assertEqual(rows[0]["formula_consistency"]["status"], "infrastructure_failed")
                self.assertEqual(list((root / "evaluations").glob("*.evaluation.json")), [])

    def test_without_flag_evaluation_remains_immediate(self):
        with tempfile.TemporaryDirectory() as directory:
            args = self.args(Path(directory), deferred=False)
            self.assertFalse(args.defer_evaluator)
            player, judge = self.player(), mock.Mock()
            judge.generate.side_effect = judge_fixtures.scientific_answer
            with contextlib.redirect_stdout(io.StringIO()):
                rows = matrix.run_matrix(
                    args, player_backend_loader=lambda: player,
                    evaluator_backend_loader=lambda: judge,
                )
            self.assertEqual(player.generate.call_count, 1)
            self.assertEqual(judge.generate.call_count, 1)
            self.assertEqual(rows[0]["llm_evaluation_status"], "evaluated")
            self.assertTrue(rows[0]["metrics_complete"], rows[0])


if __name__ == "__main__":
    unittest.main()
