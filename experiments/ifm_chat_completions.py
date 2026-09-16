"""Minimal IFM/Core42 Chat Completions binding for K2 Horizon.

IFM Platform supports native JSON-schema output, verified against the hosted
K2 Horizon endpoint. Enable it explicitly for versioned benchmark runs; local
decoding remains authoritative. Credentials never enter response metadata.
"""

from __future__ import annotations

import json
import hashlib
import math
import threading
import time
from datetime import datetime, timezone
import urllib.error
import urllib.request
from typing import Any, Callable, Dict, Mapping, Optional, Tuple

from role_benchmark import (
    GenerationRequest,
    GenerationResponse,
    ProviderTransportError,
    TokenUsage,
)
from role_benchmark.llm import generation_completion_status


DEFAULT_IFM_CHAT_COMPLETIONS_ENDPOINT = "https://api.core42.ai/v1/chat/completions"
DEFAULT_IFM_MODEL = "k2-horizon-375b"
DEFAULT_IFM_PLATFORM_ENDPOINT = "https://api.ifm.ai/v1/chat/completions"
DEFAULT_IFM_PLATFORM_MODEL = "IFM/K2-Horizon-375B-A23B"
IFM_REASONING_EFFORTS: Tuple[str, ...] = ("minimal", "low", "medium", "high")
IFM_PLATFORM_REASONING_EFFORTS: Tuple[str, ...] = ("low", "medium", "high")


def _optional_token_count(value: Any) -> Optional[int]:
    return value if type(value) is int and value >= 0 else None


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Keep credentials and prompts at the explicitly configured endpoint."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class RequestStartGate:
    """Space request starts across workers without serializing responses."""

    def __init__(self, interval_s, *, clock=time.monotonic, sleep=time.sleep, cancel_event=None):
        if not math.isfinite(interval_s) or interval_s <= 0:
            raise ValueError("request start interval must be finite and positive")
        self.interval_s = interval_s
        self._clock, self._sleep = clock, sleep
        self._next = 0.0
        self._lock = threading.Lock()
        self._cancel_event = cancel_event

    def wait(self):
        while True:
            if self._cancel_event is not None and self._cancel_event.is_set():
                raise ProviderTransportError(connection_failed=True)
            with self._lock:
                delay = self._next - self._clock()
                if delay <= 0:
                    self._next = self._clock() + self.interval_s
                    return
            self._sleep(delay)

    def defer(self, seconds):
        with self._lock:
            self._next = max(self._next, self._clock() + seconds)


