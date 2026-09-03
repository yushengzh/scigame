import unittest
from dataclasses import replace

from role_benchmark import BenchmarkTrack as PublicBenchmarkTrack
from role_benchmark.cases import PENDULUM_SPEC, make_pendulum_case
from role_benchmark.cases.matched import truth_submission
from role_benchmark.models import (
    BenchmarkTrack,
    CaseDefinition,
    ControlSpec,
    EvaluationResult,
    ExperimentProposal,
    FinalSubmission,
    Hypothesis,
    HypothesisPortfolio,
    InstrumentSpec,
    ExperimentEvidence,
    ReadoutSpec,
    ResourceCatalog,
    PlayerAction,
)
from role_benchmark.protocols import (
    BenchmarkCase,
    WorldModel,
    FinalEvaluator,
    WorldModelContractError,
    CaseOracle,
)
from role_benchmark.runner import run_episode


def pendulum_proposal(mass_kg):
    return ExperimentProposal(
        intent="Measure period at a controlled mass.",
        apparatus="simple_pendulum",
        controls={
            "length_m": 1.0,
            "bob_mass_kg": mass_kg,
            "release_angle_deg": 5.0,
        },
        readouts=("period_s",),
        replicates=3,
    )


class LinearWorldModel(WorldModel):
    def run(self, proposal):
        x = float(proposal.controls["x"])
        return ExperimentEvidence(
            measurements={"y": 2.0 * x + 1.0},
            units={"y": "arb."},
        )


class LinearEvaluator(FinalEvaluator):
    def evaluate(self, submission):
        success = (
            submission.model == "linear"
            and submission.parameters.get("slope") == 2.0
            and submission.parameters.get("intercept") == 1.0
        )
        return EvaluationResult(success=success)


class BrokenWorldModel(WorldModel):
    def run(self, proposal):
        return ExperimentEvidence(measurements={"wrong_readout": 1.0})


def make_linear_case():
    resources = ResourceCatalog(
        instruments=(
            InstrumentSpec(
                name="linear_rig",
                description="A controllable input and one readout.",
                controls=("x",),
                readouts=("y",),
            ),
        ),
        controls=(
            ControlSpec(
                name="x",
                description="Controlled input.",
                minimum=0.0,
                maximum=10.0,
            ),
        ),
        readouts=(
            ReadoutSpec(
                name="y",
                description="Observed response.",
                unit="arb.",
            ),
        ),
    )
    definition = CaseDefinition(
        case_id="linear.instance_1",
        track=BenchmarkTrack.IDENTIFICATION,
        title="Identify a linear response",
        background="Vary x and observe y.",
        initial_observations=("The readout changes when x changes.",),
        resources=resources,
        budget=3,
        confidence_threshold=0.9,
    )
    return BenchmarkCase(
        definition=definition,
        world_model=LinearWorldModel(),
        evaluator=LinearEvaluator(),
    )


class LinearPlayer:
    def next_action(self, view):
        portfolio = HypothesisPortfolio(
            (
                Hypothesis("H1", "The response is linear.", 0.95),
                Hypothesis("H2", "The response is quadratic.", 0.05),
            )
        )
        if not view.turns:
            return PlayerAction.propose_experiment(
                portfolio,
                ExperimentProposal(
                    intent="Set x and read y.",
                    apparatus="linear_rig",
                    controls={"x": 4.0},
                    readouts=("y",),
                    forecasts={
                        "H1": {"y": 9.0},
                        "H2": {"y": 16.0},
                    },
                ),
            )
        return PlayerAction.submit_final(
            portfolio,
            FinalSubmission(
                hypothesis_id="H1",
                explanation="y is twice x plus one.",
                model="linear",
                parameters={"slope": 2.0, "intercept": 1.0},
            ),
        )


