"""Second LLM stage: author a matched-case draft from a private science card."""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, replace
from itertools import product
from typing import Any, Dict, Mapping, Optional, Tuple

from role_benchmark.expression import ExpressionError, evaluate_expression_program
from role_benchmark.llm import (
    GenerationConfig,
    GenerationRequest,
    GenerationResponse,
    Message,
    TextGenerationBackend,
)
from role_benchmark.wire import canonical_json_dumps

from .candidate import (
    TemporalCaseCandidate,
    TemporalControl,
    TemporalFixedCondition,
    candidate_to_payload,
    parse_candidate_payload,
    temporal_candidate_json_schema,
)
from .filter import materialize_outputs
from .science_card import (
    ScienceCard,
    ScienceCardError,
    canonical_science_name,
    parse_science_card_payload,
    science_card_to_payload,
)


_IDENTIFIER = re.compile(r"^[a-z][a-z0-9_]*$")
_SOURCE_IDENTIFIER = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")
_DIRECTIONS = {
    "increasing",
    "decreasing",
    "non_increasing",
    "non_decreasing",
    "approximately_invariant",
    "non_monotonic",
    "source_defined",
}
_CANONICAL_RELATIONSHIP_SHAPES = {
    "increasing": "Strictly increasing over the declared control domain.",
    "decreasing": "Strictly decreasing over the declared control domain.",
    "non_increasing": (
        "Non-increasing over the declared control domain, with possible plateaus."
    ),
    "non_decreasing": (
        "Non-decreasing over the declared control domain, with possible plateaus."
    ),
    "approximately_invariant": (
        "Approximately invariant over the declared control domain."
    ),
    "non_monotonic": "Non-monotonic over the declared control domain.",
    "source_defined": "Source-defined relation over the declared control domain.",
}
_COUNTERFACTUAL_KINDS = {
    "reported_regime_selection",
    "benchmark_authored_parameter_substitution",
}

# These strings describe the executable benchmark interface, not a new sample
# from the paper's experiment.  Source aggregation, error bars, and fit
# uncertainty remain in the private science card as provenance.
EXECUTABLE_ORACLE_STATISTIC = (
    "Deterministic central value of the source-reported quantitative relation."
)
EXECUTABLE_ORACLE_UNCERTAINTY = (
    "Any source-reported uncertainty is retained as provenance and is not "
    "sampled or propagated into this query."
)
RETRYABLE_CASE_DRAFT_ERROR_CODES = frozenset(
    {
        "case_draft.public_leakage",
        "case_draft.public_lineage",
        "case_draft.schema",
    }
)


class CaseDraftError(ValueError):
    def __init__(self, code: str, path: str, detail: str) -> None:
        self.code = code
        self.path = path
        self.detail = detail
        super().__init__("%s at %s: %s" % (code, path, detail))


@dataclass(frozen=True)
class LineRange:
    line_start: int
    line_end: int


@dataclass(frozen=True)
class InformationTrace:
    items: Tuple[str, ...]
    claim_ids: Tuple[str, ...]
    mechanism_ids: Tuple[str, ...]
    fixed_condition_ids: Tuple[str, ...]
    line_ranges: Tuple[LineRange, ...]


@dataclass(frozen=True)
class PublicFieldTrace:
    field: str
    claim_ids: Tuple[str, ...]
    mechanism_ids: Tuple[str, ...]
    fixed_condition_ids: Tuple[str, ...]
    line_ranges: Tuple[LineRange, ...]


@dataclass(frozen=True)
class InformationBoundary:
    shared_player: Tuple[PublicFieldTrace, ...]
    identification_only: InformationTrace
    oracle_only: InformationTrace


@dataclass(frozen=True)
class CounterfactualDerivation:
    kind: str
    description: str
    source_claim_ids: Tuple[str, ...]
    paper_claim_ids: Tuple[str, ...]
    counterfactual_claim_ids: Tuple[str, ...]
    source_mechanism_ids: Tuple[str, ...]
    selector_parameter: str
    historical_value: float
    counterfactual_value: float
    paper_defined_equations_unchanged: bool


@dataclass(frozen=True)
class RelationshipTarget:
    control: str
    readout: str
    historical_direction: str
    counterfactual_direction: str
    historical_shape: str
    counterfactual_shape: str
    source_claim_ids: Tuple[str, ...]


@dataclass(frozen=True)
class MatchedCaseDraft:
    design_summary: str
    information_boundary: InformationBoundary
    counterfactual_derivation: CounterfactualDerivation
    relationship_targets: Tuple[RelationshipTarget, ...]
    candidate: TemporalCaseCandidate


@dataclass(frozen=True)
class CaseDraftBatch:
    assessment: str
    status: str
    drafts: Tuple[MatchedCaseDraft, ...]


@dataclass(frozen=True)
class CaseDraftResult:
    batch: CaseDraftBatch
    response: GenerationResponse
    attempt_count: int = 1
    prose_normalizations: Tuple["PublicProseNormalization", ...] = ()
    relationship_direction_bindings: Tuple[
        "RelationshipDirectionBinding", ...
    ] = ()
    condition_partition_bindings: Tuple[
        "ConditionPartitionBinding", ...
    ] = ()


@dataclass(frozen=True)
class PublicProseNormalization:
    """One transparent compiler rewrite of non-scientific Player prose."""

    path: str
    original: str
    replacement: str
    reason: str = "case_draft.public_leakage"


@dataclass(frozen=True)
class RelationshipDirectionBinding:
    """One transparent replacement of model prose by Oracle-derived labels."""

    path: str
    control: str
    readout: str
    original_historical_direction: str
    bound_historical_direction: str
    original_counterfactual_direction: str
    bound_counterfactual_direction: str
    original_historical_shape: str
    bound_historical_shape: str
    original_counterfactual_shape: str
    bound_counterfactual_shape: str


@dataclass(frozen=True)
class ConditionPartitionBinding:
    """One exact compiler split of an enumerated condition partition."""

    path: str
    control: str
    allowed_values: Tuple[float, ...]
    original_diagnostic_conditions: Tuple[Mapping[str, float], ...]
    original_hidden_conditions: Tuple[Mapping[str, float], ...]
    bound_diagnostic_conditions: Tuple[Mapping[str, float], ...]
    bound_hidden_conditions: Tuple[Mapping[str, float], ...]
    reason: str = "case_draft.enumerated_condition_partition"


@dataclass(frozen=True)
class _ReviewedOracleContract:
    """Exact executable form derived from the reviewed source programs."""

    outputs: Mapping[str, Any]
    paper_parameters: Mapping[str, float]
    counterfactual_parameters: Mapping[str, float]
    compilation_kind: str


def public_prose_normalizations_to_payload(
    items: Tuple[PublicProseNormalization, ...],
) -> Mapping[str, Any]:
    """Serialize the compiler record without altering the raw LLM response."""

    return {
        "normalizations": [
            {
                "original": item.original,
                "path": item.path,
                "reason": item.reason,
                "replacement": item.replacement,
            }
            for item in items
        ]
    }


def relationship_direction_bindings_to_payload(
    items: Tuple[RelationshipDirectionBinding, ...],
) -> Mapping[str, Any]:
    return {
        "bindings": [
            {
                "bound_counterfactual_direction": (
                    item.bound_counterfactual_direction
                ),
                "bound_historical_direction": item.bound_historical_direction,
                "bound_counterfactual_shape": item.bound_counterfactual_shape,
                "bound_historical_shape": item.bound_historical_shape,
                "control": item.control,
                "original_counterfactual_direction": (
                    item.original_counterfactual_direction
                ),
                "original_historical_direction": (
                    item.original_historical_direction
                ),
                "original_counterfactual_shape": (
                    item.original_counterfactual_shape
                ),
                "original_historical_shape": item.original_historical_shape,
                "path": item.path,
                "readout": item.readout,
            }
            for item in items
        ]
    }


def condition_partition_bindings_to_payload(
    items: Tuple[ConditionPartitionBinding, ...],
) -> Mapping[str, Any]:
    """Serialize enough state to replay each deterministic held-out split."""

    def conditions_payload(
        conditions: Tuple[Mapping[str, float], ...],
    ) -> list[Mapping[str, float]]:
        return [dict(condition) for condition in conditions]

    return {
        "bindings": [
            {
                "allowed_values": list(item.allowed_values),
                "bound_diagnostic_conditions": conditions_payload(
                    item.bound_diagnostic_conditions
                ),
                "bound_hidden_conditions": conditions_payload(
                    item.bound_hidden_conditions
                ),
                "control": item.control,
                "original_diagnostic_conditions": conditions_payload(
                    item.original_diagnostic_conditions
                ),
                "original_hidden_conditions": conditions_payload(
                    item.original_hidden_conditions
                ),
                "path": item.path,
                "reason": item.reason,
            }
            for item in items
        ]
    }


def _error(path: str, detail: str, code: str = "case_draft.schema") -> None:
    raise CaseDraftError(code, path, detail)


def _object(value: Any, path: str, keys: set[str]) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        _error(path, "must be an object")
    if set(value) != keys:
        _error(
            path,
            "keys must match exactly (missing=%s, extra=%s)"
            % (sorted(keys - set(value)), sorted(set(value) - keys)),
        )
    return value


def _array(value: Any, path: str) -> list[Any]:
    if not isinstance(value, list):
        _error(path, "must be an array")
    return value


def _text(value: Any, path: str) -> str:
    if not isinstance(value, str) or not value.strip():
        _error(path, "must be non-empty text")
    return value.strip()


def _identifier(value: Any, path: str) -> str:
    result = _text(value, path)
    if _IDENTIFIER.fullmatch(result) is None:
        _error(path, "must be lower_snake_case")
    return result


def _source_identifier(value: Any, path: str) -> str:
    result = _text(value, path)
    if _SOURCE_IDENTIFIER.fullmatch(result) is None:
        _error(path, "must be an ASCII snake-style science-card identifier")
    return result


