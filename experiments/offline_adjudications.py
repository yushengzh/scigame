"""Explicit user decisions for offline binary reporting; never alter machine evidence."""

from copy import deepcopy
import json
from pathlib import Path

from role_benchmark.postevaluation import aggregate_scientific_postevaluation

ADJUDICATION_SCHEMA = "scigame.user_adjudications.v1"
ADJUDICATED_EPISODE = "temporal_enriched_105006__canonical__counterfactual__identification__adaptive-experimental-design__r01"


def is_adjudicated(row):
    record = row.get("user_adjudication")
    return (isinstance(record, dict) and record.get("episode_id") == ADJUDICATED_EPISODE
            and record.get("authority") == "user" and record.get("decision") == "failure")


def apply_adjudications(root: Path, rows):
    """Annotate a derived copy, retaining raw status/outcome/scores/Judge fields."""
    path = Path(root) / "adjudications.json"
    if not path.exists():
        return rows
    registry = json.loads(path.read_text(encoding="utf-8"))
    if registry.get("schema") != ADJUDICATION_SCHEMA or not isinstance(registry.get("adjudications"), list):
        raise ValueError("Invalid user adjudication registry")
    records = registry["adjudications"]
    if len(records) != 1:
        raise ValueError("Exactly the one user-authorized episode may be adjudicated")
    record = records[0]
    if (record.get("episode_id") != ADJUDICATED_EPISODE or record.get("authority") != "user"
            or record.get("decision") != "failure" or not record.get("reason")
            or not record.get("recorded_at") or record.get("no_further_model_calls") is not True):
        raise ValueError("Adjudication differs from the explicit user instruction")
    copied = deepcopy(rows)
    selected = [row for row in copied if row.get("episode_id") == ADJUDICATED_EPISODE]
    if len(selected) != 1 or selected[0].get("status") != "infrastructure_failed" or selected[0].get("active_pass") is not None:
        raise ValueError("Adjudication requires the original unresolved infrastructure result")
    selected[0]["user_adjudication"] = deepcopy(record)
    selected[0]["effective_active_pass"] = False
    selected[0]["outcome_source"] = "user_adjudicated_failure"
    return copied


def scientific_summary(rows):
    """Include a manual binary failure in denominators, with no invented measurements."""
    rows = list(rows)
    result = aggregate_scientific_postevaluation(rows)
    adjudicated_n = sum(is_adjudicated(row) for row in rows)
    if not adjudicated_n:
        return result
    result["machine_evaluated_n"] = result["evaluated_n"]
    result["user_adjudicated_failure_n"] = adjudicated_n
    result["binary_outcome_n"] = result["success_rate_denominator"] + adjudicated_n
    result["success_rate_denominator"] += adjudicated_n
    result["success_rate"] = result["success_n"] / result["success_rate_denominator"]
    result["failed_n"] += adjudicated_n
    result["unclassified_failed_n"] += adjudicated_n
    result["raw_infrastructure_n"] = result["infrastructure_n"]
    result["infrastructure_n"] -= adjudicated_n
    result["judge_status_counts"]["user_adjudicated_not_judged"] = adjudicated_n
    result["expression_match"]["status_counts"]["user_adjudicated_unmeasured"] = adjudicated_n
    metrics = [result["normalized_error"], result["expression_match"],
               *[result["understanding"][key] for key in ("before", "after", "delta")]]
    for metric in metrics:
        metric["eligible_n"] += adjudicated_n
        metric["coverage"] = metric["scored_n"] / metric["eligible_n"]
    result["expression_match"]["decision_coverage"] = result["expression_match"]["coverage"]
    for label in result["failure_modes"].values():
        label["failed_n"] += adjudicated_n
        label["rate"] = label["n"] / label["failed_n"]
    counts = result["success_understanding_counts"]["failure"]
    counts["unmeasured"] = counts.get("unmeasured", 0) + adjudicated_n
    result["adjudication_semantics"] = (
        "Explicit user failure counted only in binary outcomes and missingness denominators. "
        "Raw infrastructure result is preserved. No scientific score, expression verdict, Judge rating, or F-label was created.")
    return result
