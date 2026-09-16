import math
import unittest
from numbers import Real

from role_benchmark.cases import CASE_SPECS
from role_benchmark.cases.matched import (
    MATCHED_WORLDS,
    make_matched_case,
    truth_submission,
)
from role_benchmark.counterfactual import (
    make_counterfactual_variant,
    rms_symmetric_tolerance_scaled_separation,
)
from role_benchmark.models import BenchmarkTrack


TRACKS = (BenchmarkTrack.IDENTIFICATION, BenchmarkTrack.DISCOVERY)


def _formula_structure(value):
    if isinstance(value, Real) and not isinstance(value, bool):
        return "number"
    if isinstance(value, dict):
        return {key: _formula_structure(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_formula_structure(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_formula_structure(item) for item in value)
    return value


def _changed_key(left, right):
    changed = tuple(name for name in left if left[name] != right[name])
    if len(changed) != 1:
        raise AssertionError("expected one changed parameter")
    return changed[0]


class CounterfactualVariantTests(unittest.TestCase):
    def assert_experimental_contract_unchanged(self, source, variant):
        self.assertEqual(variant.family, source.family)
        self.assertEqual(variant.case_id_prefix, source.case_id_prefix)
        self.assertEqual(variant.controls, source.controls)
        self.assertEqual(variant.readouts, source.readouts)
        self.assertEqual(variant.diagnostic_conditions, source.diagnostic_conditions)
        self.assertEqual(variant.hidden_conditions, source.hidden_conditions)
        self.assertEqual(
            variant.common_fixed_conditions,
            source.common_fixed_conditions,
        )
        self.assertEqual(variant.budget, source.budget)
        self.assertEqual(variant.max_replicates, source.max_replicates)
        self.assertEqual(variant.confidence_threshold, source.confidence_threshold)
        self.assertEqual(variant.relative_tolerance, source.relative_tolerance)
        self.assertEqual(variant.absolute_tolerances, source.absolute_tolerances)
        self.assertIs(variant.predict, source.predict)
        self.assertIs(variant.identification_predict, source.identification_predict)

    def assert_truth_submissions_pass(self, spec):
        for world in MATCHED_WORLDS:
            for track in TRACKS:
                case = make_matched_case(spec, world, track)
                result = case.evaluator.evaluate(
                    truth_submission(spec, world, track)
                )
                self.assertTrue(result.success, (spec.family, world, track))

    def test_structural_historical_relations_do_not_support_parameter_interpolation(self):
        for family, source in CASE_SPECS.items():
            with self.subTest(family=family):
                # This operation requires aligned expression trees. Structural
                # siblings are authored laws, not endpoints on that parameter path.
                with self.assertRaisesRegex(ValueError, "structures differ"):
                    make_counterfactual_variant(
                        source, "hard", counterfactual_fraction=0.5,
                    )

    def test_separation_is_symmetric_and_uses_the_fixed_design_by_default(self):
        spec = CASE_SPECS["pendulum"]
        historical = spec.truths["historical"]
        counterfactual = spec.truths["counterfactual"]
        forward = rms_symmetric_tolerance_scaled_separation(spec)
        reverse = rms_symmetric_tolerance_scaled_separation(
            spec,
            counterfactual,
            historical,
        )
        explicit = rms_symmetric_tolerance_scaled_separation(
            spec,
            conditions=spec.diagnostic_conditions,
        )
        self.assertTrue(math.isfinite(forward))
        self.assertAlmostEqual(forward, reverse)
        self.assertAlmostEqual(forward, explicit)



if __name__ == "__main__":
    unittest.main()
