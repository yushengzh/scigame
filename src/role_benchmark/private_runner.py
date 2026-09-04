"""Player-side runner for the isolated private evaluation service."""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Optional

from .llm import (
    AdapterOutputError,
    DEFAULT_PLAYER_PROMPT_VERSION,
    GenerationConfig,
    LLMPlayerBackend,
    LLMPlayerStats,
    ModelTransportError,
    PLAYER_PROMPT_VERSION_V1,
    PLAYER_PROMPT_VERSION_V2_JSON_HARDENED,
    TextGenerationBackend,
)
from .private_eval import PrivateEvaluationError
from .private_http import PrivateEvaluationHTTPClient, PrivateSessionState
from .runlog import JSONLRunLog
from .wire import (
    DEFAULT_MAX_ACTION_BYTES,
    PLAYER_ACTION_SCHEMA,
    canonical_json_dumps,
    episode_view_to_payload,
    oracle_response_to_payload,
    player_action_to_payload,
    strict_json_loads,
)


PRIVATE_ISOLATED_EVALUATION_PROFILE = "private_isolated_evaluation"


@dataclass(frozen=True)
class PrivateEpisodeReceipt:
    """Unscored receipt returned to the Player process."""

    client_run_id: str
    session_id: str
    receipt_id: str
    log_path: str
    llm_stats: LLMPlayerStats


def _stats_payload(stats: LLMPlayerStats) -> Mapping[str, Any]:
    return {
        "player_turns": stats.player_turns,
        "primary_calls": stats.primary_calls,
        "repair_calls": stats.repair_calls,
        "first_pass_valid_actions": stats.first_pass_valid_actions,
        "decoded_actions": stats.decoded_actions,
        "input_tokens": stats.input_tokens,
        "output_tokens": stats.output_tokens,
    }


def _stable_request_id(
    client_run_id: str, revision: int, kind: str, payload: Mapping[str, Any]
) -> str:
    material = canonical_json_dumps(
        {
            "client_run_id": client_run_id,
            "revision": revision,
            "kind": kind,
            "payload": payload,
        }
    )
    return "turn-" + hashlib.sha256(material.encode("utf-8")).hexdigest()


def _recover_or_retry_action(
    client: PrivateEvaluationHTTPClient,
    state: PrivateSessionState,
    action: Any,
    request_id: str,
) -> PrivateSessionState:
    try:
        return client.submit_action(state, action, request_id=request_id)
    except PrivateEvaluationError as exc:
        if exc.code != "private_transport_error":
            raise
    recovered = client.resume_session(state.session_id, state.client_run_id)
    if recovered.revision == state.revision + 1:
        return recovered
    if recovered.revision != state.revision or recovered.terminal:
        raise PrivateEvaluationError(
            "recovery_conflict", "private session changed during transport recovery", status=409
        )
    return client.submit_action(state, action, request_id=request_id)


def _recover_or_retry_failure(
    client: PrivateEvaluationHTTPClient,
    state: PrivateSessionState,
    *,
    request_id: str,
    code: str,
    message: str,
    generation_attempts: int,
) -> PrivateSessionState:
    try:
        return client.record_player_output_invalid(
            state,
            request_id=request_id,
            code=code,
            message=message,
            generation_attempts=generation_attempts,
        )
    except PrivateEvaluationError as exc:
        if exc.code != "private_transport_error":
            raise
    recovered = client.resume_session(state.session_id, state.client_run_id)
    if recovered.revision == state.revision + 1 and recovered.terminal:
        return recovered
    if recovered.revision != state.revision or recovered.terminal:
        raise PrivateEvaluationError(
            "recovery_conflict", "private session changed during transport recovery", status=409
        )
    return client.record_player_output_invalid(
        state,
        request_id=request_id,
        code=code,
        message=message,
        generation_attempts=generation_attempts,
    )


