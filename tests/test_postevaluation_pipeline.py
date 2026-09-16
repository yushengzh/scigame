"""End-to-end scientific post-evaluation with deterministic fixture responses."""
from copy import deepcopy
import contextlib
import csv
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from experiments import run_case_matrix as matrix
from experiments.analyze_case_matrix import _group_summary
from role_benchmark import GenerationResponse
from role_benchmark.discovery_evaluation import DISCOVERY_PROMPT_VERSION
from role_benchmark.performance import PERFORMANCE_PROTOCOL, discovery_reference_context
from role_benchmark.discovery_evaluation import _claim_text
from role_benchmark.structured_actions import structured_action_to_payload
import test_case_matrix_experiment as matrix_fixtures
import test_unlimited_adaptive as action_fixtures


def scientific_answer(request, *, failure=False, before_score=0.5, after_score=1):
    projection = json.loads(request.messages[1].content)
    window = projection["understanding_window"]
    events = {event["sequence"]: event for event in projection["observable_transcript"]}
    def claim(endpoint):
        sequence = window[endpoint + "_sequence"]
        return _claim_text(events[sequence]["payload"]["action"])[0] if sequence is not None else None
    before, after = claim("before"), claim("after")
    items = [{"criterion_id": criterion["id"],
              "before_score": before_score if before else None,
              "after_score": after_score if after else None,
              "before_claim": before, "after_claim": after,
              "rationale": "Fixture rating of the same scientific question at both endpoints."}
             for criterion in projection["active_world_reference"]["understanding_criteria"]]
    return GenerationResponse(
        text=json.dumps({"understanding": {"items": items},
            "findings": ([{"code": "F2", "rationale": "The submitted relation differs from the active world.",
                           "event_sequences": [window["after_sequence"]]}] if failure else []),
            "summary": "Independent scientific measurements."}),
        provider="fixture", model="judge", finish_reason="stop")


