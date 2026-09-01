import unittest

from role_benchmark.models import (
    EpisodeTermination,
    ExperimentProposal,
    FinalSubmission,
    Hypothesis,
    HypothesisPortfolio,
    PlayerAction,
    TerminationKind,
)


def portfolio(*items):
    return HypothesisPortfolio(
        tuple(
            Hypothesis(hypothesis_id, statement, confidence)
            for hypothesis_id, statement, confidence in items
        )
    )


class HypothesisPortfolioTest(unittest.TestCase):
    def test_portfolio_structure_allows_final_semantics_to_be_checked_later(self):
        current = portfolio(
            ("H1", "Period depends on length.", 0.55),
            ("H2", "Period depends on mass.", 0.30),
            ("H3", "Period depends on release angle.", 0.15),
        )

        self.assertEqual(current.top.hypothesis_id, "H1")
        self.assertAlmostEqual(current.confidence_of("H3"), 0.15)

        converged = portfolio(("H1", "Only one explanation.", 1.0))
        self.assertEqual(len(converged.hypotheses), 1)
        self.assertEqual(
            PlayerAction.submit_final(
                converged,
                FinalSubmission(explanation="Commit H1.", hypothesis_id="H1"),
            ).kind,
            "final",
        )

        for invalid in (
            portfolio(("H1", "Only one explanation.", 1.0)),
            portfolio(
                ("H1", "First explanation.", 0.60),
                ("H2", "Second explanation.", 0.30),
            ),
            portfolio(
                ("H1", "First concrete explanation.", 0.60),
                ("OTHER", "A residual bucket.", 0.40),
            ),
        ):
            proposal = ExperimentProposal(
                intent="Measure y.",
                apparatus="rig",
                controls={"x": 1.0},
                readouts=("y",),
                forecasts={
                    item.hypothesis_id: {"y": 1.0}
                    for item in invalid.hypotheses
                },
            )
            with self.assertRaises(ValueError):
                PlayerAction.propose_experiment(invalid, proposal)

    def test_hypothesis_set_can_change_between_turns(self):
        before = portfolio(
            ("H1", "Period is proportional to length.", 0.55),
            ("H2", "Period depends on bob mass alone.", 0.30),
            ("H3", "Period depends on release angle alone.", 0.15),
        )
        after = portfolio(
            ("H1", "Period is proportional to length.", 0.10),
            (
                "H3",
                "Period follows a square-root length law and may depend on mass.",
                0.80,
            ),
            ("H4", "Period depends jointly on length and release angle.", 0.10),
        )

        self.assertAlmostEqual(before.confidence_of("H2"), 0.30)
        with self.assertRaises(KeyError):
            after.confidence_of("H2")
        self.assertAlmostEqual(after.confidence_of("H3"), 0.80)

    def test_experiment_requires_one_forecast_per_current_hypothesis(self):
        current = portfolio(
            ("H1", "The response is constant.", 0.5),
            ("H2", "The response changes.", 0.5),
        )
        proposal = ExperimentProposal(
            intent="Measure y.",
            apparatus="rig",
            controls={"x": 1.0},
            readouts=("y",),
            forecasts={"H1": {"y": 1.0}},
        )
        with self.assertRaises(ValueError):
            PlayerAction.propose_experiment(current, proposal)


class EpisodeTerminationTest(unittest.TestCase):
    def test_requires_stable_labels_and_positive_optional_indices(self):
        termination = EpisodeTermination(
            kind=TerminationKind.PLAYER_OUTPUT_INVALID,
            code="invalid_json",
            message="Player output is not valid JSON.",
            action_index=2,
            generation_attempts=1,
        )
        self.assertEqual(termination.code, "invalid_json")

        for changes in (
            {"code": ""},
            {"action_index": 0},
            {"generation_attempts": 0},
        ):
            values = {
                "kind": TerminationKind.PLAYER_OUTPUT_INVALID,
                "code": "invalid_json",
                "message": "Player output is not valid JSON.",
                "action_index": 2,
                "generation_attempts": 1,
            }
            values.update(changes)
            with self.assertRaises(ValueError):
                EpisodeTermination(**values)


if __name__ == "__main__":
    unittest.main()
