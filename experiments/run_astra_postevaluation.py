#!/usr/bin/env python3
"""Run resumable, concurrent Astra Judge calls for a prepared post-evaluation.

Preparation and scientific scoring belong to postevaluate_science/run_case_matrix.
This driver only validates inputs, schedules the Judge, and retains its attempts.
"""

from __future__ import annotations

import argparse
from collections import Counter
from collections.abc import Mapping
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import time

from experiments import postevaluate_science as post
from experiments import run_case_matrix as matrix
from experiments.codex_structured_backend import CodexStructuredBackend
from role_benchmark.discovery_evaluation import DISCOVERY_INSTRUCTION, discovery_json_schema
from role_benchmark.runlog import load_run_log
from role_benchmark.wire import canonical_json_dumps


MODEL = "gpt-6-astra"
EFFORT = "high"
TIMEOUT_S = 900.0
MAX_OUTPUT_TOKENS = 8192
DEFAULT_WORKERS = 16
SUMMARY_INTERVAL_S = 60.0
SUMMARY_INTERVAL_N = 25
FAILURE_LIMIT = 8
JUDGE_SCHEMA = discovery_json_schema()
JUDGE_SYSTEM_PROMPT = DISCOVERY_INSTRUCTION + "\nEvaluator JSON Schema:\n" + canonical_json_dumps(JUDGE_SCHEMA)


def now():
    return datetime.now(timezone.utc).isoformat()


def _parser():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--workers", type=int, default=DEFAULT_WORKERS)
    parser.add_argument("--limit", type=int, help="Judge at most this many pending episodes, including their retries")
    parser.add_argument("--retry-passes", type=int, default=1, help="Additional passes over failed/missing selected Judge results")
    return parser


def evaluator_args(output):
    return matrix._parser().parse_args([
        "--output-dir", str(output), "--case-pack", "both",
        "--evaluator-provider", "codex", "--evaluator-model", MODEL,
        "--evaluator-reasoning-effort", EFFORT,
        "--evaluator-timeout-s", str(TIMEOUT_S),
        "--evaluator-max-output-tokens", str(MAX_OUTPUT_TOKENS),
    ])


def incompatibility(value, row):
    """Return a bounded reason; never treat a different Judge/run as reusable."""
    if not isinstance(value, Mapping):
        return "missing_judge_result"
    if not isinstance(row.get("run_id"), str) or not row["run_id"]:
        return "episode_run_id_missing"
    expected = {
        "status": "evaluated", "episode_id": row["episode_id"],
        "run_id": row.get("run_id"), "evaluator_provider": "codex",
        "evaluator_model": MODEL,
        "evaluator_reasoning_effort": EFFORT,
        "evaluator_prompt_version": matrix.DISCOVERY_PROMPT_VERSION,
    }
    for key, wanted in expected.items():
        if value.get(key) != wanted:
            return "judge_" + key + "_mismatch"
    response = value.get("response")
    if not isinstance(response, Mapping) or response.get("model") != MODEL:
        return "judge_response_model_mismatch"
    if response.get("provider") != "codex":
        return "judge_response_provider_mismatch"
    request = value.get("request")
    if not isinstance(request, Mapping) or request.get("response_schema") != JUDGE_SCHEMA:
        return "judge_response_schema_mismatch"
    messages = request.get("messages")
    if (not isinstance(messages, list) or len(messages) != 2
            or not all(isinstance(message, Mapping) for message in messages)
            or messages[0].get("role") != "system"
            or messages[1].get("role") != "user"
            or messages[0].get("content") != JUDGE_SYSTEM_PROMPT):
        return "judge_system_prompt_mismatch"
    evaluation = value.get("evaluation")
    details = evaluation.get("details") if isinstance(evaluation, Mapping) else None
    if not isinstance(details, Mapping) or not isinstance(details.get("understanding"), dict):
        return "judge_understanding_missing"
    return None


def usable(value, row):
    return incompatibility(value, row) is None


@contextmanager
def output_lock(output):
    """Keep the file descriptor open for the entire invocation; never unlink it."""
    with (output / ".astra_judge.lock").open("a+", encoding="utf-8") as stream:
        try:
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ValueError("another Astra Judge process holds this output directory") from exc
        try:
            stream.seek(0)
            stream.truncate()
            json.dump({"pid": os.getpid(), "locked_at": now()}, stream)
            stream.flush()
            yield
        finally:
            fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def write_progress(output, payload):
    path = output / "astra_judge_progress.json"
    temporary = path.with_suffix(".json.tmp")
    matrix._write_json(temporary, payload)
    temporary.replace(path)


