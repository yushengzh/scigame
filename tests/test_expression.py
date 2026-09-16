from __future__ import annotations

import json
import math
import unittest
from unittest.mock import patch

from role_benchmark.expression import (
    EXPRESSION_LANGUAGE_VERSION, EXPRESSION_MAX_DEPTH, EXPRESSION_MAX_NODES,
    EXPRESSION_OPERATOR_ARITIES, ExpressionError, _cbrt,
    evaluate_expression_program, validate_expression_program,
)


# One ordinary-domain example per operator, also reused to check the independent
# dataset interpreter. Every newly registered operator must have an example.
OPERATOR_EXAMPLES = {
    "add": ([2, 3, 4], 9), "subtract": ([7, 2], 5),
    "multiply": ([2, 3, 4], 24), "divide": ([7, 2], 3.5),
    "power": ([3, 2], 9), "negate": ([2], -2),
    "exp": ([1], math.e), "log": ([math.e], 1),
    "sin": ([math.pi / 2], 1), "maximum": ([1, 3, 2], 3),
    "step": ([0], 0), "erf": ([0], 0), "erfc": ([0], 1),
    "cos": ([math.pi], -1), "tan": ([math.pi / 4], 1),
    "asin": ([1], math.pi / 2), "acos": ([-1], math.pi),
    "atan": ([1], math.pi / 4), "atan2": ([1, -1], 3 * math.pi / 4),
    "sinh": ([0], 0), "cosh": ([0], 1), "tanh": ([0], 0),
    "asinh": ([0], 0), "acosh": ([1], 0), "atanh": ([0], 0),
    "sqrt": ([9], 3), "cbrt": ([-8], -2), "abs": ([-3], 3),
    "minimum": ([3, -1, 2], -1), "expm1": ([1e-20], 1e-20),
    "log1p": ([1e-20], 1e-20), "log2": ([8], 3), "log10": ([100], 2),
    "hypot": ([3, 4, 12], 13), "floor": ([-1.2], -2),
    "ceil": ([-1.2], -1), "round": ([2.5], 2), "sign": ([-5], -1),
}


def program(expression):
    return {"outputs": {"y": expression}}


def structured_payload(expression):
    from role_benchmark.structured_actions import STRUCTURED_ACTION_SCHEMA
    return {
        "wire_schema": STRUCTURED_ACTION_SCHEMA, "kind": "final",
        "portfolio": {"hypotheses": [
            {"hypothesis_id": "H1", "statement": "A test predictor.", "confidence": 1.0},
        ]},
        "experiment": None,
        "final": {"explanation": "Synthetic expression fixture.", "model": "expression",
                  "parameters": {"outputs": [{"name": "y", "value": expression}]},
                  "hypothesis_id": "H1", "scope_conditions": ["Synthetic test."]},
    }


