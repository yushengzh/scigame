"""Registry of source-derived temporal cases.

Temporal cases remain separate from the stable historical/counterfactual case
pack because their membership grows with each census window.
"""

from __future__ import annotations

from typing import Callable, Dict, Tuple

from role_benchmark.cases.matched import MatchedFamilySpec
from role_benchmark.conditions import (
    ConditionDescriptor,
    ConditionRole,
    DatasetKind,
    validate_condition_descriptors,
)
from role_benchmark.models import BenchmarkTrack
from role_benchmark.protocols import BenchmarkCase

from .kz_incompressible_energy_temperature_regimes import (
    KZ_INCOMPRESSIBLE_ENERGY_TEMPERATURE_REGIMES_SPEC,
    make_kz_incompressible_energy_temperature_regimes_case,
)
from .viscous_inertial_rheology import (
    VISCOUS_INERTIAL_RHEOLOGY_SPEC,
    make_viscous_inertial_rheology_case,
)
from .rilw_msd_scaling import RILW_MSD_SCALING_SPEC, make_rilw_msd_scaling_case
from .defect_sre import DEFECT_SRE_SPEC, make_defect_sre_case
from .trxas_lorentzian_fit import (
    TRXAS_LORENTZIAN_FIT_SPEC,
    make_trxas_lorentzian_fit_case,
)
from .self_similar_spreading_radius_ratio import (
    SELF_SIMILAR_SPREADING_RADIUS_RATIO_SPEC,
    make_self_similar_spreading_radius_ratio_case,
)
from .stealthy_hyperuniform_localization_scaling import (
    STEALTHY_HYPERUNIFORM_LOCALIZATION_SCALING_SPEC,
    make_stealthy_hyperuniform_localization_scaling_case,
)
from .uamo_lyapunov import UAMO_LYAPUNOV_SPEC, make_uamo_lyapunov_case
from .statistical_mean_field_effective_detuning import (
    STATISTICAL_MEAN_FIELD_EFFECTIVE_DETUNING_SPEC,
    make_statistical_mean_field_effective_detuning_case,
)


TemporalCaseFactory = Callable[[str, BenchmarkTrack], BenchmarkCase]

TEMPORAL_CASE_FACTORIES: Dict[str, TemporalCaseFactory] = {
    "kz_incompressible_energy_temperature_regimes": (
        make_kz_incompressible_energy_temperature_regimes_case
    ),
    "viscous_inertial_rheology": make_viscous_inertial_rheology_case,
    "rilw_msd_scaling": make_rilw_msd_scaling_case,
    "defect_sre": make_defect_sre_case,
    "trxas_lorentzian_fit": make_trxas_lorentzian_fit_case,
    "self_similar_spreading_radius_ratio": (
        make_self_similar_spreading_radius_ratio_case
    ),
    "stealthy_hyperuniform_localization_scaling": (
        make_stealthy_hyperuniform_localization_scaling_case
    ),
    "uamo_lyapunov": make_uamo_lyapunov_case,
    "statistical_mean_field_effective_detuning": (
        make_statistical_mean_field_effective_detuning_case
    ),
}

TEMPORAL_CASE_SPECS: Dict[str, MatchedFamilySpec] = {
    "kz_incompressible_energy_temperature_regimes": (
        KZ_INCOMPRESSIBLE_ENERGY_TEMPERATURE_REGIMES_SPEC
    ),
    "viscous_inertial_rheology": VISCOUS_INERTIAL_RHEOLOGY_SPEC,
    "rilw_msd_scaling": RILW_MSD_SCALING_SPEC,
    "defect_sre": DEFECT_SRE_SPEC,
    "trxas_lorentzian_fit": TRXAS_LORENTZIAN_FIT_SPEC,
    "self_similar_spreading_radius_ratio": (
        SELF_SIMILAR_SPREADING_RADIUS_RATIO_SPEC
    ),
    "stealthy_hyperuniform_localization_scaling": (
        STEALTHY_HYPERUNIFORM_LOCALIZATION_SCALING_SPEC
    ),
    "uamo_lyapunov": UAMO_LYAPUNOV_SPEC,
    "statistical_mean_field_effective_detuning": (
        STATISTICAL_MEAN_FIELD_EFFECTIVE_DETUNING_SPEC
    ),
}

