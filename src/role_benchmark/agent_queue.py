"""Sequential file queue for temporary agent-simulated generation calls."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Tuple

from .llm import (
    GenerationRequest,
    GenerationResponse,
    TextGenerationBackend,
    TokenUsage,
    generation_request_to_payload,
)


class AgentQueueResponseRequired(RuntimeError):
    def __init__(self, request_path: Path, response_path: Path) -> None:
        self.request_path = request_path
        self.response_path = response_path
        super().__init__("agent response required")


class SequentialAgentBackend(TextGenerationBackend):
    """Use numbered request/response files at the normal generation boundary."""

    def __init__(
        self,
        exchange_directory: str,
        *,
        role: str,
        agent_id: str,
        model: str = "gpt-5.6-sol",
        resume_existing: bool = True,
    ) -> None:
        self._directory = Path(exchange_directory).resolve() / role
        self._directory.mkdir(parents=True, exist_ok=True)
        self._role = role
        self._agent_id = agent_id
        self._model = model
        self._resume_existing = resume_existing
        self._position: Optional[int] = None

    def _requests(self) -> Tuple[Path, ...]:
        return tuple(sorted(self._directory.glob("[0-9][0-9][0-9][0-9][0-9][0-9].request.json")))

    @staticmethod
    def _load(path: Path) -> Mapping[str, Any]:
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise ValueError("agent queue file must contain one JSON object")
        return value

    def _select_position(self, request_payload: Mapping[str, Any]) -> int:
        for path in reversed(self._requests()):
            value = self._load(path)
            if value.get("request") == request_payload:
                return int(path.name[:6])
        requests = self._requests()
        return int(requests[-1].name[:6]) + 1 if requests else 1

    def generate(self, request: GenerationRequest) -> GenerationResponse:
        request_payload = generation_request_to_payload(request)
        if self._position is None:
            if self._resume_existing:
                self._position = self._select_position(request_payload)
            else:
                requests = self._requests()
                self._position = int(requests[-1].name[:6]) + 1 if requests else 1
        request_id = "%06d" % self._position
        request_path = self._directory / (request_id + ".request.json")
        if request_path.exists() and self._load(request_path).get("request") != request_payload:
            matching = [
                path
                for path in reversed(self._requests())
                if self._load(path).get("request") == request_payload
            ]
            if matching:
                self._position = int(matching[0].name[:6])
            else:
                requests = self._requests()
                self._position = int(requests[-1].name[:6]) + 1
            request_id = "%06d" % self._position
            request_path = self._directory / (request_id + ".request.json")
        response_path = self._directory / (request_id + ".response.json")
        request_envelope: Dict[str, Any] = {
            "schema": "role_benchmark.agent_queue_request.v1",
            "request_id": request_id,
            "role": self._role,
            "agent_id": self._agent_id,
            "model": self._model,
            "request": request_payload,
        }
        if request_path.exists():
            if self._load(request_path) != request_envelope:
                raise ValueError("numbered agent request does not match the current call")
        else:
            request_path.write_text(
                json.dumps(request_envelope, ensure_ascii=False, sort_keys=True) + "\n",
                encoding="utf-8",
            )
        if not response_path.exists():
            raise AgentQueueResponseRequired(request_path, response_path)
        response = self._load(response_path)
        expected = {
            "schema": "role_benchmark.agent_queue_response.v1",
            "request_id": request_id,
            "role": self._role,
            "agent_id": self._agent_id,
            "model": self._model,
        }
        for key, value in expected.items():
            if response.get(key) != value:
                raise ValueError("agent response %s does not match the current call" % key)
        if set(response) != set(expected) | {"text"}:
            raise ValueError("agent response contains unexpected fields")
        if not isinstance(response["text"], str):
            raise ValueError("agent response text must be text")
        self._position += 1
        return GenerationResponse(
            text=response["text"],
            provider="gpt56_agent_simulation",
            model=self._model,
            finish_reason="completed",
            usage=TokenUsage(),
            metadata={
                "role": self._role,
                "agent_id": self._agent_id,
                "request_id": request_id,
                "temporary_agent_simulation": True,
            },
        )


def pending_agent_requests(exchange_directory: str) -> Tuple[Path, ...]:
    root = Path(exchange_directory).resolve()
    pending = []
    for request_path in sorted(root.glob("*/*.request.json")):
        response_path = request_path.with_name(
            request_path.name.replace(".request.json", ".response.json")
        )
        if not response_path.exists():
            pending.append(request_path)
    return tuple(pending)
