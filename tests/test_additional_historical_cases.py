import unittest

from role_benchmark import (
    BenchmarkTrack,
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
    HISTORICAL_SCIENCE_CARDS,
    RADIOACTIVE_DECAY_SPEC,
    RUTHERFORD_SCATTERING_SPEC,
    YOUNG_DOUBLE_SLIT_SPEC,
    make_faraday_induction_case,
    make_radioactive_decay_case,
    make_rutherford_scattering_case,
    make_young_double_slit_case,
)
from role_benchmark.cases.matched import truth_submission


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
        replicates=1,
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
        replicates=1,
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
        replicates=1,
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
        replicates=1,
        forecasts={
            "H1": {"scattered_count_rate_cpm": 120.0},
            "H2": {"scattered_count_rate_cpm": 60.0},
        },
    )


def correct_young_submission():
    return truth_submission(
        YOUNG_DOUBLE_SLIT_SPEC,
        "historical",
        BenchmarkTrack.IDENTIFICATION,
    )


def correct_faraday_submission():
    return truth_submission(
        FARADAY_INDUCTION_SPEC,
        "historical",
        BenchmarkTrack.IDENTIFICATION,
    )


def correct_decay_submission():
    return truth_submission(
        RADIOACTIVE_DECAY_SPEC,
        "historical",
        BenchmarkTrack.IDENTIFICATION,
    )


def correct_scattering_submission():
    return truth_submission(
        RUTHERFORD_SCATTERING_SPEC,
        "historical",
        BenchmarkTrack.IDENTIFICATION,
    )


class AdditionalHistoricalWorldModelTest(unittest.TestCase):
    def test_science_cards_preserve_historical_assumptions(self):
        young = HISTORICAL_SCIENCE_CARDS["young_double_slit"]
        young_scope = " ".join(young.historical_applicability)
        self.assertIn("mutually coherent", young_scope)
        self.assertIn("paraxial", young_scope)
        self.assertIn("modern two-slit geometry", young.source_credits[0].role)
        for truth in YOUNG_DOUBLE_SLIT_SPEC.truths.values():
            self.assertTrue(truth.applicability)

        faraday = HISTORICAL_SCIENCE_CARDS["faraday_induction"]
        faraday_scope = " ".join(faraday.historical_applicability)
        self.assertIn("spatially uniform", faraday_scope)
        self.assertIn("constant-slope", faraday_scope)

        decay = HISTORICAL_SCIENCE_CARDS["radioactive_decay"]
        self.assertIn("(sample_mass_mg/1 mg)", decay.historical_formula)
        self.assertIn("1903", " ".join(credit.citation for credit in decay.source_credits))
        decay_scope = " ".join(decay.fixed_conditions)
        self.assertIn("same radionuclide composition", decay_scope)
        self.assertIn("Self-attenuation", decay_scope)
        self.assertIn("counter dead time", decay_scope)
        self.assertIn("no claim of physical realizability", " ".join(decay.counterfactual_scope))

        scattering = HISTORICAL_SCIENCE_CARDS["rutherford_scattering"]
        controls = {control.name: control for control in scattering.controls}
        self.assertIn("target_areal_number_density_relative", controls)
        self.assertNotIn("foil_thickness_um", controls)
        self.assertIn("flux rate", controls["exposure_relative"].description)
        self.assertIn("not accumulated fluence", " ".join(scattering.fixed_conditions))
        parameters = {parameter.name for parameter in scattering.historical_parameters}
        self.assertIn("areal_number_density_exponent", parameters)
        self.assertNotIn("thickness_exponent", parameters)
        citations = " ".join(credit.citation for credit in scattering.source_credits)
        self.assertIn("1911", citations)
        self.assertIn("1913", citations)
        scope = " ".join(scattering.historical_applicability + scattering.fixed_conditions)
        self.assertIn("unscreened Coulomb", scope)
        self.assertIn("narrow enough", scope)
        self.assertIn("recoil", scope)

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

    def test_unknown_control_references_and_unsupported_models_fail_cleanly(self):
        young = correct_young_submission()
        cases = (
            (
                make_young_double_slit_case(),
                FinalSubmission(
                    hypothesis_id="H1",
                    explanation="References an undeclared control.",
                    model=young.model,
                    parameters={
                        "outputs": {
                            "fringe_spacing_mm": {"var": "unused"},
                        }
                    },
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
