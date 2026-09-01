import unittest

from experiments.analyze_case_matrix import _probe_submission, analyze


def expression_row(family, world, expression, *, active_pass=False, repeat=1):
    readout = "period_s" if family == "pendulum" else "fringe_spacing_mm"
    return {
        "episode_id": "%s__%s__r%d" % (family, world, repeat),
        "case_family": family,
        "world": world,
        "track": "discovery",
        "repeat": repeat,
        "status": "evaluated",
        "active_pass": active_pass,
        "active_pass_category": "pass" if active_pass else "scientific_failure",
        "scientifically_evaluable": True,
        "protocol_completion": True,
        "termination_kind": "submitted",
        "attempts_used": 3,
        "elapsed_s": 1.0,
        "player_llm_stats": {},
        "oracle_llm_stats": {},
        "final_submission": {
            "model": "expression",
            "parameters": {"outputs": {readout: expression}},
        },
    }


def multiply(*args):
    return {"op": "multiply", "args": list(args)}


def power(variable, exponent):
    return {"op": "power", "args": [{"var": variable}, exponent]}


class CaseMatrixAnalysisTest(unittest.TestCase):
    def test_young_separates_direction_from_counterfactual_shape(self):
        historical_expression = multiply(
            0.001,
            {"var": "wavelength_nm"},
            {"var": "screen_distance_m"},
            power("slit_separation_mm", -1.0),
        )
        historical, error = _probe_submission(
            expression_row("young_double_slit", "historical", historical_expression)
        )
        self.assertIsNone(error)
        self.assertTrue(all(item["direction_correct"] for item in historical))
        self.assertTrue(all(item["shape_correct"] for item in historical))

        counterfactual, error = _probe_submission(
            expression_row(
                "young_double_slit",
                "counterfactual",
                historical_expression,
            )
        )
        self.assertIsNone(error)
        self.assertTrue(all(item["direction_correct"] for item in counterfactual))
        separation = next(
            item for item in counterfactual if item["relation"] == "separation_to_spacing"
        )
        self.assertEqual(separation["predicted_shape"], "decreasing_linear")
        self.assertEqual(separation["expected_shape"], "decreasing_sublinear")
        self.assertFalse(separation["shape_correct"])

    def test_pendulum_ignores_absolute_scale_for_relationship_scoring(self):
        expression = multiply(1000.0, power("length_m", 0.5))
        probes, error = _probe_submission(
            expression_row("pendulum", "historical", expression)
        )
        self.assertIsNone(error)
        self.assertTrue(all(item["direction_correct"] for item in probes))
        self.assertTrue(all(item["shape_correct"] for item in probes))

    def test_analysis_keeps_protocol_failures_in_relationship_denominator(self):
        expression = multiply(2.0, power("length_m", 0.5))
        rows = [
            expression_row("pendulum", "historical", expression, active_pass=True),
            {
                **expression_row("pendulum", "historical", expression, repeat=2),
                "active_pass_category": "player_protocol_failure",
                "scientifically_evaluable": False,
                "protocol_completion": False,
                "termination_kind": "action_rejected",
                "final_submission": None,
            },
        ]
        # Add the other seven matched cells so the factorial contrast is defined.
        for family in ("pendulum", "young_double_slit"):
            for world in ("historical", "counterfactual"):
                for track in ("identification", "discovery"):
                    if family == "pendulum" and world == "historical" and track == "discovery":
                        continue
                    row = expression_row(family, world, 1.0)
                    row["track"] = track
                    row["final_submission"] = None
                    row["scientifically_evaluable"] = False
                    row["protocol_completion"] = False
                    rows.append(row)
        result = analyze(rows)
        historical = next(
            item
            for item in result["relationships"]["cells"]
            if item["case_family"] == "pendulum" and item["world"] == "historical"
        )
        self.assertEqual(historical["n"], 2)
        self.assertEqual(historical["scorable_n"], 1)
        self.assertEqual(historical["direction_full_denominator_rate"], 0.5)
        self.assertEqual(historical["direction_given_scorable_rate"], 1.0)

        overall = result["relationships"]["overall"]
        self.assertEqual(overall["n"], 5)
        self.assertEqual(overall["scorable_n"], 1)


if __name__ == "__main__":
    unittest.main()
