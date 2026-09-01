"""Run the cross-case matrix with independent Player, Oracle, and Evaluator LLMs.

The fixed plan contains one Player, one Oracle presentation model, and one
post-hoc transcript Evaluator.  Each role has an independent provider, model,
endpoint, credential source, inference policy, and timeout.  The Evaluator runs
only after the Player--Oracle log is sealed and never changes deterministic
scientific scores.

Episodes are randomized within five complete repeat blocks for the selected
case pack. Execution is sequential so dispatch order is identical to the
persisted schedule.

Runtime credentials are passed separately in memory and are never copied into
configs, logs, result sidecars, summaries, or provider metadata.
"""

from __future__ import annotations

import argparse
import csv
import datetime as _datetime
import getpass
import json
import os
import random
import re
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

from role_benchmark import (
    BenchmarkTrack,
    EVALUATOR_SCORE_AXES,
    GenerationConfig,
    LLMEvaluatorCallError,
    PostHocLLMEvaluator,
    TerminationKind,
    TextGenerationBackend,
    analyze_failure_events,
    llm_evaluation_to_payload,
    load_run_log,
    run_llm_episode,
)
from role_benchmark.cases import CASE_FAMILIES, MATCHED_WORLDS, make_case
from role_benchmark.temporal_cases import (
    TEMPORAL_CASE_FAMILIES,
    make_temporal_case,
)
from role_benchmark.llm import (
    generation_request_to_payload,
    generation_response_to_payload,
)
from role_benchmark.wire import final_submission_to_payload

from experiments.run_pendulum_matrix import DeepSeekChatBackend
from experiments.openai_responses import OpenAIResponsesBackend


EXPERIMENT_SCHEMA = "role_benchmark.case_matrix"
EPISODE_RESULT_SCHEMA = "role_benchmark.case_matrix_episode"
LLM_EVALUATOR_RESULT_SCHEMA = "role_benchmark.case_matrix_llm_evaluation"
DEFAULT_PROVIDER = "deepseek"
DEEPSEEK_ENDPOINT = "https://api.deepseek.com/chat/completions"
OPENAI_ENDPOINT = "https://api.openai.com/v1/responses"
DEEPSEEK_API_KEY_ENV = "DEEPSEEK_API_KEY"
OPENAI_API_KEY_ENV = "OPENAI_API_KEY"

DEFAULT_SCHEDULE_SEED = 20260825
DEFAULT_CASE_PACK = "curated"

PLAYER_PROFILE = "player"
PLAYER_MODEL = "deepseek-v4-flash"
ORACLE_PROFILE = "oracle"
ORACLE_MODEL = "deepseek-v4-flash"
EVALUATOR_PROFILE = "evaluator"
EVALUATOR_MODEL = "deepseek-v4-flash"
THINKING = "disabled"
OPENAI_MODEL = "gpt-5.6"
OPENAI_REASONING_EFFORT = "none"
ROLES: Tuple[str, ...] = ("player", "oracle", "evaluator")

MATCHED_FAMILIES: Tuple[str, ...] = CASE_FAMILIES
WORLDS: Tuple[str, ...] = MATCHED_WORLDS
TRACKS: Tuple[str, ...] = (
    BenchmarkTrack.IDENTIFICATION.value,
    BenchmarkTrack.DISCOVERY.value,
)
MATCHED_REPEATS = 5
CELLS_PER_REPEAT = len(CASE_FAMILIES) * len(WORLDS) * len(TRACKS)
TOTAL_EPISODES = CELLS_PER_REPEAT * MATCHED_REPEATS

CaseFactory = Callable[[str, str, BenchmarkTrack], Any]
CASE_PACKS: Mapping[str, Tuple[Tuple[str, ...], CaseFactory]] = {
    "curated": (CASE_FAMILIES, make_case),
    "temporal": (TEMPORAL_CASE_FAMILIES, make_temporal_case),
}


class CaseMatrixDeepSeekBackend(DeepSeekChatBackend):
    """Reuse the shared transport under a matrix-specific binding identity."""

    binding_id = "case_matrix.deepseek_chat"


@dataclass(frozen=True)
class RoleRuntime:
    """Non-secret provider settings for one independently loaded LLM role."""

    role: str
    profile_id: str
    provider: str
    endpoint: str
    api: str
    response_format: str
    binding_id: str
    api_key_env: str
    model: str
    thinking: Optional[str]
    reasoning_effort: Optional[str]
    timeout_s: float


@dataclass(frozen=True)
class MatrixRuntime:
    """Three independent, non-secret role profiles for one matrix run."""

    player: RoleRuntime
    oracle: RoleRuntime
    evaluator: RoleRuntime

    def for_role(self, role: str) -> RoleRuntime:
        if role not in ROLES:
            raise ValueError("unsupported role %r" % role)
        return getattr(self, role)


def _role_value(args: argparse.Namespace, role: str, field: str) -> Any:
    return getattr(args, "%s_%s" % (role, field), None)


