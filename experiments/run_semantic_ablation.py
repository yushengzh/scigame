"""Preregistered matched semantic-cue intervention, with immutable attempts.

Run from this study's frozen snapshot. No result or partial trajectory is ever
silently retried, and infrastructure missingness is never a scientific failure.
"""
from __future__ import annotations

import argparse
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from dataclasses import asdict, replace
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import random
import tempfile
import time

from experiments import run_case_matrix as matrix
from experiments.codex_structured_backend import CodexStructuredBackend
from experiments.semantic_ablation import adapt_prepared_case, opaque_case_id
from role_benchmark import GenerationConfig, run_llm_episode
from role_benchmark.performance import formula_metric
from role_benchmark.wire import final_submission_to_payload


MODELS = ("gpt-5.6-sol", "gpt-6-astra")
ARMS = ("familiar", "anonymous")
METHODS = ("adaptive experimental design", "fixed experimental design (4 observations)")
WORLDS = ("original", "counterfactual")
REPEATS = 3
SEED = 20260919
SCHEMA = "scigame.semantic_prior_control.v1"


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
            os.link(temporary, path)
        else:
            os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
        separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def source_hashes():
    root = Path(__file__).resolve().parent.parent
    paths = []
    for part in ("src", "experiments", "datasets"):
        paths.extend(p for p in (root / part).rglob("*")
            if p.is_file() and p.suffix in (".py", ".json") and "__pycache__" not in p.parts)
    return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(paths)}


def build_schedule():
    rng = random.Random(SEED)
    families = tuple(sorted(matrix.CASE_PACKS["historical"].families))
    result = []
    # Each small block includes both worlds, both arms, and both models.
    # Blocks/repeats are randomized before observing any new outputs.
    for repeat in range(1, REPEATS + 1):
        blocks = [(family, method) for family in families for method in METHODS]
        rng.shuffle(blocks)
        for family, method in blocks:
            group = [(model, arm, world) for model in MODELS
                     for arm in ARMS for world in WORLDS]
            rng.shuffle(group)
            for model, arm, world in group:
                short_method = "adaptive" if method == METHODS[0] else "fixed4"
                episode_id = "__".join((family, world, arm, short_method,
                    "sol" if model == MODELS[0] else "astra", "r%02d" % repeat))
                result.append({"schedule_index": len(result), "episode_id": episode_id,
                    "case_family": family, "world": world, "semantic_arm": arm,
                    "player_model": model, "evaluation_method": method, "repeat": repeat,
                    "result_path": "results/" + episode_id + ".result.json",
                    "log_path": "episodes/" + episode_id + ".jsonl",
                    "opaque_case_id": opaque_case_id("semantic-prior-control-v1:" + family)})
    return result


def make_spec(row):
    world = "historical" if row["world"] == "original" else "counterfactual"
    original_plan = matrix.build_plan(SEED, case_pack="historical", repeats=1,
        families=[row["case_family"]], evaluation_methods=[row["evaluation_method"]])
    spec = next(s for s in original_plan if s.condition_id == world and s.task_setting == "discovery")
    return replace(spec, episode_id=row["episode_id"], schedule_index=row["schedule_index"], repeat=row["repeat"])


def prepare(row):
    spec = make_spec(row)
    original = matrix._prepare_case(spec)
    return spec, adapt_prepared_case(original, arm=row["semantic_arm"], opaque_id=row["opaque_case_id"])


def runtime(model):
    args = matrix._parser().parse_args(["--case-pack", "historical", "--output-dir", ".",
        "--player-provider", "codex", "--player-model", model,
        "--player-reasoning-effort", "high", "--player-timeout-s", "900", "--oracle-mode", "deterministic"])
    value = matrix._runtime_profile(args)
    return replace(value, evaluator=replace(value.evaluator, profile_id="deferred_unconfigured",
        provider=None, endpoint=None, api=None, response_format=None, binding_id=None,
        api_key_env=None, model=None, checkpoint_or_snapshot_id=None,
        thinking=None, reasoning_effort=None, timeout_s=None))


