"""Matched inclined-plane worlds inspired by Galileo's investigation."""

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


GALILEO_INCLINED_PLANE_WORLDS = MATCHED_WORLDS
_APPARATUS = "inclined_plane_water_clock"
_READOUT = "collected_water_g"
_REFERENCE_DISTANCE_M = 1.0
_REFERENCE_ANGLE_DEG = 5.0

_CONTROLS = (
    ControlSpec("distance_m", "Distance the ball travels along the marked groove.", "m", 0.25, 4.00),
    ControlSpec("incline_angle_deg", "Angle of the grooved plane above the horizontal.", "degree", 2.0, 10.0),
    ControlSpec("ball_mass_kg", "Mass of a geometrically similar round ball.", "kg", 0.05, 0.50),
)
_READOUTS = (
    ReadoutSpec(
        _READOUT,
        "Water collected during one descent; its mass is proportional to elapsed time.",
        "g",
        0.1,
    ),
)


def _predict(parameters: Mapping[str, float], controls: Mapping[str, Any]) -> Mapping[str, float]:
    sine_ratio = math.sin(math.radians(float(controls["incline_angle_deg"]))) / math.sin(
        math.radians(_REFERENCE_ANGLE_DEG)
    )
    value = float(parameters["reference_water_mass_g"]) * (
        float(controls["distance_m"]) / _REFERENCE_DISTANCE_M
    ) ** float(parameters["distance_exponent"]) * sine_ratio ** float(
        parameters["sine_angle_exponent"]
    ) * (
        float(controls["ball_mass_kg"]) / 0.20
    ) ** float(parameters["mass_exponent"])
    return {_READOUT: value}


def _expression(parameters: Mapping[str, float]) -> Mapping[str, Any]:
    sine_ratio = {
        "op": "divide",
        "args": [
            {
                "op": "sin",
                "args": [
                    {
                        "op": "multiply",
                        "args": [{"var": "incline_angle_deg"}, math.pi / 180.0],
                    }
                ],
            },
            math.sin(math.radians(_REFERENCE_ANGLE_DEG)),
        ],
    }
    return {
        "op": "multiply",
        "args": [
            parameters["reference_water_mass_g"],
            {
                "op": "power",
                "args": [
                    {
                        "op": "divide",
                        "args": [{"var": "distance_m"}, _REFERENCE_DISTANCE_M],
                    },
                    parameters["distance_exponent"],
                ],
            },
            {"op": "power", "args": [sine_ratio, parameters["sine_angle_exponent"]]},
            {
                "op": "power",
                "args": [
                    {"op": "divide", "args": [{"var": "ball_mass_kg"}, 0.20]},
                    parameters["mass_exponent"],
                ],
            },
        ],
    }


_HISTORICAL: Mapping[str, float] = {
    "reference_water_mass_g": 24.0,
    "distance_exponent": 0.50,
    "sine_angle_exponent": -0.50,
    "mass_exponent": 0.0,
}
_COUNTERFACTUAL: Mapping[str, float] = {**_HISTORICAL, "distance_exponent": 0.70}
_HIDDEN = (
    (0.30, 2.5, 0.08), (0.55, 7.0, 0.42), (0.90, 4.0, 0.15), (1.30, 9.0, 0.30),
    (1.80, 3.0, 0.48), (2.40, 6.0, 0.10), (3.10, 8.5, 0.25), (3.80, 5.0, 0.36),
)

