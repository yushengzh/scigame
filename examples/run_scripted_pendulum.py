"""Run a deterministic Player--Oracle interaction on a pendulum case.

This small script is deliberately transparent: it is an executable interface
example, not a benchmark result.  Replace the scripted proposal/update logic
with an LLM backend for evaluation.
"""

from __future__ import annotations

import argparse
import math
from typing import Dict, Mapping

from role_benchmark import (
    EpisodeView,
    ExperimentProposal,
    FinalSubmission,
    Hypothesis,
    HypothesisPortfolio,
    PlayerAction,
    run_episode,
)
from role_benchmark.cases import PENDULUM_WORLDS, make_pendulum_case


def _weights(
    textbook: float,
    linear: float,
    mass_dependent: float,
    angle_dependent: float,
) -> Dict[str, float]:
    return {
        "H1": textbook,
        "H2": linear,
        "H3": mass_dependent,
        "H4": angle_dependent,
    }


_STATEMENTS: Mapping[str, str] = {
    "H1": "The period follows a square-root length law and is independent of bob mass.",
    "H2": "The period is proportional to pendulum length.",
    "H3": "The period follows a square-root length law with bob-mass dependence.",
    "H4": "The period follows a square-root length law with release-angle dependence.",
}


def _portfolio(weights: Mapping[str, float]) -> HypothesisPortfolio:
    return HypothesisPortfolio(
        tuple(
            Hypothesis(hypothesis_id, _STATEMENTS[hypothesis_id], confidence)
            for hypothesis_id, confidence in weights.items()
        )
    )


def _print_portfolio(label: str, portfolio: HypothesisPortfolio) -> None:
    print("\n%s" % label)
    for hypothesis in portfolio.hypotheses:
        print("  %.2f  %s: %s" % (
            hypothesis.confidence,
            hypothesis.hypothesis_id,
            hypothesis.statement,
        ))


def _proposal(*, length_m: float, mass_kg: float) -> ExperimentProposal:
    return ExperimentProposal(
        intent="Measure the period while controlling length, mass, and release angle.",
        apparatus="simple_pendulum",
        controls={
            "length_m": length_m,
            "bob_mass_kg": mass_kg,
            "release_angle_deg": 5.0,
        },
        readouts=("period_s",),
        replicates=5,
        forecasts={
            "H1": {"period_s": 2.0064 * math.sqrt(length_m)},
            "H2": {"period_s": 2.0064 * length_m},
            "H3": {
                "period_s": 2.0064
                * math.sqrt(length_m)
                * (mass_kg / 0.20) ** 0.25
            },
            "H4": {"period_s": 2.1 * math.sqrt(length_m)},
        },
    )


def _period(view: EpisodeView, turn_index: int) -> float:
    evidence = view.turns[turn_index].response.evidence
    if evidence is None:
        raise RuntimeError("scripted valid experiment was rejected")
    return float(evidence.measurements["period_s"])


class ScriptedPendulumPlayer:
    """A transparent state machine used only to demonstrate the API."""

    def next_action(self, view: EpisodeView) -> PlayerAction:
        turn_count = len(view.turns)
        if turn_count == 0:
            return PlayerAction.propose_experiment(
                _portfolio(_weights(0.45, 0.25, 0.20, 0.10)),
                _proposal(length_m=1.00, mass_kg=0.20),
            )
        if turn_count == 1:
            return PlayerAction.propose_experiment(
                _portfolio(_weights(0.45, 0.25, 0.20, 0.10)),
                _proposal(length_m=0.25, mass_kg=0.20),
            )

        reference = _period(view, 0)
        short = _period(view, 1)
        length_exponent = math.log(short / reference) / math.log(0.25 / 1.00)
        if turn_count == 2:
            return PlayerAction.propose_experiment(
                _portfolio(_weights(0.55, 0.05, 0.35, 0.05)),
                _proposal(length_m=1.00, mass_kg=0.80),
            )

        heavy = _period(view, 2)
        mass_exponent = math.log(heavy / reference) / math.log(0.80 / 0.20)
        if abs(mass_exponent) < 0.05:
            final_portfolio = _portfolio(_weights(0.94, 0.01, 0.03, 0.02))
            selected_id = "H1"
        else:
            final_portfolio = _portfolio(_weights(0.03, 0.01, 0.94, 0.02))
            selected_id = "H3"

        submission = FinalSubmission(
            explanation=_STATEMENTS[selected_id],
            hypothesis_id=selected_id,
            model="normalized_power_law",
            parameters={
                "reference_period_s": reference,
                "length_exponent": length_exponent,
                "mass_exponent": mass_exponent,
            },
            scope_conditions=(
                "0.20 <= length_m <= 2.00",
                "0.05 <= bob_mass_kg <= 1.00",
                "1 <= release_angle_deg <= 10",
            ),
        )
        return PlayerAction.submit_final(final_portfolio, submission)


def run(world: str) -> int:
    case = make_pendulum_case(world)
    print("Case: %s" % case.definition.case_id)
    print(case.definition.background)
    result = run_episode(ScriptedPendulumPlayer(), case)

    for turn in result.turns:
        _print_portfolio("Turn %d portfolio" % turn.turn_index, turn.portfolio)
        controls = turn.proposal.controls
        print("Experiment: L=%.2f m, m=%.2f kg" % (
            controls["length_m"],
            controls["bob_mass_kg"],
        ))
        print("Oracle status: %s" % turn.response.status.value)
        if turn.response.evidence is not None:
            print("Evidence: period = %.2f s" % float(
                turn.response.evidence.measurements["period_s"]
            ))

    _print_portfolio("Final portfolio", result.final_portfolio)
    submission = result.final_submission
    evaluation = result.evaluation
    print("\nFinal rationale: %s" % submission.explanation)
    print("Estimated exponents: length=%.3f, mass=%.3f" % (
        submission.parameters["length_exponent"],
        submission.parameters["mass_exponent"],
    ))
    print("Confidence threshold reached: %s" % bool(
        result.final_portfolio.confidence_of(
            submission.hypothesis_id or result.final_portfolio.top.hypothesis_id
        )
        >= case.definition.confidence_threshold
    ))
    print("Predictive model passes hidden conditions: %s" % evaluation.success)
    print("Maximum hidden relative error: %.4f" % (
        evaluation.scores["hidden_test_max_relative_error"]
    ))
    return 0 if evaluation.success else 1


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--world", choices=PENDULUM_WORLDS, default="historical")
    args = parser.parse_args()
    return run(args.world)


if __name__ == "__main__":
    raise SystemExit(main())
