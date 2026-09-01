"""Matched poiseuille flow benchmark family."""

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


_REFERENCE_FLOW_RATE_ML_PER_S = 1.2271846303


def _predict(
    parameters: Mapping[str, float], controls: Mapping[str, Any]
) -> Mapping[str, float]:
    return {
        "flow_rate_ml_per_s": parameters["reference_flow_rate_ml_per_s"]
        * (float(controls["pressure_drop_kpa"]) / 10.0)
        ** parameters["pressure_exponent"]
        * (float(controls["tube_radius_mm"]) / 0.5)
        ** parameters["radius_exponent"]
        * (float(controls["tube_length_cm"]) / 20.0)
        ** parameters["length_exponent"]
        * float(controls["viscosity_mpa_s"])
        ** parameters["viscosity_exponent"]
    }


def _expression(
    reference: float,
    pressure_exponent: float,
    radius_exponent: float,
    length_exponent: float,
    viscosity_exponent: float,
) -> Mapping[str, Any]:
    return mul(
        reference,
        power(div(var("pressure_drop_kpa"), 10.0), pressure_exponent),
        power(div(var("tube_radius_mm"), 0.5), radius_exponent),
        power(div(var("tube_length_cm"), 20.0), length_exponent),
        power(var("viscosity_mpa_s"), viscosity_exponent),
    )


