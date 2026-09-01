"""Matched ohm circuit benchmark family."""

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
        "current_ma": parameters["reference_current_ma"]
        * float(controls["voltage_v"]) ** parameters["voltage_exponent"]
        * (float(controls["resistance_ohm"]) / 100.0)
        ** parameters["resistance_exponent"]
    }


def _expression(
    reference: float, voltage_exponent: float, resistance_exponent: float
) -> Mapping[str, Any]:
    return mul(
        reference,
        power(var("voltage_v"), voltage_exponent),
        power(div(var("resistance_ohm"), 100.0), resistance_exponent),
    )


OHM_CIRCUIT_SPEC = MatchedFamilySpec(
    family="ohm_circuit",
    case_id_prefix="resistive.circuit",
    response_title="the voltage-resistance current relation",
    apparatus_name="dc_resistive_circuit",
    apparatus_description=(
        "A regulated DC source, selectable two-terminal elements from a calibrated "
        "component series held at fixed temperature, and a calibrated ammeter."
    ),
    background=(
        "A steady-current circuit permits independent settings of source voltage and "
        "an element's nominal resistance label. The label is a reproducible component-"
        "series control and does not itself define the operational current relation. "
        "Temperature is fixed and self-heating is negligible. Determine the relation "
        "that predicts the measured current."
    ),
    initial_observations=(
        "The current settles to a reproducible value after each control change.",
    ),
    controls=(
        ControlSpec(
            name="voltage_v",
            description="Applied DC potential difference.",
            unit="V",
            minimum=0.2,
            maximum=5.0,
        ),
        ControlSpec(
            name="resistance_ohm",
            description="Nominal ohm-valued label of the selected component series.",
            unit="ohm",
            minimum=20.0,
            maximum=500.0,
        ),
    ),
    readouts=(
        ReadoutSpec(
            name="current_ma",
            description="Steady circuit current.",
            unit="mA",
            resolution=0.01,
        ),
    ),
    identification_model="resistive_power_law",
    identification_parameter_specs=(
        IdentificationParameterSpec(
            "reference_current_ma",
            "Measured current at voltage_v = 1 V and resistance_ohm = 100 ohm.",
            "mA",
            0.0,
            None,
        ),
        IdentificationParameterSpec(
            "voltage_exponent",
            "Power-law exponent of voltage_v / 1 V.",
            "1",
            -8.0,
            8.0,
        ),
        IdentificationParameterSpec(
            "resistance_exponent",
            "Power-law exponent of resistance_ohm / 100 ohm.",
            "1",
            -8.0,
            8.0,
        ),
    ),
    identification_formula=(
        "I = reference_current_ma*(voltage_v/1 V)^voltage_exponent"
        "*(resistance_ohm/100 ohm)^resistance_exponent"
    ),
    predict=_predict,
    truths={
        "historical": MatchedTruth(
            parameters={
                "reference_current_ma": 10.0,
                "voltage_exponent": 1.0,
                "resistance_exponent": -1.0,
            },
            discovery_outputs={"current_ma": _expression(10.0, 1.0, -1.0)},
            applicability=(
                "Steady direct-current operation of an ohmic two-terminal element at fixed temperature over the declared voltage and component-label ranges.",
            ),
            fixed_conditions=(
                "For the historical component series, the nominal resistance label equals the operational voltage-to-current resistance throughout the stated range.",
                "Contact and lead resistance, source internal resistance, ammeter burden, thermal drift, and self-heating are negligible.",
                "The meter reports the nonnegative steady-current magnitude for the fixed polarity used in every trial.",
            ),
        ),
        "counterfactual": MatchedTruth(
            parameters={
                "reference_current_ma": 10.0,
                "voltage_exponent": 1.0,
                "resistance_exponent": -0.5,
            },
            discovery_outputs={"current_ma": _expression(10.0, 1.0, -0.5)},
            applicability=(
                "Benchmark-authored fixed-temperature component series with exact linear voltage response and inverse-square-root dependence on the nominal resistance label over the declared ranges.",
            ),
            fixed_conditions=(
                "The nominal ohm-valued label remains an independently calibrated component-series coordinate and does not assert the historical operational resistance law.",
                "The -1/2 label exponent is the complete selected-world constitutive response rather than an effect of contacts, source impedance, meter burden, or self-heating.",
                "The meter reports the nonnegative steady-current magnitude for the fixed polarity used in every trial.",
            ),
        ),
    },
    diagnostic_conditions=(
        {"voltage_v": 0.25, "resistance_ohm": 100.0},
        {"voltage_v": 1.0, "resistance_ohm": 100.0},
        {"voltage_v": 4.0, "resistance_ohm": 100.0},
        {"voltage_v": 1.0, "resistance_ohm": 25.0},
        {"voltage_v": 1.0, "resistance_ohm": 400.0},
        {"voltage_v": 2.5, "resistance_ohm": 50.0},
        {"voltage_v": 3.5, "resistance_ohm": 250.0},
        {"voltage_v": 0.6, "resistance_ohm": 480.0},
    ),
    hidden_conditions=(
        {"voltage_v": 0.3, "resistance_ohm": 30.0},
        {"voltage_v": 4.7, "resistance_ohm": 45.0},
        {"voltage_v": 1.2, "resistance_ohm": 90.0},
        {"voltage_v": 3.4, "resistance_ohm": 160.0},
        {"voltage_v": 0.7, "resistance_ohm": 260.0},
        {"voltage_v": 2.8, "resistance_ohm": 420.0},
        {"voltage_v": 4.2, "resistance_ohm": 490.0},
    ),
    credits=(
        SourceCredit(
            citation=(
                "Georg Simon Ohm, Die galvanische Kette, mathematisch bearbeitet "
                "(1827)."
            ),
            url="https://library.si.edu/digital-library/book/diegalvanischeke00ohmg",
            role=(
                "Primary monograph credited for the historical current-voltage-"
                "resistance relation; the normalized exponent twin is synthetic."
            ),
        ),
    ),
    counterfactual_change=(
        "Only the normalized resistance exponent changes from -1 to -1/2. The "
        "linear voltage response and reference current remain identical."
    ),
    common_notes=DEFAULT_MATCHED_NOTES
    + (
        "Voltage sweeps stay within the fixed-temperature operating range; the "
        "ohm-valued component label is not a supplied equation for current.",
    ),
)


def make_ohm_circuit_case(
    world: str = "historical",
    track: BenchmarkTrack = BenchmarkTrack.IDENTIFICATION,
) -> BenchmarkCase:
    return make_matched_case(OHM_CIRCUIT_SPEC, world, track)


__all__ = ["OHM_CIRCUIT_SPEC", "make_ohm_circuit_case"]