def configuration(study, workers):
    schedule = build_schedule()
    return {"schema": SCHEMA, "experiment_id": study.name, "created_at": now(),
        "design": {"families": sorted(matrix.CASE_PACKS["historical"].families),
            "models": list(MODELS), "semantic_arms": list(ARMS), "worlds": list(WORLDS),
            "methods": list(METHODS), "task_setting": "discovery", "repeats": REPEATS,
            "primary_outcome": "evaluation_success", "co_reported_outcomes": ["active_pass", "protocol_completion"],
            "primary_contrast": "counterfactual: anonymous minus familiar, separately per model, adaptive",
            "interaction": "(anonymous-familiar)_counterfactual - (anonymous-familiar)_original",
            "secondary_design": "fixed4 isolates semantic effects with identical supplied observations",
            "inference_unit": "family; equal family weights; all 3 repeats required; paired cluster bootstrap",
            "missingness": "infrastructure unresolved, never zero; full-matrix estimate withheld until complete",
            "intervention": "same neutral machine interface; familiar-only original semantic sidecard",
            "shared_cleanup": "remove registered-sibling/identifiability hints in both arms; regenerate neutral shared notes",
            "interpretation": "effect of explicit semantic cues on these 20 families; numeric fingerprints remain",
            "reference_experiment": "EXP-CODEX-SOL-ASTRA-20260918; previous results are observational context only"},
        "schedule": {"seed": SEED, "policy": "randomized repeat blocks; interleaved model-arm-world blocks",
            "episodes": schedule},
        "execution": {"workers": workers, "provider": "codex", "reasoning_effort": "high",
            "oracle": "deterministic", "judge": "deferred_unconfigured", "per_request_timeout_s": 900,
            "player_prompt_version": matrix.PLAYER_PROMPT_VERSION_V5_PERFORMANCE,
            "max_action_bytes": 262144, "automatic_repairs": 0,
            "adaptive_observation_or_action_cap": None, "confidence_threshold": 0.9,
            "sampling_seed_supported": False, "sampling_temperature_enforced": False,
            "max_output_tokens_enforced": False, "model_fallback": False,
            "resume_policy": "never attempted only; preserve every result and partial log",
            "circuit_breaker": "stop scheduling after 4 consecutive infrastructure failures; drain active calls"},
        "source_files_sha256": source_hashes()}


def verify_configuration(study, config, workers):
    expected = configuration(study, workers)
    expected["created_at"] = config["created_at"]
    if config != expected:
        raise ValueError("Frozen configuration, source, schedule, or execution settings changed")


def diagnostics(log_path):
    values = {"initial_max_confidence": None, "initial_portfolio_valid": None}
    for line in log_path.read_text().splitlines():
        event = json.loads(line)
        if event.get("event_type") == "action.decoded":
            hypotheses = event["payload"]["action"]["portfolio"]["hypotheses"]
            confidences = [h["confidence"] for h in hypotheses]
            total = sum(confidences)
            values["initial_portfolio_valid"] = bool(confidences) and abs(total - 1.0) <= 1e-6
            if values["initial_portfolio_valid"]:
                values["initial_max_confidence"] = max(confidences)
            break
    return values


