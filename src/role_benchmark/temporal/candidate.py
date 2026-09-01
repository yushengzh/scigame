"""Strict data contracts for paper-derived temporal case proposals.

The model may propose zero or more candidate cases for one paper. Parsing
establishes only structural validity; scientific and benchmark eligibility are
decided separately for every candidate by the deterministic filter.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from typing import Any, Dict, Mapping, Optional, Tuple

from role_benchmark.expression import EXPRESSION_OPERATORS


_ROOT_KEYS = {
    "family",
    "title",
    "claim",
    "source",
    "apparatus",
    "background",
    "initial_observations",
    "common_fixed_conditions",
    "controls",
    "readouts",
    "oracle",
    "diagnostic_conditions",
    "hidden_conditions",
    "budget",
    "max_replicates",
    "confidence_threshold",
    "relative_tolerance",
    "notes",
    "counterfactual_change",
}
_ABSTRACTION_KEYS = {"assessment", "candidates"}
_RESOLUTION_KINDS = {"measurement_resolution", "reporting_increment"}
_IDENTIFIER = re.compile(r"^[a-z][a-z0-9_]*$")


class CandidateDecodeError(ValueError):
    """A candidate is not strict JSON or does not match the proposal schema."""

    def __init__(self, code: str, path: str, detail: str) -> None:
        self.code = code
        self.path = path
        self.detail = detail
        super().__init__("%s at %s: %s" % (code, path, detail))


@dataclass(frozen=True)
class TemporalSource:
    citation: str
    journal_doi: str
    arxiv_versioned_id: str
    locator: str
    role: str


@dataclass(frozen=True)
class TemporalApparatus:
    name: str
    description: str


@dataclass(frozen=True)
class TemporalControl:
    name: str
    description: str
    unit: str
    minimum: Optional[float]
    maximum: Optional[float]
    allowed_values: Tuple[float, ...] = ()


@dataclass(frozen=True)
class TemporalFixedCondition:
    condition_id: str
    statement: str


@dataclass(frozen=True)
class TemporalReadout:
    name: str
    description: str
    unit: str
    statistic: str
    uncertainty: str
    resolution: Optional[float]
    resolution_kind: Optional[str]


@dataclass(frozen=True)
class ClosedFormOracle:
    kind: str
    outputs: Mapping[str, Any]
    paper_parameters: Mapping[str, float]
    counterfactual_parameters: Mapping[str, float]
    paper_applicability: Tuple[str, ...]
    counterfactual_applicability: Tuple[str, ...]
    paper_fixed_conditions: Tuple[TemporalFixedCondition, ...]
    counterfactual_fixed_conditions: Tuple[TemporalFixedCondition, ...]


@dataclass(frozen=True)
class TemporalCaseCandidate:
    family: str
    title: str
    claim: str
    source: TemporalSource
    apparatus: TemporalApparatus
    background: str
    initial_observations: Tuple[str, ...]
    common_fixed_conditions: Tuple[TemporalFixedCondition, ...]
    controls: Tuple[TemporalControl, ...]
    readouts: Tuple[TemporalReadout, ...]
    oracle: ClosedFormOracle
    diagnostic_conditions: Tuple[Mapping[str, float], ...]
    hidden_conditions: Tuple[Mapping[str, float], ...]
    budget: int
    max_replicates: int
    confidence_threshold: float
    relative_tolerance: float
    notes: Tuple[str, ...]
    counterfactual_change: str


@dataclass(frozen=True)
class PaperAbstraction:
    """One paper-level assessment and its independently filterable proposals."""

    assessment: str
    candidates: Tuple[TemporalCaseCandidate, ...]


def _object(value: Any, path: str, keys: set[str]) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        raise CandidateDecodeError("candidate.schema", path, "must be an object")
    if set(value) != keys:
        missing = sorted(keys - set(value))
        extra = sorted(set(value) - keys)
        raise CandidateDecodeError(
            "candidate.schema",
            path,
            "keys must match exactly (missing=%s, extra=%s)" % (missing, extra),
        )
    return value


def _text(value: Any, path: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise CandidateDecodeError(
            "candidate.schema", path, "must be non-empty text"
        )
    return value.strip()


def _map_key(value: Any, path: str) -> str:
    if not isinstance(value, str) or not value:
        raise CandidateDecodeError(
            "candidate.schema", path, "object keys must be non-empty text"
        )
    if value != value.strip():
        raise CandidateDecodeError(
            "candidate.schema", path, "object keys cannot have surrounding whitespace"
        )
    return value


def _identifier(value: Any, path: str) -> str:
    result = _text(value, path)
    if _IDENTIFIER.fullmatch(result) is None:
        raise CandidateDecodeError(
            "candidate.schema", path, "must be lower_snake_case"
        )
    return result


def _number(value: Any, path: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise CandidateDecodeError("candidate.schema", path, "must be a number")
    try:
        result = float(value)
    except OverflowError as exc:
        raise CandidateDecodeError(
            "candidate.schema", path, "must be a finite number"
        ) from exc
    if not math.isfinite(result):
        raise CandidateDecodeError(
            "candidate.schema", path, "must be a finite number"
        )
    return result


def _optional_number(value: Any, path: str) -> Optional[float]:
    if value is None:
        return None
    return _number(value, path)


def _number_array(value: Any, path: str) -> Tuple[float, ...]:
    if not isinstance(value, list):
        raise CandidateDecodeError("candidate.schema", path, "must be an array")
    return tuple(
        _number(item, "%s[%d]" % (path, index))
        for index, item in enumerate(value)
    )


def _integer(value: Any, path: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise CandidateDecodeError("candidate.schema", path, "must be an integer")
    return value


def _text_array(value: Any, path: str) -> Tuple[str, ...]:
    if not isinstance(value, list):
        raise CandidateDecodeError("candidate.schema", path, "must be an array")
    return tuple(_text(item, "%s[%d]" % (path, index)) for index, item in enumerate(value))


def _fixed_conditions(
    value: Any, path: str
) -> Tuple[TemporalFixedCondition, ...]:
    if not isinstance(value, list):
        raise CandidateDecodeError("candidate.schema", path, "must be an array")
    result = []
    for index, raw in enumerate(value):
        item_path = "%s[%d]" % (path, index)
        item = _object(raw, item_path, {"condition_id", "statement"})
        result.append(
            TemporalFixedCondition(
                condition_id=_identifier(
                    item["condition_id"], item_path + ".condition_id"
                ),
                statement=_text(item["statement"], item_path + ".statement"),
            )
        )
    identifiers = [item.condition_id for item in result]
    if len(set(identifiers)) != len(identifiers):
        raise CandidateDecodeError(
            "candidate.schema", path, "condition_id values must be unique"
        )
    return tuple(result)


def _number_map(value: Any, path: str) -> Dict[str, float]:
    if not isinstance(value, dict):
        raise CandidateDecodeError("candidate.schema", path, "must be an object")
    result: Dict[str, float] = {}
    for key, item in value.items():
        name = _map_key(key, "%s.<key>" % path)
        result[name] = _number(item, "%s.%s" % (path, name))
    return result


def _expression(value: Any, path: str) -> Any:
    if isinstance(value, bool):
        raise CandidateDecodeError(
            "candidate.schema", path, "boolean is not an expression"
        )
    if isinstance(value, (int, float)):
        return _number(value, path)
    if not isinstance(value, dict):
        raise CandidateDecodeError(
            "candidate.schema", path, "must be a number or expression object"
        )
    if set(value) in ({"var"}, {"param"}):
        key = next(iter(value))
        return {key: _text(value[key], "%s.%s" % (path, key))}
    _object(value, path, {"op", "args"})
    operator = _text(value["op"], "%s.op" % path)
    if operator not in EXPRESSION_OPERATORS:
        raise CandidateDecodeError(
            "candidate.schema", "%s.op" % path, "unsupported expression operator"
        )
    if not isinstance(value["args"], list):
        raise CandidateDecodeError(
            "candidate.schema", "%s.args" % path, "must be an array"
        )
    return {
        "op": operator,
        "args": [
            _expression(item, "%s.args[%d]" % (path, index))
            for index, item in enumerate(value["args"])
        ],
    }


def _conditions(value: Any, path: str) -> Tuple[Mapping[str, float], ...]:
    if not isinstance(value, list):
        raise CandidateDecodeError("candidate.schema", path, "must be an array")
    return tuple(
        _number_map(item, "%s[%d]" % (path, index))
        for index, item in enumerate(value)
    )


def parse_candidate_payload(payload: Any) -> TemporalCaseCandidate:
    """Parse a decoded JSON value, rejecting every unknown or missing field."""

    root = _object(payload, "$", _ROOT_KEYS)
    source_raw = _object(
        root["source"],
        "$.source",
        {"citation", "journal_doi", "arxiv_versioned_id", "locator", "role"},
    )
    apparatus_raw = _object(
        root["apparatus"], "$.apparatus", {"name", "description"}
    )

    controls_raw = root["controls"]
    if not isinstance(controls_raw, list):
        raise CandidateDecodeError("candidate.schema", "$.controls", "must be an array")
    controls = []
    for index, value in enumerate(controls_raw):
        path = "$.controls[%d]" % index
        legacy_keys = {"name", "description", "unit", "minimum", "maximum"}
        current_keys = legacy_keys | {"allowed_values"}
        if isinstance(value, dict) and set(value) == legacy_keys:
            # Existing warm-up artifacts encoded only continuous intervals.
            # Keep them readable while all newly serialized candidates use the
            # explicit interval/enumeration union below.
            item = value
            allowed_values: Tuple[float, ...] = ()
        else:
            item = _object(value, path, current_keys)
            allowed_values = _number_array(
                item["allowed_values"], path + ".allowed_values"
            )
        controls.append(
            TemporalControl(
                name=_text(item["name"], path + ".name"),
                description=_text(item["description"], path + ".description"),
                unit=_text(item["unit"], path + ".unit"),
                minimum=_optional_number(item["minimum"], path + ".minimum"),
                maximum=_optional_number(item["maximum"], path + ".maximum"),
                allowed_values=allowed_values,
            )
        )

    readouts_raw = root["readouts"]
    if not isinstance(readouts_raw, list):
        raise CandidateDecodeError("candidate.schema", "$.readouts", "must be an array")
    readouts = []
    for index, value in enumerate(readouts_raw):
        path = "$.readouts[%d]" % index
        item = _object(
            value,
            path,
            {
                "name",
                "description",
                "unit",
                "statistic",
                "uncertainty",
                "resolution",
                "resolution_kind",
            },
        )
        resolution_raw = item["resolution"]
        resolution_kind_raw = item["resolution_kind"]
        if (resolution_raw is None) != (resolution_kind_raw is None):
            raise CandidateDecodeError(
                "candidate.schema",
                path,
                "resolution and resolution_kind must both be null or both be set",
            )
        resolution = None
        resolution_kind = None
        if resolution_raw is not None:
            resolution = _number(resolution_raw, path + ".resolution")
            resolution_kind = _text(
                resolution_kind_raw, path + ".resolution_kind"
            )
            if resolution_kind not in _RESOLUTION_KINDS:
                raise CandidateDecodeError(
                    "candidate.schema",
                    path + ".resolution_kind",
                    "must be measurement_resolution or reporting_increment",
                )
        readouts.append(
            TemporalReadout(
                name=_text(item["name"], path + ".name"),
                description=_text(item["description"], path + ".description"),
                unit=_text(item["unit"], path + ".unit"),
                statistic=_text(item["statistic"], path + ".statistic"),
                uncertainty=_text(item["uncertainty"], path + ".uncertainty"),
                resolution=resolution,
                resolution_kind=resolution_kind,
            )
        )

    oracle_raw = _object(
        root["oracle"],
        "$.oracle",
        {
            "kind",
            "outputs",
            "paper_parameters",
            "counterfactual_parameters",
            "paper_applicability",
            "counterfactual_applicability",
            "paper_fixed_conditions",
            "counterfactual_fixed_conditions",
        },
    )
    outputs_raw = oracle_raw["outputs"]
    if not isinstance(outputs_raw, dict):
        raise CandidateDecodeError(
            "candidate.schema", "$.oracle.outputs", "must be an object"
        )
    outputs = {
        _map_key(name, "$.oracle.outputs.<key>"): _expression(
            expression, "$.oracle.outputs.%s" % name
        )
        for name, expression in outputs_raw.items()
    }

    return TemporalCaseCandidate(
        family=_text(root["family"], "$.family"),
        title=_text(root["title"], "$.title"),
        claim=_text(root["claim"], "$.claim"),
        source=TemporalSource(
            citation=_text(source_raw["citation"], "$.source.citation"),
            journal_doi=_text(source_raw["journal_doi"], "$.source.journal_doi"),
            arxiv_versioned_id=_text(
                source_raw["arxiv_versioned_id"],
                "$.source.arxiv_versioned_id",
            ),
            locator=_text(source_raw["locator"], "$.source.locator"),
            role=_text(source_raw["role"], "$.source.role"),
        ),
        apparatus=TemporalApparatus(
            name=_text(apparatus_raw["name"], "$.apparatus.name"),
            description=_text(
                apparatus_raw["description"], "$.apparatus.description"
            ),
        ),
        background=_text(root["background"], "$.background"),
        initial_observations=_text_array(
            root["initial_observations"], "$.initial_observations"
        ),
        common_fixed_conditions=_fixed_conditions(
            root["common_fixed_conditions"], "$.common_fixed_conditions"
        ),
        controls=tuple(controls),
        readouts=tuple(readouts),
        oracle=ClosedFormOracle(
            kind=_text(oracle_raw["kind"], "$.oracle.kind"),
            outputs=outputs,
            paper_parameters=_number_map(
                oracle_raw["paper_parameters"], "$.oracle.paper_parameters"
            ),
            counterfactual_parameters=_number_map(
                oracle_raw["counterfactual_parameters"],
                "$.oracle.counterfactual_parameters",
            ),
            paper_applicability=_text_array(
                oracle_raw["paper_applicability"],
                "$.oracle.paper_applicability",
            ),
            counterfactual_applicability=_text_array(
                oracle_raw["counterfactual_applicability"],
                "$.oracle.counterfactual_applicability",
            ),
            paper_fixed_conditions=_fixed_conditions(
                oracle_raw["paper_fixed_conditions"],
                "$.oracle.paper_fixed_conditions",
            ),
            counterfactual_fixed_conditions=_fixed_conditions(
                oracle_raw["counterfactual_fixed_conditions"],
                "$.oracle.counterfactual_fixed_conditions",
            ),
        ),
        diagnostic_conditions=_conditions(
            root["diagnostic_conditions"], "$.diagnostic_conditions"
        ),
        hidden_conditions=_conditions(root["hidden_conditions"], "$.hidden_conditions"),
        budget=_integer(root["budget"], "$.budget"),
        max_replicates=_integer(root["max_replicates"], "$.max_replicates"),
        confidence_threshold=_number(
            root["confidence_threshold"], "$.confidence_threshold"
        ),
        relative_tolerance=_number(
            root["relative_tolerance"], "$.relative_tolerance"
        ),
        notes=_text_array(root["notes"], "$.notes"),
        counterfactual_change=_text(
            root["counterfactual_change"], "$.counterfactual_change"
        ),
    )


def parse_candidate_json(text: str) -> TemporalCaseCandidate:
    """Decode exactly one JSON object; Markdown fences and trailing text fail."""

    return parse_candidate_payload(_decode_strict_json(text))


def _decode_strict_json(text: str) -> Any:
    """Decode one strict JSON value and reject duplicate object keys."""

    if not isinstance(text, str):
        raise CandidateDecodeError("candidate.invalid_json", "$", "input must be text")

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
        payload = json.loads(
            text,
            parse_constant=reject_constant,
            object_pairs_hook=unique_object,
        )
    except (json.JSONDecodeError, ValueError) as exc:
        raise CandidateDecodeError(
            "candidate.invalid_json", "$", "expected exactly one strict JSON value"
        ) from exc
    return payload


def parse_paper_abstraction_payload(payload: Any) -> PaperAbstraction:
    """Parse one paper-level batch without treating its assessment as eligibility."""

    root = _object(payload, "$", _ABSTRACTION_KEYS)
    candidates_raw = root["candidates"]
    if not isinstance(candidates_raw, list):
        raise CandidateDecodeError(
            "candidate.schema", "$.candidates", "must be an array"
        )
    candidates = []
    family_paths: Dict[str, str] = {}
    for index, item in enumerate(candidates_raw):
        path = "$.candidates[%d]" % index
        try:
            candidate = parse_candidate_payload(item)
        except CandidateDecodeError as exc:
            nested_path = path if exc.path == "$" else path + exc.path[1:]
            raise CandidateDecodeError(exc.code, nested_path, exc.detail) from exc

        family_key = candidate.family.casefold()
        if family_key in family_paths:
            raise CandidateDecodeError(
                "abstraction.duplicate_family",
                path + ".family",
                "duplicates family declared at %s" % family_paths[family_key],
            )
        family_paths[family_key] = path + ".family"
        candidates.append(candidate)

    return PaperAbstraction(
        assessment=_text(root["assessment"], "$.assessment"),
        candidates=tuple(candidates),
    )


def parse_paper_abstraction_json(text: str) -> PaperAbstraction:
    """Decode one strict paper abstraction with zero or more candidates."""

    return parse_paper_abstraction_payload(_decode_strict_json(text))


def candidate_to_payload(candidate: TemporalCaseCandidate) -> Mapping[str, Any]:
    """Return the candidate's strict JSON representation."""

    return {
        "family": candidate.family,
        "title": candidate.title,
        "claim": candidate.claim,
        "source": {
            "citation": candidate.source.citation,
            "journal_doi": candidate.source.journal_doi,
            "arxiv_versioned_id": candidate.source.arxiv_versioned_id,
            "locator": candidate.source.locator,
            "role": candidate.source.role,
        },
        "apparatus": {
            "name": candidate.apparatus.name,
            "description": candidate.apparatus.description,
        },
        "background": candidate.background,
        "initial_observations": list(candidate.initial_observations),
        "common_fixed_conditions": [
            {
                "condition_id": item.condition_id,
                "statement": item.statement,
            }
            for item in candidate.common_fixed_conditions
        ],
        "controls": [
            {
                "name": item.name,
                "description": item.description,
                "unit": item.unit,
                "minimum": item.minimum,
                "maximum": item.maximum,
                "allowed_values": list(item.allowed_values),
            }
            for item in candidate.controls
        ],
        "readouts": [
            {
                "name": item.name,
                "description": item.description,
                "unit": item.unit,
                "statistic": item.statistic,
                "uncertainty": item.uncertainty,
                "resolution": item.resolution,
                "resolution_kind": item.resolution_kind,
            }
            for item in candidate.readouts
        ],
        "oracle": {
            "kind": candidate.oracle.kind,
            "outputs": dict(candidate.oracle.outputs),
            "paper_parameters": dict(candidate.oracle.paper_parameters),
            "counterfactual_parameters": dict(
                candidate.oracle.counterfactual_parameters
            ),
            "paper_applicability": list(candidate.oracle.paper_applicability),
            "counterfactual_applicability": list(
                candidate.oracle.counterfactual_applicability
            ),
            "paper_fixed_conditions": [
                {
                    "condition_id": item.condition_id,
                    "statement": item.statement,
                }
                for item in candidate.oracle.paper_fixed_conditions
            ],
            "counterfactual_fixed_conditions": [
                {
                    "condition_id": item.condition_id,
                    "statement": item.statement,
                }
                for item in candidate.oracle.counterfactual_fixed_conditions
            ],
        },
        "diagnostic_conditions": [dict(item) for item in candidate.diagnostic_conditions],
        "hidden_conditions": [dict(item) for item in candidate.hidden_conditions],
        "budget": candidate.budget,
        "max_replicates": candidate.max_replicates,
        "confidence_threshold": candidate.confidence_threshold,
        "relative_tolerance": candidate.relative_tolerance,
        "notes": list(candidate.notes),
        "counterfactual_change": candidate.counterfactual_change,
    }