def _number(value: Any, path: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        _error(path, "must be a number")
    result = float(value)
    if not math.isfinite(result):
        _error(path, "must be finite")
    return result


def _selector_value(value: Any, path: str) -> float:
    result = _number(value, path)
    if result not in {0.0, 1.0}:
        _error(path, "must be one of the benchmark-only selector values 0.0 or 1.0")
    return result


def _bool(value: Any, path: str) -> bool:
    if not isinstance(value, bool):
        _error(path, "must be a boolean")
    return value


def _text_array(value: Any, path: str) -> Tuple[str, ...]:
    return tuple(
        _text(item, "%s[%d]" % (path, index))
        for index, item in enumerate(_array(value, path))
    )


def _source_identifier_array(value: Any, path: str) -> Tuple[str, ...]:
    result = tuple(
        _source_identifier(item, "%s[%d]" % (path, index))
        for index, item in enumerate(_array(value, path))
    )
    if len(set(result)) != len(result):
        _error(path, "must not contain duplicates")
    return result


def _line_ranges(value: Any, path: str) -> Tuple[LineRange, ...]:
    result = []
    for index, raw in enumerate(_array(value, path)):
        item_path = "%s[%d]" % (path, index)
        item = _object(raw, item_path, {"line_start", "line_end"})
        start = item["line_start"]
        end = item["line_end"]
        if (
            isinstance(start, bool)
            or not isinstance(start, int)
            or isinstance(end, bool)
            or not isinstance(end, int)
            or start < 1
            or end < start
        ):
            _error(item_path, "must satisfy 1 <= line_start <= line_end")
        result.append(LineRange(start, end))
    return tuple(result)


def _trace(value: Any, path: str) -> InformationTrace:
    item = _object(
        value,
        path,
        {
            "items",
            "claim_ids",
            "mechanism_ids",
            "fixed_condition_ids",
            "line_ranges",
        },
    )
    items = _text_array(item["items"], path + ".items")
    if not items:
        _error(path + ".items", "must contain at least one information item")
    return InformationTrace(
        items=items,
        claim_ids=_source_identifier_array(item["claim_ids"], path + ".claim_ids"),
        mechanism_ids=_source_identifier_array(
            item["mechanism_ids"], path + ".mechanism_ids"
        ),
        fixed_condition_ids=_source_identifier_array(
            item["fixed_condition_ids"], path + ".fixed_condition_ids"
        ),
        line_ranges=_line_ranges(item["line_ranges"], path + ".line_ranges"),
    )


def _public_field_traces(
    value: Any, path: str
) -> Tuple[PublicFieldTrace, ...]:
    traces = []
    for index, raw in enumerate(_array(value, path)):
        item_path = "%s[%d]" % (path, index)
        item = _object(
            raw,
            item_path,
            {
                "field",
                "claim_ids",
                "mechanism_ids",
                "fixed_condition_ids",
                "line_ranges",
            },
        )
        traces.append(
            PublicFieldTrace(
                field=_text(item["field"], item_path + ".field"),
                claim_ids=_source_identifier_array(
                    item["claim_ids"], item_path + ".claim_ids"
                ),
                mechanism_ids=_source_identifier_array(
                    item["mechanism_ids"], item_path + ".mechanism_ids"
                ),
                fixed_condition_ids=_source_identifier_array(
                    item["fixed_condition_ids"],
                    item_path + ".fixed_condition_ids",
                ),
                line_ranges=_line_ranges(
                    item["line_ranges"], item_path + ".line_ranges"
                ),
            )
        )
    if not traces:
        _error(path, "must contain one trace for every Player-visible field")
    fields = [item.field for item in traces]
    if len(set(fields)) != len(fields):
        _error(path, "field values must be unique")
    return tuple(traces)


def _decode_json(text: str) -> Any:
    if not isinstance(text, str):
        _error("$", "input must be text", "case_draft.invalid_json")

    def reject_constant(value: str) -> None:
        raise ValueError("non-finite JSON constant %s" % value)

    def unique_object(pairs: Any) -> Dict[str, Any]:
        result: Dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate object key")
            result[key] = value
        return result

    try:
        return json.loads(
            text,
            parse_constant=reject_constant,
            object_pairs_hook=unique_object,
        )
    except (json.JSONDecodeError, ValueError) as exc:
        raise CaseDraftError(
            "case_draft.invalid_json",
            "$",
            "expected exactly one strict JSON value",
        ) from exc


def _parse_draft(value: Any, path: str) -> MatchedCaseDraft:
    item = _object(
        value,
        path,
        {
            "design_summary",
            "information_boundary",
            "counterfactual_derivation",
            "relationship_targets",
            "candidate",
        },
    )
    boundary_raw = _object(
        item["information_boundary"],
        path + ".information_boundary",
        {"shared_player", "identification_only", "oracle_only"},
    )
    derivation_raw = _object(
        item["counterfactual_derivation"],
        path + ".counterfactual_derivation",
        {
            "kind",
            "description",
            "source_claim_ids",
            "paper_claim_ids",
            "counterfactual_claim_ids",
            "source_mechanism_ids",
            "selector_parameter",
            "historical_value",
            "counterfactual_value",
            "paper_defined_equations_unchanged",
        },
    )
    kind = _text(
        derivation_raw["kind"], path + ".counterfactual_derivation.kind"
    )
    if kind not in _COUNTERFACTUAL_KINDS:
        _error(
            path + ".counterfactual_derivation.kind",
            "unsupported counterfactual kind",
        )

    targets = []
    for index, raw in enumerate(
        _array(item["relationship_targets"], path + ".relationship_targets")
    ):
        target_path = "%s.relationship_targets[%d]" % (path, index)
        target = _object(
            raw,
            target_path,
            {
                "control",
                "readout",
                "historical_direction",
                "counterfactual_direction",
                "historical_shape",
                "counterfactual_shape",
                "source_claim_ids",
            },
        )
        historical_direction = _text(
            target["historical_direction"], target_path + ".historical_direction"
        )
        counterfactual_direction = _text(
            target["counterfactual_direction"],
            target_path + ".counterfactual_direction",
        )
        if historical_direction not in _DIRECTIONS:
            _error(target_path + ".historical_direction", "unsupported direction")
        if counterfactual_direction not in _DIRECTIONS:
            _error(target_path + ".counterfactual_direction", "unsupported direction")
        targets.append(
            RelationshipTarget(
                control=_identifier(target["control"], target_path + ".control"),
                readout=_identifier(target["readout"], target_path + ".readout"),
                historical_direction=historical_direction,
                counterfactual_direction=counterfactual_direction,
                historical_shape=_text(
                    target["historical_shape"], target_path + ".historical_shape"
                ),
                counterfactual_shape=_text(
                    target["counterfactual_shape"],
                    target_path + ".counterfactual_shape",
                ),
                source_claim_ids=_source_identifier_array(
                    target["source_claim_ids"], target_path + ".source_claim_ids"
                ),
            )
        )
    if not targets:
        _error(path + ".relationship_targets", "must contain at least one target")

    try:
        candidate = parse_candidate_payload(item["candidate"])
    except ValueError as exc:
        _error(path + ".candidate", str(exc))

    return MatchedCaseDraft(
        design_summary=_text(item["design_summary"], path + ".design_summary"),
        information_boundary=InformationBoundary(
            shared_player=_public_field_traces(
                boundary_raw["shared_player"],
                path + ".information_boundary.shared_player",
            ),
            identification_only=_trace(
                boundary_raw["identification_only"],
                path + ".information_boundary.identification_only",
            ),
            oracle_only=_trace(
                boundary_raw["oracle_only"],
                path + ".information_boundary.oracle_only",
            ),
        ),
        counterfactual_derivation=CounterfactualDerivation(
            kind=kind,
            description=_text(
                derivation_raw["description"],
                path + ".counterfactual_derivation.description",
            ),
            source_claim_ids=_source_identifier_array(
                derivation_raw["source_claim_ids"],
                path + ".counterfactual_derivation.source_claim_ids",
            ),
            paper_claim_ids=_source_identifier_array(
                derivation_raw["paper_claim_ids"],
                path + ".counterfactual_derivation.paper_claim_ids",
            ),
            counterfactual_claim_ids=_source_identifier_array(
                derivation_raw["counterfactual_claim_ids"],
                path + ".counterfactual_derivation.counterfactual_claim_ids",
            ),
            source_mechanism_ids=_source_identifier_array(
                derivation_raw["source_mechanism_ids"],
                path + ".counterfactual_derivation.source_mechanism_ids",
            ),
            selector_parameter=_identifier(
                derivation_raw["selector_parameter"],
                path + ".counterfactual_derivation.selector_parameter",
            ),
            historical_value=_selector_value(
                derivation_raw["historical_value"],
                path + ".counterfactual_derivation.historical_value",
            ),
            counterfactual_value=_selector_value(
                derivation_raw["counterfactual_value"],
                path + ".counterfactual_derivation.counterfactual_value",
            ),
            paper_defined_equations_unchanged=_bool(
                derivation_raw["paper_defined_equations_unchanged"],
                path
                + ".counterfactual_derivation.paper_defined_equations_unchanged",
            ),
        ),
        relationship_targets=tuple(targets),
        candidate=candidate,
    )


def parse_case_draft_batch_payload(payload: Any) -> CaseDraftBatch:
    root = _object(payload, "$", {"assessment", "status", "drafts"})
    status = _text(root["status"], "$.status")
    if status not in {"authored", "not_authorable"}:
        _error("$.status", "must be authored or not_authorable")
    drafts = tuple(
        _parse_draft(item, "$.drafts[%d]" % index)
        for index, item in enumerate(_array(root["drafts"], "$.drafts"))
    )
    if status == "authored" and len(drafts) != 1:
        _error("$.drafts", "authored status requires exactly one draft")
    if status == "not_authorable" and drafts:
        _error("$.drafts", "not_authorable status requires an empty draft list")
    return CaseDraftBatch(
        assessment=_text(root["assessment"], "$.assessment"),
        status=status,
        drafts=drafts,
    )


def parse_case_draft_batch_json(text: str) -> CaseDraftBatch:
    return parse_case_draft_batch_payload(_decode_json(text))


def _line_range_payload(item: LineRange) -> Mapping[str, Any]:
    return {"line_start": item.line_start, "line_end": item.line_end}


def _trace_payload(trace: InformationTrace) -> Mapping[str, Any]:
    return {
        "items": list(trace.items),
        "claim_ids": list(trace.claim_ids),
        "mechanism_ids": list(trace.mechanism_ids),
        "fixed_condition_ids": list(trace.fixed_condition_ids),
        "line_ranges": [_line_range_payload(item) for item in trace.line_ranges],
    }


def _public_field_trace_payload(trace: PublicFieldTrace) -> Mapping[str, Any]:
    return {
        "field": trace.field,
        "claim_ids": list(trace.claim_ids),
        "mechanism_ids": list(trace.mechanism_ids),
        "fixed_condition_ids": list(trace.fixed_condition_ids),
        "line_ranges": [_line_range_payload(item) for item in trace.line_ranges],
    }


def case_draft_to_payload(draft: MatchedCaseDraft) -> Mapping[str, Any]:
    return {
                "design_summary": draft.design_summary,
                "information_boundary": {
                    "shared_player": [
                        _public_field_trace_payload(item)
                        for item in draft.information_boundary.shared_player
                    ],
                    "identification_only": _trace_payload(
                        draft.information_boundary.identification_only
                    ),
                    "oracle_only": _trace_payload(
                        draft.information_boundary.oracle_only
                    ),
                },
                "counterfactual_derivation": {
                    "kind": draft.counterfactual_derivation.kind,
                    "description": draft.counterfactual_derivation.description,
                    "source_claim_ids": list(
                        draft.counterfactual_derivation.source_claim_ids
                    ),
                    "paper_claim_ids": list(
                        draft.counterfactual_derivation.paper_claim_ids
                    ),
                    "counterfactual_claim_ids": list(
                        draft.counterfactual_derivation.counterfactual_claim_ids
                    ),
                    "source_mechanism_ids": list(
                        draft.counterfactual_derivation.source_mechanism_ids
                    ),
                    "selector_parameter": draft.counterfactual_derivation.selector_parameter,
                    "historical_value": draft.counterfactual_derivation.historical_value,
                    "counterfactual_value": draft.counterfactual_derivation.counterfactual_value,
                    "paper_defined_equations_unchanged": draft.counterfactual_derivation.paper_defined_equations_unchanged,
                },
                "relationship_targets": [
                    {
                        "control": target.control,
                        "readout": target.readout,
                        "historical_direction": target.historical_direction,
                        "counterfactual_direction": target.counterfactual_direction,
                        "historical_shape": target.historical_shape,
                        "counterfactual_shape": target.counterfactual_shape,
                        "source_claim_ids": list(target.source_claim_ids),
                    }
                    for target in draft.relationship_targets
                ],
                "candidate": candidate_to_payload(draft.candidate),
    }


def case_draft_batch_to_payload(batch: CaseDraftBatch) -> Mapping[str, Any]:
    return {
        "assessment": batch.assessment,
        "status": batch.status,
        "drafts": [case_draft_to_payload(draft) for draft in batch.drafts],
    }


def _card_anchor_pairs(card: ScienceCard) -> set[Tuple[int, int]]:
    pairs: set[Tuple[int, int]] = set()

    def add(anchors: Any) -> None:
        pairs.update((item.line_start, item.line_end) for item in anchors)

    for mechanism in card.mechanisms:
        add(mechanism.anchors)
        for parameter in mechanism.parameters:
            add(parameter.anchors)
    for collection in (
        card.fixed_conditions,
        card.controls,
        card.readouts,
        card.claims,
        card.source_ambiguities,
    ):
        for item in collection:
            add(item.anchors)
    return pairs


def _literal_numbers(expression: Any) -> Tuple[float, ...]:
    if isinstance(expression, (int, float)) and not isinstance(expression, bool):
        return (float(expression),)
    if "var" in expression or "param" in expression:
        return ()
    result = []
    for argument in expression["args"]:
        result.extend(_literal_numbers(argument))
    return tuple(result)


def _canonical_claim_expression(expression: Any) -> Any:
    """Translate one reviewed card expression into runtime coordinates."""

    if isinstance(expression, (int, float)) and not isinstance(expression, bool):
        return float(expression)
    if "var" in expression:
        return {"var": canonical_science_name(expression["var"])}
    if "param" in expression:
        return {"param": canonical_science_name(expression["param"])}
    return {
        "op": expression["op"],
        "args": [
            _canonical_claim_expression(argument)
            for argument in expression["args"]
        ],
    }


def _expression_parameter_names(expression: Any) -> set[str]:
    if isinstance(expression, (int, float)) and not isinstance(expression, bool):
        return set()
    if "var" in expression:
        return set()
    if "param" in expression:
        return {expression["param"]}
    result: set[str] = set()
    for argument in expression["args"]:
        result.update(_expression_parameter_names(argument))
    return result


def _merge_claim_outputs(
    claims: Tuple[Any, ...],
    *,
    path: str,
) -> Mapping[str, Any]:
    outputs: Dict[str, Any] = {}
    for claim in claims:
        assert claim.oracle_outputs is not None
        for source_name, expression in claim.oracle_outputs.items():
            name = canonical_science_name(source_name)
            if name in outputs:
                _error(
                    path,
                    "more than one selected claim defines readout %s" % name,
                    "case_draft.source_fidelity",
                )
            outputs[name] = _canonical_claim_expression(expression)
    return outputs


def _selector_weight(selector: str, active_value: float) -> Mapping[str, Any]:
    selector_node: Mapping[str, Any] = {"param": selector}
    if active_value == 1.0:
        return selector_node
    return {
        "op": "subtract",
        "args": [1.0, selector_node],
    }


def _weighted_expression(weight: Mapping[str, Any], expression: Any) -> Mapping[str, Any]:
    # Multiplication is variadic in the shared grammar.  Flattening one leading
    # multiply gives every reviewed formula one canonical compiled shape.
    arguments = (
        [weight, *expression["args"]]
        if isinstance(expression, Mapping)
        and expression.get("op") == "multiply"
        else [weight, expression]
    )
    return {"op": "multiply", "args": arguments}


def _direct_branch_parameter_contract(
    paper_outputs: Mapping[str, Any],
    counterfactual_outputs: Mapping[str, Any],
    *,
    source_parameters: Mapping[str, float],
) -> Optional[
    Tuple[Mapping[str, Any], Mapping[str, float], Mapping[str, float]]
]:
    """Compile one common source AST with one branch-varying source leaf.

    This is deliberately syntactic.  Operators, arities, variables, numeric
    literals, and repeated-parameter identity must match exactly.  A differing
    leaf pair is admissible only when the left source parameter occurs solely
    in the reviewed paper-branch programs and the right source parameter
    occurs solely in the reviewed alternate-branch programs.  This establishes
    branch ownership from the claim programs themselves, including cards that
    place both branch parameters in one shared mechanism, without inferring a
    relationship from parameter names or sampled values.
    """

    if set(paper_outputs) != set(counterfactual_outputs):
        return None

    paper_used_parameters: set[str] = set()
    counterfactual_used_parameters: set[str] = set()
    for expression in paper_outputs.values():
        paper_used_parameters.update(_expression_parameter_names(expression))
    for expression in counterfactual_outputs.values():
        counterfactual_used_parameters.update(
            _expression_parameter_names(expression)
        )

    pair_names: Dict[Tuple[str, str], str] = {}
    left_to_right: Dict[str, str] = {}
    right_to_left: Dict[str, str] = {}
    used_runtime_names: set[str] = set()
    paper_parameters: Dict[str, float] = {}
    counterfactual_parameters: Dict[str, float] = {}
    differing_source_pairs: set[Tuple[str, str]] = set()

    def allocate(
        left_name: str,
        right_name: str,
    ) -> Optional[str]:
        pair = (left_name, right_name)
        if pair in pair_names:
            return pair_names[pair]
        if (
            left_name in left_to_right
            and left_to_right[left_name] != right_name
        ) or (
            right_name in right_to_left
            and right_to_left[right_name] != left_name
        ):
            return None
        try:
            paper_value = source_parameters[left_name]
            counterfactual_value = source_parameters[right_name]
        except KeyError:
            return None
        left_to_right[left_name] = right_name
        right_to_left[right_name] = left_name

        # Use an existing reviewed leaf as the runtime coordinate.  Deriving a
        # prettier shared name from spelling or AST position would be an
        # unreviewed semantic inference.  The alternate world's value remains
        # bound to ``right_name`` by this exact source-leaf pair.
        runtime_name = left_name
        if runtime_name in used_runtime_names:
            return None
        used_runtime_names.add(runtime_name)
        pair_names[pair] = runtime_name
        paper_parameters[runtime_name] = paper_value
        counterfactual_parameters[runtime_name] = counterfactual_value
        if paper_value != counterfactual_value:
            differing_source_pairs.add(pair)
        return runtime_name

    def unify(
        left: Any,
        right: Any,
    ) -> Optional[Any]:
        if isinstance(left, (int, float)) and not isinstance(left, bool):
            if (
                isinstance(right, (int, float))
                and not isinstance(right, bool)
                and float(left) == float(right)
            ):
                return float(left)
            return None
        if not isinstance(left, Mapping) or not isinstance(right, Mapping):
            return None
        if set(left) == {"var"} and set(right) == {"var"}:
            return dict(left) if left["var"] == right["var"] else None
        if set(left) == {"param"} and set(right) == {"param"}:
            runtime_name = allocate(
                left["param"],
                right["param"],
            )
            return {"param": runtime_name} if runtime_name is not None else None
        if set(left) != {"op", "args"} or set(right) != {"op", "args"}:
            return None
        if left["op"] != right["op"] or len(left["args"]) != len(right["args"]):
            return None
        arguments = []
        for left_item, right_item in zip(left["args"], right["args"]):
            item = unify(
                left_item,
                right_item,
            )
            if item is None:
                return None
            arguments.append(item)
        return {"op": left["op"], "args": arguments}

    outputs: Dict[str, Any] = {}
    for readout_name in sorted(paper_outputs):
        expression = unify(
            paper_outputs[readout_name],
            counterfactual_outputs[readout_name],
        )
        if expression is None:
            return None
        outputs[readout_name] = expression

    changed_runtime_parameters = {
        name
        for name in paper_parameters
        if paper_parameters[name] != counterfactual_parameters[name]
    }
    if len(changed_runtime_parameters) != 1 or len(differing_source_pairs) != 1:
        return None
    left_name, right_name = next(iter(differing_source_pairs))
    if (
        left_name not in paper_used_parameters
        or left_name in counterfactual_used_parameters
        or right_name not in counterfactual_used_parameters
        or right_name in paper_used_parameters
    ):
        return None
    return outputs, paper_parameters, counterfactual_parameters


def _revalidated_science_card(card: ScienceCard, *, path: str) -> ScienceCard:
    """Recheck nested mutable payloads at the authoring trust boundary."""

    try:
        return parse_science_card_payload(science_card_to_payload(card))
    except (ScienceCardError, KeyError, TypeError, ValueError) as exc:
        _error(
            path,
            "science-card claim programs changed after validation: %s" % exc,
            "case_draft.source_fidelity",
        )


def _require_reviewed_branch_partition(
    draft: MatchedCaseDraft,
    reviewed_branch_claim_ids: Optional[
        Tuple[Tuple[str, ...], Tuple[str, ...]]
    ],
    *,
    path: str,
) -> None:
    """Keep the source review's two claim groups intact.

    World labels are benchmark labels, so swapping the two complete reviewed
    groups is allowed.  Moving one claim between groups is not.
    """

    if reviewed_branch_claim_ids is None:
        return
    branch_a, branch_b = reviewed_branch_claim_ids
    derivation = draft.counterfactual_derivation
    expected_pair = {frozenset(branch_a), frozenset(branch_b)}
    actual_pair = {
        frozenset(derivation.paper_claim_ids),
        frozenset(derivation.counterfactual_claim_ids),
    }
    if (
        not branch_a
        or not branch_b
        or set(branch_a) & set(branch_b)
        or expected_pair != actual_pair
    ):
        _error(
            path + ".counterfactual_derivation",
            "paper and alternate claim groups must equal the reviewer-selected "
            "branch partition; whole-branch swapping is allowed but regrouping "
            "is not",
            "case_draft.source_fidelity",
        )


def _reviewed_oracle_contract(
    draft: MatchedCaseDraft,
    card: ScienceCard,
    *,
    path: str,
    reviewed_branch_claim_ids: Optional[
        Tuple[Tuple[str, ...], Tuple[str, ...]]
    ] = None,
) -> Optional[_ReviewedOracleContract]:
    """Compile the unique runtime Oracle implied by selected reviewed claims.

    ``None`` is the narrow replay path for a fully legacy selection whose
    claims predate structured ``oracle_outputs``.  A mixed selection is
    rejected because it has no single source-of-truth policy.
    """

    validated_card = _revalidated_science_card(
        card,
        path=path + ".candidate.oracle.outputs",
    )
    claims_by_id = {claim.claim_id: claim for claim in validated_card.claims}
    derivation = draft.counterfactual_derivation
    _require_reviewed_branch_partition(
        draft,
        reviewed_branch_claim_ids,
        path=path,
    )
    selected_ids = (
        derivation.paper_claim_ids + derivation.counterfactual_claim_ids
    )
    unknown = sorted(set(selected_ids) - set(claims_by_id))
    if unknown:
        _error(
            path + ".counterfactual_derivation.source_claim_ids",
            "unknown science-card id(s): %s" % ", ".join(unknown),
        )
    selected = tuple(claims_by_id[claim_id] for claim_id in selected_ids)
    structured = tuple(claim.oracle_outputs is not None for claim in selected)
    if not any(structured):
        return None
    if not all(structured):
        _error(
            path + ".counterfactual_derivation.source_claim_ids",
            "cannot mix legacy opaque claims with structured claim programs",
            "case_draft.source_fidelity",
        )

    paper_claims = tuple(
        claims_by_id[claim_id] for claim_id in derivation.paper_claim_ids
    )
    counterfactual_claims = tuple(
        claims_by_id[claim_id]
        for claim_id in derivation.counterfactual_claim_ids
    )
    paper_outputs = _merge_claim_outputs(
        paper_claims,
        path=path + ".counterfactual_derivation.paper_claim_ids",
    )
    counterfactual_outputs = _merge_claim_outputs(
        counterfactual_claims,
        path=path + ".counterfactual_derivation.counterfactual_claim_ids",
    )
    expected_readouts = {readout.name for readout in draft.candidate.readouts}
    if set(paper_outputs) != expected_readouts:
        _error(
            path + ".counterfactual_derivation.paper_claim_ids",
            "selected paper claims must define every candidate readout exactly once",
            "case_draft.source_fidelity",
        )
    if set(counterfactual_outputs) != expected_readouts:
        _error(
            path + ".counterfactual_derivation.counterfactual_claim_ids",
            "selected alternate claims must define every candidate readout exactly once",
            "case_draft.source_fidelity",
        )

    selected_mechanism_ids = {
        mechanism_id
        for claim in selected
        for mechanism_id in claim.mechanism_ids
    }
    source_parameters = {
        canonical_science_name(parameter.name): parameter.value
        for mechanism in validated_card.mechanisms
        if mechanism.mechanism_id in selected_mechanism_ids
        for parameter in mechanism.parameters
    }
    # The direct program collapses two reviewed branches onto one runtime
    # coordinate.  Require the external source review's exact branch partition
    # before doing so; diagnostic/legacy callers without that partition retain
    # the explicit selector representation.
    direct_contract = (
        _direct_branch_parameter_contract(
            paper_outputs,
            counterfactual_outputs,
            source_parameters=source_parameters,
        )
        if reviewed_branch_claim_ids is not None
        else None
    )
    if direct_contract is not None:
        direct_outputs, direct_paper, direct_counterfactual = direct_contract
        return _ReviewedOracleContract(
            outputs=direct_outputs,
            paper_parameters=direct_paper,
            counterfactual_parameters=direct_counterfactual,
            compilation_kind="direct_source_parameter",
        )

    selector = derivation.selector_parameter
    if selector in source_parameters:
        _error(
            path + ".counterfactual_derivation.selector_parameter",
            "selector collides with a reviewed science parameter",
            "case_draft.source_fidelity",
        )
    used_parameters: set[str] = set()
    for expression in tuple(paper_outputs.values()) + tuple(
        counterfactual_outputs.values()
    ):
        used_parameters.update(_expression_parameter_names(expression))
    unknown_parameters = sorted(used_parameters - set(source_parameters))
    if unknown_parameters:
        _error(
            path + ".candidate.oracle.outputs",
            "reviewed claim uses unknown parameter(s): %s"
            % ", ".join(unknown_parameters),
            "case_draft.source_fidelity",
        )

    outputs: Dict[str, Any] = {}
    for readout in draft.candidate.readouts:
        name = readout.name
        outputs[name] = {
            "op": "add",
            "args": [
                _weighted_expression(
                    _selector_weight(selector, derivation.historical_value),
                    paper_outputs[name],
                ),
                _weighted_expression(
                    _selector_weight(selector, derivation.counterfactual_value),
                    counterfactual_outputs[name],
                ),
            ],
        }
    scientific_parameters = {
        name: source_parameters[name] for name in sorted(used_parameters)
    }
    return _ReviewedOracleContract(
        outputs=outputs,
        paper_parameters={
            selector: derivation.historical_value,
            **scientific_parameters,
        },
        counterfactual_parameters={
            selector: derivation.counterfactual_value,
            **scientific_parameters,
        },
        compilation_kind="selector_program",
    )


def bind_reviewed_oracle(
    batch: CaseDraftBatch,
    card: ScienceCard,
    *,
    reviewed_branch_claim_ids: Optional[
        Tuple[Tuple[str, ...], Tuple[str, ...]]
    ] = None,
) -> CaseDraftBatch:
    """Replace LLM-authored truth fields with reviewed ScienceClaim truth."""

    if batch.status != "authored":
        return batch
    bound_drafts = []
    for index, draft in enumerate(batch.drafts):
        contract = _reviewed_oracle_contract(
            draft,
            card,
            path="$.drafts[%d]" % index,
            reviewed_branch_claim_ids=reviewed_branch_claim_ids,
        )
        if contract is None:
            bound_drafts.append(draft)
            continue
        outputs = contract.outputs
        paper_parameters = contract.paper_parameters
        counterfactual_parameters = contract.counterfactual_parameters
        oracle = replace(
            draft.candidate.oracle,
            outputs=outputs,
            paper_parameters=paper_parameters,
            counterfactual_parameters=counterfactual_parameters,
        )
        readouts = tuple(
            replace(
                readout,
                statistic=EXECUTABLE_ORACLE_STATISTIC,
                uncertainty=EXECUTABLE_ORACLE_UNCERTAINTY,
            )
            for readout in draft.candidate.readouts
        )
        bound_drafts.append(
            replace(
                draft,
                candidate=replace(
                    draft.candidate,
                    readouts=readouts,
                    oracle=oracle,
                ),
            )
        )
    return replace(batch, drafts=tuple(bound_drafts))


def bind_reviewed_fixed_conditions(
    batch: CaseDraftBatch,
    card: ScienceCard,
    *,
    reviewed_branch_claim_ids: Optional[
        Tuple[Tuple[str, ...], Tuple[str, ...]]
    ] = None,
) -> CaseDraftBatch:
    """Replace all model-authored condition lists with reviewed card facts.

    The selected claims uniquely determine the shared and branch-only sets.
    The ScienceCard order, exact statement, and deterministic runtime ID are
    retained.  Information-boundary traces are deliberately untouched: the
    model must still cite exact source IDs for every Player-visible condition.
    """

    if batch.status != "authored":
        return batch
    validated_card = _revalidated_science_card(
        card,
        path="$.fixed_conditions",
    )
    claims_by_id = {
        claim.claim_id: claim for claim in validated_card.claims
    }

    def conditions_for(ids: set[str]) -> Tuple[TemporalFixedCondition, ...]:
        return tuple(
            TemporalFixedCondition(
                condition_id=canonical_science_name(item.condition_id),
                statement=item.statement,
            )
            for item in validated_card.fixed_conditions
            if item.condition_id in ids
        )

    bound_drafts = []
    for index, draft in enumerate(batch.drafts):
        path = "$.drafts[%d]" % index
        _require_reviewed_branch_partition(
            draft,
            reviewed_branch_claim_ids,
            path=path,
        )
        derivation = draft.counterfactual_derivation
        selected_ids = (
            derivation.paper_claim_ids
            + derivation.counterfactual_claim_ids
        )
        unknown = sorted(set(selected_ids) - set(claims_by_id))
        if unknown:
            _error(
                path + ".counterfactual_derivation.source_claim_ids",
                "unknown science-card id(s): %s" % ", ".join(unknown),
            )

        def branch_condition_ids(claim_ids: Tuple[str, ...]) -> set[str]:
            return {
                condition_id
                for claim_id in claim_ids
                for condition_id in claims_by_id[claim_id].fixed_condition_ids
            }

        paper_ids = branch_condition_ids(derivation.paper_claim_ids)
        counterfactual_ids = branch_condition_ids(
            derivation.counterfactual_claim_ids
        )
        common_ids = paper_ids & counterfactual_ids
        paper_only_ids = paper_ids - common_ids
        counterfactual_only_ids = counterfactual_ids - common_ids
        oracle = replace(
            draft.candidate.oracle,
            paper_fixed_conditions=conditions_for(paper_only_ids),
            counterfactual_fixed_conditions=conditions_for(
                counterfactual_only_ids
            ),
        )
        bound_drafts.append(
            replace(
                draft,
                candidate=replace(
                    draft.candidate,
                    common_fixed_conditions=conditions_for(common_ids),
                    oracle=oracle,
                ),
            )
        )
    return replace(batch, drafts=tuple(bound_drafts))


def bind_reviewed_lineage(
    batch: CaseDraftBatch,
    card: ScienceCard,
) -> CaseDraftBatch:
    """Copy exact source ranges from the reviewed card into an unbound draft.

    The case author chooses semantic card IDs and public fields.  It does not
    transcribe locators.  This binder derives the unique locator set implied by
    those choices and leaves every ID and every model-authored string unchanged.
    Unknown or insufficient selections remain for ``validate_case_draft_batch``
    to reject.
    """

    if batch.status != "authored":
        return batch

    claims_by_id = {item.claim_id: item for item in card.claims}
    mechanisms_by_id = {item.mechanism_id: item for item in card.mechanisms}
    conditions_by_id = {
        item.condition_id: item for item in card.fixed_conditions
    }
    controls_by_name = {
        canonical_science_name(item.name): item for item in card.controls
    }
    readouts_by_name = {
        canonical_science_name(item.name): item for item in card.readouts
    }
    conditions_by_name = {
        canonical_science_name(item.condition_id): item
        for item in card.fixed_conditions
    }

    def require_unbound(ranges: Tuple[LineRange, ...], path: str) -> None:
        if ranges:
            _error(
                path,
                "must be empty in a model-authored draft; exact ranges are "
                "bound deterministically from the reviewed ScienceCard",
            )

    def selected_anchor_pairs(
        claim_ids: Tuple[str, ...],
        mechanism_ids: Tuple[str, ...],
        fixed_condition_ids: Tuple[str, ...],
    ) -> set[Tuple[int, int]]:
        pairs: set[Tuple[int, int]] = set()
        for claim_id in claim_ids:
            claim = claims_by_id.get(claim_id)
            if claim is not None:
                pairs.update(
                    (anchor.line_start, anchor.line_end)
                    for anchor in claim.anchors
                )
        for mechanism_id in mechanism_ids:
            mechanism = mechanisms_by_id.get(mechanism_id)
            if mechanism is not None:
                pairs.update(
                    (anchor.line_start, anchor.line_end)
                    for anchor in mechanism.anchors
                )
        for condition_id in fixed_condition_ids:
            condition = conditions_by_id.get(condition_id)
            if condition is not None:
                pairs.update(
                    (anchor.line_start, anchor.line_end)
                    for anchor in condition.anchors
                )
        return pairs

    def ranges_from_pairs(pairs: set[Tuple[int, int]]) -> Tuple[LineRange, ...]:
        return tuple(LineRange(start, end) for start, end in sorted(pairs))

    def bind_trace(trace: InformationTrace, path: str) -> InformationTrace:
        require_unbound(trace.line_ranges, path + ".line_ranges")
        return replace(
            trace,
            line_ranges=ranges_from_pairs(
                selected_anchor_pairs(
                    trace.claim_ids,
                    trace.mechanism_ids,
                    trace.fixed_condition_ids,
                )
            ),
        )

    bound_drafts = []
    for draft_index, draft in enumerate(batch.drafts):
        draft_path = "$.drafts[%d].information_boundary" % draft_index

        bound_public = []
        for trace_index, trace in enumerate(
            draft.information_boundary.shared_player
        ):
            trace_path = "%s.shared_player[%d]" % (draft_path, trace_index)
            require_unbound(trace.line_ranges, trace_path + ".line_ranges")
            pairs = selected_anchor_pairs(
                trace.claim_ids,
                trace.mechanism_ids,
                trace.fixed_condition_ids,
            )
            if trace.field.startswith("control."):
                control_name = trace.field.split(".", 1)[1]
                control = controls_by_name.get(control_name)
                if control is not None:
                    pairs.update(
                        (anchor.line_start, anchor.line_end)
                        for anchor in control.anchors
                    )
                for branch_claim_ids in (
                    draft.counterfactual_derivation.paper_claim_ids,
                    draft.counterfactual_derivation.counterfactual_claim_ids,
                ):
                    for claim_id in branch_claim_ids:
                        claim = claims_by_id.get(claim_id)
                        if claim is None:
                            continue
                        for domain in claim.control_domains:
                            if (
                                canonical_science_name(domain.control_name)
                                == control_name
                            ):
                                pairs.update(
                                    (anchor.line_start, anchor.line_end)
                                    for anchor in domain.anchors
                                )
            elif trace.field.startswith("readout."):
                readout_name = trace.field.split(".", 1)[1]
                readout = readouts_by_name.get(readout_name)
                if readout is not None:
                    pairs.update(
                        (anchor.line_start, anchor.line_end)
                        for anchor in readout.anchors
                    )
                    if readout.resolution is not None:
                        pairs.update(
                            (anchor.line_start, anchor.line_end)
                            for anchor in readout.resolution.anchors
                        )
            elif trace.field.startswith("fixed_condition."):
                condition_name = trace.field.split(".", 1)[1]
                condition = conditions_by_name.get(condition_name)
                if condition is not None:
                    pairs.update(
                        (anchor.line_start, anchor.line_end)
                        for anchor in condition.anchors
                    )
            bound_public.append(
                replace(trace, line_ranges=ranges_from_pairs(pairs))
            )

        bound_boundary = replace(
            draft.information_boundary,
            shared_player=tuple(bound_public),
            identification_only=bind_trace(
                draft.information_boundary.identification_only,
                draft_path + ".identification_only",
            ),
            oracle_only=bind_trace(
                draft.information_boundary.oracle_only,
                draft_path + ".oracle_only",
            ),
        )
        bound_drafts.append(
            replace(draft, information_boundary=bound_boundary)
        )
    return replace(batch, drafts=tuple(bound_drafts))


_PUBLIC_ANSWER_PATTERN = re.compile(
    r"(?:=|\^|\*\*|\\frac|\\propto|[∝≈])|"
    r"\b(?:increase(?:s|d|ing)?|decrease(?:s|d|ing)?|linear|quadratic|cubic|"
    r"exponential|logarithmic|monotonic|non[- ]?monotonic|proportional|"
    r"inversely|inverse\s+(?:relationship|dependence|proportion)|"
    r"power[- ]?law|as\s+(?:a\s+)?power\s+of|"
    r"independent\s+of|depends\s+on|"
    r"saturat(?:e|es|ed|ing|ion))\b",
    re.IGNORECASE,
)
_PUBLIC_NUMERIC_LITERAL_PATTERN = re.compile(
    r"(?<![A-Za-z0-9_])(?:\d+(?:\.\d+)?|\.\d+)(?![A-Za-z0-9_])"
)

# These fields present the already source-bound case to the Player, but do not
# define the executable interface, source provenance, branch assignment, or
# Oracle program.  Warm-up runs showed that a deterministic model can repeat an
# identical rejected sentence through every bounded repair call.  Replacing
# only the diagnosed decorative field is therefore a smaller and more reliable
# operation than asking for another scientific draft.
_SAFE_DECORATIVE_PROSE = {
    "title": "Interactive measurement study",
    "apparatus.description": (
        "The apparatus exposes the listed experimental controls and readouts."
    ),
    "background": (
        "Use controlled measurements to characterize the observed phenomenon."
    ),
    "initial_observation": (
        "A measurable response is present under the stated conditions."
    ),
    "note": "Use only the stated controls, readouts, and fixed conditions.",
}
_DECORATIVE_SCALAR_PATH = re.compile(
    r"^\$\.drafts\[(\d+)\]\.candidate\."
    r"(title|background|apparatus\.description)$"
)
_DECORATIVE_OBSERVATION_PATH = re.compile(
    r"^\$\.drafts\[(\d+)\]\.candidate\.initial_observations\[(\d+)\]$"
)
_DECORATIVE_NOTE_PATH = re.compile(
    r"^\$\.drafts\[(\d+)\]\.candidate\.notes\[(\d+)\]$"
)


def _compile_safe_decorative_prose(
    batch: CaseDraftBatch,
    error: CaseDraftError,
) -> Optional[Tuple[CaseDraftBatch, PublicProseNormalization]]:
    """Replace exactly one diagnosed decorative field with neutral prose.

    The compiler is intentionally unavailable to every error class except
    ``case_draft.public_leakage`` and to semantic/interface fields such as
    controls, readouts, statistics, uncertainty, and Oracle truth. Exactly
    located initial observations and notes receive fixed neutral sentences.
    The returned batch still has to pass the complete validator.
    """

    if error.code != "case_draft.public_leakage":
        return None
    scalar_match = _DECORATIVE_SCALAR_PATH.fullmatch(error.path)
    observation_match = _DECORATIVE_OBSERVATION_PATH.fullmatch(error.path)
    note_match = _DECORATIVE_NOTE_PATH.fullmatch(error.path)
    if (
        scalar_match is None
        and observation_match is None
        and note_match is None
    ):
        return None

    draft_index = int(
        (scalar_match or observation_match or note_match).group(1)
    )
    if draft_index >= len(batch.drafts):
        return None
    draft = batch.drafts[draft_index]
    candidate = draft.candidate

    if note_match is not None:
        note_index = int(note_match.group(2))
        if note_index >= len(candidate.notes):
            return None
        original = candidate.notes[note_index]
        replacement = _SAFE_DECORATIVE_PROSE["note"]
        notes = list(candidate.notes)
        notes[note_index] = replacement
        compiled_candidate = replace(candidate, notes=tuple(notes))
    elif observation_match is not None:
        observation_index = int(observation_match.group(2))
        if observation_index >= len(candidate.initial_observations):
            return None
        original = candidate.initial_observations[observation_index]
        replacement = _SAFE_DECORATIVE_PROSE["initial_observation"]
        observations = list(candidate.initial_observations)
        observations[observation_index] = replacement
        compiled_candidate = replace(
            candidate, initial_observations=tuple(observations)
        )
    else:
        field = scalar_match.group(2)
        if field == "title":
            original = candidate.title
            replacement = _SAFE_DECORATIVE_PROSE[field]
            compiled_candidate = replace(candidate, title=replacement)
        elif field == "background":
            original = candidate.background
            replacement = _SAFE_DECORATIVE_PROSE[field]
            compiled_candidate = replace(candidate, background=replacement)
        else:
            original = candidate.apparatus.description
            replacement = _SAFE_DECORATIVE_PROSE[field]
            compiled_candidate = replace(
                candidate,
                apparatus=replace(candidate.apparatus, description=replacement),
            )

    if original == replacement:
        return None
    drafts = list(batch.drafts)
    drafts[draft_index] = replace(draft, candidate=compiled_candidate)
    return (
        replace(batch, drafts=tuple(drafts)),
        PublicProseNormalization(
            path=error.path,
            original=original,
            replacement=replacement,
        ),
    )


def _public_source_fragment(public_text: str, citation: str) -> Optional[str]:
    """Return a likely citation/title fragment exposed in Player prose."""

    def words(value: str) -> Tuple[str, ...]:
        return tuple(re.findall(r"[a-z0-9]+", value.casefold()))

    public_words = words(public_text)
    citation_words = words(citation)
    if len(public_words) < 3 or len(citation_words) < 3:
        return None
    public_trigrams = {
        public_words[index : index + 3]
        for index in range(len(public_words) - 2)
    }
    for index in range(len(citation_words) - 2):
        fragment = citation_words[index : index + 3]
        if fragment in public_trigrams:
            return " ".join(fragment)
    long_public = {item for item in public_words if len(item) >= 12}
    for item in citation_words:
        if len(item) >= 12 and item in long_public:
            return item
    return None


def _fixed_condition_payload(items: Any) -> Tuple[Tuple[str, str], ...]:
    return tuple((item.condition_id, item.statement) for item in items)


def _direction_from_differences(
    differences: Tuple[float, ...], tolerance: float
) -> str:
    has_increase = any(value > tolerance for value in differences)
    has_decrease = any(value < -tolerance for value in differences)
    if not has_increase and not has_decrease:
        return "approximately_invariant"
    if has_increase and not has_decrease:
        if all(value > tolerance for value in differences):
            return "increasing"
        return "non_decreasing"
    if has_decrease and not has_increase:
        if all(value < -tolerance for value in differences):
            return "decreasing"
        return "non_increasing"
    return "non_monotonic"


def _direction(values: Tuple[float, ...], tolerance: float) -> str:
    differences = tuple(
        right - left for left, right in zip(values, values[1:])
    )
    return _direction_from_differences(differences, tolerance)


def _control_witness_values(
    control: TemporalControl, *, target_axis: bool = False
) -> Tuple[float, ...]:
    """Return a bounded domain-spanning grid including both endpoints."""

    if control.allowed_values:
        return tuple(sorted(control.allowed_values))
    fractions = (
        tuple(index / 256.0 for index in range(257))
        if target_axis
        else (0.0, 0.5, 1.0)
    )
    return tuple(
        control.minimum + fraction * (control.maximum - control.minimum)
        for fraction in fractions
    )


def _direction_across_slices(
    slices: Tuple[Tuple[float, ...], ...],
    resolution_tolerance: float,
    numerical_tolerance: float,
) -> str:
    differences = tuple(
        right - left
        for values in slices
        for left, right in zip(values, values[1:])
    )
    has_resolved_increase = False
    has_resolved_decrease = False
    for values in slices:
        minimum_seen = values[0]
        maximum_seen = values[0]
        for value in values[1:]:
            has_resolved_increase = has_resolved_increase or (
                value > minimum_seen + resolution_tolerance
            )
            has_resolved_decrease = has_resolved_decrease or (
                value < maximum_seen - resolution_tolerance
            )
            minimum_seen = min(minimum_seen, value)
            maximum_seen = max(maximum_seen, value)
    if not has_resolved_increase and not has_resolved_decrease:
        return "approximately_invariant"
    if has_resolved_increase and has_resolved_decrease:
        return "non_monotonic"
    if has_resolved_increase:
        if all(value > numerical_tolerance for value in differences):
            return "increasing"
        return "non_decreasing"
    if all(value < -numerical_tolerance for value in differences):
        return "decreasing"
    return "non_increasing"


def _relationship_witness(
    candidate: TemporalCaseCandidate,
    target: RelationshipTarget,
) -> Tuple[str, str, bool]:
    """Numerically check direction and reject a mere additive offset."""

    controls = {item.name: item for item in candidate.controls}
    readouts = {item.name: item for item in candidate.readouts}
    control = controls[target.control]
    readout = readouts[target.readout]
    target_values = _control_witness_values(control, target_axis=True)
    other_controls = tuple(
        item for item in candidate.controls if item.name != target.control
    )
    other_value_sets = tuple(
        _control_witness_values(item) for item in other_controls
    )
    baseline_rows = product(*other_value_sets) if other_value_sets else ((),)
    condition_slices = []
    for row in baseline_rows:
        baseline = {
            item.name: value for item, value in zip(other_controls, row)
        }
        condition_slices.append(
            tuple(
                {**baseline, target.control: value} for value in target_values
            )
        )
    programs = {
        "historical": {
            "outputs": materialize_outputs(
                candidate.oracle.outputs, candidate.oracle.paper_parameters
            )
        },
        "counterfactual": {
            "outputs": materialize_outputs(
                candidate.oracle.outputs,
                candidate.oracle.counterfactual_parameters,
            )
        },
    }
    values: Dict[str, Tuple[Tuple[float, ...], ...]] = {}
    for world, program in programs.items():
        values[world] = tuple(
            tuple(
                evaluate_expression_program(
                    program,
                    condition,
                    allowed_variables=tuple(controls),
                    required_outputs=tuple(readouts),
                )[target.readout]
                for condition in conditions
            )
            for conditions in condition_slices
        )
    scale = max(
        1.0,
        *(
            abs(value)
            for world_slices in values.values()
            for world_values in world_slices
            for value in world_values
        ),
    )
    absolute_resolution = readout.resolution or 0.0
    numerical_tolerance = 1.0e-9 * scale
    direction_tolerance = max(absolute_resolution, numerical_tolerance)
    relationship_tolerance = max(
        absolute_resolution, candidate.relative_tolerance * scale
    )
    deltas = tuple(
        counterfactual - historical
        for historical_slice, counterfactual_slice in zip(
            values["historical"], values["counterfactual"]
        )
        for historical, counterfactual in zip(
            historical_slice, counterfactual_slice
        )
    )
    nonconstant_difference = (
        max(deltas) - min(deltas) > relationship_tolerance
    )
    return (
        _direction_across_slices(
            values["historical"],
            direction_tolerance,
            numerical_tolerance,
        ),
        _direction_across_slices(
            values["counterfactual"],
            direction_tolerance,
            numerical_tolerance,
        ),
        nonconstant_difference,
    )


def _canonical_relationship_shape(direction: str) -> str:
    try:
        return _CANONICAL_RELATIONSHIP_SHAPES[direction]
    except KeyError as exc:
        raise ValueError(
            "unsupported relationship direction: %s" % direction
        ) from exc


def bind_executable_relationship_directions(
    batch: CaseDraftBatch,
) -> Tuple[CaseDraftBatch, Tuple[RelationshipDirectionBinding, ...]]:
    """Bind direction labels to the already compiled executable Oracle.

    Controls, readouts, claim citations, and Oracle expressions are immutable
    here. Shape prose is reduced to the canonical phrase for the computed
    direction, without inferring curvature. Invalid target interfaces are
    deliberately left untouched so the complete validator emits its existing
    field-level diagnostic.
    """

    bound_drafts = []
    bindings = []
    for draft_index, draft in enumerate(batch.drafts):
        controls = {item.name for item in draft.candidate.controls}
        readouts = {item.name for item in draft.candidate.readouts}
        bound_targets = []
        for target_index, target in enumerate(draft.relationship_targets):
            path = "$.drafts[%d].relationship_targets[%d]" % (
                draft_index,
                target_index,
            )
            if target.control not in controls or target.readout not in readouts:
                bound_targets.append(target)
                continue
            try:
                historical, counterfactual, _ = _relationship_witness(
                    draft.candidate, target
                )
            except (ArithmeticError, ExpressionError, KeyError, ValueError) as exc:
                raise CaseDraftError(
                    "case_draft.source_fidelity",
                    path,
                    "cannot bind executable relationship directions: %s" % exc,
                ) from exc
            historical_shape = _canonical_relationship_shape(historical)
            counterfactual_shape = _canonical_relationship_shape(counterfactual)
            bound_targets.append(
                replace(
                    target,
                    historical_direction=historical,
                    counterfactual_direction=counterfactual,
                    historical_shape=historical_shape,
                    counterfactual_shape=counterfactual_shape,
                )
            )
            bindings.append(
                RelationshipDirectionBinding(
                    path=path,
                    control=target.control,
                    readout=target.readout,
                    original_historical_direction=target.historical_direction,
                    bound_historical_direction=historical,
                    original_counterfactual_direction=(
                        target.counterfactual_direction
                    ),
                    bound_counterfactual_direction=counterfactual,
                    original_historical_shape=target.historical_shape,
                    bound_historical_shape=historical_shape,
                    original_counterfactual_shape=target.counterfactual_shape,
                    bound_counterfactual_shape=counterfactual_shape,
                )
            )
        bound_drafts.append(
            replace(draft, relationship_targets=tuple(bound_targets))
        )
    return replace(batch, drafts=tuple(bound_drafts)), tuple(bindings)


def bind_enumerated_condition_partitions(
    batch: CaseDraftBatch,
) -> Tuple[CaseDraftBatch, Tuple[ConditionPartitionBinding, ...]]:
    """Split one exact all-values enumeration into visible and held-out sets.

    This deliberately recognizes only the narrow mechanical failure observed in
    temporal drafts: one purely enumerated numeric control with at least three
    values, where the model copied the same unique, complete enumeration into
    both condition lists.  Endpoints remain Player-visible diagnostics and all
    interior enumerated values become hidden evaluation conditions.  Continuous
    controls, multiple controls, partial/duplicate lists, and already-disjoint
    drafts are left untouched for the normal validator to accept or reject.
    """

    bound_drafts = []
    bindings = []
    for draft_index, draft in enumerate(batch.drafts):
        candidate = draft.candidate
        if len(candidate.controls) != 1:
            bound_drafts.append(draft)
            continue
        control = candidate.controls[0]
        if (
            control.minimum is not None
            or control.maximum is not None
            or len(control.allowed_values) < 3
        ):
            bound_drafts.append(draft)
            continue
        diagnostic = candidate.diagnostic_conditions
        hidden = candidate.hidden_conditions
        if diagnostic != hidden or len(diagnostic) != len(control.allowed_values):
            bound_drafts.append(draft)
            continue
        if any(set(condition) != {control.name} for condition in diagnostic):
            bound_drafts.append(draft)
            continue
        observed_values = tuple(condition[control.name] for condition in diagnostic)
        if (
            len(set(observed_values)) != len(observed_values)
            or set(observed_values) != set(control.allowed_values)
        ):
            bound_drafts.append(draft)
            continue

        ordered_values = tuple(sorted(control.allowed_values))
        bound_diagnostic = (
            {control.name: ordered_values[0]},
            {control.name: ordered_values[-1]},
        )
        bound_hidden = tuple(
            {control.name: value} for value in ordered_values[1:-1]
        )
        bound_candidate = replace(
            candidate,
            diagnostic_conditions=bound_diagnostic,
            hidden_conditions=bound_hidden,
        )
        path = "$.drafts[%d].candidate" % draft_index
        bindings.append(
            ConditionPartitionBinding(
                path=path,
                control=control.name,
                allowed_values=ordered_values,
                original_diagnostic_conditions=diagnostic,
                original_hidden_conditions=hidden,
                bound_diagnostic_conditions=bound_diagnostic,
                bound_hidden_conditions=bound_hidden,
            )
        )
        bound_drafts.append(replace(draft, candidate=bound_candidate))
    return replace(batch, drafts=tuple(bound_drafts)), tuple(bindings)


def validate_case_draft_batch(
    batch: CaseDraftBatch,
    card: ScienceCard,
    *,
    strict_source_only: bool = True,
    reviewed_branch_claim_ids: Optional[
        Tuple[Tuple[str, ...], Tuple[str, ...]]
    ] = None,
) -> None:
    """Bind every draft fact to the card and enforce the information boundary."""

    if not card.case_authoring_ready and batch.status == "authored":
        _error("$.status", "a non-ready science card cannot author a draft")
    claims_by_id = {item.claim_id: item for item in card.claims}
    mechanisms_by_id = {item.mechanism_id: item for item in card.mechanisms}
    fixed_conditions_by_id = {
        item.condition_id: item for item in card.fixed_conditions
    }
    claim_ids = set(claims_by_id)
    mechanism_ids = set(mechanisms_by_id)
    fixed_condition_ids = set(fixed_conditions_by_id)
    controls = {canonical_science_name(item.name): item for item in card.controls}
    readouts = {canonical_science_name(item.name): item for item in card.readouts}
    source_parameters = {
        canonical_science_name(parameter.name): parameter.value
        for mechanism in card.mechanisms
        for parameter in mechanism.parameters
    }

    def validate_ids(values: Tuple[str, ...], allowed: set[str], path: str) -> None:
        unknown = sorted(set(values) - allowed)
        if unknown:
            _error(path, "unknown science-card id(s): %s" % ", ".join(unknown))

    def validate_trace(trace: InformationTrace, path: str) -> None:
        validate_ids(trace.claim_ids, claim_ids, path + ".claim_ids")
        validate_ids(trace.mechanism_ids, mechanism_ids, path + ".mechanism_ids")
        validate_ids(
            trace.fixed_condition_ids,
            fixed_condition_ids,
            path + ".fixed_condition_ids",
        )
        if (
            not trace.claim_ids
            and not trace.mechanism_ids
            and not trace.fixed_condition_ids
        ):
            _error(
                path,
                "must cite at least one science-card claim, mechanism, or fixed condition",
            )
        if not trace.line_ranges:
            _error(
                path + ".line_ranges",
                "must contain deterministically bound source ranges",
            )
        allowed_anchors: set[Tuple[int, int]] = set()
        for claim_id in trace.claim_ids:
            allowed_anchors.update(
                (item.line_start, item.line_end)
                for item in claims_by_id[claim_id].anchors
            )
        for mechanism_id in trace.mechanism_ids:
            mechanism = mechanisms_by_id[mechanism_id]
            allowed_anchors.update(
                (item.line_start, item.line_end) for item in mechanism.anchors
            )
            for parameter in mechanism.parameters:
                allowed_anchors.update(
                    (item.line_start, item.line_end) for item in parameter.anchors
                )
        for condition_id in trace.fixed_condition_ids:
            allowed_anchors.update(
                (item.line_start, item.line_end)
                for item in fixed_conditions_by_id[condition_id].anchors
            )
        for item in trace.line_ranges:
            if (item.line_start, item.line_end) not in allowed_anchors:
                _error(
                    path + ".line_ranges",
                    "range is not an anchor of a fact cited by this trace",
                )

    def validate_public_trace(
        trace: PublicFieldTrace,
        path: str,
        *,
        direct_anchors: Tuple[Any, ...] = (),
    ) -> None:
        as_information_trace = InformationTrace(
            items=(trace.field,),
            claim_ids=trace.claim_ids,
            mechanism_ids=trace.mechanism_ids,
            fixed_condition_ids=trace.fixed_condition_ids,
            line_ranges=trace.line_ranges,
        )
        if direct_anchors:
            validate_ids(trace.claim_ids, claim_ids, path + ".claim_ids")
            validate_ids(
                trace.mechanism_ids, mechanism_ids, path + ".mechanism_ids"
            )
            validate_ids(
                trace.fixed_condition_ids,
                fixed_condition_ids,
                path + ".fixed_condition_ids",
            )
            allowed_direct = {
                (item.line_start, item.line_end) for item in direct_anchors
            }
            if not any(
                (item.line_start, item.line_end) in allowed_direct
                for item in trace.line_ranges
            ):
                _error(
                    path + ".line_ranges",
                    "field trace must include its direct science-card resource anchor",
                )
            referenced = set(allowed_direct)
            for claim_id in trace.claim_ids:
                referenced.update(
                    (item.line_start, item.line_end)
                    for item in claims_by_id[claim_id].anchors
                )
            for mechanism_id in trace.mechanism_ids:
                mechanism = mechanisms_by_id[mechanism_id]
                referenced.update(
                    (item.line_start, item.line_end) for item in mechanism.anchors
                )
                for parameter in mechanism.parameters:
                    referenced.update(
                        (item.line_start, item.line_end)
                        for item in parameter.anchors
                    )
            for condition_id in trace.fixed_condition_ids:
                referenced.update(
                    (item.line_start, item.line_end)
                    for item in fixed_conditions_by_id[condition_id].anchors
                )
            if any(
                (item.line_start, item.line_end) not in referenced
                for item in trace.line_ranges
            ):
                _error(
                    path + ".line_ranges",
                    "range is not linked to this field or a cited card fact",
                )
            return
        validate_trace(as_information_trace, path)

    for draft_index, draft in enumerate(batch.drafts):
        path = "$.drafts[%d]" % draft_index
        boundary = draft.information_boundary
        validate_trace(
            boundary.identification_only,
            path + ".information_boundary.identification_only",
        )
        validate_trace(boundary.oracle_only, path + ".information_boundary.oracle_only")

        identification_boundary_text = "\n".join(
            boundary.identification_only.items
        ).lower()
        forbidden_identification_terms = (
            "selector",
            "historical",
            "counterfactual",
            "private regime",
            "inactive branch",
        )
        if any(
            term in identification_boundary_text
            for term in forbidden_identification_terms
        ):
            _error(
                path + ".information_boundary.identification_only.items",
                "Identification may describe only the shared public scaffold, not private world machinery",
                "case_draft.public_leakage",
            )

        derivation = draft.counterfactual_derivation
        validate_ids(
            derivation.source_claim_ids,
            claim_ids,
            path + ".counterfactual_derivation.source_claim_ids",
        )
        validate_ids(
            derivation.paper_claim_ids,
            claim_ids,
            path + ".counterfactual_derivation.paper_claim_ids",
        )
        validate_ids(
            derivation.counterfactual_claim_ids,
            claim_ids,
            path + ".counterfactual_derivation.counterfactual_claim_ids",
        )
        validate_ids(
            derivation.source_mechanism_ids,
            mechanism_ids,
            path + ".counterfactual_derivation.source_mechanism_ids",
        )
        if not derivation.source_claim_ids or not derivation.source_mechanism_ids:
            _error(
                path + ".counterfactual_derivation",
                "a reported regime selection must cite both claims and mechanisms",
            )
        if (
            not derivation.paper_claim_ids
            or not derivation.counterfactual_claim_ids
            or set(derivation.paper_claim_ids)
            & set(derivation.counterfactual_claim_ids)
            or set(derivation.source_claim_ids)
            != set(derivation.paper_claim_ids)
            | set(derivation.counterfactual_claim_ids)
        ):
            _error(
                path + ".counterfactual_derivation",
                "paper/counterfactual claim sets must be non-empty, disjoint, and partition source_claim_ids",
                "case_draft.source_fidelity",
            )
        selected_mechanism_ids = {
            mechanism_id
            for selected_claim_id in derivation.source_claim_ids
            for mechanism_id in claims_by_id[selected_claim_id].mechanism_ids
        }
        if set(derivation.source_mechanism_ids) != selected_mechanism_ids:
            _error(
                path + ".counterfactual_derivation.source_mechanism_ids",
                "must equal the mechanism union linked by source_claim_ids",
                "case_draft.source_fidelity",
            )
        if strict_source_only and derivation.kind != "reported_regime_selection":
            _error(
                path + ".counterfactual_derivation.kind",
                "strict source-only authoring permits only a paper-reported alternate regime",
                "case_draft.source_fidelity",
            )
        if not derivation.paper_defined_equations_unchanged:
            _error(
                path + ".counterfactual_derivation.paper_defined_equations_unchanged",
                "a source-contained twin must preserve the reported branch equations",
                "case_draft.source_fidelity",
            )

        candidate = draft.candidate
        if (
            candidate.source.citation != card.source.citation
            or candidate.source.journal_doi != card.source.journal_doi
            or candidate.source.arxiv_versioned_id
            != card.source.arxiv_versioned_id
        ):
            _error(path + ".candidate.source", "must equal the science-card source")
        if candidate.max_replicates != 1:
            _error(
                path + ".candidate.max_replicates",
                "a deterministic paper-fit draft must expose exactly one replicate",
            )
        expected_public_fields = {
            "title",
            "background",
            "apparatus",
            *("control.%s" % item.name for item in candidate.controls),
            *("readout.%s" % item.name for item in candidate.readouts),
            *(
                "initial_observation.%d" % index
                for index in range(len(candidate.initial_observations))
            ),
            *(
                "fixed_condition.%s" % item.condition_id
                for item in candidate.common_fixed_conditions
            ),
            *("note.%d" % index for index in range(len(candidate.notes))),
        }
        public_traces = {item.field: item for item in boundary.shared_player}
        if set(public_traces) != expected_public_fields:
            _error(
                path + ".information_boundary.shared_player",
                "must contain exactly one field-level trace for each Player-visible field "
                "(missing=%s, extra=%s)"
                % (
                    sorted(expected_public_fields - set(public_traces)),
                    sorted(set(public_traces) - expected_public_fields),
                ),
                "case_draft.public_lineage",
            )
        for field, trace in public_traces.items():
            trace_path = (
                path
                + ".information_boundary.shared_player.%s" % field
            )
            if field.startswith("control."):
                control_name = field.split(".", 1)[1]
                source = controls.get(control_name)
                if source is None:
                    _error(trace_path, "trace names an unknown source control")
                branch_domain_anchors = []
                branch_domain_claim_ids = []
                for branch_claim_ids in (
                    derivation.paper_claim_ids,
                    derivation.counterfactual_claim_ids,
                ):
                    supporting_claim_ids = tuple(
                        claim_id
                        for claim_id in branch_claim_ids
                        if any(
                            canonical_science_name(domain.control_name)
                            == control_name
                            for domain in claims_by_id[claim_id].control_domains
                        )
                    )
                    branch_domain_claim_ids.append(supporting_claim_ids)
                    branch_domain_anchors.append(
                        tuple(
                            anchor
                            for claim_id in supporting_claim_ids
                            for domain in claims_by_id[claim_id].control_domains
                            if canonical_science_name(domain.control_name)
                            == control_name
                            for anchor in domain.anchors
                        )
                    )
                validate_public_trace(
                    trace,
                    trace_path,
                    direct_anchors=(
                        source.anchors
                        + tuple(
                            anchor
                            for anchors in branch_domain_anchors
                            for anchor in anchors
                        )
                    ),
                )
                allowed_control = {
                    (item.line_start, item.line_end) for item in source.anchors
                }
                if not any(
                    (item.line_start, item.line_end) in allowed_control
                    for item in trace.line_ranges
                ):
                    _error(
                        trace_path + ".line_ranges",
                        "control trace must include its direct resource anchor",
                        "case_draft.public_lineage",
                    )
                for label, anchors in zip(
                    ("paper", "alternate"), branch_domain_anchors
                ):
                    allowed = {
                        (item.line_start, item.line_end) for item in anchors
                    }
                    if allowed and not any(
                        (item.line_start, item.line_end) in allowed
                        for item in trace.line_ranges
                    ):
                        _error(
                            trace_path + ".line_ranges",
                            "control trace must include the %s branch domain anchor"
                            % label,
                            "case_draft.public_lineage",
                        )
                for label, supporting_claim_ids in zip(
                    ("paper", "alternate"), branch_domain_claim_ids
                ):
                    if supporting_claim_ids and not (
                        set(trace.claim_ids) & set(supporting_claim_ids)
                    ):
                        _error(
                            trace_path + ".claim_ids",
                            "control trace must cite a %s branch domain claim"
                            % label,
                            "case_draft.public_lineage",
                        )
            elif field.startswith("readout."):
                readout_name = field.split(".", 1)[1]
                source = readouts.get(readout_name)
                if source is None:
                    _error(trace_path, "trace names an unknown source readout")
                resolution_anchors = (
                    source.resolution.anchors
                    if source.resolution is not None
                    else ()
                )
                validate_public_trace(
                    trace,
                    trace_path,
                    direct_anchors=source.anchors + resolution_anchors,
                )
                allowed_readout = {
                    (item.line_start, item.line_end) for item in source.anchors
                }
                if not any(
                    (item.line_start, item.line_end) in allowed_readout
                    for item in trace.line_ranges
                ):
                    _error(
                        trace_path + ".line_ranges",
                        "readout trace must include its direct resource anchor",
                        "case_draft.public_lineage",
                    )
                if source.resolution is not None:
                    allowed_resolution = {
                        (item.line_start, item.line_end)
                        for item in source.resolution.anchors
                    }
                    if not any(
                        (item.line_start, item.line_end) in allowed_resolution
                        for item in trace.line_ranges
                    ):
                        _error(
                            trace_path + ".line_ranges",
                            "readout trace must include its resolution anchor",
                            "case_draft.public_lineage",
                        )
                for label, branch_claim_ids in (
                    ("paper", derivation.paper_claim_ids),
                    ("alternate", derivation.counterfactual_claim_ids),
                ):
                    supporting_claim_ids = {
                        claim_id
                        for claim_id in branch_claim_ids
                        if any(
                            canonical_science_name(name) == readout_name
                            for name in claims_by_id[claim_id].readout_names
                        )
                    }
                    if supporting_claim_ids and not (
                        set(trace.claim_ids) & supporting_claim_ids
                    ):
                        _error(
                            trace_path + ".claim_ids",
                            "readout trace must cite a %s branch readout claim"
                            % label,
                            "case_draft.public_lineage",
                        )
            elif field.startswith("fixed_condition."):
                source_id = field.split(".", 1)[1]
                source = next(
                    (
                        item
                        for item in card.fixed_conditions
                        if canonical_science_name(item.condition_id) == source_id
                    ),
                    None,
                )
                if source is None:
                    _error(trace_path, "trace names an unknown fixed condition")
                if source.condition_id not in trace.fixed_condition_ids:
                    _error(
                        trace_path + ".fixed_condition_ids",
                        "fixed-condition field must cite that exact condition",
                    )
                validate_public_trace(
                    trace, trace_path, direct_anchors=source.anchors
                )
            else:
                validate_public_trace(trace, trace_path)

        public_prose_entries = (
            (path + ".candidate.title", candidate.title),
            (
                path + ".candidate.apparatus.name",
                candidate.apparatus.name.replace("_", " "),
            ),
            (
                path + ".candidate.apparatus.description",
                candidate.apparatus.description,
            ),
            (path + ".candidate.background", candidate.background),
            *(
                (
                    "%s.candidate.initial_observations[%d]" % (path, index),
                    item,
                )
                for index, item in enumerate(candidate.initial_observations)
            ),
            *(
                (
                    "%s.candidate.controls[%d].description" % (path, index),
                    item.description,
                )
                for index, item in enumerate(candidate.controls)
            ),
            *(
                (
                    "%s.candidate.readouts[%d].description" % (path, index),
                    item.description,
                )
                for index, item in enumerate(candidate.readouts)
            ),
            *(
                ("%s.candidate.notes[%d]" % (path, index), item)
                for index, item in enumerate(candidate.notes)
            ),
        )
        # Control/readout names are source-bound machine identifiers, not
        # model-authored prose.  Their exact canonical membership is enforced
        # below; scanning identifiers such as ``l_over_l0`` for digits would
        # incorrectly reject the required source-to-machine mapping.
        public_prose = tuple(item for _, item in public_prose_entries)
        readout_semantic_entries = tuple(
            entry
            for index, item in enumerate(candidate.readouts)
            for entry in (
                (
                    "%s.candidate.readouts[%d].statistic" % (path, index),
                    item.statistic,
                ),
                (
                    "%s.candidate.readouts[%d].uncertainty" % (path, index),
                    item.uncertainty,
                ),
            )
        )
        # Common fixed-condition statements are not model-authored prose.  The
        # fixed-condition binder copies them verbatim from reviewed card facts,
        # and source-fidelity validation below checks the complete ordered
        # payload.  Source statements may legitimately contain a numeric setup
        # value or an equality, so running the public-answer heuristic over
        # them would reject correct source material.  All remaining public
        # prose, including notes and target control/readout descriptions,
        # stays under the strict leakage checks.
        public_items = public_prose + tuple(
            item for _, item in readout_semantic_entries
        )
        public_text = "\n".join(public_items)
        leaking_field = next(
            (
                (field_path, item)
                for field_path, item in public_prose_entries
                if _PUBLIC_NUMERIC_LITERAL_PATTERN.search(item)
                or _PUBLIC_ANSWER_PATTERN.search(item)
            ),
            None,
        )
        if leaking_field is None:
            leaking_field = next(
                (
                    (field_path, item)
                    for field_path, item in readout_semantic_entries
                    if _PUBLIC_ANSWER_PATTERN.search(item)
                ),
                None,
            )
        if leaking_field is not None:
            _error(
                leaking_field[0],
                "Player-visible prose cannot contain numeric answers, formulas, or answer-direction language",
                "case_draft.public_leakage",
            )
        source_tokens = (
            card.source.citation.lower(),
            card.source.journal_doi.lower(),
            card.source.arxiv_versioned_id.lower(),
        )
        source_identity_field = next(
            (
                field_path
                for field_path, item in public_prose_entries
                + readout_semantic_entries
                if any(token and token in item.lower() for token in source_tokens)
            ),
            None,
        )
        if source_identity_field is not None:
            _error(
                source_identity_field,
                "Player-visible fields cannot reveal the source identity",
                "case_draft.public_leakage",
            )
        source_fragment_field = next(
            (
                (field_path, fragment)
                for field_path, item in public_prose_entries
                + readout_semantic_entries
                for fragment in (_public_source_fragment(item, card.source.citation),)
                if fragment is not None
            ),
            None,
        )
        if source_fragment_field is not None:
            _error(
                source_fragment_field[0],
                "Player-visible prose repeats a citation/title fragment: %s"
                % source_fragment_field[1],
                "case_draft.public_leakage",
            )
        private_terms = (
            "historical",
            "counterfactual",
            "selector",
            "private regime",
            "paper branch",
            "alternate branch",
        )
        leaking_private_field = next(
            (
                field_path
                for field_path, item in public_prose_entries
                + readout_semantic_entries
                if any(term in item.lower() for term in private_terms)
            ),
            None,
        )
        if leaking_private_field is not None:
            _error(
                leaking_private_field,
                "Player-visible prose cannot describe private worlds, branches, or selectors",
                "case_draft.public_leakage",
            )

        selected_claims = tuple(
            claims_by_id[item] for item in derivation.source_claim_ids
        )
        selected_control_names = {
            canonical_science_name(name)
            for claim in selected_claims
            for name in claim.control_names
        }
        selected_readout_names = {
            canonical_science_name(name)
            for claim in selected_claims
            for name in claim.readout_names
        }
        candidate_control_names = {item.name for item in candidate.controls}
        candidate_readout_names = {item.name for item in candidate.readouts}
        if candidate_control_names != selected_control_names:
            _error(
                path + ".candidate.controls",
                "must expose exactly the controls used by the selected source claims",
                "case_draft.source_fidelity",
            )
        if candidate_readout_names != selected_readout_names:
            _error(
                path + ".candidate.readouts",
                "must expose exactly the readouts used by the selected source claims",
                "case_draft.source_fidelity",
            )

        paper_claims = [claims_by_id[item] for item in derivation.paper_claim_ids]
        counterfactual_claims = [
            claims_by_id[item] for item in derivation.counterfactual_claim_ids
        ]

        def applicability(claims: Any) -> Tuple[str, ...]:
            result = []
            for claim in claims:
                if claim.applicability not in result:
                    result.append(claim.applicability)
            return tuple(result)

        if candidate.oracle.paper_applicability != applicability(paper_claims):
            _error(
                path + ".candidate.oracle.paper_applicability",
                "must copy the paper-branch claim applicability statements exactly",
                "case_draft.source_fidelity",
            )
        if candidate.oracle.counterfactual_applicability != applicability(
            counterfactual_claims
        ):
            _error(
                path + ".candidate.oracle.counterfactual_applicability",
                "must copy the alternate-branch claim applicability statements exactly",
                "case_draft.source_fidelity",
            )

        def condition_ids(claims: Any) -> set[str]:
            return {
                condition_id
                for claim in claims
                for condition_id in claim.fixed_condition_ids
            }

        paper_condition_ids = condition_ids(paper_claims)
        counterfactual_condition_ids = condition_ids(counterfactual_claims)
        common_condition_ids = paper_condition_ids & counterfactual_condition_ids
        paper_only_condition_ids = paper_condition_ids - common_condition_ids
        counterfactual_only_condition_ids = (
            counterfactual_condition_ids - common_condition_ids
        )

        def expected_conditions(ids: set[str]) -> Tuple[Tuple[str, str], ...]:
            return tuple(
                (
                    canonical_science_name(item.condition_id),
                    item.statement,
                )
                for item in card.fixed_conditions
                if item.condition_id in ids
            )

        if _fixed_condition_payload(candidate.common_fixed_conditions) != expected_conditions(
            common_condition_ids
        ):
            _error(
                path + ".candidate.common_fixed_conditions",
                "must equal the fixed conditions shared by both source branches",
                "case_draft.source_fidelity",
            )
        if _fixed_condition_payload(
            candidate.oracle.paper_fixed_conditions
        ) != expected_conditions(paper_only_condition_ids):
            _error(
                path + ".candidate.oracle.paper_fixed_conditions",
                "must equal the paper-branch-only fixed conditions",
                "case_draft.source_fidelity",
            )
        if _fixed_condition_payload(
            candidate.oracle.counterfactual_fixed_conditions
        ) != expected_conditions(counterfactual_only_condition_ids):
            _error(
                path + ".candidate.oracle.counterfactual_fixed_conditions",
                "must equal the alternate-branch-only fixed conditions",
                "case_draft.source_fidelity",
            )

        def shared_domains(control_name: str) -> Tuple[Any, ...]:
            paper_domains = [
                domain
                for claim in paper_claims
                for domain in claim.control_domains
                if canonical_science_name(domain.control_name) == control_name
            ]
            counterfactual_domains = [
                domain
                for claim in counterfactual_claims
                for domain in claim.control_domains
                if canonical_science_name(domain.control_name) == control_name
            ]
            if not paper_domains or not counterfactual_domains:
                _error(
                    path + ".counterfactual_derivation.source_claim_ids",
                    "both branches must provide a claim-specific domain for %s"
                    % control_name,
                    "case_draft.source_fidelity",
                )
            return tuple(paper_domains + counterfactual_domains)

        def domain_supports_query(domain: Any, control: Any) -> bool:
            if control.allowed_values:
                if domain.domain_kind == "continuous_interval":
                    return (
                        domain.minimum is not None
                        and domain.maximum is not None
                        and all(
                            domain.minimum <= value <= domain.maximum
                            for value in control.allowed_values
                        )
                    )
                if domain.domain_kind in {"numeric_values", "fixed_value"}:
                    return set(control.allowed_values).issubset(
                        domain.allowed_values
                    )
                return False
            if control.minimum is None or control.maximum is None:
                return False
            return (
                domain.domain_kind == "continuous_interval"
                and domain.minimum is not None
                and domain.maximum is not None
                and domain.minimum <= control.minimum
                and control.maximum <= domain.maximum
            )

        for index, control in enumerate(candidate.controls):
            source = controls.get(control.name)
            control_path = "%s.candidate.controls[%d]" % (path, index)
            if source is None:
                _error(control_path + ".name", "control is absent from the science card")
            if control.unit != source.unit:
                _error(control_path + ".unit", "must equal the science-card unit")
            domains = shared_domains(control.name)
            if not all(domain_supports_query(domain, control) for domain in domains):
                _error(
                    control_path,
                    "benchmark query set must be contained in every selected branch domain",
                    "case_draft.source_fidelity",
                )
        selected_claims_have_structured_truth = all(
            claims_by_id[claim_id].oracle_outputs is not None
            for claim_id in derivation.source_claim_ids
        )
        for index, readout in enumerate(candidate.readouts):
            source = readouts.get(readout.name)
            readout_path = "%s.candidate.readouts[%d]" % (path, index)
            if source is None:
                _error(readout_path + ".name", "readout is absent from the science card")
            if readout.unit != source.unit:
                _error(readout_path + ".unit", "must equal the science-card unit")
            expected_statistic = (
                EXECUTABLE_ORACLE_STATISTIC
                if selected_claims_have_structured_truth
                else source.statistic
            )
            expected_uncertainty = (
                EXECUTABLE_ORACLE_UNCERTAINTY
                if selected_claims_have_structured_truth
                else source.uncertainty
            )
            if readout.statistic != expected_statistic:
                _error(
                    readout_path + ".statistic",
                    "must describe the deterministic central-relation Oracle, not the source data aggregation",
                    "case_draft.source_fidelity",
                )
            if readout.uncertainty != expected_uncertainty:
                _error(
                    readout_path + ".uncertainty",
                    "must state that source uncertainty is provenance and is not attached to this query",
                    "case_draft.source_fidelity",
                )
            if source.resolution is None:
                if (
                    readout.resolution is not None
                    or readout.resolution_kind is not None
                ):
                    _error(
                        readout_path + ".resolution",
                        "must remain null when the science card reports no quantization",
                        "case_draft.source_fidelity",
                    )
            elif (
                readout.resolution != source.resolution.value
                or readout.resolution_kind != source.resolution.kind
            ):
                _error(
                    readout_path + ".resolution",
                    "must exactly reuse the science-card resolution value and kind",
                    "case_draft.source_fidelity",
                )

        selector = derivation.selector_parameter
        paper_parameters = candidate.oracle.paper_parameters
        counterfactual_parameters = candidate.oracle.counterfactual_parameters
        if set(paper_parameters) != set(counterfactual_parameters):
            _error(
                path + ".candidate.oracle.counterfactual_parameters",
                "paper and alternate parameter maps must have identical keys",
                "case_draft.source_fidelity",
            )
        reviewed_contract = _reviewed_oracle_contract(
            draft,
            card,
            path=path,
            reviewed_branch_claim_ids=reviewed_branch_claim_ids,
        )
        if reviewed_contract is not None:
            expected_outputs = reviewed_contract.outputs
            expected_paper_parameters = reviewed_contract.paper_parameters
            expected_counterfactual_parameters = (
                reviewed_contract.counterfactual_parameters
            )
            if reviewed_contract.compilation_kind == "selector_program":
                if (
                    selector not in paper_parameters
                    or selector not in counterfactual_parameters
                ):
                    _error(
                        path + ".counterfactual_derivation.selector_parameter",
                        "selector must be an Oracle parameter",
                    )
                if paper_parameters[selector] != derivation.historical_value:
                    _error(
                        path + ".counterfactual_derivation.historical_value",
                        "does not match Oracle",
                    )
                if (
                    counterfactual_parameters[selector]
                    != derivation.counterfactual_value
                ):
                    _error(
                        path + ".counterfactual_derivation.counterfactual_value",
                        "does not match Oracle",
                    )
                if {
                    derivation.historical_value,
                    derivation.counterfactual_value,
                } != {0.0, 1.0}:
                    _error(
                        path + ".counterfactual_derivation",
                        "a source-regime selector must use the benchmark-only values zero and one",
                        "case_draft.source_fidelity",
                    )
                for parameter_name, value in paper_parameters.items():
                    if parameter_name == selector:
                        continue
                    if counterfactual_parameters[parameter_name] != value:
                        _error(
                            path
                            + ".candidate.oracle.counterfactual_parameters.%s"
                            % parameter_name,
                            "only the regime selector may change",
                            "case_draft.source_fidelity",
                        )
                    if source_parameters.get(parameter_name) != value:
                        _error(
                            path + ".candidate.oracle.paper_parameters.%s"
                            % parameter_name,
                            "must exactly reuse a same-named science-card parameter",
                            "case_draft.source_fidelity",
                        )
            else:
                if selector in paper_parameters or selector in counterfactual_parameters:
                    _error(
                        path + ".counterfactual_derivation.selector_parameter",
                        "authoring-only branch selector must not enter a direct source-parameter Oracle",
                        "case_draft.source_fidelity",
                    )
                changed_parameters = {
                    name
                    for name in paper_parameters
                    if paper_parameters[name] != counterfactual_parameters[name]
                }
                if len(changed_parameters) != 1:
                    _error(
                        path + ".candidate.oracle.counterfactual_parameters",
                        "a direct source-parameter program must change exactly one reviewed coordinate",
                        "case_draft.source_fidelity",
                    )
            if candidate.oracle.outputs != expected_outputs:
                _error(
                    path + ".candidate.oracle.outputs",
                    "must equal the deterministic compilation of the reviewed ScienceClaim oracle_outputs",
                    "case_draft.source_fidelity",
                )
            if paper_parameters != expected_paper_parameters:
                _error(
                    path + ".candidate.oracle.paper_parameters",
                    "must contain exactly the source-derived parameters used by the compiled reviewed claim program",
                    "case_draft.source_fidelity",
                )
            if counterfactual_parameters != expected_counterfactual_parameters:
                _error(
                    path + ".candidate.oracle.counterfactual_parameters",
                    "must contain exactly the source-derived parameters used by the compiled reviewed claim program",
                    "case_draft.source_fidelity",
                )
        else:
            if selector not in paper_parameters or selector not in counterfactual_parameters:
                _error(
                    path + ".counterfactual_derivation.selector_parameter",
                    "selector must be an Oracle parameter",
                )
            if paper_parameters[selector] != derivation.historical_value:
                _error(
                    path + ".counterfactual_derivation.historical_value",
                    "does not match Oracle",
                )
            if counterfactual_parameters[selector] != derivation.counterfactual_value:
                _error(
                    path + ".counterfactual_derivation.counterfactual_value",
                    "does not match Oracle",
                )
            if {
                derivation.historical_value,
                derivation.counterfactual_value,
            } != {0.0, 1.0}:
                _error(
                    path + ".counterfactual_derivation",
                    "a source-regime selector must use the benchmark-only values zero and one",
                    "case_draft.source_fidelity",
                )
            for parameter_name, value in paper_parameters.items():
                if parameter_name == selector:
                    continue
                if counterfactual_parameters[parameter_name] != value:
                    _error(
                        path
                        + ".candidate.oracle.counterfactual_parameters.%s"
                        % parameter_name,
                        "only the regime selector may change",
                        "case_draft.source_fidelity",
                    )
                if source_parameters.get(parameter_name) != value:
                    _error(
                        path + ".candidate.oracle.paper_parameters.%s"
                        % parameter_name,
                        "must exactly reuse a same-named science-card parameter",
                        "case_draft.source_fidelity",
                    )
        for readout_name, expression in candidate.oracle.outputs.items():
            unsupported = sorted(
                {
                    value
                    for value in _literal_numbers(expression)
                    if value not in {0.0, 1.0}
                }
            )
            if unsupported:
                _error(
                    path + ".candidate.oracle.outputs.%s" % readout_name,
                    "scientific numeric constants must be named science-card parameters; "
                    "unsupported literal(s): %s" % unsupported,
                    "case_draft.source_fidelity",
                )

        target_pairs = set()
        relationship_witnessed = False
        for index, target in enumerate(draft.relationship_targets):
            target_path = "%s.relationship_targets[%d]" % (path, index)
            if target.control not in {item.name for item in candidate.controls}:
                _error(target_path + ".control", "must be a candidate control")
            if target.readout not in {item.name for item in candidate.readouts}:
                _error(target_path + ".readout", "must be a candidate readout")
            validate_ids(
                target.source_claim_ids,
                claim_ids,
                target_path + ".source_claim_ids",
            )
            if not target.source_claim_ids:
                _error(
                    target_path + ".source_claim_ids",
                    "a relationship target must cite a science-card claim",
                )
            if not set(target.source_claim_ids) <= set(derivation.source_claim_ids):
                _error(
                    target_path + ".source_claim_ids",
                    "relationship claims must belong to the selected branch pair",
                    "case_draft.source_fidelity",
                )
            cited_claims = [claims_by_id[item] for item in target.source_claim_ids]
            if not all(
                any(
                    canonical_science_name(name) == target.control
                    for name in claim.control_names
                )
                and any(
                    canonical_science_name(name) == target.readout
                    for name in claim.readout_names
                )
                for claim in cited_claims
            ):
                _error(
                    target_path + ".source_claim_ids",
                    "every cited claim must support this control/readout relationship",
                    "case_draft.source_fidelity",
                )
            target_pairs.add((target.control, target.readout))
            try:
                historical_direction, counterfactual_direction, differs = (
                    _relationship_witness(candidate, target)
                )
            except (ArithmeticError, ExpressionError, KeyError, ValueError) as exc:
                _error(
                    target_path,
                    "cannot evaluate relationship witness: %s" % exc,
                    "case_draft.source_fidelity",
                )
            if (
                target.historical_direction != "source_defined"
                and target.historical_direction != historical_direction
            ):
                _error(
                    target_path + ".historical_direction",
                    "declared direction disagrees with the executable Oracle",
                    "case_draft.source_fidelity",
                )
            if (
                target.counterfactual_direction != "source_defined"
                and target.counterfactual_direction != counterfactual_direction
            ):
                _error(
                    target_path + ".counterfactual_direction",
                    "declared direction disagrees with the executable Oracle",
                    "case_draft.source_fidelity",
                )
            relationship_witnessed = relationship_witnessed or differs
        if {item.name for item in candidate.readouts} - {
            readout for _, readout in target_pairs
        }:
            _error(path + ".relationship_targets", "every readout needs a target")
        if not relationship_witnessed:
            _error(
                path + ".relationship_targets",
                "the executable worlds differ only by an invariant offset or not at all",
                "case_draft.source_fidelity",
            )


def case_draft_batch_json_schema(
    *,
    scaffold_oracle: bool = False,
) -> Mapping[str, Any]:
    identifier: Dict[str, Any] = {
        "type": "string",
        "pattern": "^[a-z][a-z0-9_]*$",
    }
    source_identifier: Dict[str, Any] = {
        "type": "string",
        "pattern": "^[A-Za-z][A-Za-z0-9_]*$",
    }
    text: Dict[str, Any] = {"type": "string", "minLength": 1}
    source_ids = {
        "type": "array",
        "items": source_identifier,
        "uniqueItems": True,
    }
    line_range = {
        "type": "object",
        "properties": {
            "line_start": {"type": "integer", "minimum": 1},
            "line_end": {"type": "integer", "minimum": 1},
        },
        "required": ["line_start", "line_end"],
        "additionalProperties": False,
    }
    trace = {
        "type": "object",
        "properties": {
            "items": {"type": "array", "items": text, "minItems": 1},
            "claim_ids": source_ids,
            "mechanism_ids": source_ids,
            "fixed_condition_ids": source_ids,
            "line_ranges": {"type": "array", "items": line_range, "maxItems": 0},
        },
        "required": [
            "items",
            "claim_ids",
            "mechanism_ids",
            "fixed_condition_ids",
            "line_ranges",
        ],
        "additionalProperties": False,
    }
    public_field_trace = {
        "type": "object",
        "properties": {
            "field": text,
            "claim_ids": source_ids,
            "mechanism_ids": source_ids,
            "fixed_condition_ids": source_ids,
            "line_ranges": {"type": "array", "items": line_range, "maxItems": 0},
        },
        "required": [
            "field",
            "claim_ids",
            "mechanism_ids",
            "fixed_condition_ids",
            "line_ranges",
        ],
        "additionalProperties": False,
    }
    boundary = {
        "type": "object",
        "properties": {
            "shared_player": {
                "type": "array",
                "items": public_field_trace,
                "minItems": 1,
            },
            "identification_only": trace,
            "oracle_only": trace,
        },
        "required": ["shared_player", "identification_only", "oracle_only"],
        "additionalProperties": False,
    }
    derivation = {
        "type": "object",
        "properties": {
            "kind": {"type": "string", "enum": sorted(_COUNTERFACTUAL_KINDS)},
            "description": text,
            "source_claim_ids": source_ids,
            "paper_claim_ids": source_ids,
            "counterfactual_claim_ids": source_ids,
            "source_mechanism_ids": source_ids,
            "selector_parameter": identifier,
            "historical_value": {"type": "number", "enum": [0.0, 1.0]},
            "counterfactual_value": {"type": "number", "enum": [0.0, 1.0]},
            "paper_defined_equations_unchanged": {"type": "boolean"},
        },
        "required": [
            "kind",
            "description",
            "source_claim_ids",
            "paper_claim_ids",
            "counterfactual_claim_ids",
            "source_mechanism_ids",
            "selector_parameter",
            "historical_value",
            "counterfactual_value",
            "paper_defined_equations_unchanged",
        ],
        "additionalProperties": False,
    }
    target = {
        "type": "object",
        "properties": {
            "control": identifier,
            "readout": identifier,
            "historical_direction": {"type": "string", "enum": sorted(_DIRECTIONS)},
            "counterfactual_direction": {"type": "string", "enum": sorted(_DIRECTIONS)},
            "historical_shape": text,
            "counterfactual_shape": text,
            "source_claim_ids": source_ids,
        },
        "required": [
            "control",
            "readout",
            "historical_direction",
            "counterfactual_direction",
            "historical_shape",
            "counterfactual_shape",
            "source_claim_ids",
        ],
        "additionalProperties": False,
    }
    candidate = dict(temporal_candidate_json_schema())
    candidate.pop("$schema")
    definitions = candidate.pop("$defs")
    # Fixed-condition membership and text are implied by the reviewed claim
    # partition, not authored by the model.  The provider emits empty
    # scaffolds; ``bind_reviewed_fixed_conditions`` fills the three lists.
    candidate["properties"]["common_fixed_conditions"]["maxItems"] = 0
    oracle_properties = candidate["properties"]["oracle"]["properties"]
    oracle_properties["paper_fixed_conditions"]["maxItems"] = 0
    oracle_properties["counterfactual_fixed_conditions"]["maxItems"] = 0
    if scaffold_oracle:
        empty_object = {
            "type": "object",
            "maxProperties": 0,
            "additionalProperties": False,
        }
        oracle_properties["outputs"] = dict(empty_object)
        oracle_properties["paper_parameters"] = dict(empty_object)
        oracle_properties["counterfactual_parameters"] = dict(empty_object)
        readout_properties = candidate["properties"]["readouts"]["items"][
            "properties"
        ]
        readout_properties["statistic"] = {
            "type": "string",
            "enum": [EXECUTABLE_ORACLE_STATISTIC],
        }
        readout_properties["uncertainty"] = {
            "type": "string",
            "enum": [EXECUTABLE_ORACLE_UNCERTAINTY],
        }
    draft = {
        "type": "object",
        "properties": {
            "design_summary": text,
            "information_boundary": boundary,
            "counterfactual_derivation": derivation,
            "relationship_targets": {"type": "array", "items": target, "minItems": 1},
            "candidate": {"$ref": "#/$defs/temporal_case_candidate"},
        },
        "required": [
            "design_summary",
            "information_boundary",
            "counterfactual_derivation",
            "relationship_targets",
            "candidate",
        ],
        "additionalProperties": False,
    }
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "properties": {
            "assessment": text,
            "status": {"type": "string", "enum": ["authored", "not_authorable"]},
            "drafts": {"type": "array", "items": draft, "maxItems": 1},
        },
        "required": ["assessment", "status", "drafts"],
        "additionalProperties": False,
        "$defs": {**definitions, "temporal_case_candidate": candidate},
    }


