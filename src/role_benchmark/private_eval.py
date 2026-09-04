"""Trusted-service core for private benchmark evaluation.

This module is intentionally transport-neutral.  A deployment loads a private
case pack only inside the trusted service process, while an untrusted Player
process receives serialized :class:`EpisodeView` values and sends serialized
``PlayerAction`` values.  Per-session scientific results are retained in the
trusted SQLite store and are available only through the administrative export.
"""

from __future__ import annotations

import copy
import hashlib
import hmac
import importlib
import os
import secrets
import sqlite3
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence, Tuple

from .episode import Episode, EpisodeProtocolError
from .models import (
    EpisodeOutcome,
    EpisodeTermination,
    PlayerAction,
    TerminationKind,
)
from .protocols import BenchmarkCase
from .wire import (
    DEFAULT_MAX_ACTION_BYTES,
    DEFAULT_MAX_JSON_BYTES,
    WireDecodeError,
    canonical_json_dumps,
    case_definition_to_payload,
    episode_view_to_payload,
    evaluation_result_to_payload,
    experiment_turn_to_payload,
    final_submission_to_payload,
    oracle_response_to_payload,
    player_action_from_payload,
    player_action_to_payload,
    strict_json_loads,
)


PRIVATE_SESSION_CREATE_SCHEMA = "role_benchmark.private_session_create.v1"
PRIVATE_SESSION_SCHEMA = "role_benchmark.private_session.v1"
PRIVATE_TURN_SCHEMA = "role_benchmark.private_turn.v1"
PRIVATE_TURN_RESULT_SCHEMA = "role_benchmark.private_turn_result.v1"
PRIVATE_FAILURE_SCHEMA = "role_benchmark.private_player_failure.v1"
PRIVATE_RESULT_EXPORT_SCHEMA = "role_benchmark.private_result_export.v1"
PRIVATE_STORE_SCHEMA_VERSION = "1"


class PrivateEvaluationError(RuntimeError):
    """Stable error raised at the private-service boundary."""

    def __init__(self, code: str, message: str, *, status: int = 400) -> None:
        if not isinstance(code, str) or not code.strip():
            raise ValueError("private evaluation error code must be non-empty")
        if not isinstance(message, str) or not message.strip():
            raise ValueError("private evaluation error message must be non-empty")
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


@dataclass(frozen=True)
class PrivateEvaluationUnit:
    """One service-only assignment in a private evaluation pack.

    ``unit_id`` and ``private_metadata`` never appear in Player-facing
    responses.  ``forbidden_public_tokens`` is a fail-closed author check for
    assignment labels, truth names, or other known private markers.
    """

    unit_id: str
    case: BenchmarkCase
    client_run_id: str
    observation_budget: Optional[int] = None
    initial_attempts_used: int = 0
    require_budget_exhaustion: bool = False
    max_actions: int = 100
    private_metadata: Mapping[str, Any] = field(default_factory=dict)
    forbidden_public_tokens: Tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.unit_id, str) or not self.unit_id.strip():
            raise ValueError("private unit_id must be non-empty text")
        if not isinstance(self.client_run_id, str) or not self.client_run_id.strip():
            raise ValueError("private client_run_id must be non-empty text")
        if len(self.client_run_id) > 256:
            raise ValueError("private client_run_id exceeds 256 characters")
        if not isinstance(self.case, BenchmarkCase):
            raise ValueError("private unit case must be a BenchmarkCase")
        if (
            isinstance(self.max_actions, bool)
            or not isinstance(self.max_actions, int)
            or self.max_actions < 1
        ):
            raise ValueError("private unit max_actions must be positive")
        if not isinstance(self.private_metadata, Mapping):
            raise ValueError("private_metadata must be a mapping")
        if not isinstance(self.forbidden_public_tokens, tuple):
            raise ValueError("forbidden_public_tokens must be a tuple")
        canonical_json_dumps(dict(self.private_metadata))
        object.__setattr__(
            self, "private_metadata", copy.deepcopy(dict(self.private_metadata))
        )
        object.__setattr__(self, "forbidden_public_tokens", tuple(self.forbidden_public_tokens))
        for token in self.forbidden_public_tokens:
            if not isinstance(token, str) or not token.strip():
                raise ValueError("forbidden public tokens must be non-empty text")
        # This validates all method-specific budget invariants without exposing
        # or executing the private truth.
        episode = Episode(
            self.case,
            observation_budget=self.observation_budget,
            initial_attempts_used=self.initial_attempts_used,
            require_budget_exhaustion=self.require_budget_exhaustion,
        )
        initial_view_text = canonical_json_dumps(
            episode_view_to_payload(episode.view())
        )
        if len(initial_view_text.encode("utf-8")) > DEFAULT_MAX_JSON_BYTES:
            raise ValueError("private unit initial public view exceeds the wire limit")
        public_text = canonical_json_dumps(
            case_definition_to_payload(self.case.definition)
        ).casefold()
        leaked = [
            token for token in self.forbidden_public_tokens
            if token.casefold() in public_text
        ]
        if leaked:
            raise ValueError(
                "private marker appears in public CaseDefinition: %s"
                % ", ".join(repr(item) for item in leaked)
            )


