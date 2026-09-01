import math
import unittest

from role_benchmark import (
    BenchmarkTrack,
    EXPRESSION_MODEL,
    ExpressionError,
    FinalSubmission,
    evaluate_expression_program,
)
from role_benchmark.cases import make_pendulum_case


def pendulum_expression(mass_exponent):
    return {
        "outputs": {
            "period_s": {
                "op": "multiply",
                "args": [
                    2.0 * math.pi * math.sqrt(1.0 / 9.80665),
                    {
                        "op": "power",
                        "args": [{"var": "length_m"}, 0.5],
                    },
                    {
                        "op": "power",
                        "args": [
                            {
                                "op": "divide",
                                "args": [{"var": "bob_mass_kg"}, 0.20],
                            },
                            mass_exponent,
                        ],
                    },
                ],
            }
        }
    }


class PendulumDiscoveryTest(unittest.TestCase):
    def test_tracks_share_world_but_not_the_information_contract(self):
        identification = make_pendulum_case(
            "counterfactual", BenchmarkTrack.IDENTIFICATION
        )
        discovery = make_pendulum_case(
            "counterfactual", BenchmarkTrack.DISCOVERY
        )

        self.assertEqual(identification.definition.case_id, discovery.definition.case_id)
        self.assertEqual(identification.definition.background, discovery.definition.background)
        self.assertEqual(
            identification.definition.resources.controls,
            discovery.definition.resources.controls,
        )
        identification_notes = " ".join(identification.definition.resources.notes)
        discovery_notes = " ".join(discovery.definition.resources.notes)
        self.assertIn("normalized_power_law", identification_notes)
        self.assertIn(EXPRESSION_MODEL, discovery_notes)
        self.assertNotIn("normalized_power_law", discovery_notes)
        self.assertNotIn("length_exponent", discovery_notes)
        self.assertNotIn("mass_exponent", discovery_notes)

    def test_family_neutral_expression_passes_both_private_worlds(self):
        for world, mass_exponent in (("historical", 0.0), ("counterfactual", 0.25)):
            with self.subTest(world=world):
                case = make_pendulum_case(world, BenchmarkTrack.DISCOVERY)
                result = case.evaluator.evaluate(
                    FinalSubmission(
                        explanation="An executable expression predicts the period.",
                        model=EXPRESSION_MODEL,
                        parameters=pendulum_expression(mass_exponent),
                    )
                )
                self.assertTrue(result.success)
                self.assertEqual(result.scores["predictive_model_pass"], 1.0)
                self.assertNotIn("mass_exponent_absolute_error", result.scores)

    def test_expression_contract_is_strict_and_supports_track_wide_unary_ops(self):
        program = {
            "outputs": {
                "y": {
                    "op": "log",
                    "args": [
                        {"op": "exp", "args": [{"var": "x"}]},
                    ],
                }
            }
        }
        outputs = evaluate_expression_program(
            program,
            {"x": 2.0},
            allowed_variables=("x",),
            required_outputs=("y",),
        )
        self.assertAlmostEqual(outputs["y"], 2.0)

        with self.assertRaises(ExpressionError):
            evaluate_expression_program(
                {"outputs": {"y": {"var": "private_truth"}}},
                {"x": 2.0},
                allowed_variables=("x",),
                required_outputs=("y",),
            )


if __name__ == "__main__":
    unittest.main()
