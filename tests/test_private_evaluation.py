import os
import sqlite3
import stat
import sys
import tempfile
import threading
import types
import unittest

from role_benchmark import (
    GenerationResponse,
    PrivateCasePack,
    PrivateEvaluationError,
    PrivateEvaluationHTTPClient,
    PrivateEvaluationService,
    PrivateEvaluationUnit,
    PLAYER_PROMPT_VERSION_V2_JSON_HARDENED,
    PLAYER_REPAIR_PROMPT_VERSION_V2_JSON_HARDENED,
    TokenUsage,
    export_private_results,
    load_private_case_pack,
    make_private_evaluation_http_server,
    run_private_llm_episode,
)
from role_benchmark.cases import make_pendulum_case
from role_benchmark.private_eval import (
    PRIVATE_FAILURE_SCHEMA,
    PRIVATE_SESSION_CREATE_SCHEMA,
    PRIVATE_TURN_SCHEMA,
)
from role_benchmark.runlog import load_run_log
from role_benchmark.wire import (
    canonical_json_dumps,
    episode_view_from_payload,
    episode_view_to_payload,
    player_action_to_json,
    player_action_to_payload,
    strict_json_loads,
)
from test_wire import experiment_action, final_action


PLAYER_TOKEN = "player-" + "p" * 40
ADMIN_TOKEN = "admin-" + "a" * 40
SESSION_TOKEN = "session-" + "s" * 40


def private_pack(run_ids=("run-1", "run-2")):
    units = []
    for index, run_id in enumerate(run_ids):
        world = "historical" if index % 2 == 0 else "counterfactual"
        units.append(
            PrivateEvaluationUnit(
                unit_id="SECRET-UNIT-%d" % index,
                case=make_pendulum_case(world),
                client_run_id=run_id,
                private_metadata={
                    "assignment": world,
                    "hidden_seed": 91000 + index,
                    "marker": "NEVER_DISCLOSE_%d" % index,
                },
                forbidden_public_tokens=("NEVER_DISCLOSE_%d" % index,),
            )
        )
    return PrivateCasePack(
        pack_id="private-pack",
        release_id="release-2026-09",
        artifact_digest="d" * 64,
        units=tuple(units),
    )


def create_request(run_id="run-1", request_id="create-1"):
    return {
        "wire_schema": PRIVATE_SESSION_CREATE_SCHEMA,
        "request_id": request_id,
        "client_run_id": run_id,
        "session_token": SESSION_TOKEN,
    }


def turn_request(revision, action, request_id):
    return {
        "wire_schema": PRIVATE_TURN_SCHEMA,
        "request_id": request_id,
        "revision": revision,
        "action": player_action_to_payload(action),
    }


class OneResponseBackend:
    def __init__(self, action):
        self._text = player_action_to_json(action)
        self.calls = 0

    def generate(self, request):
        self.calls += 1
        return GenerationResponse(
            text=self._text,
            provider="fixture",
            model="fixture-model",
            response_id="response-%d" % self.calls,
            usage=TokenUsage(input_tokens=10, output_tokens=10),
        )


class PrivateEvaluationServiceTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp.name, "trusted", "state.sqlite3")
        self.service = PrivateEvaluationService(private_pack(), self.db_path)

    def tearDown(self):
        self.temp.cleanup()

    def test_player_responses_never_disclose_assignment_truth_or_scores(self):
        created = self.service.create_session(create_request())
        serialized = canonical_json_dumps(created)
        for private_text in (
            "SECRET-UNIT-0",
            "historical",
            "hidden_seed",
            "NEVER_DISCLOSE_0",
            "world_model",
            "evaluator",
            "held_out",
        ):
            self.assertNotIn(private_text, serialized)
        decoded = episode_view_from_payload(created["view"])
        self.assertEqual(
            episode_view_to_payload(decoded), created["view"]
        )

        terminal = self.service.submit_action(
            created["session_id"],
            SESSION_TOKEN,
            turn_request(0, final_action(), "turn-final"),
        )
        self.assertEqual(terminal["status"], "terminal")
        self.assertFalse(terminal["result_released"])
        terminal_text = canonical_json_dumps(terminal)
        for forbidden in ("evaluation", "scores", "success", "SECRET-UNIT", "historical"):
            self.assertNotIn(forbidden, terminal_text)
        with self.assertRaises(PrivateEvaluationError) as context:
            self.service.export_results()
        self.assertEqual(context.exception.code, "results_embargoed")

    def test_turns_are_idempotent_revisioned_and_restart_safe(self):
        created = self.service.create_session(create_request())
        request = turn_request(0, experiment_action(), "turn-experiment")
        first = self.service.submit_action(created["session_id"], SESSION_TOKEN, request)
        repeated = self.service.submit_action(created["session_id"], SESSION_TOKEN, request)
        self.assertEqual(first, repeated)
        self.assertEqual(first["revision"], 1)
        self.assertEqual(first["view"]["attempts_used"], 1)

        restarted = PrivateEvaluationService(private_pack(), self.db_path)
        resumed = restarted.resume_session(created["session_id"], SESSION_TOKEN)
        self.assertEqual(resumed["revision"], 1)
        self.assertEqual(resumed["view"], first["view"])
        terminal = restarted.submit_action(
            created["session_id"],
            SESSION_TOKEN,
            turn_request(1, final_action(), "turn-final"),
        )
        self.assertEqual(terminal["status"], "terminal")

        changed = turn_request(0, final_action(), "turn-experiment")
        with self.assertRaises(PrivateEvaluationError) as context:
            restarted.submit_action(created["session_id"], SESSION_TOKEN, changed)
        self.assertEqual(context.exception.code, "idempotency_conflict")
        self.assertEqual(stat.S_IMODE(os.stat(self.db_path).st_mode), 0o600)

    def test_replay_detects_tampered_or_nondeterministic_public_evidence(self):
        created = self.service.create_session(create_request())
        self.service.submit_action(
            created["session_id"],
            SESSION_TOKEN,
            turn_request(0, experiment_action(), "turn-experiment"),
        )
        with sqlite3.connect(self.db_path) as connection:
            raw = connection.execute(
                "SELECT response_json FROM requests WHERE session_id = ?",
                (created["session_id"],),
            ).fetchone()[0]
            response = strict_json_loads(raw)
            response["view"]["turns"][0]["response"]["evidence"]["measurements"][
                "period_s"
            ] += 1.0
            connection.execute(
                "UPDATE requests SET response_json = ? WHERE session_id = ?",
                (canonical_json_dumps(response), created["session_id"]),
            )
        restarted = PrivateEvaluationService(private_pack(), self.db_path)
        with self.assertRaises(PrivateEvaluationError) as context:
            restarted.resume_session(created["session_id"], SESSION_TOKEN)
        self.assertEqual(context.exception.code, "state_corrupt")

    def test_same_client_run_cannot_consume_another_unit(self):
        first = self.service.create_session(create_request())
        self.assertEqual(
            self.service.create_session(create_request()), first
        )
        with self.assertRaises(PrivateEvaluationError) as context:
            self.service.create_session(create_request(request_id="different"))
        self.assertEqual(context.exception.code, "idempotency_conflict")
        with self.assertRaises(PrivateEvaluationError) as context:
            self.service.create_session(create_request("unregistered-run", "new-request"))
        self.assertEqual(context.exception.code, "assignment_unavailable")
        self.assertEqual(self.service.remaining_units, 1)

    def test_complete_pack_export_is_admin_only_transport_concern(self):
        first = self.service.create_session(create_request())
        first_terminal = self.service.submit_action(
            first["session_id"], SESSION_TOKEN,
            turn_request(0, final_action(), "first-final"),
        )
        second_request = create_request("run-2", "create-2")
        second_request["session_token"] = SESSION_TOKEN + "2"
        second = self.service.create_session(second_request)
        failure = self.service.record_player_output_invalid(
            second["session_id"],
            SESSION_TOKEN + "2",
            {
                "wire_schema": PRIVATE_FAILURE_SCHEMA,
                "request_id": "failure-2",
                "revision": 0,
                "failure": {
                    "kind": "player_output_invalid",
                    "code": "invalid_json",
                    "message": "model output was not JSON",
                    "generation_attempts": 1,
                },
            },
        )
        self.assertEqual(failure["status"], "terminal")
        exported = self.service.export_results()
        self.assertTrue(exported["complete"])
        self.assertEqual(exported["unit_count"], 2)
        self.assertEqual(exported["artifact_digest"], "d" * 64)
        self.assertEqual(exported["units"][0]["receipt_id"], first_terminal["receipt_id"])
        self.assertEqual(
            exported["units"][0]["private_metadata"]["assignment"], "historical"
        )
        self.assertIn("evaluation", exported["units"][0]["outcome"])

    def test_pack_identity_and_author_leak_checks_fail_closed(self):
        with self.assertRaises(ValueError):
            PrivateEvaluationUnit(
                unit_id="bad",
                case=make_pendulum_case(),
                client_run_id="bad-run",
                forbidden_public_tokens=("pendulum",),
            )
        with self.assertRaises(ValueError):
            PrivateCasePack(
                pack_id="pack",
                release_id="release",
                artifact_digest="not-a-digest",
                units=(PrivateEvaluationUnit("ok", make_pendulum_case(), "ok-run"),),
            )
        source = private_pack()
        other = PrivateCasePack(
            pack_id=source.pack_id,
            release_id=source.release_id,
            artifact_digest="e" * 64,
            units=source.units,
        )
        with self.assertRaises(ValueError):
            PrivateEvaluationService(other, self.db_path)

    def test_service_only_pack_factory_contract(self):
        module_name = "private_pack_test_fixture"
        module = types.ModuleType(module_name)
        expected = private_pack()
        module.build_pack = lambda: expected
        sys.modules[module_name] = module
        try:
            self.assertIs(
                load_private_case_pack(module_name + ":build_pack"), expected
            )
            with self.assertRaises(ValueError):
                load_private_case_pack(module_name + ":missing")
        finally:
            sys.modules.pop(module_name, None)


class PrivateEvaluationHTTPTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        run_ids = (
            ("runner-1", "runner-2")
            if self._testMethodName == "test_remote_runner_gets_receipt_but_no_result"
            else ("http-run-1", "http-run-2")
        )
        service = PrivateEvaluationService(
            private_pack(run_ids), os.path.join(self.temp.name, "state.sqlite3")
        )
        self.server = make_private_evaluation_http_server(
            service,
            host="127.0.0.1",
            port=0,
            player_token=PLAYER_TOKEN,
            admin_token=ADMIN_TOKEN,
        )
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.endpoint = "http://127.0.0.1:%d" % self.server.server_address[1]
        self.client = PrivateEvaluationHTTPClient(self.endpoint, PLAYER_TOKEN)

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        self.temp.cleanup()

    def test_authentication_embargo_and_resume(self):
        state = self.client.create_session("http-run-1")
        self.assertEqual(state.revision, 0)
        self.assertFalse(hasattr(state, "session_token"))
        state = self.client.submit_action(state, experiment_action(), request_id="http-turn-1")
        recovered = self.client.create_session("http-run-1")
        self.assertEqual(recovered.revision, 1)
        self.assertEqual(
            episode_view_to_payload(recovered.view), episode_view_to_payload(state.view)
        )
        with self.assertRaises(PrivateEvaluationError) as context:
            export_private_results(self.endpoint, ADMIN_TOKEN)
        self.assertEqual(context.exception.code, "results_embargoed")
        with self.assertRaises(PrivateEvaluationError) as context:
            export_private_results(self.endpoint, PLAYER_TOKEN)
        self.assertEqual(context.exception.code, "unauthorized")

        bad_client = PrivateEvaluationHTTPClient(self.endpoint, "wrong-" + "x" * 40)
        with self.assertRaises(PrivateEvaluationError) as context:
            bad_client.create_session("unauthorized-run")
        self.assertEqual(context.exception.code, "unauthorized")

    def test_remote_runner_gets_receipt_but_no_result(self):
        log_path = os.path.join(self.temp.name, "private-run.jsonl")
        receipt = run_private_llm_episode(
            OneResponseBackend(final_action()),
            self.client,
            log_path,
            client_run_id="runner-1",
        )
        self.assertTrue(receipt.receipt_id)
        self.assertEqual(receipt.llm_stats.decoded_actions, 1)
        loaded = load_run_log(log_path)
        self.assertTrue(loaded.complete)
        started = loaded.events[0]["payload"]
        self.assertNotIn("prompt_version", started["llm_config"])
        primary_request = next(
            event["payload"]["request"]
            for event in loaded.events
            if event["event_type"] == "model.requested"
        )
        self.assertNotIn("prompt_version", primary_request["metadata"])
        with open(log_path, encoding="utf-8") as stream:
            log_text = stream.read()
        for forbidden in (
            "SECRET-UNIT",
            "NEVER_DISCLOSE",
            "hidden_seed",
            '"evaluation"',
            '"scores"',
            PLAYER_TOKEN,
            ADMIN_TOKEN,
        ):
            self.assertNotIn(forbidden, log_text)

        second = self.client.create_session("runner-2")
        second = self.client.submit_action(second, final_action(), request_id="runner-2-final")
        self.assertTrue(second.terminal)
        exported = export_private_results(self.endpoint, ADMIN_TOKEN)
        self.assertEqual(exported["unit_count"], 2)

    def test_remote_runner_can_explicitly_select_json_hardened_player_prompt(self):
        log_path = os.path.join(self.temp.name, "private-v2-run.jsonl")
        run_private_llm_episode(
            OneResponseBackend(final_action()),
            self.client,
            log_path,
            client_run_id="http-run-1",
            player_prompt_version=PLAYER_PROMPT_VERSION_V2_JSON_HARDENED,
        )
        loaded = load_run_log(log_path)
        started = loaded.events[0]["payload"]
        self.assertEqual(
            started["llm_config"]["prompt_version"],
            PLAYER_PROMPT_VERSION_V2_JSON_HARDENED,
        )
        self.assertEqual(
            started["llm_config"]["repair_prompt_version"],
            PLAYER_REPAIR_PROMPT_VERSION_V2_JSON_HARDENED,
        )
        primary_request = next(
            event["payload"]["request"]
            for event in loaded.events
            if event["event_type"] == "model.requested"
        )
        self.assertEqual(
            primary_request["metadata"]["prompt_version"],
            PLAYER_PROMPT_VERSION_V2_JSON_HARDENED,
        )

    def test_non_loopback_plaintext_is_rejected(self):
        with self.assertRaises(ValueError):
            PrivateEvaluationHTTPClient("http://example.test", PLAYER_TOKEN)


if __name__ == "__main__":
    unittest.main()