_SYSTEM_PROMPT = """You are a scientific benchmark case author. You receive one private, source-grounded science card. You do not receive the paper and must not add facts from memory.
Return exactly one JSON object matching the supplied CaseDraftBatch schema, without Markdown or extra text.
Use only science-card mechanisms, claims, controls, readouts, fixed conditions, numeric values, domains, statistics, and uncertainty statements.
Prefer one coherent family that groups linked claims sharing a mechanism, rather than one isolated fitted equation. Use one or two readouts only when the card supports them.
Every shared Player fact, identification-only fact, and Oracle-only fact must be listed separately in information_boundary and select only existing card claim_ids, mechanism_ids, and fixed_condition_ids. shared_player is field-level: provide exactly one trace named title, background, apparatus, control.NAME, readout.NAME, initial_observation.INDEX, fixed_condition.ID, or note.INDEX for every corresponding public field. Emit line_ranges as exactly [] in every information_boundary trace; never transcribe or invent a locator. After parsing, deterministic code copies the canonical exact ranges from the reviewed ScienceCard: anchors of the selected IDs; for control.NAME, that control's anchors and both selected branches' claim-domain anchors; for readout.NAME, its definition and optional resolution anchors; and for fixed_condition.ID, that condition's anchors. This does not repair IDs, fields, or prose. Therefore each public control/readout trace must select a supporting claim from both branches, and every selected ID must be relevant to its field.
The user message supplies an immutable machine_interface_mapping from the ScienceCard's original control, readout, and fixed-condition symbols to lower_snake_case CaseDraft machine IDs. Preserve the ScienceCard and all source IDs cited in information_boundary claim_ids, mechanism_ids, and fixed_condition_ids exactly as supplied; leave input locators untouched and do not copy them into the response. The mapping applies only to the generated CaseDraft interface. Use mapped control/readout IDs everywhere in candidate.controls[].name, candidate.readouts[].name, relationship_targets[].control/readout, candidate.oracle.outputs keys and every oracle {"var": ...} leaf, diagnostic_conditions and hidden_conditions keys, and control.NAME/readout.NAME shared_player field suffixes. Use mapped fixed-condition IDs in fixed_condition.ID shared_player field suffixes; the trace's fixed_condition_ids array still cites the exact original ScienceCard ID. Never emit an original ScienceCard symbol in one of those machine-interface positions when it differs from its mapped ID. Do not alter, extend, or reinterpret machine_interface_mapping.
Emit candidate.common_fixed_conditions, candidate.oracle.paper_fixed_conditions, and candidate.oracle.counterfactual_fixed_conditions as exactly []. Deterministic code derives their unique shared, paper-only, and alternate-only memberships from the selected reviewed claim groups, then copies the ScienceCard order, mapped runtime ID, and exact source statement. Do not transcribe or paraphrase a fixed-condition statement. This does not fill information_boundary: include one fixed_condition.MAPPED_ID shared_player trace for every condition common to both selected branches, cite its exact original ScienceCard ID in fixed_condition_ids, and leave line_ranges empty for the locator binder.
Shared Player information gives only the minimum system, protocol, actual controls, operational readouts, and common fixed conditions needed to experiment. Do not reveal a fitted equation, coefficient, exponent, numeric outcome, hidden regime, source identity, or answer direction.
Initial observations must be qualitative and contain no digits or precomputed measurements. They may state that the phenomenon and readouts exist, but not how a readout changes with a control.
Before returning, perform a literal Player-prose check. In title, background, apparatus.description, every initial_observation, and every note, omit digits, equations, proportionality notation, coefficients, exponents, answer directions, private-condition names, and source identity. Do not repeat common fixed-condition values there; candidate.common_fixed_conditions is their only public location. Control and readout descriptions state operational meanings only and omit equations or control-response claims. Safe prose is deliberately short, for example: "The apparatus exposes an adjustable control and a measurable response. Determine their relationship experimentally." Never preserve a more detailed sentence merely because it is scientifically true when that sentence crosses the public boundary.
Identification may expose a source-defined response skeleton and named parameter slots but no true values. Discovery receives only the generic expression language through the existing runtime.
Oracle domains must be traceable to the card. A science-card readout's statistic and uncertainty describe the source data and remain private provenance; they are not the semantics of a fresh benchmark query. For structured ScienceClaim oracle_outputs, set candidate.readout.statistic exactly to "Deterministic central value of the source-reported quantitative relation." and candidate.readout.uncertainty exactly to "Any source-reported uncertainty is retained as provenance and is not sampled or propagated into this query." Never call a deterministic expression result a newly sampled measurement, ensemble, or replicate, and never attach source data-point error bars or fit-parameter uncertainty to an individual query value. The deterministic binder enforces these two phrases after parsing. The legacy compatibility path without structured oracle_outputs alone copies the source readout statistic and uncertainty. When the card supplies a resolution, copy its value and kind exactly; when resolution=null, emit resolution=null and resolution_kind=null, and the Oracle returns an unquantized deterministic central value. Do not invent single-realization noise or imply that an exact simulator output is a claim of infinite experimental precision. candidate.relative_tolerance is a benchmark scoring convention, not paper-reported measurement uncertainty. The current Oracle is deterministic, so candidate.max_replicates must be exactly 1.
Under strict source-contained authoring, the alternate world must select another regime or branch that the same paper explicitly reports. Set counterfactual_derivation.kind to reported_regime_selection. Partition source_claim_ids into non-empty disjoint paper_claim_ids and counterfactual_claim_ids. Copy their applicability statements into the corresponding private Oracle fields; the fixed-condition binder, not your response, derives branch-only and shared condition lists from those selected claims. Treat a complete source-reported apparatus or regime configuration as a descriptive branch, even when several physical settings differ; do not make a single-factor causal claim unless the source does. A Player control must be executable in both branches: use either a nonzero candidate interval wholly contained in every selected claim's continuous_interval, or at least two candidate allowed_values contained in every selected numeric_values/continuous_interval domain. The benchmark query set may be a source-supported subset; it need not equal the paper's full applicability intersection. Do not compile fixed_value, symbolic, or unreported domains as Player controls. Do not invent z=1, a new exponent, a new coefficient, a new equation, or any other unreported scientific value. A numeric selector may choose between two fully reported branches, but it is benchmark machinery rather than a paper claim.
Keep the paper-defined branch equations unchanged. Choose a single selector parameter and assign the two branches the values zero and one. When the supplied ScienceClaims contain oracle_outputs, the response schema requires candidate.oracle.outputs, paper_parameters, and counterfactual_parameters to be empty objects. Emit exactly {} for those three fields: deterministic code will compile the reviewed claim programs with the selector and insert the exact source parameters after parsing. Do not transcribe, simplify, or regenerate those formulas. The compatibility path for an older card without structured oracle_outputs retains the previous full Oracle fields.
When the user message supplies a reviewer-selected branch partition, paper_claim_ids and counterfactual_claim_ids must use those two complete groups. You may swap the two groups as wholes; never move an individual claim between groups.
If a paper reports only isolated values of a regime condition, such as two temperatures, use that condition as the hidden world selector. Do not expose it as a continuous Player control and do not interpolate between its reported values. Public controls are quantities for which both reported branch equations support arbitrary in-domain queries.
candidate.notes are Player-visible. They may give world-neutral operational guidance but must not restate fixed-condition values, mention historical/counterfactual worlds, a selector, private regime values, branch equations, answer directions, or source identity. Exact common condition statements are inserted only by the deterministic fixed-condition binder.
If the card has no source-reported alternative regime that yields a meaningful relationship-level difference under the same public controls and readouts, return status=not_authorable and drafts=[].
For every readout, provide a relationship target. Worlds must differ in their executable control-response relation, not merely in prose labels or by an additive constant; declared directions must agree with the executable Oracle. Diagnostic conditions should distinguish the worlds within the Player budget. Hidden conditions must be disjoint and spread across the source-supported interior domain.
Use source-derived reporting precision only as interface rounding; never present it as measurement resolution unless the card says so.
The Young double-slit exemplar is useful because its public observations are qualitative, its controls have independent experimental meaning, and one hidden mechanism change propagates predictively. The Brownian exemplar is useful because it defines an ensemble readout precisely and separates time and particle-size relationships. Copy these design principles, not their physics or numbers.
The generated candidate remains a draft. A deterministic filter and human source review decide acceptance.
"""


