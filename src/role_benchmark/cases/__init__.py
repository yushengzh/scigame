"""Single registry for every built-in matched case family."""

from __future__ import annotations

from typing import Callable, Dict

from role_benchmark.models import BenchmarkTrack
from role_benchmark.protocols import BenchmarkCase

from .beer_lambert import BEER_LAMBERT_SPEC, make_beer_lambert_case
from .boyle import BOYLE_J_TUBE_SPEC, make_boyle_j_tube_case
from .brownian_diffusion import BROWNIAN_DIFFUSION_SPEC, make_brownian_diffusion_case
from .coulomb_force import COULOMB_FORCE_SPEC, make_coulomb_force_case
from .faraday_induction import FARADAY_INDUCTION_SPEC, make_faraday_induction_case
from .galileo import GALILEO_INCLINED_PLANE_SPEC, make_galileo_inclined_plane_case
from .hooke_spring import HOOKE_SPRING_SPEC, make_hooke_spring_case
from .kepler_orbit import KEPLER_ORBIT_SPEC, make_kepler_orbit_case
from .matched import MATCHED_WORLDS, MatchedFamilySpec
from .source import (
    SourceFamilySpec,
    make_source_case,
    source_truth_submission,
)
from .michaelis_menten import MICHAELIS_MENTEN_SPEC, make_michaelis_menten_case
from .newton_cooling import NEWTON_COOLING_SPEC, make_newton_cooling_case
from .ohm_circuit import OHM_CIRCUIT_SPEC, make_ohm_circuit_case
from .pendulum import PENDULUM_SPEC, PENDULUM_WORLDS, make_pendulum_case
from .photoelectric import PHOTOELECTRIC_SPEC, make_photoelectric_case
from .poiseuille_flow import POISEUILLE_FLOW_SPEC, make_poiseuille_flow_case
from .radioactive_decay import RADIOACTIVE_DECAY_SPEC, make_radioactive_decay_case
from .rc_discharge import RC_DISCHARGE_SPEC, make_rc_discharge_case
from .rutherford_scattering import (
    RUTHERFORD_SCATTERING_SPEC,
    make_rutherford_scattering_case,
)
from .stefan_boltzmann import STEFAN_BOLTZMANN_SPEC, make_stefan_boltzmann_case
from .torricelli_efflux import TORRICELLI_EFFLUX_SPEC, make_torricelli_efflux_case
from .young_double_slit import (
    YOUNG_DOUBLE_SLIT_SPEC,
    YOUNG_DOUBLE_SLIT_WORLDS,
    make_young_double_slit_case,
)


CaseFactory = Callable[[str, BenchmarkTrack], BenchmarkCase]

CASE_FACTORIES: Dict[str, CaseFactory] = {
    "pendulum": make_pendulum_case,
    "young_double_slit": make_young_double_slit_case,
    "galileo_inclined_plane": make_galileo_inclined_plane_case,
    "boyle_j_tube": make_boyle_j_tube_case,
    "photoelectric": make_photoelectric_case,
    "faraday_induction": make_faraday_induction_case,
    "radioactive_decay": make_radioactive_decay_case,
    "rutherford_scattering": make_rutherford_scattering_case,
    "hooke_spring": make_hooke_spring_case,
    "torricelli_efflux": make_torricelli_efflux_case,
    "ohm_circuit": make_ohm_circuit_case,
    "rc_discharge": make_rc_discharge_case,
    "stefan_boltzmann": make_stefan_boltzmann_case,
    "newton_cooling": make_newton_cooling_case,
    "beer_lambert": make_beer_lambert_case,
    "michaelis_menten": make_michaelis_menten_case,
    "coulomb_force": make_coulomb_force_case,
    "kepler_orbit": make_kepler_orbit_case,
    "brownian_diffusion": make_brownian_diffusion_case,
    "poiseuille_flow": make_poiseuille_flow_case,
}

