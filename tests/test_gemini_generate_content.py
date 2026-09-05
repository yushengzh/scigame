from __future__ import annotations

import io
import json
import unittest
import urllib.error
from copy import deepcopy
from types import SimpleNamespace

from role_benchmark import (
    Episode,
    GenerationConfig,
    GenerationRequest,
    Message,
    PLAYER_PROMPT_VERSION_V3_CASE_BOUND_JSON,
)
from role_benchmark.cases import make_pendulum_case
from role_benchmark.llm import build_generation_request

from experiments.gemini_generate_content import (
    GeminiGenerateContentBackend,
    _gemini_messages,
    _project_gemini_request_schema,
    _project_gemini_schema,
)


class _FakeHTTPResponse:
    def __init__(self, payload):
        self._body = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return None

    def read(self):
        return self._body


def _request(*, seed=17):
    return GenerationRequest(
        messages=(
            Message("system", "Return exactly one JSON object."),
            Message("user", "Choose the next action."),
        ),
        response_schema={
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "object",
            "required": ["kind"],
            "minProperties": 1,
            "properties": {
                "kind": {
                    "type": "string",
                    "const": "final",
                    "minLength": 1,
                    "pattern": "^final$",
                }
            },
            "allOf": [{"if": {}, "then": {}}],
        },
        config=GenerationConfig(
            max_output_tokens=2048,
            temperature=0.0,
            top_p=0.95,
            seed=seed,
        ),
    )


