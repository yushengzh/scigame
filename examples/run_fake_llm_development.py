"""Exercise the LLM adapter, strict wire format, log, and replay without a SDK.

The fake backend returns prewritten actions. It tests integration only and is
not an LLM benchmark result. Replace ``FakeTextBackend.generate`` with a thin
binding to the chosen provider while preserving GenerationRequest/Response.
"""

from __future__ import annotations

import argparse
import math

from role_benchmark import (
    ExperimentProposal,
    FinalSubmission,
    GenerationConfig,
    GenerationResponse,
    Hypothesis,
    HypothesisPortfolio,
    PlayerAction,
    TokenUsage,
    replay_run_log,
    run_llm_episode,
)
from role_benchmark.cases import make_pendulum_case
from role_benchmark.wire import player_action_to_json


def _portfolio(confidence):
    return HypothesisPortfolio(
        (
            Hypothesis("H1", "A normalized power response fits the data.", confidence),
            Hypothesis("H2", "The period is proportional to length.", 1.0 - confidence),
        )
    )


def _actions():
    experiment = PlayerAction.propose_experiment(
        _portfolio(0.80),
        ExperimentProposal(
            intent="Measure a reference pendulum period.",
            apparatus="simple_pendulum",
            controls={
                "length_m": 1.0,
                "bob_mass_kg": 0.2,
                "release_angle_deg": 5.0,
            },
            readouts=("period_s",),
            replicates=5,
            forecasts={
                "H1": {"period_s": 2.01},
                "H2": {"period_s": 2.00},
            },
        ),
    )
    final = PlayerAction.submit_final(
        _portfolio(0.95),
        FinalSubmission(
            explanation="A normalized square-root length response fits this fixture.",
            hypothesis_id="H1",
            model="normalized_power_law",
            parameters={
                "reference_period_s": 2.0 * math.pi * math.sqrt(1.0 / 9.80665),
                "length_exponent": 0.5,
                "mass_exponent": 0.0,
            },
            scope_conditions=("public apparatus ranges",),
        ),
    )
    return [player_action_to_json(experiment), player_action_to_json(final)]


class FakeTextBackend:
    """Minimal provider binding contract with deterministic canned responses."""

    def __init__(self):
        self._outputs = _actions()

    def generate(self, request):
        if not self._outputs:
            raise RuntimeError("fake backend has no response left")
        return GenerationResponse(
            text=self._outputs.pop(0),
            provider="fake",
            model="canned-actions",
            finish_reason="stop",
            usage=TokenUsage(input_tokens=0, output_tokens=0),
            metadata={
                "purpose": request.metadata["purpose"],
                "binding_id": "fake-text-backend",
                "structured_output_transport": False,
            },
        )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--log", required=True, help="new JSONL path; never overwritten")
    args = parser.parse_args()

    case = make_pendulum_case("historical")
    run = run_llm_episode(
        FakeTextBackend(),
        case,
        args.log,
        config=GenerationConfig(temperature=0.0, top_p=1.0),
        max_repair_attempts=0,
        run_metadata={
            "example": "fake integration; not a benchmark result",
            "requested_model": "canned-actions",
            "provider_binding_id": "fake-text-backend",
            "transport_profile": "plain_text",
            "tool_policy": "none",
            "network_policy": "none",
        },
    )
    replay = replay_run_log(args.log, make_pendulum_case("historical"))
    print("Development profile: public identification fixture")
    print("Termination: %s" % run.outcome.termination.kind.value)
    print("Active pass: %s" % run.outcome.active_pass)
    print("Log: %s" % run.log_path)
    print("Replayed actions: %d" % replay.action_count)


if __name__ == "__main__":
    main()
