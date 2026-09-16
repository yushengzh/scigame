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
    AUTHORED_TEMPORAL_COUNTERFACTUAL_FAMILIES,
    AUTHORED_TEMPORAL_COUNTERFACTUAL_NOTE,
    make_authored_temporal_counterfactual_variants,
    make_counterfactual_variant,
    rms_symmetric_tolerance_scaled_separation,
)
from role_benchmark.models import BenchmarkTrack
from role_benchmark.temporal_cases import TEMPORAL_CASE_SPECS


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

    def test_temporal_variants_are_separate_authored_pairs_for_four_families(self):
        expected_families = {
            "self_similar_spreading_radius_ratio",
            "stealthy_hyperuniform_localization_scaling",
            "uamo_lyapunov",
            "statistical_mean_field_effective_detuning",
        }
        self.assertEqual(
            AUTHORED_TEMPORAL_COUNTERFACTUAL_FAMILIES,
            expected_families,
        )

        for family in sorted(expected_families):
            source = TEMPORAL_CASE_SPECS[family]
            source_historical = source.truths["historical"]
            source_counterfactual = source.truths["counterfactual"]
            source_truths = source.truths
            with self.subTest(family=family):
                variants = make_authored_temporal_counterfactual_variants(source)
                easy = variants["easy"]
                hard = variants["hard"]

                self.assertIs(TEMPORAL_CASE_SPECS[family], source)
                self.assertIs(source.truths, source_truths)
                self.assertIs(source.truths["historical"], source_historical)
                self.assertIs(source.truths["counterfactual"], source_counterfactual)
                self.assertEqual(easy.counterfactual_fraction, 0.75)
                self.assertEqual(hard.counterfactual_fraction, 0.5)

                parameter = _changed_key(
                    source_historical.parameters,
                    source_counterfactual.parameters,
                )
                historical_value = float(source_historical.parameters[parameter])
                source_value = float(source_counterfactual.parameters[parameter])
                for variant, fraction in ((easy, 0.75), (hard, 0.5)):
                    counterfactual = variant.spec.truths["counterfactual"]
                    self.assertIs(
                        variant.spec.truths["historical"], source_historical
                    )
                    self.assertAlmostEqual(
                        counterfactual.parameters[parameter],
                        historical_value + fraction * (source_value - historical_value),
                    )
                    self.assertIn(
                        AUTHORED_TEMPORAL_COUNTERFACTUAL_NOTE,
                        variant.spec.common_notes,
                    )
                    self.assertIn(
                        "not a source-reported condition",
                        variant.spec.counterfactual_change,
                    )
                    self.assert_experimental_contract_unchanged(
                        source, variant.spec
                    )
                    self.assertEqual(
                        _formula_structure(
                            counterfactual.discovery_outputs
                        ),
                        _formula_structure(
                            source_counterfactual.discovery_outputs
                        ),
                    )
                    self.assert_truth_submissions_pass(variant.spec)

                historical_identification = source_historical.identification_values
                source_identification = source_counterfactual.identification_values
                self.assertIsNotNone(historical_identification)
                self.assertIsNotNone(source_identification)
                identification_parameter = _changed_key(
                    historical_identification,
                    source_identification,
                )
                historical_identification_value = float(
                    historical_identification[identification_parameter]
                )
                source_identification_value = float(
                    source_identification[identification_parameter]
                )
                for variant, fraction in ((easy, 0.75), (hard, 0.5)):
                    value = variant.spec.truths[
                        "counterfactual"
                    ].identification_values[identification_parameter]
                    self.assertAlmostEqual(
                        value,
                        historical_identification_value
                        + fraction
                        * (
                            source_identification_value
                            - historical_identification_value
                        ),
                    )

                self.assertGreater(
                    easy.fixed_design_separation,
                    hard.fixed_design_separation,
                )
                self.assertGreater(hard.fixed_design_separation, 0.0)

    def test_discrete_temporal_source_pairs_are_not_eligible(self):
        for family in (
            "kz_incompressible_energy_temperature_regimes",
            "viscous_inertial_rheology",
            "rilw_msd_scaling",
            "defect_sre",
            "trxas_lorentzian_fit",
        ):
            with self.subTest(family=family):
                with self.assertRaisesRegex(
                    ValueError, "four continuous-coordinate families"
                ):
                    make_authored_temporal_counterfactual_variants(
                        TEMPORAL_CASE_SPECS[family]
                    )


if __name__ == "__main__":
    unittest.main()
