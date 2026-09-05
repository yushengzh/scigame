"""Minimal OpenAI Responses binding for the provider-neutral LLM adapter.

The benchmark's Python decoder remains the normative action-schema validator.
This transport requests one JSON object, returns the observable model text, and
does not retain provider-side response state between benchmark turns.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any, Callable, Dict, List, Mapping, Optional, Tuple

from role_benchmark import (
    GenerationRequest,
    GenerationResponse,
    ProviderTransportError,
    TokenUsage,
)


DEFAULT_OPENAI_RESPONSES_ENDPOINT = "https://api.openai.com/v1/responses"
DEFAULT_OPENAI_MODEL = "gpt-5.6"
REASONING_EFFORTS: Tuple[str, ...] = (
    "none",
    "low",
    "medium",
    "high",
    "xhigh",
    "max",
)


def _optional_token_count(value: Any) -> Optional[int]:
    return value if type(value) is int and value >= 0 else None


def _response_text(decoded: Mapping[str, Any]) -> Tuple[str, str]:
    """Extract non-streaming assistant content without assuming output[0]."""

    output = decoded.get("output")
    if not isinstance(output, list):
        raise RuntimeError("provider returned an invalid Responses output")

    texts: List[str] = []
    refusals: List[str] = []
    for raw_item in output:
        if not isinstance(raw_item, Mapping) or raw_item.get("type") != "message":
            continue
        content = raw_item.get("content")
        if not isinstance(content, list):
            raise RuntimeError("provider returned an invalid Responses message")
        for raw_part in content:
            if not isinstance(raw_part, Mapping):
                raise RuntimeError("provider returned an invalid Responses content item")
            content_type = raw_part.get("type")
            if content_type == "output_text":
                text = raw_part.get("text")
                if not isinstance(text, str):
                    raise RuntimeError("provider returned invalid output text")
                texts.append(text)
            elif content_type == "refusal":
                refusal = raw_part.get("refusal")
                if not isinstance(refusal, str):
                    raise RuntimeError("provider returned an invalid refusal")
                refusals.append(refusal)

    if texts and refusals:
        raise RuntimeError("provider returned both output text and a refusal")
    if texts:
        return "".join(texts), "output_text"
    if refusals:
        # Returning the observable refusal lets the existing strict decoder
        # classify a Player refusal as model output, rather than transport loss.
        return "\n".join(refusals), "refusal"
    raise RuntimeError("provider returned no assistant text")


class OpenAIResponsesBackend:
    """Standard-library OpenAI Responses implementation of TextGenerationBackend."""

    binding_id = "case_matrix.openai_responses"

    def __init__(
        self,
        *,
        api_key: str,
        endpoint: str = DEFAULT_OPENAI_RESPONSES_ENDPOINT,
        model: str = DEFAULT_OPENAI_MODEL,
        reasoning_effort: str = "none",
        timeout_s: float = 120.0,
        urlopen: Callable[..., Any] = urllib.request.urlopen,
    ) -> None:
        if not endpoint.startswith(("https://", "http://")):
            raise ValueError("endpoint must be an HTTP(S) URL")
        if not api_key or not api_key.strip():
            raise ValueError("api_key must be non-empty")
        if not model or not model.strip():
            raise ValueError("model must be non-empty")
        if reasoning_effort not in REASONING_EFFORTS:
            raise ValueError(
                "reasoning_effort must be one of %s"
                % ", ".join(REASONING_EFFORTS)
            )
        if timeout_s <= 0:
            raise ValueError("timeout_s must be positive")
        self._endpoint = endpoint
        self._api_key = api_key
        self._model = model
        self._reasoning_effort = reasoning_effort
        self._timeout_s = float(timeout_s)
        self._urlopen = urlopen

    def generate(self, request: GenerationRequest) -> GenerationResponse:
        if not isinstance(request, GenerationRequest):
            raise ValueError("request must be GenerationRequest")
        if request.config.seed is not None:
            raise ValueError("OpenAI Responses does not expose a seed parameter")

        payload: Dict[str, Any] = {
            "model": self._model,
            "input": [
                {"role": message.role, "content": message.content}
                for message in request.messages
            ],
            "max_output_tokens": request.config.max_output_tokens,
            "temperature": request.config.temperature,
            "top_p": request.config.top_p,
            "reasoning": {
                "effort": self._reasoning_effort,
                "context": "current_turn",
            },
            "text": {"format": {"type": "json_object"}},
            "store": False,
        }
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode(
            "utf-8"
        )
        http_request = urllib.request.Request(
            self._endpoint,
            data=body,
            headers={
                "Authorization": "Bearer " + self._api_key,
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            method="POST",
        )
        try:
            with self._urlopen(http_request, timeout=self._timeout_s) as response:
                response_body = response.read()
        except urllib.error.HTTPError as exc:
            # Provider bodies and request headers are deliberately not surfaced.
            raise ProviderTransportError(http_status=exc.code) from exc
        except urllib.error.URLError as exc:
            raise ProviderTransportError(connection_failed=True) from exc

        try:
            decoded = json.loads(response_body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RuntimeError("provider returned invalid Responses JSON") from exc
        if not isinstance(decoded, Mapping):
            raise RuntimeError("provider returned a non-object Responses payload")

        status = decoded.get("status")
        if status not in ("completed", "incomplete"):
            raise RuntimeError("provider did not complete the response")
        incomplete_details = decoded.get("incomplete_details")
        if incomplete_details is None:
            incomplete_details = {}
        if not isinstance(incomplete_details, Mapping):
            raise RuntimeError("provider returned invalid incomplete details")
        incomplete_reason = incomplete_details.get("reason")
        if incomplete_reason is not None and not isinstance(incomplete_reason, str):
            raise RuntimeError("provider returned an invalid incomplete reason")

        try:
            text, content_kind = _response_text(decoded)
        except RuntimeError:
            if status != "incomplete":
                raise
            # Preserve the same semantics as a truncated chat completion: the
            # app-side decoder sees the empty/partial output as a model failure.
            text, content_kind = "", "none"

        usage = decoded.get("usage")
        if usage is None:
            usage = {}
        if not isinstance(usage, Mapping):
            raise RuntimeError("provider returned invalid usage")
        output_details = usage.get("output_tokens_details")
        if output_details is None:
            output_details = {}
        if not isinstance(output_details, Mapping):
            raise RuntimeError("provider returned invalid output token details")

        model = decoded.get("model")
        response_id = decoded.get("id")
        returned_model = model if isinstance(model, str) and model else self._model
        returned_id = response_id if isinstance(response_id, str) else ""
        finish_reason = (
            "completed"
            if status == "completed"
            else "incomplete:%s" % (incomplete_reason or "unknown")
        )
        return GenerationResponse(
            text=text,
            provider="openai",
            model=returned_model,
            finish_reason=finish_reason,
            response_id=returned_id,
            usage=TokenUsage(
                input_tokens=_optional_token_count(usage.get("input_tokens")),
                output_tokens=_optional_token_count(usage.get("output_tokens")),
            ),
            metadata={
                "binding_id": self.binding_id,
                "structured_output_transport": "responses_json_object",
                "reasoning_effort": self._reasoning_effort,
                "reasoning_context": "current_turn",
                "returned_model": returned_model,
                "reasoning_tokens": _optional_token_count(
                    output_details.get("reasoning_tokens")
                ),
                "response_status": status,
                "incomplete_reason": incomplete_reason,
                "content_kind": content_kind,
            },
        )


__all__ = [
    "DEFAULT_OPENAI_MODEL",
    "DEFAULT_OPENAI_RESPONSES_ENDPOINT",
    "OpenAIResponsesBackend",
    "REASONING_EFFORTS",
]
