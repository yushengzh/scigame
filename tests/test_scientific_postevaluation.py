"""Scientific outcome, understanding change and failure attribution stay distinct."""

from copy import deepcopy
import unittest

from role_benchmark.postevaluation import (
    aggregate_scientific_postevaluation,
    science_postevaluation,
)


def understanding(before=0.5, after=1.0, kinds=("gained",)):
    return {"items": [], "before_score": before, "after_score": after,
            "delta": after - before if before is not None and after is not None else None,
            "status": "paired" if before is not None else "final_only",
            "window": {"before_sequence": 1 if before is not None else None, "after_sequence": 3},
            "transitions": [{"criterion_id": str(i), "kind": kind, "before_score": before,
                             "after_score": after} for i, kind in enumerate(kinds)]}


def finding(code):
    return {"code": code, "rationale": "The cited scientific claim disagrees with this world's reference.",
            "event_sequences": [1, 2, 3]}


def episode(passed=False):
    return {"status": "evaluated", "active_pass": passed, "evaluation_success": passed,
            "protocol_completion": True, "scientifically_evaluable": True,
            "termination_kind": "submitted", "active_pass_category": "pass" if passed else "scientific_failure",
            "final_submission": {"model": "expression", "parameters": {"outputs": {"y": 1}}},
            "scores": {"hidden_test_mean_scaled_error": 0.3 if passed else 2.0,
                       "held_out_prediction_score": 0.5},
            "formula_consistency": {"status": "equivalent" if passed else "not_equivalent"},
            "llm_evaluation_status": "evaluated",
            "llm_evaluation": {"details": {"understanding": understanding(), "findings": []}}}


