"""Small constructors for the benchmark's strict expression language."""

from __future__ import annotations

from typing import Any, Mapping


def var(name: str) -> Mapping[str, Any]:
    return {"var": name}


def op(operator: str, *arguments: Any) -> Mapping[str, Any]:
    return {"op": operator, "args": list(arguments)}


def add(*arguments: Any) -> Mapping[str, Any]:
    return op("add", *arguments)


def sub(left: Any, right: Any) -> Mapping[str, Any]:
    return op("subtract", left, right)


def mul(*arguments: Any) -> Mapping[str, Any]:
    return op("multiply", *arguments)


def div(left: Any, right: Any) -> Mapping[str, Any]:
    return op("divide", left, right)


def power(base: Any, exponent: Any) -> Mapping[str, Any]:
    return op("power", base, exponent)


def neg(value: Any) -> Mapping[str, Any]:
    return op("negate", value)


def exp(value: Any) -> Mapping[str, Any]:
    return op("exp", value)


__all__ = ["add", "div", "exp", "mul", "neg", "op", "power", "sub", "var"]
