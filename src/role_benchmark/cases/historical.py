"""The current Historical benchmark: twenty scientific relations and authored twins.

Scientific definitions live in the adjacent historical_cards.json, independently
of deprecated family implementations. Git records changes to this one dataset.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Mapping, Tuple

from role_benchmark.expression import evaluate_expression_program
from role_benchmark.models import BenchmarkTrack, ControlSpec, ReadoutSpec
from role_benchmark.protocols import BenchmarkCase

from .matched import (
    DEFAULT_MATCHED_NOTES,
    IdentificationParameterSpec,
    MatchedFamilySpec,
    MatchedTruth,
    SourceCredit,
    make_matched_case,
)

DATASET_ID = "role_benchmark.historical"
DATASET_STATUS = "accepted_after_independent_review"
EXPECTED_FAMILY_COUNT = 20
EXPECTED_CASE_COUNT = 80


@dataclass(frozen=True)
class StructuralMutation:
    """Authored change explaining the relation between the paired worlds."""

    mutation_id: str
    kind: str
    before_subtree: Any
    after_subtree: Any
    expected_occurrences: int
    rationale: str
    dependent_repairs: str


@dataclass(frozen=True)
class HistoricalParameter:
    name: str
    value: float
    unit: str
    description: str


@dataclass(frozen=True)
class HistoricalScienceCard:
    schema: str
    release_status: str
    family: str
    title: str
    domain: str
    historical_claim: str
    historical_formula: str
    historical_parameters: Tuple[HistoricalParameter, ...]
    source_credits: Tuple[SourceCredit, ...]
    apparatus_name: str
    apparatus_description: str
    background: str
    controls: Tuple[ControlSpec, ...]
    readouts: Tuple[ReadoutSpec, ...]
    historical_outputs: Mapping[str, Any]
    counterfactual_outputs: Mapping[str, Any]
    mutations: Tuple[StructuralMutation, ...]
    diagnostic_conditions: Tuple[Mapping[str, Any], ...]
    hidden_conditions: Tuple[Mapping[str, Any], ...]
    historical_applicability: Tuple[str, ...]
    fixed_conditions: Tuple[str, ...]
    counterfactual_scope: Tuple[str, ...]
    identifiability_witness: str
    identifiability_scope: str
    relative_tolerance: float
    absolute_tolerances: Mapping[str, float]
    confidence_threshold: float
    require_held_out_interior: bool
    budget: int = 64


def _family_spec(
    card: HistoricalScienceCard,
    *,
    swap: bool,
) -> MatchedFamilySpec:
    control_names = tuple(item.name for item in card.controls)
    readout_names = tuple(item.name for item in card.readouts)

    def predict(parameters: Mapping[str, float], values: Mapping[str, Any]) -> Mapping[str, float]:
        selector = float(parameters["counterfactual_selector"])
        historical = evaluate_expression_program(
            {"outputs": card.historical_outputs}, values,
            allowed_variables=control_names, required_outputs=readout_names,
        )
        counterfactual = evaluate_expression_program(
            {"outputs": card.counterfactual_outputs}, values,
            allowed_variables=control_names, required_outputs=readout_names,
        )
        return {
            name: (1.0 - selector) * historical[name] + selector * counterfactual[name]
            for name in readout_names
        }

    branch_0 = json.dumps(card.historical_outputs, sort_keys=True, separators=(",", ":"))
    branch_1 = json.dumps(card.counterfactual_outputs, sort_keys=True, separators=(",", ":"))
    return MatchedFamilySpec(
        family=card.family,
        case_id_prefix="historical.%s" % card.family,
        swap_public_instance_ids=swap,
        response_title=card.title,
        apparatus_name=card.apparatus_name,
        apparatus_description=card.apparatus_description,
        background=card.background,
        initial_observations=(
            "Every legal setup has a deterministic response.",
            "The active response remains fixed for the entire case.",
        ),
        controls=card.controls,
        readouts=card.readouts,
        identification_model="two_branch_structural_response_family",
        identification_parameter_specs=(IdentificationParameterSpec(
            "counterfactual_selector",
            "Branch coordinate: 0 selects branch_0 and 1 selects branch_1.",
            "1", 0.0, 1.0,
        ),),
        identification_formula=(
            "For each readout y=(1-s)*branch_0+s*branch_1, where "
            "s=counterfactual_selector; branch_0=" + branch_0 + "; branch_1=" + branch_1
        ),
        predict=predict,
        truths={
            "historical": MatchedTruth(
                parameters={"counterfactual_selector": 0.0},
                discovery_outputs=card.historical_outputs,
                applicability=card.historical_applicability,
            ),
            "counterfactual": MatchedTruth(
                parameters={"counterfactual_selector": 1.0},
                discovery_outputs=card.counterfactual_outputs,
                applicability=card.counterfactual_scope,
            ),
        },
        diagnostic_conditions=card.diagnostic_conditions,
        hidden_conditions=card.hidden_conditions,
        credits=card.source_credits,
        counterfactual_change="; ".join(
            "%s (%s): %s" % (item.mutation_id, item.kind, item.rationale)
            for item in card.mutations
        ),
        common_notes=DEFAULT_MATCHED_NOTES + (
            "Counterfactual coherence is case-local and is enforced by one frozen "
            "expression across experiments, hypotheses and held-out evaluation.",
            "Finite identifiability witness: " + card.identifiability_witness,
        ),
        common_fixed_conditions=(
            "Inputs use the units and closed domains declared in the resource catalog.",
        ),
        budget=card.budget,
        max_replicates=1,
        confidence_threshold=card.confidence_threshold,
        relative_tolerance=card.relative_tolerance,
        absolute_tolerances=card.absolute_tolerances,
        require_held_out_interior=card.require_held_out_interior,
        case_id_includes_track=True,
    )


def _science_card(data: Mapping[str, Any]) -> HistoricalScienceCard:
    values = dict(data)
    values["controls"] = tuple(
        ControlSpec(**{**item, "allowed_values": tuple(item["allowed_values"])})
        for item in data["controls"]
    )
    for key, constructor in (
        ("readouts", ReadoutSpec),
        ("historical_parameters", HistoricalParameter),
        ("source_credits", SourceCredit),
        ("mutations", StructuralMutation),
    ):
        values[key] = tuple(constructor(**item) for item in data[key])
    for key in (
        "diagnostic_conditions", "hidden_conditions", "historical_applicability",
        "fixed_conditions", "counterfactual_scope",
    ):
        values[key] = tuple(data[key])
    return HistoricalScienceCard(**values)


_SCIENCE_CARD_DATA = json.loads(
    Path(__file__).with_name("historical_cards.json").read_text(encoding="utf-8")
)
HISTORICAL_FAMILIES: Tuple[str, ...] = tuple(_SCIENCE_CARD_DATA)
HISTORICAL_SCIENCE_CARDS: Mapping[str, HistoricalScienceCard] = {
    family: _science_card(data["science_card"])
    for family, data in _SCIENCE_CARD_DATA.items()
}
HISTORICAL_CASE_SPECS: Mapping[str, MatchedFamilySpec] = {
    family: _family_spec(
        HISTORICAL_SCIENCE_CARDS[family],
        swap=data["swap_public_instance_ids"],
    )
    for family, data in _SCIENCE_CARD_DATA.items()
}
HISTORICAL_CASE_KEYS: Tuple[tuple[str, str, str], ...] = tuple(
    (family, world, track.value)
    for family in HISTORICAL_FAMILIES
    for world in ("historical", "counterfactual")
    for track in BenchmarkTrack
)


def make_historical_case(
    family: str,
    world: str = "historical",
    track: BenchmarkTrack = BenchmarkTrack.IDENTIFICATION,
) -> BenchmarkCase:
    try:
        spec = HISTORICAL_CASE_SPECS[family]
    except (KeyError, TypeError) as exc:
        raise ValueError("unknown Historical family %r" % (family,)) from exc
    return make_matched_case(spec, world, track)


if len(HISTORICAL_FAMILIES) != EXPECTED_FAMILY_COUNT:
    raise AssertionError("Historical must contain exactly 20 families")
if len(HISTORICAL_CASE_KEYS) != EXPECTED_CASE_COUNT:
    raise AssertionError("Historical must contain exactly 80 cases")


__all__ = [
    "DATASET_ID", "DATASET_STATUS", "EXPECTED_CASE_COUNT", "EXPECTED_FAMILY_COUNT",
    "HISTORICAL_CASE_KEYS", "HISTORICAL_CASE_SPECS", "HISTORICAL_FAMILIES",
    "HISTORICAL_SCIENCE_CARDS", "HistoricalScienceCard", "make_historical_case",
]