class GeminiGenerateContentBackendTests(unittest.TestCase):
    def test_nullable_any_of_uses_type_array_but_true_union_is_preserved(self):
        schema = {
            "type": "object",
            "properties": {
                "score": {
                    "anyOf": [
                        {"type": "number", "minimum": 0.0, "maximum": 1.0},
                        {"type": "null"},
                    ]
                },
                "choice": {
                    "anyOf": [{"type": "string"}, {"type": "number"}]
                },
            },
        }
        original = deepcopy(schema)

        projected = _project_gemini_schema(schema)

        self.assertEqual(schema, original)
        self.assertEqual(
            projected["properties"]["score"],
            {
                "type": ["number", "null"],
                "minimum": 0.0,
                "maximum": 1.0,
            },
        )
        self.assertEqual(
            projected["properties"]["choice"]["anyOf"],
            [{"type": "string"}, {"type": "number"}],
        )

    def test_required_recursive_refs_are_inlined_without_a_depth_cap(self):
        schema = {
            "$defs": {
                "node": {
                    "oneOf": [
                        {"type": "number"},
                        {
                            "type": "object",
                            "properties": {
                                "children": {
                                    "type": "array",
                                    "items": {"$ref": "#/$defs/node"},
                                }
                            },
                            "required": ["children"],
                        },
                    ]
                }
            },
            "type": "object",
            "properties": {"root": {"$ref": "#/$defs/node"}},
            "required": ["root"],
        }

        projected = _project_gemini_schema(schema)
        serialized = json.dumps(projected)

        self.assertNotIn('"$defs"', serialized)
        self.assertNotIn('"$ref"', serialized)
        root = projected["properties"]["root"]
        self.assertEqual(root["oneOf"][0], {"type": "number"})
        self.assertEqual(
            root["oneOf"][1]["properties"]["children"]["items"],
            {"anyOf": [{"type": "number"}, {"type": "object"}]},
        )
        self.assertEqual(root["oneOf"][1]["required"], ["children"])

    def test_case_bound_player_schema_keeps_public_envelope_without_refs(self):
        logical_request = build_generation_request(
            Episode(make_pendulum_case("historical")).view(),
            player_turn=1,
            config=GenerationConfig(),
            prompt_version=PLAYER_PROMPT_VERSION_V3_CASE_BOUND_JSON,
        )

        projected = _project_gemini_schema(logical_request.response_schema)
        serialized = json.dumps(projected)

        self.assertNotIn('"$defs"', serialized)
        self.assertNotIn('"$ref"', serialized)
        controls = projected["properties"]["experiment"]["properties"][
            "controls"
        ]
        self.assertEqual(
            controls["required"],
            ["length_m", "bob_mass_kg", "release_angle_deg"],
        )
        parameters = projected["properties"]["final"]["properties"][
            "parameters"
        ]
        self.assertEqual(parameters["required"], ["outputs"])
        self.assertEqual(
            parameters["properties"]["outputs"]["required"], ["period_s"]
        )
        expression = parameters["properties"]["outputs"]["properties"][
            "period_s"
        ]
        self.assertIn("oneOf", expression)
        self.assertTrue(
            all(
                branch.get("type") != "object" or branch.get("required")
                for branch in expression["oneOf"]
            )
        )

    def test_evaluator_request_relaxes_only_gemini_constraint_hotspots(self):
        logical_schema = {
            "type": "object",
            "properties": {
                "findings": {
                    "type": "array",
                    "maxItems": 32,
                    "items": {
                        "type": "object",
                        "properties": {
                            "score": {
                                "anyOf": [
                                    {
                                        "type": "number",
                                        "minimum": 0.0,
                                        "maximum": 1.0,
                                    },
                                    {"type": "null"},
                                ]
                            }
                        },
                    },
                }
            },
        }
        evaluator_request = GenerationRequest(
            messages=(
                Message("system", "Return exactly one JSON object."),
                Message("user", "Evaluate the transcript."),
            ),
            response_schema=logical_schema,
            config=GenerationConfig(),
            metadata={"purpose": "post_hoc_transcript_evaluation"},
        )
        player_request = GenerationRequest(
            messages=evaluator_request.messages,
            response_schema=logical_schema,
            config=evaluator_request.config,
            metadata={"purpose": "next_action"},
        )

        evaluator_schema = _project_gemini_request_schema(evaluator_request)
        player_schema = _project_gemini_request_schema(player_request)

        self.assertNotIn("maxItems", json.dumps(evaluator_schema))
        self.assertNotIn("minimum", json.dumps(evaluator_schema))
        self.assertNotIn("maximum", json.dumps(evaluator_schema))
        self.assertIn("maxItems", json.dumps(player_schema))
        self.assertIn("minimum", json.dumps(player_schema))
        self.assertIn("maximum", json.dumps(player_schema))
        self.assertEqual(evaluator_request.response_schema, logical_schema)

    def test_maps_request_response_and_usage_without_persisting_key(self):
        captured = {}

        def fake_urlopen(request, timeout):
            captured["api_key"] = request.get_header("X-goog-api-key")
            captured["body"] = json.loads(request.data.decode("utf-8"))
            captured["timeout"] = timeout
            return _FakeHTTPResponse(
                {
                    "responseId": "gemini-response-1",
                    "modelVersion": "gemini-2.5-flash-001",
                    "candidates": [
                        {
                            "finishReason": "STOP",
                            "content": {
                                "role": "model",
                                "parts": [
                                    {"text": "private chain", "thought": True},
                                    {"text": '{"kind":"final"}'},
                                ],
                            },
                        }
                    ],
                    "usageMetadata": {
                        "promptTokenCount": 13,
                        "candidatesTokenCount": 8,
                        "thoughtsTokenCount": 5,
                        "totalTokenCount": 26,
                    },
                }
            )

        backend = GeminiGenerateContentBackend(
            endpoint=(
                "https://generativelanguage.googleapis.com/v1beta/models/"
                "gemini-2.5-flash:generateContent"
            ),
            api_key="runtime-secret",
            model="gemini-2.5-flash",
            timeout_seconds=9.0,
            urlopen=fake_urlopen,
        )
        response = backend.generate(_request())

        self.assertEqual(captured["api_key"], "runtime-secret")
        self.assertEqual(captured["timeout"], 9.0)
        self.assertEqual(
            captured["body"]["systemInstruction"],
            {"parts": [{"text": "Return exactly one JSON object."}]},
        )
        self.assertEqual(
            captured["body"]["contents"],
            [
                {
                    "role": "user",
                    "parts": [{"text": "Choose the next action."}],
                }
            ],
        )
        self.assertEqual(
            captured["body"]["generationConfig"],
            {
                "candidateCount": 1,
                "maxOutputTokens": 2048,
                "temperature": 0.0,
                "topP": 0.95,
                "responseMimeType": "application/json",
                "responseJsonSchema": {
                    "type": "object",
                    "required": ["kind"],
                    "properties": {
                        "kind": {
                            "type": "string",
                            "enum": ["final"],
                        }
                    },
                },
                "seed": 17,
            },
        )
        self.assertNotIn("responseFormat", captured["body"]["generationConfig"])
        transported_schema = captured["body"]["generationConfig"][
            "responseJsonSchema"
        ]
        for unsupported in (
            "$schema",
            "allOf",
            "if",
            "then",
            "const",
            "minLength",
            "pattern",
            "minProperties",
        ):
            self.assertNotIn(unsupported, json.dumps(transported_schema))

        self.assertEqual(response.text, '{"kind":"final"}')
        self.assertEqual(response.provider, "gemini")
        self.assertEqual(response.model, "gemini-2.5-flash-001")
        self.assertEqual(response.finish_reason, "STOP")
        self.assertEqual(response.response_id, "gemini-response-1")
        self.assertEqual(response.usage.input_tokens, 13)
        self.assertEqual(response.usage.output_tokens, 8)
        self.assertEqual(response.metadata["thoughts_tokens"], 5)
        self.assertEqual(response.metadata["total_tokens"], 26)
        self.assertEqual(
            response.metadata["structured_output_transport"],
            "gemini_response_json_schema",
        )
        self.assertNotIn("runtime-secret", json.dumps(response.metadata))

    def test_maps_assistant_role_to_model_for_future_conversation_requests(self):
        system, contents = _gemini_messages(
            [
                SimpleNamespace(role="system", content="Follow the protocol."),
                SimpleNamespace(role="user", content="Observation one."),
                SimpleNamespace(role="assistant", content="Hypothesis one."),
                SimpleNamespace(role="user", content="Observation two."),
            ]
        )

        self.assertEqual(
            system, {"parts": [{"text": "Follow the protocol."}]}
        )
        self.assertEqual(
            [item["role"] for item in contents], ["user", "model", "user"]
        )

    def test_prompt_block_and_truncation_remain_observable_model_output(self):
        payloads = iter(
            [
                {
                    "promptFeedback": {"blockReason": "SAFETY"},
                    "usageMetadata": {"promptTokenCount": 4},
                },
                {
                    "candidates": [
                        {"finishReason": "MAX_TOKENS", "content": {"parts": []}}
                    ],
                    "usageMetadata": {"candidatesTokenCount": 2048},
                },
            ]
        )
        backend = GeminiGenerateContentBackend(
            endpoint="https://provider.invalid/generateContent",
            api_key="runtime-secret",
            model="gemini-2.5-flash",
            urlopen=lambda request, timeout: _FakeHTTPResponse(next(payloads)),
        )

        blocked = backend.generate(_request(seed=None))
        truncated = backend.generate(_request(seed=None))

        self.assertEqual(blocked.text, "")
        self.assertEqual(blocked.finish_reason, "prompt_blocked:SAFETY")
        self.assertEqual(blocked.usage.input_tokens, 4)
        self.assertEqual(truncated.text, "")
        self.assertEqual(truncated.finish_reason, "MAX_TOKENS")
        self.assertEqual(truncated.usage.output_tokens, 2048)

    def test_sanitizes_http_errors_and_rejects_invalid_provider_shapes(self):
        def fail_urlopen(request, timeout):
            raise urllib.error.HTTPError(
                request.full_url,
                401,
                "unauthorized",
                hdrs=None,
                fp=io.BytesIO(b'{"error":"runtime-secret"}'),
            )

        failing = GeminiGenerateContentBackend(
            endpoint="https://provider.invalid/generateContent",
            api_key="runtime-secret",
            model="gemini-2.5-flash",
            urlopen=fail_urlopen,
        )
        with self.assertRaises(RuntimeError) as raised:
            failing.generate(_request())
        self.assertEqual(str(raised.exception), "provider HTTP status 401")
        self.assertNotIn("runtime-secret", str(raised.exception))

        malformed = GeminiGenerateContentBackend(
            endpoint="https://provider.invalid/generateContent",
            api_key="runtime-secret",
            model="gemini-2.5-flash",
            urlopen=lambda request, timeout: _FakeHTTPResponse({"candidates": []}),
        )
        with self.assertRaisesRegex(RuntimeError, "no Gemini candidate"):
            malformed.generate(_request())

    def test_classifies_known_schema_error_without_persisting_body(self):
        def fail_urlopen(request, timeout):
            raise urllib.error.HTTPError(
                request.full_url,
                400,
                "bad request",
                hdrs=None,
                fp=io.BytesIO(
                    json.dumps(
                        {
                            "error": {
                                "status": "INVALID_ARGUMENT",
                                "message": (
                                    "The specified schema produces a constraint "
                                    "that has too many states for serving."
                                ),
                                "private": "runtime-secret",
                            }
                        }
                    ).encode("utf-8")
                ),
            )

        backend = GeminiGenerateContentBackend(
            endpoint="https://provider.invalid/generateContent",
            api_key="runtime-secret",
            model="gemini-2.5-flash",
            urlopen=fail_urlopen,
        )
        with self.assertRaises(RuntimeError) as raised:
            backend.generate(_request())

        self.assertEqual(
            str(raised.exception),
            "provider HTTP status 400 (schema_constraint_too_complex)",
        )
        self.assertNotIn("runtime-secret", str(raised.exception))


if __name__ == "__main__":
    unittest.main()
