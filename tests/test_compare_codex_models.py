"""Frozen denominators and paired evidence for the offline two-model report."""

from copy import deepcopy
import csv
import json
from pathlib import Path
import tempfile
import unittest

from experiments import compare_codex_models as comparison


METHOD = "prior-only baseline"


def episode(family="pendulum", repeat=1, condition="historical"):
    return "%s__canonical__%s__discovery__prior-only-baseline__r%02d" % (family, condition, repeat)


def fixture(root: Path, model: str, *, repeats: int = 2, judge_model="judge-common"):
    root.mkdir()
    (root / "results").mkdir()
    (root / "evaluations").mkdir()
    config = {"schema": "test.v1", "experiment_id": model, "metrics_protocol": "test",
        "design": {"repeats": repeats, "total_episodes": repeats * 2,
            "evaluation_methods": [METHOD], "task_settings": ["discovery"],
            "player_profile": {"model": model, "checkpoint_or_snapshot_id": model, "reasoning_effort": "high"},
            "oracle_profile": {"model": None}, "evaluator_profile": {"model": judge_model},
            "condition_semantics": {
                "pendulum": {"canonical": [{"condition_id": "historical", "dataset_kind": "historical_counterfactual", "condition_role": "historical"}]},
                "temporal_test": {"canonical": [{"condition_id": "historical", "dataset_kind": "temporal", "condition_role": "original"}]}}},
        "providers": {"player": {"name": "codex", "model": model}, "oracle": {"name": "deterministic"}, "evaluator": {"name": "codex", "model": judge_model}},
        "player_generation": {"prompt_version": "same", "max_actions": 30},
        "oracle_generation": {"mode": "deterministic"}, "evaluator_generation": {"prompt_version": comparison.DISCOVERY_PROMPT_VERSION},
        "schedule": {"seed": 42, "execution_order": [episode(family, r) for r in range(1, repeats + 1) for family in ("pendulum", "temporal_test")]}}
    (root / "config.json").write_text(json.dumps(config))
    return config


def result(root: Path, *, family="pendulum", repeat=1, passed=True, score=0.5,
           status="evaluated", judge=False, model=None):
    config = json.loads((root / "config.json").read_text())
    item = next(item for item in comparison._plan(config) if item["episode_id"] == episode(family, repeat))
    row = {**item, "experiment_id": config["experiment_id"], "status": status,
           "run_id": "run-" + item["episode_id"],
           "player_model": model or config["design"]["player_profile"]["model"],
           "active_pass": passed, "scores": {comparison.HELD_OUT_PREDICTION_SCORE: score},
           "formula_consistency": {"status": "equivalent"}, "metrics_complete": True,
           "llm_evaluation_status": "evaluated"}
    (root / "results" / (item["episode_id"] + ".result.json")).write_text(json.dumps(row))
    if judge:
        value = {**item, "experiment_id": config["experiment_id"], "run_id": row["run_id"],
            "status": "evaluated", "evaluator_model": config["design"]["evaluator_profile"]["model"],
            "evaluator_prompt_version": comparison.DISCOVERY_PROMPT_VERSION,
            "evaluation": {"details": {"understanding": {"items": [], "before_score": 0.2,
                "after_score": 0.7, "delta": 0.5, "status": "paired", "window": "episode", "transitions": []}}}}
        (root / "evaluations" / (item["episode_id"] + ".evaluation.json")).write_text(json.dumps(value))
    return row


class CompareCodexModelsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.left = self.root / "sol"
        self.right = self.root / "astra"
        fixture(self.left, "gpt-5.6-sol")
        fixture(self.right, "gpt-6-astra")

    def report(self):
        return comparison.build_comparison([self.left, self.right])

    def test_empty_runs_retain_every_dataset_repeat_and_null_rates(self):
        report = self.report()
        self.assertTrue(report["comparability"]["deterministic_comparable"])
        summary = report["runs"][0]["overall"]
        self.assertEqual(summary["planned_n"], 4)
        self.assertEqual(summary["scored_n"], 0)
        self.assertIsNone(summary["pass_rate"])
        self.assertIsNone(summary["complete_cell_any_pass_rate"])
        self.assertEqual(summary["complete_repeat_coverage"], 0)
        self.assertEqual({row["dataset"] for row in report["runs"][0]["by_dataset"]}, {"historical", "temporal"})
        self.assertEqual({row["repeat"] for row in report["runs"][0]["by_repeat"]}, {1, 2})
        self.assertEqual(report["paired_summary"]["pass_delta"]["scored_n"], 0)

    def test_missing_repeat_never_counts_as_failure_or_complete_case(self):
        result(self.left)
        report = self.report()
        summary = report["runs"][0]["overall"]
        self.assertEqual((summary["pass_n"], summary["scored_n"], summary["planned_n"]), (1, 1, 4))
        self.assertEqual(summary["pass_rate"], 1)
        self.assertEqual(summary["complete_repeat_cells_n"], 0)
        self.assertIsNone(summary["complete_cell_mean_pass_rate"])
        self.assertEqual(summary["metrics"]["held_out_prediction_score"]["scored_n"], 1)
        self.assertEqual(summary["metrics"]["held_out_prediction_score"]["mean"], 0.5)
        prefix = next(row for row in report["runs"][0]["repeat_prefixes"] if row["dataset"] == "historical" and row["repeat_prefix"] == 1)
        self.assertEqual(prefix["complete_repeat_cells_n"], 1)
        self.assertEqual(prefix["complete_cell_any_pass_rate"], 1)

    def test_full_repeat_case_rates_and_infrastructure_separate(self):
        result(self.left, repeat=1)
        result(self.left, repeat=2, passed=False, score=0)
        result(self.left, family="temporal_test", status="infrastructure_failed", passed=None, score=None)
        summary = self.report()["runs"][0]["overall"]
        self.assertEqual(summary["scored_n"], 2)
        self.assertEqual(summary["infrastructure_n"], 1)
        self.assertEqual(summary["complete_repeat_cells_n"], 1)
        self.assertEqual(summary["complete_repeat_coverage"], 0.5)
        self.assertEqual(summary["complete_cell_mean_pass_rate"], 0.5)
        self.assertIsNone(summary["full_repeat_matrix_pass_rate"])
        self.assertEqual(summary["complete_cell_any_pass_rate"], 1)
        self.assertEqual(summary["complete_cell_all_pass_rate"], 0)
        self.assertEqual(summary["metrics"]["held_out_prediction_score"]["scored_n"], 2)
        result(self.right, repeat=1)
        result(self.right, repeat=2)
        paired = self.report()["paired_summary"]
        self.assertEqual(paired["both_complete_repeat_cells_n"], 1)
        self.assertEqual(paired["complete_cell_pass_rate_delta"]["mean"], 0.5)
        report = self.report()
        historical = next(row for row in report["runs"][0]["by_dataset"] if row["dataset"] == "historical")
        self.assertEqual(historical["full_repeat_matrix_pass_rate"], 0.5)
        markdown = comparison.render_markdown(report)
        self.assertIn("**全矩阵 2 次重复算术均值：—**", markdown)
        self.assertIn("已完整 case 子集均值：50.0%", markdown)
        self.assertIn("(p1+p2+p3)/3", markdown)

    def test_judge_sidecar_is_authoritative_over_stale_result_summary(self):
        result(self.left)
        result(self.left, repeat=2, judge=True)
        summary = self.report()["runs"][0]["overall"]
        self.assertEqual(summary["judge_pending_n"], 1)
        self.assertEqual(summary["judge_evaluated_n"], 1)
        self.assertEqual(summary["metrics_complete_n"], 1)
        self.assertEqual(summary["metrics_unfinished_n"], 3)
        self.assertEqual(summary["metrics"]["understanding_gain"]["scored_n"], 1)
        self.assertEqual(summary["metrics"]["understanding_gain"]["mean"], 0.5)
        config = json.loads((self.right / "config.json").read_text())
        config["design"]["evaluator_profile"] = {"model": None, "status": "deferred_unconfigured"}
        config["providers"]["evaluator"] = {"name": None}
        config["evaluator_generation"] = {"mode": "deferred_unconfigured", "llm_calls": 0}
        (self.right / "config.json").write_text(json.dumps(config))
        row = result(self.right)
        row["elapsed_s"] = 10
        row["attempts_used"] = 4
        row["player_llm_stats"] = {"input_tokens": None, "output_tokens": 100, "decoded_actions": 1}
        (self.right / "results" / (row["episode_id"] + ".result.json")).write_text(json.dumps(row))
        report = self.report()
        self.assertTrue(report["runs"][1]["audit"]["passed"])
        self.assertFalse(report["comparability"]["scientific_judge_comparable"])
        summary = report["runs"][1]["overall"]
        self.assertEqual(summary["judge_deferred_n"], 1)
        self.assertEqual(summary["metrics_complete_n"], 0)
        self.assertEqual(summary["resources"]["elapsed_s"]["known_sum"], 10)
        self.assertEqual(summary["resources"]["player_output_tokens"]["scored_n"], 1)
        self.assertIsNone(summary["resources"]["player_input_tokens"]["known_sum"])

    def test_pairs_require_same_cell_and_repeat_with_observed_measurements(self):
        result(self.left, passed=False, score=0.25)
        result(self.right, passed=True, score=0.75)
        result(self.left, repeat=2)
        result(self.right, family="temporal_test", repeat=2)
        report = self.report()
        summary = report["paired_summary"]
        self.assertEqual(summary["both_scored_n"], 1)
        self.assertEqual(summary["pass_delta"]["mean"], 1)
        pair = next(row for row in report["paired_episodes"] if row["both_scored"])
        self.assertEqual(pair["held_out_prediction_score_delta_right_minus_left"], 0.5)
        self.assertEqual(sum(row["pass_delta_right_minus_left"] is not None for row in report["paired_episodes"]), 1)

    def test_protocol_and_identity_mismatches_disable_deltas(self):
        result(self.left, passed=False)
        result(self.right, model="wrong-model")
        report = self.report()
        self.assertFalse(report["comparability"]["deterministic_comparable"])
        self.assertTrue(report["runs"][1]["audit"]["errors"])
        self.assertIsNone(report["paired_summary"]["pass_delta"]["mean"])
        result(self.right)
        config = json.loads((self.right / "config.json").read_text())
        config["player_generation"]["max_actions"] = 5
        (self.right / "config.json").write_text(json.dumps(config))
        report = self.report()
        self.assertIn("player_generation.max_actions", report["comparability"]["protocol_differences"])
        self.assertIsNone(report["paired_summary"]["pass_delta"]["mean"])

    def test_different_judge_models_do_not_disable_deterministic_pairs(self):
        config = json.loads((self.right / "config.json").read_text())
        config["design"]["evaluator_profile"]["model"] = "other-judge"
        config["providers"]["evaluator"]["model"] = "other-judge"
        (self.right / "config.json").write_text(json.dumps(config))
        result(self.left, passed=False, judge=True)
        result(self.right, passed=True, judge=True)
        report = self.report()
        self.assertTrue(report["comparability"]["deterministic_comparable"])
        self.assertFalse(report["comparability"]["scientific_judge_comparable"])
        pair = next(row for row in report["paired_episodes"] if row["both_scored"])
        self.assertEqual(pair["pass_delta_right_minus_left"], 1)
        self.assertIsNone(pair["understanding_gain_delta_right_minus_left"])

    def test_invalid_schedule_or_mismatched_sidecar_is_detected(self):
        config = json.loads((self.left / "config.json").read_text())
        broken = deepcopy(config)
        broken["schedule"]["execution_order"].append(episode())
        with self.assertRaisesRegex(ValueError, "duplicate"):
            comparison._plan(broken)
        broken = deepcopy(config)
        broken["schedule"]["execution_order"].pop()
        broken["design"]["total_episodes"] -= 1
        with self.assertRaisesRegex(ValueError, "repeats 1..N"):
            comparison._plan(broken)
        row = result(self.left)
        row["condition_id"] = "wrong"
        (self.left / "results" / (row["episode_id"] + ".result.json")).write_text(json.dumps(row))
        self.assertFalse(self.report()["runs"][0]["audit"]["passed"])

    def test_output_is_read_only_and_exports_null_as_blank(self):
        result(self.left)
        before = {str(path): path.read_bytes() for root in (self.left, self.right) for path in root.rglob("*.json")}
        report = self.report()
        output = self.root / "comparison"
        comparison.write_report(report, output)
        self.assertEqual({str(path): path.read_bytes() for root in (self.left, self.right) for path in root.rglob("*.json")}, before)
        self.assertIn("Judge", (output / "comparison.md").read_text())
        self.assertEqual(json.loads((output / "comparison.json").read_text())["schema"], comparison.SCHEMA)
        with (output / "paired_episodes.csv").open() as stream:
            rows = list(csv.DictReader(stream))
        self.assertEqual(len(rows), 4)
        self.assertEqual(rows[0]["pass_delta_right_minus_left"], "")


if __name__ == "__main__":
    unittest.main()
