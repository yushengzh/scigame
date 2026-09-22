"""Fresh, tool-free Codex app-server turns for the scientific benchmark.

The local Codex login supplies authentication. Each call owns its own process,
empty workspace and ephemeral thread; it never resumes a conversation or repairs
an answer. The app-server's native outputSchema constrains the assistant output.
"""

from __future__ import annotations

import dataclasses
from contextlib import ExitStack
import json
import math
import os
from pathlib import Path
import queue
import re
import shutil
import signal
import subprocess
import tempfile
import threading
import time
from typing import Any, Dict, Mapping, Optional
import uuid

from role_benchmark import GenerationRequest, GenerationResponse, TokenUsage


_DISABLED_FEATURES = (
    "shell_tool", "unified_exec", "apps", "plugins", "memories",
    "multi_agent", "browser_use", "browser_use_external", "computer_use",
    "image_generation", "view_image", "hooks", "goals", "sleep_tool",
    "workspace_dependencies", "skill_search", "shell_snapshot",
    "code_mode_host", "tool_suggest",
)
ISOLATION_CONFIG = {
    **{"features." + name: False for name in _DISABLED_FEATURES},
    "features.skip_host_skill_discovery": True,
    "mcp_servers.node_repl.enabled": False,
    "web_search": "disabled",
    "project_doc_max_bytes": 0,
    "service_tier": "default",
    "forced_login_method": "chatgpt",
}
_PASSIVE_ITEM_TYPES = frozenset(("userMessage", "agentMessage", "reasoning"))
CODEX_MODELS = ("gpt-5.5", "gpt-5.6-sol", "gpt-6-astra")
# Keep benchmark effort controls common across all supported models.
CODEX_REASONING_EFFORTS = ("low", "medium", "high", "xhigh")


def validate_codex_model_config(model: str, reasoning_effort: str) -> None:
    """Accept exact benchmark model IDs, without aliases or model fallback."""
    if model not in CODEX_MODELS:
        raise ValueError("Unsupported Codex benchmark model %r; expected one of %s"
                         % (model, ", ".join(CODEX_MODELS)))
    if reasoning_effort not in CODEX_REASONING_EFFORTS:
        raise ValueError("Unsupported Codex benchmark reasoning effort %r; expected one of %s"
                         % (reasoning_effort, ", ".join(CODEX_REASONING_EFFORTS)))


def validate_fresh_thread(receipt: Mapping[str, Any], workspace: Path) -> None:
    """Fail closed if Codex reports inherited instructions or conversation state."""
    if not isinstance(receipt, Mapping) or receipt.get("instructionSources") != []:
        raise RuntimeError("Codex thread has inherited or unverified instruction sources")
    thread = receipt.get("thread")
    if not isinstance(thread, Mapping):
        raise RuntimeError("Codex thread/start receipt is missing a thread")
    if thread.get("ephemeral") is not True or thread.get("turns") != []:
        raise RuntimeError("Codex thread is not a fresh ephemeral thread")
    if thread.get("forkedFromId") is not None or thread.get("parentThreadId") is not None:
        raise RuntimeError("Codex benchmark thread must not be forked or a subagent")
    cwd = thread.get("cwd")
    if not isinstance(cwd, str) or Path(cwd).resolve() != workspace.resolve():
        raise RuntimeError("Codex thread workspace differs from the isolated workspace")
    if receipt.get("cwd") is not None and Path(receipt["cwd"]).resolve() != workspace.resolve():
        raise RuntimeError("Codex resolved workspace differs from the isolated workspace")


def _write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _token_count(value: Any) -> Optional[int]:
    return value if type(value) is int and 0 <= value <= 2**53 - 1 else None


