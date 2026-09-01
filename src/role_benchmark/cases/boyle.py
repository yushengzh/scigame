"""Matched compressed-air worlds inspired by Boyle's J-tube experiment."""

from __future__ import annotations

from typing import Any, Mapping

from role_benchmark.models import BenchmarkTrack, ControlSpec, ReadoutSpec
from role_benchmark.protocols import BenchmarkCase

from .matched import DEFAULT_MATCHED_NOTES, IdentificationParameterSpec, MATCHED_WORLDS, MatchedFamilySpec, MatchedTruth, SourceCredit, make_matched_case


BOYLE_J_TUBE_WORLDS = MATCHED_WORLDS
_APPARATUS = "sealed_j_tube"
_VOLUME = "air_volume_ml"
_PRESSURE = "absolute_pressure_kpa"
_THERMAL_CONDITION = "constant_room_temperature"

_CONTROLS = (
    ControlSpec(
        "added_pressure_kpa",
        "Additional mercury-column pressure above ambient.",
        "kPa",
        0.0,
        220.0,
    ),
    ControlSpec(
        "thermal_condition",
        "Condition of the surrounding bath during compression.",
        allowed_values=(_THERMAL_CONDITION,),
    ),
)
_READOUTS = (
    ReadoutSpec(
        _VOLUME,
        "Calibrated total volume occupied by the trapped air, including fixed end-space in the sealed branch.",
        "mL",
        0.1,
    ),
    ReadoutSpec(_PRESSURE, "Absolute pressure of the trapped air.", "kPa", 0.1),
)


def _predict(parameters: Mapping[str, float], controls: Mapping[str, Any]) -> Mapping[str, float]:
    ambient = float(parameters["ambient_pressure_kpa"])
    pressure = ambient + float(controls["added_pressure_kpa"])
    volume = float(parameters["reference_volume_ml"]) * (pressure / ambient) ** float(
        parameters["pressure_exponent"]
    )
    return {_VOLUME: volume, _PRESSURE: pressure}


def _expressions(parameters: Mapping[str, float]) -> Mapping[str, Any]:
    pressure = {
        "op": "add",
        "args": [parameters["ambient_pressure_kpa"], {"var": "added_pressure_kpa"}],
    }
    volume = {
        "op": "multiply",
        "args": [
            parameters["reference_volume_ml"],
            {
                "op": "power",
                "args": [
                    {"op": "divide", "args": [pressure, parameters["ambient_pressure_kpa"]]},
                    parameters["pressure_exponent"],
                ],
            },
        ],
    }
    return {_VOLUME: volume, _PRESSURE: pressure}


_HISTORICAL: Mapping[str, float] = {
    "reference_volume_ml": 48.0,
    "ambient_pressure_kpa": 101.3,
    "pressure_exponent": -1.0,
}
_COUNTERFACTUAL: Mapping[str, float] = {**_HISTORICAL, "pressure_exponent": -0.70}
_HIDDEN_PRESSURES = (7.0, 19.0, 38.0, 63.0, 91.0, 127.0, 169.0, 213.0)
_SHARED_FIXED_CONDITIONS = (
    "The sealed branch contains a fixed amount of gas and is allowed to reach mechanical and thermal equilibrium at each setting.",
    "Absolute pressure includes ambient pressure, and the volume calibration includes all fixed end-space occupied by the trapped gas.",
    "The bath temperature, gas composition, mercury-vapor contribution, and apparatus geometry remain fixed.",
)

