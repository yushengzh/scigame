"""Matched idealized Young double-slit family for both benchmark tracks."""

from __future__ import annotations

from typing import Any, Mapping

from role_benchmark.models import BenchmarkTrack, ControlSpec, ReadoutSpec
from role_benchmark.protocols import BenchmarkCase

from .matched import (
    DEFAULT_MATCHED_NOTES,
    IdentificationParameterSpec,
    MATCHED_WORLDS,
    MatchedFamilySpec,
    MatchedTruth,
    SourceCredit,
    make_matched_case,
)


YOUNG_DOUBLE_SLIT_WORLDS = MATCHED_WORLDS


def _predict(
    parameters: Mapping[str, float], controls: Mapping[str, Any]
) -> Mapping[str, float]:
    return {
        "fringe_spacing_mm": parameters["reference_spacing_mm"]
        * (float(controls["wavelength_nm"]) / 550.0)
        ** parameters["wavelength_exponent"]
        * (float(controls["screen_distance_m"]) / 1.0)
        ** parameters["screen_distance_exponent"]
        * (float(controls["slit_separation_mm"]) / 0.50)
        ** parameters["slit_separation_exponent"]
    }


def _expression(separation_exponent: float) -> Mapping[str, Any]:
    factors = (("wavelength_nm", 550.0, 1.0), ("screen_distance_m", 1.0, 1.0), ("slit_separation_mm", 0.50, separation_exponent))
    return {
        "op": "multiply",
        "args": [
            1.10,
            *(
                {
                    "op": "power",
                    "args": [
                        {"op": "divide", "args": [{"var": name}, reference]},
                        exponent,
                    ],
                }
                for name, reference, exponent in factors
            ),
        ],
    }


_HISTORICAL = {
    "reference_spacing_mm": 1.10,
    "wavelength_exponent": 1.0,
    "screen_distance_exponent": 1.0,
    "slit_separation_exponent": -1.0,
}
_COUNTERFACTUAL = {
    **_HISTORICAL,
    "slit_separation_exponent": -0.5,
}
_APPLICABILITY = (
    "Central paraxial fringes from two narrow, mutually coherent slits over the stated control ranges.",
)
_FIXED_CONDITIONS = (
    "The screen is normal to the incident beam and remains much farther from the slits than their separation.",
    "Slit widths, illumination coherence, polarization, and alignment remain fixed while only the listed controls vary.",
)


