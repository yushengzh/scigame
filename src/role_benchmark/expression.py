"""Small executable expression contract shared across benchmark families.

The representation is deliberately an arithmetic tree rather than Python.
Constants are JSON numbers, variables are
``{"var": "public_control_name"}``, and operations are
``{"op": "...", "args": [...]}``.  Source templates may additionally use
``{"param": "source_parameter_name"}`` when the validator is explicitly
given an allowed parameter set; ordinary executable predictor programs retain
the historical materialized-expression behavior by default.  A program maps
public readout names to expressions through ``{"outputs": {...}}``.
"""

from __future__ import annotations

import math
from types import MappingProxyType
from typing import Any, Dict, Mapping, Optional, Sequence, Set


EXPRESSION_MODEL = "expression"
EXPRESSION_MAX_DEPTH = 24
EXPRESSION_MAX_NODES = 256
EXPRESSION_OPERATOR_ARITIES = MappingProxyType({
    "add": (2, None),
    "subtract": (2, 2),
    "multiply": (2, None),
    "divide": (2, 2),
    "power": (2, 2),
    "negate": (1, 1),
    "exp": (1, 1),
    "log": (1, 1),
    "sin": (1, 1),
    "maximum": (2, None),
    "step": (1, 1),
})
EXPRESSION_OPERATORS = tuple(EXPRESSION_OPERATOR_ARITIES)


class ExpressionError(ValueError):
    """An executable expression is malformed or cannot be evaluated."""