CASE_SPECS: Dict[str, MatchedFamilySpec] = {
    "pendulum": PENDULUM_SPEC,
    "young_double_slit": YOUNG_DOUBLE_SLIT_SPEC,
    "galileo_inclined_plane": GALILEO_INCLINED_PLANE_SPEC,
    "boyle_j_tube": BOYLE_J_TUBE_SPEC,
    "photoelectric": PHOTOELECTRIC_SPEC,
    "faraday_induction": FARADAY_INDUCTION_SPEC,
    "radioactive_decay": RADIOACTIVE_DECAY_SPEC,
    "rutherford_scattering": RUTHERFORD_SCATTERING_SPEC,
    "hooke_spring": HOOKE_SPRING_SPEC,
    "torricelli_efflux": TORRICELLI_EFFLUX_SPEC,
    "ohm_circuit": OHM_CIRCUIT_SPEC,
    "rc_discharge": RC_DISCHARGE_SPEC,
    "stefan_boltzmann": STEFAN_BOLTZMANN_SPEC,
    "newton_cooling": NEWTON_COOLING_SPEC,
    "beer_lambert": BEER_LAMBERT_SPEC,
    "michaelis_menten": MICHAELIS_MENTEN_SPEC,
    "coulomb_force": COULOMB_FORCE_SPEC,
    "kepler_orbit": KEPLER_ORBIT_SPEC,
    "brownian_diffusion": BROWNIAN_DIFFUSION_SPEC,
    "poiseuille_flow": POISEUILLE_FLOW_SPEC,
}

CASE_FAMILIES = tuple(CASE_FACTORIES)
if tuple(CASE_SPECS) != CASE_FAMILIES:
    raise AssertionError("case factories and scientific specifications must align")

# The public registry and named family helpers all use the current Historical data.
from .historical import (
    DATASET_ID as HISTORICAL_DATASET_ID,
    DATASET_STATUS as HISTORICAL_DATASET_STATUS,
    HISTORICAL_CASE_SPECS,
    HISTORICAL_FAMILIES,
    HISTORICAL_SCIENCE_CARDS,
    make_historical_case,
)


def make_case(
    name: str,
    world: str = "historical",
    track: BenchmarkTrack = BenchmarkTrack.IDENTIFICATION,
) -> BenchmarkCase:
    """Build any registered family through the same four-cell interface."""

    try:
        factory = CASE_FACTORIES[name]
    except (KeyError, TypeError) as exc:
        raise ValueError(
            "unknown case family %r; choose one of %s"
            % (name, ", ".join(CASE_FAMILIES))
        ) from exc
    return factory(world, track)


__all__ = [
    "CASE_FACTORIES",
    "CASE_FAMILIES",
    "CASE_SPECS",
    "HISTORICAL_CASE_SPECS",
    "HISTORICAL_DATASET_ID",
    "HISTORICAL_DATASET_STATUS",
    "HISTORICAL_FAMILIES",
    "HISTORICAL_SCIENCE_CARDS",
    "MATCHED_WORLDS",
    "SourceFamilySpec",
    "PENDULUM_WORLDS",
    "YOUNG_DOUBLE_SLIT_WORLDS",
    "make_beer_lambert_case",
    "make_boyle_j_tube_case",
    "make_brownian_diffusion_case",
    "make_case",
    "make_source_case",
    "source_truth_submission",
    "make_coulomb_force_case",
    "make_faraday_induction_case",
    "make_galileo_inclined_plane_case",
    "make_hooke_spring_case",
    "make_historical_case",
    "make_kepler_orbit_case",
    "make_michaelis_menten_case",
    "make_newton_cooling_case",
    "make_ohm_circuit_case",
    "make_pendulum_case",
    "make_photoelectric_case",
    "make_poiseuille_flow_case",
    "make_radioactive_decay_case",
    "make_rc_discharge_case",
    "make_rutherford_scattering_case",
    "make_stefan_boltzmann_case",
    "make_torricelli_efflux_case",
    "make_young_double_slit_case",
]
