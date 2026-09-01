import copy
import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from role_benchmark import Episode, EpisodeProtocolError
from role_benchmark.cases import make_pendulum_case
from role_benchmark.expression import EXPRESSION_MODEL
from role_benchmark.llm import (
    GenerationConfig,
    GenerationRequest,
    GenerationResponse,
    LLMPlayerBackend,
    Message,
    ModelTransportError,
    TokenUsage,
    build_generation_request,
)
from role_benchmark.llm_oracle import OracleOutputError
from role_benchmark.models import BenchmarkTrack, PlayerAction, TerminationKind
from role_benchmark.protocols import BenchmarkCase, CaseOracle
from role_benchmark.runlog import (
    JSONLRunLog,
    RunLogFormatError,
    RunReplayError,
    load_run_log,
    replay_run_log,
    run_llm_episode,
    run_logged_episode,
)
from role_benchmark.wire import player_action_to_json

from test_wire import experiment_action, final_action, portfolio


def comparison_metadata():
    return {
        "requested_model": "deterministic-fixture",
        "provider_binding": "fake",
        "transport_profile": "plain_text",
        "tool_policy": "none",
        "network_policy": "none",
    }


class SequencedFakeModel:
    def __init__(self, outputs, usage=None):
        self.outputs = list(outputs)
        self.requests = []
        self.usage = usage if usage is not None else TokenUsage(10, 5)

    def generate(self, request):
        self.requests.append(request)
        if not self.outputs:
            raise AssertionError("fake model received an unexpected call")
        return GenerationResponse(
            text=self.outputs.pop(0),
            provider="fake",
            model="deterministic-fixture",
            finish_reason="stop",
            response_id="fake-%d" % len(self.requests),
            usage=self.usage,
        )


class HistoryMutatingPlayer:
    def __init__(self):
        self.turn = 0

    def next_action(self, view):
        self.turn += 1
        if self.turn == 1:
            return experiment_action()
        view.turns[0].proposal.controls["length_m"] = 9.0
        view.turns[0].response.evidence.measurements["period_s"] = 999.0
        view.turns[0].response.evidence.units["period_s"] = "forged"
        view.turns[0].response.evidence.uncertainty["period_s"] = "forged"
        return final_action()


def rewrite_log(events, path, *, reorder=None, mutate=None):
    ordered = list(reorder(events) if reorder is not None else events)
    with JSONLRunLog(str(path), run_id=events[0]["run_id"]) as writer:
        for event in ordered:
            payload = copy.deepcopy(event["payload"])
            if mutate is not None:
                mutate(event, payload)
            writer.append(event["event_type"], payload)


