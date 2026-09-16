"""Conservative, bounded formula comparison; numerical agreement is not proof.

The existing AST interpreter owns execution. This module proves a small set of
real-algebra identities, treating other operators as uninterpreted functions.
It never evaluates generated Python and never rewrites a submitted predictor.
"""
from __future__ import annotations

import itertools
import json
import math
from fractions import Fraction

from .expression import ExpressionError, evaluate_expression_program, validate_expression_program

FORMULA_METRIC_VERSION = "scigame.formula_consistency"
MAX_TERMS = 256
MAX_OPERATIONS = 50000


class _ProofLimit(ValueError):
    pass


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


class _Algebra:
    def __init__(self):
        self.work = 0
        self.functions = []

    def check(self, terms, work=1):
        self.work += work
        if self.work > MAX_OPERATIONS or len(terms) > MAX_TERMS:
            raise _ProofLimit("symbolic work limit")
        if any(abs(v.numerator).bit_length() > 8192 or v.denominator.bit_length() > 8192
               for v in terms.values()):
            raise _ProofLimit("symbolic coefficient limit")
        return {k: v for k, v in terms.items() if v}

    def add(self, left, right):
        result = dict(left)
        for key, value in right.items():
            result[key] = result.get(key, Fraction(0)) + value
        return self.check(result, len(left) + len(right))

    def mul(self, left, right):
        if len(left) * len(right) > MAX_OPERATIONS - self.work:
            raise _ProofLimit("symbolic expansion limit")
        result = {}
        for a, x in left.items():
            for b, y in right.items():
                key = tuple(sorted(a + b))
                result[key] = result.get(key, Fraction(0)) + x * y
                self.check(result)
        return self.check(result)

    def pair(self, numerator, denominator):
        if not denominator:
            raise _ProofLimit("zero symbolic denominator")
        # Normalize constant factors; polynomial GCD search is intentionally absent.
        scale = denominator[sorted(denominator)[0]]
        return ({k: v / scale for k, v in numerator.items()},
                {k: v / scale for k, v in denominator.items()})

    def key(self, pair):
        return [[[list(k), str(v)] for k, v in sorted(poly.items())] for poly in self.pair(*pair)]

    def expression(self, node):
        one = {(): Fraction(1)}
        if isinstance(node, (int, float)):
            number = Fraction(str(node))
            return ({(): number} if number else {}, one)
        if "var" in node:
            return {("variable:" + node["var"],): Fraction(1)}, one
        op = node["op"]
        args = [self.expression(x) for x in node["args"]]
        if op == "negate":
            num, den = args[0]
            return {k: -v for k, v in num.items()}, den
        if op in {"add", "subtract"}:
            num, den = args[0]
            for other_num, other_den in args[1:]:
                if op == "subtract":
                    other_num = {k: -v for k, v in other_num.items()}
                num, den = self.add(self.mul(num, other_den), self.mul(other_num, den)), self.mul(den, other_den)
            return self.pair(num, den)
        if op in {"multiply", "divide"}:
            num, den = args[0]
            for other_num, other_den in args[1:]:
                if op == "divide":
                    other_num, other_den = other_den, other_num
                num, den = self.mul(num, other_num), self.mul(den, other_den)
            return self.pair(num, den)
        exponent = node["args"][1] if op == "power" else None
        if isinstance(exponent, (int, float)) and float(exponent).is_integer() and abs(exponent) <= 8:
            num, den = one, one
            base_num, base_den = args[0]
            if exponent < 0:
                base_num, base_den = base_den, base_num
            for _ in range(abs(int(exponent))):
                num, den = self.mul(num, base_num), self.mul(den, base_den)
            return self.pair(num, den)
        keys = [self.key(arg) for arg in args]
        if op in {"maximum", "minimum", "hypot"}:
            keys.sort(key=_canonical)
        # Intern function terms within this comparison. Small local term numbers
        # keep nested expressions compact without digests or reference indexes.
        term = [op, keys]
        if term not in self.functions:
            self.functions.append(term)
        atom = "function:%d" % self.functions.index(term)
        return {(atom,): Fraction(1)}, one

    def equivalent(self, left, right):
        a, b = self.expression(left)
        c, d = self.expression(right)
        return self.mul(a, d) == self.mul(c, b)


def _shape(node):
    if isinstance(node, (int, float)):
        return "number"
    if "var" in node:
        return ["variable", node["var"]]
    children = [_shape(x) for x in node["args"]]
    if node["op"] in {"add", "multiply", "minimum", "maximum", "hypot"}:
        children.sort(key=_canonical)
    return [node["op"], children]


