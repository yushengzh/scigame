"""Current Temporal relations and their benchmark-authored counterfactuals.

The packaged cards contain the accepted scientific definitions. Git records
dataset changes; loading a case does not activate another runtime or rebuild
counterfactual relations.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict

from role_benchmark.cases.matched import (
    IdentificationParameterSpec,
    MatchedFamilySpec,
    MatchedTruth,
    SourceCredit,
    make_matched_case,
)
from role_benchmark.expression import evaluate_expression_program
from role_benchmark.models import BenchmarkTrack, ControlSpec, ReadoutSpec
from role_benchmark.protocols import BenchmarkCase


DATASET_ID = "role_benchmark.temporal"
DATASET_STATUS = "accepted_after_independent_review"

_DATA = json.loads(Path(__file__).with_name("temporal_cards.json").read_text())
TEMPORAL_SCIENCE_CARDS = _DATA["families"]
TEMPORAL_CASE_FAMILIES = tuple(TEMPORAL_SCIENCE_CARDS)


def _family_spec(card: dict) -> MatchedFamilySpec:
    original = card["original"]
    historical = original["historical_outputs"]
    counterfactual = card["counterfactual_outputs"]
    allowed_coordinates = tuple(card["identification_allowed_values"])
    variables = tuple(control["name"] for control in original["controls"])
    readout_names = tuple(readout["name"] for readout in original["readouts"])

    def predict(parameters, controls):
        coordinate = float(parameters["branch_coordinate"])
        if allowed_coordinates and coordinate not in allowed_coordinates:
            raise ValueError("Only the disclosed endpoint laws are admissible")
        if coordinate in (0.0, 1.0):
            outputs = historical if coordinate == 0.0 else counterfactual
            return evaluate_expression_program(
                {"outputs": outputs}, controls,
                allowed_variables=variables, required_outputs=readout_names,
            )
        first = evaluate_expression_program(
            {"outputs": historical}, controls,
            allowed_variables=variables, required_outputs=readout_names,
        )
        second = evaluate_expression_program(
            {"outputs": counterfactual}, controls,
            allowed_variables=variables, required_outputs=readout_names,
        )
        return {
            name: (1 - coordinate) * first[name] + coordinate * second[name]
            for name in readout_names
        }

    formula = (
        "Only the two endpoint laws s=0 and s=1 belong to this response family; "
        "intermediate linear interpolants are not admissible apparatus models. "
        if allowed_coordinates else ""
    )
    formula += (
        "For each output, y=(1-s)*branch_0+s*branch_1, s=branch_coordinate. "
        "branch_0=" + json.dumps(historical, sort_keys=True)
        + "; branch_1=" + json.dumps(counterfactual, sort_keys=True)
    )
    parameter_description = (
        "Discrete law index s; only 0 and 1 are admissible. "
        "Identify the endpoint law from observations."
        if allowed_coordinates else
        "Coordinate s in the disclosed response family; identify its value "
        "from interaction evidence."
    )
    parameter_options = (
        {"allowed_values": allowed_coordinates} if allowed_coordinates else {}
    )
    return MatchedFamilySpec(
        family=original["family"],
        case_id_prefix="temporal." + original["family"],
        response_title=original["response_title"],
        apparatus_name=original["apparatus_name"],
        apparatus_description=original["apparatus_description"],
        background=original["background"],
        initial_observations=(
            "Infer the fixed deterministic response from experiments using "
            "the listed apparatus, controls and readouts.",
        ),
        controls=tuple(
            ControlSpec(**{**item, "allowed_values": tuple(item["allowed_values"])})
            for item in original["controls"]
        ),
        readouts=tuple(ReadoutSpec(**item) for item in original["readouts"]),
        identification_model="temporal_two_branch_response",
        identification_parameter_specs=(
            IdentificationParameterSpec(
                "branch_coordinate", parameter_description, "1", 0.0, 1.0,
                **parameter_options,
            ),
        ),
        identification_formula=formula,
        predict=predict,
        truths={
            "historical": MatchedTruth(
                {"branch_coordinate": 0.0}, historical,
                tuple(original["historical_applicability"]),
            ),
            "counterfactual": MatchedTruth(
                {"branch_coordinate": 1.0}, counterfactual,
                (
                    "Benchmark-authored mathematical response; required to be "
                    "coherent within this case, not to describe real-world physics.",
                ),
            ),
        },
        diagnostic_conditions=tuple(original["diagnostic_conditions"]),
        hidden_conditions=tuple(original["hidden_conditions"]),
        credits=tuple(SourceCredit(**item) for item in original["credits"]),
        counterfactual_change="; ".join(
            mutation["rationale"]
            for mutation in card["science"]["counterfactual"]["mutations"]
        ),
        common_fixed_conditions=tuple(original["common_fixed_conditions"]),
        common_notes=tuple(original["common_notes"]),
        swap_public_instance_ids=card["swap_public_instance_ids"],
        budget=max(64, original["budget"]),
        max_replicates=original["max_replicates"],
        confidence_threshold=original["confidence_threshold"],
        relative_tolerance=original["relative_tolerance"],
        absolute_tolerances=original["absolute_tolerances"],
        case_id_includes_track=True,
    )


TEMPORAL_CASE_SPECS: Dict[str, MatchedFamilySpec] = {
    family: _family_spec(card)
    for family, card in TEMPORAL_SCIENCE_CARDS.items()
}


def make_temporal_case(
    name: str,
    condition_id: str = "source_reported",
    task_setting: BenchmarkTrack = BenchmarkTrack.IDENTIFICATION,
) -> BenchmarkCase:
    """Build a source-reported relation or its authored counterfactual."""

    try:
        spec = TEMPORAL_CASE_SPECS[name]
    except (KeyError, TypeError) as exc:
        raise ValueError(
            "unknown temporal case family %r; choose one of %s"
            % (name, ", ".join(TEMPORAL_CASE_FAMILIES))
        ) from exc
    try:
        world = {
            "source_reported": "historical",
            "counterfactual": "counterfactual",
        }[condition_id]
    except (KeyError, TypeError) as exc:
        raise ValueError(
            "unknown condition_id %r for temporal family %s"
            % (condition_id, name)
        ) from exc
    return make_matched_case(spec, world, task_setting)


__all__ = [
    "DATASET_ID", "DATASET_STATUS", "TEMPORAL_CASE_FAMILIES",
    "TEMPORAL_CASE_SPECS", "TEMPORAL_SCIENCE_CARDS", "make_temporal_case",
]
