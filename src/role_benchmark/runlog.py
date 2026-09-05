"""Plain JSONL development logs and behavioral runtime re-execution."""

from __future__ import annotations

import datetime as _datetime
import copy
import os
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, Mapping, Optional, Sequence, Tuple

from .episode import Episode, EpisodeProtocolError
from .llm import (
    AdapterOutputError,
    DEFAULT_PLAYER_PROMPT_VERSION,
    DEVELOPMENT_EVALUATION_PROFILE,
    GenerationConfig,
    GenerationResponse,
    LLMPlayerBackend,
    LLMPlayerStats,
    MAX_LLM_ACTION_BYTES,
    ModelTransportError,
    PLAYER_PROMPT_VERSION_V1,
    PLAYER_PROMPT_VERSION_V2_JSON_HARDENED,
    PLAYER_PROMPT_VERSION_V3_CASE_BOUND_JSON,
    PLAYER_REPAIR_PROMPT_VERSION_V2_JSON_HARDENED,
    PLAYER_REPAIR_PROMPT_VERSION_V3_CASE_BOUND_JSON,
    TextGenerationBackend,
    TokenUsage,
    build_generation_request,
    generation_request_to_payload,
    generation_response_to_payload,
)
from .llm_oracle import (
    DEFAULT_ORACLE_PROMPT_VERSION,
    LLMOracle,
    LLMOracleStats,
    ORACLE_MESSAGE_SCHEMA,
    ORACLE_PROMPT_VERSION_V1,
    ORACLE_PROMPT_VERSION_V2_JSON_HARDENED,
    OracleOutputError,
    build_oracle_generation_request,
    oracle_message_from_json,
)
from .models import (
    EpisodeOutcome,
    EpisodeResult,
    EpisodeTermination,
    ExperimentProposal,
    OracleResponse,
    PlayerAction,
    TerminationKind,
)
from .protocols import BenchmarkCase, CaseOracle, Oracle, PlayerBackend
from .wire import (
    DEFAULT_MAX_ACTION_BYTES,
    PLAYER_ACTION_SCHEMA,
    WireDecodeError,
    canonical_json_dumps,
    case_definition_to_payload,
    evaluation_result_to_payload,
    oracle_response_to_payload,
    player_action_from_json,
    player_action_from_payload,
    player_action_to_payload,
    strict_json_loads,
)


_MAX_EVENT_BYTES = 4_194_304


class RunLogError(RuntimeError):
    """Base class for log write, format, or replay failures."""


class RunLogFormatError(RunLogError):
    """A JSONL event is truncated, malformed, or out of sequence."""


class RunReplayError(RunLogError):
    """A loaded log cannot reproduce its parser or supplied runtime behavior."""


def _utc_now() -> str:
    return (
        _datetime.datetime.now(_datetime.timezone.utc)
        .isoformat(timespec="microseconds")
        .replace("+00:00", "Z")
    )


@dataclass(frozen=True)
class LoadedRunLog:
    run_id: str
    events: Tuple[Mapping[str, Any], ...]
    complete: bool


@dataclass(frozen=True)
class ReplayReport:
    run_id: str
    event_count: int
    action_count: int
    parser_actions_checked: int
    failed_parses_checked: int
    format_regenerations_checked: int
    prompt_requests_checked: int
    outcome: EpisodeOutcome

    @property
    def result(self) -> EpisodeResult:
        """Return the committed result for a submitted outcome."""

        return _episode_result_from_outcome(self.outcome)


@dataclass(frozen=True)
class LoggedEpisodeRun:
    run_id: str
    outcome: EpisodeOutcome
    log_path: str
    llm_stats: LLMPlayerStats
    oracle_llm_stats: Optional[LLMOracleStats]

    @property
    def result(self) -> EpisodeResult:
        """Return the committed result for a submitted outcome."""

        return _episode_result_from_outcome(self.outcome)


def _episode_result_from_outcome(outcome: EpisodeOutcome) -> EpisodeResult:
    if outcome.termination.kind != TerminationKind.SUBMITTED:
        raise EpisodeProtocolError(
            "episode has no committed final submission",
            code="no_committed_final_submission",
        )
    if outcome.final_portfolio is None or outcome.final_submission is None:
        raise RunLogError("submitted outcome is missing its committed final")
    return copy.deepcopy(EpisodeResult(
        case_id=outcome.case_id,
        track=outcome.track,
        attempts_used=outcome.attempts_used,
        turns=outcome.turns,
        final_portfolio=outcome.final_portfolio,
        final_submission=outcome.final_submission,
        evaluation=outcome.evaluation,
        trajectory_scores=outcome.trajectory_scores,
        protocol_violations=outcome.protocol_violations,
    ))


class JSONLRunLog:
    """Exclusive-create, append-only writer for one run."""

    def __init__(
        self,
        path: str,
        *,
        run_id: str,
        clock: Callable[[], str] = _utc_now,
        durable: bool = False,
    ) -> None:
        if not isinstance(run_id, str) or not run_id.strip():
            raise ValueError("run_id must be non-empty text")
        self.path = str(Path(path).resolve())
        self.run_id = run_id
        self._clock = clock
        self._durable = durable
        self._stream = open(self.path, "x", encoding="utf-8", newline="\n")
        self._event_count = 0
        self._sealed = False
        self._closed = False

    @property
    def event_count(self) -> int:
        return self._event_count

    @property
    def durable(self) -> bool:
        return self._durable

    def append(self, event_type: str, payload: Mapping[str, Any]) -> None:
        if self._closed:
            raise RunLogError("cannot append to a closed log")
        if self._sealed:
            raise RunLogError("cannot append after run.ended")
        if not isinstance(event_type, str) or not event_type.strip():
            raise ValueError("event_type must be non-empty text")
        if not isinstance(payload, Mapping):
            raise ValueError("event payload must be a mapping")
        body: Dict[str, Any] = {
            "run_id": self.run_id,
            "sequence": self._event_count,
            "event_type": event_type,
            "recorded_at": self._clock(),
            "payload": payload,
        }
        if not isinstance(body["recorded_at"], str) or not body["recorded_at"]:
            raise RunLogError("clock must return a non-empty timestamp string")
        line = canonical_json_dumps(body)
        if len(line.encode("utf-8")) > _MAX_EVENT_BYTES:
            raise RunLogError("event exceeds %d bytes" % _MAX_EVENT_BYTES)
        self._stream.write(line + "\n")
        self._stream.flush()
        if self._durable:
            os.fsync(self._stream.fileno())
        self._event_count += 1
        if event_type == "run.ended":
            self._sealed = True

    def close(self) -> None:
        if not self._closed:
            self._stream.close()
            self._closed = True

    def __enter__(self) -> "JSONLRunLog":
        return self

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        self.close()


def load_run_log(path: str) -> LoadedRunLog:
    """Load strict canonical JSONL and validate its envelope and ordering."""

    raw = Path(path).read_bytes()
    if not raw:
        raise RunLogFormatError("log is empty")
    if not raw.endswith(b"\n"):
        raise RunLogFormatError("log is truncated: final newline is missing")
    lines = raw.splitlines()
    events = []
    run_id: Optional[str] = None
    sealed = False
    required_keys = {
        "run_id",
        "sequence",
        "event_type",
        "recorded_at",
        "payload",
    }
    for sequence, raw_line in enumerate(lines):
        if not raw_line:
            raise RunLogFormatError("blank event at sequence %d" % sequence)
        if len(raw_line) > _MAX_EVENT_BYTES:
            raise RunLogFormatError("event %d exceeds size limit" % sequence)
        try:
            text = raw_line.decode("utf-8")
            event = strict_json_loads(text, max_bytes=_MAX_EVENT_BYTES)
        except (UnicodeDecodeError, WireDecodeError) as exc:
            raise RunLogFormatError(
                "event %d is not strict UTF-8 JSON: %s" % (sequence, exc)
            ) from exc
        if not isinstance(event, dict) or set(event) != required_keys:
            raise RunLogFormatError(
                "event %d has an invalid envelope" % sequence
            )
        if canonical_json_dumps(event) != text:
            raise RunLogFormatError("event %d is not canonical JSON" % sequence)
        if isinstance(event["sequence"], bool) or not isinstance(
            event["sequence"], int
        ):
            raise RunLogFormatError("event %d has an invalid sequence type" % sequence)
        if event["sequence"] != sequence:
            raise RunLogFormatError("event sequence is not contiguous")
        if not isinstance(event["run_id"], str) or not event["run_id"]:
            raise RunLogFormatError("event %d has an invalid run_id" % sequence)
        if run_id is None:
            run_id = event["run_id"]
        elif event["run_id"] != run_id:
            raise RunLogFormatError("run_id changes at event %d" % sequence)
        if not isinstance(event["event_type"], str) or not event["event_type"]:
            raise RunLogFormatError("event %d has an invalid event_type" % sequence)
        if not isinstance(event["recorded_at"], str) or not event["recorded_at"]:
            raise RunLogFormatError("event %d has an invalid timestamp" % sequence)
        if not isinstance(event["payload"], dict):
            raise RunLogFormatError("event %d payload must be an object" % sequence)
        if sealed:
            raise RunLogFormatError("event appears after run.ended")
        if event["event_type"] == "run.ended":
            sealed = True
        events.append(event)
    if run_id is None:
        raise RunLogFormatError("log contains no valid event")
    if events[0]["event_type"] != "run.started":
        raise RunLogFormatError("first event must be run.started")
    if sum(event["event_type"] == "run.started" for event in events) != 1:
        raise RunLogFormatError("log must contain exactly one run.started")
    return LoadedRunLog(
        run_id=run_id,
        events=tuple(events),
        complete=sealed,
    )


def _llm_stats_payload(player: PlayerBackend) -> Optional[Mapping[str, Any]]:
    if not isinstance(player, LLMPlayerBackend):
        return None
    stats = player.stats
    return {
        "player_turns": stats.player_turns,
        "primary_calls": stats.primary_calls,
        "repair_calls": stats.repair_calls,
        "first_pass_valid_actions": stats.first_pass_valid_actions,
        "decoded_actions": stats.decoded_actions,
        "input_tokens": stats.input_tokens,
        "output_tokens": stats.output_tokens,
    }