POISEUILLE_FLOW_SPEC = MatchedFamilySpec(
    family="poiseuille_flow",
    case_id_prefix="capillary.flow",
    swap_public_instance_ids=True,
    response_title="the capillary flow relation",
    apparatus_name="laminar_capillary_flow_rig",
    apparatus_description=(
        "A pressure-controlled reservoir, interchangeable straight circular test "
        "sections, two pressure taps, and fixed-density liquids from a calibrated "
        "rheology series. The first pressure tap is fixed 10 cm downstream of a "
        "hydrodynamically conditioned inlet; the second tap sets the selected downstream "
        "separation. A volumetric flow meter reports the steady flow rate."
    ),
    background=(
        "A single-phase liquid flows steadily through a straight circular test "
        "section. The listed range was operationally checked to remain in a steady "
        "laminar regime without transition to unsteady flow, and the first tap lies "
        "beyond the independently verified inlet-development region at every available "
        "setting. Wall interaction and the internal velocity profile are not supplied "
        "as a candidate law. Determine how flow rate depends on pressure drop, tube "
        "radius, tap separation, and the calibrated viscosity setting."
    ),
    initial_observations=(
        "Flow is steady and bubble-free, and the two pressure-tap readings are stable.",
    ),
    controls=(
        ControlSpec("pressure_drop_kpa", "Pressure difference between the two taps.", "kPa", 2.0, 10.0),
        ControlSpec("tube_radius_mm", "Internal tube radius.", "mm", 0.25, 0.5),
        ControlSpec("tube_length_cm", "Distance between the test-section pressure taps.", "cm", 20.0, 50.0),
        ControlSpec("viscosity_mpa_s", "Calibrated viscosity setting of the selected liquid.", "mPa*s", 1.0, 3.0),
    ),
    readouts=(
        ReadoutSpec(
            "flow_rate_ml_per_s",
            "Steady volumetric flow rate.",
            "mL/s",
            0.001,
        ),
    ),
    identification_model="capillary_flow_power_law",
    identification_parameter_specs=(
        IdentificationParameterSpec(
            "reference_flow_rate_ml_per_s",
            "Flow rate at pressure_drop_kpa = 10 kPa, tube_radius_mm = 0.5 mm, tube_length_cm = 20 cm, and viscosity_mpa_s = 1 mPa*s.",
            "mL/s",
            0.0,
            None,
        ),
        IdentificationParameterSpec(
            "pressure_exponent",
            "Power-law exponent of pressure_drop_kpa / 10 kPa.",
            "1",
            -8.0,
            8.0,
        ),
        IdentificationParameterSpec(
            "radius_exponent",
            "Power-law exponent of tube_radius_mm / 0.5 mm.",
            "1",
            -8.0,
            8.0,
        ),
        IdentificationParameterSpec(
            "length_exponent",
            "Power-law exponent of tube_length_cm / 20 cm.",
            "1",
            -8.0,
            8.0,
        ),
        IdentificationParameterSpec(
            "viscosity_exponent",
            "Power-law exponent of viscosity_mpa_s / 1 mPa*s.",
            "1",
            -8.0,
            8.0,
        ),
    ),
    identification_formula=(
        "Q = reference_flow_rate_ml_per_s*(pressure_drop_kpa/10)^pressure_exponent*"
        "(tube_radius_mm/0.5)^radius_exponent*(tube_length_cm/20)^length_exponent*"
        "(viscosity_mpa_s/(1 mPa*s))^viscosity_exponent"
    ),
    predict=_predict,
    truths={
        "historical": MatchedTruth(
            parameters={
                "reference_flow_rate_ml_per_s": _REFERENCE_FLOW_RATE_ML_PER_S,
                "pressure_exponent": 1.0,
                "radius_exponent": 4.0,
                "length_exponent": -1.0,
                "viscosity_exponent": -1.0,
            },
            discovery_outputs={
                "flow_rate_ml_per_s": _expression(
                    _REFERENCE_FLOW_RATE_ML_PER_S, 1.0, 4.0, -1.0, -1.0
                )
            },
            applicability=(
                "Steady, fully developed, incompressible Newtonian laminar flow through a "
                "rigid straight circular tube with a no-slip wall.",
            ),
            fixed_conditions=(
                "The first pressure tap is 10 cm downstream of the conditioned inlet; "
                "the largest declared Reynolds number is 1562.5 and the conservative "
                "laminar entrance-length estimate 0.05*Re*diameter is at most 7.82 cm.",
                "Liquid density is 1000 kg/m^3, viscosity is shear independent at each "
                "selected setting, and temperature is constant during a trial.",
                "Tube radius is uniform, walls are rigid and no slip, and pressure losses "
                "outside the two taps are excluded from the reported pressure drop.",
            ),
        ),
        "counterfactual": MatchedTruth(
            parameters={
                "reference_flow_rate_ml_per_s": _REFERENCE_FLOW_RATE_ML_PER_S,
                "pressure_exponent": 1.0,
                "radius_exponent": 3.0,
                "length_exponent": -1.0,
                "viscosity_exponent": -1.0,
            },
            discovery_outputs={
                "flow_rate_ml_per_s": _expression(
                    _REFERENCE_FLOW_RATE_ML_PER_S, 1.0, 3.0, -1.0, -1.0
                )
            },
            applicability=(
                "Steady, fully developed laminar transport in the same circular geometry, "
                "with a benchmark-authored wall-coupled mechanism producing exact cubic "
                "radius scaling over the declared range.",
            ),
            fixed_conditions=(
                "The first pressure tap is 10 cm downstream of the conditioned inlet; "
                "the selected-world flow rates imply Reynolds numbers no larger than "
                "1562.5 and an entrance-length estimate below 7.82 cm.",
                "Liquid density is 1000 kg/m^3, bulk viscosity is shear independent at each "
                "selected setting, and temperature is constant during a trial.",
                "The authored wall mechanism, rather than inlet loss or a changing tube "
                "shape, is the sole origin of the radius-exponent change.",
            ),
        ),
    },
    diagnostic_conditions=(
        {"pressure_drop_kpa": 10.0, "tube_radius_mm": 0.25, "tube_length_cm": 20.0, "viscosity_mpa_s": 1.0},
        {"pressure_drop_kpa": 10.0, "tube_radius_mm": 0.375, "tube_length_cm": 20.0, "viscosity_mpa_s": 1.0},
        {"pressure_drop_kpa": 10.0, "tube_radius_mm": 0.5, "tube_length_cm": 20.0, "viscosity_mpa_s": 1.0},
        {"pressure_drop_kpa": 2.0, "tube_radius_mm": 0.5, "tube_length_cm": 20.0, "viscosity_mpa_s": 1.0},
        {"pressure_drop_kpa": 6.0, "tube_radius_mm": 0.5, "tube_length_cm": 20.0, "viscosity_mpa_s": 1.0},
        {"pressure_drop_kpa": 10.0, "tube_radius_mm": 0.5, "tube_length_cm": 50.0, "viscosity_mpa_s": 1.0},
        {"pressure_drop_kpa": 10.0, "tube_radius_mm": 0.5, "tube_length_cm": 20.0, "viscosity_mpa_s": 3.0},
        {"pressure_drop_kpa": 7.0, "tube_radius_mm": 0.4, "tube_length_cm": 35.0, "viscosity_mpa_s": 2.0},
    ),
    hidden_conditions=(
        {"pressure_drop_kpa": 3.0, "tube_radius_mm": 0.27, "tube_length_cm": 24.0, "viscosity_mpa_s": 1.2},
        {"pressure_drop_kpa": 9.0, "tube_radius_mm": 0.31, "tube_length_cm": 46.0, "viscosity_mpa_s": 2.7},
        {"pressure_drop_kpa": 5.0, "tube_radius_mm": 0.36, "tube_length_cm": 28.0, "viscosity_mpa_s": 1.8},
        {"pressure_drop_kpa": 8.0, "tube_radius_mm": 0.4, "tube_length_cm": 38.0, "viscosity_mpa_s": 1.4},
        {"pressure_drop_kpa": 4.0, "tube_radius_mm": 0.43, "tube_length_cm": 50.0, "viscosity_mpa_s": 2.2},
        {"pressure_drop_kpa": 7.0, "tube_radius_mm": 0.47, "tube_length_cm": 32.0, "viscosity_mpa_s": 2.8},
        {"pressure_drop_kpa": 9.5, "tube_radius_mm": 0.49, "tube_length_cm": 42.0, "viscosity_mpa_s": 1.6},
    ),
    credits=(
        SourceCredit(
            citation=(
                "Gotthilf Hagen, Ueber die Bewegung des Wassers in engen "
                "cylindrischen Roehren (1839), Annalen der Physik 122, 423-442."
            ),
            url="https://doi.org/10.1002/andp.18391220304",
            role="Primary independent experimental source for capillary-flow scaling.",
        ),
        SourceCredit(
            citation=(
                "Jean-Leonard-Marie Poiseuille, Recherches experimentales sur le "
                "mouvement des liquides dans les tubes de tres-petits diametres "
                "(1840-1844)."
            ),
            url="https://www.bibnum.education.fr/sites/default/files/168-textepoiseuille.pdf",
            role=(
                "Primary experimental memoir credited for pressure, length, diameter, "
                "and temperature/viscosity dependencies."
            ),
        ),
    ),
    counterfactual_change=(
        "Only the normalized tube-radius exponent changes from 4 to 3. Pressure, "
        "length, viscosity, and reference-rate relations remain fixed."
    ),
    common_notes=DEFAULT_MATCHED_NOTES
    + (
        "The liquid density, inlet preparation, wall preparation, and pressure-tap "
        "geometry are fixed; the 10 cm inlet-to-first-tap distance is not a Player "
        "control, and the tap separation defines the reported pressure-drop section.",
    ),
)


def make_poiseuille_flow_case(
    world: str = "historical",
    track: BenchmarkTrack = BenchmarkTrack.IDENTIFICATION,
) -> BenchmarkCase:
    return make_matched_case(POISEUILLE_FLOW_SPEC, world, track)


__all__ = ["POISEUILLE_FLOW_SPEC", "make_poiseuille_flow_case"]
