"""Matched newton cooling benchmark family."""

from __future__ import annotations

import math
from typing import Any, Mapping

from role_benchmark.models import BenchmarkTrack, ControlSpec, ReadoutSpec
from role_benchmark.protocols import BenchmarkCase

from ._expressions import add, exp, mul, neg, sub, var
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
    elapsed = float(controls["elapsed_time_min"])
    rate = parameters["cooling_rate_per_min"]
    weight = parameters["fast_mode_weight"]
    relaxation = (1.0 - weight) * math.exp(-rate * elapsed) + weight * math.exp(
        -4.0 * rate * elapsed
    )
    ambient = float(controls["ambient_temperature_c"])
    initial = float(controls["initial_temperature_c"])
    return {"object_temperature_c": ambient + (initial - ambient) * relaxation}


def _expression(rate: float, weight: float) -> Mapping[str, Any]:
    elapsed = var("elapsed_time_min")
    relaxation = add(
        mul(1.0 - weight, exp(neg(mul(rate, elapsed)))),
        mul(weight, exp(neg(mul(4.0, rate, elapsed)))),
    )
    return add(
        var("ambient_temperature_c"),
        mul(
            sub(
                var("initial_temperature_c"),
                var("ambient_temperature_c"),
            ),
            relaxation,
        ),
    )


