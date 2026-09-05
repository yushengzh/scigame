from __future__ import annotations

import io
import json
import unittest
import urllib.error
from types import SimpleNamespace

from role_benchmark import GenerationConfig, GenerationRequest, Message

from experiments.gemini_generate_content import (
    GeminiGenerateContentBackend,
    _gemini_messages,
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
                "responseFormat": {
                    "text": {
                        "mimeType": "application/json",
                        "schema": {
                            "type": "object",
                            "required": ["kind"],
                            "properties": {
                                "kind": {
                                    "type": "string",
                                    "enum": ["final"],
                                }
                            },
                        },
                    }
                },
                "seed": 17,
            },
        )
        self.assertNotIn("responseMimeType", captured["body"]["generationConfig"])
        self.assertNotIn("responseJsonSchema", captured["body"]["generationConfig"])
        transported_schema = captured["body"]["generationConfig"]["responseFormat"][
            "text"
        ]["schema"]
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


if __name__ == "__main__":
    unittest.main()
