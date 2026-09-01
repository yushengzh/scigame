"""Matched ideal-pendulum family used by both benchmark tracks."""

from __future__ import annotations

import math
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


PENDULUM_WORLDS = MATCHED_WORLDS
_REFERENCE_LENGTH_M = 1.0
_REFERENCE_MASS_KG = 0.20
_REFERENCE_PERIOD_S = 2.0 * math.pi * math.sqrt(1.0 / 9.80665)


def _predict(
    parameters: Mapping[str, float], controls: Mapping[str, Any]
) -> Mapping[str, float]:
    return {
        "period_s": parameters["reference_period_s"]
        * (float(controls["length_m"]) / _REFERENCE_LENGTH_M)
        ** parameters["length_exponent"]
        * (float(controls["bob_mass_kg"]) / _REFERENCE_MASS_KG)
        ** parameters["mass_exponent"]
    }


def _expression(mass_exponent: float) -> Mapping[str, Any]:
    return {
        "op": "multiply",
        "args": [
            _REFERENCE_PERIOD_S,
            {
                "op": "power",
                "args": [
                    {"op": "divide", "args": [{"var": "length_m"}, 1.0]},
                    0.5,
                ],
            },
            {
                "op": "power",
                "args": [
                    {"op": "divide", "args": [{"var": "bob_mass_kg"}, 0.20]},
                    mass_exponent,
                ],
            },
        ],
    }


_HISTORICAL = {
    "reference_period_s": _REFERENCE_PERIOD_S,
    "length_exponent": 0.5,
    "mass_exponent": 0.0,
}
_COUNTERFACTUAL = {
    "reference_period_s": _REFERENCE_PERIOD_S,
    "length_exponent": 0.5,
    "mass_exponent": 0.25,
}


PENDULUM_SPEC = MatchedFamilySpec(
    family="pendulum",
    case_id_prefix="pendulum",
    response_title="the pendulum period response",
    apparatus_name="simple_pendulum",
    apparatus_description="Pendulum rig with a ruler, balance, protractor, and stopwatch.",
    background=(
        "You are investigating an idealized pendulum in a small-angle laboratory. "
        "Vary only the listed controls, inspect the period measurements, and infer "
        "a predictive response law."
    ),
    initial_observations=(
        "A suspended bob repeats its motion at a regular interval.",
        "The cause of changes in that interval is not given.",
    ),
    controls=(
        ControlSpec(
            name="length_m",
            description="Distance from the pivot to the bob's center.",
            unit="m",
            minimum=0.20,
            maximum=2.00,
        ),
        ControlSpec(
            name="bob_mass_kg",
            description="Mass of the pendulum bob.",
            unit="kg",
            minimum=0.05,
            maximum=1.00,
        ),
        ControlSpec(
            name="release_angle_deg",
            description="Small release angle from the vertical.",
            unit="degree",
            minimum=1.0,
            maximum=10.0,
        ),
    ),
    readouts=(
        ReadoutSpec(
            name="period_s",
            description="Mean time for one complete oscillation.",
            unit="s",
            resolution=0.01,
        ),
    ),
    identification_model="normalized_power_law",
    identification_parameter_specs=(
        IdentificationParameterSpec(
            "reference_period_s",
            "Oscillation period at length_m = 1 m and bob_mass_kg = 0.20 kg under the fixed apparatus conditions.",
            "s",
            0.0,
            None,
        ),
        IdentificationParameterSpec(
            "length_exponent",
            "Power-law exponent of length_m / 1 m.",
            "1",
            -8.0,
            8.0,
        ),
        IdentificationParameterSpec(
            "mass_exponent",
            "Power-law exponent of bob_mass_kg / 0.20 kg.",
            "1",
            -8.0,
            8.0,
        ),
    ),
    identification_formula=(
        "T = reference_period_s * (length_m / 1 m)^length_exponent * "
        "(bob_mass_kg / 0.20 kg)^mass_exponent."
    ),
    predict=_predict,
    truths={
        "historical": MatchedTruth(
            _HISTORICAL,
            {"period_s": _expression(0.0)},
            applicability=(
                "Small-angle, weakly damped motion of a simple pendulum in a uniform gravitational field over the declared length, mass, and release-angle ranges.",
            ),
            fixed_conditions=(
                "The support is massless and inextensible, the bob is represented by its center of mass, and length is measured from the pivot to that center.",
                "Gravitational acceleration is 9.80665 m/s^2; pivot friction, air drag, buoyancy, and finite-amplitude corrections are absent in the encoded idealization.",
                "Release angle remains within the stated small-angle regime and has no additional effect on the selected-world period law.",
            ),
        ),
        "counterfactual": MatchedTruth(
            _COUNTERFACTUAL,
            {"period_s": _expression(0.25)},
            applicability=(
                "Benchmark-authored small-angle pendulum world with exact square-root length scaling and a quarter-power bob-mass response over the declared ranges.",
            ),
            fixed_conditions=(
                "The support is massless and inextensible, the bob is represented by its center of mass, and length is measured from the pivot to that center.",
                "Gravitational acceleration and the one-metre reference period remain fixed; drag, friction, buoyancy, and finite-amplitude corrections are absent.",
                "The mass exponent is a fundamental selected-world response rather than an unreported change in geometry or damping, and release angle has no additional effect within the stated range.",
            ),
        ),
    },
    diagnostic_conditions=(
        {"length_m": 1.0, "bob_mass_kg": 0.20, "release_angle_deg": 5.0},
        {"length_m": 0.25, "bob_mass_kg": 0.05, "release_angle_deg": 1.0},
        {"length_m": 2.0, "bob_mass_kg": 0.80, "release_angle_deg": 10.0},
    ),
    hidden_conditions=(
        {"length_m": 0.24, "bob_mass_kg": 0.06, "release_angle_deg": 1.5},
        {"length_m": 0.31, "bob_mass_kg": 0.80, "release_angle_deg": 9.0},
        {"length_m": 0.47, "bob_mass_kg": 0.14, "release_angle_deg": 4.0},
        {"length_m": 0.68, "bob_mass_kg": 0.55, "release_angle_deg": 7.5},
        {"length_m": 0.93, "bob_mass_kg": 0.09, "release_angle_deg": 2.0},
        {"length_m": 1.18, "bob_mass_kg": 0.36, "release_angle_deg": 10.0},
        {"length_m": 1.53, "bob_mass_kg": 0.95, "release_angle_deg": 5.5},
        {"length_m": 1.91, "bob_mass_kg": 0.22, "release_angle_deg": 3.0},
    ),
    credits=(
        SourceCredit(
            citation="Christiaan Huygens, Horologium Oscillatorium (1673)",
            url="https://doi.org/10.3931/e-rara-11164",
            role=(
                "Historical basis for quantitative pendulum dynamics; the benchmark "
                "uses the modern small-angle idealization."
            ),
        ),
    ),
    counterfactual_change=(
        "Bob-mass exponent changes from 0 to 0.25 while the reference condition "
        "and square-root length dependence remain fixed."
    ),
    common_notes=DEFAULT_MATCHED_NOTES + (
        "The rig is calibrated only for the listed small release angles.",
        "The stopwatch reports measurements to the nearest 0.01 s.",
    ),
    budget=8,
    max_replicates=20,
)


def make_pendulum_case(
    world: str = "historical",
    track: BenchmarkTrack = BenchmarkTrack.IDENTIFICATION,
) -> BenchmarkCase:
    return make_matched_case(PENDULUM_SPEC, world, track)


__all__ = ["PENDULUM_SPEC", "PENDULUM_WORLDS", "make_pendulum_case"]
