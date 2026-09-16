"""Separate episode outcomes, scientific measurements and observed failure modes.

This module only combines recorded results. It neither calls a model nor changes
the case evaluator's binary outcome. An unmeasured quantity is not a zero score.
"""

from collections import Counter
from copy import deepcopy
import math
from typing import Any, Mapping

from .metrics import HELD_OUT_PREDICTION_SCORE


SCIENTIFIC_POSTEVAL_VERSION = "scigame.scientific_postevaluation"
FAILURE_CODES = ("F1", "F2", "F3", "F4", "F5")


def _mapping(value):
    return value if isinstance(value, Mapping) else {}


def _finite(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if math.isfinite(value) else None


def _normalized_error(row):
    scores = _mapping(row.get("scores"))
    for key in ("mean_normalized_error", "hidden_test_mean_scaled_error"):
        value = _finite(scores.get(key))
        if value is not None and value >= 0:
            return value
    score = _finite(scores.get(HELD_OUT_PREDICTION_SCORE))
    # Zero is also the established score for a missing/invalid predictor.
    if score is not None and 0 < score <= 1:
        error = 1.0 / score - 1.0
        return error if math.isfinite(error) else None
    return None


def _understanding(details):
    value = details.get("understanding")
    if not isinstance(value, Mapping):
        return None
    required = {"items", "before_score", "after_score", "delta", "status", "window", "transitions"}
    if not required <= set(value) or value.get("status") not in {"paired", "final_only", "unmeasured"}:
        return None
    return deepcopy(dict(value))


def science_postevaluation(row: Mapping[str, Any]) -> dict:
    """Combine one completed episode's independent scientific measurements.

    F2--F5 require explicit findings from a successfully completed scientific
    judge. A low score, numerical mismatch or missing explanation never creates
    those labels by itself. F1 is limited to a completed model episode without
    an evaluable scientific submission; external interruptions are excluded.
    """
    outcome = row.get("active_pass")
    completed = row.get("status") == "evaluated" and type(outcome) is bool
    formula = _mapping(row.get("formula_consistency"))
    formula_status = formula.get("status", "pending")
    expression_match = {"equivalent": 1, "not_equivalent": 0}.get(formula_status)
    judge_status = row.get("llm_evaluation_status", "pending")
    details = _mapping(_mapping(row.get("llm_evaluation")).get("details"))
    understanding = _understanding(details) if judge_status == "evaluated" else None
    judge_available = understanding is not None
    conflicts = []
    blocking = []
    labels = []
    final_present = isinstance(row.get("final_submission"), Mapping) and bool(row["final_submission"])
    evaluable_submission = final_present and row.get("scientifically_evaluable") is not False

    if completed and outcome is False:
        if not evaluable_submission:
            blocking.append("no_evaluable_submission")
        if evaluable_submission and row.get("evaluation_success") is False:
            blocking.append("prediction_tolerance_not_met")
        if row.get("protocol_completion") is False:
            blocking.append("protocol_not_completed")

        external_category = row.get("active_pass_category") in {
            "resource_limit_failure", "generation_incomplete", "provider_refusal", "infrastructure_failed"
        }
        external_code = row.get("reason_code") in {
            "payload_too_large", "too_deep", "too_many_values", "incomplete_output",
            "provider_refusal", "model_transport_error", "private_transport_error",
        }
        model_terminal = row.get("termination_kind") in {
            "submitted", "player_output_invalid", "action_rejected", "action_limit"
        }
        if not evaluable_submission and model_terminal and not external_category and not external_code:
            labels.append({"code": "F1", "rationale": "The completed model episode contains no evaluable final scientific submission.",
                           "event_sequences": []})

        if judge_available:
            seen = set()
            for finding in details.get("findings", []):
                finding = _mapping(finding)
                code = finding.get("code")
                if code not in FAILURE_CODES[1:] or code in seen:
                    continue
                rationale = finding.get("rationale")
                refs = finding.get("event_sequences")
                if (not isinstance(rationale, str) or not rationale.strip()
                        or not isinstance(refs, list) or not refs
                        or any(type(ref) is not int for ref in refs)):
                    continue
                if code == "F2" and formula_status == "equivalent":
                    conflicts.append("F2_conflicts_with_proven_expression_equivalence")
                    continue
                if code == "F3" and (not evaluable_submission or row.get("evaluation_success") is not False):
                    conflicts.append("F3_requires_evaluable_numerical_failure")
                    continue
                seen.add(code)
                labels.append({"code": code, "rationale": rationale, "event_sequences": list(refs)})

    failed = completed and outcome is False
    failure_status = ("not_applicable" if not completed else "passed" if outcome
                      else "classified" if labels else "unclassified")
    return {
        "version": SCIENTIFIC_POSTEVAL_VERSION,
        "status": "evaluated" if completed else "not_applicable",
        "active_pass": outcome,
        "normalized_error": _normalized_error(row) if completed else None,
        "expression_match": expression_match if completed else None,
        "understanding": understanding if completed else None,
        "failure_analysis": {"status": failure_status, "blocking_conditions": blocking,
                             "labels": labels, "unclassified": bool(failed and not labels)},
        "coverage": {
            "judge_status": judge_status,
            "scientific_judge_available": bool(completed and judge_available),
            "expression_status": formula_status,
            "understanding_status": understanding["status"] if completed and understanding else "unmeasured",
            "conflicts": conflicts,
        },
    }


def _metric(values, eligible_n):
    numbers = [number for value in values if (number := _finite(value)) is not None]
    return {"mean": sum(numbers) / len(numbers) if numbers else None,
            "scored_n": len(numbers), "eligible_n": eligible_n,
            "coverage": len(numbers) / eligible_n if eligible_n else None}


def _understanding_change(value):
    if not value or value.get("status") != "paired":
        return "unmeasured"
    kinds = {item.get("kind") for item in value.get("transitions", [])}
    if "gained" in kinds and "degraded" in kinds:
        return "mixed_gain_and_loss"
    if "gained" in kinds:
        return "improved"
    if "degraded" in kinds:
        return "degraded"
    if "retained_correct" in kinds:
        return "retained_correct"
    return "unchanged_without_correct_retention"


def aggregate_scientific_postevaluation(rows) -> dict:
    """Summarize all completed outcomes, keeping missing metrics in coverage.

    Failure-mode rates always use all failed episodes. Modes are non-exclusive,
    so their rates may sum to more than one. Understanding endpoint means use
    their own available samples; paired means are also reported on one cohort.
    """
    rows = list(rows)
    records = []
    for row in rows:
        existing = _mapping(row.get("science_postevaluation"))
        records.append(existing if existing.get("version") == SCIENTIFIC_POSTEVAL_VERSION
                       else science_postevaluation(row))
    completed = [record for record in records if record.get("status") == "evaluated"
                 and type(record.get("active_pass")) is bool]
    failed = [record for record in completed if record["active_pass"] is False]
    successful_n = sum(record["active_pass"] is True for record in completed)
    total = len(completed)
    fail_n = len(failed)
    counts = Counter(code for record in failed
                     for code in {item["code"] for item in record["failure_analysis"]["labels"]})
    values = [_mapping(record.get("understanding")) for record in completed]
    paired = [value for value in values if value.get("status") == "paired"
              and all(_finite(value.get(key)) is not None for key in ("before_score", "after_score", "delta"))]
    cross = {"success": Counter(), "failure": Counter()}
    for record in completed:
        cross["success" if record["active_pass"] else "failure"][_understanding_change(record.get("understanding"))] += 1
    formula_statuses = Counter(record["coverage"]["expression_status"] for record in completed)
    expression = _metric((record.get("expression_match") for record in completed), total)
    return {
        "version": SCIENTIFIC_POSTEVAL_VERSION,
        "total_n": len(rows), "evaluated_n": total,
        "infrastructure_n": sum(row.get("status") in {"infrastructure_failed", "infrastructure_error"} for row in rows),
        "not_evaluated_n": len(rows) - total,
        "success_n": successful_n, "failed_n": fail_n,
        "success_rate": successful_n / total if total else None,
        "success_rate_denominator": total,
        "normalized_error": _metric((record.get("normalized_error") for record in completed), total),
        "expression_match": {**expression, "status_counts": dict(sorted(formula_statuses.items())),
                             "equivalent_rate_among_decided": expression["mean"],
                             "decision_coverage": expression["coverage"]},
        "understanding": {
            "before": _metric((value.get("before_score") for value in values), total),
            "after": _metric((value.get("after_score") for value in values), total),
            "delta": _metric((value.get("delta") for value in paired), total),
            "paired": {"n": len(paired),
                       "before_mean": _metric((value["before_score"] for value in paired), len(paired))["mean"],
                       "after_mean": _metric((value["after_score"] for value in paired), len(paired))["mean"],
                       "delta_mean": _metric((value["delta"] for value in paired), len(paired))["mean"]},
        },
        "failure_modes": {code: {"n": counts[code], "failed_n": fail_n,
                                  "rate": counts[code] / fail_n if fail_n else None}
                          for code in FAILURE_CODES},
        "unclassified_failed_n": sum(record["failure_analysis"]["unclassified"] for record in failed),
        "judge_available_failed_n": sum(record["coverage"]["scientific_judge_available"] for record in failed),
        "judge_status_counts": dict(Counter(record["coverage"]["judge_status"] for record in completed)),
        "failure_labels_are_nonexclusive": True,
        "success_understanding_counts": {key: dict(sorted(value.items())) for key, value in cross.items()},
    }


__all__ = ["SCIENTIFIC_POSTEVAL_VERSION", "FAILURE_CODES", "science_postevaluation",
           "aggregate_scientific_postevaluation"]
