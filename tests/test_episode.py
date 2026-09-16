import math
import unittest
from dataclasses import replace

from role_benchmark import (
    BenchmarkCase,
    Episode,
    EpisodeProtocolError,
    EvaluationResult,
    EXPRESSION_MODEL,
    ExperimentProposal,
    OracleStatus,
    FinalSubmission,
    Hypothesis,
    HypothesisPortfolio,
    PlayerAction,
    run_episode,
)
from role_benchmark.cases import make_pendulum_case
from role_benchmark.models import EpisodeTermination, TerminationKind


def beliefs(*items):
    return HypothesisPortfolio(
        tuple(
            Hypothesis(hypothesis_id, statement, confidence)
            for hypothesis_id, statement, confidence in items
        )
    )


INITIAL = beliefs(
    ("H1", "The period is proportional to length.", 0.45),
    ("H2", "The period depends only on bob mass.", 0.35),
    ("H3", "The period follows a square-root length law.", 0.20),
)


def experiment(
    *,
    intent="Measure one controlled oscillation.",
    apparatus="simple_pendulum",
    length=1.0,
    mass=0.2,
    angle=5.0,
    readouts=("period_s",),
    hypothesis_ids=("H1", "H2", "H3"),
):
    return ExperimentProposal(
        intent=intent,
        apparatus=apparatus,
        controls={
            "length_m": length,
            "bob_mass_kg": mass,
            "release_angle_deg": angle,
        },
        readouts=readouts,
        replicates=1,
        forecasts={
            hypothesis_id: {
                readout: 2.0 + 0.2 * index for readout in readouts
            }
            for index, hypothesis_id in enumerate(hypothesis_ids)
        },
    )


class EpisodeBudgetTest(unittest.TestCase):
    def test_clarification_is_free_and_every_other_attempt_costs_one(self):
        episode = Episode(make_pendulum_case())

        ambiguous = episode.apply(
            PlayerAction.propose_experiment(
                INITIAL,
                experiment(intent=""),
            )
        )
        self.assertEqual(ambiguous.status, OracleStatus.NEEDS_CLARIFICATION)
        self.assertEqual(episode.view().attempts_used, 0)
        self.assertIsNone(episode.view().turns[-1].attempt_index)

        unavailable = episode.apply(
            PlayerAction.propose_experiment(
                INITIAL,
                experiment(apparatus="laser_interferometer"),
            )
        )
        self.assertEqual(
            unavailable.status,
            OracleStatus.UNAVAILABLE_INSTRUMENT,
        )
        self.assertEqual(episode.view().attempts_used, 1)

        out_of_range = episode.apply(
            PlayerAction.propose_experiment(
                INITIAL,
                experiment(length=20.0),
            )
        )
        self.assertEqual(out_of_range.status, OracleStatus.OUT_OF_RANGE)
        self.assertEqual(episode.view().attempts_used, 2)

        invalid = episode.apply(
            PlayerAction.propose_experiment(
                INITIAL,
                experiment(readouts=("angular_velocity",)),
            )
        )
        self.assertEqual(invalid.status, OracleStatus.INVALID_SETUP)
        self.assertEqual(episode.view().attempts_used, 3)

        valid = episode.apply(
            PlayerAction.propose_experiment(INITIAL, experiment())
        )
        self.assertEqual(valid.status, OracleStatus.VALID)
        self.assertEqual(episode.view().attempts_used, 4)
        self.assertEqual(episode.view().attempts_remaining, episode.view().case.budget - 4)

    def test_episode_snapshots_actions_responses_views_and_results(self):
        episode = Episode(make_pendulum_case())
        proposal = experiment()
        action = PlayerAction.propose_experiment(INITIAL, proposal)
        returned_response = episode.apply(action)
        original_period = episode.view().turns[0].response.evidence.measurements[
            "period_s"
        ]

        proposal.controls["length_m"] = 9.0
        returned_response.evidence.measurements["period_s"] = 999.0
        exposed = episode.view()
        exposed.turns[0].proposal.controls["length_m"] = 8.0
        exposed.turns[0].response.evidence.measurements["period_s"] = 888.0
        exposed.turns[0].response.evidence.units["period_s"] = "forged"
        exposed.turns[0].response.evidence.uncertainty["period_s"] = "forged"

        fresh = episode.view().turns[0]
        self.assertEqual(fresh.proposal.controls["length_m"], 1.0)
        self.assertEqual(
            fresh.response.evidence.measurements["period_s"], original_period
        )
        self.assertNotEqual(fresh.response.evidence.units["period_s"], "forged")
        self.assertNotEqual(
            fresh.response.evidence.uncertainty["period_s"], "forged"
        )

        final_beliefs = beliefs(
            ("H1", "A predictive structured law.", 0.95),
            ("H2", "A constant response law.", 0.05),
        )
        episode.apply(
            PlayerAction.submit_final(
                final_beliefs,
                FinalSubmission(
                    hypothesis_id="H1",
                    explanation="A predictive structured law.",
                    model="normalized_power_law",
                    parameters={
                        "reference_period_s": 2.0
                        * math.pi
                        * math.sqrt(1.0 / 9.80665),
                        "length_exponent": 0.5,
                        "mass_exponent": 0.0,
                    },
                ),
            )
        )
        exposed_result = episode.result
        exposed_result.evaluation.scores["predictive_model_pass"] = -1.0
        self.assertNotEqual(
            episode.result.evaluation.scores["predictive_model_pass"], -1.0
        )

    def test_exhausted_budget_allows_low_confidence_final(self):
        original = make_pendulum_case()
        one_attempt_case = BenchmarkCase(
            definition=replace(original.definition, budget=1),
            world_model=original.world_model,
            evaluator=original.evaluator,
        )
        episode = Episode(one_attempt_case)
        episode.apply(
            PlayerAction.propose_experiment(INITIAL, experiment())
        )

        low_confidence = beliefs(
            ("H1", "The period is proportional to length.", 0.55),
            ("H2", "The period depends only on bob mass.", 0.25),
            ("H3", "The period follows a square-root length law.", 0.20),
        )
        episode.apply(
            PlayerAction.submit_final(
                low_confidence,
                FinalSubmission(
                    hypothesis_id="H1",
                    explanation="The evidence remains inconclusive.",
                ),
            )
        )

        self.assertTrue(episode.finished)
        self.assertEqual(episode.result.attempts_used, 1)