def _number(value: Any, path: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ExpressionError("%s must be a finite number" % path)
    result = float(value)
    if not math.isfinite(result):
        raise ExpressionError("%s must be a finite number" % path)
    return result


def _validate_expression(
    expression: Any,
    *,
    allowed_variables: Optional[Set[str]],
    allowed_parameters: Optional[Set[str]],
    allowed_numeric_literals: Optional[Set[float]],
    path: str,
    depth: int,
    nodes: list[int],
    max_depth: int,
    max_nodes: int,
) -> None:
    nodes[0] += 1
    if nodes[0] > max_nodes:
        raise ExpressionError("expression exceeds %d nodes" % max_nodes)
    if depth > max_depth:
        raise ExpressionError("expression exceeds depth %d" % max_depth)
    if isinstance(expression, bool):
        raise ExpressionError("%s must not be boolean" % path)
    if isinstance(expression, (int, float)):
        numeric = _number(expression, path)
        if (
            allowed_numeric_literals is not None
            and numeric not in allowed_numeric_literals
        ):
            raise ExpressionError("%s numeric literal is not allowed" % path)
        return
    if not isinstance(expression, Mapping):
        raise ExpressionError("%s must be a number, variable, or operation" % path)

    keys = set(expression)
    if keys == {"var"}:
        name = expression["var"]
        if not isinstance(name, str) or not name.strip():
            raise ExpressionError("%s.var must be non-empty text" % path)
        if allowed_variables is not None and name not in allowed_variables:
            raise ExpressionError("%s.var is not a public control" % path)
        return
    if keys == {"param"}:
        name = expression["param"]
        if not isinstance(name, str) or not name.strip():
            raise ExpressionError("%s.param must be non-empty text" % path)
        if allowed_parameters is None:
            raise ExpressionError("%s.param is not allowed" % path)
        if name not in allowed_parameters:
            raise ExpressionError("%s.param is not an allowed parameter" % path)
        return
    if keys != {"op", "args"}:
        raise ExpressionError(
            "%s must contain exactly {'var'}, {'param'}, or {'op', 'args'}" % path
        )
    operator = expression["op"]
    if operator not in EXPRESSION_OPERATOR_ARITIES:
        raise ExpressionError("%s.op is unsupported" % path)
    arguments = expression["args"]
    if not isinstance(arguments, (list, tuple)):
        raise ExpressionError("%s.args must be an array" % path)
    minimum, maximum = EXPRESSION_OPERATOR_ARITIES[operator]
    if len(arguments) < minimum or (maximum is not None and len(arguments) > maximum):
        expected = str(minimum) if minimum == maximum else "at least %d" % minimum
        raise ExpressionError("%s requires %s argument(s)" % (operator, expected))
    for index, argument in enumerate(arguments):
        _validate_expression(
            argument,
            allowed_variables=allowed_variables,
            allowed_parameters=allowed_parameters,
            allowed_numeric_literals=allowed_numeric_literals,
            path="%s.args[%d]" % (path, index),
            depth=depth + 1,
            nodes=nodes,
            max_depth=max_depth,
            max_nodes=max_nodes,
        )


def validate_expression_program(
    parameters: Mapping[str, Any],
    *,
    allowed_variables: Optional[Sequence[str]] = None,
    allowed_parameters: Optional[Sequence[str]] = None,
    allowed_numeric_literals: Optional[Sequence[float]] = None,
    required_outputs: Optional[Sequence[str]] = None,
    max_depth: int = EXPRESSION_MAX_DEPTH,
    max_nodes: int = EXPRESSION_MAX_NODES,
) -> None:
    """Validate one expression-program parameter object.

    ``allowed_variables`` and ``required_outputs`` are case-owned constraints;
    the tree grammar itself contains no truth-specific field names.  Parameter
    leaves are disabled when ``allowed_parameters`` is ``None``, preserving the
    original executable-program contract.  Passing a parameter sequence enables
    source templates and restricts every ``{"param": ...}`` leaf to that set.
    Numeric literals remain unrestricted unless ``allowed_numeric_literals`` is
    supplied.  ``max_depth`` and ``max_nodes`` let a compiler reserve space for
    a deterministic wrapper while retaining the same grammar and runtime caps.
    """

    if isinstance(max_depth, bool) or not isinstance(max_depth, int) or max_depth < 0:
        raise ValueError("max_depth must be a non-negative integer")
    if isinstance(max_nodes, bool) or not isinstance(max_nodes, int) or max_nodes < 1:
        raise ValueError("max_nodes must be a positive integer")
    if not isinstance(parameters, Mapping) or set(parameters) != {"outputs"}:
        raise ExpressionError("parameters must contain exactly 'outputs'")
    outputs = parameters["outputs"]
    if not isinstance(outputs, Mapping) or not outputs:
        raise ExpressionError("parameters.outputs must be a non-empty object")
    if not all(isinstance(name, str) and name.strip() for name in outputs):
        raise ExpressionError("output names must be non-empty text")
    if required_outputs is not None and set(outputs) != set(required_outputs):
        raise ExpressionError("outputs must match the case readouts exactly")
    allowed = set(allowed_variables) if allowed_variables is not None else None
    allowed_params = (
        set(allowed_parameters) if allowed_parameters is not None else None
    )
    allowed_literals = (
        {
            _number(value, "allowed_numeric_literals[%d]" % index)
            for index, value in enumerate(allowed_numeric_literals)
        }
        if allowed_numeric_literals is not None
        else None
    )
    nodes = [0]
    for output, expression in outputs.items():
        _validate_expression(
            expression,
            allowed_variables=allowed,
            allowed_parameters=allowed_params,
            allowed_numeric_literals=allowed_literals,
            path="parameters.outputs.%s" % output,
            depth=0,
            nodes=nodes,
            max_depth=max_depth,
            max_nodes=max_nodes,
        )


def _evaluate(expression: Any, variables: Mapping[str, float]) -> float:
    if isinstance(expression, (int, float)) and not isinstance(expression, bool):
        return _number(expression, "constant")
    if set(expression) == {"var"}:
        name = expression["var"]
        if name not in variables:
            raise ExpressionError("missing value for variable %r" % name)
        return _number(variables[name], "variable %s" % name)
    operator = expression["op"]
    values = [_evaluate(argument, variables) for argument in expression["args"]]
    try:
        if operator == "add":
            result = sum(values)
        elif operator == "subtract":
            result = values[0] - values[1]
        elif operator == "multiply":
            result = math.prod(values)
        elif operator == "divide":
            result = values[0] / values[1]
        elif operator == "power":
            result = values[0] ** values[1]
        elif operator == "negate":
            result = -values[0]
        elif operator == "exp":
            result = math.exp(values[0])
        elif operator == "log":
            result = math.log(values[0])
        elif operator == "sin":
            result = math.sin(values[0])
        elif operator == "maximum":
            result = max(values)
        else:
            result = 1.0 if values[0] > 0.0 else 0.0
    except (ArithmeticError, OverflowError, ValueError) as exc:
        raise ExpressionError("expression is undefined for these controls") from exc
    if isinstance(result, complex) or not math.isfinite(float(result)):
        raise ExpressionError("expression produced a non-finite real value")
    return float(result)


def evaluate_expression_program(
    parameters: Mapping[str, Any],
    controls: Mapping[str, float],
    *,
    allowed_variables: Optional[Sequence[str]] = None,
    required_outputs: Optional[Sequence[str]] = None,
) -> Dict[str, float]:
    """Validate and execute a predictor expression for one intervention."""

    validate_expression_program(
        parameters,
        allowed_variables=allowed_variables,
        required_outputs=required_outputs,
    )
    return {
        output: _evaluate(expression, controls)
        for output, expression in parameters["outputs"].items()
    }


__all__ = [
    "EXPRESSION_MODEL",
    "EXPRESSION_MAX_DEPTH",
    "EXPRESSION_MAX_NODES",
    "EXPRESSION_OPERATOR_ARITIES",
    "EXPRESSION_OPERATORS",
    "ExpressionError",
    "evaluate_expression_program",
    "validate_expression_program",
]
