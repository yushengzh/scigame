"""Strict JSON boundary for Player-visible state and actions.

The wire layer validates syntax, shape, and public model invariants only.
Resource validity remains Oracle response semantics, and stopping rules remain the
Episode state machine's responsibility.
"""

from __future__ import annotations

import json
import math
from decimal import Decimal, InvalidOperation
from enum import Enum
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from .expression import EXPRESSION_MODEL, EXPRESSION_OPERATOR_ARITIES
from .models import (
    BenchmarkTrack,
    CaseDefinition,
    ControlSpec,
    EpisodeResult,
    EpisodeView,
    EvaluationResult,
    ExperimentEvidence,
    ExperimentProposal,
    ExperimentTurn,
    FinalSubmission,
    Hypothesis,
    HypothesisPortfolio,
    InstrumentSpec,
    OracleResponse,
    OracleStatus,
    PlayerAction,
    ReadoutSpec,
    ResourceCatalog,
)


EPISODE_VIEW_SCHEMA = "role_benchmark.episode_view"
PLAYER_ACTION_SCHEMA = "role_benchmark.player_action"
DEFAULT_MAX_JSON_BYTES = 1_048_576
DEFAULT_MAX_ACTION_BYTES = 65_536
_MAX_JSON_DEPTH = 64
_MAX_JSON_NODES = 20_000
_MAX_SAFE_INTEGER = 2**53 - 1
_MAX_NUMBER_TOKEN_CHARS = 128


class WireError(ValueError):
    """Base class for stable wire errors with a code and JSON path."""

    def __init__(self, code: str, path: str, message: str) -> None:
        self.code = code
        self.path = path
        self.detail = message
        super().__init__("%s at %s: %s" % (code, path, message))


class WireEncodeError(WireError):
    """A Python object could not be represented by the public wire format."""


class WireDecodeError(WireError):
    """A model response did not satisfy the public action wire format."""


class _DuplicateKeyError(ValueError):
    pass


class _NumberTokenError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


def _validate_max_bytes(max_bytes: int) -> None:
    if isinstance(max_bytes, bool) or not isinstance(max_bytes, int):
        raise ValueError("max_bytes must be an integer")
    if max_bytes < 1:
        raise ValueError("max_bytes must be positive")


def _duplicate_rejecting_object(pairs: Sequence[Tuple[str, Any]]) -> Dict[str, Any]:
    result: Dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateKeyError("duplicate object key %r" % key)
        result[key] = value
    return result


def _reject_constant(value: str) -> Any:
    raise _NumberTokenError(
        "non_finite_number", "non-standard numeric constant %s" % value
    )


def _parse_safe_integer(value: str) -> int:
    digits = value[1:] if value.startswith("-") else value
    if len(digits) > 16:
        raise _NumberTokenError(
            "number_out_of_range", "integer is outside the interoperable JSON range"
        )
    result = int(value)
    if abs(result) > _MAX_SAFE_INTEGER:
        raise _NumberTokenError(
            "number_out_of_range", "integer is outside the interoperable JSON range"
        )
    return result


def _parse_safe_float(value: str) -> float:
    if len(value) > _MAX_NUMBER_TOKEN_CHARS:
        raise _NumberTokenError("number_out_of_range", "number token is too long")
    try:
        decimal_value = Decimal(value)
        result = float(decimal_value)
    except (InvalidOperation, OverflowError, ValueError) as exc:
        raise _NumberTokenError("invalid_number", "invalid JSON number") from exc
    if not math.isfinite(result):
        raise _NumberTokenError("non_finite_number", "number must be finite")
    if decimal_value != 0 and result == 0.0:
        raise _NumberTokenError(
            "number_underflow", "non-zero number underflows the binary64 range"
        )
    if (
        decimal_value == decimal_value.to_integral_value()
        and abs(decimal_value) > _MAX_SAFE_INTEGER
    ):
        raise _NumberTokenError(
            "number_out_of_range",
            "integral number is outside the interoperable JSON range",
        )
    if Decimal(repr(result)) != decimal_value:
        raise _NumberTokenError(
            "number_precision_loss", "number cannot be represented exactly as binary64"
        )
    return result


