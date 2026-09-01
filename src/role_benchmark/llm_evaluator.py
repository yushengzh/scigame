"""Post-hoc LLM evaluation of a completed observable episode transcript.

The case-owned ``FinalEvaluator`` remains the authoritative scientific scorer.
This module adds separately named, exploratory process/result ratings after the
Player--Oracle interaction has ended.  It never changes ``predictive_model_pass``
or ``active_pass`` and it never requires hidden chain-of-thought.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Any, Dict, Mapping, Optional, Sequence, Tuple

from .llm import (
    DEVELOPMENT_EVALUATION_PROFILE,
    GenerationConfig,
    GenerationRequest,
    GenerationResponse,
    Message,
    TextGenerationBackend,
    generation_request_to_payload,
)
from .runlog import LoadedRunLog
from .wire import WireDecodeError, canonical_json_dumps, strict_json_loads


LLM_EVALUATION_SCHEMA = "role_benchmark.llm_transcript_evaluation"
MAX_LLM_EVALUATION_OUTPUT_BYTES = 262_144
MAX_EVALUATOR_SUMMARY_CHARACTERS = 4_096
MAX_FINDING_MESSAGE_CHARACTERS = 2_048
MAX_FINDINGS = 32

EVALUATOR_SCORE_AXES: Tuple[str, ...] = (
    "experiment_design",
    "evidence_use",
    "hypothesis_revision",
    "stopping_decision",
    "claim_evidence_consistency",
    "explanation_quality",
)

EVALUATOR_FINDING_STAGES: Tuple[str, ...] = (
    "action_generation",
    "experiment_design",
    "evidence_interpretation",
    "belief_update",
    "stopping_decision",
    "final_synthesis",
    "protocol",
)

_INCLUDED_EVENT_TYPES = frozenset(
    (
        "run.started",
        "model.completed",
        "action.parse_failed",
        "action.decoded",
        "protocol.transition",
        "episode.terminal",
        "run.ended",
    )
)

_FINDING_CODE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")

_SCORE_SCHEMA: Mapping[str, Any] = {
    "anyOf": [
        {"type": "number", "minimum": 0.0, "maximum": 1.0},
        {"type": "null"},
    ]
}

_LLM_EVALUATION_JSON_SCHEMA: Mapping[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "additionalProperties": False,
    "required": ["scores", "findings", "summary"],
    "properties": {
        "scores": {
            "type": "object",
            "additionalProperties": False,
            "required": list(EVALUATOR_SCORE_AXES),
            "properties": {
                axis: dict(_SCORE_SCHEMA) for axis in EVALUATOR_SCORE_AXES
            },
        },
        "findings": {
            "type": "array",
            "maxItems": MAX_FINDINGS,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "code",
                    "stage",
                    "action_index",
                    "message",
                    "event_sequences",
                ],
                "properties": {
                    "code": {
                        "type": "string",
                        "pattern": "^[a-z][a-z0-9_]{0,63}$",
                    },
                    "stage": {"enum": list(EVALUATOR_FINDING_STAGES)},
                    "action_index": {
                        "anyOf": [
                            {"type": "integer", "minimum": 1},
                            {"type": "null"},
                        ]
                    },
                    "message": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": MAX_FINDING_MESSAGE_CHARACTERS,
                    },
                    "event_sequences": {
                        "type": "array",
                        "uniqueItems": True,
                        "items": {"type": "integer", "minimum": 0},
                    },
                },
            },
        },
        "summary": {
            "type": "string",
            "minLength": 1,
            "maxLength": MAX_EVALUATOR_SUMMARY_CHARACTERS,
        },
    },
}

_SYSTEM_INSTRUCTION = """You are a post-hoc evaluator of an interactive scientific benchmark.
The Player--Oracle episode is already complete. Score only the observable record
provided by the user; never infer or request hidden chain-of-thought. The
case-owned deterministic predictive evaluation is authoritative scientific
ground truth. Your ratings are separate diagnostics and must not replace,
average with, or reinterpret predictive_model_pass or active_pass.

For each axis return a number in [0,1], or null when the observable record is
insufficient to score it:
- experiment_design: whether requested experiments were relevant and discriminative;
- evidence_use: whether conclusions tracked the returned evidence;
- hypothesis_revision: whether support changed appropriately after evidence;
- stopping_decision: whether finalization or termination was justified by the record;
- claim_evidence_consistency: whether the final claim, if any, matches observed evidence;
- explanation_quality: whether the submitted explanation, if any, is concise and faithful.

