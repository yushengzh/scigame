"""Strict provider schema with no case-dependent experimental restrictions.

Open dictionaries are represented by arrays of named entries. Conversion is
deterministic and never evaluates, repairs, or simplifies a scientific model.
The canonical action decoder and Oracle remain authoritative.
"""

from copy import deepcopy

from .wire import (
    DEFAULT_MAX_ACTION_BYTES, PLAYER_ACTION_SCHEMA, WireDecodeError,
    _expression_operator_schema_variants,
    player_action_from_payload, player_action_to_payload, strict_json_loads,
)


STRUCTURED_ACTION_SCHEMA = "role_benchmark.structured_action.v1"
STRUCTURED_ACTION_CONTRACT = "executable_grammar.v2"


def _object(properties, nullable=False):
    return {"type": ["object", "null"] if nullable else "object",
            "properties": properties, "required": list(properties),
            "additionalProperties": False}


def _array(items):
    return {"type": "array", "items": items}


def _entries(value):
    return _array(_object({"name": {"type": "string"}, "value": value}))


def structured_action_json_schema():
    """Return a fresh, case-independent schema for structured generation.

    Names, experimental bounds, categorical values and confidence thresholds
    deliberately do not appear here. Public expression syntax is generated from
    the same operator/arity table used by the executable language, not from a
    case's ground truth. The wire representation remains unchanged.
    """
    string = {"type": "string"}
    number = {"type": "number"}
    value = {"$ref": "#/$defs/value"}
    expression = {"$ref": "#/$defs/expression"}
    schema = _object({
        "wire_schema": {"type": "string", "enum": [STRUCTURED_ACTION_SCHEMA]},
        "kind": {"type": "string", "enum": ["experiment", "final"]},
        "portfolio": _object({"hypotheses": _array(_object({
            "hypothesis_id": string, "statement": string, "confidence": number,
        }))}),
        "experiment": _object({
            "intent": string, "apparatus": string, "controls": _entries(value),
            "readouts": _array(string), "replicates": {"type": "integer"},
            "forecasts": _entries(_entries(number)),
        }, nullable=True),
        "final": _object({
            "explanation": string, "model": string,
            "parameters": {"anyOf": [
                _object({"outputs": _entries(expression)}),
                _object({"entries": _entries(value)}),
            ]},
            "hypothesis_id": {"type": ["string", "null"]},
            "scope_conditions": _array(string),
        }, nullable=True),
    })
    schema["$defs"] = {
        "expression": {"anyOf": [
            number, _object({"var": string}),
            *_expression_operator_schema_variants(),
        ]},
        "value": {"anyOf": [
            {"type": ["string", "number", "boolean", "null"]},
            _array(value), _object({"entries": _entries(value)}),
        ]},
    }
    return deepcopy(schema)


def _exact(value, keys, path):
    if not isinstance(value, dict) or set(value) != set(keys):
        raise WireDecodeError("invalid_structure", path,
                              "expected an object with keys " + ", ".join(keys))


def _decode_entries(entries, path, decode):
    if not isinstance(entries, list):
        raise WireDecodeError("wrong_type", path, "expected named entries")
    result = {}
    for index, entry in enumerate(entries):
        location = "%s[%d]" % (path, index)
        _exact(entry, ("name", "value"), location)
        name = entry["name"]
        if not isinstance(name, str):
            raise WireDecodeError("wrong_type", location + ".name", "expected string")
        if name in result:
            raise WireDecodeError("duplicate_key", location + ".name",
                                  "duplicate named entry %r" % name)
        result[name] = decode(entry["value"], location + ".value")
    return result


def _decode_value(value, path):
    if isinstance(value, dict):
        _exact(value, ("entries",), path)
        return _decode_entries(value["entries"], path + ".entries", _decode_value)
    if isinstance(value, list):
        return [_decode_value(item, "%s[%d]" % (path, i))
                for i, item in enumerate(value)]
    return value


def _unchanged(value, path):
    return value


def structured_action_from_json(text, *, max_bytes=DEFAULT_MAX_ACTION_BYTES):
    payload = strict_json_loads(text, max_bytes=max_bytes)
    _exact(payload, ("wire_schema", "kind", "portfolio", "experiment", "final"), "$")
    if payload["wire_schema"] != STRUCTURED_ACTION_SCHEMA:
        raise WireDecodeError("unsupported_schema", "$.wire_schema",
                              "expected %r" % STRUCTURED_ACTION_SCHEMA)
    payload["wire_schema"] = PLAYER_ACTION_SCHEMA
    experiment = payload["experiment"]
    if experiment is not None:
        _exact(experiment, ("intent", "apparatus", "controls", "readouts",
                            "replicates", "forecasts"), "$.experiment")
        experiment["controls"] = _decode_entries(
            experiment["controls"], "$.experiment.controls", _decode_value)
        experiment["forecasts"] = _decode_entries(
            experiment["forecasts"], "$.experiment.forecasts",
            lambda value, path: _decode_entries(value, path, _unchanged))
    final = payload["final"]
    if final is not None:
        _exact(final, ("explanation", "model", "parameters", "hypothesis_id",
                       "scope_conditions"), "$.final")
        parameters = final["parameters"]
        if isinstance(parameters, dict) and set(parameters) == {"outputs"}:
            final["parameters"] = {"outputs": _decode_entries(
                parameters["outputs"], "$.final.parameters.outputs", _unchanged)}
        else:
            _exact(parameters, ("entries",), "$.final.parameters")
            final["parameters"] = _decode_entries(
                parameters["entries"], "$.final.parameters.entries", _decode_value)
    return player_action_from_payload(payload, max_bytes=max_bytes)


def _encode_value(value):
    if isinstance(value, dict):
        return {"entries": _encode_entries(value, _encode_value)}
    if isinstance(value, list):
        return [_encode_value(item) for item in value]
    return value


def _encode_entries(value, encode=lambda item: item):
    return [{"name": name, "value": encode(item)} for name, item in value.items()]


def structured_action_to_payload(action):
    """Reference encoder for fixtures and interoperability, not model repair."""
    payload = player_action_to_payload(action)
    payload["wire_schema"] = STRUCTURED_ACTION_SCHEMA
    if payload["experiment"] is not None:
        experiment = payload["experiment"]
        experiment["controls"] = _encode_entries(experiment["controls"], _encode_value)
        experiment["forecasts"] = _encode_entries(experiment["forecasts"], _encode_entries)
    if payload["final"] is not None:
        parameters = payload["final"]["parameters"]
        if set(parameters) == {"outputs"} and isinstance(parameters["outputs"], dict):
            payload["final"]["parameters"] = {"outputs": _encode_entries(parameters["outputs"])}
        else:
            payload["final"]["parameters"] = {"entries": _encode_entries(parameters, _encode_value)}
    return payload