class ScientificPostevaluationTests(unittest.TestCase):
    def test_binary_success_does_not_depend_on_understanding_gain(self):
        success = episode(True)
        success["llm_evaluation"]["details"]["understanding"] = understanding(1, 1, ("retained_correct",))
        failure = episode(False)
        failure["llm_evaluation"]["details"]["understanding"] = understanding(0, 1)
        summary = aggregate_scientific_postevaluation([success, failure])
        self.assertEqual(summary["success_rate"], 0.5)
        self.assertEqual(summary["success_understanding_counts"]["success"], {"retained_correct": 1})
        self.assertEqual(summary["success_understanding_counts"]["failure"], {"improved": 1})
        self.assertEqual(science_postevaluation(success)["failure_analysis"]["labels"], [])

    def test_fixed_final_only_does_not_create_a_before_or_delta(self):
        row = episode()
        row["llm_evaluation"]["details"]["understanding"] = understanding(None, 0.5, ("unmeasured",))
        result = aggregate_scientific_postevaluation([row])
        self.assertEqual(result["understanding"]["after"]["mean"], 0.5)
        self.assertIsNone(result["understanding"]["before"]["mean"])
        self.assertIsNone(result["understanding"]["delta"]["mean"])
        self.assertEqual(result["understanding"]["paired"]["n"], 0)
        self.assertEqual(result["success_understanding_counts"]["failure"], {"unmeasured": 1})

    def test_endpoint_and_paired_means_use_explicit_cohorts(self):
        paired = episode()
        paired["llm_evaluation"]["details"]["understanding"] = understanding(0, 0.5)
        final_only = episode()
        final_only["llm_evaluation"]["details"]["understanding"] = understanding(None, 1)
        result = aggregate_scientific_postevaluation([paired, final_only])["understanding"]
        self.assertEqual(result["after"]["mean"], 0.75)
        self.assertEqual(result["paired"]["after_mean"], 0.5)
        self.assertEqual(result["delta"]["scored_n"], 1)
        self.assertEqual(result["delta"]["eligible_n"], 2)

    def test_gains_and_losses_are_visible_despite_zero_net_change(self):
        row = episode()
        row["llm_evaluation"]["details"]["understanding"] = understanding(0.5, 0.5, ("gained", "degraded"))
        result = aggregate_scientific_postevaluation([row])
        self.assertEqual(result["understanding"]["delta"]["mean"], 0)
        self.assertEqual(result["success_understanding_counts"]["failure"], {"mixed_gain_and_loss": 1})

    def test_error_uses_recorded_mean_and_does_not_invert_invalid_zero(self):
        row = episode()
        self.assertEqual(science_postevaluation(row)["normalized_error"], 2.0)
        row["scores"] = {"held_out_prediction_score": 0.25}
        self.assertEqual(science_postevaluation(row)["normalized_error"], 3.0)
        row["scores"] = {"held_out_prediction_score": 0}
        self.assertIsNone(science_postevaluation(row)["normalized_error"])

    def test_expression_inconclusive_is_not_scored_incorrect(self):
        uncertain = episode()
        uncertain["formula_consistency"]["status"] = "inconclusive"
        result = aggregate_scientific_postevaluation([episode(True), episode(False), uncertain])
        self.assertEqual(result["expression_match"]["mean"], 0.5)
        self.assertEqual(result["expression_match"]["scored_n"], 2)
        self.assertEqual(result["expression_match"]["eligible_n"], 3)
        self.assertEqual(result["expression_match"]["decision_coverage"], 2 / 3)

    def test_non_equivalence_or_ast_shape_does_not_invent_f2_or_f3(self):
        row = episode()
        row["formula_consistency"]["operator_structure_match"] = True
        result = science_postevaluation(row)
        self.assertEqual(result["failure_analysis"]["labels"], [])
        self.assertTrue(result["failure_analysis"]["unclassified"])
        row["llm_evaluation"]["details"]["findings"] = [finding("F3")]
        result = science_postevaluation(row)
        self.assertEqual([item["code"] for item in result["failure_analysis"]["labels"]], ["F3"])

    def test_scientifically_correct_protocol_failure_does_not_become_f3(self):
        row = episode(True)
        row.update(active_pass=False, protocol_completion=False)
        row["llm_evaluation"]["details"]["findings"] = [finding("F3")]
        result = science_postevaluation(row)
        self.assertEqual(result["failure_analysis"]["blocking_conditions"], ["protocol_not_completed"])
        self.assertEqual(result["failure_analysis"]["labels"], [])
        self.assertIn("F3_requires_evaluable_numerical_failure", result["coverage"]["conflicts"])

    def test_formula_proof_conflict_remains_explicit_and_unclassified(self):
        row = episode()
        row["formula_consistency"]["status"] = "equivalent"
        row["llm_evaluation"]["details"]["findings"] = [finding("F2")]
        result = science_postevaluation(row)
        self.assertEqual(result["failure_analysis"]["labels"], [])
        self.assertTrue(result["failure_analysis"]["unclassified"])
        self.assertEqual(result["coverage"]["conflicts"], ["F2_conflicts_with_proven_expression_equivalence"])

    def test_multilabel_failure_rates_include_unclassified_failures(self):
        first = episode()
        first["llm_evaluation"]["details"]["findings"] = [finding("F2"), finding("F4"), finding("F5"), finding("F4")]
        second = episode()
        second["llm_evaluation_status"] = "pending"
        result = aggregate_scientific_postevaluation([first, second, episode(True)])
        for code in ("F2", "F4", "F5"):
            self.assertEqual(result["failure_modes"][code], {"n": 1, "failed_n": 2, "rate": 0.5})
        self.assertEqual(result["unclassified_failed_n"], 1)
        self.assertEqual(result["judge_available_failed_n"], 1)
        self.assertGreater(sum(item["rate"] for item in result["failure_modes"].values()), 1)

    def test_judge_unavailable_does_not_change_episode_or_imply_no_defects(self):
        for status in ("pending", "infrastructure_failed"):
            row = episode()
            row["llm_evaluation_status"] = status
            row["llm_evaluation"]["details"]["findings"] = [finding("F2")]
            original = deepcopy(row)
            result = science_postevaluation(row)
            self.assertFalse(result["active_pass"])
            self.assertFalse(result["coverage"]["scientific_judge_available"])
            self.assertEqual(result["failure_analysis"]["labels"], [])
            self.assertIsNone(result["understanding"])
            self.assertEqual(row, original)

    def test_missing_scientific_submission_and_external_interruption_differ(self):
        row = episode()
        row.update(final_submission=None, scientifically_evaluable=False,
                   termination_kind="player_output_invalid", active_pass_category="player_generation_failure")
        self.assertEqual(science_postevaluation(row)["failure_analysis"]["labels"][0]["code"], "F1")
        row.update(active_pass_category="generation_incomplete", reason_code="incomplete_output")
        self.assertEqual(science_postevaluation(row)["failure_analysis"]["labels"], [])
        row.update(status="infrastructure_failed", active_pass=None)
        result = aggregate_scientific_postevaluation([row, episode(True)])
        self.assertEqual(result["success_rate"], 1)
        self.assertEqual(result["success_rate_denominator"], 1)
        self.assertEqual(result["infrastructure_n"], 1)

    def test_existing_per_episode_result_can_be_aggregated(self):
        row = episode()
        row["science_postevaluation"] = science_postevaluation(row)
        result = aggregate_scientific_postevaluation([row])
        self.assertEqual(result["failed_n"], 1)
        self.assertEqual(result["normalized_error"]["mean"], 2)


if __name__ == "__main__":
    unittest.main()
