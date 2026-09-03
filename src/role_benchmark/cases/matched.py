"""Reusable machinery for scientifically authored matched case families.

The machinery is deliberately small: a family supplies public resources, two
private laws, one identification predictor, and fixed diagnostic/held-out
conditions.  The runner and Oracle remain case-neutral.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Mapping, Optional, Sequence, Tuple

from role_benchmark.expression import (
    EXPRESSION_MODEL,
    EXPRESSION_OPERATORS,
    ExpressionError,
    evaluate_expression_program,
    validate_expression_program,
)
from role_benchmark.models import (
    BenchmarkTrack,
    CaseDefinition,
    ControlSpec,
    EvaluationResult,
    ExperimentEvidence,
    ExperimentProposal,
    FinalSubmission,
    InstrumentSpec,
    ReadoutSpec,
    ResourceCatalog,
)
from role_benchmark.metrics import (
    HELD_OUT_PREDICTION_SCORE,
    held_out_prediction_score,
)
from role_benchmark.protocols import BenchmarkCase, FinalEvaluator, WorldModel


MATCHED_WORLDS: Tuple[str, ...] = ("historical", "counterfactual")
DEFAULT_MATCHED_NOTES: Tuple[str, ...] = (
    "This is a deterministic idealized benchmark world, not a literal replay "
    "of a source measurement table.",
    "A valid experiment changes only listed controls and consumes one episode attempt.",
)
PredictionFunction = Callable[
    [Mapping[str, float], Mapping[str, Any]], Mapping[str, float]
]


@dataclass(frozen=True)
class SourceCredit:
    """One source and the precise role it plays in case authoring."""

    citation: str
    url: str
    role: str


@dataclass(frozen=True)
class MatchedTruth:
    """One private world law with its executable predictor fixture."""

    parameters: Mapping[str, float]
    discovery_outputs: Mapping[str, Any]
    applicability: Tuple[str, ...] = ()
    fixed_conditions: Tuple[str, ...] = ()
    identification_values: Optional[Mapping[str, float]] = None


@dataclass(frozen=True)
class IdentificationParameterSpec:
    """One public scalar slot in the identification model family."""

    name: str
    description: str
    unit: str
    minimum: Optional[float] = None
    maximum: Optional[float] = None

    def __post_init__(self) -> None:
        if (
            not self.name.strip()
            or not self.description.strip()
            or not self.unit.strip()
        ):
            raise ValueError(
                "identification parameter name, description, and unit must be non-empty"
            )
        bounds = (self.minimum, self.maximum)
        for bound in bounds:
            if bound is None:
                continue
            if (
                isinstance(bound, bool)
                or not isinstance(bound, (int, float))
                or not math.isfinite(float(bound))
            ):
                raise ValueError("identification parameter bounds must be finite")
        if (
            self.minimum is not None
            and self.maximum is not None
            and float(self.minimum) >= float(self.maximum)
        ):
            raise ValueError(
                "identification parameter minimum must be below maximum"
            )

    def contains(self, value: float) -> bool:
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(float(value))
        ):
            return False
        numeric = float(value)
        return (
            (self.minimum is None or numeric >= float(self.minimum))
            and (self.maximum is None or numeric <= float(self.maximum))
        )


@dataclass(frozen=True)
class MatchedFamilySpec:
    """Declarative contract for one historical/counterfactual matched family."""

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
    predict: PredictionFunction
    truths: Mapping[str, MatchedTruth]
    diagnostic_conditions: Tuple[Mapping[str, Any], ...]
    hidden_conditions: Tuple[Mapping[str, Any], ...]
    credits: Tuple[SourceCredit, ...]
    counterfactual_change: str
    common_notes: Tuple[str, ...] = ()
    common_fixed_conditions: Tuple[str, ...] = ()
    swap_public_instance_ids: bool = False
    require_held_out_interior: bool = False
    budget: int = 8
    max_replicates: int = 12
    confidence_threshold: float = 0.90
    relative_tolerance: float = 0.05
    absolute_tolerances: Mapping[str, float] = field(default_factory=dict)
    identification_predict: Optional[PredictionFunction] = None

    def __post_init__(self) -> None:
        validate_matched_family_spec(self)

    @property
    def identification_parameters(self) -> Tuple[str, ...]:
        return tuple(item.name for item in self.identification_parameter_specs)


def _finite_number(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("%s must be numeric" % name)
    try:
        result = float(value)
    except (OverflowError, TypeError, ValueError) as exc:
        raise ValueError("%s must be finite" % name) from exc
    if not math.isfinite(result):
        raise ValueError("%s must be finite" % name)
    return result


def _control_map(spec: MatchedFamilySpec) -> Dict[str, ControlSpec]:
    return {control.name: control for control in spec.controls}


def _readout_map(spec: MatchedFamilySpec) -> Dict[str, ReadoutSpec]:
    return {readout.name: readout for readout in spec.readouts}


def _validated_controls(
    spec: MatchedFamilySpec, controls: Mapping[str, Any]
) -> Dict[str, Any]:
    declared = _control_map(spec)
    if set(controls) != set(declared):
        raise ValueError("controls must match the case resource contract exactly")
    result: Dict[str, Any] = {}
    for name, control in declared.items():
        value = controls[name]
        if control.allowed_values:
            if value not in control.allowed_values:
                raise ValueError("%s is not an allowed value" % name)
            result[name] = value
            continue
        numeric = _finite_number(value, name)
        if control.minimum is not None and numeric < control.minimum:
            raise ValueError("%s is below the available range" % name)
        if control.maximum is not None and numeric > control.maximum:
            raise ValueError("%s is above the available range" % name)
        result[name] = numeric
    return result


def _predictions(
    spec: MatchedFamilySpec,
    parameters: Mapping[str, float],
    controls: Mapping[str, Any],
) -> Dict[str, float]:
    try:
        raw = spec.predict(parameters, controls)
    except (ArithmeticError, OverflowError, TypeError, ValueError) as exc:
        raise ValueError("predictor is undefined for this condition") from exc
    expected = {readout.name for readout in spec.readouts}
    if set(raw) != expected:
        raise ValueError("predictor outputs must match the declared readouts exactly")
    return {
        name: _finite_number(value, "prediction %s" % name)
        for name, value in raw.items()
    }


def _identification_predictions(
    spec: MatchedFamilySpec,
    parameters: Mapping[str, float],
    controls: Mapping[str, Any],
) -> Dict[str, float]:
    predictor = spec.identification_predict or spec.predict
    try:
        raw = predictor(parameters, controls)
    except (ArithmeticError, OverflowError, TypeError, ValueError) as exc:
        raise ValueError(
            "identification predictor is undefined for this condition"
        ) from exc
    expected = {readout.name for readout in spec.readouts}
    if set(raw) != expected:
        raise ValueError(
            "identification predictor outputs must match the declared readouts exactly"
        )
    return {
        name: _finite_number(value, "identification prediction %s" % name)
        for name, value in raw.items()
    }


def _identification_values(truth: MatchedTruth) -> Mapping[str, float]:
    return (
        truth.parameters
        if truth.identification_values is None
        else truth.identification_values
    )


def _round_to_resolution(value: float, resolution: float) -> float:
    digits = 0
    text = format(resolution, ".12f").rstrip("0").rstrip(".")
    if "." in text:
        digits = len(text.split(".", 1)[1])
    return round(round(value / resolution) * resolution, digits)


def _absolute_tolerance(spec: MatchedFamilySpec, readout: str) -> float:
    configured = spec.absolute_tolerances.get(readout)
    if configured is not None:
        return float(configured)
    resource = _readout_map(spec)[readout]
    return float(resource.resolution or 1.0e-9)


def _parameter_domain_text(parameter: IdentificationParameterSpec) -> str:
    if parameter.minimum is None and parameter.maximum is None:
        return "any finite real value"
    if parameter.minimum is None:
        return "<= %g" % float(parameter.maximum)
    if parameter.maximum is None:
        return ">= %g" % float(parameter.minimum)
    return "[%g, %g]" % (float(parameter.minimum), float(parameter.maximum))


def _scaled_error(
    spec: MatchedFamilySpec, readout: str, prediction: float, target: float
) -> float:
    allowance = _absolute_tolerance(spec, readout) + (
        spec.relative_tolerance * abs(target)
    )
    return abs(prediction - target) / allowance


def _resources(spec: MatchedFamilySpec, track: BenchmarkTrack) -> ResourceCatalog:
    required_outputs = ", ".join(readout.name for readout in spec.readouts)
    submission_note = (
        "Submit an executable predictor. FinalSubmission.model must equal '%s'. "
        "FinalSubmission.parameters must equal {'outputs': {READOUT: EXPR, ...}} "
        "with exactly these readouts: %s. EXPR is the expression format shared "
        "across all benchmark families: a JSON arithmetic tree over public "
        "controls. Materialize fitted constants "
        "as finite JSON numbers. Supported operators are: %s."
        % (
            EXPRESSION_MODEL,
            required_outputs,
            ", ".join(EXPRESSION_OPERATORS),
        )
    )
    notes = spec.common_fixed_conditions + spec.common_notes + (submission_note,)
    if track is BenchmarkTrack.IDENTIFICATION:
        parameter_contract = "; ".join(
            "%s: %s (unit: %s; admissible: %s)"
            % (
                parameter.name,
                parameter.description,
                parameter.unit,
                _parameter_domain_text(parameter),
            )
            for parameter in spec.identification_parameter_specs
        )
        model_specification = (
            "Model specification: %s. Equation: %s Parameter meanings and "
            "admissible domains: %s"
            % (
                spec.identification_model,
                spec.identification_formula,
                parameter_contract,
            )
        )
        notes += (model_specification,)
    return ResourceCatalog(
        instruments=(
            InstrumentSpec(
                name=spec.apparatus_name,
                description=spec.apparatus_description,
                controls=tuple(control.name for control in spec.controls),
                readouts=tuple(readout.name for readout in spec.readouts),
            ),
        ),
        controls=spec.controls,
        readouts=spec.readouts,
        max_replicates=spec.max_replicates,
        notes=notes,
    )


class MatchedWorldModel(WorldModel):
    """Execute one private truth after repeating the public resource checks."""

    def __init__(self, spec: MatchedFamilySpec, truth: MatchedTruth) -> None:
        self._spec = spec
        self._truth = truth

    def run(self, proposal: ExperimentProposal) -> ExperimentEvidence:
        if proposal.apparatus != self._spec.apparatus_name:
            raise ValueError("apparatus must be %r" % self._spec.apparatus_name)
        declared_readouts = _readout_map(self._spec)
        if (
            not proposal.readouts
            or len(set(proposal.readouts)) != len(proposal.readouts)
            or not set(proposal.readouts).issubset(declared_readouts)
        ):
            raise ValueError("readouts must be a non-empty declared subset")
        controls = _validated_controls(self._spec, proposal.controls)
        if isinstance(proposal.replicates, bool) or not isinstance(
            proposal.replicates, int
        ):
            raise ValueError("replicates must be an integer")
        if not 1 <= proposal.replicates <= self._spec.max_replicates:
            raise ValueError("replicates is outside the available range")

        exact = _predictions(self._spec, self._truth.parameters, controls)
        measurements: Dict[str, float] = {}
        units: Dict[str, str] = {}
        uncertainty: Dict[str, str] = {}
        for name in proposal.readouts:
            readout = declared_readouts[name]
            value = exact[name]
            if readout.resolution is not None:
                value = _round_to_resolution(value, float(readout.resolution))
                if not readout.uncertainty:
                    uncertainty[name] = "+/- %g %s (rounding interval)" % (
                        float(readout.resolution) / 2.0,
                        readout.unit,
                    )
            if readout.uncertainty:
                uncertainty[name] = readout.uncertainty
            measurements[name] = value
            units[name] = readout.unit
        declared_statistics = tuple(
            "%s: %s" % (name, declared_readouts[name].statistic)
            for name in proposal.readouts
            if declared_readouts[name].statistic
        )
        if declared_statistics:
            message = "The apparatus reports the deterministic source-defined statistic (%s)." % "; ".join(
                declared_statistics
            )
        else:
            message = "The apparatus reports the deterministic mean of %d replicate(s)." % proposal.replicates
        return ExperimentEvidence(
            measurements=measurements,
            units=units,
            uncertainty=uncertainty,
            message=message,
        )


class MatchedEvaluator(FinalEvaluator):
    """Score both tracks through one executable-predictor evaluation path."""

    def __init__(
        self,
        spec: MatchedFamilySpec,
        truth: MatchedTruth,
    ) -> None:
        self._spec = spec
        self._truth = truth

    def _failure(self, message: str) -> EvaluationResult:
        return EvaluationResult(
            success=False,
            scores={
                "predictive_model_pass": 0.0,
                HELD_OUT_PREDICTION_SCORE: 0.0,
            },
            message=message,
        )

    def evaluate(self, submission: FinalSubmission) -> EvaluationResult:
        if submission.model != EXPRESSION_MODEL:
            return self._failure(
                "The final model must use the public executable expression representation.",
            )

        scaled_errors = []
        per_readout: Dict[str, list[float]] = {
            readout.name: [] for readout in self._spec.readouts
        }
        for condition in self._spec.hidden_conditions:
            controls = _validated_controls(self._spec, condition)
            targets = _predictions(self._spec, self._truth.parameters, controls)
            try:
                predictions = evaluate_expression_program(
                    submission.parameters,
                    controls,
                    allowed_variables=tuple(controls),
                    required_outputs=tuple(per_readout),
                )
            except (ExpressionError, ValueError) as exc:
                return self._failure(str(exc))
            for readout, target in targets.items():
                try:
                    prediction = _finite_number(
                        predictions[readout], "prediction %s" % readout
                    )
                except (KeyError, ValueError) as exc:
                    return self._failure(str(exc))
                error = _scaled_error(
                    self._spec, readout, prediction, target
                )
                scaled_errors.append(error)
                per_readout[readout].append(error)

        maximum_error = max(scaled_errors)
        success = maximum_error <= 1.0
        scores: Dict[str, float] = {
            "predictive_model_pass": float(success),
            HELD_OUT_PREDICTION_SCORE: held_out_prediction_score(scaled_errors),
            "hidden_test_mean_scaled_error": sum(scaled_errors)
            / len(scaled_errors),
            "hidden_test_max_scaled_error": maximum_error,
        }
        for readout, errors in per_readout.items():
            scores["%s_max_scaled_error" % readout] = max(errors)
        return EvaluationResult(
            success=success,
            scores=scores,
            message=(
                "The submitted predictor passed the held-out interventions."
                if success
                else "The submitted predictor exceeded the declared held-out tolerance."
            ),
        )


def make_matched_case(
    spec: MatchedFamilySpec,
    world: str = "historical",
    track: BenchmarkTrack = BenchmarkTrack.IDENTIFICATION,
) -> BenchmarkCase:
    """Instantiate one of a family specification's four matched cells."""

    if world not in MATCHED_WORLDS:
        raise ValueError(
            "unknown world %r; choose one of %s"
            % (world, ", ".join(MATCHED_WORLDS))
        )
    if not isinstance(track, BenchmarkTrack):
        raise ValueError("track must be a BenchmarkTrack")
    truth = spec.truths[world]
    world_index = MATCHED_WORLDS.index(world)
    if spec.swap_public_instance_ids:
        world_index = 1 - world_index
    case_id = "%s.instance_%d" % (spec.case_id_prefix, world_index + 1)
    definition = CaseDefinition(
        case_id=case_id,
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
        world_model=MatchedWorldModel(spec, truth),
        evaluator=MatchedEvaluator(spec, truth),
    )