def execute_one(study, row, config):
    started_at, started_clock = now(), time.monotonic()
    log_path = study / row["log_path"]
    result_path = study / row["result_path"]
    if result_path.exists() or log_path.exists():
        raise ValueError("Attempt already exists: " + row["episode_id"])
    spec, adapted = prepare(row)
    prepared = adapted.prepared
    rt = runtime(row["player_model"])
    backend = CodexStructuredBackend(model=row["player_model"], reasoning_effort="high",
        timeout_s=900, audit_dir=study / "calls" / row["episode_id"], role="player")
    try:
        run = run_llm_episode(backend, adapted.case, str(log_path),
            config=GenerationConfig(max_output_tokens=8192, temperature=0.0, top_p=1.0, seed=None),
            player_prompt_version=matrix.PLAYER_PROMPT_VERSION_V5_PERFORMANCE,
            max_repair_attempts=0, max_action_bytes=262144, max_actions=None,
            run_id=row["episode_id"], observation_budget=prepared.plan.observation_budget,
            initial_attempts_used=prepared.initial_attempts_used,
            require_budget_exhaustion=prepared.plan.require_budget_exhaustion,
            run_metadata={"experiment_id": study.name, "schema": SCHEMA, **row,
                "player_provider": "codex", "player_reasoning_effort": "high",
                "oracle_mode": "deterministic", "evaluator_status": "deferred_unconfigured",
                "mapping_sha256": digest(adapted.manifest), "configuration_sha256": digest(config),
                "fixed_observations": [matrix.fixed_observation_to_payload(x) for x in prepared.fixed_observations]})
        result = dict(matrix._evaluated_result(spec=spec, log_path=log_path, output_dir=study,
            run=run, started_at=started_at, elapsed_s=time.monotonic() - started_clock,
            runtime=rt, experiment_id=study.name, oracle_mode="deterministic"))
        try:
            result.update(diagnostics(log_path))
            original_final = (adapted.to_original_submission(run.outcome.final_submission)
                              if run.outcome.final_submission is not None else None)
            result["original_coordinate_final_submission"] = (final_submission_to_payload(original_final)
                if original_final is not None else None)
            family_spec = matrix.CASE_PACKS["historical"].specifications[row["case_family"]]["canonical"]
            result["formula_consistency"] = formula_metric(original_final, family_spec,
                "historical" if row["world"] == "original" else "counterfactual")
            if row["world"] == "counterfactual" and original_final is not None:
                original_case = matrix.make_matched_case(family_spec, "historical", matrix.BenchmarkTrack.DISCOVERY)
                original_score = original_case.evaluator.evaluate(original_final)
                result["inactive_original_prediction_success"] = original_score.success
                result["inactive_original_prediction_scores"] = dict(original_score.scores)
        except Exception as exc:
            # Ancillary diagnostics must never discard an already-scored episode.
            result["diagnostic_error"] = type(exc).__name__ + ": " + str(exc)
    except Exception as exc:
        result = dict(matrix._infrastructure_failed_result(spec=spec, log_path=log_path,
            output_dir=study, exc=exc, started_at=started_at,
            elapsed_s=time.monotonic() - started_clock, runtime=rt,
            experiment_id=study.name, oracle_mode="deterministic"))
    result.update({k: row[k] for k in ("world", "semantic_arm", "player_model", "repeat", "schedule_index")})
    result.update(study_schema=SCHEMA, configuration_sha256=digest(config),
        mapping_sha256=digest(adapted.manifest), evaluator_status="deferred_unconfigured",
        final_selected_confidence=(result.get("scores") or {}).get("selected_portfolio_confidence"))
    atomic(result_path, result, exclusive=True)
    return result