Findings must identify concrete observable errors and cite sequence numbers from
the supplied transcript. Return exactly one JSON object matching the schema,
with no Markdown, hidden reasoning, overall score, pass/fail field, or extra keys.
"""


class LLMEvaluatorError(RuntimeError):
    """Base class for post-hoc evaluator failures."""


class LLMEvaluatorCallError(LLMEvaluatorError):
    """A failed call with its non-secret logical request and optional response."""

    def __init__(
        self,
        message: str,
        *,
        request: GenerationRequest,
        response: Optional[GenerationResponse] = None,
    ) -> None:
        self.request = request
        self.response = response
        super().__init__(message)


class LLMEvaluatorTransportError(LLMEvaluatorCallError):
    """The evaluator provider failed before a decodable response was produced."""


class LLMEvaluatorOutputError(LLMEvaluatorCallError):
    """The evaluator returned text outside its strict result schema."""

    def __init__(
        self,
        error: WireDecodeError,
        *,
        request: GenerationRequest,
        response: GenerationResponse,
    ) -> None:
        self.wire_error = error
        super().__init__(
            "LLM evaluator output is invalid: %s" % error,
            request=request,
            response=response,
        )


@dataclass(frozen=True)
class LLMEvaluatorFinding:
    code: str
    stage: str
    action_index: Optional[int]
    message: str
    event_sequences: Tuple[int, ...]


@dataclass(frozen=True)
class LLMTranscriptEvaluation:
    scores: Mapping[str, Optional[float]]
    findings: Tuple[LLMEvaluatorFinding, ...]
    summary: str


@dataclass(frozen=True)
class LLMEvaluatorRun:
    request: GenerationRequest
    response: GenerationResponse
    evaluation: LLMTranscriptEvaluation


def llm_evaluation_json_schema() -> Mapping[str, Any]:
    """Return a detached copy of the evaluator's strict JSON Schema."""

    return strict_json_loads(canonical_json_dumps(_LLM_EVALUATION_JSON_SCHEMA))


def _wire_error(code: str, path: str, detail: str) -> WireDecodeError:
    return WireDecodeError(code, path, detail)


def _exact_keys(
    value: Mapping[str, Any],
    expected: Sequence[str],
    path: str,
) -> None:
    expected_set = set(expected)
    actual = set(value)
    missing = expected_set - actual
    extra = actual - expected_set
    if missing:
        raise _wire_error(
            "missing_key",
            path,
            "missing required key(s): %s" % ", ".join(sorted(missing)),
        )
    if extra:
        raise _wire_error(
            "extra_key",
            path,
            "unexpected key(s): %s" % ", ".join(sorted(str(key) for key in extra)),
        )


def _bounded_text(value: Any, path: str, maximum: int) -> str:
    if not isinstance(value, str):
        raise _wire_error("wrong_type", path, "expected a string")
    if not value.strip():
        raise _wire_error("empty_string", path, "text must be non-empty")
    if len(value) > maximum:
        raise _wire_error(
            "string_too_long", path, "text exceeds %d characters" % maximum
        )
    return value


