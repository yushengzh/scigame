"""Deterministic compilation of one reviewed Temporal quantitative relation."""

from __future__ import annotations

import itertools
import json
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Mapping, Sequence, Tuple, Union

from role_benchmark.cases.matched import (
    IdentificationParameterSpec,
    MatchedTruth,
    SourceCredit,
)
from role_benchmark.cases.source import SourceFamilySpec
from role_benchmark.expression import evaluate_expression_program
from role_benchmark.models import ControlSpec, ReadoutSpec

from .filter import materialize_outputs, validate_materialized_outputs_totality
from .admission import (
    TemporalAdmissionResult,
    assess_temporal_admission,
    parse_temporal_admission_review_payload,
    temporal_admission_review_to_payload,
)
from .minimal_science_card import (
    MinimalAnchor,
    MinimalQuantitativeRelation,
    MinimalScienceCard,
    minimal_science_card_to_payload,
)


TEMPORAL_PROVENANCE_SCHEMA = "role_benchmark.temporal_provenance.v1"
_IDENTIFIER = re.compile(r"^[a-z][a-z0-9_]*$")


class TemporalCaseConstructionError(ValueError):
    """A reviewed relation cannot support the deterministic case contract."""


@dataclass(frozen=True)
class TemporalSourceCaseBuild:
    spec: SourceFamilySpec
    provenance: Mapping[str, Any]


def _canonical_name(value: str) -> str:
    result = value.lower()
    if _IDENTIFIER.fullmatch(result) is None:
        raise TemporalCaseConstructionError(
            "minimal ScienceCard names must canonicalize to lower_snake_case"
        )
    return result


def _canonical_expression(expression: Any) -> Any:
    if isinstance(expression, (int, float)) and not isinstance(expression, bool):
        return float(expression)
    if "var" in expression:
        return {"var": _canonical_name(expression["var"])}
    if "param" in expression:
        return {"param": _canonical_name(expression["param"])}
    return {
        "op": expression["op"],
        "args": [_canonical_expression(item) for item in expression["args"]],
    }


def _condition_key(
    condition: Mapping[str, float],
    control_names: Sequence[str],
) -> Tuple[float, ...]:
    return tuple(float(condition[name]) for name in control_names)


def _domain_levels(domain: Any) -> Tuple[float, ...]:
    if domain.domain_kind == "continuous_interval":
        if domain.minimum is None or domain.maximum is None:
            raise TemporalCaseConstructionError(
                "continuous control domain is missing a finite endpoint"
            )
        lower = float(domain.minimum)
        upper = float(domain.maximum)
        width = upper - lower
        if not math.isfinite(width) or width <= 0.0:
            raise TemporalCaseConstructionError(
                "continuous control domain does not support finite interior points"
            )
        # Use interior points so a source-reported boundary is never treated as
        # experimentally admissible merely because the minimal card stores a
        # finite interval without endpoint-inclusion metadata.
        levels = tuple(
            lower + fraction * width
            for fraction in (0.1, 0.3, 0.5, 0.7, 0.9)
        )
        if any(not math.isfinite(value) for value in levels):
            raise TemporalCaseConstructionError(
                "continuous control domain does not support finite interior points"
            )
        return levels
    values = tuple(sorted(float(value) for value in domain.allowed_values))
    if len(values) < 2:
        raise TemporalCaseConstructionError(
            "enumerated control domain requires at least two values"
        )
    return values