class EpisodeSubmissionTest(unittest.TestCase):
    def test_one_hypothesis_final_is_protocol_valid(self):
        episode = Episode(make_pendulum_case())
        converged = beliefs(
            ("H1", "The response follows the selected relationship.", 1.0),
        )
        episode.apply(
            PlayerAction.submit_final(
                converged,
                FinalSubmission(
                    hypothesis_id="H1",
                    explanation="The evidence selects H1.",
                ),
            )
        )

        self.assertTrue(episode.outcome.protocol_completed)
        self.assertEqual(
            episode.outcome.evaluation.scores[
                "selected_portfolio_confidence"
            ],
            1.0,
        )

    def test_threshold_permits_submission_but_does_not_mean_correct(self):
        case = make_pendulum_case()
        below_threshold = beliefs(
            ("H1", "The period is proportional to length.", 0.89),
            ("H2", "The period is independent of length.", 0.11),
        )
        below_episode = Episode(case)
        below_episode.apply(
            PlayerAction.submit_final(
                below_threshold,
                FinalSubmission(
                    hypothesis_id="H1",
                    explanation="The period is proportional to length.",
                ),
            )
        )
        self.assertTrue(below_episode.outcome.scientifically_evaluable)
        self.assertFalse(below_episode.outcome.protocol_completed)
        self.assertEqual(
            [item.code for item in below_episode.outcome.protocol_violations],
            ["stopping_condition_not_met"],
        )

        at_threshold = beliefs(
            ("H1", "The period is proportional to length.", 0.90),
            ("H2", "The period is independent of length.", 0.10),
        )
        episode = Episode(case)
        episode.apply(
            PlayerAction.submit_final(
                at_threshold,
                FinalSubmission(
                    hypothesis_id="H1",
                    explanation="The period is proportional to length.",
                ),
            )
        )

        self.assertTrue(episode.finished)
        self.assertFalse(episode.result.evaluation.success)
        with self.assertRaises(EpisodeProtocolError):
            episode.apply(
                PlayerAction.propose_experiment(
                    at_threshold,
                    experiment(hypothesis_ids=("H1", "H2")),
                )
            )

    def test_final_result_mechanically_scores_forecasts_and_belief_updates(self):
        original = make_pendulum_case("historical")
        one_attempt_case = BenchmarkCase(
            definition=replace(original.definition, budget=1),
            world_model=original.world_model,
            evaluator=original.evaluator,
        )
        before = beliefs(
            ("H1", "The period is near 2.01 seconds.", 0.40),
            ("H2", "The period is near 3 seconds.", 0.60),
        )
        proposal = experiment(hypothesis_ids=("H1", "H2"))
        proposal = replace(
            proposal,
            forecasts={
                "H1": {"period_s": 2.01},
                "H2": {"period_s": 3.00},
            },
        )
        episode = Episode(one_attempt_case)
        episode.apply(PlayerAction.propose_experiment(before, proposal))

        after = beliefs(
            ("H1", "The period is near 2.01 seconds.", 0.90),
            ("H2", "The period is near 3 seconds.", 0.10),
        )
        episode.apply(
            PlayerAction.submit_final(
                after,
                FinalSubmission(
                    hypothesis_id="H1",
                    explanation="The fitted law predicts held-out periods.",
                    model="normalized_power_law",
                    parameters={
                        "reference_period_s": 2.0
                        * math.pi
                        * math.sqrt(1.0 / 9.80665),
                        "length_exponent": 0.5,
                        "mass_exponent": 0.0,
                    },
                ),
            )
        )

        scores = episode.result.trajectory_scores
        self.assertGreater(scores["experiment_discriminativeness_mean"], 0.0)
        self.assertEqual(scores["evidence_aligned_belief_update_rate"], 1.0)
        self.assertEqual(scores["forecast_pair_count"], 1.0)
        self.assertEqual(scores["scorable_belief_pair_count"], 1.0)


