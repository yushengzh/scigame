"""Provider-neutral text-generation adapter for development evaluations.

The adapter deliberately exposes one small transport port. Provider SDKs map a
logical :class:`GenerationRequest` to their API and return the raw assistant
text in :class:`GenerationResponse`. No tools, planning, judge, or semantic
auto-correction are hidden in this layer.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Mapping, Optional, Protocol, Tuple, runtime_checkable

from .models import BenchmarkTrack, EpisodeView, PlayerAction
from .wire import (
    DEFAULT_MAX_ACTION_BYTES,
    PLAYER_ACTION_SCHEMA,
    WireDecodeError,
    canonical_json_dumps,
    episode_view_to_json,
    episode_view_to_payload,
    player_action_from_json,
    player_action_json_schema,
    player_action_to_payload,
)


DEVELOPMENT_EVALUATION_PROFILE = "public_development_fixture"
MAX_LLM_ACTION_BYTES = 1_048_576
_MAX_METADATA_BYTES = 1_048_576
_MAX_IDENTITY_TEXT_BYTES = 4_096
_MAX_SAFE_INTEGER = 2**53 - 1


def _finite_number(value: Any) -> bool:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return False
    try:
        return math.isfinite(float(value))
    except OverflowError:
        return False


def _validate_json_mapping(value: Mapping[str, Any], label: str) -> None:
    if not isinstance(value, Mapping):
        raise ValueError("%s must be a mapping" % label)
    text = canonical_json_dumps(value)
    if len(text.encode("utf-8")) > _MAX_METADATA_BYTES:
        raise ValueError("%s exceeds %d bytes" % (label, _MAX_METADATA_BYTES))


def _json_copy(value: Any) -> Any:
    if isinstance(value, Enum):
        return _json_copy(value.value)
    if isinstance(value, Mapping):
        return {key: _json_copy(child) for key, child in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_copy(child) for child in value]
    return value


def _validate_utf8_text(
    value: Any,
    label: str,
    *,
    nonempty: bool = False,
    max_bytes: Optional[int] = None,
) -> None:
    if not isinstance(value, str) or (nonempty and not value.strip()):
        suffix = "non-empty text" if nonempty else "text"
        raise ValueError("%s must be %s" % (label, suffix))
    try:
        encoded = value.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise ValueError("%s must be valid UTF-8 text" % label) from exc
    if max_bytes is not None and len(encoded) > max_bytes:
        raise ValueError("%s exceeds %d bytes" % (label, max_bytes))


@dataclass(frozen=True)
class Message:
    role: str
    content: str

    def __post_init__(self) -> None:
        if self.role not in ("system", "user"):
            raise ValueError("message role must be 'system' or 'user'")
        _validate_utf8_text(self.content, "message content", nonempty=True)


@dataclass(frozen=True)
class GenerationConfig:
    max_output_tokens: int = 4096
    temperature: float = 0.0
    top_p: float = 1.0
    seed: Optional[int] = None

    def __post_init__(self) -> None:
        if isinstance(self.max_output_tokens, bool) or not isinstance(
            self.max_output_tokens, int
        ):
            raise ValueError("max_output_tokens must be an integer")
        if self.max_output_tokens < 1:
            raise ValueError("max_output_tokens must be positive")
        if self.max_output_tokens > _MAX_SAFE_INTEGER:
            raise ValueError("max_output_tokens exceeds the safe integer range")
        if not _finite_number(self.temperature) or self.temperature < 0.0:
            raise ValueError("temperature must be a finite non-negative number")
        if not _finite_number(self.top_p) or not 0.0 < self.top_p <= 1.0:
            raise ValueError("top_p must be in (0, 1]")
        if self.seed is not None and (
            isinstance(self.seed, bool) or not isinstance(self.seed, int)
        ):
            raise ValueError("seed must be an integer or None")
        if self.seed is not None and abs(self.seed) > _MAX_SAFE_INTEGER:
            raise ValueError("seed exceeds the safe integer range")


@dataclass(frozen=True)
class GenerationRequest:
    messages: Tuple[Message, ...]
    response_schema: Mapping[str, Any]
    config: GenerationConfig
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.messages, tuple) or not all(
            isinstance(message, Message) for message in self.messages
        ):
            raise ValueError("generation request messages must be a tuple of Message")
        if not self.messages:
            raise ValueError("generation request must contain messages")
        if not isinstance(self.config, GenerationConfig):
            raise ValueError("generation request config must be GenerationConfig")
        _validate_json_mapping(self.response_schema, "response_schema")
        _validate_json_mapping(self.metadata, "request metadata")
        object.__setattr__(self, "response_schema", _json_copy(self.response_schema))
        object.__setattr__(self, "metadata", _json_copy(self.metadata))


@dataclass(frozen=True)
class TokenUsage:
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None

    def __post_init__(self) -> None:
        for label, value in (
            ("input_tokens", self.input_tokens),
            ("output_tokens", self.output_tokens),
        ):
            if value is not None and (
                isinstance(value, bool) or not isinstance(value, int) or value < 0
            ):
                raise ValueError("%s must be a non-negative integer or None" % label)
            if value is not None and value > _MAX_SAFE_INTEGER:
                raise ValueError("%s exceeds the safe integer range" % label)


@dataclass(frozen=True)
class GenerationResponse:
    """Raw text and metadata returned by one provider binding call."""

    text: str
    provider: str
    model: str
    finish_reason: str = ""
    response_id: str = ""
    usage: TokenUsage = field(default_factory=TokenUsage)
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _validate_utf8_text(self.text, "generation response text")
        _validate_utf8_text(
            self.provider,
            "generation response provider",
            nonempty=True,
            max_bytes=_MAX_IDENTITY_TEXT_BYTES,
        )
        _validate_utf8_text(
            self.model,
            "generation response model",
            nonempty=True,
            max_bytes=_MAX_IDENTITY_TEXT_BYTES,
        )
        _validate_utf8_text(
            self.finish_reason,
            "finish_reason",
            max_bytes=_MAX_IDENTITY_TEXT_BYTES,
        )
        _validate_utf8_text(
            self.response_id, "response_id", max_bytes=_MAX_IDENTITY_TEXT_BYTES
        )
        if not isinstance(self.usage, TokenUsage):
            raise ValueError("generation response usage must be TokenUsage")
        _validate_json_mapping(self.metadata, "response metadata")
        object.__setattr__(self, "metadata", _json_copy(self.metadata))


@runtime_checkable
class TextGenerationBackend(Protocol):
    """Provider binding that performs exactly one text generation call."""

    def generate(self, request: GenerationRequest) -> GenerationResponse:
        ...


EventSink = Callable[[str, Mapping[str, Any]], Any]


class LLMAdapterError(RuntimeError):
    """Base class for an adapter or provider boundary failure."""


class ModelTransportError(LLMAdapterError):
    """The provider binding failed before returning a usable response object."""


class AdapterOutputError(LLMAdapterError):
    """The enabled generation calls did not yield a decodable action."""

    def __init__(self, error: WireDecodeError, attempts: int) -> None:
        self.wire_error = error
        self.attempts = attempts
        super().__init__(
            "model output remained invalid after %d generation call(s): %s"
            % (attempts, error)
        )


@dataclass(frozen=True)
class LLMPlayerStats:
    player_turns: int
    primary_calls: int
    repair_calls: int
    first_pass_valid_actions: int
    decoded_actions: int
    input_tokens: Optional[int]
    output_tokens: Optional[int]


_SYSTEM_INSTRUCTION = """You are the Player in an interactive scientific modelling episode.
Use only the public episode view and Oracle responses. Choose exactly one next action.
Return only one JSON object matching the supplied action schema: no Markdown,
commentary, or extra keys. Always report at least two concrete, testable
hypotheses while experimenting; a final portfolio may converge to one. Never
use OTHER or a residual catch-all. Portfolio confidences must sum to 1.
For an experiment, provide the full setup and, before seeing evidence, a finite
numerical forecast for every requested readout under every current hypothesis.
The forecast hypothesis keys must exactly match the portfolio hypothesis_ids.
For a final submission, provide the structured model requested by the public
case resources. The selected hypothesis's portfolio confidence is the sole
final confidence; do not repeat confidence inside final.
The final.explanation field is a concise rationale and is not itself scored.
Do not reveal hidden chain-of-thought;
put only concise, decision-relevant statements in public fields.
"""


def generation_config_to_payload(config: GenerationConfig) -> Mapping[str, Any]:
    return {
        "max_output_tokens": config.max_output_tokens,
        "temperature": config.temperature,
        "top_p": config.top_p,
        "seed": config.seed,
    }


def generation_request_to_payload(request: GenerationRequest) -> Mapping[str, Any]:
    return {
        "messages": [
            {"role": message.role, "content": message.content}
            for message in request.messages
        ],
        "response_schema": _json_copy(request.response_schema),
        "config": generation_config_to_payload(request.config),
        "metadata": _json_copy(request.metadata),
    }


def generation_response_to_payload(
    response: GenerationResponse,
) -> Mapping[str, Any]:
    return {
        "text": response.text,
        "provider": response.provider,
        "model": response.model,
        "finish_reason": response.finish_reason,
        "response_id": response.response_id,
        "usage": {
            "input_tokens": response.usage.input_tokens,
            "output_tokens": response.usage.output_tokens,
        },
        "metadata": _json_copy(response.metadata),
    }


def build_generation_request(
    view: EpisodeView,
    *,
    player_turn: int,
    config: GenerationConfig,
    purpose: str = "next_action",
    invalid_output: Optional[str] = None,
    wire_error: Optional[WireDecodeError] = None,
) -> GenerationRequest:
    """Build the exact logical request for a primary or repair generation."""

    if purpose not in ("next_action", "repair_action"):
        raise ValueError("unsupported generation purpose")
    schema = player_action_json_schema()
    # The executable-expression contract belongs only to Discovery.  Keeping
    # its recursive ``outputs`` shape in an Identification prompt gives the
    # model a second, irrelevant parameter format and can contaminate the
    # otherwise explicit case-owned submission contract.
    if view.case.track is BenchmarkTrack.IDENTIFICATION:
        schema.pop("$defs", None)
        schema["properties"]["final"].pop("allOf", None)
    episode_view_to_json(view)
    view_payload = episode_view_to_payload(view)
    system = _SYSTEM_INSTRUCTION + "\nAction JSON Schema:\n" + canonical_json_dumps(
        schema
    )
    if purpose == "next_action":
        user_payload: Mapping[str, Any] = {"episode_view": view_payload}
    else:
        if invalid_output is None or wire_error is None:
            raise ValueError("repair request requires invalid output and wire error")
        user_payload = {
            "episode_view": view_payload,
            "repair": {
                "instruction": (
                    "Generate exactly one valid action for the same episode view. "
                    "You received no Oracle response or evidence between calls. "
                    "This is a second generation and may differ semantically."
                ),
                "invalid_output": invalid_output,
                "wire_error": {
                    "code": wire_error.code,
                    "path": wire_error.path,
                    "message": wire_error.detail,
                },
            },
        }
    metadata = {
        "action_schema": PLAYER_ACTION_SCHEMA,
        "evaluation_profile": DEVELOPMENT_EVALUATION_PROFILE,
        "case_id": view.case.case_id,
        "track": view.case.track.value,
        "player_turn": player_turn,
        "purpose": purpose,
    }
    return GenerationRequest(
        messages=(
            Message("system", system),
            Message("user", canonical_json_dumps(user_payload)),
        ),
        response_schema=schema,
        config=config,
        metadata=metadata,
    )


class LLMPlayerBackend:
    """Drive ``PlayerBackend`` with strict JSON from any text backend.

    At most one schema-directed second generation is supported. It never calls
    Oracle and therefore does not consume the scientific experiment budget, but it
    can change semantics and is a distinct evaluation policy.
    """

    def __init__(
        self,
        backend: TextGenerationBackend,
        *,
        config: Optional[GenerationConfig] = None,
        max_repair_attempts: int = 0,
        max_action_bytes: int = DEFAULT_MAX_ACTION_BYTES,
        event_sink: Optional[EventSink] = None,
    ) -> None:
        if isinstance(max_repair_attempts, bool) or max_repair_attempts not in (0, 1):
            raise ValueError("max_repair_attempts must be 0 or 1")
        if isinstance(max_action_bytes, bool) or not isinstance(max_action_bytes, int):
            raise ValueError("max_action_bytes must be an integer")
        if max_action_bytes < 1:
            raise ValueError("max_action_bytes must be positive")
        if max_action_bytes > _MAX_SAFE_INTEGER:
            raise ValueError("max_action_bytes exceeds the safe integer range")
        if max_action_bytes > MAX_LLM_ACTION_BYTES:
            raise ValueError(
                "max_action_bytes exceeds the logged LLM profile limit of %d"
                % MAX_LLM_ACTION_BYTES
            )
        if config is not None and not isinstance(config, GenerationConfig):
            raise ValueError("config must be GenerationConfig or None")
        if not callable(getattr(backend, "generate", None)):
            raise ValueError("backend must provide a callable generate method")
        if event_sink is not None and not callable(event_sink):
            raise ValueError("event_sink must be callable or None")
        self._backend = backend
        self._config = GenerationConfig() if config is None else config
        self._max_repair_attempts = max_repair_attempts
        self._max_action_bytes = max_action_bytes
        self._event_sink = event_sink
        self._player_turns = 0
        self._generation_calls = 0
        self._primary_calls = 0
        self._repair_calls = 0
        self._first_pass_valid = 0
        self._decoded_actions = 0
        self._input_tokens = 0
        self._output_tokens = 0
        self._input_usage_complete = True
        self._output_usage_complete = True

    @property
    def run_config(self) -> Mapping[str, Any]:
        """Return the adapter settings needed to reconstruct this run."""

        return {
            "evaluation_profile": DEVELOPMENT_EVALUATION_PROFILE,
            "action_schema": PLAYER_ACTION_SCHEMA,
            "generation_config": generation_config_to_payload(self._config),
            "max_action_bytes": self._max_action_bytes,
            "max_repair_attempts": self._max_repair_attempts,
            "generation_policy": (
                "plain_text_no_regeneration"
                if self._max_repair_attempts == 0
                else "plain_text_one_schema_directed_regeneration"
            ),
        }

    @property
    def stats(self) -> LLMPlayerStats:
        return LLMPlayerStats(
            player_turns=self._player_turns,
            primary_calls=self._primary_calls,
            repair_calls=self._repair_calls,
            first_pass_valid_actions=self._first_pass_valid,
            decoded_actions=self._decoded_actions,
            input_tokens=(self._input_tokens if self._input_usage_complete else None),
            output_tokens=(
                self._output_tokens if self._output_usage_complete else None
            ),
        )

    def _emit(self, event_type: str, payload: Mapping[str, Any]) -> None:
        if self._event_sink is not None:
            self._event_sink(event_type, payload)

    def _generate(
        self,
        request: GenerationRequest,
        *,
        player_turn: int,
        purpose: str,
    ) -> Tuple[GenerationResponse, int]:
        self._generation_calls += 1
        call_index = self._generation_calls
        if purpose == "next_action":
            self._primary_calls += 1
        else:
            self._repair_calls += 1
        request_payload = generation_request_to_payload(request)
        self._emit(
            "model.requested",
            {
                "call_index": call_index,
                "player_turn": player_turn,
                "purpose": purpose,
                "request": request_payload,
            },
        )
        try:
            response = self._backend.generate(request)
            if not isinstance(response, GenerationResponse):
                raise TypeError("backend must return GenerationResponse")
            if generation_request_to_payload(request) != request_payload:
                raise TypeError("backend mutated the logical generation request")
        except Exception as exc:
            self._emit(
                "model.completed",
                {
                    "call_index": call_index,
                    "player_turn": player_turn,
                    "purpose": purpose,
                    "status": "error",
                    "error": {
                        "type": type(exc).__name__,
                        "message": "provider binding failed before a valid response",
                    },
                },
            )
            raise ModelTransportError(
                "text generation backend failed: %s" % type(exc).__name__
            ) from exc

        if response.usage.input_tokens is not None:
            self._input_tokens += response.usage.input_tokens
        else:
            self._input_usage_complete = False
        if response.usage.output_tokens is not None:
            self._output_tokens += response.usage.output_tokens
        else:
            self._output_usage_complete = False

        response_bytes = response.text.encode("utf-8")
        if len(response_bytes) > self._max_action_bytes:
            wire_error = WireDecodeError(
                "payload_too_large",
                "$",
                "JSON input exceeds %d bytes" % self._max_action_bytes,
            )
            self._emit(
                "model.completed",
                {
                    "call_index": call_index,
                    "player_turn": player_turn,
                    "purpose": purpose,
                    "status": "output_rejected",
                    "response_summary": {
                        "provider": response.provider,
                        "model": response.model,
                        "finish_reason": response.finish_reason,
                        "response_id": response.response_id,
                        "usage": {
                            "input_tokens": response.usage.input_tokens,
                            "output_tokens": response.usage.output_tokens,
                        },
                        "text_bytes": len(response_bytes),
                        "text_omitted": True,
                    },
                    "wire_error": {
                        "code": wire_error.code,
                        "path": wire_error.path,
                        "message": wire_error.detail,
                    },
                },
            )
            raise AdapterOutputError(
                wire_error, attempts=1 if purpose == "next_action" else 2
            ) from wire_error

        try:
            response_payload = generation_response_to_payload(response)
        except Exception as exc:
            self._emit(
                "model.completed",
                {
                    "call_index": call_index,
                    "player_turn": player_turn,
                    "purpose": purpose,
                    "status": "error",
                    "error": {
                        "type": type(exc).__name__,
                        "message": "provider response violated the adapter contract",
                    },
                },
            )
            raise ModelTransportError(
                "text generation response failed validation: %s"
                % type(exc).__name__
            ) from exc
        self._emit(
            "model.completed",
            {
                "call_index": call_index,
                "player_turn": player_turn,
                "purpose": purpose,
                "status": "ok",
                "response": response_payload,
            },
        )
        return response, call_index

    def _parse(
        self,
        response: GenerationResponse,
        *,
        player_turn: int,
        call_index: int,
        repair_attempt: int,
    ) -> PlayerAction:
        try:
            action = player_action_from_json(
                response.text, max_bytes=self._max_action_bytes
            )
        except WireDecodeError as exc:
            self._emit(
                "action.parse_failed",
                {
                    "call_index": call_index,
                    "player_turn": player_turn,
                    "repair_attempt": repair_attempt,
                    "wire_error": {
                        "code": exc.code,
                        "path": exc.path,
                        "message": exc.detail,
                    },
                },
            )
            raise
        action_payload = player_action_to_payload(action)
        self._emit(
            "action.parsed",
            {
                "call_index": call_index,
                "player_turn": player_turn,
                "repair_attempt": repair_attempt,
                "action": action_payload,
            },
        )
        return action

    def next_action(self, view: EpisodeView) -> PlayerAction:
        self._player_turns += 1
        player_turn = self._player_turns
        request = build_generation_request(
            view,
            player_turn=player_turn,
            config=self._config,
            purpose="next_action",
        )
        response, call_index = self._generate(
            request, player_turn=player_turn, purpose="next_action"
        )
        try:
            action = self._parse(
                response,
                player_turn=player_turn,
                call_index=call_index,
                repair_attempt=0,
            )
        except WireDecodeError as first_error:
            # Inputs that hit structural safety limits are not copied into a
            # second prompt.  This keeps the optional second call bounded by
            # the same public action limit instead of amplifying hostile text.
            if self._max_repair_attempts == 0 or first_error.code in {
                "payload_too_large",
                "too_deep",
                "too_many_values",
                "invalid_unicode",
            }:
                raise AdapterOutputError(first_error, attempts=1) from first_error
            repair_request = build_generation_request(
                view,
                player_turn=player_turn,
                config=self._config,
                purpose="repair_action",
                invalid_output=response.text,
                wire_error=first_error,
            )
            repaired_response, repair_call_index = self._generate(
                repair_request,
                player_turn=player_turn,
                purpose="repair_action",
            )
            try:
                action = self._parse(
                    repaired_response,
                    player_turn=player_turn,
                    call_index=repair_call_index,
                    repair_attempt=1,
                )
            except WireDecodeError as repair_error:
                raise AdapterOutputError(repair_error, attempts=2) from repair_error
        else:
            self._first_pass_valid += 1
        self._decoded_actions += 1
        return action


__all__ = [
    "AdapterOutputError",
    "DEVELOPMENT_EVALUATION_PROFILE",
    "GenerationConfig",
    "GenerationRequest",
    "GenerationResponse",
    "LLMAdapterError",
    "LLMPlayerBackend",
    "LLMPlayerStats",
    "MAX_LLM_ACTION_BYTES",
    "Message",
    "ModelTransportError",
    "TextGenerationBackend",
    "TokenUsage",
    "build_generation_request",
    "generation_request_to_payload",
    "generation_response_to_payload",
    "generation_config_to_payload",
]
