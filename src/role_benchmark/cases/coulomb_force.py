"""Matched coulomb force benchmark family."""

from __future__ import annotations

from typing import Any, Mapping

from role_benchmark.models import BenchmarkTrack, ControlSpec, ReadoutSpec
from role_benchmark.protocols import BenchmarkCase

from ._expressions import div, mul, power, var
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
        "force_un": parameters["reference_force_un"]
        * (float(controls["charge_1_nc"]) / 5.0)
        ** parameters["charge_1_exponent"]
        * (float(controls["charge_2_nc"]) / 5.0)
        ** parameters["charge_2_exponent"]
        * (float(controls["separation_cm"]) / 10.0)
        ** parameters["distance_exponent"]
    }


def _expression(
    reference: float,
    charge_1_exponent: float,
    charge_2_exponent: float,
    distance_exponent: float,
) -> Mapping[str, Any]:
    return mul(
        reference,
        power(div(var("charge_1_nc"), 5.0), charge_1_exponent),
        power(div(var("charge_2_nc"), 5.0), charge_2_exponent),
        power(div(var("separation_cm"), 10.0), distance_exponent),
    )


COULOMB_FORCE_SPEC = MatchedFamilySpec(
    family="coulomb_force",
    case_id_prefix="electrostatic.balance",
    response_title="the electrostatic force relation",
    apparatus_name="electrostatic_torsion_balance",
    apparatus_description=(
        "A vacuum torsion balance with two effectively point-like charged spheres, "
        "independently calibrated charges, and adjustable center-to-center separation."
    ),
    background=(
        "Two like point-source charges produce a mutual repulsive interaction in the "
        "evacuated chamber. Sphere radii are negligible relative to every listed "
        "separation; charges remain fixed, and polarization, image forces, and external "
        "fields are absent. Determine how the reported force magnitude depends on the "
        "two charges and their separation."
    ),
    initial_observations=(
        "The balance deflects in the repulsive direction, while its reported "
        "nonnegative force magnitude is reproducible.",
    ),
    controls=(
        ControlSpec("charge_1_nc", "Magnitude of charge on sphere one.", "nC", 1.0, 10.0),
        ControlSpec("charge_2_nc", "Magnitude of charge on sphere two.", "nC", 1.0, 10.0),
        ControlSpec("separation_cm", "Center-to-center sphere separation.", "cm", 2.0, 20.0),
    ),
    readouts=(
        ReadoutSpec(
            "force_un",
            "Magnitude of electrostatic repulsion.",
            "uN",
            0.01,
        ),
    ),
    identification_model="electrostatic_power_law",
    identification_parameter_specs=(
        IdentificationParameterSpec(
            "reference_force_un",
            "Force magnitude at charge_1_nc = 5 nC, charge_2_nc = 5 nC, and separation_cm = 10 cm.",
            "uN",
            0.0,
            None,
        ),
        IdentificationParameterSpec(
            "charge_1_exponent",
            "Power-law exponent of charge_1_nc / 5 nC.",
            "1",
            -8.0,
            8.0,
        ),
        IdentificationParameterSpec(
            "charge_2_exponent",
            "Power-law exponent of charge_2_nc / 5 nC.",
            "1",
            -8.0,
            8.0,
        ),
        IdentificationParameterSpec(
            "distance_exponent",
            "Power-law exponent of separation_cm / 10 cm.",
            "1",
            -8.0,
            8.0,
        ),
    ),
    identification_formula=(
        "F = reference_force_un*(charge_1_nc/5)^charge_1_exponent*"
        "(charge_2_nc/5)^charge_2_exponent*"
        "(separation_cm/10)^distance_exponent"
    ),
    predict=_predict,
    truths={
        "historical": MatchedTruth(
            parameters={
                "reference_force_un": 22.47,
                "charge_1_exponent": 1.0,
                "charge_2_exponent": 1.0,
                "distance_exponent": -2.0,
            },
            discovery_outputs={
                "force_un": _expression(22.47, 1.0, 1.0, -2.0)
            },
            applicability=(
                "Static vacuum interaction of two effectively point-like charges in the "
                "historical inverse-square world.",
            ),
            fixed_conditions=(
                "The reported scalar is the magnitude of the radial repulsive force; the "
                "raw signed torsion deflection supplies direction separately.",
                "Charge distributions are fixed and localized, separation is center to "
                "center, and polarization, image forces, external fields, and material "
                "screening are absent.",
                "The reference coefficient 22.47 uN is the calibrated force for two 5 nC "
                "charges separated by 10 cm in this idealized world.",
            ),
        ),
        "counterfactual": MatchedTruth(
            parameters={
                "reference_force_un": 22.47,
                "charge_1_exponent": 1.0,
                "charge_2_exponent": 1.0,
                "distance_exponent": -1.0,
            },
            discovery_outputs={
                "force_un": _expression(22.47, 1.0, 1.0, -1.0)
            },
            applicability=(
                "Benchmark-authored vacuum interaction world with an exact inverse-distance "
                "force magnitude over the declared charge and separation ranges.",
            ),
            fixed_conditions=(
                "The reported scalar is the magnitude of the radial repulsive force; the "
                "raw signed torsion deflection supplies direction separately.",
                "Charge distributions are fixed and localized, separation is center to "
                "center, and polarization, image forces, external fields, and material "
                "screening are absent.",
                "The alternate distance law is a fundamental law of the selected "
                "counterfactual world, not a finite-size or apparatus artifact.",
            ),
        ),
    },
    diagnostic_conditions=(
        {"charge_1_nc": 5.0, "charge_2_nc": 5.0, "separation_cm": 2.5},
        {"charge_1_nc": 5.0, "charge_2_nc": 5.0, "separation_cm": 5.0},
        {"charge_1_nc": 5.0, "charge_2_nc": 5.0, "separation_cm": 10.0},
        {"charge_1_nc": 5.0, "charge_2_nc": 5.0, "separation_cm": 20.0},
        {"charge_1_nc": 1.0, "charge_2_nc": 5.0, "separation_cm": 10.0},
        {"charge_1_nc": 10.0, "charge_2_nc": 5.0, "separation_cm": 10.0},
        {"charge_1_nc": 5.0, "charge_2_nc": 1.0, "separation_cm": 10.0},
        {"charge_1_nc": 5.0, "charge_2_nc": 10.0, "separation_cm": 10.0},
    ),
    hidden_conditions=(
        {"charge_1_nc": 1.3, "charge_2_nc": 8.7, "separation_cm": 3.2},
        {"charge_1_nc": 9.4, "charge_2_nc": 2.1, "separation_cm": 5.8},
        {"charge_1_nc": 3.6, "charge_2_nc": 6.2, "separation_cm": 7.5},
        {"charge_1_nc": 7.8, "charge_2_nc": 4.4, "separation_cm": 11.5},
        {"charge_1_nc": 2.5, "charge_2_nc": 9.7, "separation_cm": 14.0},
        {"charge_1_nc": 8.2, "charge_2_nc": 7.1, "separation_cm": 17.3},
        {"charge_1_nc": 5.5, "charge_2_nc": 1.6, "separation_cm": 19.2},
    ),
    credits=(
        SourceCredit(
            citation=(
                "Charles-Augustin de Coulomb, Premier memoire sur l'electricite "
                "et le magnetisme (presented 1785; collected 1789)."
            ),
            url="https://doi.org/10.5479/sil.304245.39088000647479",
            role=(
                "Primary collected memoir credited for torsion-balance evidence "
                "supporting charge proportionality and inverse-square distance scaling."
            ),
        ),
    ),
    counterfactual_change=(
        "Only the normalized separation exponent changes from -2 to -1. Both charge "
        "exponents, the reference force, apparatus, and observable range stay fixed."
    ),
    common_notes=DEFAULT_MATCHED_NOTES,
)


def make_coulomb_force_case(
    world: str = "historical",
    track: BenchmarkTrack = BenchmarkTrack.IDENTIFICATION,
) -> BenchmarkCase:
    return make_matched_case(COULOMB_FORCE_SPEC, world, track)


__all__ = ["COULOMB_FORCE_SPEC", "make_coulomb_force_case"]
