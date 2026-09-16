from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from experiments.run_gpt56_agent_sandbox import (
    _complete_log,
    _official_pilot_root,
    _reject_official_output,
)
from role_benchmark.agent_sandbox import (
    AGENT_SANDBOX_RESPONSE_SCHEMA,
    AgentFileExchangeBackend,
    AgentSandboxResponseError,
    AgentSandboxResponseRequired,
    pending_agent_sandbox_requests,
)
from role_benchmark.llm import GenerationConfig, GenerationRequest, Message


def _request(content="Choose one action."):
    return GenerationRequest(
        messages=(Message("system", "Return JSON."), Message("user", content)),
        response_schema={"type": "object"},
        config=GenerationConfig(max_output_tokens=128),
        metadata={"purpose": "test"},
    )


class AgentSandboxTests(unittest.TestCase):
    def test_captures_exact_request_then_replays_matching_response(self):
        with tempfile.TemporaryDirectory() as directory:
            backend = AgentFileExchangeBackend(
                directory,
                role="player",
                agent_id="player_sandbox_agent",
            )
            with self.assertRaises(AgentSandboxResponseRequired) as raised:
                backend.generate(_request())
            request_path = raised.exception.request_path
            response_path = raised.exception.response_path
            envelope = json.loads(request_path.read_text(encoding="utf-8"))
            self.assertEqual(envelope["role"], "player")
            self.assertEqual(pending_agent_sandbox_requests(directory), (request_path,))
            response_path.write_text(
                json.dumps(
                    {
                        "schema": AGENT_SANDBOX_RESPONSE_SCHEMA,
                        "role": "player",
                        "agent_id": "player_sandbox_agent",
                        "request_sha256": envelope["request_sha256"],
                        "model": "gpt-5.6-sol",
                        "text": '{"kind":"final"}',
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            response = backend.generate(_request())
            self.assertEqual(response.text, '{"kind":"final"}')
            self.assertEqual(response.provider, "codex_agent_sandbox")
            self.assertTrue(response.metadata["sandbox_only"])
            self.assertEqual(pending_agent_sandbox_requests(directory), ())

    def test_request_change_requires_a_distinct_response(self):
        with tempfile.TemporaryDirectory() as directory:
            backend = AgentFileExchangeBackend(
                directory,
                role="oracle",
                agent_id="oracle_sandbox_agent",
            )
            with self.assertRaises(AgentSandboxResponseRequired) as first:
                backend.generate(_request("first"))
            with self.assertRaises(AgentSandboxResponseRequired) as second:
                backend.generate(_request("second"))
            self.assertNotEqual(first.exception.request_path, second.exception.request_path)
            self.assertEqual(len(pending_agent_sandbox_requests(directory)), 2)

    def test_rejects_wrong_role_identity_hash_and_extra_fields(self):
        cases = (
            {"role": "oracle"},
            {"agent_id": "another-agent"},
            {"request_sha256": "0" * 64},
            {"extra": True},
        )
        for override in cases:
            with self.subTest(override=override), tempfile.TemporaryDirectory() as directory:
                backend = AgentFileExchangeBackend(
                    directory,
                    role="evaluator",
                    agent_id="evaluator_sandbox_agent",
                )
                with self.assertRaises(AgentSandboxResponseRequired) as raised:
                    backend.generate(_request())
                envelope = json.loads(
                    raised.exception.request_path.read_text(encoding="utf-8")
                )
                response = {
                    "schema": AGENT_SANDBOX_RESPONSE_SCHEMA,
                    "role": "evaluator",
                    "agent_id": "evaluator_sandbox_agent",
                    "request_sha256": envelope["request_sha256"],
                    "model": "gpt-5.6-sol",
                    "text": "{}",
                }
                response.update(override)
                raised.exception.response_path.write_text(
                    json.dumps(response), encoding="utf-8"
                )
                with self.assertRaises(AgentSandboxResponseError):
                    backend.generate(_request())

    def test_requires_distinct_supported_roles(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(ValueError):
                AgentFileExchangeBackend(
                    directory, role="judge", agent_id="judge-agent"
                )

    def test_complete_log_ignores_sealed_infrastructure_failures(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            attempts = root / "attempts"
            attempts.mkdir()
            failed = attempts / "episode-attempt-01.jsonl"
            evaluated = attempts / "episode-attempt-02.jsonl"
            failed.touch()
            evaluated.touch()

            def fake_load(path):
                status = "evaluated" if path.endswith("02.jsonl") else "infrastructure_error"
                return SimpleNamespace(
                    complete=True,
                    events=(
                        {
                            "event_type": "run.ended",
                            "payload": {"status": status},
                        },
                    ),
                )

            with mock.patch(
                "experiments.run_gpt56_agent_sandbox.load_run_log",
                side_effect=fake_load,
            ):
                self.assertEqual(_complete_log(root), evaluated)

    def test_rejects_the_official_pilot_output_tree(self):
        official = _official_pilot_root()
        with self.assertRaises(ValueError):
            _reject_official_output(official)
        with self.assertRaises(ValueError):
            _reject_official_output(official / "nested")


if __name__ == "__main__":
    unittest.main()
