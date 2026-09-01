import unittest

from role_benchmark import (
    CaseOracle,
    Episode,
    ExperimentProposal,
    FinalSubmission,
    Hypothesis,
    HypothesisPortfolio,
    OracleStatus,
    PlayerAction,
)
from role_benchmark.cases import (
    FARADAY_INDUCTION_SPEC,
    RADIOACTIVE_DECAY_SPEC,
    RUTHERFORD_SCATTERING_SPEC,
    YOUNG_DOUBLE_SLIT_SPEC,
    make_faraday_induction_case,
    make_radioactive_decay_case,
    make_rutherford_scattering_case,
    make_young_double_slit_case,
)


def confident_portfolio():
    return HypothesisPortfolio(
        (
            Hypothesis("H1", "A quantitative law fits the observations.", 0.95),
            Hypothesis("H2", "A different quantitative dependence fits.", 0.05),
        )
    )


def young_proposal(wavelength=550.0, distance=1.0, separation=0.5):
    return ExperimentProposal(
        intent="Measure how the bright-fringe spacing changes.",
        apparatus="double_slit_screen",
        controls={
            "wavelength_nm": wavelength,
            "screen_distance_m": distance,
            "slit_separation_mm": separation,
        },
        readouts=("fringe_spacing_mm",),
        replicates=4,
        forecasts={
            "H1": {"fringe_spacing_mm": 1.1},
            "H2": {"fringe_spacing_mm": 0.5},
        },
    )


def faraday_proposal(turns=100, area=20.0, field_change=10.0, change_time=100.0):
    return ExperimentProposal(
        intent="Measure the peak voltage during a controlled field ramp.",
        apparatus="induction_coil_galvanometer",
        controls={
            "coil_turns": turns,
            "loop_area_cm2": area,
            "field_change_mt": field_change,
            "change_time_ms": change_time,
        },
        readouts=("peak_emf_mv",),
        replicates=4,
        forecasts={
            "H1": {"peak_emf_mv": 20.0},
            "H2": {"peak_emf_mv": 10.0},
        },
    )


def decay_proposal(elapsed=0.0, mass=1.0):
    return ExperimentProposal(
        intent="Measure the activity after a controlled elapsed time.",
        apparatus="shielded_radiation_counter",
        controls={"elapsed_time_min": elapsed, "sample_mass_mg": mass},
        readouts=("count_rate_cpm",),
        replicates=5,
        forecasts={
            "H1": {"count_rate_cpm": 820.0},
            "H2": {"count_rate_cpm": 400.0},
        },
    )


def scattering_proposal(
    angle=60.0, atomic_number=79, areal_density=1.0, exposure=1.0
):
    return ExperimentProposal(
        intent="Measure the scattering rate at a selected detector angle.",
        apparatus="alpha_foil_scattering_scope",
        controls={
            "scattering_angle_deg": angle,
            "foil_atomic_number": atomic_number,
            "target_areal_number_density_relative": areal_density,
            "exposure_relative": exposure,
        },
        readouts=("scattered_count_rate_cpm",),
        replicates=5,
        forecasts={
            "H1": {"scattered_count_rate_cpm": 120.0},
            "H2": {"scattered_count_rate_cpm": 60.0},
        },
    )


def correct_young_submission():
    return FinalSubmission(
        hypothesis_id="H1",
        explanation="Fringe spacing follows the fitted geometric scaling.",
        model="double_slit_power_law",
        parameters={
            "reference_spacing_mm": 1.10,
            "wavelength_exponent": 1.0,
            "screen_distance_exponent": 1.0,
            "slit_separation_exponent": -1.0,
        },
    )


def correct_faraday_submission():
    return FinalSubmission(
        hypothesis_id="H1",
        explanation="Peak voltage follows the rate of magnetic-flux change.",
        model="faraday_flux_change_power_law",
        parameters={
            "reference_emf_mv": 20.0,
            "turn_exponent": 1.0,
            "area_exponent": 1.0,
            "field_change_exponent": 1.0,
            "change_time_exponent": -1.0,
        },
    )


def correct_decay_submission():
    return FinalSubmission(
        hypothesis_id="H1",
        explanation="Net activity halves after a fixed elapsed time.",
        model="single_exponential_decay",
        parameters={
            "background_cpm": 20.0,
            "reference_activity_cpm": 800.0,
            "half_life_min": 60.0,
            "mass_exponent": 1.0,
        },
    )


def correct_scattering_submission():
    return FinalSubmission(
        hypothesis_id="H1",
        explanation="The angular and foil dependences fit a central-scattering law.",
        model="rutherford_scattering_law",
        parameters={
            "reference_count_rate_cpm": 120.0,
            "atomic_number_exponent": 2.0,
            "areal_number_density_exponent": 1.0,
            "exposure_exponent": 1.0,
            "sine_half_angle_exponent": -4.0,
        },
    )


