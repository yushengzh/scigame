import contextlib
import io
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from examples.render_run_log import (
    RunLogRenderError,
    main,
    render_loaded_run,
    render_run_log,
)
from role_benchmark.cases import make_pendulum_case
from role_benchmark.llm import GenerationResponse, TokenUsage
from role_benchmark.models import (
    ExperimentProposal,
    FinalSubmission,
    Hypothesis,
    HypothesisPortfolio,
    PlayerAction,
)
from role_benchmark.protocols import BenchmarkCase
from role_benchmark.runlog import (
    LoadedRunLog,
    JSONLRunLog,
    load_run_log,
    run_llm_episode,
    run_logged_episode,
)
from role_benchmark.wire import player_action_to_json


class SequencedFakeModel:
    def __init__(self, outputs):
        self._outputs = list(outputs)
        self._calls = 0

    def generate(self, _request):
        if not self._outputs:
            raise AssertionError("fake model received an unexpected call")
        self._calls += 1
        return GenerationResponse(
            text=self._outputs.pop(0),
            provider="fake",
            model="renderer-fixture",
            finish_reason="stop",
            response_id="fixture-%d" % self._calls,
            usage=TokenUsage(10, 5),
        )


class ScriptedPlayer:
    def __init__(self, actions):
        self._actions = list(actions)

    def next_action(self, _view):
        if not self._actions:
            raise AssertionError("renderer fixture exhausted its actions")
        return self._actions.pop(0)


def renderer_actions():
    first_portfolio = HypothesisPortfolio(
        (
            Hypothesis(
                "H1",
                "The period follows sqrt(length) <script>alert('x')</script>.",
                0.60,
            ),
            Hypothesis(
                "H2",
                "The period is proportional to length and may depend on mass.",
                0.40,
            ),
        )
    )
    experiment = PlayerAction.propose_experiment(
        first_portfolio,
        ExperimentProposal(
            intent="Measure a baseline & compare the forecasts.",
            apparatus="simple_pendulum",
            controls={
                "length_m": 1.0,
                "bob_mass_kg": 0.20,
                "release_angle_deg": 5.0,
            },
            readouts=("period_s",),
            replicates=5,
            forecasts={
                "H1": {"period_s": 2.01},
                "H2": {"period_s": 3.00},
            },
        ),
    )
    final_portfolio = HypothesisPortfolio(
        (
            Hypothesis("H1", "The period follows sqrt(length).", 0.95),
            Hypothesis("H2", "The period follows a linear response.", 0.05),
        )
    )
    final = PlayerAction.submit_final(
        final_portfolio,
        FinalSubmission(
            hypothesis_id="H1",
            explanation="Evidence supports H1 <img src=x onerror=alert(1)>.",
            model="normalized_power_law",
            parameters={
                "reference_period_s": 2.0064,
                "length_exponent": 0.5,
                "mass_exponent": 0.0,
            },
            scope_conditions=("small release angles",),
        ),
    )
    return experiment, final


def write_current_fixture(path):
    base = make_pendulum_case("historical")
    case = BenchmarkCase(
        definition=replace(
            base.definition,
            background="Public background <b>must remain text</b>.",
        ),
        world_model=base.world_model,
        evaluator=base.evaluator,
    )
    with JSONLRunLog(str(path), run_id="renderer-fixture") as log:
        run_logged_episode(
            ScriptedPlayer(renderer_actions()),
            case,
            log,
            run_metadata={
                "player_model": "fixture-player <unsafe>",
                "oracle_model": "unused",
            },
        )


def write_failure_fixture(path):
    before = HypothesisPortfolio(
        (
            Hypothesis("H1", "The period is independent of bob mass.", 0.50),
            Hypothesis("H2", "The period increases with bob mass.", 0.50),
        )
    )
    first = PlayerAction.propose_experiment(
        before,
        ExperimentProposal(
            intent="Establish a mass baseline.",
            apparatus="simple_pendulum",
            controls={
                "length_m": 1.0,
                "bob_mass_kg": 0.20,
                "release_angle_deg": 5.0,
            },
            readouts=("period_s",),
            forecasts={
                "H1": {"period_s": 2.01},
                "H2": {"period_s": 2.01},
            },
        ),
    )
    second = PlayerAction.propose_experiment(
        before,
        ExperimentProposal(
            intent="Change only bob mass.",
            apparatus="simple_pendulum",
            controls={
                "length_m": 1.0,
                "bob_mass_kg": 0.50,
                "release_angle_deg": 5.0,
            },
            readouts=("period_s",),
            forecasts={
                "H1": {"period_s": 2.01},
                "H2": {"period_s": 2.52},
            },
        ),
    )
    final_beliefs = HypothesisPortfolio(
        (
            Hypothesis("H1", "The period is independent of bob mass.", 0.90),
            Hypothesis("H2", "The period increases with bob mass.", 0.10),
        )
    )
    final = PlayerAction.submit_final(
        final_beliefs,
        FinalSubmission(
            hypothesis_id="H1",
            explanation="The period is independent of bob mass.",
            model="normalized_power_law",
            parameters={
                "reference_period_s": 2.01,
                "length_exponent": 0.5,
                "mass_exponent": 0.0,
            },
        ),
    )
    case = make_pendulum_case("counterfactual")
    with JSONLRunLog(str(path), run_id="renderer-failure") as log:
        run_logged_episode(
            ScriptedPlayer((first, second, final)),
            case,
            log,
            run_metadata={"player_model": "fixture-player"},
        )


