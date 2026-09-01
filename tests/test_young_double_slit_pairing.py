import unittest

from role_benchmark import (
    BenchmarkTrack,
    CaseOracle,
    EXPRESSION_MODEL,
    ExperimentProposal,
    FinalSubmission,
    OracleStatus,
)
from role_benchmark.cases import make_young_double_slit_case


WORLDS = ("historical", "counterfactual")
TRACKS = (BenchmarkTrack.IDENTIFICATION, BenchmarkTrack.DISCOVERY)


def young_proposal(
    wavelength_nm=440.0,
    screen_distance_m=1.0,
    slit_separation_mm=1.0,
):
    return ExperimentProposal(
        intent="Compare competing fringe-spacing laws.",
        apparatus="double_slit_screen",
        controls={
            "wavelength_nm": wavelength_nm,
            "screen_distance_m": screen_distance_m,
            "slit_separation_mm": slit_separation_mm,
        },
        readouts=("fringe_spacing_mm",),
        replicates=4,
        forecasts={
            "H1": {"fringe_spacing_mm": 0.44},
            "H2": {"fringe_spacing_mm": 0.62},
        },
    )


def identification_submission(slit_separation_exponent):
    return FinalSubmission(
        explanation="A normalized power law predicts held-out fringe spacing.",
        model="double_slit_power_law",
        parameters={
            "reference_spacing_mm": 1.10,
            "wavelength_exponent": 1.0,
            "screen_distance_exponent": 1.0,
            "slit_separation_exponent": slit_separation_exponent,
        },
    )


def expression_submission(slit_separation_exponent):
    expression = {
        "op": "multiply",
        "args": [
            1.10,
            {
                "op": "power",
                "args": [
                    {
                        "op": "divide",
                        "args": [{"var": "wavelength_nm"}, 550.0],
                    },
                    1.0,
                ],
            },
            {
                "op": "power",
                "args": [
                    {
                        "op": "divide",
                        "args": [{"var": "screen_distance_m"}, 1.0],
                    },
                    1.0,
                ],
            },
            {
                "op": "power",
                "args": [
                    {
                        "op": "divide",
                        "args": [{"var": "slit_separation_mm"}, 0.50],
                    },
                    slit_separation_exponent,
                ],
            },
        ],
    }
    return FinalSubmission(
        explanation="An arithmetic expression predicts held-out fringe spacing.",
        model=EXPRESSION_MODEL,
        parameters={"outputs": {"fringe_spacing_mm": expression}},
    )


