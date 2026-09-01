import unittest

from role_benchmark import (
    BenchmarkTrack,
    Episode,
    ExperimentProposal,
    OracleStatus,
    FinalSubmission,
    Hypothesis,
    HypothesisPortfolio,
    PlayerAction,
    CaseOracle,
)
from role_benchmark.cases import (
    BOYLE_J_TUBE_SPEC,
    CASE_FAMILIES,
    GALILEO_INCLINED_PLANE_SPEC,
    PHOTOELECTRIC_SPEC,
    make_boyle_j_tube_case,
    make_case,
    make_galileo_inclined_plane_case,
    make_photoelectric_case,
)


def confident_portfolio():
    return HypothesisPortfolio(
        (
            Hypothesis("H1", "A quantitative law fits the observations.", 0.95),
            Hypothesis("H2", "The measured response is constant.", 0.05),
        )
    )


def galileo_proposal(distance=1.0, angle=5.0, mass=0.2):
    return ExperimentProposal(
        intent="Compare descent duration using the water clock.",
        apparatus="inclined_plane_water_clock",
        controls={
            "distance_m": distance,
            "incline_angle_deg": angle,
            "ball_mass_kg": mass,
        },
        readouts=("collected_water_g",),
        replicates=4,
        forecasts={
            "H1": {"collected_water_g": 24.0},
            "H2": {"collected_water_g": 12.0},
        },
    )


def boyle_proposal(added_pressure=0.0, readouts=("air_volume_ml",)):
    return ExperimentProposal(
        intent="Compress the trapped air at a fixed thermal condition.",
        apparatus="sealed_j_tube",
        controls={
            "added_pressure_kpa": added_pressure,
            "thermal_condition": "constant_room_temperature",
        },
        readouts=readouts,
        replicates=3,
        forecasts={
            "H1": {readout: 48.0 for readout in readouts},
            "H2": {readout: 24.0 for readout in readouts},
        },
    )


def photoelectric_proposal(
    frequency=800.0,
    absorbed_flux=1.0,
    readouts=("stopping_potential_v", "saturation_current_ua"),
):
    return ExperimentProposal(
        intent="Compare photoemission while controlling frequency and absorbed photon flux.",
        apparatus="vacuum_phototube",
        controls={
            "frequency_thz": frequency,
            "absorbed_photon_flux_relative": absorbed_flux,
        },
        readouts=readouts,
        replicates=5,
        forecasts={
            "H1": {readout: 1.0 for readout in readouts},
            "H2": {readout: 0.0 for readout in readouts},
        },
    )


def correct_galileo_submission(explanation="Uniform acceleration fits the data."):
    return FinalSubmission(
        hypothesis_id="H1",
        explanation=explanation,
        model="inclined_plane_power_law",
        parameters={
            "reference_water_mass_g": 24.0,
            "distance_exponent": 0.5,
            "sine_angle_exponent": -0.5,
            "mass_exponent": 0.0,
        },
    )


def correct_boyle_submission(explanation="Pressure and volume vary inversely."):
    return FinalSubmission(
        hypothesis_id="H1",
        explanation=explanation,
        model="boyle_inverse_law",
        parameters={
            "reference_volume_ml": 48.0,
            "ambient_pressure_kpa": 101.3,
            "pressure_exponent": -1.0,
        },
    )


def correct_photoelectric_submission(
    explanation="Frequency sets electron energy; absorbed photon flux sets their number.",
):
    return FinalSubmission(
        hypothesis_id="H1",
        explanation=explanation,
        model="einstein_photoelectric_law",
        parameters={
            "h_over_e_v_s": 4.135667696e-15,
            "work_function_equivalent_v": 2.28,
            "reference_saturation_current_ua": 3.0,
        },
    )


class HistoricalCaseRegistryTest(unittest.TestCase):
    def test_registry_builds_fresh_cases_and_rejects_unknown_names(self):
        self.assertEqual(len(CASE_FAMILIES), 20)
        first = [make_case(name) for name in CASE_FAMILIES]
        second = [make_case(name) for name in CASE_FAMILIES]
        self.assertEqual(len({case.definition.case_id for case in first}), 20)
        for left, right in zip(first, second):
            self.assertIs(left.definition.track, BenchmarkTrack.IDENTIFICATION)
            self.assertIsNot(left, right)
            self.assertIsNot(left.world_model, right.world_model)
            self.assertIsNot(left.evaluator, right.evaluator)
        with self.assertRaises(ValueError):
            make_case("unknown")
        with self.assertRaises(ValueError):
            make_case(None)