class EpisodeOutcomeTest(unittest.TestCase):
    def test_final_portfolio_semantic_errors_do_not_hide_scientific_score(self):
        class RecordingEvaluator:
            def __init__(self):
                self.calls = 0

            def evaluate(self, submission):
                self.calls += 1
                return EvaluationResult(
                    success=True,
                    scores={"predictive_model_pass": 1.0},
                    message="Scientific model passed.",
                )

        original = make_pendulum_case()
        evaluator = RecordingEvaluator()
        case = BenchmarkCase(
            definition=original.definition,
            world_model=original.world_model,
            evaluator=evaluator,
        )
        inconsistent = beliefs(
            ("H1", "First H1 entry.", 0.40),
            ("H1", "Second H1 entry.", 0.30),
            ("OTHER", "Residual alternative.", 0.20),
        )
        episode = Episode(case)
        episode.apply(
            PlayerAction.submit_final(
                inconsistent,
                FinalSubmission(
                    hypothesis_id="H1",
                    explanation="A strictly decoded scientific claim.",
                    model="candidate_model",
                    parameters={"coefficient": 1.0},
                ),
            )
        )

        outcome = episode.outcome
        self.assertEqual(evaluator.calls, 1)
        self.assertTrue(outcome.scientifically_evaluable)
        self.assertTrue(outcome.evaluation.success)
        self.assertFalse(outcome.protocol_completed)
        self.assertFalse(outcome.active_pass)
        self.assertEqual(
            {item.code for item in outcome.protocol_violations},
            {
                "reserved_hypothesis_id",
                "duplicate_hypothesis_id",
                "portfolio_confidence_not_normalized",
                "final_hypothesis_not_unique",
            },
        )
        self.assertNotIn(
            "selected_portfolio_confidence", outcome.evaluation.scores
        )

    def test_protocol_errors_have_stable_codes(self):
        episode = Episode(make_pendulum_case())
        with self.assertRaises(EpisodeProtocolError) as active_error:
            _ = episode.outcome
        self.assertEqual(active_error.exception.code, "episode_not_finished")

        current = beliefs(
            ("H1", "The response changes with length.", 0.89),
            ("H2", "The response is constant.", 0.11),
        )
        mismatched = PlayerAction.submit_final(
            current,
            FinalSubmission(
                hypothesis_id="H1",
                explanation="The response changes with length.",
            ),
        )
        episode.apply(mismatched)
        self.assertEqual(
            [item.code for item in episode.outcome.protocol_violations],
            ["stopping_condition_not_met"],
        )

        legacy = EpisodeProtocolError("legacy caller")
        self.assertEqual(legacy.code, "episode_protocol_error")

    def test_decoded_final_is_scored_despite_portfolio_protocol_violation(self):
        class RecordingEvaluator:
            called = False

            def evaluate(self, submission):
                self.called = True
                return EvaluationResult(
                    success=True,
                    scores={"predictive_model_pass": 1.0},
                    message="Scientific model passed.",
                )

        original = make_pendulum_case()
        case = BenchmarkCase(
            definition=original.definition,
            world_model=original.world_model,
            evaluator=RecordingEvaluator(),
        )
        episode = Episode(case)
        current = beliefs(
            ("H1", "The response changes with length.", 0.89),
            ("H2", "The response is constant.", 0.11),
        )
        rejected_action = PlayerAction.submit_final(
            current,
            FinalSubmission(
                hypothesis_id="H1",
                explanation="The response changes with length.",
                parameters={"reported_value": 1.0},
            ),
        )
        episode.apply(rejected_action)
        outcome = episode.outcome

        self.assertTrue(episode.finished)
        self.assertFalse(outcome.protocol_completed)
        self.assertTrue(outcome.scientifically_evaluable)
        self.assertFalse(outcome.active_pass)
        self.assertTrue(case.evaluator.called)
        self.assertEqual(outcome.evaluation.scores["predictive_model_pass"], 1.0)
        self.assertEqual(outcome.evaluation.scores["active_pass"], 0.0)
        self.assertEqual(outcome.evaluation.scores["submission_available"], 1.0)
        self.assertEqual(outcome.final_submission, rejected_action.final)
        self.assertIsNone(outcome.candidate_action)
        outcome.final_submission.parameters["reported_value"] = 999.0
        self.assertEqual(
            episode.outcome.final_submission.parameters["reported_value"],
            1.0,
        )
        self.assertEqual(episode.result.final_submission, rejected_action.final)
        with self.assertRaises(EpisodeProtocolError) as already_finished:
            episode.apply(rejected_action)
        self.assertEqual(
            already_finished.exception.code,
            "episode_already_terminated",
        )

    def test_failure_scores_forecasts_without_inventing_a_final_belief_update(self):
        episode = Episode(make_pendulum_case("historical"))
        current = beliefs(
            ("H1", "The period is near 2.01 seconds.", 0.40),
            ("H2", "The period is near 3 seconds.", 0.60),
        )
        proposal = replace(
            experiment(hypothesis_ids=("H1", "H2")),
            forecasts={
                "H1": {"period_s": 2.01},
                "H2": {"period_s": 3.00},
            },
        )
        episode.apply(PlayerAction.propose_experiment(current, proposal))

        outcome = episode.terminate_player_failure(
            EpisodeTermination(
                kind=TerminationKind.PLAYER_OUTPUT_INVALID,
                code="invalid_json",
                message="Player output is not valid JSON.",
                action_index=2,
                generation_attempts=2,
            )
        )

        self.assertGreater(
            outcome.trajectory_scores["experiment_discriminativeness_mean"],
            0.0,
        )
        self.assertEqual(outcome.trajectory_scores["forecast_pair_count"], 1.0)
        self.assertEqual(
            outcome.trajectory_scores["scorable_belief_pair_count"],
            0.0,
        )

    def test_protocol_invalid_final_portfolio_is_an_observed_belief_update(self):
        episode = Episode(make_pendulum_case("historical"))
        before = beliefs(
            ("H1", "The period is near 2.01 seconds.", 0.40),
            ("H2", "The period is near 3 seconds.", 0.60),
        )
        proposal = replace(
            experiment(hypothesis_ids=("H1", "H2")),
            forecasts={
                "H1": {"period_s": 2.01},
                "H2": {"period_s": 3.00},
            },
        )
        episode.apply(PlayerAction.propose_experiment(before, proposal))
        after = beliefs(
            ("H1", "The period is near 2.01 seconds.", 0.89),
            ("H2", "The period is near 3 seconds.", 0.11),
        )
        rejected_action = PlayerAction.submit_final(
            after,
            FinalSubmission(
                hypothesis_id="H1",
                explanation="The first forecast fit the evidence.",
            ),
        )
        episode.apply(rejected_action)
        outcome = episode.outcome

        self.assertFalse(outcome.protocol_completed)
        self.assertTrue(outcome.scientifically_evaluable)
        self.assertEqual(
            outcome.trajectory_scores["scorable_belief_pair_count"],
            1.0,
        )
        self.assertEqual(
            outcome.trajectory_scores["evidence_aligned_belief_update_rate"],
            1.0,
        )

    def test_valid_final_keeps_case_evaluator_result_and_adds_submitted_outcome(self):
        episode = Episode(make_pendulum_case())
        final_beliefs = beliefs(
            ("H1", "The period is proportional to length.", 0.90),
            ("H2", "The period is independent of length.", 0.10),
        )
        episode.apply(
            PlayerAction.submit_final(
                final_beliefs,
                FinalSubmission(
                    hypothesis_id="H1",
                    explanation="The period is proportional to length.",
                ),
            )
        )

        result = episode.result
        outcome = episode.outcome
        self.assertEqual(outcome.termination.kind, TerminationKind.SUBMITTED)
        self.assertTrue(outcome.protocol_completed)
        self.assertTrue(outcome.scientifically_evaluable)
        self.assertEqual(outcome.active_pass, result.evaluation.success)
        self.assertEqual(outcome.evaluation, result.evaluation)
        self.assertEqual(outcome.final_submission, result.final_submission)


