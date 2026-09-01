"""Matched induction-coil worlds inspired by Faraday's experiments."""

from __future__ import annotations

from typing import Any, Mapping

from role_benchmark.models import BenchmarkTrack, ControlSpec, ReadoutSpec
from role_benchmark.protocols import BenchmarkCase

from .matched import DEFAULT_MATCHED_NOTES, IdentificationParameterSpec, MATCHED_WORLDS, MatchedFamilySpec, MatchedTruth, SourceCredit, make_matched_case


FARADAY_INDUCTION_WORLDS = MATCHED_WORLDS
_APPARATUS = "induction_coil_galvanometer"
_READOUT = "peak_emf_mv"
_REFERENCES = {
    "coil_turns": 100.0,
    "loop_area_cm2": 20.0,
    "field_change_mt": 10.0,
    "change_time_ms": 100.0,
}
_EXPONENTS = {
    "coil_turns": "turn_exponent",
    "loop_area_cm2": "area_exponent",
    "field_change_mt": "field_change_exponent",
    "change_time_ms": "change_time_exponent",
}

_CONTROLS = (
    ControlSpec("coil_turns", "Number of turns in the aligned pickup coil.", allowed_values=(50, 100, 200, 400)),
    ControlSpec("loop_area_cm2", "Area enclosed by each turn.", "cm^2", 5.0, 100.0),
    ControlSpec(
        "field_change_mt",
        "Magnitude of the spatially uniform magnetic-field change during a linear ramp.",
        "mT",
        1.0,
        50.0,
    ),
    ControlSpec(
        "change_time_ms",
        "Duration of the constant-slope linear magnetic-field ramp.",
        "ms",
        5.0,
        500.0,
    ),
)
_READOUTS = (
    ReadoutSpec(
        _READOUT,
        "Magnitude of the induced emf during the constant-slope ramp; this is the peak in the idealized ramp.",
        "mV",
        0.01,
    ),
)


def _predict(parameters: Mapping[str, float], controls: Mapping[str, Any]) -> Mapping[str, float]:
    value = float(parameters["reference_emf_mv"])
    for control, reference in _REFERENCES.items():
        value *= (float(controls[control]) / reference) ** float(parameters[_EXPONENTS[control]])
    return {_READOUT: value}


def _expression(parameters: Mapping[str, float]) -> Mapping[str, Any]:
    return {
        "op": "multiply",
        "args": [parameters["reference_emf_mv"]]
        + [
            {
                "op": "power",
                "args": [
                    {"op": "divide", "args": [{"var": control}, reference]},
                    parameters[_EXPONENTS[control]],
                ],
            }
            for control, reference in _REFERENCES.items()
        ],
    }


_HISTORICAL: Mapping[str, float] = {
    "reference_emf_mv": 20.0,
    "turn_exponent": 1.0,
    "area_exponent": 1.0,
    "field_change_exponent": 1.0,
    "change_time_exponent": -1.0,
}
_COUNTERFACTUAL: Mapping[str, float] = {**_HISTORICAL, "change_time_exponent": -0.70}
_HIDDEN = (
    (50, 8.0, 4.0, 300.0), (100, 15.0, 35.0, 250.0), (200, 35.0, 8.0, 60.0),
    (400, 12.0, 22.0, 180.0), (50, 80.0, 45.0, 20.0), (200, 60.0, 18.0, 450.0),
    (400, 95.0, 3.0, 90.0),
)