def run_private_llm_episode(
    backend: TextGenerationBackend,
    client: PrivateEvaluationHTTPClient,
    log_path: str,
    *,
    config: Optional[GenerationConfig] = None,
    player_prompt_version: str = DEFAULT_PLAYER_PROMPT_VERSION,
    max_repair_attempts: int = 0,
    max_action_bytes: int = DEFAULT_MAX_ACTION_BYTES,
    client_run_id: Optional[str] = None,
    run_metadata: Optional[Mapping[str, Any]] = None,
    durable_log: bool = True,
) -> PrivateEpisodeReceipt:
    """Run one private episode without importing truth, scorer, or case pack.

    The returned object deliberately has no score.  Administrative results are
    released separately only after the service has completed the whole pack.
    """

    if not isinstance(client, PrivateEvaluationHTTPClient):
        raise ValueError("client must be PrivateEvaluationHTTPClient")
    if not callable(getattr(backend, "generate", None)):
        raise ValueError("backend must provide a callable generate method")
    if config is not None and not isinstance(config, GenerationConfig):
        raise ValueError("config must be GenerationConfig or None")
    if player_prompt_version not in (
        PLAYER_PROMPT_VERSION_V1,
        PLAYER_PROMPT_VERSION_V2_JSON_HARDENED,
    ):
        raise ValueError(
            "unsupported Player prompt_version %r" % player_prompt_version
        )
    if isinstance(max_repair_attempts, bool) or max_repair_attempts not in (0, 1):
        raise ValueError("max_repair_attempts must be 0 or 1")
    if (
        isinstance(max_action_bytes, bool)
        or not isinstance(max_action_bytes, int)
        or max_action_bytes < 1
        or max_action_bytes > DEFAULT_MAX_ACTION_BYTES
    ):
        raise ValueError(
            "max_action_bytes must be between 1 and %d" % DEFAULT_MAX_ACTION_BYTES
        )
    if run_metadata is not None and not isinstance(run_metadata, Mapping):
        raise ValueError("run_metadata must be a mapping or None")
    if not isinstance(durable_log, bool):
        raise ValueError("durable_log must be boolean")
    metadata = strict_json_loads(canonical_json_dumps(dict(run_metadata or {})))
    resolved_run_id = client_run_id or uuid.uuid4().hex

    with JSONLRunLog(
        log_path, run_id=resolved_run_id, durable=durable_log
    ) as log:
        player = LLMPlayerBackend(
            backend,
            config=config,
            max_repair_attempts=max_repair_attempts,
            max_action_bytes=max_action_bytes,
            evaluation_profile=PRIVATE_ISOLATED_EVALUATION_PROFILE,
            prompt_version=player_prompt_version,
            event_sink=log.append,
        )
        log.append(
            "run.started",
            {
                "evaluation_profile": PRIVATE_ISOLATED_EVALUATION_PROFILE,
                "case": None,
                "action_schema": PLAYER_ACTION_SCHEMA,
                "llm_config": player.run_config,
                "policy": {"durable_log": durable_log, "result_visibility": "embargoed"},
                "run_metadata": metadata,
            },
        )
        try:
            try:
                state = client.create_session(resolved_run_id)
            except PrivateEvaluationError as exc:
                if exc.code != "private_transport_error":
                    raise
                state = client.create_session(resolved_run_id)
        except PrivateEvaluationError as exc:
            log.append(
                "run.ended",
                {
                    "status": "infrastructure_error",
                    "stop_reason": "private_service_error",
                    "error": {"code": exc.code, "message": exc.message},
                    "llm_stats": _stats_payload(player.stats),
                    "event_count_including_this": log.event_count + 1,
                },
            )
            raise
        log.append(
            "private.session.started",
            {
                "case": (
                    episode_view_to_payload(state.view)["case"]
                    if state.view is not None
                    else None
                ),
                "session_id": state.session_id,
                "resumed_revision": state.revision,
                "status": state.status,
            },
        )
        if state.terminal:
            log.append(
                "run.ended",
                {
                    "status": "submitted_to_trusted_evaluator",
                    "receipt_id": state.receipt_id,
                    "llm_stats": _stats_payload(player.stats),
                    "event_count_including_this": log.event_count + 1,
                },
            )
        else:
            while not state.terminal:
                if state.view is None:
                    raise PrivateEvaluationError(
                        "invalid_service_response", "active session has no public view", status=502
                    )
                try:
                    action = player.next_action(state.view)
                except AdapterOutputError as exc:
                    failure_payload = {
                        "code": exc.wire_error.code,
                        "message": str(exc),
                        "generation_attempts": exc.attempts,
                    }
                    request_id = _stable_request_id(
                        resolved_run_id, state.revision, "failure", failure_payload
                    )
                    try:
                        state = _recover_or_retry_failure(
                            client,
                            state,
                            request_id=request_id,
                            code=exc.wire_error.code,
                            message=str(exc),
                            generation_attempts=exc.attempts,
                        )
                    except PrivateEvaluationError as service_error:
                        log.append(
                            "run.ended",
                            {
                                "status": "infrastructure_error",
                                "stop_reason": "private_service_error",
                                "error": {
                                    "code": service_error.code,
                                    "message": service_error.message,
                                },
                                "llm_stats": _stats_payload(player.stats),
                                "event_count_including_this": log.event_count + 1,
                            },
                        )
                        raise
                    log.append(
                        "private.transition",
                        {
                            "request_id": request_id,
                            "revision": state.revision,
                            "status": state.status,
                            "receipt_id": state.receipt_id,
                            "player_failure": failure_payload,
                        },
                    )
                    break
                except ModelTransportError as exc:
                    log.append(
                        "run.ended",
                        {
                            "status": "infrastructure_error",
                            "stop_reason": "model_transport_error",
                            "error": {"type": type(exc).__name__, "message": str(exc)},
                            "llm_stats": _stats_payload(player.stats),
                            "event_count_including_this": log.event_count + 1,
                        },
                    )
                    raise

                action_payload = player_action_to_payload(action)
                request_id = _stable_request_id(
                    resolved_run_id, state.revision, "action", action_payload
                )
                log.append(
                    "private.action.sent",
                    {
                        "request_id": request_id,
                        "revision": state.revision,
                        "action": action_payload,
                    },
                )
                try:
                    state = _recover_or_retry_action(client, state, action, request_id)
                except PrivateEvaluationError as exc:
                    log.append(
                        "run.ended",
                        {
                            "status": "infrastructure_error",
                            "stop_reason": "private_service_error",
                            "error": {"code": exc.code, "message": exc.message},
                            "llm_stats": _stats_payload(player.stats),
                            "event_count_including_this": log.event_count + 1,
                        },
                    )
                    raise
                log.append(
                    "private.transition",
                    {
                        "request_id": request_id,
                        "revision": state.revision,
                        "status": state.status,
                        "oracle_response": (
                            oracle_response_to_payload(state.oracle_response)
                            if state.oracle_response is not None
                            else None
                        ),
                        "view": (
                            episode_view_to_payload(state.view)
                            if state.view is not None
                            else None
                        ),
                        "receipt_id": state.receipt_id,
                    },
                )
            log.append(
                "run.ended",
                {
                    "status": "submitted_to_trusted_evaluator",
                    "receipt_id": state.receipt_id,
                    "llm_stats": _stats_payload(player.stats),
                    "event_count_including_this": log.event_count + 1,
                },
            )

    if state.receipt_id is None:
        raise PrivateEvaluationError(
            "invalid_service_response", "terminal private session has no receipt", status=502
        )
    return PrivateEpisodeReceipt(
        client_run_id=resolved_run_id,
        session_id=state.session_id,
        receipt_id=state.receipt_id,
        log_path=str(Path(log_path).resolve()),
        llm_stats=player.stats,
    )


__all__ = [
    "PRIVATE_ISOLATED_EVALUATION_PROFILE",
    "PrivateEpisodeReceipt",
    "run_private_llm_episode",
]