def _role_runtime(args: argparse.Namespace, role: str) -> RoleRuntime:
    if role not in ROLES:
        raise ValueError("unsupported role %r" % role)
    provider = str(_role_value(args, role, "provider") or DEFAULT_PROVIDER)
    endpoint_override = _role_value(args, role, "endpoint")
    model_override = _role_value(args, role, "model")
    effort_override = _role_value(args, role, "reasoning_effort")
    thinking_override = _role_value(args, role, "thinking")
    timeout_s = _role_value(args, role, "timeout_s")
    if timeout_s is None:
        timeout_s = 120.0
    if isinstance(timeout_s, bool) or not isinstance(timeout_s, (int, float)):
        raise ValueError("--%s-timeout-s must be a number" % role)
    if float(timeout_s) <= 0:
        raise ValueError("--%s-timeout-s must be positive" % role)
    profile_id = {
        "player": PLAYER_PROFILE,
        "oracle": ORACLE_PROFILE,
        "evaluator": EVALUATOR_PROFILE,
    }[role]
    default_model = {
        "player": PLAYER_MODEL,
        "oracle": ORACLE_MODEL,
        "evaluator": EVALUATOR_MODEL,
    }[role]

    if provider == "deepseek":
        thinking = thinking_override or THINKING
        if thinking not in ("enabled", "disabled"):
            raise ValueError(
                "--%s-thinking must be 'enabled' or 'disabled'" % role
            )
        if effort_override == "none":
            effort_override = None
        if effort_override not in (None, "low", "high", "max"):
            raise ValueError(
                "--%s-reasoning-effort for DeepSeek must be low, high, or max"
                % role
            )
        if thinking == "disabled" and effort_override is not None:
            raise ValueError(
                "--%s-reasoning-effort requires --%s-thinking enabled"
                % (role, role)
            )
        return RoleRuntime(
            role=role,
            profile_id=profile_id,
            provider="deepseek",
            endpoint=endpoint_override or DEEPSEEK_ENDPOINT,
            api="chat_completions",
            response_format="json_object",
            binding_id=CaseMatrixDeepSeekBackend.binding_id,
            api_key_env=(
                _role_value(args, role, "api_key_env") or DEEPSEEK_API_KEY_ENV
            ),
            model=model_override or default_model,
            thinking=thinking,
            reasoning_effort=effort_override,
            timeout_s=float(timeout_s),
        )
    if provider == "openai":
        if thinking_override is not None:
            raise ValueError("--%s-thinking is only defined for DeepSeek" % role)
        effort = effort_override or OPENAI_REASONING_EFFORT
        return RoleRuntime(
            role=role,
            profile_id=profile_id,
            provider="openai",
            endpoint=endpoint_override or OPENAI_ENDPOINT,
            api="responses",
            response_format="json_object_with_app_schema",
            binding_id=OpenAIResponsesBackend.binding_id,
            api_key_env=(
                _role_value(args, role, "api_key_env") or OPENAI_API_KEY_ENV
            ),
            model=model_override or OPENAI_MODEL,
            thinking=None,
            reasoning_effort=effort,
            timeout_s=float(timeout_s),
        )
    raise ValueError("unsupported provider %r" % provider)


def _runtime_profile(args: argparse.Namespace) -> MatrixRuntime:
    return MatrixRuntime(
        player=_role_runtime(args, "player"),
        oracle=_role_runtime(args, "oracle"),
        evaluator=_role_runtime(args, "evaluator"),
    )


def _default_runtime() -> MatrixRuntime:
    defaults = argparse.Namespace()
    return _runtime_profile(defaults)


