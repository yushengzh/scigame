"""Truth-grounded LLM presentation layer for the Oracle role.

The language model never creates or rewrites experimental evidence.
``CaseOracle`` first validates the proposal and obtains the authoritative
response from the private WorldModel.  The model is still called as the Oracle
backend, but its decoded ``message`` must exactly copy the authoritative
``CaseOracle.message``.  Status, message, measurements, units, uncertainty, and
budget semantics therefore all remain authoritative.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Optional

from .llm import (
    DEVELOPMENT_EVALUATION_PROFILE,
    GenerationConfig,
    GenerationRequest,
    GenerationResponse,
    Message,
    ModelTransportError,
    _safe_transport_failure_detail,
    TextGenerationBackend,
    generation_config_to_payload,
    generation_request_to_payload,
    generation_response_to_payload,
)
from .models import CaseDefinition, ExperimentProposal, OracleResponse
from .protocols import CaseOracle, WorldModel
from .wire import (
    WireDecodeError,
    canonical_json_dumps,
    case_definition_to_payload,
    experiment_proposal_to_payload,
    oracle_response_to_payload,
    strict_json_loads,
)
from .llm import validate_generation_completion


ORACLE_MESSAGE_SCHEMA = "role_benchmark.oracle_message"
ORACLE_PROMPT_VERSION_V1 = "role_benchmark.oracle_prompt.v1"
ORACLE_PROMPT_VERSION_V2_JSON_HARDENED = (
    "role_benchmark.oracle_prompt.v2_json_hardened"
)
DEFAULT_ORACLE_PROMPT_VERSION = ORACLE_PROMPT_VERSION_V1
MAX_LLM_ORACLE_OUTPUT_BYTES = 65_536
MAX_ORACLE_MESSAGE_CHARACTERS = 4_096
_MAX_SAFE_INTEGER = 2**53 - 1


EventSink = Callable[[str, Mapping[str, Any]], Any]


class OracleAdapterError(RuntimeError):
    """Base class for failures in the LLM Oracle presentation layer."""


class OracleOutputError(OracleAdapterError):
    """The Oracle model violated its strict output contract."""

    def __init__(self, error: WireDecodeError) -> None:
        self.wire_error = error
        super().__init__("Oracle model output is invalid: %s" % error)


@dataclass(frozen=True)
class LLMOracleStats:
    oracle_turns: int
    generation_calls: int
    parsed_messages: int
    input_tokens: Optional[int]
    output_tokens: Optional[int]


_ORACLE_MESSAGE_JSON_SCHEMA: Mapping[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "additionalProperties": False,
    "required": ["message"],
    "properties": {
        "message": {
            "type": "string",
            "minLength": 1,
            "maxLength": MAX_ORACLE_MESSAGE_CHARACTERS,
        }
    },
}


_SYSTEM_INSTRUCTION = """You are the Oracle presentation layer in a scientific benchmark.
The authoritative Oracle response in the user message is the only factual source.
Return exactly one JSON object matching the supplied schema, with no Markdown or
extra keys. Set message to an exact character-for-character copy of
authoritative_response.message. Do not paraphrase, summarize, prefix, suffix, or
otherwise rewrite it. JSON escaping may differ, but the decoded string must be
identical. Do not add measurements, infer missing facts, evaluate Player
hypotheses, or reveal hidden formulae. The benchmark runtime, not you, supplies
the authoritative status, message, and experimental evidence.
"""

_JSON_HARDENED_SYSTEM_INSTRUCTION = _SYSTEM_INSTRUCTION + """
Construct an object with exactly one key, message. Treat
authoritative_response.message as a string value and serialize it with JSON
escaping; do not manually copy already-serialized punctuation. Before
returning, verify that decoding your JSON produces a message exactly equal
character-for-character to authoritative_response.message. The first
non-whitespace character must be { and the last must be }; emit no other text.
"""


def _oracle_prompt_text(prompt_version: str) -> str:
    if prompt_version == ORACLE_PROMPT_VERSION_V1:
        return _SYSTEM_INSTRUCTION
    if prompt_version == ORACLE_PROMPT_VERSION_V2_JSON_HARDENED:
        return _JSON_HARDENED_SYSTEM_INSTRUCTION
    raise ValueError("unsupported Oracle prompt_version %r" % prompt_version)


def oracle_message_json_schema() -> Mapping[str, Any]:
    """Return a detached copy of the strict Oracle-message JSON Schema."""

    return strict_json_loads(canonical_json_dumps(_ORACLE_MESSAGE_JSON_SCHEMA))


def oracle_message_from_json(
    text: str,
    *,
    authoritative_message: str,
    max_bytes: int = MAX_LLM_ORACLE_OUTPUT_BYTES,
) -> str:
    """Decode one message and require an exact authoritative copy."""

    if not isinstance(authoritative_message, str):
        raise ValueError("authoritative_message must be a string")

    value = strict_json_loads(text, max_bytes=max_bytes)
    if not isinstance(value, dict):
        raise WireDecodeError("wrong_type", "$", "expected an object")
    if set(value) != {"message"}:
        missing = {"message"} - set(value)
        extra = set(value) - {"message"}
        if missing:
            raise WireDecodeError(
                "missing_key", "$", "missing required key: message"
            )
        raise WireDecodeError(
            "extra_key",
            "$",
            "unexpected key(s): %s" % ", ".join(sorted(str(key) for key in extra)),
        )
    message = value["message"]
    if not isinstance(message, str):
        raise WireDecodeError("wrong_type", "$.message", "expected a string")
    if not message.strip():
        raise WireDecodeError(
            "empty_string", "$.message", "message must be non-empty"
        )
    if len(message) > MAX_ORACLE_MESSAGE_CHARACTERS:
        raise WireDecodeError(
            "string_too_long",
            "$.message",
            "message exceeds %d characters" % MAX_ORACLE_MESSAGE_CHARACTERS,
        )
    if message != authoritative_message:
        raise WireDecodeError(
            "value_mismatch",
            "$.message",
            "message must exactly equal the authoritative Oracle message",
        )
    return message


def build_oracle_generation_request(
    definition: CaseDefinition,
    proposal: ExperimentProposal,
    authoritative_response: OracleResponse,
    *,
    oracle_turn: int,
    config: GenerationConfig,
    prompt_version: str = DEFAULT_ORACLE_PROMPT_VERSION,
) -> GenerationRequest:
    """Build the exact request used to present one authoritative response."""

    if isinstance(oracle_turn, bool) or not isinstance(oracle_turn, int):
        raise ValueError("oracle_turn must be an integer")
    if oracle_turn < 1 or oracle_turn > _MAX_SAFE_INTEGER:
        raise ValueError("oracle_turn must be a positive safe integer")
    if not isinstance(config, GenerationConfig):
        raise ValueError("config must be GenerationConfig")
    system_instruction = _oracle_prompt_text(prompt_version)
    schema = oracle_message_json_schema()
    schema["properties"]["message"]["const"] = authoritative_response.message
    system = (
        system_instruction
        + "\nOracle Message JSON Schema:\n"
        + canonical_json_dumps(schema)
    )
    user_payload = {
        "case": case_definition_to_payload(definition),
        "experiment_proposal": experiment_proposal_to_payload(proposal),
        "authoritative_response": oracle_response_to_payload(
            authoritative_response
        ),
    }
    metadata = {
        "message_schema": ORACLE_MESSAGE_SCHEMA,
        "evaluation_profile": DEVELOPMENT_EVALUATION_PROFILE,
        "case_id": definition.case_id,
        "oracle_turn": oracle_turn,
        "purpose": "present_authoritative_response",
    }
    # Preserve the frozen v1 request payload unless v2 is explicitly selected.
    if prompt_version != DEFAULT_ORACLE_PROMPT_VERSION:
        metadata["prompt_version"] = prompt_version
    return GenerationRequest(
        messages=(
            Message("system", system),
            Message("user", canonical_json_dumps(user_payload)),
        ),
        response_schema=schema,
        config=config,
        metadata=metadata,
    )


class LLMOracle:
    """Present ``CaseOracle`` responses through a provider-neutral text model.

    The wrapped model must return an exact JSON copy of the authoritative
    ``OracleResponse.message``.  Every visible response field is copied from an
    internal ``CaseOracle`` after its resource checks and WorldModel call have
    completed.
    """

    def __init__(
        self,
        definition: CaseDefinition,
        world_model: WorldModel,
        backend: TextGenerationBackend,
        *,
        config: Optional[GenerationConfig] = None,
        max_output_bytes: int = MAX_LLM_ORACLE_OUTPUT_BYTES,
        prompt_version: str = DEFAULT_ORACLE_PROMPT_VERSION,
        event_sink: Optional[EventSink] = None,
    ) -> None:
        if not isinstance(definition, CaseDefinition):
            raise ValueError("definition must be CaseDefinition")
        if not callable(getattr(world_model, "run", None)):
            raise ValueError("world_model must provide a callable run method")
        if not callable(getattr(backend, "generate", None)):
            raise ValueError("backend must provide a callable generate method")
        if config is not None and not isinstance(config, GenerationConfig):
            raise ValueError("config must be GenerationConfig or None")
        if isinstance(max_output_bytes, bool) or not isinstance(max_output_bytes, int):
            raise ValueError("max_output_bytes must be an integer")
        if max_output_bytes < 1 or max_output_bytes > MAX_LLM_ORACLE_OUTPUT_BYTES:
            raise ValueError(
                "max_output_bytes must be between 1 and %d"
                % MAX_LLM_ORACLE_OUTPUT_BYTES
            )
        if event_sink is not None and not callable(event_sink):
            raise ValueError("event_sink must be callable or None")
        _oracle_prompt_text(prompt_version)

        definition_snapshot = copy.deepcopy(definition)
        self._definition = definition_snapshot
        self._case_oracle = CaseOracle(definition_snapshot, world_model)
        self._backend = backend
        self._config = GenerationConfig() if config is None else config
        self._max_output_bytes = max_output_bytes
        self._prompt_version = prompt_version
        self._event_sink = event_sink
        self._oracle_turns = 0
        self._generation_calls = 0
        self._parsed_messages = 0
        self._input_tokens = 0
        self._output_tokens = 0
        self._input_usage_complete = True
        self._output_usage_complete = True

    @property
    def run_config(self) -> Mapping[str, Any]:
        run_config = {
            "evaluation_profile": DEVELOPMENT_EVALUATION_PROFILE,
            "message_schema": ORACLE_MESSAGE_SCHEMA,
            "generation_config": generation_config_to_payload(self._config),
            "max_output_bytes": self._max_output_bytes,
            "generation_policy": "authoritative_message_exact_copy_one_call",
        }
        # Existing logged-run grammars expect the frozen v1 key set.
        if self._prompt_version != DEFAULT_ORACLE_PROMPT_VERSION:
            run_config["prompt_version"] = self._prompt_version
        return run_config

    @property
    def stats(self) -> LLMOracleStats:
        return LLMOracleStats(
            oracle_turns=self._oracle_turns,
            generation_calls=self._generation_calls,
            parsed_messages=self._parsed_messages,
            input_tokens=(self._input_tokens if self._input_usage_complete else None),
            output_tokens=(
                self._output_tokens if self._output_usage_complete else None
            ),
        )

    def _emit(self, event_type: str, payload: Mapping[str, Any]) -> None:
        if self._event_sink is not None:
            self._event_sink(event_type, payload)

    def _generate(
        self, request: GenerationRequest, *, oracle_turn: int, purpose: str
    ) -> GenerationResponse:
        """One logged call, shared by presentation and semantic review."""
        request_payload = generation_request_to_payload(request)
        self._generation_calls += 1
        call_index = self._generation_calls
        event_base = {
            "call_index": call_index,
            "oracle_turn": oracle_turn,
            "purpose": purpose,
        }
        self._emit(
            "oracle.model.requested",
            {**event_base, "request": request_payload},
        )

        try:
            response = self._backend.generate(request)
            if not isinstance(response, GenerationResponse):
                raise TypeError("backend must return GenerationResponse")
            if generation_request_to_payload(request) != request_payload:
                raise TypeError("backend mutated the logical generation request")
            response_payload = generation_response_to_payload(response)
        except Exception as exc:
            failure_detail = _safe_transport_failure_detail(exc)
            self._emit(
                "oracle.model.completed",
                {
                    **event_base,
                    "status": "error",
                    "error": {
                        "type": type(exc).__name__,
                        "message": (
                            "provider binding failed before a valid response: %s"
                            % failure_detail
                        ),
                    },
                },
            )
            raise ModelTransportError(
                "Oracle text generation backend failed: %s" % failure_detail
            ) from exc

        if response.usage.input_tokens is None:
            self._input_usage_complete = False
        else:
            self._input_tokens += response.usage.input_tokens
        if response.usage.output_tokens is None:
            self._output_usage_complete = False
        else:
            self._output_tokens += response.usage.output_tokens

        # Record the complete observable completion before attempting to parse
        # it so malformed model output is retained in the same JSONL stream.
        self._emit(
            "oracle.model.completed",
            {**event_base, "status": "ok", "response": response_payload},
        )
        return response

    def respond(self, proposal: ExperimentProposal) -> OracleResponse:
        if not isinstance(proposal, ExperimentProposal):
            raise ValueError("proposal must be ExperimentProposal")
        self._oracle_turns += 1
        oracle_turn = self._oracle_turns
        authoritative = self._case_oracle.respond(copy.deepcopy(proposal))
        request = build_oracle_generation_request(
            self._definition, proposal, authoritative, oracle_turn=oracle_turn,
            config=self._config, prompt_version=self._prompt_version,
        )
        response = self._generate(
            request, oracle_turn=oracle_turn, purpose="present_authoritative_response"
        )
        call_index = self._generation_calls
        try:
            validate_generation_completion(response)
            oracle_message_from_json(
                response.text,
                authoritative_message=authoritative.message,
                max_bytes=self._max_output_bytes,
            )
        except WireDecodeError as exc:
            self._emit(
                (
                    "oracle.output.validation_failed"
                    if exc.code == "value_mismatch"
                    else "oracle.output.parse_failed"
                ),
                {
                    "call_index": call_index,
                    "oracle_turn": oracle_turn,
                    "wire_error": {
                        "code": exc.code,
                        "path": exc.path,
                        "message": exc.detail,
                    },
                },
            )
            raise OracleOutputError(exc) from exc

        # The decoded message has now been checked for exact equality.  Copy the
        # authoritative object so no model-owned value enters Player evidence.
        visible_response = copy.deepcopy(authoritative)
        self._parsed_messages += 1
        self._emit(
            "oracle.output.parsed",
            {
                "call_index": call_index,
                "oracle_turn": oracle_turn,
                "oracle_response": oracle_response_to_payload(visible_response),
            },
        )
        return visible_response


__all__ = [
    "DEFAULT_ORACLE_PROMPT_VERSION",
    "LLMOracle",
    "LLMOracleStats",
    "MAX_LLM_ORACLE_OUTPUT_BYTES",
    "MAX_ORACLE_MESSAGE_CHARACTERS",
    "ORACLE_MESSAGE_SCHEMA",
    "ORACLE_PROMPT_VERSION_V1",
    "ORACLE_PROMPT_VERSION_V2_JSON_HARDENED",
    "OracleAdapterError",
    "OracleOutputError",
    "build_oracle_generation_request",
    "oracle_message_from_json",
    "oracle_message_json_schema",
]
