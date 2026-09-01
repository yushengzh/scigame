"""Matched thin-foil scattering worlds inspired by Geiger, Marsden, and Rutherford."""

from __future__ import annotations

import math
from typing import Any, Mapping

from role_benchmark.models import BenchmarkTrack, ControlSpec, ReadoutSpec
from role_benchmark.protocols import BenchmarkCase

from .matched import DEFAULT_MATCHED_NOTES, IdentificationParameterSpec, MATCHED_WORLDS, MatchedFamilySpec, MatchedTruth, SourceCredit, make_matched_case


RUTHERFORD_SCATTERING_WORLDS = MATCHED_WORLDS
_APPARATUS = "alpha_foil_scattering_scope"
_READOUT = "scattered_count_rate_cpm"
_REFERENCE_ANGLE_DEG = 60.0
_REFERENCES = {
    "foil_atomic_number": 79.0,
    "target_areal_number_density_relative": 1.0,
    "exposure_relative": 1.0,
}
_EXPONENTS = {
    "foil_atomic_number": "atomic_number_exponent",
    "target_areal_number_density_relative": "areal_number_density_exponent",
    "exposure_relative": "exposure_exponent",
}

_CONTROLS = (
    ControlSpec("scattering_angle_deg", "Detector angle relative to the incident beam.", "degree", 20.0, 160.0),
    ControlSpec("foil_atomic_number", "Atomic number of the available foil.", allowed_values=(13, 29, 47, 79)),
    ControlSpec(
        "target_areal_number_density_relative",
        "Calibrated number of target nuclei per unit beam area relative to the reference target.",
        "relative",
        0.10,
        4.00,
    ),
    ControlSpec(
        "exposure_relative",
        "Time-averaged incident alpha-particle flux rate through the target region, relative to the reference beam rate.",
        "relative",
        0.25,
        2.00,
    ),
)
_READOUTS = (
    ReadoutSpec(
        _READOUT,
        "Background-corrected mean alpha-particle count rate within the detector's narrow angular acceptance centered on the selected angle.",
        "counts/min",
        0.1,
    ),
)


def _predict(parameters: Mapping[str, float], controls: Mapping[str, Any]) -> Mapping[str, float]:
    angular_ratio = math.sin(math.radians(float(controls["scattering_angle_deg"]) / 2.0)) / math.sin(
        math.radians(_REFERENCE_ANGLE_DEG / 2.0)
    )
    value = float(parameters["reference_count_rate_cpm"])
    for control, reference in _REFERENCES.items():
        value *= (float(controls[control]) / reference) ** float(parameters[_EXPONENTS[control]])
    value *= angular_ratio ** float(parameters["sine_half_angle_exponent"])
    return {_READOUT: value}


def _expression(parameters: Mapping[str, float]) -> Mapping[str, Any]:
    angular_ratio = {
        "op": "divide",
        "args": [
            {
                "op": "sin",
                "args": [
                    {
                        "op": "multiply",
                        "args": [{"var": "scattering_angle_deg"}, math.pi / 360.0],
                    }
                ],
            },
            math.sin(math.radians(_REFERENCE_ANGLE_DEG / 2.0)),
        ],
    }
    return {
        "op": "multiply",
        "args": [parameters["reference_count_rate_cpm"]]
        + [
            {
                "op": "power",
                "args": [
                    {"op": "divide", "args": [{"var": control}, reference]},
                    parameters[_EXPONENTS[control]],
                ],
            }
            for control, reference in _REFERENCES.items()
        ]
        + [{"op": "power", "args": [angular_ratio, parameters["sine_half_angle_exponent"]]}],
    }