def _utc_now() -> str:
    return (
        _datetime.datetime.now(_datetime.timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z")
    )


def _slug(value: str) -> str:
    result = re.sub(r"[^A-Za-z0-9._-]+", "-", value.strip()).strip("-._")
    if not result:
        raise ValueError("identifier must contain a filename-safe character")
    return result.lower()


@dataclass(frozen=True)
class EpisodeSpec:
    schedule_index: int
    episode_id: str
    case_family: str
    world: str
    track: str
    repeat: int

    @property
    def cell(self) -> Tuple[str, str, str]:
        return (self.case_family, self.world, self.track)


def _matched_cells(
    families: Sequence[str] = MATCHED_FAMILIES,
) -> List[Tuple[str, str, str]]:
    return [
        (family, world, track)
        for family in families
        for world in WORLDS
        for track in TRACKS
    ]


def build_plan(
    schedule_seed: int = DEFAULT_SCHEDULE_SEED,
    *,
    families: Sequence[str] = MATCHED_FAMILIES,
    repeats: int = MATCHED_REPEATS,
) -> List[EpisodeSpec]:
    """Build deterministic randomized blocks over a complete matched case pack."""

    if isinstance(schedule_seed, bool) or not isinstance(schedule_seed, int):
        raise ValueError("schedule_seed must be an integer")
    family_tuple = tuple(families)
    if not family_tuple or len(set(family_tuple)) != len(family_tuple):
        raise ValueError("families must be a non-empty sequence of unique names")
    if isinstance(repeats, bool) or not isinstance(repeats, int) or repeats < 1:
        raise ValueError("repeats must be a positive integer")
    generator = random.Random(schedule_seed)
    matched = _matched_cells(family_tuple)
    plan: List[EpisodeSpec] = []

    for repeat in range(1, repeats + 1):
        block = list(matched)
        generator.shuffle(block)
        if plan and block[0] == plan[-1].cell:
            replacement = next(
                index
                for index, cell in enumerate(block[1:], start=1)
                if cell != block[0]
            )
            block[0], block[replacement] = block[replacement], block[0]

        for family, world, track in block:
            episode_id = "%s__%s__%s__r%02d" % (
                _slug(family),
                world,
                track,
                repeat,
            )
            plan.append(
                EpisodeSpec(
                    schedule_index=len(plan) + 1,
                    episode_id=episode_id,
                    case_family=family,
                    world=world,
                    track=track,
                    repeat=repeat,
                )
            )

    expected_total = len(matched) * repeats
    if len(plan) != expected_total:
        raise AssertionError(
            "the case matrix must contain %d episodes" % expected_total
        )
    if len({spec.episode_id for spec in plan}) != expected_total:
        raise AssertionError("case-matrix episode IDs must be unique")
    return plan


def select_plan(
    plan: Sequence[EpisodeSpec],
    *,
    families: Optional[Sequence[str]] = None,
    worlds: Optional[Sequence[str]] = None,
    tracks: Optional[Sequence[str]] = None,
    repeats: Optional[Sequence[int]] = None,
) -> List[EpisodeSpec]:
    """Filter cells without changing their frozen global order."""

    family_set = (
        set(families)
        if families is not None
        else {spec.case_family for spec in plan}
    )
    world_set = set(worlds) if worlds is not None else {spec.world for spec in plan}
    track_set = set(tracks) if tracks is not None else {spec.track for spec in plan}
    repeat_set = (
        set(repeats) if repeats is not None else {spec.repeat for spec in plan}
    )
    return [
        spec
        for spec in plan
        if spec.case_family in family_set
        and spec.world in world_set
        and spec.track in track_set
        and spec.repeat in repeat_set
    ]


BackendLoader = Callable[[], TextGenerationBackend]


def _build_backend(runtime: RoleRuntime, api_key: str) -> TextGenerationBackend:
    if runtime.provider == "deepseek":
        return CaseMatrixDeepSeekBackend(
            endpoint=runtime.endpoint,
            api_key=api_key,
            model=runtime.model,
            thinking=runtime.thinking or THINKING,
            reasoning_effort=runtime.reasoning_effort,
            timeout_s=runtime.timeout_s,
        )
    if runtime.provider == "openai":
        return OpenAIResponsesBackend(
            endpoint=runtime.endpoint,
            api_key=api_key,
            model=runtime.model,
            reasoning_effort=runtime.reasoning_effort or OPENAI_REASONING_EFFORT,
            timeout_s=runtime.timeout_s,
        )
    raise ValueError("unsupported provider %r" % runtime.provider)


def load_role_backend(
    args: argparse.Namespace,
    role: str,
    *,
    api_key: Optional[str] = None,
    loader: Optional[BackendLoader] = None,
) -> TextGenerationBackend:
    """Load exactly one role without touching either of the other clients."""

    runtime = _runtime_profile(args).for_role(role)
    if loader is not None:
        backend = loader()
    else:
        if not isinstance(api_key, str) or not api_key.strip():
            raise ValueError("%s api_key must be non-empty" % role)
        backend = _build_backend(runtime, api_key)
    if not callable(getattr(backend, "generate", None)):
        raise ValueError(
            "%s backend must provide a callable generate method"
            % role.capitalize()
        )
    return backend


def load_backends(
    args: argparse.Namespace,
    *,
    player_api_key: Optional[str],
    oracle_api_key: Optional[str],
    evaluator_api_key: Optional[str],
    player_loader: Optional[BackendLoader] = None,
    oracle_loader: Optional[BackendLoader] = None,
    evaluator_loader: Optional[BackendLoader] = None,
) -> Tuple[TextGenerationBackend, TextGenerationBackend, TextGenerationBackend]:
    """Load three independently configured provider backend objects."""

    player = load_role_backend(
        args,
        "player",
        api_key=player_api_key,
        loader=player_loader,
    )
    oracle = load_role_backend(
        args,
        "oracle",
        api_key=oracle_api_key,
        loader=oracle_loader,
    )
    evaluator = load_role_backend(
        args,
        "evaluator",
        api_key=evaluator_api_key,
        loader=evaluator_loader,
    )
    backends = {
        "Player": player,
        "Oracle": oracle,
        "Evaluator": evaluator,
    }
    if len({id(backend) for backend in backends.values()}) != len(backends):
        raise ValueError(
            "Player, Oracle, and Evaluator must use distinct backend instances"
        )
    return player, oracle, evaluator


def _profile_payload(runtime: RoleRuntime) -> Mapping[str, Any]:
    return {
        "profile_id": runtime.profile_id,
        "provider": runtime.provider,
        "model": runtime.model,
        "thinking": runtime.thinking,
        "reasoning_effort": runtime.reasoning_effort,
    }


def _provider_payload(runtime: RoleRuntime) -> Mapping[str, Any]:
    payload: Dict[str, Any] = {
        "name": runtime.provider,
        "binding_id": runtime.binding_id,
        "endpoint": runtime.endpoint,
        "api": runtime.api,
        "response_format": runtime.response_format,
        "timeout_s": runtime.timeout_s,
    }
    if runtime.provider == "openai":
        payload.update({"store": False, "reasoning_context": "current_turn"})
    return payload


def _case_pack(args: argparse.Namespace) -> Tuple[str, Tuple[str, ...], CaseFactory]:
    name = str(getattr(args, "case_pack", DEFAULT_CASE_PACK))
    try:
        families, factory = CASE_PACKS[name]
    except KeyError as exc:
        raise ValueError(
            "unknown case pack %r; choose one of %s"
            % (name, ", ".join(CASE_PACKS))
        ) from exc
    return name, families, factory


def _config_payload(
    args: argparse.Namespace,
    plan: Sequence[EpisodeSpec],
) -> Mapping[str, Any]:
    case_pack, case_families, _ = _case_pack(args)
    expected = build_plan(args.schedule_seed, families=case_families)
    if list(plan) != expected:
        raise ValueError("plan does not match the declared schedule_seed")
    runtime = _runtime_profile(args)
    cells_per_repeat = len(case_families) * len(WORLDS) * len(TRACKS)
    total_episodes = cells_per_repeat * MATCHED_REPEATS
    return {
        "schema": EXPERIMENT_SCHEMA,
        "created_at": _utc_now(),
        "design": {
            "player_profile": _profile_payload(runtime.player),
            "oracle_profile": _profile_payload(runtime.oracle),
            "evaluator_profile": _profile_payload(runtime.evaluator),
            "case_pack": case_pack,
            "case_families": list(case_families),
            "worlds": list(WORLDS),
            "tracks": list(TRACKS),
            "repeats": MATCHED_REPEATS,
            "cells_per_repeat": cells_per_repeat,
            "total_episodes": total_episodes,
            "repeat_policy": "provider-stochastic repeats; no client seed",
        },
        "schedule": {
            "policy": "seeded_randomized_repeat_blocks",
            "seed": args.schedule_seed,
            "block_sizes": [cells_per_repeat] * MATCHED_REPEATS,
            "execution_order": [spec.episode_id for spec in plan],
        },
        "providers": {
            role: _provider_payload(runtime.for_role(role)) for role in ROLES
        },
        "player_generation": {
            "temperature": 0.0,
            "top_p": 1.0,
            "seed": None,
            "max_output_tokens": args.player_max_output_tokens,
            "max_repair_attempts": args.max_repair_attempts,
            "max_actions": args.max_actions,
        },
        "oracle_generation": {
            "mode": "llm_presentation_over_authoritative_world_model",
            "temperature": 0.0,
            "top_p": 1.0,
            "seed": None,
            "max_output_tokens": args.oracle_max_output_tokens,
        },
        "evaluator_generation": {
            "mode": "post_hoc_observable_transcript",
            "temperature": 0.0,
            "top_p": 1.0,
            "seed": None,
            "max_output_tokens": args.evaluator_max_output_tokens,
            "score_axes": list(EVALUATOR_SCORE_AXES),
            "scientific_score_policy": "separate_from_deterministic_evaluation",
        },
        "execution": {
            "workers": args.workers,
            "order_guarantee": "sequential_schedule_index",
            "player_termination_policy": "evaluate_and_consume_active_episode",
            "active_infrastructure_failure_policy": "halt_and_retry_same_index",
            "evaluator_failure_policy": "halt_and_retry_evaluator_only",
        },
    }


def _write_json(path: Path, payload: Any, *, exclusive: bool = False) -> None:
    with path.open(
        "x" if exclusive else "w",
        encoding="utf-8",
        newline="\n",
    ) as stream:
        json.dump(payload, stream, ensure_ascii=False, indent=2, sort_keys=True)
        stream.write("\n")


def prepare_output(output_dir: Path, config: Mapping[str, Any]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "episodes").mkdir(exist_ok=True)
    (output_dir / "results").mkdir(exist_ok=True)
    (output_dir / "evaluations").mkdir(exist_ok=True)
    config_path = output_dir / "config.json"
    if not config_path.exists():
        _write_json(config_path, config, exclusive=True)
        return

    existing = json.loads(config_path.read_text(encoding="utf-8"))
    comparable_existing = dict(existing)
    comparable_new = dict(config)
    comparable_existing.pop("created_at", None)
    comparable_new.pop("created_at", None)
    if comparable_existing != comparable_new:
        raise ValueError("output directory contains a different experiment config")


def _result_path(output_dir: Path, spec: EpisodeSpec) -> Path:
    return output_dir / "results" / (spec.episode_id + ".result.json")


def _evaluator_result_path(output_dir: Path, spec: EpisodeSpec) -> Path:
    return output_dir / "evaluations" / (spec.episode_id + ".evaluation.json")


def _next_log_path(output_dir: Path, spec: EpisodeSpec) -> Path:
    base = output_dir / "episodes" / (spec.episode_id + ".jsonl")
    if not base.exists():
        return base
    resume = 1
    while True:
        candidate = output_dir / "episodes" / (
            "%s.resume-%d.jsonl" % (spec.episode_id, resume)
        )
        if not candidate.exists():
            return candidate
        resume += 1


def _stats_payload(stats: Any) -> Optional[Mapping[str, Any]]:
    return asdict(stats) if stats is not None else None


def _relative_path(path: Path, output_dir: Path) -> str:
    return str(path.relative_to(output_dir))


def _base_result(
    spec: EpisodeSpec,
    log_path: Path,
    output_dir: Path,
    *,
    runtime: Optional[MatrixRuntime] = None,
) -> Dict[str, Any]:
    if runtime is None:
        runtime = _default_runtime()
    return {
        "schema": EPISODE_RESULT_SCHEMA,
        "schedule_index": spec.schedule_index,
        "episode_id": spec.episode_id,
        "case_family": spec.case_family,
        "world": spec.world,
        "track": spec.track,
        "repeat": spec.repeat,
        "player_profile": runtime.player.profile_id,
        "player_provider": runtime.player.provider,
        "player_model": runtime.player.model,
        "player_thinking": runtime.player.thinking,
        "player_reasoning_effort": runtime.player.reasoning_effort,
        "oracle_profile": runtime.oracle.profile_id,
        "oracle_provider": runtime.oracle.provider,
        "oracle_model": runtime.oracle.model,
        "oracle_thinking": runtime.oracle.thinking,
        "oracle_reasoning_effort": runtime.oracle.reasoning_effort,
        "evaluator_profile": runtime.evaluator.profile_id,
        "evaluator_provider": runtime.evaluator.provider,
        "evaluator_model": runtime.evaluator.model,
        "evaluator_thinking": runtime.evaluator.thinking,
        "evaluator_reasoning_effort": runtime.evaluator.reasoning_effort,
        "log_path": _relative_path(log_path, output_dir),
    }


def _evaluated_result(
    *,
    spec: EpisodeSpec,
    log_path: Path,
    output_dir: Path,
    run: Any,
    started_at: str,
    elapsed_s: float,
    failure_analysis: Optional[Mapping[str, Any]] = None,
    runtime: Optional[MatrixRuntime] = None,
) -> Mapping[str, Any]:
    outcome = run.outcome
    termination_kind = outcome.termination.kind
    if termination_kind == TerminationKind.SUBMITTED:
        if not outcome.protocol_completed:
            category = "player_protocol_failure"
        else:
            category = "pass" if outcome.active_pass else "scientific_failure"
    elif termination_kind == TerminationKind.PLAYER_OUTPUT_INVALID:
        category = "player_generation_failure"
    elif termination_kind in (
        TerminationKind.ACTION_REJECTED,
        TerminationKind.ACTION_LIMIT,
    ):
        category = "player_protocol_failure"
    else:
        raise ValueError("unsupported episode termination kind")

    result = _base_result(spec, log_path, output_dir, runtime=runtime)
    result.update(
        {
            "case_id": outcome.case_id,
            "status": "evaluated",
            "run_id": run.run_id,
            "started_at": started_at,
            "ended_at": _utc_now(),
            "elapsed_s": round(elapsed_s, 3),
            "active_pass": bool(outcome.active_pass),
            "active_pass_category": category,
            "termination_kind": termination_kind.value,
            "reason_code": outcome.termination.code,
            "termination_message": outcome.termination.message,
            "scientifically_evaluable": bool(outcome.scientifically_evaluable),
            "protocol_completion": bool(outcome.protocol_completed),
            "evaluation_success": outcome.evaluation.success,
            "evaluation_message": outcome.evaluation.message,
            "attempts_used": outcome.attempts_used,
            "final_submission": (
                final_submission_to_payload(outcome.final_submission)
                if outcome.final_submission is not None
                else None
            ),
            "scores": dict(outcome.evaluation.scores),
            "trajectory_scores": dict(outcome.trajectory_scores),
            "protocol_violations": [
                {"code": item.code, "message": item.message}
                for item in outcome.protocol_violations
            ],
            "failure_analysis": failure_analysis,
            "player_llm_stats": _stats_payload(run.llm_stats),
            "oracle_llm_stats": _stats_payload(run.oracle_llm_stats),
            "error_type": None,
            "error_message": None,
        }
    )
    return result


def _infrastructure_failed_result(
    *,
    spec: EpisodeSpec,
    log_path: Path,
    output_dir: Path,
    exc: Exception,
    started_at: str,
    elapsed_s: float,
    runtime: Optional[MatrixRuntime] = None,
) -> Mapping[str, Any]:
    result = _base_result(spec, log_path, output_dir, runtime=runtime)
    result.update(
        {
            "case_id": None,
            "status": "infrastructure_failed",
            "run_id": None,
            "started_at": started_at,
            "ended_at": _utc_now(),
            "elapsed_s": round(elapsed_s, 3),
            "active_pass": None,
            "active_pass_category": None,
            "termination_kind": None,
            "reason_code": None,
            "termination_message": None,
            "scientifically_evaluable": None,
            "protocol_completion": None,
            "evaluation_success": None,
            "evaluation_message": None,
            "attempts_used": None,
            "final_submission": None,
            "scores": {},
            "trajectory_scores": {},
            "protocol_violations": [],
            "failure_analysis": None,
            "player_llm_stats": None,
            "oracle_llm_stats": None,
            "error_type": type(exc).__name__,
            "error_message": str(exc),
        }
    )
    return result


def _run_evaluator(
    args: argparse.Namespace,
    *,
    evaluator_backend: TextGenerationBackend,
    output_dir: Path,
    spec: EpisodeSpec,
    episode_result: Mapping[str, Any],
) -> Mapping[str, Any]:
    """Evaluate one sealed transcript without changing its active outcome."""

    started_at = _utc_now()
    started_clock = time.monotonic()
    runtime = _runtime_profile(args).evaluator
    base: Dict[str, Any] = {
        "schema": LLM_EVALUATOR_RESULT_SCHEMA,
        "episode_id": spec.episode_id,
        "run_id": episode_result.get("run_id"),
        "evaluator_profile": runtime.profile_id,
        "evaluator_provider": runtime.provider,
        "evaluator_model": runtime.model,
        "started_at": started_at,
    }
    log_path_value = episode_result.get("log_path")
    if not isinstance(log_path_value, str) or not log_path_value:
        raise ValueError("evaluated episode is missing its canonical log path")
    log_path = Path(log_path_value)
    if not log_path.is_absolute():
        log_path = output_dir / log_path
    try:
        evaluator = PostHocLLMEvaluator(
            evaluator_backend,
            config=GenerationConfig(
                max_output_tokens=args.evaluator_max_output_tokens,
                temperature=0.0,
                top_p=1.0,
                seed=None,
            ),
        )
        evaluated = evaluator.evaluate(load_run_log(str(log_path)))
        base.update(
            {
                "status": "evaluated",
                "ended_at": _utc_now(),
                "elapsed_s": round(time.monotonic() - started_clock, 3),
                "request": generation_request_to_payload(evaluated.request),
                "response": generation_response_to_payload(evaluated.response),
                "evaluation": llm_evaluation_to_payload(evaluated.evaluation),
                "llm_stats": {
                    "generation_calls": 1,
                    "input_tokens": evaluated.response.usage.input_tokens,
                    "output_tokens": evaluated.response.usage.output_tokens,
                },
                "error_type": None,
                "error_message": None,
            }
        )
    except LLMEvaluatorCallError as exc:
        response = exc.response
        base.update(
            {
                "status": "infrastructure_failed",
                "ended_at": _utc_now(),
                "elapsed_s": round(time.monotonic() - started_clock, 3),
                "request": generation_request_to_payload(exc.request),
                "response": (
                    generation_response_to_payload(response)
                    if response is not None
                    else None
                ),
                "evaluation": None,
                "llm_stats": (
                    {
                        "generation_calls": 1,
                        "input_tokens": response.usage.input_tokens,
                        "output_tokens": response.usage.output_tokens,
                    }
                    if response is not None
                    else None
                ),
                "error_type": type(exc).__name__,
                "error_message": "post-hoc evaluator call or decoding failed",
            }
        )
    except Exception as exc:
        base.update(
            {
                "status": "infrastructure_failed",
                "ended_at": _utc_now(),
                "elapsed_s": round(time.monotonic() - started_clock, 3),
                "request": None,
                "response": None,
                "evaluation": None,
                "llm_stats": None,
                "error_type": type(exc).__name__,
                "error_message": "post-hoc evaluator call or decoding failed",
            }
        )
    return base


def _load_evaluator_result(
    output_dir: Path, episode_id: str
) -> Optional[Mapping[str, Any]]:
    path = output_dir / "evaluations" / (episode_id + ".evaluation.json")
    if not path.exists():
        return None
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, Mapping):
        raise ValueError("evaluator result must contain a JSON object")
    return value