BOYLE_J_TUBE_SPEC = MatchedFamilySpec(
    family="boyle_j_tube",
    case_id_prefix="sealed_gas.j_tube",
    swap_public_instance_ids=True,
    response_title="the isothermal pressure-volume response",
    apparatus_name=_APPARATUS,
    apparatus_description=(
        "A sealed J-tube with trapped air, mercury, an absolute-pressure scale, "
        "and a scale calibrated for the total trapped-gas volume."
    ),
    background=(
        "A fixed amount of air is trapped above mercury in a sealed J-tube. Add "
        "mercury pressure while holding the thermal condition fixed, then infer "
        "how pressure and air volume are related."
    ),
    initial_observations=(
        "Adding mercury compresses the trapped air reversibly.",
        "The bath prevents deliberate temperature changes during a run.",
    ),
    controls=_CONTROLS,
    readouts=_READOUTS,
    identification_model="boyle_inverse_law",
    identification_parameter_specs=(
        IdentificationParameterSpec(
            "reference_volume_ml",
            "Total calibrated trapped-gas volume when added_pressure_kpa = 0.",
            "mL",
            0.0,
            None,
        ),
        IdentificationParameterSpec(
            "ambient_pressure_kpa",
            "Absolute ambient pressure added to added_pressure_kpa and used as the pressure normalization.",
            "kPa",
            1.0,
            None,
        ),
        IdentificationParameterSpec(
            "pressure_exponent",
            "Power-law exponent of absolute_pressure_kpa / ambient_pressure_kpa in the volume response.",
            "1",
            -8.0,
            8.0,
        ),
    ),
    identification_formula=(
        "P = ambient_pressure_kpa + added_pressure_kpa; V = reference_volume_ml "
        "* (P/ambient_pressure_kpa)^pressure_exponent."
    ),
    predict=_predict,
    truths={
        "historical": MatchedTruth(
            _HISTORICAL,
            _expressions(_HISTORICAL),
            applicability=(
                "Quasistatic compression of a dilute, single-phase gas in the ideal-gas limit over the stated pressure range.",
            ),
            fixed_conditions=_SHARED_FIXED_CONDITIONS
            + (
                "Gas adsorption, dissolution, leakage, and composition changes are negligible.",
            ),
        ),
        "counterfactual": MatchedTruth(
            _COUNTERFACTUAL,
            _expressions(_COUNTERFACTUAL),
            applicability=(
                "Authored alternate compressible-medium response over the same pressure and volume ranges; it is not asserted to be an ideal gas.",
            ),
            fixed_conditions=_SHARED_FIXED_CONDITIONS
            + (
                "The encoded pressure exponent is the complete equilibrium constitutive response; no unmodeled leakage or volume offset is present.",
            ),
        ),
    },
    diagnostic_conditions=tuple(
        {"added_pressure_kpa": pressure, "thermal_condition": _THERMAL_CONDITION}
        for pressure in (0.0, 55.0, 120.0, 220.0)
    ),
    hidden_conditions=tuple(
        {"added_pressure_kpa": pressure, "thermal_condition": _THERMAL_CONDITION}
        for pressure in _HIDDEN_PRESSURES
    ),
    credits=(SourceCredit(
        "Robert Boyle, An Experimentall Account of the Compression of Aire (1661 manuscript)",
        "https://makingscience.royalsociety.org/items/rbo_1_22/an-experimentall-account-of-the-compression-of-aire-made-by-mr-boyle",
        "Primary record of the trapped-air mercury-column compression measurements later published in 1662.",
    ),),
    counterfactual_change="Only the normalized pressure exponent changes from -1.00 to -0.70.",
    common_notes=DEFAULT_MATCHED_NOTES + (
        "The trapped amount of air and its temperature remain fixed.",
        "Any non-empty subset of the two listed readouts may be requested.",
    ),
    budget=8,
    max_replicates=10,
    relative_tolerance=0.03,
)


def make_boyle_j_tube_case(
    world: str = "historical", track: BenchmarkTrack = BenchmarkTrack.IDENTIFICATION
) -> BenchmarkCase:
    return make_matched_case(BOYLE_J_TUBE_SPEC, world, track)


__all__ = ["BOYLE_J_TUBE_SPEC", "BOYLE_J_TUBE_WORLDS", "make_boyle_j_tube_case"]