NEWTON_COOLING_SPEC = MatchedFamilySpec(
    family="newton_cooling",
    case_id_prefix="body.cooling",
    swap_public_instance_ids=True,
    response_title="the cooling-time relation",
    apparatus_name="controlled_cooling_chamber",
    apparatus_description=(
        "A reproducibly heated object in a controlled-temperature chamber with a "
        "timer and a calibrated sensor reporting its aggregate temperature."
    ),
    background=(
        "A small object starts above the chamber temperature and cools without a "
        "phase change. The chamber temperature is constant during a trial. The "
        "reported temperature is a reproducibly defined aggregate of the object's "
        "thermal state. Determine its dependence on initial temperature, ambient "
        "temperature, and elapsed time."
    ),
    initial_observations=(
        "The object approaches the ambient temperature without crossing it.",
    ),
    controls=(
        ControlSpec("initial_temperature_c", "Object temperature at time zero.", "degC", 50.0, 100.0),
        ControlSpec("ambient_temperature_c", "Chamber temperature.", "degC", 10.0, 30.0),
        ControlSpec("elapsed_time_min", "Elapsed cooling time.", "min", 0.0, 25.0),
    ),
    readouts=(
        ReadoutSpec(
            "object_temperature_c",
            "Object temperature at the selected time.",
            "degC",
            0.1,
        ),
    ),
    identification_model="two_mode_cooling",
    identification_parameter_specs=(
        IdentificationParameterSpec(
            "cooling_rate_per_min",
            "Nonnegative decay rate of the slower temperature-relaxation component.",
            "min^-1",
            0.0,
            None,
        ),
        IdentificationParameterSpec(
            "fast_mode_weight",
            "Mixture weight assigned to the component whose decay rate is four times cooling_rate_per_min.",
            "1",
            0.0,
            1.0,
        ),
    ),
    identification_formula=(
        "object_temperature_c = ambient_temperature_c + "
        "(initial_temperature_c-ambient_temperature_c)*"
        "[(1-fast_mode_weight)*exp(-cooling_rate_per_min*elapsed_time_min) + "
        "fast_mode_weight*exp(-4*cooling_rate_per_min*elapsed_time_min)]"
    ),
    predict=_predict,
    truths={
        "historical": MatchedTruth(
            parameters={"cooling_rate_per_min": 0.12, "fast_mode_weight": 0.0},
            discovery_outputs={
                "object_temperature_c": _expression(0.12, 0.0)
            },
            applicability=(
                "Lumped-capacitance cooling of a body whose internal temperature is "
                "effectively uniform over the declared time and temperature ranges.",
            ),
            fixed_conditions=(
                "The Biot number is small, the effective heat-transfer coefficient and "
                "thermal properties are constant, and the chamber is an effectively "
                "infinite constant-temperature reservoir.",
                "Radiative exchange and other losses are negligible or already absorbed "
                "into the constant effective cooling rate.",
                "The sensor reports the lumped body temperature without appreciable lag.",
            ),
        ),
        "counterfactual": MatchedTruth(
            parameters={"cooling_rate_per_min": 0.12, "fast_mode_weight": 0.25},
            discovery_outputs={
                "object_temperature_c": _expression(0.12, 0.25)
            },
            applicability=(
                "Benchmark-authored object with two independently relaxing lumped thermal "
                "components, both approaching the same chamber temperature.",
            ),
            fixed_conditions=(
                "The slow and fast components have fixed readout weights 0.75 and 0.25; "
                "their rates are 0.12 and 0.48 per minute, respectively.",
                "Each component has constant thermal properties and coupling throughout a "
                "trial, and the chamber is a constant-temperature reservoir.",
                "The sensor reports the same fixed weighted aggregate in every trial and "
                "has negligible measurement lag.",
            ),
        ),
    },
    diagnostic_conditions=(
        {"initial_temperature_c": 80.0, "ambient_temperature_c": 20.0, "elapsed_time_min": 0.0},
        {"initial_temperature_c": 80.0, "ambient_temperature_c": 20.0, "elapsed_time_min": 1.0},
        {"initial_temperature_c": 80.0, "ambient_temperature_c": 20.0, "elapsed_time_min": 3.0},
        {"initial_temperature_c": 80.0, "ambient_temperature_c": 20.0, "elapsed_time_min": 8.0},
        {"initial_temperature_c": 80.0, "ambient_temperature_c": 20.0, "elapsed_time_min": 20.0},
        {"initial_temperature_c": 50.0, "ambient_temperature_c": 20.0, "elapsed_time_min": 3.0},
        {"initial_temperature_c": 100.0, "ambient_temperature_c": 20.0, "elapsed_time_min": 3.0},
        {"initial_temperature_c": 80.0, "ambient_temperature_c": 10.0, "elapsed_time_min": 3.0},
    ),
    hidden_conditions=(
        {"initial_temperature_c": 80.0, "ambient_temperature_c": 20.0, "elapsed_time_min": 0.7},
        {"initial_temperature_c": 65.0, "ambient_temperature_c": 12.0, "elapsed_time_min": 2.0},
        {"initial_temperature_c": 95.0, "ambient_temperature_c": 28.0, "elapsed_time_min": 4.5},
        {"initial_temperature_c": 55.0, "ambient_temperature_c": 18.0, "elapsed_time_min": 7.0},
        {"initial_temperature_c": 88.0, "ambient_temperature_c": 25.0, "elapsed_time_min": 11.0},
        {"initial_temperature_c": 72.0, "ambient_temperature_c": 15.0, "elapsed_time_min": 16.0},
        {"initial_temperature_c": 100.0, "ambient_temperature_c": 30.0, "elapsed_time_min": 23.0},
    ),
    credits=(
        SourceCredit(
            citation=(
                "Isaac Newton, Scala graduum caloris, Philosophical Transactions "
                "22 (1701), 824-829."
            ),
            url="https://doi.org/10.1098/rstl.1700.0082",
            role=(
                "Primary historical source for the cooling relation. The explicit "
                "lumped exponential solution is a modern idealization."
            ),
        ),
    ),
    counterfactual_change=(
        "Only one relaxation structure changes: a fast mode of fixed fourfold rate "
        "receives weight 0.25 instead of zero. This authored two-mode twin is the "
        "smallest linear superposition that departs from single-exponential cooling."
    ),
    common_notes=DEFAULT_MATCHED_NOTES
    + (
        "The preparation procedure, chamber coupling, and aggregate-temperature "
        "readout are held fixed; no internal temperature profile or response-law "
        "family is supplied.",
    ),
)


def make_newton_cooling_case(
    world: str = "historical",
    track: BenchmarkTrack = BenchmarkTrack.IDENTIFICATION,
) -> BenchmarkCase:
    return make_matched_case(NEWTON_COOLING_SPEC, world, track)


__all__ = ["NEWTON_COOLING_SPEC", "make_newton_cooling_case"]
