"""Matched kepler orbit benchmark family."""

from __future__ import annotations

from typing import Any, Mapping

from role_benchmark.models import BenchmarkTrack, ControlSpec, ReadoutSpec
from role_benchmark.protocols import BenchmarkCase

from ._expressions import add, mul, power, var
from .matched import (
    DEFAULT_MATCHED_NOTES,
    IdentificationParameterSpec,
    MatchedFamilySpec,
    MatchedTruth,
    SourceCredit,
    make_matched_case,
)


def _predict(
    parameters: Mapping[str, float], controls: Mapping[str, Any]
) -> Mapping[str, float]:
    return {
        "orbital_period_days": parameters["reference_period_days"]
        * float(controls["semi_major_axis_au"])
        ** parameters["axis_exponent"]
        * (1.0 + float(controls["eccentricity"]))
        ** parameters["eccentricity_exponent"]
    }


def _expression(
    reference: float, axis_exponent: float, eccentricity_exponent: float
) -> Mapping[str, Any]:
    return mul(
        reference,
        power(var("semi_major_axis_au"), axis_exponent),
        power(add(1.0, var("eccentricity")), eccentricity_exponent),
    )


KEPLER_ORBIT_SPEC = MatchedFamilySpec(
    family="kepler_orbit",
    case_id_prefix="orbital.period",
    swap_public_instance_ids=True,
    response_title="the orbital period relation",
    apparatus_name="ideal_orbit_observatory",
    apparatus_description=(
        "A synthetic observatory that places a negligible-mass test body on a stable "
        "elliptical orbit around the same reference star and times complete revolutions."
    ),
    background=(
        "Test bodies orbit one fixed central star. Determine how orbital period "
        "depends on semi-major axis and eccentricity within the available stable orbits."
    ),
    initial_observations=(
        "Each orbit closes and repeats with the reported period.",
    ),
    controls=(
        ControlSpec(
            "semi_major_axis_au",
            "Orbital semi-major axis.",
            "AU",
            0.2,
            8.0,
        ),
        ControlSpec(
            "eccentricity",
            "Dimensionless orbital eccentricity.",
            "",
            0.0,
            0.7,
        ),
    ),
    readouts=(
        ReadoutSpec(
            "orbital_period_days",
            "Time for one complete orbit.",
            "day",
            0.01,
        ),
    ),
    identification_model="orbital_power_law",
    identification_parameter_specs=(
        IdentificationParameterSpec(
            "reference_period_days",
            "Orbital period at semi_major_axis_au = 1 AU and eccentricity = 0.",
            "day",
            0.0,
            None,
        ),
        IdentificationParameterSpec(
            "axis_exponent",
            "Power-law exponent of semi_major_axis_au / 1 AU.",
            "1",
            -8.0,
            8.0,
        ),
        IdentificationParameterSpec(
            "eccentricity_exponent",
            "Power-law exponent of 1 + eccentricity.",
            "1",
            -8.0,
            8.0,
        ),
    ),
    identification_formula=(
        "P = reference_period_days*(semi_major_axis_au/1 AU)^axis_exponent*"
        "(1 + eccentricity)^eccentricity_exponent"
    ),
    predict=_predict,
    truths={
        "historical": MatchedTruth(
            parameters={
                "reference_period_days": 365.25,
                "axis_exponent": 1.5,
                "eccentricity_exponent": 0.0,
            },
            discovery_outputs={
                "orbital_period_days": _expression(365.25, 1.5, 0.0)
            },
            applicability=(
                "Bound Newtonian two-body motion of negligible-mass test bodies around the same fixed central star over the declared semi-major-axis and eccentricity ranges.",
            ),
            fixed_conditions=(
                "The central mass is fixed so that a one-AU orbit has period 365.25 days; semi-major axis is measured for the osculating ellipse around that body.",
                "Test-body masses do not affect the central mass, and mutual perturbations, external tides, relativistic corrections, mass loss, and drag are absent.",
                "Period depends on semi-major axis but not eccentricity in the selected historical world.",
            ),
        ),
        "counterfactual": MatchedTruth(
            parameters={
                "reference_period_days": 365.25,
                "axis_exponent": 1.0,
                "eccentricity_exponent": 0.0,
            },
            discovery_outputs={
                "orbital_period_days": _expression(365.25, 1.0, 0.0)
            },
            applicability=(
                "Benchmark-authored bound-orbit world with exact linear semi-major-axis scaling and eccentricity-independent periods over the declared stable-orbit range.",
            ),
            fixed_conditions=(
                "The linear axis exponent is the fundamental selected-world orbital response rather than a change in central mass, period convention, or distance calibration.",
                "The central star and one-AU reference period remain fixed; test bodies are negligible and do not perturb one another.",
                "External tides, relativistic corrections, mass loss, and drag are absent, and eccentricity has no additional period effect.",
            ),
        ),
    },
    diagnostic_conditions=(
        {"semi_major_axis_au": 0.2, "eccentricity": 0.0},
        {"semi_major_axis_au": 0.5, "eccentricity": 0.0},
        {"semi_major_axis_au": 1.0, "eccentricity": 0.0},
        {"semi_major_axis_au": 2.0, "eccentricity": 0.0},
        {"semi_major_axis_au": 8.0, "eccentricity": 0.0},
        {"semi_major_axis_au": 1.5, "eccentricity": 0.1},
        {"semi_major_axis_au": 1.5, "eccentricity": 0.4},
        {"semi_major_axis_au": 1.5, "eccentricity": 0.7},
    ),
    hidden_conditions=(
        {"semi_major_axis_au": 0.23, "eccentricity": 0.6},
        {"semi_major_axis_au": 0.45, "eccentricity": 0.1},
        {"semi_major_axis_au": 0.72, "eccentricity": 0.42},
        {"semi_major_axis_au": 1.3, "eccentricity": 0.68},
        {"semi_major_axis_au": 2.1, "eccentricity": 0.25},
        {"semi_major_axis_au": 4.5, "eccentricity": 0.52},
        {"semi_major_axis_au": 7.4, "eccentricity": 0.05},
    ),
    credits=(
        SourceCredit(
            citation="Johannes Kepler, Harmonices mundi libri V (1619).",
            url="https://doi.org/10.5479/sil.135810.39088002800316",
            role=(
                "Primary volume credited for the historical period-squared to "
                "semi-major-axis-cubed relation around a fixed central body."
            ),
        ),
    ),
    counterfactual_change=(
        "Only the semi-major-axis exponent changes from 3/2 to 1. Eccentricity "
        "independence, the central body, and the one-AU reference period stay fixed."
    ),
    common_notes=DEFAULT_MATCHED_NOTES,
)


def make_kepler_orbit_case(
    world: str = "historical",
    track: BenchmarkTrack = BenchmarkTrack.IDENTIFICATION,
) -> BenchmarkCase:
    return make_matched_case(KEPLER_ORBIT_SPEC, world, track)


__all__ = ["KEPLER_ORBIT_SPEC", "make_kepler_orbit_case"]
