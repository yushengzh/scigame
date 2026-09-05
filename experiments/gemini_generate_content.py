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

from role_benchmark import (
    GenerationRequest,
    GenerationResponse,
    ProviderTransportError,
    TokenUsage,
)


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


def _schema_types(schema: Mapping[str, Any]) -> Tuple[str, ...]:
    """Return the primitive types visible without following references."""

    result: List[str] = []
    declared = schema.get("type")
    if isinstance(declared, str):
        result.append(declared)
    elif isinstance(declared, (list, tuple)):
        result.extend(item for item in declared if isinstance(item, str))
    for keyword in ("anyOf", "oneOf"):
        branches = schema.get(keyword)
        if isinstance(branches, (list, tuple)):
            for branch in branches:
                if isinstance(branch, Mapping):
                    result.extend(_schema_types(branch))
    return tuple(dict.fromkeys(result))


def _relaxed_recursive_value(schema: Mapping[str, Any]) -> Mapping[str, Any]:
    """Keep recursive values generatable without imposing an arbitrary depth."""

    types = _schema_types(schema)
    if not types:
        return {}
    if len(types) == 1:
        return {"type": types[0]}
    return {"anyOf": [{"type": item} for item in types]}


def _schema_references(value: Any) -> Tuple[str, ...]:
    references: List[str] = []
    if isinstance(value, Mapping):
        reference = value.get("$ref")
        if isinstance(reference, str):
            references.append(reference)
        for child in value.values():
            references.extend(_schema_references(child))
    elif isinstance(value, (list, tuple)):
        for child in value:
            references.extend(_schema_references(child))
    return tuple(references)


def _inline_local_definitions(schema: Mapping[str, Any]) -> Mapping[str, Any]:
    """Inline local definitions and relax only recursive back-edges.

    Gemini accepts ``$defs``/``$ref`` but rejects cyclic references on required
    paths.  The logical request and system prompt retain the complete recursive
    schema; this provider projection leaves recursive descendants open to the
    same primitive types so the local strict decoder remains authoritative and
    no finite expression-depth limit is introduced.
    """

    raw_definitions = schema.get("$defs")
    if not isinstance(raw_definitions, Mapping):
        return _copy_json(schema)
    definitions = {
        "#/$defs/" + name.replace("~", "~0").replace("/", "~1"): value
        for name, value in raw_definitions.items()
        if isinstance(name, str) and isinstance(value, Mapping)
    }
    references = set(_schema_references(schema))
    if not references or not references.issubset(definitions):
        return _copy_json(schema)

    def inline(value: Any, active: frozenset[str]) -> Any:
        if isinstance(value, Mapping):
            reference = value.get("$ref")
            if isinstance(reference, str) and reference in definitions:
                target = definitions[reference]
                # Expand the first occurrence so a required expression root
                # still has a meaningful shape.  Relax only the actual
                # recursive back-edge; otherwise every expression object was
                # projected to a bare ``{"type": "object"}``, which lets the
                # provider satisfy the transport schema with ``{}``.
                if reference in active:
                    return _relaxed_recursive_value(target)
                return inline(target, active | {reference})
            return {
                key: inline(child, active)
                for key, child in value.items()
                if key != "$defs"
            }
        if isinstance(value, (list, tuple)):
            return [inline(child, active) for child in value]
        return value

    result = inline(schema, frozenset())
    if not isinstance(result, Mapping):
        raise AssertionError("schema inlining must preserve an object root")
    return result


def _collapse_nullable_any_of(schema: Mapping[str, Any]) -> Mapping[str, Any]:
    """Use Gemini's documented type-array spelling for a nullable scalar."""

    if set(schema) != {"anyOf"}:
        return schema
    branches = schema.get("anyOf")
    if not isinstance(branches, (list, tuple)) or len(branches) != 2:
        return schema
    null_branches = [
        branch
        for branch in branches
        if isinstance(branch, Mapping) and branch == {"type": "null"}
    ]
    non_null_branches = [
        branch for branch in branches if branch not in null_branches
    ]
    if len(null_branches) != 1 or len(non_null_branches) != 1:
        return schema
    base = non_null_branches[0]
    if not isinstance(base, Mapping) or not isinstance(base.get("type"), str):
        return schema
    if base["type"] == "null":
        return schema
    result = _copy_json(base)
    result["type"] = [base["type"], "null"]
    return result


