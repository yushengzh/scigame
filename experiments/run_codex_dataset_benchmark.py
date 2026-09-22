"""Run fresh, matched Codex Player trials with sealed results and deferred Judge.

Execute from a frozen source snapshot. Every result (including infrastructure
failure) is preserved; resumption schedules only never-attempted episodes.
"""
from __future__ import annotations

import argparse
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from dataclasses import replace
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import tempfile
import time

from experiments import run_case_matrix as matrix
from experiments.codex_structured_backend import CodexStructuredBackend


def now():
    return datetime.now(timezone.utc).isoformat()


def atomic(path, value, *, exclusive=False):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix="." + path.name, dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.write("\n")
        if exclusive:
            # Publish the completed JSON without replacing a sealed result.
            os.link(temporary, path)
        else:
            os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def methods(profile):
    fixed = [4] if profile == "main3" else [2, 4, 8]
    return ["prior-only baseline"] + [
        "fixed experimental design (%d observations)" % n for n in fixed
    ] + ["adaptive experimental design"]


def arguments(options):
    argv = ["--case-pack", "both", "--repeats", str(options.repeats),
        "--schedule-seed", "20260825", "--oracle-mode", "deterministic",
        "--player-provider", "codex", "--player-model", options.model,
        "--player-reasoning-effort", "high", "--player-timeout-s", "900",
        "--player-max-action-bytes", "262144", "--max-repair-attempts", "0",
        "--workers", str(options.workers), "--experiment-id", Path(options.output_dir).name,
        "--output-dir", str(Path(options.output_dir).resolve())]
    for method in methods(options.profile):
        argv += ["--evaluation-method", method]
    for family in options.family or []:
        argv += ["--family", family]
    return matrix._parser().parse_args(argv)


def defer_judge():
    original = matrix._runtime_profile
    def profile(args):
        runtime = original(args)
        deferred = replace(runtime.evaluator, profile_id="deferred_unconfigured",
            provider=None, endpoint=None, api=None, response_format=None, binding_id=None,
            api_key_env=None, model=None, checkpoint_or_snapshot_id=None,
            thinking=None, reasoning_effort=None, timeout_s=None)
        return replace(runtime, evaluator=deferred)
    matrix._runtime_profile = profile


