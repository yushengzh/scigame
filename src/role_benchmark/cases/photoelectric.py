"""Matched threshold-response worlds inspired by photoelectric measurements."""

from __future__ import annotations

from typing import Any, Mapping

from role_benchmark.models import BenchmarkTrack, ControlSpec, ReadoutSpec
from role_benchmark.protocols import BenchmarkCase

from .matched import DEFAULT_MATCHED_NOTES, IdentificationParameterSpec, MATCHED_WORLDS, MatchedFamilySpec, MatchedTruth, SourceCredit, make_matched_case


PHOTOELECTRIC_WORLDS = MATCHED_WORLDS
_APPARATUS = "vacuum_phototube"
_STOPPING = "stopping_potential_v"
_CURRENT = "saturation_current_ua"

_CONTROLS = (
    ControlSpec("frequency_thz", "Frequency of monochromatic incident light.", "THz", 400.0, 1000.0),
    ControlSpec(
        "absorbed_photon_flux_relative",
        "Absorbed photon rate at the cathode relative to the reference setting.",
        "relative",
        0.10,
        2.00,
    ),
)
_READOUTS = (
    ReadoutSpec(
        _STOPPING,
        "Reverse-potential magnitude needed to reduce photocurrent to zero.",
        "V",
        0.01,
    ),
    ReadoutSpec(
        _CURRENT,
        "Saturation photocurrent with all emitted electrons collected.",
        "uA",
        0.02,
    ),
)


def _predict(parameters: Mapping[str, float], controls: Mapping[str, Any]) -> Mapping[str, float]:
    excess = float(parameters["h_over_e_v_s"]) * float(controls["frequency_thz"]) * 1e12 - float(
        parameters["work_function_equivalent_v"]
    )
    return {
        _STOPPING: max(0.0, excess),
        _CURRENT: (
            float(parameters["reference_saturation_current_ua"])
            * float(controls["absorbed_photon_flux_relative"])
            if excess > 0.0
            else 0.0
        ),
    }


def _excess(parameters: Mapping[str, float]) -> Mapping[str, Any]:
    return {
        "op": "subtract",
        "args": [
            {
                "op": "multiply",
                "args": [parameters["h_over_e_v_s"], {"var": "frequency_thz"}, 1e12],
            },
            parameters["work_function_equivalent_v"],
        ],
    }


def _expressions(parameters: Mapping[str, float]) -> Mapping[str, Any]:
    return {
        _STOPPING: {"op": "maximum", "args": [0.0, _excess(parameters)]},
        _CURRENT: {
            "op": "multiply",
            "args": [
                parameters["reference_saturation_current_ua"],
                {"var": "absorbed_photon_flux_relative"},
                {"op": "step", "args": [_excess(parameters)]},
            ],
        },
    }


_HISTORICAL: Mapping[str, float] = {
    "h_over_e_v_s": 4.135667696e-15,
    "work_function_equivalent_v": 2.28,
    "reference_saturation_current_ua": 3.0,
}
_COUNTERFACTUAL: Mapping[str, float] = {**_HISTORICAL, "h_over_e_v_s": 3.20e-15}
_HIDDEN = (
    (430.0, 0.20), (520.0, 1.80), (560.0, 0.35), (610.0, 1.40),
    (690.0, 0.70), (780.0, 2.00), (890.0, 0.50), (970.0, 1.10),
)
_APPLICABILITY = (
    "Ideal single-photon photoemission over the stated monochromatic-frequency and absorbed-photon-flux ranges.",
)
_FIXED_CONDITIONS = (
    "The clean cathode has a spatially uniform, time-independent work function and no contact-potential drift.",
    "Above the selected world's emission threshold, absorbed photons have a frequency-independent emission yield and the saturation circuit collects every emitted electron.",
    "Space-charge, multiphoton, dark-current, and detector-nonlinearity effects are negligible.",
)