def _oracle_llm_stats_payload(oracle: Oracle) -> Optional[Mapping[str, Any]]:
    if not isinstance(oracle, LLMOracle):
        return None
    stats = oracle.stats
    return {
        "oracle_turns": stats.oracle_turns,
        "generation_calls": stats.generation_calls,
        "parsed_messages": stats.parsed_messages,
        "input_tokens": stats.input_tokens,
        "output_tokens": stats.output_tokens,
    }


def _error_payload(exc: Exception) -> Mapping[str, str]:
    return {"type": type(exc).__name__, "message": str(exc)}


def _termination_payload(
    termination: EpisodeTermination,
) -> Mapping[str, Any]:
    return {
        "kind": termination.kind.value,
        "code": termination.code,
        "message": termination.message,
        "action_index": termination.action_index,
        "generation_attempts": termination.generation_attempts,
    }


def _terminal_payload(outcome: EpisodeOutcome) -> Mapping[str, Any]:
    return {
        "termination": _termination_payload(outcome.termination),
        "evaluation": evaluation_result_to_payload(outcome.evaluation),
        "trajectory_scores": dict(outcome.trajectory_scores),
        "protocol_violations": [
            {"code": item.code, "message": item.message}
            for item in outcome.protocol_violations
        ],
    }


def _append_evaluated_terminal(
    log: JSONLRunLog,
    outcome: EpisodeOutcome,
    *,
    player: PlayerBackend,
    oracle: Oracle,
) -> None:
    """Write the one terminal record shared by every evaluated outcome."""

    log.append("episode.terminal", _terminal_payload(outcome))
    log.append(
        "run.ended",
        {
            "status": "evaluated",
            "stop_reason": outcome.termination.kind.value,
            "llm_stats": _llm_stats_payload(player),
            "oracle_llm_stats": _oracle_llm_stats_payload(oracle),
            "event_count_including_this": log.event_count + 1,
        },
    )


def run_logged_episode(
    player: PlayerBackend,
    case: BenchmarkCase,
    log: JSONLRunLog,
    *,
    oracle: Optional[Oracle] = None,
    max_actions: int = 100,
    run_metadata: Optional[Mapping[str, Any]] = None,
    observation_budget: Optional[int] = None,
    initial_attempts_used: int = 0,
    require_budget_exhaustion: bool = False,
) -> EpisodeOutcome:
    """Run one episode while recording every decoded action and transition.

    An ``LLMPlayerBackend`` writes its logical requests, raw observable model
    completions, parse failures, and optional repair completion into the same
    log before this runner records the decoded action.
    """

    if isinstance(max_actions, bool) or not isinstance(max_actions, int):
        raise ValueError("max_actions must be an integer")
    if max_actions < 1:
        raise ValueError("max_actions must be positive")
    if log.event_count != 0:
        raise RunLogError("run log must be empty before an episode starts")
    metadata = strict_json_loads(canonical_json_dumps(dict(run_metadata or {})))
    public_case = case_definition_to_payload(case.definition)
    effective_oracle: Oracle = oracle or CaseOracle(
        case.definition, case.world_model
    )
    llm_config = player.run_config if isinstance(player, LLMPlayerBackend) else None
    oracle_mode = "llm_case" if isinstance(effective_oracle, LLMOracle) else (
        "custom" if oracle is not None else "case"
    )
    oracle_llm_config = (
        effective_oracle.run_config
        if isinstance(effective_oracle, LLMOracle)
        else None
    )
    episode = Episode(
        case,
        oracle=effective_oracle,
        observation_budget=observation_budget,
        initial_attempts_used=initial_attempts_used,
        require_budget_exhaustion=require_budget_exhaustion,
    )
    policy: Dict[str, Any] = {
        "max_actions": max_actions,
        "durable_log": log.durable,
    }
    if (
        observation_budget is not None
        or initial_attempts_used != 0
        or require_budget_exhaustion
    ):
        policy.update(
            {
                "observation_budget": (
                    case.definition.budget
                    if observation_budget is None
                    else observation_budget
                ),
                "initial_attempts_used": initial_attempts_used,
                "require_budget_exhaustion": require_budget_exhaustion,
            }
        )
    log.append(
        "run.started",
        {
            "evaluation_profile": DEVELOPMENT_EVALUATION_PROFILE,
            "case": public_case,
            "action_schema": PLAYER_ACTION_SCHEMA,
            "player_kind": "llm" if isinstance(player, LLMPlayerBackend) else "custom",
            "llm_config": llm_config,
            "policy": policy,
            "oracle_mode": oracle_mode,
            "oracle_llm_config": oracle_llm_config,
            "run_metadata": metadata,
        },
    )
    for action_index in range(1, max_actions + 1):
        view_before = episode.view()
        try:
            action = player.next_action(view_before)
            if not isinstance(action, PlayerAction):
                raise TypeError("player backend must return PlayerAction")
            action_payload = player_action_to_payload(action)
        except AdapterOutputError as exc:
            outcome = episode.terminate_player_failure(
                EpisodeTermination(
                    kind=TerminationKind.PLAYER_OUTPUT_INVALID,
                    code=exc.wire_error.code,
                    message=str(exc),
                    action_index=action_index,
                    generation_attempts=exc.attempts,
                )
            )
            _append_evaluated_terminal(
                log,
                outcome,
                player=player,
                oracle=effective_oracle,
            )
            return outcome
        except ModelTransportError as exc:
            log.append(
                "run.ended",
                {
                    "status": "infrastructure_error",
                    "stop_reason": "model_transport_error",
                    "error": _error_payload(exc),
                    "llm_stats": _llm_stats_payload(player),
                    "oracle_llm_stats": _oracle_llm_stats_payload(effective_oracle),
                    "event_count_including_this": log.event_count + 1,
                },
            )
            raise
        except Exception as exc:
            log.append(
                "run.ended",
                {
                    "status": "player_error",
                    "stop_reason": "player_backend_exception",
                    "error": _error_payload(exc),
                    "llm_stats": _llm_stats_payload(player),
                    "oracle_llm_stats": _oracle_llm_stats_payload(effective_oracle),
                    "event_count_including_this": log.event_count + 1,
                },
            )
            raise

        log.append(
            "action.decoded",
            {
                "action_index": action_index,
                "action": action_payload,
            },
        )
        attempts_before = episode.view().attempts_used
        try:
            response = episode.apply(action)
        except EpisodeProtocolError as exc:
            log.append(
                "protocol.transition",
                {
                    "action_index": action_index,
                    "outcome_kind": "protocol_rejected",
                    "error": _error_payload(exc),
                    "attempts_used_before": attempts_before,
                    "attempts_used_after": episode.view().attempts_used,
                },
            )
            outcome = episode.terminate_player_failure(
                EpisodeTermination(
                    kind=TerminationKind.ACTION_REJECTED,
                    code=exc.code,
                    message=str(exc),
                    action_index=action_index,
                ),
                candidate_action=action,
            )
            _append_evaluated_terminal(
                log,
                outcome,
                player=player,
                oracle=effective_oracle,
            )
            return outcome
        except OracleOutputError as exc:
            log.append(
                "protocol.transition",
                {
                    "action_index": action_index,
                    "outcome_kind": "oracle_output_invalid",
                    "error": _error_payload(exc),
                    "attempts_used_before": attempts_before,
                    "attempts_used_after": episode.view().attempts_used,
                },
            )
            log.append(
                "run.ended",
                {
                    "status": "infrastructure_error",
                    "stop_reason": "oracle_output_invalid",
                    "error": _error_payload(exc),
                    "llm_stats": _llm_stats_payload(player),
                    "oracle_llm_stats": _oracle_llm_stats_payload(effective_oracle),
                    "event_count_including_this": log.event_count + 1,
                },
            )
            raise
        except Exception as exc:
            log.append(
                "protocol.transition",
                {
                    "action_index": action_index,
                    "outcome_kind": "infrastructure_error",
                    "error": _error_payload(exc),
                    "attempts_used_before": attempts_before,
                    "attempts_used_after": episode.view().attempts_used,
                },
            )
            log.append(
                "run.ended",
                {
                    "status": "infrastructure_error",
                    "stop_reason": "oracle_or_evaluator_error",
                    "error": _error_payload(exc),
                    "llm_stats": _llm_stats_payload(player),
                    "oracle_llm_stats": _oracle_llm_stats_payload(effective_oracle),
                    "event_count_including_this": log.event_count + 1,
                },
            )
            raise

        if response is not None:
            outcome_kind = "experiment_evidence"
            outcome: Mapping[str, Any] = {
                "oracle_response": oracle_response_to_payload(response)
            }
        else:
            outcome_kind = "final_evaluation"
            outcome = {
                "evaluation": evaluation_result_to_payload(
                    episode.result.evaluation
                ),
                "trajectory_scores": dict(episode.result.trajectory_scores),
                "protocol_violations": [
                    {"code": item.code, "message": item.message}
                    for item in episode.result.protocol_violations
                ],
            }
        log.append(
            "protocol.transition",
            {
                "action_index": action_index,
                "outcome_kind": outcome_kind,
                "outcome": outcome,
                "attempts_used_before": attempts_before,
                "attempts_used_after": episode.view().attempts_used,
            },
        )
        if episode.finished:
            outcome = episode.outcome
            _append_evaluated_terminal(
                log,
                outcome,
                player=player,
                oracle=effective_oracle,
            )
            return outcome

    outcome = episode.terminate_player_failure(
        EpisodeTermination(
            kind=TerminationKind.ACTION_LIMIT,
            code="max_actions_reached",
            message="Player did not commit within max_actions.",
            action_index=max_actions,
        )
    )
    _append_evaluated_terminal(
        log,
        outcome,
        player=player,
        oracle=effective_oracle,
    )
    return outcome