def deterministic_condition_design(
    relation: MinimalQuantitativeRelation,
    *,
    maximum_hidden_count: int = 3,
    minimum_diagnostic_count: int = 1,
) -> Tuple[Tuple[Mapping[str, float], ...], Tuple[Mapping[str, float], ...]]:
    """Create a compact diagnostic design and disjoint held-out points."""

    if (
        isinstance(maximum_hidden_count, bool)
        or not isinstance(maximum_hidden_count, int)
        or maximum_hidden_count < 1
    ):
        raise ValueError("maximum_hidden_count must be a positive integer")
    if (
        isinstance(minimum_diagnostic_count, bool)
        or not isinstance(minimum_diagnostic_count, int)
        or minimum_diagnostic_count < 1
    ):
        raise ValueError("minimum_diagnostic_count must be a positive integer")
    domains = {item.control_name: item for item in relation.domain.controls}
    control_names = tuple(item.name for item in relation.controls)
    levels = {name: _domain_levels(domains[name]) for name in control_names}

    lower = {name: levels[name][0] for name in control_names}
    diagnostic = [lower]
    for name in control_names:
        condition = dict(lower)
        condition[name] = levels[name][-1]
        diagnostic.append(condition)

    target_diagnostic_count = max(
        len(diagnostic),
        minimum_diagnostic_count,
    )

    diagnostic_keys = {
        _condition_key(item, control_names) for item in diagnostic
    }
    candidates = []

    def add_candidate(values: Sequence[float]) -> None:
        condition = dict(zip(control_names, values))
        key = _condition_key(condition, control_names)
        if key not in diagnostic_keys and all(
            _condition_key(item, control_names) != key for item in candidates
        ):
            candidates.append(condition)

    add_candidate([levels[name][len(levels[name]) // 2] for name in control_names])
    add_candidate([levels[name][-1] for name in control_names])
    add_candidate([levels[name][max(0, (len(levels[name]) - 1) // 3)] for name in control_names])
    add_candidate([levels[name][min(len(levels[name]) - 1, 2 * (len(levels[name]) - 1) // 3)] for name in control_names])
    required_candidate_count = (
        target_diagnostic_count - len(diagnostic) + maximum_hidden_count
    )
    for values in itertools.product(*(levels[name] for name in control_names)):
        add_candidate(values)
        if len(candidates) >= required_candidate_count:
            break

    promoted_count = target_diagnostic_count - len(diagnostic)
    if len(candidates) <= promoted_count:
        raise TemporalCaseConstructionError(
            "the source-supported Cartesian domain has no held-out condition "
            "after allocating the minimum diagnostic observations required "
            "for Identification"
        )
    diagnostic.extend(candidates[:promoted_count])
    hidden = tuple(candidates[promoted_count:][:maximum_hidden_count])
    if not hidden:
        raise TemporalCaseConstructionError(
            "the source-supported domain has no held-out condition disjoint "
            "from the diagnostic design"
        )
    return tuple(diagnostic), hidden


def _anchor_payload(anchor: MinimalAnchor) -> Mapping[str, int]:
    return {"line_start": anchor.line_start, "line_end": anchor.line_end}


def build_temporal_provenance_mapping(
    card: MinimalScienceCard,
) -> Mapping[str, Any]:
    """Map compiled fields to line ranges or registered deterministic policy."""

    if len(card.relations) != 1:
        raise TemporalCaseConstructionError(
            "provenance mapping requires one admitted relation"
        )
    relation = card.relations[0]
    mappings = [
        {
            "field": "oracle.formula",
            "origin": "source",
            "line_ranges": [_anchor_payload(item) for item in relation.anchors],
        }
    ]
    for field, values, name_field in (
        ("oracle.parameters", relation.parameters, "name"),
        ("public.controls", relation.controls, "name"),
        ("public.readouts", relation.readouts, "name"),
        ("public.domain", relation.domain.controls, "control_name"),
    ):
        for item in values:
            name = getattr(item, name_field)
            mappings.append(
                {
                    "field": "%s.%s" % (field, _canonical_name(name)),
                    "origin": "source",
                    "line_ranges": [
                        _anchor_payload(anchor) for anchor in item.anchors
                    ],
                }
            )
    for index, item in enumerate(relation.domain.applicability):
        mappings.append(
            {
                "field": "oracle.applicability.%d" % index,
                "origin": "source",
                "line_ranges": [
                    _anchor_payload(anchor) for anchor in item.anchors
                ],
            }
        )
    for field in (
        "case.family",
        "case.title",
        "case.background",
        "case.initial_observations",
        "design.budget",
        "design.diagnostic_conditions",
        "design.hidden_conditions",
        "design.max_replicates",
        "evaluation.confidence_threshold",
        "evaluation.relative_tolerance",
    ):
        mappings.append(
            {"field": field, "origin": "deterministic_code", "line_ranges": []}
        )
    mappings.append(
        {
            "field": "public.identification_formula",
            "origin": "source",
            "line_ranges": [
                _anchor_payload(item) for item in relation.anchors
            ],
        }
    )
    return {
        "schema": TEMPORAL_PROVENANCE_SCHEMA,
        "source": {
            "citation": card.source.citation,
            "journal_doi": card.source.journal_doi,
            "arxiv_versioned_id": card.source.arxiv_versioned_id,
        },
        "mappings": mappings,
    }


def _matrix_rank(matrix: Sequence[Sequence[float]], tolerance: float) -> int:
    """Return the numerical row rank using scaled Gaussian elimination."""

    if not matrix:
        return 0
    work = [list(map(float, row)) for row in matrix]
    row_count = len(work)
    column_count = len(work[0])
    rank = 0
    for column in range(column_count):
        pivot = max(
            range(rank, row_count),
            key=lambda row: abs(work[row][column]),
        )
        if abs(work[pivot][column]) <= tolerance:
            continue
        work[rank], work[pivot] = work[pivot], work[rank]
        pivot_value = work[rank][column]
        work[rank] = [value / pivot_value for value in work[rank]]
        for row in range(row_count):
            if row == rank:
                continue
            factor = work[row][column]
            if abs(factor) <= tolerance:
                continue
            work[row] = [
                value - factor * pivot_item
                for value, pivot_item in zip(work[row], work[rank])
            ]
        rank += 1
        if rank == row_count:
            break
    return rank


def _validate_local_identifiability(
    predict: Any,
    parameter_values: Mapping[str, float],
    diagnostic_conditions: Sequence[Mapping[str, float]],
    readout_names: Sequence[str],
) -> None:
    """Require full local sensitivity rank within the public experiment budget."""

    parameter_names = tuple(parameter_values)
    if not parameter_names:
        raise TemporalCaseConstructionError(
            "a parameter-free relation supports Discovery but not the required "
            "Identification task setting"
        )
    observation_count = len(diagnostic_conditions) * len(readout_names)
    if len(parameter_names) > observation_count:
        raise TemporalCaseConstructionError(
            "the deterministic diagnostic design has fewer observations than "
            "identification parameters"
        )
    try:
        baseline = [
            float(predict(parameter_values, condition)[readout])
            for condition in diagnostic_conditions
            for readout in readout_names
        ]
    except (ArithmeticError, OverflowError, TypeError, ValueError) as exc:
        raise TemporalCaseConstructionError(
            "the identification model is not evaluable on the deterministic "
            "diagnostic design"
        ) from exc
    columns = []
    for name in parameter_names:
        value = float(parameter_values[name])
        step = 1.0e-6 * max(1.0, abs(value))
        lower = dict(parameter_values)
        upper = dict(parameter_values)
        lower[name] = value - step
        upper[name] = value + step
        try:
            upper_response = [
                float(predict(upper, condition)[readout])
                for condition in diagnostic_conditions
                for readout in readout_names
            ]
            lower_response = [
                float(predict(lower, condition)[readout])
                for condition in diagnostic_conditions
                for readout in readout_names
            ]
            response = [
                (upper_value - lower_value)
                / (2.0 * max(1.0, abs(reference)))
                for upper_value, lower_value, reference in zip(
                    upper_response, lower_response, baseline
                )
            ]
        except (ArithmeticError, OverflowError, TypeError, ValueError) as exc:
            raise TemporalCaseConstructionError(
                "the identification model is not locally evaluable at the "
                "source-reported parameter values"
            ) from exc
        scale = max(abs(item) for item in response)
        if not math.isfinite(scale) or scale <= 1.0e-10:
            raise TemporalCaseConstructionError(
                "an identification parameter has no measurable local effect "
                "under the deterministic diagnostic design"
            )
        columns.append([item / scale for item in response])
    matrix = [list(row) for row in zip(*columns)]
    if _matrix_rank(matrix, tolerance=1.0e-7) != len(parameter_names):
        raise TemporalCaseConstructionError(
            "the identification parameters are not locally identifiable under "
            "the deterministic diagnostic design"
        )


def compile_temporal_source_case(
    admission: TemporalAdmissionResult,
    *,
    case_index: int,
    maximum_hidden_count: int = 3,
) -> TemporalSourceCaseBuild:
    """Compile a reviewed single relation without any LLM authoring call."""

    if not isinstance(admission, TemporalAdmissionResult):
        raise TypeError("admission must be a TemporalAdmissionResult")
    if not admission.admitted or admission.card is None:
        raise TemporalCaseConstructionError(
            "case construction requires an eligible independent source review"
        )
    card = admission.card
    if len(card.relations) != 1:
        raise TemporalCaseConstructionError(
            "Temporal admission requires one source-supported executable relation"
        )
    if (
        isinstance(case_index, bool)
        or not isinstance(case_index, int)
        or case_index < 1
    ):
        raise ValueError("case_index must be a positive integer")
    relation = card.relations[0]
    parameter_count = len(relation.parameters)
    readout_count = len(relation.readouts)
    minimum_diagnostic_count = max(
        1,
        math.ceil(parameter_count / readout_count),
    )
    source_diagnostics, source_hidden = deterministic_condition_design(
        relation,
        maximum_hidden_count=maximum_hidden_count,
        minimum_diagnostic_count=minimum_diagnostic_count,
    )
    diagnostics = tuple(
        {_canonical_name(name): value for name, value in condition.items()}
        for condition in source_diagnostics
    )
    hidden = tuple(
        {_canonical_name(name): value for name, value in condition.items()}
        for condition in source_hidden
    )
    parameter_values = {
        _canonical_name(item.name): float(item.value)
        for item in relation.parameters
    }
    template = {
        _canonical_name(name): _canonical_expression(expression)
        for name, expression in relation.formula.items()
    }
    discovery_outputs = materialize_outputs(template, parameter_values)
    control_names = tuple(_canonical_name(item.name) for item in relation.controls)
    readout_names = tuple(_canonical_name(item.name) for item in relation.readouts)

    def predict(
        parameters: Mapping[str, float],
        controls: Mapping[str, Any],
    ) -> Mapping[str, float]:
        return evaluate_expression_program(
            {"outputs": materialize_outputs(template, parameters)},
            controls,
            allowed_variables=control_names,
            required_outputs=readout_names,
        )

    _validate_local_identifiability(
        predict,
        parameter_values,
        diagnostics,
        readout_names,
    )

    domains = {
        _canonical_name(item.control_name): item
        for item in relation.domain.controls
    }
    controls = tuple(
        ControlSpec(
            name=_canonical_name(item.name),
            description="Numeric experimental control %s." % _canonical_name(item.name),
            unit=item.unit,
            minimum=(
                _domain_levels(domains[_canonical_name(item.name)])[0]
                if domains[_canonical_name(item.name)].domain_kind
                == "continuous_interval"
                else None
            ),
            maximum=(
                _domain_levels(domains[_canonical_name(item.name)])[-1]
                if domains[_canonical_name(item.name)].domain_kind
                == "continuous_interval"
                else None
            ),
            allowed_values=domains[_canonical_name(item.name)].allowed_values,
        )
        for item in relation.controls
    )
    try:
        validate_materialized_outputs_totality(discovery_outputs, controls)
    except ValueError as exc:
        raise TemporalCaseConstructionError(
            "the source relation is not total on the public query domain: %s" % exc
        ) from exc
    readouts = tuple(
        ReadoutSpec(
            name=_canonical_name(item.name),
            description="Numeric experimental readout %s." % _canonical_name(item.name),
            unit=item.unit,
            resolution=None,
            statistic="deterministic central value",
            uncertainty="not applicable to the deterministic Oracle",
            resolution_kind="",
        )
        for item in relation.readouts
    )
    parameter_specs = tuple(
        IdentificationParameterSpec(
            name=_canonical_name(item.name),
            description="Scalar parameter in the public quantitative model.",
            unit=item.unit,
        )
        for item in relation.parameters
    )
    identification_formula = json.dumps(
        {"outputs": template},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    family = "temporal_source_%03d" % case_index
    applicability = tuple(item.statement for item in relation.domain.applicability)
    spec = SourceFamilySpec(
        family=family,
        case_id_prefix="temporal.%s" % family,
        response_title="the quantitative response",
        apparatus_name="measurement_system",
        apparatus_description=(
            "A deterministic interface exposing the listed controls and readouts."
        ),
        background=(
            "Determine a quantitative relation between the listed controls and "
            "readouts within the stated applicability conditions."
        ),
        initial_observations=(
            "Only experiments within the declared control domain are valid.",
        ),
        controls=controls,
        readouts=readouts,
        identification_model="parametric_equation",
        identification_parameter_specs=parameter_specs,
        identification_formula="Expression template: " + identification_formula,
        model_outputs=template,
        predict=predict,
        identification_predict=predict,
        truth=MatchedTruth(
            parameters=parameter_values,
            identification_values=parameter_values,
            discovery_outputs=discovery_outputs,
            applicability=applicability,
            fixed_conditions=applicability,
        ),
        diagnostic_conditions=tuple(
            {
                _canonical_name(name): float(value)
                for name, value in condition.items()
            }
            for condition in diagnostics
        ),
        hidden_conditions=tuple(
            {
                _canonical_name(name): float(value)
                for name, value in condition.items()
            }
            for condition in hidden
        ),
        credits=(
            SourceCredit(
                citation=card.source.citation,
                url="https://doi.org/%s" % card.source.journal_doi,
                role=(
                    "Source of the reviewed quantitative relation; fixed arXiv "
                    "version %s." % card.source.arxiv_versioned_id
                ),
            ),
        ),
        common_notes=(
            "The benchmark Oracle evaluates the reviewed central relation "
            "deterministically within its source-supported domain.",
        ),
        common_fixed_conditions=(
            "All non-queryable conditions remain fixed at the source-reviewed setting.",
        ),
        budget=len(diagnostics),
        max_replicates=1,
        confidence_threshold=0.90,
        relative_tolerance=0.05,
    )
    return TemporalSourceCaseBuild(
        spec=spec,
        provenance=build_temporal_provenance_mapping(card),
    )


def render_temporal_source_case_module(
    admission: TemporalAdmissionResult,
    *,
    case_index: int,
) -> str:
    """Render a deterministic module that reconstructs the reviewed case."""

    build = compile_temporal_source_case(admission, case_index=case_index)
    if admission.card is None:  # Guard the admitted-result invariant.
        raise AssertionError("admitted result is missing its ScienceCard")
    card = admission.card
    payload = json.dumps(
        minimal_science_card_to_payload(card),
        ensure_ascii=False,
        indent=4,
        sort_keys=True,
    )
    review_payload = json.dumps(
        temporal_admission_review_to_payload(admission.review),
        ensure_ascii=False,
        indent=4,
        sort_keys=True,
    )
    constant = build.spec.family.upper() + "_SPEC"
    provenance_constant = build.spec.family.upper() + "_PROVENANCE"
    factory = "make_%s_case" % build.spec.family
    return '''"""Generated source-reported Temporal benchmark case."""

import json

from role_benchmark.cases.source import make_source_case
from role_benchmark.models import BenchmarkTrack
from role_benchmark.temporal.admission import assess_temporal_admission, parse_temporal_admission_review_payload
from role_benchmark.temporal.minimal_science_card import parse_minimal_science_card_payload
from role_benchmark.temporal.source_case import compile_temporal_source_case


_CARD = parse_minimal_science_card_payload(json.loads(%r))
_REVIEW = parse_temporal_admission_review_payload(json.loads(%r))
_ADMISSION = assess_temporal_admission(
    _CARD,
    _REVIEW,
    paper_id=%r,
    source_line_count=%d,
)
_BUILD = compile_temporal_source_case(_ADMISSION, case_index=%d)
%s = _BUILD.spec
%s = _BUILD.provenance


def %s(track=BenchmarkTrack.IDENTIFICATION):
    return make_source_case(%s, track)


__all__ = ["%s", "%s", "%s"]
''' % (
        payload,
        review_payload,
        admission.paper_id,
        admission.source_line_count,
        case_index,
        constant,
        provenance_constant,
        factory,
        constant,
        constant,
        provenance_constant,
        factory,
    )


def write_temporal_source_case_module(
    admission: TemporalAdmissionResult,
    path: Union[str, Path],
    *,
    case_index: int,
) -> Path:
    output = Path(path)
    if output.suffix.lower() != ".py":
        raise ValueError("generated case path must end in .py")
    rendered = render_temporal_source_case_module(admission, case_index=case_index)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(rendered, encoding="utf-8")
    return output


__all__ = [
    "TEMPORAL_PROVENANCE_SCHEMA",
    "TemporalCaseConstructionError",
    "TemporalSourceCaseBuild",
    "build_temporal_provenance_mapping",
    "compile_temporal_source_case",
    "deterministic_condition_design",
    "render_temporal_source_case_module",
    "write_temporal_source_case_module",
]