class HistoricalWorldModelTest(unittest.TestCase):
    def test_corrected_public_scientific_contracts_are_explicit(self):
        self.assertIn(
            "(distance_m / 1 m)",
            GALILEO_INCLINED_PLANE_SPEC.identification_formula,
        )
        galileo_notes = " ".join(GALILEO_INCLINED_PLANE_SPEC.common_notes)
        self.assertIn("from rest", galileo_notes)
        self.assertIn("geometrically similar", galileo_notes)

        boyle_credit = " ".join(
            credit.citation for credit in BOYLE_J_TUBE_SPEC.credits
        )
        self.assertIn("1661", boyle_credit)
        self.assertNotIn("1660", boyle_credit)
        boyle_volume = next(
            readout
            for readout in BOYLE_J_TUBE_SPEC.readouts
            if readout.name == "air_volume_ml"
        )
        self.assertIn("total volume", boyle_volume.description)
        self.assertIn("fixed end-space", boyle_volume.description)
        historical_boyle_scope = " ".join(
            BOYLE_J_TUBE_SPEC.truths["historical"].applicability
            + BOYLE_J_TUBE_SPEC.truths["historical"].fixed_conditions
        )
        self.assertIn("ideal-gas limit", historical_boyle_scope)
        self.assertIn("adsorption", historical_boyle_scope)
        self.assertIn(
            "not asserted to be an ideal gas",
            " ".join(BOYLE_J_TUBE_SPEC.truths["counterfactual"].applicability),
        )

        photo_controls = {
            control.name for control in PHOTOELECTRIC_SPEC.controls
        }
        self.assertIn("absorbed_photon_flux_relative", photo_controls)
        self.assertNotIn("intensity_relative", photo_controls)
        photo_parameters = set(PHOTOELECTRIC_SPEC.identification_parameters)
        self.assertIn("work_function_equivalent_v", photo_parameters)
        self.assertNotIn("work_function_ev", photo_parameters)
        photo_notes = " ".join(PHOTOELECTRIC_SPEC.common_notes)
        self.assertNotIn("frequency-independent quantum yield", photo_notes)
        self.assertNotIn("collects every emitted electron", photo_notes)
        for truth in PHOTOELECTRIC_SPEC.truths.values():
            private_scope = " ".join(truth.applicability + truth.fixed_conditions)
            self.assertIn("single-photon photoemission", private_scope)
            self.assertIn("frequency-independent emission yield", private_scope)
            self.assertIn("collects every emitted electron", private_scope)

    def test_galileo_distance_square_root_and_mass_independence(self):
        case = make_galileo_inclined_plane_case()
        oracle = CaseOracle(case.definition, case.world_model)
        reference = oracle.respond(galileo_proposal(distance=1.0, mass=0.2))
        long_run = oracle.respond(galileo_proposal(distance=4.0, mass=0.2))
        heavy = oracle.respond(galileo_proposal(distance=1.0, mass=0.5))

        self.assertEqual(reference.status, OracleStatus.VALID)
        reference_water = reference.evidence.measurements["collected_water_g"]
        long_water = long_run.evidence.measurements["collected_water_g"]
        heavy_water = heavy.evidence.measurements["collected_water_g"]
        self.assertAlmostEqual(long_water / reference_water, 2.0, delta=0.01)
        self.assertEqual(heavy_water, reference_water)

    def test_boyle_supports_readout_subsets_and_inverse_relation(self):
        case = make_boyle_j_tube_case()
        oracle = CaseOracle(case.definition, case.world_model)
        reference = oracle.respond(
            boyle_proposal(
                added_pressure=0.0,
                readouts=("air_volume_ml", "absolute_pressure_kpa"),
            )
        )
        doubled_pressure = oracle.respond(boyle_proposal(added_pressure=101.3))

        self.assertEqual(reference.status, OracleStatus.VALID)
        self.assertEqual(
            set(reference.evidence.measurements),
            {"air_volume_ml", "absolute_pressure_kpa"},
        )
        self.assertEqual(reference.evidence.measurements["air_volume_ml"], 48.0)
        self.assertEqual(
            reference.evidence.measurements["absolute_pressure_kpa"], 101.3
        )
        self.assertEqual(
            doubled_pressure.evidence.measurements["air_volume_ml"], 24.0
        )

        invalid = boyle_proposal()
        invalid.controls["thermal_condition"] = "warming"
        response = oracle.respond(invalid)
        self.assertEqual(response.status, OracleStatus.OUT_OF_RANGE)

    def test_photoelectric_case_has_threshold_and_separates_absorbed_flux(self):
        case = make_photoelectric_case()
        oracle = CaseOracle(case.definition, case.world_model)
        below = oracle.respond(photoelectric_proposal(frequency=500.0, absorbed_flux=2.0))
        above = oracle.respond(photoelectric_proposal(frequency=800.0, absorbed_flux=1.0))
        brighter = oracle.respond(
            photoelectric_proposal(frequency=800.0, absorbed_flux=2.0)
        )

        self.assertEqual(below.status, OracleStatus.VALID)
        self.assertEqual(
            below.evidence.measurements,
            {"stopping_potential_v": 0.0, "saturation_current_ua": 0.0},
        )
        self.assertEqual(
            above.evidence.measurements["stopping_potential_v"], 1.03
        )
        self.assertEqual(
            brighter.evidence.measurements["stopping_potential_v"], 1.03
        )
        self.assertEqual(above.evidence.measurements["saturation_current_ua"], 3.0)
        self.assertEqual(
            brighter.evidence.measurements["saturation_current_ua"], 6.0
        )