def _with_evaluator_summary(
    output_dir: Path, result: Mapping[str, Any]
) -> Mapping[str, Any]:
    merged = dict(result)
    if result.get("status") != "evaluated":
        merged.update(
            {
                "llm_evaluation_status": "not_applicable",
                "llm_evaluation": None,
                "evaluator_llm_stats": None,
                "evaluator_result_path": None,
            }
        )
        return merged
    evaluator_result = _load_evaluator_result(output_dir, str(result["episode_id"]))
    if evaluator_result is None:
        merged.update(
            {
                "llm_evaluation_status": "pending",
                "llm_evaluation": None,
                "evaluator_llm_stats": None,
                "evaluator_result_path": None,
            }
        )
        return merged
    merged.update(
        {
            "llm_evaluation_status": evaluator_result.get("status"),
            "llm_evaluation": evaluator_result.get("evaluation"),
            "evaluator_llm_stats": evaluator_result.get("llm_stats"),
            "evaluator_result_path": _relative_path(
                output_dir
                / "evaluations"
                / (str(result["episode_id"]) + ".evaluation.json"),
                output_dir,
            ),
        }
    )
    return merged


SUMMARY_COLUMNS = (
    "schedule_index",
    "episode_id",
    "case_family",
    "case_id",
    "world",
    "track",
    "repeat",
    "player_profile",
    "player_provider",
    "player_model",
    "player_reasoning_effort",
    "oracle_profile",
    "oracle_provider",
    "oracle_model",
    "oracle_reasoning_effort",
    "evaluator_profile",
    "evaluator_provider",
    "evaluator_model",
    "evaluator_reasoning_effort",
    "status",
    "active_pass",
    "active_pass_category",
    "termination_kind",
    "reason_code",
    "scientifically_evaluable",
    "protocol_completion",
    "evaluation_success",
    "attempts_used",
    "final_model",
    "final_parameters_json",
    "player_turns",
    "player_input_tokens",
    "player_output_tokens",
    "oracle_turns",
    "oracle_input_tokens",
    "oracle_output_tokens",
    "evaluator_input_tokens",
    "evaluator_output_tokens",
    "llm_evaluation_status",
    "llm_evaluation_scores_json",
    "llm_evaluation_finding_count",
    "llm_evaluation_summary",
    "elapsed_s",
    "experiment_discriminativeness_mean",
    "evidence_aligned_belief_update_rate",
    "trajectory_scores_json",
    "scores_json",
    "log_path",
    "evaluator_result_path",
    "run_id",
    "error_type",
    "error_message",
)