def paper_abstraction_to_payload(abstraction: PaperAbstraction) -> Mapping[str, Any]:
    """Return the abstraction's strict JSON representation."""

    return {
        "assessment": abstraction.assessment,
        "candidates": [candidate_to_payload(item) for item in abstraction.candidates],
    }


def temporal_candidate_json_schema() -> Mapping[str, Any]:
    """Return the provider-facing strict JSON Schema for one proposal."""

    identifier: Dict[str, Any] = {
        "type": "string",
        "pattern": "^[a-z][a-z0-9_]*$",
    }
    expression: Dict[str, Any] = {
        "anyOf": [
            {"type": "number"},
            {
                "type": "object",
                "properties": {"var": identifier},
                "required": ["var"],
                "additionalProperties": False,
            },
            {
                "type": "object",
                "properties": {"param": identifier},
                "required": ["param"],
                "additionalProperties": False,
            },
            {
                "type": "object",
                "properties": {
                    "op": {"type": "string", "enum": list(EXPRESSION_OPERATORS)},
                    "args": {
                        "type": "array",
                        "items": {"$ref": "#/$defs/expression_template"},
                    },
                },
                "required": ["op", "args"],
                "additionalProperties": False,
            },
        ]
    }
    control = {
        "type": "object",
        "properties": {
            "name": identifier,
            "description": {"type": "string", "minLength": 1},
            "unit": {"type": "string", "minLength": 1},
            "minimum": {"anyOf": [{"type": "number"}, {"type": "null"}]},
            "maximum": {"anyOf": [{"type": "number"}, {"type": "null"}]},
            "allowed_values": {
                "type": "array",
                "items": {"type": "number"},
                "uniqueItems": True,
            },
        },
        "required": [
            "name",
            "description",
            "unit",
            "minimum",
            "maximum",
            "allowed_values",
        ],
        "additionalProperties": False,
        "oneOf": [
            {
                "properties": {
                    "minimum": {"type": "number"},
                    "maximum": {"type": "number"},
                    "allowed_values": {"type": "array", "maxItems": 0},
                }
            },
            {
                "properties": {
                    "minimum": {"type": "null"},
                    "maximum": {"type": "null"},
                    "allowed_values": {
                        "type": "array",
                        "items": {"type": "number"},
                        "minItems": 2,
                        "uniqueItems": True,
                    },
                }
            },
        ],
    }
    readout = {
        "type": "object",
        "properties": {
            "name": identifier,
            "description": {"type": "string", "minLength": 1},
            "unit": {"type": "string", "minLength": 1},
            "statistic": {"type": "string", "minLength": 1},
            "uncertainty": {"type": "string", "minLength": 1},
            "resolution": {
                "anyOf": [
                    {"type": "number", "exclusiveMinimum": 0},
                    {"type": "null"},
                ]
            },
            "resolution_kind": {
                "anyOf": [
                    {
                        "type": "string",
                        "enum": sorted(_RESOLUTION_KINDS),
                    },
                    {"type": "null"},
                ]
            },
        },
        "required": [
            "name",
            "description",
            "unit",
            "statistic",
            "uncertainty",
            "resolution",
            "resolution_kind",
        ],
        "additionalProperties": False,
        "oneOf": [
            {
                "properties": {
                    "resolution": {
                        "type": "number",
                        "exclusiveMinimum": 0,
                    },
                    "resolution_kind": {
                        "type": "string",
                        "enum": sorted(_RESOLUTION_KINDS),
                    },
                }
            },
            {
                "properties": {
                    "resolution": {"type": "null"},
                    "resolution_kind": {"type": "null"},
                }
            },
        ],
    }
    fixed_condition = {
        "type": "object",
        "properties": {
            "condition_id": identifier,
            "statement": {"type": "string", "minLength": 1},
        },
        "required": ["condition_id", "statement"],
        "additionalProperties": False,
    }
    source = {
        "type": "object",
        "properties": {
            name: {"type": "string", "minLength": 1}
            for name in (
                "citation",
                "journal_doi",
                "arxiv_versioned_id",
                "locator",
                "role",
            )
        },
        "required": [
            "citation",
            "journal_doi",
            "arxiv_versioned_id",
            "locator",
            "role",
        ],
        "additionalProperties": False,
    }
    apparatus = {
        "type": "object",
        "properties": {
            "name": identifier,
            "description": {"type": "string", "minLength": 1},
        },
        "required": ["name", "description"],
        "additionalProperties": False,
    }
    number_map = {
        "type": "object",
        "propertyNames": identifier,
        "additionalProperties": {"type": "number"},
        "minProperties": 1,
    }
    condition = {
        "type": "object",
        "propertyNames": identifier,
        "additionalProperties": {"type": "number"},
        "minProperties": 1,
    }
    properties: Dict[str, Any] = {
        "family": identifier,
        "title": {"type": "string", "minLength": 1},
        "claim": {"type": "string", "minLength": 1},
        "source": source,
        "apparatus": apparatus,
        "background": {"type": "string", "minLength": 1},
        "initial_observations": {
            "type": "array",
            "items": {"type": "string", "minLength": 1},
            "minItems": 1,
        },
        "common_fixed_conditions": {
            "type": "array",
            "items": fixed_condition,
        },
        "controls": {"type": "array", "items": control, "minItems": 1, "maxItems": 5},
        "readouts": {"type": "array", "items": readout, "minItems": 1, "maxItems": 2},
        "oracle": {
            "type": "object",
            "properties": {
                "kind": {"const": "closed_form"},
                "outputs": {
                    "type": "object",
                    "propertyNames": identifier,
                    "additionalProperties": {"$ref": "#/$defs/expression_template"},
                    "minProperties": 1,
                    "maxProperties": 2,
                },
                "paper_parameters": number_map,
                "counterfactual_parameters": number_map,
                "paper_applicability": {
                    "type": "array",
                    "items": {"type": "string", "minLength": 1},
                    "minItems": 1,
                    "uniqueItems": True,
                },
                "counterfactual_applicability": {
                    "type": "array",
                    "items": {"type": "string", "minLength": 1},
                    "minItems": 1,
                    "uniqueItems": True,
                },
                "paper_fixed_conditions": {
                    "type": "array",
                    "items": fixed_condition,
                },
                "counterfactual_fixed_conditions": {
                    "type": "array",
                    "items": fixed_condition,
                },
            },
            "required": [
                "kind",
                "outputs",
                "paper_parameters",
                "counterfactual_parameters",
                "paper_applicability",
                "counterfactual_applicability",
                "paper_fixed_conditions",
                "counterfactual_fixed_conditions",
            ],
            "additionalProperties": False,
        },
        "diagnostic_conditions": {
            "type": "array",
            "items": condition,
            "minItems": 1,
        },
        "hidden_conditions": {"type": "array", "items": condition, "minItems": 1},
        "budget": {"type": "integer", "minimum": 1},
        "max_replicates": {"type": "integer", "minimum": 1},
        "confidence_threshold": {"type": "number", "exclusiveMinimum": 0, "maximum": 1},
        "relative_tolerance": {"type": "number", "exclusiveMinimum": 0, "exclusiveMaximum": 1},
        "notes": {"type": "array", "items": {"type": "string", "minLength": 1}},
        "counterfactual_change": {"type": "string", "minLength": 1},
    }
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "properties": properties,
        "required": list(properties),
        "additionalProperties": False,
        "$defs": {"expression_template": expression},
    }