class ScriptedIdentificationPlayer:
    def next_action(self, view):
        turn = len(view.turns)
        if turn == 0:
            return PlayerAction.propose_experiment(
                INITIAL,
                experiment(length=1.0, mass=0.2),
            )
        if turn == 1:
            revised = beliefs(
                ("H1", "The period may follow a square-root length law.", 0.60),
                ("H3", "The period may depend on length and mass.", 0.30),
                ("H4", "The period may depend on release angle.", 0.10),
            )
            return PlayerAction.propose_experiment(
                revised,
                experiment(
                    length=0.25,
                    mass=0.2,
                    hypothesis_ids=("H1", "H3", "H4"),
                ),
            )
        if turn == 2:
            revised_again = beliefs(
                ("H1", "The period follows a square-root length law.", 0.78),
                ("H3", "The period may also depend on mass.", 0.17),
                ("H4", "The period may depend on release angle.", 0.05),
            )
            return PlayerAction.propose_experiment(
                revised_again,
                experiment(
                    length=1.0,
                    mass=0.8,
                    hypothesis_ids=("H1", "H3", "H4"),
                ),
            )

        final_beliefs = beliefs(
            (
                "H1",
                "The period follows a square-root length law and is mass-independent.",
                0.94,
            ),
            ("H3", "The period also depends on mass.", 0.03),
            ("H4", "The period also depends on release angle.", 0.03),
        )
        return PlayerAction.submit_final(
            final_beliefs,
            FinalSubmission(
                hypothesis_id="H1",
                explanation=(
                    "Within the available small-angle apparatus, the period is "
                    "proportional to the square root of length and independent "
                    "of bob mass."
                ),
                model=EXPRESSION_MODEL,
                parameters={
                    "outputs": {
                        "period_s": {
                            "op": "multiply",
                            "args": [
                                2.0 * math.pi * math.sqrt(1.0 / 9.80665),
                                {
                                    "op": "power",
                                    "args": [{"var": "length_m"}, 0.5],
                                },
                            ],
                        }
                    }
                },
                scope_conditions=(
                    "0.20 <= length_m <= 2.00",
                    "1 <= release_angle_deg <= 10",
                ),
            ),
        )


class FullEpisodeTest(unittest.TestCase):
    def test_complete_run_allows_dynamic_hypotheses_and_passes_hidden_tests(self):
        result = run_episode(
            ScriptedIdentificationPlayer(),
            make_pendulum_case("historical"),
        )

        self.assertTrue(result.evaluation.success)
        self.assertEqual(result.attempts_used, 3)
        self.assertEqual(len(result.turns), 3)
        self.assertEqual(result.turns[0].response.status, OracleStatus.VALID)
        self.assertEqual(result.turns[0].portfolio.confidence_of("H2"), 0.35)
        with self.assertRaises(KeyError):
            result.turns[1].portfolio.confidence_of("H2")
        self.assertAlmostEqual(
            result.turns[1].portfolio.confidence_of("H3"),
            0.30,
        )
        self.assertEqual(result.final_submission.hypothesis_id, "H1")


if __name__ == "__main__":
    unittest.main()
