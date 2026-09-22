"""Recover one frozen set of failed stages while two original episodes finish.

This orchestration uses the original matrix scientific functions and full frozen
configuration. It never writes aggregate files. Only the 25 explicitly named
failed stages may run; active sidecars are atomically replaced after comparison,
and the original runner retains sole ownership of aggregate generation.
"""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import tempfile
from typing import Any, Mapping, Optional, Sequence

from experiments import run_case_matrix as matrix


EXPERIMENT_ID = "EXP-CODEX-GPT55-BOTH-R1-20260917"
ACTIVE_IDS = (
    "michaelis_menten__canonical__counterfactual__discovery__fixed-experimental-design__r01",
    "rc_discharge__canonical__counterfactual__discovery__fixed-experimental-design__r01",
    "temporal_enriched_102006__canonical__counterfactual__discovery__fixed-experimental-design__r01",
    "temporal_enriched_102006__canonical__counterfactual__identification__fixed-experimental-design__r01",
    "temporal_enriched_102006__canonical__source_reported__discovery__fixed-experimental-design__r01",
    "temporal_enriched_105006__canonical__counterfactual__identification__adaptive-experimental-design__r01",
    "temporal_enriched_109001__canonical__source_reported__identification__prior-only-baseline__r01",
    "temporal_enriched_90023__canonical__counterfactual__discovery__fixed-experimental-design__r01",
    "temporal_enriched_90313__canonical__source_reported__discovery__prior-only-baseline__r01",
    "temporal_enriched_90314__canonical__counterfactual__identification__adaptive-experimental-design__r01",
    "temporal_enriched_98304__canonical__counterfactual__identification__fixed-experimental-design__r01",
    "temporal_enriched_98304__canonical__source_reported__identification__fixed-experimental-design__r01",
)
JUDGE_IDS = (
    "faraday_induction__canonical__historical__identification__adaptive-experimental-design__r01",
    "ohm_circuit__canonical__counterfactual__identification__adaptive-experimental-design__r01",
    "rc_discharge__canonical__historical__identification__prior-only-baseline__r01",
    "stefan_boltzmann__canonical__historical__discovery__fixed-experimental-design__r01",
    "temporal_enriched_102006__canonical__counterfactual__discovery__prior-only-baseline__r01",
    "temporal_enriched_104003__canonical__counterfactual__identification__prior-only-baseline__r01",
    "temporal_enriched_90023__canonical__counterfactual__identification__prior-only-baseline__r01",
    "temporal_enriched_90023__canonical__source_reported__discovery__adaptive-experimental-design__r01",
    "temporal_enriched_90220__canonical__source_reported__discovery__prior-only-baseline__r01",
    "temporal_enriched_98304__canonical__source_reported__identification__adaptive-experimental-design__r01",
    "temporal_source_2001__canonical__source_reported__discovery__adaptive-experimental-design__r01",
    "young_double_slit__canonical__counterfactual__identification__fixed-experimental-design__r01",
    "young_double_slit__canonical__historical__identification__fixed-experimental-design__r01",
)
EXCLUDED_IDS = (
    "temporal_enriched_109001__canonical__source_reported__discovery__adaptive-experimental-design__r01",
    "temporal_enriched_90317__canonical__counterfactual__discovery__adaptive-experimental-design__r01",
)
SEALED_FIELDS = ("active_pass", "evaluation_success", "final_submission", "scores")


