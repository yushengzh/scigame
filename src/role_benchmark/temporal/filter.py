"""Deterministic eligibility filter for temporal case proposals."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from enum import Enum
from itertools import product
from typing import Any, Dict, Mapping, Optional, Set, Tuple

from role_benchmark.expression import (
    ExpressionError,
    evaluate_expression_program,
    validate_expression_program,
)

from .candidate import TemporalCaseCandidate
from .arxiv import parse_versioned_arxiv_id
from .census import canonicalize_doi


_IDENTIFIER = re.compile(r"^[a-z][a-z0-9_]*$")
_NUMERIC_FLOOR = 1.0e-9


class RejectionCode(str, Enum):
    """Stable reasons why a structurally valid proposal is not case-ready."""

    INVALID_IDENTIFIER = "case.invalid_identifier"
    INVALID_SOURCE_IDENTITY = "case.invalid_source_identity"
    MISSING_OBSERVATION = "case.missing_initial_observation"
    UNSUPPORTED_ORACLE = "oracle.unsupported_kind"
    CONTROL_COUNT = "controls.count"
    READOUT_COUNT = "readouts.count"
    DUPLICATE_NAME = "resource.duplicate_name"
    INVALID_RANGE = "control.invalid_range"
    INVALID_RESOLUTION = "readout.invalid_resolution"
    INVALID_BUDGET = "evaluation.invalid_budget"
    INVALID_THRESHOLD = "evaluation.invalid_threshold"
    OUTPUT_MISMATCH = "oracle.output_mismatch"
    PARAMETER_MISMATCH = "oracle.parameter_mismatch"
    UNUSED_PARAMETER = "oracle.unused_parameter"
    UNKNOWN_VARIABLE = "oracle.unknown_variable"
    UNKNOWN_PARAMETER = "oracle.unknown_parameter"
    INVALID_EXPRESSION = "oracle.invalid_expression"
    DOMAIN_UNSAFE = "oracle.domain_unsafe"
    COUNTERFACTUAL_CHANGE_COUNT = "counterfactual.change_count"
    MISSING_CONDITIONS = "conditions.missing"
    DIAGNOSTIC_OVER_BUDGET = "conditions.diagnostic_over_budget"
    CONDITION_KEYS = "conditions.control_mismatch"
    CONDITION_OUT_OF_RANGE = "conditions.out_of_range"
    DUPLICATE_CONDITION = "conditions.duplicate"
    HELD_OUT_OVERLAP = "conditions.hidden_not_held_out"
    HIDDEN_NOT_INTERIOR = "conditions.hidden_not_interior"
    HIDDEN_NOT_SPREAD = "conditions.hidden_not_spread"
    CONTROL_NOT_VARIED = "conditions.control_not_varied"
    NONFINITE_EVALUATION = "oracle.nonfinite_evaluation"
    WORLDS_NOT_DISTINGUISHABLE = "counterfactual.not_distinguishable"
    FALSE_TWIN_PASSES = "counterfactual.false_twin_passes"
    IDENTIFICATION_NO_COMMON_SKELETON = "identification.no_common_skeleton"
    IDENTIFICATION_CAPACITY = "identification.insufficient_observation_capacity"
    ENUMERABLE_CONTROL_DOMAIN = "discovery.enumerable_control_domain"


@dataclass(frozen=True)
class FilterIssue:
    code: str
    path: str
    message: str


@dataclass(frozen=True)
class FilterResult:
    issues: Tuple[FilterIssue, ...]

    @property
    def eligible(self) -> bool:
        return not self.issues


class IneligibleCandidateError(ValueError):
    """Raised when rendering is requested for a rejected proposal."""

    def __init__(self, result: FilterResult) -> None:
        self.result = result
        super().__init__(
            "temporal candidate is ineligible: "
            + ", ".join(issue.code for issue in result.issues)
        )


def _symbols(expression: Any, variables: Set[str], parameters: Set[str]) -> None:
    if isinstance(expression, (int, float)) and not isinstance(expression, bool):
        return
    if "var" in expression:
        variables.add(expression["var"])
        return
    if "param" in expression:
        parameters.add(expression["param"])
        return
    for argument in expression["args"]:
        _symbols(argument, variables, parameters)


def materialize_expression(
    expression: Any, parameters: Mapping[str, float]
) -> Any:
    """Replace parameter leaves with numbers; never interpret generated code."""

    if isinstance(expression, (int, float)) and not isinstance(expression, bool):
        return float(expression)
    if "var" in expression:
        return {"var": expression["var"]}
    if "param" in expression:
        return float(parameters[expression["param"]])
    return {
        "op": expression["op"],
        "args": [
            materialize_expression(argument, parameters)
            for argument in expression["args"]
        ],
    }


def materialize_outputs(
    outputs: Mapping[str, Any], parameters: Mapping[str, float]
) -> Dict[str, Any]:
    return {
        name: materialize_expression(expression, parameters)
        for name, expression in outputs.items()
    }


def _allowance(
    resolution: Optional[float], relative_tolerance: float, target: float
) -> float:
    absolute_tolerance = (
        resolution if resolution is not None else _NUMERIC_FLOOR
    )
    return absolute_tolerance + relative_tolerance * abs(target)


def _is_interval_control(control: Any) -> bool:
    return (
        control.minimum is not None
        and control.maximum is not None
        and not control.allowed_values
        and control.minimum < control.maximum
    )


def _is_enumerated_control(control: Any) -> bool:
    return (
        control.minimum is None
        and control.maximum is None
        and len(control.allowed_values) >= 2
        and len(set(control.allowed_values)) == len(control.allowed_values)
    )


def _control_contains(control: Any, value: float) -> bool:
    if _is_enumerated_control(control):
        return value in control.allowed_values
    if _is_interval_control(control):
        return control.minimum <= value <= control.maximum
    return False


class _UnsafeDomain(ValueError):
    pass


def _finite_interval(lower: float, upper: float) -> Tuple[float, float]:
    if not math.isfinite(lower) or not math.isfinite(upper) or lower > upper:
        raise _UnsafeDomain("expression is not finite over the control domain")
    return lower, upper


def _multiply_intervals(
    left: Tuple[float, float], right: Tuple[float, float]
) -> Tuple[float, float]:
    values = tuple(a * b for a in left for b in right)
    return _finite_interval(min(values), max(values))


def _power_interval(
    base: Tuple[float, float], exponent: Tuple[float, float]
) -> Tuple[float, float]:
    base_lower, base_upper = base
    exponent_lower, exponent_upper = exponent
    try:
        if exponent_lower == exponent_upper:
            value = exponent_lower
            if value.is_integer():
                integer = int(value)
                if integer < 0 and base_lower <= 0.0 <= base_upper:
                    raise _UnsafeDomain("negative power can divide by zero")
                if integer == 0:
                    return 1.0, 1.0
                values = [base_lower ** integer, base_upper ** integer]
                if integer > 0 and integer % 2 == 0 and base_lower <= 0.0 <= base_upper:
                    values.append(0.0)
                return _finite_interval(min(values), max(values))
            if base_lower < 0.0 or (base_lower == 0.0 and value <= 0.0):
                raise _UnsafeDomain(
                    "non-integer power is undefined for part of the base domain"
                )
            values = [base_lower ** value, base_upper ** value]
            return _finite_interval(min(values), max(values))

        if base_lower <= 0.0:
            raise _UnsafeDomain(
                "a varying exponent requires a strictly positive base domain"
            )
        logarithm = (math.log(base_lower), math.log(base_upper))
        product = _multiply_intervals(
            logarithm, (exponent_lower, exponent_upper)
        )
        return _finite_interval(math.exp(product[0]), math.exp(product[1]))
    except (OverflowError, ValueError) as exc:
        if isinstance(exc, _UnsafeDomain):
            raise
        raise _UnsafeDomain("power is undefined over the control domain") from exc


def _expression_interval(
    expression: Any,
    variables: Mapping[str, Tuple[float, float]],
) -> Tuple[float, float]:
    """Conservatively prove that a materialized expression is domain-total."""

    if isinstance(expression, (int, float)) and not isinstance(expression, bool):
        value = float(expression)
        return _finite_interval(value, value)
    if "var" in expression:
        return variables[expression["var"]]

    operator = expression["op"]
    arguments = [
        _expression_interval(argument, variables)
        for argument in expression["args"]
    ]
    try:
        if operator == "add":
            return _finite_interval(
                sum(item[0] for item in arguments),
                sum(item[1] for item in arguments),
            )
        if operator == "subtract":
            return _finite_interval(
                arguments[0][0] - arguments[1][1],
                arguments[0][1] - arguments[1][0],
            )
        if operator == "multiply":
            result = (1.0, 1.0)
            for argument in arguments:
                result = _multiply_intervals(result, argument)
            return result
        if operator == "divide":
            denominator = arguments[1]
            if denominator[0] <= 0.0 <= denominator[1]:
                raise _UnsafeDomain("denominator can be zero")
            reciprocal = (1.0 / denominator[1], 1.0 / denominator[0])
            return _multiply_intervals(arguments[0], reciprocal)
        if operator == "power":
            return _power_interval(arguments[0], arguments[1])
        if operator == "negate":
            return _finite_interval(-arguments[0][1], -arguments[0][0])
        if operator == "exp":
            return _finite_interval(
                math.exp(arguments[0][0]), math.exp(arguments[0][1])
            )
        if operator == "log":
            if arguments[0][0] <= 0.0:
                raise _UnsafeDomain("log input can be non-positive")
            return _finite_interval(
                math.log(arguments[0][0]), math.log(arguments[0][1])
            )
        if operator == "sin":
            return -1.0, 1.0
        if operator == "maximum":
            return _finite_interval(
                max(item[0] for item in arguments),
                max(item[1] for item in arguments),
            )
        if operator == "step":
            return 0.0, 1.0
    except (ArithmeticError, OverflowError, ValueError) as exc:
        if isinstance(exc, _UnsafeDomain):
            raise
        raise _UnsafeDomain(
            "%s is undefined over the control domain" % operator
        ) from exc
    raise _UnsafeDomain("unsupported expression operator")


def filter_candidate(candidate: TemporalCaseCandidate) -> FilterResult:
    """Apply the closed-form admission rules without an LLM judgment."""

    issues = []

    def reject(code: RejectionCode, path: str, message: str) -> None:
        issues.append(FilterIssue(code.value, path, message))

    identifiers = [
        ("$.family", candidate.family),
        ("$.apparatus.name", candidate.apparatus.name),
    ]
    identifiers.extend(
        ("$.controls[%d].name" % index, item.name)
        for index, item in enumerate(candidate.controls)
    )
    identifiers.extend(
        ("$.readouts[%d].name" % index, item.name)
        for index, item in enumerate(candidate.readouts)
    )
    identifiers.extend(
        ("$.oracle.paper_parameters.%s" % name, name)
        for name in candidate.oracle.paper_parameters
    )
    for path, name in identifiers:
        if not _IDENTIFIER.fullmatch(name):
            reject(
                RejectionCode.INVALID_IDENTIFIER,
                path,
                "names must use lower_snake_case",
            )

    try:
        canonical_doi = canonicalize_doi(candidate.source.journal_doi)
    except ValueError:
        canonical_doi = ""
    if (
        canonical_doi != candidate.source.journal_doi
        or not canonical_doi.startswith("10.")
        or "/" not in canonical_doi
        or any(character.isspace() for character in canonical_doi)
    ):
        reject(
            RejectionCode.INVALID_SOURCE_IDENTITY,
            "$.source.journal_doi",
            "journal DOI must use its canonical DOI form",
        )
    try:
        versioned_id = parse_versioned_arxiv_id(candidate.source.arxiv_versioned_id)
    except ValueError:
        versioned_id = ""
    if versioned_id != candidate.source.arxiv_versioned_id:
        reject(
            RejectionCode.INVALID_SOURCE_IDENTITY,
            "$.source.arxiv_versioned_id",
            "arXiv source must identify one concrete version",
        )
    if not candidate.initial_observations:
        reject(
            RejectionCode.MISSING_OBSERVATION,
            "$.initial_observations",
            "at least one initial observation is required",
        )
    if candidate.oracle.kind != "closed_form":
        reject(
            RejectionCode.UNSUPPORTED_ORACLE,
            "$.oracle.kind",
            "the initial temporal pipeline accepts only closed_form",
        )
    if not 1 <= len(candidate.controls) <= 5:
        reject(
            RejectionCode.CONTROL_COUNT,
            "$.controls",
            "a case needs 1-5 numeric controls",
        )
    if not 1 <= len(candidate.readouts) <= 2:
        reject(
            RejectionCode.READOUT_COUNT,
            "$.readouts",
            "a case needs 1-2 numeric readouts",
        )

    control_names = tuple(item.name for item in candidate.controls)
    readout_names = tuple(item.name for item in candidate.readouts)
    if len(set(control_names)) != len(control_names):
        reject(
            RejectionCode.DUPLICATE_NAME,
            "$.controls",
            "control names must be unique",
        )
    if len(set(readout_names)) != len(readout_names):
        reject(
            RejectionCode.DUPLICATE_NAME,
            "$.readouts",
            "readout names must be unique",
        )
    for index, control in enumerate(candidate.controls):
        if not (_is_interval_control(control) or _is_enumerated_control(control)):
            reject(
                RejectionCode.INVALID_RANGE,
                "$.controls[%d]" % index,
                "declare either minimum < maximum or at least two unique allowed_values",
            )
    for index, readout in enumerate(candidate.readouts):
        if (readout.resolution is None) != (readout.resolution_kind is None):
            reject(
                RejectionCode.INVALID_RESOLUTION,
                "$.readouts[%d]" % index,
                "resolution and resolution_kind must both be null or both be set",
            )
        elif readout.resolution is not None and readout.resolution <= 0.0:
            reject(
                RejectionCode.INVALID_RESOLUTION,
                "$.readouts[%d].resolution" % index,
                "resolution must be positive",
            )

    if candidate.budget < 1 or candidate.max_replicates < 1:
        reject(
            RejectionCode.INVALID_BUDGET,
            "$.budget",
            "budget and max_replicates must be positive",
        )
    if (
        not 0.0 < candidate.confidence_threshold <= 1.0
        or not 0.0 < candidate.relative_tolerance < 1.0
    ):
        reject(
            RejectionCode.INVALID_THRESHOLD,
            "$.confidence_threshold",
            "confidence threshold must be in (0,1] and relative tolerance in (0,1)",
        )

    if set(candidate.oracle.outputs) != set(readout_names):
        reject(
            RejectionCode.OUTPUT_MISMATCH,
            "$.oracle.outputs",
            "outputs must match readouts exactly",
        )
    paper_parameters = set(candidate.oracle.paper_parameters)
    counterfactual_parameters = set(candidate.oracle.counterfactual_parameters)
    if not paper_parameters or paper_parameters != counterfactual_parameters:
        reject(
            RejectionCode.PARAMETER_MISMATCH,
            "$.oracle",
            "both worlds must define the same non-empty parameter set",
        )
    changed = [
        name
        for name in sorted(paper_parameters & counterfactual_parameters)
        if candidate.oracle.paper_parameters[name]
        != candidate.oracle.counterfactual_parameters[name]
    ]
    if len(changed) != 1:
        reject(
            RejectionCode.COUNTERFACTUAL_CHANGE_COUNT,
            "$.oracle.counterfactual_parameters",
            "exactly one parameter value must change",
        )

    used_variables: Set[str] = set()
    used_parameters: Set[str] = set()
    for expression in candidate.oracle.outputs.values():
        _symbols(expression, used_variables, used_parameters)
    for name in sorted(used_variables - set(control_names)):
        reject(
            RejectionCode.UNKNOWN_VARIABLE,
            "$.oracle.outputs",
            "unknown control variable %r" % name,
        )
    for name in sorted(used_parameters - paper_parameters):
        reject(
            RejectionCode.UNKNOWN_PARAMETER,
            "$.oracle.outputs",
            "unknown named parameter %r" % name,
        )
    for name in sorted(paper_parameters - used_parameters):
        reject(
            RejectionCode.UNUSED_PARAMETER,
            "$.oracle.paper_parameters.%s" % name,
            "every named parameter must affect an output template",
        )

    programs: Dict[str, Mapping[str, Any]] = {}
    if not (used_parameters - paper_parameters) and paper_parameters == counterfactual_parameters:
        for world, parameters in (
            ("historical", candidate.oracle.paper_parameters),
            ("counterfactual", candidate.oracle.counterfactual_parameters),
        ):
            try:
                outputs = materialize_outputs(candidate.oracle.outputs, parameters)
                program = {"outputs": outputs}
                validate_expression_program(
                    program,
                    allowed_variables=control_names,
                    required_outputs=readout_names,
                )
                programs[world] = program
            except (ExpressionError, KeyError) as exc:
                reject(
                    RejectionCode.INVALID_EXPRESSION,
                    "$.oracle.outputs",
                    "%s expression is invalid: %s" % (world, exc),
                )

    ranges_are_valid = (
        len(set(control_names)) == len(control_names)
        and all(
            _is_interval_control(item) or _is_enumerated_control(item)
            for item in candidate.controls
        )
    )
    if programs and ranges_are_valid:
        variable_intervals = {
            item.name: (
                (item.minimum, item.maximum)
                if _is_interval_control(item)
                else (min(item.allowed_values), max(item.allowed_values))
            )
            for item in candidate.controls
        }
        enumerated_controls = tuple(
            item for item in candidate.controls if _is_enumerated_control(item)
        )
        for world, program in programs.items():
            for readout, expression in program["outputs"].items():
                try:
                    _expression_interval(expression, variable_intervals)
                except _UnsafeDomain as exc:
                    # The interval hull can contain unsupported points between
                    # discrete settings.  The Oracle only owes answers on Q,
                    # so retry with every enumerated coordinate fixed exactly.
                    if enumerated_controls:
                        try:
                            for values in product(
                                *(item.allowed_values for item in enumerated_controls)
                            ):
                                exact_intervals = dict(variable_intervals)
                                for control, value in zip(
                                    enumerated_controls, values
                                ):
                                    exact_intervals[control.name] = (value, value)
                                _expression_interval(expression, exact_intervals)
                            continue
                        except _UnsafeDomain as exact_exc:
                            exc = exact_exc
                    reject(
                        RejectionCode.DOMAIN_UNSAFE,
                        "$.oracle.outputs.%s" % readout,
                        "%s world is not total on the declared control domain: %s"
                        % (world, exc),
                    )

    if not candidate.diagnostic_conditions or not candidate.hidden_conditions:
        reject(
            RejectionCode.MISSING_CONDITIONS,
            "$.diagnostic_conditions",
            "both diagnostic and hidden conditions are required",
        )
    if len(candidate.diagnostic_conditions) > candidate.budget:
        reject(
            RejectionCode.DIAGNOSTIC_OVER_BUDGET,
            "$.diagnostic_conditions",
            "diagnostic set must fit within the Player experiment budget",
        )

    valid_conditions: Dict[str, list[Mapping[str, float]]] = {
        "diagnostic": [],
        "hidden": [],
    }
    controls_by_name = {item.name: item for item in candidate.controls}
    for group_name, conditions in (
        ("diagnostic", candidate.diagnostic_conditions),
        ("hidden", candidate.hidden_conditions),
    ):
        for index, condition in enumerate(conditions):
            path = "$.%s_conditions[%d]" % (group_name, index)
            if set(condition) != set(control_names):
                reject(
                    RejectionCode.CONDITION_KEYS,
                    path,
                    "condition controls must match declared controls exactly",
                )
                continue
            out_of_range = [
                name
                for name, value in condition.items()
                if not _control_contains(controls_by_name[name], value)
            ]
            if out_of_range:
                reject(
                    RejectionCode.CONDITION_OUT_OF_RANGE,
                    path,
                    "outside declared range: %s" % ", ".join(sorted(out_of_range)),
                )
                continue
            valid_conditions[group_name].append(condition)

    # Held-out evaluation only measures generalization when it contains new
    # interventions.  Exact tuple comparison is appropriate here because the
    # conditions are decoded numeric literals, not noisy measurements.
    condition_keys: Dict[str, list[Tuple[float, ...]]] = {
        group_name: [
            tuple(float(condition[name]) for name in control_names)
            for condition in conditions
        ]
        for group_name, conditions in valid_conditions.items()
    }
    for group_name, keys in condition_keys.items():
        if len(keys) != len(set(keys)):
            reject(
                RejectionCode.DUPLICATE_CONDITION,
                "$.%s_conditions" % group_name,
                "%s conditions must be unique" % group_name,
            )
    if set(condition_keys["diagnostic"]) & set(condition_keys["hidden"]):
        reject(
            RejectionCode.HELD_OUT_OVERLAP,
            "$.hidden_conditions",
            "hidden conditions must be disjoint from Player-visible diagnostic conditions",
        )

    for index, condition in enumerate(valid_conditions["hidden"]):
        boundary_controls = [
            name
            for name, value in condition.items()
            if _is_interval_control(controls_by_name[name])
            and (
                value <= controls_by_name[name].minimum
                or value >= controls_by_name[name].maximum
            )
        ]
        if boundary_controls:
            reject(
                RejectionCode.HIDDEN_NOT_INTERIOR,
                "$.hidden_conditions[%d]" % index,
                "hidden conditions must lie in the interior of the supported domain: %s"
                % ", ".join(sorted(boundary_controls)),
            )

    if len(valid_conditions["hidden"]) > 1:
        unvaried_hidden_controls = [
            name
            for name in control_names
            if len(
                {condition[name] for condition in valid_conditions["hidden"]}
            )
            < 2
        ]
        if unvaried_hidden_controls:
            reject(
                RejectionCode.HIDDEN_NOT_SPREAD,
                "$.hidden_conditions",
                "multiple hidden conditions must vary every control: %s"
                % ", ".join(sorted(unvaried_hidden_controls)),
            )

    for name in control_names:
        values = {
            condition[name]
            for condition in valid_conditions["diagnostic"]
            if name in condition
        }
        if len(values) < 2:
            reject(
                RejectionCode.CONTROL_NOT_VARIED,
                "$.diagnostic_conditions",
                "diagnostic conditions must vary control %s" % name,
            )

    predictions: Dict[Tuple[str, str, int], Mapping[str, float]] = {}
    if len(programs) == 2:
        for group_name, conditions in valid_conditions.items():
            for index, condition in enumerate(conditions):
                for world, program in programs.items():
                    try:
                        values = evaluate_expression_program(
                            program,
                            condition,
                            allowed_variables=control_names,
                            required_outputs=readout_names,
                        )
                        if not all(math.isfinite(value) for value in values.values()):
                            raise ExpressionError("non-finite output")
                        predictions[(group_name, world, index)] = values
                    except (ExpressionError, ArithmeticError, ValueError) as exc:
                        reject(
                            RejectionCode.NONFINITE_EVALUATION,
                            "$.%s_conditions[%d]" % (group_name, index),
                            "%s world is undefined: %s" % (world, exc),
                        )

    readouts_by_name = {item.name: item for item in candidate.readouts}
    diagnostic_separates = False
    for index in range(len(valid_conditions["diagnostic"])):
        left = predictions.get(("diagnostic", "historical", index))
        right = predictions.get(("diagnostic", "counterfactual", index))
        if left is None or right is None:
            continue
        if any(
            abs(left[name] - right[name])
            > _allowance(
                readouts_by_name[name].resolution,
                candidate.relative_tolerance,
                right[name],
            )
            for name in readout_names
        ):
            diagnostic_separates = True
    if programs and not diagnostic_separates:
        reject(
            RejectionCode.WORLDS_NOT_DISTINGUISHABLE,
            "$.diagnostic_conditions",
            "the worlds do not differ beyond declared tolerance and resolution",
        )

    for source, target in (
        ("historical", "counterfactual"),
        ("counterfactual", "historical"),
    ):
        false_twin_fails = False
        for index in range(len(valid_conditions["hidden"])):
            predicted = predictions.get(("hidden", source, index))
            expected = predictions.get(("hidden", target, index))
            if predicted is None or expected is None:
                continue
            if any(
                abs(predicted[name] - expected[name])
                > _allowance(
                    readouts_by_name[name].resolution,
                    candidate.relative_tolerance,
                    expected[name],
                )
                for name in readout_names
            ):
                false_twin_fails = True
                break
        if programs and not false_twin_fails:
            reject(
                RejectionCode.FALSE_TWIN_PASSES,
                "$.hidden_conditions",
                "%s truth would pass the %s held-out world" % (source, target),
            )

    # A dual-track candidate is not admissible unless the two private laws can
    # be projected to one world-neutral Identification scaffold.  The deferred
    # import avoids making the renderer part of basic candidate decoding.
    if not issues:
        from .render import (  # pylint: disable=import-outside-toplevel
            IdentificationProjectionError,
            build_identification_contract,
        )

        try:
            identification = build_identification_contract(candidate)
        except IdentificationProjectionError as exc:
            reject(
                RejectionCode.IDENTIFICATION_NO_COMMON_SKELETON,
                exc.path,
                str(exc),
            )
        else:
            parameter_count = len(identification.parameter_names)
            readout_count = len(candidate.readouts)
            budget_capacity = candidate.budget * readout_count
            if parameter_count > budget_capacity:
                reject(
                    RejectionCode.IDENTIFICATION_CAPACITY,
                    "$.budget",
                    (
                        "the Identification contract has %d free parameters but "
                        "the episode can return at most %d scalar observations"
                    )
                    % (parameter_count, budget_capacity),
                )

            if all(control.allowed_values for control in candidate.controls):
                unique_conditions = math.prod(
                    len(control.allowed_values) for control in candidate.controls
                )
                grid_capacity = unique_conditions * readout_count
                if parameter_count > grid_capacity:
                    reject(
                        RejectionCode.IDENTIFICATION_CAPACITY,
                        "$.controls",
                        (
                            "the Identification contract has %d free parameters but "
                            "the finite control grid can return at most %d distinct "
                            "scalar observations"
                        )
                        % (parameter_count, grid_capacity),
                    )
                if unique_conditions <= candidate.budget:
                    reject(
                        RejectionCode.ENUMERABLE_CONTROL_DOMAIN,
                        "$.controls",
                        (
                            "the finite control domain has %d unique conditions, so "
                            "an episode budget of %d can enumerate the entire domain"
                        )
                        % (unique_conditions, candidate.budget),
                    )

    return FilterResult(tuple(issues))


__all__ = [
    "FilterIssue",
    "FilterResult",
    "IneligibleCandidateError",
    "RejectionCode",
    "filter_candidate",
    "materialize_expression",
    "materialize_outputs",
]