def _domain_safe(program, domains):
    # Reuse the existing conservative domain checker, rather than a second
    # implementation of logarithm/root/pole conditions. Failure means unknown.
    from .temporal.filter import _expression_interval
    try:
        for expression in program["outputs"].values():
            lo, hi = _expression_interval(expression, domains)
            if not math.isfinite(lo) or not math.isfinite(hi):
                return False
        return True
    except (ValueError, ArithmeticError, KeyError, TypeError, RecursionError):
        return False


def compare_formulas(candidate, reference, controls, *, probes=(), relative_tolerance=1e-9,
                     absolute_tolerance=1e-12):
    """Compare programs on the declared domain; return proof or a checked witness.

    Numbers denote exact decimal constants for algebraic proofs. Counterexamples
    use the actual interpreter and explicit numerical tolerances. Passing every
    probe without an algebraic proof remains inconclusive, never equivalent.
    """
    if any(not math.isfinite(x) or x < 0 for x in (relative_tolerance, absolute_tolerance)):
        raise ValueError("formula tolerances must be finite and nonnegative")
    names = tuple(c.name for c in controls)
    outputs = tuple(reference["outputs"])
    validate_expression_program(reference, allowed_variables=names, required_outputs=outputs)
    base = {"version": FORMULA_METRIC_VERSION,
        "relative_tolerance": relative_tolerance, "absolute_tolerance": absolute_tolerance}
    try:
        validate_expression_program(candidate, allowed_variables=names, required_outputs=outputs)
    except (ExpressionError, ValueError, TypeError):
        return {**base, "status": "not_equivalent", "method": "invalid_predictor_contract", "outputs": {}}
    shape = all(_shape(candidate["outputs"][name]) == _shape(reference["outputs"][name]) for name in outputs)
    domains, choices = {}, {}
    for control in controls:
        values = control.allowed_values
        if values and all(isinstance(x, (int, float)) and not isinstance(x, bool) for x in values):
            values = sorted(set(values))
            domains[control.name] = (min(values), max(values))
            choices[control.name] = [values[0], values[len(values)//2], values[-1]]
        elif control.minimum is not None and control.maximum is not None:
            lo, hi = control.minimum, control.maximum
            domains[control.name] = (lo, hi)
            choices[control.name] = [lo, lo / 2 + hi / 2, hi]
    safe = len(domains) == len(names) and _domain_safe(candidate, domains) and _domain_safe(reference, domains)
    per_output = {}
    for name in outputs:
        left, right = candidate["outputs"][name], reference["outputs"][name]
        if left == right:
            per_output[name] = {"status": "equivalent", "method": "identical_ast"}
            continue
        try:
            proven = safe and _Algebra().equivalent(left, right)
        except (_ProofLimit, ArithmeticError, RecursionError):
            proven = False
        per_output[name] = {"status": "equivalent" if proven else "inconclusive",
                            "method": "domain_checked_algebra" if proven else "no_symbolic_proof"}
    if all(row["status"] == "equivalent" for row in per_output.values()):
        return {**base, "status": "equivalent", "method": "symbolic", "operator_structure_match": shape,
                "outputs": per_output, "probes_checked": 0}
    sample_points = list(probes)
    if len(choices) == len(names):
        sample_points += [dict(zip(names, p)) for p in itertools.islice(
            itertools.product(*(choices[name] for name in names)), 64)]
    checked, seen = 0, set()
    for point in sample_points:
        if set(point) != set(names) or any(
            (c.allowed_values and point[c.name] not in c.allowed_values)
            or (c.minimum is not None and point[c.name] < c.minimum)
            or (c.maximum is not None and point[c.name] > c.maximum) for c in controls):
            continue
        identity = _canonical(point)
        if identity in seen:
            continue
        seen.add(identity)
        try:
            expected = evaluate_expression_program(reference, point)
        except (ExpressionError, ValueError):
            continue
        checked += 1
        try:
            actual = evaluate_expression_program(candidate, point)
        except (ExpressionError, ValueError):
            return {**base, "status": "not_equivalent", "method": "domain_counterexample",
                    "operator_structure_match": shape, "outputs": per_output,
                    "counterexample": {"controls": point, "reference": expected, "candidate": None}, "probes_checked": checked}
        different = [name for name in outputs if not math.isclose(actual[name], expected[name],
            rel_tol=relative_tolerance, abs_tol=absolute_tolerance)]
        if different:
            for name in different:
                per_output[name] = {"status": "not_equivalent", "method": "numerical_counterexample"}
            return {**base, "status": "not_equivalent", "method": "numerical_counterexample",
                    "operator_structure_match": shape, "outputs": per_output,
                    "counterexample": {"controls": point, "reference": expected, "candidate": actual}, "probes_checked": checked}
    return {**base, "status": "inconclusive", "method": "no_symbolic_proof",
            "operator_structure_match": shape, "outputs": per_output, "probes_checked": checked}