def llm_evaluation_from_json(
    text: str,
    *,
    max_bytes: int = MAX_LLM_EVALUATION_OUTPUT_BYTES,
) -> LLMTranscriptEvaluation:
    """Strictly decode one post-hoc evaluator result."""

    value = strict_json_loads(text, max_bytes=max_bytes)
    if not isinstance(value, dict):
        raise _wire_error("wrong_type", "$", "expected an object")
    _exact_keys(value, ("scores", "findings", "summary"), "$")

    score_payload = value["scores"]
    if not isinstance(score_payload, dict):
        raise _wire_error("wrong_type", "$.scores", "expected an object")
    _exact_keys(score_payload, EVALUATOR_SCORE_AXES, "$.scores")
    scores: Dict[str, Optional[float]] = {}
    for axis in EVALUATOR_SCORE_AXES:
        raw = score_payload[axis]
        path = "$.scores.%s" % axis
        if raw is None:
            scores[axis] = None
            continue
        if isinstance(raw, bool) or not isinstance(raw, (int, float)):
            raise _wire_error("wrong_type", path, "expected a number or null")
        numeric = float(raw)
        if not math.isfinite(numeric):
            raise _wire_error("non_finite_number", path, "score must be finite")
        if numeric < 0.0 or numeric > 1.0:
            raise _wire_error("number_out_of_range", path, "score must be in [0,1]")
        scores[axis] = numeric

    finding_payload = value["findings"]
    if not isinstance(finding_payload, list):
        raise _wire_error("wrong_type", "$.findings", "expected an array")
    if len(finding_payload) > MAX_FINDINGS:
        raise _wire_error(
            "array_too_long", "$.findings", "at most %d findings are allowed" % MAX_FINDINGS
        )
    findings = []
    required = ("code", "stage", "action_index", "message", "event_sequences")
    for index, item in enumerate(finding_payload):
        path = "$.findings[%d]" % index
        if not isinstance(item, dict):
            raise _wire_error("wrong_type", path, "expected an object")
        _exact_keys(item, required, path)
        code = _bounded_text(item["code"], path + ".code", 64)
        if _FINDING_CODE.fullmatch(code) is None:
            raise _wire_error(
                "invalid_value", path + ".code", "code must be lower snake_case"
            )
        stage = item["stage"]
        if stage not in EVALUATOR_FINDING_STAGES:
            raise _wire_error(
                "invalid_value", path + ".stage", "unsupported finding stage"
            )
        action_index = item["action_index"]
        if action_index is not None and (
            isinstance(action_index, bool)
            or not isinstance(action_index, int)
            or action_index < 1
        ):
            raise _wire_error(
                "invalid_value",
                path + ".action_index",
                "action_index must be a positive integer or null",
            )
        message = _bounded_text(
            item["message"], path + ".message", MAX_FINDING_MESSAGE_CHARACTERS
        )
        sequences = item["event_sequences"]
        if not isinstance(sequences, list):
            raise _wire_error(
                "wrong_type", path + ".event_sequences", "expected an array"
            )
        if any(
            isinstance(sequence, bool)
            or not isinstance(sequence, int)
            or sequence < 0
            for sequence in sequences
        ):
            raise _wire_error(
                "invalid_value",
                path + ".event_sequences",
                "event sequences must be non-negative integers",
            )
        if len(set(sequences)) != len(sequences):
            raise _wire_error(
                "duplicate_value",
                path + ".event_sequences",
                "event sequences must be unique",
            )
        findings.append(
            LLMEvaluatorFinding(
                code=code,
                stage=str(stage),
                action_index=action_index,
                message=message,
                event_sequences=tuple(sequences),
            )
        )

    summary = _bounded_text(
        value["summary"], "$.summary", MAX_EVALUATOR_SUMMARY_CHARACTERS
    )
    return LLMTranscriptEvaluation(
        scores=scores,
        findings=tuple(findings),
        summary=summary,
    )


def evaluator_transcript_projection(log: LoadedRunLog) -> Mapping[str, Any]:
    """Project one sealed log onto the observable evidence needed by the Judge."""

    if not isinstance(log, LoadedRunLog):
        raise ValueError("log must be a LoadedRunLog")
    if not log.complete:
        raise ValueError("LLM evaluation requires a complete sealed run log")
    projected = []
    for event in log.events:
        event_type = event.get("event_type")
        if event_type not in _INCLUDED_EVENT_TYPES:
            continue
        sequence = event.get("sequence")
        payload = event.get("payload")
        if isinstance(sequence, bool) or not isinstance(sequence, int) or sequence < 0:
            raise ValueError("run log contains an invalid event sequence")
        if not isinstance(payload, Mapping):
            raise ValueError("run log contains an invalid event payload")
        projected.append(
            {
                "sequence": sequence,
                "event_type": event_type,
                "payload": strict_json_loads(canonical_json_dumps(payload)),
            }
        )
    if not projected or projected[0]["event_type"] != "run.started":
        raise ValueError("run log projection must start with run.started")
    if projected[-1]["event_type"] != "run.ended":
        raise ValueError("run log projection must end with run.ended")
    return {
        "run_id": log.run_id,
        "observable_transcript": projected,
    }


def build_evaluator_generation_request(
    log: LoadedRunLog,
    *,
    config: GenerationConfig,
) -> GenerationRequest:
    """Build the exact one-call request for post-hoc transcript evaluation."""

    if not isinstance(config, GenerationConfig):
        raise ValueError("config must be GenerationConfig")
    schema = llm_evaluation_json_schema()
    projection = evaluator_transcript_projection(log)
    system = _SYSTEM_INSTRUCTION + "\nEvaluator JSON Schema:\n" + canonical_json_dumps(
        schema
    )
    return GenerationRequest(
        messages=(
            Message("system", system),
            Message("user", canonical_json_dumps(projection)),
        ),
        response_schema=schema,
        config=config,
        metadata={
            "evaluation_schema": LLM_EVALUATION_SCHEMA,
            "evaluation_profile": DEVELOPMENT_EVALUATION_PROFILE,
            "run_id": log.run_id,
            "purpose": "post_hoc_transcript_evaluation",
        },
    )