TEMPORAL_CASE_FAMILIES = tuple(TEMPORAL_CASE_FACTORIES)
if tuple(TEMPORAL_CASE_SPECS) != TEMPORAL_CASE_FAMILIES:
    raise AssertionError("temporal case factories and specifications must align")


def _source_condition_pair(family_id: str) -> Tuple[ConditionDescriptor, ...]:
    return validate_condition_descriptors(
        (
            ConditionDescriptor(
                dataset_kind=DatasetKind.TEMPORAL,
                family_id=family_id,
                variant_id="source_reported_v1",
                condition_id="condition_a",
                condition_role=ConditionRole.SOURCE_REPORTED,
                source_condition_id="source_condition_a",
            ),
            ConditionDescriptor(
                dataset_kind=DatasetKind.TEMPORAL,
                family_id=family_id,
                variant_id="source_reported_v1",
                condition_id="condition_b",
                condition_role=ConditionRole.SOURCE_REPORTED,
                source_condition_id="source_condition_b",
            ),
        )
    )


# These descriptors are the scientific condition semantics for the Temporal
# pack.  A/B are deliberately neutral: neither branch is historical,
# counterfactual, easy, or hard.
TEMPORAL_SOURCE_CONDITIONS: Dict[str, Tuple[ConditionDescriptor, ...]] = {
    "kz_incompressible_energy_temperature_regimes": _source_condition_pair(
        "kz_incompressible_energy_temperature_regimes"
    ),
    "viscous_inertial_rheology": _source_condition_pair(
        "viscous_inertial_rheology"
    ),
    "rilw_msd_scaling": _source_condition_pair("rilw_msd_scaling"),
    "defect_sre": _source_condition_pair("defect_sre"),
    "trxas_lorentzian_fit": _source_condition_pair("trxas_lorentzian_fit"),
    "self_similar_spreading_radius_ratio": _source_condition_pair(
        "self_similar_spreading_radius_ratio"
    ),
    "stealthy_hyperuniform_localization_scaling": _source_condition_pair(
        "stealthy_hyperuniform_localization_scaling"
    ),
    "uamo_lyapunov": _source_condition_pair("uamo_lyapunov"),
    "statistical_mean_field_effective_detuning": _source_condition_pair(
        "statistical_mean_field_effective_detuning"
    ),
}


# The generated case modules still accept the old two runtime storage keys.
# This explicit per-family map is compatibility plumbing only; its values must
# never be interpreted as Temporal scientific roles.
TEMPORAL_SOURCE_CONDITION_RUNTIME_MAP: Dict[str, Dict[str, str]] = {
    "kz_incompressible_energy_temperature_regimes": {
        "condition_a": "historical",
        "condition_b": "counterfactual",
    },
    "viscous_inertial_rheology": {
        "condition_a": "historical",
        "condition_b": "counterfactual",
    },
    "rilw_msd_scaling": {
        "condition_a": "historical",
        "condition_b": "counterfactual",
    },
    "defect_sre": {
        "condition_a": "historical",
        "condition_b": "counterfactual",
    },
    "trxas_lorentzian_fit": {
        "condition_a": "historical",
        "condition_b": "counterfactual",
    },
    "self_similar_spreading_radius_ratio": {
        "condition_a": "historical",
        "condition_b": "counterfactual",
    },
    "stealthy_hyperuniform_localization_scaling": {
        "condition_a": "historical",
        "condition_b": "counterfactual",
    },
    "uamo_lyapunov": {
        "condition_a": "historical",
        "condition_b": "counterfactual",
    },
    "statistical_mean_field_effective_detuning": {
        "condition_a": "historical",
        "condition_b": "counterfactual",
    },
}

