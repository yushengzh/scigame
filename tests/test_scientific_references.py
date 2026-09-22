"""Judge references must agree with the real active world across both datasets."""

import math
import unittest

from experiments import run_case_matrix as matrix
from role_benchmark import BenchmarkTrack, ExperimentProposal, FinalSubmission
from role_benchmark.cases.matched import truth_submission
from role_benchmark.expression import evaluate_expression_program
from role_benchmark.performance import discovery_reference_context, formula_metric


class ScientificReferenceTests(unittest.TestCase):
    def test_all_212_cases_use_the_active_truth_without_sibling_contamination(self):
        plan = matrix.build_plan(case_pack="both", repeats=1,
            evaluation_methods=[matrix.PRIOR_ONLY_BASELINE])
        self.assertEqual(len(plan), 212)
        self.assertEqual(len({item.case_family for item in plan}), 53)
        for item in plan:
            with self.subTest(case=item.benchmark_instance_id):
                pack = matrix.CASE_PACKS[item.case_pack]
                spec = pack.specifications[item.case_family][item.variant_id]
                world = pack.runtime_condition_ids.get(item.case_family, {}).get(
                    item.condition_id, item.condition_id)
                case = matrix._make_case(item)
                reference = discovery_reference_context(case, spec, world)
                self.assertEqual(reference["predictor"]["outputs"],
                    spec.truths[world].discovery_outputs)
                self.assertEqual(reference["active_world"], {
                    "runtime_key": world, "is_counterfactual": world == "counterfactual"})
                if world == "counterfactual":
                    self.assertEqual(reference["counterfactual_change"], spec.counterfactual_change)
                    self.assertEqual(reference["original_world_comparison"]["predictor"]["outputs"],
                        spec.truths["historical"].discovery_outputs)
                    self.assertIn("Inactive", reference["original_world_comparison"]["purpose"])
                else:
                    self.assertNotIn("counterfactual_change", reference)
                    self.assertNotIn("original_world_comparison", reference)

                submission = truth_submission(spec, world, BenchmarkTrack(item.task_setting))
                self.assertTrue(case.evaluator.evaluate(submission).success)
                self.assertEqual(formula_metric(submission, spec, world)["status"], "equivalent")
                sibling = "historical" if world == "counterfactual" else "counterfactual"
                self.assertEqual(formula_metric(submission, spec, sibling)["status"], "not_equivalent")

                # Exercise the actual world model, including instrument rounding,
                # rather than only comparing two references to the same registry.
                for controls in spec.diagnostic_conditions + spec.hidden_conditions:
                    predictions = evaluate_expression_program(reference["predictor"], controls)
                    evidence = case.world_model.run(ExperimentProposal(
                        intent="Check the sealed active-world scientific reference.",
                        apparatus=spec.apparatus_name, controls=dict(controls),
                        readouts=tuple(readout.name for readout in spec.readouts),
                        replicates=1))
                    for readout in spec.readouts:
                        expected = predictions[readout.name]
                        allowance = float(readout.resolution or 0) / 2 + max(1e-12, abs(expected) * 1e-12)
                        self.assertAlmostEqual(evidence.measurements[readout.name], expected,
                            delta=allowance)

    def test_nearby_pendulum_constants_remain_strictly_nonequivalent(self):
        spec = matrix.CASE_PACKS["historical"].specifications["pendulum"]["canonical"]
        case = matrix.make_matched_case(spec, "historical", BenchmarkTrack.DISCOVERY)
        submission = FinalSubmission(hypothesis_id="H1", explanation="Approximate pendulum law.",
            model="expression", parameters={"outputs": {"period_s": {
                "op": "multiply", "args": [2 * math.pi, {"op": "sqrt", "args": [
                    {"op": "divide", "args": [{"var": "length_m"}, 9.81]}]}]}}})
        self.assertTrue(case.evaluator.evaluate(submission).success)
        metric = formula_metric(submission, spec, "historical")
        self.assertEqual(metric["status"], "not_equivalent")
        self.assertEqual(metric["method"], "numerical_counterexample")


if __name__ == "__main__":
    unittest.main()