class YoungDoubleSlitPairingTest(unittest.TestCase):
    def test_four_cells_hold_public_pairing_invariants(self):
        cases = {
            (world, track): make_young_double_slit_case(world=world, track=track)
            for world in WORLDS
            for track in TRACKS
        }
        self.assertEqual(len(cases), 4)

        for track in TRACKS:
            historical = cases[("historical", track)].definition
            counterfactual = cases[("counterfactual", track)].definition
            self.assertEqual(historical.background, counterfactual.background)
            self.assertEqual(
                historical.initial_observations,
                counterfactual.initial_observations,
            )
            self.assertEqual(historical.resources, counterfactual.resources)
            self.assertEqual(historical.budget, counterfactual.budget)
            self.assertEqual(
                historical.confidence_threshold,
                counterfactual.confidence_threshold,
            )

        self.assertEqual(
            cases[("historical", BenchmarkTrack.IDENTIFICATION)].definition.case_id,
            "optical.interference.instance_2",
        )
        self.assertEqual(
            cases[("counterfactual", BenchmarkTrack.IDENTIFICATION)].definition.case_id,
            "optical.interference.instance_1",
        )
        for world in WORLDS:
            identification = cases[(world, BenchmarkTrack.IDENTIFICATION)].definition
            discovery = cases[(world, BenchmarkTrack.DISCOVERY)].definition
            self.assertEqual(identification.case_id, discovery.case_id)
            self.assertEqual(identification.background, discovery.background)
            self.assertEqual(
                identification.initial_observations,
                discovery.initial_observations,
            )
            self.assertEqual(
                identification.resources.instruments,
                discovery.resources.instruments,
            )
            self.assertEqual(
                identification.resources.controls,
                discovery.resources.controls,
            )
            self.assertEqual(
                identification.resources.readouts,
                discovery.resources.readouts,
            )
            self.assertEqual(
                identification.resources.max_replicates,
                discovery.resources.max_replicates,
            )
            self.assertEqual(identification.budget, discovery.budget)

    def test_tracks_share_authoritative_evidence_within_each_world(self):
        proposal = young_proposal()
        measurements = {}
        for world in WORLDS:
            for track in TRACKS:
                case = make_young_double_slit_case(world=world, track=track)
                response = CaseOracle(case.definition, case.world_model).respond(
                    proposal
                )
                self.assertEqual(response.status, OracleStatus.VALID)
                measurements[(world, track)] = response.evidence

            self.assertEqual(
                measurements[(world, BenchmarkTrack.IDENTIFICATION)],
                measurements[(world, BenchmarkTrack.DISCOVERY)],
            )

        self.assertNotEqual(
            measurements[("historical", BenchmarkTrack.IDENTIFICATION)].measurements,
            measurements[
                ("counterfactual", BenchmarkTrack.IDENTIFICATION)
            ].measurements,
        )

    def test_discovery_contract_does_not_leak_private_family_or_world(self):
        forbidden = (
            "double_slit_power_law",
            "reference_spacing_mm",
            "wavelength_exponent",
            "screen_distance_exponent",
            "slit_separation_exponent",
            "historical",
            "counterfactual",
        )
        for world in WORLDS:
            definition = make_young_double_slit_case(
                world=world,
                track=BenchmarkTrack.DISCOVERY,
            ).definition
            public_text = " ".join(
                (
                    definition.case_id,
                    definition.title,
                    definition.background,
                    *definition.initial_observations,
                    *definition.resources.notes,
                )
            ).lower()
            self.assertIn(EXPRESSION_MODEL, public_text)
            for token in forbidden:
                with self.subTest(world=world, token=token):
                    self.assertNotIn(token, public_text)

    def test_correct_identification_and_expression_models_pass(self):
        exponents = {"historical": -1.0, "counterfactual": -0.5}
        for world, exponent in exponents.items():
            with self.subTest(world=world, track="identification"):
                case = make_young_double_slit_case(
                    world=world,
                    track=BenchmarkTrack.IDENTIFICATION,
                )
                result = case.evaluator.evaluate(
                    identification_submission(exponent)
                )
                self.assertTrue(result.success)
                self.assertEqual(result.scores["predictive_model_pass"], 1.0)
                self.assertEqual(
                    result.scores["slit_separation_exponent_absolute_error"],
                    0.0,
                )

            with self.subTest(world=world, track="discovery"):
                case = make_young_double_slit_case(
                    world=world,
                    track=BenchmarkTrack.DISCOVERY,
                )
                result = case.evaluator.evaluate(expression_submission(exponent))
                self.assertTrue(result.success)
                self.assertEqual(result.scores["predictive_model_pass"], 1.0)
                self.assertNotIn(
                    "slit_separation_exponent_absolute_error",
                    result.scores,
                )

    def test_each_world_rejects_the_other_worlds_law(self):
        pairs = (
            ("historical", -0.5),
            ("counterfactual", -1.0),
        )
        for world, false_exponent in pairs:
            for track, submission in (
                (
                    BenchmarkTrack.IDENTIFICATION,
                    identification_submission(false_exponent),
                ),
                (
                    BenchmarkTrack.DISCOVERY,
                    expression_submission(false_exponent),
                ),
            ):
                with self.subTest(world=world, track=track.value):
                    case = make_young_double_slit_case(world=world, track=track)
                    result = case.evaluator.evaluate(submission)
                    self.assertFalse(result.success)
                    self.assertEqual(result.scores["predictive_model_pass"], 0.0)

    def test_invalid_factory_and_submission_parameters_fail_cleanly(self):
        with self.assertRaises(ValueError):
            make_young_double_slit_case(world="unknown")
        with self.assertRaises(ValueError):
            make_young_double_slit_case(track="discovery")

        identification = make_young_double_slit_case(
            track=BenchmarkTrack.IDENTIFICATION
        )
        invalid_identification = identification.evaluator.evaluate(
            FinalSubmission(
                explanation="A required parameter is missing.",
                model="double_slit_power_law",
                parameters={
                    "reference_spacing_mm": 1.10,
                    "wavelength_exponent": 1.0,
                    "screen_distance_exponent": 1.0,
                },
            )
        )
        self.assertFalse(invalid_identification.success)

        discovery = make_young_double_slit_case(track=BenchmarkTrack.DISCOVERY)
        invalid_discovery = discovery.evaluator.evaluate(
            FinalSubmission(
                explanation="The expression refers to a private variable.",
                model=EXPRESSION_MODEL,
                parameters={
                    "outputs": {
                        "fringe_spacing_mm": {"var": "private_truth"},
                    }
                },
            )
        )
        self.assertFalse(invalid_discovery.success)
        self.assertEqual(
            invalid_discovery.scores["predictive_model_pass"],
            0.0,
        )


if __name__ == "__main__":
    unittest.main()