PHOTOELECTRIC_SPEC = MatchedFamilySpec(
    family="photoelectric",
    case_id_prefix="phototube.response",
    response_title="the phototube frequency-photon-flux response",
    apparatus_name=_APPARATUS,
    apparatus_description="A clean-cathode vacuum phototube with monochromatic illumination and electrical meters.",
    background=(
        "Monochromatic light illuminates a clean cathode in a vacuum phototube. "
        "Vary frequency and the absorbed photon rate, then use stopping potential "
        "and saturation current to explain when and how electrons are emitted."
    ),
    initial_observations=(
        "Some illumination settings produce no measurable photocurrent.",
        "When electrons are emitted, a reverse voltage can stop the current.",
    ),
    controls=_CONTROLS,
    readouts=_READOUTS,
    identification_model="einstein_photoelectric_law",
    identification_parameter_specs=(
        IdentificationParameterSpec(
            "h_over_e_v_s",
            "Coefficient converting incident-light frequency in hertz to the frequency-dependent contribution to stopping potential.",
            "V*s",
            0.0,
            None,
        ),
        IdentificationParameterSpec(
            "work_function_equivalent_v",
            "Cathode emission-energy offset divided by elementary charge.",
            "V",
            0.0,
            None,
        ),
        IdentificationParameterSpec(
            "reference_saturation_current_ua",
            "Saturation current per unit absorbed_photon_flux_relative when the model's emission condition is satisfied.",
            "uA",
            0.0,
            None,
        ),
    ),
    identification_formula=(
        "excess_voltage = h_over_e_v_s*frequency_thz*1e12 - "
        "work_function_equivalent_v; "
        "stopping_potential_v=max(0,excess_voltage); current is zero for "
        "excess_voltage<=0 and otherwise reference_saturation_current_ua*"
        "absorbed_photon_flux_relative."
    ),
    predict=_predict,
    truths={
        "historical": MatchedTruth(
            _HISTORICAL,
            _expressions(_HISTORICAL),
            applicability=_APPLICABILITY,
            fixed_conditions=_FIXED_CONDITIONS,
        ),
        "counterfactual": MatchedTruth(
            _COUNTERFACTUAL,
            _expressions(_COUNTERFACTUAL),
            applicability=_APPLICABILITY,
            fixed_conditions=_FIXED_CONDITIONS,
        ),
    },
    diagnostic_conditions=(
        {"frequency_thz": 450.0, "absorbed_photon_flux_relative": 0.10},
        {"frequency_thz": 600.0, "absorbed_photon_flux_relative": 2.00},
        {"frequency_thz": 800.0, "absorbed_photon_flux_relative": 0.50},
        {"frequency_thz": 1000.0, "absorbed_photon_flux_relative": 1.50},
    ),
    hidden_conditions=tuple(
        {
            "frequency_thz": frequency,
            "absorbed_photon_flux_relative": absorbed_flux,
        }
        for frequency, absorbed_flux in _HIDDEN
    ),
    credits=(
        SourceCredit(
            "Albert Einstein, On a Heuristic Point of View Concerning the Production and Transformation of Light (1905)",
            "https://doi.org/10.1002/andp.19053220607",
            "Source for the photon-energy balance underlying the stopping-potential frequency law.",
        ),
        SourceCredit(
            "R. A. Millikan, The Electron and the Light-Quant from the Experimental Point of View (1923)",
            "https://www.nobelprize.org/uploads/2018/06/millikan-lecture.pdf",
            "Source for quantitative stopping-potential tests of the frequency law.",
        ),
    ),
    counterfactual_change=(
        "Only the energy-per-frequency coefficient changes from 4.135667696e-15 "
        "to 3.20e-15 V s."
    ),
    common_notes=DEFAULT_MATCHED_NOTES + (
        "The cathode remains clean and unchanged across experiments.",
        "The photon-flux control is absorbed photon rate, not optical power or irradiance.",
    ),
    budget=10,
    max_replicates=15,
    relative_tolerance=0.01,
    absolute_tolerances={_STOPPING: 0.08, _CURRENT: 0.20},
)


def make_photoelectric_case(
    world: str = "historical", track: BenchmarkTrack = BenchmarkTrack.IDENTIFICATION
) -> BenchmarkCase:
    return make_matched_case(PHOTOELECTRIC_SPEC, world, track)


__all__ = ["PHOTOELECTRIC_SPEC", "PHOTOELECTRIC_WORLDS", "make_photoelectric_case"]