def truth_submission(
    spec: MatchedFamilySpec,
    world: str,
    track: BenchmarkTrack,
) -> FinalSubmission:
    """Build a development-only known-truth submission for contract tests."""

    if world not in MATCHED_WORLDS:
        raise ValueError("unknown world %r" % world)
    if not isinstance(track, BenchmarkTrack):
        raise ValueError("track must be a BenchmarkTrack")
    truth = spec.truths[world]
    return FinalSubmission(
        hypothesis_id="H1",
        explanation="Development truth fixture for protocol validation.",
        model=EXPRESSION_MODEL,
        parameters={"outputs": dict(truth.discovery_outputs)},
    )


def validate_matched_family_spec(spec: MatchedFamilySpec) -> None:
    """Reject incomplete, leaky, or empirically indistinguishable specifications."""

    if not spec.family or not spec.case_id_prefix:
        raise ValueError("family and case_id_prefix must be non-empty")
    if not isinstance(spec.swap_public_instance_ids, bool):
        raise ValueError("swap_public_instance_ids must be boolean")
    if not isinstance(spec.require_held_out_interior, bool):
        raise ValueError("require_held_out_interior must be boolean")
    if set(spec.truths) != set(MATCHED_WORLDS):
        raise ValueError("truths must contain historical and counterfactual worlds")
    if not spec.controls or not spec.readouts:
        raise ValueError("a family needs controls and readouts")
    if len({item.name for item in spec.controls}) != len(spec.controls):
        raise ValueError("control names must be unique")
    if len({item.name for item in spec.readouts}) != len(spec.readouts):
        raise ValueError("readout names must be unique")
    for readout in spec.readouts:
        if readout.resolution_kind and readout.resolution_kind not in {
            "measurement_resolution",
            "reporting_increment",
        }:
            raise ValueError("readout resolution_kind is unsupported")
        if readout.resolution_kind and (
            not readout.statistic or not readout.uncertainty
        ):
            raise ValueError(
                "readouts derived from source evidence need statistic and uncertainty semantics"
            )
    if not spec.identification_model or not spec.identification_parameter_specs:
        raise ValueError("identification contract must be explicit")
    if len(set(spec.identification_parameters)) != len(
        spec.identification_parameters
    ):
        raise ValueError("identification parameter names must be unique")
    if not spec.credits or any(
        not credit.citation
        or not credit.role
        or not credit.url.startswith(("https://", "http://"))
        for credit in spec.credits
    ):
        raise ValueError("every family needs explicit source credit")
    if not spec.counterfactual_change.strip():
        raise ValueError("counterfactual_change must state the authored change")
    if not spec.diagnostic_conditions:
        raise ValueError("diagnostic conditions must be declared")
    if len(spec.diagnostic_conditions) > spec.budget:
        raise ValueError("diagnostic conditions must fit within the experiment budget")
    if not spec.hidden_conditions:
        raise ValueError("hidden conditions must be declared")
    if not 0.0 < spec.relative_tolerance < 1.0:
        raise ValueError("relative_tolerance must be in (0, 1)")

    expected_parameters = set(spec.identification_parameters)
    readout_names = tuple(readout.name for readout in spec.readouts)
    control_names = tuple(control.name for control in spec.controls)
    all_conditions = spec.diagnostic_conditions + spec.hidden_conditions
    for condition in all_conditions:
        _validated_controls(spec, condition)

    def condition_key(condition: Mapping[str, Any]) -> Tuple[Any, ...]:
        return tuple(condition[name] for name in control_names)

    if spec.require_held_out_interior:
        diagnostic_keys = tuple(
            condition_key(item) for item in spec.diagnostic_conditions
        )
        hidden_keys = tuple(condition_key(item) for item in spec.hidden_conditions)
        if len(set(diagnostic_keys)) != len(diagnostic_keys):
            raise ValueError("diagnostic conditions must be unique")
        if len(set(hidden_keys)) != len(hidden_keys):
            raise ValueError("hidden conditions must be unique")
        if set(diagnostic_keys) & set(hidden_keys):
            raise ValueError(
                "hidden conditions must be disjoint from diagnostic conditions"
            )
        controls_by_name = _control_map(spec)
        for condition in spec.hidden_conditions:
            for name, value in condition.items():
                control = controls_by_name[name]
                if (
                    control.minimum is not None
                    and control.maximum is not None
                    and (value <= control.minimum or value >= control.maximum)
                ):
                    raise ValueError(
                        "hidden conditions must lie in the control interior"
                    )
        if len(spec.hidden_conditions) > 1:
            for control in spec.controls:
                if len({item[control.name] for item in spec.hidden_conditions}) < 2:
                    raise ValueError(
                        "multiple hidden conditions must vary control %s" % control.name
                    )

    private_parameter_keys = {
        frozenset(truth.parameters) for truth in spec.truths.values()
    }
    if len(private_parameter_keys) != 1:
        raise ValueError("private truth parameter maps must have identical keys")
    for truth in spec.truths.values():
        for name, value in truth.parameters.items():
            _finite_number(value, name)
        identification_values = _identification_values(truth)
        if set(identification_values) != expected_parameters:
            raise ValueError(
                "truth identification values must match the public identification contract"
            )
        for name, value in identification_values.items():
            numeric = _finite_number(value, name)
            parameter = next(
                item
                for item in spec.identification_parameter_specs
                if item.name == name
            )
            if not parameter.contains(numeric):
                raise ValueError(
                    "identification truth parameter %s is outside its public domain"
                    % name
                )
        validate_expression_program(
            {"outputs": truth.discovery_outputs},
            allowed_variables=control_names,
            required_outputs=readout_names,
        )
        for condition in all_conditions:
            controls = _validated_controls(spec, condition)
            expected = _predictions(spec, truth.parameters, controls)
            identified = _identification_predictions(
                spec, identification_values, controls
            )
            expressed = evaluate_expression_program(
                {"outputs": truth.discovery_outputs},
                controls,
                allowed_variables=control_names,
                required_outputs=readout_names,
            )
            for readout in readout_names:
                if not math.isclose(
                    expected[readout],
                    identified[readout],
                    rel_tol=1.0e-10,
                    abs_tol=1.0e-10,
                ):
                    raise ValueError(
                        "identification truth must equal the private world predictor"
                    )
                if not math.isclose(
                    expected[readout],
                    expressed[readout],
                    rel_tol=1.0e-10,
                    abs_tol=1.0e-10,
                ):
                    raise ValueError(
                        "discovery truth must equal the private world predictor"
                    )

    # A compact diagnostic set must actually vary every non-constant numeric
    # control; otherwise claims of active relation testing are unsupported.
    for control in spec.controls:
        values = {condition[control.name] for condition in spec.diagnostic_conditions}
        can_vary = (
            (control.minimum is not None and control.maximum is not None)
            or len(control.allowed_values) > 1
        )
        if can_vary and all(
            isinstance(value, (int, float)) and not isinstance(value, bool)
            for value in values
        ) and len(values) < 2:
            raise ValueError(
                "diagnostic conditions do not vary control %s" % control.name
            )

    historical = spec.truths["historical"]
    counterfactual = spec.truths["counterfactual"]
    changed_parameters = tuple(
        name
        for name in historical.parameters
        if historical.parameters[name] != counterfactual.parameters[name]
    )
    if len(changed_parameters) != 1:
        raise ValueError(
            "a matched counterfactual must change exactly one mechanism parameter"
        )
    diagnostic_separates = False
    for condition in spec.diagnostic_conditions:
        controls = _validated_controls(spec, condition)
        left = _predictions(spec, historical.parameters, controls)
        right = _predictions(spec, counterfactual.parameters, controls)
        for readout in readout_names:
            if _scaled_error(spec, readout, left[readout], right[readout]) > 1.0:
                diagnostic_separates = True
    if not diagnostic_separates:
        raise ValueError("the two worlds are not distinguishable within the budget")

    for source, target in (
        (historical, counterfactual),
        (counterfactual, historical),
    ):
        false_twin_fails = False
        for condition in spec.hidden_conditions:
            controls = _validated_controls(spec, condition)
            prediction = _predictions(spec, source.parameters, controls)
            expected = _predictions(spec, target.parameters, controls)
            if any(
                _scaled_error(
                    spec, readout, prediction[readout], expected[readout]
                )
                > 1.0
                for readout in readout_names
            ):
                false_twin_fails = True
                break
        if not false_twin_fails:
            raise ValueError("each world's identification truth must fail its twin")


__all__ = [
    "DEFAULT_MATCHED_NOTES",
    "MATCHED_WORLDS",
    "IdentificationParameterSpec",
    "MatchedEvaluator",
    "MatchedFamilySpec",
    "MatchedTruth",
    "MatchedWorldModel",
    "SourceCredit",
    "make_matched_case",
    "truth_submission",
    "validate_matched_family_spec",
]
