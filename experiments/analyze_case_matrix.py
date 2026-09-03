"""Aggregate the cross-case run and probe qualitative discovery relations.

For families with declared exploratory relationship probes, this analysis
reports outcomes in the order that the current protocol can support:

1. Did the submitted executable expression recover dependency and direction?
2. Did it recover a coarse response shape (invariant, sublinear, linear, or
   superlinear on a log-response scale)?
3. Did the expression also pass the case's held-out numerical predictor test?

These post-hoc relationship probes are exploratory.  They motivate a future
structured functional-relationship submission contract; they are not a
replacement for a pre-registered evaluator.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from role_benchmark import (
    ADAPTIVE_EXPERIMENTAL_DESIGN,
    EVALUATOR_SCORE_AXES,
    FIXED_EXPERIMENTAL_DESIGN,
    HELD_OUT_PREDICTION_SCORE,
    PRIOR_ONLY_BASELINE,
)
from role_benchmark.expression import ExpressionError, evaluate_expression_program


ANALYSIS_SCHEMA = "role_benchmark.case_matrix_analysis.v2"
HISTORICAL_COUNTERFACTUAL_DATASET = "historical_counterfactual"
TEMPORAL_DATASET = "temporal"
HISTORICAL_ROLE = "historical"
COUNTERFACTUAL_ROLE = "counterfactual"
IDENTIFICATION_TASK_SETTING = "identification"
DISCOVERY_TASK_SETTING = "discovery"
CELL_FIELDS = (
    "dataset_kind",
    "case_family",
    "variant_id",
    "condition_id",
    "condition_role",
    "source_condition_id",
    "source_paper_id",
    "source_version_id",
    "task_setting",
    "evaluation_method",
)


def _rate(values: Iterable[bool]) -> Optional[float]:
    items = list(values)
    return sum(items) / len(items) if items else None


def _mean(values: Iterable[Optional[float]]) -> Optional[float]:
    items = [float(value) for value in values if value is not None]
    return sum(items) / len(items) if items else None


def _group_summary(rows: Sequence[Mapping[str, Any]]) -> Mapping[str, Any]:
    evaluated = [row for row in rows if row.get("status") == "evaluated"]
    player = [row.get("player_llm_stats") or {} for row in evaluated]
    oracle = [row.get("oracle_llm_stats") or {} for row in evaluated]
    evaluator = [row.get("evaluator_llm_stats") or {} for row in evaluated]
    llm_evaluations = [
        row.get("llm_evaluation") or {}
        for row in evaluated
        if row.get("llm_evaluation_status") == "evaluated"
    ]
    prediction_scores = [
        (row.get("scores") or {}).get(HELD_OUT_PREDICTION_SCORE)
        for row in evaluated
    ]
    return {
        "n": len(rows),
        "evaluated_n": len(evaluated),
        "active_pass_n": sum(row.get("active_pass") is True for row in evaluated),
        "active_pass_rate": _rate(row.get("active_pass") is True for row in evaluated),
        "scientifically_evaluable_n": sum(
            row.get("scientifically_evaluable") is True for row in evaluated
        ),
        "scientifically_evaluable_rate": _rate(
            row.get("scientifically_evaluable") is True for row in evaluated
        ),
        "protocol_completion_rate": _rate(
            row.get("protocol_completion") is True for row in evaluated
        ),
        "held_out_prediction_score_mean": _mean(prediction_scores),
        "held_out_prediction_score_n": sum(
            value is not None for value in prediction_scores
        ),
        "terminal_categories": dict(
            sorted(Counter(row.get("active_pass_category") for row in evaluated).items())
        ),
        "termination_kinds": dict(
            sorted(Counter(row.get("termination_kind") for row in evaluated).items())
        ),
        "mean_attempts": _mean(row.get("attempts_used") for row in evaluated),
        "player_calls": sum(
            int(stats.get("primary_calls") or 0) + int(stats.get("repair_calls") or 0)
            for stats in player
        ),
        "oracle_calls": sum(int(stats.get("generation_calls") or 0) for stats in oracle),
        "evaluator_calls": sum(
            int(stats.get("generation_calls") or 0) for stats in evaluator
        ),
        "player_input_tokens": sum(int(stats.get("input_tokens") or 0) for stats in player),
        "player_output_tokens": sum(int(stats.get("output_tokens") or 0) for stats in player),
        "oracle_input_tokens": sum(int(stats.get("input_tokens") or 0) for stats in oracle),
        "oracle_output_tokens": sum(int(stats.get("output_tokens") or 0) for stats in oracle),
        "evaluator_input_tokens": sum(
            int(stats.get("input_tokens") or 0) for stats in evaluator
        ),
        "evaluator_output_tokens": sum(
            int(stats.get("output_tokens") or 0) for stats in evaluator
        ),
        "llm_evaluation_n": len(llm_evaluations),
        "llm_evaluation_coverage": (
            len(llm_evaluations) / len(evaluated) if evaluated else None
        ),
        "llm_evaluator_axis_means": {
            axis: _mean(
                (evaluation.get("scores") or {}).get(axis)
                for evaluation in llm_evaluations
            )
            for axis in EVALUATOR_SCORE_AXES
        },
        "elapsed_s": sum(float(row.get("elapsed_s") or 0.0) for row in evaluated),
    }


def _cell_key(row: Mapping[str, Any]) -> Tuple[Any, ...]:
    return tuple(row.get(field) for field in CELL_FIELDS)


def _cell_summaries(rows: Sequence[Mapping[str, Any]]) -> List[Mapping[str, Any]]:
    groups: Dict[Tuple[Any, ...], List[Mapping[str, Any]]] = defaultdict(list)
    for row in rows:
        groups[_cell_key(row)].append(row)
    output = []
    for key, group in sorted(groups.items(), key=lambda item: repr(item[0])):
        output.append(
            {
                **dict(zip(CELL_FIELDS, key)),
                **_group_summary(group),
            }
        )
    return output


def _estimands(cell_summaries: Sequence[Mapping[str, Any]]) -> Mapping[str, Any]:
    scores: Dict[Tuple[str, str, str, str, str], List[float]] = defaultdict(list)
    strata = set()
    for row in cell_summaries:
        if row["dataset_kind"] != HISTORICAL_COUNTERFACTUAL_DATASET:
            continue
        condition_role = str(row["condition_role"])
        task_setting = str(row["task_setting"])
        if condition_role not in (HISTORICAL_ROLE, COUNTERFACTUAL_ROLE):
            continue
        if task_setting not in (
            IDENTIFICATION_TASK_SETTING,
            DISCOVERY_TASK_SETTING,
        ):
            continue
        family = str(row["case_family"])
        variant_id = str(row["variant_id"])
        evaluation_method = str(row["evaluation_method"])
        if evaluation_method not in (
            PRIOR_ONLY_BASELINE,
            FIXED_EXPERIMENTAL_DESIGN,
            ADAPTIVE_EXPERIMENTAL_DESIGN,
        ):
            continue
        strata.add((family, variant_id, task_setting))
        score = row["held_out_prediction_score_mean"]
        if score is not None:
            scores[
                (
                    family,
                    variant_id,
                    task_setting,
                    evaluation_method,
                    condition_role,
                )
            ].append(float(score))

    family_estimates = []
    for family, variant_id, task_setting in sorted(strata):
        values = {
            (evaluation_method, role): _mean(
                scores.get(
                    (
                        family,
                        variant_id,
                        task_setting,
                        evaluation_method,
                        role,
                    ),
                    (),
                )
            )
            for evaluation_method in (
                PRIOR_ONLY_BASELINE,
                FIXED_EXPERIMENTAL_DESIGN,
                ADAPTIVE_EXPERIMENTAL_DESIGN,
            )
            for role in (HISTORICAL_ROLE, COUNTERFACTUAL_ROLE)
        }
        if any(value is None for value in values.values()):
            continue
        y_h0 = float(values[(PRIOR_ONLY_BASELINE, HISTORICAL_ROLE)])
        y_c0 = float(values[(PRIOR_ONLY_BASELINE, COUNTERFACTUAL_ROLE)])
        y_hf = float(values[(FIXED_EXPERIMENTAL_DESIGN, HISTORICAL_ROLE)])
        y_cf = float(values[(FIXED_EXPERIMENTAL_DESIGN, COUNTERFACTUAL_ROLE)])
        y_ha = float(values[(ADAPTIVE_EXPERIMENTAL_DESIGN, HISTORICAL_ROLE)])
        y_ca = float(values[(ADAPTIVE_EXPERIMENTAL_DESIGN, COUNTERFACTUAL_ROLE)])
        family_estimates.append(
            {
                "dataset_kind": HISTORICAL_COUNTERFACTUAL_DATASET,
                "case_family": family,
                "variant_id": variant_id,
                "task_setting": task_setting,
                "Y_H0": y_h0,
                "Y_C0": y_c0,
                "Y_HF": y_hf,
                "Y_CF": y_cf,
                "Y_HA": y_ha,
                "Y_CA": y_ca,
                "delta_0": y_h0 - y_c0,
                "delta_F": (y_cf - y_c0) - (y_hf - y_h0),
                "delta_A": (y_ca - y_cf) - (y_ha - y_hf),
            }
        )

    mean_groups: Dict[
        Tuple[str, str], List[Mapping[str, Any]]
    ] = defaultdict(list)
    for item in family_estimates:
        mean_groups[(str(item["variant_id"]), str(item["task_setting"]))].append(
            item
        )
    equal_family_means = [
        {
            "dataset_kind": HISTORICAL_COUNTERFACTUAL_DATASET,
            "variant_id": variant_id,
            "task_setting": task_setting,
            "family_n": len(group),
            "delta_0": _mean(item["delta_0"] for item in group),
            "delta_F": _mean(item["delta_F"] for item in group),
            "delta_A": _mean(item["delta_A"] for item in group),
        }
        for (variant_id, task_setting), group in sorted(mean_groups.items())
    ]
    return {
        "outcome": HELD_OUT_PREDICTION_SCORE,
        "family_estimates": family_estimates,
        "equal_family_means": equal_family_means,
    }


def _common_value(rows: Sequence[Mapping[str, Any]], field: str) -> Any:
    values = {row.get(field) for row in rows}
    if len(values) != 1:
        raise ValueError("temporal estimand rows must share one %s" % field)
    return next(iter(values))


def _temporal_estimands(
    cell_summaries: Sequence[Mapping[str, Any]],
) -> Mapping[str, Any]:
    condition_groups: Dict[
        Tuple[str, str, str, str, str], List[Mapping[str, Any]]
    ] = defaultdict(list)
    for row in cell_summaries:
        if row["dataset_kind"] != TEMPORAL_DATASET:
            continue
        source_paper_id = row.get("source_paper_id")
        source_version_id = row.get("source_version_id")
        if not source_paper_id or not source_version_id:
            raise ValueError(
                "temporal rows require source_paper_id and source_version_id"
            )
        task_setting = str(row["task_setting"])
        if task_setting not in (
            IDENTIFICATION_TASK_SETTING,
            DISCOVERY_TASK_SETTING,
        ):
            continue
        evaluation_method = str(row["evaluation_method"])
        if evaluation_method not in (
            PRIOR_ONLY_BASELINE,
            FIXED_EXPERIMENTAL_DESIGN,
            ADAPTIVE_EXPERIMENTAL_DESIGN,
        ):
            continue
        condition_groups[
            (
                str(source_paper_id),
                str(row["case_family"]),
                str(row["variant_id"]),
                str(row["condition_id"]),
                task_setting,
            )
        ].append(row)

    condition_estimates = []
    for (
        source_paper_id,
        family,
        variant_id,
        condition_id,
        task_setting,
    ), group in sorted(condition_groups.items()):
        values = {
            method: _mean(
                row["held_out_prediction_score_mean"]
                for row in group
                if row["evaluation_method"] == method
            )
            for method in (
                PRIOR_ONLY_BASELINE,
                FIXED_EXPERIMENTAL_DESIGN,
                ADAPTIVE_EXPERIMENTAL_DESIGN,
            )
        }
        if any(value is None for value in values.values()):
            continue
        y_0 = float(values[PRIOR_ONLY_BASELINE])
        y_f = float(values[FIXED_EXPERIMENTAL_DESIGN])
        y_a = float(values[ADAPTIVE_EXPERIMENTAL_DESIGN])
        condition_estimates.append(
            {
                "dataset_kind": TEMPORAL_DATASET,
                "source_paper_id": source_paper_id,
                "source_version_id": _common_value(group, "source_version_id"),
                "case_family": family,
                "variant_id": variant_id,
                "condition_id": condition_id,
                "condition_role": _common_value(group, "condition_role"),
                "source_condition_id": _common_value(
                    group, "source_condition_id"
                ),
                "task_setting": task_setting,
                "Y_0": y_0,
                "Y_F": y_f,
                "Y_A": y_a,
                "fixed_gain": y_f - y_0,
                "adaptive_gain": y_a - y_f,
            }
        )

    family_groups: Dict[
        Tuple[str, str, str, str], List[Mapping[str, Any]]
    ] = defaultdict(list)
    for item in condition_estimates:
        family_groups[
            (
                str(item["source_paper_id"]),
                str(item["case_family"]),
                str(item["variant_id"]),
                str(item["task_setting"]),
            )
        ].append(item)
    family_estimates = [
        {
            "dataset_kind": TEMPORAL_DATASET,
            "source_paper_id": source_paper_id,
            "source_version_id": _common_value(group, "source_version_id"),
            "case_family": family,
            "variant_id": variant_id,
            "task_setting": task_setting,
            "condition_n": len(group),
            "Y_0": _mean(item["Y_0"] for item in group),
            "Y_F": _mean(item["Y_F"] for item in group),
            "Y_A": _mean(item["Y_A"] for item in group),
            "fixed_gain": _mean(item["fixed_gain"] for item in group),
            "adaptive_gain": _mean(item["adaptive_gain"] for item in group),
        }
        for (
            source_paper_id,
            family,
            variant_id,
            task_setting,
        ), group in sorted(family_groups.items())
    ]

    paper_groups: Dict[
        Tuple[str, str, str], List[Mapping[str, Any]]
    ] = defaultdict(list)
    for item in family_estimates:
        paper_groups[
            (
                str(item["source_paper_id"]),
                str(item["variant_id"]),
                str(item["task_setting"]),
            )
        ].append(item)
    source_paper_estimates = [
        {
            "dataset_kind": TEMPORAL_DATASET,
            "source_paper_id": source_paper_id,
            "source_version_id": _common_value(group, "source_version_id"),
            "variant_id": variant_id,
            "task_setting": task_setting,
            "family_n": len(group),
            "fixed_gain": _mean(item["fixed_gain"] for item in group),
            "adaptive_gain": _mean(item["adaptive_gain"] for item in group),
        }
        for (
            source_paper_id,
            variant_id,
            task_setting,
        ), group in sorted(paper_groups.items())
    ]

    mean_groups: Dict[
        Tuple[str, str], List[Mapping[str, Any]]
    ] = defaultdict(list)
    for item in source_paper_estimates:
        mean_groups[(str(item["variant_id"]), str(item["task_setting"]))].append(
            item
        )
    equal_source_paper_means = [
        {
            "dataset_kind": TEMPORAL_DATASET,
            "variant_id": variant_id,
            "task_setting": task_setting,
            "source_paper_n": len(group),
            "fixed_gain": _mean(item["fixed_gain"] for item in group),
            "adaptive_gain": _mean(item["adaptive_gain"] for item in group),
        }
        for (variant_id, task_setting), group in sorted(mean_groups.items())
    ]
    return {
        "outcome": HELD_OUT_PREDICTION_SCORE,
        "condition_estimates": condition_estimates,
        "family_estimates": family_estimates,
        "source_paper_estimates": source_paper_estimates,
        "equal_source_paper_means": equal_source_paper_means,
    }


# Each probe compares a low and high value of one control while holding the
# remaining controls fixed. The expected shape comes from the benchmark reference.
_PROBES: Mapping[str, Tuple[Mapping[str, Any], ...]] = {
    "pendulum": (
        {
            "relation": "length_to_period",
            "control": "length_m",
            "readout": "period_s",
            "low": {"length_m": 0.25, "bob_mass_kg": 0.20, "release_angle_deg": 5.0},
            "high": {"length_m": 1.0, "bob_mass_kg": 0.20, "release_angle_deg": 5.0},
            "historical": "increasing_sublinear",
            "counterfactual": "increasing_sublinear",
        },
        {
            "relation": "mass_to_period",
            "control": "bob_mass_kg",
            "readout": "period_s",
            "low": {"length_m": 1.0, "bob_mass_kg": 0.05, "release_angle_deg": 5.0},
            "high": {"length_m": 1.0, "bob_mass_kg": 0.80, "release_angle_deg": 5.0},
            "historical": "invariant",
            "counterfactual": "increasing_sublinear",
        },
        {
            "relation": "angle_to_period",
            "control": "release_angle_deg",
            "readout": "period_s",
            "low": {"length_m": 1.0, "bob_mass_kg": 0.20, "release_angle_deg": 1.0},
            "high": {"length_m": 1.0, "bob_mass_kg": 0.20, "release_angle_deg": 10.0},
            "historical": "invariant",
            "counterfactual": "invariant",
        },
    ),
    "young_double_slit": (
        {
            "relation": "wavelength_to_spacing",
            "control": "wavelength_nm",
            "readout": "fringe_spacing_mm",
            "low": {"wavelength_nm": 400.0, "screen_distance_m": 1.0, "slit_separation_mm": 0.50},
            "high": {"wavelength_nm": 700.0, "screen_distance_m": 1.0, "slit_separation_mm": 0.50},
            "historical": "increasing_linear",
            "counterfactual": "increasing_linear",
        },
        {
            "relation": "distance_to_spacing",
            "control": "screen_distance_m",
            "readout": "fringe_spacing_mm",
            "low": {"wavelength_nm": 550.0, "screen_distance_m": 0.50, "slit_separation_mm": 0.50},
            "high": {"wavelength_nm": 550.0, "screen_distance_m": 3.0, "slit_separation_mm": 0.50},
            "historical": "increasing_linear",
            "counterfactual": "increasing_linear",
        },
        {
            "relation": "separation_to_spacing",
            "control": "slit_separation_mm",
            "readout": "fringe_spacing_mm",
            "low": {"wavelength_nm": 550.0, "screen_distance_m": 1.0, "slit_separation_mm": 0.10},
            "high": {"wavelength_nm": 550.0, "screen_distance_m": 1.0, "slit_separation_mm": 1.00},
            "historical": "decreasing_linear",
            "counterfactual": "decreasing_sublinear",
        },
    ),
}


def _shape_from_elasticity(elasticity: float) -> str:
    if abs(elasticity) <= 0.05:
        return "invariant"
    direction = "increasing" if elasticity > 0.0 else "decreasing"
    magnitude = abs(elasticity)
    if magnitude < 0.80:
        shape = "sublinear"
    elif magnitude <= 1.20:
        shape = "linear"
    else:
        shape = "superlinear"
    return "%s_%s" % (direction, shape)


def _direction(shape: str) -> str:
    if shape == "invariant":
        return shape
    return shape.split("_", 1)[0]


def _probe_submission(
    row: Mapping[str, Any],
) -> Tuple[List[Mapping[str, Any]], Optional[str]]:
    family = str(row["case_family"])
    final = row.get("final_submission")
    if not isinstance(final, Mapping) or final.get("model") != "expression":
        return [], "no executable discovery expression"
    parameters = final.get("parameters")
    if not isinstance(parameters, Mapping):
        return [], "missing expression parameters"
    variables = tuple(_PROBES[family][0]["low"])
    output: List[Mapping[str, Any]] = []
    try:
        for probe in _PROBES[family]:
            readout = str(probe["readout"])
            low_controls = probe["low"]
            high_controls = probe["high"]
            low_y = evaluate_expression_program(
                parameters,
                low_controls,
                allowed_variables=variables,
                required_outputs=(readout,),
            )[readout]
            high_y = evaluate_expression_program(
                parameters,
                high_controls,
                allowed_variables=variables,
                required_outputs=(readout,),
            )[readout]
            low_x = float(low_controls[str(probe["control"])])
            high_x = float(high_controls[str(probe["control"])])
            if low_y <= 0.0 or high_y <= 0.0:
                raise ExpressionError("relationship probe requires positive predictions")
            elasticity = math.log(high_y / low_y) / math.log(high_x / low_x)
            predicted = _shape_from_elasticity(elasticity)
            expected = str(probe[str(row["condition_role"])])
            output.append(
                {
                    "relation": probe["relation"],
                    "expected_shape": expected,
                    "predicted_shape": predicted,
                    "elasticity": elasticity,
                    "direction_correct": _direction(predicted) == _direction(expected),
                    "shape_correct": predicted == expected,
                }
            )
    except (ExpressionError, ArithmeticError, KeyError, TypeError, ValueError) as exc:
        return [], str(exc)
    return output, None


def _relationship_rows(rows: Sequence[Mapping[str, Any]]) -> List[Mapping[str, Any]]:
    output: List[Mapping[str, Any]] = []
    for row in rows:
        if (
            row.get("dataset_kind") != HISTORICAL_COUNTERFACTUAL_DATASET
            or row.get("case_family") not in _PROBES
            or row.get("task_setting") != DISCOVERY_TASK_SETTING
            or row.get("condition_role")
            not in (HISTORICAL_ROLE, COUNTERFACTUAL_ROLE)
        ):
            continue
        probes, error = _probe_submission(row)
        scorable = bool(probes) and error is None
        direction_pass = scorable and all(item["direction_correct"] for item in probes)
        shape_pass = scorable and all(item["shape_correct"] for item in probes)
        output.append(
            {
                "episode_id": row["episode_id"],
                **{field: row.get(field) for field in CELL_FIELDS},
                "repeat": row["repeat"],
                "held_out_predictive_pass": row.get("active_pass") is True,
                "scorable": scorable,
                "direction_pass": direction_pass,
                "shape_pass": shape_pass,
                "probe_error": error,
                "probes": probes,
            }
        )
    return output


def _relationship_summary(rows: Sequence[Mapping[str, Any]]) -> Mapping[str, Any]:
    episode_rows = _relationship_rows(rows)
    groups: Dict[Tuple[Any, ...], List[Mapping[str, Any]]] = defaultdict(list)
    for row in episode_rows:
        groups[_cell_key(row)].append(row)

    def summarize(group: Sequence[Mapping[str, Any]]) -> Mapping[str, Any]:
        return {
            "n": len(group),
            "scorable_n": sum(row["scorable"] for row in group),
            "direction_full_denominator_rate": _rate(
                row["direction_pass"] for row in group
            ),
            "shape_full_denominator_rate": _rate(row["shape_pass"] for row in group),
            "direction_given_scorable_rate": _rate(
                row["direction_pass"] for row in group if row["scorable"]
            ),
            "shape_given_scorable_rate": _rate(
                row["shape_pass"] for row in group if row["scorable"]
            ),
            "held_out_predictive_pass_rate": _rate(
                row["held_out_predictive_pass"] for row in group
            ),
        }

    cells = []
    for key, group in sorted(groups.items(), key=lambda item: repr(item[0])):
        cells.append(
            {
                **dict(zip(CELL_FIELDS, key)),
                **summarize(group),
            }
        )
    return {
        "status": "exploratory_post_hoc",
        "note": (
            "Relationship recovery is reported before held-out numerical prediction. "
            "Relations are probed from submitted expressions, so this run remains "
            "exploratory; future evaluations should collect a structured functional-"
            "relationship submission directly. Only historical/counterfactual "
            "Discovery conditions are included; Identification is excluded because "
            "its public skeleton already discloses these relations, and Temporal "
            "source-reported conditions are not H/C estimands."
        ),
        "overall": summarize(episode_rows),
        "cells": cells,
        "episodes": episode_rows,
    }


def analyze(rows: Sequence[Mapping[str, Any]]) -> Mapping[str, Any]:
    experiment_ids = {
        str(row["experiment_id"])
        for row in rows
        if row.get("experiment_id") is not None
    }
    if len(experiment_ids) > 1:
        raise ValueError("analysis rows must share one experiment_id")
    cells = _cell_summaries(rows)
    family_groups: Dict[
        Tuple[str, str, str, Optional[str], Optional[str], str],
        List[Mapping[str, Any]],
    ] = defaultdict(list)
    for row in rows:
        family_groups[
            (
                str(row["dataset_kind"]),
                str(row["case_family"]),
                str(row["variant_id"]),
                row.get("source_paper_id"),
                row.get("source_version_id"),
                str(row["evaluation_method"]),
            )
        ].append(row)
    families = [
        {
            "dataset_kind": dataset_kind,
            "case_family": family,
            "variant_id": variant_id,
            "source_paper_id": source_paper_id,
            "source_version_id": source_version_id,
            "evaluation_method": evaluation_method,
            **_group_summary(group),
        }
        for (
            dataset_kind,
            family,
            variant_id,
            source_paper_id,
            source_version_id,
            evaluation_method,
        ), group in sorted(family_groups.items(), key=lambda item: repr(item[0]))
    ]
    return {
        "schema": ANALYSIS_SCHEMA,
        "experiment_id": next(iter(experiment_ids), None),
        "overall": _group_summary(rows),
        "families": families,
        "cells": cells,
        "estimands": _estimands(cells),
        "temporal_estimands": _temporal_estimands(cells),
        "relationships": _relationship_summary(rows),
    }


def _write_json(path: Path, payload: Any) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        json.dump(payload, stream, ensure_ascii=False, indent=2, sort_keys=True)
        stream.write("\n")


def _write_cell_csv(path: Path, cells: Sequence[Mapping[str, Any]]) -> None:
    fields = CELL_FIELDS + (
        "n",
        "active_pass_n",
        "active_pass_rate",
        "scientifically_evaluable_n",
        "scientifically_evaluable_rate",
        "protocol_completion_rate",
        "held_out_prediction_score_mean",
        "held_out_prediction_score_n",
        "mean_attempts",
        "terminal_categories",
    )
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for cell in cells:
            row = {field: cell.get(field) for field in fields}
            row["terminal_categories"] = json.dumps(
                cell["terminal_categories"], ensure_ascii=False, sort_keys=True
            )
            writer.writerow(row)


def _write_relationship_csv(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    fields = (
        "episode_id",
        *CELL_FIELDS,
        "repeat",
        "held_out_predictive_pass",
        "scorable",
        "direction_pass",
        "shape_pass",
        "probe_error",
        "probes_json",
    )
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for item in rows:
            writer.writerow(
                {
                    **{field: item.get(field) for field in fields if field != "probes_json"},
                    "probes_json": json.dumps(
                        item["probes"], ensure_ascii=False, sort_keys=True
                    ),
                }
            )


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("run_dir")
    parser.add_argument("--output-dir")
    args = parser.parse_args(argv)
    run_dir = Path(args.run_dir).resolve()
    source = json.loads((run_dir / "episodes.json").read_text(encoding="utf-8"))
    rows = source.get("episodes")
    if not isinstance(rows, list):
        raise SystemExit("episodes.json does not contain an episodes array")
    result = analyze(rows)
    output_dir = (
        Path(args.output_dir).resolve()
        if args.output_dir
        else run_dir / "analysis"
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    _write_json(output_dir / "summary.json", result)
    _write_cell_csv(output_dir / "cells.csv", result["cells"])
    _write_relationship_csv(
        output_dir / "relationships.csv", result["relationships"]["episodes"]
    )
    print(output_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