TEMPORAL_SOURCE_VERSION_IDS: Dict[str, str] = {
    "kz_incompressible_energy_temperature_regimes": "2506.21670v3",
    "viscous_inertial_rheology": "2505.04242v1",
    "rilw_msd_scaling": "2503.15027v1",
    "defect_sre": "2501.09498v1",
    "trxas_lorentzian_fit": "2510.24686v1",
    "self_similar_spreading_radius_ratio": "2502.06256v3",
    "stealthy_hyperuniform_localization_scaling": "2509.13502v3",
    "uamo_lyapunov": "2508.08255v1",
    "statistical_mean_field_effective_detuning": "2506.20617v2",
}
TEMPORAL_SOURCE_PAPER_IDS: Dict[str, str] = {
    family_id: "arxiv:" + version_id.rsplit("v", 1)[0]
    for family_id, version_id in TEMPORAL_SOURCE_VERSION_IDS.items()
}

if tuple(TEMPORAL_SOURCE_CONDITIONS) != TEMPORAL_CASE_FAMILIES:
    raise AssertionError("temporal source-condition descriptors must align")
if tuple(TEMPORAL_SOURCE_CONDITION_RUNTIME_MAP) != TEMPORAL_CASE_FAMILIES:
    raise AssertionError("temporal source-condition runtime maps must align")
if tuple(TEMPORAL_SOURCE_VERSION_IDS) != TEMPORAL_CASE_FAMILIES:
    raise AssertionError("temporal source-version IDs must align")
if tuple(TEMPORAL_SOURCE_PAPER_IDS) != TEMPORAL_CASE_FAMILIES:
    raise AssertionError("temporal source-paper IDs must align")
for _family_id in TEMPORAL_CASE_FAMILIES:
    _condition_ids = {
        item.condition_id for item in TEMPORAL_SOURCE_CONDITIONS[_family_id]
    }
    if set(TEMPORAL_SOURCE_CONDITION_RUNTIME_MAP[_family_id]) != _condition_ids:
        raise AssertionError(
            "temporal source-condition descriptors and runtime keys must align"
        )


def make_temporal_case(
    name: str,
    condition_id: str = "condition_a",
    task_setting: BenchmarkTrack = BenchmarkTrack.IDENTIFICATION,
) -> BenchmarkCase:
    """Build a registered source-derived Temporal case."""

    try:
        factory = TEMPORAL_CASE_FACTORIES[name]
    except (KeyError, TypeError) as exc:
        raise ValueError(
            "unknown temporal case family %r; choose one of %s"
            % (name, ", ".join(TEMPORAL_CASE_FAMILIES))
        ) from exc
    try:
        runtime_condition = TEMPORAL_SOURCE_CONDITION_RUNTIME_MAP[name][
            condition_id
        ]
    except (KeyError, TypeError) as exc:
        raise ValueError(
            "unknown condition_id %r for temporal family %s"
            % (condition_id, name)
        ) from exc
    return factory(runtime_condition, task_setting)


__all__ = [
    "TEMPORAL_CASE_FACTORIES",
    "TEMPORAL_CASE_FAMILIES",
    "TEMPORAL_CASE_SPECS",
    "TEMPORAL_SOURCE_CONDITIONS",
    "TEMPORAL_SOURCE_CONDITION_RUNTIME_MAP",
    "TEMPORAL_SOURCE_PAPER_IDS",
    "TEMPORAL_SOURCE_VERSION_IDS",
    "make_defect_sre_case",
    "make_kz_incompressible_energy_temperature_regimes_case",
    "make_rilw_msd_scaling_case",
    "make_self_similar_spreading_radius_ratio_case",
    "make_statistical_mean_field_effective_detuning_case",
    "make_stealthy_hyperuniform_localization_scaling_case",
    "make_temporal_case",
    "make_trxas_lorentzian_fit_case",
    "make_uamo_lyapunov_case",
    "make_viscous_inertial_rheology_case",
]