def _machine_interface_mapping(card: ScienceCard) -> Mapping[str, Any]:
    return {
        "immutable": True,
        "controls": {
            item.name: canonical_science_name(item.name) for item in card.controls
        },
        "readouts": {
            item.name: canonical_science_name(item.name) for item in card.readouts
        },
        "fixed_conditions": {
            item.condition_id: canonical_science_name(item.condition_id)
            for item in card.fixed_conditions
        },
    }


def build_case_draft_request(
    card: ScienceCard,
    *,
    config: Optional[GenerationConfig] = None,
    reviewed_branch_claim_ids: Optional[
        Tuple[Tuple[str, ...], Tuple[str, ...]]
    ] = None,
    retry_artifact_error: Optional[CaseDraftError] = None,
) -> GenerationRequest:
    card = _revalidated_science_card(card, path="$.claims")
    structured_claims = tuple(
        claim.oracle_outputs is not None for claim in card.claims
    )
    if any(structured_claims) and not all(structured_claims):
        raise CaseDraftError(
            "case_draft.mixed_truth_contract",
            "$.claims",
            "a card cannot mix legacy opaque claims with structured claim programs",
        )
    scaffold_oracle = bool(structured_claims) and all(structured_claims)
    schema = case_draft_batch_json_schema(scaffold_oracle=scaffold_oracle)
    card_payload: Mapping[str, Any] = science_card_to_payload(card)
    machine_interface_mapping = _machine_interface_mapping(card)
    user_content = (
        "Private science card; this is the only scientific authority:\n"
        + canonical_json_dumps(card_payload)
        + "\nImmutable CaseDraft machine interface; use mapped values in every "
        "generated machine-interface position while leaving the ScienceCard "
        "above unchanged:\n"
        + canonical_json_dumps(
            {"machine_interface_mapping": machine_interface_mapping}
        )
    )
    if reviewed_branch_claim_ids is not None:
        branch_a, branch_b = reviewed_branch_claim_ids
        user_content += (
            "\nReviewer-selected branch partition; preserve each group intact, "
            "though the two complete groups may swap world labels:\n"
            + canonical_json_dumps(
                {
                    "branch_a_claim_ids": list(branch_a),
                    "branch_b_claim_ids": list(branch_b),
                }
            )
        )
    if retry_artifact_error is not None:
        if not isinstance(retry_artifact_error, CaseDraftError):
            raise ValueError("retry_artifact_error must be a CaseDraftError")
        if retry_artifact_error.code not in RETRYABLE_CASE_DRAFT_ERROR_CODES:
            raise ValueError(
                "retry_artifact_error must be a deterministic schema, "
                "public-lineage, or public-leakage failure"
            )
        user_content += (
            "\nFrozen failure from the one explicitly authorized prior CaseDraft "
            "attempt. Correct only this structural/interface/field-lineage/public-prose error. "
            "All private scientific truth, quantities, source IDs, "
            "branch assignments, conditions, domains, information boundaries, "
            "and Oracle semantics must remain faithful to the unchanged ScienceCard. "
            "For a public-leakage diagnostic, do not preserve the rejected public "
            "phrase: delete it or replace it with a shorter neutral description. "
            "Use the repeated immutable machine_interface_mapping in every machine "
            "interface position; do not rename any ScienceCard ID. Emit line_ranges "
            "as [] in every trace because reviewed locators are filled by deterministic "
            "code, not by the model. Return one complete "
            "CaseDraftBatch JSON object, without commentary:\n"
            + canonical_json_dumps(
                {
                    "case_draft_retry": {
                        "frozen_original_failure": {
                            "code": retry_artifact_error.code,
                            "detail": retry_artifact_error.detail,
                            "path": retry_artifact_error.path,
                        },
                        "machine_interface_mapping": machine_interface_mapping,
                    }
                }
            )
        )
    metadata = {
        "purpose": "temporal_case_authoring",
        "source_mode": "science_card_only",
    }
    if retry_artifact_error is not None:
        metadata["retry_reason"] = retry_artifact_error.code
    return GenerationRequest(
        messages=(
            Message(
                "system",
                _SYSTEM_PROMPT
                + "\nCaseDraftBatch JSON Schema:\n"
                + canonical_json_dumps(schema),
            ),
            Message("user", user_content),
        ),
        response_schema=schema,
        config=config
        or GenerationConfig(max_output_tokens=32768, temperature=0.0, top_p=1.0),
        metadata=metadata,
    )