def run_llm_episode(
    backend: TextGenerationBackend,
    case: BenchmarkCase,
    log_path: str,
    *,
    config: Optional[GenerationConfig] = None,
    player_prompt_version: str = DEFAULT_PLAYER_PROMPT_VERSION,
    oracle_backend: Optional[TextGenerationBackend] = None,
    oracle_config: Optional[GenerationConfig] = None,
    oracle_prompt_version: str = DEFAULT_ORACLE_PROMPT_VERSION,
    max_repair_attempts: int = 0,
    max_action_bytes: int = DEFAULT_MAX_ACTION_BYTES,
    max_actions: int = 100,
    run_id: Optional[str] = None,
    run_metadata: Optional[Mapping[str, Any]] = None,
    durable_log: bool = False,
    observation_budget: Optional[int] = None,
    initial_attempts_used: int = 0,
    require_budget_exhaustion: bool = False,
) -> LoggedEpisodeRun:
    """Run one logged development episode with an LLM on either track."""
    if isinstance(max_actions, bool) or not isinstance(max_actions, int) or max_actions < 1:
        raise ValueError("max_actions must be a positive integer")
    if isinstance(max_repair_attempts, bool) or max_repair_attempts not in (0, 1):
        raise ValueError("max_repair_attempts must be 0 or 1")
    if (
        isinstance(max_action_bytes, bool)
        or not isinstance(max_action_bytes, int)
        or max_action_bytes < 1
        or max_action_bytes > MAX_LLM_ACTION_BYTES
    ):
        raise ValueError(
            "max_action_bytes must be between 1 and %d" % MAX_LLM_ACTION_BYTES
        )
    if config is not None and not isinstance(config, GenerationConfig):
        raise ValueError("config must be GenerationConfig or None")
    if player_prompt_version not in (
        PLAYER_PROMPT_VERSION_V1,
        PLAYER_PROMPT_VERSION_V2_JSON_HARDENED,
        PLAYER_PROMPT_VERSION_V3_CASE_BOUND_JSON,
    ):
        raise ValueError(
            "unsupported Player prompt_version %r" % player_prompt_version
        )
    if not callable(getattr(backend, "generate", None)):
        raise ValueError("backend must provide a callable generate method")
    if oracle_backend is not None and not callable(
        getattr(oracle_backend, "generate", None)
    ):
        raise ValueError("oracle_backend must provide a callable generate method")
    if oracle_config is not None and not isinstance(oracle_config, GenerationConfig):
        raise ValueError("oracle_config must be GenerationConfig or None")
    if oracle_backend is None and oracle_config is not None:
        raise ValueError("oracle_config requires oracle_backend")
    if oracle_prompt_version not in (
        ORACLE_PROMPT_VERSION_V1,
        ORACLE_PROMPT_VERSION_V2_JSON_HARDENED,
    ):
        raise ValueError(
            "unsupported Oracle prompt_version %r" % oracle_prompt_version
        )
    if (
        oracle_backend is None
        and oracle_prompt_version != DEFAULT_ORACLE_PROMPT_VERSION
    ):
        raise ValueError("oracle_prompt_version requires oracle_backend")
    if run_metadata is not None and not isinstance(run_metadata, Mapping):
        raise ValueError("run_metadata must be a mapping or None")
    if not isinstance(durable_log, bool):
        raise ValueError("durable_log must be boolean")
    canonical_json_dumps(dict(run_metadata or {}))
    # Validate the method-specific episode policy before creating a run log.
    Episode(
        case,
        observation_budget=observation_budget,
        initial_attempts_used=initial_attempts_used,
        require_budget_exhaustion=require_budget_exhaustion,
    )

    resolved_run_id = run_id or uuid.uuid4().hex
    with JSONLRunLog(
        log_path,
        run_id=resolved_run_id,
        durable=durable_log,
    ) as log:
        player = LLMPlayerBackend(
            backend,
            config=config,
            max_repair_attempts=max_repair_attempts,
            max_action_bytes=max_action_bytes,
            prompt_version=player_prompt_version,
            event_sink=log.append,
        )
        llm_oracle = (
            LLMOracle(
                case.definition,
                case.world_model,
                oracle_backend,
                config=oracle_config,
                prompt_version=oracle_prompt_version,
                event_sink=log.append,
            )
            if oracle_backend is not None
            else None
        )
        outcome = run_logged_episode(
            player,
            case,
            log,
            oracle=llm_oracle,
            max_actions=max_actions,
            run_metadata=run_metadata,
            observation_budget=observation_budget,
            initial_attempts_used=initial_attempts_used,
            require_budget_exhaustion=require_budget_exhaustion,
        )
        stats = player.stats
        oracle_stats = llm_oracle.stats if llm_oracle is not None else None
    return LoggedEpisodeRun(
        run_id=resolved_run_id,
        outcome=outcome,
        log_path=str(Path(log_path).resolve()),
        llm_stats=stats,
        oracle_llm_stats=oracle_stats,
    )


@dataclass(frozen=True)
class _ReplayTurn:
    primary_request: Optional[Mapping[str, Any]]
    primary_completion: Optional[Mapping[str, Any]]
    parse_failure: Optional[Mapping[str, Any]]
    repair_request: Optional[Mapping[str, Any]]
    repair_completion: Optional[Mapping[str, Any]]
    parsed: Optional[Mapping[str, Any]]
    action: Mapping[str, Any]
    oracle_request: Optional[Mapping[str, Any]]
    oracle_completion: Optional[Mapping[str, Any]]
    oracle_parsed: Optional[Mapping[str, Any]]
    transition: Mapping[str, Any]


@dataclass(frozen=True)
class _ReplayFailedAttempt:
    primary_request: Mapping[str, Any]
    primary_completion: Mapping[str, Any]
    primary_parse_failure: Optional[Mapping[str, Any]]
    repair_request: Optional[Mapping[str, Any]]
    repair_completion: Optional[Mapping[str, Any]]
    repair_parse_failure: Optional[Mapping[str, Any]]


def _payload(event: Mapping[str, Any], event_type: str) -> Mapping[str, Any]:
    if event.get("event_type") != event_type:
        raise RunReplayError(
            "event %s must be %s, found %s"
            % (event.get("sequence"), event_type, event.get("event_type"))
        )
    payload = event.get("payload")
    if not isinstance(payload, dict):
        raise RunReplayError("%s payload is invalid" % event_type)
    return payload


