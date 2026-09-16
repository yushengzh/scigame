"""Run the cross-case/method matrix with independent role backends.

The frozen plan crosses every selected case cell with prior-only baseline,
fixed experimental design, and adaptive experimental design.  It exposes
Player, Oracle, and post-hoc Evaluator interfaces.  The primary Oracle is the
deterministic case implementation; an independently configured LLM may instead
present the same structured observation.  The Evaluator runs only after the
Player--Oracle log is sealed and never changes deterministic scientific scores.

Episodes are randomized within complete repeat blocks for the selected case
pack. Episodes may execute concurrently, while every Player--Oracle dialogue
remains sequential inside its episode and the post-hoc Evaluator starts only
after that episode's active result has been sealed and persisted. Completion
order never changes the frozen schedule used for summaries and analysis.

Runtime credentials are passed separately in memory and are never copied into
configs, logs, result sidecars, summaries, or provider metadata.
"""

from __future__ import annotations

import argparse
import csv
import datetime as _datetime
import getpass
import json
import math
import os
import random
import re
import sys
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple
from urllib.parse import quote
from role_benchmark.llm import PLAYER_PROMPT_VERSION_V5_PERFORMANCE, STRUCTURED_PLAYER_PROMPTS, MAX_LLM_ACTION_BYTES
from role_benchmark.performance import PERFORMANCE_PROTOCOL, formula_metric, discovery_reference_context
from role_benchmark.discovery_evaluation import DISCOVERY_PROMPT_VERSION
from role_benchmark.postevaluation import science_postevaluation, aggregate_scientific_postevaluation
from role_benchmark.semantic_oracle import ORACLE_PROMPT_VERSION_V3_SEMANTIC

