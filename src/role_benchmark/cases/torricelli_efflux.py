"""Matched torricelli efflux benchmark family."""

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
        "exit_speed_m_per_s": parameters["reference_speed_m_per_s"]
        * float(controls["liquid_head_m"]) ** parameters["head_exponent"]
        * (float(controls["orifice_area_mm2"]) / 5.0)
        ** parameters["area_exponent"]
    }


def _expression(
    reference: float, head_exponent: float, area_exponent: float
) -> Mapping[str, Any]:
    return mul(
        reference,
        power(var("liquid_head_m"), head_exponent),
        power(div(var("orifice_area_mm2"), 5.0), area_exponent),
    )


TORRICELLI_EFFLUX_SPEC = MatchedFamilySpec(
    family="torricelli_efflux",
    case_id_prefix="fluid.efflux",
    swap_public_instance_ids=True,
    response_title="the liquid-head efflux relation",
    apparatus_name="constant_head_efflux_tank",
    apparatus_description=(
        "A large constant-head tank holding a fixed single-phase test liquid, with "
        "interchangeable geometrically matched outlet plates and an optical exit-speed meter."
    ),
    background=(
        "Liquid exits a small opening from a large maintained reservoir. The free "
        "surface and outlet share the same ambient pressure, and all liquid and outlet "
        "properties other than the listed controls are held fixed. Determine empirically "
        "how exit speed changes with liquid head and outlet area."
    ),
    initial_observations=(
        "The measured exit speed is stable while the selected head is maintained.",
    ),
    controls=(
        ControlSpec(
            name="liquid_head_m",
            description="Vertical liquid height above the outlet center.",
            unit="m",
            minimum=0.1,
            maximum=2.0,
        ),
        ControlSpec(
            name="orifice_area_mm2",
            description="Area of the small outlet opening.",
            unit="mm^2",
            minimum=1.0,
            maximum=20.0,
        ),
    ),
    readouts=(
        ReadoutSpec(
            name="exit_speed_m_per_s",
            description="Mean liquid speed immediately outside the outlet.",
            unit="m/s",
            resolution=0.01,
        ),
    ),
    identification_model="efflux_power_law",
    identification_parameter_specs=(
        IdentificationParameterSpec(
            "reference_speed_m_per_s",
            "Exit speed at liquid_head_m = 1 m and orifice_area_mm2 = 5 mm^2.",
            "m/s",
            0.0,
            None,
        ),
        IdentificationParameterSpec(
            "head_exponent",
            "Power-law exponent of liquid_head_m / 1 m.",
            "1",
            -8.0,
            8.0,
        ),
        IdentificationParameterSpec(
            "area_exponent",
            "Power-law exponent of orifice_area_mm2 / 5 mm^2.",
            "1",
            -8.0,
            8.0,
        ),
    ),
    identification_formula=(
        "v = reference_speed_m_per_s*(liquid_head_m/1 m)^head_exponent"
        "*(orifice_area_mm2/5 mm^2)^area_exponent"
    ),
    predict=_predict,
    truths={
        "historical": MatchedTruth(
            parameters={
                "reference_speed_m_per_s": 4.43,
                "head_exponent": 0.5,
                "area_exponent": 0.0,
            },
            discovery_outputs={
                "exit_speed_m_per_s": _expression(4.43, 0.5, 0.0)
            },
            applicability=(
                "Steady incompressible efflux in the Bernoulli/Torricelli ideal limit over the stated liquid-head and outlet-area ranges.",
            ),
            fixed_conditions=(
                "Viscous dissipation, contraction and discharge losses are negligible, and the large reservoir makes free-surface speed negligible relative to outlet speed.",
                "Free surface and outlet are at the same ambient pressure; liquid density, gravitational acceleration, and outlet elevation remain fixed, while the interchangeable openings retain the same shape, edge profile, thickness, and orientation as their selected area changes.",
            ),
        ),
        "counterfactual": MatchedTruth(
            parameters={
                "reference_speed_m_per_s": 4.43,
                "head_exponent": 1.0,
                "area_exponent": 0.0,
            },
            discovery_outputs={
                "exit_speed_m_per_s": _expression(4.43, 1.0, 0.0)
            },
            applicability=(
                "Authored alternate steady-efflux law over the same liquid-head and outlet-area ranges; it is not asserted to follow Bernoulli's equation.",
            ),
            fixed_conditions=(
                "The encoded linear head response is the complete idealized outlet-speed law, with no additional viscous, contraction, or area correction.",
                "Free surface and outlet are at the same ambient pressure; liquid properties, gravitational environment, and outlet elevation remain fixed, while the interchangeable openings retain the same shape, edge profile, thickness, and orientation as their selected area changes.",
            ),
        ),
    },
    diagnostic_conditions=(
        {"liquid_head_m": 0.1, "orifice_area_mm2": 5.0},
        {"liquid_head_m": 0.2, "orifice_area_mm2": 5.0},
        {"liquid_head_m": 0.5, "orifice_area_mm2": 5.0},
        {"liquid_head_m": 1.0, "orifice_area_mm2": 5.0},
        {"liquid_head_m": 2.0, "orifice_area_mm2": 5.0},
        {"liquid_head_m": 0.5, "orifice_area_mm2": 1.0},
        {"liquid_head_m": 0.5, "orifice_area_mm2": 20.0},
        {"liquid_head_m": 1.5, "orifice_area_mm2": 12.0},
    ),
    hidden_conditions=(
        {"liquid_head_m": 0.12, "orifice_area_mm2": 2.0},
        {"liquid_head_m": 0.24, "orifice_area_mm2": 15.0},
        {"liquid_head_m": 0.45, "orifice_area_mm2": 6.0},
        {"liquid_head_m": 0.8, "orifice_area_mm2": 19.0},
        {"liquid_head_m": 1.15, "orifice_area_mm2": 4.0},
        {"liquid_head_m": 1.55, "orifice_area_mm2": 11.0},
        {"liquid_head_m": 1.9, "orifice_area_mm2": 7.0},
    ),
    credits=(
        SourceCredit(
            citation=(
                "Evangelista Torricelli, Opera geometrica, De motu aquarum "
                "within De motu projectorum (1644)."
            ),
            url="https://www.e-rara.ch/zut/content/structure/1275063",
            role=(
                "Primary volume credited for the historical square-root head law; "
                "the optical meter and exact ranges are modern benchmark choices."
            ),
        ),
    ),
    counterfactual_change=(
        "Only the normalized liquid-head exponent changes from 1/2 to 1, while "
        "reference speed, outlet-area independence, apparatus, and range stay fixed."
    ),
    common_notes=DEFAULT_MATCHED_NOTES
    + (
        "Liquid head is measured vertically from the outlet center to the maintained "
        "free surface; the readout is speed immediately outside the outlet, not volume flow.",
    ),
)


def make_torricelli_efflux_case(
    world: str = "historical",
    track: BenchmarkTrack = BenchmarkTrack.IDENTIFICATION,
) -> BenchmarkCase:
    return make_matched_case(TORRICELLI_EFFLUX_SPEC, world, track)


__all__ = ["TORRICELLI_EFFLUX_SPEC", "make_torricelli_efflux_case"]
