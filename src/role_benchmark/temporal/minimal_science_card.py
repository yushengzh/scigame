"""Minimal source-supported representation for Temporal case admission.

The authoring model extracts only one quantitative relation and direct source
line ranges. Task budgets, experiment conditions, public text, and provenance
mappings are absent; deterministic code derives them after source review.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from typing import Any, Dict, Mapping, Optional, Tuple

from role_benchmark.expression import (
    EXPRESSION_OPERATOR_ARITIES,
    EXPRESSION_OPERATORS,
    ExpressionError,
    validate_expression_program,
)

from .arxiv import parse_versioned_arxiv_id
from .census import canonicalize_doi
from .science_card import ScienceSource


MINIMAL_SCIENCE_CARD_SCHEMA = "role_benchmark.minimal_science_card.v1"
_IDENTIFIER = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")
_DOMAIN_KINDS = {"continuous_interval", "numeric_values"}
_STRUCTURAL_LITERALS = (0.0, 1.0)


class MinimalScienceCardError(ValueError):
    """A minimal ScienceCard is not strict, linked, or executable."""

    def __init__(self, code: str, path: str, detail: str) -> None:
        self.code = code
        self.path = path
        self.detail = detail
        super().__init__("%s at %s: %s" % (code, path, detail))


@dataclass(frozen=True)
class MinimalAnchor:
    line_start: int
    line_end: int


@dataclass(frozen=True)
class MinimalParameter:
    name: str
    value: float
    unit: str
    anchors: Tuple[MinimalAnchor, ...]


@dataclass(frozen=True)
class MinimalControl:
    name: str
    definition: str
    unit: str
    anchors: Tuple[MinimalAnchor, ...]


@dataclass(frozen=True)
class MinimalReadout:
    name: str
    definition: str
    unit: str
    anchors: Tuple[MinimalAnchor, ...]


@dataclass(frozen=True)
class MinimalControlDomain:
    control_name: str
    domain_kind: str
    minimum: Optional[float]
    maximum: Optional[float]
    allowed_values: Tuple[float, ...]
    anchors: Tuple[MinimalAnchor, ...]


@dataclass(frozen=True)
class MinimalApplicability:
    statement: str
    anchors: Tuple[MinimalAnchor, ...]


@dataclass(frozen=True)
class MinimalDomain:
    controls: Tuple[MinimalControlDomain, ...]
    applicability: Tuple[MinimalApplicability, ...]


@dataclass(frozen=True)
class MinimalQuantitativeRelation:
    """The six fields that may be authored by the extraction model."""

    formula: Mapping[str, Any]
    parameters: Tuple[MinimalParameter, ...]
    controls: Tuple[MinimalControl, ...]
    readouts: Tuple[MinimalReadout, ...]
    domain: MinimalDomain
    anchors: Tuple[MinimalAnchor, ...]


@dataclass(frozen=True)
class MinimalScienceCard:
    """Caller-supplied source identity plus zero or one extracted relation."""

    source: ScienceSource
    relations: Tuple[MinimalQuantitativeRelation, ...]


def _error(path: str, detail: str, code: str = "minimal_science_card.schema") -> None:
    raise MinimalScienceCardError(code, path, detail)


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
        _error(path, "must be an ASCII identifier")
    return result


def _number(value: Any, path: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        _error(path, "must be a number")
    result = float(value)
    if not math.isfinite(result):
        _error(path, "must be finite")
    return result


def _optional_number(value: Any, path: str) -> Optional[float]:
    return None if value is None else _number(value, path)


def _anchors(value: Any, path: str) -> Tuple[MinimalAnchor, ...]:
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
            _error(item_path, "line range must satisfy 1 <= line_start <= line_end")
        result.append(MinimalAnchor(line_start=start, line_end=end))
    if not result:
        _error(path, "must contain at least one source line range")
    return tuple(result)


def _expression(value: Any, path: str) -> Any:
    if isinstance(value, bool):
        _error(path, "boolean is not an expression")
    if isinstance(value, (int, float)):
        number = _number(value, path)
        if number not in _STRUCTURAL_LITERALS:
            _error(
                path,
                "numeric literals are limited to structural zero and one; "
                "represent other source constants as anchored parameters",
            )
        return number
    if not isinstance(value, dict):
        _error(path, "must be a number or expression object")
    if set(value) in ({"var"}, {"param"}):
        key = next(iter(value))
        return {key: _identifier(value[key], path + "." + key)}
    item = _object(value, path, {"op", "args"})
    operator = _text(item["op"], path + ".op")
    if operator not in EXPRESSION_OPERATORS:
        _error(path + ".op", "unsupported expression operator")
    return {
        "op": operator,
        "args": [
            _expression(argument, "%s.args[%d]" % (path, index))
            for index, argument in enumerate(_array(item["args"], path + ".args"))
        ],
    }


def _formula(value: Any, path: str) -> Mapping[str, Any]:
    item = _object(value, path, {"outputs"})
    raw_outputs = item["outputs"]
    if not isinstance(raw_outputs, dict) or not raw_outputs:
        _error(path + ".outputs", "must be a non-empty object")
    return {
        _identifier(name, path + ".outputs.<key>"): _expression(
            expression, "%s.outputs.%s" % (path, name)
        )
        for name, expression in raw_outputs.items()
    }


def _unique_names(values: Tuple[str, ...], path: str) -> None:
    if len(set(values)) != len(values):
        _error(path, "names must be unique")
    lowered = tuple(value.lower() for value in values)
    if len(set(lowered)) != len(lowered):
        _error(path, "names must remain unique after lowercasing")


def _symbols(value: Any, variables: set[str], parameters: set[str]) -> None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return
    if "var" in value:
        variables.add(value["var"])
        return
    if "param" in value:
        parameters.add(value["param"])
        return
    for argument in value["args"]:
        _symbols(argument, variables, parameters)


def _readout_limit(max_readouts: int) -> int:
    if isinstance(max_readouts, bool) or not isinstance(max_readouts, int) or not 1 <= max_readouts <= 8:
        raise ValueError("max_readouts must be an integer between one and eight")
    return max_readouts


def _validate_relation(relation: MinimalQuantitativeRelation, path: str, *, max_readouts: int = 2) -> None:
    if not 1 <= len(relation.controls) <= 5:
        _error(path + ".controls", "must contain between one and five controls")
    if not 1 <= len(relation.readouts) <= max_readouts:
        _error(path + ".readouts", "must contain one or two readouts" if max_readouts == 2
               else "must contain between one and %d readouts" % max_readouts)
    parameter_names = tuple(item.name for item in relation.parameters)
    control_names = tuple(item.name for item in relation.controls)
    readout_names = tuple(item.name for item in relation.readouts)
    domain_names = tuple(item.control_name for item in relation.domain.controls)
    _unique_names(parameter_names, path + ".parameters")
    _unique_names(control_names, path + ".controls")
    _unique_names(readout_names, path + ".readouts")
    _unique_names(domain_names, path + ".domain.controls")
    named_sets = {
        "parameters": set(name.lower() for name in parameter_names),
        "controls": set(name.lower() for name in control_names),
        "readouts": set(name.lower() for name in readout_names),
    }
    if (
        named_sets["parameters"] & named_sets["controls"]
        or named_sets["parameters"] & named_sets["readouts"]
        or named_sets["controls"] & named_sets["readouts"]
    ):
        _error(
            path,
            "parameter, control, and readout names must be mutually distinct",
        )
    if set(domain_names) != set(control_names):
        _error(path + ".domain.controls", "must name every control exactly once")

    try:
        validate_expression_program(
            {"outputs": relation.formula},
            allowed_variables=control_names,
            allowed_parameters=parameter_names,
            allowed_numeric_literals=_STRUCTURAL_LITERALS,
            required_outputs=readout_names,
        )
    except ExpressionError as exc:
        _error(path + ".formula.outputs", str(exc))

    used_variables: set[str] = set()
    used_parameters: set[str] = set()
    for expression in relation.formula.values():
        _symbols(expression, used_variables, used_parameters)
    if used_variables != set(control_names):
        _error(path + ".controls", "every declared control must occur in the formula")
    if used_parameters != set(parameter_names):
        _error(path + ".parameters", "every declared parameter must occur in the formula")


def _decode_provider_payload(payload: Any, *, max_readouts: int = 2) -> Tuple[MinimalQuantitativeRelation, ...]:
    root = _object(payload, "$", {"relations"})
    raw_relations = _array(root["relations"], "$.relations")
    if len(raw_relations) > 1:
        _error("$.relations", "must contain at most one quantitative relation")
    relations = []
    for relation_index, raw in enumerate(raw_relations):
        path = "$.relations[%d]" % relation_index
        item = _object(
            raw,
            path,
            {"formula", "parameters", "controls", "readouts", "domain", "anchors"},
        )

        parameters = []
        for index, raw_parameter in enumerate(
            _array(item["parameters"], path + ".parameters")
        ):
            parameter_path = "%s.parameters[%d]" % (path, index)
            parameter = _object(
                raw_parameter,
                parameter_path,
                {"name", "value", "unit", "anchors"},
            )
            parameters.append(
                MinimalParameter(
                    name=_identifier(parameter["name"], parameter_path + ".name"),
                    value=_number(parameter["value"], parameter_path + ".value"),
                    unit=_text(parameter["unit"], parameter_path + ".unit"),
                    anchors=_anchors(parameter["anchors"], parameter_path + ".anchors"),
                )
            )

        controls = []
        for index, raw_control in enumerate(_array(item["controls"], path + ".controls")):
            control_path = "%s.controls[%d]" % (path, index)
            control = _object(
                raw_control,
                control_path,
                {"name", "definition", "unit", "anchors"},
            )
            controls.append(
                MinimalControl(
                    name=_identifier(control["name"], control_path + ".name"),
                    definition=_text(control["definition"], control_path + ".definition"),
                    unit=_text(control["unit"], control_path + ".unit"),
                    anchors=_anchors(control["anchors"], control_path + ".anchors"),
                )
            )

        readouts = []
        for index, raw_readout in enumerate(_array(item["readouts"], path + ".readouts")):
            readout_path = "%s.readouts[%d]" % (path, index)
            readout = _object(
                raw_readout,
                readout_path,
                {"name", "definition", "unit", "anchors"},
            )
            readouts.append(
                MinimalReadout(
                    name=_identifier(readout["name"], readout_path + ".name"),
                    definition=_text(readout["definition"], readout_path + ".definition"),
                    unit=_text(readout["unit"], readout_path + ".unit"),
                    anchors=_anchors(readout["anchors"], readout_path + ".anchors"),
                )
            )

        domain_raw = _object(
            item["domain"],
            path + ".domain",
            {"controls", "applicability"},
        )
        control_domains = []
        for index, raw_domain in enumerate(
            _array(domain_raw["controls"], path + ".domain.controls")
        ):
            domain_path = "%s.domain.controls[%d]" % (path, index)
            domain = _object(
                raw_domain,
                domain_path,
                {
                    "control_name",
                    "domain_kind",
                    "minimum",
                    "maximum",
                    "allowed_values",
                    "anchors",
                },
            )
            kind = _text(domain["domain_kind"], domain_path + ".domain_kind")
            if kind not in _DOMAIN_KINDS:
                _error(
                    domain_path + ".domain_kind",
                    "must be continuous_interval or numeric_values",
                )
            minimum = _optional_number(domain["minimum"], domain_path + ".minimum")
            maximum = _optional_number(domain["maximum"], domain_path + ".maximum")
            allowed_values = tuple(
                _number(value, "%s.allowed_values[%d]" % (domain_path, value_index))
                for value_index, value in enumerate(
                    _array(domain["allowed_values"], domain_path + ".allowed_values")
                )
            )
            if kind == "continuous_interval":
                if minimum is None or maximum is None or minimum >= maximum:
                    _error(domain_path, "continuous_interval requires minimum < maximum")
                if allowed_values:
                    _error(
                        domain_path + ".allowed_values",
                        "must be empty for continuous_interval",
                    )
            else:
                if minimum is not None or maximum is not None:
                    _error(
                        domain_path,
                        "numeric_values requires null minimum and maximum",
                    )
                if len(allowed_values) < 2 or len(set(allowed_values)) != len(
                    allowed_values
                ):
                    _error(
                        domain_path + ".allowed_values",
                        "must contain at least two unique numeric values",
                    )
            control_domains.append(
                MinimalControlDomain(
                    control_name=_identifier(
                        domain["control_name"], domain_path + ".control_name"
                    ),
                    domain_kind=kind,
                    minimum=minimum,
                    maximum=maximum,
                    allowed_values=allowed_values,
                    anchors=_anchors(domain["anchors"], domain_path + ".anchors"),
                )
            )
        applicability = []
        for index, raw_applicability in enumerate(
            _array(domain_raw["applicability"], path + ".domain.applicability")
        ):
            applicability_path = "%s.domain.applicability[%d]" % (path, index)
            value = _object(
                raw_applicability,
                applicability_path,
                {"statement", "anchors"},
            )
            applicability.append(
                MinimalApplicability(
                    statement=_text(
                        value["statement"], applicability_path + ".statement"
                    ),
                    anchors=_anchors(
                        value["anchors"], applicability_path + ".anchors"
                    ),
                )
            )

        relation = MinimalQuantitativeRelation(
            formula=_formula(item["formula"], path + ".formula"),
            parameters=tuple(parameters),
            controls=tuple(controls),
            readouts=tuple(readouts),
            domain=MinimalDomain(
                controls=tuple(control_domains),
                applicability=tuple(applicability),
            ),
            anchors=_anchors(item["anchors"], path + ".anchors"),
        )
        _validate_relation(relation, path, max_readouts=max_readouts)
        relations.append(relation)
    return tuple(relations)


def _validated_source(source: ScienceSource) -> ScienceSource:
    if not isinstance(source, ScienceSource):
        raise ValueError("source must be a ScienceSource")
    citation = _text(source.citation, "$.source.citation")
    doi = _text(source.journal_doi, "$.source.journal_doi")
    if canonicalize_doi(doi) != doi:
        _error("$.source.journal_doi", "must be a canonical DOI")
    arxiv_id = (parse_versioned_arxiv_id(source.arxiv_versioned_id)
                if source.arxiv_versioned_id is not None else None)
    return ScienceSource(citation=citation, journal_doi=doi, arxiv_versioned_id=arxiv_id)


def parse_minimal_science_card_provider_payload(
    payload: Any,
    *,
    source: ScienceSource,
    max_readouts: int = 2,
) -> MinimalScienceCard:
    """Parse model output and inject the caller-supplied source identity.

    The original two-readout contract remains the default. A separate enriched
    pipeline may explicitly permit up to eight complete scientific readouts.
    """

    return MinimalScienceCard(
        source=_validated_source(source),
        relations=_decode_provider_payload(payload, max_readouts=_readout_limit(max_readouts)),
    )


def _decode_json(text: str) -> Any:
    if not isinstance(text, str):
        _error("$", "input must be text", "minimal_science_card.invalid_json")

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
        raise MinimalScienceCardError(
            "minimal_science_card.invalid_json",
            "$",
            "expected exactly one strict JSON value",
        ) from exc


def parse_minimal_science_card_provider_json(
    text: str,
    *,
    source: ScienceSource,
    max_readouts: int = 2,
) -> MinimalScienceCard:
    return parse_minimal_science_card_provider_payload(_decode_json(text), source=source, max_readouts=max_readouts)


def _anchor_payload(anchor: MinimalAnchor) -> Mapping[str, Any]:
    return {"line_start": anchor.line_start, "line_end": anchor.line_end}


def _expression_payload(expression: Any) -> Any:
    if isinstance(expression, (int, float)) and not isinstance(expression, bool):
        return float(expression)
    if "var" in expression:
        return {"var": expression["var"]}
    if "param" in expression:
        return {"param": expression["param"]}
    return {
        "op": expression["op"],
        "args": [_expression_payload(item) for item in expression["args"]],
    }


def minimal_science_card_provider_payload(card: MinimalScienceCard) -> Mapping[str, Any]:
    return {
        "relations": [
            {
                "formula": {
                    "outputs": {
                        name: _expression_payload(expression)
                        for name, expression in relation.formula.items()
                    }
                },
                "parameters": [
                    {
                        "name": item.name,
                        "value": item.value,
                        "unit": item.unit,
                        "anchors": [_anchor_payload(anchor) for anchor in item.anchors],
                    }
                    for item in relation.parameters
                ],
                "controls": [
                    {
                        "name": item.name,
                        "definition": item.definition,
                        "unit": item.unit,
                        "anchors": [_anchor_payload(anchor) for anchor in item.anchors],
                    }
                    for item in relation.controls
                ],
                "readouts": [
                    {
                        "name": item.name,
                        "definition": item.definition,
                        "unit": item.unit,
                        "anchors": [_anchor_payload(anchor) for anchor in item.anchors],
                    }
                    for item in relation.readouts
                ],
                "domain": {
                    "controls": [
                        {
                            "control_name": item.control_name,
                            "domain_kind": item.domain_kind,
                            "minimum": item.minimum,
                            "maximum": item.maximum,
                            "allowed_values": list(item.allowed_values),
                            "anchors": [
                                _anchor_payload(anchor) for anchor in item.anchors
                            ],
                        }
                        for item in relation.domain.controls
                    ],
                    "applicability": [
                        {
                            "statement": item.statement,
                            "anchors": [
                                _anchor_payload(anchor) for anchor in item.anchors
                            ],
                        }
                        for item in relation.domain.applicability
                    ],
                },
                "anchors": [_anchor_payload(anchor) for anchor in relation.anchors],
            }
            for relation in card.relations
        ]
    }


def minimal_science_card_to_payload(card: MinimalScienceCard) -> Mapping[str, Any]:
    return {
        "schema": MINIMAL_SCIENCE_CARD_SCHEMA,
        "source": {
            "citation": card.source.citation,
            "journal_doi": card.source.journal_doi,
            "arxiv_versioned_id": card.source.arxiv_versioned_id,
        },
        **minimal_science_card_provider_payload(card),
    }


def parse_minimal_science_card_payload(payload: Any, *, max_readouts: int = 2) -> MinimalScienceCard:
    root = _object(payload, "$", {"schema", "source", "relations"})
    if root["schema"] != MINIMAL_SCIENCE_CARD_SCHEMA:
        _error("$.schema", "unsupported minimal ScienceCard schema")
    source_raw = _object(
        root["source"],
        "$.source",
        {"citation", "journal_doi", "arxiv_versioned_id"},
    )
    source = ScienceSource(
        citation=_text(source_raw["citation"], "$.source.citation"),
        journal_doi=_text(source_raw["journal_doi"], "$.source.journal_doi"),
        arxiv_versioned_id=None if source_raw["arxiv_versioned_id"] is None else _text(
            source_raw["arxiv_versioned_id"], "$.source.arxiv_versioned_id"
        ),
    )
    return parse_minimal_science_card_provider_payload(
        {"relations": root["relations"]}, source=source, max_readouts=max_readouts
    )


def parse_minimal_science_card_json(text: str, *, max_readouts: int = 2) -> MinimalScienceCard:
    return parse_minimal_science_card_payload(_decode_json(text), max_readouts=max_readouts)


def _all_anchors(card: MinimalScienceCard) -> Tuple[Tuple[str, MinimalAnchor], ...]:
    result = []
    for relation_index, relation in enumerate(card.relations):
        base = "$.relations[%d]" % relation_index
        for index, anchor in enumerate(relation.anchors):
            result.append(("%s.anchors[%d]" % (base, index), anchor))
        for field, values in (
            ("parameters", relation.parameters),
            ("controls", relation.controls),
            ("readouts", relation.readouts),
            ("domain.controls", relation.domain.controls),
            ("domain.applicability", relation.domain.applicability),
        ):
            for item_index, item in enumerate(values):
                for anchor_index, anchor in enumerate(item.anchors):
                    result.append(
                        (
                            "%s.%s[%d].anchors[%d]"
                            % (base, field, item_index, anchor_index),
                            anchor,
                        )
                    )
    return tuple(result)


def validate_minimal_science_card_lineage(
    card: MinimalScienceCard,
    source_line_count: int,
) -> None:
    if isinstance(source_line_count, bool) or not isinstance(source_line_count, int):
        raise ValueError("source_line_count must be an integer")
    if source_line_count < 1:
        raise ValueError("source_line_count must be positive")
    for path, anchor in _all_anchors(card):
        if anchor.line_end > source_line_count:
            raise MinimalScienceCardError(
                "minimal_science_card.locator",
                path,
                "source line %d exceeds the %d-line model input"
                % (anchor.line_end, source_line_count),
            )


def minimal_science_card_json_schema(*, max_readouts: int = 2) -> Mapping[str, Any]:
    """Return the provider-facing schema; source identity is intentionally absent."""

    max_readouts = _readout_limit(max_readouts)
    identifier: Dict[str, Any] = {
        "type": "string",
        "pattern": "^[A-Za-z][A-Za-z0-9_]*$",
    }
    text: Dict[str, Any] = {"type": "string", "minLength": 1}
    anchor = {
        "type": "object",
        "properties": {
            "line_start": {"type": "integer", "minimum": 1},
            "line_end": {"type": "integer", "minimum": 1},
        },
        "required": ["line_start", "line_end"],
        "additionalProperties": False,
    }
    anchors = {"type": "array", "items": anchor, "minItems": 1}
    grouped_arities: Dict[Tuple[int, Optional[int]], list[str]] = {}
    for operator, bounds in EXPRESSION_OPERATOR_ARITIES.items():
        grouped_arities.setdefault(bounds, []).append(operator)
    operations = []
    for (minimum, maximum), operators in grouped_arities.items():
        arguments: Dict[str, Any] = {
            "type": "array",
            "minItems": minimum,
            "items": {"$ref": "#/$defs/expression"},
        }
        if maximum is not None:
            arguments["maxItems"] = maximum
        operations.append(
            {
                "type": "object",
                "properties": {
                    "op": {"type": "string", "enum": sorted(operators)},
                    "args": arguments,
                },
                "required": ["op", "args"],
                "additionalProperties": False,
            }
        )
    expression = {
        "anyOf": [
            {"type": "number", "enum": [0, 1]},
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
            *operations,
        ]
    }
    named_evidence = {
        "type": "object",
        "properties": {
            "name": identifier,
            "definition": text,
            "unit": text,
            "anchors": anchors,
        },
        "required": ["name", "definition", "unit", "anchors"],
        "additionalProperties": False,
    }
    parameter = {
        "type": "object",
        "properties": {
            "name": identifier,
            "value": {"type": "number"},
            "unit": text,
            "anchors": anchors,
        },
        "required": ["name", "value", "unit", "anchors"],
        "additionalProperties": False,
    }
    control_domain = {
        "type": "object",
        "properties": {
            "control_name": identifier,
            "domain_kind": {
                "type": "string",
                "enum": sorted(_DOMAIN_KINDS),
            },
            "minimum": {"anyOf": [{"type": "number"}, {"type": "null"}]},
            "maximum": {"anyOf": [{"type": "number"}, {"type": "null"}]},
            "allowed_values": {
                "type": "array",
                "items": {"type": "number"},
                "uniqueItems": True,
            },
            "anchors": anchors,
        },
        "required": [
            "control_name",
            "domain_kind",
            "minimum",
            "maximum",
            "allowed_values",
            "anchors",
        ],
        "additionalProperties": False,
    }
    applicability = {
        "type": "object",
        "properties": {"statement": text, "anchors": anchors},
        "required": ["statement", "anchors"],
        "additionalProperties": False,
    }
    relation = {
        "type": "object",
        "properties": {
            "formula": {
                "type": "object",
                "properties": {
                    "outputs": {
                        "type": "object",
                        "minProperties": 1,
                        "propertyNames": identifier,
                        "additionalProperties": {"$ref": "#/$defs/expression"},
                    }
                },
                "required": ["outputs"],
                "additionalProperties": False,
            },
            "parameters": {"type": "array", "items": parameter},
            "controls": {
                "type": "array",
                "items": named_evidence,
                "minItems": 1,
                "maxItems": 5,
            },
            "readouts": {
                "type": "array",
                "items": named_evidence,
                "minItems": 1,
                "maxItems": max_readouts,
            },
            "domain": {
                "type": "object",
                "properties": {
                    "controls": {
                        "type": "array",
                        "items": control_domain,
                        "minItems": 1,
                        "maxItems": 5,
                    },
                    "applicability": {
                        "type": "array",
                        "items": applicability,
                    },
                },
                "required": ["controls", "applicability"],
                "additionalProperties": False,
            },
            "anchors": anchors,
        },
        "required": [
            "formula",
            "parameters",
            "controls",
            "readouts",
            "domain",
            "anchors",
        ],
        "additionalProperties": False,
    }
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$defs": {"expression": expression},
        "type": "object",
        "properties": {
            "relations": {
                "type": "array",
                "items": relation,
                "maxItems": 1,
            }
        },
        "required": ["relations"],
        "additionalProperties": False,
    }


__all__ = [
    "MINIMAL_SCIENCE_CARD_SCHEMA",
    "MinimalAnchor",
    "MinimalApplicability",
    "MinimalControl",
    "MinimalControlDomain",
    "MinimalDomain",
    "MinimalParameter",
    "MinimalQuantitativeRelation",
    "MinimalReadout",
    "MinimalScienceCard",
    "MinimalScienceCardError",
    "minimal_science_card_json_schema",
    "minimal_science_card_provider_payload",
    "minimal_science_card_to_payload",
    "parse_minimal_science_card_json",
    "parse_minimal_science_card_payload",
    "parse_minimal_science_card_provider_json",
    "parse_minimal_science_card_provider_payload",
    "validate_minimal_science_card_lineage",
]