def llm_evaluation_to_payload(
    evaluation: LLMTranscriptEvaluation,
) -> Mapping[str, Any]:
    return {
        "scores": dict(evaluation.scores),
        "findings": [
            {
                "code": finding.code,
                "stage": finding.stage,
                "action_index": finding.action_index,
                "message": finding.message,
                "event_sequences": list(finding.event_sequences),
            }
            for finding in evaluation.findings
        ],
        "summary": evaluation.summary,
    }


class PostHocLLMEvaluator:
    """Run one strict generation over a completed observable transcript."""

    def __init__(
        self,
        backend: TextGenerationBackend,
        *,
        config: Optional[GenerationConfig] = None,
        max_output_bytes: int = MAX_LLM_EVALUATION_OUTPUT_BYTES,
    ) -> None:
        if not callable(getattr(backend, "generate", None)):
            raise ValueError("backend must provide a callable generate method")
        if config is not None and not isinstance(config, GenerationConfig):
            raise ValueError("config must be GenerationConfig or None")
        if (
            isinstance(max_output_bytes, bool)
            or not isinstance(max_output_bytes, int)
            or max_output_bytes < 1
            or max_output_bytes > MAX_LLM_EVALUATION_OUTPUT_BYTES
        ):
            raise ValueError(
                "max_output_bytes must be between 1 and %d"
                % MAX_LLM_EVALUATION_OUTPUT_BYTES
            )
        self._backend = backend
        self._config = GenerationConfig() if config is None else config
        self._max_output_bytes = max_output_bytes

    def evaluate(self, log: LoadedRunLog) -> LLMEvaluatorRun:
        request = build_evaluator_generation_request(log, config=self._config)
        request_payload = generation_request_to_payload(request)
        try:
            response = self._backend.generate(request)
        except Exception as exc:
            raise LLMEvaluatorTransportError(
                "LLM evaluator backend failed: %s" % type(exc).__name__,
                request=request,
            ) from exc
        if not isinstance(response, GenerationResponse):
            raise LLMEvaluatorTransportError(
                "LLM evaluator backend returned an invalid response object",
                request=request,
            )
        if generation_request_to_payload(request) != request_payload:
            raise LLMEvaluatorTransportError(
                "LLM evaluator backend mutated the logical request",
                request=request,
                response=response,
            )
        try:
            evaluation = llm_evaluation_from_json(
                response.text,
                max_bytes=self._max_output_bytes,
            )
        except WireDecodeError as exc:
            raise LLMEvaluatorOutputError(
                exc,
                request=request,
                response=response,
            ) from exc

        available_sequences = {
            item["sequence"]
            for item in evaluator_transcript_projection(log)["observable_transcript"]
        }
        for finding_index, finding in enumerate(evaluation.findings):
            unknown = set(finding.event_sequences) - available_sequences
            if unknown:
                error = _wire_error(
                    "unknown_reference",
                    "$.findings[%d].event_sequences" % finding_index,
                    "unknown event sequence(s): %s"
                    % ", ".join(str(value) for value in sorted(unknown)),
                )
                raise LLMEvaluatorOutputError(
                    error,
                    request=request,
                    response=response,
                )
        return LLMEvaluatorRun(
            request=request,
            response=response,
            evaluation=evaluation,
        )


__all__ = [
    "EVALUATOR_FINDING_STAGES",
    "EVALUATOR_SCORE_AXES",
    "LLM_EVALUATION_SCHEMA",
    "LLMEvaluatorError",
    "LLMEvaluatorCallError",
    "LLMEvaluatorFinding",
    "LLMEvaluatorOutputError",
    "LLMEvaluatorTransportError",
    "LLMEvaluatorRun",
    "LLMTranscriptEvaluation",
    "MAX_LLM_EVALUATION_OUTPUT_BYTES",
    "PostHocLLMEvaluator",
    "build_evaluator_generation_request",
    "evaluator_transcript_projection",
    "llm_evaluation_from_json",
    "llm_evaluation_json_schema",
    "llm_evaluation_to_payload",
]