def _csv_row(result: Mapping[str, Any]) -> Mapping[str, Any]:
    player = result.get("player_llm_stats") or {}
    oracle = result.get("oracle_llm_stats") or {}
    evaluator = result.get("evaluator_llm_stats") or {}
    llm_evaluation = result.get("llm_evaluation") or {}
    trajectory = result.get("trajectory_scores") or {}
    final = result.get("final_submission") or {}
    return {
        "schedule_index": result.get("schedule_index"),
        "episode_id": result["episode_id"],
        "case_family": result["case_family"],
        "case_id": result.get("case_id"),
        "world": result["world"],
        "track": result["track"],
        "repeat": result["repeat"],
        "player_profile": result.get("player_profile"),
        "player_provider": result.get("player_provider"),
        "player_model": result.get("player_model"),
        "player_reasoning_effort": result.get("player_reasoning_effort"),
        "oracle_profile": result.get("oracle_profile"),
        "oracle_provider": result.get("oracle_provider"),
        "oracle_model": result.get("oracle_model"),
        "oracle_reasoning_effort": result.get("oracle_reasoning_effort"),
        "evaluator_profile": result.get("evaluator_profile"),
        "evaluator_provider": result.get("evaluator_provider"),
        "evaluator_model": result.get("evaluator_model"),
        "evaluator_reasoning_effort": result.get("evaluator_reasoning_effort"),
        "status": result["status"],
        "active_pass": result.get("active_pass"),
        "active_pass_category": result.get("active_pass_category"),
        "termination_kind": result.get("termination_kind"),
        "reason_code": result.get("reason_code"),
        "scientifically_evaluable": result.get("scientifically_evaluable"),
        "protocol_completion": result.get("protocol_completion"),
        "evaluation_success": result.get("evaluation_success"),
        "attempts_used": result.get("attempts_used"),
        "final_model": final.get("model"),
        "final_parameters_json": json.dumps(
            final.get("parameters") or {}, ensure_ascii=False, sort_keys=True
        ),
        "player_turns": player.get("player_turns"),
        "player_input_tokens": player.get("input_tokens"),
        "player_output_tokens": player.get("output_tokens"),
        "oracle_turns": oracle.get("oracle_turns"),
        "oracle_input_tokens": oracle.get("input_tokens"),
        "oracle_output_tokens": oracle.get("output_tokens"),
        "evaluator_input_tokens": evaluator.get("input_tokens"),
        "evaluator_output_tokens": evaluator.get("output_tokens"),
        "llm_evaluation_status": result.get("llm_evaluation_status"),
        "llm_evaluation_scores_json": json.dumps(
            llm_evaluation.get("scores") or {}, ensure_ascii=False, sort_keys=True
        ),
        "llm_evaluation_finding_count": len(llm_evaluation.get("findings") or []),
        "llm_evaluation_summary": llm_evaluation.get("summary"),
        "elapsed_s": result.get("elapsed_s"),
        "experiment_discriminativeness_mean": trajectory.get(
            "experiment_discriminativeness_mean"
        ),
        "evidence_aligned_belief_update_rate": trajectory.get(
            "evidence_aligned_belief_update_rate"
        ),
        "trajectory_scores_json": json.dumps(
            trajectory, ensure_ascii=False, sort_keys=True
        ),
        "scores_json": json.dumps(
            result.get("scores") or {}, ensure_ascii=False, sort_keys=True
        ),
        "log_path": result["log_path"],
        "evaluator_result_path": result.get("evaluator_result_path"),
        "run_id": result.get("run_id"),
        "error_type": result.get("error_type"),
        "error_message": result.get("error_message"),
    }


