"""Minimal native Gemini ``generateContent`` provider binding.

The benchmark's Python decoder remains the normative action-schema validator.
This transport asks Gemini for JSON, returns only the observable model text,
and keeps provider credentials out of response metadata and raised errors.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

from role_benchmark import GenerationRequest, GenerationResponse, TokenUsage


_GEMINI_SCHEMA_KEYS = frozenset(
    {
        "$id",
        "$defs",
        "$ref",
        "$anchor",
        "type",
        "format",
        "title",
        "description",
        "enum",
        "items",
        "prefixItems",
        "minItems",
        "maxItems",
        "minimum",
        "maximum",
        "anyOf",
        "oneOf",
        "properties",
        "additionalProperties",
        "required",
    }
)


def _copy_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _copy_json(child) for key, child in value.items()}
    if isinstance(value, (list, tuple)):
        return [_copy_json(child) for child in value]
    return value


def _project_gemini_schema(schema: Mapping[str, Any]) -> Mapping[str, Any]:
    """Project the app schema onto Gemini's supported JSON Schema subset."""

    projected: Dict[str, Any] = {}
    for key, value in schema.items():
        if key not in _GEMINI_SCHEMA_KEYS:
            continue
        if key in ("$defs", "properties"):
            if isinstance(value, Mapping):
                projected[key] = {
                    name: _project_gemini_schema(child)
                    for name, child in value.items()
                    if isinstance(name, str) and isinstance(child, Mapping)
                }
        elif key in ("anyOf", "oneOf", "prefixItems"):
            if isinstance(value, (list, tuple)):
                projected[key] = [
                    _project_gemini_schema(child)
                    for child in value
                    if isinstance(child, Mapping)
                ]
        elif key == "items":
            if isinstance(value, Mapping):
                projected[key] = _project_gemini_schema(value)
        elif key == "additionalProperties":
            if isinstance(value, Mapping):
                projected[key] = _project_gemini_schema(value)
            elif isinstance(value, bool):
                projected[key] = value
        else:
            projected[key] = _copy_json(value)

    # ``const`` is unsupported, but a singleton enum has the same meaning.
    if "const" in schema:
        projected["enum"] = [_copy_json(schema["const"])]
    return projected


def _optional_token_count(value: Any) -> Optional[int]:
    return value if type(value) is int and value >= 0 else None


def _gemini_messages(
    messages: Sequence[Any],
) -> Tuple[Optional[Mapping[str, Any]], List[Mapping[str, Any]]]:
    """Map neutral roles to Gemini's system instruction and content roles."""

    system_parts: List[Mapping[str, str]] = []
    contents: List[Mapping[str, Any]] = []
    for message in messages:
        role = message.role
        content = message.content
        if role == "system":
            system_parts.append({"text": content})
        elif role == "user":
            contents.append({"role": "user", "parts": [{"text": content}]})
        elif role == "assistant":
            contents.append({"role": "model", "parts": [{"text": content}]})
        else:
            raise ValueError("unsupported Gemini message role: %s" % role)

    if not contents:
        raise ValueError("Gemini request must contain a user or assistant message")
    system_instruction: Optional[Mapping[str, Any]] = None
    if system_parts:
        system_instruction = {"parts": system_parts}
    return system_instruction, contents


def _candidate_text(candidate: Mapping[str, Any]) -> Tuple[str, str]:
    """Return visible answer text, excluding any explicitly marked thoughts."""

    content = candidate.get("content")
    if content is None:
        return "", "none"
    if not isinstance(content, Mapping):
        raise RuntimeError("provider returned invalid Gemini candidate content")
    parts = content.get("parts")
    if parts is None:
        return "", "none"
    if not isinstance(parts, list):
        raise RuntimeError("provider returned invalid Gemini candidate parts")

    texts: List[str] = []
    for part in parts:
        if not isinstance(part, Mapping):
            raise RuntimeError("provider returned an invalid Gemini content part")
        if part.get("thought") is True:
            continue
        if "text" not in part:
            continue
        text = part.get("text")
        if not isinstance(text, str):
            raise RuntimeError("provider returned non-text Gemini content")
        texts.append(text)
    if not texts:
        return "", "none"
    return "".join(texts), "text"


