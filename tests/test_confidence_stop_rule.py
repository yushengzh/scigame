"""Reject adaptive experiments after the public confidence stop condition."""

from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import Mock, patch

from role_benchmark import (
    ADAPTIVE_EXPERIMENTAL_DESIGN,
    Episode,
    EpisodeProtocolError,
    ExperimentProposal,
    GenerationResponse,
    Hypothesis,
    HypothesisPortfolio,
    OracleStatus,
    PlayerAction,
    load_run_log,
    prepare_evaluation_case,
    replay_run_log,
    run_llm_episode,
)
from role_benchmark.cases import CASE_SPECS, make_case
from role_benchmark.cases.matched import truth_submission
from role_benchmark.models import TerminationKind
from role_benchmark.protocols import CaseOracle
from role_benchmark.wire import player_action_to_json


class ConfidenceStopRuleTests(unittest.TestCase):
    def setUp(self):
        self.spec = CASE_SPECS["pendulum"]
        self.raw = make_case("pendulum", "historical")
        self.case = prepare_evaluation_case(
            self.raw, self.spec, ADAPTIVE_EXPERIMENTAL_DESIGN
        ).case

    def portfolio(self, confidence):
        return HypothesisPortfolio((
            Hypothesis("H1", "The proposed relation.", confidence),
            Hypothesis("H2", "A competing relation.", 1 - confidence),
        ))

    def experiment(self, confidence):
        readouts = tuple(item.name for item in self.spec.readouts)
        return PlayerAction.propose_experiment(
            self.portfolio(confidence),
            ExperimentProposal(
                intent="Measure the controlled response.",
                apparatus=self.spec.apparatus_name,
                controls=dict(self.spec.diagnostic_conditions[0]),
                readouts=readouts,
                forecasts={key: {name: 0.0 for name in readouts}
                           for key in ("H1", "H2")},
            ),
        )

    def final(self, confidence=0.99):
        return PlayerAction.submit_final(
            self.portfolio(confidence),
            truth_submission(self.spec, "historical", self.case.definition.track),
        )

    def test_above_actual_threshold_rejects_before_oracle_and_budget_charge(self):
        for threshold in (0.7, 0.9, 0.95):
            with self.subTest(threshold=threshold):
                case = replace(self.case, definition=replace(
                    self.case.definition, confidence_threshold=threshold,
                    count_all_experiment_attempts=True,
                ))
                oracle = Mock(spec=CaseOracle)
                episode = Episode(case, oracle=oracle)
                with self.assertRaises(EpisodeProtocolError) as rejected:
                    episode.apply(self.experiment(threshold + 0.01))
                self.assertEqual(rejected.exception.code, "confidence_stop_required")
                oracle.respond.assert_not_called()
                self.assertEqual(episode.view().attempts_used, 0)
                self.assertEqual(episode.view().turns, ())

    def test_equal_and_below_threshold_still_execute(self):
        for threshold in (0.7, 0.9, 0.95):
            for confidence in (threshold - 0.01, threshold):
                with self.subTest(threshold=threshold, confidence=confidence):
                    case = replace(self.case, definition=replace(
                        self.case.definition, confidence_threshold=threshold,
                    ))
                    episode = Episode(case)
                    response = episode.apply(self.experiment(confidence))
                    self.assertEqual(response.status, OracleStatus.VALID)
                    self.assertEqual(episode.view().attempts_used, 1)
                    episode.apply(self.final())
                    self.assertTrue(episode.outcome.active_pass)

    def test_current_action_beliefs_apply_before_its_new_observation(self):
        episode = Episode(self.case)
        threshold = self.case.definition.confidence_threshold
        episode.apply(self.experiment(threshold))
        previous_view = episode.view()
        with patch.object(episode.oracle, "respond") as respond:
            with self.assertRaises(EpisodeProtocolError):
                episode.apply(self.experiment(threshold + 0.01))
        respond.assert_not_called()
        self.assertEqual(episode.view(), previous_view)

    def test_highest_confidence_is_checked_independent_of_portfolio_order(self):
        action = self.experiment(0.99)
        action = replace(action, portfolio=HypothesisPortfolio(
            tuple(reversed(action.portfolio.hypotheses))
        ))
        episode = Episode(self.case)
        with self.assertRaises(EpisodeProtocolError) as rejected:
            episode.apply(action)
        self.assertEqual(rejected.exception.code, "confidence_stop_required")
        self.assertEqual(episode.view().attempts_used, 0)

    def test_caught_rejection_cannot_become_a_clean_final(self):
        episode = Episode(self.case)
        for _ in range(2):
            with self.assertRaises(EpisodeProtocolError):
                episode.apply(self.experiment(0.99))
        episode.apply(self.final())
        self.assertTrue(episode.outcome.evaluation.success)
        self.assertFalse(episode.outcome.protocol_completed)
        self.assertFalse(episode.outcome.active_pass)
        self.assertEqual(episode.outcome.evaluation.scores["protocol_completion"], 0.0)
        self.assertEqual(episode.outcome.evaluation.scores["active_pass"], 0.0)
        self.assertEqual([item.code for item in episode.outcome.protocol_violations],
                         ["confidence_stop_required"])
        self.assertEqual(episode.outcome.attempts_used, 0)

    def test_finite_budget_behavior_is_unchanged(self):
        episode = Episode(self.raw)
        response = episode.apply(self.experiment(0.99))
        self.assertEqual(response.status, OracleStatus.VALID)
        self.assertEqual(episode.view().attempts_used, 1)
        episode.apply(self.final())
        self.assertTrue(episode.outcome.active_pass)

    def test_unconfigured_legacy_threshold_does_not_add_a_stop_rule(self):
        # Current CaseDefinition requires a threshold; exercise the defensive
        # guard with a legacy duck-typed definition without widening that schema.
        for absent in (True, False):
            with self.subTest(absent=absent):
                fields = vars(self.case.definition).copy()
                if absent:
                    fields.pop("confidence_threshold")
                else:
                    fields["confidence_threshold"] = None
                case = replace(self.case, definition=SimpleNamespace(**fields))
                episode = Episode(case)
                response = episode.apply(self.experiment(0.99))
                self.assertEqual(response.status, OracleStatus.VALID)
                self.assertEqual(episode.view().attempts_used, 1)

    def test_logged_rejection_keeps_evidence_and_replays_without_new_observation(self):
        threshold = self.case.definition.confidence_threshold
        rejected = self.experiment(threshold + 0.01)
        actions = iter((self.experiment(threshold), rejected, self.final()))

        class SequenceBackend:
            calls = 0

            def generate(self, request):
                self.calls += 1
                return GenerationResponse(
                    text=player_action_to_json(next(actions)),
                    provider="test", model="sequence",
                )

        backend = SequenceBackend()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "confidence-stop.jsonl"
            original_respond = CaseOracle.respond
            with patch.object(CaseOracle, "respond", autospec=True,
                              side_effect=original_respond) as respond, patch.object(
                                  type(self.case.evaluator), "evaluate"
                              ) as evaluate:
                run = run_llm_episode(backend, self.case, str(path), max_actions=None)
                evaluate.assert_not_called()
            self.assertEqual(respond.call_count, 1)
            replay = replay_run_log(str(path), self.case)
            events = load_run_log(str(path)).events

        self.assertEqual(backend.calls, 2)
        self.assertEqual(run.outcome.termination.kind, TerminationKind.ACTION_REJECTED)
        self.assertEqual(run.outcome.termination.code, "confidence_stop_required")
        self.assertEqual(run.outcome.termination.action_index, 2)
        self.assertEqual(run.outcome.candidate_action, rejected)
        self.assertEqual(run.outcome.attempts_used, 1)
        self.assertEqual(len(run.outcome.turns), 1)
        self.assertFalse(run.outcome.protocol_completed)
        self.assertFalse(run.outcome.scientifically_evaluable)
        self.assertFalse(run.outcome.active_pass)
        self.assertEqual(replay.outcome, run.outcome)
        transitions = [item["payload"] for item in events
                       if item["event_type"] == "protocol.transition"]
        self.assertEqual(transitions[-1]["outcome_kind"], "protocol_rejected")
        self.assertEqual(transitions[-1]["error"]["type"], "EpisodeProtocolError")
        self.assertEqual(transitions[-1]["error"]["message"], run.outcome.termination.message)
        self.assertEqual(transitions[-1]["attempts_used_before"], 1)
        self.assertEqual(transitions[-1]["attempts_used_after"], 1)
        terminal = next(item["payload"] for item in events
                        if item["event_type"] == "episode.terminal")
        self.assertEqual(terminal["termination"]["code"], "confidence_stop_required")


if __name__ == "__main__":
    unittest.main()