def load_episode_results(output_dir: Path) -> List[Mapping[str, Any]]:
    results = [
        json.loads(path.read_text(encoding="utf-8"))
        for path in sorted((output_dir / "results").glob("*.result.json"))
    ]
    return sorted(
        results,
        key=lambda result: (
            result.get("schedule_index", TOTAL_EPISODES + 1),
            result["episode_id"],
        ),
    )


def write_summaries(output_dir: Path) -> List[Mapping[str, Any]]:
    results = [
        _with_evaluator_summary(output_dir, result)
        for result in load_episode_results(output_dir)
    ]
    _write_json(
        output_dir / "episodes.json",
        {
            "schema": EXPERIMENT_SCHEMA,
            "episode_count": len(results),
            "episodes": results,
        },
    )
    with (output_dir / "episodes.csv").open(
        "w", encoding="utf-8", newline=""
    ) as stream:
        writer = csv.DictWriter(stream, fieldnames=SUMMARY_COLUMNS)
        writer.writeheader()
        for result in results:
            writer.writerow(_csv_row(result))
    return results


def _make_case(
    spec: EpisodeSpec,
    case_factory: CaseFactory = make_case,
) -> Any:
    return case_factory(spec.case_family, spec.world, BenchmarkTrack(spec.track))


def _run_one_episode(
    args: argparse.Namespace,
    *,
    player_backend: TextGenerationBackend,
    oracle_backend: TextGenerationBackend,
    output_dir: Path,
    spec: EpisodeSpec,
    log_path: Path,
    case_factory: CaseFactory = make_case,
) -> Mapping[str, Any]:
    started_at = _utc_now()
    started_clock = time.monotonic()
    runtime = _runtime_profile(args)
    try:
        case = _make_case(spec, case_factory)
        run = run_llm_episode(
            player_backend,
            case,
            str(log_path),
            config=GenerationConfig(
                max_output_tokens=args.player_max_output_tokens,
                temperature=0.0,
                top_p=1.0,
                seed=None,
            ),
            oracle_backend=oracle_backend,
            oracle_config=GenerationConfig(
                max_output_tokens=args.oracle_max_output_tokens,
                temperature=0.0,
                top_p=1.0,
                seed=None,
            ),
            max_repair_attempts=args.max_repair_attempts,
            max_actions=args.max_actions,
            run_id=spec.episode_id,
            run_metadata={
                "experiment_schema": EXPERIMENT_SCHEMA,
                "episode_id": spec.episode_id,
                "case_family": spec.case_family,
                "world": spec.world,
                "track": spec.track,
                "repeat": spec.repeat,
                "schedule_index": spec.schedule_index,
                "schedule_seed": args.schedule_seed,
                "schedule_policy": "seeded_randomized_repeat_blocks",
                "player_profile": runtime.player.profile_id,
                "player_provider": runtime.player.provider,
                "player_model": runtime.player.model,
                "player_binding_id": runtime.player.binding_id,
                "player_reasoning_effort": runtime.player.reasoning_effort,
                "oracle_profile": runtime.oracle.profile_id,
                "oracle_provider": runtime.oracle.provider,
                "oracle_model": runtime.oracle.model,
                "oracle_binding_id": runtime.oracle.binding_id,
                "oracle_reasoning_effort": runtime.oracle.reasoning_effort,
                "evaluator_profile": runtime.evaluator.profile_id,
                "evaluator_provider": runtime.evaluator.provider,
                "evaluator_model": runtime.evaluator.model,
            },
        )
        run_log_path = getattr(run, "log_path", None)
        failure_analysis = (
            analyze_failure_events(load_run_log(run_log_path).events)
            if isinstance(run_log_path, str)
            else None
        )
        return _evaluated_result(
            spec=spec,
            log_path=log_path,
            output_dir=output_dir,
            run=run,
            started_at=started_at,
            elapsed_s=time.monotonic() - started_clock,
            failure_analysis=failure_analysis,
            runtime=runtime,
        )
    except Exception as exc:
        return _infrastructure_failed_result(
            spec=spec,
            log_path=log_path,
            output_dir=output_dir,
            exc=exc,
            started_at=started_at,
            elapsed_s=time.monotonic() - started_clock,
            runtime=runtime,
        )


