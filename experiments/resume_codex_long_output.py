"""Resume the one oversized-output case with a recorded transport deadline exception."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

from experiments import run_case_matrix as matrix
from experiments.codex_structured_backend import CodexStructuredBackend
from experiments.recover_codex_failed import original_args, _verify_sealed

TARGET = "temporal_enriched_105006__canonical__counterfactual__identification__adaptive-experimental-design__r01"
RUN = Path("runs/EXP-CODEX-GPT55-BOTH-R1-20260917")


def read(path):
    return json.loads(path.read_text())


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def now():
    return datetime.now(timezone.utc).isoformat()


def preflight(root):
    args = original_args(root)
    plan = matrix.build_plan(case_pack="both", repeats=1, schedule_seed=20260825)
    config = read(root / "config.json")
    expected = matrix._config_payload(args, plan)
    assert {k: v for k, v in config.items() if k != "created_at"} == {
        k: v for k, v in expected.items() if k != "created_at"}, "Frozen config mismatch"
    assert not (root / "recovery_history/parallel_recovery.lock").exists()
    snapshot_path = root / "recovery_history/attempt-01.json"
    snapshot = read(snapshot_path)
    assert snapshot_path.with_suffix(".tar.gz").is_file()
    assert snapshot["active_infrastructure_ids"] == [TARGET]
    assert len(snapshot["sealed_evaluated"]) == 635
    assert len(snapshot["judge_retry_ids"]) == 3
    _verify_sealed(root, snapshot["sealed_evaluated"])
    rows = [read(p) for p in (root / "results").glob("*.result.json")]
    assert len(rows) == 636 and {r["episode_id"] for r in rows} == {s.episode_id for s in plan}
    assert [r["episode_id"] for r in rows if r["status"] != "evaluated"] == [TARGET]
    judges = [read(p) for p in (root / "evaluations").glob("*.evaluation.json")]
    assert {r["episode_id"] for r in judges if r["status"] != "evaluated"} == set(snapshot["judge_retry_ids"])
    for path in (root / "codex_calls").glob("*/request.json"):
        assert (path.parent / "response.json").exists() or (path.parent / "failure.json").exists(), "A model call is still running"
    repo = Path(__file__).resolve().parents[1]
    frozen = read(root / "provenance.json")["source_sha256"]
    execution = {p: h for p, h in frozen.items() if p.startswith("src/") or p in (
        "experiments/run_case_matrix.py", "experiments/codex_structured_backend.py", "scripts/run_codex_gpt55_both.sh")}
    assert all(sha(repo / p) == h for p, h in execution.items()), "Frozen execution source changed"
    return args, snapshot, execution


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    cli = parser.parse_args()
    root = RUN.resolve()
    args, snapshot, execution = preflight(root)
    print("Validated: one active retry at 3600 seconds; three Judge retries at 900 seconds; 635 sealed outcomes preserved.", flush=True)
    if cli.dry_run:
        return 0
    repo = Path(__file__).resolve().parents[1]
    before = {p.parent.name for p in (root / "codex_calls").glob("*/request.json")}
    path = root / "recovery_history/timeout_override_provenance.json"
    record = {
        "schema": "codex_timeout_override.v1", "created_at": now(),
        "reason": "Two 900-second attempts timed out while continuously streaming a large final predictor AST; the second exceeded 136650 response characters before timeout.",
        "active_retry_ids": [TARGET], "judge_only_retry_ids": snapshot["judge_retry_ids"],
        "original_player_timeout_s": 900, "actual_player_timeout_s": 3600,
        "actual_evaluator_timeout_s": 900,
        "scientific_parameters_unchanged": True,
        "config_sha256": sha(root / "config.json"),
        "root_snapshot_sha256": sha(root / "recovery_history/attempt-01.json"),
        "execution_source_sha256": execution,
        "orchestration_source_sha256": {p: sha(repo / p) for p in (
            "experiments/resume_codex_long_output.py", "scripts/resume_codex_long_output.sh")},
        "call_ids_before": sorted(before), "status": "running",
    }
    with path.open("x") as stream:
        json.dump(record, stream, indent=2)
    def player_loader():
        return CodexStructuredBackend(model="gpt-5.5", reasoning_effort="high", timeout_s=3600,
                                      audit_dir=root / "codex_calls", role="player")
    code = 0
    try:
        matrix.run_matrix(args, player_backend_loader=player_loader)
        record["status"] = "completed"
    except Exception as exc:
        record.update(status="failed", error_type=type(exc).__name__, error_message=str(exc))
        print(str(exc), flush=True)
        code = 1
    finally:
        _verify_sealed(root, snapshot["sealed_evaluated"])
        assert sha(root / "config.json") == record["config_sha256"]
        record["completed_at"] = now()
        record["new_call_ids"] = sorted({p.parent.name for p in (root / "codex_calls").glob("*/request.json")} - before)
        record["sealed_outcomes_preserved"] = True
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(record, indent=2) + "\n")
        temporary.replace(path)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