@dataclass(frozen=True)
class PrivateCasePack:
    """Immutable ordered case pack loaded only by the trusted service."""

    pack_id: str
    release_id: str
    artifact_digest: str
    units: Tuple[PrivateEvaluationUnit, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.pack_id, str) or not self.pack_id.strip():
            raise ValueError("private pack_id must be non-empty text")
        if not isinstance(self.release_id, str) or not self.release_id.strip():
            raise ValueError("private release_id must be non-empty text")
        if (
            not isinstance(self.artifact_digest, str)
            or len(self.artifact_digest) != 64
            or any(
                character not in "0123456789abcdef"
                for character in self.artifact_digest
            )
        ):
            raise ValueError(
                "private artifact_digest must be a lowercase SHA-256 digest"
            )
        if not self.units:
            raise ValueError("a private case pack must contain at least one unit")
        if not isinstance(self.units, tuple) or not all(
            isinstance(unit, PrivateEvaluationUnit) for unit in self.units
        ):
            raise ValueError("private pack units must be a tuple of PrivateEvaluationUnit")
        ids = [unit.unit_id for unit in self.units]
        if len(ids) != len(set(ids)):
            raise ValueError("private unit_id values must be unique")
        run_ids = [unit.client_run_id for unit in self.units]
        if len(run_ids) != len(set(run_ids)):
            raise ValueError("private client_run_id values must be unique")

    @property
    def identity_digest(self) -> str:
        payload = {
            "pack_id": self.pack_id,
            "release_id": self.release_id,
            "artifact_digest": self.artifact_digest,
            "unit_ids": [unit.unit_id for unit in self.units],
            "client_run_ids": [unit.client_run_id for unit in self.units],
        }
        return hashlib.sha256(canonical_json_dumps(payload).encode("utf-8")).hexdigest()


def load_private_case_pack(factory_spec: str) -> PrivateCasePack:
    """Load ``module:factory`` in the trusted service process.

    The factory module is not copied, imported, or named in any Player-facing
    payload.  Formal deployments place it on a service-only import path.
    """

    if not isinstance(factory_spec, str) or factory_spec.count(":") != 1:
        raise ValueError("private pack factory must use module:callable syntax")
    module_name, attribute = (part.strip() for part in factory_spec.split(":"))
    if not module_name or not attribute:
        raise ValueError("private pack factory must use module:callable syntax")
    module = importlib.import_module(module_name)
    factory = getattr(module, attribute, None)
    if not callable(factory):
        raise ValueError("private pack factory is not callable")
    pack = factory()
    if not isinstance(pack, PrivateCasePack):
        raise ValueError("private pack factory must return PrivateCasePack")
    return pack


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _request_hash(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        canonical_json_dumps(payload).encode("utf-8")
    ).hexdigest()


def _require_object(
    value: Any,
    *,
    keys: Sequence[str],
    label: str,
) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        raise PrivateEvaluationError("invalid_request", "%s must be an object" % label)
    if set(value) != set(keys):
        raise PrivateEvaluationError(
            "invalid_request",
            "%s keys do not match the protocol" % label,
        )
    return value


def _require_text(value: Any, label: str, *, maximum: int = 256) -> str:
    if not isinstance(value, str) or not value.strip():
        raise PrivateEvaluationError(
            "invalid_request", "%s must be non-empty text" % label
        )
    if len(value) > maximum:
        raise PrivateEvaluationError(
            "invalid_request", "%s exceeds %d characters" % (label, maximum)
        )
    return value