FARADAY_INDUCTION_SPEC = MatchedFamilySpec(
    family="faraday_induction",
    case_id_prefix="induction.coil",
    swap_public_instance_ids=True,
    response_title="the electromagnetic-induction response",
    apparatus_name=_APPARATUS,
    apparatus_description="Aligned pickup coils, a controlled field ramp, timer, and galvanometer.",
    background=(
        "A pickup coil is connected to a galvanometer inside a controlled magnetic "
        "field. Apply a spatially uniform field change as a linear ramp. The meter "
        "responds during the ramp but returns to zero when the field is steady. "
        "Infer the law governing response magnitude."
    ),
    initial_observations=(
        "A steady field produces no sustained meter deflection.",
        "Changing the field produces a transient voltage whose dependencies are not given.",
    ),
    controls=_CONTROLS,
    readouts=_READOUTS,
    identification_model="faraday_flux_change_power_law",
    identification_parameter_specs=(
        IdentificationParameterSpec(
            "reference_emf_mv",
            "Peak EMF at coil_turns = 100, loop_area_cm2 = 20 cm^2, field_change_mt = 10 mT, and change_time_ms = 100 ms.",
            "mV",
            0.0,
            None,
        ),
        IdentificationParameterSpec(
            "turn_exponent",
            "Power-law exponent of coil_turns / 100.",
            "1",
            -8.0,
            8.0,
        ),
        IdentificationParameterSpec(
            "area_exponent",
            "Power-law exponent of loop_area_cm2 / 20 cm^2.",
            "1",
            -8.0,
            8.0,
        ),
        IdentificationParameterSpec(
            "field_change_exponent",
            "Power-law exponent of field_change_mt / 10 mT.",
            "1",
            -8.0,
            8.0,
        ),
        IdentificationParameterSpec(
            "change_time_exponent",
            "Power-law exponent of change_time_ms / 100 ms.",
            "1",
            -8.0,
            8.0,
        ),
    ),
    identification_formula=(
        "emf=reference_emf_mv*(coil_turns/100)^turn_exponent*"
        "(loop_area_cm2/20)^area_exponent*(field_change_mt/10)^field_change_exponent*"
        "(change_time_ms/100)^change_time_exponent."
    ),
    predict=_predict,
    truths={
        "historical": MatchedTruth(
            _HISTORICAL,
            {_READOUT: _expression(_HISTORICAL)},
            applicability=(
                "Quasistatic induction in a pickup coil during a spatially uniform, constant-slope magnetic-field ramp normal to every turn.",
            ),
            fixed_conditions=(
                "Every turn encloses the selected loop area and experiences the same field change; coil orientation, winding geometry, and detector calibration remain fixed.",
                "The high-impedance meter does not load the induced voltage, and self-inductance, resistance-dependent loading, switching-edge transients, and stray flux are absent from the reported ramp value.",
                "The reported magnitude is the absolute emf during the ramp; reversal of the field-change direction would reverse polarity without changing this readout.",
            ),
        ),
        "counterfactual": MatchedTruth(
            _COUNTERFACTUAL,
            {_READOUT: _expression(_COUNTERFACTUAL)},
            applicability=(
                "Benchmark-authored induction world with exact -0.70 ramp-duration scaling and unchanged turn, area, and field-change responses over the declared ranges.",
            ),
            fixed_conditions=(
                "The alternate duration exponent is the complete selected-world induction response rather than a switching transient or meter-loading artifact.",
                "Every turn experiences the same uniform normal field ramp; coil geometry, detector calibration, and acquisition convention remain fixed.",
                "Self-inductance, resistance-dependent loading, switching-edge transients, and stray flux are absent from the reported ramp value.",
            ),
        ),
    },
    diagnostic_conditions=(
        {"coil_turns": 50, "loop_area_cm2": 5.0, "field_change_mt": 1.0, "change_time_ms": 5.0},
        {"coil_turns": 100, "loop_area_cm2": 20.0, "field_change_mt": 10.0, "change_time_ms": 100.0},
        {"coil_turns": 200, "loop_area_cm2": 60.0, "field_change_mt": 30.0, "change_time_ms": 250.0},
        {"coil_turns": 400, "loop_area_cm2": 100.0, "field_change_mt": 50.0, "change_time_ms": 500.0},
    ),
    hidden_conditions=tuple(
        {"coil_turns": turns, "loop_area_cm2": area, "field_change_mt": field, "change_time_ms": time}
        for turns, area, field, time in _HIDDEN
    ),
    credits=(SourceCredit(
        "Michael Faraday, Experimental Researches in Electricity, Vol. I",
        "https://www.gutenberg.org/files/14986/14986-h/14986-h.htm",
        "Source for induced currents produced by changing magnetic relations.",
    ),),
    counterfactual_change="Only the normalized change-time exponent changes from -1.00 to -0.70.",
    common_notes=DEFAULT_MATCHED_NOTES + (
        "The field is spatially uniform, normal to every turn, and changes at a constant rate during each ramp.",
        "The meter does not load the voltage; switching-edge transients are outside this world.",
    ),
    budget=10,
    max_replicates=10,
    relative_tolerance=0.04,
)


def make_faraday_induction_case(
    world: str = "historical", track: BenchmarkTrack = BenchmarkTrack.IDENTIFICATION
) -> BenchmarkCase:
    return make_matched_case(FARADAY_INDUCTION_SPEC, world, track)


__all__ = ["FARADAY_INDUCTION_SPEC", "FARADAY_INDUCTION_WORLDS", "make_faraday_induction_case"]
