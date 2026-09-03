from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from role_benchmark import (
    ADAPTIVE_EXPERIMENTAL_DESIGN,
    EVALUATION_METHODS,
    FIXED_EXPERIMENTAL_DESIGN,
    PRIOR_ONLY_BASELINE,
    Episode,
    EpisodeProtocolError,
    ExperimentProposal,
    GenerationResponse,
    Hypothesis,
    HypothesisPortfolio,
    PlayerAction,
    TerminationKind,
    TokenUsage,
    build_evaluation_method_plan,
    load_run_log,
    prepare_evaluation_case,
    replay_run_log,
    run_llm_episode,
)
from role_benchmark.cases import CASE_SPECS, make_case
from role_benchmark.cases.matched import truth_submission
from role_benchmark.temporal_cases import (
    TEMPORAL_CASE_SPECS,
    TEMPORAL_SOURCE_CONDITIONS,
    make_temporal_case,
)
from role_benchmark.wire import player_action_to_json


def _truth_action(spec, world, track):
    portfolio = HypothesisPortfolio(
        (Hypothesis("H1", "The submitted executable predictor.", 1.0),)
    )
    return PlayerAction.submit_final(
        portfolio,
        truth_submission(spec, world, track),
    )


class _StaticBackend:
    def __init__(self, action):
        self.action = action
        self.requests = []

    def generate(self, request):
        self.requests.append(request)
        return GenerationResponse(
            text=player_action_to_json(self.action),
            provider="test",
            model="static-final",
            usage=TokenUsage(input_tokens=10, output_tokens=5),
        )