class _AppServerSession:
    """One stdio connection, with a reader thread so deadlines cover silent peers."""

    def __init__(self, command: list[str], workspace: Path, audit_dir: Path, timeout_s: float):
        self._deadline = time.monotonic() + timeout_s
        self._started_at = time.monotonic()
        self._next_id = 0
        self._pending: list[dict[str, Any]] = []
        self._lines: queue.Queue[Any] = queue.Queue()
        self._events = (audit_dir / "events.jsonl").open("w", encoding="utf-8")
        self._stderr = (audit_dir / "stderr.log").open("w", encoding="utf-8")
        try:
            self._process = subprocess.Popen(
                command, cwd=str(workspace), stdin=subprocess.PIPE,
                stdout=subprocess.PIPE, stderr=self._stderr, text=True,
                encoding="utf-8", bufsize=1, start_new_session=True,
            )
        except BaseException:
            self._events.close()
            self._stderr.close()
            raise
        self._reader = threading.Thread(target=self._read_lines, daemon=True)
        self._reader.start()

    def _read_lines(self) -> None:
        try:
            for line in self._process.stdout:
                self._lines.put(line)
        except Exception as exc:
            self._lines.put(exc)
        finally:
            self._lines.put(None)

    def _audit(self, direction: str, message: Mapping[str, Any]) -> None:
        # account/read may include the user's email. Authentication tokens are
        # never read by this module; omit email from the audit as well.
        safe = dict(message)
        result = safe.get("result")
        if isinstance(result, Mapping) and isinstance(result.get("account"), Mapping):
            safe["result"] = {**result, "account": {
                key: value for key, value in result["account"].items() if key != "email"
            }}
        self._events.write(json.dumps({
            "elapsed_s": time.monotonic() - self._started_at,
            "direction": direction, "message": safe,
        }, ensure_ascii=False) + "\n")
        self._events.flush()

    def _send(self, message: Mapping[str, Any]) -> None:
        self._audit("send", message)
        self._process.stdin.write(json.dumps(message, ensure_ascii=False) + "\n")
        self._process.stdin.flush()

    def notify(self, method: str, params: Optional[Mapping[str, Any]] = None) -> None:
        message: Dict[str, Any] = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            message["params"] = params
        self._send(message)

    def _receive(self) -> dict[str, Any]:
        remaining = self._deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("Codex app-server generation deadline exceeded")
        try:
            line = self._lines.get(timeout=remaining)
        except queue.Empty as exc:
            raise TimeoutError("Codex app-server generation deadline exceeded") from exc
        if line is None:
            raise RuntimeError("Codex app-server closed stdout before generation completed")
        if isinstance(line, Exception):
            raise RuntimeError("Codex app-server stdout could not be decoded") from line
        try:
            message = json.loads(line)
        except (ValueError, TypeError) as exc:
            raise RuntimeError("Codex app-server emitted invalid JSONL") from exc
        if not isinstance(message, dict):
            raise RuntimeError("Codex app-server emitted a non-object event")
        self._audit("receive", message)
        if "method" in message and "id" in message:
            self._send({"jsonrpc": "2.0", "id": message["id"], "error": {
                "code": -32601, "message": "Client requests and tool calls are disabled for benchmark turns",
            }})
            raise RuntimeError("Codex attempted a client request or tool call: " + str(message["method"]))
        return message

    def rpc(self, method: str, params: Mapping[str, Any]) -> Mapping[str, Any]:
        self._next_id += 1
        request_id = self._next_id
        self._send({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params})
        while True:
            message = self._receive()
            if message.get("id") == request_id:
                if "error" in message:
                    raise RuntimeError("Codex app-server rejected " + method + ": " + json.dumps(message["error"]))
                result = message.get("result")
                if not isinstance(result, Mapping):
                    raise RuntimeError("Codex app-server returned an invalid result for " + method)
                return result
            if "id" in message:
                raise RuntimeError("Codex app-server returned an unexpected RPC response")
            self._pending.append(message)

    def next_event(self) -> Mapping[str, Any]:
        if self._pending:
            return self._pending.pop(0)
        return self._receive()

    def close(self) -> None:
        try:
            if self._process.poll() is None:
                os.killpg(self._process.pid, signal.SIGTERM)
                try:
                    self._process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    os.killpg(self._process.pid, signal.SIGKILL)
                    self._process.wait(timeout=2)
        except ProcessLookupError:
            pass
        finally:
            self._reader.join(timeout=2)
            if self._process.stdin:
                self._process.stdin.close()
            if self._process.stdout:
                self._process.stdout.close()
            self._events.close()
            self._stderr.close()


