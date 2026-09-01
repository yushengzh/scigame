"""Matched rc discharge benchmark family."""

from __future__ import annotations

import math
from typing import Any, Mapping

from role_benchmark.models import BenchmarkTrack, ControlSpec, ReadoutSpec
from role_benchmark.protocols import BenchmarkCase

from ._expressions import div, exp, mul, neg, power, var
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
    # kOhm * uF = 10^-3 s.
    tau_s = (
        float(controls["resistance_kohm"])
        * float(controls["capacitance_uf"])
        / 1000.0
    )
    scaled_time = float(controls["elapsed_time_s"]) / tau_s
    return {
        "capacitor_voltage_v": float(controls["initial_voltage_v"])
        * math.exp(
            -parameters["rate_scale"]
            * scaled_time ** parameters["time_shape"]
        )
    }


def _expression(rate_scale: float, time_shape: float) -> Mapping[str, Any]:
    tau_s = div(
        mul(var("resistance_kohm"), var("capacitance_uf")),
        1000.0,
    )
    scaled_time = div(var("elapsed_time_s"), tau_s)
    return mul(
        var("initial_voltage_v"),
        exp(neg(mul(rate_scale, power(scaled_time, time_shape)))),
    )


RC_DISCHARGE_SPEC = MatchedFamilySpec(
    family="rc_discharge",
    case_id_prefix="capacitor.discharge",
    swap_public_instance_ids=True,
    response_title="the resistor-capacitor discharge relation",
    apparatus_name="rc_discharge_scope",
    apparatus_description=(
        "A charged capacitor, selectable resistor and capacitor, precision switch, "
        "timer, and high-impedance voltmeter."
    ),
    background=(
        "A capacitor is charged to a selected voltage and then discharged through a "
        "selected resistance. Determine its remaining voltage at a chosen elapsed time."
    ),
    initial_observations=(
        "The voltage falls monotonically after the discharge switch is closed.",
    ),
    controls=(
        ControlSpec("initial_voltage_v", "Voltage just before discharge.", "V", 2.0, 10.0),
        ControlSpec("resistance_kohm", "Selected resistance.", "kOhm", 25.0, 100.0),
        ControlSpec("capacitance_uf", "Selected capacitance.", "uF", 10.0, 40.0),
        ControlSpec("elapsed_time_s", "Time after closing the switch.", "s", 0.05, 4.0),
    ),
    readouts=(
        ReadoutSpec(
            "capacitor_voltage_v",
            "Remaining capacitor voltage at the selected time.",
            "V",
            0.001,
        ),
    ),
    identification_model="generalized_exponential_rc_discharge",
    identification_parameter_specs=(
        IdentificationParameterSpec(
            "rate_scale",
            "Nonnegative dimensionless multiplier of the normalized-time term in the exponential decay exponent.",
            "1",
            0.0,
            None,
        ),
        IdentificationParameterSpec(
            "time_shape",
            "Positive exponent applied to elapsed_time_s / tau_s inside the exponential decay law.",
            "1",
            0.1,
            8.0,
        ),
    ),
    identification_formula=(
        "tau_s = resistance_kohm*capacitance_uf/1000; "
        "V = initial_voltage_v*exp[-rate_scale*"
        "(elapsed_time_s/tau_s)^time_shape]"
    ),
    predict=_predict,
    truths={
        "historical": MatchedTruth(
            parameters={"rate_scale": 1.0, "time_shape": 1.0},
            discovery_outputs={
                "capacitor_voltage_v": _expression(1.0, 1.0)
            },
            applicability=(
                "Ideal lumped, first-order resistor-capacitor discharge over the "
                "declared resistance, capacitance, voltage, and time ranges.",
            ),
            fixed_conditions=(
                "Resistance and capacitance are constant during each trial, and their "
                "product defines the discharge time scale.",
                "Switch resistance, capacitor leakage, dielectric absorption, equivalent "
                "series resistance, and parasitic reactances are negligible.",
                "The voltmeter input impedance is much larger than every selected "
                "resistance, so the readout does not load the circuit.",
            ),
        ),
        "counterfactual": MatchedTruth(
            parameters={"rate_scale": 1.0, "time_shape": 2.0},
            discovery_outputs={
                "capacitor_voltage_v": _expression(1.0, 2.0)
            },
            applicability=(
                "Benchmark-authored memory-dependent discharge dynamics whose normalized "
                "voltage is a compressed exponential exp[-(t/RC)^2] over the declared "
                "control ranges.",
            ),
            fixed_conditions=(
                "Resistance and capacitance remain constant and their product defines the "
                "reference time scale in this counterfactual world.",
                "The selected-world memory mechanism, rather than unreported leakage or "
                "meter loading, is the sole origin of the quadratic time shape.",
                "The voltmeter input impedance is much larger than every selected "
                "resistance, so the readout does not load the circuit.",
            ),
        ),
    },
    diagnostic_conditions=(
        {"initial_voltage_v": 6.0, "resistance_kohm": 50.0, "capacitance_uf": 20.0, "elapsed_time_s": 0.1},
        {"initial_voltage_v": 6.0, "resistance_kohm": 50.0, "capacitance_uf": 20.0, "elapsed_time_s": 0.4},
        {"initial_voltage_v": 6.0, "resistance_kohm": 50.0, "capacitance_uf": 20.0, "elapsed_time_s": 0.8},
        {"initial_voltage_v": 6.0, "resistance_kohm": 50.0, "capacitance_uf": 20.0, "elapsed_time_s": 1.5},
        {"initial_voltage_v": 3.0, "resistance_kohm": 50.0, "capacitance_uf": 20.0, "elapsed_time_s": 0.4},
        {"initial_voltage_v": 6.0, "resistance_kohm": 100.0, "capacitance_uf": 20.0, "elapsed_time_s": 0.4},
        {"initial_voltage_v": 6.0, "resistance_kohm": 50.0, "capacitance_uf": 10.0, "elapsed_time_s": 0.4},
        {"initial_voltage_v": 8.0, "resistance_kohm": 75.0, "capacitance_uf": 40.0, "elapsed_time_s": 2.0},
    ),
    hidden_conditions=(
        {"initial_voltage_v": 8.0, "resistance_kohm": 50.0, "capacitance_uf": 20.0, "elapsed_time_s": 0.2},
        {"initial_voltage_v": 5.0, "resistance_kohm": 25.0, "capacitance_uf": 40.0, "elapsed_time_s": 0.5},
        {"initial_voltage_v": 7.0, "resistance_kohm": 100.0, "capacitance_uf": 10.0, "elapsed_time_s": 1.0},
        {"initial_voltage_v": 4.0, "resistance_kohm": 50.0, "capacitance_uf": 20.0, "elapsed_time_s": 1.5},
        {"initial_voltage_v": 9.0, "resistance_kohm": 100.0, "capacitance_uf": 20.0, "elapsed_time_s": 4.0},
        {"initial_voltage_v": 6.0, "resistance_kohm": 25.0, "capacitance_uf": 20.0, "elapsed_time_s": 1.25},
    ),
    credits=(
        SourceCredit(
            citation="William Thomson, On Transient Electric Currents (1853).",
            url="https://doi.org/10.1080/14786445308647279",
            role=(
                "Classic primary source credited for transient circuit analysis. "
                "The exact lumped RC calibration is a modern idealized derivation."
            ),
        ),
    ),
    counterfactual_change=(
        "Only the dimensionless time-shape exponent changes from the ordinary "
        "exponential value 1 to the compressed-exponential value 2; the RC product, "
        "initial-voltage scaling, and reference decay rate stay fixed."
    ),
    common_notes=DEFAULT_MATCHED_NOTES,
)


def make_rc_discharge_case(
    world: str = "historical",
    track: BenchmarkTrack = BenchmarkTrack.IDENTIFICATION,
) -> BenchmarkCase:
    return make_matched_case(RC_DISCHARGE_SPEC, world, track)


__all__ = ["RC_DISCHARGE_SPEC", "make_rc_discharge_case"]