YOUNG_DOUBLE_SLIT_SPEC = MatchedFamilySpec(
    family="young_double_slit",
    case_id_prefix="optical.interference",
    swap_public_instance_ids=True,
    response_title="the double-slit fringe response",
    apparatus_name="double_slit_screen",
    apparatus_description=(
        "A monochromatic source coherently illuminates two narrow parallel slits, "
        "with a movable screen and a scale for adjacent bright fringes."
    ),
    background=(
        "Monochromatic light passes through two narrow parallel slits and forms "
        "alternating bright and dark bands on a screen. Vary only the listed "
        "controls and infer a predictive law for adjacent bright-fringe spacing."
    ),
    initial_observations=(
        "Blocking either slit removes the fine two-slit fringe train, although a broad single-slit diffraction envelope may remain.",
        "Changing the geometry shifts the bright bands, but the dependence is not given.",
    ),
    controls=(
        ControlSpec(
            name="wavelength_nm",
            description="Wavelength of the monochromatic incident light.",
            unit="nm",
            minimum=400.0,
            maximum=700.0,
        ),
        ControlSpec(
            name="screen_distance_m",
            description="Distance from the slits to the observation screen.",
            unit="m",
            minimum=0.50,
            maximum=3.00,
        ),
        ControlSpec(
            name="slit_separation_mm",
            description="Center-to-center separation of the two narrow slits.",
            unit="mm",
            minimum=0.10,
            maximum=1.00,
        ),
    ),
    readouts=(
        ReadoutSpec(
            name="fringe_spacing_mm",
            description="Mean separation between adjacent bright fringes.",
            unit="mm",
            resolution=0.01,
        ),
    ),
    identification_model="double_slit_power_law",
    identification_parameter_specs=(
        IdentificationParameterSpec(
            "reference_spacing_mm",
            "Adjacent bright-fringe spacing at wavelength_nm = 550 nm, screen_distance_m = 1 m, and slit_separation_mm = 0.50 mm.",
            "mm",
            0.0,
            None,
        ),
        IdentificationParameterSpec(
            "wavelength_exponent",
            "Power-law exponent of wavelength_nm / 550 nm.",
            "1",
            -8.0,
            8.0,
        ),
        IdentificationParameterSpec(
            "screen_distance_exponent",
            "Power-law exponent of screen_distance_m / 1 m.",
            "1",
            -8.0,
            8.0,
        ),
        IdentificationParameterSpec(
            "slit_separation_exponent",
            "Power-law exponent of slit_separation_mm / 0.50 mm.",
            "1",
            -8.0,
            8.0,
        ),
    ),
    identification_formula=(
        "spacing = reference_spacing_mm * (wavelength_nm / 550 nm)^wavelength_exponent "
        "* (screen_distance_m / 1 m)^screen_distance_exponent * "
        "(slit_separation_mm / 0.50 mm)^slit_separation_exponent."
    ),
    predict=_predict,
    truths={
        "historical": MatchedTruth(
            _HISTORICAL,
            {"fringe_spacing_mm": _expression(-1.0)},
            applicability=_APPLICABILITY,
            fixed_conditions=_FIXED_CONDITIONS,
        ),
        "counterfactual": MatchedTruth(
            _COUNTERFACTUAL,
            {"fringe_spacing_mm": _expression(-0.5)},
            applicability=_APPLICABILITY,
            fixed_conditions=_FIXED_CONDITIONS,
        ),
    },
    diagnostic_conditions=(
        {"wavelength_nm": 550.0, "screen_distance_m": 1.0, "slit_separation_mm": 0.50},
        {"wavelength_nm": 400.0, "screen_distance_m": 0.50, "slit_separation_mm": 0.10},
        {"wavelength_nm": 700.0, "screen_distance_m": 3.00, "slit_separation_mm": 1.00},
    ),
    hidden_conditions=(
        {"wavelength_nm": 420.0, "screen_distance_m": 0.70, "slit_separation_mm": 0.25},
        {"wavelength_nm": 465.0, "screen_distance_m": 1.25, "slit_separation_mm": 0.80},
        {"wavelength_nm": 510.0, "screen_distance_m": 2.60, "slit_separation_mm": 0.35},
        {"wavelength_nm": 555.0, "screen_distance_m": 0.90, "slit_separation_mm": 0.60},
        {"wavelength_nm": 605.0, "screen_distance_m": 1.80, "slit_separation_mm": 0.45},
        {"wavelength_nm": 650.0, "screen_distance_m": 2.90, "slit_separation_mm": 0.90},
        {"wavelength_nm": 690.0, "screen_distance_m": 1.40, "slit_separation_mm": 0.20},
    ),
    credits=(
        SourceCredit(
            citation=(
                "Thomas Young, Bakerian lecture Experiments and Calculations "
                "Relative to Physical Optics (read 1803; published 1804)"
            ),
            url="https://makingscience.royalsociety.org/items/l-and-p_12_60/paper-experiments-and-observations-relative-to-physical-optica-bakerian-lecture-by-thomas-young",
            role=(
                "Historical source for optical interference. The modern two-slit "
                "geometry, paraxial formula, and metric calibration are benchmark "
                "idealizations rather than a literal reconstruction of Young's apparatus."
            ),
        ),
    ),
    counterfactual_change=(
        "Only the slit-separation exponent changes from -1 to -0.5; the reference "
        "condition and wavelength/distance dependences remain fixed."
    ),
    common_notes=DEFAULT_MATCHED_NOTES + (
        "Both narrow parallel slits are mutually coherently illuminated.",
        "Only central paraxial fringes are measured, with screen distance much larger than slit separation.",
        "The screen remains normal to the incident beam.",
    ),
    budget=8,
    max_replicates=12,
    relative_tolerance=0.03,
)


def make_young_double_slit_case(
    world: str = "historical",
    track: BenchmarkTrack = BenchmarkTrack.IDENTIFICATION,
) -> BenchmarkCase:
    return make_matched_case(YOUNG_DOUBLE_SLIT_SPEC, world, track)


__all__ = [
    "YOUNG_DOUBLE_SLIT_SPEC",
    "YOUNG_DOUBLE_SLIT_WORLDS",
    "make_young_double_slit_case",
]