def _outcome_payload(outcome: EpisodeOutcome) -> Mapping[str, Any]:
    """Serialize the complete service-only terminal record."""

    return {
        "case_id": outcome.case_id,
        "track": outcome.track.value,
        "attempts_used": outcome.attempts_used,
        "turns": [experiment_turn_to_payload(item) for item in outcome.turns],
        "termination": {
            "kind": outcome.termination.kind.value,
            "code": outcome.termination.code,
            "message": outcome.termination.message,
            "action_index": outcome.termination.action_index,
            "generation_attempts": outcome.termination.generation_attempts,
        },
        "evaluation": evaluation_result_to_payload(outcome.evaluation),
        "trajectory_scores": dict(outcome.trajectory_scores),
        "final_portfolio": (
            player_action_to_payload(
                PlayerAction.submit_final(
                    outcome.final_portfolio,
                    outcome.final_submission,
                )
            )["portfolio"]
            if outcome.final_portfolio is not None
            and outcome.final_submission is not None
            else None
        ),
        "final_submission": (
            final_submission_to_payload(outcome.final_submission)
            if outcome.final_submission is not None
            else None
        ),
        "candidate_action": (
            player_action_to_payload(outcome.candidate_action)
            if outcome.candidate_action is not None
            else None
        ),
        "protocol_violations": [
            {"code": item.code, "message": item.message}
            for item in outcome.protocol_violations
        ],
    }