from role_benchmark import (
    ADAPTIVE_EXPERIMENTAL_DESIGN,
    BenchmarkTrack,
    ConditionDescriptor,
    ConditionRole,
    DatasetKind,
    DEFAULT_EVALUATOR_PROMPT_VERSION,
    DEFAULT_ORACLE_PROMPT_VERSION,
    DEFAULT_PLAYER_PROMPT_VERSION,
    EVALUATION_METHODS,
    FIXED_EXPERIMENTAL_DESIGN,
    FinalSubmission,
    GenerationConfig,
    HELD_OUT_PREDICTION_SCORE,
    HELD_OUT_PREDICTION_SCORE_VERSION,
    LLMEvaluatorCallError,
    ORACLE_PROMPT_VERSION_V1,
    ORACLE_PROMPT_VERSION_V2_JSON_HARDENED,
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
from role_benchmark.temporal_cases import (
    TEMPORAL_CASE_FAMILIES as LEGACY_TEMPORAL_CASE_FAMILIES,
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
from role_benchmark.wire import DEFAULT_MAX_ACTION_BYTES, final_submission_to_payload

from experiments.core160_pack import load_accepted_temporal_pack
from experiments.gemini_generate_content import GeminiGenerateContentBackend
from experiments.ifm_chat_completions import (
    DEFAULT_IFM_CHAT_COMPLETIONS_ENDPOINT,
    DEFAULT_IFM_MODEL,
    DEFAULT_IFM_PLATFORM_ENDPOINT,
    DEFAULT_IFM_PLATFORM_MODEL,
    IFMChatCompletionsBackend,
    IFM_REASONING_EFFORTS,
    IFM_PLATFORM_REASONING_EFFORTS,
    RequestStartGate,
)
from experiments.run_pendulum_matrix import DeepSeekChatBackend
from experiments.openai_responses import OpenAIResponsesBackend


EXPERIMENT_SCHEMA = "role_benchmark.case_matrix.v2"
EPISODE_RESULT_SCHEMA = "role_benchmark.case_matrix_episode.v2"
LLM_EVALUATOR_RESULT_SCHEMA = "role_benchmark.case_matrix_llm_evaluation.v2"
DEFAULT_PROVIDER = "deepseek"
DEEPSEEK_ENDPOINT = "https://api.deepseek.com/chat/completions"
OPENAI_ENDPOINT = "https://api.openai.com/v1/responses"
GEMINI_ENDPOINT_TEMPLATE = (
    "https://generativelanguage.googleapis.com/v1beta/models/"
    "{model}:generateContent"
)
DEEPSEEK_API_KEY_ENV = "DEEPSEEK_API_KEY"
OPENAI_API_KEY_ENV = "OPENAI_API_KEY"
GEMINI_API_KEY_ENV = "GEMINI_API_KEY"
IFM_API_KEY_ENV = "IFM_API_KEY"

DEFAULT_SCHEDULE_SEED = 20260825
DEFAULT_EXPERIMENT_ID = "development"
HISTORICAL_CASE_PACK = "historical"
TEMPORAL_CASE_PACK = "temporal"
BOTH_CASE_PACK = "both"

PLAYER_PROFILE = "player"
PLAYER_MODEL = "deepseek-v4-flash"
ORACLE_PROFILE = "oracle"
ORACLE_MODEL = "deepseek-v4-flash"
EVALUATOR_PROFILE = "evaluator"
EVALUATOR_MODEL = "deepseek-v4-flash"
THINKING = "disabled"
OPENAI_MODEL = "gpt-5.6"
OPENAI_REASONING_EFFORT = "none"
GEMINI_MODEL = "gemini-2.5-flash"
ROLES: Tuple[str, ...] = ("player", "oracle", "evaluator")
ROLE_PROMPT_VERSIONS: Mapping[str, Tuple[str, ...]] = {
    "player": (PLAYER_PROMPT_VERSION_V5_PERFORMANCE,),
    "oracle": (
        ORACLE_PROMPT_VERSION_V1,
        ORACLE_PROMPT_VERSION_V2_JSON_HARDENED,
        ORACLE_PROMPT_VERSION_V3_SEMANTIC,
    ),
    "evaluator": (DISCOVERY_PROMPT_VERSION,),
}
DEFAULT_ROLE_PROMPT_VERSIONS: Mapping[str, str] = {
    "player": PLAYER_PROMPT_VERSION_V5_PERFORMANCE,
    "oracle": DEFAULT_ORACLE_PROMPT_VERSION,
    "evaluator": DISCOVERY_PROMPT_VERSION,
}

DETERMINISTIC_ORACLE = "deterministic"
LLM_PRESENTATION_ORACLE = "llm_presentation"
LLM_SEMANTIC_ORACLE = "llm_semantic"
ORACLE_MODES: Tuple[str, ...] = (
    DETERMINISTIC_ORACLE,
    LLM_PRESENTATION_ORACLE,
    LLM_SEMANTIC_ORACLE,
)

HISTORICAL_CASE_FAMILIES: Tuple[str, ...] = CASE_FAMILIES
HISTORICAL_CONDITION_IDS: Tuple[str, ...] = ("historical", "counterfactual")
TASK_SETTINGS: Tuple[str, ...] = (
    BenchmarkTrack.IDENTIFICATION.value,
    BenchmarkTrack.DISCOVERY.value,
)
MATCHED_REPEATS = 5


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
    ifm_api_mode: Optional[str] = None


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


def _player_action_bytes(args):
    value = getattr(args, "player_max_action_bytes", None)
    if value is None:
        return DEFAULT_MAX_ACTION_BYTES
    if type(value) is not int or not 1 <= value <= MAX_LLM_ACTION_BYTES:
        raise ValueError("player_max_action_bytes must be in [1, %d]" % MAX_LLM_ACTION_BYTES)
    return value


def _prompt_version(args: argparse.Namespace, role: str) -> str:
    if role not in ROLES:
        raise ValueError("unsupported role %r" % role)
    value = _role_value(args, role, "prompt_version")
    if role == "oracle":
        if _oracle_mode(args) == LLM_SEMANTIC_ORACLE:
            if value not in (None, DEFAULT_ORACLE_PROMPT_VERSION, ORACLE_PROMPT_VERSION_V3_SEMANTIC):
                raise ValueError("semantic Oracle requires the v3 semantic prompt")
            return ORACLE_PROMPT_VERSION_V3_SEMANTIC
        if value == ORACLE_PROMPT_VERSION_V3_SEMANTIC:
            raise ValueError("semantic Oracle prompt requires --oracle-mode llm_semantic")
    if role in {"player", "evaluator"}:
        expected = DEFAULT_ROLE_PROMPT_VERSIONS[role]
        if value not in (None, expected):
            raise ValueError("the benchmark uses the current scientific Player and Evaluator prompts")
        return expected
    if value is None:
        value = DEFAULT_ROLE_PROMPT_VERSIONS[role]
    if value not in ROLE_PROMPT_VERSIONS[role]:
        raise ValueError("unsupported %s prompt version %r" % (role, value))
    return str(value)


def _role_runtime(args: argparse.Namespace, role: str) -> RoleRuntime:
    if role not in ROLES:
        raise ValueError("unsupported role %r" % role)
    provider = str(_role_value(args, role, "provider") or ("openai" if role == "player" else DEFAULT_PROVIDER))
    ifm_api_mode = _role_value(args, role, "ifm_api_mode")
    if ifm_api_mode is not None and provider != "ifm":
        raise ValueError("--%s-ifm-api-mode is only defined for IFM" % role)
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
            response_format=("responses_json_schema_strict"
                if role != "player" or _prompt_version(args, role) in STRUCTURED_PLAYER_PROMPTS
                else "json_object_with_app_schema"),
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
    if provider == "gemini":
        if thinking_override is not None:
            raise ValueError("--%s-thinking is only defined for DeepSeek" % role)
        if effort_override not in (None, "none"):
            raise ValueError(
                "--%s-reasoning-effort is not supported for Gemini" % role
            )
        model = model_override or GEMINI_MODEL
        return RoleRuntime(
            role=role,
            profile_id=profile_id,
            provider="gemini",
            endpoint=(
                endpoint_override
                or GEMINI_ENDPOINT_TEMPLATE.format(model=quote(model, safe=""))
            ),
            api="generate_content",
            response_format="application/json",
            binding_id=GeminiGenerateContentBackend.binding_id,
            api_key_env=(
                _role_value(args, role, "api_key_env") or GEMINI_API_KEY_ENV
            ),
            model=model,
            checkpoint_or_snapshot_id=snapshot_override or "unknown",
            thinking=None,
            reasoning_effort=None,
            timeout_s=float(timeout_s),
        )
    if provider == "ifm":
        if thinking_override is not None:
            raise ValueError("--%s-thinking is only defined for DeepSeek" % role)
        effort = effort_override or "medium"
        if effort not in IFM_REASONING_EFFORTS:
            raise ValueError(
                "--%s-reasoning-effort for IFM must be %s"
                % (role, ", ".join(IFM_REASONING_EFFORTS))
            )
        api_mode = ifm_api_mode or "ifm_platform"
        if api_mode not in ("ifm_platform", "core42"):
            raise ValueError("--%s-ifm-api-mode must be ifm_platform or core42" % role)
        if api_mode == "ifm_platform" and effort not in IFM_PLATFORM_REASONING_EFFORTS:
            raise ValueError("IFM Platform reasoning effort must be low, medium, or high")
        native_schema = (api_mode == "ifm_platform" and
            (role != "player" or _prompt_version(args, role) in STRUCTURED_PLAYER_PROMPTS))
        if role == "player" and _prompt_version(args, role) in STRUCTURED_PLAYER_PROMPTS and api_mode != "ifm_platform":
            raise ValueError("structured Player requires IFM Platform native schema output")
        default_endpoint, ifm_model = (
            (DEFAULT_IFM_PLATFORM_ENDPOINT, DEFAULT_IFM_PLATFORM_MODEL)
            if api_mode == "ifm_platform"
            else (DEFAULT_IFM_CHAT_COMPLETIONS_ENDPOINT, DEFAULT_IFM_MODEL)
        )
        return RoleRuntime(
            role=role,
            profile_id=profile_id,
            provider="ifm",
            endpoint=endpoint_override or default_endpoint,
            api="chat_completions",
            response_format=(
                "native_json_schema_local_validation" if native_schema
                else "prompt_json_local_validation"
            ),
            binding_id=IFMChatCompletionsBackend.binding_id,
            api_key_env=(
                _role_value(args, role, "api_key_env") or IFM_API_KEY_ENV
            ),
            model=model_override or ifm_model,
            checkpoint_or_snapshot_id=snapshot_override or "unknown",
            thinking=None,
            reasoning_effort=effort,
            timeout_s=float(timeout_s),
            ifm_api_mode=api_mode,
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
    runtime_condition_ids: Mapping[str, Mapping[str, str]] = field(
        default_factory=dict
    )
    release_metadata: Mapping[str, Any] = field(default_factory=dict)


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


_ACCEPTED_TEMPORAL_PACK = load_accepted_temporal_pack()
ACCEPTED_TEMPORAL_CASE_FAMILIES: Tuple[str, ...] = (
    _ACCEPTED_TEMPORAL_PACK.family_ids
)
TEMPORAL_CASE_FAMILIES: Tuple[str, ...] = (
    LEGACY_TEMPORAL_CASE_FAMILIES + ACCEPTED_TEMPORAL_CASE_FAMILIES
)
if len(set(TEMPORAL_CASE_FAMILIES)) != len(TEMPORAL_CASE_FAMILIES):
    raise ValueError(
        "legacy and accepted Temporal releases contain duplicate families"
    )
BOTH_CASE_FAMILIES: Tuple[str, ...] = (
    HISTORICAL_CASE_FAMILIES + TEMPORAL_CASE_FAMILIES
)
if len(set(BOTH_CASE_FAMILIES)) != len(BOTH_CASE_FAMILIES):
    raise ValueError(
        "Historical and Temporal releases contain duplicate families"
    )


def _merge_unique_temporal_identities(
    label: str,
    legacy: Mapping[str, str],
    accepted: Mapping[str, str],
    *,
    normalize: Optional[Callable[[str], str]] = None,
) -> Mapping[str, str]:
    """Merge complete family identities while rejecting reused source data."""

    merged = {**legacy, **accepted}
    if set(merged) != set(TEMPORAL_CASE_FAMILIES):
        raise ValueError("Temporal %s must cover every family exactly once" % label)
    identities = tuple(merged.values())
    if normalize is not None:
        identities = tuple(normalize(value) for value in identities)
    if len(set(identities)) != len(TEMPORAL_CASE_FAMILIES):
        raise ValueError("Temporal %s values must be unique" % label)
    return merged


_TEMPORAL_SOURCE_PAPER_IDS = _merge_unique_temporal_identities(
    "source_paper_id",
    TEMPORAL_SOURCE_PAPER_IDS,
    _ACCEPTED_TEMPORAL_PACK.source_paper_ids,
)


def _arxiv_base_id(versioned_id: str) -> str:
    """Normalize an arXiv identity so different versions still collide."""

    return re.sub(r"v[0-9]+$", "", versioned_id)


_TEMPORAL_SOURCE_VERSION_IDS = _merge_unique_temporal_identities(
    "source_version_id",
    TEMPORAL_SOURCE_VERSION_IDS,
    _ACCEPTED_TEMPORAL_PACK.source_version_ids,
    normalize=_arxiv_base_id,
)


_HISTORICAL_PACK = CasePackDefinition(
    name=HISTORICAL_CASE_PACK,
    families=HISTORICAL_CASE_FAMILIES,
    specifications={
        family: {"canonical": CASE_SPECS[family]}
        for family in HISTORICAL_CASE_FAMILIES
    },
    conditions={
        family: {
            "canonical": _historical_counterfactual_conditions(
                family,
                "canonical",
            )
        }
        for family in HISTORICAL_CASE_FAMILIES
    },
    source_paper_ids={},
    source_version_ids={},
)
_TEMPORAL_PACK = CasePackDefinition(
    name=TEMPORAL_CASE_PACK,
    families=TEMPORAL_CASE_FAMILIES,
    specifications={
        **{
            family: {"source_reported_v1": TEMPORAL_CASE_SPECS[family]}
            for family in LEGACY_TEMPORAL_CASE_FAMILIES
        },
        **_ACCEPTED_TEMPORAL_PACK.specifications,
    },
    conditions={
        **{
            family: {"source_reported_v1": TEMPORAL_SOURCE_CONDITIONS[family]}
            for family in LEGACY_TEMPORAL_CASE_FAMILIES
        },
        **_ACCEPTED_TEMPORAL_PACK.conditions,
    },
    source_paper_ids=_TEMPORAL_SOURCE_PAPER_IDS,
    source_version_ids=_TEMPORAL_SOURCE_VERSION_IDS,
    runtime_condition_ids={
        **TEMPORAL_SOURCE_CONDITION_RUNTIME_MAP,
        **_ACCEPTED_TEMPORAL_PACK.runtime_truth_keys,
    },
)


def _combine_case_packs(
    name: str,
    first: CasePackDefinition,
    second: CasePackDefinition,
) -> CasePackDefinition:
    """Combine two disjoint registered releases without count assumptions."""

    families = first.families + second.families
    if len(set(families)) != len(families):
        raise ValueError("%s contains duplicate family IDs" % name)
    return CasePackDefinition(
        name=name,
        families=families,
        specifications={**first.specifications, **second.specifications},
        conditions={**first.conditions, **second.conditions},
        source_paper_ids={**first.source_paper_ids, **second.source_paper_ids},
        source_version_ids={
            **first.source_version_ids,
            **second.source_version_ids,
        },
        runtime_condition_ids={
            **first.runtime_condition_ids,
            **second.runtime_condition_ids,
        },
    )


CASE_PACKS: Mapping[str, CasePackDefinition] = {
    HISTORICAL_CASE_PACK: _HISTORICAL_PACK,
    TEMPORAL_CASE_PACK: _TEMPORAL_PACK,
    BOTH_CASE_PACK: _combine_case_packs(
        BOTH_CASE_PACK,
        _HISTORICAL_PACK,
        _TEMPORAL_PACK,
    ),
}

def _historical_dataset_metadata() -> Mapping[str, Any]:
    """Record the selected dataset identity without a separate metric release."""
    path = Path(__file__).resolve().parents[1] / "datasets/historical/manifest.json"
    metadata = json.loads(path.read_text(encoding="utf-8"))
    return {key: metadata[key] for key in ("dataset_id", "status", "family_count", "case_count") if key in metadata}


CASE_PACK_FAMILY_CHOICES: Tuple[str, ...] = tuple(
    dict.fromkeys(
        family
        for case_pack in CASE_PACKS.values()
        for family in case_pack.families
    )
)
CASE_PACK_VARIANT_CHOICES: Tuple[str, ...] = tuple(
    dict.fromkeys(
        variant_id
        for case_pack in CASE_PACKS.values()
        for family in case_pack.families
        for variant_id in case_pack.conditions[family]
    )
)
CASE_PACK_CONDITION_CHOICES: Tuple[str, ...] = tuple(
    dict.fromkeys(
        condition.condition_id
        for case_pack in CASE_PACKS.values()
        for family in case_pack.families
        for conditions in case_pack.conditions[family].values()
        for condition in conditions
    )
)


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
    families: Optional[Sequence[str]] = None,
    repeats: int = MATCHED_REPEATS,
    case_pack: str = HISTORICAL_CASE_PACK,
    variants: Optional[Sequence[str]] = None,
    conditions: Optional[Sequence[str]] = None,
    task_settings: Optional[Sequence[str]] = None,
    evaluation_methods: Optional[Sequence[str]] = None,
) -> List[EpisodeSpec]:
    """Build deterministic randomized blocks over a complete case pack."""

    if isinstance(schedule_seed, bool) or not isinstance(schedule_seed, int):
        raise ValueError("schedule_seed must be an integer")
    try:
        pack = CASE_PACKS[case_pack]
    except KeyError as exc:
        raise ValueError("unknown case pack %r" % case_pack) from exc
    family_tuple = tuple(pack.families if families is None else families)
    if not family_tuple or len(set(family_tuple)) != len(family_tuple):
        raise ValueError("families must be a non-empty sequence of unique names")
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


class ConcurrencyLimitedBackend:
    """Apply one role-local, thread-safe limit to provider generation calls."""

    def __init__(
        self,
        backend: TextGenerationBackend,
        *,
        role: str,
        concurrency_limit: int,
    ) -> None:
        if role not in ROLES:
            raise ValueError("unsupported role %r" % role)
        if (
            isinstance(concurrency_limit, bool)
            or not isinstance(concurrency_limit, int)
            or concurrency_limit < 1
        ):
            raise ValueError("concurrency_limit must be a positive integer")
        if not callable(getattr(backend, "generate", None)):
            raise ValueError("backend must provide a callable generate method")
        self._backend = backend
        self._role = role
        self._concurrency_limit = concurrency_limit
        self._semaphore = threading.BoundedSemaphore(concurrency_limit)

    @property
    def role(self) -> str:
        return self._role

    @property
    def concurrency_limit(self) -> int:
        return self._concurrency_limit

    @property
    def supports_strict_action_schema(self) -> bool:
        return getattr(self._backend, "supports_strict_action_schema", False) is True

    def generate(self, request: Any) -> Any:
        with self._semaphore:
            return self._backend.generate(request)


def _build_backend(runtime: RoleRuntime, api_key: str, *, ifm_options=None) -> TextGenerationBackend:
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
    if runtime.provider == "gemini":
        return GeminiGenerateContentBackend(
            endpoint=runtime.endpoint,
            api_key=api_key,
            model=runtime.model,
            timeout_seconds=runtime.timeout_s,
        )
    if runtime.provider == "ifm":
        return IFMChatCompletionsBackend(
            endpoint=runtime.endpoint,
            api_key=api_key,
            model=runtime.model,
            reasoning_effort=runtime.reasoning_effort or "medium",
            timeout_s=runtime.timeout_s,
            api_mode=runtime.ifm_api_mode or "ifm_platform",
            native_structured_output=(
                runtime.response_format == "native_json_schema_local_validation"
            ),
            **(ifm_options or {}),
        )
    raise ValueError("unsupported provider %r" % runtime.provider)


def load_role_backend(
    args: argparse.Namespace,
    role: str,
    *,
    api_key: Optional[str] = None,
    loader: Optional[BackendLoader] = None,
    ifm_request_gate=None,
) -> TextGenerationBackend:
    """Load exactly one role without touching either of the other clients."""

    runtime = _runtime_profile(args).for_role(role)
    if loader is not None:
        backend = loader()
    else:
        if not isinstance(api_key, str) or not api_key.strip():
            raise ValueError("%s api_key must be non-empty" % role)
        settings = _ifm_transport_settings(args)
        backend = _build_backend(runtime, api_key, ifm_options={
            "stream": settings["stream"], "request_gate": ifm_request_gate,
            "max_rate_limit_retries": settings["max_rate_limit_retries"],
            "context_window_tokens": settings["context_window_tokens"],
        })
    if not callable(getattr(backend, "generate", None)):
        raise ValueError(
            "%s backend must provide a callable generate method"
            % role.capitalize()
        )
    if role == "player" and _prompt_version(args, role) in STRUCTURED_PLAYER_PROMPTS:
        if getattr(backend, "supports_strict_action_schema", False) is not True:
            raise ValueError("the selected Player protocol requires a backend with native recursive JSON Schema support")
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
    payload = {
        "profile_id": runtime.profile_id,
        "provider": runtime.provider,
        "model": runtime.model,
        "checkpoint_or_snapshot_id": runtime.checkpoint_or_snapshot_id,
        "thinking": runtime.thinking,
        "reasoning_effort": runtime.reasoning_effort,
    }
    return payload


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
    if runtime.provider == "ifm":
        payload["api_mode"] = runtime.ifm_api_mode or "ifm_platform"
    return payload


def _oracle_mode(args: argparse.Namespace) -> str:
    mode = str(getattr(args, "oracle_mode", DETERMINISTIC_ORACLE))
    if mode not in ORACLE_MODES:
        raise ValueError(
            "unknown oracle mode %r; choose one of %s"
            % (mode, ", ".join(ORACLE_MODES))
        )
    return mode


def _worker_count(args: argparse.Namespace) -> int:
    value = getattr(args, "workers", 1)
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError("workers must be a positive integer")
    return value


def _role_concurrency_limits(args: argparse.Namespace) -> Mapping[str, int]:
    """Return effective provider-call limits for this process.

    A deterministic Oracle has no provider calls, so its effective limit is
    recorded as zero even when an Oracle limit is supplied for a reusable CLI
    invocation.
    """

    workers = _worker_count(args)
    limits: Dict[str, int] = {}
    for role in ROLES:
        configured = getattr(args, "%s_concurrency" % role, None)
        if configured is None:
            configured = workers
        if (
            isinstance(configured, bool)
            or not isinstance(configured, int)
            or configured < 1
        ):
            raise ValueError("%s_concurrency must be a positive integer" % role)
        limits[role] = min(workers, configured)
    if _oracle_mode(args) == DETERMINISTIC_ORACLE:
        limits["oracle"] = 0
    return limits


def _parallel_config_requested(args: argparse.Namespace) -> bool:
    return _worker_count(args) > 1 or any(
        getattr(args, "%s_concurrency" % role, None) is not None
        for role in ROLES
    )


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
    payload = {
        "variants": getattr(args, "variant", None),
        "conditions": getattr(args, "condition", None),
        "task_settings": getattr(args, "task_setting", None),
        "evaluation_methods": getattr(args, "evaluation_method", None),
    }
    return payload


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
        "implementation": ("llm_semantic_validation_with_deterministic_observation"
            if _oracle_mode(args) == LLM_SEMANTIC_ORACLE
            else "llm_presentation_of_deterministic_observation"),
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
    value = getattr(args, "case_pack", None)
    if value is None:
        raise ValueError("case_pack is required")
    name = str(value)
    try:
        pack = CASE_PACKS[name]
    except KeyError as exc:
        raise ValueError(
            "unknown case pack %r; choose one of %s"
            % (name, ", ".join(CASE_PACKS))
        ) from exc
    if pack.name in (HISTORICAL_CASE_PACK, BOTH_CASE_PACK):
        historical = dict(_historical_dataset_metadata())
        pack = replace(pack, release_metadata=(historical if pack.name == HISTORICAL_CASE_PACK
                                               else {"historical": historical}))
    return pack


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


def _ifm_transport_settings(args):
    interval = getattr(args, "ifm_request_interval", None)
    retries = getattr(args, "ifm_rate_limit_retries", 0)
    context = getattr(args, "ifm_context_window_tokens", None)
    if interval is not None and (isinstance(interval, bool) or not isinstance(interval, (int, float))
                                or not math.isfinite(interval) or interval <= 0):
        raise ValueError("ifm_request_interval must be finite and positive")
    if type(retries) is not int or retries < 0:
        raise ValueError("ifm_rate_limit_retries must be a nonnegative integer")
    if context is not None and (type(context) is not int or context <= 1024):
        raise ValueError("ifm_context_window_tokens must exceed 1024")
    return {"stream": bool(getattr(args, "ifm_stream", False)),
        "request_start_interval_s": interval, "max_rate_limit_retries": retries,
        "context_window_tokens": context}


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
            "mode": oracle_mode,
            "implementation": (
                "LLM validates request semantics; case executes authoritative measurements"
                if oracle_mode == LLM_SEMANTIC_ORACLE else
                "LLM presentation accepted only when its structured observation "
                "equals the deterministic observation"
            ),
            "temperature": 0.0,
            "top_p": 1.0,
            "seed": None,
            "max_output_tokens": args.oracle_max_output_tokens,
        }
    player_prompt_version = _prompt_version(args, "player")
    oracle_prompt_version = _prompt_version(args, "oracle")
    evaluator_prompt_version = _prompt_version(args, "evaluator")
    if (
        oracle_mode == DETERMINISTIC_ORACLE
        and oracle_prompt_version != DEFAULT_ORACLE_PROMPT_VERSION
    ):
        raise ValueError(
            "--oracle-prompt-version requires --oracle-mode llm_presentation"
        )
    player_generation: Dict[str, Any] = {
        "temperature": 0.0,
        "top_p": 1.0,
        "seed": None,
        "max_output_tokens": args.player_max_output_tokens,
        "max_repair_attempts": 0 if player_prompt_version in STRUCTURED_PLAYER_PROMPTS else args.max_repair_attempts,
        "max_actions": args.max_actions,
    }
    player_generation["max_action_bytes"] = _player_action_bytes(args)
    evaluator_generation: Dict[str, Any] = {
        "mode": "post_hoc_observable_transcript",
        "temperature": 0.0,
        "top_p": 1.0,
        "seed": None,
        "max_output_tokens": args.evaluator_max_output_tokens,
        "score_axes": ["understanding_before", "understanding_after", "understanding_gain"],
        "scientific_score_policy": "separate_from_deterministic_evaluation",
    }
    # Record the actual prompts used for this run.
    player_generation["prompt_version"] = player_prompt_version
    if oracle_prompt_version != DEFAULT_ORACLE_PROMPT_VERSION:
        oracle_generation["prompt_version"] = oracle_prompt_version
    evaluator_generation["prompt_version"] = evaluator_prompt_version
    workers = _worker_count(args)
    execution: Dict[str, Any] = {
        "workers": workers,
        "order_guarantee": "sequential_schedule_index",
        "player_termination_policy": "evaluate_and_consume_active_episode",
        "active_infrastructure_failure_policy": "halt_and_retry_same_index",
        "evaluator_failure_policy": "halt_and_retry_evaluator_only",
    }
    ifm_settings = _ifm_transport_settings(args)
    if any(value not in (None, False, 0) for value in ifm_settings.values()):
        execution["ifm_transport"] = ifm_settings
    if _parallel_config_requested(args):
        execution.update(
            {
                "episode_causality": (
                    "player_oracle_turns_sequential; evaluator_after_sealed_"
                    "and_persisted_active_result"
                ),
                "role_concurrency_limits": dict(
                    _role_concurrency_limits(args)
                ),
            }
        )
        if oracle_mode == DETERMINISTIC_ORACLE:
            execution["deterministic_oracle_llm_calls"] = 0
    if workers > 1:
        execution.update(
            {
                "parallelism_scope": "independent_episodes",
                "order_guarantee": (
                    "completion_order_unconstrained; summaries_sorted_by_"
                    "schedule_index_then_episode_id"
                ),
                "resume_policy": (
                    "accept_out_of_order_sidecars; retry_failed_or_missing_"
                    "active_work; retry_missing_or_failed_evaluator_only"
                ),
                "active_infrastructure_failure_policy": (
                    "persist_and_continue_parallel_batch_then_raise"
                ),
                "evaluator_failure_policy": (
                    "persist_and_continue_parallel_batch_then_raise; retry_"
                    "evaluator_only"
                ),
            }
        )
    payload = {
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
                    "unlimited experiments and actions until selected confidence exceeds threshold"
                ),
                "adaptive_early_stopping": True,
            },
            "fixed_experimental_designs": fixed_designs,
            "counterfactual_difficulty": None,
            "primary_outcome": {
                "name": "active_pass",
                "definition": "protocol_completion and evaluation_success",
                "range": "{false, true}",
                "infrastructure_failure": "missing; report separately",
                "interpretation": "episode outcome; report scientific measurements independently",
            },
            "prediction_score": {
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
        "player_generation": player_generation,
        "oracle_generation": oracle_generation,
        "evaluator_generation": evaluator_generation,
        "execution": execution,
    }
    if case_pack.release_metadata:
        payload["design"]["dataset_release"] = dict(case_pack.release_metadata)
    payload["metrics_protocol"] = PERFORMANCE_PROTOCOL
    payload["design"]["performance_metrics"] = {
        "deterministic_prediction": "case_owned_ast_evaluator",
        "formula_consistency": "bounded_domain_checked_algebra_and_counterexamples",
        "scientific_understanding": "same_episode_same_criteria_before_after",
        "failure_modes": "F1_F5_multi_label_among_failed_episodes",
        "missing_metric_policy": "report_status_and_coverage; never_impute_zero",
    }

    return payload


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


