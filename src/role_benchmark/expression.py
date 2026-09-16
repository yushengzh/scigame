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
EXPRESSION_LANGUAGE_VERSION = "scigame.expression.v2"
# Resource limits, not a symbolic-complexity objective. Frozen runs retain
# their own interpreter and original limits.
EXPRESSION_MAX_DEPTH = 64
EXPRESSION_MAX_NODES = 1024
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
    "erf": (1, 1),
    "erfc": (1, 1),
    "cos": (1, 1),
    "tan": (1, 1),
    "asin": (1, 1),
    "acos": (1, 1),
    "atan": (1, 1),
    "atan2": (2, 2),
    "sinh": (1, 1),
    "cosh": (1, 1),
    "tanh": (1, 1),
    "asinh": (1, 1),
    "acosh": (1, 1),
    "atanh": (1, 1),
    "sqrt": (1, 1),
    "cbrt": (1, 1),
    "abs": (1, 1),
    "minimum": (2, None),
    "expm1": (1, 1),
    "log1p": (1, 1),
    "log2": (1, 1),
    "log10": (1, 1),
    "hypot": (2, None),
    "floor": (1, 1),
    "ceil": (1, 1),
    "round": (1, 1),
    "sign": (1, 1),
})
EXPRESSION_OPERATORS = tuple(EXPRESSION_OPERATOR_ARITIES)


def _cbrt(value: float) -> float:
    # math.cbrt was added in Python 3.11; the project also supports 3.9/3.10.
    if hasattr(math, "cbrt"):
        return math.cbrt(value)
    return math.copysign(abs(value) ** (1.0 / 3.0), value)


_ADDITIONAL_UNARY_FUNCTIONS = MappingProxyType({
    "cos": math.cos, "tan": math.tan,
    "asin": math.asin, "acos": math.acos, "atan": math.atan,
    "sinh": math.sinh, "cosh": math.cosh, "tanh": math.tanh,
    "asinh": math.asinh, "acosh": math.acosh, "atanh": math.atanh,
    "sqrt": math.sqrt, "cbrt": _cbrt, "abs": abs,
    "expm1": math.expm1, "log1p": math.log1p,
    "log2": math.log2, "log10": math.log10,
    "floor": math.floor, "ceil": math.ceil, "round": round,
    "sign": lambda value: float((value > 0) - (value < 0)),
})


class ExpressionError(ValueError):
    """An executable expression is malformed or cannot be evaluated."""


def _number(value: Any, path: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ExpressionError("%s must be a finite number" % path)
    try:
        result = float(value)
    except OverflowError as exc:
        raise ExpressionError("%s must be a finite number" % path) from exc
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
    if not isinstance(operator, str) or operator not in EXPRESSION_OPERATOR_ARITIES:
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
    # JSON object order is not semantic and canonical run logs sort keys.
    # Keep the first validation error reproducible after a log round trip.
    for output in sorted(outputs):
        expression = outputs[output]
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
        elif operator == "erf":
            result = math.erf(values[0])
        elif operator == "erfc":
            # Evaluate directly to preserve small positive tail probabilities.
            result = math.erfc(values[0])
        elif operator == "maximum":
            result = max(values)
        elif operator == "step":
            result = 1.0 if values[0] > 0.0 else 0.0
        elif operator in _ADDITIONAL_UNARY_FUNCTIONS:
            result = _ADDITIONAL_UNARY_FUNCTIONS[operator](values[0])
        elif operator == "atan2":
            # Standard atan2(y, x), in radians.
            result = math.atan2(values[0], values[1])
        elif operator == "hypot":
            result = math.hypot(*values)
        elif operator == "minimum":
            result = min(values)
        else:
            raise ExpressionError("unsupported expression operator")
    except ExpressionError:
        raise
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
        output: _evaluate(parameters["outputs"][output], controls)
        for output in sorted(parameters["outputs"])
    }


__all__ = [
    "EXPRESSION_MODEL",
    "EXPRESSION_LANGUAGE_VERSION",
    "EXPRESSION_MAX_DEPTH",
    "EXPRESSION_MAX_NODES",
    "EXPRESSION_OPERATOR_ARITIES",
    "EXPRESSION_OPERATORS",
    "ExpressionError",
    "evaluate_expression_program",
    "validate_expression_program",
]
