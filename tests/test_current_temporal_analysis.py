"""Offline reporting must include the current 33-family Temporal pack."""

from collections import Counter
from dataclasses import asdict
import json
from pathlib import Path
import tempfile
import unittest

from experiments import run_case_matrix as matrix
from experiments.analyze_case_matrix import analyze
from experiments.report_codex_benchmark import build_report, render_report


def current_temporal_rows():
    rows = []
    for spec in matrix.build_plan(case_pack="temporal", repeats=1):
        # These two scientific relations share a paper. Vary their gains to
        # distinguish equal-paper weighting from an accidental equal-family mean.
        fixed_gain = {"temporal_source_2025": 0.2, "temporal_enriched_90016": 0.6}.get(spec.case_family, 0.1)
        baseline = 0.1 if spec.condition_id == "source_reported" else 0.15
        score = {matrix.PRIOR_ONLY_BASELINE: baseline,
                 matrix.FIXED_EXPERIMENTAL_DESIGN: baseline + fixed_gain,
                 matrix.ADAPTIVE_EXPERIMENTAL_DESIGN: baseline + fixed_gain + 0.1}[spec.evaluation_method]
        rows.append({**asdict(spec), "experiment_id": "offline-current-temporal-fixture",
                     "status": "evaluated", "active_pass": True,
                     "scores": {"held_out_prediction_score": score}})
    return rows


class CurrentTemporalAnalysisTests(unittest.TestCase):
    def test_all_actual_current_cells_and_papers_have_method_contrasts(self):
        rows = current_temporal_rows()
        self.assertEqual(len(rows), 396)
        result = analyze(rows)["temporal_estimands"]
        for key, expected in (("condition_estimates", 132), ("family_estimates", 66),
                              ("source_paper_estimates", 64), ("equal_source_paper_means", 2)):
            self.assertEqual(len(result[key]), expected, key)
            self.assertEqual({item["dataset_kind"] for item in result[key]}, {"temporal_counterfactual"})
        self.assertEqual(Counter(item["condition_id"] for item in result["condition_estimates"]),
                         {"source_reported": 66, "counterfactual": 66})
        expected_versions = {row["case_family"]: row["source_version_id"] for row in rows}
        self.assertIn(None, expected_versions.values())
        self.assertTrue(all(item["source_version_id"] == expected_versions[item["case_family"]]
                            for item in result["condition_estimates"]))
        self.assertTrue(all(item["condition_n"] == 2 for item in result["family_estimates"]))
        for item in result["equal_source_paper_means"]:
            self.assertEqual(item["source_paper_n"], 32)
            self.assertAlmostEqual(item["fixed_gain"], (31 * 0.1 + (0.2 + 0.6) / 2) / 32)
            self.assertAlmostEqual(item["adaptive_gain"], 0.1)

    def test_missing_method_is_not_substituted_with_zero(self):
        rows = current_temporal_rows()
        target = next(row for row in rows if row["case_family"] == "defect_sre"
                      and row["condition_id"] == "counterfactual" and row["task_setting"] == "discovery"
                      and row["evaluation_method"] == matrix.FIXED_EXPERIMENTAL_DESIGN)
        target.update(status="infrastructure_failed", active_pass=None, scores={})
        result = analyze(rows)["temporal_estimands"]
        self.assertEqual(len(result["condition_estimates"]), 131)
        self.assertFalse(any(item["case_family"] == "defect_sre" and item["condition_id"] == "counterfactual"
                             and item["task_setting"] == "discovery" for item in result["condition_estimates"]))
        family = next(item for item in result["family_estimates"] if item["case_family"] == "defect_sre"
                      and item["task_setting"] == "discovery")
        self.assertEqual(family["condition_n"], 1)
        self.assertAlmostEqual(family["fixed_gain"], 0.1)

    def test_report_retains_both_conditions_and_explicit_outcome_denominators(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            args = matrix._parser().parse_args(["--case-pack", "both", "--repeats", "1", "--output-dir", directory])
            plan = matrix.build_plan(case_pack="both", repeats=1)
            config = matrix._config_payload(args, plan)
            (root / "config.json").write_text(json.dumps(config))
            rows = [{**asdict(plan[0]), "status": "evaluated", "active_pass": True},
                    {**asdict(plan[1]), "status": "infrastructure_failed", "active_pass": None}]
            (root / "episodes.json").write_text(json.dumps({"episodes": rows}))
            report = build_report(root)
            groups = report["condition_groups"]
            self.assertEqual(len(groups), 24)
            self.assertEqual({(g["dataset"], g["condition_id"]) for g in groups},
                             {("historical", "historical"), ("historical", "counterfactual"),
                              ("temporal", "source_reported"), ("temporal", "counterfactual")})
            self.assertEqual(sum(g["planned_n"] for g in groups), 636)
            self.assertEqual(sum(g["active_pass_denominator"] for g in groups), 1)
            self.assertEqual(sum(g["active_pass_n"] for g in groups), 1)
            self.assertEqual(sum(g["active_fail_n"] for g in groups), 0)
            self.assertEqual(sum(g["infrastructure_n"] for g in groups), 1)
            self.assertEqual(sum(g["pending_n"] for g in groups), 634)
            self.assertTrue(all(g["active_pass_rate"] is None for g in groups if g["active_pass_denominator"] == 0))
            markdown = render_report(report)
            self.assertIn("明确通过", markdown)
            self.assertIn("source_reported", markdown)


if __name__ == "__main__":
    unittest.main()