class ExpressionValidationTests(unittest.TestCase):
    def test_error_diagnostics_survive_canonical_json_round_trip(self):
        original = {"outputs": {
            "volume": {"var": "missing_volume"},
            "pressure": {"var": "missing_pressure"},
        }}
        canonical = json.loads(json.dumps(original, sort_keys=True))
        for operation in (
            lambda p: validate_expression_program(p, allowed_variables=("x",)),
            lambda p: evaluate_expression_program(p, {}),
        ):
            messages = []
            for parameters in (original, canonical):
                with self.assertRaises(ExpressionError) as caught:
                    operation(parameters)
                messages.append(str(caught.exception))
            self.assertEqual(messages[0], messages[1])
            self.assertIn("pressure", messages[0])

    def test_version_and_all_operator_examples(self):
        self.assertEqual(EXPRESSION_LANGUAGE_VERSION, "scigame.expression.v2")
        self.assertEqual(set(OPERATOR_EXAMPLES), set(EXPRESSION_OPERATOR_ARITIES))
        for name, (args, expected) in OPERATOR_EXAMPLES.items():
            with self.subTest(operator=name):
                value = evaluate_expression_program(program({"op": name, "args": args}), {})["y"]
                self.assertTrue(math.isclose(value, expected, rel_tol=1e-12, abs_tol=1e-30))

    def test_all_operators_round_trip_through_structured_and_wire_actions(self):
        from role_benchmark.structured_actions import structured_action_from_json
        from role_benchmark.wire import player_action_to_json, player_action_from_json
        for name, (args, expected) in OPERATOR_EXAMPLES.items():
            with self.subTest(operator=name):
                payload = structured_payload({"op": name, "args": args})
                action = structured_action_from_json(json.dumps(payload))
                decoded = player_action_from_json(player_action_to_json(action))
                self.assertEqual(action, decoded)
                actual = evaluate_expression_program(decoded.final.parameters, {})["y"]
                self.assertTrue(math.isclose(actual, expected, rel_tol=1e-12, abs_tol=1e-30))

    def test_all_operator_arities_remain_enforced(self):
        for name, (minimum, maximum) in EXPRESSION_OPERATOR_ARITIES.items():
            for count in [minimum - 1] + ([] if maximum is None else [maximum + 1]):
                with self.subTest(operator=name, count=count):
                    with self.assertRaises(ExpressionError):
                        validate_expression_program(program({"op": name, "args": [1] * count}))

    def test_source_domain_checker_supports_every_operator(self):
        from role_benchmark.temporal.filter import _expression_interval
        for name, (args, _) in OPERATOR_EXAMPLES.items():
            with self.subTest(operator=name):
                expression = {"op": name, "args": args}
                lower, upper = _expression_interval(expression, {})
                actual = evaluate_expression_program(program(expression), {})["y"]
                self.assertLessEqual(lower, actual)
                self.assertLessEqual(actual, upper)

    def test_source_domain_checker_bounds_intervals_and_rejects_singularities(self):
        from role_benchmark.temporal.filter import _expression_interval, _UnsafeDomain
        domains = {"cos": (-4, 5), "tan": (-0.5, 0.5), "asin": (-1, 1),
                   "acos": (-1, 1), "cosh": (-3, 2), "abs": (-3, 2),
                   "sqrt": (0, 4), "cbrt": (-8, 27), "atanh": (-0.5, 0.5),
                   "log1p": (-0.5, 2), "sign": (-2, 3), "round": (-2.5, 3.5)}
        for name, (lo, hi) in domains.items():
            expression = {"op": name, "args": [{"var": "x"}]}
            lower, upper = _expression_interval(expression, {"x": (lo, hi)})
            for index in range(101):
                x = lo + (hi - lo) * index / 100
                actual = evaluate_expression_program(program(expression), {"x": x})["y"]
                self.assertLessEqual(lower, actual)
                self.assertLessEqual(actual, upper)
        for name, domain in (("tan", (0, math.pi)), ("tan", (1e20, 1e20)),
                             ("sqrt", (-1, 1)), ("log1p", (-1, 2)),
                             ("asin", (-2, 0)), ("acosh", (0, 2)),
                             ("atanh", (-1, 0.5))):
            with self.subTest(operator=name, domain=domain), self.assertRaises(_UnsafeDomain):
                _expression_interval({"op": name, "args": [{"var": "x"}]}, {"x": domain})

    def test_real_domain_errors_are_not_repaired(self):
        invalid = [("sqrt", [-1]), ("log", [0]), ("log2", [-1]), ("log10", [0]),
                   ("log1p", [-1]), ("asin", [1.01]), ("acos", [-1.01]),
                   ("acosh", [0.99]), ("atanh", [1]), ("atanh", [-1]),
                   ("divide", [1, 0]), ("power", [-1, 0.5]),
                   ("exp", [1000]), ("expm1", [1000]), ("sinh", [1000]),
                   ("cosh", [1000])]
        for name, args in invalid:
            with self.subTest(operator=name, args=args):
                with self.assertRaises(ExpressionError):
                    evaluate_expression_program(program({"op": name, "args": args}), {})

    def test_stable_elementary_functions_and_rounding_conventions(self):
        for name in ("expm1", "log1p"):
            self.assertEqual(evaluate_expression_program(program({"op": name, "args": [1e-20]}), {})["y"], 1e-20)
        self.assertTrue(math.isfinite(evaluate_expression_program(program({"op": "hypot", "args": [1e308, 1e308]}), {})["y"]))
        for value, expected in ((2.5, 2), (3.5, 4), (-2.5, -2)):
            self.assertEqual(evaluate_expression_program(program({"op": "round", "args": [value]}), {})["y"], expected)
        self.assertEqual(evaluate_expression_program(program({"op": "sign", "args": [0]}), {})["y"], 0)
        self.assertEqual(evaluate_expression_program(program({"op": "step", "args": [0]}), {})["y"], 0)
        # Exercise the Python 3.9/3.10 cube-root fallback without global changes.
        with patch("role_benchmark.expression.hasattr", return_value=False, create=True):
            self.assertAlmostEqual(_cbrt(-8), -2)
            self.assertEqual(math.copysign(1, _cbrt(-0.0)), -1)

    def test_long_expression_and_json_envelope_limits_agree(self):
        from role_benchmark.structured_actions import structured_action_from_json
        from role_benchmark.wire import DEFAULT_MAX_ACTION_BYTES
        expression = {"op": "add", "args": [
            {"op": "cos", "args": [{"var": "x"}]} for _ in range(500)
        ]}
        # 1,001 AST nodes fit the expression limit. The action envelope has a
        # separate byte limit, including non-expression explanatory text.
        payload = structured_payload(expression)
        payload["final"]["explanation"] = "Synthetic explanation. " * 3500
        encoded = json.dumps(payload)
        self.assertGreater(len(encoded.encode()), 65_536)
        self.assertLess(len(encoded.encode()), DEFAULT_MAX_ACTION_BYTES)
        action = structured_action_from_json(encoded)
        self.assertEqual(evaluate_expression_program(action.final.parameters, {"x": 0}, allowed_variables=("x",))["y"], 500)

    def test_expression_node_limit_is_global_and_inclusive(self):
        self.assertEqual(EXPRESSION_MAX_NODES, 1024)
        at_limit = program({"op": "add", "args": [1] * (EXPRESSION_MAX_NODES - 1)})
        self.assertEqual(evaluate_expression_program(at_limit, {})["y"], EXPRESSION_MAX_NODES - 1)
        with self.assertRaisesRegex(ExpressionError, "exceeds 1024 nodes"):
            validate_expression_program({"outputs": {"y": at_limit["outputs"]["y"], "z": 0}})
        with self.assertRaisesRegex(ExpressionError, "exceeds 1024 nodes"):
            validate_expression_program(program({"op": "add", "args": [1] * EXPRESSION_MAX_NODES}))

    def test_depth_limit_fits_structured_action_envelope(self):
        from role_benchmark.structured_actions import structured_action_from_json
        expression = {"var": "x"}
        for _ in range(EXPRESSION_MAX_DEPTH):
            expression = {"op": "negate", "args": [expression]}
        action = structured_action_from_json(json.dumps(structured_payload(expression)))
        self.assertEqual(evaluate_expression_program(action.final.parameters, {"x": 2})["y"], 2)
        with self.assertRaisesRegex(ExpressionError, "exceeds depth 64"):
            validate_expression_program(program({"op": "negate", "args": [expression]}))

    def test_malformed_operators_and_nonfinite_numbers_are_rejected(self):
        for name in (["cos"], {"name": "cos"}, None, "eval"):
            with self.subTest(operator=name), self.assertRaises(ExpressionError):
                validate_expression_program(program({"op": name, "args": [0]}))
        for value in (math.inf, math.nan, True, 10 ** 1000):
            with self.assertRaises(ExpressionError):
                evaluate_expression_program(program(value), {})

    def test_parameter_leaves_are_opt_in(self):
        program = {"outputs": {"y": {"param": "scale"}}}

        with self.assertRaisesRegex(ExpressionError, "param is not allowed"):
            validate_expression_program(program, required_outputs=("y",))

        validate_expression_program(
            program,
            allowed_parameters=("scale",),
            required_outputs=("y",),
        )

    def test_parameter_allowlist_is_enforced(self):
        with self.assertRaisesRegex(ExpressionError, "not an allowed parameter"):
            validate_expression_program(
                {"outputs": {"y": {"param": "unlinked_scale"}}},
                allowed_parameters=("scale",),
                required_outputs=("y",),
            )

    def test_numeric_literal_allowlist_is_opt_in(self):
        program = {
            "outputs": {
                "y": {
                    "op": "multiply",
                    "args": [2.0, {"var": "x"}],
                }
            }
        }

        # Existing discovery programs retain unrestricted finite literals.
        validate_expression_program(
            program,
            allowed_variables=("x",),
            required_outputs=("y",),
        )

        with self.assertRaisesRegex(ExpressionError, "numeric literal is not allowed"):
            validate_expression_program(
                program,
                allowed_variables=("x",),
                allowed_numeric_literals=(0.0, 1.0),
                required_outputs=("y",),
            )

        validate_expression_program(
            {
                "outputs": {
                    "y": {
                        "op": "add",
                        "args": [0.0, 1.0],
                    }
                }
            },
            allowed_numeric_literals=(0.0, 1.0),
            required_outputs=("y",),
        )

    def test_callers_can_reserve_compiler_depth_and_node_headroom(self):
        expression = {"var": "x"}
        for _ in range(3):
            expression = {"op": "negate", "args": [expression]}
        program = {"outputs": {"y": expression}}

        validate_expression_program(
            program,
            allowed_variables=("x",),
            required_outputs=("y",),
            max_depth=3,
            max_nodes=4,
        )
        with self.assertRaisesRegex(ExpressionError, "exceeds depth 2"):
            validate_expression_program(
                program,
                allowed_variables=("x",),
                required_outputs=("y",),
                max_depth=2,
            )
        with self.assertRaisesRegex(ExpressionError, "exceeds 3 nodes"):
            validate_expression_program(
                program,
                allowed_variables=("x",),
                required_outputs=("y",),
                max_nodes=3,
            )


if __name__ == "__main__":
    unittest.main()
