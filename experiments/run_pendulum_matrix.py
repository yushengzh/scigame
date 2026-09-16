"""Run the minimal pendulum prior-versus-evidence validation matrix.

The fixed design is three independently loaded Player slots by two pendulum
worlds by two tracks by five provider-stochastic repeats (60 episodes).  The
three slots currently use the same model and inference policy; they are replicate
groups, not three model treatments.  This module deliberately stays outside the
benchmark core: it expands the matrix, binds DeepSeek Chat Completions to the
provider-neutral adapter, and writes one JSONL log per episode plus small
machine-readable summaries.

API credentials are accepted only through a command-line argument, a named
process environment variable, stdin, or ``getpass``.  They are held in memory
and are never included in run metadata, config files, summaries, or provider
response metadata.
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
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence

from role_benchmark import (
    BenchmarkTrack,
    GenerationConfig,
    GenerationRequest,
    GenerationResponse,
    TerminationKind,
    TextGenerationBackend,
    TokenUsage,
    analyze_failure_events,
    load_run_log,
    run_llm_episode,
)
from role_benchmark.cases import make_pendulum_case


EXPERIMENT_SCHEMA = "role_benchmark.pendulum_matrix"
EPISODE_RESULT_SCHEMA = "role_benchmark.pendulum_matrix_episode"
DEFAULT_ENDPOINT = "https://api.deepseek.com/chat/completions"
DEFAULT_API_KEY_ENV = "DEEPSEEK_API_KEY"
DEFAULT_SCHEDULE_SEED = 20260824
WORLDS = ("historical", "counterfactual")
TRACKS = (BenchmarkTrack.IDENTIFICATION.value, BenchmarkTrack.DISCOVERY.value)
REPEATS = 5


@dataclass(frozen=True)
class ModelProfile:
    profile_id: str
    model: str
    thinking: str
    reasoning_effort: Optional[str]


PLAYER_PROFILES = (
    ModelProfile("player_1", "deepseek-v4-flash", "disabled", None),
    ModelProfile("player_2", "deepseek-v4-flash", "disabled", None),
    ModelProfile("player_3", "deepseek-v4-flash", "disabled", None),
)
ORACLE_PROFILE = ModelProfile(
    "oracle_flash_no_think", "deepseek-v4-flash", "disabled", None
)


def _utc_now() -> str:
    return (
        _datetime.datetime.now(_datetime.timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z")
    )


def _slug(value: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", value.strip()).strip("-._")
    if not slug:
        raise ValueError("model name must contain a filename-safe character")
    return slug.lower()


@dataclass(frozen=True)
class EpisodeSpec:
    schedule_index: int
    episode_id: str
    player_profile: str
    player_model: str
    thinking: str
    reasoning_effort: Optional[str]
    world: str
    track: str
    repeat: int


def build_plan(schedule_seed: int = DEFAULT_SCHEDULE_SEED) -> List[EpisodeSpec]:
    """Expand a seeded randomized-complete-block 3 x 2 x 2 x 5 design."""

    if isinstance(schedule_seed, bool) or not isinstance(schedule_seed, int):
        raise ValueError("schedule_seed must be an integer")
    cells = [
        (profile_index, profile, world, track)
        for profile_index, profile in enumerate(PLAYER_PROFILES, start=1)
        for world in WORLDS
        for track in TRACKS
    ]
    generator = random.Random(schedule_seed)
    plan: List[EpisodeSpec] = []
    for repeat in range(1, REPEATS + 1):
        block = list(cells)
        generator.shuffle(block)
        if plan and (
            block[0][1].profile_id,
            block[0][2],
            block[0][3],
        ) == (
            plan[-1].player_profile,
            plan[-1].world,
            plan[-1].track,
        ):
            block[0], block[1] = block[1], block[0]
        for profile_index, profile, world, track in block:
            episode_id = (
                "p%02d-%s__%s__%s__r%02d"
                % (profile_index, _slug(profile.profile_id), world, track, repeat)
            )
            plan.append(
                EpisodeSpec(
                    schedule_index=len(plan) + 1,
                    episode_id=episode_id,
                    player_profile=profile.profile_id,
                    player_model=profile.model,
                    thinking=profile.thinking,
                    reasoning_effort=profile.reasoning_effort,
                    world=world,
                    track=track,
                    repeat=repeat,
                )
            )
    if len(plan) != 60 or len({spec.episode_id for spec in plan}) != 60:
        raise AssertionError("the pendulum validation plan must contain 60 unique episodes")
    return plan


def select_plan(
    plan: Sequence[EpisodeSpec],
    *,
    profiles: Optional[Sequence[str]] = None,
    worlds: Optional[Sequence[str]] = None,
    tracks: Optional[Sequence[str]] = None,
    repeats: Optional[Sequence[int]] = None,
) -> List[EpisodeSpec]:
    """Select fixed-design cells without changing their IDs or formal status."""

    profile_set = set(profiles or [profile.profile_id for profile in PLAYER_PROFILES])
    world_set = set(worlds or WORLDS)
    track_set = set(tracks or TRACKS)
    repeat_set = set(repeats or range(1, REPEATS + 1))
    return [
        spec
        for spec in plan
        if spec.player_profile in profile_set
        and spec.world in world_set
        and spec.track in track_set
        and spec.repeat in repeat_set
    ]


class DeepSeekChatBackend:
    """Thin standard-library binding for DeepSeek Chat Completions."""

    binding_id = "pendulum_matrix.deepseek_chat"

    def __init__(
        self,
        *,
        endpoint: str,
        api_key: str,
        model: str,
        thinking: str,
        reasoning_effort: Optional[str],
        timeout_s: float = 120.0,
        urlopen: Callable[..., Any] = urllib.request.urlopen,
    ) -> None:
        if not endpoint.startswith(("https://", "http://")):
            raise ValueError("endpoint must be an HTTP(S) URL")
        if not api_key or not api_key.strip():
            raise ValueError("api_key must be non-empty")
        if not model or not model.strip():
            raise ValueError("model must be non-empty")
        if thinking not in ("enabled", "disabled"):
            raise ValueError("thinking must be 'enabled' or 'disabled'")
        if reasoning_effort not in (None, "low", "high", "max"):
            raise ValueError("reasoning_effort must be None, 'low', 'high', or 'max'")
        if thinking == "disabled" and reasoning_effort is not None:
            raise ValueError("reasoning_effort requires thinking='enabled'")
        if timeout_s <= 0:
            raise ValueError("timeout_s must be positive")
        self._endpoint = endpoint
        self._api_key = api_key
        self._model = model
        self._thinking = thinking
        self._reasoning_effort = reasoning_effort
        self._timeout_s = float(timeout_s)
        self._urlopen = urlopen

    def generate(self, request: GenerationRequest) -> GenerationResponse:
        payload: Dict[str, Any] = {
            "model": self._model,
            "messages": [
                {"role": message.role, "content": message.content}
                for message in request.messages
            ],
            "max_tokens": request.config.max_output_tokens,
            "temperature": request.config.temperature,
            "top_p": request.config.top_p,
            "stream": False,
            "response_format": {"type": "json_object"},
            "thinking": {"type": self._thinking},
        }
        if self._reasoning_effort is not None:
            payload["reasoning_effort"] = self._reasoning_effort

        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode(
            "utf-8"
        )
        http_request = urllib.request.Request(
            self._endpoint,
            data=body,
            headers={
                "Authorization": "Bearer " + self._api_key,
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            method="POST",
        )
        try:
            with self._urlopen(http_request, timeout=self._timeout_s) as response:
                response_body = response.read()
        except urllib.error.HTTPError as exc:
            # Do not copy provider bodies or request headers into errors/logs.
            raise RuntimeError("provider HTTP status %d" % exc.code) from exc
        except urllib.error.URLError as exc:
            raise RuntimeError("provider connection failed") from exc

        try:
            decoded = json.loads(response_body.decode("utf-8"))
            choice = decoded["choices"][0]
            message = choice["message"]
            refusal = message.get("refusal")
            text = message.get("content")
            if text is None and isinstance(refusal, str) and refusal:
                text = refusal
        except (
            KeyError,
            IndexError,
            TypeError,
            UnicodeDecodeError,
            json.JSONDecodeError,
        ) as exc:
            raise RuntimeError("provider returned an invalid chat-completion response") from exc
        if not isinstance(text, str):
            raise RuntimeError("provider returned non-text assistant content")
        finish_reason = choice.get("finish_reason")
        if not isinstance(finish_reason, str) or not finish_reason.strip():
            raise RuntimeError("provider response omitted completion status")

        usage = decoded.get("usage") or {}
        input_tokens = usage.get("prompt_tokens")
        output_tokens = usage.get("completion_tokens")
        details = usage.get("completion_tokens_details") or {}
        reasoning_tokens = details.get("reasoning_tokens")
        return GenerationResponse(
            text=text,
            provider="deepseek",
            model=str(decoded.get("model") or self._model),
            finish_reason=finish_reason,
            response_id=str(decoded.get("id") or ""),
            usage=TokenUsage(
                input_tokens=input_tokens if isinstance(input_tokens, int) else None,
                output_tokens=output_tokens if isinstance(output_tokens, int) else None,
            ),
            metadata={
                **({"content_kind": "refusal"} if refusal else {}),
                "binding_id": self.binding_id,
                "structured_output_transport": "chat_completions_json_object",
                "thinking": self._thinking,
                "reasoning_effort": self._reasoning_effort,
                "reasoning_tokens": (
                    reasoning_tokens if isinstance(reasoning_tokens, int) else None
                ),
            },
        )


BackendLoader = Callable[[], TextGenerationBackend]


def load_player_backends(
    args: argparse.Namespace,
    *,
    api_key: str,
    loaders: Optional[Mapping[str, BackendLoader]] = None,
) -> Mapping[str, TextGenerationBackend]:
    """Load exactly one independent provider backend for each Player slot."""

    expected_ids = tuple(profile.profile_id for profile in PLAYER_PROFILES)
    if loaders is not None and set(loaders) != set(expected_ids):
        raise ValueError("Player backend loaders must match every Player slot exactly")

    backends: Dict[str, TextGenerationBackend] = {}
    for profile in PLAYER_PROFILES:
        if loaders is None:
            backend = DeepSeekChatBackend(
                endpoint=args.endpoint,
                api_key=api_key,
                model=profile.model,
                thinking=profile.thinking,
                reasoning_effort=profile.reasoning_effort,
                timeout_s=args.timeout_s,
            )
        else:
            backend = loaders[profile.profile_id]()
        if not callable(getattr(backend, "generate", None)):
            raise ValueError(
                "Player backend loader for %s returned an invalid backend"
                % profile.profile_id
            )
        backends[profile.profile_id] = backend

    if len({id(backend) for backend in backends.values()}) != len(expected_ids):
        raise ValueError("each Player slot must load a distinct backend instance")
    return backends


def load_oracle_backend(
    args: argparse.Namespace,
    *,
    api_key: str,
    loader: Optional[BackendLoader] = None,
) -> TextGenerationBackend:
    """Load the Oracle presentation backend independently from all Players."""

    backend = (
        loader()
        if loader is not None
        else DeepSeekChatBackend(
            endpoint=args.endpoint,
            api_key=api_key,
            model=ORACLE_PROFILE.model,
            thinking=ORACLE_PROFILE.thinking,
            reasoning_effort=ORACLE_PROFILE.reasoning_effort,
            timeout_s=args.timeout_s,
        )
    )
    if not callable(getattr(backend, "generate", None)):
        raise ValueError("Oracle backend loader returned an invalid backend")
    return backend


def _config_payload(
    args: argparse.Namespace,
    plan: Sequence[EpisodeSpec],
) -> Mapping[str, Any]:
    """Return the persisted experiment config.  Credentials are absent by construction."""

    expected_order = [spec.episode_id for spec in build_plan(args.schedule_seed)]
    actual_order = [spec.episode_id for spec in plan]
    if actual_order != expected_order:
        raise ValueError("plan does not match the declared schedule_seed")
    return {
        "schema": EXPERIMENT_SCHEMA,
        "created_at": _utc_now(),
        "design": {
            "player_profiles": [asdict(profile) for profile in PLAYER_PROFILES],
            "base_models": sorted({profile.model for profile in PLAYER_PROFILES}),
            "profile_interpretation": (
                "three independently loaded Player slots with an identical model "
                "and inference policy; replicate groups, not model treatments"
            ),
            "worlds": list(WORLDS),
            "tracks": list(TRACKS),
            "repeats": REPEATS,
            "repeat_policy": "provider-stochastic repeats; no client seed",
            "total_episodes": len(plan),
        },
        "schedule": {
            "policy": "seeded_randomized_complete_blocks",
            "seed": args.schedule_seed,
            "block_size": len(PLAYER_PROFILES) * len(WORLDS) * len(TRACKS),
            "execution_order": actual_order,
        },
        "provider": {
            "binding_id": DeepSeekChatBackend.binding_id,
            "endpoint": args.endpoint,
            "api": "chat_completions",
            "response_format": "json_object",
        },
        "player_generation": {
            "temperature": 0.0,
            "top_p": 1.0,
            "seed": None,
            "max_output_tokens": args.max_output_tokens,
            "max_repair_attempts": args.max_repair_attempts,
            "max_actions": args.max_actions,
            "note": (
                "thinking is disabled for every Player, so max_output_tokens "
                "bounds only the visible JSON completion"
            ),
        },
        "oracle": {
            "mode": "llm_presentation_over_authoritative_world_model",
            "profile": asdict(ORACLE_PROFILE),
            "temperature": 0.0,
        },
        "execution": {
            "workers": args.workers,
            "order_guarantee": "sequential_schedule_index",
            "player_termination_policy": "evaluate_and_consume_active_episode",
            "infrastructure_failure_policy": "halt_and_retry_same_index",
        },
    }


def _write_json(path: Path, payload: Any, *, exclusive: bool = False) -> None:
    mode = "x" if exclusive else "w"
    with path.open(mode, encoding="utf-8", newline="\n") as stream:
        json.dump(payload, stream, ensure_ascii=False, indent=2, sort_keys=True)
        stream.write("\n")


def prepare_output(output_dir: Path, config: Mapping[str, Any]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "episodes").mkdir(exist_ok=True)
    (output_dir / "results").mkdir(exist_ok=True)
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
        raise ValueError(
            "output directory already contains a different experiment config"
        )


def _result_path(output_dir: Path, spec: EpisodeSpec) -> Path:
    return output_dir / "results" / (spec.episode_id + ".result.json")


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


def _selected_portfolio_confidence(outcome: Any) -> Optional[float]:
    portfolio = outcome.final_portfolio
    submission = outcome.final_submission
    if portfolio is None or submission is None:
        return None
    selected_id = submission.hypothesis_id or portfolio.top.hypothesis_id
    matches = [
        item.confidence
        for item in portfolio.hypotheses
        if item.hypothesis_id == selected_id
    ]
    return matches[0] if len(matches) == 1 else None


def _evaluated_result(
    *,
    spec: EpisodeSpec,
    log_path: Path,
    output_dir: Path,
    run: Any,
    started_at: str,
    elapsed_s: float,
    failure_analysis: Optional[Mapping[str, Any]] = None,
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

    return {
        "schema": EPISODE_RESULT_SCHEMA,
        "schedule_index": spec.schedule_index,
        "episode_id": spec.episode_id,
        "status": "evaluated",
        "player_profile": spec.player_profile,
        "player_model": spec.player_model,
        "thinking": spec.thinking,
        "reasoning_effort": spec.reasoning_effort,
        "world": spec.world,
        "track": spec.track,
        "repeat": spec.repeat,
        "log_path": _relative_path(log_path, output_dir),
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
        "selected_portfolio_confidence": _selected_portfolio_confidence(
            outcome
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


def _infrastructure_failed_result(
    *,
    spec: EpisodeSpec,
    log_path: Path,
    output_dir: Path,
    exc: Exception,
    started_at: str,
    elapsed_s: float,
) -> Mapping[str, Any]:
    return {
        "schema": EPISODE_RESULT_SCHEMA,
        "schedule_index": spec.schedule_index,
        "episode_id": spec.episode_id,
        "status": "infrastructure_failed",
        "player_profile": spec.player_profile,
        "player_model": spec.player_model,
        "thinking": spec.thinking,
        "reasoning_effort": spec.reasoning_effort,
        "world": spec.world,
        "track": spec.track,
        "repeat": spec.repeat,
        "log_path": _relative_path(log_path, output_dir),
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
        "selected_portfolio_confidence": None,
        "scores": {},
        "trajectory_scores": {},
        "protocol_violations": [],
        "failure_analysis": None,
        "player_llm_stats": None,
        "oracle_llm_stats": None,
        "error_type": type(exc).__name__,
        # Core/provider boundaries already sanitize transport details.
        "error_message": str(exc),
    }


SUMMARY_COLUMNS = (
    "schedule_index",
    "episode_id",
    "status",
    "active_pass",
    "active_pass_category",
    "termination_kind",
    "reason_code",
    "termination_message",
    "scientifically_evaluable",
    "protocol_completion",
    "player_profile",
    "player_model",
    "thinking",
    "reasoning_effort",
    "world",
    "track",
    "repeat",
    "log_path",
    "run_id",
    "evaluation_success",
    "evaluation_message",
    "attempts_used",
    "selected_portfolio_confidence",
    "player_turns",
    "player_input_tokens",
    "player_output_tokens",
    "oracle_turns",
    "oracle_input_tokens",
    "oracle_output_tokens",
    "elapsed_s",
    "experiment_discriminativeness_mean",
    "evidence_aligned_belief_update_rate",
    "forecast_pair_count",
    "scorable_belief_pair_count",
    "trajectory_scores_json",
    "scores_json",
    "error_type",
    "error_message",
)


def _csv_row(result: Mapping[str, Any]) -> Mapping[str, Any]:
    player = result.get("player_llm_stats") or {}
    oracle = result.get("oracle_llm_stats") or {}
    trajectory = result.get("trajectory_scores") or {}
    return {
        "schedule_index": result.get("schedule_index"),
        "episode_id": result["episode_id"],
        "status": result["status"],
        "active_pass": result.get(
            "active_pass", result.get("evaluation_success") is True
        ),
        "active_pass_category": result.get("active_pass_category"),
        "termination_kind": result.get("termination_kind"),
        "reason_code": result.get("reason_code"),
        "termination_message": result.get("termination_message"),
        "scientifically_evaluable": result.get("scientifically_evaluable"),
        "protocol_completion": result.get("protocol_completion"),
        "player_profile": result["player_profile"],
        "player_model": result["player_model"],
        "thinking": result["thinking"],
        "reasoning_effort": result.get("reasoning_effort"),
        "world": result["world"],
        "track": result["track"],
        "repeat": result["repeat"],
        "log_path": result["log_path"],
        "run_id": result.get("run_id"),
        "evaluation_success": result.get("evaluation_success"),
        "evaluation_message": result.get("evaluation_message"),
        "attempts_used": result.get("attempts_used"),
        "selected_portfolio_confidence": result.get(
            "selected_portfolio_confidence"
        ),
        "player_turns": player.get("player_turns"),
        "player_input_tokens": player.get("input_tokens"),
        "player_output_tokens": player.get("output_tokens"),
        "oracle_turns": oracle.get("oracle_turns"),
        "oracle_input_tokens": oracle.get("input_tokens"),
        "oracle_output_tokens": oracle.get("output_tokens"),
        "elapsed_s": result.get("elapsed_s"),
        "experiment_discriminativeness_mean": trajectory.get(
            "experiment_discriminativeness_mean"
        ),
        "evidence_aligned_belief_update_rate": trajectory.get(
            "evidence_aligned_belief_update_rate"
        ),
        "forecast_pair_count": trajectory.get("forecast_pair_count"),
        "scorable_belief_pair_count": trajectory.get(
            "scorable_belief_pair_count"
        ),
        "trajectory_scores_json": json.dumps(
            trajectory, ensure_ascii=False, sort_keys=True
        ),
        "scores_json": json.dumps(
            result.get("scores") or {}, ensure_ascii=False, sort_keys=True
        ),
        "error_type": result.get("error_type"),
        "error_message": result.get("error_message"),
    }


def load_episode_results(output_dir: Path) -> List[Mapping[str, Any]]:
    results = []
    for path in sorted((output_dir / "results").glob("*.result.json")):
        results.append(json.loads(path.read_text(encoding="utf-8")))
    missing_schedule_index = (
        len(PLAYER_PROFILES) * len(WORLDS) * len(TRACKS) * REPEATS + 1
    )
    return sorted(
        results,
        key=lambda result: (
            result.get("schedule_index", missing_schedule_index),
            result["episode_id"],
        ),
    )


def _result_consumes_schedule(result: Mapping[str, Any]) -> bool:
    return result.get("status") == "evaluated"


def write_summaries(output_dir: Path) -> List[Mapping[str, Any]]:
    results = load_episode_results(output_dir)
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


def _make_case(spec: EpisodeSpec) -> Any:
    try:
        return make_pendulum_case(
            spec.world,
            track=BenchmarkTrack(spec.track),
        )
    except TypeError as exc:
        raise RuntimeError(
            "the benchmark core must expose make_pendulum_case(world, track=...)"
        ) from exc


def _run_one_episode(
    args: argparse.Namespace,
    *,
    player_backend: TextGenerationBackend,
    oracle_backend: TextGenerationBackend,
    output_dir: Path,
    spec: EpisodeSpec,
    log_path: Path,
) -> Mapping[str, Any]:
    started_at = _utc_now()
    started_clock = time.monotonic()
    try:
        case = _make_case(spec)
        run = run_llm_episode(
            player_backend,
            case,
            str(log_path),
            config=GenerationConfig(
                max_output_tokens=args.max_output_tokens,
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
                "player_profile": spec.player_profile,
                "player_model": spec.player_model,
                "thinking": spec.thinking,
                "reasoning_effort": spec.reasoning_effort,
                "world": spec.world,
                "track": spec.track,
                "repeat": spec.repeat,
                "schedule_index": spec.schedule_index,
                "schedule_seed": args.schedule_seed,
                "schedule_policy": "seeded_randomized_complete_blocks",
                "repeat_policy": "provider_stochastic_no_client_seed",
                "oracle_profile": ORACLE_PROFILE.profile_id,
                "oracle_model": ORACLE_PROFILE.model,
                "provider_binding_id": DeepSeekChatBackend.binding_id,
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
        )
    except Exception as exc:
        return _infrastructure_failed_result(
            spec=spec,
            log_path=log_path,
            output_dir=output_dir,
            exc=exc,
            started_at=started_at,
            elapsed_s=time.monotonic() - started_clock,
        )


def run_matrix(
    args: argparse.Namespace,
    *,
    api_key: str,
    player_backend_loaders: Optional[Mapping[str, BackendLoader]] = None,
    oracle_backend_loader: Optional[BackendLoader] = None,
) -> List[Mapping[str, Any]]:
    if args.workers != 1:
        raise ValueError("the frozen randomized schedule requires workers=1")
    output_dir = Path(args.output_dir).resolve()
    full_plan = build_plan(args.schedule_seed)
    plan = select_plan(
        full_plan,
        profiles=args.profile,
        worlds=args.world,
        tracks=args.track,
        repeats=args.repeat,
    )
    config = _config_payload(args, full_plan)
    prepare_output(output_dir, config)
    write_summaries(output_dir)

    if args.dry_run:
        print("Selected %d of 60 episodes in %s" % (len(plan), output_dir))
        return []

    loaded_results = load_episode_results(output_dir)
    existing_results = {result["episode_id"]: result for result in loaded_results}
    if len(existing_results) != len(loaded_results):
        raise ValueError("result sidecars contain duplicate episode IDs")
    expected_ids = [spec.episode_id for spec in full_plan]
    unknown_ids = set(existing_results) - set(expected_ids)
    if unknown_ids:
        raise ValueError("result sidecars contain episode IDs outside the frozen plan")
    recorded_ids = [
        episode_id for episode_id in expected_ids if episode_id in existing_results
    ]
    if recorded_ids != expected_ids[: len(recorded_ids)]:
        raise ValueError("result sidecars must form a prefix of the frozen schedule")
    for spec in full_plan[: len(recorded_ids)]:
        recorded_index = existing_results[spec.episode_id].get("schedule_index")
        if recorded_index != spec.schedule_index:
            raise ValueError("result sidecar schedule_index differs from the frozen plan")

    consumed_count = 0
    for spec in full_plan:
        result = existing_results.get(spec.episode_id)
        if result is None or not _result_consumes_schedule(result):
            break
        consumed_count += 1
    remaining = full_plan[consumed_count:]
    selected_ids = {spec.episode_id for spec in plan}
    selected_pending = [
        spec for spec in remaining if spec.episode_id in selected_ids
    ]
    if selected_pending != remaining[: len(selected_pending)]:
        raise ValueError(
            "selectors must choose a prefix of the remaining frozen schedule"
        )

    # Fail before the first paid API request if any selected track cannot be built.
    for selected_track in sorted({spec.track for spec in selected_pending}):
        _make_case(
            next(spec for spec in selected_pending if spec.track == selected_track)
        )

    pending = []
    selected_pending_ids = {spec.episode_id for spec in selected_pending}
    for spec in plan:
        index = spec.schedule_index
        if spec.episode_id not in selected_pending_ids:
            print("[%02d/60] SKIP %s" % (index, spec.episode_id))
        else:
            pending.append((index, spec, _next_log_path(output_dir, spec)))

    print(
        "Running %d selected unfinished episode(s) sequentially"
        % len(pending),
        flush=True,
    )
    if pending:
        player_backends = load_player_backends(
            args,
            api_key=api_key,
            loaders=player_backend_loaders,
        )
        oracle_backend = load_oracle_backend(
            args,
            api_key=api_key,
            loader=oracle_backend_loader,
        )
        if id(oracle_backend) in {id(backend) for backend in player_backends.values()}:
            raise ValueError("Oracle and Player slots must use distinct backend instances")

        for index, spec, log_path in pending:
            episode_result = _run_one_episode(
                args,
                player_backend=player_backends[spec.player_profile],
                oracle_backend=oracle_backend,
                output_dir=output_dir,
                spec=spec,
                log_path=log_path,
            )
            result_path = _result_path(output_dir, spec)
            _write_json(
                result_path,
                episode_result,
                exclusive=not result_path.exists(),
            )
            write_summaries(output_dir)
            labels = {
                "pass": "PASS",
                "scientific_failure": "SCI",
                "player_generation_failure": "GEN",
                "player_protocol_failure": "PROTO",
            }
            label = (
                "INFRA"
                if episode_result["status"] == "infrastructure_failed"
                else labels[episode_result["active_pass_category"]]
            )
            print("[%02d/60] %-4s %s" % (index, label, spec.episode_id), flush=True)
            if episode_result["status"] == "infrastructure_failed":
                raise RuntimeError(
                    "episode %s hit an infrastructure failure: %s"
                    % (spec.episode_id, episode_result["error_message"])
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


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run 3 independently loaded Player slots x 2 pendulum worlds x "
            "2 tracks x 5 provider-stochastic repeats."
        )
    )
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--endpoint", default=DEFAULT_ENDPOINT)
    parser.add_argument(
        "--profile",
        action="append",
        choices=tuple(profile.profile_id for profile in PLAYER_PROFILES),
        help="filter slots; paid execution must still be the next schedule prefix",
    )
    parser.add_argument(
        "--world",
        action="append",
        choices=WORLDS,
        help="filter worlds; paid execution must still be the next schedule prefix",
    )
    parser.add_argument(
        "--track",
        action="append",
        choices=TRACKS,
        help="filter tracks; paid execution must still be the next schedule prefix",
    )
    parser.add_argument(
        "--repeat",
        action="append",
        type=int,
        choices=tuple(range(1, REPEATS + 1)),
        help="filter blocks; paid execution must still be the next schedule prefix",
    )
    parser.add_argument(
        "--schedule-seed",
        type=int,
        default=DEFAULT_SCHEDULE_SEED,
        help="seed for the frozen randomized-complete-block execution order",
    )
    credential_group = parser.add_mutually_exclusive_group()
    credential_group.add_argument(
        "--api-key",
        help="runtime credential; never persisted (prefer the environment for shell history)",
    )
    credential_group.add_argument(
        "--api-key-stdin",
        action="store_true",
        help="read one credential line from stdin",
    )
    credential_group.add_argument(
        "--prompt-api-key",
        action="store_true",
        help="read the credential interactively with getpass",
    )
    parser.add_argument(
        "--api-key-env",
        default=DEFAULT_API_KEY_ENV,
        help="environment variable used when no explicit credential mode is selected",
    )
    parser.add_argument("--max-output-tokens", type=int, default=8192)
    parser.add_argument(
        "--max-repair-attempts",
        type=int,
        choices=(0, 1),
        default=1,
        help=(
            "logged schema-directed regeneration calls per Player turn; "
            "the formal validation uses one"
        ),
    )
    parser.add_argument("--oracle-max-output-tokens", type=int, default=256)
    parser.add_argument("--max-actions", type=int, default=16)
    parser.add_argument("--timeout-s", type=float, default=120.0)
    parser.add_argument(
        "--workers",
        type=int,
        choices=(1,),
        default=1,
        help="formal randomized execution is sequential",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="write and validate the 60-episode plan without reading an API key",
    )
    return parser


def _resolve_api_key(args: argparse.Namespace) -> str:
    if args.api_key is not None:
        api_key = args.api_key
    elif args.api_key_stdin:
        api_key = sys.stdin.readline().rstrip("\r\n")
    elif args.prompt_api_key:
        api_key = getpass.getpass("DeepSeek API key: ")
    else:
        api_key = os.environ.get(args.api_key_env, "")
    if not api_key.strip():
        raise SystemExit(
            "missing API key: use --api-key, --api-key-stdin, "
            "--prompt-api-key, or set %s" % args.api_key_env
        )
    return api_key


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = _parser().parse_args(argv)
    # Validate the fixed design before looking for a credential.
    build_plan(args.schedule_seed)
    if args.dry_run:
        api_key = "dry-run-not-used"
    else:
        api_key = _resolve_api_key(args)
    run_matrix(args, api_key=api_key)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