class PrivateEvaluationService:
    """Persistent trusted evaluator with least-disclosure session responses."""

    def __init__(self, pack: PrivateCasePack, database_path: str) -> None:
        if not isinstance(pack, PrivateCasePack):
            raise ValueError("pack must be PrivateCasePack")
        path = Path(database_path)
        if path.name in {"", ".", ".."}:
            raise ValueError("database_path must name a SQLite file")
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.is_symlink():
            raise ValueError("database_path must not be a symbolic link")
        self._pack = pack
        self._path = path.resolve()
        self._lock = threading.RLock()
        self._initialize()

    @property
    def database_path(self) -> str:
        return str(self._path)

    @property
    def remaining_units(self) -> int:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT COUNT(*) FROM units WHERE status = 'available'"
            ).fetchone()
        return int(row[0])

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(str(self._path), timeout=30.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA synchronous = FULL")
        for candidate in (
            self._path,
            Path(str(self._path) + "-wal"),
            Path(str(self._path) + "-shm"),
        ):
            if candidate.exists():
                os.chmod(candidate, 0o600)
        return connection

    def _initialize(self) -> None:
        with self._lock, self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS metadata (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS units (
                    ordinal INTEGER PRIMARY KEY,
                    unit_id TEXT NOT NULL UNIQUE,
                    client_run_id TEXT NOT NULL UNIQUE,
                    status TEXT NOT NULL CHECK(status IN ('available','active','terminal')),
                    session_id TEXT UNIQUE
                );
                CREATE TABLE IF NOT EXISTS sessions (
                    session_id TEXT PRIMARY KEY,
                    ordinal INTEGER NOT NULL UNIQUE REFERENCES units(ordinal),
                    client_run_id TEXT NOT NULL UNIQUE,
                    create_request_id TEXT NOT NULL UNIQUE,
                    create_request_hash TEXT NOT NULL,
                    session_token_hash TEXT NOT NULL,
                    revision INTEGER NOT NULL,
                    action_count INTEGER NOT NULL,
                    status TEXT NOT NULL CHECK(status IN ('active','terminal')),
                    receipt_id TEXT UNIQUE,
                    outcome_json TEXT
                );
                CREATE TABLE IF NOT EXISTS requests (
                    session_id TEXT NOT NULL REFERENCES sessions(session_id),
                    request_id TEXT NOT NULL,
                    request_hash TEXT NOT NULL,
                    request_kind TEXT NOT NULL CHECK(request_kind IN ('action','failure')),
                    request_json TEXT NOT NULL,
                    response_json TEXT NOT NULL,
                    revision_after INTEGER NOT NULL,
                    PRIMARY KEY(session_id, request_id),
                    UNIQUE(session_id, revision_after)
                );
                """
            )
            connection.execute("BEGIN IMMEDIATE")
            expected = {
                "schema_version": PRIVATE_STORE_SCHEMA_VERSION,
                "pack_identity_digest": self._pack.identity_digest,
            }
            existing = {
                row["key"]: row["value"]
                for row in connection.execute("SELECT key, value FROM metadata")
            }
            if existing:
                if existing != expected:
                    raise ValueError(
                        "private state database belongs to a different pack or schema"
                    )
                rows = list(
                    connection.execute(
                        "SELECT ordinal, unit_id, client_run_id FROM units ORDER BY ordinal"
                    )
                )
                if [row["unit_id"] for row in rows] != [
                    unit.unit_id for unit in self._pack.units
                ]:
                    raise ValueError("private state unit order does not match the pack")
                if [row["client_run_id"] for row in rows] != [
                    unit.client_run_id for unit in self._pack.units
                ]:
                    raise ValueError("private state assignments do not match the pack")
                return
            connection.executemany(
                "INSERT INTO metadata(key, value) VALUES (?, ?)",
                tuple(expected.items()),
            )
            connection.executemany(
                "INSERT INTO units(ordinal, unit_id, client_run_id, status) "
                "VALUES (?, ?, ?, 'available')",
                (
                    (index, unit.unit_id, unit.client_run_id)
                    for index, unit in enumerate(self._pack.units, start=1)
                ),
            )

    def _unit(self, ordinal: int) -> PrivateEvaluationUnit:
        return self._pack.units[ordinal - 1]

    def _new_episode(self, unit: PrivateEvaluationUnit) -> Episode:
        return Episode(
            unit.case,
            observation_budget=unit.observation_budget,
            initial_attempts_used=unit.initial_attempts_used,
            require_budget_exhaustion=unit.require_budget_exhaustion,
        )

    def _replay_session(
        self,
        connection: sqlite3.Connection,
        session: sqlite3.Row,
    ) -> Episode:
        unit = self._unit(int(session["ordinal"]))
        episode = self._new_episode(unit)
        action_count = 0
        rows = connection.execute(
            "SELECT request_kind, request_json, response_json, revision_after "
            "FROM requests "
            "WHERE session_id = ? ORDER BY revision_after",
            (session["session_id"],),
        )
        for row in rows:
            request = strict_json_loads(row["request_json"])
            if not isinstance(request, dict):
                raise PrivateEvaluationError(
                    "state_corrupt",
                    "stored private request is not an object",
                    status=500,
                )
            oracle_response = None
            revision_after = int(row["revision_after"])
            if request.get("revision") != revision_after - 1:
                raise PrivateEvaluationError(
                    "state_corrupt",
                    "stored private request revision is inconsistent",
                    status=500,
                )
            if row["request_kind"] == "failure":
                failure = request["failure"]
                episode.terminate_player_failure(
                    EpisodeTermination(
                        kind=TerminationKind.PLAYER_OUTPUT_INVALID,
                        code=failure["code"],
                        message=failure["message"],
                        action_index=action_count + 1,
                        generation_attempts=failure["generation_attempts"],
                    )
                )
            else:
                action = player_action_from_payload(request["action"])
                action_count += 1
                try:
                    oracle_response = episode.apply(action)
                except EpisodeProtocolError as exc:
                    episode.terminate_player_failure(
                        EpisodeTermination(
                            kind=TerminationKind.ACTION_REJECTED,
                            code=exc.code,
                            message=str(exc),
                            action_index=action_count,
                        ),
                        candidate_action=action,
                    )
                if action_count >= unit.max_actions and not episode.finished:
                    episode.terminate_player_failure(
                        EpisodeTermination(
                            kind=TerminationKind.ACTION_LIMIT,
                            code="max_actions_reached",
                            message="Player did not commit within max_actions.",
                            action_index=action_count,
                        )
                    )
            stored_response = strict_json_loads(row["response_json"])
            if episode.finished:
                if (
                    not isinstance(stored_response, dict)
                    or not isinstance(stored_response.get("receipt_id"), str)
                    or stored_response
                    != self._terminal_response(
                        session["session_id"],
                        revision_after,
                        stored_response["receipt_id"],
                    )
                ):
                    raise PrivateEvaluationError(
                        "state_corrupt",
                        "stored private terminal response is inconsistent",
                        status=500,
                    )
            elif stored_response != self._active_response(
                session["session_id"], revision_after, episode, oracle_response
            ):
                raise PrivateEvaluationError(
                    "state_corrupt",
                    "private session public transition replay mismatch",
                    status=500,
                )
        if action_count != int(session["action_count"]):
            raise PrivateEvaluationError(
                "state_corrupt", "stored private session action count is inconsistent", status=500
            )
        if episode.finished != (session["status"] == "terminal"):
            raise PrivateEvaluationError(
                "state_corrupt", "stored private session terminal state is inconsistent", status=500
            )
        if episode.finished:
            stored = strict_json_loads(session["outcome_json"])
            if stored != _outcome_payload(episode.outcome):
                raise PrivateEvaluationError(
                    "state_corrupt", "private session outcome replay mismatch", status=500
                )
            if stored_response["receipt_id"] != session["receipt_id"]:
                raise PrivateEvaluationError(
                    "state_corrupt",
                    "private session receipt is inconsistent",
                    status=500,
                )
        return episode

    def create_session(self, request: Any) -> Mapping[str, Any]:
        root = _require_object(
            request,
            keys=("wire_schema", "request_id", "client_run_id", "session_token"),
            label="session request",
        )
        if root["wire_schema"] != PRIVATE_SESSION_CREATE_SCHEMA:
            raise PrivateEvaluationError("unsupported_schema", "unsupported session schema")
        request_id = _require_text(root["request_id"], "request_id")
        client_run_id = _require_text(root["client_run_id"], "client_run_id")
        session_token = _require_text(
            root["session_token"], "session_token", maximum=512
        )
        if len(session_token) < 32:
            raise PrivateEvaluationError(
                "invalid_request", "session_token must contain at least 32 characters"
            )
        request_hash = _request_hash(root)
        with self._lock, self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            priors = list(connection.execute(
                "SELECT * FROM sessions WHERE create_request_id = ? OR client_run_id = ?",
                (request_id, client_run_id),
            ))
            if len(priors) > 1:
                raise PrivateEvaluationError(
                    "idempotency_conflict",
                    "request identity conflicts with an existing session",
                    status=409,
                )
            if priors:
                prior = priors[0]
                if (
                    prior["create_request_id"] != request_id
                    or prior["client_run_id"] != client_run_id
                    or prior["create_request_hash"] != request_hash
                ):
                    raise PrivateEvaluationError(
                        "idempotency_conflict",
                        "request_id was already used with different content",
                        status=409,
                    )
                if not hmac.compare_digest(
                    prior["session_token_hash"], _hash_token(session_token)
                ):
                    raise PrivateEvaluationError(
                        "session_not_found", "private session was not found", status=404
                    )
                unit = self._unit(int(prior["ordinal"]))
                return {
                    "wire_schema": PRIVATE_SESSION_SCHEMA,
                    "session_id": prior["session_id"],
                    "revision": 0,
                    "view": episode_view_to_payload(self._new_episode(unit).view()),
                }
            unit_row = connection.execute(
                "SELECT ordinal FROM units WHERE status = 'available' "
                "AND client_run_id = ?",
                (client_run_id,),
            ).fetchone()
            if unit_row is None:
                raise PrivateEvaluationError(
                    "assignment_unavailable",
                    "no available private assignment matches this run",
                    status=409,
                )
            ordinal = int(unit_row["ordinal"])
            unit = self._unit(ordinal)
            session_id = secrets.token_urlsafe(24)
            response = {
                "wire_schema": PRIVATE_SESSION_SCHEMA,
                "session_id": session_id,
                "revision": 0,
                "view": episode_view_to_payload(self._new_episode(unit).view()),
            }
            if len(canonical_json_dumps(response).encode("utf-8")) > DEFAULT_MAX_JSON_BYTES:
                raise PrivateEvaluationError(
                    "private_contract_error",
                    "private initial public response exceeds the wire size limit",
                    status=500,
                )
            connection.execute(
                "INSERT INTO sessions(session_id, ordinal, client_run_id, "
                "create_request_id, create_request_hash, session_token_hash, "
                "revision, action_count, status) VALUES (?, ?, ?, ?, ?, ?, 0, 0, 'active')",
                (
                    session_id,
                    ordinal,
                    client_run_id,
                    request_id,
                    request_hash,
                    _hash_token(session_token),
                ),
            )
            connection.execute(
                "UPDATE units SET status = 'active', session_id = ? WHERE ordinal = ?",
                (session_id, ordinal),
            )
            return response

    def resume_session(
        self,
        session_id: str,
        session_token: str,
    ) -> Mapping[str, Any]:
        """Return only the current public state or an unreleased receipt."""

        session_id = _require_text(session_id, "session_id")
        session_token = _require_text(session_token, "session_token")
        with self._lock, self._connect() as connection:
            session = self._session(connection, session_id, session_token)
            revision = int(session["revision"])
            if session["status"] == "terminal":
                return self._terminal_response(
                    session_id, revision, session["receipt_id"]
                )
            episode = self._replay_session(connection, session)
            return {
                "wire_schema": PRIVATE_TURN_RESULT_SCHEMA,
                "session_id": session_id,
                "revision": revision,
                "status": "active",
                "oracle_response": None,
                "view": episode_view_to_payload(episode.view()),
                "receipt_id": None,
                "result_released": False,
            }

    def _session(
        self,
        connection: sqlite3.Connection,
        session_id: str,
        session_token: str,
    ) -> sqlite3.Row:
        row = connection.execute(
            "SELECT * FROM sessions WHERE session_id = ?", (session_id,)
        ).fetchone()
        if row is None or not hmac.compare_digest(
            row["session_token_hash"], _hash_token(session_token)
        ):
            raise PrivateEvaluationError(
                "session_not_found", "private session was not found", status=404
            )
        return row

    def _prior_response(
        self,
        connection: sqlite3.Connection,
        session_id: str,
        request_id: str,
        request_hash: str,
    ) -> Optional[Mapping[str, Any]]:
        prior = connection.execute(
            "SELECT request_hash, response_json FROM requests "
            "WHERE session_id = ? AND request_id = ?",
            (session_id, request_id),
        ).fetchone()
        if prior is None:
            return None
        if prior["request_hash"] != request_hash:
            raise PrivateEvaluationError(
                "idempotency_conflict",
                "request_id was already used with different content",
                status=409,
            )
        return strict_json_loads(prior["response_json"])

    def _terminal_response(
        self,
        session_id: str,
        revision: int,
        receipt_id: str,
    ) -> Mapping[str, Any]:
        return {
            "wire_schema": PRIVATE_TURN_RESULT_SCHEMA,
            "session_id": session_id,
            "revision": revision,
            "status": "terminal",
            "oracle_response": None,
            "view": None,
            "receipt_id": receipt_id,
            "result_released": False,
        }

    def _active_response(
        self,
        session_id: str,
        revision: int,
        episode: Episode,
        oracle_response: Any,
    ) -> Mapping[str, Any]:
        return {
            "wire_schema": PRIVATE_TURN_RESULT_SCHEMA,
            "session_id": session_id,
            "revision": revision,
            "status": "active",
            "oracle_response": (
                oracle_response_to_payload(oracle_response)
                if oracle_response is not None
                else None
            ),
            "view": episode_view_to_payload(episode.view()),
            "receipt_id": None,
            "result_released": False,
        }

    def submit_action(
        self,
        session_id: str,
        session_token: str,
        request: Any,
    ) -> Mapping[str, Any]:
        session_id = _require_text(session_id, "session_id")
        session_token = _require_text(session_token, "session_token")
        root = _require_object(
            request,
            keys=("wire_schema", "request_id", "revision", "action"),
            label="turn request",
        )
        if root["wire_schema"] != PRIVATE_TURN_SCHEMA:
            raise PrivateEvaluationError("unsupported_schema", "unsupported turn schema")
        request_id = _require_text(root["request_id"], "request_id")
        revision = root["revision"]
        if isinstance(revision, bool) or not isinstance(revision, int) or revision < 0:
            raise PrivateEvaluationError("invalid_request", "revision must be non-negative")
        request_hash = _request_hash(root)
        try:
            action = player_action_from_payload(
                root["action"], max_bytes=DEFAULT_MAX_ACTION_BYTES
            )
        except WireDecodeError as exc:
            raise PrivateEvaluationError(
                "invalid_action", "%s at %s" % (exc.code, exc.path)
            ) from exc

        with self._lock, self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            session = self._session(connection, session_id, session_token)
            prior = self._prior_response(
                connection, session_id, request_id, request_hash
            )
            if prior is not None:
                return prior
            if session["status"] != "active":
                raise PrivateEvaluationError(
                    "session_terminal", "private session is already terminal", status=409
                )
            if revision != int(session["revision"]):
                raise PrivateEvaluationError(
                    "revision_conflict", "turn revision does not match service state", status=409
                )
            episode = self._replay_session(connection, session)
            unit = self._unit(int(session["ordinal"]))
            action_index = int(session["action_count"]) + 1
            oracle_response = None
            try:
                oracle_response = episode.apply(action)
            except EpisodeProtocolError as exc:
                episode.terminate_player_failure(
                    EpisodeTermination(
                        kind=TerminationKind.ACTION_REJECTED,
                        code=exc.code,
                        message=str(exc),
                        action_index=action_index,
                    ),
                    candidate_action=action,
                )
            if action_index >= unit.max_actions and not episode.finished:
                episode.terminate_player_failure(
                    EpisodeTermination(
                        kind=TerminationKind.ACTION_LIMIT,
                        code="max_actions_reached",
                        message="Player did not commit within max_actions.",
                        action_index=action_index,
                    )
                )
            next_revision = revision + 1
            if episode.finished:
                receipt_id = secrets.token_urlsafe(24)
                outcome_json = canonical_json_dumps(_outcome_payload(episode.outcome))
                response = self._terminal_response(
                    session_id, next_revision, receipt_id
                )
                status = "terminal"
            else:
                receipt_id = None
                outcome_json = None
                response = self._active_response(
                    session_id, next_revision, episode, oracle_response
                )
                status = "active"
            response_json = canonical_json_dumps(response)
            if len(response_json.encode("utf-8")) > DEFAULT_MAX_JSON_BYTES:
                raise PrivateEvaluationError(
                    "private_contract_error",
                    "private public transition exceeds the wire size limit",
                    status=500,
                )
            connection.execute(
                "INSERT INTO requests(session_id, request_id, request_hash, request_kind, "
                "request_json, response_json, revision_after) VALUES (?, ?, ?, 'action', ?, ?, ?)",
                (
                    session_id,
                    request_id,
                    request_hash,
                    canonical_json_dumps(root),
                    response_json,
                    next_revision,
                ),
            )
            connection.execute(
                "UPDATE sessions SET revision = ?, action_count = ?, status = ?, "
                "receipt_id = ?, outcome_json = ? WHERE session_id = ?",
                (
                    next_revision,
                    action_index,
                    status,
                    receipt_id,
                    outcome_json,
                    session_id,
                ),
            )
            if status == "terminal":
                connection.execute(
                    "UPDATE units SET status = 'terminal' WHERE ordinal = ?",
                    (int(session["ordinal"]),),
                )
            return response

    def record_player_output_invalid(
        self,
        session_id: str,
        session_token: str,
        request: Any,
    ) -> Mapping[str, Any]:
        session_id = _require_text(session_id, "session_id")
        session_token = _require_text(session_token, "session_token")
        root = _require_object(
            request,
            keys=("wire_schema", "request_id", "revision", "failure"),
            label="failure request",
        )
        if root["wire_schema"] != PRIVATE_FAILURE_SCHEMA:
            raise PrivateEvaluationError("unsupported_schema", "unsupported failure schema")
        request_id = _require_text(root["request_id"], "request_id")
        revision = root["revision"]
        if isinstance(revision, bool) or not isinstance(revision, int) or revision < 0:
            raise PrivateEvaluationError("invalid_request", "revision must be non-negative")
        failure = _require_object(
            root["failure"],
            keys=("kind", "code", "message", "generation_attempts"),
            label="failure",
        )
        if failure["kind"] != TerminationKind.PLAYER_OUTPUT_INVALID.value:
            raise PrivateEvaluationError(
                "invalid_request", "only player_output_invalid may be reported"
            )
        code = _require_text(failure["code"], "failure.code")
        message = _require_text(failure["message"], "failure.message", maximum=2048)
        attempts = failure["generation_attempts"]
        if isinstance(attempts, bool) or not isinstance(attempts, int) or attempts < 1:
            raise PrivateEvaluationError(
                "invalid_request", "generation_attempts must be positive"
            )
        request_hash = _request_hash(root)
        with self._lock, self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            session = self._session(connection, session_id, session_token)
            prior = self._prior_response(
                connection, session_id, request_id, request_hash
            )
            if prior is not None:
                return prior
            if session["status"] != "active":
                raise PrivateEvaluationError(
                    "session_terminal", "private session is already terminal", status=409
                )
            if revision != int(session["revision"]):
                raise PrivateEvaluationError(
                    "revision_conflict", "failure revision does not match service state", status=409
                )
            episode = self._replay_session(connection, session)
            episode.terminate_player_failure(
                EpisodeTermination(
                    kind=TerminationKind.PLAYER_OUTPUT_INVALID,
                    code=code,
                    message=message,
                    action_index=int(session["action_count"]) + 1,
                    generation_attempts=attempts,
                )
            )
            next_revision = revision + 1
            receipt_id = secrets.token_urlsafe(24)
            response = self._terminal_response(session_id, next_revision, receipt_id)
            connection.execute(
                "INSERT INTO requests(session_id, request_id, request_hash, request_kind, "
                "request_json, response_json, revision_after) VALUES (?, ?, ?, 'failure', ?, ?, ?)",
                (
                    session_id,
                    request_id,
                    request_hash,
                    canonical_json_dumps(root),
                    canonical_json_dumps(response),
                    next_revision,
                ),
            )
            connection.execute(
                "UPDATE sessions SET revision = ?, status = 'terminal', receipt_id = ?, "
                "outcome_json = ? WHERE session_id = ?",
                (
                    next_revision,
                    receipt_id,
                    canonical_json_dumps(_outcome_payload(episode.outcome)),
                    session_id,
                ),
            )
            connection.execute(
                "UPDATE units SET status = 'terminal' WHERE ordinal = ?",
                (int(session["ordinal"]),),
            )
            return response

    def export_results(self) -> Mapping[str, Any]:
        """Return the complete pack only after every unit is terminal."""

        with self._lock, self._connect() as connection:
            rows = list(
                connection.execute(
                    "SELECT u.ordinal, u.unit_id, u.status, s.session_id, "
                    "s.client_run_id, s.receipt_id, s.outcome_json "
                    "FROM units u LEFT JOIN sessions s ON u.session_id = s.session_id "
                    "ORDER BY u.ordinal"
                )
            )
        complete = all(row["status"] == "terminal" for row in rows)
        if not complete:
            raise PrivateEvaluationError(
                "results_embargoed",
                "results remain embargoed until every private unit is terminal",
                status=409,
            )
        units = []
        for row in rows:
            unit = self._unit(int(row["ordinal"]))
            units.append(
                {
                    "ordinal": int(row["ordinal"]),
                    "unit_id": row["unit_id"],
                    "client_run_id": row["client_run_id"],
                    "session_id": row["session_id"],
                    "receipt_id": row["receipt_id"],
                    "private_metadata": copy.deepcopy(dict(unit.private_metadata)),
                    "outcome": strict_json_loads(row["outcome_json"]),
                }
            )
        return {
            "schema": PRIVATE_RESULT_EXPORT_SCHEMA,
            "pack_id": self._pack.pack_id,
            "release_id": self._pack.release_id,
            "artifact_digest": self._pack.artifact_digest,
            "pack_identity_digest": self._pack.identity_digest,
            "complete": True,
            "unit_count": len(units),
            "units": units,
        }


__all__ = [
    "PRIVATE_FAILURE_SCHEMA",
    "PRIVATE_RESULT_EXPORT_SCHEMA",
    "PRIVATE_SESSION_CREATE_SCHEMA",
    "PRIVATE_SESSION_SCHEMA",
    "PRIVATE_STORE_SCHEMA_VERSION",
    "PRIVATE_TURN_RESULT_SCHEMA",
    "PRIVATE_TURN_SCHEMA",
    "PrivateCasePack",
    "PrivateEvaluationError",
    "PrivateEvaluationService",
    "PrivateEvaluationUnit",
    "load_private_case_pack",
]
