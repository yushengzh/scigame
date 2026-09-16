"""Difficulty variants for matched historical/counterfactual case pairs.

The variants in this module are complete two-world pairs.  ``easy`` and
``hard`` are therefore design variants of the same family, not additional
world labels. Numeric interpolation applies only to pairs with the same
expression structure and compatible parameter domains and predictors.
This utility does not define current benchmark dataset membership.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace
from numbers import Real
from typing import Any, Dict, Mapping, Optional, Sequence, Tuple

from role_benchmark.cases.matched import (
    MatchedFamilySpec,
    MatchedTruth,
    _absolute_tolerance,
    _identification_values,
    _predictions,
    _validated_controls,
)


COUNTERFACTUAL_DIFFICULTIES: Tuple[str, ...] = ("easy", "hard")

_AUTHORED_APPLICABILITY = (
    "Benchmark-authored counterfactual relation over the unchanged declared "
    "control and readout domains.",
)


@dataclass(frozen=True)
class CounterfactualVariant:
    """One complete H/C pair at a preregistered difficulty level."""

    difficulty: str
    counterfactual_fraction: float
    spec: MatchedFamilySpec
    fixed_design_separation: float


def _is_number(value: Any) -> bool:
    return isinstance(value, Real) and not isinstance(value, bool)


def _interpolate_numeric_leaves(
    historical: Any,
    counterfactual: Any,
    fraction: float,
    *,
    path: str,
) -> Any:
    """Interpolate numeric leaves while requiring identical container structure."""

    if historical == counterfactual:
        return historical
    if _is_number(historical) and _is_number(counterfactual):
        return float(historical) + fraction * (
            float(counterfactual) - float(historical)
        )
    if isinstance(historical, Mapping) and isinstance(counterfactual, Mapping):
        if set(historical) != set(counterfactual):
            raise ValueError(
                "historical and counterfactual structures differ at %s" % path
            )
        return {
            key: _interpolate_numeric_leaves(
                historical[key],
                counterfactual[key],
                fraction,
                path="%s/%s" % (path, key),
            )
            for key in historical
        }
    if isinstance(historical, (list, tuple)) and isinstance(
        counterfactual, type(historical)
    ):
        if len(historical) != len(counterfactual):
            raise ValueError(
                "historical and counterfactual structures differ at %s" % path
            )
        items = [
            _interpolate_numeric_leaves(
                left,
                right,
                fraction,
                path="%s/%d" % (path, index),
            )
            for index, (left, right) in enumerate(
                zip(historical, counterfactual)
            )
        ]
        return tuple(items) if isinstance(historical, tuple) else items
    raise ValueError(
        "historical and counterfactual structures differ at %s" % path
    )


def _changed_parameter(spec: MatchedFamilySpec) -> str:
    historical = spec.truths["historical"]
    counterfactual = spec.truths["counterfactual"]
    if set(historical.parameters) != set(counterfactual.parameters):
        raise ValueError("historical and counterfactual parameter keys must match")
    changed = tuple(
        name
        for name in historical.parameters
        if historical.parameters[name] != counterfactual.parameters[name]
    )
    if len(changed) != 1:
        raise ValueError(
            "counterfactual variants require exactly one changed mechanism parameter"
        )
    return changed[0]


def _interpolated_truth(
    spec: MatchedFamilySpec,
    fraction: float,
) -> MatchedTruth:
    historical = spec.truths["historical"]
    counterfactual = spec.truths["counterfactual"]
    _changed_parameter(spec)

    parameters = _interpolate_numeric_leaves(
        historical.parameters,
        counterfactual.parameters,
        fraction,
        path="parameters",
    )
    if (
        historical.identification_values is None
        and counterfactual.identification_values is None
    ):
        identification_values: Optional[Mapping[str, float]] = None
    else:
        historical_values = _identification_values(historical)
        counterfactual_values = _identification_values(counterfactual)
        changed_identification_values = tuple(
            name
            for name in historical_values
            if historical_values[name] != counterfactual_values[name]
        )
        if (
            set(historical_values) != set(counterfactual_values)
            or len(changed_identification_values) != 1
        ):
            raise ValueError(
                "counterfactual variants require one continuous identification "
                "coordinate"
            )
        identification_values = _interpolate_numeric_leaves(
            historical_values,
            counterfactual_values,
            fraction,
            path="identification_values",
        )

    discovery_outputs = _interpolate_numeric_leaves(
        historical.discovery_outputs,
        counterfactual.discovery_outputs,
        fraction,
        path="discovery_outputs",
    )
    return MatchedTruth(
        parameters=parameters,
        identification_values=identification_values,
        discovery_outputs=discovery_outputs,
        applicability=_AUTHORED_APPLICABILITY,
        fixed_conditions=counterfactual.fixed_conditions,
    )


def _symmetric_scaled_separations(
    spec: MatchedFamilySpec,
    historical: MatchedTruth,
    counterfactual: MatchedTruth,
    conditions: Sequence[Mapping[str, Any]],
) -> Tuple[float, ...]:
    scaled = []
    for condition in conditions:
        controls = _validated_controls(spec, condition)
        left = _predictions(spec, historical.parameters, controls)
        right = _predictions(spec, counterfactual.parameters, controls)
        for readout in (item.name for item in spec.readouts):
            symmetric_scale = _absolute_tolerance(spec, readout) + (
                spec.relative_tolerance
                * (abs(left[readout]) + abs(right[readout]))
                / 2.0
            )
            scaled.append(abs(left[readout] - right[readout]) / symmetric_scale)
    return tuple(scaled)


def rms_symmetric_tolerance_scaled_separation(
    spec: MatchedFamilySpec,
    historical: Optional[MatchedTruth] = None,
    counterfactual: Optional[MatchedTruth] = None,
    *,
    conditions: Optional[Sequence[Mapping[str, Any]]] = None,
) -> float:
    """Return RMS symmetric tolerance-scaled H/C separation.

    Each readout difference is divided by its absolute tolerance plus the
    relative tolerance times the mean absolute H/C prediction.  This scale is
    invariant to swapping the two worlds.  The default conditions are the
    family's preregistered fixed diagnostic design.
    """

    historical_truth = historical or spec.truths["historical"]
    counterfactual_truth = counterfactual or spec.truths["counterfactual"]
    selected_conditions = (
        spec.diagnostic_conditions if conditions is None else conditions
    )
    if not selected_conditions:
        raise ValueError("separation requires at least one fixed-design condition")
    scaled = _symmetric_scaled_separations(
        spec,
        historical_truth,
        counterfactual_truth,
        selected_conditions,
    )
    return math.sqrt(sum(value * value for value in scaled) / len(scaled))


def make_counterfactual_variant(
    spec: MatchedFamilySpec,
    difficulty: str,
    *,
    counterfactual_fraction: float,
) -> CounterfactualVariant:
    """Construct an H/C pair; fractions below one require matching structures."""

    if difficulty not in COUNTERFACTUAL_DIFFICULTIES:
        raise ValueError(
            "unknown counterfactual difficulty %r; choose one of %s"
            % (difficulty, ", ".join(COUNTERFACTUAL_DIFFICULTIES))
        )
    if (
        isinstance(counterfactual_fraction, bool)
        or not isinstance(counterfactual_fraction, Real)
        or not math.isfinite(float(counterfactual_fraction))
        or not 0.0 < float(counterfactual_fraction) <= 1.0
    ):
        raise ValueError("counterfactual_fraction must be finite and in (0, 1]")
    fraction = float(counterfactual_fraction)
    historical = spec.truths["historical"]
    parameter = _changed_parameter(spec)
    if fraction == 1.0:
        variant_spec = spec
    else:
        counterfactual = _interpolated_truth(spec, fraction)
        source_counterfactual = spec.truths["counterfactual"]
        variant_spec = replace(
            spec,
            truths={
                "historical": historical,
                "counterfactual": counterfactual,
            },
            counterfactual_change=(
                "The counterfactual sets %s to %.12g of the interval from the "
                "historical value %.12g toward the reference counterfactual "
                "value %.12g; all other mechanism parameters are unchanged."
                % (
                    parameter,
                    fraction,
                    float(historical.parameters[parameter]),
                    float(source_counterfactual.parameters[parameter]),
                )
            ),
        )

    separation = rms_symmetric_tolerance_scaled_separation(variant_spec)
    return CounterfactualVariant(
        difficulty=difficulty,
        counterfactual_fraction=fraction,
        spec=variant_spec,
        fixed_design_separation=separation,
    )


__all__ = [
    "COUNTERFACTUAL_DIFFICULTIES",
    "CounterfactualVariant",
    "make_counterfactual_variant",
    "rms_symmetric_tolerance_scaled_separation",
]
