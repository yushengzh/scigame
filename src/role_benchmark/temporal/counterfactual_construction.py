"""Explicit counterfactual construction from an accepted Temporal source case.

This module is not called by Temporal admission or deterministic source-case
compilation. A counterfactual family exists only after an explicit request that
names one dimension-compatible parameter and target value.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Dict

from role_benchmark.cases.matched import MatchedFamilySpec, MatchedTruth
from role_benchmark.cases.source import SourceFamilySpec
from role_benchmark.counterfactual import (
    CounterfactualVariant,
    rms_symmetric_tolerance_scaled_separation,
)

from .filter import materialize_outputs


TEMPORAL_COUNTERFACTUAL_DIFFICULTIES = ("easy", "hard")
_DIFFICULTY_FRACTIONS = {"easy": 1.0, "hard": 0.5}


@dataclass(frozen=True)
class TemporalCounterfactualRequest:
    """One explicitly authored, unit-preserving parameter intervention."""

    parameter_name: str
    target_value: float
    unit: str


def _variant_spec(
    source: SourceFamilySpec,
    request: TemporalCounterfactualRequest,
    difficulty: str,
    fraction: float,
) -> MatchedFamilySpec:
    if request.parameter_name not in source.truth.parameters:
        raise ValueError("counterfactual parameter is not in the source model")
    if isinstance(request.target_value, bool) or not isinstance(
        request.target_value, (int, float)
    ):
        raise ValueError("counterfactual target value must be numeric")
    target = float(request.target_value)
    if not math.isfinite(target):
        raise ValueError("counterfactual target value must be finite")
    parameter_spec = next(
        item
        for item in source.identification_parameter_specs
        if item.name == request.parameter_name
    )
    if not isinstance(request.unit, str) or request.unit != parameter_spec.unit:
        raise ValueError(
            "counterfactual request unit must exactly match the source parameter unit"
        )
    if not parameter_spec.contains(target):
        raise ValueError("counterfactual target is outside the parameter domain")
    source_value = float(source.truth.parameters[request.parameter_name])
    if target == source_value:
        raise ValueError("counterfactual target must differ from the source value")
    variant_value = source_value + fraction * (target - source_value)
    parameters = dict(source.truth.parameters)
    parameters[request.parameter_name] = variant_value
    alternate_outputs = materialize_outputs(source.model_outputs, parameters)
    source_truth = MatchedTruth(
        parameters=dict(source.truth.parameters),
        identification_values=dict(source.truth.parameters),
        discovery_outputs=dict(source.truth.discovery_outputs),
        applicability=source.truth.applicability,
        fixed_conditions=source.truth.fixed_conditions,
    )
    alternate_truth = MatchedTruth(
        parameters=parameters,
        identification_values=parameters,
        discovery_outputs=alternate_outputs,
        applicability=(
            "Benchmark-authored counterfactual over the unchanged source-supported domain.",
        ),
        fixed_conditions=source.truth.fixed_conditions,
    )
    return MatchedFamilySpec(
        family=source.family + "_counterfactual_" + difficulty,
        case_id_prefix=source.case_id_prefix + ".counterfactual_" + difficulty,
        response_title=source.response_title,
        apparatus_name=source.apparatus_name,
        apparatus_description=source.apparatus_description,
        background=source.background,
        initial_observations=source.initial_observations,
        controls=source.controls,
        readouts=source.readouts,
        identification_model=source.identification_model,
        identification_parameter_specs=source.identification_parameter_specs,
        identification_formula=source.identification_formula,
        predict=source.predict,
        identification_predict=source.identification_predict,
        truths={"historical": source_truth, "counterfactual": alternate_truth},
        diagnostic_conditions=source.diagnostic_conditions,
        hidden_conditions=source.hidden_conditions,
        credits=source.credits,
        counterfactual_change=(
            "The benchmark-authored counterfactual changes parameter %s from "
            "%.12g toward the preregistered same-unit target %.12g by fraction "
            "%.12g; all other parameters and the experimental interface are unchanged."
            % (request.parameter_name, source_value, target, fraction)
        ),
        common_notes=source.common_notes
        + (
            "The alternate relation is benchmark-authored and is not a "
            "source-reported condition.",
        ),
        common_fixed_conditions=source.common_fixed_conditions,
        swap_public_instance_ids=False,
        require_held_out_interior=False,
        budget=source.budget,
        max_replicates=source.max_replicates,
        confidence_threshold=source.confidence_threshold,
        relative_tolerance=source.relative_tolerance,
        absolute_tolerances=source.absolute_tolerances,
    )


def construct_temporal_counterfactual_variants(
    source: SourceFamilySpec,
    request: TemporalCounterfactualRequest,
) -> Dict[str, CounterfactualVariant]:
    """Return easy/hard pairs only after an explicit construction request."""

    if not isinstance(source, SourceFamilySpec):
        raise ValueError("source must be an accepted SourceFamilySpec")
    if not isinstance(request, TemporalCounterfactualRequest):
        raise ValueError("request must be a TemporalCounterfactualRequest")
    candidates = []
    for fraction in _DIFFICULTY_FRACTIONS.values():
        candidate = _variant_spec(
            source,
            request,
            "candidate",
            fraction,
        )
        candidates.append(
            (
                rms_symmetric_tolerance_scaled_separation(candidate),
                fraction,
            )
        )
    candidates.sort(reverse=True)
    easy_separation, easy_fraction = candidates[0]
    hard_separation, hard_fraction = candidates[1]
    if easy_separation <= hard_separation or math.isclose(
        easy_separation,
        hard_separation,
        rel_tol=1.0e-12,
        abs_tol=1.0e-12,
    ):
        raise ValueError(
            "counterfactual request does not produce two ordered difficulty levels"
        )
    assigned = {
        "easy": (easy_fraction, easy_separation),
        "hard": (hard_fraction, hard_separation),
    }
    variants = {}
    for difficulty in TEMPORAL_COUNTERFACTUAL_DIFFICULTIES:
        fraction, separation = assigned[difficulty]
        spec = _variant_spec(source, request, difficulty, fraction)
        variants[difficulty] = CounterfactualVariant(
            difficulty=difficulty,
            counterfactual_fraction=fraction,
            spec=spec,
            fixed_design_separation=separation,
        )
    return variants


__all__ = [
    "TEMPORAL_COUNTERFACTUAL_DIFFICULTIES",
    "TemporalCounterfactualRequest",
    "construct_temporal_counterfactual_variants",
]
