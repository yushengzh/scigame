"""Matched beer lambert benchmark family."""

from __future__ import annotations

import math
from typing import Any, Mapping

from role_benchmark.models import BenchmarkTrack, ControlSpec, ReadoutSpec
from role_benchmark.protocols import BenchmarkCase

from ._expressions import exp, mul, neg, power, var
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
    attenuation = parameters["attenuation_coefficient"] * float(
        controls["concentration_mm"]
    ) * float(controls["path_length_cm"]) ** parameters["path_exponent"]
    return {
        "transmitted_power_uw": float(controls["incident_power_uw"])
        * math.exp(-attenuation)
    }


def _expression(coefficient: float, path_exponent: float) -> Mapping[str, Any]:
    return mul(
        var("incident_power_uw"),
        exp(
            neg(
                mul(
                    coefficient,
                    var("concentration_mm"),
                    power(var("path_length_cm"), path_exponent),
                )
            )
        ),
    )


BEER_LAMBERT_SPEC = MatchedFamilySpec(
    family="beer_lambert",
    case_id_prefix="solution.attenuation",
    response_title="the optical attenuation relation",
    apparatus_name="solution_absorption_cell",
    apparatus_description=(
        "A monochromatic source, variable-power attenuator, calibrated solution "
        "cell with selectable path length, and transmitted-power detector."
    ),
    background=(
        "Monochromatic light passes through a clear absorbing preparation loaded "
        "reproducibly into interchangeable cells. The preparation is stable during "
        "a trial and the listed range shows no detectable fluorescence or scattering. "
        "Determine how transmitted power depends on incident power, concentration, "
        "and optical path length."
    ),
    initial_observations=(
        "The solution does not fluoresce or scatter within the available range.",
    ),
    controls=(
        ControlSpec("incident_power_uw", "Incident optical power.", "uW", 20.0, 100.0),
        ControlSpec("concentration_mm", "Absorber concentration.", "mM", 0.05, 1.0),
        ControlSpec("path_length_cm", "Optical path through solution.", "cm", 0.25, 2.0),
    ),
    readouts=(
        ReadoutSpec(
            "transmitted_power_uw",
            "Optical power leaving the solution cell.",
            "uW",
            0.01,
        ),
    ),
    identification_model="exponential_attenuation",
    identification_parameter_specs=(
        IdentificationParameterSpec(
            "attenuation_coefficient",
            "Napierian attenuation coefficient multiplying concentration_mm and the normalized path-length term.",
            "mM^-1",
            0.0,
            None,
        ),
        IdentificationParameterSpec(
            "path_exponent",
            "Power-law exponent of path_length_cm / 1 cm in the optical-depth term.",
            "1",
            -8.0,
            8.0,
        ),
    ),
    identification_formula=(
        "I_out = incident_power_uw*exp[-attenuation_coefficient*"
        "concentration_mm*(path_length_cm/1 cm)^path_exponent], where "
        "attenuation_coefficient is Napierian and has units mM^-1"
    ),
    predict=_predict,
    truths={
        "historical": MatchedTruth(
            parameters={"attenuation_coefficient": 0.6, "path_exponent": 1.0},
            discovery_outputs={
                "transmitted_power_uw": _expression(0.6, 1.0)
            },
            applicability=(
                "Monochromatic transmission through a homogeneous, stable, non-scattering and non-fluorescent absorbing solution in the linear Beer-Lambert regime over the declared ranges.",
            ),
            fixed_conditions=(
                "The absorber's Napierian attenuation coefficient is constant, concentration is spatially uniform, and absorbers do not interact or saturate over the encoded domain.",
                "Cell-window and interface losses are negligible or calibrated out, and the incident and transmitted power channels are linear on the same scale.",
                "Wavelength, solvent, temperature, cell shape apart from selected optical path, and preparation protocol remain fixed.",
            ),
        ),
        "counterfactual": MatchedTruth(
            parameters={"attenuation_coefficient": 0.6, "path_exponent": 2.0},
            discovery_outputs={
                "transmitted_power_uw": _expression(0.6, 2.0)
            },
            applicability=(
                "Benchmark-authored homogeneous absorbing preparation with optical depth exactly proportional to concentration and the square of normalized path length over the declared ranges.",
            ),
            fixed_conditions=(
                "The quadratic path response is a fundamental selected-world attenuation law rather than a concentration gradient, scattering, fluorescence, reflection, detector nonlinearity, or saturation artifact.",
                "Cell-window and interface losses are negligible or calibrated out, and the incident and transmitted power channels are linear on the same scale.",
                "Wavelength, solvent, temperature, geometrically matched cell preparation, and absorber stability remain fixed.",
            ),
        ),
    },
    diagnostic_conditions=(
        {"incident_power_uw": 50.0, "concentration_mm": 0.5, "path_length_cm": 0.25},
        {"incident_power_uw": 50.0, "concentration_mm": 0.5, "path_length_cm": 0.5},
        {"incident_power_uw": 50.0, "concentration_mm": 0.5, "path_length_cm": 1.0},
        {"incident_power_uw": 50.0, "concentration_mm": 0.5, "path_length_cm": 2.0},
        {"incident_power_uw": 20.0, "concentration_mm": 0.5, "path_length_cm": 1.0},
        {"incident_power_uw": 100.0, "concentration_mm": 0.5, "path_length_cm": 1.0},
        {"incident_power_uw": 60.0, "concentration_mm": 0.05, "path_length_cm": 1.0},
        {"incident_power_uw": 60.0, "concentration_mm": 1.0, "path_length_cm": 1.0},
    ),
    hidden_conditions=(
        {"incident_power_uw": 35.0, "concentration_mm": 0.08, "path_length_cm": 0.4},
        {"incident_power_uw": 90.0, "concentration_mm": 0.3, "path_length_cm": 1.7},
        {"incident_power_uw": 55.0, "concentration_mm": 0.55, "path_length_cm": 0.8},
        {"incident_power_uw": 75.0, "concentration_mm": 0.8, "path_length_cm": 1.3},
        {"incident_power_uw": 25.0, "concentration_mm": 0.7, "path_length_cm": 0.55},
        {"incident_power_uw": 100.0, "concentration_mm": 0.9, "path_length_cm": 1.85},
        {"incident_power_uw": 48.0, "concentration_mm": 1.0, "path_length_cm": 1.05},
    ),
    credits=(
        SourceCredit(
            citation=(
                "Pierre Bouguer, Essai d'optique sur la gradation de la "
                "lumiere (1729)."
            ),
            url="https://books.google.com/books?id=um1bAAAAQAAJ",
            role=(
                "Primary early source for exponential attenuation with optical "
                "path; it predates the concentration extension."
            ),
        ),
        SourceCredit(
            citation="Johann Heinrich Lambert, Photometria (1760).",
            url="https://doi.org/10.3931/e-rara-9488",
            role=(
                "Primary source credited for the path-length attenuation law and "
                "its explicit mathematical treatment."
            ),
        ),
        SourceCredit(
            citation=(
                "August Beer, Bestimmung der Absorption des rothen Lichts in "
                "farbigen Fluessigkeiten (1852), Annalen der Physik 162, 78-88."
            ),
            url="https://doi.org/10.1002/andp.18521620505",
            role=(
                "Primary source credited for extending optical attenuation to "
                "solution concentration."
            ),
        ),
    ),
    counterfactual_change=(
        "Only the normalized optical-path exponent changes from 1 to 2; incident-"
        "power proportionality, concentration dependence, and attenuation scale stay fixed."
    ),
    common_notes=DEFAULT_MATCHED_NOTES
    + (
        "Incident and transmitted powers use the same linear detector scale; cell "
        "geometry other than the selected path and the preparation protocol are fixed.",
    ),
)


def make_beer_lambert_case(
    world: str = "historical",
    track: BenchmarkTrack = BenchmarkTrack.IDENTIFICATION,
) -> BenchmarkCase:
    return make_matched_case(BEER_LAMBERT_SPEC, world, track)


__all__ = ["BEER_LAMBERT_SPEC", "make_beer_lambert_case"]
