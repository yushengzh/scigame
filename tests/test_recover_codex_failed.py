"""The bounded recovery orchestrator cannot consume successes or write aggregates."""

from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock
import contextlib
import io

from experiments import recover_codex_failed as recovery


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value))


def fixture(root):
    plan = recovery.matrix.build_plan(case_pack="both", repeats=1)
    by_id = {spec.episode_id: spec for spec in plan}
    write(root / "config.json", recovery.matrix._config_payload(recovery.original_args(root), plan))
    repo = Path(recovery.__file__).resolve().parents[1]
    execution = "experiments/run_case_matrix.py"
    write(root / "provenance.json", {"source_sha256": {execution: recovery._sha(repo / execution)}})
    sealed = []
    for episode_id in (*recovery.ACTIVE_IDS, *recovery.JUDGE_IDS):
        active_path, judge_path = recovery._paths(root, episode_id)
        row = {**asdict(by_id[episode_id]), "log_path": "episodes/" + episode_id + ".jsonl",
               "status": "infrastructure_failed", "active_pass": None}
        log = root / row["log_path"]
        log.parent.mkdir(exist_ok=True)
        log.write_text("original log, preserved exactly\n")
        if episode_id in recovery.JUDGE_IDS:
            row.update(status="evaluated", active_pass=True, evaluation_success=True,
                       final_submission={"fixture": "sealed"}, scores={"fixture": 1})
            write(judge_path, {"episode_id": episode_id, "status": "infrastructure_failed"})
            sealed.append({"episode_id": episode_id, "log_path": row["log_path"],
                           "log_sha256": recovery._sha(log),
                           **{key: row[key] for key in recovery.SEALED_FIELDS}})
        write(active_path, row)
    write(root / "recovery_history" / "attempt-00.json", {
        "active_infrastructure_ids": list(recovery.ACTIVE_IDS),
        "judge_retry_ids": list(recovery.JUDGE_IDS), "sealed_evaluated": sealed})
    (root / "recovery_history" / "attempt-00.tar.gz").write_bytes(b"root snapshot fixture")


class CodexRecoveryTests(unittest.TestCase):
    def test_frozen_preflight_rejects_success_and_configuration_change(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture(root)
            prepared = recovery.preflight(root, require_snapshot=True)
            self.assertEqual(len(prepared["guards"]), 25)
            self.assertFalse(set(recovery.EXCLUDED_IDS) & set(prepared["selected_rows"]))
            target = recovery._paths(root, recovery.ACTIVE_IDS[0])[0]
            old = recovery._read(target)
            write(target, {**old, "status": "evaluated", "active_pass": True})
            with self.assertRaisesRegex(ValueError, "no longer failed"):
                recovery.preflight(root, require_snapshot=True)
            write(target, old)
            config = recovery._read(root / "config.json")
            config["execution"]["workers"] = 25
            write(root / "config.json", config)
            with self.assertRaisesRegex(ValueError, "full frozen config"):
                recovery.preflight(root, require_snapshot=True)

    def test_atomic_commit_refuses_to_overwrite_changed_sidecar(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "result.json"
            write(path, {"old": True})
            original = path.read_bytes()
            with self.assertRaisesRegex(ValueError, "changed before atomic commit"):
                recovery._atomic_active(path, {"new": True}, "wrong-hash")
            self.assertEqual(path.read_bytes(), original)
            self.assertEqual(list(path.parent.glob(".recovery-*")), [])
            recovery._atomic_active(path, {"new": True}, hashlib.sha256(original).hexdigest())
            self.assertEqual(recovery._read(path), {"new": True})

    def test_exact_failed_stages_use_original_functions_and_leave_aggregates_untouched(self):
        with tempfile.TemporaryDirectory() as directory, contextlib.redirect_stdout(io.StringIO()):
            root = Path(directory)
            fixture(root)
            aggregates = ("episodes.json", "episodes.csv", "scientific_postevaluation.json", "REPORT.md")
            for name in aggregates:
                (root / name).write_text("owned by original runner\n")
            prepared = recovery.preflight(root, require_snapshot=True)
            def active(args, **kwargs):
                kwargs["log_path"].write_text("retry log\n")
                return {**asdict(kwargs["spec"]), "status": "evaluated", "active_pass": True,
                        "log_path": str(kwargs["log_path"].relative_to(root))}
            def judge(args, **kwargs):
                return {"episode_id": kwargs["spec"].episode_id, "status": "evaluated"}
            with mock.patch.object(recovery.matrix, "load_role_backend", side_effect=[object(), object()]), \
                    mock.patch.object(recovery.matrix, "_run_one_episode", side_effect=active) as active_call, \
                    mock.patch.object(recovery.matrix, "_run_evaluator", side_effect=judge) as judge_call, \
                    mock.patch.object(recovery.matrix, "write_summaries", side_effect=AssertionError("aggregate write")), \
                    mock.patch.object(recovery.matrix, "_write_episode_result", side_effect=AssertionError("non-atomic commit")):
                result = recovery.execute(root, prepared, workers=25)
            self.assertEqual(active_call.call_count, 12)
            self.assertEqual(judge_call.call_count, 25)
            self.assertEqual({call.kwargs["spec"].episode_id for call in active_call.call_args_list}, set(recovery.ACTIVE_IDS))
            self.assertTrue(all(row["judge_status"] == "evaluated" for row in result["outcomes"]))
            for name in aggregates:
                self.assertEqual((root / name).read_text(), "owned by original runner\n")
            self.assertEqual(len(list((root / "recovery_history" / "parallel_recovery_previous").glob("*/*.json"))), 25)
            self.assertFalse((root / "recovery_history" / "parallel_recovery.lock").exists())
            recovery._verify_sealed(root, prepared["sealed"])


if __name__ == "__main__":
    unittest.main()