def _validate_manifest(output, source, rows):
    """When preparation froze inputs, enforce that freeze before any requests."""
    path = output / "input_manifest.json"
    if not path.exists():
        return
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if (manifest.get("judge_model") != MODEL or manifest.get("judge_reasoning_effort") != EFFORT
            or manifest.get("source_run_dir") != str(source)
            or manifest.get("output_dir") != str(output)):
        raise ValueError("input manifest does not identify this output/source and Astra/high Judge")
    episode_ids = {row["episode_id"] for row in rows}
    prepared = manifest.get("prepared_results_sha256")
    sources = manifest.get("source_inputs")
    if (not isinstance(prepared, dict) or not isinstance(sources, dict)
            or set(prepared) != episode_ids or set(sources) != episode_ids
            or manifest.get("episode_n") != len(rows)):
        raise ValueError("input manifest episode cohort differs from prepared results")
    cached = {}

    def check(raw_path, expected):
        file_path = Path(raw_path)
        if not file_path.is_absolute() or not isinstance(expected, str) or len(expected) != 64:
            raise ValueError("input manifest requires absolute paths and SHA-256 hashes")
        if file_path not in cached:
            digest = hashlib.sha256()
            with file_path.open("rb") as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(chunk)
            cached[file_path] = digest.hexdigest()
        if cached[file_path] != expected:
            raise ValueError("frozen input SHA-256 mismatch: " + str(file_path))

    check(output / "config.json", manifest.get("posteval_config_sha256"))
    check(source / "config.json", manifest.get("source_config_sha256"))
    for row in rows:
        episode_id = row["episode_id"]
        check(output / "results" / (episode_id + ".result.json"), prepared[episode_id])
        receipt = sources[episode_id]
        hashes = receipt.get("sha256") if isinstance(receipt, dict) else None
        if not isinstance(hashes, dict) or not hashes:
            raise ValueError("input manifest source hashes missing: " + episode_id)
        for raw_path, digest in hashes.items():
            check(raw_path, digest)
        raw_log = row.get("log_path")
        if not row.get("post_evaluation_exclusion_reason") and raw_log not in hashes:
            raise ValueError("eligible run log is absent from frozen source inputs: " + episode_id)
        origin = receipt.get("origin")
        if isinstance(origin, dict) and "source_result_sha256" in origin:
            check(origin["source_result"], origin["source_result_sha256"])


def preflight(output):
    """Validate the complete input set before any request or sidecar mutation."""
    config = json.loads((output / "config.json").read_text(encoding="utf-8"))
    if not isinstance(config, dict) or config.get("mode") != post.MODE:
        raise ValueError("output must have a prepared scientific_postevaluation_only config")
    if not isinstance(config.get("source_run_dir"), str) or not config["source_run_dir"]:
        raise ValueError("post-evaluation config is missing source_run_dir")
    source = Path(config["source_run_dir"]).resolve()
    if source == output or source in output.parents or output in source.parents:
        raise ValueError("post-evaluation output and source run must be separate directories")
    source_config = json.loads((source / "config.json").read_text(encoding="utf-8"))
    experiment_id = config.get("experiment_id")
    if not experiment_id or source_config.get("experiment_id") != experiment_id:
        raise ValueError("post-evaluation and source config experiment_id differ")
    rows = matrix.load_episode_results(output)
    if not rows:
        raise ValueError("no prepared results/*.result.json found")
    _validate_manifest(output, source, rows)
    eligible, excluded, existing, seen = [], {}, {}, set()
    for row in rows:
        episode_id = row.get("episode_id")
        if (not isinstance(episode_id, str) or not episode_id
                or Path(episode_id).name != episode_id or episode_id in {".", ".."}
                or episode_id in seen):
            raise ValueError("episode IDs must be unique, nonempty filename-safe strings")
        seen.add(episode_id)
        if row.get("experiment_id") != experiment_id:
            raise ValueError("episode and config experiment_id differ: " + episode_id)
        spec = post._episode_spec(row)
        existing[episode_id] = matrix._load_evaluator_result(output, episode_id)
        reason = row.get("post_evaluation_exclusion_reason")
        if reason is not None:
            if not isinstance(reason, str) or not reason.strip():
                raise ValueError("exclusion requires a nonempty documented reason: " + episode_id)
            excluded[episode_id] = reason
            continue
        raw_path = row.get("log_path")
        if not isinstance(raw_path, str) or not raw_path:
            raise ValueError("eligible episode has no run log: " + episode_id)
        path = Path(raw_path)
        path = (path if path.is_absolute() else output / path).resolve()
        log = load_run_log(str(path))
        if not log.complete or not row.get("run_id") or log.run_id != row["run_id"]:
            raise ValueError("eligible episode must identify its own completed run log: " + episode_id)
        case = log.events[0]["payload"].get("case", {})
        if not row.get("case_id") or case.get("case_id") != row["case_id"]:
            raise ValueError("episode and run log case_id differ: " + episode_id)
        if case.get("track") != row.get("task_setting"):
            raise ValueError("episode and run log task_setting differ: " + episode_id)
        eligible.append((spec, row))
    eligible.sort(key=lambda item: item[0].episode_id)
    return rows, eligible, excluded, existing


