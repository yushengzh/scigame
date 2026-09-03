"""Strict intermediate representation supported by evidence from one paper.

The science card records what the paper says before any benchmark world is
authored.  It deliberately contains no Player prompt, counterfactual, episode
budget, or evaluator choice.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from typing import Any, Dict, Mapping, Optional, Tuple

from role_benchmark.expression import (
    EXPRESSION_MAX_DEPTH,
    EXPRESSION_MAX_NODES,
    EXPRESSION_OPERATOR_ARITIES,
    EXPRESSION_OPERATORS,
    ExpressionError,
    validate_expression_program,
)


_IDENTIFIER = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")
_RESOLUTION_KINDS = {"measurement_resolution", "reporting_increment"}
_DOMAIN_KINDS = {
    "continuous_interval",
    "numeric_values",
    "fixed_value",
    "symbolic",
    "unreported",
}
# The case binder adds two AST levels and can combine two branches for each of
# two readouts.  These derived limits guarantee that every accepted source
# program remains inside the unchanged runtime expression limits after binding.
_SOURCE_EXPRESSION_MAX_DEPTH = EXPRESSION_MAX_DEPTH - 2
_SOURCE_EXPRESSION_MAX_NODES = (EXPRESSION_MAX_NODES - 14) // 4


class ScienceCardError(ValueError):
    """The model output is not a strict, internally linked science card."""

    def __init__(self, code: str, path: str, detail: str) -> None:
        self.code = code
        self.path = path
        self.detail = detail
        super().__init__("%s at %s: %s" % (code, path, detail))


@dataclass(frozen=True)
class ScienceSource:
    citation: str
    journal_doi: str
    arxiv_versioned_id: str


@dataclass(frozen=True)
class SourceAnchor:
    line_start: int
    line_end: int
    support: str


@dataclass(frozen=True)
class ScienceParameter:
    name: str
    value: float
    uncertainty: str
    unit: str
    role: str
    anchors: Tuple[SourceAnchor, ...]


@dataclass(frozen=True)
class ScienceMechanism:
    mechanism_id: str
    statement: str
    equations: Tuple[str, ...]
    variable_names: Tuple[str, ...]
    parameters: Tuple[ScienceParameter, ...]
    anchors: Tuple[SourceAnchor, ...]


@dataclass(frozen=True)
class ScienceFixedCondition:
    condition_id: str
    statement: str
    anchors: Tuple[SourceAnchor, ...]


@dataclass(frozen=True)
class ScienceControl:
    name: str
    definition: str
    unit: str
    minimum: Optional[float]
    maximum: Optional[float]
    anchors: Tuple[SourceAnchor, ...]
    domain_kind: str = "continuous_interval"
    allowed_values: Tuple[float, ...] = ()
    domain_statement: str = ""


@dataclass(frozen=True)
class ScienceResolution:
    """One source-reported numeric precision contract for a readout."""

    value: float
    kind: str
    anchors: Tuple[SourceAnchor, ...]


@dataclass(frozen=True)
class ScienceReadout:
    """Source-observation semantics retained as private provenance.

    ``statistic`` and ``uncertainty`` describe the paper's data, not the value
    returned by a deterministic benchmark Oracle.
    """

    name: str
    definition: str
    unit: str
    statistic: str
    uncertainty: str
    resolution: Optional[ScienceResolution]
    anchors: Tuple[SourceAnchor, ...]


@dataclass(frozen=True)
class ScienceControlDomain:
    """The source-reported applicability of one claim to one control."""

    control_name: str
    minimum: Optional[float]
    maximum: Optional[float]
    anchors: Tuple[SourceAnchor, ...]
    domain_kind: str = "continuous_interval"
    allowed_values: Tuple[float, ...] = ()
    domain_statement: str = ""


@dataclass(frozen=True)
class ScienceClaim:
    claim_id: str
    statement: str
    quantitative_form: str
    mechanism_ids: Tuple[str, ...]
    control_names: Tuple[str, ...]
    control_domains: Tuple[ScienceControlDomain, ...]
    readout_names: Tuple[str, ...]
    fixed_condition_ids: Tuple[str, ...]
    applicability: str
    statistical_basis: str
    uncertainty: str
    depends_on: Tuple[str, ...]
    anchors: Tuple[SourceAnchor, ...]
    # The structured program is the source-reported central-value relation.
    # It deliberately excludes source data-point and parameter uncertainty.
    # ``None`` exists only for reading cards persisted before this field was
    # introduced. Provider-facing schemas and strict extraction require a
    # program for every authoring-ready quantitative claim.
    oracle_outputs: Optional[Mapping[str, Any]] = None


@dataclass(frozen=True)
class ScienceAmbiguity:
    ambiguity_id: str
    statement: str
    claim_ids: Tuple[str, ...]
    mechanism_ids: Tuple[str, ...]
    control_names: Tuple[str, ...]
    readout_names: Tuple[str, ...]
    fixed_condition_ids: Tuple[str, ...]
    anchors: Tuple[SourceAnchor, ...]


@dataclass(frozen=True)
class ScienceCard:
    assessment: str
    case_authoring_ready: bool
    source: ScienceSource
    paper_scope: str
    mechanisms: Tuple[ScienceMechanism, ...]
    fixed_conditions: Tuple[ScienceFixedCondition, ...]
    controls: Tuple[ScienceControl, ...]
    readouts: Tuple[ScienceReadout, ...]
    claims: Tuple[ScienceClaim, ...]
    source_ambiguities: Tuple[ScienceAmbiguity, ...]


def _error(path: str, detail: str, code: str = "science_card.schema") -> None:
    raise ScienceCardError(code, path, detail)


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
        _error(path, "must be an ASCII snake-style identifier")
    return result


def canonical_science_name(value: str) -> str:
    """Map a card label to the runtime's lower-snake coordinate system."""

    if not isinstance(value, str) or _IDENTIFIER.fullmatch(value) is None:
        raise ValueError("science-card name must be an ASCII snake-style identifier")
    return value.lower()