class EvaluationMethodTests(unittest.TestCase):
    def test_every_family_freezes_one_shared_fixed_and_adaptive_budget(self):
        registries = (CASE_SPECS, TEMPORAL_CASE_SPECS)
        for registry in registries:
            for family, spec in registry.items():
                with self.subTest(family=family):
                    prior = build_evaluation_method_plan(
                        spec, PRIOR_ONLY_BASELINE
                    )
                    fixed = build_evaluation_method_plan(
                        spec, FIXED_EXPERIMENTAL_DESIGN
                    )
                    adaptive = build_evaluation_method_plan(
                        spec, ADAPTIVE_EXPERIMENTAL_DESIGN
                    )
                    self.assertEqual(prior.observation_budget, 0)
                    self.assertEqual(
                        fixed.observation_budget,
                        len(spec.diagnostic_conditions),
                    )
                    self.assertEqual(
                        adaptive.observation_budget,
                        fixed.observation_budget,
                    )
                    self.assertLessEqual(fixed.observation_budget, spec.budget)
                    self.assertEqual(len(fixed.fixed_experiments), fixed.observation_budget)
                    self.assertEqual(adaptive.fixed_experiments, ())
                    self.assertEqual(
                        [dict(item.controls) for item in fixed.fixed_experiments],
                        [dict(item) for item in spec.diagnostic_conditions],
                    )

    def test_fixed_controls_match_across_conditions_and_observations_differ(self):
        packs = (
            (
                CASE_SPECS,
                make_case,
                lambda _family: ("historical", "counterfactual"),
            ),
            (
                TEMPORAL_CASE_SPECS,
                make_temporal_case,
                lambda family: tuple(
                    item.condition_id
                    for item in TEMPORAL_SOURCE_CONDITIONS[family]
                ),
            ),
        )
        for registry, factory, condition_ids in packs:
            for family, spec in registry.items():
                with self.subTest(family=family):
                    left_condition, right_condition = condition_ids(family)
                    left = prepare_evaluation_case(
                        factory(family, left_condition),
                        spec,
                        FIXED_EXPERIMENTAL_DESIGN,
                    )
                    right = prepare_evaluation_case(
                        factory(family, right_condition),
                        spec,
                        FIXED_EXPERIMENTAL_DESIGN,
                    )
                    left_controls = [
                        dict(item.proposal.controls)
                        for item in left.fixed_observations
                    ]
                    right_controls = [
                        dict(item.proposal.controls)
                        for item in right.fixed_observations
                    ]
                    self.assertEqual(left_controls, right_controls)
                    self.assertEqual(
                        left.initial_attempts_used,
                        left.plan.observation_budget,
                    )
                    self.assertTrue(
                        any(
                            left.response.evidence.measurements
                            != right.response.evidence.measurements
                            for left, right in zip(
                                left.fixed_observations,
                                right.fixed_observations,
                            )
                        )
                    )

    def test_episode_policy_enforces_zero_or_exact_observation_budget(self):
        spec = CASE_SPECS["pendulum"]
        case = make_case("pendulum", "historical")
        final_action = _truth_action(spec, "historical", case.definition.track)

        prior = prepare_evaluation_case(case, spec, PRIOR_ONLY_BASELINE)
        prior_episode = Episode(
            prior.case,
            observation_budget=prior.plan.observation_budget,
            require_budget_exhaustion=True,
        )
        self.assertEqual(prior_episode.view().attempts_remaining, 0)
        prior_episode.apply(final_action)
        self.assertTrue(prior_episode.finished)
        self.assertEqual(prior_episode.outcome.attempts_used, 0)

        adaptive = prepare_evaluation_case(
            case, spec, ADAPTIVE_EXPERIMENTAL_DESIGN
        )
        adaptive_episode = Episode(
            adaptive.case,
            observation_budget=adaptive.plan.observation_budget,
            require_budget_exhaustion=True,
        )
        with self.assertRaises(EpisodeProtocolError) as raised:
            adaptive_episode.apply(final_action)
        self.assertEqual(raised.exception.code, "observation_budget_not_exhausted")

        fixed = prepare_evaluation_case(case, spec, FIXED_EXPERIMENTAL_DESIGN)
        fixed_episode = Episode(
            fixed.case,
            observation_budget=fixed.plan.observation_budget,
            initial_attempts_used=fixed.initial_attempts_used,
            require_budget_exhaustion=True,
        )
        self.assertEqual(fixed_episode.view().attempts_remaining, 0)
        fixed_episode.apply(final_action)
        self.assertEqual(
            fixed_episode.outcome.attempts_used,
            fixed.plan.observation_budget,
        )

    def test_fixed_method_log_records_policy_and_replays(self):
        spec = CASE_SPECS["pendulum"]
        raw_case = make_case("pendulum", "historical")
        prepared = prepare_evaluation_case(
            raw_case, spec, FIXED_EXPERIMENTAL_DESIGN
        )
        backend = _StaticBackend(
            _truth_action(spec, "historical", raw_case.definition.track)
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "fixed.jsonl"
            run = run_llm_episode(
                backend,
                prepared.case,
                str(path),
                max_actions=1,
                observation_budget=prepared.plan.observation_budget,
                initial_attempts_used=prepared.initial_attempts_used,
                require_budget_exhaustion=True,
                run_metadata={"evaluation_method": FIXED_EXPERIMENTAL_DESIGN},
            )
            loaded = load_run_log(str(path))
            policy = loaded.events[0]["payload"]["policy"]
            replay = replay_run_log(str(path), prepared.case)

        self.assertEqual(len(backend.requests), 1)
        self.assertEqual(
            policy["observation_budget"], len(spec.diagnostic_conditions)
        )
        self.assertEqual(
            policy["initial_attempts_used"], len(spec.diagnostic_conditions)
        )
        self.assertIs(policy["require_budget_exhaustion"], True)
        self.assertEqual(run.outcome.attempts_used, len(spec.diagnostic_conditions))
        self.assertEqual(replay.outcome, run.outcome)

    def test_nonlegal_adaptive_attempts_cannot_satisfy_observation_budget(self):
        spec = CASE_SPECS["pendulum"]
        raw_case = make_case("pendulum", "historical")
        prepared = prepare_evaluation_case(
            raw_case, spec, ADAPTIVE_EXPERIMENTAL_DESIGN
        )
        portfolio = HypothesisPortfolio(
            (
                Hypothesis("H1", "First competing relation.", 0.5),
                Hypothesis("H2", "Second competing relation.", 0.5),
            )
        )
        readouts = tuple(item.name for item in spec.readouts)
        invalid = PlayerAction.propose_experiment(
            portfolio,
            ExperimentProposal(
                intent="An unavailable setup.",
                apparatus="not-available",
                controls=dict(spec.diagnostic_conditions[0]),
                readouts=readouts,
                forecasts={
                    hypothesis.hypothesis_id: {
                        readout: 0.0 for readout in readouts
                    }
                    for hypothesis in portfolio.hypotheses
                },
            ),
        )
        episode = Episode(
            prepared.case,
            observation_budget=prepared.plan.observation_budget,
            require_budget_exhaustion=True,
        )
        for _ in range(prepared.plan.observation_budget):
            episode.apply(invalid)
        with self.assertRaises(EpisodeProtocolError) as raised:
            episode.apply(
                _truth_action(spec, "historical", raw_case.definition.track)
            )
        self.assertEqual(
            raised.exception.code,
            "valid_observation_budget_not_met",
        )

    def test_adaptive_early_final_is_logged_as_protocol_failure(self):
        spec = CASE_SPECS["pendulum"]
        raw_case = make_case("pendulum", "historical")
        prepared = prepare_evaluation_case(
            raw_case, spec, ADAPTIVE_EXPERIMENTAL_DESIGN
        )
        backend = _StaticBackend(
            _truth_action(spec, "historical", raw_case.definition.track)
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "adaptive-early-final.jsonl"
            run = run_llm_episode(
                backend,
                prepared.case,
                str(path),
                max_actions=1,
                observation_budget=prepared.plan.observation_budget,
                require_budget_exhaustion=True,
                run_metadata={
                    "evaluation_method": ADAPTIVE_EXPERIMENTAL_DESIGN
                },
            )
            replay = replay_run_log(str(path), prepared.case)

        self.assertIs(run.outcome.termination.kind, TerminationKind.ACTION_REJECTED)
        self.assertEqual(
            run.outcome.termination.code,
            "observation_budget_not_exhausted",
        )
        self.assertEqual(replay.outcome, run.outcome)

    def test_evaluation_method_names_are_the_frozen_public_terminology(self):
        self.assertEqual(
            EVALUATION_METHODS,
            (
                "prior-only baseline",
                "fixed experimental design",
                "adaptive experimental design",
            ),
        )


if __name__ == "__main__":
    unittest.main()
