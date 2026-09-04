"""Authenticated HTTP boundary for private benchmark evaluation.

Only this server imports the private case pack.  The Player-side client deals
exclusively in public ``EpisodeView`` and ``PlayerAction`` values.  Results are
embargoed behind a distinct administrative credential until the whole pack is
terminal.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import ipaddress
import ssl
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Mapping, Optional

from .models import EpisodeView, OracleResponse, PlayerAction, TerminationKind
from .private_eval import (
    PRIVATE_FAILURE_SCHEMA,
    PRIVATE_RESULT_EXPORT_SCHEMA,
    PRIVATE_SESSION_CREATE_SCHEMA,
    PRIVATE_SESSION_SCHEMA,
    PRIVATE_TURN_RESULT_SCHEMA,
    PRIVATE_TURN_SCHEMA,
    PrivateEvaluationError,
    PrivateEvaluationService,
)
from .wire import (
    DEFAULT_MAX_JSON_BYTES,
    WireDecodeError,
    canonical_json_dumps,
    episode_view_from_payload,
    episode_view_to_payload,
    oracle_response_from_payload,
    oracle_response_to_payload,
    player_action_to_payload,
    strict_json_loads,
)


PRIVATE_ERROR_SCHEMA = "role_benchmark.private_error.v1"
_SESSION_HEADER = "X-Role-Benchmark-Session"
_MAX_EXPORT_BYTES = 67_108_864


def _is_loopback(host: str) -> bool:
    if host.casefold() == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _validate_token(token: str, label: str) -> None:
    if (
        not isinstance(token, str)
        or len(token) < 32
        or any(ord(character) < 33 or ord(character) > 126 for character in token)
    ):
        raise ValueError(
            "%s must contain at least 32 printable ASCII characters" % label
        )


@dataclass(frozen=True)
class PrivateSessionState:
    """Player-visible state for one remotely hosted private episode."""

    session_id: str
    client_run_id: str
    revision: int
    status: str
    view: Optional[EpisodeView]
    oracle_response: Optional[OracleResponse] = None
    receipt_id: Optional[str] = None

    @property
    def terminal(self) -> bool:
        return self.status == "terminal"


def _expect_response_object(value: Any, keys: tuple[str, ...]) -> Mapping[str, Any]:
    if not isinstance(value, dict) or set(value) != set(keys):
        raise PrivateEvaluationError(
            "invalid_service_response", "private service returned an invalid object", status=502
        )
    return value


def _decode_turn_response(
    payload: Any,
    *,
    expected_session_id: str,
    client_run_id: str,
) -> PrivateSessionState:
    root = _expect_response_object(
        payload,
        (
            "wire_schema", "session_id", "revision", "status",
            "oracle_response", "view", "receipt_id", "result_released",
        ),
    )
    if root["wire_schema"] != PRIVATE_TURN_RESULT_SCHEMA:
        raise PrivateEvaluationError(
            "invalid_service_response", "private service returned an unsupported schema", status=502
        )
    if root["session_id"] != expected_session_id:
        raise PrivateEvaluationError(
            "invalid_service_response", "private service returned the wrong session", status=502
        )
    revision = root["revision"]
    if isinstance(revision, bool) or not isinstance(revision, int) or revision < 0:
        raise PrivateEvaluationError(
            "invalid_service_response", "private service returned an invalid revision", status=502
        )
    if root["result_released"] is not False:
        raise PrivateEvaluationError(
            "invalid_service_response", "Player response attempted to release a result", status=502
        )
    status = root["status"]
    try:
        if status == "active":
            if root["view"] is None or root["receipt_id"] is not None:
                raise ValueError("invalid active response")
            view = episode_view_from_payload(root["view"])
            oracle = (
                None
                if root["oracle_response"] is None
                else oracle_response_from_payload(root["oracle_response"])
            )
            return PrivateSessionState(
                session_id=expected_session_id,
                client_run_id=client_run_id,
                revision=revision,
                status=status,
                view=view,
                oracle_response=oracle,
            )
        if status == "terminal":
            if (
                root["view"] is not None
                or root["oracle_response"] is not None
                or not isinstance(root["receipt_id"], str)
                or not root["receipt_id"].strip()
            ):
                raise ValueError("invalid terminal response")
            return PrivateSessionState(
                session_id=expected_session_id,
                client_run_id=client_run_id,
                revision=revision,
                status=status,
                view=None,
                receipt_id=root["receipt_id"],
            )
    except (WireDecodeError, TypeError, ValueError) as exc:
        raise PrivateEvaluationError(
            "invalid_service_response", "private service returned invalid public state", status=502
        ) from exc
    raise PrivateEvaluationError(
        "invalid_service_response", "private service returned an invalid status", status=502
    )


class PrivateEvaluationHTTPClient:
    """Strict Player-side client; credentials are never included in results."""

    def __init__(
        self,
        endpoint: str,
        player_token: str,
        *,
        timeout: float = 60.0,
        ssl_context: Optional[ssl.SSLContext] = None,
    ) -> None:
        _validate_token(player_token, "player_token")
        parsed = urllib.parse.urlsplit(endpoint)
        if (
            parsed.scheme not in ("http", "https")
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path not in ("", "/")
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("endpoint must be an HTTP(S) origin without credentials or query")
        if parsed.scheme == "http" and not _is_loopback(parsed.hostname):
            raise ValueError("unencrypted private evaluation is allowed only on loopback")
        if not isinstance(timeout, (int, float)) or isinstance(timeout, bool) or timeout <= 0:
            raise ValueError("timeout must be positive")
        self._endpoint = endpoint.rstrip("/")
        self._player_token = player_token
        self._timeout = float(timeout)
        self._ssl_context = ssl_context

    def _session_token(self, client_run_id: str) -> str:
        digest = hmac.new(
            self._player_token.encode("utf-8"),
            ("session:" + client_run_id).encode("utf-8"),
            hashlib.sha256,
        ).digest()
        return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")

    @staticmethod
    def _request_id(namespace: str, value: str) -> str:
        return namespace + "-" + hashlib.sha256(value.encode("utf-8")).hexdigest()

    def _request(
        self,
        method: str,
        path: str,
        *,
        payload: Any = None,
        session_token: Optional[str] = None,
    ) -> Any:
        data = None
        headers = {
            "Accept": "application/json",
            "Authorization": "Bearer " + self._player_token,
        }
        if session_token is not None:
            headers[_SESSION_HEADER] = session_token
        if payload is not None:
            data = canonical_json_dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(
            self._endpoint + path, data=data, headers=headers, method=method
        )
        try:
            with urllib.request.urlopen(
                request, timeout=self._timeout, context=self._ssl_context
            ) as response:
                raw = response.read(DEFAULT_MAX_JSON_BYTES + 1)
        except urllib.error.HTTPError as exc:
            raw = exc.read(DEFAULT_MAX_JSON_BYTES + 1)
            try:
                error = strict_json_loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, WireDecodeError):
                error = None
            if (
                isinstance(error, dict)
                and set(error) == {"schema", "code", "message"}
                and error["schema"] == PRIVATE_ERROR_SCHEMA
                and isinstance(error["code"], str)
                and isinstance(error["message"], str)
            ):
                raise PrivateEvaluationError(
                    error["code"], error["message"], status=exc.code
                ) from exc
            raise PrivateEvaluationError(
                "private_http_error", "private service returned HTTP %d" % exc.code,
                status=exc.code,
            ) from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise PrivateEvaluationError(
                "private_transport_error", "private service transport failed", status=503
            ) from exc
        if len(raw) > DEFAULT_MAX_JSON_BYTES:
            raise PrivateEvaluationError(
                "invalid_service_response", "private service response is too large", status=502
            )
        try:
            return strict_json_loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, WireDecodeError) as exc:
            raise PrivateEvaluationError(
                "invalid_service_response", "private service returned invalid JSON", status=502
            ) from exc

    def create_session(self, client_run_id: str) -> PrivateSessionState:
        if not isinstance(client_run_id, str) or not client_run_id.strip():
            raise ValueError("client_run_id must be non-empty text")
        session_token = self._session_token(client_run_id)
        request_id = self._request_id("create", client_run_id)
        response = self._request(
            "POST",
            "/v1/sessions",
            payload={
                "wire_schema": PRIVATE_SESSION_CREATE_SCHEMA,
                "request_id": request_id,
                "client_run_id": client_run_id,
                "session_token": session_token,
            },
        )
        root = _expect_response_object(
            response, ("wire_schema", "session_id", "revision", "view")
        )
        if (
            root["wire_schema"] != PRIVATE_SESSION_SCHEMA
            or not isinstance(root["session_id"], str)
            or not root["session_id"].strip()
            or isinstance(root["revision"], bool)
            or not isinstance(root["revision"], int)
            or root["revision"] != 0
        ):
            raise PrivateEvaluationError(
                "invalid_service_response", "private service returned an invalid session", status=502
            )
        try:
            episode_view_from_payload(root["view"])
        except WireDecodeError as exc:
            raise PrivateEvaluationError(
                "invalid_service_response", "private service returned an invalid initial view", status=502
            ) from exc
        # A repeated create is a recovery operation.  Resume immediately so a
        # restarted Player receives the current revision rather than revision 0.
        return self.resume_session(root["session_id"], client_run_id)

    def resume_session(
        self, session_id: str, client_run_id: str
    ) -> PrivateSessionState:
        session_token = self._session_token(client_run_id)
        response = self._request(
            "GET", "/v1/sessions/" + urllib.parse.quote(session_id, safe=""),
            session_token=session_token,
        )
        return _decode_turn_response(
            response, expected_session_id=session_id, client_run_id=client_run_id
        )

    def submit_action(
        self,
        state: PrivateSessionState,
        action: PlayerAction,
        *,
        request_id: str,
    ) -> PrivateSessionState:
        response = self._request(
            "POST",
            "/v1/sessions/%s/turns" % urllib.parse.quote(state.session_id, safe=""),
            session_token=self._session_token(state.client_run_id),
            payload={
                "wire_schema": PRIVATE_TURN_SCHEMA,
                "request_id": request_id,
                "revision": state.revision,
                "action": player_action_to_payload(action),
            },
        )
        result = _decode_turn_response(
            response,
            expected_session_id=state.session_id,
            client_run_id=state.client_run_id,
        )
        if result.revision != state.revision + 1:
            raise PrivateEvaluationError(
                "invalid_service_response", "private service skipped a turn revision", status=502
            )
        if result.status == "active":
            if result.oracle_response is None or result.view is None or state.view is None:
                raise PrivateEvaluationError(
                    "invalid_service_response", "active turn omitted its public transition", status=502
                )
            if episode_view_to_payload(result.view)["case"] != episode_view_to_payload(state.view)["case"]:
                raise PrivateEvaluationError(
                    "invalid_service_response", "private service changed the public case", status=502
                )
            if len(result.view.turns) != len(state.view.turns) + 1:
                raise PrivateEvaluationError(
                    "invalid_service_response", "private service returned an invalid turn history", status=502
                )
            if oracle_response_to_payload(result.oracle_response) != oracle_response_to_payload(
                result.view.turns[-1].response
            ):
                raise PrivateEvaluationError(
                    "invalid_service_response", "private service returned inconsistent Oracle evidence", status=502
                )
        return result

    def record_player_output_invalid(
        self,
        state: PrivateSessionState,
        *,
        request_id: str,
        code: str,
        message: str,
        generation_attempts: int,
    ) -> PrivateSessionState:
        response = self._request(
            "POST",
            "/v1/sessions/%s/failures" % urllib.parse.quote(state.session_id, safe=""),
            session_token=self._session_token(state.client_run_id),
            payload={
                "wire_schema": PRIVATE_FAILURE_SCHEMA,
                "request_id": request_id,
                "revision": state.revision,
                "failure": {
                    "kind": TerminationKind.PLAYER_OUTPUT_INVALID.value,
                    "code": code,
                    "message": message,
                    "generation_attempts": generation_attempts,
                },
            },
        )
        result = _decode_turn_response(
            response,
            expected_session_id=state.session_id,
            client_run_id=state.client_run_id,
        )
        if not result.terminal or result.revision != state.revision + 1:
            raise PrivateEvaluationError(
                "invalid_service_response", "failure report did not terminate one revision", status=502
            )
        return result


def _read_json_request(handler: BaseHTTPRequestHandler) -> Any:
    content_type = handler.headers.get("Content-Type", "").split(";", 1)[0].strip()
    if content_type != "application/json":
        raise PrivateEvaluationError("invalid_request", "Content-Type must be application/json")
    raw_length = handler.headers.get("Content-Length")
    try:
        length = int(raw_length) if raw_length is not None else -1
    except ValueError as exc:
        raise PrivateEvaluationError("invalid_request", "invalid Content-Length") from exc
    if length < 0 or length > DEFAULT_MAX_JSON_BYTES:
        raise PrivateEvaluationError("invalid_request", "request body size is invalid", status=413)
    raw = handler.rfile.read(length)
    try:
        return strict_json_loads(raw.decode("utf-8"), max_bytes=DEFAULT_MAX_JSON_BYTES)
    except (UnicodeDecodeError, WireDecodeError) as exc:
        raise PrivateEvaluationError("invalid_request", "request body is invalid JSON") from exc


def make_private_evaluation_http_server(
    service: PrivateEvaluationService,
    *,
    host: str,
    port: int,
    player_token: str,
    admin_token: str,
    tls_certfile: Optional[str] = None,
    tls_keyfile: Optional[str] = None,
) -> ThreadingHTTPServer:
    """Construct the trusted server; callers own ``serve_forever``/shutdown."""

    if not isinstance(service, PrivateEvaluationService):
        raise ValueError("service must be PrivateEvaluationService")
    _validate_token(player_token, "player_token")
    _validate_token(admin_token, "admin_token")
    if hmac.compare_digest(player_token, admin_token):
        raise ValueError("player_token and admin_token must be distinct")
    if (tls_certfile is None) != (tls_keyfile is None):
        raise ValueError("TLS certificate and key must be supplied together")
    if not _is_loopback(host) and tls_certfile is None:
        raise ValueError("non-loopback private evaluation requires TLS")

    class Handler(BaseHTTPRequestHandler):
        server_version = "RoleBenchmarkPrivate/1"
        sys_version = ""

        def log_message(self, format: str, *args: Any) -> None:
            return

        def _authorized(self, expected: str) -> bool:
            supplied = self.headers.get("Authorization", "")
            return hmac.compare_digest(supplied, "Bearer " + expected)

        def _session_token(self) -> str:
            value = self.headers.get(_SESSION_HEADER, "")
            if len(value) < 32:
                raise PrivateEvaluationError(
                    "session_not_found", "private session was not found", status=404
                )
            return value

        def _send(self, status: int, payload: Mapping[str, Any]) -> None:
            body = canonical_json_dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(body)

        def _error(self, error: PrivateEvaluationError) -> None:
            self._send(
                error.status,
                {"schema": PRIVATE_ERROR_SCHEMA, "code": error.code, "message": error.message},
            )

        def _dispatch(self) -> None:
            parsed = urllib.parse.urlsplit(self.path)
            if parsed.query or parsed.fragment:
                raise PrivateEvaluationError("not_found", "endpoint was not found", status=404)
            parts = [urllib.parse.unquote(part) for part in parsed.path.split("/") if part]
            if self.command == "GET" and parts == ["healthz"]:
                self._send(200, {"status": "ok"})
                return
            if parts[:2] == ["v1", "admin"]:
                if not self._authorized(admin_token):
                    raise PrivateEvaluationError("unauthorized", "authorization failed", status=401)
                if self.command == "GET" and parts == ["v1", "admin", "results"]:
                    self._send(200, service.export_results())
                    return
                raise PrivateEvaluationError("not_found", "endpoint was not found", status=404)
            if not self._authorized(player_token):
                raise PrivateEvaluationError("unauthorized", "authorization failed", status=401)
            if self.command == "POST" and parts == ["v1", "sessions"]:
                self._send(201, service.create_session(_read_json_request(self)))
                return
            if len(parts) == 3 and parts[:2] == ["v1", "sessions"] and self.command == "GET":
                self._send(200, service.resume_session(parts[2], self._session_token()))
                return
            if len(parts) == 4 and parts[:2] == ["v1", "sessions"] and self.command == "POST":
                if parts[3] == "turns":
                    result = service.submit_action(
                        parts[2], self._session_token(), _read_json_request(self)
                    )
                elif parts[3] == "failures":
                    result = service.record_player_output_invalid(
                        parts[2], self._session_token(), _read_json_request(self)
                    )
                else:
                    raise PrivateEvaluationError("not_found", "endpoint was not found", status=404)
                self._send(200, result)
                return
            raise PrivateEvaluationError("not_found", "endpoint was not found", status=404)

        def do_GET(self) -> None:
            self._handle()

        def do_POST(self) -> None:
            self._handle()

        def _handle(self) -> None:
            try:
                self._dispatch()
            except PrivateEvaluationError as exc:
                self._error(exc)
            except Exception:
                self._error(
                    PrivateEvaluationError(
                        "internal_error", "private service failed", status=500
                    )
                )

    server = ThreadingHTTPServer((host, port), Handler)
    server.daemon_threads = True
    if tls_certfile is not None and tls_keyfile is not None:
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        context.load_cert_chain(tls_certfile, tls_keyfile)
        server.socket = context.wrap_socket(server.socket, server_side=True)
    return server


def export_private_results(
    endpoint: str,
    admin_token: str,
    *,
    timeout: float = 60.0,
    ssl_context: Optional[ssl.SSLContext] = None,
) -> Mapping[str, Any]:
    """Fetch the embargoed complete pack with the administrator credential."""

    _validate_token(admin_token, "admin_token")
    parsed = urllib.parse.urlsplit(endpoint)
    if (
        parsed.scheme not in ("http", "https")
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in ("", "/")
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("endpoint must be an HTTP(S) origin without credentials or query")
    if parsed.scheme == "http" and not _is_loopback(parsed.hostname):
        raise ValueError("unencrypted private evaluation is allowed only on loopback")
    if not isinstance(timeout, (int, float)) or isinstance(timeout, bool) or timeout <= 0:
        raise ValueError("timeout must be positive")
    request = urllib.request.Request(
        endpoint.rstrip("/") + "/v1/admin/results",
        headers={"Accept": "application/json", "Authorization": "Bearer " + admin_token},
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout, context=ssl_context) as response:
            raw = response.read(_MAX_EXPORT_BYTES + 1)
    except urllib.error.HTTPError as exc:
        raw = exc.read(DEFAULT_MAX_JSON_BYTES + 1)
        try:
            error = strict_json_loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, WireDecodeError):
            error = None
        if (
            isinstance(error, dict)
            and set(error) == {"schema", "code", "message"}
            and error.get("schema") == PRIVATE_ERROR_SCHEMA
            and isinstance(error.get("code"), str)
            and isinstance(error.get("message"), str)
        ):
            raise PrivateEvaluationError(
                error["code"], str(error.get("message", "private export failed")), status=exc.code
            ) from exc
        raise PrivateEvaluationError(
            "private_http_error", "private service returned HTTP %d" % exc.code, status=exc.code
        ) from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise PrivateEvaluationError(
            "private_transport_error", "private service transport failed", status=503
        ) from exc
    if len(raw) > _MAX_EXPORT_BYTES:
        raise PrivateEvaluationError(
            "invalid_service_response", "private export is too large", status=502
        )
    try:
        result = strict_json_loads(raw.decode("utf-8"), max_bytes=_MAX_EXPORT_BYTES)
    except (UnicodeDecodeError, WireDecodeError) as exc:
        raise PrivateEvaluationError(
            "invalid_service_response", "private export is invalid JSON", status=502
        ) from exc
    if (
        not isinstance(result, dict)
        or set(result) != {
            "schema", "pack_id", "release_id", "artifact_digest",
            "pack_identity_digest", "complete", "unit_count", "units",
        }
        or result.get("schema") != PRIVATE_RESULT_EXPORT_SCHEMA
        or result.get("complete") is not True
        or isinstance(result.get("unit_count"), bool)
        or not isinstance(result.get("unit_count"), int)
        or not isinstance(result.get("units"), list)
        or result["unit_count"] != len(result["units"])
    ):
        raise PrivateEvaluationError(
            "invalid_service_response", "private export is invalid", status=502
        )
    return result


__all__ = [
    "PRIVATE_ERROR_SCHEMA",
    "PrivateEvaluationHTTPClient",
    "PrivateSessionState",
    "export_private_results",
    "make_private_evaluation_http_server",
]