class GeminiGenerateContentBackend:
    """Standard-library binding for Gemini's native ``generateContent`` API."""

    binding_id = "case_matrix.gemini_generate_content"

    def __init__(
        self,
        *,
        endpoint: str,
        api_key: str,
        model: str,
        timeout_seconds: float = 120.0,
        urlopen: Callable[..., Any] = urllib.request.urlopen,
    ) -> None:
        if not endpoint.startswith(("https://", "http://")):
            raise ValueError("endpoint must be an HTTP(S) URL")
        if not api_key or not api_key.strip():
            raise ValueError("api_key must be non-empty")
        if not model or not model.strip():
            raise ValueError("model must be non-empty")
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        self._endpoint = endpoint
        self._api_key = api_key
        self._model = model
        self._timeout_s = float(timeout_seconds)
        self._urlopen = urlopen

    def generate(self, request: GenerationRequest) -> GenerationResponse:
        if not isinstance(request, GenerationRequest):
            raise ValueError("request must be GenerationRequest")

        system_instruction, contents = _gemini_messages(request.messages)
        generation_config: Dict[str, Any] = {
            "candidateCount": 1,
            "maxOutputTokens": request.config.max_output_tokens,
            "temperature": request.config.temperature,
            "topP": request.config.top_p,
            "responseFormat": {
                "text": {
                    "mimeType": "application/json",
                    "schema": _project_gemini_schema(request.response_schema),
                }
            },
        }
        if request.config.seed is not None:
            generation_config["seed"] = request.config.seed
        payload: Dict[str, Any] = {
            "contents": contents,
            "generationConfig": generation_config,
        }
        if system_instruction is not None:
            payload["systemInstruction"] = system_instruction

        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode(
            "utf-8"
        )
        http_request = urllib.request.Request(
            self._endpoint,
            data=body,
            headers={
                "x-goog-api-key": self._api_key,
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            method="POST",
        )
        try:
            with self._urlopen(http_request, timeout=self._timeout_s) as response:
                response_body = response.read()
        except urllib.error.HTTPError as exc:
            raise RuntimeError("provider HTTP status %d" % exc.code) from exc
        except urllib.error.URLError as exc:
            raise RuntimeError("provider connection failed") from exc

        try:
            decoded = json.loads(response_body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RuntimeError("provider returned invalid Gemini JSON") from exc
        if not isinstance(decoded, Mapping):
            raise RuntimeError("provider returned a non-object Gemini payload")

        candidates = decoded.get("candidates")
        if not isinstance(candidates, list) or not candidates:
            feedback = decoded.get("promptFeedback")
            block_reason = (
                feedback.get("blockReason")
                if isinstance(feedback, Mapping)
                else None
            )
            if isinstance(block_reason, str) and block_reason:
                candidate: Mapping[str, Any] = {}
                text = ""
                content_kind = "none"
                finish_reason = "prompt_blocked:%s" % block_reason
            else:
                raise RuntimeError("provider returned no Gemini candidate")
        else:
            candidate = candidates[0]
            if not isinstance(candidate, Mapping):
                raise RuntimeError("provider returned an invalid Gemini candidate")
            text, content_kind = _candidate_text(candidate)
            raw_finish_reason = candidate.get("finishReason")
            finish_reason = (
                raw_finish_reason if isinstance(raw_finish_reason, str) else ""
            )

        usage = decoded.get("usageMetadata")
        if usage is None:
            usage = {}
        if not isinstance(usage, Mapping):
            raise RuntimeError("provider returned invalid Gemini usage metadata")
        returned_model = decoded.get("modelVersion")
        response_id = decoded.get("responseId")
        model = (
            returned_model
            if isinstance(returned_model, str) and returned_model
            else self._model
        )
        return GenerationResponse(
            text=text,
            provider="gemini",
            model=model,
            finish_reason=finish_reason,
            response_id=response_id if isinstance(response_id, str) else "",
            usage=TokenUsage(
                input_tokens=_optional_token_count(usage.get("promptTokenCount")),
                output_tokens=_optional_token_count(
                    usage.get("candidatesTokenCount")
                ),
            ),
            metadata={
                "binding_id": self.binding_id,
                "structured_output_transport": "gemini_response_format_json_schema",
                "returned_model": model,
                "content_kind": content_kind,
                "thoughts_tokens": _optional_token_count(
                    usage.get("thoughtsTokenCount")
                ),
                "total_tokens": _optional_token_count(usage.get("totalTokenCount")),
            },
        )


__all__ = ["GeminiGenerateContentBackend"]