class LLMDevelopmentLoopTest(unittest.TestCase):
    def test_player_and_oracle_llms_share_one_replayable_log(self):
        player = SequencedFakeModel(
            (
                player_action_to_json(experiment_action()),
                player_action_to_json(final_action()),
            )
        )
        case = make_pendulum_case("historical")
        authoritative = CaseOracle(case.definition, case.world_model).respond(
            experiment_action().experiment
        )
        oracle_message = authoritative.message
        oracle = SequencedFakeModel(
            (json.dumps({"message": oracle_message}, separators=(",", ":")),)
        )

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "two-role.jsonl"
            run = run_llm_episode(
                player,
                case,
                str(path),
                oracle_backend=oracle,
                run_metadata=comparison_metadata(),
            )

            self.assertEqual(len(player.requests), 2)
            self.assertEqual(len(oracle.requests), 1)
            self.assertEqual(run.oracle_llm_stats.oracle_turns, 1)
            self.assertEqual(run.oracle_llm_stats.generation_calls, 1)
            self.assertEqual(run.oracle_llm_stats.parsed_messages, 1)
            self.assertEqual(run.oracle_llm_stats.input_tokens, 10)
            self.assertEqual(run.oracle_llm_stats.output_tokens, 5)
            self.assertEqual(run.result.turns[0].response.message, oracle_message)
            self.assertIn(
                "period_s",
                run.result.turns[0].response.evidence.measurements,
            )

            loaded = load_run_log(str(path))
            started = loaded.events[0]["payload"]
            self.assertEqual(
                set(loaded.events[0]),
                {"run_id", "sequence", "event_type", "recorded_at", "payload"},
            )
            self.assertEqual(
                set(started),
                {
                    "evaluation_profile",
                    "case",
                    "action_schema",
                    "player_kind",
                    "llm_config",
                    "policy",
                    "oracle_mode",
                    "oracle_llm_config",
                    "run_metadata",
                },
            )
            self.assertEqual(started["oracle_mode"], "llm_case")
            self.assertIsInstance(started["oracle_llm_config"], dict)
            self.assertEqual(
                started["oracle_llm_config"]["generation_policy"],
                "authoritative_message_exact_copy_one_call",
            )
            self.assertEqual(
                set(started["llm_config"]),
                {
                    "evaluation_profile",
                    "action_schema",
                    "generation_config",
                    "max_action_bytes",
                    "max_repair_attempts",
                    "generation_policy",
                },
            )
            self.assertEqual(
                set(started["oracle_llm_config"]),
                {
                    "evaluation_profile",
                    "message_schema",
                    "generation_config",
                    "max_output_bytes",
                    "generation_policy",
                },
            )
            event_types = [event["event_type"] for event in loaded.events]
            self.assertEqual(
                event_types[4:9],
                [
                    "action.decoded",
                    "oracle.model.requested",
                    "oracle.model.completed",
                    "oracle.output.parsed",
                    "protocol.transition",
                ],
            )
            oracle_events = [
                event
                for event in loaded.events
                if event["event_type"].startswith("oracle.")
            ]
            self.assertEqual(
                [event["event_type"] for event in oracle_events],
                [
                    "oracle.model.requested",
                    "oracle.model.completed",
                    "oracle.output.parsed",
                ],
            )
            self.assertEqual(oracle_events[0]["payload"]["call_index"], 1)
            self.assertEqual(oracle_events[0]["payload"]["oracle_turn"], 1)
            self.assertEqual(
                oracle_events[0]["payload"]["purpose"],
                "present_authoritative_response",
            )
            oracle_request = oracle.requests[0]
            self.assertIn(
                "exact character-for-character copy",
                oracle_request.messages[0].content,
            )
            self.assertEqual(
                oracle_request.response_schema["properties"]["message"]["const"],
                oracle_message,
            )
            parsed_response = oracle_events[2]["payload"]["oracle_response"]
            self.assertEqual(
                set(oracle_events[2]["payload"]),
                {"call_index", "oracle_turn", "oracle_response"},
            )
            self.assertEqual(parsed_response["message"], oracle_message)
            first_transition = next(
                event
                for event in loaded.events
                if event["event_type"] == "protocol.transition"
            )
            self.assertEqual(
                parsed_response,
                first_transition["payload"]["outcome"]["oracle_response"],
            )
            final_transition = [
                event
                for event in loaded.events
                if event["event_type"] == "protocol.transition"
            ][-1]
            self.assertEqual(
                final_transition["payload"]["outcome"]["trajectory_scores"],
                dict(run.result.trajectory_scores),
            )

            player_calls_before_replay = len(player.requests)
            oracle_calls_before_replay = len(oracle.requests)
            replay = replay_run_log(str(path), make_pendulum_case("historical"))
            self.assertEqual(replay.action_count, 2)
            self.assertEqual(replay.prompt_requests_checked, 3)
            self.assertEqual(len(player.requests), player_calls_before_replay)
            self.assertEqual(len(oracle.requests), oracle_calls_before_replay)
            self.assertEqual(
                replay.result.turns[0].response.message,
                oracle_message,
            )

            tampered = Path(directory) / "tampered-oracle.jsonl"

            def change_oracle_completion(event, payload):
                if event["event_type"] == "oracle.model.completed":
                    payload["response"]["text"] = (
                        '{"message":"A different presentation."}'
                    )
                elif event["event_type"] == "oracle.output.parsed":
                    payload["oracle_response"]["message"] = (
                        "A different presentation."
                    )
                elif (
                    event["event_type"] == "protocol.transition"
                    and payload.get("outcome_kind") == "experiment_evidence"
                ):
                    payload["outcome"]["oracle_response"]["message"] = (
                        "A different presentation."
                    )

            rewrite_log(
                loaded.events,
                tampered,
                mutate=change_oracle_completion,
            )
            with self.assertRaises(RunReplayError):
                replay_run_log(
                    str(tampered),
                    make_pendulum_case("historical"),
                )

    def test_repair_logged_run_and_replay(self):
        fake = SequencedFakeModel(
            (
                "```json\n{}\n```",
                player_action_to_json(experiment_action()),
                player_action_to_json(final_action()),
            )
        )
        case = make_pendulum_case("historical")
        with tempfile.TemporaryDirectory() as directory:
            log_path = str(Path(directory) / "run.jsonl")
            run = run_llm_episode(
                fake,
                case,
                log_path,
                run_id="development-test-run",
                config=GenerationConfig(
                    max_output_tokens=2048,
                    temperature=0.0,
                    top_p=1.0,
                    seed=7,
                ),
                max_repair_attempts=1,
                run_metadata=comparison_metadata(),
            )

            self.assertTrue(run.result.evaluation.success)
            self.assertEqual(run.result.attempts_used, 1)
            self.assertEqual(run.llm_stats.primary_calls, 2)
            self.assertEqual(run.llm_stats.repair_calls, 1)
            self.assertEqual(run.llm_stats.first_pass_valid_actions, 1)
            self.assertEqual(run.llm_stats.input_tokens, 30)
            self.assertEqual(len(fake.requests), 3)
            self.assertEqual(fake.requests[1].metadata["purpose"], "repair_action")

            loaded = load_run_log(log_path)
            self.assertTrue(loaded.complete)
            self.assertEqual(loaded.run_id, "development-test-run")
            self.assertIn("```json", Path(log_path).read_text(encoding="utf-8"))

            replay = replay_run_log(
                log_path,
                make_pendulum_case("historical"),
            )
            self.assertEqual(replay.action_count, 2)
            self.assertEqual(replay.parser_actions_checked, 2)
            self.assertEqual(replay.failed_parses_checked, 1)
            self.assertEqual(replay.format_regenerations_checked, 1)
            self.assertEqual(replay.prompt_requests_checked, 3)
            self.assertEqual(
                replay.result.evaluation.scores,
                run.result.evaluation.scores,
            )

    def test_log_loader_rejects_truncation(self):
        fake = SequencedFakeModel((player_action_to_json(final_action()),))
        with tempfile.TemporaryDirectory() as directory:
            log_path = Path(directory) / "run.jsonl"
            run_llm_episode(
                fake,
                make_pendulum_case("historical"),
                str(log_path),
                run_id="format-test-run",
            )
            self.assertTrue(load_run_log(str(log_path)).complete)
            original = log_path.read_text(encoding="utf-8")
            log_path.write_text(original[:-1], encoding="utf-8")
            with self.assertRaises(RunLogFormatError):
                load_run_log(str(log_path))

    def test_default_baseline_does_not_generate_again_after_invalid_output(self):
        fake = SequencedFakeModel(("not json", player_action_to_json(final_action())))
        with tempfile.TemporaryDirectory() as directory:
            log_path = Path(directory) / "baseline-invalid.jsonl"
            run = run_llm_episode(
                fake,
                make_pendulum_case("historical"),
                str(log_path),
                run_metadata=comparison_metadata(),
            )
            self.assertEqual(len(fake.requests), 1)
            self.assertIs(
                run.outcome.termination.kind,
                TerminationKind.PLAYER_OUTPUT_INVALID,
            )
            self.assertEqual(run.outcome.termination.code, "invalid_json")
            self.assertEqual(run.outcome.termination.generation_attempts, 1)
            self.assertFalse(run.outcome.scientifically_evaluable)
            with self.assertRaises(EpisodeProtocolError):
                _ = run.result
            loaded = load_run_log(str(log_path))
            self.assertTrue(loaded.complete)
            started = loaded.events[0]["payload"]
            self.assertEqual(started["llm_config"]["max_repair_attempts"], 0)
            self.assertEqual(
                loaded.events[-1]["payload"]["status"],
                "evaluated",
            )
            self.assertEqual(loaded.events[-2]["event_type"], "episode.terminal")
            calls_before_replay = len(fake.requests)
            replay = replay_run_log(
                str(log_path), make_pendulum_case("historical")
            )
            self.assertIs(
                replay.outcome.termination.kind,
                TerminationKind.PLAYER_OUTPUT_INVALID,
            )
            self.assertEqual(replay.action_count, 0)
            self.assertEqual(replay.failed_parses_checked, 1)
            self.assertEqual(len(fake.requests), calls_before_replay)

    def test_oversized_provider_output_is_omitted_and_classified(self):
        oversized = "x" * 4_300_000
        fake = SequencedFakeModel((oversized,))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "oversized.jsonl"
            run = run_llm_episode(
                fake,
                make_pendulum_case("historical"),
                str(path),
                run_metadata=comparison_metadata(),
            )
            loaded = load_run_log(str(path))
            completions = [
                event
                for event in loaded.events
                if event["event_type"] == "model.completed"
            ]
            self.assertEqual(completions[0]["payload"]["status"], "output_rejected")
            summary = completions[0]["payload"]["response_summary"]
            self.assertEqual(summary["text_bytes"], len(oversized))
            self.assertTrue(summary["text_omitted"])
            self.assertNotIn(oversized[:1000], path.read_text(encoding="utf-8"))
            self.assertEqual(
                loaded.events[-1]["payload"]["status"],
                "evaluated",
            )
            self.assertEqual(
                run.outcome.termination.code,
                "payload_too_large",
            )
            replay = replay_run_log(str(path), make_pendulum_case("historical"))
            self.assertEqual(replay.action_count, 0)
            self.assertEqual(replay.failed_parses_checked, 0)

    def test_protocol_invalid_final_is_scored_and_replayable(self):
        base = final_action()
        rejected = PlayerAction.submit_final(
            portfolio(0.89),
            base.final,
        )
        fake = SequencedFakeModel((player_action_to_json(rejected),))
        case = make_pendulum_case("historical")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "rejected.jsonl"
            run = run_llm_episode(fake, case, str(path))

            self.assertIs(
                run.outcome.termination.kind,
                TerminationKind.SUBMITTED,
            )
            self.assertEqual(
                run.outcome.termination.code,
                "submitted_with_protocol_violations",
            )
            self.assertTrue(run.outcome.scientifically_evaluable)
            self.assertFalse(run.outcome.protocol_completed)
            self.assertIsNone(run.outcome.candidate_action)
            self.assertEqual(run.outcome.evaluation.scores["active_pass"], 0.0)
            events = load_run_log(str(path)).events
            self.assertEqual(events[-2]["event_type"], "episode.terminal")
            self.assertEqual(
                events[-3]["payload"]["outcome_kind"],
                "final_evaluation",
            )

            calls_before_replay = len(fake.requests)
            replay = replay_run_log(str(path), make_pendulum_case("historical"))
            self.assertIs(
                replay.outcome.termination.kind,
                TerminationKind.SUBMITTED,
            )
            self.assertFalse(replay.outcome.protocol_completed)
            self.assertEqual(replay.result.final_submission, rejected.final)
            self.assertEqual(replay.action_count, 1)
            self.assertEqual(len(fake.requests), calls_before_replay)

    def test_action_limit_is_an_evaluated_replayable_outcome(self):
        fake = SequencedFakeModel(
            (
                player_action_to_json(experiment_action()),
                player_action_to_json(experiment_action()),
            )
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "action-limit.jsonl"
            run = run_llm_episode(
                fake,
                make_pendulum_case("historical"),
                str(path),
                max_actions=2,
            )

            self.assertIs(
                run.outcome.termination.kind,
                TerminationKind.ACTION_LIMIT,
            )
            self.assertEqual(run.outcome.termination.action_index, 2)
            self.assertEqual(run.outcome.attempts_used, 2)
            replay = replay_run_log(str(path), make_pendulum_case("historical"))
            self.assertIs(
                replay.outcome.termination.kind,
                TerminationKind.ACTION_LIMIT,
            )
            self.assertEqual(replay.action_count, 2)

    def test_second_invalid_generation_replays_without_an_llm_call(self):
        fake = SequencedFakeModel(("not json", "still not json"))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "twice-invalid.jsonl"
            run = run_llm_episode(
                fake,
                make_pendulum_case("historical"),
                str(path),
                max_repair_attempts=1,
            )
            self.assertEqual(run.outcome.termination.generation_attempts, 2)
            self.assertEqual(len(fake.requests), 2)

            replay = replay_run_log(str(path), make_pendulum_case("historical"))
            self.assertEqual(replay.failed_parses_checked, 2)
            self.assertEqual(replay.format_regenerations_checked, 1)
            self.assertEqual(replay.prompt_requests_checked, 2)
            self.assertEqual(len(fake.requests), 2)

    def test_discovery_uses_the_same_logged_llm_entry_point(self):
        discovery = make_pendulum_case(
            "historical", track=BenchmarkTrack.DISCOVERY
        )
        base_final = final_action()
        discovery_final = PlayerAction.submit_final(
            base_final.portfolio,
            replace(
                base_final.final,
                model=EXPRESSION_MODEL,
                parameters={
                    "outputs": {
                        "period_s": {
                            "op": "multiply",
                            "args": [
                                2.006409,
                                {
                                    "op": "power",
                                    "args": [{"var": "length_m"}, 0.5],
                                },
                            ],
                        }
                    }
                },
            ),
        )
        fake = SequencedFakeModel((player_action_to_json(discovery_final),))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "discovery.jsonl"
            run = run_llm_episode(fake, discovery, str(path))
            self.assertTrue(path.exists())
            self.assertEqual(len(fake.requests), 1)
            self.assertIs(run.result.track, BenchmarkTrack.DISCOVERY)
            self.assertTrue(run.result.evaluation.success)

    def test_unknown_usage_is_not_reported_as_zero(self):
        fake = SequencedFakeModel(
            (player_action_to_json(final_action()),), usage=TokenUsage()
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "unknown-usage.jsonl"
            run = run_llm_episode(
                fake,
                make_pendulum_case("historical"),
                str(path),
                run_metadata=comparison_metadata(),
            )
            self.assertIsNone(run.llm_stats.input_tokens)
            self.assertIsNone(run.llm_stats.output_tokens)
            replay = replay_run_log(str(path), make_pendulum_case("historical"))
            self.assertEqual(replay.action_count, 1)

    def test_prompt_and_adapter_value_objects_match_the_wire_contract(self):
        request = build_generation_request(
            Episode(make_pendulum_case("historical")).view(),
            player_turn=1,
            config=GenerationConfig(),
        )
        system = request.messages[0].content
        self.assertIn("final.explanation", system)
        self.assertNotIn("The rationale field", system)
        self.assertNotIn("$defs", request.response_schema)

        discovery_request = build_generation_request(
            Episode(
                make_pendulum_case("historical", BenchmarkTrack.DISCOVERY)
            ).view(),
            player_turn=1,
            config=GenerationConfig(),
        )
        self.assertIn("$defs", discovery_request.response_schema)

        schema_source = {"nested": {"enum": ["a"]}}
        metadata_source = {"nested": [1]}
        detached = GenerationRequest(
            messages=(Message("system", "s"), Message("user", "u")),
            response_schema=schema_source,
            config=GenerationConfig(),
            metadata=metadata_source,
        )
        schema_source["nested"]["enum"].append("b")
        metadata_source["nested"].append(2)
        self.assertEqual(detached.response_schema["nested"]["enum"], ["a"])
        self.assertEqual(detached.metadata["nested"], [1])
        json.dumps(detached.response_schema)

        response_metadata = {"nested": [1]}
        response = GenerationResponse(
            text="{}", provider="p", model="m", metadata=response_metadata
        )
        response_metadata["nested"].append(2)
        self.assertEqual(response.metadata["nested"], [1])

        with self.assertRaises(ValueError):
            GenerationResponse(text="{}", provider="p", model="m", usage=None)
        with self.assertRaises(ValueError):
            GenerationResponse(text="{}", provider="\ud800", model="m")
        with self.assertRaises(ValueError):
            GenerationRequest(
                messages=(Message("system", "s"),),
                response_schema={},
                config=None,
            )
        with self.assertRaises(ValueError):
            LLMPlayerBackend(SequencedFakeModel(()), config=False)
        with self.assertRaises(ValueError):
            LLMPlayerBackend(SequencedFakeModel(()), max_repair_attempts=True)

    def test_backend_request_mutation_is_a_transport_error(self):
        class MutatingBackend:
            def generate(self, request):
                request.metadata["mutated"] = True
                return GenerationResponse(
                    text=player_action_to_json(final_action()),
                    provider="fake",
                    model="mutator",
                )

        player = LLMPlayerBackend(MutatingBackend())
        with self.assertRaises(ModelTransportError):
            player.next_action(Episode(make_pendulum_case()).view())

        class MutatingResponseBackend:
            def generate(self, request):
                response = GenerationResponse(text="{}", provider="fake", model="m")
                response.metadata["cycle"] = response.metadata
                return response

        with self.assertRaises(ModelTransportError):
            LLMPlayerBackend(MutatingResponseBackend()).next_action(
                Episode(make_pendulum_case()).view()
            )

    def test_transport_oracle_and_evaluator_failures_still_raise(self):
        class FailingTransport:
            def generate(self, request):
                raise RuntimeError("network unavailable")

        class FailingEvaluator:
            def evaluate(self, submission):
                raise RuntimeError("evaluator unavailable")

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaises(ModelTransportError):
                run_llm_episode(
                    FailingTransport(),
                    make_pendulum_case("historical"),
                    str(root / "transport.jsonl"),
                )

            with self.assertRaises(OracleOutputError):
                run_llm_episode(
                    SequencedFakeModel(
                        (player_action_to_json(experiment_action()),)
                    ),
                    make_pendulum_case("historical"),
                    str(root / "oracle.jsonl"),
                    oracle_backend=SequencedFakeModel(("not json",)),
                )

            base = make_pendulum_case("historical")
            broken = BenchmarkCase(
                base.definition,
                base.world_model,
                FailingEvaluator(),
            )
            with self.assertRaisesRegex(RuntimeError, "evaluator unavailable"):
                run_llm_episode(
                    SequencedFakeModel(
                        (player_action_to_json(final_action()),)
                    ),
                    broken,
                    str(root / "evaluator.jsonl"),
                )

            for name in ("transport.jsonl", "oracle.jsonl", "evaluator.jsonl"):
                loaded = load_run_log(str(root / name))
                self.assertEqual(
                    loaded.events[-1]["payload"]["status"],
                    "infrastructure_error",
                )
                self.assertNotIn(
                    "episode.terminal",
                    [event["event_type"] for event in loaded.events],
                )

    def test_oracle_paraphrase_is_an_infrastructure_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "oracle-paraphrase.jsonl"
            with self.assertRaises(OracleOutputError) as raised:
                run_llm_episode(
                    SequencedFakeModel(
                        (player_action_to_json(experiment_action()),)
                    ),
                    make_pendulum_case("historical"),
                    str(path),
                    oracle_backend=SequencedFakeModel(
                        ('{"message":"A neutral but rewritten response."}',)
                    ),
                )

            self.assertEqual(raised.exception.wire_error.code, "value_mismatch")
            loaded = load_run_log(str(path))
            event_types = [event["event_type"] for event in loaded.events]
            self.assertIn("oracle.output.validation_failed", event_types)
            self.assertNotIn("oracle.output.parsed", event_types)
            transition = next(
                event
                for event in loaded.events
                if event["event_type"] == "protocol.transition"
            )
            self.assertEqual(
                transition["payload"]["outcome_kind"], "oracle_output_invalid"
            )
            self.assertEqual(
                loaded.events[-1]["payload"]["status"], "infrastructure_error"
            )
            self.assertEqual(
                loaded.events[-1]["payload"]["stop_reason"],
                "oracle_output_invalid",
            )

    def test_replay_rejects_causal_reordering(self):
        with tempfile.TemporaryDirectory() as directory:
            original = Path(directory) / "original.jsonl"
            run_llm_episode(
                SequencedFakeModel((player_action_to_json(final_action()),)),
                make_pendulum_case("historical"),
                str(original),
                run_metadata=comparison_metadata(),
            )
            events = load_run_log(str(original)).events

            def reorder(items):
                items = list(items)
                items[2], items[3] = items[3], items[2]
                return items

            rewritten = Path(directory) / "reordered.jsonl"
            rewrite_log(events, rewritten, reorder=reorder)
            self.assertTrue(load_run_log(str(rewritten)).complete)
            with self.assertRaises(RunReplayError):
                replay_run_log(str(rewritten), make_pendulum_case("historical"))

    def test_replay_rechecks_failed_parse(self):
        invalid = "not json"
        valid = player_action_to_json(final_action())
        with tempfile.TemporaryDirectory() as directory:
            original = Path(directory) / "repair.jsonl"
            run_llm_episode(
                SequencedFakeModel((invalid, valid)),
                make_pendulum_case("historical"),
                str(original),
                max_repair_attempts=1,
                run_metadata=comparison_metadata(),
            )
            events = load_run_log(str(original)).events

            rewritten = Path(directory) / "false-failure.jsonl"

            def mutate(event, payload):
                if (
                    event["event_type"] == "model.completed"
                    and payload.get("purpose") == "next_action"
                ):
                    payload["response"]["text"] = valid

            rewrite_log(events, rewritten, mutate=mutate)
            self.assertTrue(load_run_log(str(rewritten)).complete)
            with self.assertRaises(RunReplayError):
                replay_run_log(str(rewritten), make_pendulum_case("historical"))

    def test_replay_uses_recorded_action_byte_limit(self):
        large_action = PlayerAction.submit_final(
            final_action().portfolio,
            replace(final_action().final, explanation="x" * 70_000),
        )
        raw = player_action_to_json(large_action, max_bytes=100_000)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "large-action.jsonl"
            run_llm_episode(
                SequencedFakeModel((raw,)),
                make_pendulum_case("historical"),
                str(path),
                max_action_bytes=100_000,
                run_metadata=comparison_metadata(),
            )
            replay = replay_run_log(str(path), make_pendulum_case("historical"))
            self.assertEqual(replay.action_count, 1)

    def test_large_bounded_actions_still_produce_a_complete_replayable_log(self):
        experiment = experiment_action()
        large_experiment = PlayerAction.propose_experiment(
            experiment.portfolio,
            replace(experiment.experiment, intent="x" * 280_000),
        )
        final = final_action()
        large_final = PlayerAction.submit_final(
            final.portfolio,
            replace(final.final, explanation="x" * 900_000),
        )
        outputs = [
            player_action_to_json(large_experiment, max_bytes=1_048_576)
            for _ in range(3)
        ]
        outputs.append(player_action_to_json(large_final, max_bytes=1_048_576))

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "large-multiturn.jsonl"
            run_llm_episode(
                SequencedFakeModel(outputs),
                make_pendulum_case("historical"),
                str(path),
                max_action_bytes=1_048_576,
                run_metadata=comparison_metadata(),
            )
            self.assertTrue(load_run_log(str(path)).complete)
            replay = replay_run_log(str(path), make_pendulum_case("historical"))
            self.assertEqual(replay.action_count, 4)

    def test_player_cannot_mutate_episode_history_through_its_view(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "defensive-view.jsonl"
            with JSONLRunLog(str(path), run_id="defensive-view") as log:
                result = run_logged_episode(
                    HistoryMutatingPlayer(),
                    make_pendulum_case("historical"),
                    log,
                    run_metadata=comparison_metadata(),
                )
            recorded_period = result.turns[0].response.evidence.measurements[
                "period_s"
            ]
            self.assertNotEqual(recorded_period, 999.0)
            replay = replay_run_log(str(path), make_pendulum_case("historical"))
            self.assertEqual(replay.action_count, 2)


if __name__ == "__main__":
    unittest.main()