class AdditionalHistoricalWorldModelTest(unittest.TestCase):
    def test_corrected_public_scientific_assumptions_are_explicit(self):
        young_observations = " ".join(YOUNG_DOUBLE_SLIT_SPEC.initial_observations)
        self.assertIn("fine two-slit fringe train", young_observations)
        self.assertIn("single-slit diffraction envelope", young_observations)
        young_notes = " ".join(YOUNG_DOUBLE_SLIT_SPEC.common_notes)
        self.assertIn("mutually coherently", young_notes)
        self.assertIn("central paraxial", young_notes)
        self.assertIn("modern two-slit geometry", YOUNG_DOUBLE_SLIT_SPEC.credits[0].role)
        for truth in YOUNG_DOUBLE_SLIT_SPEC.truths.values():
            self.assertTrue(truth.applicability)
            self.assertTrue(truth.fixed_conditions)

        faraday_notes = " ".join(FARADAY_INDUCTION_SPEC.common_notes)
        self.assertIn("spatially uniform", faraday_notes)
        self.assertIn("constant rate", faraday_notes)

        decay_notes = " ".join(RADIOACTIVE_DECAY_SPEC.common_notes)
        self.assertIn("same source material", decay_notes)
        self.assertIn("effective collection", decay_notes)
        self.assertIn("not assumed away", decay_notes)
        self.assertNotIn("same initial specific activity", decay_notes)
        self.assertNotIn("Self-absorption and detector dead time are negligible", decay_notes)
        self.assertIn(
            "(sample_mass_mg/1 mg)",
            RADIOACTIVE_DECAY_SPEC.identification_formula,
        )
        self.assertIn(
            "1903",
            " ".join(
                credit.citation for credit in RADIOACTIVE_DECAY_SPEC.credits
            ),
        )
        historical_decay_scope = " ".join(
            RADIOACTIVE_DECAY_SPEC.truths["historical"].fixed_conditions
        )
        self.assertIn("Self-attenuation", historical_decay_scope)
        self.assertIn("counter dead time", historical_decay_scope)
        counterfactual_decay_scope = " ".join(
            RADIOACTIVE_DECAY_SPEC.truths["counterfactual"].fixed_conditions
        )
        self.assertIn("complete effective", counterfactual_decay_scope)

        scattering_control_specs = {
            control.name: control for control in RUTHERFORD_SCATTERING_SPEC.controls
        }
        scattering_controls = set(scattering_control_specs)
        self.assertIn(
            "target_areal_number_density_relative", scattering_controls
        )
        self.assertNotIn("foil_thickness_um", scattering_controls)
        self.assertIn(
            "flux rate",
            scattering_control_specs["exposure_relative"].description,
        )
        self.assertIn(
            "not accumulated fluence",
            " ".join(RUTHERFORD_SCATTERING_SPEC.common_notes),
        )
        scattering_parameters = set(
            RUTHERFORD_SCATTERING_SPEC.identification_parameters
        )
        self.assertIn("areal_number_density_exponent", scattering_parameters)
        self.assertNotIn("thickness_exponent", scattering_parameters)
        citations = " ".join(
            credit.citation for credit in RUTHERFORD_SCATTERING_SPEC.credits
        )
        self.assertIn("1911", citations)
        self.assertIn("1913", citations)
        historical_scattering_scope = " ".join(
            RUTHERFORD_SCATTERING_SPEC.truths["historical"].applicability
            + RUTHERFORD_SCATTERING_SPEC.truths["historical"].fixed_conditions
        )
        self.assertIn("unscreened Coulomb", historical_scattering_scope)
        self.assertIn("narrow enough", historical_scattering_scope)
        self.assertIn("recoil", historical_scattering_scope)

    def test_young_case_separates_distance_and_slit_spacing(self):
        case = make_young_double_slit_case()
        oracle = CaseOracle(case.definition, case.world_model)
        baseline = oracle.respond(young_proposal())
        distant = oracle.respond(young_proposal(distance=2.0))
        wider_slits = oracle.respond(young_proposal(separation=1.0))
        self.assertEqual(baseline.status, OracleStatus.VALID)
        self.assertEqual(baseline.evidence.measurements["fringe_spacing_mm"], 1.10)
        self.assertEqual(distant.evidence.measurements["fringe_spacing_mm"], 2.20)
        self.assertEqual(wider_slits.evidence.measurements["fringe_spacing_mm"], 0.55)

    def test_faraday_case_separates_turns_and_change_time(self):
        case = make_faraday_induction_case()
        oracle = CaseOracle(case.definition, case.world_model)
        baseline = oracle.respond(faraday_proposal())
        more_turns = oracle.respond(faraday_proposal(turns=200))
        slower = oracle.respond(faraday_proposal(change_time=200.0))
        self.assertEqual(baseline.evidence.measurements["peak_emf_mv"], 20.0)
        self.assertEqual(more_turns.evidence.measurements["peak_emf_mv"], 40.0)
        self.assertEqual(slower.evidence.measurements["peak_emf_mv"], 10.0)

    def test_decay_case_has_half_life_background_and_mass_scaling(self):
        case = make_radioactive_decay_case()
        oracle = CaseOracle(case.definition, case.world_model)
        start = oracle.respond(decay_proposal())
        half_life = oracle.respond(decay_proposal(elapsed=60.0))
        double_mass = oracle.respond(decay_proposal(mass=2.0))
        self.assertEqual(start.evidence.measurements["count_rate_cpm"], 820.0)
        self.assertEqual(half_life.evidence.measurements["count_rate_cpm"], 420.0)
        self.assertEqual(double_mass.evidence.measurements["count_rate_cpm"], 1620.0)

    def test_rutherford_case_separates_target_amount_and_angle(self):
        case = make_rutherford_scattering_case()
        oracle = CaseOracle(case.definition, case.world_model)
        baseline = oracle.respond(scattering_proposal())
        denser_target = oracle.respond(scattering_proposal(areal_density=2.0))
        smaller_angle = oracle.respond(scattering_proposal(angle=30.0))
        silver = oracle.respond(scattering_proposal(atomic_number=47))
        baseline_rate = baseline.evidence.measurements["scattered_count_rate_cpm"]
        self.assertEqual(baseline_rate, 120.0)
        self.assertEqual(
            denser_target.evidence.measurements["scattered_count_rate_cpm"],
            240.0,
        )
        self.assertGreater(
            smaller_angle.evidence.measurements["scattered_count_rate_cpm"],
            10.0 * baseline_rate,
        )
        self.assertAlmostEqual(
            silver.evidence.measurements["scattered_count_rate_cpm"]
            / baseline_rate,
            (47.0 / 79.0) ** 2,
            delta=0.001,
        )