def configuration(args, plan):
    config = matrix._config_payload(args, plan)
    config["design"]["evaluator_profile"] = {"status": "deferred_unconfigured", "model": None}
    config["providers"]["evaluator"] = {"name": None, "status": "deferred_unconfigured", "llm_calls": 0}
    config["evaluator_generation"] = {"mode": "deferred_unconfigured", "llm_calls": 0}
    config["execution"].update(
        evaluator_failure_policy="not_applicable_until_configured",
        evaluator_status="deferred_unconfigured", evaluator_calls=0,
        active_infrastructure_failure_policy="persist_once_no_automatic_retry",
        resume_policy="never_attempted_only; all_existing_attempts_sealed",
        episode_causality="player_oracle_turns_sequential; evaluator_deferred")
    config["execution"].setdefault("role_concurrency_limits",
        {"player": args.workers, "oracle": 0})["evaluator"] = 0
    config["player_only"] = True
    config["protocol_revision"] = "fixed-observation-prefixes-confidence-ge-0.9"
    config["binary_aggregation"] = {
        "required_repeats": list(range(1, args.repeats + 1)),
        "missing_repeat": "incomplete; never imputed as failure",
        "across_cases": "equal case weight",
        "repeat_policy": "all fresh calls; no reuse from other models or runs"}
    return config


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", required=True, choices=("gpt-5.6-sol", "gpt-6-astra"))
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--profile", choices=("main3", "five"), default="main3")
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--workers", type=int, default=16)
    parser.add_argument("--family", action="append")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--limit", type=int, help="Only select this many never-attempted episodes")
    options = parser.parse_args(argv)
    if not 1 <= options.workers <= 64 or options.repeats < 1 or (options.limit is not None and options.limit < 1):
        parser.error("workers must be 1..64, repeats and limit positive")
    defer_judge()
    args = arguments(options)
    plan = matrix.build_plan(args.schedule_seed, case_pack="both", repeats=args.repeats,
        families=args.family, evaluation_methods=args.evaluation_method)
    output = Path(options.output_dir).resolve()
    matrix.prepare_output(output, configuration(args, plan))
    rows = matrix.load_episode_results(output)
    existing = {row["episode_id"]: row for row in rows}
    expected = {spec.episode_id: spec for spec in plan}
    if len(existing) != len(rows) or set(existing) - set(expected):
        raise ValueError("Duplicate or unexpected result identities")
    for key, row in existing.items():
        if row.get("schedule_index") != expected[key].schedule_index or row.get("player_model") != options.model:
            raise ValueError("Existing result differs from frozen schedule/model: " + key)
    pending = [spec for spec in plan if spec.episode_id not in existing]
    # An interrupted partial trajectory is evidence, never permission to retry it.
    orphaned = [spec.episode_id for spec in pending
                if (output / "episodes" / (spec.episode_id + ".jsonl")).exists()]
    if orphaned:
        raise ValueError("Unsealed trajectories require explicit recovery: " + ", ".join(orphaned))
    if options.limit:
        pending = pending[:options.limit]
    preview = {"model": options.model, "profile": options.profile, "planned_n": len(plan),
        "selected_n": len(pending), "workers": options.workers, "repeats": options.repeats,
        "reasoning_effort": "high", "judge": "deferred_unconfigured"}
    print(json.dumps(preview, ensure_ascii=False), flush=True)
    if options.dry_run:
        matrix.write_summaries(output)
        atomic(output / "driver_status.json", {"status": "prepared", "updated_at": now(), **preview})
        return 0
    for spec in {spec.cell: spec for spec in pending}.values():
        matrix._prepare_case(spec)
    lock = output / ".player_execution.lock"
    descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    os.write(descriptor, str(os.getpid()).encode())
    os.close(descriptor)
    state = {"status": "running", "pid": os.getpid(), "started_at": now(), **preview}
    finished = []
    last_summary = 0.0
    def progress(status):
        recorded = matrix.load_episode_results(output)
        state.update(status=status, updated_at=now(),
            finished_this_run_n=sum(r["episode_id"] not in existing for r in recorded),
            recorded_n=len(recorded),
            evaluated_n=sum(r.get("status") == "evaluated" for r in recorded),
            infrastructure_n=sum(r.get("status") != "evaluated" for r in recorded))
        atomic(output / "driver_status.json", state)
    def execute(spec):
        result_path = output / "results" / (spec.episode_id + ".result.json")
        log_path = output / "episodes" / (spec.episode_id + ".jsonl")
        # The plan was read before acquiring the run lock; a preceding process
        # may have sealed an episode while this process was still preparing.
        if result_path.exists() or log_path.exists():
            raise ValueError("Refusing to rerun an existing attempt: " + spec.episode_id)
        result = matrix._run_one_episode(args, player_backend=backend, oracle_backend=None,
            output_dir=output, spec=spec, log_path=log_path)
        result["evaluator_status"] = "deferred_unconfigured"
        result["protocol_revision"] = "fixed-observation-prefixes-confidence-ge-0.9"
        atomic(result_path, result, exclusive=True)
        return result
    try:
        progress("running")
        backend = CodexStructuredBackend(model=options.model, reasoning_effort="high", timeout_s=900,
            audit_dir=output / "codex_calls", role="player")
        streak = 0
        halted = False
        iterator = iter(pending)
        with ThreadPoolExecutor(max_workers=options.workers) as pool:
            active = {pool.submit(execute, spec) for spec in pending[:options.workers]}
            for _ in range(min(len(pending), options.workers)):
                next(iterator)
            while active:
                done, active = wait(active, timeout=30, return_when=FIRST_COMPLETED)
                for future in done:
                    result = future.result()
                    finished.append(result)
                    ok = result.get("status") == "evaluated"
                    streak = 0 if ok else streak + 1
                    halted = halted or streak >= 4
                    print(json.dumps({k: result.get(k) for k in
                        ("episode_id", "status", "active_pass", "error_type", "error_message")}), flush=True)
                    if not halted:
                        spec = next(iterator, None)
                        if spec is not None:
                            active.add(pool.submit(execute, spec))
                if time.monotonic() - last_summary >= 60:
                    matrix.write_summaries(output)
                    last_summary = time.monotonic()
                progress("draining_after_infrastructure_failures" if halted else "running")
        matrix.write_summaries(output)
        all_rows = list(existing.values()) + finished
        complete = len(all_rows) == len(plan) and all(r.get("status") == "evaluated" for r in all_rows)
        progress("player_complete" if complete else "needs_attention" if halted else "incomplete")
        return 0 if complete or (options.limit and not halted) else 1
    except BaseException as exc:
        state["error"] = type(exc).__name__ + ": " + str(exc)
        matrix.write_summaries(output)
        progress("interrupted")
        raise
    finally:
        lock.unlink()


if __name__ == "__main__":
    raise SystemExit(main())