def build_case_draft_repair_request(
    primary_request: GenerationRequest,
    previous_output: str,
    mechanical_error: CaseDraftError,
    machine_interface_mapping: Mapping[str, Any],
    *,
    attempt_number: int,
) -> GenerationRequest:
    """Build one bounded mechanical repair request.

    The model receives the immediately preceding complete response, its exact
    deterministic diagnostic, the immutable interface mapping, and the same
    schema it saw initially. Scientific validation failures are never routed
    here.
    """

    if primary_request.metadata.get("purpose") != "temporal_case_authoring":
        raise ValueError("primary_request must be a temporal case-authoring request")
    if not isinstance(previous_output, str):
        raise ValueError("previous_output must be text")
    if not isinstance(mechanical_error, CaseDraftError):
        raise ValueError("mechanical_error must be a CaseDraftError")
    if mechanical_error.code not in RETRYABLE_CASE_DRAFT_ERROR_CODES:
        raise ValueError(
            "only a schema, public-lineage, or public-leakage error is repairable"
        )
    if not isinstance(machine_interface_mapping, Mapping):
        raise ValueError("machine_interface_mapping must be a mapping")
    if (
        isinstance(attempt_number, bool)
        or not isinstance(attempt_number, int)
        or attempt_number < 2
        or attempt_number > 4
    ):
        raise ValueError("attempt_number must be between 2 and 4")

    repair_payload = {
        "repair": {
            "instruction": (
                "Return one complete corrected CaseDraftBatch JSON object. This "
                "is a bounded mechanical repair only: change only the field or "
                "fields needed to satisfy the exact schema/interface/field-lineage/"
                "public-leakage error. When the diagnostic names Player-visible "
                "prose, remove or neutrally rephrase only the leaking numeric answer, "
                "formula, direction, private regime, or source identity; do not move "
                "it to another public field. "
                "Preserve all private scientific truth, quantities, source IDs, "
                "branch assignments, conditions, domains, and "
                "information-boundary semantics from the rejected response. A "
                "public-leakage repair may and must omit the rejected public phrase; "
                "that omission does not alter the private truth contract. Only "
                "add, remove, or rename trace fields when the exact field-lineage "
                "diagnostic requires it. Do not add, remove, reinterpret, or improve "
                "scientific content. Emit line_ranges as [] in every trace; reviewed "
                "ScienceCard locators are copied later by deterministic code and must "
                "not be generated. When an "
                "interface identifier violates lower_snake_case, rename that same "
                "interface identifier consistently everywhere it is referenced; "
                "do not rename source ScienceCard IDs. Return JSON only, with no "
                "Markdown or commentary."
            ),
            "machine_interface_mapping": dict(machine_interface_mapping),
            "previous_output": previous_output,
            "validation_error": {
                "code": mechanical_error.code,
                "detail": mechanical_error.detail,
                "path": mechanical_error.path,
            },
            "schema": primary_request.response_schema,
        }
    }
    metadata = dict(primary_request.metadata)
    metadata.update(
        {
            "generation_attempt": attempt_number,
            "repair_reason": mechanical_error.code,
        }
    )
    return GenerationRequest(
        messages=primary_request.messages
        + (Message("user", canonical_json_dumps(repair_payload)),),
        response_schema=primary_request.response_schema,
        config=primary_request.config,
        metadata=metadata,
    )