def _validate_json_tree(
    value: Any,
    *,
    path: str,
    depth: int,
    nodes: List[int],
    error_type: type,
    seen: Any = None,
) -> None:
    if seen is None:
        seen = set()
    nodes[0] += 1
    if nodes[0] > _MAX_JSON_NODES:
        raise error_type("too_many_values", path, "JSON value exceeds node limit")
    if depth > _MAX_JSON_DEPTH:
        raise error_type("too_deep", path, "JSON value exceeds nesting limit")

    if isinstance(value, Enum):
        if error_type is WireEncodeError:
            _validate_json_tree(
                value.value,
                path=path,
                depth=depth,
                nodes=nodes,
                error_type=error_type,
                seen=seen,
            )
            return
        raise error_type("non_json_value", path, "enum objects are not JSON values")
    if value is None or type(value) is bool:
        return
    if type(value) is str:
        try:
            value.encode("utf-8")
        except UnicodeEncodeError as exc:
            raise error_type(
                "invalid_unicode", path, "string is not valid UTF-8 text"
            ) from exc
        return
    if type(value) is int:
        if abs(value) > _MAX_SAFE_INTEGER:
            raise error_type(
                "number_out_of_range",
                path,
                "integer must be within the IEEE-754 safe range",
            )
        try:
            numeric = float(value)
        except OverflowError as exc:
            raise error_type(
                "non_finite_number", path, "integer is outside the finite numeric range"
            ) from exc
        if not math.isfinite(numeric):
            raise error_type(
                "non_finite_number", path, "integer is outside the finite numeric range"
            )
        return
    if type(value) is float:
        if not math.isfinite(value):
            raise error_type("non_finite_number", path, "number must be finite")
        if value.is_integer() and abs(value) > _MAX_SAFE_INTEGER:
            raise error_type(
                "number_out_of_range",
                path,
                "integral number must be within the IEEE-754 safe range",
            )
        return
    if isinstance(value, Mapping):
        if error_type is WireDecodeError and type(value) is not dict:
            raise error_type("non_json_value", path, "expected a plain JSON object")
        identity = id(value)
        if identity in seen:
            raise error_type("cyclic_value", path, "JSON values must not be cyclic")
        seen.add(identity)
        try:
            for key, child in value.items():
                if type(key) is not str:
                    raise error_type(
                        "non_string_key", path, "object keys must be strings"
                    )
                try:
                    key.encode("utf-8")
                except UnicodeEncodeError as exc:
                    raise error_type(
                        "invalid_unicode",
                        path + ".<key>",
                        "object key is not valid UTF-8 text",
                    ) from exc
                _validate_json_tree(
                    child,
                    path="%s.%s" % (path, key),
                    depth=depth + 1,
                    nodes=nodes,
                    error_type=error_type,
                    seen=seen,
                )
        finally:
            seen.remove(identity)
        return
    if isinstance(value, list) or (
        error_type is WireEncodeError and isinstance(value, tuple)
    ):
        identity = id(value)
        if identity in seen:
            raise error_type("cyclic_value", path, "JSON values must not be cyclic")
        seen.add(identity)
        try:
            for index, child in enumerate(value):
                _validate_json_tree(
                    child,
                    path="%s[%d]" % (path, index),
                    depth=depth + 1,
                    nodes=nodes,
                    error_type=error_type,
                    seen=seen,
                )
        finally:
            seen.remove(identity)
        return
    raise error_type(
        "non_json_value",
        path,
        "value of type %s is not JSON-compatible" % type(value).__name__,
    )


def _convert_json_safe(value: Any, *, path: str) -> Any:
    if isinstance(value, Enum):
        return _convert_json_safe(value.value, path=path)
    if isinstance(value, Mapping):
        converted: Dict[str, Any] = {}
        for key, child in value.items():
            converted[key] = _convert_json_safe(
                child, path="%s.%s" % (path, key)
            )
        return converted
    if isinstance(value, (list, tuple)):
        return [
            _convert_json_safe(child, path="%s[%d]" % (path, index))
            for index, child in enumerate(value)
        ]
    return value


def _json_safe(value: Any, *, path: str = "$") -> Any:
    _validate_json_tree(
        value,
        path=path,
        depth=0,
        nodes=[0],
        error_type=WireEncodeError,
    )
    return _convert_json_safe(value, path=path)


