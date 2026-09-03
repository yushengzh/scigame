"""Run the cross-case/method matrix with independent role backends.

The frozen plan crosses every selected case cell with prior-only baseline,
fixed experimental design, and adaptive experimental design.  It exposes
Player, Oracle, and post-hoc Evaluator interfaces.  The primary Oracle is the
deterministic case implementation; an independently configured LLM may instead
present the same structured observation.  The Evaluator runs only after the
Player--Oracle log is sealed and never changes deterministic scientific scores.

Episodes are randomized within complete repeat blocks for the selected case
pack. Execution is sequential so dispatch order is identical to the
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
    ADAPTIVE_EXPERIMENTAL_DESIGN,
    BenchmarkTrack,
    ConditionDescriptor,
    ConditionRole,
    DatasetKind,
    EVALUATOR_SCORE_AXES,
    EVALUATION_METHODS,
    FIXED_EXPERIMENTAL_DESIGN,
    GenerationConfig,
    HELD_OUT_PREDICTION_SCORE,
    HELD_OUT_PREDICTION_SCORE_VERSION,
    LLMEvaluatorCallError,
    PRIOR_ONLY_BASELINE,
    PostHocLLMEvaluator,
    TerminationKind,
    TextGenerationBackend,
    analyze_failure_events,
    build_evaluation_method_plan,
    condition_descriptor_to_payload,
    evaluation_method_plan_to_payload,
    fixed_observation_to_payload,
    llm_evaluation_to_payload,
    load_run_log,
    prepare_evaluation_case,
    run_llm_episode,
    validate_condition_descriptors,
)
from role_benchmark.cases import (
    CASE_FAMILIES,
    CASE_SPECS,
)
from role_benchmark.cases.matched import MatchedFamilySpec, make_matched_case
from role_benchmark.counterfactual import (
    AUTHORED_TEMPORAL_COUNTERFACTUAL_FAMILIES,
    COUNTERFACTUAL_DIFFICULTIES,
    make_authored_temporal_counterfactual_variants,
    make_curated_counterfactual_variants,
)
from role_benchmark.temporal_cases import (
    TEMPORAL_CASE_FAMILIES,
    TEMPORAL_CASE_SPECS,
    TEMPORAL_SOURCE_CONDITIONS,
    TEMPORAL_SOURCE_CONDITION_RUNTIME_MAP,
    TEMPORAL_SOURCE_PAPER_IDS,
    TEMPORAL_SOURCE_VERSION_IDS,
)
from role_benchmark.llm import (
    generation_request_to_payload,
    generation_response_to_payload,
)
from role_benchmark.wire import final_submission_to_payload

from experiments.run_pendulum_matrix import DeepSeekChatBackend
from experiments.openai_responses import OpenAIResponsesBackend


EXPERIMENT_SCHEMA = "role_benchmark.case_matrix.v2"
EPISODE_RESULT_SCHEMA = "role_benchmark.case_matrix_episode.v2"
LLM_EVALUATOR_RESULT_SCHEMA = "role_benchmark.case_matrix_llm_evaluation.v2"
DEFAULT_PROVIDER = "deepseek"
DEEPSEEK_ENDPOINT = "https://api.deepseek.com/chat/completions"
OPENAI_ENDPOINT = "https://api.openai.com/v1/responses"
DEEPSEEK_API_KEY_ENV = "DEEPSEEK_API_KEY"
OPENAI_API_KEY_ENV = "OPENAI_API_KEY"

DEFAULT_SCHEDULE_SEED = 20260825
DEFAULT_CASE_PACK = "curated"
DEFAULT_EXPERIMENT_ID = "development"

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

DETERMINISTIC_ORACLE = "deterministic"
LLM_PRESENTATION_ORACLE = "llm_presentation"
ORACLE_MODES: Tuple[str, ...] = (
    DETERMINISTIC_ORACLE,
    LLM_PRESENTATION_ORACLE,
)

MATCHED_FAMILIES: Tuple[str, ...] = CASE_FAMILIES
CONDITIONS: Tuple[str, ...] = ("historical", "counterfactual")
TASK_SETTINGS: Tuple[str, ...] = (
    BenchmarkTrack.IDENTIFICATION.value,
    BenchmarkTrack.DISCOVERY.value,
)
MATCHED_REPEATS = 5
CELLS_PER_REPEAT = (
    len(CASE_FAMILIES)
    * len(COUNTERFACTUAL_DIFFICULTIES)
    * len(CONDITIONS)
    * len(TASK_SETTINGS)
    * len(EVALUATION_METHODS)
)
TOTAL_EPISODES = CELLS_PER_REPEAT * MATCHED_REPEATS


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
    checkpoint_or_snapshot_id: str
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
    snapshot_override = _role_value(args, role, "snapshot_id")
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
            checkpoint_or_snapshot_id=snapshot_override or "unknown",
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
            checkpoint_or_snapshot_id=snapshot_override or "unknown",
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
class CasePackDefinition:
    """Registered scientific specifications and condition semantics."""

    name: str
    families: Tuple[str, ...]
    specifications: Mapping[str, Mapping[str, MatchedFamilySpec]]
    conditions: Mapping[str, Mapping[str, Tuple[ConditionDescriptor, ...]]]
    source_paper_ids: Mapping[str, str]
    source_version_ids: Mapping[str, str]


def _historical_counterfactual_conditions(
    family_id: str,
    variant_id: str,
) -> Tuple[ConditionDescriptor, ...]:
    return validate_condition_descriptors(
        (
            ConditionDescriptor(
                dataset_kind=DatasetKind.HISTORICAL_COUNTERFACTUAL,
                family_id=family_id,
                variant_id=variant_id,
                condition_id="historical",
                condition_role=ConditionRole.HISTORICAL,
            ),
            ConditionDescriptor(
                dataset_kind=DatasetKind.HISTORICAL_COUNTERFACTUAL,
                family_id=family_id,
                variant_id=variant_id,
                condition_id="counterfactual",
                condition_role=ConditionRole.COUNTERFACTUAL,
            ),
        )
    )


_CURATED_VARIANTS = {
    family: make_curated_counterfactual_variants(specification)
    for family, specification in CASE_SPECS.items()
}
_TEMPORAL_COUNTERFACTUAL_VARIANTS = {
    family: make_authored_temporal_counterfactual_variants(
        TEMPORAL_CASE_SPECS[family]
    )
    for family in sorted(AUTHORED_TEMPORAL_COUNTERFACTUAL_FAMILIES)
}


def _variant_specifications(
    variants: Mapping[str, Mapping[str, Any]],
) -> Dict[str, Dict[str, MatchedFamilySpec]]:
    return {
        family: {
            variant_id: variant.spec
            for variant_id, variant in family_variants.items()
        }
        for family, family_variants in variants.items()
    }


def _variant_conditions(
    variants: Mapping[str, Mapping[str, Any]],
) -> Dict[str, Dict[str, Tuple[ConditionDescriptor, ...]]]:
    return {
        family: {
            variant_id: _historical_counterfactual_conditions(
                family, variant_id
            )
            for variant_id in family_variants
        }
        for family, family_variants in variants.items()
    }


CASE_PACKS: Mapping[str, CasePackDefinition] = {
    "curated": CasePackDefinition(
        name="curated",
        families=CASE_FAMILIES,
        specifications=_variant_specifications(_CURATED_VARIANTS),
        conditions=_variant_conditions(_CURATED_VARIANTS),
        source_paper_ids={},
        source_version_ids={},
    ),
    "temporal": CasePackDefinition(
        name="temporal",
        families=TEMPORAL_CASE_FAMILIES,
        specifications={
            family: {"source_reported_v1": TEMPORAL_CASE_SPECS[family]}
            for family in TEMPORAL_CASE_FAMILIES
        },
        conditions={
            family: {"source_reported_v1": TEMPORAL_SOURCE_CONDITIONS[family]}
            for family in TEMPORAL_CASE_FAMILIES
        },
        source_paper_ids=TEMPORAL_SOURCE_PAPER_IDS,
        source_version_ids=TEMPORAL_SOURCE_VERSION_IDS,
    ),
    "temporal_counterfactual": CasePackDefinition(
        name="temporal_counterfactual",
        families=tuple(sorted(AUTHORED_TEMPORAL_COUNTERFACTUAL_FAMILIES)),
        specifications=_variant_specifications(
            _TEMPORAL_COUNTERFACTUAL_VARIANTS
        ),
        conditions=_variant_conditions(_TEMPORAL_COUNTERFACTUAL_VARIANTS),
        source_paper_ids={
            family: TEMPORAL_SOURCE_PAPER_IDS[family]
            for family in sorted(AUTHORED_TEMPORAL_COUNTERFACTUAL_FAMILIES)
        },
        source_version_ids={
            family: TEMPORAL_SOURCE_VERSION_IDS[family]
            for family in sorted(AUTHORED_TEMPORAL_COUNTERFACTUAL_FAMILIES)
        },
    ),
}


@dataclass(frozen=True)
class EpisodeSpec:
    schedule_index: int
    episode_id: str
    case_pack: str
    dataset_kind: str
    case_family: str
    variant_id: str
    condition_id: str
    condition_role: str
    source_condition_id: Optional[str]
    source_paper_id: Optional[str]
    source_version_id: Optional[str]
    task_setting: str
    evaluation_method: str
    repeat: int

    @property
    def cell(self) -> Tuple[str, str, str, str, str, str]:
        return (
            self.case_family,
            self.variant_id,
            self.condition_id,
            self.condition_role,
            self.task_setting,
            self.evaluation_method,
        )

    @property
    def benchmark_instance_id(self) -> str:
        return "%s.%s.%s.%s.%s" % (
            self.case_pack,
            self.case_family,
            self.variant_id,
            self.condition_id,
            self.task_setting,
        )

def _case_cells(
    case_pack: CasePackDefinition,
    families: Sequence[str],
    *,
    variants: Optional[Sequence[str]] = None,
    conditions: Optional[Sequence[str]] = None,
    task_settings: Optional[Sequence[str]] = None,
    evaluation_methods: Optional[Sequence[str]] = None,
) -> List[Tuple[ConditionDescriptor, str, str]]:
    variant_set = set(variants) if variants is not None else None
    condition_set = set(conditions) if conditions is not None else None
    selected_task_settings = tuple(task_settings or TASK_SETTINGS)
    selected_methods = tuple(evaluation_methods or EVALUATION_METHODS)
    if not selected_task_settings or not set(selected_task_settings) <= set(TASK_SETTINGS):
        raise ValueError("task_settings must be registered task settings")
    if not selected_methods or not set(selected_methods) <= set(EVALUATION_METHODS):
        raise ValueError("evaluation_methods must be registered methods")
    cells = [
        (condition, task_setting, evaluation_method)
        for family in families
        for variant_id, variant_conditions in case_pack.conditions[family].items()
        if variant_set is None or variant_id in variant_set
        for condition in variant_conditions
        if condition_set is None or condition.condition_id in condition_set
        for task_setting in selected_task_settings
        for evaluation_method in selected_methods
    ]
    if not cells:
        raise ValueError("the selected design contains no benchmark cells")
    if variant_set is not None:
        available_variants = {
            variant_id
            for family in families
            for variant_id in case_pack.conditions[family]
        }
        if not variant_set <= available_variants:
            raise ValueError("variants must be registered in the selected case pack")
    if condition_set is not None:
        available_conditions = {
            item.condition_id
            for family in families
            for family_conditions in case_pack.conditions[family].values()
            for item in family_conditions
        }
        if not condition_set <= available_conditions:
            raise ValueError("conditions must be registered in the selected case pack")
    return cells


def _cell_tuple(
    cell: Tuple[ConditionDescriptor, str, str],
) -> Tuple[str, str, str, str, str, str]:
    condition, task_setting, evaluation_method = cell
    return (
        condition.family_id,
        condition.variant_id,
        condition.condition_id,
        condition.condition_role.value,
        task_setting,
        evaluation_method,
    )


def build_plan(
    schedule_seed: int = DEFAULT_SCHEDULE_SEED,
    *,
    families: Sequence[str] = MATCHED_FAMILIES,
    repeats: int = MATCHED_REPEATS,
    case_pack: str = DEFAULT_CASE_PACK,
    variants: Optional[Sequence[str]] = None,
    conditions: Optional[Sequence[str]] = None,
    task_settings: Optional[Sequence[str]] = None,
    evaluation_methods: Optional[Sequence[str]] = None,
) -> List[EpisodeSpec]:
    """Build deterministic randomized blocks over a complete case pack."""

    if isinstance(schedule_seed, bool) or not isinstance(schedule_seed, int):
        raise ValueError("schedule_seed must be an integer")
    family_tuple = tuple(families)
    if not family_tuple or len(set(family_tuple)) != len(family_tuple):
        raise ValueError("families must be a non-empty sequence of unique names")
    try:
        pack = CASE_PACKS[case_pack]
    except KeyError as exc:
        raise ValueError("unknown case pack %r" % case_pack) from exc
    unknown_families = set(family_tuple) - set(pack.families)
    if unknown_families:
        raise ValueError(
            "case family %s is not registered in the %s case pack"
            % (", ".join(sorted(unknown_families)), case_pack)
        )
    if isinstance(repeats, bool) or not isinstance(repeats, int) or repeats < 1:
        raise ValueError("repeats must be a positive integer")
    generator = random.Random(schedule_seed)
    cells = _case_cells(
        pack,
        family_tuple,
        variants=variants,
        conditions=conditions,
        task_settings=task_settings,
        evaluation_methods=evaluation_methods,
    )
    plan: List[EpisodeSpec] = []

    for repeat in range(1, repeats + 1):
        block = list(cells)
        generator.shuffle(block)
        if len(block) > 1 and plan and _cell_tuple(block[0]) == plan[-1].cell:
            replacement = next(
                index
                for index, cell in enumerate(block[1:], start=1)
                if _cell_tuple(cell) != plan[-1].cell
            )
            block[0], block[replacement] = block[replacement], block[0]

        for condition, task_setting, evaluation_method in block:
            episode_id = "%s__%s__%s__%s__%s__r%02d" % (
                _slug(condition.family_id),
                condition.variant_id,
                condition.condition_id,
                task_setting,
                _slug(evaluation_method),
                repeat,
            )
            plan.append(
                EpisodeSpec(
                    schedule_index=len(plan) + 1,
                    episode_id=episode_id,
                    case_pack=case_pack,
                    dataset_kind=condition.dataset_kind.value,
                    case_family=condition.family_id,
                    variant_id=condition.variant_id,
                    condition_id=condition.condition_id,
                    condition_role=condition.condition_role.value,
                    source_condition_id=condition.source_condition_id,
                    source_paper_id=pack.source_paper_ids.get(
                        condition.family_id
                    ),
                    source_version_id=pack.source_version_ids.get(
                        condition.family_id
                    ),
                    task_setting=task_setting,
                    evaluation_method=evaluation_method,
                    repeat=repeat,
                )
            )

    expected_total = len(cells) * repeats
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
    variants: Optional[Sequence[str]] = None,
    conditions: Optional[Sequence[str]] = None,
    task_settings: Optional[Sequence[str]] = None,
    evaluation_methods: Optional[Sequence[str]] = None,
    repeats: Optional[Sequence[int]] = None,
) -> List[EpisodeSpec]:
    """Filter cells without changing their frozen global order."""

    family_set = (
        set(families)
        if families is not None
        else {spec.case_family for spec in plan}
    )
    variant_set = (
        set(variants) if variants is not None else {spec.variant_id for spec in plan}
    )
    condition_set = (
        set(conditions)
        if conditions is not None
        else {spec.condition_id for spec in plan}
    )
    task_setting_set = (
        set(task_settings)
        if task_settings is not None
        else {spec.task_setting for spec in plan}
    )
    evaluation_method_set = (
        set(evaluation_methods)
        if evaluation_methods is not None
        else {spec.evaluation_method for spec in plan}
    )
    repeat_set = (
        set(repeats) if repeats is not None else {spec.repeat for spec in plan}
    )
    return [
        spec
        for spec in plan
        if spec.case_family in family_set
        and spec.variant_id in variant_set
        and spec.condition_id in condition_set
        and spec.task_setting in task_setting_set
        and spec.evaluation_method in evaluation_method_set
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
        "checkpoint_or_snapshot_id": runtime.checkpoint_or_snapshot_id,
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


def _oracle_mode(args: argparse.Namespace) -> str:
    mode = str(getattr(args, "oracle_mode", DETERMINISTIC_ORACLE))
    if mode not in ORACLE_MODES:
        raise ValueError(
            "unknown oracle mode %r; choose one of %s"
            % (mode, ", ".join(ORACLE_MODES))
        )
    return mode


def _experiment_id(args: argparse.Namespace) -> str:
    value = str(getattr(args, "experiment_id", DEFAULT_EXPERIMENT_ID))
    if not value.strip() or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", value) is None:
        raise ValueError("experiment_id must be a non-empty portable identifier")
    return value


def _repeat_count(args: argparse.Namespace) -> int:
    value = getattr(args, "repeats", MATCHED_REPEATS)
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError("repeats must be a positive integer")
    return value


def _design_selectors(args: argparse.Namespace) -> Mapping[str, Any]:
    return {
        "variants": getattr(args, "variant", None),
        "conditions": getattr(args, "condition", None),
        "task_settings": getattr(args, "task_setting", None),
        "evaluation_methods": getattr(args, "evaluation_method", None),
    }


def _oracle_profile_payload(
    args: argparse.Namespace,
    runtime: MatrixRuntime,
) -> Mapping[str, Any]:
    if _oracle_mode(args) == DETERMINISTIC_ORACLE:
        return {
            "profile_id": ORACLE_PROFILE,
            "implementation": "deterministic_case_oracle",
            "provider": None,
            "model": None,
            "checkpoint_or_snapshot_id": "deterministic-v1",
            "thinking": None,
            "reasoning_effort": None,
        }
    return {
        **_profile_payload(runtime.oracle),
        "implementation": "llm_presentation_of_deterministic_observation",
    }


def _oracle_provider_payload(
    args: argparse.Namespace,
    runtime: MatrixRuntime,
) -> Mapping[str, Any]:
    if _oracle_mode(args) == DETERMINISTIC_ORACLE:
        return {
            "name": "deterministic",
            "binding_id": "role_benchmark.case_oracle",
            "api": "local",
            "response_format": "structured_observation",
        }
    return _provider_payload(runtime.oracle)


def _case_pack(args: argparse.Namespace) -> CasePackDefinition:
    name = str(getattr(args, "case_pack", DEFAULT_CASE_PACK))
    try:
        return CASE_PACKS[name]
    except KeyError as exc:
        raise ValueError(
            "unknown case pack %r; choose one of %s"
            % (name, ", ".join(CASE_PACKS))
        ) from exc


def _configured_families(
    args: argparse.Namespace,
    case_pack: CasePackDefinition,
) -> Tuple[str, ...]:
    requested = getattr(args, "family", None)
    if not requested:
        return case_pack.families
    if len(set(requested)) != len(requested):
        raise ValueError("family selectors must be unique")
    unknown = set(requested) - set(case_pack.families)
    if unknown:
        raise ValueError(
            "case family %s is not registered in the %s case pack"
            % (", ".join(sorted(unknown)), case_pack.name)
        )
    requested_set = set(requested)
    return tuple(
        family for family in case_pack.families if family in requested_set
    )


def _config_payload(
    args: argparse.Namespace,
    plan: Sequence[EpisodeSpec],
) -> Mapping[str, Any]:
    case_pack = _case_pack(args)
    case_families = _configured_families(args, case_pack)
    repeats = _repeat_count(args)
    expected = build_plan(
        args.schedule_seed,
        families=case_families,
        repeats=repeats,
        case_pack=case_pack.name,
        **_design_selectors(args),
    )
    if list(plan) != expected:
        raise ValueError("plan does not match the declared design")
    runtime = _runtime_profile(args)
    fixed_designs = {
        family: {
            variant_id: evaluation_method_plan_to_payload(
                build_evaluation_method_plan(
                    specification, FIXED_EXPERIMENTAL_DESIGN
                )
            )
            for variant_id, specification in case_pack.specifications[family].items()
            if any(
                item.case_family == family and item.variant_id == variant_id
                for item in plan
            )
        }
        for family in case_families
    }
    cells_per_repeat = len(plan) // repeats
    total_episodes = len(plan)
    selected_variants = {item.variant_id for item in plan}
    selected_conditions = {item.condition_id for item in plan}
    selected_task_settings = tuple(
        value for value in TASK_SETTINGS if any(item.task_setting == value for item in plan)
    )
    selected_methods = tuple(
        value
        for value in EVALUATION_METHODS
        if any(item.evaluation_method == value for item in plan)
    )
    condition_semantics = {
        family: {
            variant_id: [
                condition_descriptor_to_payload(condition)
                for condition in conditions
                if condition.condition_id in selected_conditions
            ]
            for variant_id, conditions in case_pack.conditions[family].items()
            if variant_id in selected_variants
        }
        for family in case_families
    }
    difficulty_variants: Dict[str, Any] = {}
    source_variants = (
        _CURATED_VARIANTS
        if case_pack.name == "curated"
        else _TEMPORAL_COUNTERFACTUAL_VARIANTS
        if case_pack.name == "temporal_counterfactual"
        else {}
    )
    for family in case_families:
        if family not in source_variants:
            continue
        difficulty_variants[family] = {
            variant_id: {
                "counterfactual_fraction": variant.counterfactual_fraction,
                "fixed_design_separation": variant.fixed_design_separation,
            }
            for variant_id, variant in source_variants[family].items()
            if variant_id in selected_variants
        }
    oracle_mode = _oracle_mode(args)
    oracle_generation: Mapping[str, Any]
    if oracle_mode == DETERMINISTIC_ORACLE:
        oracle_generation = {
            "mode": DETERMINISTIC_ORACLE,
            "implementation": "case data-generating process",
            "llm_calls": 0,
        }
    else:
        oracle_generation = {
            "mode": LLM_PRESENTATION_ORACLE,
            "implementation": (
                "LLM presentation accepted only when its structured observation "
                "equals the deterministic observation"
            ),
            "temperature": 0.0,
            "top_p": 1.0,
            "seed": None,
            "max_output_tokens": args.oracle_max_output_tokens,
        }
    return {
        "schema": EXPERIMENT_SCHEMA,
        "experiment_id": _experiment_id(args),
        "created_at": _utc_now(),
        "design": {
            "player_profile": _profile_payload(runtime.player),
            "oracle_profile": _oracle_profile_payload(args, runtime),
            "evaluator_profile": _profile_payload(runtime.evaluator),
            "case_pack": case_pack.name,
            "case_families": list(case_families),
            "source_papers": {
                family: {
                    "source_paper_id": case_pack.source_paper_ids[family],
                    "source_version_id": case_pack.source_version_ids[family],
                }
                for family in case_families
                if family in case_pack.source_paper_ids
            },
            "condition_semantics": condition_semantics,
            "task_settings": list(selected_task_settings),
            "evaluation_methods": list(selected_methods),
            "repeats": repeats,
            "cells_per_repeat": cells_per_repeat,
            "total_episodes": total_episodes,
            "repeat_policy": "provider-stochastic repeats; no client seed",
            "observation_budget_policy": {
                PRIOR_ONLY_BASELINE: 0,
                FIXED_EXPERIMENTAL_DESIGN: (
                    "family-specific B from pre-defined diagnostic_conditions"
                ),
                ADAPTIVE_EXPERIMENTAL_DESIGN: (
                    "same family-specific B as fixed experimental design"
                ),
                "adaptive_early_stopping": False,
            },
            "fixed_experimental_designs": fixed_designs,
            "counterfactual_difficulty": (
                {
                    "levels": list(COUNTERFACTUAL_DIFFICULTIES),
                    "definition": (
                        "RMS symmetric tolerance-scaled separation under the fixed "
                        "experimental design; easy is more separated than hard"
                    ),
                    "variants": difficulty_variants,
                    "temporal_source_conditions_unchanged": True,
                }
                if source_variants
                else None
            ),
            "primary_outcome": {
                "name": HELD_OUT_PREDICTION_SCORE,
                "version": HELD_OUT_PREDICTION_SCORE_VERSION,
                "direction": "higher_is_better",
                "range": "[0, 1]",
                "definition": "1 / (1 + mean held-out scaled absolute error)",
                "aggregation": "equal weight per condition-readout pair",
                "scaled_error": (
                    "absolute error / (absolute tolerance + relative tolerance "
                    "* absolute target)"
                ),
                "invalid_or_missing_player_submission": 0.0,
                "infrastructure_failure": "missing; rerun and report",
            },
        },
        "schedule": {
            "policy": "seeded_randomized_repeat_blocks",
            "seed": args.schedule_seed,
            "block_sizes": [cells_per_repeat] * repeats,
            "execution_order": [spec.episode_id for spec in plan],
        },
        "providers": {
            "player": _provider_payload(runtime.player),
            "oracle": _oracle_provider_payload(args, runtime),
            "evaluator": _provider_payload(runtime.evaluator),
        },
        "player_generation": {
            "temperature": 0.0,
            "top_p": 1.0,
            "seed": None,
            "max_output_tokens": args.player_max_output_tokens,
            "max_repair_attempts": args.max_repair_attempts,
            "max_actions": args.max_actions,
        },
        "oracle_generation": oracle_generation,
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
    experiment_id: str = DEFAULT_EXPERIMENT_ID,
    oracle_mode: str = DETERMINISTIC_ORACLE,
) -> Dict[str, Any]:
    if runtime is None:
        runtime = _default_runtime()
    if oracle_mode not in ORACLE_MODES:
        raise ValueError("unsupported oracle_mode %r" % oracle_mode)
    case_pack = CASE_PACKS[spec.case_pack]
    observation_budget = build_evaluation_method_plan(
        case_pack.specifications[spec.case_family][spec.variant_id],
        spec.evaluation_method,
    ).observation_budget
    oracle_provider = (
        "deterministic"
        if oracle_mode == DETERMINISTIC_ORACLE
        else runtime.oracle.provider
    )
    oracle_model = (
        None if oracle_mode == DETERMINISTIC_ORACLE else runtime.oracle.model
    )
    oracle_snapshot = (
        "deterministic-v1"
        if oracle_mode == DETERMINISTIC_ORACLE
        else runtime.oracle.checkpoint_or_snapshot_id
    )
    return {
        "schema": EPISODE_RESULT_SCHEMA,
        "experiment_id": experiment_id,
        "schedule_index": spec.schedule_index,
        "episode_id": spec.episode_id,
        "benchmark_instance_id": spec.benchmark_instance_id,
        "case_pack": spec.case_pack,
        "dataset_kind": spec.dataset_kind,
        "case_family": spec.case_family,
        "variant_id": spec.variant_id,
        "condition_id": spec.condition_id,
        "condition_role": spec.condition_role,
        "source_condition_id": spec.source_condition_id,
        "source_paper_id": spec.source_paper_id,
        "source_version_id": spec.source_version_id,
        "task_setting": spec.task_setting,
        "evaluation_method": spec.evaluation_method,
        "observation_budget": observation_budget,
        "repeat": spec.repeat,
        "player_profile": runtime.player.profile_id,
        "player_provider": runtime.player.provider,
        "player_model": runtime.player.model,
        "player_checkpoint_or_snapshot_id": (
            runtime.player.checkpoint_or_snapshot_id
        ),
        "player_thinking": runtime.player.thinking,
        "player_reasoning_effort": runtime.player.reasoning_effort,
        "oracle_profile": runtime.oracle.profile_id,
        "oracle_mode": oracle_mode,
        "oracle_provider": oracle_provider,
        "oracle_model": oracle_model,
        "oracle_checkpoint_or_snapshot_id": oracle_snapshot,
        "oracle_thinking": (
            None
            if oracle_mode == DETERMINISTIC_ORACLE
            else runtime.oracle.thinking
        ),
        "oracle_reasoning_effort": (
            None
            if oracle_mode == DETERMINISTIC_ORACLE
            else runtime.oracle.reasoning_effort
        ),
        "evaluator_profile": runtime.evaluator.profile_id,
        "evaluator_provider": runtime.evaluator.provider,
        "evaluator_model": runtime.evaluator.model,
        "evaluator_checkpoint_or_snapshot_id": (
            runtime.evaluator.checkpoint_or_snapshot_id
        ),
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
    experiment_id: str = DEFAULT_EXPERIMENT_ID,
    oracle_mode: str = DETERMINISTIC_ORACLE,
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

    result = _base_result(
        spec,
        log_path,
        output_dir,
        runtime=runtime,
        experiment_id=experiment_id,
        oracle_mode=oracle_mode,
    )
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
    experiment_id: str = DEFAULT_EXPERIMENT_ID,
    oracle_mode: str = DETERMINISTIC_ORACLE,
) -> Mapping[str, Any]:
    result = _base_result(
        spec,
        log_path,
        output_dir,
        runtime=runtime,
        experiment_id=experiment_id,
        oracle_mode=oracle_mode,
    )
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
    """Evaluate one sealed transcript without changing its scientific outcome."""

    started_at = _utc_now()
    started_clock = time.monotonic()
    runtime = _runtime_profile(args).evaluator
    base: Dict[str, Any] = {
        "schema": LLM_EVALUATOR_RESULT_SCHEMA,
        "experiment_id": episode_result.get("experiment_id"),
        "episode_id": spec.episode_id,
        "benchmark_instance_id": spec.benchmark_instance_id,
        "run_id": episode_result.get("run_id"),
        "dataset_kind": spec.dataset_kind,
        "case_family": spec.case_family,
        "variant_id": spec.variant_id,
        "condition_id": spec.condition_id,
        "condition_role": spec.condition_role,
        "source_condition_id": spec.source_condition_id,
        "source_paper_id": spec.source_paper_id,
        "source_version_id": spec.source_version_id,
        "task_setting": spec.task_setting,
        "evaluation_method": spec.evaluation_method,
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
    "experiment_id",
    "schedule_index",
    "episode_id",
    "benchmark_instance_id",
    "case_pack",
    "dataset_kind",
    "case_family",
    "case_id",
    "variant_id",
    "condition_id",
    "condition_role",
    "source_condition_id",
    "source_paper_id",
    "source_version_id",
    "task_setting",
    "evaluation_method",
    "observation_budget",
    "repeat",
    "player_profile",
    "player_provider",
    "player_model",
    "player_checkpoint_or_snapshot_id",
    "player_reasoning_effort",
    "oracle_profile",
    "oracle_mode",
    "oracle_provider",
    "oracle_model",
    "oracle_checkpoint_or_snapshot_id",
    "oracle_reasoning_effort",
    "evaluator_profile",
    "evaluator_provider",
    "evaluator_model",
    "evaluator_checkpoint_or_snapshot_id",
    "evaluator_reasoning_effort",
    "status",
    "active_pass",
    "active_pass_category",
    "termination_kind",
    "reason_code",
    "scientifically_evaluable",
    "protocol_completion",
    "evaluation_success",
    HELD_OUT_PREDICTION_SCORE,
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
    scientific_scores = result.get("scores") or {}
    return {
        "experiment_id": result.get("experiment_id"),
        "schedule_index": result.get("schedule_index"),
        "episode_id": result["episode_id"],
        "benchmark_instance_id": result["benchmark_instance_id"],
        "case_pack": result["case_pack"],
        "dataset_kind": result["dataset_kind"],
        "case_family": result["case_family"],
        "case_id": result.get("case_id"),
        "variant_id": result["variant_id"],
        "condition_id": result["condition_id"],
        "condition_role": result["condition_role"],
        "source_condition_id": result.get("source_condition_id"),
        "source_paper_id": result.get("source_paper_id"),
        "source_version_id": result.get("source_version_id"),
        "task_setting": result["task_setting"],
        "evaluation_method": result["evaluation_method"],
        "observation_budget": result.get("observation_budget"),
        "repeat": result["repeat"],
        "player_profile": result.get("player_profile"),
        "player_provider": result.get("player_provider"),
        "player_model": result.get("player_model"),
        "player_checkpoint_or_snapshot_id": result.get(
            "player_checkpoint_or_snapshot_id"
        ),
        "player_reasoning_effort": result.get("player_reasoning_effort"),
        "oracle_profile": result.get("oracle_profile"),
        "oracle_mode": result.get("oracle_mode"),
        "oracle_provider": result.get("oracle_provider"),
        "oracle_model": result.get("oracle_model"),
        "oracle_checkpoint_or_snapshot_id": result.get(
            "oracle_checkpoint_or_snapshot_id"
        ),
        "oracle_reasoning_effort": result.get("oracle_reasoning_effort"),
        "evaluator_profile": result.get("evaluator_profile"),
        "evaluator_provider": result.get("evaluator_provider"),
        "evaluator_model": result.get("evaluator_model"),
        "evaluator_checkpoint_or_snapshot_id": result.get(
            "evaluator_checkpoint_or_snapshot_id"
        ),
        "evaluator_reasoning_effort": result.get("evaluator_reasoning_effort"),
        "status": result["status"],
        "active_pass": result.get("active_pass"),
        "active_pass_category": result.get("active_pass_category"),
        "termination_kind": result.get("termination_kind"),
        "reason_code": result.get("reason_code"),
        "scientifically_evaluable": result.get("scientifically_evaluable"),
        "protocol_completion": result.get("protocol_completion"),
        "evaluation_success": result.get("evaluation_success"),
        HELD_OUT_PREDICTION_SCORE: scientific_scores.get(
            HELD_OUT_PREDICTION_SCORE
        ),
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
            scientific_scores, ensure_ascii=False, sort_keys=True
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
            "experiment_id": json.loads(
                (output_dir / "config.json").read_text(encoding="utf-8")
            )["experiment_id"],
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
    case_factory: Optional[Callable[[str, str, BenchmarkTrack], Any]] = None,
) -> Any:
    pack = CASE_PACKS[spec.case_pack]
    runtime_condition_id = spec.condition_id
    if spec.case_pack == "temporal":
        runtime_condition_id = TEMPORAL_SOURCE_CONDITION_RUNTIME_MAP[
            spec.case_family
        ][spec.condition_id]
    task_setting = BenchmarkTrack(spec.task_setting)
    if case_factory is not None:
        return case_factory(spec.case_family, runtime_condition_id, task_setting)
    return make_matched_case(
        pack.specifications[spec.case_family][spec.variant_id],
        runtime_condition_id,
        task_setting,
    )


def _prepare_case(
    spec: EpisodeSpec,
    case_factory: Optional[Callable[[str, str, BenchmarkTrack], Any]] = None,
) -> Any:
    case = _make_case(spec, case_factory)
    family_spec = CASE_PACKS[spec.case_pack].specifications[
        spec.case_family
    ][spec.variant_id]
    return prepare_evaluation_case(
        case,
        family_spec,
        spec.evaluation_method,
    )


def _run_one_episode(
    args: argparse.Namespace,
    *,
    player_backend: TextGenerationBackend,
    oracle_backend: Optional[TextGenerationBackend],
    output_dir: Path,
    spec: EpisodeSpec,
    log_path: Path,
    case_factory: Optional[Callable[[str, str, BenchmarkTrack], Any]] = None,
) -> Mapping[str, Any]:
    started_at = _utc_now()
    started_clock = time.monotonic()
    runtime = _runtime_profile(args)
    oracle_mode = _oracle_mode(args)
    try:
        if oracle_mode == DETERMINISTIC_ORACLE and oracle_backend is not None:
            raise ValueError("deterministic oracle mode does not use an LLM backend")
        if oracle_mode == LLM_PRESENTATION_ORACLE and oracle_backend is None:
            raise ValueError("llm_presentation oracle mode requires an LLM backend")
        prepared = _prepare_case(spec, case_factory)
        method_plan = evaluation_method_plan_to_payload(prepared.plan)
        fixed_observations = [
            fixed_observation_to_payload(observation)
            for observation in prepared.fixed_observations
        ]
        run = run_llm_episode(
            player_backend,
            prepared.case,
            str(log_path),
            config=GenerationConfig(
                max_output_tokens=args.player_max_output_tokens,
                temperature=0.0,
                top_p=1.0,
                seed=None,
            ),
            oracle_backend=oracle_backend,
            oracle_config=(
                GenerationConfig(
                    max_output_tokens=args.oracle_max_output_tokens,
                    temperature=0.0,
                    top_p=1.0,
                    seed=None,
                )
                if oracle_backend is not None
                else None
            ),
            max_repair_attempts=args.max_repair_attempts,
            max_actions=args.max_actions,
            run_id=spec.episode_id,
            observation_budget=prepared.plan.observation_budget,
            initial_attempts_used=prepared.initial_attempts_used,
            require_budget_exhaustion=True,
            run_metadata={
                "experiment_schema": EXPERIMENT_SCHEMA,
                "experiment_id": _experiment_id(args),
                "episode_id": spec.episode_id,
                "benchmark_instance_id": spec.benchmark_instance_id,
                "case_pack": spec.case_pack,
                "dataset_kind": spec.dataset_kind,
                "case_family": spec.case_family,
                "variant_id": spec.variant_id,
                "condition_id": spec.condition_id,
                "condition_role": spec.condition_role,
                "source_condition_id": spec.source_condition_id,
                "source_paper_id": spec.source_paper_id,
                "source_version_id": spec.source_version_id,
                "task_setting": spec.task_setting,
                "evaluation_method": spec.evaluation_method,
                "evaluation_method_plan": method_plan,
                "fixed_observations": fixed_observations,
                "repeat": spec.repeat,
                "schedule_index": spec.schedule_index,
                "schedule_seed": args.schedule_seed,
                "schedule_policy": "seeded_randomized_repeat_blocks",
                "player_profile": runtime.player.profile_id,
                "player_provider": runtime.player.provider,
                "player_model": runtime.player.model,
                "player_checkpoint_or_snapshot_id": (
                    runtime.player.checkpoint_or_snapshot_id
                ),
                "player_binding_id": runtime.player.binding_id,
                "player_reasoning_effort": runtime.player.reasoning_effort,
                "oracle_profile": runtime.oracle.profile_id,
                "oracle_mode": oracle_mode,
                "oracle_provider": (
                    "deterministic"
                    if oracle_mode == DETERMINISTIC_ORACLE
                    else runtime.oracle.provider
                ),
                "oracle_model": (
                    None
                    if oracle_mode == DETERMINISTIC_ORACLE
                    else runtime.oracle.model
                ),
                "oracle_checkpoint_or_snapshot_id": (
                    "deterministic-v1"
                    if oracle_mode == DETERMINISTIC_ORACLE
                    else runtime.oracle.checkpoint_or_snapshot_id
                ),
                "oracle_binding_id": (
                    "role_benchmark.case_oracle"
                    if oracle_mode == DETERMINISTIC_ORACLE
                    else runtime.oracle.binding_id
                ),
                "oracle_reasoning_effort": (
                    None
                    if oracle_mode == DETERMINISTIC_ORACLE
                    else runtime.oracle.reasoning_effort
                ),
                "evaluator_profile": runtime.evaluator.profile_id,
                "evaluator_provider": runtime.evaluator.provider,
                "evaluator_model": runtime.evaluator.model,
                "evaluator_checkpoint_or_snapshot_id": (
                    runtime.evaluator.checkpoint_or_snapshot_id
                ),
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
            experiment_id=_experiment_id(args),
            oracle_mode=oracle_mode,
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
            experiment_id=_experiment_id(args),
            oracle_mode=oracle_mode,
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
    case_pack = _case_pack(args)
    case_families = _configured_families(args, case_pack)
    repeat_count = _repeat_count(args)
    if args.repeat is not None and any(
        isinstance(value, bool)
        or not isinstance(value, int)
        or value < 1
        or value > repeat_count
        for value in args.repeat
    ):
        raise ValueError("repeat selectors must be within the configured repeats")
    full_plan = build_plan(
        args.schedule_seed,
        families=case_families,
        repeats=repeat_count,
        case_pack=case_pack.name,
        **_design_selectors(args),
    )
    total_episodes = len(full_plan)
    selected = select_plan(
        full_plan,
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
        _prepare_case(
            next(spec for spec in selected_pending if spec.cell == cell),
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
        player_backend = load_role_backend(
            args,
            "player",
            api_key=_key_for_backend(
                args, "player", player_api_key, player_backend_loader
            ),
            loader=player_backend_loader,
        )
        evaluator_backend = load_role_backend(
            args,
            "evaluator",
            api_key=_key_for_backend(
                args, "evaluator", evaluator_api_key, evaluator_backend_loader
            ),
            loader=evaluator_backend_loader,
        )
        oracle_backend = None
        if _oracle_mode(args) == LLM_PRESENTATION_ORACLE:
            oracle_backend = load_role_backend(
                args,
                "oracle",
                api_key=_key_for_backend(
                    args, "oracle", oracle_api_key, oracle_backend_loader
                ),
                loader=oracle_backend_loader,
            )
        active_backends = [player_backend, evaluator_backend]
        if oracle_backend is not None:
            active_backends.append(oracle_backend)
        if len({id(backend) for backend in active_backends}) != len(active_backends):
            raise ValueError("LLM roles must use distinct backend instances")
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
        if player_backend is None or evaluator_backend is None:
            raise AssertionError("active execution requires Player and Evaluator backends")
        if (
            _oracle_mode(args) == LLM_PRESENTATION_ORACLE
            and oracle_backend is None
        ):
            raise AssertionError("LLM presentation requires an Oracle backend")
        for spec, log_path in pending:
            result = _run_one_episode(
                args,
                player_backend=player_backend,
                oracle_backend=oracle_backend,
                output_dir=output_dir,
                spec=spec,
                log_path=log_path,
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
        "--%s-snapshot-id" % role,
        help=(
            "immutable checkpoint or snapshot ID; use 'unknown' when the "
            "provider does not disclose one"
        ),
    )
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
            "interfaces across one registered scientific case pack."
        )
    )
    parser.add_argument("--output-dir", required=True)
    parser.add_argument(
        "--experiment-id",
        default=DEFAULT_EXPERIMENT_ID,
        help="registered experiment identifier",
    )
    parser.add_argument(
        "--case-pack",
        choices=tuple(CASE_PACKS),
        default=DEFAULT_CASE_PACK,
        help="registered case collection; temporal cases remain separate from curated",
    )
    for role in ROLES:
        _add_role_arguments(parser, role)
    parser.add_argument(
        "--oracle-mode",
        choices=ORACLE_MODES,
        default=DETERMINISTIC_ORACLE,
        help=(
            "deterministic returns the authoritative structured observation; "
            "llm_presentation uses an LLM but accepts only an exactly matching "
            "structured observation"
        ),
    )
    parser.add_argument(
        "--family",
        action="append",
        choices=CASE_FAMILIES + TEMPORAL_CASE_FAMILIES,
        help="include a registered family in the experiment design",
    )
    parser.add_argument(
        "--variant",
        action="append",
        choices=COUNTERFACTUAL_DIFFICULTIES + ("source_reported_v1",),
        help="include a registered variant in the experiment design",
    )
    parser.add_argument(
        "--condition",
        action="append",
        choices=CONDITIONS + ("condition_a", "condition_b"),
        help="include a condition ID in the experiment design",
    )
    parser.add_argument(
        "--task-setting",
        action="append",
        choices=TASK_SETTINGS,
        help="include a task setting in the experiment design",
    )
    parser.add_argument(
        "--evaluation-method",
        action="append",
        choices=EVALUATION_METHODS,
        help="include an evaluation method in the experiment design",
    )
    parser.add_argument(
        "--repeats",
        type=int,
        default=MATCHED_REPEATS,
        help="number of complete randomized repeat blocks",
    )
    parser.add_argument(
        "--repeat",
        action="append",
        type=int,
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
    case_pack = _case_pack(args)
    build_plan(
        args.schedule_seed,
        families=_configured_families(args, case_pack),
        repeats=_repeat_count(args),
        case_pack=case_pack.name,
        **_design_selectors(args),
    )
    run_matrix(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
