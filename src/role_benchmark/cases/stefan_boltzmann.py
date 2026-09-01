"""Matched stefan boltzmann benchmark family."""

from __future__ import annotations

from typing import Any, Mapping

from role_benchmark.models import BenchmarkTrack, ControlSpec, ReadoutSpec
from role_benchmark.protocols import BenchmarkCase

from ._expressions import div, mul, power, sub, var
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
    exponent = parameters["temperature_exponent"]
    temperature_term = (float(controls["emitter_temperature_k"]) / 500.0) ** (
        exponent
    ) - (float(controls["ambient_temperature_k"]) / 500.0) ** exponent
    return {
        "net_radiative_power_w": parameters["reference_power_scale_w"]
        * (float(controls["emitting_area_cm2"]) / 100.0)
        * temperature_term
    }


def _expression(reference: float, exponent: float) -> Mapping[str, Any]:
    return mul(
        reference,
        div(var("emitting_area_cm2"), 100.0),
        sub(
            power(div(var("emitter_temperature_k"), 500.0), exponent),
            power(div(var("ambient_temperature_k"), 500.0), exponent),
        ),
    )


_STEFAN_REFERENCE_POWER_W = 5.670374419e-8 * 0.01 * 500.0**4


STEFAN_BOLTZMANN_SPEC = MatchedFamilySpec(
    family="stefan_boltzmann",
    case_id_prefix="thermal.radiation",
    response_title="the net thermal-radiation relation",
    apparatus_name="thermal_radiation_calorimeter",
    apparatus_description=(
        "A temperature-controlled radiative emitter of selectable exposed area in a "
        "temperature-controlled enclosure, with a calibrated net-radiation calorimeter."
    ),
    background=(
        "An emitter with a stable surface preparation exchanges thermal radiation with "
        "a cooler enclosure. The calorimeter isolates the net radiative contribution. "
        "Determine how that power depends on emitter temperature, enclosure temperature, "
        "and emitting area."
    ),
    initial_observations=(
        "Net power is outward throughout the available temperature range.",
    ),
    controls=(
        ControlSpec(
            "emitter_temperature_k",
            "Absolute temperature of the emitter.",
            "K",
            400.0,
            900.0,
        ),
        ControlSpec(
            "ambient_temperature_k",
            "Absolute temperature of the enclosing radiative environment.",
            "K",
            250.0,
            350.0,
        ),
        ControlSpec(
            "emitting_area_cm2",
            "Exposed emitting surface area.",
            "cm^2",
            20.0,
            200.0,
        ),
    ),
    readouts=(
        ReadoutSpec(
            "net_radiative_power_w",
            "Net radiative power leaving the emitter.",
            "W",
            0.01,
        ),
    ),
    identification_model="net_radiation_power_law",
    identification_parameter_specs=(
        IdentificationParameterSpec(
            "reference_power_scale_w",
            "Power scale multiplying normalized emitting area and the difference of normalized emitter and ambient temperature powers.",
            "W",
            0.0,
            None,
        ),
        IdentificationParameterSpec(
            "temperature_exponent",
            "Common exponent applied to emitter_temperature_k / 500 K and ambient_temperature_k / 500 K.",
            "1",
            -8.0,
            8.0,
        ),
    ),
    identification_formula=(
        "P = reference_power_scale_w*(emitting_area_cm2/100)*"
        "[(emitter_temperature_k/500)^temperature_exponent - "
        "(ambient_temperature_k/500)^temperature_exponent]"
    ),
    predict=_predict,
    truths={
        "historical": MatchedTruth(
            parameters={
                "reference_power_scale_w": _STEFAN_REFERENCE_POWER_W,
                "temperature_exponent": 4.0,
            },
            discovery_outputs={
                "net_radiative_power_w": _expression(
                    _STEFAN_REFERENCE_POWER_W, 4.0
                )
            },
            applicability=(
                "Net exchange between an opaque diffuse black emitter and a much larger "
                "isothermal black enclosure in radiative equilibrium.",
            ),
            fixed_conditions=(
                "The emitter has unit total hemispherical emissivity in this idealized "
                "world and the enclosure subtends view factor one.",
                "Emitter and enclosure temperatures are spatially uniform and constant "
                "during a reported measurement.",
                "The calibrated readout excludes conduction, convection, supports, and "
                "other non-radiative heat transfer.",
            ),
        ),
        "counterfactual": MatchedTruth(
            parameters={
                "reference_power_scale_w": _STEFAN_REFERENCE_POWER_W,
                "temperature_exponent": 3.0,
            },
            discovery_outputs={
                "net_radiative_power_w": _expression(
                    _STEFAN_REFERENCE_POWER_W, 3.0
                )
            },
            applicability=(
                "Benchmark-authored net-radiation world with a cubic absolute-temperature "
                "law for the same diffuse emitter-enclosure geometry.",
            ),
            fixed_conditions=(
                "The selected surface preparation has unit normalized radiative factor "
                "and the enclosure subtends view factor one.",
                "Emitter and enclosure temperatures are spatially uniform and constant "
                "during a reported measurement.",
                "The calibrated readout excludes conduction, convection, supports, and "
                "other non-radiative heat transfer.",
            ),
        ),
    },
    diagnostic_conditions=(
        {"emitter_temperature_k": 400.0, "ambient_temperature_k": 300.0, "emitting_area_cm2": 100.0},
        {"emitter_temperature_k": 500.0, "ambient_temperature_k": 300.0, "emitting_area_cm2": 100.0},
        {"emitter_temperature_k": 700.0, "ambient_temperature_k": 300.0, "emitting_area_cm2": 100.0},
        {"emitter_temperature_k": 900.0, "ambient_temperature_k": 300.0, "emitting_area_cm2": 100.0},
        {"emitter_temperature_k": 600.0, "ambient_temperature_k": 250.0, "emitting_area_cm2": 100.0},
        {"emitter_temperature_k": 600.0, "ambient_temperature_k": 350.0, "emitting_area_cm2": 100.0},
        {"emitter_temperature_k": 600.0, "ambient_temperature_k": 300.0, "emitting_area_cm2": 20.0},
        {"emitter_temperature_k": 600.0, "ambient_temperature_k": 300.0, "emitting_area_cm2": 200.0},
    ),
    hidden_conditions=(
        {"emitter_temperature_k": 420.0, "ambient_temperature_k": 270.0, "emitting_area_cm2": 35.0},
        {"emitter_temperature_k": 480.0, "ambient_temperature_k": 330.0, "emitting_area_cm2": 160.0},
        {"emitter_temperature_k": 560.0, "ambient_temperature_k": 250.0, "emitting_area_cm2": 85.0},
        {"emitter_temperature_k": 650.0, "ambient_temperature_k": 310.0, "emitting_area_cm2": 45.0},
        {"emitter_temperature_k": 735.0, "ambient_temperature_k": 285.0, "emitting_area_cm2": 190.0},
        {"emitter_temperature_k": 820.0, "ambient_temperature_k": 340.0, "emitting_area_cm2": 110.0},
        {"emitter_temperature_k": 890.0, "ambient_temperature_k": 260.0, "emitting_area_cm2": 70.0},
    ),
    credits=(
        SourceCredit(
            citation=(
                "Josef Stefan, Ueber die Beziehung zwischen der Waermestrahlung "
                "und der Temperatur (1879), Sitzungsberichte 79, 391-428."
            ),
            url="https://www.ub.edu/hcub/hfq/node/89",
            role="Primary empirical source for the historical fourth-power relation.",
        ),
        SourceCredit(
            citation=(
                "Ludwig Boltzmann, Ableitung des Stefan'schen Gesetzes (1884), "
                "Annalen der Physik 258, 291-294."
            ),
            url="https://doi.org/10.1002/andp.18842580616",
            role="Primary theoretical derivation credited for the historical law.",
        ),
    ),
    counterfactual_change=(
        "Only the normalized absolute-temperature exponent changes from 4 to 3; "
        "area scaling, net hot-minus-ambient structure, and reference scale stay fixed."
    ),
    common_notes=DEFAULT_MATCHED_NOTES
    + (
        "Emitter and enclosure surface preparations are fixed but their spectral law "
        "is not supplied; conduction and convection are excluded from the reported readout.",
    ),
)


def make_stefan_boltzmann_case(
    world: str = "historical",
    track: BenchmarkTrack = BenchmarkTrack.IDENTIFICATION,
) -> BenchmarkCase:
    return make_matched_case(STEFAN_BOLTZMANN_SPEC, world, track)


__all__ = ["STEFAN_BOLTZMANN_SPEC", "make_stefan_boltzmann_case"]