def temporal_paper_abstraction_json_schema() -> Mapping[str, Any]:
    """Return the strict provider-facing schema for one paper abstraction."""

    candidate_schema = dict(temporal_candidate_json_schema())
    candidate_schema.pop("$schema")
    candidate_definitions = candidate_schema.pop("$defs")
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "properties": {
            "assessment": {"type": "string", "minLength": 1},
            "candidates": {
                "type": "array",
                "items": {"$ref": "#/$defs/temporal_case_candidate"},
                "minItems": 0,
            },
        },
        "required": ["assessment", "candidates"],
        "additionalProperties": False,
        "$defs": {
            **candidate_definitions,
            "temporal_case_candidate": candidate_schema,
        },
    }


__all__ = [
    "CandidateDecodeError",
    "ClosedFormOracle",
    "PaperAbstraction",
    "TemporalApparatus",
    "TemporalCaseCandidate",
    "TemporalControl",
    "TemporalFixedCondition",
    "TemporalReadout",
    "TemporalSource",
    "candidate_to_payload",
    "paper_abstraction_to_payload",
    "parse_candidate_json",
    "parse_candidate_payload",
    "parse_paper_abstraction_json",
    "parse_paper_abstraction_payload",
    "temporal_candidate_json_schema",
    "temporal_paper_abstraction_json_schema",
]
