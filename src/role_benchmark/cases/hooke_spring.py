"""Matched hooke spring benchmark family."""

from __future__ import annotations

from typing import Any, Mapping

from role_benchmark.models import BenchmarkTrack, ControlSpec, ReadoutSpec
from role_benchmark.protocols import BenchmarkCase

from ._expressions import add, div, mul, power, sub, var
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
    force_ratio = float(controls["force_n"]) / 2.0
    stiffness_ratio = float(controls["spring_stiffness_n_per_m"]) / 40.0
    correction = 1.0 + parameters["nonlinear_coefficient"] * (
        force_ratio**2 - 1.0
    )
    return {
        "extension_cm": parameters["reference_extension_cm"]
        * force_ratio
        * stiffness_ratio ** -1.0
        * correction
    }


def _expression(reference: float, nonlinear: float) -> Mapping[str, Any]:
    force_ratio = div(var("force_n"), 2.0)
    stiffness_ratio = div(var("spring_stiffness_n_per_m"), 40.0)
    correction = add(
        1.0,
        mul(nonlinear, sub(power(force_ratio, 2.0), 1.0)),
    )
    return mul(
        reference,
        force_ratio,
        power(stiffness_ratio, -1.0),
        correction,
    )


HOOKE_SPRING_SPEC = MatchedFamilySpec(
    family="hooke_spring",
    case_id_prefix="spring.extension",
    response_title="the load-extension relation",
    apparatus_name="spring_extension_rig",
    apparatus_description=(
        "A calibrated quasistatic loading frame with interchangeable springs, "
        "a force setting, and an extension gauge."
    ),
    background=(
        "A spring is loaded slowly enough that inertia and hysteresis can be ignored. "
        "Determine how its equilibrium extension depends on applied force and the "
        "spring's calibrated stiffness setting."
    ),
    initial_observations=(
        "The unloaded spring returns to the same reference position after each trial.",
        "Changing the applied force produces a reproducible change in extension.",
    ),
    controls=(
        ControlSpec(
            name="force_n",
            description="Applied tensile force.",
            unit="N",
            minimum=0.5,
            maximum=4.0,
        ),
        ControlSpec(
            name="spring_stiffness_n_per_m",
            description=(
                "Reference secant stiffness F/x of the installed spring, calibrated "
                "at an applied force of 2.0 N; it is not a tangent stiffness."
            ),
            unit="N/m",
            minimum=20.0,
            maximum=80.0,
        ),
    ),
    readouts=(
        ReadoutSpec(
            name="extension_cm",
            description="Equilibrium extension from the unloaded position.",
            unit="cm",
            resolution=0.01,
        ),
    ),
    identification_model="weakly_nonlinear_spring",
    identification_parameter_specs=(
        IdentificationParameterSpec(
            "reference_extension_cm",
            "Equilibrium extension at force_n = 2 N and spring_stiffness_n_per_m = 40 N/m.",
            "cm",
            0.0,
            None,
        ),
        IdentificationParameterSpec(
            "nonlinear_coefficient",
            "Dimensionless coefficient of the force-dependent correction 1 + coefficient*((force_n/2 N)^2 - 1).",
            "1",
            -0.3,
            1.0,
        ),
    ),
    identification_formula=(
        "x = reference_extension_cm*(force_n/2)*(spring_stiffness_n_per_m/40)^-1"
        "*[1 + nonlinear_coefficient*((force_n/2)^2 - 1)]"
    ),
    predict=_predict,
    truths={
        "historical": MatchedTruth(
            parameters={
                "reference_extension_cm": 5.0,
                "nonlinear_coefficient": 0.0,
            },
            discovery_outputs={"extension_cm": _expression(5.0, 0.0)},
            applicability=(
                "Reversible quasistatic tensile extension within the stated force and reference-stiffness ranges.",
            ),
            fixed_conditions=(
                "The installed spring is Hookean over the encoded range, with negligible hysteresis, creep, inertia, and temperature drift.",
                "spring_stiffness_n_per_m is the secant value F/x at the 2.0 N calibration point.",
            ),
        ),
        "counterfactual": MatchedTruth(
            parameters={
                "reference_extension_cm": 5.0,
                "nonlinear_coefficient": 0.2,
            },
            discovery_outputs={"extension_cm": _expression(5.0, 0.2)},
            applicability=(
                "Authored reversible odd-nonlinear elastic response within the stated force and reference-stiffness ranges.",
            ),
            fixed_conditions=(
                "The encoded cubic correction is the complete equilibrium nonlinearity; hysteresis, creep, inertia, and temperature drift are negligible.",
                "spring_stiffness_n_per_m is the secant value F/x at the 2.0 N calibration point, not the tangent stiffness away from that point.",
            ),
        ),
    },
    diagnostic_conditions=(
        {"force_n": 0.5, "spring_stiffness_n_per_m": 40.0},
        {"force_n": 1.0, "spring_stiffness_n_per_m": 40.0},
        {"force_n": 2.0, "spring_stiffness_n_per_m": 40.0},
        {"force_n": 4.0, "spring_stiffness_n_per_m": 40.0},
        {"force_n": 2.0, "spring_stiffness_n_per_m": 20.0},
        {"force_n": 2.0, "spring_stiffness_n_per_m": 80.0},
        {"force_n": 3.0, "spring_stiffness_n_per_m": 25.0},
        {"force_n": 0.75, "spring_stiffness_n_per_m": 70.0},
    ),
    hidden_conditions=(
        {"force_n": 0.65, "spring_stiffness_n_per_m": 70.0},
        {"force_n": 1.1, "spring_stiffness_n_per_m": 25.0},
        {"force_n": 1.6, "spring_stiffness_n_per_m": 55.0},
        {"force_n": 2.4, "spring_stiffness_n_per_m": 32.0},
        {"force_n": 3.1, "spring_stiffness_n_per_m": 75.0},
        {"force_n": 3.8, "spring_stiffness_n_per_m": 45.0},
    ),
    credits=(
        SourceCredit(
            citation="Robert Hooke, Lectures de Potentia Restitutiva (1678).",
            url="https://quod.lib.umich.edu/e/eebo/A44322.0001.001?view=toc",
            role=(
                "Primary scan credited for the historical proportionality between "
                "extension and restoring force; metric calibration is benchmark-authored."
            ),
        ),
    ),
    counterfactual_change=(
        "Only a dimensionless cubic correction coefficient changes from 0 to 0.2. "
        "It is the lowest odd-order correction to a sign-symmetric restoring law, "
        "used here as an authored twin rather than a historical claim."
    ),
    common_notes=DEFAULT_MATCHED_NOTES
    + (
        "The stiffness control is a reference secant calibration at 2.0 N and is not a claim about tangent stiffness away from that point.",
    ),
)


def make_hooke_spring_case(
    world: str = "historical",
    track: BenchmarkTrack = BenchmarkTrack.IDENTIFICATION,
) -> BenchmarkCase:
    return make_matched_case(HOOKE_SPRING_SPEC, world, track)


__all__ = ["HOOKE_SPRING_SPEC", "make_hooke_spring_case"]
