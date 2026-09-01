"""Matched activity-decay worlds inspired by Rutherford and Soddy."""

from __future__ import annotations

from typing import Any, Mapping

from role_benchmark.models import BenchmarkTrack, ControlSpec, ReadoutSpec
from role_benchmark.protocols import BenchmarkCase

from .matched import DEFAULT_MATCHED_NOTES, IdentificationParameterSpec, MATCHED_WORLDS, MatchedFamilySpec, MatchedTruth, SourceCredit, make_matched_case


RADIOACTIVE_DECAY_WORLDS = MATCHED_WORLDS
_APPARATUS = "shielded_radiation_counter"
_READOUT = "count_rate_cpm"
_REFERENCE_SAMPLE_MASS_MG = 1.0

_CONTROLS = (
    ControlSpec("elapsed_time_min", "Elapsed time since chemical isolation.", "min", 0.0, 300.0),
    ControlSpec("sample_mass_mg", "Calibrated active source-material mass loaded into the holder.", "mg", 0.25, 4.00),
)
_READOUTS = (ReadoutSpec(_READOUT, "Mean detected count rate including background.", "counts/min", 1.0),)


def _predict(parameters: Mapping[str, float], controls: Mapping[str, Any]) -> Mapping[str, float]:
    value = float(parameters["background_cpm"]) + (
        float(parameters["reference_activity_cpm"])
        * (float(controls["sample_mass_mg"]) / _REFERENCE_SAMPLE_MASS_MG)
        ** float(parameters["mass_exponent"])
        * 2.0
        ** (
            -float(controls["elapsed_time_min"])
            / float(parameters["half_life_min"])
        )
    )
    return {_READOUT: value}


def _expression(parameters: Mapping[str, float]) -> Mapping[str, Any]:
    return {
        "op": "add",
        "args": [
            parameters["background_cpm"],
            {
                "op": "multiply",
                "args": [
                    parameters["reference_activity_cpm"],
                    {
                        "op": "power",
                        "args": [
                            {
                                "op": "divide",
                                "args": [
                                    {"var": "sample_mass_mg"},
                                    _REFERENCE_SAMPLE_MASS_MG,
                                ],
                            },
                            parameters["mass_exponent"],
                        ],
                    },
                    {
                        "op": "power",
                        "args": [
                            2.0,
                            {
                                "op": "negate",
                                "args": [
                                    {
                                        "op": "divide",
                                        "args": [{"var": "elapsed_time_min"}, parameters["half_life_min"]],
                                    }
                                ],
                            },
                        ],
                    },
                ],
            },
        ],
    }


_HISTORICAL: Mapping[str, float] = {
    "background_cpm": 20.0,
    "reference_activity_cpm": 800.0,
    "half_life_min": 60.0,
    "mass_exponent": 1.0,
}
_COUNTERFACTUAL: Mapping[str, float] = {**_HISTORICAL, "mass_exponent": 0.70}
_HIDDEN = (
    (5.0, 0.30), (25.0, 1.70), (55.0, 0.80), (90.0, 3.20),
    (135.0, 0.45), (180.0, 2.40), (245.0, 1.10), (295.0, 3.80),
)
_SHARED_FIXED_CONDITIONS = (
    "All preparations have the same radionuclide composition, chemical protocol, sealed-holder geometry, and isolation-time convention.",
    "Counter position, counting interval, detection threshold, and separately calibrated background remain fixed.",
)