def _result_consumes_schedule(result: Mapping[str, Any]) -> bool:
    return result.get("status") == "evaluated"


def _key_for_backend(
    args: argparse.Namespace,
    role: str,
    supplied: Optional[str],
    loader: Optional[BackendLoader],
) -> Optional[str]:
    if loader is not None or supplied is not None:
        return supplied
    return _resolve_api_key(args, role)


def run_matrix(
    args: argparse.Namespace,
    *,
    player_api_key: Optional[str] = None,
    oracle_api_key: Optional[str] = None,
    evaluator_api_key: Optional[str] = None,
    player_backend_loader: Optional[BackendLoader] = None,
    oracle_backend_loader: Optional[BackendLoader] = None,
    evaluator_backend_loader: Optional[BackendLoader] = None,
) -> List[Mapping[str, Any]]:
    if args.workers != 1:
        raise ValueError("the randomized schedule requires workers=1")
    output_dir = Path(args.output_dir).resolve()
    case_pack, case_families, case_factory = _case_pack(args)
    requested_families = set(args.family or case_families)
    unknown_families = requested_families - set(case_families)
    if unknown_families:
        raise ValueError(
            "case family %s is not registered in the %s case pack"
            % (", ".join(sorted(unknown_families)), case_pack)
        )
    full_plan = build_plan(args.schedule_seed, families=case_families)
    total_episodes = len(full_plan)
    selected = select_plan(
        full_plan,
        families=args.family,
        worlds=args.world,
        tracks=args.track,
        repeats=args.repeat,
    )
    prepare_output(output_dir, _config_payload(args, full_plan))
    write_summaries(output_dir)

    if args.dry_run:
        print(
            "Selected %d of %d episodes in %s"
            % (len(selected), total_episodes, output_dir)
        )
        return []

    loaded = load_episode_results(output_dir)
    existing = {result["episode_id"]: result for result in loaded}
    if len(existing) != len(loaded):
        raise ValueError("result sidecars contain duplicate episode IDs")
    expected_ids = [spec.episode_id for spec in full_plan]
    unknown_ids = set(existing) - set(expected_ids)
    if unknown_ids:
        raise ValueError("result sidecars contain episode IDs outside the plan")
    recorded_ids = [episode_id for episode_id in expected_ids if episode_id in existing]
    if recorded_ids != expected_ids[: len(recorded_ids)]:
        raise ValueError("result sidecars must form a prefix of the schedule")
    for spec in full_plan[: len(recorded_ids)]:
        if existing[spec.episode_id].get("schedule_index") != spec.schedule_index:
            raise ValueError("result sidecar schedule_index differs from the plan")

    consumed = 0
    for spec in full_plan:
        result = existing.get(spec.episode_id)
        if result is None or not _result_consumes_schedule(result):
            break
        consumed += 1
    remaining = full_plan[consumed:]
    selected_ids = {spec.episode_id for spec in selected}
    selected_pending = [
        spec for spec in remaining if spec.episode_id in selected_ids
    ]
    if selected_pending != remaining[: len(selected_pending)]:
        raise ValueError("selectors must choose a prefix of the remaining schedule")

    # Validate every selected case before constructing a paid provider backend.
    for cell in dict.fromkeys(spec.cell for spec in selected_pending):
        _make_case(
            next(spec for spec in selected_pending if spec.cell == cell),
            case_factory,
        )

    pending_ids = {spec.episode_id for spec in selected_pending}
    pending = [
        (spec, _next_log_path(output_dir, spec))
        for spec in selected
        if spec.episode_id in pending_ids
    ]
    evaluator_pending = []
    for spec in full_plan[:consumed]:
        episode_result = existing[spec.episode_id]
        evaluator_result = _load_evaluator_result(output_dir, spec.episode_id)
        if evaluator_result is None or evaluator_result.get("status") != "evaluated":
            evaluator_pending.append((spec, episode_result))
    print(
        "Running %d unfinished episode(s) and %d evaluator-only retry(s) sequentially"
        % (len(pending), len(evaluator_pending)),
        flush=True,
    )

    if pending:
        player_backend, oracle_backend, evaluator_backend = load_backends(
            args,
            player_api_key=_key_for_backend(
                args, "player", player_api_key, player_backend_loader
            ),
            oracle_api_key=_key_for_backend(
                args, "oracle", oracle_api_key, oracle_backend_loader
            ),
            evaluator_api_key=_key_for_backend(
                args, "evaluator", evaluator_api_key, evaluator_backend_loader
            ),
            player_loader=player_backend_loader,
            oracle_loader=oracle_backend_loader,
            evaluator_loader=evaluator_backend_loader,
        )
    elif evaluator_pending:
        evaluator_backend = load_role_backend(
            args,
            "evaluator",
            api_key=_key_for_backend(
                args, "evaluator", evaluator_api_key, evaluator_backend_loader
            ),
            loader=evaluator_backend_loader,
        )
        player_backend = None
        oracle_backend = None
    else:
        player_backend = None
        oracle_backend = None
        evaluator_backend = None

    if evaluator_backend is not None:
        for spec, episode_result in evaluator_pending:
            evaluator_result = _run_evaluator(
                args,
                evaluator_backend=evaluator_backend,
                output_dir=output_dir,
                spec=spec,
                episode_result=episode_result,
            )
            _write_json(_evaluator_result_path(output_dir, spec), evaluator_result)
            write_summaries(output_dir)
            if evaluator_result["status"] != "evaluated":
                raise RuntimeError(
                    "episode %s hit an evaluator failure: %s"
                    % (spec.episode_id, evaluator_result["error_message"])
                )

    if pending:
        if player_backend is None or oracle_backend is None or evaluator_backend is None:
            raise AssertionError("active execution requires all three role backends")
        for spec, log_path in pending:
            result = _run_one_episode(
                args,
                player_backend=player_backend,
                oracle_backend=oracle_backend,
                output_dir=output_dir,
                spec=spec,
                log_path=log_path,
                case_factory=case_factory,
            )
            result_path = _result_path(output_dir, spec)
            _write_json(result_path, result, exclusive=not result_path.exists())
            write_summaries(output_dir)
            label = (
                "INFRA"
                if result["status"] == "infrastructure_failed"
                else {
                    "pass": "PASS",
                    "scientific_failure": "SCI",
                    "player_generation_failure": "GEN",
                    "player_protocol_failure": "PROTO",
                }[result["active_pass_category"]]
            )
            print(
                "[%02d/%02d] %-5s %s"
                % (spec.schedule_index, total_episodes, label, spec.episode_id),
                flush=True,
            )
            if result["status"] == "infrastructure_failed":
                raise RuntimeError(
                    "episode %s hit an infrastructure failure: %s"
                    % (spec.episode_id, result["error_message"])
                )
            evaluator_result = _run_evaluator(
                args,
                evaluator_backend=evaluator_backend,
                output_dir=output_dir,
                spec=spec,
                episode_result=result,
            )
            _write_json(_evaluator_result_path(output_dir, spec), evaluator_result)
            write_summaries(output_dir)
            if evaluator_result["status"] != "evaluated":
                raise RuntimeError(
                    "episode %s hit an evaluator failure: %s"
                    % (spec.episode_id, evaluator_result["error_message"])
                )

    results = write_summaries(output_dir)
    evaluated = sum(result["status"] == "evaluated" for result in results)
    failed = sum(
        result["status"] == "infrastructure_failed" for result in results
    )
    print(
        "Finished: %d evaluated, %d infrastructure failed, %d total"
        % (evaluated, failed, len(results))
    )
    return results


