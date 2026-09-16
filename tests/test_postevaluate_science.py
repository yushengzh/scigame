"""Post-evaluation reuses completed episodes and calls only the missing judge."""

from copy import deepcopy
import csv
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from experiments import postevaluate_science as post
from experiments import run_case_matrix as matrix
from role_benchmark import GenerationResponse
from role_benchmark.discovery_evaluation import DISCOVERY_PROMPT_VERSION
from role_benchmark.discovery_evaluation import _claim_text
from role_benchmark.structured_actions import structured_action_to_payload
import test_case_matrix_experiment as matrix_fixtures
import test_unlimited_adaptive as action_fixtures


class PostevaluateScienceTests(unittest.TestCase):
    def source(self, root):
        source = root / "source"
        source.mkdir()
        (source / "results").mkdir()
        (source / "episodes").mkdir()
        (source / "evaluations").mkdir()
        args = matrix_fixtures._args(source)
        spec = matrix.build_plan(args.schedule_seed, families=["pendulum"], repeats=1,
                                 case_pack="historical", task_settings=["discovery"],
                                 evaluation_methods=[matrix.FIXED_EXPERIMENTAL_DESIGN],
                                 conditions=["historical"])[0]
        fixture = action_fixtures.UnlimitedAdaptiveTests()
        fixture.setUp()
        player = mock.Mock(supports_strict_action_schema=True)
        player.generate.return_value = GenerationResponse(
            text=json.dumps(structured_action_to_payload(fixture.final())), provider="test", model="source-player", finish_reason="stop")
        # The stored result intentionally refers to a resume-named log.
        row = matrix._run_one_episode(args, player_backend=player, oracle_backend=None,
                                      output_dir=source, spec=spec,
                                      log_path=source / "episodes" / (spec.episode_id + ".resume-1.jsonl"))
        self.assertEqual(row["status"], "evaluated", row)
        row.pop("metrics_protocol", None)  # Historical source predates the current metrics.
        matrix._write_json(matrix._result_path(source, spec), row)
        matrix._write_json(source / "config.json", {"experiment_id": row["experiment_id"], "original": True})
        return source, spec, row

    def options(self, source, output, judge=False):
        arguments = ["--run-dir", str(source), "--output-dir", str(output)]
        if judge:
            arguments.append("--judge")
        return post._parser().parse_args(arguments)

    @staticmethod
    def answer(request):
        projection = json.loads(request.messages[1].content)
        window = projection["understanding_window"]
        events = {event["sequence"]: event for event in projection["observable_transcript"]}
        after = events[window["after_sequence"]]["payload"]["action"]
        quote = next(text for text in _claim_text(after) if text.strip())
        payload = {"understanding": {"items": [
            {"criterion_id": criterion["id"], "before_score": None,
             "after_score": 0.5, "before_claim": None, "after_claim": quote,
             "rationale": "The recorded final scientific statement provides partial content."}
            for criterion in projection["active_world_reference"]["understanding_criteria"]]},
            "findings": [], "summary": "Only the final endpoint is available in this fixed-observation episode."}
        return GenerationResponse(text=json.dumps(payload), provider="test", model="judge", finish_reason="stop")

    def test_offline_formula_and_summary_leave_source_unchanged(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, spec, original = self.source(root)
            before = {str(path.relative_to(source)): path.read_bytes() for path in source.rglob("*") if path.is_file()}
            with mock.patch.object(matrix, "load_role_backend") as loader:
                rows = post.run_postevaluation(self.options(source, root / "post"))
            loader.assert_not_called()
            self.assertEqual(rows[0]["active_pass"], original["active_pass"])
            self.assertEqual(rows[0]["formula_consistency"]["status"], "equivalent")
            self.assertEqual(rows[0]["source_metrics_protocol"], "legacy")
            self.assertEqual(rows[0]["llm_evaluation_status"], "pending")
            self.assertIsNone(rows[0]["science_postevaluation"]["understanding"])
            self.assertTrue(Path(rows[0]["log_path"]).is_absolute())
            self.assertIn("resume-1", rows[0]["log_path"])
            after = {str(path.relative_to(source)): path.read_bytes() for path in source.rglob("*") if path.is_file()}
            self.assertEqual(before, after)

    def test_judge_only_then_resume_makes_no_new_call_and_preserves_missing_before(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, _, _ = self.source(root)
            options = self.options(source, root / "post", judge=True)
            judge = mock.Mock()
            judge.generate.side_effect = self.answer
            with mock.patch.object(matrix, "load_role_backend", wraps=matrix.load_role_backend) as loader, \
                    mock.patch.object(matrix, "_run_one_episode") as player_runner:
                rows = post.run_postevaluation(options, evaluator_backend_loader=lambda: judge)
                player_runner.assert_not_called()
                self.assertEqual([call.args[1] for call in loader.call_args_list], ["evaluator"])
            self.assertEqual(judge.generate.call_count, 1)
            self.assertTrue(rows[0]["metrics_complete"], rows[0])
            measured = rows[0]["science_postevaluation"]["understanding"]
            self.assertEqual(measured["status"], "final_only")
            self.assertIsNone(measured["before_score"])
            self.assertIsNone(measured["delta"])
            with mock.patch.object(matrix, "load_role_backend") as loader:
                repeated = post.run_postevaluation(options)
            loader.assert_not_called()
            self.assertEqual(repeated[0]["science_postevaluation"], rows[0]["science_postevaluation"])

    def test_matching_successful_current_sidecar_is_reused_without_backend(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, spec, row = self.source(root)
            options = self.options(source, root / "post")
            judge = mock.Mock()
            judge.generate.side_effect = self.answer
            sidecar = matrix._run_evaluator(post._judge_args(options, spec.case_pack),
                                            evaluator_backend=judge, output_dir=source,
                                            spec=spec, episode_result=row)
            self.assertEqual(sidecar["status"], "evaluated", sidecar)
            self.assertEqual(sidecar["evaluator_prompt_version"], DISCOVERY_PROMPT_VERSION)
            matrix._persist_evaluator_result(source, spec, sidecar)
            with mock.patch.object(matrix, "load_role_backend") as loader:
                rows = post.run_postevaluation(options)
            loader.assert_not_called()
            self.assertTrue(rows[0]["metrics_complete"])

    def test_old_judge_is_not_relabelled_as_new_understanding(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, spec, row = self.source(root)
            matrix._persist_evaluator_result(source, spec,
                {"episode_id": spec.episode_id, "run_id": row["run_id"], "status": "evaluated",
                 "evaluator_prompt_version": "role_benchmark.evaluator_prompt.v3_physical",
                 "evaluation": {"scores": {}, "details": {"assessments": {}}}})
            rows = post.run_postevaluation(self.options(source, root / "post"))
            self.assertEqual(rows[0]["llm_evaluation_status"], "pending")
            self.assertFalse(rows[0]["metrics_complete"])

    def test_explicit_new_judge_model_replaces_reuse_and_is_reported_in_json_csv(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, spec, row = self.source(root)
            row["evaluator_model"] = "judge-A"
            matrix._write_json(matrix._result_path(source, spec), row)
            old_options = self.options(source, root / "post")
            old_options.evaluator_model = "judge-A"
            old_judge = mock.Mock()
            old_judge.generate.side_effect = self.answer
            sidecar = matrix._run_evaluator(post._judge_args(old_options, spec.case_pack),
                                            evaluator_backend=old_judge, output_dir=source,
                                            spec=spec, episode_result=row)
            matrix._persist_evaluator_result(source, spec, sidecar)
            # First populate the separate view with an existing successful A result.
            reused = post.run_postevaluation(old_options)
            self.assertEqual(reused[0]["evaluator_model"], "judge-A")
            new_options = self.options(source, root / "post", judge=True)
            new_options.evaluator_model = "judge-B"
            new_judge = mock.Mock()
            new_judge.generate.side_effect = self.answer
            rows = post.run_postevaluation(new_options, evaluator_backend_loader=lambda: new_judge)
            self.assertEqual(new_judge.generate.call_count, 1)
            self.assertEqual(rows[0]["evaluator_model"], "judge-B")
            self.assertEqual(rows[0]["source_evaluator_model"], "judge-A")
            saved = json.loads((root / "post" / "episodes.json").read_text())["episodes"][0]
            self.assertEqual(saved["evaluator_model"], "judge-B")
            with (root / "post" / "episodes.csv").open(newline="") as stream:
                csv_row = next(csv.DictReader(stream))
            self.assertEqual(csv_row["evaluator_model"], "judge-B")
            with mock.patch.object(matrix, "load_role_backend") as loader:
                post.run_postevaluation(new_options)
            loader.assert_not_called()
            self.assertEqual(json.loads(matrix._result_path(source, spec).read_text())["evaluator_model"], "judge-A")

    def test_judge_failure_is_saved_without_changing_the_successful_episode(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, _, row = self.source(root)
            judge = mock.Mock()
            judge.generate.side_effect = RuntimeError("mock provider failure")
            rows = post.run_postevaluation(self.options(source, root / "post", judge=True),
                                          evaluator_backend_loader=lambda: judge)
            self.assertEqual(rows[0]["active_pass"], row["active_pass"])
            self.assertEqual(rows[0]["status"], "evaluated")
            self.assertEqual(rows[0]["llm_evaluation_status"], "infrastructure_failed")
            self.assertIsNone(rows[0]["science_postevaluation"]["understanding"])
            self.assertFalse(rows[0]["metrics_complete"])

    def test_incompatible_specialized_results_have_an_explicit_error(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            (source / "results").mkdir(parents=True)
            matrix._write_json(source / "results" / "a.result.json",
                               {"episode_id": "a", "schema": "specialized_revision_format"})
            with self.assertRaisesRegex(ValueError, "specialized historical/revision"):
                post.run_postevaluation(self.options(source, root / "post"))

    def test_mismatched_resume_result_is_not_judged_against_wrong_log(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, spec, row = self.source(root)
            changed = deepcopy(row)
            changed["run_id"] = "different-episode-attempt"
            matrix._write_json(matrix._result_path(source, spec), changed)
            with self.assertRaisesRegex(ValueError, "own completed run log"):
                post.run_postevaluation(self.options(source, root / "post"))


if __name__ == "__main__":
    unittest.main()
