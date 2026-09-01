from __future__ import annotations

import io
import json
import unittest
import urllib.error

from role_benchmark import GenerationConfig, GenerationRequest, Message

from experiments.openai_responses import OpenAIResponsesBackend


class _FakeHTTPResponse:
    def __init__(self, payload):
        self._body = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return None

    def read(self):
        return self._body


def _request(*, seed=None):
    return GenerationRequest(
        messages=(
            Message("system", "Return one JSON object."),
            Message("user", "Choose the next action."),
        ),
        response_schema={"type": "object"},
        config=GenerationConfig(
            max_output_tokens=2048,
            temperature=0.0,
            top_p=1.0,
            seed=seed,
        ),
    )


class OpenAIResponsesBackendTests(unittest.TestCase):
    def test_maps_request_output_and_usage_without_persisting_key(self):
        captured = {}

        def fake_urlopen(request, timeout):
            captured["authorization"] = request.get_header("Authorization")
            captured["body"] = json.loads(request.data.decode("utf-8"))
            captured["timeout"] = timeout
            return _FakeHTTPResponse(
                {
                    "id": "resp-1",
                    "model": "gpt-5.6-sol",
                    "status": "completed",
                    "output": [
                        {"type": "reasoning", "id": "reasoning-1"},
                        {
                            "type": "message",
                            "role": "assistant",
                            "content": [
                                {
                                    "type": "output_text",
                                    "text": '{"kind":"final"}',
                                    "annotations": [],
                                }
                            ],
                        },
                    ],
                    "usage": {
                        "input_tokens": 11,
                        "output_tokens": 7,
                        "output_tokens_details": {"reasoning_tokens": 3},
                        "total_tokens": 18,
                    },
                }
            )

        backend = OpenAIResponsesBackend(
            api_key="runtime-secret",
            reasoning_effort="none",
            timeout_s=9.0,
            urlopen=fake_urlopen,
        )
        response = backend.generate(_request())

        self.assertEqual(captured["authorization"], "Bearer runtime-secret")
        self.assertEqual(captured["timeout"], 9.0)
        self.assertEqual(captured["body"]["model"], "gpt-5.6")
        self.assertEqual(
            captured["body"]["input"],
            [
                {"role": "system", "content": "Return one JSON object."},
                {"role": "user", "content": "Choose the next action."},
            ],
        )
        self.assertEqual(captured["body"]["max_output_tokens"], 2048)
        self.assertEqual(captured["body"]["temperature"], 0.0)
        self.assertEqual(captured["body"]["top_p"], 1.0)
        self.assertEqual(
            captured["body"]["reasoning"],
            {"effort": "none", "context": "current_turn"},
        )
        self.assertEqual(
            captured["body"]["text"], {"format": {"type": "json_object"}}
        )
        self.assertIs(captured["body"]["store"], False)
        self.assertNotIn("seed", captured["body"])
        self.assertNotIn("response_schema", captured["body"])

        self.assertEqual(response.text, '{"kind":"final"}')
        self.assertEqual(response.provider, "openai")
        self.assertEqual(response.model, "gpt-5.6-sol")
        self.assertEqual(response.finish_reason, "completed")
        self.assertEqual(response.response_id, "resp-1")
        self.assertEqual(response.usage.input_tokens, 11)
        self.assertEqual(response.usage.output_tokens, 7)
        self.assertEqual(response.metadata["reasoning_tokens"], 3)
        self.assertEqual(response.metadata["reasoning_context"], "current_turn")
        self.assertEqual(response.metadata["returned_model"], "gpt-5.6-sol")
        self.assertEqual(response.metadata["content_kind"], "output_text")
        self.assertNotIn("runtime-secret", json.dumps(response.metadata))

    def test_refusal_and_incomplete_output_remain_observable_model_output(self):
        responses = iter(
            [
                {
                    "status": "completed",
                    "output": [
                        {
                            "type": "message",
                            "content": [
                                {"type": "refusal", "refusal": "Cannot comply."}
                            ],
                        }
                    ],
                },
                {
                    "status": "incomplete",
                    "incomplete_details": {"reason": "max_output_tokens"},
                    "output": [],
                    "usage": {
                        "input_tokens": 5,
                        "output_tokens": 2048,
                        "output_tokens_details": {"reasoning_tokens": 2048},
                    },
                },
            ]
        )

        def fake_urlopen(request, timeout):
            return _FakeHTTPResponse(next(responses))

        backend = OpenAIResponsesBackend(
            api_key="runtime-secret",
            urlopen=fake_urlopen,
        )
        refusal = backend.generate(_request())
        incomplete = backend.generate(_request())

        self.assertEqual(refusal.text, "Cannot comply.")
        self.assertEqual(refusal.metadata["content_kind"], "refusal")
        self.assertEqual(incomplete.text, "")
        self.assertEqual(
            incomplete.finish_reason, "incomplete:max_output_tokens"
        )
        self.assertEqual(incomplete.metadata["response_status"], "incomplete")
        self.assertEqual(incomplete.metadata["reasoning_tokens"], 2048)

    def test_rejects_unsupported_seed_and_sanitizes_provider_errors(self):
        backend = OpenAIResponsesBackend(
            api_key="runtime-secret",
            urlopen=lambda request, timeout: None,
        )
        with self.assertRaisesRegex(ValueError, "does not expose a seed"):
            backend.generate(_request(seed=7))

        def fail_urlopen(request, timeout):
            raise urllib.error.HTTPError(
                request.full_url,
                401,
                "unauthorized",
                hdrs=None,
                fp=io.BytesIO(b'{"error":"runtime-secret"}'),
            )

        failing = OpenAIResponsesBackend(
            api_key="runtime-secret",
            urlopen=fail_urlopen,
        )
        with self.assertRaises(RuntimeError) as raised:
            failing.generate(_request())
        self.assertEqual(str(raised.exception), "provider HTTP status 401")
        self.assertNotIn("runtime-secret", str(raised.exception))

    def test_rejects_failed_or_structurally_invalid_responses(self):
        payloads = iter(
            [
                {"status": "failed", "error": {"message": "internal detail"}},
                {"status": "completed", "output": [{"type": "reasoning"}]},
                {
                    "status": "completed",
                    "output": [
                        {
                            "type": "message",
                            "content": [
                                {"type": "output_text", "text": '{"ok":true}'}
                            ],
                        }
                    ],
                    "usage": [],
                },
            ]
        )

        backend = OpenAIResponsesBackend(
            api_key="runtime-secret",
            urlopen=lambda request, timeout: _FakeHTTPResponse(next(payloads)),
        )
        with self.assertRaisesRegex(RuntimeError, "did not complete"):
            backend.generate(_request())
        with self.assertRaisesRegex(RuntimeError, "no assistant text"):
            backend.generate(_request())

        with self.assertRaisesRegex(ValueError, "reasoning_effort"):
            OpenAIResponsesBackend(
                api_key="runtime-secret",
                reasoning_effort="unsupported",
            )
        with self.assertRaisesRegex(RuntimeError, "invalid usage"):
            backend.generate(_request())


if __name__ == "__main__":
    unittest.main()