def _add_role_arguments(parser: argparse.ArgumentParser, role: str) -> None:
    label = role.capitalize()
    parser.add_argument(
        "--%s-provider" % role,
        choices=("deepseek", "openai"),
        default=DEFAULT_PROVIDER,
        help="%s provider binding" % label,
    )
    parser.add_argument("--%s-model" % role, help="exact %s model ID" % label)
    parser.add_argument(
        "--%s-endpoint" % role,
        help="complete %s HTTP endpoint override" % label,
    )
    parser.add_argument(
        "--%s-thinking" % role,
        choices=("enabled", "disabled"),
        help="DeepSeek thinking mode for %s" % label,
    )
    parser.add_argument(
        "--%s-reasoning-effort" % role,
        choices=("none", "low", "medium", "high", "xhigh", "max"),
        help="provider reasoning effort for %s" % label,
    )
    parser.add_argument(
        "--%s-timeout-s" % role,
        type=float,
        default=120.0,
        help="HTTP timeout for each %s call" % label,
    )
    credential_group = parser.add_mutually_exclusive_group()
    credential_group.add_argument(
        "--%s-api-key" % role,
        help="runtime-only %s credential; prompt/stdin/environment is safer" % label,
    )
    credential_group.add_argument(
        "--%s-api-key-stdin" % role,
        action="store_true",
        help="read one %s credential line from stdin" % label,
    )
    credential_group.add_argument(
        "--%s-prompt-api-key" % role,
        action="store_true",
        help="read the %s credential interactively without echo" % label,
    )
    parser.add_argument(
        "--%s-api-key-env" % role,
        help=(
            "environment variable used for %s when no explicit credential mode "
            "is selected; defaults by provider" % label
        ),
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run independently configured Player, Oracle, and post-hoc Evaluator "
            "profiles across one registered matched four-cell case pack."
        )
    )
    parser.add_argument("--output-dir", required=True)
    parser.add_argument(
        "--case-pack",
        choices=tuple(CASE_PACKS),
        default=DEFAULT_CASE_PACK,
        help="registered case collection; temporal cases remain separate from curated",
    )
    for role in ROLES:
        _add_role_arguments(parser, role)
    parser.add_argument(
        "--family",
        action="append",
        choices=CASE_FAMILIES + TEMPORAL_CASE_FAMILIES,
        help="filter families; paid execution must remain a schedule prefix",
    )
    parser.add_argument(
        "--world",
        action="append",
        choices=WORLDS,
        help="filter worlds; paid execution must remain a schedule prefix",
    )
    parser.add_argument(
        "--track",
        action="append",
        choices=TRACKS,
        help="filter tracks; paid execution must remain a schedule prefix",
    )
    parser.add_argument(
        "--repeat",
        action="append",
        type=int,
        choices=tuple(range(1, MATCHED_REPEATS + 1)),
        help="filter repeat blocks; paid execution must remain a schedule prefix",
    )
    parser.add_argument(
        "--schedule-seed",
        type=int,
        default=DEFAULT_SCHEDULE_SEED,
    )
    parser.add_argument("--player-max-output-tokens", type=int, default=8192)
    parser.add_argument(
        "--max-repair-attempts",
        type=int,
        choices=(0, 1),
        default=1,
    )
    parser.add_argument("--oracle-max-output-tokens", type=int, default=256)
    parser.add_argument("--evaluator-max-output-tokens", type=int, default=2048)
    parser.add_argument("--max-actions", type=int, default=16)
    parser.add_argument("--workers", type=int, choices=(1,), default=1)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="write and validate the plan without reading an API key",
    )
    return parser


def _resolve_api_key(args: argparse.Namespace, role: str) -> str:
    runtime = _runtime_profile(args).for_role(role)
    direct = _role_value(args, role, "api_key")
    from_stdin = bool(_role_value(args, role, "api_key_stdin"))
    from_prompt = bool(_role_value(args, role, "prompt_api_key"))
    if direct is not None:
        api_key = direct
    elif from_stdin:
        api_key = sys.stdin.readline().rstrip("\r\n")
    elif from_prompt:
        api_key = getpass.getpass(
            "%s %s API key: " % (role.capitalize(), runtime.provider.title())
        )
    else:
        api_key = os.environ.get(runtime.api_key_env, "")
    if not api_key.strip():
        raise SystemExit(
            "missing %s API key: use --%s-api-key, --%s-api-key-stdin, "
            "--%s-prompt-api-key, or set %s"
            % (role, role, role, role, runtime.api_key_env)
        )
    return api_key


def _resolve_api_keys(args: argparse.Namespace) -> Mapping[str, str]:
    return {role: _resolve_api_key(args, role) for role in ROLES}


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = _parser().parse_args(argv)
    _, case_families, _ = _case_pack(args)
    build_plan(args.schedule_seed, families=case_families)
    run_matrix(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