RADIOACTIVE_DECAY_SPEC = MatchedFamilySpec(
    family="radioactive_decay",
    case_id_prefix="decaying_sample.counter",
    response_title="the radioactive count-rate response",
    apparatus_name=_APPARATUS,
    apparatus_description="Sealed sample holders, a shielded counter, timer, and background calibration.",
    background=(
        "Radioisotope-bearing preparations made by the same protocol are sealed in "
        "identical holders and observed with a shielded counter. Vary elapsed time "
        "and calibrated active source-material mass, then infer how the measured count rate changes."
    ),
    initial_observations=(
        "The count rate decreases after isolation even though the holder remains sealed.",
        "A separately measured background remains present at late times.",
    ),
    controls=_CONTROLS,
    readouts=_READOUTS,
    identification_model="single_exponential_decay",
    identification_parameter_specs=(
        IdentificationParameterSpec(
            "background_cpm",
            "Additive detector background count rate.",
            "counts/min",
            0.0,
            None,
        ),
        IdentificationParameterSpec(
            "reference_activity_cpm",
            "Net source count rate above background at elapsed_time_min = 0 and sample_mass_mg = 1 mg.",
            "counts/min",
            0.0,
            None,
        ),
        IdentificationParameterSpec(
            "half_life_min",
            "Elapsed time associated with a factor-of-two decrease in the net time-dependent response.",
            "min",
            0.01,
            None,
        ),
        IdentificationParameterSpec(
            "mass_exponent",
            "Power-law exponent of sample_mass_mg / 1 mg in the net source response.",
            "1",
            -8.0,
            8.0,
        ),
    ),
    identification_formula=(
        "rate=background_cpm+reference_activity_cpm*(sample_mass_mg/1 mg)^mass_exponent*"
        "2^(-elapsed_time_min/half_life_min)."
    ),
    predict=_predict,
    truths={
        "historical": MatchedTruth(
            _HISTORICAL,
            {_READOUT: _expression(_HISTORICAL)},
            applicability=(
                "A single exponentially decaying radionuclide whose initial activity is proportional to calibrated active-source mass over the stated ranges.",
            ),
            fixed_conditions=_SHARED_FIXED_CONDITIONS
            + (
                "Self-attenuation and geometry-dependent collection are negligible or mass-independent, detection efficiency is linear, and counter dead time is negligible.",
            ),
        ),
        "counterfactual": MatchedTruth(
            _COUNTERFACTUAL,
            {_READOUT: _expression(_COUNTERFACTUAL)},
            applicability=(
                "Authored alternate preparation-and-detection response with the encoded mass exponent over the same elapsed-time and mass ranges.",
            ),
            fixed_conditions=_SHARED_FIXED_CONDITIONS
            + (
                "The mass exponent is the complete effective attenuation-and-collection response; detection remains linear in the resulting incident count rate and counter dead time is negligible.",
            ),
        ),
    },
    diagnostic_conditions=(
        {"elapsed_time_min": 0.0, "sample_mass_mg": 0.25},
        {"elapsed_time_min": 60.0, "sample_mass_mg": 1.0},
        {"elapsed_time_min": 180.0, "sample_mass_mg": 2.0},
        {"elapsed_time_min": 300.0, "sample_mass_mg": 4.0},
    ),
    hidden_conditions=tuple(
        {"elapsed_time_min": elapsed, "sample_mass_mg": mass} for elapsed, mass in _HIDDEN
    ),
    credits=(
        SourceCredit(
            "Ernest Rutherford and Frederick Soddy, The Cause and Nature of Radioactivity (1902)",
            "https://www.tandfonline.com/doi/abs/10.1080/14786440209462856",
            "Source for the radioactive-transformation interpretation.",
        ),
        SourceCredit(
            "Ernest Rutherford and Frederick Soddy, Radioactive Change (1903)",
            "https://doi.org/10.1080/14786440309462960",
            "Source for the quantitative time law underlying exponential activity decay.",
        ),
    ),
    counterfactual_change="Only the normalized sample-mass exponent changes from 1.00 to 0.70.",
    common_notes=DEFAULT_MATCHED_NOTES + (
        "Every preparation uses the same source material and loading protocol.",
        "Each holder remains sealed; holder geometry, counter position, and separately "
        "calibrated background are fixed.",
        "Mass-dependent transport, attenuation, or effective collection is not assumed "
        "away; its net effect is part of the measured response to infer.",
        "The Oracle reports a deterministic mean rate, not individual random counts.",
    ),
    budget=8,
    max_replicates=20,
    relative_tolerance=0.04,
)


def make_radioactive_decay_case(
    world: str = "historical", track: BenchmarkTrack = BenchmarkTrack.IDENTIFICATION
) -> BenchmarkCase:
    return make_matched_case(RADIOACTIVE_DECAY_SPEC, world, track)


__all__ = ["RADIOACTIVE_DECAY_SPEC", "RADIOACTIVE_DECAY_WORLDS", "make_radioactive_decay_case"]
