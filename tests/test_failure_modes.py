import unittest

from role_benchmark.cases import make_pendulum_case
from role_benchmark.failure_modes import _candidate_prediction, analyze_failure_events
from role_benchmark.models import (
    ExperimentEvidence,
    ExperimentProposal,
    ExperimentTurn,
    Hypothesis,
    HypothesisPortfolio,
    OracleResponse,
    OracleStatus,
)
from role_benchmark.trajectory import score_trajectory


def portfolio(h1=0.5, h2=0.5, *, h1_statement="mass independent"):
    return HypothesisPortfolio(
        (
            Hypothesis("H1", h1_statement, h1),
            Hypothesis("H2", "mass dependent", h2),
        )
    )


def case_payload():
    return {
        "case_id": "pendulum.instance_2",
        "resources": {
            "readouts": [{"name": "period_s", "resolution": 0.01}]
        },
    }


def experiment_action(index, mass, *, forecasts=None, beliefs=None):
    return {
        "sequence": 10 * index,
        "event_type": "action.decoded",
        "payload": {
            "action_index": index,
            "action": {
                "kind": "experiment",
                "portfolio": {
                    "hypotheses": beliefs
                    or [
                        {
                            "hypothesis_id": "H1",
                            "statement": "mass independent",
                            "confidence": 0.5,
                        },
                        {
                            "hypothesis_id": "H2",
                            "statement": "mass dependent",
                            "confidence": 0.5,
                        },
                    ]
                },
                "experiment": {
                    "apparatus": "simple_pendulum",
                    "controls": {
                        "length_m": 1.0,
                        "bob_mass_kg": mass,
                        "release_angle_deg": 5.0,
                    },
                    "readouts": ["period_s"],
                    "replicates": 5,
                    **({"forecasts": forecasts} if forecasts is not None else {}),
                },
                "final": None,
            },
        },
    }


def evidence_event(index, period):
    return {
        "sequence": 10 * index + 1,
        "event_type": "protocol.transition",
        "payload": {
            "action_index": index,
            "outcome_kind": "experiment_evidence",
            "outcome": {
                "oracle_response": {
                    "status": "VALID",
                    "evidence": {"measurements": {"period_s": period}},
                }
            },
        },
    }


def final_action(index, *, h1=0.9, h2=0.1):
    return {
        "sequence": 10 * index,
        "event_type": "action.decoded",
        "payload": {
            "action_index": index,
            "action": {
                "kind": "final",
                "portfolio": {
                    "hypotheses": [
                        {
                            "hypothesis_id": "H1",
                            "statement": "mass independent",
                            "confidence": h1,
                        },
                        {
                            "hypothesis_id": "H2",
                            "statement": "mass dependent",
                            "confidence": h2,
                        },
                    ]
                },
                "experiment": None,
                "final": {
                    "hypothesis_id": "H1",
                    "model": "normalized_power_law",
                    "parameters": {
                        "reference_period_s": 2.01,
                        "length_exponent": 0.5,
                        "mass_exponent": 0.0,
                    },
                },
            },
        },
    }


def terminal(
    *,
    success=False,
    kind="submitted",
    code="submitted",
    action_index=3,
    protocol_violations=(),
):
    return {
        "sequence": 99,
        "event_type": "episode.terminal",
        "payload": {
            "termination": {
                "kind": kind,
                "code": code,
                "message": "terminal message",
                "action_index": action_index,
            },
            "evaluation": {
                "success": success,
                "message": "hidden prediction failed" if not success else "passed",
                "scores": {
                    "predictive_model_pass": float(success),
                    **({"hidden_test_max_relative_error": 0.3} if not success else {}),
                },
            },
            "trajectory_scores": {},
            "protocol_violations": list(protocol_violations),
        },
    }