def _project_gemini_schema_node(schema: Mapping[str, Any]) -> Mapping[str, Any]:
    projected_input = _collapse_nullable_any_of(schema)

    projected: Dict[str, Any] = {}
    for key, value in projected_input.items():
        if key not in _GEMINI_SCHEMA_KEYS:
            continue
        if key in ("$defs", "properties"):
            if isinstance(value, Mapping):
                projected[key] = {
                    name: _project_gemini_schema_node(child)
                    for name, child in value.items()
                    if isinstance(name, str) and isinstance(child, Mapping)
                }
        elif key in ("anyOf", "oneOf", "prefixItems"):
            if isinstance(value, (list, tuple)):
                projected[key] = [
                    _project_gemini_schema_node(child)
                    for child in value
                    if isinstance(child, Mapping)
                ]
        elif key == "items":
            if isinstance(value, Mapping):
                projected[key] = _project_gemini_schema_node(value)
        elif key == "additionalProperties":
            if isinstance(value, Mapping):
                projected[key] = _project_gemini_schema_node(value)
            elif isinstance(value, bool):
                projected[key] = value
        else:
            projected[key] = _copy_json(value)

    # ``const`` is unsupported, but a singleton enum has the same meaning.
    if "const" in projected_input:
        projected["enum"] = [_copy_json(projected_input["const"])]
    return projected


def _project_gemini_schema(schema: Mapping[str, Any]) -> Mapping[str, Any]:
    """Project the app schema onto Gemini's supported JSON Schema subset."""

    return _project_gemini_schema_node(_inline_local_definitions(schema))


def _without_constraint_state_hotspots(value: Any) -> Any:
    """Relax constraints that can exceed Gemini's serving-state limit.

    This is used only for the post-hoc Evaluator transport.  The complete
    provider-neutral schema remains in the prompt and the local decoder stays
    authoritative for array length and numeric range validation.
    """

    if isinstance(value, Mapping):
        return {
            key: _without_constraint_state_hotspots(child)
            for key, child in value.items()
            if key not in ("maxItems", "minimum", "maximum")
        }
    if isinstance(value, (list, tuple)):
        return [_without_constraint_state_hotspots(child) for child in value]
    return value


def _project_gemini_request_schema(
    request: GenerationRequest,
) -> Mapping[str, Any]:
    projected = _project_gemini_schema(request.response_schema)
    if request.metadata.get("purpose") == "post_hoc_transcript_evaluation":
        relaxed = _without_constraint_state_hotspots(projected)
        if not isinstance(relaxed, Mapping):
            raise AssertionError("schema relaxation must preserve an object root")
        return relaxed
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


def _gemini_http_error_reason(exc: urllib.error.HTTPError) -> Optional[str]:
    """Classify a Google error without persisting its response or request."""

    try:
        body = exc.read(65_537)
    except Exception:
        return None
    if not isinstance(body, bytes) or len(body) > 65_536:
        return None
    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(payload, Mapping):
        return None
    error = payload.get("error")
    if not isinstance(error, Mapping):
        return None
    message = error.get("message")
    if not isinstance(message, str):
        return None
    normalized = message.casefold()
    if "too many states" in normalized:
        return "schema_constraint_too_complex"
    if "invalid json payload" in normalized:
        return "invalid_request_payload"
    if "response schema" in normalized or "responsejsonschema" in normalized:
        return "response_schema_rejected"
    if "api key" in normalized or "permission denied" in normalized:
        return "authentication_rejected"
    if "quota" in normalized or "rate limit" in normalized:
        return "quota_or_rate_limit"
    return None


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
            # Use the long-standing Developer API fields documented by the
            # Google Gen AI SDK for Gemini 2.5.  This remains compatible with
            # 2.5 endpoints that do not accept the newer responseFormat form.
            "responseMimeType": "application/json",
            "responseJsonSchema": _project_gemini_request_schema(request),
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
            raise ProviderTransportError(
                http_status=exc.code,
                safe_reason=_gemini_http_error_reason(exc),
            ) from exc
        except urllib.error.URLError as exc:
            raise ProviderTransportError(connection_failed=True) from exc

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
                "structured_output_transport": "gemini_response_json_schema",
                "returned_model": model,
                "content_kind": content_kind,
                "thoughts_tokens": _optional_token_count(
                    usage.get("thoughtsTokenCount")
                ),
                "total_tokens": _optional_token_count(usage.get("totalTokenCount")),
            },
        )


__all__ = ["GeminiGenerateContentBackend"]
