import csv
import tempfile
import unittest
from pathlib import Path

from experiments.analyze_case_matrix import (
    ANALYSIS_SCHEMA,
    CELL_FIELDS,
    _probe_submission,
    _write_cell_csv,
    _write_relationship_csv,
    analyze,
)
from role_benchmark import (
    ADAPTIVE_EXPERIMENTAL_DESIGN as ADAPTIVE,
    FIXED_EXPERIMENTAL_DESIGN as FIXED,
    PRIOR_ONLY_BASELINE as PRIOR,
)


HISTORICAL_COUNTERFACTUAL = "historical_counterfactual"
TEMPORAL = "temporal"


def expression_row(
    family,
    condition_role,
    expression,
    *,
    active_pass=False,
    repeat=1,
    dataset_kind=HISTORICAL_COUNTERFACTUAL,
    variant_id="base_v1",
    condition_id=None,
    source_condition_id=None,
    source_paper_id=None,
    source_version_id=None,
    task_setting="discovery",
    evaluation_method=ADAPTIVE,
    prediction_score=0.5,
):
    readout = "period_s" if family == "pendulum" else "fringe_spacing_mm"
    if condition_id is None:
        condition_id = {
            "historical": "condition_a",
            "counterfactual": "condition_b",
            "source_reported": "condition_a",
        }[condition_role]
    row = {
        "episode_id": "%s__%s__%s__r%d"
        % (family, condition_id, evaluation_method, repeat),
        "dataset_kind": dataset_kind,
        "case_family": family,
        "variant_id": variant_id,
        "condition_id": condition_id,
        "condition_role": condition_role,
        "source_condition_id": source_condition_id,
        "task_setting": task_setting,
        "evaluation_method": evaluation_method,
        "repeat": repeat,
        "status": "evaluated",
        "active_pass": active_pass,
        "active_pass_category": "pass" if active_pass else "scientific_failure",
        "scientifically_evaluable": True,
        "protocol_completion": True,
        "termination_kind": "submitted",
        "attempts_used": 3,
        "elapsed_s": 1.0,
        "scores": {"held_out_prediction_score": prediction_score},
        "player_llm_stats": {},
        "oracle_llm_stats": {},
        "final_submission": {
            "model": "expression",
            "parameters": {"outputs": {readout: expression}},
        },
    }
    if source_paper_id is not None:
        row["source_paper_id"] = source_paper_id
    if source_version_id is not None:
        row["source_version_id"] = source_version_id
    return row


def multiply(*args):
    return {"op": "multiply", "args": list(args)}


def power(variable, exponent):
    return {"op": "power", "args": [{"var": variable}, exponent]}


def estimand_rows(
    family,
    values,
    *,
    variant_id="base_v1",
    task_setting="discovery",
):
    rows = []
    condition_ids = {
        "historical": "condition_b",
        "counterfactual": "condition_a",
    }
    for evaluation_method in (PRIOR, FIXED, ADAPTIVE):
        for condition_role in ("historical", "counterfactual"):
            rows.append(
                expression_row(
                    family,
                    condition_role,
                    1.0,
                    active_pass=(condition_role == "historical"),
                    variant_id=variant_id,
                    condition_id=condition_ids[condition_role],
                    task_setting=task_setting,
                    evaluation_method=evaluation_method,
                    prediction_score=values[(evaluation_method, condition_role)],
                )
            )
    return rows


def temporal_estimand_rows(
    family,
    source_paper_id,
    source_version_id,
    condition_id,
    source_condition_id,
    values,
    *,
    variant_id="source_reported_v1",
    task_setting="discovery",
):
    return [
        expression_row(
            family,
            "source_reported",
            1.0,
            dataset_kind=TEMPORAL,
            variant_id=variant_id,
            condition_id=condition_id,
            source_condition_id=source_condition_id,
            source_paper_id=source_paper_id,
            source_version_id=source_version_id,
            task_setting=task_setting,
            evaluation_method=method,
            prediction_score=values[method],
        )
        for method in (PRIOR, FIXED, ADAPTIVE)
    ]