class FailureModeAnalysisTest(unittest.TestCase):
    def test_replays_every_builtin_final_model_contract(self):
        fixtures = (
            (
                "pendulum.instance_2",
                "normalized_power_law",
                {
                    "reference_period_s": 2.0,
                    "length_exponent": 0.5,
                    "mass_exponent": 0.25,
                },
                {"length_m": 1.0, "bob_mass_kg": 0.2},
                "period_s",
                2.0,
            ),
            (
                "optical.interference.instance_2",
                "double_slit_power_law",
                {
                    "reference_spacing_mm": 1.1,
                    "wavelength_exponent": 1.0,
                    "screen_distance_exponent": 1.0,
                    "slit_separation_exponent": -1.0,
                },
                {
                    "wavelength_nm": 550.0,
                    "screen_distance_m": 1.0,
                    "slit_separation_mm": 0.5,
                },
                "fringe_spacing_mm",
                1.1,
            ),
            (
                "sealed_gas.j_tube.instance_2",
                "boyle_inverse_law",
                {
                    "reference_volume_ml": 48.0,
                    "ambient_pressure_kpa": 101.3,
                    "pressure_exponent": -1.0,
                },
                {"added_pressure_kpa": 0.0},
                "air_volume_ml",
                48.0,
            ),
            (
                "inclined_plane.descent.instance_1",
                "inclined_plane_power_law",
                {
                    "reference_water_mass_g": 24.0,
                    "distance_exponent": 0.5,
                    "sine_angle_exponent": -0.5,
                    "mass_exponent": 0.0,
                },
                {
                    "distance_m": 1.0,
                    "incline_angle_deg": 5.0,
                    "ball_mass_kg": 0.2,
                },
                "collected_water_g",
                24.0,
            ),
            (
                "phototube.response.instance_1",
                "einstein_photoelectric_law",
                {
                    "h_over_e_v_s": 4.135667696e-15,
                    "work_function_equivalent_v": 2.28,
                    "reference_saturation_current_ua": 3.0,
                },
                {
                    "frequency_thz": 700.0,
                    "absorbed_photon_flux_relative": 0.5,
                },
                "saturation_current_ua",
                1.5,
            ),
            (
                "induction.coil.instance_2",
                "faraday_flux_change_power_law",
                {
                    "reference_emf_mv": 20.0,
                    "turn_exponent": 1.0,
                    "area_exponent": 1.0,
                    "field_change_exponent": 1.0,
                    "change_time_exponent": -1.0,
                },
                {
                    "coil_turns": 100.0,
                    "loop_area_cm2": 20.0,
                    "field_change_mt": 10.0,
                    "change_time_ms": 100.0,
                },
                "peak_emf_mv",
                20.0,
            ),
            (
                "decaying_sample.counter.instance_1",
                "single_exponential_decay",
                {
                    "background_cpm": 20.0,
                    "reference_activity_cpm": 800.0,
                    "half_life_min": 60.0,
                    "mass_exponent": 1.0,
                },
                {"elapsed_time_min": 0.0, "sample_mass_mg": 1.0},
                "count_rate_cpm",
                820.0,
            ),
            (
                "foil_scattering.alpha.instance_2",
                "rutherford_scattering_law",
                {
                    "reference_count_rate_cpm": 120.0,
                    "atomic_number_exponent": 2.0,
                    "areal_number_density_exponent": 1.0,
                    "exposure_exponent": 1.0,
                    "sine_half_angle_exponent": -4.0,
                },
                {
                    "scattering_angle_deg": 60.0,
                    "foil_atomic_number": 79.0,
                    "target_areal_number_density_relative": 1.0,
                    "exposure_relative": 1.0,
                },
                "scattered_count_rate_cpm",
                120.0,
            ),
        )
        for case_id, model, parameters, controls, readout, expected in fixtures:
            with self.subTest(case_id=case_id):
                prediction = _candidate_prediction(
                    case_id,
                    {"model": model, "parameters": parameters},
                    controls,
                )
                self.assertAlmostEqual(prediction[readout], expected)

    def test_locates_final_claim_that_omits_observed_mass_effect(self):
        events = [
            {"sequence": 1, "event_type": "run.started", "payload": {"case": case_payload()}},
            experiment_action(1, 0.2),
            evidence_event(1, 2.01),
            experiment_action(2, 0.5),
            evidence_event(2, 2.52),
            final_action(3),
            terminal(),
        ]

        analysis = analyze_failure_events(events)
        codes = {mode["code"] for mode in analysis["modes"]}

        self.assertEqual(analysis["status"], "failed_analyzed")
        self.assertIn("final_model_omits_observed_effect", codes)
        self.assertIn("final_model_misses_observed_evidence", codes)
        self.assertEqual(
            analysis["first_observed_misstep"]["code"],
            "final_model_omits_observed_effect",
        )
        primary = analysis["first_observed_misstep"]
        self.assertEqual(primary["action_index"], 3)
        self.assertEqual(primary["evidence_turns"], [1, 2])
        self.assertEqual(
            primary["details"]["selected_hypothesis"]["hypothesis_id"], "H1"
        )
        self.assertEqual(primary["event_refs"][0]["event_sequence"], 11)
        self.assertEqual(analysis["coverage"]["forecast_update_turns"], 0)
        self.assertFalse(
            any(mode["stage"] == "belief_update" for mode in analysis["modes"])
        )

    def test_separates_inert_and_unsupported_confidence_updates(self):
        started = {
            "sequence": 1,
            "event_type": "run.started",
            "payload": {"case": case_payload()},
        }
        inert = analyze_failure_events(
            [
                started,
                experiment_action(
                    1,
                    0.2,
                    forecasts={"H1": {"period_s": 2.0}, "H2": {"period_s": 3.0}},
                ),
                evidence_event(1, 3.0),
                final_action(2, h1=0.5, h2=0.5),
                terminal(action_index=2),
            ]
        )
        inert_mode = next(
            mode for mode in inert["modes"]
            if mode["code"] == "belief_update_omitted"
        )
        self.assertEqual(inert_mode["action_index"], 2)
        self.assertEqual(inert_mode["evidence_turns"], [1])

        unsupported = analyze_failure_events(
            [
                started,
                experiment_action(
                    1,
                    0.2,
                    forecasts={"H1": {"period_s": 1.0}, "H2": {"period_s": 3.0}},
                ),
                evidence_event(1, 2.0),
                final_action(2, h1=0.9, h2=0.1),
                terminal(action_index=2),
            ]
        )
        unsupported_mode = next(
            mode for mode in unsupported["modes"]
            if mode["code"] == "unsupported_confidence_shift"
        )
        self.assertEqual(unsupported_mode["details"]["hypothesis_ids"], ["H1", "H2"])
        self.assertNotIn("favored_hypothesis_id", unsupported_mode["details"])
        self.assertIn("returned evidence did not discriminate", unsupported_mode["message"])

    def test_non_submitted_episode_still_localizes_evidence_process_failures(self):
        rejected_final = final_action(3, h1=0.9, h2=0.1)
        rejected_final["payload"]["action"]["final"]["hypothesis_id"] = "H3"
        events = [
            {
                "sequence": 1,
                "event_type": "run.started",
                "payload": {"case": case_payload()},
            },
            experiment_action(
                1,
                0.2,
                forecasts={"H1": {"period_s": 2.0}, "H2": {"period_s": 3.0}},
            ),
            evidence_event(1, 3.0),
            experiment_action(
                2,
                0.5,
                forecasts={"H1": {"period_s": 2.01}, "H2": {"period_s": 3.6}},
            ),
            evidence_event(2, 3.6),
            rejected_final,
            terminal(
                success=True,
                kind="action_rejected",
                code="final_hypothesis_not_in_portfolio",
                action_index=3,
            ),
        ]

        analysis = analyze_failure_events(events)
        codes = {mode["code"] for mode in analysis["modes"]}

        self.assertEqual(analysis["status"], "failed_analyzed")
        self.assertEqual(
            analysis["terminal_failure"]["code"],
            "final_hypothesis_not_in_portfolio",
        )
        self.assertEqual(
            analysis["terminal_failure"]["localization_basis"], "hard_contract"
        )
        self.assertIn("belief_update_omitted", codes)
        self.assertIn("final_model_misses_observed_evidence", codes)
        self.assertIn("final_model_omits_observed_effect", codes)
        self.assertEqual(analysis["coverage"]["forecast_update_turns"], 2)
        self.assertEqual(analysis["coverage"]["observed_prediction_points"], 2)
        self.assertEqual(analysis["coverage"]["controlled_contrasts"], 1)
        self.assertEqual(
            analysis["first_observed_misstep"]["code"],
            "belief_update_omitted",
        )

    def test_scientifically_correct_final_keeps_protocol_failure_separate(self):
        events = [
            {
                "sequence": 1,
                "event_type": "run.started",
                "payload": {"case": case_payload()},
            },
            final_action(1),
            terminal(
                success=True,
                code="submitted_with_protocol_violations",
                action_index=1,
                protocol_violations=(
                    {
                        "code": "portfolio_confidence_not_normalized",
                        "message": "Final portfolio confidences do not sum to 1.",
                    },
                ),
            ),
        ]

        analysis = analyze_failure_events(events)
        codes = {mode["code"] for mode in analysis["modes"]}

        self.assertEqual(analysis["status"], "failed_analyzed")
        self.assertEqual(
            analysis["terminal_failure"]["code"],
            "submitted_with_protocol_violations",
        )
        self.assertTrue(
            analysis["terminal_failure"]["details"][
                "scientific_evaluation_success"
            ]
        )
        self.assertIn("portfolio_confidence_not_normalized", codes)
        self.assertEqual(
            analysis["first_observed_misstep"]["localization_basis"],
            "hard_contract",
        )

    def test_protocol_and_scientific_failures_are_both_retained(self):
        events = [
            {
                "sequence": 1,
                "event_type": "run.started",
                "payload": {"case": case_payload()},
            },
            final_action(1),
            terminal(
                success=False,
                code="submitted_with_protocol_violations",
                action_index=1,
                protocol_violations=(
                    {
                        "code": "stopping_condition_not_met",
                        "message": "Selected support is below the threshold.",
                    },
                ),
            ),
        ]

        analysis = analyze_failure_events(events)
        codes = {mode["code"] for mode in analysis["modes"]}

        self.assertIn("stopping_condition_not_met", codes)
        self.assertIn("held_out_prediction_error", codes)
        self.assertEqual(
            analysis["terminal_failure"]["code"],
            "submitted_with_protocol_violations",
        )

    def test_distinguishes_terminal_failure_from_recovered_parse_incident(self):
        events = [
            {"sequence": 1, "event_type": "run.started", "payload": {"case": case_payload()}},
            {
                "sequence": 2,
                "event_type": "action.parse_failed",
                "payload": {
                    "player_turn": 1,
                    "wire_error": {
                        "code": "invalid_json",
                        "path": "$",
                        "message": "invalid JSON",
                    },
                },
            },
            final_action(1),
            terminal(success=True),
        ]
        analysis = analyze_failure_events(events)
        self.assertEqual(analysis["status"], "passed_no_failure")
        self.assertEqual(len(analysis["incidents"]), 1)
        self.assertEqual(analysis["incidents"][0]["status"], "recovered")

        failed = analyze_failure_events(
            [
                events[0],
                {
                    "sequence": 3,
                    "event_type": "episode.terminal",
                    "payload": {
                        "termination": {
                            "kind": "player_output_invalid",
                            "code": "invalid_json",
                            "message": "output remained invalid",
                            "action_index": 1,
                        },
                        "evaluation": {"success": False, "scores": {}, "message": ""},
                        "trajectory_scores": {},
                    },
                },
            ]
        )
        self.assertEqual(failed["terminal_failure"]["stage"], "action_generation")
        self.assertEqual(failed["terminal_failure"]["code"], "invalid_json")