class IFMChatCompletionsBackend:
    """Standard-library binding for the IFM-hosted K2 Horizon endpoint."""

    binding_id = "case_matrix.ifm_chat_completions"
    supports_strict_action_schema = False

    def __init__(
        self,
        *,
        api_key: str,
        endpoint: str = DEFAULT_IFM_CHAT_COMPLETIONS_ENDPOINT,
        model: str = DEFAULT_IFM_MODEL,
        reasoning_effort: str = "medium",
        timeout_s: float = 120.0,
        api_mode: str = "core42",
        context_window_tokens: Optional[int] = None,
        native_structured_output: bool = False,
        stream: bool = False,
        event_sink: Optional[Callable[[Mapping[str, Any]], None]] = None,
        request_gate: Optional[RequestStartGate] = None,
        max_rate_limit_retries: int = 0,
        sleep: Callable[[float], Any] = time.sleep,
        urlopen: Optional[Callable[..., Any]] = None,
    ) -> None:
        if not endpoint.startswith(("https://", "http://")):
            raise ValueError("endpoint must be an HTTP(S) URL")
        if not api_key or not api_key.strip():
            raise ValueError("api_key must be non-empty")
        if not model or not model.strip():
            raise ValueError("model must be non-empty")
        if reasoning_effort not in IFM_REASONING_EFFORTS:
            raise ValueError(
                "reasoning_effort must be one of %s"
                % ", ".join(IFM_REASONING_EFFORTS)
            )
        if timeout_s <= 0:
            raise ValueError("timeout_s must be positive")
        if api_mode not in ("core42", "ifm_platform"):
            raise ValueError("api_mode must be core42 or ifm_platform")
        if api_mode == "ifm_platform" and reasoning_effort not in IFM_PLATFORM_REASONING_EFFORTS:
            raise ValueError("IFM Platform reasoning_effort must be low, medium, or high")
        if type(native_structured_output) is not bool:
            raise ValueError("native_structured_output must be boolean")
        if native_structured_output and api_mode != "ifm_platform":
            raise ValueError("Native schema output is verified only for IFM Platform")
        if type(stream) is not bool:
            raise ValueError("stream must be boolean")
        if context_window_tokens is not None and (
                type(context_window_tokens) is not int or context_window_tokens <= 1024):
            raise ValueError("context_window_tokens must exceed the 1024-token template margin")
        if type(max_rate_limit_retries) is not int or max_rate_limit_retries < 0:
            raise ValueError("max_rate_limit_retries must be a nonnegative integer")
        self._endpoint = endpoint
        self._api_key = api_key
        self._model = model
        self._reasoning_effort = reasoning_effort
        self._timeout_s = float(timeout_s)
        self._api_mode = api_mode
        self._context_window_tokens = context_window_tokens
        self.supports_strict_action_schema = native_structured_output
        self._stream = stream
        self._event_sink = event_sink
        self._call_index = 0
        self._request_gate = request_gate
        self._max_rate_limit_retries = max_rate_limit_retries
        self._sleep = sleep
        self._urlopen = (
            urllib.request.build_opener(_NoRedirectHandler()).open
            if urlopen is None else urlopen
        )

    def _event(self, event, **fields):
        if self._event_sink is not None:
            self._event_sink({"event": event, "call_index": self._call_index, **fields})

    def _read_stream(self, response):
        content, refusals, event_lines = [], [], []
        model, response_id, finish_reason, usage = None, None, None, {}
        chunks, reasoning_chars, content_chars = 0, 0, 0
        last_progress = time.monotonic()
        done = False
        for raw_line in response:
            line = raw_line.decode("utf-8").rstrip("\r\n")
            if line.startswith("data:"):
                event_lines.append(line[5:].lstrip(" "))
                continue
            if line or not event_lines:
                continue
            data = "\n".join(event_lines)
            event_lines = []
            if data == "[DONE]":
                done = True
                break
            chunk = json.loads(data)
            if not isinstance(chunk, Mapping) or chunk.get("error"):
                raise RuntimeError("Invalid or error Chat Completions stream event")
            chunks += 1
            for field, prior in (("model", model), ("id", response_id)):
                value = chunk.get(field)
                if value is not None and (not isinstance(value, str) or (prior is not None and value != prior)):
                    raise RuntimeError("Provider changed stream identity")
            if chunk.get("model") is not None:
                model = chunk["model"]
            if chunk.get("id") is not None:
                response_id = chunk["id"]
            if chunk.get("usage") is not None:
                usage = chunk["usage"]
            choices = chunk.get("choices")
            if not isinstance(choices, list) or len(choices) > 1:
                raise RuntimeError("Invalid stream choices")
            for choice in choices:
                if not isinstance(choice, Mapping) or choice.get("index") != 0:
                    raise RuntimeError("Unexpected stream choice index")
                delta = choice.get("delta")
                if not isinstance(delta, Mapping):
                    raise RuntimeError("Invalid stream delta")
                piece = delta.get("content")
                if piece is not None:
                    if not isinstance(piece, str):
                        raise RuntimeError("Non-text stream content")
                    if finish_reason is not None and piece:
                        raise RuntimeError("Stream content arrived after termination")
                    content.append(piece)
                    content_chars += len(piece)
                refusal = delta.get("refusal")
                if refusal is not None:
                    if not isinstance(refusal, str):
                        raise RuntimeError("Invalid stream refusal")
                    if finish_reason is not None and refusal:
                        raise RuntimeError("Stream refusal arrived after termination")
                    refusals.append(refusal)
                for name in ("reasoning", "reasoning_content"):
                    if isinstance(delta.get(name), str):
                        reasoning_chars += len(delta[name])
                reason = choice.get("finish_reason")
                if reason is not None:
                    if not isinstance(reason, str) or (finish_reason is not None and finish_reason != reason):
                        raise RuntimeError("Invalid stream termination")
                    finish_reason = reason
            if chunks == 1 or time.monotonic() - last_progress >= 10:
                self._event("stream_progress", chunks=chunks, content_chars=content_chars,
                    reasoning_chars=reasoning_chars, model=model, response_id=response_id)
                last_progress = time.monotonic()
        if not done or finish_reason is None:
            self._event("stream_incomplete", chunks=chunks, content_chars=content_chars,
                reasoning_chars=reasoning_chars)
            raise RuntimeError("Incomplete Chat Completions stream; partial output is not scored")
        self._event("stream_completed", chunks=chunks, content_chars=content_chars,
            reasoning_chars=reasoning_chars, finish_reason=finish_reason)
        return {"model": model, "id": response_id, "usage": usage, "choices": [{
            "message": {"content": "".join(content), "refusal": "".join(refusals) or None},
            "finish_reason": finish_reason}]}, chunks

    def generate(self, request: GenerationRequest) -> GenerationResponse:
        if not isinstance(request, GenerationRequest):
            raise ValueError("request must be GenerationRequest")
        if request.config.seed is not None:
            raise ValueError("IFM Chat Completions does not expose a seed parameter")
        self._call_index += 1

        payload: Dict[str, Any] = {
            "model": self._model,
            "messages": [
                {"role": message.role, "content": message.content}
                for message in request.messages
            ],
            "max_tokens": request.config.max_output_tokens,
            "temperature": request.config.temperature,
            "top_p": request.config.top_p,
            "reasoning_effort": self._reasoning_effort,
            "stream": self._stream,
        }
        if self._stream:
            payload["stream_options"] = {"include_usage": True}
        schema_sha256 = None
        if self.supports_strict_action_schema:
            if not request.response_schema:
                raise ValueError("Native structured output requires a nonempty response schema")
            payload["response_format"] = {"type": "json_schema", "json_schema": {
                "name": "role_benchmark_action", "strict": True,
                "schema": dict(request.response_schema)}}
            schema_sha256 = hashlib.sha256(json.dumps(request.response_schema,
                sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()
        input_reserve = None
        if self._context_window_tokens is not None:
            # Reserve UTF-8 bytes (conservative for tokenized message text) and
            # 1024 tokens for chat-template overhead. Do not allocate the full
            # combined context window to output and leave no room for input.
            input_reserve = len(json.dumps(payload["messages"], ensure_ascii=False,
                separators=(",", ":")).encode("utf-8")) + 1024
            remaining = self._context_window_tokens - input_reserve
            if remaining < 1:
                raise ValueError("No output capacity remains after reserving prompt space")
            payload["max_tokens"] = min(request.config.max_output_tokens, remaining)
        auth_headers = {"api-key": self._api_key}
        if self._api_mode == "ifm_platform":
            payload.pop("reasoning_effort")
            payload["chat_template_kwargs"] = {"reasoning_effort": self._reasoning_effort}
            auth_headers = {"Authorization": "Bearer " + self._api_key}
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode(
            "utf-8"
        )
        http_request = urllib.request.Request(
            self._endpoint,
            data=body,
            headers={
                **auth_headers,
                "Content-Type": "application/json",
                "Accept": "text/event-stream" if self._stream else "application/json",
            },
            method="POST",
        )
        rate_limit_retries = []
        stream_chunks = 0
        while True:
            if self._request_gate is not None:
                self._request_gate.wait()
            self._event("request_started", http_attempt=1 + len(rate_limit_retries),
                model=self._model, stream=self._stream,
                provider_schema_enforced=self.supports_strict_action_schema,
                response_schema_sha256=schema_sha256,
                max_output_tokens_sent=payload["max_tokens"])
            try:
                http_started_at = datetime.now(timezone.utc).isoformat()
                with self._urlopen(http_request, timeout=self._timeout_s) as response:
                    self._event("response_started")
                    if self._stream:
                        decoded, stream_chunks = self._read_stream(response)
                    else:
                        response_body = response.read()
                http_finished_at = datetime.now(timezone.utc).isoformat()
                break
            except urllib.error.HTTPError as exc:
                # Only rejected HTTP 429 requests are eligible. Never retry a
                # returned model output, malformed content, or another error.
                if exc.code != 429 or len(rate_limit_retries) >= self._max_rate_limit_retries:
                    exc.close()
                    raise ProviderTransportError(http_status=exc.code) from exc
                delay = min(60.0, 2.0 ** (len(rate_limit_retries) + 1))
                headers = exc.headers or {}
                for name in ("Retry-After", "X-Ratelimit-Reset-Requests"):
                    try:
                        reported = float(headers.get(name, "").removesuffix("s"))
                        if math.isfinite(reported) and reported >= 0:
                            delay = max(delay, reported)
                    except (ValueError, AttributeError):
                        pass
                exc.close()
                if delay > 300:
                    raise ProviderTransportError(http_status=429) from exc
                rate_limit_retries.append({"http_status": 429, "backoff_s": delay})
                self._event("rate_limit_backoff", backoff_s=delay, http_status=429)
                if self._request_gate is not None:
                    self._request_gate.defer(delay)
                else:
                    self._sleep(delay)
            except urllib.error.URLError as exc:
                raise ProviderTransportError(connection_failed=True) from exc

        if not self._stream:
            try:
                decoded = json.loads(response_body.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise RuntimeError("provider returned invalid Chat Completions JSON") from exc
        if not isinstance(decoded, Mapping):
            raise RuntimeError("provider returned a non-object Chat Completions payload")

        choices = decoded.get("choices")
        if not isinstance(choices, list) or len(choices) != 1:
            raise RuntimeError("provider returned an invalid number of choices")
        choice = choices[0]
        if not isinstance(choice, Mapping):
            raise RuntimeError("provider returned an invalid choice")
        message = choice.get("message")
        if not isinstance(message, Mapping):
            raise RuntimeError("provider returned an invalid assistant message")
        finish_reason = choice.get("finish_reason")
        if not isinstance(finish_reason, str) or not finish_reason.strip():
            raise RuntimeError("provider response omitted completion status")
        content = message.get("content")
        refusal = message.get("refusal")
        if refusal is not None and not isinstance(refusal, str):
            raise RuntimeError("provider returned invalid refusal content")
        content_kind = "refusal" if refusal else "output_text"
        if refusal and content in (None, ""):
            content = refusal
        if content is None and generation_completion_status(finish_reason) in {"refused", "truncated"}:
            content = ""
        if not isinstance(content, str):
            raise RuntimeError("provider returned non-text assistant content")

        usage = decoded.get("usage") or {}
        if not isinstance(usage, Mapping):
            raise RuntimeError("provider returned invalid usage")
        completion_details = usage.get("completion_tokens_details") or {}
        if not isinstance(completion_details, Mapping):
            raise RuntimeError("provider returned invalid completion token details")
        returned_model = decoded.get("model")
        if self._api_mode == "ifm_platform" and (not isinstance(returned_model, str) or not returned_model):
            raise RuntimeError("IFM platform response omitted model identity")
        if not isinstance(returned_model, str) or not returned_model:
            returned_model = self._model
        response_id = decoded.get("id")
        return GenerationResponse(
            text=content,
            provider="ifm",
            model=returned_model,
            finish_reason=finish_reason if isinstance(finish_reason, str) else "",
            response_id=response_id if isinstance(response_id, str) else "",
            usage=TokenUsage(
                input_tokens=_optional_token_count(usage.get("prompt_tokens")),
                output_tokens=_optional_token_count(usage.get("completion_tokens")),
            ),
            metadata={
                "binding_id": self.binding_id,
                "api_mode": self._api_mode,
                "stream": self._stream,
                "stream_chunks": stream_chunks,
                "content_kind": content_kind,
                "completion_status": generation_completion_status(finish_reason, {"content_kind": content_kind}),
                "http_attempts": 1 + len(rate_limit_retries),
                "http_started_at": http_started_at,
                "http_finished_at": http_finished_at,
                "rate_limit_retries": rate_limit_retries,
                "request_start_interval_s": self._request_gate.interval_s if self._request_gate else None,
                "max_output_tokens_requested": request.config.max_output_tokens,
                "max_output_tokens_sent": payload["max_tokens"],
                "context_window_tokens": self._context_window_tokens,
                "input_reserve_tokens": input_reserve,
                "input_reserve_policy": "utf8_message_json_bytes_plus_1024" if input_reserve is not None else None,
                "structured_output_transport": "native_json_schema_local_validation" if self.supports_strict_action_schema else "prompt_json_local_validation",
                "provider_schema_enforced": self.supports_strict_action_schema,
                "response_schema_sha256": schema_sha256,
                "reasoning_effort": self._reasoning_effort,
                "reasoning_tokens": _optional_token_count(
                    completion_details.get("reasoning_tokens")
                ),
                "model_requested": self._model,
                "model_resolved": returned_model,
                "provider_state_reused": False,
            },
        )


__all__ = [
    "DEFAULT_IFM_CHAT_COMPLETIONS_ENDPOINT",
    "DEFAULT_IFM_MODEL",
    "DEFAULT_IFM_PLATFORM_ENDPOINT",
    "DEFAULT_IFM_PLATFORM_MODEL",
    "IFMChatCompletionsBackend",
    "RequestStartGate",
    "IFM_REASONING_EFFORTS",
    "IFM_PLATFORM_REASONING_EFFORTS",
]
