from __future__ import annotations

import io
import json
import unittest
import urllib.error
import urllib.request
import urllib.response
from email.message import Message as HTTPHeaders
from unittest import mock

from role_benchmark import GenerationConfig, GenerationRequest, Message, ProviderTransportError

from experiments.ifm_chat_completions import IFMChatCompletionsBackend, RequestStartGate


class _FakeHTTPResponse:
    def __init__(self, payload):
        self._body = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return None

    def read(self):
        return self._body


class _FakeStreamResponse(_FakeHTTPResponse):
    def __init__(self, chunks, done=True):
        events = ["data: " + json.dumps(chunk, ensure_ascii=False) + "\n\n" for chunk in chunks]
        if done:
            events.append("data: [DONE]\n\n")
        self._body = "".join(events).encode("utf-8")

    def __iter__(self):
        return iter(self._body.splitlines(keepends=True))


def _request():
    return GenerationRequest(
        messages=(
            Message("system", "Return exactly one JSON object."),
            Message("user", "Choose the next action."),
        ),
        response_schema={"type": "object"},
        config=GenerationConfig(
            max_output_tokens=256,
            temperature=0.0,
            top_p=1.0,
            seed=None,
        ),
        metadata={"require_structured_output": True},
    )


class IFMChatCompletionsBackendTests(unittest.TestCase):
    def test_platform_rejects_unsupported_reasoning_before_http(self):
        transport = mock.Mock()
        with self.assertRaisesRegex(ValueError, "low, medium, or high"):
            IFMChatCompletionsBackend(api_key="test-secret", api_mode="ifm_platform",
                reasoning_effort="minimal", urlopen=transport)
        transport.assert_not_called()

    def test_stream_reassembles_only_content_and_retains_final_usage(self):
        captured, events = [], []
        identity = {"id": "stream-id", "model": "IFM/K2-Horizon-375B-A23B"}
        def chunk(delta, finish=None):
            return {**identity, "choices": [{"index": 0, "delta": delta, "finish_reason": finish}]}
        chunks = [chunk({"role": "assistant"}), chunk({"reasoning": "not final content"}),
            chunk({"content": '{"answer":'}), chunk({"content": '"中文"}'}), chunk({}, "stop"),
            {**identity, "choices": [], "usage": {"prompt_tokens": 7, "completion_tokens": 12}}]
        def urlopen(request, timeout):
            captured.append(json.loads(request.data))
            return _FakeStreamResponse(chunks)
        backend = IFMChatCompletionsBackend(api_key="test-secret", api_mode="ifm_platform",
            native_structured_output=True, stream=True, event_sink=events.append, urlopen=urlopen)
        response = backend.generate(_request())
        self.assertEqual(response.text, '{"answer":"中文"}')
        self.assertEqual(response.finish_reason, "stop")
        self.assertEqual(response.usage.input_tokens, 7)
        self.assertEqual(response.usage.output_tokens, 12)
        self.assertTrue(captured[0]["stream"])
        self.assertEqual(captured[0]["stream_options"], {"include_usage": True})
        self.assertTrue(events[0]["provider_schema_enforced"])
        self.assertEqual(events[-1]["event"], "stream_completed")
        self.assertEqual(events[-1]["reasoning_chars"], len("not final content"))
        self.assertEqual(response.metadata["stream_chunks"], 6)
        self.assertNotIn("test-secret", json.dumps(events))

    def test_incomplete_stream_is_not_scored_or_retried(self):
        for done, finish in ((False, "stop"), (True, None)):
            calls = []
            def urlopen(request, timeout):
                calls.append(1)
                return _FakeStreamResponse([{"model": "IFM/K2-Horizon-375B-A23B", "id": "x",
                    "choices": [{"index": 0, "delta": {"content": "{}"}, "finish_reason": finish}]}], done=done)
            backend = IFMChatCompletionsBackend(api_key="test-secret", stream=True,
                max_rate_limit_retries=6, urlopen=urlopen)
            with self.assertRaisesRegex(RuntimeError, "Incomplete Chat Completions stream"):
                backend.generate(_request())
            self.assertEqual(len(calls), 1)

    def test_stream_identity_cannot_change_after_null_or_missing_fields(self):
        identity = {"model": "expected-model", "id": "expected-id"}
        for field in ("model", "id"):
            for gap in ([], [{"choices": []}], [{"model": None, "id": None, "choices": []}]):
                with self.subTest(field=field, gap=gap):
                    def urlopen(request, timeout):
                        return _FakeStreamResponse([
                            {**identity, "choices": [{"index": 0, "delta": {"content": "{"}}]},
                            *gap,
                            {**identity, field: "changed", "choices": [{"index": 0,
                                "delta": {"content": "}"}, "finish_reason": "stop"}]},
                        ])
                    backend = IFMChatCompletionsBackend(
                        api_key="test-secret", stream=True, urlopen=urlopen,
                    )
                    with self.assertRaisesRegex(RuntimeError, "changed stream identity"):
                        backend.generate(_request())

    def test_stream_null_and_missing_fields_preserve_confirmed_identity(self):
        for absent_fields in ({}, {"model": None, "id": None}):
            with self.subTest(absent_fields=absent_fields):
                def urlopen(request, timeout):
                    return _FakeStreamResponse([
                        {**absent_fields, "choices": []},
                        {"model": "expected-model", "id": "expected-id", "choices": [
                            {"index": 0, "delta": {"content": "{}"}}]},
                        {**absent_fields, "choices": [{"index": 0,
                            "delta": {}, "finish_reason": "stop"}]},
                    ])
                backend = IFMChatCompletionsBackend(api_key="test-secret",
                    api_mode="ifm_platform", stream=True, urlopen=urlopen)
                response = backend.generate(_request())
                self.assertEqual(response.model, "expected-model")
                self.assertEqual(response.response_id, "expected-id")
                self.assertEqual(response.text, "{}")

    def test_default_transport_rejects_redirects_without_forwarding_credentials(self):
        endpoint = "https://origin.invalid/v1/chat/completions"
        for mode in ("core42", "ifm_platform"):
            for code in (301, 302, 303, 307, 308):
                for destination in (
                    "https://origin.invalid/redirected",
                    "https://other.invalid/redirected",
                    "http://origin.invalid/redirected",
                ):
                    with self.subTest(mode=mode, code=code, destination=destination):
                        requests = []

                        def do_open(handler, connection_class, request, **kwargs):
                            requests.append(request)
                            headers = HTTPHeaders()
                            headers["Location"] = destination
                            status = code if request.full_url == endpoint else 200
                            response = urllib.response.addinfourl(io.BytesIO(json.dumps({
                                "model": "fixture", "choices": [{
                                    "message": {"content": "{}"}, "finish_reason": "stop",
                                }],
                            }).encode()), headers, request.full_url, status)
                            response.msg = "Synthetic response"
                            return response

                        backend = IFMChatCompletionsBackend(api_key="test-secret",
                            endpoint=endpoint, api_mode=mode, max_rate_limit_retries=2)
                        # Exercise the real opener and redirect handlers while replacing
                        # both HTTP and HTTPS network I/O with an in-memory response.
                        with mock.patch.object(urllib.request.AbstractHTTPHandler, "do_open", do_open):
                            with self.assertRaises(ProviderTransportError) as caught:
                                backend.generate(_request())
                        self.assertEqual(caught.exception.http_status, code)
                        self.assertEqual(len(requests), 1)
                        self.assertEqual(requests[0].full_url, endpoint)
                        self.assertNotIn("test-secret", str(caught.exception))

    def test_native_schema_sends_full_recursive_contract_and_records_identity(self):
        from role_benchmark.structured_actions import structured_action_json_schema
        import hashlib
        captured = []
        def urlopen(request, timeout):
            captured.append(json.loads(request.data))
            return _FakeHTTPResponse({"model": "IFM/K2-Horizon-375B-A23B",
                "choices": [{"message": {"content": "{}"}, "finish_reason": "stop"}]})
        schema = structured_action_json_schema()
        request = GenerationRequest(messages=_request().messages, config=_request().config,
            response_schema=schema)
        backend = IFMChatCompletionsBackend(api_key="test-secret", api_mode="ifm_platform",
            native_structured_output=True, urlopen=urlopen)
        response = backend.generate(request)
        self.assertTrue(backend.supports_strict_action_schema)
        self.assertEqual(captured[0]["response_format"], {"type": "json_schema", "json_schema": {
            "name": "role_benchmark_action", "strict": True, "schema": schema}})
        self.assertTrue(response.metadata["provider_schema_enforced"])
        self.assertEqual(response.metadata["structured_output_transport"], "native_json_schema_local_validation")
        self.assertEqual(response.metadata["response_schema_sha256"], hashlib.sha256(json.dumps(schema,
            sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest())
        with self.assertRaisesRegex(ValueError, "nonempty response schema"):
            backend.generate(GenerationRequest(messages=_request().messages,
                config=_request().config, response_schema={}))
        self.assertEqual(len(captured), 1)

    def test_native_schema_rejection_never_falls_back_to_prompt_only(self):
        calls = []
        def urlopen(request, timeout):
            calls.append(json.loads(request.data))
            raise urllib.error.HTTPError(request.full_url, 400, "schema rejected", {}, io.BytesIO())
        backend = IFMChatCompletionsBackend(api_key="test-secret", api_mode="ifm_platform",
            native_structured_output=True, max_rate_limit_retries=6, urlopen=urlopen)
        with self.assertRaises(ProviderTransportError):
            backend.generate(_request())
        self.assertEqual(len(calls), 1)
        self.assertIn("response_format", calls[0])
        with self.assertRaisesRegex(ValueError, "only for IFM Platform"):
            IFMChatCompletionsBackend(api_key="test-secret", native_structured_output=True)

    def test_shared_gate_spaces_starts_and_applies_global_backoff(self):
        clock = [0.0]
        def sleep(delay):
            clock[0] += delay
        gate = RequestStartGate(1.0, clock=lambda: clock[0], sleep=sleep)
        starts = []
        for _ in range(3):
            gate.wait()
            starts.append(clock[0])
        self.assertEqual(starts, [0.0, 1.0, 2.0])
        gate.defer(5)
        gate.wait()
        self.assertEqual(clock[0], 7.0)

    def test_rejected_429_retries_same_payload_with_recorded_backoff(self):
        requests, waits = [], []
        def urlopen(request, timeout):
            requests.append(request.data)
            if len(requests) == 1:
                raise urllib.error.HTTPError(request.full_url, 429, "limited",
                    {"Retry-After": "3"}, io.BytesIO(b"limited"))
            return _FakeHTTPResponse({"choices": [{"message": {"content": "{}"}, "finish_reason": "stop"}]})
        backend = IFMChatCompletionsBackend(api_key="test-secret", urlopen=urlopen,
            max_rate_limit_retries=2, sleep=waits.append)
        response = backend.generate(_request())
        self.assertEqual(len(requests), 2)
        self.assertEqual(requests[0], requests[1])
        self.assertEqual(waits, [3.0])
        self.assertEqual(response.metadata["http_attempts"], 2)
        self.assertEqual(response.metadata["rate_limit_retries"], [{"http_status": 429, "backoff_s": 3.0}])

    def test_retries_are_bounded_and_never_apply_to_other_http_errors(self):
        for code, expected_calls in ((429, 3), (400, 1), (401, 1), (500, 1)):
            calls = []
            def urlopen(request, timeout):
                calls.append(1)
                raise urllib.error.HTTPError(request.full_url, code, "failed", {}, io.BytesIO())
            backend = IFMChatCompletionsBackend(api_key="test-secret", urlopen=urlopen,
                max_rate_limit_retries=2, sleep=lambda delay: None)
            with self.assertRaises(ProviderTransportError) as caught:
                backend.generate(_request())
            self.assertEqual(caught.exception.http_status, code)
            self.assertEqual(len(calls), expected_calls)

    def test_context_cap_reserves_prompt_space_and_records_actual_output_limit(self):
        captured = []
        def urlopen(request, timeout):
            captured.append(json.loads(request.data))
            return _FakeHTTPResponse({"model": "IFM/K2-Horizon-375B-A23B", "choices": [{
                "message": {"content": "OK"}, "finish_reason": "stop"}]})
        backend = IFMChatCompletionsBackend(api_key="test-secret", api_mode="ifm_platform",
            context_window_tokens=524288, urlopen=urlopen)
        for message in ("hello", "中文" * 200):
            request = GenerationRequest(messages=(Message("user", message),),
                config=GenerationConfig(max_output_tokens=524288), response_schema={})
            response = backend.generate(request)
            reserve = response.metadata["input_reserve_tokens"]
            self.assertGreater(reserve, len(message.encode("utf-8")))
            self.assertEqual(captured[-1]["max_tokens"] + reserve, 524288)
            self.assertEqual(response.metadata["max_output_tokens_sent"], captured[-1]["max_tokens"])
        self.assertLess(captured[1]["max_tokens"], captured[0]["max_tokens"])
        with self.assertRaisesRegex(ValueError, "No output capacity"):
            backend.generate(GenerationRequest(messages=(Message("user", "a" * 524288),),
                config=GenerationConfig(max_output_tokens=524288), response_schema={}))
        self.assertEqual(len(captured), 2)

    def test_ifm_platform_uses_bearer_and_chat_template_reasoning(self):
        captured = {}
        def urlopen(request, timeout):
            captured["request"] = request
            return _FakeHTTPResponse({"model": "IFM/K2-Horizon-375B-A23B", "choices": [{
                "message": {"content": '{"ok":true}'}, "finish_reason": "stop"}],
                "usage": {"completion_tokens_details": None, "prompt_tokens": 5, "completion_tokens": 4}})
        backend = IFMChatCompletionsBackend(api_key="test-secret", api_mode="ifm_platform",
            endpoint="https://api.ifm.ai/v1/chat/completions", model="IFM/K2-Horizon-375B-A23B",
            reasoning_effort="high", urlopen=urlopen)
        response = backend.generate(_request())
        headers = {k.lower(): v for k, v in captured["request"].header_items()}
        payload = json.loads(captured["request"].data)
        self.assertEqual(headers["authorization"], "Bearer test-secret")
        self.assertNotIn("api-key", headers)
        self.assertNotIn("reasoning_effort", payload)
        self.assertEqual(payload["chat_template_kwargs"], {"reasoning_effort": "high"})
        self.assertEqual(response.model, "IFM/K2-Horizon-375B-A23B")
        self.assertEqual(response.metadata["api_mode"], "ifm_platform")
        self.assertNotIn("test-secret", repr(response))

    def test_ifm_platform_requires_returned_model_identity(self):
        def urlopen(request, timeout):
            return _FakeHTTPResponse({"choices": [{"message": {"content": "{}"}, "finish_reason": "stop"}]})
        backend = IFMChatCompletionsBackend(api_key="test-secret", api_mode="ifm_platform", urlopen=urlopen)
        with self.assertRaisesRegex(RuntimeError, "model identity"):
            backend.generate(_request())

    def test_request_and_response_follow_documented_contract(self):
        captured = {}

        def urlopen(request, timeout):
            captured["request"] = request
            captured["timeout"] = timeout
            return _FakeHTTPResponse(
                {
                    "id": "chatcmpl-test",
                    "model": "k2-horizon-375b",
                    "choices": [{
                        "message": {
                            "role": "assistant",
                            "reasoning_content": "private reasoning",
                            "content": '{"kind":"final"}',
                        },
                        "finish_reason": "stop",
                    }],
                    "usage": {
                        "prompt_tokens": 10,
                        "completion_tokens": 7,
                        "completion_tokens_details": {"reasoning_tokens": 4},
                    },
                }
            )

        backend = IFMChatCompletionsBackend(
            api_key="test-secret",
            reasoning_effort="high",
            timeout_s=9.0,
            urlopen=urlopen,
        )
        response = backend.generate(_request())

        request = captured["request"]
        payload = json.loads(request.data.decode("utf-8"))
        headers = {key.casefold(): value for key, value in request.header_items()}
        self.assertEqual(headers["api-key"], "test-secret")
        self.assertNotIn("authorization", headers)
        self.assertEqual(captured["timeout"], 9.0)
        self.assertEqual(payload["model"], "k2-horizon-375b")
        self.assertEqual(payload["reasoning_effort"], "high")
        self.assertFalse(payload["stream"])
        self.assertNotIn("response_format", payload)
        self.assertNotIn("thinking", payload)
        self.assertNotIn("seed", payload)
        self.assertEqual(response.text, '{"kind":"final"}')
        self.assertNotIn("private reasoning", response.text)
        self.assertEqual(response.provider, "ifm")
        self.assertEqual(response.model, "k2-horizon-375b")
        self.assertEqual(response.usage.input_tokens, 10)
        self.assertEqual(response.usage.output_tokens, 7)
        self.assertEqual(response.metadata["reasoning_tokens"], 4)
        self.assertNotIn("test-secret", json.dumps(response.metadata))

    def test_http_error_is_sanitized(self):
        def urlopen(request, timeout):
            raise urllib.error.HTTPError(
                request.full_url,
                401,
                "contains secret provider text",
                {},
                io.BytesIO(b'{"error":"credential detail"}'),
            )

        backend = IFMChatCompletionsBackend(api_key="test-secret", urlopen=urlopen)
        with self.assertRaises(ProviderTransportError) as caught:
            backend.generate(_request())

        self.assertEqual(caught.exception.http_status, 401)
        self.assertNotIn("credential", str(caught.exception))

    def test_seed_is_rejected_before_transport(self):
        request = GenerationRequest(
            messages=(Message("user", "hello"),),
            response_schema={},
            config=GenerationConfig(seed=1),
        )
        backend = IFMChatCompletionsBackend(api_key="test-secret")
        with self.assertRaisesRegex(ValueError, "does not expose a seed"):
            backend.generate(request)

    def test_refusal_is_preserved_for_streaming_and_buffered_responses(self):
        for stream in (False, True):
            def urlopen(request, timeout):
                message = {"content": None, "refusal": "Cannot answer."}
                if stream:
                    return _FakeStreamResponse([{"model": "fixture", "choices": [
                        {"index": 0, "delta": message, "finish_reason": "stop"}]}])
                return _FakeHTTPResponse({"model": "fixture", "choices": [
                    {"message": message, "finish_reason": "stop"}]})
            backend = IFMChatCompletionsBackend(api_key="synthetic", stream=stream, urlopen=urlopen)
            response = backend.generate(_request())
            self.assertEqual(response.metadata["content_kind"], "refusal")
            self.assertEqual(response.metadata["completion_status"], "refused")
            self.assertEqual(response.text, "Cannot answer.")

    def test_empty_blocked_or_truncated_output_retains_provider_attribution(self):
        for reason, expected in (("length", "truncated"), ("content_filter", "refused")):
            backend = IFMChatCompletionsBackend(api_key="synthetic", urlopen=lambda *args, **kwargs:
                _FakeHTTPResponse({"choices": [{"message": {"content": None}, "finish_reason": reason}]}))
            response = backend.generate(_request())
            self.assertEqual(response.text, "")
            self.assertEqual(response.metadata["completion_status"], expected)

    def test_buffered_response_requires_terminal_status(self):
        backend = IFMChatCompletionsBackend(api_key="synthetic", urlopen=lambda *args, **kwargs:
            _FakeHTTPResponse({"choices": [{"message": {"content": "{}"}}]}))
        with self.assertRaisesRegex(RuntimeError, "completion status"):
            backend.generate(_request())


if __name__ == "__main__":
    unittest.main()