def _persist_evaluator_result(output_dir: Path, spec: EpisodeSpec, result: Mapping[str, Any]) -> None:
    """Keep every completed judge attempt before replacing the canonical sidecar."""
    path = _evaluator_result_path(output_dir, spec)
    history = path.parent / "attempts" / spec.episode_id
    history.mkdir(parents=True, exist_ok=True)
    # Include a pre-existing sidecar produced before attempt retention was added.
    if path.exists() and not any(history.glob("*.json")):
        _write_json(history / "0001.json", json.loads(path.read_text(encoding="utf-8")), exclusive=True)
    index = len(list(history.glob("*.json"))) + 1
    _write_json(history / ("%04d.json" % index), result, exclusive=True)
    temporary = path.with_suffix(".json.tmp")
    _write_json(temporary, result)
    temporary.replace(path)


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
    release_metadata = (
        _historical_dataset_metadata()
        if spec.dataset_kind == DatasetKind.HISTORICAL_COUNTERFACTUAL.value
        else case_pack.release_metadata
    )
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
    payload = {
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
    if release_metadata:
        payload["dataset_release"] = dict(release_metadata)
    payload["metrics_protocol"] = PERFORMANCE_PROTOCOL
    return payload


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
        code = outcome.termination.code
        if code in {"payload_too_large", "too_deep", "too_many_values"}:
            category = "resource_limit_failure"
        elif code == "incomplete_output":
            category = "generation_incomplete"
        elif code == "provider_refusal":
            category = "provider_refusal"
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
        "evaluator_checkpoint_or_snapshot_id": runtime.checkpoint_or_snapshot_id,
        "evaluator_reasoning_effort": runtime.reasoning_effort,
        "evaluator_thinking": runtime.thinking,
        "started_at": started_at,
    }
    evaluator_prompt_version = _prompt_version(args, "evaluator")
    base["evaluator_prompt_version"] = evaluator_prompt_version
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
            prompt_version=evaluator_prompt_version,
        )
        case = _make_case(spec)
        pack = CASE_PACKS[spec.case_pack]
        world = pack.runtime_condition_ids.get(spec.case_family, {}).get(spec.condition_id, spec.condition_id)
        reference = discovery_reference_context(case, pack.specifications[spec.case_family][spec.variant_id], world)
        evaluated = evaluator.evaluate(load_run_log(str(log_path)), reference=reference)
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
                # ``PostHocLLMEvaluator`` has already reduced backend failures
                # to credential-free details (for example, an HTTP status) and
                # decoder failures to bounded wire diagnostics.  Preserve that
                # distinction so an evaluator-only retry can be diagnosed
                # without replaying the completed Player--Oracle episode.
                "error_message": str(exc),
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
    merged["metrics_complete"] = False
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
    for key in ("evaluator_profile", "evaluator_provider", "evaluator_model",
                "evaluator_checkpoint_or_snapshot_id", "evaluator_reasoning_effort",
                "evaluator_thinking", "evaluator_prompt_version"):
        if key in evaluator_result:
            if key in merged and merged[key] != evaluator_result[key]:
                merged.setdefault("source_" + key, merged[key])
            merged[key] = evaluator_result[key]
    merged["metrics_complete"] = (
        (result.get("formula_consistency") or {}).get("status") in
        {"equivalent", "not_equivalent", "inconclusive", "unavailable"}
        and evaluator_result.get("status") == "evaluated"
        and evaluator_result.get("evaluator_prompt_version") == DISCOVERY_PROMPT_VERSION
        and isinstance(((evaluator_result.get("evaluation") or {}).get("details") or {}).get("understanding"), dict))
    return merged