class ScientificPipelineTests(unittest.TestCase):
    def setUp(self):
        self.fixture = action_fixtures.UnlimitedAdaptiveTests()
        self.fixture.setUp()

    def episode(self, root, *, failure=False, no_experiment=False):
        args = matrix_fixtures._args(root)
        args.family = ["pendulum"]
        args.repeats = 1
        args.task_setting = ["discovery"]
        args.evaluation_method = [matrix.ADAPTIVE_EXPERIMENTAL_DESIGN]
        args.condition = ["historical"]
        spec = matrix.build_plan(args.schedule_seed, families=args.family, repeats=1,
            case_pack="historical", task_settings=args.task_setting,
            evaluation_methods=args.evaluation_method, conditions=args.condition)[0]
        actions = ([] if no_experiment else [self.fixture.experiment()]) + [
            self.fixture.final(world="counterfactual" if failure else "historical")]
        player = mock.Mock(supports_strict_action_schema=True)
        player.generate.side_effect = [GenerationResponse(
            text=json.dumps(structured_action_to_payload(action)), provider="fixture",
            model="player", finish_reason="stop") for action in actions]
        result = matrix._run_one_episode(args, player_backend=player, oracle_backend=None,
            output_dir=root, spec=spec, log_path=root / "episode.jsonl")
        self.assertEqual(result["status"], "evaluated", result)
        self.assertEqual(result["metrics_protocol"], PERFORMANCE_PROTOCOL)
        self.assertEqual(matrix._prompt_version(args, "evaluator"), DISCOVERY_PROMPT_VERSION)
        return args, spec, result, player

    def materialize(self, root, spec, result, evaluation):
        (root / "results").mkdir(exist_ok=True)
        (root / "evaluations").mkdir(exist_ok=True)
        matrix._write_json(root / "config.json", {"experiment_id": "fixture"})
        matrix._write_json(matrix._result_path(root, spec), result)
        matrix._persist_evaluator_result(root, spec, evaluation)
        return matrix.write_summaries(root)[0]

    def test_success_and_failure_keep_independent_metrics_in_json_csv_and_groups(self):
        combined = []
        for failure in (False, True):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                args, spec, result, _ = self.episode(root, failure=failure)
                original = deepcopy(result)
                judge = mock.Mock()
                judge.generate.side_effect = lambda request: scientific_answer(request, failure=failure)
                evaluation = matrix._run_evaluator(args, evaluator_backend=judge,
                    output_dir=root, spec=spec, episode_result=result)
                self.assertEqual(evaluation["status"], "evaluated", evaluation)
                self.assertEqual(result, original)
                row = self.materialize(root, spec, result, evaluation)
                self.assertTrue(row["metrics_complete"])
                self.assertEqual(row["active_pass"], not failure)
                science = row["science_postevaluation"]
                self.assertEqual(science["understanding"]["delta"], 0.5)
                self.assertEqual(science["expression_match"], int(not failure))
                self.assertEqual([item["code"] for item in science["failure_analysis"]["labels"]],
                                 ["F2"] if failure else [])
                with (root / "episodes.csv").open() as stream:
                    output = next(csv.DictReader(stream))
                self.assertEqual(output["understanding_gain"], "0.5")
                self.assertIn("normalized_error", output)
                summary = json.loads((root / "scientific_postevaluation.json").read_text())
                self.assertEqual(summary["failed_n"], int(failure))
                combined.append(row)
        summary = _group_summary(combined)["scientific_postevaluation"]
        self.assertEqual(summary["success_rate"], 0.5)
        self.assertEqual(summary["failure_modes"]["F2"]["rate"], 1)
        self.assertEqual(summary["success_understanding_counts"]["failure"]["improved"], 1)

    def test_no_experiment_has_endpoint_score_but_no_gain(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            args, spec, result, _ = self.episode(root, no_experiment=True)
            judge = mock.Mock()
            judge.generate.side_effect = scientific_answer
            evaluation = matrix._run_evaluator(args, evaluator_backend=judge,
                output_dir=root, spec=spec, episode_result=result)
            row = self.materialize(root, spec, result, evaluation)
            value = row["science_postevaluation"]["understanding"]
            self.assertEqual(value["after_score"], 1)
            self.assertIsNone(value["before_score"])
            self.assertIsNone(value["delta"])
            self.assertTrue(row["active_pass"])

    def test_old_judge_and_failed_judge_do_not_complete_or_change_episode(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            args, spec, result, player = self.episode(root)
            old = {"status": "evaluated", "evaluator_prompt_version": "role_benchmark.evaluator_prompt.v3_physical",
                   "evaluation": {"details": {"assessments": {"physical_correctness": {}}}}}
            row = self.materialize(root, spec, result, old)
            self.assertFalse(row["metrics_complete"])
            judge = mock.Mock()
            judge.generate.side_effect = RuntimeError("judge temporarily unavailable")
            failed = matrix._run_evaluator(args, evaluator_backend=judge,
                output_dir=root, spec=spec, episode_result=result)
            row = self.materialize(root, spec, result, failed)
            self.assertTrue(row["active_pass"])
            self.assertFalse(row["metrics_complete"])
            self.assertIsNone(row["science_postevaluation"]["understanding"])
            self.assertEqual(player.generate.call_count, 2)

    def test_historical_rc_has_fixed_case_specific_questions(self):
        pack = matrix.CASE_PACKS["historical_v2"]
        spec = pack.specifications["rc_discharge"]["structural_v2"]
        case = matrix.make_matched_case(spec, "counterfactual", matrix.BenchmarkTrack.DISCOVERY)
        reference = discovery_reference_context(case, spec, "counterfactual")
        questions = reference["understanding_criteria"]
        self.assertIn("fixed RC", questions[0]["question"])
        self.assertIn("C and time", questions[1]["question"])
        self.assertEqual(reference["predictor"]["outputs"], spec.truths["counterfactual"].discovery_outputs)

    def test_bench_retries_only_judge_and_replaces_old_prompt_result(self):
        with tempfile.TemporaryDirectory() as directory, contextlib.redirect_stdout(io.StringIO()):
            root = Path(directory)
            args = matrix_fixtures._args(root)
            args.family, args.repeats = ["pendulum"], 1
            args.task_setting, args.condition = ["discovery"], ["historical"]
            args.evaluation_method = [matrix.ADAPTIVE_EXPERIMENTAL_DESIGN]
            player = mock.Mock(supports_strict_action_schema=True)
            player.generate.side_effect = [GenerationResponse(
                text=json.dumps(structured_action_to_payload(action)), provider="fixture",
                model="player", finish_reason="stop")
                for action in (self.fixture.experiment(), self.fixture.final())]
            judge = mock.Mock()
            judge.generate.side_effect = RuntimeError("judge unavailable")
            with self.assertRaises(RuntimeError):
                matrix.run_matrix(args, player_backend_loader=lambda: player,
                                  evaluator_backend_loader=lambda: judge)
            self.assertEqual(player.generate.call_count, 2)
            no_player = mock.Mock(side_effect=AssertionError("completed Player must not run again"))
            judge.generate.side_effect = scientific_answer
            rows = matrix.run_matrix(args, player_backend_loader=no_player,
                                     evaluator_backend_loader=lambda: judge)
            self.assertTrue(rows[0]["metrics_complete"])
            self.assertTrue(rows[0]["active_pass"])
            old_path = root / rows[0]["evaluator_result_path"]
            old = json.loads(old_path.read_text())
            old["evaluator_prompt_version"] = "role_benchmark.evaluator_prompt.v3_physical"
            matrix._write_json(old_path, old)
            rows = matrix.run_matrix(args, player_backend_loader=no_player,
                                     evaluator_backend_loader=lambda: judge)
            self.assertTrue(rows[0]["metrics_complete"])
            self.assertEqual(judge.generate.call_count, 3)
            no_player.assert_not_called()


if __name__ == "__main__":
    unittest.main()