def _retire_incompatible(output, spec, value):
    """Retain a stale evaluated receipt, then remove it from summary visibility."""
    path = matrix._evaluator_result_path(output, spec)
    history = path.parent / "attempts" / spec.episode_id
    history.mkdir(parents=True, exist_ok=True)
    attempts = sorted(history.glob("*.json"))
    if not attempts or json.loads(attempts[-1].read_text(encoding="utf-8")) != value:
        index = max((int(p.stem) for p in attempts if p.stem.isdigit()), default=0) + 1
        matrix._write_json(history / ("%04d.json" % index), value, exclusive=True)
    path.unlink()


def _failed_exception(spec, row, exc):
    # Exceptions outside matrix's decoder must not spill arbitrary backend text.
    return {
        "schema": matrix.LLM_EVALUATOR_RESULT_SCHEMA,
        "experiment_id": row.get("experiment_id"), "episode_id": spec.episode_id,
        "run_id": row.get("run_id"), "status": "infrastructure_failed",
        "evaluator_provider": "codex", "evaluator_model": MODEL,
        "evaluator_reasoning_effort": EFFORT,
        "evaluator_prompt_version": matrix.DISCOVERY_PROMPT_VERSION,
        "ended_at": now(), "response": None, "evaluation": None,
        "error_type": type(exc).__name__,
        "error_message": "Judge worker failed before returning a valid result",
    }


def run(options, *, backend_factory=None):
    if not 1 <= options.workers <= 32:
        raise ValueError("workers must be in 1..32")
    if options.limit is not None and options.limit < 1:
        raise ValueError("limit must be positive")
    if options.retry_passes < 0:
        raise ValueError("retry-passes must be nonnegative")
    output = Path(options.output_dir).resolve()
    with output_lock(output):
        return _run_locked(options, output, backend_factory=backend_factory)