def _reject_incomplete_case_draft(response: GenerationResponse) -> None:
    reason = response.finish_reason.strip().lower()
    if reason in {
        "length",
        "max_tokens",
        "max_output_tokens",
        "incomplete",
    } or reason.startswith("incomplete:"):
        raise CaseDraftError(
            "case_draft.incomplete_generation",
            "$",
            "provider generation did not complete (%s)" % response.finish_reason,
        )


def _parse_case_draft_response(response: GenerationResponse) -> CaseDraftBatch:
    _reject_incomplete_case_draft(response)
    return parse_case_draft_batch_json(response.text)


def author_case_draft(
    backend: TextGenerationBackend,
    card: ScienceCard,
    *,
    config: Optional[GenerationConfig] = None,
    strict_source_only: bool = True,
    reviewed_branch_claim_ids: Optional[
        Tuple[Tuple[str, ...], Tuple[str, ...]]
    ] = None,
    max_total_attempts: int = 1,
    retry_artifact_error: Optional[CaseDraftError] = None,
) -> CaseDraftResult:
    if (
        isinstance(max_total_attempts, bool)
        or not isinstance(max_total_attempts, int)
        or max_total_attempts < 1
        or max_total_attempts > 4
    ):
        raise ValueError("max_total_attempts must be an integer between 1 and 4")
    request = build_case_draft_request(
        card,
        config=config,
        reviewed_branch_claim_ids=reviewed_branch_claim_ids,
        retry_artifact_error=retry_artifact_error,
    )
    primary_request = request
    machine_interface_mapping = _machine_interface_mapping(card)
    for attempt_count in range(1, max_total_attempts + 1):
        response = backend.generate(request)
        prose_normalizations = []
        relationship_direction_bindings = ()
        condition_partition_bindings = ()
        try:
            batch = _parse_case_draft_response(response)
            batch = bind_reviewed_oracle(
                batch,
                card,
                reviewed_branch_claim_ids=reviewed_branch_claim_ids,
            )
            batch, relationship_direction_bindings = (
                bind_executable_relationship_directions(batch)
            )
            batch = bind_reviewed_fixed_conditions(
                batch,
                card,
                reviewed_branch_claim_ids=reviewed_branch_claim_ids,
            )
            batch, condition_partition_bindings = (
                bind_enumerated_condition_partitions(batch)
            )
            batch = bind_reviewed_lineage(batch, card)
            while True:
                try:
                    validate_case_draft_batch(
                        batch,
                        card,
                        strict_source_only=strict_source_only,
                        reviewed_branch_claim_ids=reviewed_branch_claim_ids,
                    )
                except CaseDraftError as error:
                    compiled = _compile_safe_decorative_prose(batch, error)
                    if compiled is None:
                        raise
                    batch, normalization = compiled
                    prose_normalizations.append(normalization)
                    # A compiler rewrite never establishes validity by itself:
                    # rerun every scientific, source, private-boundary, and
                    # family-level deterministic gate from the beginning.
                    continue
                break
        except CaseDraftError as error:
            if (
                error.code not in RETRYABLE_CASE_DRAFT_ERROR_CODES
                or attempt_count >= max_total_attempts
            ):
                raise
            request = build_case_draft_repair_request(
                primary_request,
                response.text,
                error,
                machine_interface_mapping,
                attempt_number=attempt_count + 1,
            )
            continue
        return CaseDraftResult(
            batch=batch,
            response=response,
            attempt_count=attempt_count,
            prose_normalizations=tuple(prose_normalizations),
            relationship_direction_bindings=relationship_direction_bindings,
            condition_partition_bindings=condition_partition_bindings,
        )
    raise RuntimeError("unreachable CaseDraft authoring state")


