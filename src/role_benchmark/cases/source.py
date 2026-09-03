"""Runtime contract for one source-reported quantitative relation."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Mapping, Optional, Tuple

from role_benchmark.expression import (
    EXPRESSION_MODEL,
    evaluate_expression_program,
    validate_expression_program,
)
from role_benchmark.models import (
    BenchmarkTrack,
    CaseDefinition,
    ControlSpec,
    FinalSubmission,
    ReadoutSpec,
)
from role_benchmark.protocols import BenchmarkCase

from .matched import (
    IdentificationParameterSpec,
    MatchedEvaluator,
    MatchedTruth,
    MatchedWorldModel,
    PredictionFunction,
    SourceCredit,
    _identification_predictions,
    _identification_values,
    _predictions,
    _resources,
    _validated_controls,
)


@dataclass(frozen=True)
class SourceFamilySpec:
    """Declarative benchmark family with one source-reported condition."""

    family: str
    case_id_prefix: str
    response_title: str
    apparatus_name: str
    apparatus_description: str
    background: str
    initial_observations: Tuple[str, ...]
    controls: Tuple[ControlSpec, ...]
    readouts: Tuple[ReadoutSpec, ...]
    identification_model: str
    identification_parameter_specs: Tuple[IdentificationParameterSpec, ...]
    identification_formula: str
    model_outputs: Mapping[str, Any]
    predict: PredictionFunction
    truth: MatchedTruth
    diagnostic_conditions: Tuple[Mapping[str, Any], ...]
    hidden_conditions: Tuple[Mapping[str, Any], ...]
    credits: Tuple[SourceCredit, ...]
    common_notes: Tuple[str, ...] = ()
    common_fixed_conditions: Tuple[str, ...] = ()
    budget: int = 8
    max_replicates: int = 1
    confidence_threshold: float = 0.90
    relative_tolerance: float = 0.05
    absolute_tolerances: Mapping[str, float] = field(default_factory=dict)
    identification_predict: Optional[PredictionFunction] = None

    def __post_init__(self) -> None:
        validate_source_family_spec(self)

    @property
    def identification_parameters(self) -> Tuple[str, ...]:
        return tuple(item.name for item in self.identification_parameter_specs)


def _finite_number(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("%s must be numeric" % name)
    result = float(value)
    if not math.isfinite(result):
        raise ValueError("%s must be finite" % name)
    return result


def validate_source_family_spec(spec: SourceFamilySpec) -> None:
    """Reject an incomplete single-relation runtime specification."""

    text_fields = (
        spec.family,
        spec.case_id_prefix,
        spec.response_title,
        spec.apparatus_name,
        spec.apparatus_description,
        spec.background,
        spec.identification_model,
        spec.identification_formula,
    )
    if any(not isinstance(value, str) or not value.strip() for value in text_fields):
        raise ValueError("source-family text fields must be non-empty")
    if not spec.controls or not spec.readouts:
        raise ValueError("a source family needs controls and readouts")
    if not spec.identification_parameter_specs:
        raise ValueError(
            "a source family needs at least one parameter for Identification"
        )
    if len({item.name for item in spec.controls}) != len(spec.controls):
        raise ValueError("control names must be unique")
    if len({item.name for item in spec.readouts}) != len(spec.readouts):
        raise ValueError("readout names must be unique")
    if len(set(spec.identification_parameters)) != len(
        spec.identification_parameters
    ):
        raise ValueError("identification parameter names must be unique")
    if not spec.credits or any(
        not item.citation
        or not item.role
        or not item.url.startswith(("https://", "http://"))
        for item in spec.credits
    ):
        raise ValueError("every source family needs an explicit source credit")
    if (
        isinstance(spec.budget, bool)
        or not isinstance(spec.budget, int)
        or spec.budget < 1
    ):
        raise ValueError("budget must be a positive integer")
    if (
        isinstance(spec.max_replicates, bool)
        or not isinstance(spec.max_replicates, int)
        or spec.max_replicates < 1
    ):
        raise ValueError("max_replicates must be a positive integer")
    if not 0.0 < spec.confidence_threshold <= 1.0:
        raise ValueError("confidence_threshold must be in (0, 1]")
    if not 0.0 < spec.relative_tolerance < 1.0:
        raise ValueError("relative_tolerance must be in (0, 1)")
    if not spec.diagnostic_conditions:
        raise ValueError("diagnostic conditions must be declared")
    if len(spec.diagnostic_conditions) > spec.budget:
        raise ValueError("diagnostic conditions must fit within the budget")
    if not spec.hidden_conditions:
        raise ValueError("hidden conditions must be declared")

    control_names = tuple(item.name for item in spec.controls)
    readout_names = tuple(item.name for item in spec.readouts)
    all_conditions = spec.diagnostic_conditions + spec.hidden_conditions
    condition_keys = []
    for condition in all_conditions:
        controls = _validated_controls(spec, condition)
        condition_keys.append(tuple(controls[name] for name in control_names))
    diagnostic_count = len(spec.diagnostic_conditions)
    if set(condition_keys[:diagnostic_count]) & set(condition_keys[diagnostic_count:]):
        raise ValueError("hidden conditions must be disjoint from diagnostic conditions")

    for control in spec.controls:
        values = {item[control.name] for item in spec.diagnostic_conditions}
        can_vary = (
            control.minimum is not None and control.maximum is not None
        ) or len(control.allowed_values) > 1
        if can_vary and len(values) < 2:
            raise ValueError(
                "diagnostic conditions do not vary control %s" % control.name
            )

    expected_parameters = set(spec.identification_parameters)
    if set(spec.truth.parameters) != expected_parameters:
        raise ValueError(
            "truth parameters must match the public identification contract"
        )
    identification_values = _identification_values(spec.truth)
    if set(identification_values) != expected_parameters:
        raise ValueError(
            "truth identification values must match the public identification contract"
        )
    for name, value in spec.truth.parameters.items():
        numeric = _finite_number(value, name)
        parameter = next(
            item for item in spec.identification_parameter_specs if item.name == name
        )
        if not parameter.contains(numeric):
            raise ValueError("truth parameter %s is outside its public domain" % name)
    validate_expression_program(
        {"outputs": spec.model_outputs},
        allowed_variables=control_names,
        allowed_parameters=tuple(spec.truth.parameters),
        required_outputs=readout_names,
    )
    validate_expression_program(
        {"outputs": spec.truth.discovery_outputs},
        allowed_variables=control_names,
        required_outputs=readout_names,
    )

    for condition in all_conditions:
        controls = _validated_controls(spec, condition)
        expected = _predictions(spec, spec.truth.parameters, controls)
        identified = _identification_predictions(
            spec,
            identification_values,
            controls,
        )
        expressed = evaluate_expression_program(
            {"outputs": spec.truth.discovery_outputs},
            controls,
            allowed_variables=control_names,
            required_outputs=readout_names,
        )
        for name in readout_names:
            if not math.isclose(
                expected[name],
                identified[name],
                rel_tol=1.0e-10,
                abs_tol=1.0e-10,
            ):
                raise ValueError(
                    "identification truth must equal the source predictor"
                )
            if not math.isclose(
                expected[name],
                expressed[name],
                rel_tol=1.0e-10,
                abs_tol=1.0e-10,
            ):
                raise ValueError("discovery truth must equal the source predictor")


def make_source_case(
    spec: SourceFamilySpec,
    track: BenchmarkTrack = BenchmarkTrack.IDENTIFICATION,
) -> BenchmarkCase:
    """Instantiate one source-reported condition for one task setting."""

    if not isinstance(spec, SourceFamilySpec):
        raise ValueError("spec must be a SourceFamilySpec")
    if not isinstance(track, BenchmarkTrack):
        raise ValueError("track must be a BenchmarkTrack")
    definition = CaseDefinition(
        case_id=spec.case_id_prefix + ".instance_1",
        track=track,
        title=(
            ("Identify " if track is BenchmarkTrack.IDENTIFICATION else "Discover ")
            + spec.response_title
        ),
        background=spec.background,
        initial_observations=spec.initial_observations,
        resources=_resources(spec, track),
        budget=spec.budget,
        confidence_threshold=spec.confidence_threshold,
    )
    return BenchmarkCase(
        definition=definition,
        world_model=MatchedWorldModel(spec, spec.truth),
        evaluator=MatchedEvaluator(spec, spec.truth),
    )


def source_truth_submission(
    spec: SourceFamilySpec,
    track: BenchmarkTrack,
) -> FinalSubmission:
    """Return a development-only known-truth submission for validation."""

    if not isinstance(track, BenchmarkTrack):
        raise ValueError("track must be a BenchmarkTrack")
    return FinalSubmission(
        hypothesis_id="H1",
        explanation="Development truth fixture for protocol validation.",
        model=EXPRESSION_MODEL,
        parameters={"outputs": dict(spec.truth.discovery_outputs)},
    )


__all__ = [
    "SourceFamilySpec",
    "make_source_case",
    "source_truth_submission",
    "validate_source_family_spec",
]