def canonical_json_dumps(value: Any) -> str:
    """Return the project's deterministic UTF-8 JSON representation.

    This is a project-local Python codec, not a claim of cross-language RFC 8785
    conformance.
    """

    safe = _json_safe(value)
    try:
        return json.dumps(
            safe,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    except (TypeError, ValueError, OverflowError) as exc:
        raise WireEncodeError("json_encode", "$", str(exc)) from exc


def strict_json_loads(
    text: str,
    *,
    max_bytes: int = DEFAULT_MAX_JSON_BYTES,
) -> Any:
    _validate_max_bytes(max_bytes)
    if not isinstance(text, str):
        raise WireDecodeError("wrong_type", "$", "JSON input must be text")
    try:
        encoded_size = len(text.encode("utf-8"))
    except UnicodeEncodeError as exc:
        raise WireDecodeError(
            "invalid_unicode", "$", "JSON input is not valid UTF-8 text"
        ) from exc
    if encoded_size > max_bytes:
        raise WireDecodeError(
            "payload_too_large", "$", "JSON input exceeds %d bytes" % max_bytes
        )
    try:
        value = json.loads(
            text,
            object_pairs_hook=_duplicate_rejecting_object,
            parse_constant=_reject_constant,
            parse_int=_parse_safe_integer,
            parse_float=_parse_safe_float,
        )
    except _DuplicateKeyError as exc:
        raise WireDecodeError("duplicate_key", "$", str(exc)) from exc
    except _NumberTokenError as exc:
        raise WireDecodeError(exc.code, "$", str(exc)) from exc
    except (json.JSONDecodeError, ValueError, RecursionError) as exc:
        raise WireDecodeError("invalid_json", "$", str(exc)) from exc
    _validate_json_tree(
        value,
        path="$",
        depth=0,
        nodes=[0],
        error_type=WireDecodeError,
    )
    return value


def _expect_mapping(value: Any, path: str) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        raise WireDecodeError("wrong_type", path, "expected an object")
    return value


def _expect_list(value: Any, path: str) -> List[Any]:
    if not isinstance(value, list):
        raise WireDecodeError("wrong_type", path, "expected an array")
    return value


def _expect_string(value: Any, path: str) -> str:
    if not isinstance(value, str):
        raise WireDecodeError("wrong_type", path, "expected a string")
    return value


def _expect_number(value: Any, path: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise WireDecodeError("wrong_type", path, "expected a finite number")
    try:
        numeric = float(value)
    except OverflowError as exc:
        raise WireDecodeError(
            "non_finite_number", path, "number must be finite"
        ) from exc
    if not math.isfinite(numeric):
        raise WireDecodeError("non_finite_number", path, "number must be finite")
    return numeric


def _expect_integer(value: Any, path: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise WireDecodeError("wrong_type", path, "expected an integer")
    return value


def _expect_exact_keys(
    value: Mapping[str, Any], required: Sequence[str], path: str
) -> None:
    required_set = set(required)
    actual = set(value)
    missing = sorted(required_set - actual)
    unknown = sorted(actual - required_set)
    if missing:
        raise WireDecodeError(
            "missing_field", path, "missing field(s): %s" % ", ".join(missing)
        )
    if unknown:
        raise WireDecodeError(
            "unknown_field", path, "unknown field(s): %s" % ", ".join(unknown)
        )


def _strings(value: Any, path: str) -> Tuple[str, ...]:
    items = _expect_list(value, path)
    return tuple(
        _expect_string(item, "%s[%d]" % (path, index))
        for index, item in enumerate(items)
    )


def _hypothesis_to_payload(hypothesis: Hypothesis) -> Dict[str, Any]:
    return {
        "hypothesis_id": hypothesis.hypothesis_id,
        "statement": hypothesis.statement,
        "confidence": hypothesis.confidence,
    }


def _portfolio_to_payload(portfolio: HypothesisPortfolio) -> Dict[str, Any]:
    return {
        "hypotheses": [
            _hypothesis_to_payload(item) for item in portfolio.hypotheses
        ]
    }


def _portfolio_from_payload(value: Any, path: str) -> HypothesisPortfolio:
    payload = _expect_mapping(value, path)
    _expect_exact_keys(payload, ("hypotheses",), path)
    hypotheses_payload = _expect_list(payload["hypotheses"], path + ".hypotheses")
    hypotheses: List[Hypothesis] = []
    for index, raw in enumerate(hypotheses_payload):
        item_path = "%s.hypotheses[%d]" % (path, index)
        item = _expect_mapping(raw, item_path)
        _expect_exact_keys(
            item, ("hypothesis_id", "statement", "confidence"), item_path
        )
        try:
            hypotheses.append(
                Hypothesis(
                    hypothesis_id=_expect_string(
                        item["hypothesis_id"], item_path + ".hypothesis_id"
                    ),
                    statement=_expect_string(
                        item["statement"], item_path + ".statement"
                    ),
                    confidence=_expect_number(
                        item["confidence"], item_path + ".confidence"
                    ),
                )
            )
        except WireDecodeError:
            raise
        except (TypeError, ValueError, OverflowError) as exc:
            raise WireDecodeError("model_invariant", item_path, str(exc)) from exc
    try:
        return HypothesisPortfolio(tuple(hypotheses))
    except WireDecodeError:
        raise
    except (TypeError, ValueError, OverflowError) as exc:
        raise WireDecodeError("model_invariant", path, str(exc)) from exc


def experiment_proposal_to_payload(proposal: ExperimentProposal) -> Dict[str, Any]:
    return {
        "intent": proposal.intent,
        "apparatus": proposal.apparatus,
        "controls": _json_safe(proposal.controls, path="$.controls"),
        "readouts": list(proposal.readouts),
        "replicates": proposal.replicates,
        "forecasts": _json_safe(proposal.forecasts, path="$.forecasts"),
    }


def _experiment_from_payload(value: Any, path: str) -> ExperimentProposal:
    payload = _expect_mapping(value, path)
    _expect_exact_keys(
        payload,
        ("intent", "apparatus", "controls", "readouts", "replicates", "forecasts"),
        path,
    )
    controls = _expect_mapping(payload["controls"], path + ".controls")
    forecasts = _expect_mapping(payload["forecasts"], path + ".forecasts")
    return ExperimentProposal(
        intent=_expect_string(payload["intent"], path + ".intent"),
        apparatus=_expect_string(payload["apparatus"], path + ".apparatus"),
        # Detach nested JSON containers from the caller.  The public model is
        # frozen, so retaining a nested list/dict owned by the input would make
        # a successfully decoded action mutable through an alias.
        controls=_convert_json_safe(controls, path=path + ".controls"),
        readouts=_strings(payload["readouts"], path + ".readouts"),
        replicates=_expect_integer(payload["replicates"], path + ".replicates"),
        forecasts=_convert_json_safe(forecasts, path=path + ".forecasts"),
    )


def final_submission_to_payload(submission: FinalSubmission) -> Dict[str, Any]:
    return {
        "explanation": submission.explanation,
        "model": submission.model,
        "parameters": _json_safe(submission.parameters, path="$.parameters"),
        "hypothesis_id": submission.hypothesis_id,
        "scope_conditions": list(submission.scope_conditions),
    }


def _final_from_payload(value: Any, path: str) -> FinalSubmission:
    payload = _expect_mapping(value, path)
    _expect_exact_keys(
        payload,
        (
            "explanation",
            "model",
            "parameters",
            "hypothesis_id",
            "scope_conditions",
        ),
        path,
    )
    hypothesis_id = payload["hypothesis_id"]
    if hypothesis_id is not None:
        hypothesis_id = _expect_string(hypothesis_id, path + ".hypothesis_id")
    parameters = _expect_mapping(payload["parameters"], path + ".parameters")
    try:
        return FinalSubmission(
            explanation=_expect_string(payload["explanation"], path + ".explanation"),
            model=_expect_string(payload["model"], path + ".model"),
            parameters=_convert_json_safe(parameters, path=path + ".parameters"),
            hypothesis_id=hypothesis_id,
            scope_conditions=_strings(
                payload["scope_conditions"], path + ".scope_conditions"
            ),
        )
    except WireDecodeError:
        raise
    except (TypeError, ValueError, OverflowError) as exc:
        raise WireDecodeError("model_invariant", path, str(exc)) from exc


def player_action_to_payload(action: PlayerAction) -> Dict[str, Any]:
    return {
        "wire_schema": PLAYER_ACTION_SCHEMA,
        "kind": action.kind,
        "portfolio": _portfolio_to_payload(action.portfolio),
        "experiment": (
            experiment_proposal_to_payload(action.experiment)
            if action.experiment is not None
            else None
        ),
        "final": (
            final_submission_to_payload(action.final)
            if action.final is not None
            else None
        ),
    }


def player_action_from_payload(
    value: Any,
    *,
    max_bytes: int = DEFAULT_MAX_ACTION_BYTES,
) -> PlayerAction:
    _validate_max_bytes(max_bytes)
    _validate_json_tree(
        value,
        path="$",
        depth=0,
        nodes=[0],
        error_type=WireDecodeError,
    )
    if len(canonical_json_dumps(value).encode("utf-8")) > max_bytes:
        raise WireDecodeError(
            "payload_too_large", "$", "action payload exceeds %d bytes" % max_bytes
        )
    payload = _expect_mapping(value, "$")
    _expect_exact_keys(
        payload,
        ("wire_schema", "kind", "portfolio", "experiment", "final"),
        "$",
    )
    schema = _expect_string(payload["wire_schema"], "$.wire_schema")
    if schema != PLAYER_ACTION_SCHEMA:
        raise WireDecodeError(
            "unsupported_schema",
            "$.wire_schema",
            "expected %r" % PLAYER_ACTION_SCHEMA,
        )
    kind = _expect_string(payload["kind"], "$.kind")
    if kind not in ("experiment", "final"):
        raise WireDecodeError(
            "invalid_value", "$.kind", "expected 'experiment' or 'final'"
        )
    portfolio = _portfolio_from_payload(payload["portfolio"], "$.portfolio")
    try:
        if kind == "experiment":
            if payload["experiment"] is None or payload["final"] is not None:
                raise WireDecodeError(
                    "invalid_union",
                    "$",
                    "experiment kind requires an experiment object and final=null",
                )
            return PlayerAction.propose_experiment(
                portfolio,
                _experiment_from_payload(payload["experiment"], "$.experiment"),
            )
        if payload["final"] is None or payload["experiment"] is not None:
            raise WireDecodeError(
                "invalid_union",
                "$",
                "final kind requires a final object and experiment=null",
            )
        return PlayerAction.submit_final(
            portfolio,
            _final_from_payload(payload["final"], "$.final"),
        )
    except WireDecodeError:
        raise
    except (TypeError, ValueError, OverflowError) as exc:
        raise WireDecodeError("model_invariant", "$", str(exc)) from exc


def player_action_from_json(
    text: str,
    *,
    max_bytes: int = DEFAULT_MAX_ACTION_BYTES,
) -> PlayerAction:
    return player_action_from_payload(
        strict_json_loads(text, max_bytes=max_bytes),
        max_bytes=max_bytes,
    )


def player_action_to_json(
    action: PlayerAction,
    *,
    max_bytes: int = DEFAULT_MAX_ACTION_BYTES,
) -> str:
    _validate_max_bytes(max_bytes)
    text = canonical_json_dumps(player_action_to_payload(action))
    if len(text.encode("utf-8")) > max_bytes:
        raise WireEncodeError(
            "payload_too_large", "$", "action payload exceeds %d bytes" % max_bytes
        )
    return text


def _control_to_payload(control: ControlSpec) -> Dict[str, Any]:
    return {
        "name": control.name,
        "description": control.description,
        "unit": control.unit,
        "minimum": control.minimum,
        "maximum": control.maximum,
        "allowed_values": _json_safe(control.allowed_values),
    }


def _readout_to_payload(readout: ReadoutSpec) -> Dict[str, Any]:
    payload = {
        "name": readout.name,
        "description": readout.description,
        "unit": readout.unit,
        "resolution": readout.resolution,
    }
    if readout.statistic or readout.uncertainty or readout.resolution_kind:
        payload.update(
            {
                "statistic": readout.statistic,
                "uncertainty": readout.uncertainty,
                "resolution_kind": readout.resolution_kind,
            }
        )
    return payload


def _instrument_to_payload(instrument: InstrumentSpec) -> Dict[str, Any]:
    return {
        "name": instrument.name,
        "description": instrument.description,
        "controls": list(instrument.controls),
        "readouts": list(instrument.readouts),
    }


def resource_catalog_to_payload(resources: ResourceCatalog) -> Dict[str, Any]:
    return {
        "instruments": [
            _instrument_to_payload(item) for item in resources.instruments
        ],
        "controls": [_control_to_payload(item) for item in resources.controls],
        "readouts": [_readout_to_payload(item) for item in resources.readouts],
        "max_replicates": resources.max_replicates,
        "notes": list(resources.notes),
    }


def case_definition_to_payload(definition: CaseDefinition) -> Dict[str, Any]:
    return {
        "case_id": definition.case_id,
        "track": definition.track.value,
        "title": definition.title,
        "background": definition.background,
        "initial_observations": list(definition.initial_observations),
        "resources": resource_catalog_to_payload(definition.resources),
        "budget": definition.budget,
        "confidence_threshold": definition.confidence_threshold,
        "max_hypotheses": definition.max_hypotheses,
    }


def experiment_evidence_to_payload(evidence: ExperimentEvidence) -> Dict[str, Any]:
    return {
        "measurements": _json_safe(evidence.measurements),
        "units": _json_safe(evidence.units),
        "uncertainty": _json_safe(evidence.uncertainty),
        "message": evidence.message,
    }


def oracle_response_to_payload(response: OracleResponse) -> Dict[str, Any]:
    return {
        "status": response.status.value,
        "message": response.message,
        "evidence": (
            experiment_evidence_to_payload(response.evidence)
            if response.evidence is not None
            else None
        ),
    }


def experiment_turn_to_payload(turn: ExperimentTurn) -> Dict[str, Any]:
    return {
        "turn_index": turn.turn_index,
        "portfolio": _portfolio_to_payload(turn.portfolio),
        "proposal": experiment_proposal_to_payload(turn.proposal),
        "response": oracle_response_to_payload(turn.response),
        "attempt_index": turn.attempt_index,
    }


def episode_view_to_payload(view: EpisodeView) -> Dict[str, Any]:
    return {
        "wire_schema": EPISODE_VIEW_SCHEMA,
        "case": case_definition_to_payload(view.case),
        "attempts_used": view.attempts_used,
        "attempts_remaining": view.attempts_remaining,
        "turns": [experiment_turn_to_payload(turn) for turn in view.turns],
    }


def _optional_number(value: Any, path: str) -> Optional[float]:
    if value is None:
        return None
    return _expect_number(value, path)


def _control_from_payload(value: Any, path: str) -> ControlSpec:
    payload = _expect_mapping(value, path)
    _expect_exact_keys(
        payload,
        ("name", "description", "unit", "minimum", "maximum", "allowed_values"),
        path,
    )
    allowed_values = _expect_list(payload["allowed_values"], path + ".allowed_values")
    return ControlSpec(
        name=_expect_string(payload["name"], path + ".name"),
        description=_expect_string(payload["description"], path + ".description"),
        unit=_expect_string(payload["unit"], path + ".unit"),
        minimum=_optional_number(payload["minimum"], path + ".minimum"),
        maximum=_optional_number(payload["maximum"], path + ".maximum"),
        allowed_values=tuple(
            _convert_json_safe(item, path="%s.allowed_values[%d]" % (path, index))
            for index, item in enumerate(allowed_values)
        ),
    )


def _readout_from_payload(value: Any, path: str) -> ReadoutSpec:
    payload = _expect_mapping(value, path)
    basic = ("name", "description", "unit", "resolution")
    extended = basic + ("statistic", "uncertainty", "resolution_kind")
    if set(payload) == set(basic):
        statistic = uncertainty = resolution_kind = ""
    else:
        _expect_exact_keys(payload, extended, path)
        statistic = _expect_string(payload["statistic"], path + ".statistic")
        uncertainty = _expect_string(payload["uncertainty"], path + ".uncertainty")
        resolution_kind = _expect_string(
            payload["resolution_kind"], path + ".resolution_kind"
        )
    return ReadoutSpec(
        name=_expect_string(payload["name"], path + ".name"),
        description=_expect_string(payload["description"], path + ".description"),
        unit=_expect_string(payload["unit"], path + ".unit"),
        resolution=_optional_number(payload["resolution"], path + ".resolution"),
        statistic=statistic,
        uncertainty=uncertainty,
        resolution_kind=resolution_kind,
    )


def _instrument_from_payload(value: Any, path: str) -> InstrumentSpec:
    payload = _expect_mapping(value, path)
    _expect_exact_keys(payload, ("name", "description", "controls", "readouts"), path)
    return InstrumentSpec(
        name=_expect_string(payload["name"], path + ".name"),
        description=_expect_string(payload["description"], path + ".description"),
        controls=_strings(payload["controls"], path + ".controls"),
        readouts=_strings(payload["readouts"], path + ".readouts"),
    )


def resource_catalog_from_payload(value: Any, path: str = "$") -> ResourceCatalog:
    payload = _expect_mapping(value, path)
    _expect_exact_keys(
        payload,
        ("instruments", "controls", "readouts", "max_replicates", "notes"),
        path,
    )
    instruments = _expect_list(payload["instruments"], path + ".instruments")
    controls = _expect_list(payload["controls"], path + ".controls")
    readouts = _expect_list(payload["readouts"], path + ".readouts")
    try:
        return ResourceCatalog(
            instruments=tuple(
                _instrument_from_payload(item, "%s.instruments[%d]" % (path, index))
                for index, item in enumerate(instruments)
            ),
            controls=tuple(
                _control_from_payload(item, "%s.controls[%d]" % (path, index))
                for index, item in enumerate(controls)
            ),
            readouts=tuple(
                _readout_from_payload(item, "%s.readouts[%d]" % (path, index))
                for index, item in enumerate(readouts)
            ),
            max_replicates=_expect_integer(
                payload["max_replicates"], path + ".max_replicates"
            ),
            notes=_strings(payload["notes"], path + ".notes"),
        )
    except WireDecodeError:
        raise
    except (TypeError, ValueError, OverflowError) as exc:
        raise WireDecodeError("model_invariant", path, str(exc)) from exc


def case_definition_from_payload(value: Any, path: str = "$") -> CaseDefinition:
    payload = _expect_mapping(value, path)
    _expect_exact_keys(
        payload,
        (
            "case_id", "track", "title", "background", "initial_observations",
            "resources", "budget", "confidence_threshold", "max_hypotheses",
        ),
        path,
    )
    track_text = _expect_string(payload["track"], path + ".track")
    try:
        track = BenchmarkTrack(track_text)
    except ValueError as exc:
        raise WireDecodeError(
            "invalid_value", path + ".track", "unsupported benchmark track"
        ) from exc
    try:
        return CaseDefinition(
            case_id=_expect_string(payload["case_id"], path + ".case_id"),
            track=track,
            title=_expect_string(payload["title"], path + ".title"),
            background=_expect_string(payload["background"], path + ".background"),
            initial_observations=_strings(
                payload["initial_observations"], path + ".initial_observations"
            ),
            resources=resource_catalog_from_payload(
                payload["resources"], path + ".resources"
            ),
            budget=_expect_integer(payload["budget"], path + ".budget"),
            confidence_threshold=_expect_number(
                payload["confidence_threshold"], path + ".confidence_threshold"
            ),
            max_hypotheses=_expect_integer(
                payload["max_hypotheses"], path + ".max_hypotheses"
            ),
        )
    except WireDecodeError:
        raise
    except (TypeError, ValueError, OverflowError) as exc:
        raise WireDecodeError("model_invariant", path, str(exc)) from exc


def experiment_evidence_from_payload(
    value: Any, path: str = "$"
) -> ExperimentEvidence:
    payload = _expect_mapping(value, path)
    _expect_exact_keys(payload, ("measurements", "units", "uncertainty", "message"), path)
    measurements = _expect_mapping(payload["measurements"], path + ".measurements")
    units = _expect_mapping(payload["units"], path + ".units")
    uncertainty = _expect_mapping(payload["uncertainty"], path + ".uncertainty")
    for key, item in units.items():
        _expect_string(item, "%s.units.%s" % (path, key))
    for key, item in uncertainty.items():
        _expect_string(item, "%s.uncertainty.%s" % (path, key))
    return ExperimentEvidence(
        measurements=_convert_json_safe(measurements, path=path + ".measurements"),
        units=dict(units),
        uncertainty=dict(uncertainty),
        message=_expect_string(payload["message"], path + ".message"),
    )


def oracle_response_from_payload(value: Any, path: str = "$") -> OracleResponse:
    payload = _expect_mapping(value, path)
    _expect_exact_keys(payload, ("status", "message", "evidence"), path)
    status_text = _expect_string(payload["status"], path + ".status")
    try:
        status = OracleStatus(status_text)
    except ValueError as exc:
        raise WireDecodeError(
            "invalid_value", path + ".status", "unsupported oracle status"
        ) from exc
    evidence = (
        None
        if payload["evidence"] is None
        else experiment_evidence_from_payload(payload["evidence"], path + ".evidence")
    )
    try:
        return OracleResponse(
            status=status,
            message=_expect_string(payload["message"], path + ".message"),
            evidence=evidence,
        )
    except WireDecodeError:
        raise
    except (TypeError, ValueError, OverflowError) as exc:
        raise WireDecodeError("model_invariant", path, str(exc)) from exc


def experiment_turn_from_payload(value: Any, path: str = "$") -> ExperimentTurn:
    payload = _expect_mapping(value, path)
    _expect_exact_keys(
        payload,
        ("turn_index", "portfolio", "proposal", "response", "attempt_index"),
        path,
    )
    attempt_index = payload["attempt_index"]
    if attempt_index is not None:
        attempt_index = _expect_integer(attempt_index, path + ".attempt_index")
    try:
        portfolio = _portfolio_from_payload(payload["portfolio"], path + ".portfolio")
        proposal = _experiment_from_payload(payload["proposal"], path + ".proposal")
        # Reuse the normative action invariant for the recorded pre-evidence
        # portfolio, forecasts, and requested readouts.
        PlayerAction.propose_experiment(portfolio, proposal)
        response = oracle_response_from_payload(payload["response"], path + ".response")
        if response.consumes_budget != (attempt_index is not None):
            raise ValueError("attempt_index does not match Oracle budget semantics")
        if attempt_index is not None and attempt_index < 1:
            raise ValueError("attempt_index must be positive")
        if response.evidence is not None:
            requested = set(proposal.readouts)
            if set(response.evidence.measurements) != requested:
                raise ValueError("evidence measurements do not match requested readouts")
            if set(response.evidence.units) != requested:
                raise ValueError("evidence units do not match requested readouts")
            if not set(response.evidence.uncertainty).issubset(requested):
                raise ValueError("evidence uncertainty contains an unknown readout")
        return ExperimentTurn(
            turn_index=_expect_integer(payload["turn_index"], path + ".turn_index"),
            portfolio=portfolio,
            proposal=proposal,
            response=response,
            attempt_index=attempt_index,
        )
    except WireDecodeError:
        raise
    except (TypeError, ValueError, OverflowError) as exc:
        raise WireDecodeError("model_invariant", path, str(exc)) from exc


def episode_view_from_payload(value: Any) -> EpisodeView:
    _validate_json_tree(
        value, path="$", depth=0, nodes=[0], error_type=WireDecodeError
    )
    payload = _expect_mapping(value, "$")
    _expect_exact_keys(
        payload, ("wire_schema", "case", "attempts_used", "attempts_remaining", "turns"), "$"
    )
    if _expect_string(payload["wire_schema"], "$.wire_schema") != EPISODE_VIEW_SCHEMA:
        raise WireDecodeError(
            "unsupported_schema", "$.wire_schema", "expected %r" % EPISODE_VIEW_SCHEMA
        )
    case = case_definition_from_payload(payload["case"], "$.case")
    attempts_used = _expect_integer(payload["attempts_used"], "$.attempts_used")
    attempts_remaining = _expect_integer(
        payload["attempts_remaining"], "$.attempts_remaining"
    )
    if attempts_used < 0 or attempts_remaining < 0:
        raise WireDecodeError(
            "model_invariant", "$", "attempt counts must be non-negative"
        )
    if attempts_used + attempts_remaining > case.budget:
        raise WireDecodeError(
            "model_invariant", "$", "attempt counts exceed the public case budget"
        )
    turns_payload = _expect_list(payload["turns"], "$.turns")
    turns = tuple(
        experiment_turn_from_payload(item, "$.turns[%d]" % index)
        for index, item in enumerate(turns_payload)
    )
    if any(turn.turn_index != index for index, turn in enumerate(turns, start=1)):
        raise WireDecodeError(
            "model_invariant", "$.turns", "turn_index values must be sequential"
        )
    consumed = [
        turn.attempt_index for turn in turns if turn.attempt_index is not None
    ]
    if consumed:
        expected = list(range(consumed[0], consumed[0] + len(consumed)))
        if consumed != expected or consumed[-1] != attempts_used:
            raise WireDecodeError(
                "model_invariant",
                "$.turns",
                "attempt_index values must be contiguous and end at attempts_used",
            )
    return EpisodeView(
        case=case,
        attempts_used=attempts_used,
        attempts_remaining=attempts_remaining,
        turns=turns,
    )


def episode_view_from_json(
    text: str, *, max_bytes: int = DEFAULT_MAX_JSON_BYTES
) -> EpisodeView:
    return episode_view_from_payload(strict_json_loads(text, max_bytes=max_bytes))


def episode_view_to_json(
    view: EpisodeView,
    *,
    max_bytes: int = DEFAULT_MAX_JSON_BYTES,
) -> str:
    _validate_max_bytes(max_bytes)
    text = canonical_json_dumps(episode_view_to_payload(view))
    if len(text.encode("utf-8")) > max_bytes:
        raise WireEncodeError(
            "payload_too_large", "$", "episode view exceeds %d bytes" % max_bytes
        )
    return text


def evaluation_result_to_payload(result: EvaluationResult) -> Dict[str, Any]:
    return {
        "success": result.success,
        "scores": _json_safe(result.scores),
        "message": result.message,
    }


def episode_result_to_payload(result: EpisodeResult) -> Dict[str, Any]:
    return {
        "case_id": result.case_id,
        "track": result.track.value,
        "attempts_used": result.attempts_used,
        "turns": [experiment_turn_to_payload(turn) for turn in result.turns],
        "final_portfolio": _portfolio_to_payload(result.final_portfolio),
        "final_submission": final_submission_to_payload(result.final_submission),
        "evaluation": evaluation_result_to_payload(result.evaluation),
        "trajectory_scores": _json_safe(result.trajectory_scores),
        "protocol_violations": [
            {"code": item.code, "message": item.message}
            for item in result.protocol_violations
        ],
    }


def _expression_operator_schema_variants() -> List[Dict[str, Any]]:
    """Build JSON-Schema operation branches from the executable grammar."""

    grouped: Dict[Tuple[int, Optional[int]], List[str]] = {}
    for operator, bounds in EXPRESSION_OPERATOR_ARITIES.items():
        grouped.setdefault(bounds, []).append(operator)

    variants: List[Dict[str, Any]] = []
    for (minimum, maximum), operators in grouped.items():
        arguments: Dict[str, Any] = {
            "type": "array",
            "minItems": minimum,
            "items": {"$ref": "#/$defs/expression"},
        }
        if maximum is not None:
            arguments["maxItems"] = maximum
        variants.append(
            {
                "type": "object",
                "additionalProperties": False,
                "required": ["op", "args"],
                "properties": {
                    "op": {"enum": operators},
                    "args": arguments,
                },
            }
        )
    return variants


_PLAYER_ACTION_JSON_SCHEMA: Dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": PLAYER_ACTION_SCHEMA,
    "$defs": {
        "expression": {
            "oneOf": [
                {"type": "number"},
                {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["var"],
                    "properties": {
                        "var": {
                            "type": "string",
                            "minLength": 1,
                            "pattern": ".*\\S.*",
                        }
                    },
                },
                *_expression_operator_schema_variants(),
            ]
        },
        "expression_program": {
            "type": "object",
            "additionalProperties": False,
            "required": ["outputs"],
            "properties": {
                "outputs": {
                    "type": "object",
                    "minProperties": 1,
                    "additionalProperties": {"$ref": "#/$defs/expression"},
                }
            },
        },
    },
    "type": "object",
    "additionalProperties": False,
    "required": ["wire_schema", "kind", "portfolio", "experiment", "final"],
    "properties": {
        "wire_schema": {"const": PLAYER_ACTION_SCHEMA},
        "kind": {"enum": ["experiment", "final"]},
        "portfolio": {
            "type": "object",
            "additionalProperties": False,
            "required": ["hypotheses"],
            "properties": {
                "hypotheses": {
                    "type": "array",
                    "minItems": 1,
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["hypothesis_id", "statement", "confidence"],
                        "properties": {
                            "hypothesis_id": {
                                "type": "string",
                                "minLength": 1,
                                "pattern": ".*\\S.*",
                            },
                            "statement": {
                                "type": "string",
                                "minLength": 1,
                                "pattern": ".*\\S.*",
                            },
                            "confidence": {
                                "type": "number",
                                "minimum": 0.0,
                                "maximum": 1.0,
                            },
                        },
                    },
                }
            },
        },
        "experiment": {
            "type": ["object", "null"],
            "additionalProperties": False,
            "required": [
                "intent",
                "apparatus",
                "controls",
                "readouts",
                "replicates",
                "forecasts",
            ],
            "properties": {
                "intent": {"type": "string"},
                "apparatus": {"type": "string"},
                "controls": {"type": "object"},
                "readouts": {"type": "array", "items": {"type": "string"}},
                "replicates": {
                    "type": "integer",
                    "minimum": -9007199254740991,
                    "maximum": 9007199254740991,
                },
                "forecasts": {
                    "type": "object",
                    "minProperties": 2,
                    "additionalProperties": {
                        "type": "object",
                        "additionalProperties": {"type": "number"},
                    },
                },
            },
        },
        "final": {
            "type": ["object", "null"],
            "additionalProperties": False,
            "required": [
                "explanation",
                "model",
                "parameters",
                "hypothesis_id",
                "scope_conditions",
            ],
            "properties": {
                "explanation": {
                    "type": "string",
                    "minLength": 1,
                    "pattern": ".*\\S.*",
                },
                "model": {"type": "string"},
                "parameters": {"type": "object"},
                "hypothesis_id": {"type": ["string", "null"]},
                "scope_conditions": {
                    "type": "array",
                    "items": {"type": "string"},
                },
            },
            "allOf": [
                {
                    "if": {
                        "properties": {"model": {"const": EXPRESSION_MODEL}},
                        "required": ["model"],
                    },
                    "then": {
                        "properties": {
                            "parameters": {"$ref": "#/$defs/expression_program"}
                        }
                    },
                }
            ],
        },
    },
    "oneOf": [
        {
            "properties": {
                "kind": {"const": "experiment"},
                "portfolio": {
                    "properties": {
                        "hypotheses": {"minItems": 2},
                    }
                },
                "experiment": {"type": "object"},
                "final": {"type": "null"},
            }
        },
        {
            "properties": {
                "kind": {"const": "final"},
                "experiment": {"type": "null"},
                "final": {"type": "object"},
            }
        },
    ],
}


def player_action_json_schema() -> Dict[str, Any]:
    """Return the detached provider-facing structural action schema.

    The Python decoder remains normative for lexical numeric rules
    and cross-field/model invariants that JSON Schema cannot fully express.
    """

    return strict_json_loads(canonical_json_dumps(_PLAYER_ACTION_JSON_SCHEMA))


__all__ = [
    "DEFAULT_MAX_ACTION_BYTES",
    "DEFAULT_MAX_JSON_BYTES",
    "EPISODE_VIEW_SCHEMA",
    "PLAYER_ACTION_SCHEMA",
    "WireDecodeError",
    "WireEncodeError",
    "WireError",
    "canonical_json_dumps",
    "case_definition_from_payload",
    "case_definition_to_payload",
    "episode_result_to_payload",
    "episode_view_from_json",
    "episode_view_from_payload",
    "episode_view_to_json",
    "episode_view_to_payload",
    "evaluation_result_to_payload",
    "experiment_evidence_from_payload",
    "experiment_evidence_to_payload",
    "experiment_proposal_to_payload",
    "experiment_turn_from_payload",
    "final_submission_to_payload",
    "oracle_response_from_payload",
    "oracle_response_to_payload",
    "player_action_from_json",
    "player_action_from_payload",
    "player_action_json_schema",
    "player_action_to_json",
    "player_action_to_payload",
    "resource_catalog_from_payload",
    "resource_catalog_to_payload",
    "strict_json_loads",
]