def _run_locked(options, output, *, backend_factory=None):
    rows, eligible, excluded, existing = preflight(output)
    # The shared summary code accepts other Judge models. Hide incompatible old
    # successes before the first summary, while retaining their full receipts.
    retired = {}
    for row in rows:
        value = existing[row["episode_id"]]
        if value and value.get("status") == "evaluated" and not usable(value, row):
            spec = post._episode_spec(row)
            retired[spec.episode_id] = incompatibility(value, row)
            _retire_incompatible(output, spec, value)
            existing[spec.episode_id] = None
    selected = [item for item in eligible if not usable(existing[item[0].episode_id], item[1])]
    if options.limit is not None:
        selected = selected[:options.limit]
    args = evaluator_args(output)
    backend_factory = backend_factory or (lambda: CodexStructuredBackend(
        model=MODEL, reasoning_effort=EFFORT, timeout_s=TIMEOUT_S,
        audit_dir=output / "codex_calls", role="evaluator"))
    started = now()
    progress = {
        "schema": "scigame.astra_judge_progress.v2", "started_at": started,
        "status": "running", "pid": os.getpid(), "model": MODEL,
        "reasoning_effort": EFFORT, "timeout_s": TIMEOUT_S,
        "max_output_tokens_requested": MAX_OUTPUT_TOKENS,
        "workers": options.workers, "retry_passes": options.retry_passes,
        "source_episode_n": len(rows), "eligible_episode_n": len(eligible),
        "excluded_episode_ids": sorted(excluded), "exclusions": excluded,
        "retired_incompatible_results": retired,
        "already_complete_n": sum(usable(existing[s.episode_id], r) for s, r in eligible),
        "selected_n": len(selected), "completed_this_run_n": 0,
        "evaluated_this_run_n": 0, "infrastructure_failed_this_run_n": 0,
        "pass_index": 0, "active_n": 0, "active_episode_ids": [],
        "consecutive_infrastructure_failures": 0, "failure_reasons": {},
        "latest_failures": {},
    }
    successes, attempted = set(), set()
    failures = Counter()
    last_summary, since_summary = time.monotonic(), 0
    paused = False

    def refresh(*, summaries=False):
        nonlocal last_summary, since_summary
        progress["updated_at"] = now()
        progress["usable_this_run_n"] = len(successes)
        progress["attempted_episode_n"] = len(attempted)
        progress["usable_n"] = sum(usable(existing[s.episode_id], r) for s, r in eligible)
        progress["overall_usable_n"] = sum(usable(existing[r["episode_id"]], r) for r in rows)
        progress["remaining_n"] = len(eligible) - progress["usable_n"]
        progress["selected_remaining_n"] = sum(not usable(existing[s.episode_id], r) for s, r in selected)
        progress["failure_reasons"] = dict(failures)
        if summaries or since_summary >= SUMMARY_INTERVAL_N or time.monotonic() - last_summary >= SUMMARY_INTERVAL_S:
            matrix.write_summaries(output)
            last_summary, since_summary = time.monotonic(), 0
            progress["summaries_updated_at"] = now()
        write_progress(output, progress)

    def judge(item):
        spec, row = item
        try:
            result = matrix._run_evaluator(args, evaluator_backend=backend_factory(),
                output_dir=output, spec=spec, episode_result=row)
            if not isinstance(result, Mapping):
                raise ValueError("Judge returned a non-object result")
            result = dict(result)
            reason = incompatibility(result, row)
            if result.get("status") == "evaluated" and reason:
                result.update(status="infrastructure_failed", original_status="evaluated",
                              error_type="InvalidJudgeResult", error_message=reason)
            return result
        except Exception as exc:
            return _failed_exception(spec, row, exc)

    refresh(summaries=True)
    for pass_index in range(options.retry_passes + 1):
        work = [item for item in selected if not usable(existing[item[0].episode_id], item[1])]
        if not work or paused:
            break
        progress["pass_index"] = pass_index
        with ThreadPoolExecutor(max_workers=options.workers) as pool:
            active, next_index = {}, 0
            while active or (not paused and next_index < len(work)):
                while not paused and len(active) < options.workers and next_index < len(work):
                    item = work[next_index]
                    active[pool.submit(judge, item)] = item
                    next_index += 1
                progress["active_n"] = len(active)
                progress["active_episode_ids"] = sorted(item[0].episode_id for item in active.values())
                progress["unscheduled_this_pass_n"] = len(work) - next_index
                refresh()
                done, _ = wait(active, timeout=SUMMARY_INTERVAL_S, return_when=FIRST_COMPLETED)
                for future in done:
                    spec, row = active.pop(future)
                    result = future.result()
                    # Only the coordinator writes artifacts and summaries.
                    matrix._persist_evaluator_result(output, spec, result)
                    existing[spec.episode_id] = result
                    attempted.add(spec.episode_id)
                    since_summary += 1
                    progress["completed_this_run_n"] += 1
                    progress["last_episode_id"] = spec.episode_id
                    if usable(result, row):
                        successes.add(spec.episode_id)
                        progress["evaluated_this_run_n"] += 1
                        progress["consecutive_infrastructure_failures"] = 0
                        progress["latest_failures"].pop(spec.episode_id, None)
                    else:
                        progress["infrastructure_failed_this_run_n"] += 1
                        progress["consecutive_infrastructure_failures"] += 1
                        reason = str(result.get("error_type") or incompatibility(result, row))
                        message = str(result.get("error_message") or reason)[:1000]
                        failures[reason] += 1
                        progress["latest_failures"][spec.episode_id] = {"reason": reason, "message": message}
                        if progress["consecutive_infrastructure_failures"] >= FAILURE_LIMIT:
                            paused = True
                            progress["status"] = "draining_after_infrastructure_failures"
                            progress["stopped_scheduling_reason"] = "8_consecutive_infrastructure_failures"
                progress["active_n"] = len(active)
                progress["active_episode_ids"] = sorted(item[0].episode_id for item in active.values())
                refresh()
    progress["status"] = (
        "paused_infrastructure_failures" if paused else
        "completed_with_infrastructure_failures" if progress["selected_remaining_n"] else
        "completed_limited" if progress["remaining_n"] else "complete")
    progress["completed_at"] = now()
    refresh(summaries=True)
    return progress


def main(argv=None):
    parser = _parser()
    options = parser.parse_args(argv)
    try:
        progress = run(options)
    except (ValueError, OSError) as exc:
        parser.error(str(exc))
    print(json.dumps(progress, ensure_ascii=False, sort_keys=True), flush=True)
    return int(progress["status"] not in {"complete", "completed_limited"})


if __name__ == "__main__":
    raise SystemExit(main())
