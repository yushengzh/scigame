import unittest

from role_benchmark import (
    BenchmarkTrack,
    CaseOracle,
    EXPRESSION_MODEL,
    ExperimentProposal,
    FinalSubmission,
    OracleStatus,
)
from role_benchmark.cases import YOUNG_DOUBLE_SLIT_SPEC, make_young_double_slit_case
from role_benchmark.cases.matched import truth_submission


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
        replicates=1,
        forecasts={
            "H1": {"fringe_spacing_mm": 0.44},
            "H2": {"fringe_spacing_mm": 0.62},
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
            "historical.young_double_slit.instance_2.identification",
        )
        self.assertEqual(
            cases[("counterfactual", BenchmarkTrack.IDENTIFICATION)].definition.case_id,
            "historical.young_double_slit.instance_1.identification",
        )
        for world in WORLDS:
            identification = cases[(world, BenchmarkTrack.IDENTIFICATION)].definition
            discovery = cases[(world, BenchmarkTrack.DISCOVERY)].definition
            self.assertEqual(identification.case_id.rsplit(".", 1)[0],
                             discovery.case_id.rsplit(".", 1)[0])
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
            "counterfactual_selector",
            "branch_0=",
            "branch_1=",
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

    def test_one_expression_predictor_and_score_path_serves_both_tracks(self):
        for world in WORLDS:
            submission = truth_submission(YOUNG_DOUBLE_SLIT_SPEC, world,
                                          BenchmarkTrack.DISCOVERY)
            results = []
            for track in TRACKS:
                with self.subTest(world=world, track=track.value):
                    case = make_young_double_slit_case(world=world, track=track)
                    result = case.evaluator.evaluate(submission)
                    results.append(result)
                    self.assertTrue(result.success)
                    self.assertEqual(result.scores["predictive_model_pass"], 1.0)
                    self.assertNotIn(
                        "slit_separation_exponent_absolute_error",
                        result.scores,
                    )
            self.assertEqual(results[0], results[1])

    def test_legacy_identification_representation_is_rejected(self):
        for track in TRACKS:
            with self.subTest(track=track.value):
                case = make_young_double_slit_case(track=track)
                result = case.evaluator.evaluate(
                    FinalSubmission(
                        explanation="A legacy named-parameter predictor.",
                        model="double_slit_power_law",
                        parameters={
                            "reference_spacing_mm": 1.10,
                            "wavelength_exponent": 1.0,
                            "screen_distance_exponent": 1.0,
                            "slit_separation_exponent": -1.0,
                        },
                    )
                )
                self.assertFalse(result.success)
                self.assertIn("executable expression representation", result.message)

    def test_each_world_rejects_the_other_worlds_law(self):
        for world, other_world in (("historical", "counterfactual"),
                                   ("counterfactual", "historical")):
            submission = truth_submission(YOUNG_DOUBLE_SLIT_SPEC, other_world,
                                          BenchmarkTrack.DISCOVERY)
            for track in TRACKS:
                with self.subTest(world=world, track=track.value):
                    case = make_young_double_slit_case(world=world, track=track)
                    result = case.evaluator.evaluate(submission)
                    self.assertFalse(result.success)
                    self.assertEqual(result.scores["predictive_model_pass"], 0.0)

    def test_historical_simple_law_passes_and_retired_parameter_twin_fails(self):
        for world, exponent, expected in (("historical", -1.0, True),
                                           ("counterfactual", -0.5, False)):
            with self.subTest(world=world):
                result = make_young_double_slit_case(world=world).evaluator.evaluate(
                    expression_submission(exponent)
                )
                self.assertEqual(result.success, expected)

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
                explanation="A legacy named-parameter submission.",
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