class CaseFactoryTest(unittest.TestCase):
    def test_track_is_explicit_and_enum_typed(self):
        case = make_linear_case()
        self.assertIs(PublicBenchmarkTrack, BenchmarkTrack)
        self.assertEqual(BenchmarkTrack.IDENTIFICATION.value, "identification")
        self.assertEqual(BenchmarkTrack.DISCOVERY.value, "discovery")
        self.assertIs(case.definition.track, BenchmarkTrack.IDENTIFICATION)
        discovery = replace(case.definition, track=BenchmarkTrack.DISCOVERY)
        self.assertIs(discovery.track, BenchmarkTrack.DISCOVERY)
        with self.assertRaises(ValueError):
            replace(case.definition, track="identification")

        values = {
            field: getattr(case.definition, field)
            for field in (
                "case_id",
                "title",
                "background",
                "initial_observations",
                "resources",
                "budget",
                "confidence_threshold",
            )
        }
        with self.assertRaises(TypeError):
            CaseDefinition(**values)

    def test_matched_pendulum_worlds_share_the_public_interface(self):
        historical = make_pendulum_case("historical")
        counterfactual = make_pendulum_case("counterfactual")

        self.assertNotEqual(
            historical.definition.case_id,
            counterfactual.definition.case_id,
        )
        self.assertNotIn("historical", historical.definition.case_id)
        self.assertNotIn("counterfactual", counterfactual.definition.case_id)
        self.assertIs(
            historical.definition.track,
            BenchmarkTrack.IDENTIFICATION,
        )
        self.assertIs(
            counterfactual.definition.track,
            BenchmarkTrack.IDENTIFICATION,
        )
        self.assertEqual(
            historical.definition.background,
            counterfactual.definition.background,
        )
        self.assertEqual(
            historical.definition.resources,
            counterfactual.definition.resources,
        )

        historical_response = CaseOracle(
            historical.definition, historical.world_model
        ).respond(pendulum_proposal(0.8))
        counterfactual_response = CaseOracle(
            counterfactual.definition, counterfactual.world_model
        ).respond(pendulum_proposal(0.8))
        historical_period = historical_response.evidence.measurements["period_s"]
        counterfactual_period = counterfactual_response.evidence.measurements[
            "period_s"
        ]
        self.assertNotEqual(historical_period, counterfactual_period)

    def test_future_case_factory_needs_no_runner_change(self):
        case = make_linear_case()
        result = run_episode(LinearPlayer(), case)

        self.assertEqual(result.turns[0].response.status.value, "VALID")
        self.assertEqual(
            result.turns[0].response.evidence.measurements["y"],
            9.0,
        )
        self.assertIs(result.track, BenchmarkTrack.IDENTIFICATION)
        self.assertTrue(result.evaluation.success)

    def test_pendulum_metric_names_predictive_success_and_failures(self):
        evaluator = make_pendulum_case("historical").evaluator
        correct = truth_submission(
            PENDULUM_SPEC,
            "historical",
            BenchmarkTrack.IDENTIFICATION,
        )
        submissions = (
            (correct, True),
            (
                replace(correct, model="unsupported"),
                False,
            ),
            (
                replace(
                    correct,
                    parameters={
                        "outputs": {"period_s": {"var": "unknown_control"}}
                    },
                ),
                False,
            ),
            (
                replace(
                    correct,
                    parameters={"outputs": {"period_s": 0.0}},
                ),
                False,
            ),
        )
        for submission, expected_success in submissions:
            with self.subTest(model=submission.model, parameters=submission.parameters):
                result = evaluator.evaluate(submission)
                self.assertIs(result.success, expected_success)
                self.assertEqual(
                    bool(result.scores["predictive_model_pass"]),
                    result.success,
                )
                self.assertNotIn("explanation_correct", result.scores)

    def test_unknown_builtin_world_is_rejected(self):
        with self.assertRaises(ValueError):
            make_pendulum_case("unknown")

    def test_case_oracle_rejects_a_world_model_that_breaks_the_contract(self):
        case = make_linear_case()
        oracle = CaseOracle(case.definition, BrokenWorldModel())
        with self.assertRaises(WorldModelContractError):
            oracle.respond(
                ExperimentProposal(
                    intent="Set x and read y.",
                    apparatus="linear_rig",
                    controls={"x": 4.0},
                    readouts=("y",),
                )
            )


if __name__ == "__main__":
    unittest.main()