class CodexStructuredBackend:
    """Native structured generation using the user's local ChatGPT Codex login."""

    binding_id = "case_matrix.codex_app_server"
    supports_strict_action_schema = True

    def __init__(
        self, *, model: str = "gpt-5.5", reasoning_effort: str = "high",
        timeout_s: float = 900, audit_dir: Path, role: str,
    ) -> None:
        validate_codex_model_config(model, reasoning_effort)
        if not math.isfinite(timeout_s) or timeout_s <= 0:
            raise ValueError("timeout_s must be finite and positive")
        if not isinstance(role, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", role):
            raise ValueError("role must be a nonempty filename-safe identifier")
        self._model = model
        self._reasoning_effort = reasoning_effort
        self._timeout_s = float(timeout_s)
        self._audit_dir = Path(audit_dir).resolve()
        self._role = role

    def generate(self, request: GenerationRequest) -> GenerationResponse:
        if not isinstance(request, GenerationRequest):
            raise ValueError("request must be GenerationRequest")
        if tuple(message.role for message in request.messages) != ("system", "user"):
            raise ValueError("Codex benchmark requests must contain exactly one system and one user message")
        if not request.response_schema:
            raise ValueError("Codex structured generation requires a nonempty response schema")
        if request.config.seed is not None:
            raise ValueError("Codex app-server does not expose a seed parameter")
        executable = shutil.which("codex")
        if executable is None:
            raise RuntimeError("The codex executable is not available on PATH")

        call_id = self._role + "-" + uuid.uuid4().hex
        call_dir = self._audit_dir / call_id
        call_dir.mkdir(parents=True, exist_ok=False)
        config = {**ISOLATION_CONFIG, "model_reasoning_effort": self._reasoning_effort}
        command = [executable, "app-server", "--listen", "stdio://"]
        for key, value in config.items():
            command += ["-c", key + "=" + json.dumps(value)]
        _write_json(call_dir / "request.json", {
            "call_id": call_id, "role": self._role, "model": self._model,
            "reasoning_effort": self._reasoning_effort,
            "messages": [dataclasses.asdict(message) for message in request.messages],
            "response_schema": request.response_schema,
            "generation_config_requested": dataclasses.asdict(request.config),
            "generation_config_enforced": {
                "max_output_tokens": False, "temperature": False, "top_p": False,
                "note": "These sampling/token-limit controls are not exposed by turn/start.",
            },
            "metadata": request.metadata, "command": command,
        })
        started = time.monotonic()
        try:
            with ExitStack() as cleanup:
                temporary = cleanup.enter_context(
                    tempfile.TemporaryDirectory(prefix="scigame-codex-", dir="/tmp")
                )
                workspace = Path(temporary).resolve()
                session = _AppServerSession(command, workspace, call_dir, self._timeout_s)
                # Terminate the process before deleting its isolated workspace.
                cleanup.callback(session.close)
                session.rpc("initialize", {
                    "clientInfo": {"name": "scigame_benchmark", "version": "1.0.0"},
                    "capabilities": {"experimentalApi": True},
                })
                session.notify("initialized")
                account = session.rpc("account/read", {"refreshToken": False}).get("account")
                if not isinstance(account, Mapping) or account.get("type") != "chatgpt":
                    raise RuntimeError("Codex benchmark requires a current ChatGPT login")
                thread_params = {
                    "model": self._model, "modelProvider": "openai",
                    "allowProviderModelFallback": False,
                    "cwd": str(workspace), "ephemeral": True,
                    "approvalPolicy": "never", "sandbox": "read-only",
                    "baseInstructions": request.messages[0].content,
                    "developerInstructions": "", "personality": "none",
                    "config": config, "dynamicTools": [], "environments": [],
                    "selectedCapabilityRoots": [], "runtimeWorkspaceRoots": [],
                    "serviceTier": "default",
                }
                _write_json(call_dir / "thread_start_request.json", thread_params)
                receipt = session.rpc("thread/start", thread_params)
                _write_json(call_dir / "thread_start_receipt.json", receipt)
                validate_fresh_thread(receipt, workspace)
                if receipt.get("model") != self._model:
                    raise RuntimeError("Codex resolved a different model: requested %r, returned %r"
                                       % (self._model, receipt.get("model")))
                thread_id = receipt["thread"].get("id")
                if not isinstance(thread_id, str) or not thread_id:
                    raise RuntimeError("Codex thread/start did not return a thread ID")
                turn_params = {
                    "threadId": thread_id,
                    "input": [{"type": "text", "text": request.messages[1].content}],
                    "model": self._model, "effort": self._reasoning_effort,
                    "outputSchema": request.response_schema, "environments": [],
                    "serviceTier": "default", "summary": "none",
                }
                _write_json(call_dir / "turn_start_request.json", turn_params)
                turn_receipt = session.rpc("turn/start", turn_params)
                _write_json(call_dir / "turn_start_receipt.json", turn_receipt)
                turn_id = turn_receipt.get("turn", {}).get("id")
                if not isinstance(turn_id, str) or not turn_id:
                    raise RuntimeError("Codex turn/start did not return a turn ID")
                completed_items: dict[str, Mapping[str, Any]] = {}
                token_usage: Mapping[str, Any] = {}
                while True:
                    event = session.next_event()
                    method = event.get("method", "")
                    params = event.get("params", {})
                    if not isinstance(params, Mapping):
                        raise RuntimeError("Codex app-server emitted invalid notification parameters")
                    if params.get("threadId") not in (None, thread_id):
                        raise RuntimeError("Codex app-server emitted an event for another thread")
                    if params.get("turnId") not in (None, turn_id):
                        raise RuntimeError("Codex app-server emitted an event for another turn")
                    if method in ("item/started", "item/completed"):
                        item = params.get("item", {})
                        self._validate_item(item)
                        if method == "item/completed":
                            completed_items[item["id"]] = item
                    elif method == "thread/tokenUsage/updated":
                        token_usage = params.get("tokenUsage", {})
                        if not isinstance(token_usage, Mapping):
                            raise RuntimeError("Codex emitted invalid token usage")
                        _write_json(call_dir / "token_usage.json", token_usage)
                    elif method == "turn/completed":
                        turn = params.get("turn", {})
                        if not isinstance(turn, Mapping) or turn.get("id") != turn_id:
                            raise RuntimeError("Codex completed an unexpected turn")
                        _write_json(call_dir / "turn_completed.json", turn)
                        for item in turn.get("items", []):
                            self._validate_item(item)
                            completed_items[item["id"]] = item
                        if turn.get("status") != "completed":
                            raise RuntimeError("Codex turn did not complete: " + str(turn.get("status")))
                        break
                    elif method == "error" and params.get("willRetry") is not True:
                        raise RuntimeError("Codex emitted a generation error: " + json.dumps(params.get("error", {})))

                messages = [item for item in completed_items.values()
                            if item.get("type") == "agentMessage" and item.get("phase") != "commentary"]
                if len(messages) != 1 or not isinstance(messages[0].get("text"), str):
                    raise RuntimeError("Codex did not return exactly one final assistant message")
                usage = token_usage.get("total", {})
                if not isinstance(usage, Mapping):
                    raise RuntimeError("Codex emitted invalid total token usage")
                response = GenerationResponse(
                    text=messages[0]["text"], provider="codex", model=receipt["model"],
                    finish_reason="completed", response_id=turn_id,
                    usage=TokenUsage(input_tokens=_token_count(usage.get("inputTokens")),
                                     output_tokens=_token_count(usage.get("outputTokens"))),
                    metadata={
                        "binding_id": self.binding_id,
                        "structured_output_transport": "codex_app_server_output_schema",
                        "requested_model": self._model, "returned_model": receipt["model"],
                        "model_evidence": "thread/start receipt; not per-turn execution telemetry",
                        "reasoning_effort": self._reasoning_effort,
                        "reasoning_tokens": _token_count(usage.get("reasoningOutputTokens")),
                        "cached_input_tokens": _token_count(usage.get("cachedInputTokens")),
                        "thread_id": thread_id, "turn_id": turn_id,
                        "fresh_ephemeral_thread": True, "instruction_sources": [],
                        "audit_dir": str(call_dir), "call_id": call_id,
                        "max_output_tokens_requested": request.config.max_output_tokens,
                        "max_output_tokens_enforced": False,
                        "temperature_enforced": False, "top_p_enforced": False,
                        "service_tier": "default", "authentication": "chatgpt",
                        "elapsed_s": time.monotonic() - started,
                    },
                )
                _write_json(call_dir / "response.json", dataclasses.asdict(response))
                return response
        except BaseException as exc:
            _write_json(call_dir / "failure.json", {
                "error_type": type(exc).__name__, "error": str(exc),
                "elapsed_s": time.monotonic() - started,
            })
            raise
    @staticmethod
    def _validate_item(item: Any) -> None:
        if not isinstance(item, Mapping) or item.get("type") not in _PASSIVE_ITEM_TYPES:
            item_type = item.get("type") if isinstance(item, Mapping) else "invalid"
            raise RuntimeError("Codex attempted a tool or unexpected item: " + str(item_type))
        if not isinstance(item.get("id"), str) or not item["id"]:
            raise RuntimeError("Codex emitted an item without an ID")
        if item.get("memoryCitation") is not None:
            raise RuntimeError("Codex emitted a memory citation in an isolated benchmark turn")


__all__ = ["CodexStructuredBackend", "CODEX_MODELS", "CODEX_REASONING_EFFORTS",
           "ISOLATION_CONFIG", "validate_codex_model_config", "validate_fresh_thread"]
