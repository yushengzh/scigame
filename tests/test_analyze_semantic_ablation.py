"""Missingness, paired family estimands, and frozen semantic-ablation scope."""

from copy import deepcopy
import itertools
import json
from pathlib import Path
import tempfile
import unittest

from experiments import analyze_semantic_ablation as analysis


def make_config(root):
    families = ["family_%02d" % index for index in range(20)]
    plan = []
    for index, key in enumerate(itertools.product(analysis.MODELS, analysis.METHODS, families,
                                                 analysis.WORLDS, analysis.ARMS, analysis.REPEATS)):
        item = dict(zip((*analysis.CELL_FIELDS, "repeat"), key))
        item.update(episode_id="episode-%04d" % index,
                    result_path="results/episode-%04d.result.json" % index)
        plan.append(item)
    config = {"schema": "test.semantic_ablation.v1", "experiment_id": "semantic-test",
              "design": {"families": families, "models": list(analysis.MODELS),
                         "methods": list(analysis.METHODS), "worlds": list(analysis.WORLDS),
                         "semantic_arms": list(analysis.ARMS), "repeats": 3, "task_setting": "discovery"},
              "schedule": {"episodes": plan}}
    (root / "results").mkdir()
    (root / "config.json").write_text(json.dumps(config))
    return config


class SemanticAblationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.config = make_config(self.root)

    def result(self, *, family="family_00", world="counterfactual", arm="familiar", repeat=1,
               model=analysis.MODELS[0], method=analysis.ADAPTIVE, **fields):
        item = next(item for item in self.config["schedule"]["episodes"] if
                    (item["case_family"], item["world"], item["semantic_arm"], item["repeat"], item["player_model"], item["evaluation_method"])
                    == (family, world, arm, repeat, model, method))
        row = {**item, "experiment_id": self.config["experiment_id"], "task_setting": "discovery",
               "status": "evaluated", "evaluation_success": True, "active_pass": True,
               "protocol_completion": True, **fields}
        (self.root / item["result_path"]).write_text(json.dumps(row))
        return row

    def case(self, **fields):
        for repeat in analysis.REPEATS:
            self.result(repeat=repeat, **fields)

    def report(self):
        return analysis.build_analysis(self.root, bootstrap_samples=1000, bootstrap_seed=17)

    @staticmethod
    def effect(report, estimand="counterfactual_arm_effect", metric="evaluation_success"):
        return next(effect for effect in report["effects"] if effect["player_model"] == analysis.MODELS[0]
                    and effect["evaluation_method"] == analysis.ADAPTIVE
                    and effect["metric"] == metric and effect["estimand"] == estimand)

    def test_empty_frozen_schedule_keeps_full_960_denominator(self):
        report = self.report()
        self.assertEqual(report["overall"]["planned_n"], 960)
        self.assertEqual(report["overall"]["planned_cells_n"], 320)
        self.assertEqual(len(report["groups"]), 16)
        self.assertEqual(report["overall"]["missing_sidecar_n"], 960)
        for effect in report["effects"]:
            self.assertEqual(effect["planned_families_n"], 20)
            self.assertEqual(effect["complete_families_n"], 0)
            self.assertIsNone(effect["estimate"])
            self.assertIsNone(effect["exploratory_complete_family_estimate"])

    def test_one_missing_repeat_excludes_the_whole_family_metric(self):
        self.case(arm="familiar")
        self.result(arm="anonymous", repeat=1, evaluation_success=False)
        self.result(arm="anonymous", repeat=2, evaluation_success=False)
        self.result(arm="anonymous", repeat=3, status="infrastructure_failed", evaluation_success=False)
        report = self.report()
        effect = self.effect(report)
        self.assertEqual(effect["complete_families_n"], 0)
        self.assertIsNone(effect["exploratory_complete_family_estimate"])
        self.assertEqual(report["overall"]["infrastructure_n"], 1)
        self.result(arm="anonymous", repeat=3, evaluation_success=True)
        effect = self.effect(self.report())
        self.assertEqual(effect["complete_families_n"], 1)
        self.assertAlmostEqual(effect["exploratory_complete_family_estimate"], -2 / 3)
        self.assertIsNone(effect["estimate"])
        self.assertIsNone(effect["exploratory_complete_family_ci95"])

    def test_family_pairing_does_not_match_different_families_or_count_repeats_independently(self):
        self.case(family="family_00", arm="familiar", evaluation_success=False)
        self.case(family="family_00", arm="anonymous", evaluation_success=True)
        self.case(family="family_01", arm="familiar", evaluation_success=True)
        self.case(family="family_01", arm="anonymous", evaluation_success=False)
        # Different one-sided families must not create a third pair.
        self.case(family="family_02", arm="familiar")
        self.case(family="family_03", arm="anonymous")
        effect = self.effect(self.report())
        self.assertEqual(effect["complete_families_n"], 2)
        self.assertEqual(effect["exploratory_complete_family_estimate"], 0)
        self.assertEqual(effect["exploratory_complete_family_ci95"], [-1, 1])
        self.assertIsNone(effect["ci95"])

    def test_full_primary_and_interaction_use_three_repeat_means_then_equal_family_weights(self):
        for index, family in enumerate(self.config["design"]["families"]):
            self.case(family=family, arm="familiar", evaluation_success=False)
            self.case(family=family, arm="anonymous", evaluation_success=index < 10)
            self.case(family=family, world="original", arm="familiar", evaluation_success=True)
            self.case(family=family, world="original", arm="anonymous", evaluation_success=index >= 5)
        report = self.report()
        primary = self.effect(report)
        interaction = self.effect(report, "world_interaction")
        self.assertTrue(primary["primary"])
        self.assertEqual(primary["estimate"], 0.5)
        self.assertEqual(primary["complete_families_n"], 20)
        self.assertEqual(interaction["estimate"], 0.75)
        # All 20 CF arm pairs remain complete; interaction loses the missing original cell.
        item = next(item for item in self.config["schedule"]["episodes"] if item["case_family"] == "family_00"
                    and item["world"] == "original" and item["semantic_arm"] == "anonymous"
                    and item["repeat"] == 3 and item["player_model"] == analysis.MODELS[0]
                    and item["evaluation_method"] == analysis.ADAPTIVE)
        (self.root / item["result_path"]).unlink()
        report = self.report()
        self.assertEqual(self.effect(report)["estimate"], 0.5)
        self.assertEqual(self.effect(report, "world_interaction")["complete_families_n"], 19)
        self.assertIsNone(self.effect(report, "world_interaction")["estimate"])

    def test_prediction_protocol_and_active_remain_separate_and_missing_is_not_failure(self):
        self.case(arm="familiar", evaluation_success=True, active_pass=False, protocol_completion=False)
        self.case(arm="anonymous", evaluation_success=None, active_pass=True, protocol_completion=True)
        report = self.report()
        self.assertEqual(self.effect(report)["complete_families_n"], 0)
        for metric in ("active_pass", "protocol_completion"):
            effect = self.effect(report, metric=metric)
            self.assertEqual(effect["complete_families_n"], 1)
            self.assertEqual(effect["exploratory_complete_family_estimate"], 1)
        self.assertEqual(report["overall"]["prediction_pass_active_fail_n"], 3)
        self.assertEqual(report["overall"]["prediction_active_joint_observed_n"], 3)

    def test_scope_identity_and_unplanned_results_fail_closed(self):
        for change in (lambda c: c["design"].update(repeats=2),
                       lambda c: c["design"]["families"].pop(),
                       lambda c: c["schedule"]["episodes"].__setitem__(1, deepcopy(c["schedule"]["episodes"][0]))):
            changed = deepcopy(self.config)
            change(changed)
            with self.assertRaises(ValueError):
                analysis.validate_plan(changed, self.root)
        row = self.result()
        row["semantic_arm"] = "anonymous"
        (self.root / row["result_path"]).write_text(json.dumps(row))
        with self.assertRaisesRegex(ValueError, "identity mismatch"):
            self.report()
        self.result()
        (self.root / "results" / "unplanned.result.json").write_text("{}")
        with self.assertRaisesRegex(ValueError, "outside the frozen plan"):
            self.report()

    def test_optional_diagnostics_report_coverage_and_deduplicate_protocol_reasons(self):
        self.result(active_pass=False, protocol_completion=False, attempts_used=0,
                    termination_kind="submitted", reason_code="submitted_with_protocol_violations",
                    protocol_violations=[{"code": "portfolio_confidence_not_normalized"}] * 2,
                    initial_max_confidence=0.95, final_selected_confidence=None,
                    inactive_original_prediction_success=False,
                    player_llm_stats={"input_tokens": None, "output_tokens": 123})
        self.result(repeat=2, protocol_violations=None, initial_max_confidence=float("nan"),
                    evaluation_success=False, inactive_original_prediction_success=True)
        summary = self.report()["overall"]
        self.assertEqual(summary["protocol_violation_episode_counts"], {"portfolio_confidence_not_normalized": 1})
        self.assertEqual(summary["numeric"]["initial_max_confidence"]["observed_n"], 1)
        self.assertEqual(summary["numeric"]["initial_max_confidence"]["mean"], 0.95)
        self.assertIsNone(summary["numeric"]["final_selected_confidence"]["mean"])
        self.assertIsNone(summary["numeric"]["input_tokens"]["known_sum"])
        self.assertEqual(summary["adaptive_stop_diagnostic"]["submitted_without_observations_n"], 1)
        self.assertEqual(summary["adaptive_stop_diagnostic"]["observable_n"], 1)
        inactive = summary["counterfactual_inactive_original_diagnostic"]
        self.assertEqual(inactive["joint_observed_n"], 2)
        self.assertEqual(inactive["inactive_original_only_n"], 1)
        self.assertEqual(inactive["active_counterfactual_only_n"], 1)

    def test_bootstrap_and_read_only_exports_are_reproducible(self):
        self.case(arm="familiar", evaluation_success=False)
        self.case(arm="anonymous")
        self.case(family="family_01", arm="familiar", evaluation_success=False)
        self.case(family="family_01", arm="anonymous")
        before = {str(path): path.read_bytes() for path in self.root.rglob("*.json")}
        report = self.report()
        self.assertEqual(report["effects"], self.report()["effects"])
        output = self.root / "report"
        analysis.write_analysis(report, output)
        self.assertEqual(before, {path: Path(path).read_bytes() for path in before})
        self.assertEqual(len(list(output.iterdir())), 7)
        markdown = (output / "analysis.md").read_text()
        self.assertIn("探索性完整 family 子集", markdown)
        self.assertIn("(p1+p2+p3)/3", markdown)
        self.assertEqual(json.loads((output / "analysis.json").read_text())["schema"], analysis.SCHEMA)


if __name__ == "__main__":
    unittest.main()