class TrajectoryBreakdownTest(unittest.TestCase):
    def _turn(self, forecasts):
        return ExperimentTurn(
            turn_index=1,
            portfolio=portfolio(),
            proposal=ExperimentProposal(
                intent="test mass",
                apparatus="simple_pendulum",
                controls={
                    "length_m": 1.0,
                    "bob_mass_kg": 0.5,
                    "release_angle_deg": 5.0,
                },
                readouts=("period_s",),
                replicates=1,
                forecasts=forecasts,
            ),
            response=OracleResponse(
                status=OracleStatus.VALID,
                message="",
                evidence=ExperimentEvidence(measurements={"period_s": 2.52}),
            ),
            attempt_index=1,
        )

    def test_reports_inert_and_nondiagnostic_shift_separately(self):
        definition = make_pendulum_case("counterfactual").definition
        inert = score_trajectory(
            definition,
            (self._turn({"H1": {"period_s": 2.01}, "H2": {"period_s": 2.52}}),),
            portfolio(),
        )
        self.assertEqual(inert["belief_update_inert_pair_count"], 1.0)
        self.assertEqual(inert["belief_update_aligned_pair_count"], 0.0)

        shifted = score_trajectory(
            definition,
            (self._turn({"H1": {"period_s": 2.52}, "H2": {"period_s": 2.52}}),),
            portfolio(0.9, 0.1),
        )
        self.assertEqual(shifted["scorable_belief_pair_count"], 0.0)
        self.assertEqual(shifted["unsupported_confidence_shift_pair_count"], 1.0)

    def test_excludes_same_id_when_statement_was_rewritten(self):
        definition = make_pendulum_case("counterfactual").definition
        scores = score_trajectory(
            definition,
            (self._turn({"H1": {"period_s": 2.01}, "H2": {"period_s": 2.52}}),),
            portfolio(0.2, 0.8, h1_statement="now mass dependent too"),
        )
        self.assertEqual(scores["scorable_belief_pair_count"], 0.0)
        self.assertEqual(scores["hypothesis_rewrite_excluded_pair_count"], 1.0)


if __name__ == "__main__":
    unittest.main()
