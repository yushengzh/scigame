"""Registry of source-reviewed temporal cases.

Temporal cases remain separate from the stable historical/counterfactual case
pack because their membership grows with each census window.
"""

from __future__ import annotations

from typing import Callable, Dict

from role_benchmark.cases.matched import MATCHED_WORLDS, MatchedFamilySpec
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


def make_temporal_case(
    name: str,
    world: str = "historical",
    track: BenchmarkTrack = BenchmarkTrack.IDENTIFICATION,
) -> BenchmarkCase:
    """Build a registered source-reviewed temporal family."""

    try:
        factory = TEMPORAL_CASE_FACTORIES[name]
    except (KeyError, TypeError) as exc:
        raise ValueError(
            "unknown temporal case family %r; choose one of %s"
            % (name, ", ".join(TEMPORAL_CASE_FAMILIES))
        ) from exc
    return factory(world, track)


__all__ = [
    "MATCHED_WORLDS",
    "TEMPORAL_CASE_FACTORIES",
    "TEMPORAL_CASE_FAMILIES",
    "TEMPORAL_CASE_SPECS",
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
