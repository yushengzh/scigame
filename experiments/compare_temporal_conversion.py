"""Compare a completed Temporal conversion run with its historical record.

The comparison is controlled only when the pre-execution registration and the
recorded run configuration identify the same non-placeholder immutable model
snapshot as the historical run.  A mutable model alias is not a snapshot.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Sequence


EXPERIMENT_ID = "EXP-TEMPORAL-AUTHORING-001"
COHORT_SIZE = 37
COMPARISON_SCHEMA = "role_benchmark.temporal_conversion_comparison.v1"
DEFAULT_REGISTRATION = (
    Path(__file__).resolve().parent
    / "registrations"
    / EXPERIMENT_ID
    / "registration.json"
)

_HISTORICAL_KEYS = {
    "first_attempt_structural_validity_rate": (
        "first_attempt_structural_validity_rate",
        "first_attempt_structural_validity",
    ),
    "post_repair_structural_validity_rate": (
        "post_repair_structural_validity_rate",
        "post_repair_structural_validity",
    ),
    "source_review_retention_rate": (
        "source_review_retention_rate",
        "source_review_retention",
    ),
    "final_acceptance_rate": (
        "final_acceptance_rate",
        "final_acceptance",
    ),
}


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError("%s must contain valid JSON" % path) from exc


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _integer(value: Any, label: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ValueError("%s must be an integer >= %d" % (label, minimum))
    return value


def _validated_rate(
    payload: Mapping[str, Any],
    label: str,
    *,
    count_key: str,
) -> Dict[str, Any]:
    if not isinstance(payload, Mapping):
        raise ValueError("%s must be an object" % label)
    numerator = _integer(payload.get(count_key), "%s.%s" % (label, count_key))
    denominator = _integer(payload.get("denominator"), "%s.denominator" % label, minimum=1)
    if denominator != COHORT_SIZE:
        raise ValueError("%s denominator must be the fixed cohort of 37 papers" % label)
    if numerator > denominator:
        raise ValueError("%s numerator exceeds its denominator" % label)
    rate = payload.get("rate")
    if isinstance(rate, bool) or not isinstance(rate, (int, float)) or not math.isfinite(rate):
        raise ValueError("%s.rate must be finite" % label)
    expected = numerator / denominator
    if not math.isclose(float(rate), expected, rel_tol=0.0, abs_tol=1e-12):
        raise ValueError("%s.rate does not equal numerator / denominator" % label)
    return {
        "numerator": numerator,
        "denominator": denominator,
        "rate": expected,
    }


def _binomial_cdf(k: int, n: int, probability: float) -> float:
    return sum(
        math.comb(n, value)
        * probability**value
        * (1.0 - probability) ** (n - value)
        for value in range(k + 1)
    )


def _decreasing_root(k: int, n: int, target: float) -> float:
    lower = 0.0
    upper = 1.0
    for _ in range(100):
        midpoint = (lower + upper) / 2.0
        if _binomial_cdf(k, n, midpoint) > target:
            lower = midpoint
        else:
            upper = midpoint
    return (lower + upper) / 2.0


def _exact_binomial_interval_95(numerator: int, denominator: int) -> list[float]:
    """Return the two-sided 95% Clopper-Pearson interval."""

    lower = (
        0.0
        if numerator == 0
        else _decreasing_root(numerator - 1, denominator, 0.975)
    )
    upper = (
        1.0
        if numerator == denominator
        else _decreasing_root(numerator, denominator, 0.025)
    )
    return [lower, upper]


def _manifest_paper_ids(
    registration_path: Path,
    registration: Mapping[str, Any],
) -> tuple[list[str], Mapping[str, int]]:
    manifest_name = registration.get("source_manifest")
    if not isinstance(manifest_name, str) or not manifest_name:
        raise ValueError("registration.source_manifest must be non-empty text")
    manifest = _read_json(registration_path.with_name(manifest_name))
    if not isinstance(manifest, Mapping) or manifest.get("cohort_size") != COHORT_SIZE:
        raise ValueError("source manifest must declare exactly 37 papers")
    sources = manifest.get("sources")
    if not isinstance(sources, list) or len(sources) != COHORT_SIZE:
        raise ValueError("source manifest must contain exactly 37 papers")
    paper_ids = []
    call_caps: Dict[str, int] = {}
    for expected_order, source in enumerate(sources, start=1):
        if not isinstance(source, Mapping) or source.get("order") != expected_order:
            raise ValueError("source manifest order must be exactly 1 through 37")
        paper_id = source.get("paper_id")
        if not isinstance(paper_id, str) or not paper_id or paper_id in call_caps:
            raise ValueError("source manifest paper IDs must be non-empty and unique")
        cap = _integer(
            source.get("max_total_attempts"),
            "source[%d].max_total_attempts" % expected_order,
            minimum=1,
        )
        paper_ids.append(paper_id)
        call_caps[paper_id] = cap
    return paper_ids, call_caps


def _historical_metrics(registration: Mapping[str, Any]) -> Mapping[str, Mapping[str, Any]]:
    baseline = registration.get("historical_baseline")
    if not isinstance(baseline, Mapping):
        raise ValueError("registration.historical_baseline must be an object")
    if baseline.get("comparison_status") not in {"controlled", "descriptive_only"}:
        raise ValueError(
            "historical comparison_status must be controlled or descriptive_only"
        )
    raw = baseline.get("metrics")
    if not isinstance(raw, Mapping):
        raise ValueError("historical_baseline.metrics must be an object")
    output = {}
    for output_name, (historical_name, _) in _HISTORICAL_KEYS.items():
        if historical_name not in raw:
            raise ValueError("historical baseline is missing %s" % historical_name)
        output[output_name] = _validated_rate(
            raw[historical_name],
            "historical_baseline.metrics.%s" % historical_name,
            count_key="numerator",
        )

    # A revision-required decision is not an eligible relation.  Counting the
    # six historical revision requests as retained would change the estimand.
    retention = output["source_review_retention_rate"]
    if retention["numerator"] != 0:
        raise ValueError(
            "historical source-review retention must count eligible decisions "
            "only: expected 0/37; revision-required papers are not retained"
        )
    return output


def _nonplaceholder_snapshot(value: Any) -> bool:
    return (
        isinstance(value, str)
        and bool(value.strip())
        and value.strip().lower() not in {"unknown", "unavailable", "none", "null"}
    )


def _run_config(
    registration_path: Path,
    result_path: Path,
    registration: Mapping[str, Any],
) -> Mapping[str, Any]:
    """Validate the frozen registration and the configuration used by the run."""

    frozen_registration_path = result_path.with_name("registration.json")
    if not frozen_registration_path.is_file():
        raise ValueError("run directory is missing its frozen registration.json")
    frozen_registration = _read_json(frozen_registration_path)
    if frozen_registration != registration:
        raise ValueError("run registration differs from the supplied frozen registration")

    config_path = result_path.with_name("config.json")
    if not config_path.is_file():
        raise ValueError("run directory is missing config.json")
    config = _read_json(config_path)
    if not isinstance(config, Mapping):
        raise ValueError("run config must be an object")
    if config.get("schema") != "role_benchmark.temporal_conversion_run.v1":
        raise ValueError("unexpected run-config schema")
    if config.get("experiment_id") != EXPERIMENT_ID:
        raise ValueError("run config has an unexpected experiment_id")
    if config.get("cohort_size") != COHORT_SIZE:
        raise ValueError("run config must use the fixed cohort of 37 papers")
    if config.get("process_all_sources") is not True:
        raise ValueError("run config must process all frozen sources")
    if config.get("source_manifest") != registration.get("source_manifest"):
        raise ValueError("run config and registration use different source manifests")
    manifest_name = registration.get("source_manifest")
    registered_manifest_path = registration_path.with_name(str(manifest_name))
    frozen_manifest_path = result_path.with_name(str(manifest_name))
    if not frozen_manifest_path.is_file():
        raise ValueError("run directory is missing its frozen source manifest")
    if _read_json(frozen_manifest_path) != _read_json(registered_manifest_path):
        raise ValueError("run source manifest differs from the registered source manifest")
    if config.get("dry_run") is not False:
        raise ValueError("a dry run cannot be compared as a completed experiment")

    registered_model = registration.get("authoring_model")
    actual_model = config.get("model")
    if not isinstance(registered_model, Mapping) or not isinstance(actual_model, Mapping):
        raise ValueError("registration and run config must record authoring-model settings")
    model_fields = (
        "provider",
        "api",
        "endpoint",
        "model_id",
        "checkpoint_or_snapshot_id",
        "knowledge_cutoff",
        "thinking",
        "reasoning_effort",
    )
    for field in model_fields:
        if actual_model.get(field) != registered_model.get(field):
            raise ValueError(
                "run config authoring-model field %s differs from registration" % field
            )

    registered_snapshot = registered_model.get("checkpoint_or_snapshot_id")
    if actual_model.get("provider_request_model") != registered_snapshot:
        raise ValueError(
            "provider_request_model must exactly equal the registered immutable snapshot"
        )

    generation = config.get("generation")
    if not isinstance(generation, Mapping):
        raise ValueError("run config must record generation settings")
    generation_fields = ("temperature", "top_p", "max_output_tokens")
    for field in generation_fields:
        if generation.get(field) != registered_model.get(field):
            raise ValueError(
                "run config generation field %s differs from registration" % field
            )
    if generation.get("per_source_max_total_attempts") != registration.get(
        "source_manifest"
    ):
        raise ValueError("run config must use the registered per-source call limits")
    return config


def _comparison_status(
    registration: Mapping[str, Any],
    config: Mapping[str, Any],
) -> str:
    baseline = registration["historical_baseline"]
    historical_status = baseline["comparison_status"]
    historical_snapshot = baseline.get("authoring_model_checkpoint_or_snapshot_id")
    registered_snapshot = registration["authoring_model"].get(
        "checkpoint_or_snapshot_id"
    )
    actual_model = config["model"]
    actual_snapshot = actual_model.get("checkpoint_or_snapshot_id")
    provider_request_model = actual_model.get("provider_request_model")

    if historical_status == "descriptive_only":
        return "descriptive_only"
    if registration.get("status") != "ready_for_execution":
        raise ValueError("a controlled comparison requires a ready registration")
    if not _nonplaceholder_snapshot(historical_snapshot):
        raise ValueError(
            "a controlled comparison requires a non-placeholder historical snapshot"
        )
    if not (
        historical_snapshot
        == registered_snapshot
        == actual_snapshot
        == provider_request_model
    ):
        raise ValueError(
            "controlled comparison requires identical historical, registered, "
            "run-config, and provider-request snapshot IDs"
        )
    return "controlled"


def _validate_paper_results(
    paper_results: Any,
    expected_paper_ids: Sequence[str],
    call_caps: Mapping[str, int],
) -> Mapping[str, int]:
    if not isinstance(paper_results, list) or len(paper_results) != COHORT_SIZE:
        raise ValueError("result.paper_results must contain all 37 papers")
    observed_ids = [item.get("paper_id") if isinstance(item, Mapping) else None for item in paper_results]
    if observed_ids != list(expected_paper_ids):
        raise ValueError("result.paper_results must match the frozen paper IDs and order")

    first = post_repair = nonempty = reviewed = eligible = accepted = 0
    revision_required = rejected = calls = 0
    eligible_statuses = {"case_accepted", "construction_rejected"}
    reviewed_statuses = eligible_statuses | {
        "card_revision_required",
        "source_review_rejected",
    }
    for item in paper_results:
        paper_id = str(item["paper_id"])
        attempt_count = _integer(
            item.get("attempt_count"),
            "paper_results[%s].attempt_count" % paper_id,
            minimum=1,
        )
        if attempt_count > call_caps[paper_id]:
            raise ValueError("paper %s exceeds its frozen authoring-call limit" % paper_id)
        calls += attempt_count
        relation = item.get("nonempty_relation") is True
        structural = item.get("structural_valid") is True and relation
        first_valid = (
            item.get("first_attempt_structural_valid") is True and structural
        )
        if relation:
            completed_response_count = _integer(
                item.get("completed_response_count"),
                "paper_results[%s].completed_response_count" % paper_id,
                minimum=1,
            )
            if completed_response_count > attempt_count:
                raise ValueError(
                    "paper %s has more completed responses than provider calls"
                    % paper_id
                )
            if first_valid != (completed_response_count == 1):
                raise ValueError(
                    "paper %s has an inconsistent first-response validity flag"
                    % paper_id
                )
        source_review_completed = item.get("source_review_completed") is True
        status = item.get("status")
        if source_review_completed != (status in reviewed_statuses):
            raise ValueError("paper %s has inconsistent source-review status" % paper_id)
        if source_review_completed and not relation:
            raise ValueError("paper %s was reviewed without a nonempty relation" % paper_id)
        if relation and not source_review_completed:
            raise ValueError("source review is incomplete for paper %s" % paper_id)
        first += int(first_valid)
        post_repair += int(structural)
        nonempty += int(relation)
        reviewed += int(source_review_completed)
        eligible += int(status in eligible_statuses)
        accepted += int(status == "case_accepted")
        revision_required += int(status == "card_revision_required")
        rejected += int(status == "source_review_rejected")
    if post_repair != nonempty:
        raise ValueError(
            "post-repair structural validity must require a nonempty relation"
        )
    if first > post_repair:
        raise ValueError("first-attempt validity cannot exceed post-repair validity")
    if reviewed != nonempty:
        raise ValueError("source review is incomplete for the structurally valid papers")
    return {
        "first": first,
        "post_repair": post_repair,
        "nonempty": nonempty,
        "reviewed": reviewed,
        "eligible": eligible,
        "accepted": accepted,
        "revision_required": revision_required,
        "rejected": rejected,
        "calls": calls,
    }


def _revised_metrics(
    metrics: Mapping[str, Any],
    derived: Mapping[str, int],
    maximum_calls: int,
) -> Mapping[str, Mapping[str, Any]]:
    if metrics.get("cohort_size") != COHORT_SIZE:
        raise ValueError("revised metrics must use the fixed cohort of 37 papers")
    calls = _integer(metrics.get("actual_science_card_calls"), "actual_science_card_calls")
    if calls != derived["calls"]:
        raise ValueError("actual_science_card_calls disagrees with paper results")
    if calls > maximum_calls:
        raise ValueError("revised run exceeds the registered authoring-call budget")

    first = _validated_rate(
        metrics.get("first_attempt_structural_validity"),
        "metrics.first_attempt_structural_validity",
        count_key="count",
    )
    post_repair = _validated_rate(
        metrics.get("post_repair_structural_validity"),
        "metrics.post_repair_structural_validity",
        count_key="count",
    )
    nonempty = _validated_rate(
        metrics.get("nonempty_relation"),
        "metrics.nonempty_relation",
        count_key="count",
    )
    if first["numerator"] != derived["first"]:
        raise ValueError("first-attempt structural-validity count disagrees with paper results")
    if post_repair["numerator"] != derived["post_repair"]:
        raise ValueError("post-repair structural-validity count disagrees with paper results")
    if nonempty["numerator"] != derived["nonempty"]:
        raise ValueError("nonempty-relation count disagrees with paper results")
    if post_repair != nonempty:
        raise ValueError("post-repair structural validity must require a nonempty relation")

    review = metrics.get("source_review")
    if not isinstance(review, Mapping) or review.get("complete") is not True:
        raise ValueError("all source reviews must be complete before comparison")
    checks = {
        "completed_count": "reviewed",
        "eligible_count": "eligible",
        "card_revision_required_count": "revision_required",
        "rejected_count": "rejected",
    }
    for field, derived_field in checks.items():
        if _integer(review.get(field), "metrics.source_review.%s" % field) != derived[derived_field]:
            raise ValueError("metrics.source_review.%s disagrees with paper results" % field)
    conditional = review.get("conditional_retention_rate")
    expected_conditional = (
        derived["eligible"] / derived["nonempty"] if derived["nonempty"] else None
    )
    if conditional != expected_conditional:
        raise ValueError("conditional source-review retention is inconsistent")
    unconditional = review.get("unconditional_retention_rate")
    expected_unconditional = derived["eligible"] / COHORT_SIZE
    if unconditional != expected_unconditional:
        raise ValueError("unconditional source-review retention is inconsistent")
    source_review = {
        "numerator": derived["eligible"],
        "denominator": COHORT_SIZE,
        "rate": expected_unconditional,
    }

    final_acceptance = _validated_rate(
        metrics.get("final_acceptance"),
        "metrics.final_acceptance",
        count_key="count",
    )
    if final_acceptance["numerator"] != derived["accepted"]:
        raise ValueError("final-acceptance count disagrees with paper results")
    if final_acceptance["numerator"] > source_review["numerator"]:
        raise ValueError("final acceptance cannot exceed source-review eligibility")
    return {
        "first_attempt_structural_validity_rate": first,
        "post_repair_structural_validity_rate": post_repair,
        "source_review_retention_rate": source_review,
        "final_acceptance_rate": final_acceptance,
    }


def compare_temporal_conversion(
    registration_path: Path,
    result_path: Path,
    metrics_path: Path,
) -> Mapping[str, Any]:
    registration = _read_json(registration_path)
    result = _read_json(result_path)
    metrics = _read_json(metrics_path)
    if not isinstance(registration, Mapping) or registration.get("experiment_id") != EXPERIMENT_ID:
        raise ValueError("unexpected or missing experiment_id in registration")
    if registration.get("cohort_size") != COHORT_SIZE:
        raise ValueError("registration must freeze exactly 37 papers")
    if not isinstance(result, Mapping) or result.get("experiment_id") != EXPERIMENT_ID:
        raise ValueError("unexpected or missing experiment_id in revised result")
    if result.get("status") != "complete":
        raise ValueError("revised run must be complete before comparison")
    if result.get("metrics") != metrics:
        raise ValueError("result.json and metrics.json disagree")

    config = _run_config(registration_path, result_path, registration)
    paper_ids, call_caps = _manifest_paper_ids(registration_path, registration)
    historical = _historical_metrics(registration)
    derived = _validate_paper_results(result.get("paper_results"), paper_ids, call_caps)
    call_budget = registration.get("call_budget")
    if not isinstance(call_budget, Mapping):
        raise ValueError("registration.call_budget must be an object")
    maximum_calls = _integer(
        call_budget.get("maximum_attempts_total"),
        "registration.call_budget.maximum_attempts_total",
        minimum=1,
    )
    if maximum_calls != sum(call_caps.values()):
        raise ValueError("registered total call budget disagrees with source-level limits")
    revised = _revised_metrics(metrics, derived, maximum_calls)
    comparison_status = _comparison_status(registration, config)
    comparable = comparison_status == "controlled"
    if config.get("historical_snapshot_comparable") is not comparable:
        raise ValueError(
            "run config historical_snapshot_comparable disagrees with validated snapshots"
        )
    if metrics.get("historical_snapshot_comparable") is not comparable:
        raise ValueError(
            "metrics historical_snapshot_comparable disagrees with validated snapshots"
        )

    comparisons = {}
    for metric_name in _HISTORICAL_KEYS:
        old = historical[metric_name]
        new = revised[metric_name]
        comparisons[metric_name] = {
            "historical": old,
            "revised": new,
            "revised_exact_binomial_confidence_interval_95": (
                _exact_binomial_interval_95(
                    new["numerator"],
                    new["denominator"],
                )
            ),
            "percentage_point_difference": 100.0 * (new["rate"] - old["rate"]),
        }
    if comparison_status == "controlled":
        interpretation = (
            "The frozen registration and run configuration identify the same "
            "non-placeholder immutable authoring-model snapshot as the historical "
            "run. The reported differences are a controlled comparison of the two "
            "registered pipelines on this fixed cohort. No statistical significance "
            "claim is made."
        )
    else:
        interpretation = (
            "Differences are descriptive only because the historical immutable "
            "authoring-model snapshot was not preregistered as controlled. Matching "
            "the mutable model alias is insufficient. No causal effect or statistical "
            "significance claim is supported."
        )
    return {
        "schema": COMPARISON_SCHEMA,
        "experiment_id": EXPERIMENT_ID,
        "cohort_size": COHORT_SIZE,
        "comparison_status": comparison_status,
        "source_reviews_complete": True,
        "metrics": comparisons,
        "interpretation": interpretation,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Compare one complete revised Temporal conversion run."
    )
    parser.add_argument("run_directory")
    parser.add_argument("--registration", default=str(DEFAULT_REGISTRATION))
    parser.add_argument(
        "--output",
        help="defaults to <run_directory>/comparison.json",
    )
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = _parser().parse_args(argv)
    run_directory = Path(args.run_directory)
    output_path = Path(args.output) if args.output else run_directory / "comparison.json"
    comparison = compare_temporal_conversion(
        Path(args.registration).resolve(),
        run_directory / "result.json",
        run_directory / "metrics.json",
    )
    _write_json(output_path, comparison)
    print(json.dumps(comparison, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
