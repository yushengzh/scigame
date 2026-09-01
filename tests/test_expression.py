from __future__ import annotations

import unittest

from role_benchmark.expression import ExpressionError, validate_expression_program


class ExpressionValidationTests(unittest.TestCase):
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