class RunLogRendererTest(unittest.TestCase):
    def test_renders_public_case_paired_turns_and_post_episode_scores(self):
        with tempfile.TemporaryDirectory() as directory:
            log_path = Path(directory) / "episode.jsonl"
            write_current_fixture(log_path)

            rendered = render_run_log(str(log_path))

        self.assertEqual(rendered.count('id="dialogue"'), 1)
        self.assertEqual(rendered.count('id="replay-context"'), 1)
        self.assertIn("Replay context", rendered)
        self.assertIn("PASS", rendered)
        self.assertIn("Public case information supplied to Player", rendered)
        self.assertIn("Complete public case JSON", rendered)
        self.assertIn("length_m", rendered)
        self.assertIn("release_angle_deg", rendered)
        self.assertIn("Initial observations", rendered)
        self.assertIn("H1", rendered)
        self.assertIn("H2", rendered)
        self.assertIn("60%", rendered)
        self.assertIn("Forecasts made before evidence", rendered)
        self.assertIn("2.01", rendered)
        self.assertIn("3.0", rendered)
        self.assertIn("Oracle · VALID", rendered)
        self.assertIn("period_s", rendered)
        self.assertIn("+/- 0.005 s", rendered)
        self.assertIn("Oracle · no call", rendered)
        self.assertIn("Post-episode evaluation", rendered)
        self.assertIn("predictive_model_pass", rendered)
        self.assertIn("experiment_discriminativeness_mean", rendered)

    def test_renders_failure_locus_and_structured_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            log_path = Path(directory) / "failure.jsonl"
            write_failure_fixture(log_path)
            rendered = render_run_log(str(log_path))

        self.assertIn("Failure-mode analysis", rendered)
        self.assertIn("First observed misstep", rendered)
        self.assertIn("final_model_omits_observed_effect", rendered)
        self.assertIn("evidence turns 1, 2", rendered)
        self.assertIn("selected_hypothesis", rendered)

    def test_escapes_every_model_and_case_controlled_text(self):
        with tempfile.TemporaryDirectory() as directory:
            log_path = Path(directory) / "episode.jsonl"
            write_current_fixture(log_path)
            rendered = render_run_log(str(log_path))

        self.assertNotIn("<script>alert('x')</script>", rendered)
        self.assertNotIn("<img src=x onerror=alert(1)>", rendered)
        self.assertNotIn("<b>must remain text</b>", rendered)
        self.assertNotIn("fixture-player <unsafe>", rendered)
        self.assertIn("&lt;script&gt;alert(&#x27;x&#x27;)&lt;/script&gt;", rendered)
        self.assertIn("&lt;img src=x onerror=alert(1)&gt;", rendered)
        self.assertIn("Public background &lt;b&gt;must remain text&lt;/b&gt;.", rendered)
        self.assertIn("fixture-player &lt;unsafe&gt;", rendered)
        self.assertIn("<code>unused</code>", rendered)
        self.assertIn("baseline &amp; compare", rendered)

    def test_renders_rejected_primary_before_successful_repair_only(self):
        rejected = "REJECTED_ONLY <script>alert('repair-me')</script>"
        experiment, final = renderer_actions()
        backend = SequencedFakeModel(
            (
                rejected,
                player_action_to_json(experiment),
                player_action_to_json(final),
            )
        )
        with tempfile.TemporaryDirectory() as directory:
            log_path = Path(directory) / "recovered.jsonl"
            run_llm_episode(
                backend,
                make_pendulum_case("historical"),
                str(log_path),
                max_repair_attempts=1,
                run_metadata={"player_model": "renderer-fixture"},
            )
            rendered = render_run_log(str(log_path))

        self.assertEqual(rendered.count('class="turn rejected-attempt"'), 1)
        self.assertEqual(rendered.count("Rejected raw completion"), 1)
        self.assertIn(
            "REJECTED_ONLY &lt;script&gt;alert(&#x27;repair-me&#x27;)&lt;/script&gt;",
            rendered,
        )
        self.assertNotIn("<script>alert('repair-me')</script>", rendered)
        self.assertLess(
            rendered.index("Rejected raw completion"),
            rendered.index("Turn 1 · experiment"),
        )
        rejected_start = rendered.index('class="turn rejected-attempt"')
        accepted_start = rendered.index('class="turn"', rejected_start)
        self.assertIn("Oracle · no call", rendered[rejected_start:accepted_start])
        self.assertEqual(rendered.count("Player · experiment"), 1)
        self.assertEqual(rendered.count("Player · final"), 1)

    def test_renders_every_terminal_generation_failure_without_oracle_call(self):
        primary = "PRIMARY_ONLY <img src=x onerror=alert(1)>"
        repair = "REPAIR_ONLY <script>alert('x')</script>"
        backend = SequencedFakeModel((primary, repair))
        with tempfile.TemporaryDirectory() as directory:
            log_path = Path(directory) / "generation-failure.jsonl"
            run_llm_episode(
                backend,
                make_pendulum_case("historical"),
                str(log_path),
                max_repair_attempts=1,
                run_metadata={"player_model": "renderer-fixture"},
            )
            rendered = render_run_log(str(log_path))

        self.assertEqual(rendered.count('class="turn rejected-attempt"'), 2)
        self.assertEqual(rendered.count('class="turn"'), 0)
        self.assertEqual(rendered.count("Rejected raw completion"), 2)
        self.assertEqual(rendered.count("Player · rejected output"), 2)
        self.assertEqual(rendered.count("Oracle · no call"), 2)
        self.assertIn("PRIMARY_ONLY &lt;img src=x onerror=alert(1)&gt;", rendered)
        self.assertIn(
            "REPAIR_ONLY &lt;script&gt;alert(&#x27;x&#x27;)&lt;/script&gt;", rendered
        )
        self.assertNotIn("<img src=x onerror=alert(1)>", rendered)
        self.assertNotIn("<script>alert('x')</script>", rendered)
        self.assertIn("player_output_invalid", rendered)

    def test_cli_places_reviewer_ground_truth_after_evaluation_only(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            log_path = root / "episode.jsonl"
            output_dir = root / "rendered"
            truth_path = root / "truth.json"
            write_current_fixture(log_path)
            truth_path.write_text(
                '{"formula":"T = C * L^0.5 <private>",'
                '"mass_exponent":0.0,"reviewer_secret":"truth-only-marker"}',
                encoding="utf-8",
            )

            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                status = main(
                    (
                        str(log_path),
                        "--output-dir",
                        str(output_dir),
                        "--ground-truth-json",
                        str(truth_path),
                    )
                )
            output_path = output_dir / "episode.html"
            rendered = output_path.read_text(encoding="utf-8")

        self.assertEqual(status, 0)
        self.assertEqual(stdout.getvalue().strip(), str(output_path))
        self.assertIn("Private ground truth — revealed post-run", rendered)
        self.assertIn("&lt;private&gt;", rendered)
        self.assertNotIn("<private>", rendered)
        public_start = rendered.index('id="public-case"')
        public_end = rendered.index("</section>", public_start)
        truth_start = rendered.index('id="ground-truth"')
        evaluation_start = rendered.index('id="evaluation"')
        self.assertNotIn("truth-only-marker", rendered[public_start:public_end])
        self.assertLess(public_end, truth_start)
        self.assertLess(evaluation_start, truth_start)

    def test_rejects_unpaired_actions(self):
        with tempfile.TemporaryDirectory() as directory:
            log_path = Path(directory) / "episode.jsonl"
            write_current_fixture(log_path)
            loaded = load_run_log(str(log_path))

        events = tuple(
            event
            for event in loaded.events
            if not (
                event["event_type"] == "protocol.transition"
                and event["payload"]["action_index"] == 1
            )
        )
        malformed = LoadedRunLog(
            run_id=loaded.run_id,
            events=events,
            complete=True,
        )
        with self.assertRaisesRegex(
            RunLogRenderError,
            "action_index sets differ",
        ):
            render_loaded_run(malformed)


if __name__ == "__main__":
    unittest.main()