def _number(value: Any, path: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        _error(path, "must be a number")
    result = float(value)
    if not math.isfinite(result):
        _error(path, "must be finite")
    return result


def _claim_expression(value: Any, path: str) -> Any:
    """Strictly decode the shared expression AST, including parameter leaves."""

    if isinstance(value, bool):
        _error(path, "boolean is not an expression")
    if isinstance(value, (int, float)):
        return _number(value, path)
    if not isinstance(value, dict):
        _error(path, "must be a number or expression object")
    keys = set(value)
    if keys in ({"var"}, {"param"}):
        key = next(iter(keys))
        return {key: _identifier(value[key], path + "." + key)}
    item = _object(value, path, {"op", "args"})
    operator = _text(item["op"], path + ".op")
    if operator not in EXPRESSION_OPERATORS:
        _error(path + ".op", "unsupported expression operator")
    return {
        "op": operator,
        "args": [
            _claim_expression(argument, "%s.args[%d]" % (path, index))
            for index, argument in enumerate(_array(item["args"], path + ".args"))
        ],
    }


def _oracle_outputs(value: Any, path: str) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        _error(path, "must be an object mapping readouts to expressions")
    if not value:
        _error(path, "must contain at least one readout expression")
    return {
        _identifier(name, path + ".<key>"): _claim_expression(
            expression, "%s.%s" % (path, name)
        )
        for name, expression in value.items()
    }


def _integer(value: Any, path: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        _error(path, "must be an integer")
    return value


def _bool(value: Any, path: str) -> bool:
    if not isinstance(value, bool):
        _error(path, "must be a boolean")
    return value


def _identifier_array(value: Any, path: str) -> Tuple[str, ...]:
    result = tuple(
        _identifier(item, "%s[%d]" % (path, index))
        for index, item in enumerate(_array(value, path))
    )
    if len(set(result)) != len(result):
        _error(path, "must not contain duplicates")
    return result


def _text_array(value: Any, path: str) -> Tuple[str, ...]:
    return tuple(
        _text(item, "%s[%d]" % (path, index))
        for index, item in enumerate(_array(value, path))
    )


def _unique_text_array(value: Any, path: str) -> Tuple[str, ...]:
    result = _text_array(value, path)
    if len(set(result)) != len(result):
        _error(path, "must not contain duplicates")
    return result


def _anchors(value: Any, path: str) -> Tuple[SourceAnchor, ...]:
    result = []
    for index, raw in enumerate(_array(value, path)):
        item_path = "%s[%d]" % (path, index)
        item = _object(raw, item_path, {"line_start", "line_end", "support"})
        line_start = _integer(item["line_start"], item_path + ".line_start")
        line_end = _integer(item["line_end"], item_path + ".line_end")
        if line_start < 1 or line_end < line_start:
            _error(item_path, "line range must satisfy 1 <= line_start <= line_end")
        result.append(
            SourceAnchor(
                line_start=line_start,
                line_end=line_end,
                support=_text(item["support"], item_path + ".support"),
            )
        )
    if not result:
        _error(path, "must contain at least one source anchor")
    return tuple(result)


def _domain_fields(
    value: Any,
    path: str,
    base_keys: set[str],
) -> Tuple[Mapping[str, Any], str, Optional[float], Optional[float], Tuple[float, ...], str]:
    """Decode source applicability while retaining old interval-only cards."""

    legacy_keys = base_keys | {"minimum", "maximum", "anchors"}
    current_keys = legacy_keys | {
        "domain_kind",
        "allowed_values",
        "domain_statement",
    }
    if isinstance(value, dict) and set(value) == legacy_keys:
        item = value
        kind = "continuous_interval"
        minimum = _number(item["minimum"], path + ".minimum")
        maximum = _number(item["maximum"], path + ".maximum")
        allowed_values: Tuple[float, ...] = ()
        statement = ""
    else:
        item = _object(value, path, current_keys)
        kind = _text(item["domain_kind"], path + ".domain_kind")
        if kind not in _DOMAIN_KINDS:
            _error(
                path + ".domain_kind",
                "must be one of %s" % ", ".join(sorted(_DOMAIN_KINDS)),
            )
        minimum = (
            None
            if item["minimum"] is None
            else _number(item["minimum"], path + ".minimum")
        )
        maximum = (
            None
            if item["maximum"] is None
            else _number(item["maximum"], path + ".maximum")
        )
        allowed_values = tuple(
            _number(raw, "%s.allowed_values[%d]" % (path, index))
            for index, raw in enumerate(
                _array(item["allowed_values"], path + ".allowed_values")
            )
        )
        raw_statement = item["domain_statement"]
        if not isinstance(raw_statement, str):
            _error(path + ".domain_statement", "must be text")
        statement = raw_statement.strip()

    if kind == "continuous_interval":
        if minimum is None or maximum is None or minimum >= maximum:
            _error(path, "continuous_interval requires minimum < maximum")
        if allowed_values:
            _error(path + ".allowed_values", "must be empty for continuous_interval")
    elif kind == "numeric_values":
        if minimum is not None or maximum is not None:
            _error(path, "numeric_values requires null minimum and maximum")
        if len(allowed_values) < 2 or len(set(allowed_values)) != len(allowed_values):
            _error(path + ".allowed_values", "must contain at least two unique values")
    elif kind == "fixed_value":
        if minimum is not None or maximum is not None:
            _error(path, "fixed_value requires null minimum and maximum")
        if len(allowed_values) != 1:
            _error(path + ".allowed_values", "must contain exactly one value")
    else:
        if minimum is not None or maximum is not None or allowed_values:
            _error(path, "%s cannot assert a numeric domain" % kind)
        if not statement:
            _error(
                path + ".domain_statement",
                "%s requires a description supported by source evidence" % kind,
            )
    return item, kind, minimum, maximum, allowed_values, statement


def _decode_json(text: str) -> Any:
    if not isinstance(text, str):
        _error("$", "input must be text", "science_card.invalid_json")

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
        raise ScienceCardError(
            "science_card.invalid_json",
            "$",
            "expected exactly one strict JSON value",
        ) from exc


def parse_science_card_payload(
    payload: Any,
    *,
    require_oracle_outputs: bool = False,
) -> ScienceCard:
    """Parse one card and validate every internal identifier reference.

    ``require_oracle_outputs=False`` is the narrow compatibility path for
    cards persisted before structured claim programs existed.  New extraction
    calls and the provider-facing schema use the strict ``True`` setting.
    """

    if not isinstance(require_oracle_outputs, bool):
        raise ValueError("require_oracle_outputs must be a boolean")

    root = _object(
        payload,
        "$",
        {
            "assessment",
            "case_authoring_ready",
            "source",
            "paper_scope",
            "mechanisms",
            "fixed_conditions",
            "controls",
            "readouts",
            "claims",
            "source_ambiguities",
        },
    )
    source_raw = _object(
        root["source"],
        "$.source",
        {"citation", "journal_doi", "arxiv_versioned_id"},
    )

    mechanisms = []
    for index, raw in enumerate(_array(root["mechanisms"], "$.mechanisms")):
        path = "$.mechanisms[%d]" % index
        item = _object(
            raw,
            path,
            {
                "mechanism_id",
                "statement",
                "equations",
                "variable_names",
                "parameters",
                "anchors",
            },
        )
        parameters = []
        for parameter_index, parameter_raw in enumerate(
            _array(item["parameters"], path + ".parameters")
        ):
            parameter_path = "%s.parameters[%d]" % (path, parameter_index)
            parameter = _object(
                parameter_raw,
                parameter_path,
                {"name", "value", "uncertainty", "unit", "role", "anchors"},
            )
            parameters.append(
                ScienceParameter(
                    name=_identifier(parameter["name"], parameter_path + ".name"),
                    value=_number(parameter["value"], parameter_path + ".value"),
                    uncertainty=_text(
                        parameter["uncertainty"], parameter_path + ".uncertainty"
                    ),
                    unit=_text(parameter["unit"], parameter_path + ".unit"),
                    role=_text(parameter["role"], parameter_path + ".role"),
                    anchors=_anchors(
                        parameter["anchors"], parameter_path + ".anchors"
                    ),
                )
            )
        parameter_names = [item.name for item in parameters]
        if len(set(parameter_names)) != len(parameter_names):
            _error(path + ".parameters", "parameter names must be unique")
        equations = _text_array(item["equations"], path + ".equations")
        if not equations:
            _error(path + ".equations", "must contain at least one equation")
        mechanisms.append(
            ScienceMechanism(
                mechanism_id=_identifier(
                    item["mechanism_id"], path + ".mechanism_id"
                ),
                statement=_text(item["statement"], path + ".statement"),
                equations=equations,
                variable_names=_unique_text_array(
                    item["variable_names"], path + ".variable_names"
                ),
                parameters=tuple(parameters),
                anchors=_anchors(item["anchors"], path + ".anchors"),
            )
        )

    fixed_conditions = []
    for index, raw in enumerate(
        _array(root["fixed_conditions"], "$.fixed_conditions")
    ):
        path = "$.fixed_conditions[%d]" % index
        item = _object(raw, path, {"condition_id", "statement", "anchors"})
        fixed_conditions.append(
            ScienceFixedCondition(
                condition_id=_identifier(
                    item["condition_id"], path + ".condition_id"
                ),
                statement=_text(item["statement"], path + ".statement"),
                anchors=_anchors(item["anchors"], path + ".anchors"),
            )
        )

    controls = []
    for index, raw in enumerate(_array(root["controls"], "$.controls")):
        path = "$.controls[%d]" % index
        (
            item,
            domain_kind,
            minimum,
            maximum,
            allowed_values,
            domain_statement,
        ) = _domain_fields(
            raw,
            path,
            {"name", "definition", "unit"},
        )
        controls.append(
            ScienceControl(
                name=_identifier(item["name"], path + ".name"),
                definition=_text(item["definition"], path + ".definition"),
                unit=_text(item["unit"], path + ".unit"),
                minimum=minimum,
                maximum=maximum,
                anchors=_anchors(item["anchors"], path + ".anchors"),
                domain_kind=domain_kind,
                allowed_values=allowed_values,
                domain_statement=domain_statement,
            )
        )

    readouts = []
    for index, raw in enumerate(_array(root["readouts"], "$.readouts")):
        path = "$.readouts[%d]" % index
        item = _object(
            raw,
            path,
            {
                "name",
                "definition",
                "unit",
                "statistic",
                "uncertainty",
                "resolution",
                "anchors",
            },
        )
        resolution_raw = item["resolution"]
        resolution = None
        if resolution_raw is not None:
            resolution_path = path + ".resolution"
            resolution_item = _object(
                resolution_raw,
                resolution_path,
                {"value", "kind", "anchors"},
            )
            resolution_value = _number(
                resolution_item["value"], resolution_path + ".value"
            )
            if resolution_value <= 0.0:
                _error(resolution_path + ".value", "must be positive")
            resolution_kind = _text(
                resolution_item["kind"], resolution_path + ".kind"
            )
            if resolution_kind not in _RESOLUTION_KINDS:
                _error(
                    resolution_path + ".kind",
                    "must be measurement_resolution or reporting_increment",
                )
            resolution = ScienceResolution(
                value=resolution_value,
                kind=resolution_kind,
                anchors=_anchors(
                    resolution_item["anchors"], resolution_path + ".anchors"
                ),
            )
        readouts.append(
            ScienceReadout(
                name=_identifier(item["name"], path + ".name"),
                definition=_text(item["definition"], path + ".definition"),
                unit=_text(item["unit"], path + ".unit"),
                statistic=_text(item["statistic"], path + ".statistic"),
                uncertainty=_text(item["uncertainty"], path + ".uncertainty"),
                resolution=resolution,
                anchors=_anchors(item["anchors"], path + ".anchors"),
            )
        )

    claims = []
    for index, raw in enumerate(_array(root["claims"], "$.claims")):
        path = "$.claims[%d]" % index
        legacy_claim_keys = {
            "claim_id",
            "statement",
            "quantitative_form",
            "mechanism_ids",
            "control_names",
            "control_domains",
            "readout_names",
            "fixed_condition_ids",
            "applicability",
            "statistical_basis",
            "uncertainty",
            "depends_on",
            "anchors",
        }
        current_claim_keys = legacy_claim_keys | {"oracle_outputs"}
        if isinstance(raw, dict) and set(raw) == legacy_claim_keys:
            item = raw
            oracle_outputs = None
        else:
            item = _object(raw, path, current_claim_keys)
            oracle_outputs = _oracle_outputs(
                item["oracle_outputs"], path + ".oracle_outputs"
            )
        control_domains = []
        for domain_index, domain_raw in enumerate(
            _array(item["control_domains"], path + ".control_domains")
        ):
            domain_path = "%s.control_domains[%d]" % (path, domain_index)
            (
                domain,
                domain_kind,
                domain_minimum,
                domain_maximum,
                allowed_values,
                domain_statement,
            ) = _domain_fields(
                domain_raw,
                domain_path,
                {"control_name"},
            )
            control_domains.append(
                ScienceControlDomain(
                    control_name=_identifier(
                        domain["control_name"], domain_path + ".control_name"
                    ),
                    minimum=domain_minimum,
                    maximum=domain_maximum,
                    anchors=_anchors(domain["anchors"], domain_path + ".anchors"),
                    domain_kind=domain_kind,
                    allowed_values=allowed_values,
                    domain_statement=domain_statement,
                )
            )
        domain_names = [domain.control_name for domain in control_domains]
        if len(set(domain_names)) != len(domain_names):
            _error(path + ".control_domains", "control names must be unique")
        claims.append(
            ScienceClaim(
                claim_id=_identifier(item["claim_id"], path + ".claim_id"),
                statement=_text(item["statement"], path + ".statement"),
                quantitative_form=_text(
                    item["quantitative_form"], path + ".quantitative_form"
                ),
                mechanism_ids=_identifier_array(
                    item["mechanism_ids"], path + ".mechanism_ids"
                ),
                control_names=_identifier_array(
                    item["control_names"], path + ".control_names"
                ),
                control_domains=tuple(control_domains),
                readout_names=_identifier_array(
                    item["readout_names"], path + ".readout_names"
                ),
                fixed_condition_ids=_identifier_array(
                    item["fixed_condition_ids"], path + ".fixed_condition_ids"
                ),
                applicability=_text(
                    item["applicability"], path + ".applicability"
                ),
                statistical_basis=_text(
                    item["statistical_basis"], path + ".statistical_basis"
                ),
                uncertainty=_text(item["uncertainty"], path + ".uncertainty"),
                depends_on=_identifier_array(
                    item["depends_on"], path + ".depends_on"
                ),
                anchors=_anchors(item["anchors"], path + ".anchors"),
                oracle_outputs=oracle_outputs,
            )
        )

    ambiguities = []
    for index, raw in enumerate(
        _array(root["source_ambiguities"], "$.source_ambiguities")
    ):
        path = "$.source_ambiguities[%d]" % index
        item = _object(
            raw,
            path,
            {
                "ambiguity_id",
                "statement",
                "claim_ids",
                "mechanism_ids",
                "control_names",
                "readout_names",
                "fixed_condition_ids",
                "anchors",
            },
        )
        ambiguities.append(
            ScienceAmbiguity(
                ambiguity_id=_identifier(
                    item["ambiguity_id"], path + ".ambiguity_id"
                ),
                statement=_text(item["statement"], path + ".statement"),
                claim_ids=_identifier_array(item["claim_ids"], path + ".claim_ids"),
                mechanism_ids=_identifier_array(
                    item["mechanism_ids"], path + ".mechanism_ids"
                ),
                control_names=_identifier_array(
                    item["control_names"], path + ".control_names"
                ),
                readout_names=_identifier_array(
                    item["readout_names"], path + ".readout_names"
                ),
                fixed_condition_ids=_identifier_array(
                    item["fixed_condition_ids"], path + ".fixed_condition_ids"
                ),
                anchors=_anchors(item["anchors"], path + ".anchors"),
            )
        )

    card = ScienceCard(
        assessment=_text(root["assessment"], "$.assessment"),
        case_authoring_ready=_bool(
            root["case_authoring_ready"], "$.case_authoring_ready"
        ),
        source=ScienceSource(
            citation=_text(source_raw["citation"], "$.source.citation"),
            journal_doi=_text(source_raw["journal_doi"], "$.source.journal_doi"),
            arxiv_versioned_id=_text(
                source_raw["arxiv_versioned_id"], "$.source.arxiv_versioned_id"
            ),
        ),
        paper_scope=_text(root["paper_scope"], "$.paper_scope"),
        mechanisms=tuple(mechanisms),
        fixed_conditions=tuple(fixed_conditions),
        controls=tuple(controls),
        readouts=tuple(readouts),
        claims=tuple(claims),
        source_ambiguities=tuple(ambiguities),
    )
    _validate_links(card, require_oracle_outputs=require_oracle_outputs)
    return card


def _unique(values: Tuple[str, ...], path: str) -> set[str]:
    if len(set(values)) != len(values):
        _error(path, "identifiers must be unique")
    return set(values)


def _require_canonical_unique(values: Tuple[str, ...], path: str) -> None:
    canonical = tuple(canonical_science_name(value) for value in values)
    if len(set(canonical)) != len(canonical):
        _error(path, "names collide after deterministic lowercase canonicalization")


def _require_subset(values: Tuple[str, ...], allowed: set[str], path: str) -> None:
    unknown = sorted(set(values) - allowed)
    if unknown:
        _error(path, "unknown identifier(s): %s" % ", ".join(unknown))


def _source_domain_contains(parent: Any, child: Any) -> bool:
    """Return whether a claim narrows, rather than expands, source support."""

    if parent.domain_kind == "continuous_interval":
        if child.domain_kind == "continuous_interval":
            return (
                child.minimum is not None
                and child.maximum is not None
                and parent.minimum is not None
                and parent.maximum is not None
                and child.minimum >= parent.minimum
                and child.maximum <= parent.maximum
            )
        if child.domain_kind in {"numeric_values", "fixed_value"}:
            return (
                parent.minimum is not None
                and parent.maximum is not None
                and all(
                    parent.minimum <= value <= parent.maximum
                    for value in child.allowed_values
                )
            )
        return child.domain_kind == parent.domain_kind and (
            child.domain_statement == parent.domain_statement
        )
    if parent.domain_kind in {"numeric_values", "fixed_value"}:
        return child.domain_kind in {"numeric_values", "fixed_value"} and set(
            child.allowed_values
        ).issubset(parent.allowed_values)
    return child.domain_kind == parent.domain_kind and (
        child.domain_statement == parent.domain_statement
    )


def _validate_links(
    card: ScienceCard,
    *,
    require_oracle_outputs: bool = False,
) -> None:
    mechanism_ids = _unique(
        tuple(item.mechanism_id for item in card.mechanisms), "$.mechanisms"
    )
    condition_ids = _unique(
        tuple(item.condition_id for item in card.fixed_conditions),
        "$.fixed_conditions",
    )
    control_names = _unique(tuple(item.name for item in card.controls), "$.controls")
    readout_names = _unique(tuple(item.name for item in card.readouts), "$.readouts")
    claim_ids = _unique(tuple(item.claim_id for item in card.claims), "$.claims")
    parameter_names = tuple(
        parameter.name
        for mechanism in card.mechanisms
        for parameter in mechanism.parameters
    )
    mechanisms_by_id = {
        mechanism.mechanism_id: mechanism for mechanism in card.mechanisms
    }
    _unique(parameter_names, "$.mechanisms[*].parameters")
    _require_canonical_unique(control_names, "$.controls")
    _require_canonical_unique(readout_names, "$.readouts")
    _require_canonical_unique(parameter_names, "$.mechanisms[*].parameters")
    _unique(
        tuple(item.ambiguity_id for item in card.source_ambiguities),
        "$.source_ambiguities",
    )

    if card.case_authoring_ready and not (
        card.mechanisms and card.controls and card.readouts and card.claims
    ):
        _error(
            "$.case_authoring_ready",
            "a ready card needs mechanisms, controls, readouts, and claims",
        )

    for index, claim in enumerate(card.claims):
        path = "$.claims[%d]" % index
        _require_subset(claim.mechanism_ids, mechanism_ids, path + ".mechanism_ids")
        _require_subset(claim.control_names, control_names, path + ".control_names")
        domain_names = tuple(item.control_name for item in claim.control_domains)
        _require_subset(domain_names, control_names, path + ".control_domains")
        if set(domain_names) != set(claim.control_names):
            _error(
                path + ".control_domains",
                "must define exactly one source applicability domain for every claim control",
            )
        controls_by_name = {item.name: item for item in card.controls}
        for domain_index, domain in enumerate(claim.control_domains):
            source_control = controls_by_name[domain.control_name]
            if not _source_domain_contains(source_control, domain):
                _error(
                    "%s.control_domains[%d]" % (path, domain_index),
                    "claim domain exceeds the control's source-supported domain",
                )
        _require_subset(claim.readout_names, readout_names, path + ".readout_names")
        _require_subset(
            claim.fixed_condition_ids,
            condition_ids,
            path + ".fixed_condition_ids",
        )
        _require_subset(claim.depends_on, claim_ids, path + ".depends_on")
        if claim.claim_id in claim.depends_on:
            _error(path + ".depends_on", "a claim cannot depend on itself")
        if claim.oracle_outputs is None:
            if require_oracle_outputs and card.case_authoring_ready:
                _error(
                    path + ".oracle_outputs",
                    "is required for every claim in an authoring-ready card",
                )
        else:
            linked_parameters = tuple(
                parameter.name
                for mechanism_id in claim.mechanism_ids
                for parameter in mechanisms_by_id[mechanism_id].parameters
            )
            try:
                validate_expression_program(
                    {"outputs": claim.oracle_outputs},
                    allowed_variables=claim.control_names,
                    allowed_parameters=linked_parameters,
                    allowed_numeric_literals=(),
                    required_outputs=claim.readout_names,
                    max_depth=_SOURCE_EXPRESSION_MAX_DEPTH,
                    max_nodes=_SOURCE_EXPRESSION_MAX_NODES,
                )
            except ExpressionError as exc:
                _error(path + ".oracle_outputs", str(exc))

    for index, ambiguity in enumerate(card.source_ambiguities):
        path = "$.source_ambiguities[%d]" % index
        _require_subset(
            ambiguity.claim_ids,
            claim_ids,
            path + ".claim_ids",
        )
        _require_subset(ambiguity.mechanism_ids, mechanism_ids, path + ".mechanism_ids")
        _require_subset(ambiguity.control_names, control_names, path + ".control_names")
        _require_subset(ambiguity.readout_names, readout_names, path + ".readout_names")
        _require_subset(
            ambiguity.fixed_condition_ids,
            condition_ids,
            path + ".fixed_condition_ids",
        )

    dependencies = {item.claim_id: item.depends_on for item in card.claims}
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(claim_id: str) -> None:
        if claim_id in visiting:
            _error("$.claims", "claim dependencies must form a directed acyclic graph")
        if claim_id in visited:
            return
        visiting.add(claim_id)
        for dependency in dependencies[claim_id]:
            visit(dependency)
        visiting.remove(claim_id)
        visited.add(claim_id)

    for claim_id in dependencies:
        visit(claim_id)


def _all_anchors(card: ScienceCard) -> Tuple[Tuple[str, SourceAnchor], ...]:
    """Return every anchor with its exact ScienceCard path."""

    result = []

    def add(path: str, anchors: Tuple[SourceAnchor, ...]) -> None:
        result.extend(
            ("%s[%d]" % (path, index), anchor)
            for index, anchor in enumerate(anchors)
        )

    for mechanism_index, mechanism in enumerate(card.mechanisms):
        mechanism_path = "$.mechanisms[%d]" % mechanism_index
        add(mechanism_path + ".anchors", mechanism.anchors)
        for parameter_index, parameter in enumerate(mechanism.parameters):
            add(
                "%s.parameters[%d].anchors"
                % (mechanism_path, parameter_index),
                parameter.anchors,
            )
    for index, item in enumerate(card.fixed_conditions):
        add("$.fixed_conditions[%d].anchors" % index, item.anchors)
    for index, item in enumerate(card.controls):
        add("$.controls[%d].anchors" % index, item.anchors)
    for index, item in enumerate(card.readouts):
        readout_path = "$.readouts[%d]" % index
        add(readout_path + ".anchors", item.anchors)
        if item.resolution is not None:
            add(readout_path + ".resolution.anchors", item.resolution.anchors)
    for claim_index, item in enumerate(card.claims):
        claim_path = "$.claims[%d]" % claim_index
        add(claim_path + ".anchors", item.anchors)
        for domain_index, domain in enumerate(item.control_domains):
            add(
                "%s.control_domains[%d].anchors" % (claim_path, domain_index),
                domain.anchors,
            )
    for index, item in enumerate(card.source_ambiguities):
        add("$.source_ambiguities[%d].anchors" % index, item.anchors)
    return tuple(result)


def validate_science_card_lineage(card: ScienceCard, source_line_count: int) -> None:
    """Ensure every model-cited line exists in the exact model-visible source."""

    if isinstance(source_line_count, bool) or not isinstance(source_line_count, int):
        raise ValueError("source_line_count must be an integer")
    if source_line_count < 1:
        raise ValueError("source_line_count must be positive")
    for path, anchor in _all_anchors(card):
        if anchor.line_end > source_line_count:
            raise ScienceCardError(
                "science_card.locator",
                path,
                "source line %d exceeds the %d-line model input"
                % (anchor.line_end, source_line_count),
            )


def parse_science_card_json(
    text: str,
    *,
    require_oracle_outputs: bool = False,
) -> ScienceCard:
    return parse_science_card_payload(
        _decode_json(text),
        require_oracle_outputs=require_oracle_outputs,
    )


def _anchor_payload(anchor: SourceAnchor) -> Mapping[str, Any]:
    return {
        "line_start": anchor.line_start,
        "line_end": anchor.line_end,
        "support": anchor.support,
    }


def _claim_expression_payload(expression: Any) -> Any:
    if isinstance(expression, (int, float)) and not isinstance(expression, bool):
        return float(expression)
    if "var" in expression:
        return {"var": expression["var"]}
    if "param" in expression:
        return {"param": expression["param"]}
    return {
        "op": expression["op"],
        "args": [
            _claim_expression_payload(argument) for argument in expression["args"]
        ],
    }


def _oracle_outputs_payload(outputs: Mapping[str, Any]) -> Mapping[str, Any]:
    return {
        name: _claim_expression_payload(expression)
        for name, expression in outputs.items()
    }


def science_card_to_payload(card: ScienceCard) -> Mapping[str, Any]:
    return {
        "assessment": card.assessment,
        "case_authoring_ready": card.case_authoring_ready,
        "source": {
            "citation": card.source.citation,
            "journal_doi": card.source.journal_doi,
            "arxiv_versioned_id": card.source.arxiv_versioned_id,
        },
        "paper_scope": card.paper_scope,
        "mechanisms": [
            {
                "mechanism_id": item.mechanism_id,
                "statement": item.statement,
                "equations": list(item.equations),
                "variable_names": list(item.variable_names),
                "parameters": [
                    {
                        "name": parameter.name,
                        "value": parameter.value,
                        "uncertainty": parameter.uncertainty,
                        "unit": parameter.unit,
                        "role": parameter.role,
                        "anchors": [
                            _anchor_payload(anchor) for anchor in parameter.anchors
                        ],
                    }
                    for parameter in item.parameters
                ],
                "anchors": [_anchor_payload(anchor) for anchor in item.anchors],
            }
            for item in card.mechanisms
        ],
        "fixed_conditions": [
            {
                "condition_id": item.condition_id,
                "statement": item.statement,
                "anchors": [_anchor_payload(anchor) for anchor in item.anchors],
            }
            for item in card.fixed_conditions
        ],
        "controls": [
            {
                "name": item.name,
                "definition": item.definition,
                "unit": item.unit,
                "domain_kind": item.domain_kind,
                "minimum": item.minimum,
                "maximum": item.maximum,
                "allowed_values": list(item.allowed_values),
                "domain_statement": item.domain_statement,
                "anchors": [_anchor_payload(anchor) for anchor in item.anchors],
            }
            for item in card.controls
        ],
        "readouts": [
            {
                "name": item.name,
                "definition": item.definition,
                "unit": item.unit,
                "statistic": item.statistic,
                "uncertainty": item.uncertainty,
                "resolution": (
                    {
                        "value": item.resolution.value,
                        "kind": item.resolution.kind,
                        "anchors": [
                            _anchor_payload(anchor)
                            for anchor in item.resolution.anchors
                        ],
                    }
                    if item.resolution is not None
                    else None
                ),
                "anchors": [_anchor_payload(anchor) for anchor in item.anchors],
            }
            for item in card.readouts
        ],
        "claims": [
            {
                "claim_id": item.claim_id,
                "statement": item.statement,
                "quantitative_form": item.quantitative_form,
                **(
                    {
                        "oracle_outputs": _oracle_outputs_payload(
                            item.oracle_outputs
                        )
                    }
                    if item.oracle_outputs is not None
                    else {}
                ),
                "mechanism_ids": list(item.mechanism_ids),
                "control_names": list(item.control_names),
                "control_domains": [
                    {
                        "control_name": domain.control_name,
                        "domain_kind": domain.domain_kind,
                        "minimum": domain.minimum,
                        "maximum": domain.maximum,
                        "allowed_values": list(domain.allowed_values),
                        "domain_statement": domain.domain_statement,
                        "anchors": [
                            _anchor_payload(anchor) for anchor in domain.anchors
                        ],
                    }
                    for domain in item.control_domains
                ],
                "readout_names": list(item.readout_names),
                "fixed_condition_ids": list(item.fixed_condition_ids),
                "applicability": item.applicability,
                "statistical_basis": item.statistical_basis,
                "uncertainty": item.uncertainty,
                "depends_on": list(item.depends_on),
                "anchors": [_anchor_payload(anchor) for anchor in item.anchors],
            }
            for item in card.claims
        ],
        "source_ambiguities": [
            {
                "ambiguity_id": item.ambiguity_id,
                "statement": item.statement,
                "claim_ids": list(item.claim_ids),
                "mechanism_ids": list(item.mechanism_ids),
                "control_names": list(item.control_names),
                "readout_names": list(item.readout_names),
                "fixed_condition_ids": list(item.fixed_condition_ids),
                "anchors": [_anchor_payload(anchor) for anchor in item.anchors],
            }
            for item in card.source_ambiguities
        ],
    }


def science_card_json_schema() -> Mapping[str, Any]:
    identifier: Dict[str, Any] = {
        "type": "string",
        "pattern": "^[A-Za-z][A-Za-z0-9_]*$",
    }
    text: Dict[str, Any] = {"type": "string", "minLength": 1}
    identifier_array = {
        "type": "array",
        "items": identifier,
        "uniqueItems": True,
    }
    grouped_arities: Dict[Tuple[int, Optional[int]], list[str]] = {}
    for operator, bounds in EXPRESSION_OPERATOR_ARITIES.items():
        grouped_arities.setdefault(bounds, []).append(operator)
    expression_operations = []
    for (minimum, maximum), operators in grouped_arities.items():
        arguments: Dict[str, Any] = {
            "type": "array",
            "minItems": minimum,
            "items": {"$ref": "#/$defs/science_expression"},
        }
        if maximum is not None:
            arguments["maxItems"] = maximum
        expression_operations.append(
            {
                "type": "object",
                "properties": {
                    "op": {"type": "string", "enum": operators},
                    "args": arguments,
                },
                "required": ["op", "args"],
                "additionalProperties": False,
            }
        )
    science_expression = {
        "anyOf": [
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
            *expression_operations,
        ]
    }
    oracle_outputs = {
        "type": "object",
        "minProperties": 1,
        "propertyNames": identifier,
        "additionalProperties": {"$ref": "#/$defs/science_expression"},
        "description": (
            "Source-reported central-value control-to-readout relation; source "
            "data and parameter uncertainty are provenance outside this AST."
        ),
    }
    anchor = {
        "type": "object",
        "properties": {
            "line_start": {"type": "integer", "minimum": 1},
            "line_end": {"type": "integer", "minimum": 1},
            "support": text,
        },
        "required": ["line_start", "line_end", "support"],
        "additionalProperties": False,
    }
    anchors = {"type": "array", "items": anchor, "minItems": 1}
    parameter = {
        "type": "object",
        "properties": {
            "name": identifier,
            "value": {"type": "number"},
            "uncertainty": text,
            "unit": text,
            "role": text,
            "anchors": anchors,
        },
        "required": ["name", "value", "uncertainty", "unit", "role", "anchors"],
        "additionalProperties": False,
    }
    mechanism = {
        "type": "object",
        "properties": {
            "mechanism_id": identifier,
            "statement": text,
            "equations": {"type": "array", "items": text, "minItems": 1},
            "variable_names": {
                "type": "array",
                "items": text,
                "uniqueItems": True,
            },
            "parameters": {"type": "array", "items": parameter},
            "anchors": anchors,
        },
        "required": [
            "mechanism_id",
            "statement",
            "equations",
            "variable_names",
            "parameters",
            "anchors",
        ],
        "additionalProperties": False,
    }
    fixed_condition = {
        "type": "object",
        "properties": {
            "condition_id": identifier,
            "statement": text,
            "anchors": anchors,
        },
        "required": ["condition_id", "statement", "anchors"],
        "additionalProperties": False,
    }
    control = {
        "type": "object",
        "properties": {
            "name": identifier,
            "definition": text,
            "unit": text,
            "domain_kind": {"type": "string", "enum": sorted(_DOMAIN_KINDS)},
            "minimum": {"anyOf": [{"type": "number"}, {"type": "null"}]},
            "maximum": {"anyOf": [{"type": "number"}, {"type": "null"}]},
            "allowed_values": {
                "type": "array",
                "items": {"type": "number"},
                "uniqueItems": True,
            },
            "domain_statement": {"type": "string"},
            "anchors": anchors,
        },
        "required": [
            "name",
            "definition",
            "unit",
            "domain_kind",
            "minimum",
            "maximum",
            "allowed_values",
            "domain_statement",
            "anchors",
        ],
        "additionalProperties": False,
    }
    readout = {
        "type": "object",
        "properties": {
            "name": identifier,
            "definition": text,
            "unit": text,
            "statistic": {
                **text,
                "description": (
                    "Aggregation or summary statistic of the source data; this "
                    "does not describe a future deterministic Oracle query."
                ),
            },
            "uncertainty": {
                **text,
                "description": (
                    "Source-reported data uncertainty convention retained as "
                    "provenance, not per-query Oracle uncertainty."
                ),
            },
            "resolution": {
                "anyOf": [
                    {"type": "null"},
                    {
                        "type": "object",
                        "properties": {
                            "value": {"type": "number", "exclusiveMinimum": 0},
                            "kind": {
                                "type": "string",
                                "enum": sorted(_RESOLUTION_KINDS),
                            },
                            "anchors": anchors,
                        },
                        "required": ["value", "kind", "anchors"],
                        "additionalProperties": False,
                    },
                ]
            },
            "anchors": anchors,
        },
        "required": [
            "name",
            "definition",
            "unit",
            "statistic",
            "uncertainty",
            "resolution",
            "anchors",
        ],
        "additionalProperties": False,
    }
    control_domain = {
        "type": "object",
        "properties": {
            "control_name": identifier,
            "domain_kind": {"type": "string", "enum": sorted(_DOMAIN_KINDS)},
            "minimum": {"anyOf": [{"type": "number"}, {"type": "null"}]},
            "maximum": {"anyOf": [{"type": "number"}, {"type": "null"}]},
            "allowed_values": {
                "type": "array",
                "items": {"type": "number"},
                "uniqueItems": True,
            },
            "domain_statement": {"type": "string"},
            "anchors": anchors,
        },
        "required": [
            "control_name",
            "domain_kind",
            "minimum",
            "maximum",
            "allowed_values",
            "domain_statement",
            "anchors",
        ],
        "additionalProperties": False,
    }
    claim = {
        "type": "object",
        "properties": {
            "claim_id": identifier,
            "statement": text,
            "quantitative_form": text,
            "oracle_outputs": oracle_outputs,
            "mechanism_ids": identifier_array,
            "control_names": identifier_array,
            "control_domains": {
                "type": "array",
                "items": control_domain,
            },
            "readout_names": identifier_array,
            "fixed_condition_ids": identifier_array,
            "applicability": text,
            "statistical_basis": text,
            "uncertainty": text,
            "depends_on": identifier_array,
            "anchors": anchors,
        },
        "required": [
            "claim_id",
            "statement",
            "quantitative_form",
            "oracle_outputs",
            "mechanism_ids",
            "control_names",
            "control_domains",
            "readout_names",
            "fixed_condition_ids",
            "applicability",
            "statistical_basis",
            "uncertainty",
            "depends_on",
            "anchors",
        ],
        "additionalProperties": False,
    }
    ambiguity = {
        "type": "object",
        "properties": {
            "ambiguity_id": identifier,
            "statement": text,
            "claim_ids": identifier_array,
            "mechanism_ids": identifier_array,
            "control_names": identifier_array,
            "readout_names": identifier_array,
            "fixed_condition_ids": identifier_array,
            "anchors": anchors,
        },
        "required": [
            "ambiguity_id",
            "statement",
            "claim_ids",
            "mechanism_ids",
            "control_names",
            "readout_names",
            "fixed_condition_ids",
            "anchors",
        ],
        "additionalProperties": False,
    }
    properties: Dict[str, Any] = {
        "assessment": text,
        "case_authoring_ready": {"type": "boolean"},
        "source": {
            "type": "object",
            "properties": {
                "citation": text,
                "journal_doi": text,
                "arxiv_versioned_id": text,
            },
            "required": ["citation", "journal_doi", "arxiv_versioned_id"],
            "additionalProperties": False,
        },
        "paper_scope": text,
        "mechanisms": {"type": "array", "items": mechanism},
        "fixed_conditions": {"type": "array", "items": fixed_condition},
        "controls": {"type": "array", "items": control},
        "readouts": {"type": "array", "items": readout},
        "claims": {"type": "array", "items": claim},
        "source_ambiguities": {"type": "array", "items": ambiguity},
    }
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$defs": {"science_expression": science_expression},
        "type": "object",
        "properties": properties,
        "required": list(properties),
        "additionalProperties": False,
    }


__all__ = [
    "ScienceCard",
    "ScienceCardError",
    "ScienceAmbiguity",
    "ScienceClaim",
    "ScienceControl",
    "ScienceControlDomain",
    "ScienceFixedCondition",
    "ScienceMechanism",
    "ScienceParameter",
    "ScienceReadout",
    "ScienceResolution",
    "ScienceSource",
    "SourceAnchor",
    "canonical_science_name",
    "parse_science_card_json",
    "parse_science_card_payload",
    "science_card_json_schema",
    "science_card_to_payload",
    "validate_science_card_lineage",
]
