"""An explicit user failure changes binary denominators, never machine evidence."""

from copy import deepcopy
from dataclasses import asdict
import json
from pathlib import Path
import tempfile
import unittest

from experiments import run_case_matrix as matrix
from experiments.analyze_case_matrix import _group_summary
from experiments.offline_adjudications import (
    ADJUDICATED_EPISODE, ADJUDICATION_SCHEMA, apply_adjudications, scientific_summary,
)
from experiments.report_codex_benchmark import build_report, render_report


def registry():
    return {"schema": ADJUDICATION_SCHEMA, "adjudications": [{
        "episode_id": ADJUDICATED_EPISODE, "authority": "user", "decision": "failure",
        "reason": "User explicitly stopped oversized incomplete final output.",
        "recorded_at": "2026-09-17T13:27:56+00:00", "no_further_model_calls": True,
    }]}


class OfflineAdjudicationTests(unittest.TestCase):
    def test_binary_failure_preserves_raw_and_missing_scientific_measurements(self):
        rows = [
            {"episode_id": "completed", "status": "evaluated", "active_pass": True,
             "scores": {"held_out_prediction_score": 0.8},
             "formula_consistency": {"status": "equivalent"}},
            {"episode_id": ADJUDICATED_EPISODE, "status": "infrastructure_failed",
             "active_pass": None, "scores": {}, "llm_evaluation": None},
        ]
        original = deepcopy(rows)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "adjudications.json").write_text(json.dumps(registry()))
            derived = apply_adjudications(root, rows)
        self.assertEqual(rows, original)
        self.assertEqual(derived[1]["status"], "infrastructure_failed")
        self.assertIsNone(derived[1]["active_pass"])
        self.assertEqual(derived[1]["scores"], {})
        self.assertIsNone(derived[1]["llm_evaluation"])
        summary = scientific_summary(derived)
        self.assertEqual(summary["machine_evaluated_n"], 1)
        self.assertEqual(summary["binary_outcome_n"], 2)
        self.assertEqual(summary["success_rate"], 0.5)
        self.assertEqual(summary["failed_n"], 1)
        self.assertEqual(summary["raw_infrastructure_n"], 1)
        self.assertEqual(summary["infrastructure_n"], 0)
        self.assertAlmostEqual(summary["normalized_error"]["mean"], 0.25)
        self.assertEqual(summary["normalized_error"]["scored_n"], 1)
        self.assertEqual(summary["normalized_error"]["eligible_n"], 2)
        self.assertEqual(summary["expression_match"]["mean"], 1.0)
        self.assertEqual(summary["understanding"]["after"]["scored_n"], 0)
        self.assertIsNone(summary["understanding"]["after"]["mean"])
        self.assertTrue(all(value["n"] == 0 for value in summary["failure_modes"].values()))
        self.assertEqual(_group_summary(derived)["active_pass_denominator"], 2)
        self.assertEqual(_group_summary(derived)["active_fail_n"], 1)

    def test_rejects_unapproved_episode_or_overwriting_a_machine_outcome(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            record = registry()
            record["adjudications"][0]["episode_id"] = "different-episode"
            (root / "adjudications.json").write_text(json.dumps(record))
            with self.assertRaisesRegex(ValueError, "explicit user instruction"):
                apply_adjudications(root, [])
            (root / "adjudications.json").write_text(json.dumps(registry()))
            with self.assertRaisesRegex(ValueError, "original unresolved"):
                apply_adjudications(root, [{"episode_id": ADJUDICATED_EPISODE,
                                           "status": "evaluated", "active_pass": True}])

    def test_actual_636_schedule_is_resolved_without_creating_final_or_judge(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            args = matrix._parser().parse_args(["--case-pack", "both", "--repeats", "1", "--output-dir", directory])
            plan = matrix.build_plan(case_pack="both", repeats=1)
            rows = [{**asdict(spec), "status": "evaluated", "active_pass": True,
                     "metrics_complete": True, "scores": {"held_out_prediction_score": 0.8},
                     "formula_consistency": {"status": "equivalent"},
                     "llm_evaluation_status": "evaluated"} for spec in plan]
            selected = next(row for row in rows if row["episode_id"] == ADJUDICATED_EPISODE)
            selected.update(status="infrastructure_failed", active_pass=None, metrics_complete=False,
                            scores={}, formula_consistency=None, llm_evaluation_status="not_applicable")
            (root / "config.json").write_text(json.dumps(matrix._config_payload(args, plan)))
            (root / "episodes.json").write_text(json.dumps({"episodes": rows}))
            (root / "adjudications.json").write_text(json.dumps(registry()))
            status = build_report(root)
            self.assertTrue(status["complete"])
            self.assertTrue(status["execution_ended"])
            overall = status["overall"]
            self.assertEqual(overall["completed_n"], 636)
            self.assertEqual(overall["machine_completed_n"], 635)
            self.assertEqual(overall["active_pass_denominator"], 636)
            self.assertEqual(overall["active_fail_n"], 1)
            self.assertEqual(overall["adjudicated_metrics_unavailable_n"], 1)
            self.assertEqual(sum(g["user_adjudicated_failure_n"] for g in status["condition_groups"]), 1)
            self.assertEqual(overall["scientific_postevaluation"]["normalized_error"]["scored_n"], 635)
            self.assertEqual(overall["scientific_postevaluation"]["normalized_error"]["eligible_n"], 636)
            markdown = render_report(status)
            self.assertIn("636 个二元判定：635 个机器结果 + 1 个用户指定失败", markdown)
            self.assertIn("执行已结束", markdown)
            self.assertIn("科学指标缺测保留", markdown)
            self.assertEqual(json.loads((root / "episodes.json").read_text())["episodes"], rows)


if __name__ == "__main__":
    unittest.main()
