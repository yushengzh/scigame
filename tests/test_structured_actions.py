"""Formatting must not change experimental choices or scientific scoring."""

import copy
from dataclasses import replace
import json
from pathlib import Path
import tempfile
import unittest

from experiments.codex_structured_backend import validate_fresh_thread
from experiments.openai_responses import OpenAIResponsesBackend
from role_benchmark import Episode, prepare_evaluation_case, run_llm_episode, replay_run_log
from role_benchmark.llm import (
    GenerationConfig, GenerationResponse, LLMPlayerBackend,
    PLAYER_PROMPT_VERSION_V4_STRUCTURED, build_generation_request,
    decode_player_response,
)
from role_benchmark.structured_actions import (
    STRUCTURED_ACTION_SCHEMA, structured_action_from_json,
    structured_action_json_schema, structured_action_to_payload,
)
from role_benchmark.wire import WireDecodeError, player_action_to_payload
import test_unlimited_adaptive


class StructuredBackend:
    supports_strict_action_schema = True

    def __init__(self, outputs):
        self.outputs = iter(outputs)
        self.requests = []

    def generate(self, request):
        self.requests.append(request)
        return GenerationResponse(text=next(self.outputs), provider="fixture", model="fixture")


class StructuredActionTests(unittest.TestCase):
    def setUp(self):
        self.fixture = test_unlimited_adaptive.UnlimitedAdaptiveTests()
        self.fixture.setUp()
        self.fixture.case = replace(self.fixture.case, definition=replace(
            self.fixture.case.definition, count_all_experiment_attempts=True))

    def encode(self, action):
        return json.dumps(structured_action_to_payload(action))

    def run_actions(self, actions, prepared=None):
        case = self.fixture.case if prepared is None else prepared.case
        options = {} if prepared is None else {
            "observation_budget": prepared.plan.observation_budget,
            "initial_attempts_used": prepared.initial_attempts_used,
            "require_budget_exhaustion": prepared.plan.require_budget_exhaustion,
        }
        backend = StructuredBackend(self.encode(action) for action in actions)
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / "episode.jsonl")
            run = run_llm_episode(backend, case, path, max_actions=None,
                player_prompt_version=PLAYER_PROMPT_VERSION_V4_STRUCTURED, **options)
            replay = replay_run_log(path, case)
            self.assertEqual(replay.outcome, run.outcome)
        return run, backend

    def test_round_trip_preserves_expression_and_all_scientific_fields(self):
        for action in (self.fixture.experiment(), self.fixture.final()):
            self.assertEqual(player_action_to_payload(structured_action_from_json(self.encode(action))),
                             player_action_to_payload(action))

    def test_long_legal_submission_is_evaluated_and_replayable(self):
        action = self.fixture.final()
        parameters = copy.deepcopy(action.final.parameters)
        name = next(iter(parameters["outputs"]))
        variable = self.fixture.spec.controls[0].name
        # Expand a reference predictor with exact-zero terms. This tests the
        # real structured-action, episode, evaluator and log replay paths.
        parameters["outputs"][name] = {"op": "add", "args": [
            parameters["outputs"][name],
            *[{"op": "subtract", "args": [
                {"op": "cos", "args": [{"var": variable}]},
                {"op": "cos", "args": [{"var": variable}]},
            ]} for _ in range(150)],
        ]}
        action = replace(action, final=replace(action.final, parameters=parameters,
            explanation="Synthetic explanation. " * 3500))
        self.assertGreater(len(self.encode(action).encode()), 65_536)
        run, backend = self.run_actions([action])
        self.assertTrue(run.outcome.evaluation.success)
        self.assertIsNotNone(run.outcome.final_submission)
        self.assertEqual(len(backend.requests), 1)

    def test_generic_parameters_and_nested_control_values_are_lossless(self):
        payload = structured_action_to_payload(self.fixture.final())
        payload["final"]["model"] = "case_owned_model"
        payload["final"]["parameters"] = {"entries": [
            {"name": "p", "value": {"entries": [{"name": "nested", "value": [2, True, None]}]}}]}
        action = structured_action_from_json(json.dumps(payload))
        self.assertEqual(action.final.parameters, {"p": {"nested": [2, True, None]}})

    def test_duplicate_names_are_rejected_not_overwritten(self):
        for root, key in (("experiment", "controls"), ("experiment", "forecasts")):
            payload = structured_action_to_payload(self.fixture.experiment())
            payload[root][key].append(copy.deepcopy(payload[root][key][0]))
            with self.assertRaises(WireDecodeError) as error:
                structured_action_from_json(json.dumps(payload))
            self.assertEqual(error.exception.code, "duplicate_key")
        payload = structured_action_to_payload(self.fixture.final())
        outputs = payload["final"]["parameters"]["outputs"]
        outputs.append(copy.deepcopy(outputs[0]))
        with self.assertRaises(WireDecodeError):
            structured_action_from_json(json.dumps(payload))

    def test_schema_does_not_encode_scientific_limits(self):
        schema = structured_action_json_schema()
        forbidden = {"minimum", "maximum", "pattern",
                     "allOf", "oneOf", "if", "then", "not"}

        def visit(node, path="$"):
            if isinstance(node, dict):
                self.assertFalse(forbidden & set(node), path)
                if "properties" in node:
                    self.assertIs(node["additionalProperties"], False)
                    self.assertEqual(set(node["required"]), set(node["properties"]))
                if "enum" in node:
                    self.assertTrue(path in ("$.properties.wire_schema", "$.properties.kind")
                        or (path.startswith("$.$defs.expression.anyOf.") and path.endswith(".properties.op")), path)
                if {"minItems", "maxItems"} & set(node):
                    self.assertTrue(path.startswith("$.$defs.expression.anyOf.")
                        and path.endswith(".properties.args"), path)
                for key, value in node.items():
                    visit(value, path + "." + key)
            elif isinstance(node, list):
                for i, value in enumerate(node):
                    visit(value, path + ".%d" % i)
        visit(schema)
        request = build_generation_request(Episode(self.fixture.case).view(), player_turn=1,
            config=GenerationConfig(), prompt_version=PLAYER_PROMPT_VERSION_V4_STRUCTURED)
        self.assertEqual(request.response_schema, schema)
        self.assertIs(request.metadata["require_structured_output"], True)

    def test_expression_schema_covers_executable_grammar_and_rejects_bad_arity(self):
        from role_benchmark.expression import EXPRESSION_OPERATOR_ARITIES
        variants = structured_action_json_schema()["$defs"]["expression"]["anyOf"][2:]
        bounds = {op: (branch["properties"]["args"]["minItems"],
                       branch["properties"]["args"].get("maxItems"))
                  for branch in variants for op in branch["properties"]["op"]["enum"]}
        self.assertEqual(bounds, dict(EXPRESSION_OPERATOR_ARITIES))
        # These completed responses previously satisfied the provider schema
        # but could not be executed. Check both sides of the public contract.
        for op, count in (("power", 5), ("divide", 1), ("multiply", 1), ("invented", 2)):
            with self.subTest(op=op, count=count):
                self.assertFalse(op in bounds and count >= bounds[op][0]
                    and (bounds[op][1] is None or count <= bounds[op][1]))
                payload = structured_action_to_payload(self.fixture.final())
                payload["final"]["parameters"]["outputs"][0]["value"] = {"op": op, "args": [1] * count}
                with self.assertRaises(WireDecodeError):
                    structured_action_from_json(json.dumps(payload))

    def test_oversized_answer_has_resource_attribution_and_replays(self):
        from experiments.run_structured_case44 import measurements
        action = self.fixture.final()
        action = replace(action, final=replace(action.final, explanation="x" * 270000))
        run, backend = self.run_actions([action])
        result = measurements(run.outcome)
        self.assertTrue(result["resource_limit_failure"])
        self.assertFalse(result["serialization_failure"])
        self.assertFalse(result["contract_failure"])
        self.assertIsNone(result["scientific_pass"])
        self.assertEqual(len(backend.requests), 1)
        self.assertEqual(run.llm_stats.repair_calls, 0)

    def test_illegal_apparatus_survives_formatting_and_counts_as_an_attempt(self):
        run, backend = self.run_actions([self.fixture.experiment(invalid=True), self.fixture.final()])
        self.assertEqual(run.outcome.attempts_used, 1)
        self.assertTrue(run.outcome.active_pass)
        self.assertIsNone(run.outcome.turns[0].response.evidence)
        self.assertEqual(run.llm_stats.repair_calls, 0)
        self.assertEqual(len(backend.requests), 2)

    def test_missing_unknown_and_out_of_range_controls_reach_oracle(self):
        for controls in ({}, {"unknown_variable": 1}, {"length_m": -1000, "amplitude_deg": 10}):
            payload = structured_action_to_payload(self.fixture.experiment())
            payload["experiment"]["controls"] = [{"name": key, "value": value}
                                                 for key, value in controls.items()]
            action = structured_action_from_json(json.dumps(payload))
            episode = Episode(self.fixture.case)
            episode.apply(action)
            self.assertEqual(episode.view().attempts_used, 1)
            self.assertIsNone(episode.view().turns[-1].response.evidence)

    def test_unlimited_adaptive_still_has_no_action_cap(self):
        run, _ = self.run_actions([self.fixture.experiment()] * 21 + [self.fixture.final()])
        self.assertEqual(run.outcome.attempts_used, 21)
        self.assertTrue(run.outcome.active_pass)

    def test_clarification_request_is_counted_and_replays_in_new_protocol(self):
        payload = structured_action_to_payload(self.fixture.experiment())
        payload["experiment"]["controls"] = []
        action = structured_action_from_json(json.dumps(payload))
        run, _ = self.run_actions([action, self.fixture.final()])
        self.assertEqual(run.outcome.attempts_used, 1)
        self.assertEqual(run.outcome.turns[0].response.status.value, "NEEDS_CLARIFICATION")
        self.assertEqual(run.outcome.turns[0].attempt_index, 1)

    def test_result_reporting_does_not_call_missing_answer_scientifically_wrong(self):
        from experiments.run_structured_case44 import measurements
        backend = StructuredBackend(['{"wire_schema":'])
        with tempfile.TemporaryDirectory() as directory:
            run = run_llm_episode(backend, self.fixture.case,
                str(Path(directory) / "failed.jsonl"), max_actions=None,
                player_prompt_version=PLAYER_PROMPT_VERSION_V4_STRUCTURED)
        result = measurements(run.outcome)
        self.assertTrue(result["serialization_failure"])
        self.assertFalse(result["contract_failure"])
        self.assertIsNone(result["scientific_pass"])
        self.assertFalse(result["active_pass"])

    def test_confidence_threshold_does_not_replace_scientific_correctness(self):
        run, _ = self.run_actions([self.fixture.final(world="counterfactual")])
        self.assertTrue(run.outcome.protocol_completed)
        self.assertFalse(run.outcome.active_pass)
        run, _ = self.run_actions([self.fixture.final(confidence=0.9)])
        self.assertFalse(run.outcome.protocol_completed)

    def test_prior_and_fixed_budgets_have_independent_public_contexts(self):
        spec = replace(self.fixture.spec, budget=8,
            diagnostic_conditions=(tuple(self.fixture.spec.diagnostic_conditions) * 8)[:8])
        raw = replace(self.fixture.raw, definition=replace(self.fixture.raw.definition, budget=8))
        for budget in (0, 2, 4, 8):
            method = "prior-only baseline" if budget == 0 else "fixed experimental design"
            kwargs = {} if budget == 0 else {"fixed_budget": budget}
            prepared = prepare_evaluation_case(raw, spec, method, **kwargs)
            run, backend = self.run_actions([self.fixture.final()], prepared)
            self.assertEqual(run.outcome.attempts_used, budget)
            self.assertTrue(run.outcome.active_pass)
            view = json.loads(backend.requests[0].messages[1].content)["episode_view"]
            self.assertEqual(view["attempts_used"], budget)
            self.assertEqual(view["turns"], [])

    def test_malformed_output_is_terminal_and_never_repaired_or_counted(self):
        backend = StructuredBackend(['{"wire_schema":'])
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / "failed.jsonl")
            run = run_llm_episode(backend, self.fixture.case, path, max_actions=None,
                player_prompt_version=PLAYER_PROMPT_VERSION_V4_STRUCTURED)
            replay = replay_run_log(path, self.fixture.case)
            self.assertEqual(replay.outcome, run.outcome)
        self.assertEqual(run.outcome.termination.code, "invalid_json")
        self.assertEqual(run.outcome.attempts_used, 0)
        self.assertFalse(run.outcome.scientifically_evaluable)
        self.assertEqual(run.llm_stats.repair_calls, 0)
        self.assertEqual(len(backend.requests), 1)

    def test_unknown_operator_remains_a_contract_error_not_json_syntax(self):
        payload = structured_action_to_payload(self.fixture.final())
        payload["final"]["parameters"]["outputs"][0]["value"] = {"op": "unsupported", "args": [1]}
        with self.assertRaises(WireDecodeError) as error:
            structured_action_from_json(json.dumps(payload))
        self.assertEqual(error.exception.code, "model_invariant")
        self.assertIn("unsupported", error.exception.detail)

    def test_non_enforcing_backend_and_regeneration_are_disallowed(self):
        class Plain:
            def generate(self, request):
                raise AssertionError("must not be called")
        for backend, retries in ((Plain(), 0), (StructuredBackend([]), 1)):
            with self.assertRaises(ValueError):
                LLMPlayerBackend(backend, max_repair_attempts=retries,
                                 prompt_version=PLAYER_PROMPT_VERSION_V4_STRUCTURED)

    def test_refusal_and_incomplete_output_are_not_json_syntax_errors(self):
        cases = [("provider_refusal", {"metadata": {"content_kind": "refusal"}})]
        cases += [("provider_refusal", {"finish_reason": reason})
                  for reason in ("content_filter", "SAFETY", "prompt_blocked:OTHER")]
        cases += [("incomplete_output", {"finish_reason": reason})
                  for reason in ("incomplete:max_output_tokens", "length", "MAX_TOKENS", "new_unknown_status")]
        for code, kwargs in cases:
            for text in (self.encode(self.fixture.final()), '{"wire_schema":'):
                with self.subTest(code=code, kwargs=kwargs, complete_json=text.endswith("}")):
                    with self.assertRaises(WireDecodeError) as error:
                        decode_player_response(text, prompt_version=PLAYER_PROMPT_VERSION_V4_STRUCTURED, **kwargs)
                    self.assertEqual(error.exception.code, code)
        for reason in ("stop", "STOP", "completed", "end_turn"):
            self.assertEqual(decode_player_response(self.encode(self.fixture.final()),
                prompt_version=PLAYER_PROMPT_VERSION_V4_STRUCTURED, finish_reason=reason), self.fixture.final())

    def test_fresh_native_thread_guard(self):
        workspace = Path("/tmp/synthetic-workspace")
        receipt = {"instructionSources": [], "thread": {"ephemeral": True,
            "turns": [], "forkedFromId": None, "parentThreadId": None, "cwd": str(workspace)}}
        validate_fresh_thread(receipt, workspace)
        for key, value in (("ephemeral", False), ("turns", [{}]),
                           ("forkedFromId", "old"), ("parentThreadId", "old"), ("cwd", "/tmp/other")):
            altered = copy.deepcopy(receipt)
            altered["thread"][key] = value
            with self.assertRaises(RuntimeError):
                validate_fresh_thread(altered, workspace)

    def test_responses_sends_strict_schema_without_shared_response_state(self):
        requests = []

        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                pass

            def read(self):
                return json.dumps({"status": "completed", "output": [{"type": "message",
                    "content": [{"type": "output_text", "text": "{}"}]}]}).encode()

        def send(request, **kwargs):
            requests.append(json.loads(request.data))
            return Response()

        backend = OpenAIResponsesBackend(api_key="synthetic-not-a-key", urlopen=send)
        request = build_generation_request(Episode(self.fixture.case).view(), player_turn=1,
            config=GenerationConfig(), prompt_version=PLAYER_PROMPT_VERSION_V4_STRUCTURED)
        response = backend.generate(request)
        self.assertEqual(requests[0]["text"]["format"]["schema"], request.response_schema)
        self.assertIs(requests[0]["text"]["format"]["strict"], True)
        self.assertFalse(requests[0]["store"])
        self.assertNotIn("previous_response_id", requests[0])
        self.assertEqual(response.metadata["structured_output_transport"], "responses_json_schema_strict")


if __name__ == "__main__":
    unittest.main()
