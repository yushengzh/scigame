"""Matched brownian diffusion benchmark family."""

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
        "mean_squared_displacement_um2": parameters["reference_msd_um2"]
        * float(controls["lag_time_s"]) ** parameters["time_exponent"]
        * (float(controls["particle_radius_um"]) / 0.5)
        ** parameters["radius_exponent"]
    }


def _expression(
    reference: float, time_exponent: float, radius_exponent: float
) -> Mapping[str, Any]:
    return mul(
        reference,
        power(var("lag_time_s"), time_exponent),
        power(div(var("particle_radius_um"), 0.5), radius_exponent),
    )


BROWNIAN_DIFFUSION_SPEC = MatchedFamilySpec(
    family="brownian_diffusion",
    case_id_prefix="particle.motion",
    response_title="the tracer mean-squared-displacement relation",
    apparatus_name="two_dimensional_tracer_microscope",
    apparatus_description=(
        "A temperature-controlled bulk fluid containing selectable spherical tracers, "
        "with a video microscope that records their two-dimensional image-plane "
        "displacements and an ensemble displacement analyzer."
    ),
    background=(
        "Microscopic spherical tracers undergo reproducible stochastic motion far "
        "from boundaries. Temperature and carrier-medium preparation are fixed. The "
        "readout is the two-dimensional image-plane projection of three-dimensional "
        "motion. Determine how ensemble mean-squared displacement depends on lag "
        "time and tracer radius over the listed observation window."
    ),
    initial_observations=(
        "The ensemble mean displacement is approximately zero, while its squared "
        "magnitude is positive and reproducible.",
    ),
    controls=(
        ControlSpec("lag_time_s", "Time interval used for displacement pairs.", "s", 0.05, 5.0),
        ControlSpec("particle_radius_um", "Radius of the spherical tracer.", "um", 0.2, 1.0),
    ),
    readouts=(
        ReadoutSpec(
            "mean_squared_displacement_um2",
            "Two-dimensional ensemble mean of squared displacement magnitude.",
            "um^2",
            0.01,
        ),
    ),
    identification_model="tracer_msd_power_law",
    identification_parameter_specs=(
        IdentificationParameterSpec(
            "reference_msd_um2",
            "Mean-squared displacement at lag_time_s = 1 s and particle_radius_um = 0.5 um.",
            "um^2",
            0.0,
            None,
        ),
        IdentificationParameterSpec(
            "time_exponent",
            "Power-law exponent of lag_time_s / 1 s.",
            "1",
            -8.0,
            8.0,
        ),
        IdentificationParameterSpec(
            "radius_exponent",
            "Power-law exponent of particle_radius_um / 0.5 um.",
            "1",
            -8.0,
            8.0,
        ),
    ),
    identification_formula=(
        "MSD = reference_msd_um2*(lag_time_s/1 s)^time_exponent*"
        "(particle_radius_um/0.5 um)^radius_exponent"
    ),
    predict=_predict,
    truths={
        "historical": MatchedTruth(
            parameters={
                "reference_msd_um2": 8.0,
                "time_exponent": 1.0,
                "radius_exponent": -1.0,
            },
            discovery_outputs={
                "mean_squared_displacement_um2": _expression(8.0, 1.0, -1.0)
            },
            applicability=(
                "Overdamped translational diffusion of dilute spherical tracers in a "
                "Newtonian fluid, observed at lags long compared with momentum relaxation "
                "and short compared with drift or confinement times.",
            ),
            fixed_conditions=(
                "Tracer surfaces obey no slip, hydrodynamic radius equals the selected "
                "particle radius, and inter-particle hydrodynamic interactions are "
                "negligible.",
                "Fluid viscosity and absolute temperature are constant; tracers remain far "
                "from walls and the suspension is dilute and at equilibrium.",
                "The readout is the two-dimensional image-plane MSD, so isotropic "
                "three-dimensional diffusion contributes 4D times the lag.",
            ),
        ),
        "counterfactual": MatchedTruth(
            parameters={
                "reference_msd_um2": 8.0,
                "time_exponent": 2.0,
                "radius_exponent": -1.0,
            },
            discovery_outputs={
                "mean_squared_displacement_um2": _expression(8.0, 2.0, -1.0)
            },
            applicability=(
                "Benchmark-authored persistent stochastic dynamics with an exact "
                "quadratic-lag image-plane MSD and inverse-radius scaling over the "
                "declared finite observation window.",
            ),
            fixed_conditions=(
                "The quadratic time dependence and inverse-radius dependence jointly "
                "define the selected-world mechanism; it is not the short-time inertial "
                "ballistic limit of an ordinary Brownian particle.",
                "Carrier preparation, temperature, tracer dilution, distance from walls, "
                "tracking calibration, and image-plane projection are fixed.",
                "The stochastic process has zero ensemble mean displacement and the stated "
                "MSD throughout the listed lag range.",
            ),
        ),
    },
    diagnostic_conditions=(
        {"lag_time_s": 0.05, "particle_radius_um": 0.5},
        {"lag_time_s": 0.1, "particle_radius_um": 0.5},
        {"lag_time_s": 0.5, "particle_radius_um": 0.5},
        {"lag_time_s": 1.0, "particle_radius_um": 0.5},
        {"lag_time_s": 5.0, "particle_radius_um": 0.5},
        {"lag_time_s": 1.0, "particle_radius_um": 0.2},
        {"lag_time_s": 1.0, "particle_radius_um": 1.0},
        {"lag_time_s": 2.5, "particle_radius_um": 0.75},
    ),
    hidden_conditions=(
        {"lag_time_s": 0.07, "particle_radius_um": 0.9},
        {"lag_time_s": 0.16, "particle_radius_um": 0.25},
        {"lag_time_s": 0.4, "particle_radius_um": 0.7},
        {"lag_time_s": 0.85, "particle_radius_um": 0.35},
        {"lag_time_s": 1.4, "particle_radius_um": 1.0},
        {"lag_time_s": 2.7, "particle_radius_um": 0.55},
        {"lag_time_s": 4.6, "particle_radius_um": 0.22},
    ),
    credits=(
        SourceCredit(
            citation=(
                "Albert Einstein, Ueber die von der molekularkinetischen Theorie "
                "der Waerme geforderte Bewegung ... (1905), Annalen der Physik "
                "322, 549-560."
            ),
            url="https://doi.org/10.1002/andp.19053220806",
            role=(
                "Primary source credited for linear-in-time Brownian mean-squared "
                "displacement and the diffusion-coefficient framework."
            ),
        ),
    ),
    counterfactual_change=(
        "Only the lag-time exponent changes from 1 to 2, creating an authored "
        "quadratic-lag twin. It is not presented as the real inertial ballistic "
        "regime; tracer-radius dependence and the one-second reference MSD stay fixed."
    ),
    common_notes=DEFAULT_MATCHED_NOTES
    + (
        "Every condition uses the same carrier-medium preparation, temperature, "
        "tracking calibration, and image-plane projection convention.",
    ),
)


def make_brownian_diffusion_case(
    world: str = "historical",
    track: BenchmarkTrack = BenchmarkTrack.IDENTIFICATION,
) -> BenchmarkCase:
    return make_matched_case(BROWNIAN_DIFFUSION_SPEC, world, track)


__all__ = ["BROWNIAN_DIFFUSION_SPEC", "make_brownian_diffusion_case"]
