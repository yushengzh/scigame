"""Auditable file exchange for manually mediated LLM sandbox calls.

This module is deliberately separate from the HTTP provider bindings used by
registered experiments.  A backend writes the exact logical generation request
to a role-specific directory and only returns a response after a matching,
strict response envelope has been supplied.  It performs no network access and
must not be used to label a run as a call to an API provider.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Mapping, Optional, Tuple

from .llm import (
    GenerationRequest,
    GenerationResponse,
    TextGenerationBackend,
    TokenUsage,
    generation_request_to_payload,
)
from .wire import WireDecodeError, canonical_json_dumps, strict_json_loads


AGENT_SANDBOX_REQUEST_SCHEMA = "role_benchmark.agent_sandbox_request.v1"
AGENT_SANDBOX_RESPONSE_SCHEMA = "role_benchmark.agent_sandbox_response.v1"
AGENT_SANDBOX_PROVIDER = "codex_agent_sandbox"
AGENT_SANDBOX_ROLES: Tuple[str, ...] = ("player", "oracle", "evaluator")
MAX_AGENT_SANDBOX_RESPONSE_BYTES = 1_048_576


class AgentSandboxError(RuntimeError):
    """Base class for agent-sandbox exchange failures."""


class AgentSandboxResponseRequired(AgentSandboxError):
    """The exact request was captured but has no matching response yet."""

    def __init__(self, request_path: Path, response_path: Path) -> None:
        self.request_path = request_path
        self.response_path = response_path
        super().__init__("a matching sandbox response is required")


class AgentSandboxResponseError(AgentSandboxError):
    """A supplied sandbox response failed the strict exchange contract."""


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _exact_keys(
    value: Mapping[str, Any], expected: Tuple[str, ...], label: str
) -> None:
    actual = set(value)
    wanted = set(expected)
    if actual == wanted:
        return
    missing = sorted(wanted - actual)
    extra = sorted(actual - wanted)
    details = []
    if missing:
        details.append("missing %s" % ", ".join(missing))
    if extra:
        details.append("unexpected %s" % ", ".join(extra))
    raise AgentSandboxResponseError("%s has %s" % (label, "; ".join(details)))


def _write_canonical_once(path: Path, payload: Mapping[str, Any]) -> None:
    text = canonical_json_dumps(payload) + "\n"
    try:
        with path.open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(text)
    except FileExistsError:
        if path.read_text(encoding="utf-8") != text:
            raise AgentSandboxError(
                "existing sandbox exchange file differs from the exact request"
            )


class AgentFileExchangeBackend(TextGenerationBackend):
    """Capture exact requests and replay role-bound gpt-5.6 agent responses."""

    def __init__(
        self,
        exchange_directory: str,
        *,
        role: str,
        agent_id: str,
        model: str = "gpt-5.6-sol",
    ) -> None:
        if role not in AGENT_SANDBOX_ROLES:
            raise ValueError("unsupported sandbox role %r" % role)
        if not isinstance(agent_id, str) or not agent_id.strip():
            raise ValueError("agent_id must be non-empty text")
        if not isinstance(model, str) or not model.strip():
            raise ValueError("model must be non-empty text")
        self._directory = Path(exchange_directory).resolve() / role
        self._directory.mkdir(parents=True, exist_ok=True)
        self._role = role
        self._agent_id = agent_id
        self._model = model

    @property
    def role(self) -> str:
        return self._role

    @property
    def agent_id(self) -> str:
        return self._agent_id

    def generate(self, request: GenerationRequest) -> GenerationResponse:
        if not isinstance(request, GenerationRequest):
            raise ValueError("request must be GenerationRequest")
        request_payload = generation_request_to_payload(request)
        request_text = canonical_json_dumps(request_payload)
        request_sha256 = _sha256_text(request_text)
        stem = request_sha256
        request_path = self._directory / (stem + ".request.json")
        response_path = self._directory / (stem + ".response.json")
        request_envelope = {
            "schema": AGENT_SANDBOX_REQUEST_SCHEMA,
            "role": self._role,
            "expected_agent_id": self._agent_id,
            "request_sha256": request_sha256,
            "request": request_payload,
        }
        _write_canonical_once(request_path, request_envelope)
        if not response_path.exists():
            raise AgentSandboxResponseRequired(request_path, response_path)

        try:
            response_value = strict_json_loads(
                response_path.read_text(encoding="utf-8"),
                max_bytes=MAX_AGENT_SANDBOX_RESPONSE_BYTES,
            )
        except (OSError, UnicodeError, WireDecodeError) as exc:
            raise AgentSandboxResponseError(
                "sandbox response is not strict UTF-8 JSON"
            ) from exc
        if not isinstance(response_value, dict):
            raise AgentSandboxResponseError("sandbox response must be an object")
        _exact_keys(
            response_value,
            (
                "schema",
                "role",
                "agent_id",
                "request_sha256",
                "model",
                "text",
            ),
            "sandbox response",
        )
        expected = {
            "schema": AGENT_SANDBOX_RESPONSE_SCHEMA,
            "role": self._role,
            "agent_id": self._agent_id,
            "request_sha256": request_sha256,
            "model": self._model,
        }
        for key, expected_value in expected.items():
            if response_value[key] != expected_value:
                raise AgentSandboxResponseError(
                    "sandbox response %s does not match the captured request" % key
                )
        response_text = response_value["text"]
        if not isinstance(response_text, str):
            raise AgentSandboxResponseError("sandbox response text must be text")
        return GenerationResponse(
            text=response_text,
            provider=AGENT_SANDBOX_PROVIDER,
            model=self._model,
            finish_reason="captured",
            response_id="agent-sandbox-" + request_sha256[:16],
            usage=TokenUsage(),
            metadata={
                "binding_id": "role_benchmark.agent_file_exchange",
                "sandbox_only": True,
                "role": self._role,
                "agent_id": self._agent_id,
                "request_sha256": request_sha256,
            },
        )


def pending_agent_sandbox_requests(
    exchange_directory: str,
) -> Tuple[Path, ...]:
    """Return captured requests whose role-bound response is still absent."""

    root = Path(exchange_directory).resolve()
    pending = []
    for request_path in sorted(root.glob("*/*.request.json")):
        response_path = request_path.with_name(
            request_path.name.replace(".request.json", ".response.json")
        )
        if not response_path.exists():
            pending.append(request_path)
    return tuple(pending)


__all__ = [
    "AGENT_SANDBOX_PROVIDER",
    "AGENT_SANDBOX_REQUEST_SCHEMA",
    "AGENT_SANDBOX_RESPONSE_SCHEMA",
    "AGENT_SANDBOX_ROLES",
    "AgentFileExchangeBackend",
    "AgentSandboxError",
    "AgentSandboxResponseError",
    "AgentSandboxResponseRequired",
    "pending_agent_sandbox_requests",
]
