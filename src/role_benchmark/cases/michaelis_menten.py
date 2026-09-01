"""Matched michaelis menten benchmark family."""

from __future__ import annotations

from typing import Any, Mapping

from role_benchmark.models import BenchmarkTrack, ControlSpec, ReadoutSpec
from role_benchmark.protocols import BenchmarkCase

from ._expressions import add, div, mul, power, var
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
    substrate = float(controls["substrate_concentration_mM"])
    enzyme = float(controls["enzyme_concentration_relative"])
    km = parameters["michaelis_constant_mM"]
    denominator = (
        km
        + substrate
        + parameters["substrate_inhibition_strength"] * substrate**2 / km
    )
    return {
        "initial_rate_uM_per_min": parameters["reference_vmax_uM_per_min"]
        * enzyme
        * substrate
        / denominator
    }


def _expression(
    maximum_rate: float, km: float, inhibition: float
) -> Mapping[str, Any]:
    substrate = var("substrate_concentration_mM")
    denominator = add(
        km,
        substrate,
        div(mul(inhibition, power(substrate, 2.0)), km),
    )
    return div(
        mul(
            maximum_rate,
            var("enzyme_concentration_relative"),
            substrate,
        ),
        denominator,
    )


MICHAELIS_MENTEN_SPEC = MatchedFamilySpec(
    family="michaelis_menten",
    case_id_prefix="enzyme.rate",
    swap_public_instance_ids=True,
    response_title="the enzyme initial-rate relation",
    apparatus_name="enzyme_initial_rate_assay",
    apparatus_description=(
        "A temperature-buffered enzyme assay with adjustable substrate and enzyme "
        "concentrations and an initial-rate spectrophotometer."
    ),
    background=(
        "An enzyme converts one substrate to product under fixed buffer and "
        "temperature. Determine how the initial product-formation rate depends on "
        "substrate and enzyme concentrations."
    ),
    initial_observations=(
        "Initial rates are recorded before appreciable substrate depletion.",
    ),
    controls=(
        ControlSpec(
            "substrate_concentration_mM",
            "Initial substrate concentration.",
            "mM",
            0.05,
            10.0,
        ),
        ControlSpec(
            "enzyme_concentration_relative",
            "Enzyme concentration relative to a reference preparation.",
            "relative",
            0.25,
            2.0,
        ),
    ),
    readouts=(
        ReadoutSpec(
            "initial_rate_uM_per_min",
            "Initial product concentration-formation rate.",
            "umol L^-1 min^-1",
            0.01,
        ),
    ),
    identification_model="substrate_inhibition_rate",
    identification_parameter_specs=(
        IdentificationParameterSpec(
            "reference_vmax_uM_per_min",
            "Rate scale at enzyme_concentration_relative = 1 before the substrate-dependent denominator is applied.",
            "umol L^-1 min^-1",
            0.0,
            None,
        ),
        IdentificationParameterSpec(
            "michaelis_constant_mM",
            "Positive substrate-concentration scale appearing in both the saturation and inhibition terms.",
            "mM",
            0.001,
            None,
        ),
        IdentificationParameterSpec(
            "substrate_inhibition_strength",
            "Nonnegative dimensionless coefficient of the quadratic substrate-inhibition term.",
            "1",
            0.0,
            None,
        ),
    ),
    identification_formula=(
        "initial_rate_uM_per_min = reference_vmax_uM_per_min*"
        "enzyme_concentration_relative*substrate_concentration_mM/"
        "[michaelis_constant_mM + substrate_concentration_mM + "
        "substrate_inhibition_strength*substrate_concentration_mM^2/"
        "michaelis_constant_mM]"
    ),
    predict=_predict,
    truths={
        "historical": MatchedTruth(
            parameters={
                "reference_vmax_uM_per_min": 80.0,
                "michaelis_constant_mM": 1.0,
                "substrate_inhibition_strength": 0.0,
            },
            discovery_outputs={
                "initial_rate_uM_per_min": _expression(80.0, 1.0, 0.0)
            },
            applicability=(
                "Single-substrate quasi-steady-state Michaelis-Menten kinetics in an "
                "initial-rate window with no substrate inhibition.",
            ),
            fixed_conditions=(
                "One unit of relative enzyme concentration is a fixed reference "
                "preparation; enzyme remains negligible compared with substrate across "
                "the declared range.",
                "Product accumulation, reverse reaction, enzyme inactivation, mass-transfer "
                "limitation, and appreciable substrate depletion are negligible during the "
                "rate-estimation window.",
                "Temperature, pH, ionic strength, optical path, and the conversion from "
                "absorbance slope to concentration rate are fixed and calibrated.",
            ),
        ),
        "counterfactual": MatchedTruth(
            parameters={
                "reference_vmax_uM_per_min": 80.0,
                "michaelis_constant_mM": 1.0,
                "substrate_inhibition_strength": 0.25,
            },
            discovery_outputs={
                "initial_rate_uM_per_min": _expression(80.0, 1.0, 0.25)
            },
            applicability=(
                "Single-substrate initial-rate kinetics with one additional inhibitory "
                "substrate-binding term, giving denominator Km + S + S^2/Ki.",
            ),
            fixed_conditions=(
                "Km is 1 mM and the dimensionless inhibition strength Km/Ki is 0.25, "
                "equivalent to Ki=4 mM in this selected world.",
                "One unit of relative enzyme concentration is a fixed reference "
                "preparation; enzyme remains negligible compared with substrate across "
                "the declared range.",
                "Product accumulation, reverse reaction, enzyme inactivation, mass-transfer "
                "limitation, and appreciable substrate depletion are negligible during the "
                "rate-estimation window.",
                "Temperature, pH, ionic strength, optical path, and the conversion from "
                "absorbance slope to concentration rate are fixed and calibrated.",
            ),
        ),
    },
    diagnostic_conditions=(
        {"substrate_concentration_mM": 0.05, "enzyme_concentration_relative": 1.0},
        {"substrate_concentration_mM": 0.2, "enzyme_concentration_relative": 1.0},
        {"substrate_concentration_mM": 0.7, "enzyme_concentration_relative": 1.0},
        {"substrate_concentration_mM": 1.5, "enzyme_concentration_relative": 1.0},
        {"substrate_concentration_mM": 4.0, "enzyme_concentration_relative": 1.0},
        {"substrate_concentration_mM": 10.0, "enzyme_concentration_relative": 1.0},
        {"substrate_concentration_mM": 1.0, "enzyme_concentration_relative": 0.25},
        {"substrate_concentration_mM": 1.0, "enzyme_concentration_relative": 2.0},
    ),
    hidden_conditions=(
        {"substrate_concentration_mM": 0.08, "enzyme_concentration_relative": 1.7},
        {"substrate_concentration_mM": 0.25, "enzyme_concentration_relative": 0.4},
        {"substrate_concentration_mM": 0.7, "enzyme_concentration_relative": 1.1},
        {"substrate_concentration_mM": 1.2, "enzyme_concentration_relative": 1.8},
        {"substrate_concentration_mM": 2.5, "enzyme_concentration_relative": 0.65},
        {"substrate_concentration_mM": 4.0, "enzyme_concentration_relative": 1.35},
        {"substrate_concentration_mM": 7.5, "enzyme_concentration_relative": 0.9},
        {"substrate_concentration_mM": 9.5, "enzyme_concentration_relative": 1.55},
    ),
    credits=(
        SourceCredit(
            citation=(
                "Leonor Michaelis and Maud L. Menten, Die Kinetik der "
                "Invertinwirkung (1913), Biochemische Zeitschrift 49, 333-369."
            ),
            url="https://pmc.ncbi.nlm.nih.gov/articles/PMC3381512/",
            role=(
                "Original paper and scholarly translation credited for the "
                "historical saturating initial-rate law."
            ),
        ),
        SourceCredit(
            citation="J. B. S. Haldane, Enzymes (1930).",
            url="https://www.ncbi.nlm.nih.gov/nlmcatalog/152965",
            role=(
                "Classic source credited for substrate-inhibition mechanisms that "
                "motivate, but do not uniquely determine, the authored twin."
            ),
        ),
    ),
    counterfactual_change=(
        "Only one denominator term is activated: its dimensionless substrate-"
        "inhibition strength changes from 0 to 0.25. Low-substrate behavior and "
        "linear enzyme scaling stay fixed."
    ),
    common_notes=DEFAULT_MATCHED_NOTES,
)


def make_michaelis_menten_case(
    world: str = "historical",
    track: BenchmarkTrack = BenchmarkTrack.IDENTIFICATION,
) -> BenchmarkCase:
    return make_matched_case(MICHAELIS_MENTEN_SPEC, world, track)


__all__ = ["MICHAELIS_MENTEN_SPEC", "make_michaelis_menten_case"]