def _read(path: Path) -> Mapping[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("Expected JSON object: " + str(path))
    return value


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def original_args(root: Path):
    """Exactly the registered launch parameters, including its 32 workers."""
    return matrix._parser().parse_args([
        "--case-pack", "both", "--repeats", "1", "--schedule-seed", "20260825",
        "--oracle-mode", "deterministic", "--player-provider", "codex",
        "--player-model", "gpt-5.5", "--player-reasoning-effort", "high", "--player-timeout-s", "900",
        "--evaluator-provider", "codex", "--evaluator-model", "gpt-5.5",
        "--evaluator-reasoning-effort", "high", "--evaluator-timeout-s", "900",
        "--player-max-output-tokens", "8192", "--evaluator-max-output-tokens", "8192",
        "--max-repair-attempts", "0", "--workers", "32",
        "--experiment-id", EXPERIMENT_ID, "--output-dir", str(root),
    ])


def _paths(root: Path, episode_id: str):
    return (root / "results" / (episode_id + ".result.json"),
            root / "evaluations" / (episode_id + ".evaluation.json"))


def _verify_sealed(root: Path, records: Sequence[Mapping[str, Any]]) -> None:
    for record in records:
        active = _read(_paths(root, record["episode_id"])[0])
        log = Path(record["log_path"])
        log = log if log.is_absolute() else root / log
        if active.get("status") != "evaluated" or _sha(log) != record["log_sha256"]:
            raise ValueError("Sealed active episode changed: " + record["episode_id"])
        if any(active.get(key) != record.get(key) for key in SEALED_FIELDS):
            raise ValueError("Sealed active outcome changed: " + record["episode_id"])


def preflight(root: Path, *, require_snapshot: bool) -> dict:
    root = root.resolve()
    args = original_args(root)
    plan = matrix.build_plan(case_pack="both", repeats=1, schedule_seed=20260825)
    stored = _read(root / "config.json")
    expected = matrix._config_payload(args, plan)
    if {k: v for k, v in stored.items() if k != "created_at"} != {
            k: v for k, v in expected.items() if k != "created_at"}:
        raise ValueError("Original launch arguments do not match the full frozen config")
    if len(plan) != 636 or (len(ACTIVE_IDS), len(JUDGE_IDS)) != (12, 13):
        raise ValueError("Unexpected frozen plan or retry target counts")
    targets = set(ACTIVE_IDS) | set(JUDGE_IDS)
    if len(targets) != 25 or targets & set(EXCLUDED_IDS):
        raise ValueError("Retry targets overlap each other or excluded active episodes")
    by_id = {spec.episode_id: spec for spec in plan}
    if not targets | set(EXCLUDED_IDS) <= set(by_id):
        raise ValueError("Retry or excluded IDs are not in the full frozen plan")
    guards, selected_rows = {}, {}
    for episode_id in (*ACTIVE_IDS, *JUDGE_IDS):
        active_path, judge_path = _paths(root, episode_id)
        row = _read(active_path)
        spec = by_id[episode_id]
        if row.get("episode_id") != episode_id or row.get("schedule_index") != spec.schedule_index:
            raise ValueError("Retry target identity differs from frozen plan: " + episode_id)
        if episode_id in ACTIVE_IDS:
            if row.get("status") != "infrastructure_failed" or row.get("active_pass") is not None:
                raise ValueError("Active retry target is no longer failed: " + episode_id)
            if judge_path.exists():
                raise ValueError("Failed active target unexpectedly has a Judge sidecar: " + episode_id)
            guarded = active_path
        else:
            if row.get("status") != "evaluated":
                raise ValueError("Judge-only target does not have a sealed active episode: " + episode_id)
            judge = _read(judge_path)
            if judge.get("status") != "infrastructure_failed":
                raise ValueError("Judge retry target is no longer failed: " + episode_id)
            guarded = judge_path
        guards[str(guarded.relative_to(root))] = _sha(guarded)
        selected_rows[episode_id] = row
    provenance = _read(root / "provenance.json")
    repo = Path(__file__).resolve().parents[1]
    source_hashes = {}
    for name, checksum in provenance["source_sha256"].items():
        if name.startswith("src/") or name in (
                "experiments/run_case_matrix.py", "experiments/codex_structured_backend.py",
                "scripts/run_codex_gpt55_both.sh"):
            if _sha(repo / name) != checksum:
                raise ValueError("Frozen execution source changed: " + name)
            source_hashes[name] = checksum
    snapshot_path = root / "recovery_history" / "attempt-00.json"
    snapshot = _read(snapshot_path) if snapshot_path.exists() else None
    if require_snapshot and (snapshot is None or not snapshot_path.with_suffix(".tar.gz").is_file()):
        raise ValueError("Root-owned attempt-00.json and attempt-00.tar.gz snapshot must exist before execution")
    if snapshot is not None:
        if set(snapshot.get("active_infrastructure_ids", [])) != set(ACTIVE_IDS):
            raise ValueError("Root snapshot active retry IDs differ from the frozen 12 IDs")
        if set(snapshot.get("judge_retry_ids", [])) != set(JUDGE_IDS):
            raise ValueError("Root snapshot Judge retry IDs differ from the frozen 13 IDs")
        _verify_sealed(root, snapshot.get("sealed_evaluated", []))
    sealed = []
    # Only sealed active results are hashed. The excluded, unfinished logs are
    # never read; if their results appear later they remain owned by the parent.
    for path in sorted((root / "results").glob("*.result.json")):
        if path.name.removesuffix(".result.json") in EXCLUDED_IDS:
            continue
        row = _read(path)
        if row.get("status") == "evaluated":
            log = Path(row["log_path"])
            log = log if log.is_absolute() else root / log
            sealed.append({"episode_id": row["episode_id"], "log_path": row["log_path"],
                           "log_sha256": _sha(log), **{key: row.get(key) for key in SEALED_FIELDS}})
    return {"args": args, "plan": by_id, "guards": guards, "selected_rows": selected_rows,
            "source_hashes": source_hashes, "sealed": sealed,
            "config_sha256": _sha(root / "config.json"),
            "snapshot_sha256": _sha(snapshot_path) if snapshot is not None else None}


def _exclusive_json(path: Path, value: Any) -> None:
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())


