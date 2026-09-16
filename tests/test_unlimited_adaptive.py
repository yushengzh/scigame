"""Regression coverage for confidence stopping without an experiment cap."""

from dataclasses import replace
from pathlib import Path
import tempfile
import unittest

from role_benchmark import (
    ADAPTIVE_EXPERIMENTAL_DESIGN, FIXED_EXPERIMENTAL_DESIGN,
    Episode, ExperimentProposal, GenerationResponse, Hypothesis,
    HypothesisPortfolio, PlayerAction, build_evaluation_method_plan,
    load_run_log, prepare_evaluation_case, replay_run_log, run_llm_episode,
)
from role_benchmark.cases import CASE_SPECS, make_case
from role_benchmark.cases.matched import truth_submission
from role_benchmark.runner import run_episode
from role_benchmark.wire import (
    WireDecodeError, episode_view_from_json, episode_view_from_payload,
    episode_view_to_json, episode_view_to_payload, player_action_to_json,
)


class UnlimitedAdaptiveTests(unittest.TestCase):
    def setUp(self):
        self.spec = CASE_SPECS["pendulum"]
        self.raw = make_case("pendulum", "historical")
        self.prepared = prepare_evaluation_case(
            self.raw, self.spec, ADAPTIVE_EXPERIMENTAL_DESIGN
        )
        self.case = self.prepared.case

    def final(self, confidence=0.95, world="historical"):
        return PlayerAction.submit_final(
            HypothesisPortfolio((
                Hypothesis("H1", "The submitted predictor.", confidence),
                Hypothesis("H2", "A competing relation.", 1 - confidence),
            )),
            truth_submission(self.spec, world, self.case.definition.track),
        )

    def experiment(self, invalid=False):
        readouts = tuple(item.name for item in self.spec.readouts)
        return PlayerAction.propose_experiment(
            HypothesisPortfolio((
                Hypothesis("H1", "The first relation.", 0.5),
                Hypothesis("H2", "The second relation.", 0.5),
            )),
            ExperimentProposal(
                intent="Measure the controlled response.",
                apparatus="unavailable" if invalid else self.spec.apparatus_name,
                controls=dict(self.spec.diagnostic_conditions[0]),
                readouts=readouts,
                forecasts={key: {name: 0.0 for name in readouts} for key in ("H1", "H2")},
            ),
        )

    def test_unlimited_attempts_include_rejected_experiments_and_round_trip(self):
        episode = Episode(self.case)
        for index in range(25):
            episode.apply(self.experiment(invalid=index % 2 == 0))
            self.assertIsNone(episode.view().attempts_remaining)
        self.assertEqual(episode.view().attempts_used, 25)
        encoded = episode_view_to_json(episode.view())
        decoded = episode_view_from_json(encoded)
        self.assertIsNone(decoded.case.budget)
        self.assertIsNone(decoded.attempts_remaining)
        self.assertEqual(decoded.attempts_used, 25)
        self.assertEqual(episode_view_to_json(decoded), encoded)
        episode.apply(self.final())
        self.assertTrue(episode.outcome.active_pass)

    def test_threshold_is_strict_and_not_a_scientific_correctness_label(self):
        threshold = self.case.definition.confidence_threshold
        for confidence, completed in ((threshold - 0.01, False), (threshold, False),
                                      (threshold + 0.01, True)):
            with self.subTest(confidence=confidence):
                episode = Episode(self.case)
                episode.apply(self.final(confidence))
                self.assertEqual(episode.outcome.protocol_completed, completed)
                self.assertEqual(episode.outcome.active_pass, completed)
        episode = Episode(self.case)
        episode.apply(self.final(world="counterfactual"))
        self.assertTrue(episode.outcome.protocol_completed)
        self.assertFalse(episode.outcome.evaluation.success)
        self.assertFalse(episode.outcome.active_pass)

    def test_many_attempts_do_not_bypass_the_confidence_rule(self):
        episode = Episode(self.case)
        for _ in range(25):
            episode.apply(self.experiment())
        episode.apply(self.final(0.8))
        self.assertFalse(episode.outcome.protocol_completed)

    def test_no_finite_cap_can_silently_replace_unlimited(self):
        with self.assertRaises(ValueError):
            Episode(self.case, require_budget_exhaustion=True)
        with self.assertRaises(ValueError):
            Episode(self.case, observation_budget=8)
        with self.assertRaises(ValueError):
            replace(self.case.definition, confidence_threshold=1.0)
        with tempfile.TemporaryDirectory() as directory:
            log_path = Path(directory) / "should-not-exist.jsonl"
            with self.assertRaises(ValueError):
                run_llm_episode(None, self.case, str(log_path))
            self.assertFalse(log_path.exists())
        with self.assertRaises(ValueError):
            run_episode(None, self.case)
        payload = episode_view_to_payload(Episode(self.raw).view())
        payload["attempts_remaining"] = None
        with self.assertRaises(WireDecodeError):
            episode_view_from_payload(payload)

    def test_unlimited_log_and_replay_after_more_than_sixteen_actions(self):
        actions = [self.experiment() for _ in range(21)] + [self.final()]

        class SequenceBackend:
            def __init__(self):
                self.actions = iter(actions)

            def generate(self, request):
                return GenerationResponse(
                    text=player_action_to_json(next(self.actions)),
                    provider="test", model="sequence",
                )

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "unlimited.jsonl"
            run = run_llm_episode(SequenceBackend(), self.case, str(path), max_actions=None)
            replay = replay_run_log(str(path), self.case)
            policy = load_run_log(str(path)).events[0]["payload"]["policy"]
        self.assertIsNone(policy["max_actions"])
        self.assertIsNone(policy["observation_budget"])
        self.assertFalse(policy["require_budget_exhaustion"])
        self.assertTrue(run.outcome.active_pass)
        self.assertEqual(run.outcome.attempts_used, 21)
        self.assertEqual(replay.outcome, run.outcome)

    def test_plain_runner_has_no_hidden_one_hundred_action_cap(self):
        actions = iter([self.experiment()] * 101 + [self.final()])

        class SequencePlayer:
            def next_action(self, view):
                return next(actions)

        result = run_episode(SequencePlayer(), self.case, max_turns=None)
        self.assertTrue(result.evaluation.success)

    def test_fixed_two_four_eight_are_nested_and_exact(self):
        conditions = tuple(self.spec.diagnostic_conditions)
        spec = replace(self.spec, budget=8,
                       diagnostic_conditions=(conditions * 8)[:8])
        definition = replace(self.raw.definition, budget=8)
        raw = replace(self.raw, definition=definition)
        full = build_evaluation_method_plan(spec, FIXED_EXPERIMENTAL_DESIGN)
        for budget in (2, 4, 8):
            prepared = prepare_evaluation_case(
                raw, spec, FIXED_EXPERIMENTAL_DESIGN, fixed_budget=budget
            )
            self.assertEqual(prepared.plan.fixed_experiments, full.fixed_experiments[:budget])
            self.assertEqual(len(prepared.fixed_observations), budget)
            self.assertEqual(prepared.initial_attempts_used, budget)
            episode = Episode(prepared.case, observation_budget=budget,
                              initial_attempts_used=budget, require_budget_exhaustion=True)
            self.assertEqual(episode.view().attempts_remaining, 0)
            episode.apply(self.final())
            self.assertEqual(episode.outcome.attempts_used, budget)
            self.assertTrue(episode.outcome.active_pass)
        for budget in (0, -1, 9, True, 2.5):
            with self.assertRaises(ValueError):
                build_evaluation_method_plan(spec, FIXED_EXPERIMENTAL_DESIGN, fixed_budget=budget)
        with self.assertRaises(ValueError):
            build_evaluation_method_plan(spec, ADAPTIVE_EXPERIMENTAL_DESIGN, fixed_budget=2)


if __name__ == "__main__":
    unittest.main()
