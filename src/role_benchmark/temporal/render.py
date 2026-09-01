"""Render an eligible temporal proposal as a normal matched-family module."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Mapping, Tuple, Union

from role_benchmark.cases.matched import (
    IdentificationParameterSpec,
    MatchedFamilySpec,
    MatchedTruth,
    SourceCredit,
)
from role_benchmark.expression import evaluate_expression_program
from role_benchmark.models import ControlSpec, ReadoutSpec

from .candidate import TemporalCaseCandidate, candidate_to_payload
from .filter import IneligibleCandidateError, filter_candidate, materialize_outputs


@dataclass(frozen=True)
class TemporalIdentificationContract:
    """A world-neutral scalar-parameter scaffold shared by both active laws.

    This is a representational contract for the Identification track.  It does
    not claim that every exposed scalar is statistically identifiable under a
    particular experiment budget.
    """

    outputs: Mapping[str, Any]
    parameter_names: Tuple[str, ...]
    paper_parameters: Mapping[str, float]
    alternate_parameters: Mapping[str, float]
    paper_outputs: Mapping[str, Any]
    alternate_outputs: Mapping[str, Any]


class IdentificationProjectionError(ValueError):
    """The two private laws cannot form one non-leaking Identification task."""

    code = "identification.no_common_skeleton"

    def __init__(self, message: str) -> None:
        self.path = "$.oracle.outputs"
        super().__init__(message)


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _contains_symbol(expression: Any) -> bool:
    if _is_number(expression):
        return False
    if "var" in expression or "param" in expression:
        return True
    return any(_contains_symbol(argument) for argument in expression["args"])


def _numeric_value(expression: Mapping[str, Any]) -> float:
    value = evaluate_expression_program(
        {"outputs": {"value": expression}},
        {},
        allowed_variables=(),
        required_outputs=("value",),
    )["value"]
    if not math.isfinite(value):
        raise ValueError("identification scaffold contains a non-finite constant")
    return value


def _simplify_expression(expression: Any) -> Any:
    """Fold only exact selector arithmetic; preserve the scientific structure."""

    if _is_number(expression) or "var" in expression or "param" in expression:
        return expression
    operator = expression["op"]
    arguments = [_simplify_expression(item) for item in expression["args"]]
    candidate = {"op": operator, "args": arguments}
    if not _contains_symbol(candidate):
        return _numeric_value(candidate)
    if operator == "add":
        arguments = [item for item in arguments if not (_is_number(item) and item == 0)]
        if not arguments:
            return 0.0
        if len(arguments) == 1:
            return arguments[0]
    elif operator == "multiply":
        if any(_is_number(item) and item == 0 for item in arguments):
            return 0.0
        arguments = [item for item in arguments if not (_is_number(item) and item == 1)]
        if not arguments:
            return 1.0
        if len(arguments) == 1:
            return arguments[0]
    elif operator == "subtract" and _is_number(arguments[1]) and arguments[1] == 0:
        return arguments[0]
    elif operator == "divide" and _is_number(arguments[1]) and arguments[1] == 1:
        return arguments[0]
    elif operator == "power" and _is_number(arguments[1]):
        if arguments[1] == 0:
            return 1.0
        if arguments[1] == 1:
            return arguments[0]
    return {"op": operator, "args": arguments}


def _select_branch_outputs(
    outputs: Mapping[str, Any], selector: str, value: float
) -> Mapping[str, Any]:
    def select(expression: Any) -> Any:
        if _is_number(expression) or "var" in expression:
            return expression
        if "param" in expression:
            return value if expression["param"] == selector else expression
        return _simplify_expression(
            {"op": expression["op"], "args": [select(item) for item in expression["args"]]}
        )

    return {name: select(expression) for name, expression in outputs.items()}


def _parameter_base(output: str, operator: str, index: int) -> str:
    if operator == "power" and index == 1:
        role = "exponent"
    elif operator in {"multiply", "divide"}:
        role = "scale"
    elif operator in {"add", "subtract"}:
        role = "offset"
    else:
        role = "parameter"
    return "%s_%s" % (output, role)


def _is_compiled_selector_program(
    outputs: Mapping[str, Any], selector: str
) -> bool:
    """Recognize only the deterministic two-branch shape emitted by the binder."""

    def selector_role(expression: Any) -> str:
        if isinstance(expression, Mapping) and expression == {"param": selector}:
            return "selector"
        if (
            isinstance(expression, Mapping)
            and expression.get("op") == "subtract"
            and expression.get("args")
            == [1.0, {"param": selector}]
        ):
            return "complement"
        return ""

    def contains_selector(expression: Any) -> bool:
        if _is_number(expression) or "var" in expression:
            return False
        if "param" in expression:
            return expression["param"] == selector
        return any(contains_selector(item) for item in expression["args"])

    for expression in outputs.values():
        if not (
            isinstance(expression, Mapping)
            and expression.get("op") == "add"
            and len(expression.get("args", ())) == 2
        ):
            return False
        roles = []
        for term in expression["args"]:
            if not (
                isinstance(term, Mapping)
                and term.get("op") == "multiply"
                and len(term.get("args", ())) >= 2
            ):
                return False
            role = selector_role(term["args"][0])
            if not role or any(contains_selector(item) for item in term["args"][1:]):
                return False
            roles.append(role)
        if set(roles) != {"selector", "complement"}:
            return False
    return True


def build_identification_contract(
    candidate: TemporalCaseCandidate,
) -> TemporalIdentificationContract:
    """Anti-unify the two active laws without exposing selector internals.

    Identification is admitted only when both worlds instantiate one common
    expression skeleton.  Source parameter leaves become neutral public slots;
    private branch names and inactive-branch parameters disappear.
    """

    paper_parameter_map = candidate.oracle.paper_parameters
    alternate_parameter_map = candidate.oracle.counterfactual_parameters
    changed = [
        name
        for name in paper_parameter_map
        if paper_parameter_map[name] != alternate_parameter_map[name]
    ]
    if len(changed) != 1:
        raise IdentificationProjectionError(
            "temporal Oracle must change exactly one private mechanism parameter"
        )
    selector = changed[0]
    compiled_selector = _is_compiled_selector_program(
        candidate.oracle.outputs, selector
    )
    if compiled_selector:
        selector_values = {
            float(paper_parameter_map[selector]),
            float(alternate_parameter_map[selector]),
        }
        if selector_values != {0.0, 1.0}:
            raise IdentificationProjectionError(
                "a compiled private branch selector must switch exactly between zero and one"
            )
        paper_skeleton = _select_branch_outputs(
            candidate.oracle.outputs, selector, paper_parameter_map[selector]
        )
        alternate_skeleton = _select_branch_outputs(
            candidate.oracle.outputs,
            selector,
            alternate_parameter_map[selector],
        )
    else:
        # Ordinary authored families already share one expression tree.  Run
        # them through the same neutral projection so source names such as
        # ``historical_*`` or ``alpha_*`` never enter the Player contract.
        paper_skeleton = dict(candidate.oracle.outputs)
        alternate_skeleton = dict(candidate.oracle.outputs)

    pair_names: Dict[Tuple[str, str], str] = {}
    left_to_right: Dict[str, str] = {}
    right_to_left: Dict[str, str] = {}
    used_names: Dict[str, int] = {}
    parameter_names = []
    paper_values: Dict[str, float] = {}
    alternate_values: Dict[str, float] = {}

    def allocate(base: str, left_name: str, right_name: str) -> str:
        pair = (left_name, right_name)
        existing = pair_names.get(pair)
        if existing is not None:
            return existing
        if (
            left_name in left_to_right
            and left_to_right[left_name] != right_name
        ) or (
            right_name in right_to_left
            and right_to_left[right_name] != left_name
        ):
            raise IdentificationProjectionError(
                "source branches do not preserve repeated-parameter identity"
            )
        left_to_right[left_name] = right_name
        right_to_left[right_name] = left_name
        count = used_names.get(base, 0) + 1
        used_names[base] = count
        name = base if count == 1 else "%s_%d" % (base, count)
        pair_names[pair] = name
        parameter_names.append(name)
        try:
            paper_values[name] = float(paper_parameter_map[left_name])
            alternate_values[name] = float(alternate_parameter_map[right_name])
        except KeyError as exc:
            raise IdentificationProjectionError(
                "active identification branch references an unknown source parameter"
            ) from exc
        return name

    def unify(
        left: Any,
        right: Any,
        *,
        output: str,
        parent_operator: str = "root",
        argument_index: int = 0,
    ) -> Any:
        if _is_number(left) and _is_number(right):
            if float(left) == float(right):
                return float(left)
            raise IdentificationProjectionError(
                "source branches contain unmatched numeric literals outside named parameters"
            )
        if isinstance(left, Mapping) and isinstance(right, Mapping):
            if set(left) == {"var"} and set(right) == {"var"}:
                if left["var"] != right["var"]:
                    raise IdentificationProjectionError(
                        "source branches use different public controls"
                    )
                return {"var": left["var"]}
            if set(left) == {"param"} and set(right) == {"param"}:
                try:
                    left_value = float(paper_parameter_map[left["param"]])
                    right_value = float(alternate_parameter_map[right["param"]])
                except KeyError as exc:
                    raise IdentificationProjectionError(
                        "active identification branch references an unknown source parameter"
                    ) from exc
                if left_value == right_value:
                    # A scalar that is fixed in both source-grounded worlds is
                    # part of the common public model, not an unknown mechanism
                    # coordinate.  Keeping it as a free slot creates artificial
                    # non-identifiability without adding scientific signal.
                    return left_value
                name = allocate(
                    _parameter_base(output, parent_operator, argument_index),
                    left["param"],
                    right["param"],
                )
                return {"param": name}
            if set(left) == {"op", "args"} and set(right) == {"op", "args"}:
                if left["op"] != right["op"] or len(left["args"]) != len(right["args"]):
                    raise IdentificationProjectionError(
                        "source branches do not share one identification model skeleton"
                    )
                return {
                    "op": left["op"],
                    "args": [
                        unify(
                            left_item,
                            right_item,
                            output=output,
                            parent_operator=left["op"],
                            argument_index=index,
                        )
                        for index, (left_item, right_item) in enumerate(
                            zip(left["args"], right["args"])
                        )
                    ],
                }
        raise IdentificationProjectionError(
            "source branches do not share one identification model skeleton"
        )

    if set(paper_skeleton) != set(alternate_skeleton):
        raise IdentificationProjectionError(
            "source branches report different readout sets"
        )
    identification_outputs = {
        output: unify(
            paper_skeleton[output], alternate_skeleton[output], output=output
        )
        for output in sorted(paper_skeleton)
    }
    if not parameter_names:
        raise IdentificationProjectionError(
            "identification scaffold has no scalar parameter slots"
        )

    paper_outputs = materialize_outputs(paper_skeleton, paper_parameter_map)
    alternate_outputs = materialize_outputs(
        alternate_skeleton, alternate_parameter_map
    )
    return TemporalIdentificationContract(
        outputs=identification_outputs,
        parameter_names=tuple(parameter_names),
        paper_parameters=paper_values,
        alternate_parameters=alternate_values,
        paper_outputs=paper_outputs,
        alternate_outputs=alternate_outputs,
    )


def _swap_public_instance_ids(candidate: TemporalCaseCandidate) -> bool:
    """Balance the opaque mapping by the private sequential arXiv record parity."""

    stem = candidate.source.arxiv_versioned_id.rsplit("v", 1)[0]
    digits = "".join(character for character in stem if character.isdigit())
    if not digits:
        raise ValueError("versioned arXiv identity must contain a numeric record id")
    return int(digits[-1]) % 2 == 1


def _identification_parameter_spec(
    name: str, readout_names: Tuple[str, ...]
) -> IdentificationParameterSpec:
    """Describe one neutral scaffold slot without reconstructing private names."""

    output = next(
        (item for item in sorted(readout_names, key=len, reverse=True)
         if name.startswith(item + "_")),
        "the corresponding readout",
    )
    suffix = name[len(output) + 1 :] if output in readout_names else name
    role = suffix.rsplit("_", 1)[0] if suffix.rsplit("_", 1)[-1].isdigit() else suffix
    role_text = {
        "exponent": "Exponent",
        "scale": "Multiplicative or divisive coefficient",
        "offset": "Additive or subtractive coefficient",
        "parameter": "Scalar coefficient",
    }.get(role, "Scalar coefficient")
    return IdentificationParameterSpec(
        name=name,
        description=(
            "%s at the named position(s) of the public expression for %s; "
            "repeated occurrences share one value."
            % (role_text, output)
        ),
        unit=("1" if role == "exponent" else "expression-defined"),
    )


def build_matched_spec(candidate: TemporalCaseCandidate) -> MatchedFamilySpec:
    """Compile a filtered proposal to the existing declarative case contract."""

    result = filter_candidate(candidate)
    if not result.eligible:
        raise IneligibleCandidateError(result)

    control_names = tuple(item.name for item in candidate.controls)
    readout_names = tuple(item.name for item in candidate.readouts)
    template = dict(candidate.oracle.outputs)
    identification = build_identification_contract(candidate)

    def predict(
        parameters: Mapping[str, float], controls: Mapping[str, Any]
    ) -> Mapping[str, float]:
        return evaluate_expression_program(
            {"outputs": materialize_outputs(template, parameters)},
            controls,
            allowed_variables=control_names,
            required_outputs=readout_names,
        )

    def identification_predict(
        parameters: Mapping[str, float], controls: Mapping[str, Any]
    ) -> Mapping[str, float]:
        return evaluate_expression_program(
            {
                "outputs": materialize_outputs(
                    identification.outputs, parameters
                )
            },
            controls,
            allowed_variables=control_names,
            required_outputs=readout_names,
        )

    template_text = json.dumps(
        {"outputs": identification.outputs},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return MatchedFamilySpec(
        family=candidate.family,
        # Runtime identifiers may repeat public apparatus semantics, but must
        # not expose the private source/family label or its hidden world axis.
        case_id_prefix="temporal.%s" % candidate.apparatus.name,
        response_title=candidate.title,
        apparatus_name=candidate.apparatus.name,
        apparatus_description=candidate.apparatus.description,
        background=candidate.background,
        initial_observations=candidate.initial_observations,
        controls=tuple(
            ControlSpec(
                name=item.name,
                description=item.description,
                unit=item.unit,
                minimum=item.minimum,
                maximum=item.maximum,
                allowed_values=item.allowed_values,
            )
            for item in candidate.controls
        ),
        readouts=tuple(
            ReadoutSpec(
                name=item.name,
                description=item.description,
                unit=item.unit,
                resolution=item.resolution,
                statistic=item.statistic,
                uncertainty=item.uncertainty,
                resolution_kind=item.resolution_kind or "",
            )
            for item in candidate.readouts
        ),
        identification_model="case_specific_closed_form",
        identification_parameter_specs=tuple(
            _identification_parameter_spec(name, readout_names)
            for name in identification.parameter_names
        ),
        identification_formula="Expression template: " + template_text,
        predict=predict,
        truths={
            "historical": MatchedTruth(
                parameters=dict(candidate.oracle.paper_parameters),
                discovery_outputs=identification.paper_outputs,
                applicability=candidate.oracle.paper_applicability,
                fixed_conditions=tuple(
                    item.statement
                    for item in (
                        candidate.common_fixed_conditions
                        + candidate.oracle.paper_fixed_conditions
                    )
                ),
                identification_values=dict(identification.paper_parameters),
            ),
            "counterfactual": MatchedTruth(
                parameters=dict(candidate.oracle.counterfactual_parameters),
                discovery_outputs=identification.alternate_outputs,
                applicability=candidate.oracle.counterfactual_applicability,
                fixed_conditions=tuple(
                    item.statement
                    for item in (
                        candidate.common_fixed_conditions
                        + candidate.oracle.counterfactual_fixed_conditions
                    )
                ),
                identification_values=dict(identification.alternate_parameters),
            ),
        },
        diagnostic_conditions=candidate.diagnostic_conditions,
        hidden_conditions=candidate.hidden_conditions,
        credits=(
            SourceCredit(
                citation=candidate.source.citation,
                url="https://doi.org/%s" % candidate.source.journal_doi,
                role=(
                    "%s arXiv source: %s. Source locator: %s. Extracted claim: %s"
                    % (
                        candidate.source.role,
                        candidate.source.arxiv_versioned_id,
                        candidate.source.locator,
                        candidate.claim,
                    )
                ),
            ),
        ),
        counterfactual_change=candidate.counterfactual_change,
        common_notes=candidate.notes,
        common_fixed_conditions=tuple(
            item.statement for item in candidate.common_fixed_conditions
        ),
        swap_public_instance_ids=_swap_public_instance_ids(candidate),
        require_held_out_interior=True,
        budget=candidate.budget,
        max_replicates=candidate.max_replicates,
        confidence_threshold=candidate.confidence_threshold,
        relative_tolerance=candidate.relative_tolerance,
        identification_predict=identification_predict,
    )


def render_candidate_module(candidate: TemporalCaseCandidate) -> str:
    """Produce deterministic Python data plus trusted construction calls."""

    build_matched_spec(candidate)
    payload = json.dumps(
        candidate_to_payload(candidate),
        ensure_ascii=False,
        indent=4,
        sort_keys=True,
    )
    constant = candidate.family.upper() + "_SPEC"
    factory = "make_%s_case" % candidate.family
    return '''"""Generated paper-grounded temporal matched family."""

import json

from role_benchmark.cases.matched import make_matched_case
from role_benchmark.models import BenchmarkTrack
from role_benchmark.temporal.candidate import parse_candidate_payload
from role_benchmark.temporal.render import build_matched_spec


_CANDIDATE = json.loads(%r)

%s = build_matched_spec(parse_candidate_payload(_CANDIDATE))


def %s(
    world="historical",
    track=BenchmarkTrack.IDENTIFICATION,
):
    return make_matched_case(%s, world, track)


__all__ = ["%s", "%s"]
''' % (payload, constant, factory, constant, constant, factory)


def write_candidate_module(
    candidate: TemporalCaseCandidate, path: Union[str, Path]
) -> Path:
    """Write one accepted generated module to an explicit ``.py`` path."""

    output = Path(path)
    if output.suffix.lower() != ".py":
        raise ValueError("generated case path must end in .py")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(render_candidate_module(candidate), encoding="utf-8")
    return output


__all__ = [
    "IdentificationProjectionError",
    "TemporalIdentificationContract",
    "build_identification_contract",
    "build_matched_spec",
    "render_candidate_module",
    "write_candidate_module",
]