GALILEO_INCLINED_PLANE_SPEC = MatchedFamilySpec(
    family="galileo_inclined_plane",
    case_id_prefix="inclined_plane.descent",
    response_title="the inclined-plane response",
    apparatus_name=_APPARATUS,
    apparatus_description="A grooved plane, round balls, a steady water clock, and a balance.",
    background=(
        "You have a long grooved plane, round balls, and a water clock. Collected "
        "water mass is a repeatable proxy for descent time. Determine how descent "
        "depends on distance, inclination, and mass."
    ),
    initial_observations=(
        "A ball speeds up as it descends rather than moving uniformly.",
        "A shallow plane makes the motion slow enough to compare with a water clock.",
    ),
    controls=_CONTROLS,
    readouts=_READOUTS,
    identification_model="inclined_plane_power_law",
    identification_parameter_specs=(
        IdentificationParameterSpec(
            "reference_water_mass_g",
            "Collected water mass at distance_m = 1 m, incline_angle_deg = 5 degrees, and ball_mass_kg = 0.20 kg.",
            "g",
            0.0,
            None,
        ),
        IdentificationParameterSpec(
            "distance_exponent",
            "Power-law exponent of distance_m / 1 m.",
            "1",
            -8.0,
            8.0,
        ),
        IdentificationParameterSpec(
            "sine_angle_exponent",
            "Power-law exponent of sin(incline_angle_deg) / sin(5 degrees).",
            "1",
            -8.0,
            8.0,
        ),
        IdentificationParameterSpec(
            "mass_exponent",
            "Power-law exponent of ball_mass_kg / 0.20 kg.",
            "1",
            -8.0,
            8.0,
        ),
    ),
    identification_formula=(
        "W = reference_water_mass_g * (distance_m / 1 m)^distance_exponent * "
        "(sin(incline_angle_deg)/sin(5 deg))^sine_angle_exponent * "
        "(ball_mass_kg/0.20 kg)^mass_exponent."
    ),
    predict=_predict,
    truths={
        "historical": MatchedTruth(
            _HISTORICAL,
            {_READOUT: _expression(_HISTORICAL)},
            applicability=(
                "Rolling from rest without slipping on a fixed straight incline, with constant acceleration and geometrically similar balls over the declared ranges.",
            ),
            fixed_conditions=(
                "Gravitational acceleration and the balls' dimensionless rotational-inertia ratio are fixed, so descent time is proportional to the square root of distance divided by sin(incline angle) and is independent of ball mass.",
                "The water-clock flow rate is steady and common to every trial; collected water mass is therefore a linear proxy for elapsed descent time.",
                "Air drag, rolling resistance, slip, release impulse, and groove irregularities are absent from the encoded idealization.",
            ),
        ),
        "counterfactual": MatchedTruth(
            _COUNTERFACTUAL,
            {_READOUT: _expression(_COUNTERFACTUAL)},
            applicability=(
                "Benchmark-authored rolling-descent world with an exact 0.70 distance exponent and the same sine-angle and mass responses over the declared ranges.",
            ),
            fixed_conditions=(
                "The selected-world distance exponent is the complete kinematic response rather than an effect of slip, drag, or a changing water-clock calibration.",
                "The water-clock flow rate, gravitational environment, ball shape and dimensionless rotational-inertia ratio, release protocol, and groove preparation remain fixed.",
                "Air drag, rolling resistance, release impulse, and groove irregularities are absent from the encoded idealization.",
            ),
        ),
    },
    diagnostic_conditions=(
        {"distance_m": 0.25, "incline_angle_deg": 2.0, "ball_mass_kg": 0.05},
        {"distance_m": 1.0, "incline_angle_deg": 5.0, "ball_mass_kg": 0.20},
        {"distance_m": 2.0, "incline_angle_deg": 8.0, "ball_mass_kg": 0.35},
        {"distance_m": 4.0, "incline_angle_deg": 10.0, "ball_mass_kg": 0.50},
    ),
    hidden_conditions=tuple(
        {"distance_m": distance, "incline_angle_deg": angle, "ball_mass_kg": mass}
        for distance, angle, mass in _HIDDEN
    ),
    credits=(SourceCredit(
        "Galileo Galilei, Dialogues Concerning Two New Sciences (1638)",
        "https://oll.libertyfund.org/titles/galilei-dialogues-concerning-two-new-sciences",
        "Source for the grooved plane, rolling ball, water clock, and repeated comparisons.",
    ),),
    counterfactual_change="Only the normalized distance exponent changes from 0.50 to 0.70.",
    common_notes=DEFAULT_MATCHED_NOTES + (
        "Treat the water flow as steady during the allowed experiments.",
        "Release every ball from rest without a push; each ball rolls without slipping.",
        "The balls are geometrically similar, so their dimensionless rotational-inertia ratio is fixed.",
        "Air drag, rolling resistance, and irregular-ball effects are outside this world.",
    ),
    budget=9,
    max_replicates=12,
    relative_tolerance=0.05,
)


def make_galileo_inclined_plane_case(
    world: str = "historical", track: BenchmarkTrack = BenchmarkTrack.IDENTIFICATION
) -> BenchmarkCase:
    return make_matched_case(GALILEO_INCLINED_PLANE_SPEC, world, track)


__all__ = ["GALILEO_INCLINED_PLANE_SPEC", "GALILEO_INCLINED_PLANE_WORLDS", "make_galileo_inclined_plane_case"]