def inventory(study, config):
    planned = {r["episode_id"]: r for r in config["schedule"]["episodes"]}
    rows = {}
    for path in sorted((study / "results").glob("*.result.json")):
        value = json.loads(path.read_text())
        key = value.get("episode_id")
        if key not in planned or key in rows or path != study / planned[key]["result_path"]:
            raise ValueError("Duplicate, unexpected or misplaced result")
        for field in ("case_family", "world", "semantic_arm", "player_model", "evaluation_method", "repeat", "schedule_index"):
            if value.get(field) != planned[key][field]:
                raise ValueError("Result identity mismatch: " + key + " / " + field)
        if value.get("configuration_sha256") != digest(config):
            raise ValueError("Result configuration mismatch: " + key)
        rows[key] = value
    pending = [r for r in config["schedule"]["episodes"] if r["episode_id"] not in rows]
    for row in pending:
        if (study / row["log_path"]).exists() or (study / "calls" / row["episode_id"]).exists():
            raise ValueError("Partial attempted episode needs explicit recovery: " + row["episode_id"])
    return rows, pending


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--study-dir", required=True)
    parser.add_argument("--workers", type=int, default=16)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--limit", type=int)
    options = parser.parse_args(argv)
    if not 1 <= options.workers <= 32 or (options.limit is not None and options.limit < 1):
        parser.error("workers must be 1..32; limit must be positive")
    study = Path(options.study_dir).resolve()
    study.mkdir(parents=True, exist_ok=True)
    for name in ("results", "episodes", "mappings"):
        (study / name).mkdir(exist_ok=True)
    path = study / "config.json"
    if path.exists():
        config = json.loads(path.read_text())
        verify_configuration(study, config, options.workers)
    else:
        config = configuration(study, options.workers)
        atomic(path, config, exclusive=True)
    existing, pending = inventory(study, config)
    cells = {}
    for row in config["schedule"]["episodes"]:
        key = (row["case_family"], row["world"], row["semantic_arm"], row["evaluation_method"])
        cells.setdefault(key, row)
    for row in cells.values():
        _, adapted = prepare(row)
        mapping_path = study / "mappings" / (row["episode_id"].rsplit("__", 2)[0] + ".json")
        if mapping_path.exists():
            if digest(json.loads(mapping_path.read_text())) != digest(adapted.manifest):
                raise ValueError("Semantic mapping changed")
        else:
            atomic(mapping_path, adapted.manifest, exclusive=True)
    status = {"schema": SCHEMA, "planned_n": len(config["schedule"]["episodes"]),
        "selected_n": min(len(pending), options.limit or len(pending)), "workers": options.workers,
        "configuration_sha256": digest(config), "pid": os.getpid(), "started_at": now()}
    def progress(label, active=()):
        all_rows = list(existing.values())
        status.update(status=label, updated_at=now(), recorded_n=len(all_rows),
            evaluated_n=sum(r.get("status") == "evaluated" for r in all_rows),
            infrastructure_n=sum(r.get("status") != "evaluated" for r in all_rows),
            active_episode_ids=list(active))
        atomic(study / "driver_status.json", status)
    print(json.dumps(status), flush=True)
    if options.dry_run:
        progress("prepared")
        return 0
    selected = pending[:options.limit] if options.limit else pending
    lock = study / ".execution.lock"
    fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    os.write(fd, str(os.getpid()).encode()); os.close(fd)
    try:
        iterator = iter(selected)
        streak = 0
        halted = False
        with ThreadPoolExecutor(max_workers=options.workers) as pool:
            active = {}
            for _ in range(min(options.workers, len(selected))):
                row = next(iterator)
                active[pool.submit(execute_one, study, row, config)] = row["episode_id"]
            while active:
                progress("draining_after_infrastructure_failures" if halted else "running", active.values())
                done, _ = wait(active, timeout=30, return_when=FIRST_COMPLETED)
                for future in done:
                    active.pop(future)
                    result = future.result()
                    existing[result["episode_id"]] = result
                    streak = 0 if result.get("status") == "evaluated" else streak + 1
                    halted = halted or streak >= 4
                    print(json.dumps({k: result.get(k) for k in ("episode_id", "status", "evaluation_success", "active_pass", "error_type")}), flush=True)
                    if not halted:
                        row = next(iterator, None)
                        if row is not None:
                            active[pool.submit(execute_one, study, row, config)] = row["episode_id"]
        complete = len(existing) == len(config["schedule"]["episodes"]) and all(r.get("status") == "evaluated" for r in existing.values())
        progress("complete" if complete else "needs_attention" if halted else "incomplete")
        return 0 if complete or (options.limit and not halted) else 1
    except BaseException as exc:
        status["error"] = type(exc).__name__ + ": " + str(exc)
        progress("interrupted")
        raise
    finally:
        lock.unlink()


if __name__ == "__main__":
    raise SystemExit(main())