class HistoricalEvaluatorTest(unittest.TestCase):
    def test_each_structured_truth_passes_its_hidden_conditions(self):
        cases_and_submissions = (
            (make_galileo_inclined_plane_case(), correct_galileo_submission()),
            (make_boyle_j_tube_case(), correct_boyle_submission()),
            (make_photoelectric_case(), correct_photoelectric_submission()),
        )
        for case, submission in cases_and_submissions:
            with self.subTest(case_id=case.definition.case_id):
                result = case.evaluator.evaluate(submission)
                self.assertTrue(result.success)
                self.assertEqual(result.scores["predictive_model_pass"], 1.0)
                self.assertEqual(
                    bool(result.scores["predictive_model_pass"]),
                    result.success,
                )
                self.assertNotIn("explanation_correct", result.scores)

    def test_each_structured_evaluator_uses_predictive_name_on_failure(self):
        cases = (
            make_galileo_inclined_plane_case(),
            make_boyle_j_tube_case(),
            make_photoelectric_case(),
        )
        for case in cases:
            with self.subTest(case_id=case.definition.case_id):
                result = case.evaluator.evaluate(
                    FinalSubmission(
                        explanation="An unsupported predictor.",
                        model="unsupported",
                    )
                )
                self.assertFalse(result.success)
                self.assertEqual(result.scores["predictive_model_pass"], 0.0)
                self.assertNotIn("explanation_correct", result.scores)

    def test_existing_protocol_scores_parameters_not_explanatory_prose(self):
        case = make_photoelectric_case()
        submission = correct_photoelectric_submission(
            explanation=(
                "Incorrect on purpose: absorbed photon flux determines electron energy and "
                "frequency has no effect."
            )
        )
        result = case.evaluator.evaluate(submission)
        self.assertTrue(result.success)
        self.assertEqual(result.scores["predictive_model_pass"], 1.0)

    def test_new_case_evaluators_turn_huge_parameters_into_failures(self):
        case = make_galileo_inclined_plane_case()
        submission = FinalSubmission(
            explanation="An invalid numeric model.",
            model="inclined_plane_power_law",
            parameters={
                "reference_water_mass_g": 10**10000,
                "distance_exponent": 0.5,
                "sine_angle_exponent": -0.5,
                "mass_exponent": 0.0,
            },
        )
        result = case.evaluator.evaluate(submission)
        self.assertFalse(result.success)
        self.assertIn("finite", result.message)

    def test_each_case_runs_through_the_unchanged_episode_protocol(self):
        cases_actions = (
            (
                make_galileo_inclined_plane_case(),
                galileo_proposal(),
                correct_galileo_submission(),
            ),
            (
                make_boyle_j_tube_case(),
                boyle_proposal(),
                correct_boyle_submission(),
            ),
            (
                make_photoelectric_case(),
                photoelectric_proposal(),
                correct_photoelectric_submission(),
            ),
        )
        portfolio = confident_portfolio()
        for case, proposal, submission in cases_actions:
            with self.subTest(case_id=case.definition.case_id):
                episode = Episode(case)
                response = episode.apply(
                    PlayerAction.propose_experiment(portfolio, proposal)
                )
                self.assertEqual(response.status, OracleStatus.VALID)
                episode.apply(PlayerAction.submit_final(portfolio, submission))
                self.assertTrue(episode.result.evaluation.success)
                self.assertEqual(episode.result.attempts_used, 1)


if __name__ == "__main__":
    unittest.main()