class CaseMatrixAnalysisTest(unittest.TestCase):
    def test_young_separates_direction_from_counterfactual_shape(self):
        historical_expression = multiply(
            0.001,
            {"var": "wavelength_nm"},
            {"var": "screen_distance_m"},
            power("slit_separation_mm", -1.0),
        )
        historical, error = _probe_submission(
            expression_row(
                "young_double_slit",
                "historical",
                historical_expression,
            )
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
            item
            for item in counterfactual
            if item["relation"] == "separation_to_spacing"
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
                **expression_row(
                    "pendulum",
                    "historical",
                    expression,
                    repeat=2,
                ),
                "active_pass_category": "player_protocol_failure",
                "scientifically_evaluable": False,
                "protocol_completion": False,
                "termination_kind": "action_rejected",
                "final_submission": None,
            },
        ]
        # Add the other seven H/C task-setting cells so contrasts are defined.
        for family in ("pendulum", "young_double_slit"):
            for condition_role in ("historical", "counterfactual"):
                for task_setting in ("identification", "discovery"):
                    if (
                        family == "pendulum"
                        and condition_role == "historical"
                        and task_setting == "discovery"
                    ):
                        continue
                    row = expression_row(
                        family,
                        condition_role,
                        1.0,
                        task_setting=task_setting,
                    )
                    row["final_submission"] = None
                    row["scientifically_evaluable"] = False
                    row["protocol_completion"] = False
                    rows.append(row)
        result = analyze(rows)
        historical = next(
            item
            for item in result["relationships"]["cells"]
            if item["case_family"] == "pendulum"
            and item["condition_role"] == "historical"
        )
        self.assertEqual(historical["n"], 2)
        self.assertEqual(historical["scorable_n"], 1)
        self.assertEqual(historical["direction_full_denominator_rate"], 0.5)
        self.assertEqual(historical["direction_given_scorable_rate"], 1.0)

        overall = result["relationships"]["overall"]
        self.assertEqual(overall["n"], 5)
        self.assertEqual(overall["scorable_n"], 1)

    def test_primary_estimands_use_prediction_score(self):
        first = {
            (PRIOR, "historical"): 0.90,
            (PRIOR, "counterfactual"): 0.40,
            (FIXED, "historical"): 0.80,
            (FIXED, "counterfactual"): 0.70,
            (ADAPTIVE, "historical"): 0.95,
            (ADAPTIVE, "counterfactual"): 0.90,
        }
        second = {
            (PRIOR, "historical"): 0.80,
            (PRIOR, "counterfactual"): 0.60,
            (FIXED, "historical"): 0.90,
            (FIXED, "counterfactual"): 0.80,
            (ADAPTIVE, "historical"): 1.00,
            (ADAPTIVE, "counterfactual"): 0.90,
        }
        rows = estimand_rows("pendulum", first)
        rows += estimand_rows("young_double_slit", second)
        rows += estimand_rows(
            "pendulum",
            second,
            variant_id="hard_v1",
            task_setting="identification",
        )

        result = analyze(rows)
        self.assertEqual(result["schema"], ANALYSIS_SCHEMA)
        self.assertEqual(len(result["cells"]), 18)
        self.assertEqual(
            {item["evaluation_method"] for item in result["families"]},
            {PRIOR, FIXED, ADAPTIVE},
        )
        estimates = result["estimands"]["family_estimates"]
        self.assertEqual(len(estimates), 3)
        pendulum = next(
            item
            for item in estimates
            if item["case_family"] == "pendulum"
            and item["variant_id"] == "base_v1"
        )
        self.assertEqual(pendulum["Y_H0"], 0.90)
        self.assertEqual(pendulum["Y_C0"], 0.40)
        self.assertEqual(pendulum["Y_HF"], 0.80)
        self.assertEqual(pendulum["Y_CF"], 0.70)
        self.assertEqual(pendulum["Y_HA"], 0.95)
        self.assertEqual(pendulum["Y_CA"], 0.90)
        self.assertAlmostEqual(pendulum["delta_0"], 0.50)
        self.assertAlmostEqual(pendulum["delta_F"], 0.40)
        self.assertAlmostEqual(pendulum["delta_A"], 0.05)
        self.assertNotIn("P_HI", pendulum)
        self.assertNotIn("active_pass_rate", pendulum)

        means = {
            (item["variant_id"], item["task_setting"]): item
            for item in result["estimands"]["equal_family_means"]
        }
        base_discovery = means[("base_v1", "discovery")]
        self.assertEqual(base_discovery["family_n"], 2)
        self.assertAlmostEqual(base_discovery["delta_0"], 0.35)
        self.assertAlmostEqual(base_discovery["delta_F"], 0.25)
        self.assertAlmostEqual(base_discovery["delta_A"], 0.025)
        self.assertEqual(
            means[("hard_v1", "identification")]["family_n"],
            1,
        )

    def test_temporal_rows_are_excluded_from_hc_estimands_and_probes(self):
        values = {
            (method, role): 0.5
            for method in (PRIOR, FIXED, ADAPTIVE)
            for role in ("historical", "counterfactual")
        }
        rows = estimand_rows("pendulum", values)
        for source_condition_id, condition_id in (
            ("published_regime_a", "condition_a"),
            ("published_regime_b", "condition_b"),
        ):
            rows.append(
                expression_row(
                    "pendulum",
                    "source_reported",
                    1.0,
                    dataset_kind=TEMPORAL,
                    variant_id="source_reported_v1",
                    condition_id=condition_id,
                    source_condition_id=source_condition_id,
                    source_paper_id="paper_one",
                    source_version_id="paper_one_v1",
                )
            )

        result = analyze(rows)
        self.assertEqual(len(result["estimands"]["family_estimates"]), 1)
        self.assertTrue(
            all(
                item["dataset_kind"] == HISTORICAL_COUNTERFACTUAL
                for item in result["estimands"]["family_estimates"]
            )
        )
        self.assertEqual(result["relationships"]["overall"]["n"], 6)
        self.assertTrue(
            all(
                item["dataset_kind"] == HISTORICAL_COUNTERFACTUAL
                for item in result["relationships"]["episodes"]
            )
        )
        self.assertEqual(
            {item["dataset_kind"] for item in result["families"]},
            {HISTORICAL_COUNTERFACTUAL, TEMPORAL},
        )
        self.assertEqual(
            result["temporal_estimands"]["condition_estimates"],
            [],
        )

    def test_temporal_estimands_aggregate_within_source_paper_first(self):
        rows = []
        rows += temporal_estimand_rows(
            "temporal_family_a",
            "paper_one",
            "paper_one_v2",
            "condition_a",
            "published_regime_a",
            {PRIOR: 0.20, FIXED: 0.40, ADAPTIVE: 0.50},
        )
        rows += temporal_estimand_rows(
            "temporal_family_a",
            "paper_one",
            "paper_one_v2",
            "condition_b",
            "published_regime_b",
            {PRIOR: 0.10, FIXED: 0.50, ADAPTIVE: 0.70},
        )
        rows += temporal_estimand_rows(
            "temporal_family_b",
            "paper_one",
            "paper_one_v2",
            "condition_a",
            "published_regime_c",
            {PRIOR: 0.10, FIXED: 0.70, ADAPTIVE: 1.00},
        )
        rows += temporal_estimand_rows(
            "temporal_family_c",
            "paper_two",
            "paper_two_v1",
            "condition_a",
            "published_regime_d",
            {PRIOR: 0.30, FIXED: 0.40, ADAPTIVE: 0.45},
        )

        result = analyze(rows)
        temporal = result["temporal_estimands"]
        self.assertEqual(result["estimands"]["family_estimates"], [])
        self.assertEqual(len(temporal["condition_estimates"]), 4)
        self.assertEqual(len(temporal["family_estimates"]), 3)
        self.assertEqual(len(temporal["source_paper_estimates"]), 2)
        self.assertEqual(len(temporal["equal_source_paper_means"]), 1)

        condition = next(
            item
            for item in temporal["condition_estimates"]
            if item["case_family"] == "temporal_family_a"
            and item["condition_id"] == "condition_a"
        )
        self.assertEqual(condition["source_paper_id"], "paper_one")
        self.assertEqual(condition["source_version_id"], "paper_one_v2")
        self.assertEqual(condition["source_condition_id"], "published_regime_a")
        self.assertAlmostEqual(condition["fixed_gain"], 0.20)
        self.assertAlmostEqual(condition["adaptive_gain"], 0.10)

        family = next(
            item
            for item in temporal["family_estimates"]
            if item["case_family"] == "temporal_family_a"
        )
        self.assertEqual(family["condition_n"], 2)
        self.assertAlmostEqual(family["fixed_gain"], 0.30)
        self.assertAlmostEqual(family["adaptive_gain"], 0.15)

        paper = next(
            item
            for item in temporal["source_paper_estimates"]
            if item["source_paper_id"] == "paper_one"
        )
        self.assertEqual(paper["family_n"], 2)
        self.assertAlmostEqual(paper["fixed_gain"], 0.45)
        self.assertAlmostEqual(paper["adaptive_gain"], 0.225)

        overall = temporal["equal_source_paper_means"][0]
        self.assertEqual(overall["source_paper_n"], 2)
        self.assertAlmostEqual(overall["fixed_gain"], 0.275)
        self.assertAlmostEqual(overall["adaptive_gain"], 0.1375)

    def test_exports_use_only_v2_design_fields(self):
        row = expression_row("pendulum", "historical", 1.0)
        result = analyze([row])
        exported = (
            result["cells"]
            + result["families"]
            + result["relationships"]["cells"]
            + result["relationships"]["episodes"]
        )
        for item in exported:
            self.assertNotIn("world", item)
            self.assertNotIn("track", item)

        with tempfile.TemporaryDirectory() as directory:
            cell_path = Path(directory) / "cells.csv"
            relationship_path = Path(directory) / "relationships.csv"
            _write_cell_csv(cell_path, result["cells"])
            _write_relationship_csv(
                relationship_path,
                result["relationships"]["episodes"],
            )
            with cell_path.open(encoding="utf-8", newline="") as stream:
                cell_fields = tuple(csv.DictReader(stream).fieldnames or ())
            with relationship_path.open(encoding="utf-8", newline="") as stream:
                relationship_fields = tuple(csv.DictReader(stream).fieldnames or ())
        self.assertTrue(set(CELL_FIELDS).issubset(cell_fields))
        self.assertTrue(set(CELL_FIELDS).issubset(relationship_fields))
        self.assertIn("held_out_prediction_score_mean", cell_fields)
        self.assertIn("held_out_prediction_score_n", cell_fields)
        self.assertNotIn("world", cell_fields)
        self.assertNotIn("track", cell_fields)
        self.assertNotIn("world", relationship_fields)
        self.assertNotIn("track", relationship_fields)


if __name__ == "__main__":
    unittest.main()