def _expect_index(value: Any, expected: int, label: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value != expected:
        raise RunReplayError("%s must be contiguous at %d" % (label, expected))


def _validate_request_event(
    event: Mapping[str, Any],
    *,
    call_index: int,
    player_turn: int,
    purpose: str,
) -> None:
    payload = _payload(event, "model.requested")
    if set(payload) != {
        "call_index",
        "player_turn",
        "purpose",
        "request",
    }:
        raise RunReplayError("model.requested has an invalid payload shape")
    _expect_index(payload.get("call_index"), call_index, "model call index")
    _expect_index(payload.get("player_turn"), player_turn, "Player turn")
    if payload.get("purpose") != purpose:
        raise RunReplayError("model request purpose differs from event grammar")
    request = payload.get("request")
    if not isinstance(request, dict):
        raise RunReplayError("model.requested has no logical request object")
    metadata = request.get("metadata")
    if not isinstance(metadata, dict):
        raise RunReplayError("logical model request metadata is invalid")
    if metadata.get("purpose") != purpose or metadata.get("player_turn") != player_turn:
        raise RunReplayError("logical request metadata differs from its event")


def _validate_oracle_request_event(
    event: Mapping[str, Any],
    *,
    call_index: int,
    oracle_turn: int,
) -> None:
    payload = _payload(event, "oracle.model.requested")
    if set(payload) != {
        "call_index",
        "oracle_turn",
        "purpose",
        "request",
    }:
        raise RunReplayError("oracle.model.requested has an invalid payload shape")
    _expect_index(payload.get("call_index"), call_index, "Oracle model call index")
    _expect_index(payload.get("oracle_turn"), oracle_turn, "Oracle turn")
    if payload.get("purpose") != "present_authoritative_response":
        raise RunReplayError("Oracle request purpose differs from event grammar")
    request = payload.get("request")
    if not isinstance(request, dict):
        raise RunReplayError("oracle.model.requested has no logical request object")
    metadata = request.get("metadata")
    if not isinstance(metadata, dict):
        raise RunReplayError("logical Oracle request metadata is invalid")
    if (
        metadata.get("purpose") != "present_authoritative_response"
        or metadata.get("oracle_turn") != oracle_turn
    ):
        raise RunReplayError("logical Oracle request metadata differs from its event")


def _response_from_completion(
    event: Mapping[str, Any],
    *,
    request_event: Mapping[str, Any],
) -> GenerationResponse:
    payload = _payload(event, "model.completed")
    request = _payload(request_event, "model.requested")
    if set(payload) != {
        "call_index",
        "player_turn",
        "purpose",
        "status",
        "response",
    }:
        raise RunReplayError("successful model.completed has an invalid payload shape")
    for key in ("call_index", "player_turn", "purpose"):
        if payload.get(key) != request.get(key):
            raise RunReplayError("model request/completion %s differs" % key)
    if payload.get("status") != "ok":
        raise RunReplayError("completed-run model call must have status=ok")
    response = payload.get("response")
    if not isinstance(response, dict) or set(response) != {
        "text",
        "provider",
        "model",
        "finish_reason",
        "response_id",
        "usage",
        "metadata",
    }:
        raise RunReplayError("model response has an invalid shape")
    usage = response.get("usage")
    if not isinstance(usage, dict) or set(usage) != {"input_tokens", "output_tokens"}:
        raise RunReplayError("model response usage has an invalid shape")
    try:
        rebuilt = GenerationResponse(
            text=response["text"],
            provider=response["provider"],
            model=response["model"],
            finish_reason=response["finish_reason"],
            response_id=response["response_id"],
            usage=TokenUsage(
                input_tokens=usage["input_tokens"],
                output_tokens=usage["output_tokens"],
            ),
            metadata=response["metadata"],
        )
    except (TypeError, ValueError) as exc:
        raise RunReplayError("model response violates the adapter contract") from exc
    if generation_response_to_payload(rebuilt) != response:
        raise RunReplayError("model response does not round-trip canonically")
    return rebuilt


def _wire_error_from_payload(value: Any, label: str) -> WireDecodeError:
    if not isinstance(value, dict) or set(value) != {"code", "path", "message"}:
        raise RunReplayError("%s wire error has an invalid shape" % label)
    if any(
        not isinstance(value.get(key), str) or not value.get(key)
        for key in ("code", "path", "message")
    ):
        raise RunReplayError("%s wire error is invalid" % label)
    try:
        return WireDecodeError(value["code"], value["path"], value["message"])
    except (TypeError, ValueError) as exc:
        raise RunReplayError("%s wire error is invalid" % label) from exc


def _wire_error_payload(error: WireDecodeError) -> Mapping[str, str]:
    return {
        "code": error.code,
        "path": error.path,
        "message": error.detail,
    }


def _rejected_response_from_completion(
    event: Mapping[str, Any],
    *,
    request_event: Mapping[str, Any],
) -> Tuple[Mapping[str, Any], WireDecodeError]:
    """Validate a bounded provider output omitted from the log."""

    payload = _payload(event, "model.completed")
    request = _payload(request_event, "model.requested")
    if set(payload) != {
        "call_index",
        "player_turn",
        "purpose",
        "status",
        "response_summary",
        "wire_error",
    }:
        raise RunReplayError("rejected model.completed has an invalid payload shape")
    for key in ("call_index", "player_turn", "purpose"):
        if payload.get(key) != request.get(key):
            raise RunReplayError("model request/completion %s differs" % key)
    if payload.get("status") != "output_rejected":
        raise RunReplayError("rejected model completion has an invalid status")
    summary = payload.get("response_summary")
    if not isinstance(summary, dict) or set(summary) != {
        "provider",
        "model",
        "finish_reason",
        "response_id",
        "usage",
        "text_bytes",
        "text_omitted",
    }:
        raise RunReplayError("rejected model response summary has an invalid shape")
    usage = summary.get("usage")
    if not isinstance(usage, dict) or set(usage) != {
        "input_tokens",
        "output_tokens",
    }:
        raise RunReplayError("rejected model response usage has an invalid shape")
    for key in ("input_tokens", "output_tokens"):
        value = usage.get(key)
        if value is not None and (
            isinstance(value, bool) or not isinstance(value, int) or value < 0
        ):
            raise RunReplayError("rejected model response usage is invalid")
    text_bytes = summary.get("text_bytes")
    if (
        isinstance(text_bytes, bool)
        or not isinstance(text_bytes, int)
        or text_bytes < 1
        or summary.get("text_omitted") is not True
    ):
        raise RunReplayError("rejected model response byte summary is invalid")
    for key in ("provider", "model"):
        if not isinstance(summary.get(key), str) or not summary.get(key):
            raise RunReplayError("rejected model response identity is invalid")
    for key in ("finish_reason", "response_id"):
        if summary.get(key) is not None and not isinstance(summary.get(key), str):
            raise RunReplayError("rejected model response metadata is invalid")
    error = _wire_error_from_payload(payload.get("wire_error"), "rejected output")
    return summary, error


def _response_from_oracle_completion(
    event: Mapping[str, Any],
    *,
    request_event: Mapping[str, Any],
) -> GenerationResponse:
    payload = _payload(event, "oracle.model.completed")
    request = _payload(request_event, "oracle.model.requested")
    if set(payload) != {
        "call_index",
        "oracle_turn",
        "purpose",
        "status",
        "response",
    }:
        raise RunReplayError(
            "successful oracle.model.completed has an invalid payload shape"
        )
    for key in ("call_index", "oracle_turn", "purpose"):
        if payload.get(key) != request.get(key):
            raise RunReplayError("Oracle request/completion %s differs" % key)
    if payload.get("status") != "ok":
        raise RunReplayError("completed-run Oracle model call must have status=ok")
    response = payload.get("response")
    if not isinstance(response, dict) or set(response) != {
        "text",
        "provider",
        "model",
        "finish_reason",
        "response_id",
        "usage",
        "metadata",
    }:
        raise RunReplayError("Oracle model response has an invalid shape")
    usage = response.get("usage")
    if not isinstance(usage, dict) or set(usage) != {"input_tokens", "output_tokens"}:
        raise RunReplayError("Oracle model response usage has an invalid shape")
    try:
        rebuilt = GenerationResponse(
            text=response["text"],
            provider=response["provider"],
            model=response["model"],
            finish_reason=response["finish_reason"],
            response_id=response["response_id"],
            usage=TokenUsage(
                input_tokens=usage["input_tokens"],
                output_tokens=usage["output_tokens"],
            ),
            metadata=response["metadata"],
        )
    except (TypeError, ValueError) as exc:
        raise RunReplayError(
            "Oracle model response violates the adapter contract"
        ) from exc
    if generation_response_to_payload(rebuilt) != response:
        raise RunReplayError("Oracle model response does not round-trip canonically")
    return rebuilt


def _validate_oracle_parse_event(
    event: Mapping[str, Any],
    *,
    completion_event: Mapping[str, Any],
    oracle_turn: int,
) -> None:
    payload = _payload(event, "oracle.output.parsed")
    completion = _payload(completion_event, "oracle.model.completed")
    if set(payload) != {
        "call_index",
        "oracle_turn",
        "oracle_response",
    }:
        raise RunReplayError("oracle.output.parsed has an invalid payload shape")
    if payload.get("call_index") != completion.get("call_index"):
        raise RunReplayError("Oracle parser event does not reference its completion")
    _expect_index(payload.get("oracle_turn"), oracle_turn, "Oracle parser turn")
    if not isinstance(payload.get("oracle_response"), dict):
        raise RunReplayError("parsed Oracle response is invalid")


def _validate_parse_event(
    event: Mapping[str, Any],
    *,
    event_type: str,
    completion_event: Mapping[str, Any],
    player_turn: int,
    repair_attempt: int,
) -> None:
    payload = _payload(event, event_type)
    completion = _payload(completion_event, "model.completed")
    expected_keys = {
        "call_index",
        "player_turn",
        "repair_attempt",
        "wire_error" if event_type == "action.parse_failed" else "action",
    }
    if set(payload) != expected_keys:
        raise RunReplayError("%s has an invalid payload shape" % event_type)
    if payload.get("call_index") != completion.get("call_index"):
        raise RunReplayError("parser event does not reference its model completion")
    _expect_index(payload.get("player_turn"), player_turn, "parser Player turn")
    if payload.get("repair_attempt") != repair_attempt:
        raise RunReplayError("parser repair_attempt differs from event grammar")


def _llm_policy_from_started(
    started: Mapping[str, Any],
) -> Tuple[GenerationConfig, int, int, str]:
    llm_config = started.get("llm_config")
    base_keys = {
        "evaluation_profile",
        "action_schema",
        "generation_config",
        "max_action_bytes",
        "max_repair_attempts",
        "generation_policy",
    }
    if not isinstance(llm_config, dict):
        raise RunReplayError("logged LLM configuration has an invalid shape")
    if set(llm_config) == base_keys:
        prompt_version = DEFAULT_PLAYER_PROMPT_VERSION
    elif set(llm_config) == base_keys | {
        "prompt_version",
        "repair_prompt_version",
    }:
        prompt_version = llm_config.get("prompt_version")
        expected_repair_version = {
            PLAYER_PROMPT_VERSION_V2_JSON_HARDENED: (
                PLAYER_REPAIR_PROMPT_VERSION_V2_JSON_HARDENED
            ),
            PLAYER_PROMPT_VERSION_V3_CASE_BOUND_JSON: (
                PLAYER_REPAIR_PROMPT_VERSION_V3_CASE_BOUND_JSON
            ),
        }.get(prompt_version)
        if (
            expected_repair_version is None
            or llm_config.get("repair_prompt_version")
            != expected_repair_version
        ):
            raise RunReplayError("logged Player prompt version is unavailable")
    else:
        raise RunReplayError("logged LLM configuration has an invalid shape")
    expected_values = {
        "evaluation_profile": DEVELOPMENT_EVALUATION_PROFILE,
        "action_schema": PLAYER_ACTION_SCHEMA,
    }
    for key, expected in expected_values.items():
        if llm_config.get(key) != expected:
            raise RunReplayError("logged %s is unavailable" % key)
    max_repair = llm_config.get("max_repair_attempts")
    if isinstance(max_repair, bool) or max_repair not in (0, 1):
        raise RunReplayError("logged second-generation policy is invalid")
    expected_policy = (
        "plain_text_no_regeneration"
        if max_repair == 0
        else "plain_text_one_schema_directed_regeneration"
    )
    if llm_config.get("generation_policy") != expected_policy:
        raise RunReplayError("generation policy name and limit differ")
    max_action_bytes = llm_config.get("max_action_bytes")
    if (
        isinstance(max_action_bytes, bool)
        or not isinstance(max_action_bytes, int)
        or max_action_bytes < 1
        or max_action_bytes > MAX_LLM_ACTION_BYTES
    ):
        raise RunReplayError("logged action byte limit is invalid")
    config_payload = llm_config.get("generation_config")
    if not isinstance(config_payload, dict) or set(config_payload) != {
        "max_output_tokens",
        "temperature",
        "top_p",
        "seed",
    }:
        raise RunReplayError("logged generation config is invalid")
    try:
        config = GenerationConfig(**config_payload)
    except (TypeError, ValueError) as exc:
        raise RunReplayError("logged generation config is unavailable") from exc
    return config, max_action_bytes, max_repair, prompt_version


def _oracle_llm_policy_from_started(
    started: Mapping[str, Any],
) -> Tuple[GenerationConfig, int, str]:
    oracle_config = started.get("oracle_llm_config")
    base_keys = {
        "evaluation_profile",
        "message_schema",
        "generation_config",
        "max_output_bytes",
        "generation_policy",
    }
    if not isinstance(oracle_config, dict):
        raise RunReplayError("logged Oracle LLM configuration has an invalid shape")
    if set(oracle_config) == base_keys:
        prompt_version = DEFAULT_ORACLE_PROMPT_VERSION
    elif set(oracle_config) == base_keys | {"prompt_version"}:
        prompt_version = oracle_config.get("prompt_version")
        if prompt_version != ORACLE_PROMPT_VERSION_V2_JSON_HARDENED:
            raise RunReplayError("logged Oracle prompt version is unavailable")
    else:
        raise RunReplayError("logged Oracle LLM configuration has an invalid shape")
    expected_values = {
        "evaluation_profile": DEVELOPMENT_EVALUATION_PROFILE,
        "message_schema": ORACLE_MESSAGE_SCHEMA,
        "generation_policy": "authoritative_message_exact_copy_one_call",
    }
    for key, expected in expected_values.items():
        if oracle_config.get(key) != expected:
            raise RunReplayError("logged Oracle %s is unavailable" % key)
    config_payload = oracle_config.get("generation_config")
    if not isinstance(config_payload, dict) or set(config_payload) != {
        "max_output_tokens",
        "temperature",
        "top_p",
        "seed",
    }:
        raise RunReplayError("logged Oracle generation config is invalid")
    try:
        config = GenerationConfig(**config_payload)
    except (TypeError, ValueError) as exc:
        raise RunReplayError("logged Oracle generation config is unavailable") from exc
    max_output_bytes = oracle_config.get("max_output_bytes")
    if (
        isinstance(max_output_bytes, bool)
        or not isinstance(max_output_bytes, int)
        or max_output_bytes < 1
        or max_output_bytes > 65_536
    ):
        raise RunReplayError("logged Oracle output byte limit is invalid")
    return config, max_output_bytes, prompt_version


def _completed_event_grammar(
    events: Sequence[Mapping[str, Any]],
    *,
    player_kind: str,
    oracle_mode: str,
    max_actions: int,
    max_repair_attempts: int,
    terminal_position: Optional[int] = None,
    termination_kind: Optional[TerminationKind] = TerminationKind.SUBMITTED,
) -> Tuple[_ReplayTurn, ...]:
    turns = []
    position = 1
    expected_turn = 1
    expected_call = 1
    expected_oracle_call = 1
    expected_oracle_turn = 1
    if terminal_position is None:
        terminal_position = len(events) - 1
    if terminal_position < 1 or terminal_position >= len(events):
        raise RunReplayError("terminal event position is invalid")
    while position < terminal_position:
        if player_kind == "custom":
            primary_request = None
            primary_completion = None
            parse_failure = None
            repair_request = None
            repair_completion = None
            parsed = None
        else:
            primary_request = events[position]
            _validate_request_event(
                primary_request,
                call_index=expected_call,
                player_turn=expected_turn,
                purpose="next_action",
            )
            expected_call += 1
            position += 1
            if position >= terminal_position:
                raise RunReplayError("model request has no completion")
            primary_completion = events[position]
            _response_from_completion(
                primary_completion, request_event=primary_request
            )
            position += 1
            if position >= terminal_position:
                raise RunReplayError("model completion has no parser event")
            if events[position].get("event_type") == "action.parse_failed":
                if max_repair_attempts != 1:
                    raise RunReplayError("log used a disabled second generation")
                parse_failure = events[position]
                _validate_parse_event(
                    parse_failure,
                    event_type="action.parse_failed",
                    completion_event=primary_completion,
                    player_turn=expected_turn,
                    repair_attempt=0,
                )
                position += 1
                if position >= terminal_position:
                    raise RunReplayError("parse failure has no second request")
                repair_request = events[position]
                _validate_request_event(
                    repair_request,
                    call_index=expected_call,
                    player_turn=expected_turn,
                    purpose="repair_action",
                )
                expected_call += 1
                position += 1
                if position >= terminal_position:
                    raise RunReplayError("second request has no completion")
                repair_completion = events[position]
                _response_from_completion(
                    repair_completion, request_event=repair_request
                )
                position += 1
                if position >= terminal_position:
                    raise RunReplayError("second completion has no parser event")
                parsed = events[position]
                _validate_parse_event(
                    parsed,
                    event_type="action.parsed",
                    completion_event=repair_completion,
                    player_turn=expected_turn,
                    repair_attempt=1,
                )
            else:
                parse_failure = None
                repair_request = None
                repair_completion = None
                parsed = events[position]
                _validate_parse_event(
                    parsed,
                    event_type="action.parsed",
                    completion_event=primary_completion,
                    player_turn=expected_turn,
                    repair_attempt=0,
                )
            position += 1
        if position + 1 >= terminal_position:
            raise RunReplayError("Player turn lacks an action/transition pair")
        action_event = events[position]
        action_payload = _payload(action_event, "action.decoded")
        if set(action_payload) != {"action_index", "action"}:
            raise RunReplayError("action.decoded has an invalid payload shape")
        _expect_index(action_payload.get("action_index"), expected_turn, "action index")
        position += 1
        action_body = action_payload.get("action")
        if not isinstance(action_body, dict) or action_body.get("kind") not in (
            "experiment",
            "final",
        ):
            raise RunReplayError("action.decoded contains an invalid action kind")
        oracle_request = None
        oracle_completion = None
        oracle_parsed = None
        if (
            oracle_mode == "llm_case"
            and action_body.get("kind") == "experiment"
            and position < terminal_position
            and events[position].get("event_type") == "oracle.model.requested"
        ):
            if position + 2 >= terminal_position:
                raise RunReplayError("experiment has incomplete Oracle model events")
            oracle_request = events[position]
            _validate_oracle_request_event(
                oracle_request,
                call_index=expected_oracle_call,
                oracle_turn=expected_oracle_turn,
            )
            position += 1
            oracle_completion = events[position]
            _response_from_oracle_completion(
                oracle_completion,
                request_event=oracle_request,
            )
            position += 1
            oracle_parsed = events[position]
            _validate_oracle_parse_event(
                oracle_parsed,
                completion_event=oracle_completion,
                oracle_turn=expected_oracle_turn,
            )
            position += 1
            expected_oracle_call += 1
            expected_oracle_turn += 1
        if position >= terminal_position:
            raise RunReplayError("decoded action has no protocol transition")
        transition_event = events[position]
        transition = _payload(transition_event, "protocol.transition")
        normal_keys = {
            "action_index", "outcome_kind", "outcome",
            "attempts_used_before", "attempts_used_after",
        }
        rejected_keys = {
            "action_index", "outcome_kind", "error",
            "attempts_used_before", "attempts_used_after",
        }
        if set(transition) not in (normal_keys, rejected_keys):
            raise RunReplayError("protocol.transition has an invalid payload shape")
        if set(transition) == rejected_keys:
            if transition.get("outcome_kind") != "protocol_rejected":
                raise RunReplayError("rejected transition has an invalid outcome kind")
            error = transition.get("error")
            if not isinstance(error, dict) or set(error) != {"type", "message"}:
                raise RunReplayError("rejected transition has an invalid error")
        elif transition.get("outcome_kind") not in (
            "experiment_evidence",
            "final_evaluation",
        ):
            raise RunReplayError("successful transition has an invalid outcome kind")
        _expect_index(transition.get("action_index"), expected_turn, "transition index")
        turns.append(
            _ReplayTurn(
                primary_request=primary_request,
                primary_completion=primary_completion,
                parse_failure=parse_failure,
                repair_request=repair_request,
                repair_completion=repair_completion,
                parsed=parsed,
                action=action_event,
                oracle_request=oracle_request,
                oracle_completion=oracle_completion,
                oracle_parsed=oracle_parsed,
                transition=transition_event,
            )
        )
        position += 1
        expected_turn += 1
    if len(turns) > max_actions:
        raise RunReplayError("run exceeds its action policy")
    kinds = [
        _payload(turn.transition, "protocol.transition").get("outcome_kind")
        for turn in turns
    ]
    if termination_kind == TerminationKind.SUBMITTED:
        if not turns or kinds[-1] != "final_evaluation":
            raise RunReplayError("submitted run must end with final evaluation")
        if any(kind != "experiment_evidence" for kind in kinds[:-1]):
            raise RunReplayError("only the submitted turn may contain final evaluation")
    elif termination_kind == TerminationKind.ACTION_REJECTED:
        if not turns or kinds[-1] != "protocol_rejected":
            raise RunReplayError("rejected run must end with a rejected transition")
        if any(kind != "experiment_evidence" for kind in kinds[:-1]):
            raise RunReplayError("only the final action may be rejected")
    elif termination_kind == TerminationKind.ACTION_LIMIT:
        if len(turns) != max_actions:
            raise RunReplayError("action-limit run does not reach max_actions")
        if any(kind != "experiment_evidence" for kind in kinds):
            raise RunReplayError("action-limit run may contain only experiments")
    elif termination_kind == TerminationKind.PLAYER_OUTPUT_INVALID:
        raise RunReplayError("undecodable attempt must use failed-attempt grammar")
    elif termination_kind is None:
        if any(kind != "experiment_evidence" for kind in kinds):
            raise RunReplayError("unterminated prefix may contain only experiments")
    else:
        raise RunReplayError("terminal kind is unavailable")
    return tuple(turns)


def _failed_attempt_event_grammar(
    events: Sequence[Mapping[str, Any]],
    *,
    start_position: int,
    terminal_position: int,
    player_turn: int,
    call_index: int,
    max_repair_attempts: int,
) -> _ReplayFailedAttempt:
    """Validate the model-event suffix for one undecodable Player turn."""

    position = start_position
    if position >= terminal_position:
        raise RunReplayError("LLM output-invalid run has no failed model attempt")
    primary_request = events[position]
    _validate_request_event(
        primary_request,
        call_index=call_index,
        player_turn=player_turn,
        purpose="next_action",
    )
    position += 1
    if position >= terminal_position:
        raise RunReplayError("failed model request has no completion")
    primary_completion = events[position]
    primary_payload = _payload(primary_completion, "model.completed")
    position += 1

    primary_parse_failure = None
    repair_request = None
    repair_completion = None
    repair_parse_failure = None
    if primary_payload.get("status") == "output_rejected":
        _rejected_response_from_completion(
            primary_completion,
            request_event=primary_request,
        )
    elif primary_payload.get("status") == "ok":
        _response_from_completion(primary_completion, request_event=primary_request)
        if position >= terminal_position:
            raise RunReplayError("failed model completion has no parse failure")
        primary_parse_failure = events[position]
        _validate_parse_event(
            primary_parse_failure,
            event_type="action.parse_failed",
            completion_event=primary_completion,
            player_turn=player_turn,
            repair_attempt=0,
        )
        position += 1
        recorded_error = _wire_error_from_payload(
            _payload(primary_parse_failure, "action.parse_failed").get("wire_error"),
            "primary parse failure",
        )
        unsafe_to_regenerate = {
            "payload_too_large",
            "too_deep",
            "too_many_values",
            "invalid_unicode",
        }
        should_repair = (
            max_repair_attempts == 1
            and recorded_error.code not in unsafe_to_regenerate
        )
        if should_repair:
            if position >= terminal_position:
                raise RunReplayError("parse failure has no configured second request")
            repair_request = events[position]
            _validate_request_event(
                repair_request,
                call_index=call_index + 1,
                player_turn=player_turn,
                purpose="repair_action",
            )
            position += 1
            if position >= terminal_position:
                raise RunReplayError("second request has no completion")
            repair_completion = events[position]
            repair_payload = _payload(repair_completion, "model.completed")
            position += 1
            if repair_payload.get("status") == "output_rejected":
                _rejected_response_from_completion(
                    repair_completion,
                    request_event=repair_request,
                )
            elif repair_payload.get("status") == "ok":
                _response_from_completion(
                    repair_completion,
                    request_event=repair_request,
                )
                if position >= terminal_position:
                    raise RunReplayError("second completion has no parse failure")
                repair_parse_failure = events[position]
                _validate_parse_event(
                    repair_parse_failure,
                    event_type="action.parse_failed",
                    completion_event=repair_completion,
                    player_turn=player_turn,
                    repair_attempt=1,
                )
                position += 1
            else:
                raise RunReplayError("failed second completion has an invalid status")
    else:
        raise RunReplayError("failed primary completion has an invalid status")
    if position != terminal_position:
        raise RunReplayError("unexpected event follows undecodable Player output")
    return _ReplayFailedAttempt(
        primary_request=primary_request,
        primary_completion=primary_completion,
        primary_parse_failure=primary_parse_failure,
        repair_request=repair_request,
        repair_completion=repair_completion,
        repair_parse_failure=repair_parse_failure,
    )


def _replay_parsers(
    turns: Sequence[_ReplayTurn], max_action_bytes: int
) -> Tuple[Dict[int, PlayerAction], Dict[int, WireDecodeError], int]:
    actions: Dict[int, PlayerAction] = {}
    failures: Dict[int, WireDecodeError] = {}
    repairs = 0
    unsafe_to_regenerate = {
        "payload_too_large",
        "too_deep",
        "too_many_values",
        "invalid_unicode",
    }
    for player_turn, turn in enumerate(turns, start=1):
        if turn.primary_completion is None or turn.parsed is None:
            continue
        primary = _response_from_completion(
            turn.primary_completion, request_event=turn.primary_request
        )
        source = primary
        if turn.parse_failure is not None:
            try:
                player_action_from_json(primary.text, max_bytes=max_action_bytes)
            except WireDecodeError as exc:
                actual_error = {
                    "code": exc.code,
                    "path": exc.path,
                    "message": exc.detail,
                }
                recorded_error = _payload(
                    turn.parse_failure, "action.parse_failed"
                ).get("wire_error")
                if actual_error != recorded_error:
                    raise RunReplayError("recorded parse failure differs from decoder")
                if exc.code in unsafe_to_regenerate:
                    raise RunReplayError(
                        "second generation followed a structural safety-limit failure"
                    )
                failures[player_turn] = exc
            else:
                raise RunReplayError("recorded parse failure now decodes successfully")
            if turn.repair_completion is None or turn.repair_request is None:
                raise RunReplayError("parse failure lacks its second generation")
            source = _response_from_completion(
                turn.repair_completion, request_event=turn.repair_request
            )
            repairs += 1
        try:
            action = player_action_from_json(source.text, max_bytes=max_action_bytes)
        except WireDecodeError as exc:
            raise RunReplayError(
                "recorded successful parse no longer decodes: %s" % exc
            ) from exc
        action_payload = player_action_to_payload(action)
        parsed = _payload(turn.parsed, "action.parsed")
        if parsed.get("action") != action_payload:
            raise RunReplayError("parser replay produced a different action")
        actions[player_turn] = action
    return actions, failures, repairs


def _replay_one_parse_failure(
    completion: Mapping[str, Any],
    request: Mapping[str, Any],
    parse_failure: Mapping[str, Any],
    *,
    max_action_bytes: int,
) -> WireDecodeError:
    response = _response_from_completion(completion, request_event=request)
    try:
        player_action_from_json(response.text, max_bytes=max_action_bytes)
    except WireDecodeError as exc:
        recorded = _payload(parse_failure, "action.parse_failed").get("wire_error")
        if recorded != _wire_error_payload(exc):
            raise RunReplayError("recorded parse failure differs from decoder")
        return exc
    raise RunReplayError("recorded parse failure now decodes successfully")


def _replay_failed_attempt(
    failed: _ReplayFailedAttempt,
    *,
    max_action_bytes: int,
) -> Tuple[WireDecodeError, WireDecodeError, int]:
    primary_payload = _payload(failed.primary_completion, "model.completed")
    if primary_payload.get("status") == "output_rejected":
        _, primary_error = _rejected_response_from_completion(
            failed.primary_completion,
            request_event=failed.primary_request,
        )
    else:
        if failed.primary_parse_failure is None:
            raise RunReplayError("failed primary output has no parse failure")
        primary_error = _replay_one_parse_failure(
            failed.primary_completion,
            failed.primary_request,
            failed.primary_parse_failure,
            max_action_bytes=max_action_bytes,
        )
    if failed.repair_completion is None:
        return primary_error, primary_error, 0
    if failed.repair_request is None:
        raise RunReplayError("second completion has no request")
    repair_payload = _payload(failed.repair_completion, "model.completed")
    if repair_payload.get("status") == "output_rejected":
        _, final_error = _rejected_response_from_completion(
            failed.repair_completion,
            request_event=failed.repair_request,
        )
    else:
        if failed.repair_parse_failure is None:
            raise RunReplayError("failed second output has no parse failure")
        final_error = _replay_one_parse_failure(
            failed.repair_completion,
            failed.repair_request,
            failed.repair_parse_failure,
            max_action_bytes=max_action_bytes,
        )
    return primary_error, final_error, 1


def _completion_usage(completion: Mapping[str, Any]) -> Mapping[str, Any]:
    payload = _payload(completion, "model.completed")
    if payload.get("status") == "ok":
        response = payload.get("response")
    elif payload.get("status") == "output_rejected":
        response = payload.get("response_summary")
    else:
        raise RunReplayError("evaluated run contains a failed transport completion")
    if not isinstance(response, dict) or not isinstance(response.get("usage"), dict):
        raise RunReplayError("model completion usage is unavailable")
    return response["usage"]


def _expected_llm_stats(
    turns: Sequence[_ReplayTurn],
    failed: Optional[_ReplayFailedAttempt] = None,
) -> Mapping[str, Any]:
    completions = []
    for turn in turns:
        if turn.primary_completion is None:
            raise RunReplayError("LLM turn has no primary completion")
        completions.append(turn.primary_completion)
        if turn.repair_completion is not None:
            completions.append(turn.repair_completion)
    if failed is not None:
        completions.append(failed.primary_completion)
        if failed.repair_completion is not None:
            completions.append(failed.repair_completion)
    input_total = 0
    output_total = 0
    input_complete = True
    output_complete = True
    for completion in completions:
        usage = _completion_usage(completion)
        if usage["input_tokens"] is None:
            input_complete = False
        else:
            input_total += usage["input_tokens"]
        if usage["output_tokens"] is None:
            output_complete = False
        else:
            output_total += usage["output_tokens"]
    repair_count = sum(turn.repair_completion is not None for turn in turns) + (
        1 if failed is not None and failed.repair_completion is not None else 0
    )
    return {
        "player_turns": len(turns) + (1 if failed is not None else 0),
        "primary_calls": len(turns) + (1 if failed is not None else 0),
        "repair_calls": repair_count,
        "first_pass_valid_actions": sum(
            turn.repair_completion is None for turn in turns
        ),
        "decoded_actions": len(turns),
        "input_tokens": input_total if input_complete else None,
        "output_tokens": output_total if output_complete else None,
    }


def _expected_oracle_llm_stats(
    turns: Sequence[_ReplayTurn],
) -> Mapping[str, Any]:
    completions = [
        turn.oracle_completion
        for turn in turns
        if turn.oracle_completion is not None
    ]
    input_total = 0
    output_total = 0
    input_complete = True
    output_complete = True
    for completion in completions:
        response = _payload(completion, "oracle.model.completed")["response"]
        usage = response["usage"]
        if usage["input_tokens"] is None:
            input_complete = False
        else:
            input_total += usage["input_tokens"]
        if usage["output_tokens"] is None:
            output_complete = False
        else:
            output_total += usage["output_tokens"]
    return {
        "oracle_turns": len(completions),
        "generation_calls": len(completions),
        "parsed_messages": len(completions),
        "input_tokens": input_total if input_complete else None,
        "output_tokens": output_total if output_complete else None,
    }


class _ReplayOracle:
    """Return exactly one response prepared by the replay verifier."""

    def __init__(self) -> None:
        self._proposal: Optional[ExperimentProposal] = None
        self._response: Optional[OracleResponse] = None

    def prepare(
        self,
        proposal: ExperimentProposal,
        response: OracleResponse,
    ) -> None:
        if self._proposal is not None or self._response is not None:
            raise RunReplayError("replay Oracle already has a pending response")
        self._proposal = proposal
        self._response = response

    def respond(self, proposal: ExperimentProposal) -> OracleResponse:
        if self._proposal is None or self._response is None:
            raise RunReplayError("replay Oracle has no prepared response")
        if proposal != self._proposal:
            raise RunReplayError("replay Oracle proposal differs")
        response = self._response
        self._proposal = None
        self._response = None
        return response


def _termination_from_terminal_event(
    event: Mapping[str, Any],
) -> Tuple[EpisodeTermination, Mapping[str, Any]]:
    terminal = _payload(event, "episode.terminal")
    if set(terminal) != {
        "termination",
        "evaluation",
        "trajectory_scores",
        "protocol_violations",
    }:
        raise RunReplayError("episode.terminal has an invalid payload shape")
    raw = terminal.get("termination")
    if not isinstance(raw, dict) or set(raw) != {
        "kind",
        "code",
        "message",
        "action_index",
        "generation_attempts",
    }:
        raise RunReplayError("terminal termination has an invalid shape")
    try:
        termination = EpisodeTermination(
            kind=TerminationKind(raw["kind"]),
            code=raw["code"],
            message=raw["message"],
            action_index=raw["action_index"],
            generation_attempts=raw["generation_attempts"],
        )
    except (TypeError, ValueError) as exc:
        raise RunReplayError("terminal termination is invalid") from exc
    if not isinstance(terminal.get("evaluation"), dict):
        raise RunReplayError("terminal evaluation is invalid")
    trajectory = terminal.get("trajectory_scores")
    if not isinstance(trajectory, dict):
        raise RunReplayError("terminal trajectory scores are invalid")
    violations = terminal.get("protocol_violations")
    if not isinstance(violations, list) or any(
        not isinstance(item, dict)
        or set(item) != {"code", "message"}
        or not isinstance(item.get("code"), str)
        or not item.get("code")
        or not isinstance(item.get("message"), str)
        or not item.get("message")
        for item in violations
    ):
        raise RunReplayError("terminal protocol violations are invalid")
    return termination, terminal


def replay_run_log(
    path: str,
    case: BenchmarkCase,
) -> ReplayReport:
    """Replay parsers and behavior against the supplied case; no LLM is called."""

    loaded = load_run_log(path)
    if not loaded.complete:
        raise RunReplayError("log is incomplete")
    started = _payload(loaded.events[0], "run.started")
    ended = _payload(loaded.events[-1], "run.ended")
    if ended.get("status") != "evaluated":
        raise RunReplayError("only evaluated runs can be replayed")
    if len(loaded.events) < 3:
        raise RunReplayError("evaluated run has no terminal event")
    terminal_position = len(loaded.events) - 2
    recorded_termination, terminal_record = _termination_from_terminal_event(
        loaded.events[terminal_position]
    )
    termination_kind = recorded_termination.kind
    if ended.get("stop_reason") != termination_kind.value:
        raise RunReplayError("run.ended disagrees with episode.terminal")
    if set(ended) != {
        "status",
        "stop_reason",
        "llm_stats",
        "oracle_llm_stats",
        "event_count_including_this",
    }:
        raise RunReplayError("evaluated run.ended has an invalid payload shape")
    if termination_kind == TerminationKind.PLAYER_OUTPUT_INVALID:
        if recorded_termination.generation_attempts not in (1, 2):
            raise RunReplayError("undecodable output lacks generation attempts")
    elif recorded_termination.generation_attempts is not None:
        raise RunReplayError("non-decoder termination has generation attempts")
    if started.get("evaluation_profile") != DEVELOPMENT_EVALUATION_PROFILE:
        raise RunReplayError("logged evaluation profile is unavailable")
    run_metadata = started.get("run_metadata")
    if not isinstance(run_metadata, dict):
        raise RunReplayError("run metadata is invalid")
    current_case = case_definition_to_payload(case.definition)
    recorded_case = started.get("case")
    if recorded_case != current_case:
        raise RunReplayError("public case snapshot does not match supplied case")
    if started.get("action_schema") != PLAYER_ACTION_SCHEMA:
        raise RunReplayError("logged action schema is unavailable")
    oracle_mode = started.get("oracle_mode")
    if oracle_mode not in ("case", "llm_case"):
        raise RunReplayError("only deterministic case Oracle logs can be replayed")
    player_kind = started.get("player_kind")
    if player_kind not in ("llm", "custom"):
        raise RunReplayError("logged player kind is unavailable")
    policy = started.get("policy")
    base_policy_fields = {"max_actions", "durable_log"}
    observation_policy_fields = {
        "observation_budget",
        "initial_attempts_used",
        "require_budget_exhaustion",
    }
    if not isinstance(policy, dict) or set(policy) not in (
        base_policy_fields,
        base_policy_fields | observation_policy_fields,
    ):
        raise RunReplayError("run action/log policy is invalid")
    max_actions = policy.get("max_actions")
    if isinstance(max_actions, bool) or not isinstance(max_actions, int) or max_actions < 1:
        raise RunReplayError("logged max_actions is invalid")
    if not isinstance(policy.get("durable_log"), bool):
        raise RunReplayError("logged durability policy is invalid")
    if observation_policy_fields.issubset(policy):
        observation_budget = policy["observation_budget"]
        initial_attempts_used = policy["initial_attempts_used"]
        require_budget_exhaustion = policy["require_budget_exhaustion"]
        if (
            isinstance(observation_budget, bool)
            or not isinstance(observation_budget, int)
            or not 0 <= observation_budget <= case.definition.budget
        ):
            raise RunReplayError("logged observation budget is invalid")
        if (
            isinstance(initial_attempts_used, bool)
            or not isinstance(initial_attempts_used, int)
            or not 0 <= initial_attempts_used <= observation_budget
        ):
            raise RunReplayError("logged initial observation count is invalid")
        if not isinstance(require_budget_exhaustion, bool):
            raise RunReplayError("logged observation stopping policy is invalid")
    else:
        observation_budget = None
        initial_attempts_used = 0
        require_budget_exhaustion = False
    if player_kind == "llm":
        (
            config,
            max_action_bytes,
            max_repair,
            player_prompt_version,
        ) = _llm_policy_from_started(started)
    else:
        if started.get("llm_config") is not None:
            raise RunReplayError("custom player must not have LLM configuration")
        config = GenerationConfig()
        max_action_bytes = _MAX_EVENT_BYTES
        max_repair = 0
        player_prompt_version = DEFAULT_PLAYER_PROMPT_VERSION
    if oracle_mode == "llm_case":
        (
            oracle_config,
            oracle_max_output_bytes,
            oracle_prompt_version,
        ) = _oracle_llm_policy_from_started(started)
    else:
        if started.get("oracle_llm_config") is not None:
            raise RunReplayError("case Oracle must not have LLM configuration")
        oracle_config = GenerationConfig()
        oracle_max_output_bytes = 65_536
        oracle_prompt_version = DEFAULT_ORACLE_PROMPT_VERSION

    # Validate the physical cause/effect sequence before invoking any private
    # runtime component.  An undecodable turn is a model-event suffix with no
    # invented action.decoded event.
    failed_attempt: Optional[_ReplayFailedAttempt] = None
    if termination_kind == TerminationKind.PLAYER_OUTPUT_INVALID:
        transition_positions = [
            index
            for index, event in enumerate(loaded.events[:terminal_position])
            if event.get("event_type") == "protocol.transition"
        ]
        failed_start = (max(transition_positions) + 1) if transition_positions else 1
        turns = _completed_event_grammar(
            loaded.events,
            player_kind=player_kind,
            oracle_mode=oracle_mode,
            max_actions=max_actions,
            max_repair_attempts=max_repair,
            terminal_position=failed_start,
            termination_kind=None,
        )
        if player_kind == "llm":
            next_call = 1 + sum(
                1 + (1 if turn.repair_completion is not None else 0)
                for turn in turns
            )
            failed_attempt = _failed_attempt_event_grammar(
                loaded.events,
                start_position=failed_start,
                terminal_position=terminal_position,
                player_turn=len(turns) + 1,
                call_index=next_call,
                max_repair_attempts=max_repair,
            )
        elif failed_start != terminal_position:
            raise RunReplayError("custom Player failure contains model events")
    else:
        turns = _completed_event_grammar(
            loaded.events,
            player_kind=player_kind,
            oracle_mode=oracle_mode,
            max_actions=max_actions,
            max_repair_attempts=max_repair,
            terminal_position=terminal_position,
            termination_kind=termination_kind,
        )
    parsed_actions, parse_failures, repair_count = _replay_parsers(
        turns, max_action_bytes
    )
    failed_primary_error = None
    failed_final_error = None
    if failed_attempt is not None:
        (
            failed_primary_error,
            failed_final_error,
            failed_repair_count,
        ) = _replay_failed_attempt(
            failed_attempt,
            max_action_bytes=max_action_bytes,
        )
        repair_count += failed_repair_count
    canonical_oracle = CaseOracle(case.definition, case.world_model)
    replay_oracle = _ReplayOracle()
    effective_oracle: Oracle = (
        replay_oracle if oracle_mode == "llm_case" else canonical_oracle
    )
    episode = Episode(
        case,
        oracle=effective_oracle,
        observation_budget=observation_budget,
        initial_attempts_used=initial_attempts_used,
        require_budget_exhaustion=require_budget_exhaustion,
    )
    prompt_requests_checked = 0
    oracle_turn = 0
    replayed_outcome: Optional[EpisodeOutcome] = None
    for expected_index, turn in enumerate(turns, start=1):
        view_before = episode.view()
        action_event = _payload(turn.action, "action.decoded")
        transition = _payload(turn.transition, "protocol.transition")

        if player_kind == "llm":
            if turn.primary_request is None or turn.primary_completion is None:
                raise RunReplayError("LLM turn lacks its primary request/completion")
            expected_primary = generation_request_to_payload(
                build_generation_request(
                    view_before,
                    player_turn=expected_index,
                    config=config,
                    purpose="next_action",
                    prompt_version=player_prompt_version,
                )
            )
            if _payload(turn.primary_request, "model.requested").get(
                "request"
            ) != expected_primary:
                raise RunReplayError("primary logical prompt/request differs")
            prompt_requests_checked += 1
            if turn.repair_request is not None:
                first_response = _response_from_completion(
                    turn.primary_completion, request_event=turn.primary_request
                )
                expected_repair = generation_request_to_payload(
                    build_generation_request(
                        view_before,
                        player_turn=expected_index,
                        config=config,
                        purpose="repair_action",
                        prompt_version=player_prompt_version,
                        invalid_output=first_response.text,
                        wire_error=parse_failures[expected_index],
                    )
                )
                if _payload(turn.repair_request, "model.requested").get(
                    "request"
                ) != expected_repair:
                    raise RunReplayError("second-generation logical request differs")
                prompt_requests_checked += 1

        raw_action = action_event.get("action")
        try:
            action = player_action_from_payload(
                raw_action, max_bytes=max_action_bytes
            )
        except WireDecodeError as exc:
            raise RunReplayError("logged action is no longer decodable: %s" % exc) from exc
        if player_kind == "llm":
            if player_action_to_payload(parsed_actions[expected_index]) != raw_action:
                raise RunReplayError("adapter parse and runner action differ")

        rejected_turn = transition.get("outcome_kind") == "protocol_rejected"
        if (
            oracle_mode == "llm_case"
            and action.kind == "experiment"
            and not rejected_turn
        ):
            if action.experiment is None:
                raise RunReplayError("experiment action lacks a proposal")
            if (
                turn.oracle_request is None
                or turn.oracle_completion is None
                or turn.oracle_parsed is None
            ):
                raise RunReplayError("experiment lacks recorded Oracle model events")
            oracle_turn += 1
            try:
                authoritative = canonical_oracle.respond(action.experiment)
            except Exception as exc:
                raise RunReplayError(
                    "supplied world model rejected Oracle proposal %d: %s"
                    % (expected_index, type(exc).__name__)
                ) from exc
            expected_oracle_request = generation_request_to_payload(
                build_oracle_generation_request(
                    case.definition,
                    action.experiment,
                    authoritative,
                    oracle_turn=oracle_turn,
                    config=oracle_config,
                    prompt_version=oracle_prompt_version,
                )
            )
            if _payload(
                turn.oracle_request, "oracle.model.requested"
            ).get("request") != expected_oracle_request:
                raise RunReplayError("Oracle logical prompt/request differs")
            oracle_completion = _response_from_oracle_completion(
                turn.oracle_completion,
                request_event=turn.oracle_request,
            )
            try:
                oracle_message_from_json(
                    oracle_completion.text,
                    authoritative_message=authoritative.message,
                    max_bytes=oracle_max_output_bytes,
                )
            except WireDecodeError as exc:
                raise RunReplayError(
                    "recorded Oracle completion no longer decodes: %s" % exc
                ) from exc
            # The decoded value is only a checked copy; the replayed response
            # itself remains entirely authoritative.
            visible_response = copy.deepcopy(authoritative)
            parsed_oracle_response = _payload(
                turn.oracle_parsed, "oracle.output.parsed"
            ).get("oracle_response")
            if parsed_oracle_response != oracle_response_to_payload(visible_response):
                raise RunReplayError("Oracle parser replay produced a different response")
            replay_oracle.prepare(action.experiment, visible_response)
            prompt_requests_checked += 1
        elif any(
            event is not None
            for event in (
                turn.oracle_request,
                turn.oracle_completion,
                turn.oracle_parsed,
            )
        ):
            raise RunReplayError("non-experiment turn contains Oracle model events")

        attempts_before = episode.view().attempts_used
        if rejected_turn:
            try:
                episode.apply(action)
            except EpisodeProtocolError as exc:
                if transition.get("error") != _error_payload(exc):
                    raise RunReplayError("recorded protocol rejection differs")
                if transition.get("attempts_used_before") != attempts_before:
                    raise RunReplayError(
                        "attempts-before differs at rejected action %d"
                        % expected_index
                    )
                if transition.get("attempts_used_after") != episode.view().attempts_used:
                    raise RunReplayError(
                        "attempts-after differs at rejected action %d"
                        % expected_index
                    )
                expected_termination = EpisodeTermination(
                    kind=TerminationKind.ACTION_REJECTED,
                    code=exc.code,
                    message=str(exc),
                    action_index=expected_index,
                )
                if recorded_termination != expected_termination:
                    raise RunReplayError("terminal rejection differs from protocol")
                replayed_outcome = episode.terminate_player_failure(
                    expected_termination,
                    candidate_action=action,
                )
            except Exception as exc:
                raise RunReplayError(
                    "supplied runtime failed at rejected action %d: %s"
                    % (expected_index, type(exc).__name__)
                ) from exc
            else:
                raise RunReplayError("recorded rejected action now succeeds")
            continue
        try:
            response: Optional[OracleResponse] = episode.apply(action)
        except Exception as exc:
            raise RunReplayError(
                "supplied runtime rejected action %d: %s"
                % (expected_index, type(exc).__name__)
            ) from exc
        if transition.get("attempts_used_before") != attempts_before:
            raise RunReplayError("attempts-before differs at action %d" % expected_index)
        if transition.get("attempts_used_after") != episode.view().attempts_used:
            raise RunReplayError("attempts-after differs at action %d" % expected_index)
        outcome = transition.get("outcome")
        if response is not None:
            if transition.get("outcome_kind") != "experiment_evidence":
                raise RunReplayError("experiment transition has an invalid kind")
            if not isinstance(outcome, dict) or outcome.get(
                "oracle_response"
            ) != oracle_response_to_payload(response):
                raise RunReplayError(
                    "Oracle response differs at action %d" % expected_index
                )
        else:
            if transition.get("outcome_kind") != "final_evaluation":
                raise RunReplayError("final transition has an invalid kind")
            expected_outcome = {
                "evaluation": evaluation_result_to_payload(
                    episode.result.evaluation
                ),
                "trajectory_scores": dict(episode.result.trajectory_scores),
                "protocol_violations": [
                    {"code": item.code, "message": item.message}
                    for item in episode.result.protocol_violations
                ],
            }
            if not isinstance(outcome, dict) or outcome != expected_outcome:
                raise RunReplayError("evaluation differs at final action")

    if failed_attempt is not None:
        view_before = episode.view()
        failed_index = len(turns) + 1
        expected_primary = generation_request_to_payload(
            build_generation_request(
                view_before,
                player_turn=failed_index,
                config=config,
                purpose="next_action",
                prompt_version=player_prompt_version,
            )
        )
        if _payload(failed_attempt.primary_request, "model.requested").get(
            "request"
        ) != expected_primary:
            raise RunReplayError("failed-turn logical prompt/request differs")
        prompt_requests_checked += 1
        if failed_attempt.repair_request is not None:
            if failed_primary_error is None:
                raise RunReplayError("failed repair has no primary parser error")
            first_response = _response_from_completion(
                failed_attempt.primary_completion,
                request_event=failed_attempt.primary_request,
            )
            expected_repair = generation_request_to_payload(
                build_generation_request(
                    view_before,
                    player_turn=failed_index,
                    config=config,
                    purpose="repair_action",
                    prompt_version=player_prompt_version,
                    invalid_output=first_response.text,
                    wire_error=failed_primary_error,
                )
            )
            if _payload(failed_attempt.repair_request, "model.requested").get(
                "request"
            ) != expected_repair:
                raise RunReplayError("failed-turn second request differs")
            prompt_requests_checked += 1

    if termination_kind == TerminationKind.SUBMITTED:
        if not episode.finished:
            raise RunReplayError("submitted run did not finish during replay")
        replayed_outcome = episode.outcome
    elif termination_kind == TerminationKind.PLAYER_OUTPUT_INVALID:
        if episode.finished or recorded_termination is None:
            raise RunReplayError("undecodable run has an invalid episode state")
        if recorded_termination.action_index != len(turns) + 1:
            raise RunReplayError("undecodable terminal action index differs")
        if player_kind == "llm":
            if failed_final_error is None:
                raise RunReplayError("undecodable run has no verified decoder error")
            attempts = 1 + (
                1
                if failed_attempt is not None
                and failed_attempt.repair_completion is not None
                else 0
            )
            expected_termination = EpisodeTermination(
                kind=TerminationKind.PLAYER_OUTPUT_INVALID,
                code=failed_final_error.code,
                message=str(AdapterOutputError(failed_final_error, attempts=attempts)),
                action_index=len(turns) + 1,
                generation_attempts=attempts,
            )
            if recorded_termination != expected_termination:
                raise RunReplayError("terminal decoder failure differs from model events")
        replayed_outcome = episode.terminate_player_failure(recorded_termination)
    elif termination_kind == TerminationKind.ACTION_LIMIT:
        if episode.finished or recorded_termination is None:
            raise RunReplayError("action-limit run has an invalid episode state")
        expected_termination = EpisodeTermination(
            kind=TerminationKind.ACTION_LIMIT,
            code="max_actions_reached",
            message="Player did not commit within max_actions.",
            action_index=max_actions,
        )
        if recorded_termination != expected_termination:
            raise RunReplayError("terminal action limit differs from policy")
        replayed_outcome = episode.terminate_player_failure(expected_termination)
    elif termination_kind == TerminationKind.ACTION_REJECTED:
        if replayed_outcome is None or not episode.finished:
            raise RunReplayError("rejected run did not terminate during replay")
    else:
        raise RunReplayError("terminal kind is unavailable")

    if replayed_outcome is None:
        raise RunReplayError("replay produced no terminal outcome")
    if terminal_record is not None and terminal_record != _terminal_payload(
        replayed_outcome
    ):
        raise RunReplayError("recorded terminal outcome differs from replay")
    if ended.get("event_count_including_this") != len(loaded.events):
        raise RunReplayError("final event count differs")
    if player_kind == "llm" and ended.get("llm_stats") != _expected_llm_stats(
        turns,
        failed_attempt,
    ):
        raise RunReplayError("final LLM statistics differ from model events")
    if player_kind == "custom" and ended.get("llm_stats") is not None:
        raise RunReplayError("custom-player run contains LLM statistics")
    if oracle_mode == "llm_case" and ended.get(
        "oracle_llm_stats"
    ) != _expected_oracle_llm_stats(turns):
        raise RunReplayError("final Oracle LLM statistics differ from model events")
    if oracle_mode == "case" and ended.get("oracle_llm_stats") is not None:
        raise RunReplayError("case-Oracle run contains Oracle LLM statistics")
    return ReplayReport(
        run_id=loaded.run_id,
        event_count=len(loaded.events),
        action_count=len(turns),
        parser_actions_checked=len(parsed_actions),
        failed_parses_checked=(
            len(parse_failures)
            + (
                1
                if failed_attempt is not None
                and failed_attempt.primary_parse_failure is not None
                else 0
            )
            + (
                1
                if failed_attempt is not None
                and failed_attempt.repair_parse_failure is not None
                else 0
            )
        ),
        format_regenerations_checked=repair_count,
        prompt_requests_checked=prompt_requests_checked,
        outcome=replayed_outcome,
    )


__all__ = [
    "JSONLRunLog",
    "LoadedRunLog",
    "LoggedEpisodeRun",
    "ReplayReport",
    "RunLogError",
    "RunLogFormatError",
    "RunReplayError",
    "load_run_log",
    "replay_run_log",
    "run_llm_episode",
    "run_logged_episode",
]