SUMMARY_COLUMNS = (
    "metrics_protocol",
    "metrics_complete",
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
    "formula_consistency_status",
    "formula_consistency_json",
    "scientific_assessments_json",
    "normalized_error",
    "expression_match",
    "understanding_before",
    "understanding_after",
    "understanding_gain",
    "understanding_status",
    "scientific_failure_labels_json",
    "scientific_postevaluation_json",
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
    scientific = result.get("science_postevaluation") or {}
    understanding = scientific.get("understanding") or {}
    return {
        "metrics_protocol": result.get("metrics_protocol"),
        "metrics_complete": result.get("metrics_complete"),
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
        "llm_evaluation_finding_count": len((llm_evaluation.get("details") or {}).get("findings", llm_evaluation.get("findings") or [])),
        "llm_evaluation_summary": llm_evaluation.get("summary"),
        "formula_consistency_status": (result.get("formula_consistency") or {}).get("status"),
        "formula_consistency_json": json.dumps(result.get("formula_consistency"), ensure_ascii=False, sort_keys=True),
        "scientific_assessments_json": json.dumps(llm_evaluation.get("details"), ensure_ascii=False, sort_keys=True),
        "normalized_error": scientific.get("normalized_error"),
        "expression_match": scientific.get("expression_match"),
        "understanding_before": understanding.get("before_score"),
        "understanding_after": understanding.get("after_score"),
        "understanding_gain": understanding.get("delta"),
        "understanding_status": understanding.get("status"),
        "scientific_failure_labels_json": json.dumps((scientific.get("failure_analysis") or {}).get("labels"), ensure_ascii=False),
        "scientific_postevaluation_json": json.dumps(scientific or None, ensure_ascii=False),
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
            result.get("schedule_index", sys.maxsize),
            result["episode_id"],
        ),
    )