__all__ = [
    "CaseDraftBatch",
    "CaseDraftError",
    "CaseDraftResult",
    "ConditionPartitionBinding",
    "CounterfactualDerivation",
    "InformationBoundary",
    "InformationTrace",
    "LineRange",
    "MatchedCaseDraft",
    "PublicFieldTrace",
    "PublicProseNormalization",
    "RelationshipDirectionBinding",
    "RelationshipTarget",
    "EXECUTABLE_ORACLE_STATISTIC",
    "EXECUTABLE_ORACLE_UNCERTAINTY",
    "RETRYABLE_CASE_DRAFT_ERROR_CODES",
    "author_case_draft",
    "bind_enumerated_condition_partitions",
    "bind_executable_relationship_directions",
    "bind_reviewed_fixed_conditions",
    "bind_reviewed_lineage",
    "bind_reviewed_oracle",
    "build_case_draft_repair_request",
    "build_case_draft_request",
    "case_draft_batch_json_schema",
    "case_draft_batch_to_payload",
    "case_draft_to_payload",
    "condition_partition_bindings_to_payload",
    "parse_case_draft_batch_json",
    "parse_case_draft_batch_payload",
    "public_prose_normalizations_to_payload",
    "relationship_direction_bindings_to_payload",
    "validate_case_draft_batch",
]