def _atomic_active(path: Path, value: Any, expected_sha256: str) -> None:
    descriptor, temporary = tempfile.mkstemp(prefix=".recovery-", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        if _sha(path) != expected_sha256:
            raise ValueError("Target changed before atomic commit: " + path.name)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def execute(root: Path, prepared: dict, workers: int) -> dict:
    history = root / "recovery_history"
    lock = history / "parallel_recovery.lock"
    _exclusive_json(lock, {"pid": os.getpid(), "created_at": _now()})
    outcomes = []
    try:
        # Recheck after acquiring the recovery-only lock, before any generation.
        prepared = preflight(root, require_snapshot=True)
        previous = history / "parallel_recovery_previous"
        previous.mkdir(exist_ok=False)
        for name, checksum in prepared["guards"].items():
            source = root / name
            if _sha(source) != checksum:
                raise ValueError("Target changed before archival: " + name)
            target = previous / name
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("xb") as stream:
                stream.write(source.read_bytes())
        repo = Path(__file__).resolve().parents[1]
        _exclusive_json(history / "parallel_recovery_provenance.json", {
            "created_at": _now(), "experiment_id": EXPERIMENT_ID,
            "full_plan_episodes": 636, "original_workers": 32, "recovery_workers": workers,
            "active_retry_ids": list(ACTIVE_IDS), "judge_only_retry_ids": list(JUDGE_IDS),
            "excluded_ids": list(EXCLUDED_IDS), "config_sha256": prepared["config_sha256"],
            "root_snapshot_sha256": prepared["snapshot_sha256"],
            "previous_failed_sidecars_sha256": prepared["guards"],
            "sealed_evaluated": prepared["sealed"],
            "execution_source_sha256": prepared["source_hashes"],
            "orchestration_source_sha256": {name: _sha(repo / name) for name in (
                "experiments/recover_codex_failed.py", "scripts/recover_codex_failed.sh")},
            "aggregate_policy": "No aggregate writes; original runner remains sole aggregate writer.",
            "mutation_policy": "Only listed failed sidecars may be replaced; completed active outcomes/logs are preserved.",
        })
        args = prepared["args"]
        player = matrix.load_role_backend(args, "player")
        judge = matrix.load_role_backend(args, "evaluator")
        if player is judge:
            raise ValueError("Player and Judge backends must be independent")

        def one(episode_id: str, kind: str) -> dict:
            spec = prepared["plan"][episode_id]
            active_path, judge_path = _paths(root, episode_id)
            guarded_path = active_path if kind == "active" else judge_path
            guard = prepared["guards"][str(guarded_path.relative_to(root))]
            if _sha(guarded_path) != guard:
                raise ValueError("Retry target changed before generation: " + episode_id)
            row = prepared["selected_rows"][episode_id]
            if kind == "active":
                row = matrix._run_one_episode(args, player_backend=player, oracle_backend=None,
                    output_dir=root, spec=spec, log_path=matrix._next_log_path(root, spec))
                _atomic_active(active_path, row, guard)
                if row.get("status") != "evaluated":
                    return {"episode_id": episode_id, "stage": kind,
                            "active_status": row.get("status"), "judge_status": "not_applicable"}
            evaluation = matrix._run_evaluator(args, evaluator_backend=judge, output_dir=root,
                                                spec=spec, episode_result=row)
            if kind == "judge" and _sha(judge_path) != guard:
                raise ValueError("Judge sidecar changed before commit: " + episode_id)
            if kind == "active" and judge_path.exists():
                raise ValueError("New active episode unexpectedly acquired a concurrent Judge result: " + episode_id)
            matrix._persist_evaluator_result(root, spec, evaluation)
            return {"episode_id": episode_id, "stage": kind, "active_status": row["status"],
                    "active_pass": row.get("active_pass"), "judge_status": evaluation["status"]}

        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="codex-recovery") as pool:
            futures = {pool.submit(one, episode_id, kind): (episode_id, kind)
                       for kind, ids in (("judge", JUDGE_IDS), ("active", ACTIVE_IDS)) for episode_id in ids}
            for future in as_completed(futures):
                episode_id, kind = futures[future]
                try:
                    result = future.result()
                except Exception as exc:
                    result = {"episode_id": episode_id, "stage": kind, "status": "orchestration_failed",
                              "error_type": type(exc).__name__, "error_message": str(exc)}
                outcomes.append(result)
                print(json.dumps(result, ensure_ascii=False), flush=True)
        _verify_sealed(root, prepared["sealed"])
        if _sha(root / "config.json") != prepared["config_sha256"]:
            raise ValueError("Frozen config changed during recovery")
        summary = {"completed_at": _now(), "target_count": 25, "outcomes": outcomes,
                   "sealed_active_logs_and_outcomes_preserved": True,
                   "aggregate_files_written": False}
        _exclusive_json(history / "parallel_recovery_results.json", summary)
        return summary
    finally:
        lock.unlink()


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, default=Path("runs") / EXPERIMENT_ID)
    parser.add_argument("--workers", type=int, default=25)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    if not 1 <= args.workers <= 25:
        parser.error("recovery workers must be between 1 and 25")
    root = args.run_dir.resolve()
    prepared = preflight(root, require_snapshot=not args.dry_run)
    print("Validated 12 active retries + 13 Judge-only retries; 2 unfinished IDs excluded; full 636-plan/config unchanged.", flush=True)
    if args.dry_run:
        print("Dry run: no backend loaded, no model calls, no files written.")
        return 0
    summary = execute(root, prepared, args.workers)
    return int(any(row.get("active_status") != "evaluated" or row.get("judge_status") != "evaluated"
                   for row in summary["outcomes"]))


if __name__ == "__main__":
    raise SystemExit(main())