def write_summaries(output_dir: Path) -> List[Mapping[str, Any]]:
    results = [
        _with_evaluator_summary(output_dir, result)
        for result in load_episode_results(output_dir)
    ]
    for row in results:
        row["science_postevaluation"] = science_postevaluation(row)
    summary = aggregate_scientific_postevaluation(results)
    fields = ("dataset_kind", "condition_role", "player_model", "evaluation_method", "task_setting", "evaluator_model")
    groups = {}
    for row in results:
        groups.setdefault(tuple(row.get(field) for field in fields), []).append(row)
    summary["by_condition"] = [
        {**dict(zip(fields, key)), **aggregate_scientific_postevaluation(group)}
        for key, group in sorted(groups.items(), key=lambda item: repr(item[0]))]
    _write_json(output_dir / "scientific_postevaluation.json", summary)
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
    runtime_condition_id = pack.runtime_condition_ids.get(
        spec.case_family, {}
    ).get(spec.condition_id, spec.condition_id)
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
        if oracle_mode != DETERMINISTIC_ORACLE and oracle_backend is None:
            raise ValueError("LLM Oracle mode requires an LLM backend")
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
            player_prompt_version=_prompt_version(args, "player"),
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
            oracle_prompt_version=_prompt_version(args, "oracle"),
            max_repair_attempts=0 if _prompt_version(args, "player") in STRUCTURED_PLAYER_PROMPTS else args.max_repair_attempts,
            max_action_bytes=_player_action_bytes(args),
            max_actions=None if prepared.plan.observation_budget is None else args.max_actions,
            run_id=spec.episode_id,
            observation_budget=prepared.plan.observation_budget,
            initial_attempts_used=prepared.initial_attempts_used,
            require_budget_exhaustion=prepared.plan.require_budget_exhaustion,
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
        try:
            failure_analysis = (
                analyze_failure_events(load_run_log(run_log_path).events,
                    include_success=True)
                if isinstance(run_log_path, str) else None)
        except Exception as exc:
            failure_analysis = {"status": "infrastructure_failed", "error_type": type(exc).__name__}
        result = _evaluated_result(
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
        result["formula_consistency"] = _formula_result(spec, result)
        return result
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


def _formula_result(spec, result):
    try:
        pack = CASE_PACKS[spec.case_pack]
        world = pack.runtime_condition_ids.get(spec.case_family, {}).get(spec.condition_id, spec.condition_id)
        raw = result.get("final_submission")
        submission = FinalSubmission(**raw) if raw is not None else None
        return formula_metric(submission, pack.specifications[spec.case_family][spec.variant_id], world)
    except Exception as exc:
        return {"status": "infrastructure_failed", "error_type": type(exc).__name__}


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


@dataclass(frozen=True)
class _ParallelTaskOutcome:
    spec: EpisodeSpec
    task_kind: str
    episode_result: Optional[Mapping[str, Any]]
    evaluator_result: Optional[Mapping[str, Any]]


def _write_episode_result(
    output_dir: Path,
    spec: EpisodeSpec,
    result: Mapping[str, Any],
    output_lock: threading.Lock,
) -> None:
    result_path = _result_path(output_dir, spec)
    with output_lock:
        _write_json(result_path, result, exclusive=not result_path.exists())


def _write_evaluator_result(
    output_dir: Path,
    spec: EpisodeSpec,
    result: Mapping[str, Any],
    output_lock: threading.Lock,
) -> None:
    with output_lock:
        _persist_evaluator_result(output_dir, spec, result)


def _run_parallel_active_task(
    args: argparse.Namespace,
    *,
    player_backend: TextGenerationBackend,
    oracle_backend: Optional[TextGenerationBackend],
    evaluator_backend: TextGenerationBackend,
    output_dir: Path,
    spec: EpisodeSpec,
    log_path: Path,
    output_lock: threading.Lock,
) -> _ParallelTaskOutcome:
    """Run one causal episode pipeline and persist each completed stage."""

    episode_result = _run_one_episode(
        args,
        player_backend=player_backend,
        oracle_backend=oracle_backend,
        output_dir=output_dir,
        spec=spec,
        log_path=log_path,
    )
    _write_episode_result(output_dir, spec, episode_result, output_lock)
    if episode_result.get("status") != "evaluated":
        return _ParallelTaskOutcome(
            spec=spec,
            task_kind="active",
            episode_result=episode_result,
            evaluator_result=None,
        )

    # The active transcript is closed by _run_one_episode and its evaluated
    # sidecar is durably visible before post-hoc evaluation begins.
    evaluator_result = _run_evaluator(
        args,
        evaluator_backend=evaluator_backend,
        output_dir=output_dir,
        spec=spec,
        episode_result=episode_result,
    )
    _write_evaluator_result(output_dir, spec, evaluator_result, output_lock)
    return _ParallelTaskOutcome(
        spec=spec,
        task_kind="active",
        episode_result=episode_result,
        evaluator_result=evaluator_result,
    )


def _run_parallel_evaluator_task(
    args: argparse.Namespace,
    *,
    evaluator_backend: TextGenerationBackend,
    output_dir: Path,
    spec: EpisodeSpec,
    episode_result: Mapping[str, Any],
    output_lock: threading.Lock,
) -> _ParallelTaskOutcome:
    evaluator_result = _run_evaluator(
        args,
        evaluator_backend=evaluator_backend,
        output_dir=output_dir,
        spec=spec,
        episode_result=episode_result,
    )
    _write_evaluator_result(output_dir, spec, evaluator_result, output_lock)
    return _ParallelTaskOutcome(
        spec=spec,
        task_kind="evaluator_only",
        episode_result=episode_result,
        evaluator_result=evaluator_result,
    )


def _result_label(result: Mapping[str, Any]) -> str:
    if result.get("status") == "infrastructure_failed":
        return "INFRA"
    return {
        "pass": "PASS",
        "scientific_failure": "SCI",
        "player_generation_failure": "GEN",
        "player_protocol_failure": "PROTO",
        "resource_limit_failure": "LIMIT",
        "generation_incomplete": "TRUNC",
        "provider_refusal": "REFUSE",
    }[str(result["active_pass_category"])]


def _run_parallel_tasks(
    args: argparse.Namespace,
    *,
    player_backend: Optional[TextGenerationBackend],
    oracle_backend: Optional[TextGenerationBackend],
    evaluator_backend: TextGenerationBackend,
    output_dir: Path,
    pending: Sequence[Tuple[EpisodeSpec, Path]],
    evaluator_pending: Sequence[Tuple[EpisodeSpec, Mapping[str, Any]]],
    total_episodes: int,
) -> None:
    output_lock = threading.Lock()
    futures: Dict[Future[_ParallelTaskOutcome], Tuple[str, EpisodeSpec]] = {}
    failures: List[str] = []
    with ThreadPoolExecutor(
        max_workers=_worker_count(args),
        thread_name_prefix="case-matrix",
    ) as executor:
        for spec, episode_result in evaluator_pending:
            future = executor.submit(
                _run_parallel_evaluator_task,
                args,
                evaluator_backend=evaluator_backend,
                output_dir=output_dir,
                spec=spec,
                episode_result=episode_result,
                output_lock=output_lock,
            )
            futures[future] = ("evaluator_only", spec)
        if pending and player_backend is None:
            raise AssertionError("parallel active execution requires Player backend")
        for spec, log_path in pending:
            future = executor.submit(
                _run_parallel_active_task,
                args,
                player_backend=player_backend,
                oracle_backend=oracle_backend,
                evaluator_backend=evaluator_backend,
                output_dir=output_dir,
                spec=spec,
                log_path=log_path,
                output_lock=output_lock,
            )
            futures[future] = ("active", spec)

        for future in as_completed(futures):
            task_kind, spec = futures[future]
            try:
                outcome = future.result()
            except Exception as exc:
                with output_lock:
                    write_summaries(output_dir)
                failures.append(
                    "%s %s raised %s: %s"
                    % (spec.episode_id, task_kind, type(exc).__name__, exc)
                )
                continue
            with output_lock:
                write_summaries(output_dir)
            if outcome.task_kind == "active":
                if outcome.episode_result is None:
                    raise AssertionError("active task must return an episode result")
                print(
                    "[%02d/%02d] %-5s %s"
                    % (
                        spec.schedule_index,
                        total_episodes,
                        _result_label(outcome.episode_result),
                        spec.episode_id,
                    ),
                    flush=True,
                )
                if outcome.episode_result.get("status") != "evaluated":
                    failures.append(
                        "episode %s hit an infrastructure failure: %s"
                        % (
                            spec.episode_id,
                            outcome.episode_result.get("error_message"),
                        )
                    )
            if (
                outcome.evaluator_result is not None
                and outcome.evaluator_result.get("status") != "evaluated"
            ):
                failures.append(
                    "episode %s hit an evaluator failure: %s"
                    % (
                        spec.episode_id,
                        outcome.evaluator_result.get("error_message"),
                    )
                )

    if failures:
        raise RuntimeError(
            "parallel batch completed with %d failure(s); retry runs only failed "
            "or missing work; first failure: %s" % (len(failures), failures[0])
        )


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
    workers = _worker_count(args)
    role_concurrency_limits = _role_concurrency_limits(args)
    schedule_start_index = int(getattr(args, "schedule_start_index", 1))
    schedule_stop_index = getattr(args, "schedule_stop_index", None)
    if schedule_stop_index is not None:
        schedule_stop_index = int(schedule_stop_index)
    schedule_shard_count = int(getattr(args, "schedule_shard_count", 1))
    schedule_shard_index = int(getattr(args, "schedule_shard_index", 0))
    if schedule_start_index < 1:
        raise ValueError("schedule_start_index must be positive")
    if schedule_stop_index is not None and schedule_stop_index < schedule_start_index:
        raise ValueError("schedule_stop_index must not precede schedule_start_index")
    if schedule_shard_count < 1:
        raise ValueError("schedule_shard_count must be positive")
    if not 0 <= schedule_shard_index < schedule_shard_count:
        raise ValueError(
            "schedule_shard_index must be in [0, schedule_shard_count)"
        )
    sparse_schedule = (
        schedule_start_index > 1
        or schedule_stop_index is not None
        or schedule_shard_count > 1
    )
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
    if sparse_schedule:
        selected = [
            spec
            for spec in selected
            if spec.schedule_index >= schedule_start_index
            and (
                schedule_stop_index is None
                or spec.schedule_index <= schedule_stop_index
            )
            and (
                (spec.schedule_index - schedule_start_index)
                % schedule_shard_count
                == schedule_shard_index
            )
        ]
        if not selected:
            raise ValueError("the schedule shard contains no episodes")
    prepare_output(output_dir, _config_payload(args, full_plan))
    write_summaries(output_dir)

    if args.dry_run:
        print(
            "Selected %d of %d episodes in %s"
            % (len(selected), total_episodes, output_dir)
        )
        return []

    interval = _ifm_transport_settings(args)["request_start_interval_s"]
    ifm_gate = RequestStartGate(interval) if interval is not None else None

    loaded = load_episode_results(output_dir)
    existing = {result["episode_id"]: result for result in loaded}
    if len(existing) != len(loaded):
        raise ValueError("result sidecars contain duplicate episode IDs")
    expected_ids = [spec.episode_id for spec in full_plan]
    unknown_ids = set(existing) - set(expected_ids)
    if unknown_ids:
        raise ValueError("result sidecars contain episode IDs outside the plan")
    recorded_ids = [episode_id for episode_id in expected_ids if episode_id in existing]
    if (
        workers == 1
        and not sparse_schedule
        and recorded_ids != expected_ids[: len(recorded_ids)]
    ):
        raise ValueError("result sidecars must form a prefix of the schedule")
    for spec in full_plan:
        if (
            spec.episode_id in existing
            and existing[spec.episode_id].get("schedule_index") != spec.schedule_index
        ):
            raise ValueError("result sidecar schedule_index differs from the plan")

    if sparse_schedule or workers > 1:
        selected_pending = [
            spec
            for spec in selected
            if not _result_consumes_schedule(existing.get(spec.episode_id, {}))
        ]
    else:
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
    completed_specs = [
        spec
        for spec in full_plan
        if _result_consumes_schedule(existing.get(spec.episode_id, {}))
    ]
    for spec in completed_specs:
        episode_result = existing[spec.episode_id]
        if ((episode_result.get("formula_consistency") or {}).get("status") in
                {None, "pending", "infrastructure_failed"}):
            episode_result["formula_consistency"] = _formula_result(spec, episode_result)
            _write_json(_result_path(output_dir, spec), episode_result)
        evaluator_result = _load_evaluator_result(output_dir, spec.episode_id)
        if (evaluator_result is None or evaluator_result.get("status") != "evaluated"
                or evaluator_result.get("evaluator_prompt_version") != DISCOVERY_PROMPT_VERSION):
            evaluator_pending.append((spec, episode_result))
    print(
        "Running %d unfinished episode(s) and %d evaluator-only retry(s) with "
        "%d episode worker(s)"
        % (len(pending), len(evaluator_pending), workers),
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
            ifm_request_gate=ifm_gate,
        )
        evaluator_backend = load_role_backend(
            args,
            "evaluator",
            api_key=_key_for_backend(
                args, "evaluator", evaluator_api_key, evaluator_backend_loader
            ),
            loader=evaluator_backend_loader,
            ifm_request_gate=ifm_gate,
        )
        oracle_backend = None
        if _oracle_mode(args) != DETERMINISTIC_ORACLE:
            oracle_backend = load_role_backend(
                args,
                "oracle",
                api_key=_key_for_backend(
                    args, "oracle", oracle_api_key, oracle_backend_loader
                ),
                loader=oracle_backend_loader,
                ifm_request_gate=ifm_gate,
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
            ifm_request_gate=ifm_gate,
        )
        player_backend = None
        oracle_backend = None
    else:
        player_backend = None
        oracle_backend = None
        evaluator_backend = None

    limit_provider_calls = _parallel_config_requested(args)
    if limit_provider_calls and player_backend is not None:
        player_backend = ConcurrencyLimitedBackend(
            player_backend,
            role="player",
            concurrency_limit=role_concurrency_limits["player"],
        )
    if limit_provider_calls and oracle_backend is not None:
        oracle_backend = ConcurrencyLimitedBackend(
            oracle_backend,
            role="oracle",
            concurrency_limit=role_concurrency_limits["oracle"],
        )
    if limit_provider_calls and evaluator_backend is not None:
        evaluator_backend = ConcurrencyLimitedBackend(
            evaluator_backend,
            role="evaluator",
            concurrency_limit=role_concurrency_limits["evaluator"],
        )

    if workers > 1 and evaluator_backend is not None:
        if pending and player_backend is None:
            raise AssertionError(
                "parallel active execution requires Player and Evaluator backends"
            )
        if (
            pending
            and _oracle_mode(args) != DETERMINISTIC_ORACLE
            and oracle_backend is None
        ):
            raise AssertionError("LLM presentation requires an Oracle backend")
        _run_parallel_tasks(
            args,
            player_backend=player_backend,
            oracle_backend=oracle_backend,
            evaluator_backend=evaluator_backend,
            output_dir=output_dir,
            pending=pending,
            evaluator_pending=evaluator_pending,
            total_episodes=total_episodes,
        )
        pending = []
        evaluator_pending = []

    if evaluator_backend is not None:
        for spec, episode_result in evaluator_pending:
            evaluator_result = _run_evaluator(
                args,
                evaluator_backend=evaluator_backend,
                output_dir=output_dir,
                spec=spec,
                episode_result=episode_result,
            )
            _persist_evaluator_result(output_dir, spec, evaluator_result)
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
            _oracle_mode(args) != DETERMINISTIC_ORACLE
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
            print(
                "[%02d/%02d] %-5s %s"
                % (
                    spec.schedule_index,
                    total_episodes,
                    _result_label(result),
                    spec.episode_id,
                ),
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
            _persist_evaluator_result(output_dir, spec, evaluator_result)
            write_summaries(output_dir)
            if evaluator_result["status"] != "evaluated":
                raise RuntimeError(
                    "episode %s hit an evaluator failure: %s"
                    % (spec.episode_id, evaluator_result["error_message"])
                )

    results = write_summaries(output_dir)
    if any(row.get("status") == "evaluated" and not row.get("metrics_complete") for row in results):
        raise RuntimeError("required performance metrics remain incomplete; completed Player episodes are preserved for metric-only retry")
    evaluated = sum(result["status"] == "evaluated" for result in results)
    failed = sum(
        result["status"] == "infrastructure_failed" for result in results
    )
    print(
        "Finished: %d evaluated, %d infrastructure failed, %d total"
        % (evaluated, failed, len(results))
    )
    return results


def _positive_int_argument(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be an integer") from exc
    if parsed < 1:
        raise argparse.ArgumentTypeError("must be positive")
    return parsed


def _add_role_arguments(parser: argparse.ArgumentParser, role: str) -> None:
    label = role.capitalize()
    parser.add_argument(
        "--%s-provider" % role,
        choices=("deepseek", "openai", "gemini", "ifm"),
        default="openai" if role == "player" else DEFAULT_PROVIDER,
        help="%s provider binding" % label,
    )
    parser.add_argument("--%s-model" % role, help="exact %s model ID" % label)
    parser.add_argument(
        "--%s-ifm-api-mode" % role,
        choices=("ifm_platform", "core42"),
        help="IFM API contract; defaults to ifm_platform, with core42 available explicitly",
    )
    if role == "oracle":
        parser.add_argument(
            "--%s-prompt-version" % role,
            choices=ROLE_PROMPT_VERSIONS[role],
            default=DEFAULT_ROLE_PROMPT_VERSIONS[role],
            help=(
                "%s adapter prompt contract; Oracle observation contract"
                % label
            ),
        )
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
        choices=("none", "minimal", "low", "medium", "high", "xhigh", "max"),
        help="provider reasoning effort for %s" % label,
    )
    parser.add_argument(
        "--%s-timeout-s" % role,
        type=float,
        default=120.0,
        help="HTTP timeout for each %s call" % label,
    )
    parser.add_argument(
        "--%s-concurrency" % role,
        type=_positive_int_argument,
        help=(
            "maximum simultaneous %s provider generate calls; defaults to "
            "--workers and is capped by it%s"
            % (
                label,
                (
                    "; the deterministic Oracle always makes zero calls"
                    if role == "oracle"
                    else ""
                ),
            )
        ),
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
        required=True,
        help="required benchmark slice: historical, temporal, or both",
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
            "structured observation; llm_semantic uses an LLM for request legality "
            "and computes measurements with the deterministic world"
        ),
    )
    parser.add_argument(
        "--family",
        action="append",
        choices=CASE_PACK_FAMILY_CHOICES,
        help="include a registered family in the experiment design",
    )
    parser.add_argument(
        "--variant",
        action="append",
        choices=CASE_PACK_VARIANT_CHOICES,
        help="include a registered variant in the experiment design",
    )
    parser.add_argument(
        "--condition",
        action="append",
        choices=CASE_PACK_CONDITION_CHOICES,
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
        help=(
            "filter repeat blocks; single-worker paid execution must remain a "
            "schedule prefix"
        ),
    )
    parser.add_argument(
        "--schedule-seed",
        type=int,
        default=DEFAULT_SCHEDULE_SEED,
    )
    parser.add_argument("--player-max-output-tokens", type=int, default=8192)
    parser.add_argument("--ifm-stream", action="store_true", help="receive IFM final responses through SSE")
    parser.add_argument("--ifm-request-interval", type=float,
        help="minimum seconds between IFM HTTP request starts, shared across all three roles")
    parser.add_argument("--ifm-rate-limit-retries", type=int, default=0,
        help="retry only rejected IFM HTTP 429 requests; never regenerate returned content")
    parser.add_argument("--ifm-context-window-tokens", type=_positive_int_argument,
        help="reserve prompt capacity before setting the IFM output allowance")
    parser.add_argument("--player-max-action-bytes", type=_positive_int_argument,
        help="local final-action UTF-8 byte limit (default 262144, maximum 1048576); independent of token allowance")
    parser.add_argument(
        "--max-repair-attempts",
        type=int,
        choices=(0, 1),
        default=1,
    )
    parser.add_argument("--oracle-max-output-tokens", type=int, default=256)
    parser.add_argument("--evaluator-max-output-tokens", type=int, default=2048)
    parser.add_argument("--max-actions", type=int, default=16)
    parser.add_argument(
        "--workers",
        type=_positive_int_argument,
        default=1,
        help=(
            "maximum independent episode pipelines executed concurrently; "
            "turns remain sequential inside each episode"
        ),
    )
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