_HISTORICAL: Mapping[str, float] = {
    "reference_count_rate_cpm": 120.0,
    "atomic_number_exponent": 2.0,
    "areal_number_density_exponent": 1.0,
    "exposure_exponent": 1.0,
    "sine_half_angle_exponent": -4.0,
}
_COUNTERFACTUAL: Mapping[str, float] = {**_HISTORICAL, "sine_half_angle_exponent": -3.0}
_HIDDEN = (
    (25.0, 79, 0.30, 1.40), (40.0, 47, 1.10, 0.70), (55.0, 29, 1.50, 1.20),
    (70.0, 79, 0.20, 0.50), (85.0, 47, 0.80, 1.80), (105.0, 29, 1.70, 1.50),
    (125.0, 13, 1.50, 2.00), (145.0, 79, 1.80, 0.40),
)
_SHARED_FIXED_CONDITIONS = (
    "Incident alpha-particle energy, beam geometry, target orientation, detector efficiency, and narrow angular acceptance remain fixed.",
    "The exposure_relative control denotes incident particle flux rate, not accumulated fluence; acquisition duration is fixed for the count-rate readout.",
    "Instrumental background is subtracted and multiple scattering remains negligible.",
)

RUTHERFORD_SCATTERING_SPEC = MatchedFamilySpec(
    family="rutherford_scattering",
    case_id_prefix="foil_scattering.alpha",
    swap_public_instance_ids=True,
    response_title="the alpha-particle scattering response",
    apparatus_name=_APPARATUS,
    apparatus_description=(
        "A collimated alpha source, thin foils, a rotatable narrow-acceptance detector, "
        "and an incident particle-rate monitor."
    ),
    background=(
        "A collimated alpha beam strikes a thin metal foil. A rotatable detector "
        "counts particles emerging at selected angles. Vary material, calibrated "
        "target-nucleus areal density, incident beam-rate setting, and angle to infer the scattering "
        "response."
    ),
    initial_observations=(
        "Most incident particles are not detected at large angles.",
        "Rare large deflections are nevertheless reproducible above background.",
    ),
    controls=_CONTROLS,
    readouts=_READOUTS,
    identification_model="rutherford_scattering_law",
    identification_parameter_specs=(
        IdentificationParameterSpec(
            "reference_count_rate_cpm",
            "Background-corrected count rate at scattering_angle_deg = 60 degrees, foil_atomic_number = 79, and unit relative target density and incident flux rate.",
            "counts/min",
            0.0,
            None,
        ),
        IdentificationParameterSpec(
            "atomic_number_exponent",
            "Power-law exponent of foil_atomic_number / 79.",
            "1",
            -8.0,
            8.0,
        ),
        IdentificationParameterSpec(
            "areal_number_density_exponent",
            "Power-law exponent of target_areal_number_density_relative.",
            "1",
            -8.0,
            8.0,
        ),
        IdentificationParameterSpec(
            "exposure_exponent",
            "Power-law exponent of exposure_relative, where that control denotes relative incident alpha-particle flux rate.",
            "1",
            -8.0,
            8.0,
        ),
        IdentificationParameterSpec(
            "sine_half_angle_exponent",
            "Power-law exponent of sin(scattering_angle_deg / 2) / sin(30 degrees).",
            "1",
            -8.0,
            8.0,
        ),
    ),
    identification_formula=(
        "rate=reference_count_rate_cpm*(foil_atomic_number/79)^atomic_number_exponent*"
        "target_areal_number_density_relative^areal_number_density_exponent*"
        "exposure_relative^exposure_exponent*"
        "(sin(scattering_angle_deg/2)/sin(30 deg))^sine_half_angle_exponent."
    ),
    predict=_predict,
    truths={
        "historical": MatchedTruth(
            _HISTORICAL,
            {_READOUT: _expression(_HISTORICAL)},
            applicability=(
                "Elastic, nonrelativistic, unscreened Coulomb scattering of alpha particles by effectively stationary nuclei in a thin single-scattering target.",
                "Detector acceptance is narrow enough that its rate is proportional to the differential cross section at the selected central angle.",
            ),
            fixed_conditions=_SHARED_FIXED_CONDITIONS
            + (
                "Nuclear recoil, alpha energy loss, electron screening, and finite nuclear-size corrections are negligible over the encoded domain.",
            ),
        ),
        "counterfactual": MatchedTruth(
            _COUNTERFACTUAL,
            {_READOUT: _expression(_COUNTERFACTUAL)},
            applicability=(
                "Authored alternate central-scattering interaction with the encoded sine-half-angle exponent in the same thin-target, single-scattering regime.",
                "Detector acceptance is narrow enough that its rate represents the response at the selected central angle.",
            ),
            fixed_conditions=_SHARED_FIXED_CONDITIONS
            + (
                "The alternate angular kernel is the complete scattering response; recoil, energy-loss, screening, and finite-size corrections are absent.",
            ),
        ),
    },
    diagnostic_conditions=(
        {"scattering_angle_deg": 20.0, "foil_atomic_number": 13, "target_areal_number_density_relative": 0.10, "exposure_relative": 0.25},
        {"scattering_angle_deg": 60.0, "foil_atomic_number": 29, "target_areal_number_density_relative": 1.00, "exposure_relative": 0.75},
        {"scattering_angle_deg": 110.0, "foil_atomic_number": 47, "target_areal_number_density_relative": 2.40, "exposure_relative": 1.25},
        {"scattering_angle_deg": 160.0, "foil_atomic_number": 79, "target_areal_number_density_relative": 4.00, "exposure_relative": 2.00},
    ),
    hidden_conditions=tuple(
        {
            "scattering_angle_deg": angle,
            "foil_atomic_number": atomic_number,
            "target_areal_number_density_relative": areal_density,
            "exposure_relative": exposure,
        }
        for angle, atomic_number, areal_density, exposure in _HIDDEN
    ),
    credits=(
        SourceCredit(
            "Hans Geiger and Ernest Marsden, On a Diffuse Reflection of the Alpha Particles (1909)",
            "https://doi.org/10.1098/rspa.1909.0054",
            "Source for the observation of rare large-angle alpha-particle scattering.",
        ),
        SourceCredit(
            "Ernest Rutherford, The Scattering of Alpha and Beta Particles by Matter and the Structure of the Atom (1911)",
            "https://doi.org/10.1080/14786440508637080",
            "Source for the central-scattering theory underlying the angular and atomic-number dependence.",
        ),
        SourceCredit(
            "Hans Geiger and Ernest Marsden, The Laws of Deflexion of Alpha Particles through Large Angles (1913)",
            "https://doi.org/10.1080/14786440408634197",
            "Source for quantitative tests of angular, material, and target-amount dependences.",
        ),
    ),
    counterfactual_change="Only the sine-half-angle exponent changes from -4.0 to -3.0.",
    common_notes=DEFAULT_MATCHED_NOTES + (
        "All targets remain in the thin, single-scattering regime.",
        "Source energy, detector angular acceptance, and beam geometry remain fixed.",
        "The detector acceptance is sufficiently narrow that its count rate represents the response at the selected central angle.",
        "The exposure_relative setting is a time-averaged incident particle flux rate relative to the reference beam, not accumulated fluence.",
        "Target areal number density is independently calibrated, so equal settings mean equal target nuclei per unit beam area across materials.",
        "Available foil atomic numbers are 13, 29, 47, and 79.",
    ),
    budget=10,
    max_replicates=15,
    relative_tolerance=0.05,
)


def make_rutherford_scattering_case(
    world: str = "historical", track: BenchmarkTrack = BenchmarkTrack.IDENTIFICATION
) -> BenchmarkCase:
    return make_matched_case(RUTHERFORD_SCATTERING_SPEC, world, track)


__all__ = ["RUTHERFORD_SCATTERING_SPEC", "RUTHERFORD_SCATTERING_WORLDS", "make_rutherford_scattering_case"]
