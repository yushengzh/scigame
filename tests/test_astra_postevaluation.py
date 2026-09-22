"""Offline orchestration tests; no test starts a model request."""

from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest import mock

from experiments import run_astra_postevaluation as runner
from experiments import run_case_matrix as matrix


class AstraPostevaluationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.source = self.root / "source"
        self.output = self.root / "post"
        self.source.mkdir()
        self.output.mkdir()
        (self.output / "results").mkdir()
        (self.output / "evaluations").mkdir()
        self.write(self.source / "config.json", {"experiment_id": "fixture"})
        self.write(self.output / "config.json", {
            "mode": runner.post.MODE, "experiment_id": "fixture",
            "source_run_dir": str(self.source),
        })
        self.base_spec = matrix.build_plan(0, families=["pendulum"], repeats=1,
            case_pack="historical", task_settings=["discovery"],
            evaluation_methods=[matrix.ADAPTIVE_EXPERIMENTAL_DESIGN],
            conditions=["historical"])[0]

    @staticmethod
    def write(path, value):
        path.write_text(json.dumps(value), encoding="utf-8")

    def episode(self, index, *, complete=True, excluded=None):
        row = asdict(self.base_spec)
        episode_id = "episode-%03d" % index
        log_path = self.source / (episode_id + ".jsonl")
        row.update(schema=matrix.EPISODE_RESULT_SCHEMA, experiment_id="fixture",
                   episode_id=episode_id, run_id=episode_id, case_id="fixture.case",
                   status="evaluated", log_path=str(log_path), schedule_index=index)
        events = [{"run_id": episode_id, "sequence": 0, "recorded_at": "fixture",
                   "event_type": "run.started", "payload": {"case": {
                       "case_id": row["case_id"], "track": row["task_setting"]}}}]
        if complete:
            events.append({"run_id": episode_id, "sequence": 1,
                "recorded_at": "fixture", "event_type": "run.ended", "payload": {}})
        log_path.write_text("".join(json.dumps(e, sort_keys=True, separators=(",", ":")) + "\n"
                                    for e in events), encoding="utf-8")
        if excluded is not None:
            row["post_evaluation_exclusion_reason"] = excluded
            row["status"] = "infrastructure_failed"
        self.write(self.output / "results" / (episode_id + ".result.json"), row)
        return row

    @staticmethod
    def successful(row):
        return {"status": "evaluated", "episode_id": row["episode_id"],
                "run_id": row["run_id"], "evaluator_provider": "codex",
                "evaluator_model": runner.MODEL,
                "evaluator_reasoning_effort": runner.EFFORT,
                "evaluator_prompt_version": matrix.DISCOVERY_PROMPT_VERSION,
                "response": {"model": runner.MODEL, "provider": "codex"},
                "request": {"response_schema": runner.JUDGE_SCHEMA, "messages": [
                    {"role": "system", "content": runner.JUDGE_SYSTEM_PROMPT},
                    {"role": "user", "content": "fixture projection"}]},
                "evaluation": {"details": {"understanding": {"status": "final_only"}}}}

    def options(self, *extra):
        return runner._parser().parse_args(["--output-dir", str(self.output), *extra])

    def run_offline(self, options=None, judge=None):
        if judge is None:
            judge = lambda *args, **kwargs: self.successful(kwargs["episode_result"])
        with mock.patch.object(matrix, "_run_evaluator", side_effect=judge) as evaluator, \
                mock.patch.object(matrix, "write_summaries") as summaries:
            result = runner.run(options or self.options(), backend_factory=lambda: object())
        return result, evaluator, summaries

    def test_fixed_settings_and_cli_validation(self):
        opts = self.options()
        self.assertEqual((opts.workers, opts.retry_passes), (16, 1))
        args = runner.evaluator_args(self.output)
        self.assertEqual(args.evaluator_model, "gpt-6-astra")
        self.assertEqual(args.evaluator_reasoning_effort, "high")
        self.assertEqual(args.evaluator_timeout_s, 900)
        self.assertEqual(args.evaluator_max_output_tokens, 8192)
        for extra in (("--workers", "0"), ("--workers", "33"),
                      ("--limit", "0"), ("--retry-passes", "-1")):
            with self.subTest(extra=extra), self.assertRaises(ValueError):
                runner.run(self.options(*extra))

    def test_usable_checks_every_identity_and_nested_shape(self):
        row = self.episode(0)
        good = self.successful(row)
        self.assertTrue(runner.usable(good, row))
        changes = [{"status": "infrastructure_failed"}, {"episode_id": "other"},
                   {"run_id": "other-attempt"}, {"evaluator_provider": "other"},
                   {"evaluator_model": "gpt-5.5"}, {"evaluator_prompt_version": "old"},
                   {"evaluator_reasoning_effort": "low"},
                   {"response": {"model": "gpt-5.5"}}, {"response": []},
                   {"response": {"model": runner.MODEL, "provider": "other"}},
                   {"request": {"response_schema": {}, "messages": []}},
                   {"request": {"response_schema": runner.JUDGE_SCHEMA, "messages": []}},
                   {"evaluation": []}, {"evaluation": {"details": []}},
                   {"evaluation": {"details": {"understanding": None}}}]
        for change in changes:
            with self.subTest(change=change):
                self.assertFalse(runner.usable({**good, **change}, row))

    def test_retry_only_failed_judge_and_preserve_every_attempt(self):
        rows = [self.episode(i) for i in range(3)]
        counts = {}
        def judge(*args, episode_result, **kwargs):
            key = episode_result["episode_id"]
            counts[key] = counts.get(key, 0) + 1
            if key == rows[0]["episode_id"] and counts[key] == 1:
                return {"status": "infrastructure_failed", "error_type": "Unavailable"}
            return self.successful(episode_result)
        result, evaluator, _ = self.run_offline(judge=judge)
        self.assertEqual(result["status"], "complete")
        self.assertEqual(evaluator.call_count, 4)
        self.assertEqual(result["usable_n"], 3)
        self.assertEqual(result["usable_this_run_n"], 3)
        self.assertEqual(result["completed_this_run_n"], 4)
        self.assertEqual(result["infrastructure_failed_this_run_n"], 1)
        self.assertEqual(result["latest_failures"], {})
        history = self.output / "evaluations" / "attempts" / rows[0]["episode_id"]
        self.assertEqual(len(list(history.glob("*.json"))), 2)
        again, evaluator, _ = self.run_offline()
        self.assertEqual(evaluator.call_count, 0)
        self.assertEqual(again["already_complete_n"], 3)

    def test_incompatible_evaluated_result_is_archived_and_not_counted(self):
        rows = [self.episode(i) for i in range(2)]
        for row in rows:
            result = self.successful(row)
            result["response"]["model"] = "gpt-5.5"
            self.write(self.output / "evaluations" / (row["episode_id"] + ".evaluation.json"), result)
        progress, evaluator, _ = self.run_offline(self.options("--limit", "1"))
        self.assertEqual(progress["status"], "completed_limited")
        self.assertEqual(progress["already_complete_n"], 0)
        self.assertEqual(progress["remaining_n"], 1)
        self.assertEqual(evaluator.call_count, 1)
        self.assertFalse((self.output / "evaluations" / (rows[1]["episode_id"] + ".evaluation.json")).exists())
        for row, count in zip(rows, (2, 1)):
            history = self.output / "evaluations" / "attempts" / row["episode_id"]
            self.assertEqual(len(list(history.glob("*.json"))), count)

    def test_explicit_exclusion_skips_unfinished_log(self):
        self.episode(0)
        excluded = self.episode(1, complete=False, excluded="reviewed unfinished log")
        progress, evaluator, _ = self.run_offline()
        self.assertEqual(evaluator.call_count, 1)
        self.assertEqual(progress["eligible_episode_n"], 1)
        self.assertEqual(progress["excluded_episode_ids"], [excluded["episode_id"]])
        self.assertEqual(progress["status"], "complete")

    def test_preflight_validates_every_episode_before_calling_judge(self):
        self.episode(0)
        row = self.episode(1, complete=False)
        with mock.patch.object(matrix, "_run_evaluator") as judge, self.assertRaisesRegex(ValueError, "completed run log"):
            runner.run(self.options("--limit", "1"), backend_factory=lambda: object())
        judge.assert_not_called()
        self.assertFalse((self.output / "astra_judge_progress.json").exists())
        row["post_evaluation_exclusion_reason"] = ""
        self.write(self.output / "results" / (row["episode_id"] + ".result.json"), row)
        with self.assertRaisesRegex(ValueError, "nonempty documented reason"):
            runner.preflight(self.output)

    def test_config_case_and_run_identity_mismatches_are_rejected(self):
        row = self.episode(0)
        path = self.output / "results" / (row["episode_id"] + ".result.json")
        for key, value, message in (("experiment_id", "other", "experiment_id"),
                                    ("run_id", "other", "completed run log"),
                                    ("case_id", "other", "case_id"),
                                    ("task_setting", "identification", "task_setting")):
            with self.subTest(key=key):
                self.write(path, {**row, key: value})
                with self.assertRaisesRegex(ValueError, message):
                    runner.preflight(self.output)
        self.write(path, row)
        self.write(self.source / "config.json", {"experiment_id": "other"})
        with self.assertRaisesRegex(ValueError, "source config experiment_id"):
            runner.preflight(self.output)

    def test_manifest_freeze_rejects_changed_input_before_backend_construction(self):
        row = self.episode(0)
        result_path = self.output / "results" / (row["episode_id"] + ".result.json")
        source_result = self.source / "source.result.json"
        self.write(source_result, row)
        digest = lambda p: hashlib.sha256(Path(p).read_bytes()).hexdigest()
        manifest = {
            "judge_model": runner.MODEL, "judge_reasoning_effort": runner.EFFORT,
            "source_run_dir": str(self.source), "output_dir": str(self.output),
            "episode_n": 1,
            "posteval_config_sha256": digest(self.output / "config.json"),
            "source_config_sha256": digest(self.source / "config.json"),
            "prepared_results_sha256": {row["episode_id"]: digest(result_path)},
            "source_inputs": {row["episode_id"]: {"sha256": {
                row["log_path"]: digest(row["log_path"]), str(source_result): digest(source_result)}}},
        }
        self.write(self.output / "input_manifest.json", manifest)
        runner.preflight(self.output)
        for path in (result_path, source_result, Path(row["log_path"]),
                     self.source / "config.json", self.output / "config.json"):
            original = path.read_bytes()
            path.write_bytes(original + b" ")
            backend = mock.Mock()
            with self.subTest(path=path), self.assertRaisesRegex(ValueError, "SHA-256 mismatch"):
                runner.run(self.options(), backend_factory=backend)
            backend.assert_not_called()
            path.write_bytes(original)
        manifest["episode_n"] = 2
        self.write(self.output / "input_manifest.json", manifest)
        with self.assertRaisesRegex(ValueError, "episode cohort"):
            runner.preflight(self.output)

    def test_eight_consecutive_failures_pause_without_retrying_or_new_work(self):
        for i in range(12):
            self.episode(i)
        failure = lambda *a, **kw: {"status": "infrastructure_failed", "error_type": "Unavailable"}
        progress, evaluator, _ = self.run_offline(self.options("--workers", "1"), judge=failure)
        self.assertEqual(evaluator.call_count, 8)
        self.assertEqual(progress["status"], "paused_infrastructure_failures")
        self.assertEqual(progress["active_n"], 0)
        self.assertEqual(progress["remaining_n"], 12)
        self.assertEqual(progress["unscheduled_this_pass_n"], 4)
        self.assertEqual(progress["failure_reasons"], {"Unavailable": 8})

    def test_worker_exception_and_incompatible_new_success_are_recorded(self):
        row = self.episode(0)
        def judge(*a, **kw):
            raise RuntimeError("must not print arbitrary backend exception text")
        progress, evaluator, _ = self.run_offline(self.options("--retry-passes", "0"), judge=judge)
        self.assertEqual(evaluator.call_count, 1)
        self.assertEqual(progress["status"], "completed_with_infrastructure_failures")
        result = matrix._load_evaluator_result(self.output, row["episode_id"])
        self.assertNotIn("arbitrary", result["error_message"])
        def incompatible(*a, **kw):
            return {**self.successful(row), "evaluator_model": "wrong"}
        self.run_offline(self.options("--retry-passes", "0"), judge=incompatible)
        result = matrix._load_evaluator_result(self.output, row["episode_id"])
        self.assertEqual(result["status"], "infrastructure_failed")
        self.assertEqual(result["error_type"], "InvalidJudgeResult")

    def test_lock_prevents_double_start_and_releases_after_failure(self):
        with runner.output_lock(self.output):
            with self.assertRaisesRegex(ValueError, "another Astra"):
                with runner.output_lock(self.output):
                    self.fail("second lock acquired")
        with runner.output_lock(self.output):
            pass

    def test_parallel_workers_and_single_summary_writer(self):
        for i in range(4):
            self.episode(i)
        barrier = threading.Barrier(4)
        def judge(*args, episode_result, **kwargs):
            barrier.wait(timeout=5)
            return self.successful(episode_result)
        caller = threading.get_ident()
        summary_threads = []
        with mock.patch.object(matrix, "_run_evaluator", side_effect=judge), \
                mock.patch.object(matrix, "write_summaries", side_effect=lambda _: summary_threads.append(threading.get_ident())):
            progress = runner.run(self.options("--workers", "4"), backend_factory=lambda: object())
        self.assertEqual(progress["usable_n"], 4)
        self.assertEqual(set(summary_threads), {caller})
        self.assertEqual(json.loads((self.output / "astra_judge_progress.json").read_text()), progress)
        self.assertFalse((self.output / "astra_judge_progress.json.tmp").exists())

    def test_summaries_are_periodic_and_excluded_adapter_success_is_visible(self):
        for i in range(26):
            self.episode(i)
        row = self.episode(26, complete=False, excluded="dedicated reviewed adapter")
        self.write(self.output / "evaluations" / (row["episode_id"] + ".evaluation.json"), self.successful(row))
        progress, _, summaries = self.run_offline(self.options("--workers", "1"))
        self.assertEqual(progress["usable_n"], 26)
        self.assertEqual(progress["overall_usable_n"], 27)
        self.assertGreaterEqual(summaries.call_count, 3)


if __name__ == "__main__":
    unittest.main()