class AdditionalHistoricalEvaluatorTest(unittest.TestCase):
    def test_correct_structured_models_pass_hidden_conditions(self):
        cases = (
            (make_young_double_slit_case(), correct_young_submission()),
            (make_faraday_induction_case(), correct_faraday_submission()),
            (make_radioactive_decay_case(), correct_decay_submission()),
            (make_rutherford_scattering_case(), correct_scattering_submission()),
        )
        for case, submission in cases:
            with self.subTest(case_id=case.definition.case_id):
                result = case.evaluator.evaluate(submission)
                self.assertTrue(result.success)
                self.assertEqual(result.scores["predictive_model_pass"], 1.0)

    def test_each_case_runs_through_the_existing_episode_protocol(self):
        fixtures = (
            (make_young_double_slit_case(), young_proposal(), correct_young_submission()),
            (make_faraday_induction_case(), faraday_proposal(), correct_faraday_submission()),
            (make_radioactive_decay_case(), decay_proposal(), correct_decay_submission()),
            (
                make_rutherford_scattering_case(),
                scattering_proposal(),
                correct_scattering_submission(),
            ),
        )
        portfolio = confident_portfolio()
        for case, proposal, submission in fixtures:
            with self.subTest(case_id=case.definition.case_id):
                episode = Episode(case)
                response = episode.apply(
                    PlayerAction.propose_experiment(portfolio, proposal)
                )
                self.assertEqual(response.status, OracleStatus.VALID)
                episode.apply(PlayerAction.submit_final(portfolio, submission))
                self.assertTrue(episode.result.evaluation.success)
                self.assertEqual(episode.result.attempts_used, 1)

    def test_extra_parameters_and_unsupported_models_fail_cleanly(self):
        young = correct_young_submission()
        extra_parameters = dict(young.parameters)
        extra_parameters["unused"] = 1.0
        cases = (
            (
                make_young_double_slit_case(),
                FinalSubmission(
                    hypothesis_id="H1",
                    explanation="Includes an undeclared parameter.",
                    model=young.model,
                    parameters=extra_parameters,
                ),
            ),
            (
                make_faraday_induction_case(),
                FinalSubmission(
                    hypothesis_id="H1",
                    explanation="Unsupported model.",
                    model="unsupported",
                ),
            ),
        )
        for case, submission in cases:
            with self.subTest(case_id=case.definition.case_id):
                result = case.evaluator.evaluate(submission)
                self.assertFalse(result.success)
                self.assertEqual(result.scores["predictive_model_pass"], 0.0)


if __name__ == "__main__":
    unittest.main()
