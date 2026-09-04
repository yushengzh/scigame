"""Run the full-cohort minimal-ScienceCard Temporal conversion experiment."""

from __future__ import annotations

import argparse
import getpass
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Sequence

from experiments.run_pendulum_matrix import DeepSeekChatBackend
from role_benchmark import (
    BenchmarkTrack,
    Episode,
    GenerationConfig,
    GenerationRequest,
    GenerationResponse,
    Hypothesis,
    HypothesisPortfolio,
    PlayerAction,
    TextGenerationBackend,
    TokenUsage,
)
from role_benchmark.cases.source import make_source_case, source_truth_submission
from role_benchmark.llm import (
    generation_request_to_payload,
    generation_response_to_payload,
)
from role_benchmark.temporal import (
    MinimalScienceCardError,
    TemporalAdmissionError,
    TemporalCaseConstructionError,
    assess_temporal_admission,
    compile_temporal_source_case,
    extract_minimal_science_card,
    minimal_science_card_to_payload,
    normalize_source_packet,
    parse_minimal_science_card_json,
    parse_temporal_admission_review_json,
    temporal_admission_review_request_payload,
    validate_minimal_science_card_lineage,
    write_temporal_source_case_module,
)


DEFAULT_REGISTRATION = (
    Path(__file__).resolve().parent
    / "registrations"
    / "EXP-TEMPORAL-AUTHORING-001"
    / "registration.json"
)
DEFAULT_API_KEY_ENV = "DEEPSEEK_API_KEY"
RUN_CONFIG_SCHEMA = "role_benchmark.temporal_conversion_run.v1"
METRICS_SCHEMA = "role_benchmark.temporal_conversion_metrics.v1"


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


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Process all 37 preregistered frozen source packets with the "
            "minimal ScienceCard pipeline; never reselect sources."
        )
    )
    parser.add_argument("output_directory")
    parser.add_argument(
        "--registration",
        default=str(DEFAULT_REGISTRATION),
    )
    parser.add_argument(
        "--reviews-directory",
        help="independent reviews; defaults to <output_directory>/reviews",
    )
    parser.add_argument(
        "--authoring-snapshot-id",
        required=True,
        help=(
            "actual immutable checkpoint/snapshot ID recorded in the ready "
            "experiment registration"
        ),
    )
    credential = parser.add_mutually_exclusive_group()
    credential.add_argument("--api-key", help="runtime credential; never persisted")
    credential.add_argument("--api-key-stdin", action="store_true")
    credential.add_argument("--prompt-api-key", action="store_true")
    parser.add_argument("--api-key-env", default=DEFAULT_API_KEY_ENV)
    parser.add_argument("--dry-run", action="store_true")
    return parser


def _api_key(args: argparse.Namespace) -> str:
    if args.api_key is not None:
        value = args.api_key
    elif args.api_key_stdin:
        value = sys.stdin.readline().rstrip("\r\n")
    elif args.prompt_api_key:
        value = getpass.getpass("Authoring API key: ")
    else:
        value = os.environ.get(args.api_key_env, "")
    if not value.strip():
        raise ValueError(
            "missing API key: use --api-key, --api-key-stdin, "
            "--prompt-api-key, or set %s" % args.api_key_env
        )
    return value


def _generation_response_from_payload(payload: Any) -> GenerationResponse:
    if not isinstance(payload, Mapping):
        raise ValueError("recorded generation response must be an object")
    usage = payload.get("usage")
    if not isinstance(usage, Mapping):
        raise ValueError("recorded generation response usage must be an object")
    try:
        return GenerationResponse(
            text=payload["text"],
            provider=payload["provider"],
            model=payload["model"],
            finish_reason=payload["finish_reason"],
            response_id=payload["response_id"],
            usage=TokenUsage(
                input_tokens=usage.get("input_tokens"),
                output_tokens=usage.get("output_tokens"),
            ),
            metadata=payload["metadata"],
        )
    except KeyError as exc:
        raise ValueError("recorded generation response is incomplete") from exc


class _RecordingBackend:
    def __init__(
        self,
        backend: TextGenerationBackend,
        directory: Path,
        *,
        max_total_attempts: int,
    ) -> None:
        self._backend = backend
        self._directory = directory
        self._max_total_attempts = max_total_attempts
        attempt_numbers = []
        for path in directory.iterdir():
            if not path.is_dir() or not path.name.startswith("attempt_"):
                continue
            suffix = path.name.removeprefix("attempt_")
            if not suffix.isdigit() or len(suffix) != 2:
                raise RuntimeError("invalid ScienceCard attempt directory name")
            attempt_numbers.append(int(suffix))
        attempt_numbers.sort()
        if attempt_numbers != list(range(1, len(attempt_numbers) + 1)):
            raise RuntimeError("ScienceCard attempt directories must be contiguous")
        if len(attempt_numbers) > max_total_attempts:
            raise RuntimeError("recorded ScienceCard attempts exceed the frozen budget")
        for attempt_number in attempt_numbers:
            attempt_directory = directory / ("attempt_%02d" % attempt_number)
            if not (attempt_directory / "request.json").is_file():
                raise RuntimeError("recorded ScienceCard attempt has no request")
        self._existing_attempt_count = len(attempt_numbers)
        self._cursor = 0
        self.attempt_count = 0

    def generate(self, request: GenerationRequest) -> GenerationResponse:
        request_payload = generation_request_to_payload(request)
        while self._cursor < self._existing_attempt_count:
            self._cursor += 1
            self.attempt_count = self._cursor
            attempt_directory = self._directory / (
                "attempt_%02d" % self.attempt_count
            )
            if _read_json(attempt_directory / "request.json") != request_payload:
                raise RuntimeError(
                    "recorded ScienceCard request differs from the resumed request"
                )
            response_path = attempt_directory / "response.json"
            if response_path.is_file():
                return _generation_response_from_payload(_read_json(response_path))

            interruption_path = attempt_directory / "response_unavailable.json"
            if not interruption_path.exists():
                _write_json(
                    interruption_path,
                    {
                        "attempt_number": self.attempt_count,
                        "budget_accounting": "counted_as_consumed",
                        "response_status": "unavailable",
                        "recovery_action": "continue_with_next_attempt_if_budget_remains",
                    },
                )

        if self._existing_attempt_count >= self._max_total_attempts:
            raise RuntimeError(
                "a recorded provider call has no response and the frozen per-paper "
                "budget is exhausted; this is missing infrastructure data, not a "
                "ScienceCard failure"
            )

        self._existing_attempt_count += 1
        self._cursor = self._existing_attempt_count
        self.attempt_count = self._cursor
        attempt_directory = self._directory / ("attempt_%02d" % self.attempt_count)
        attempt_directory.mkdir(exist_ok=False)
        _write_json(
            attempt_directory / "request.json",
            request_payload,
        )
        try:
            response = self._backend.generate(request)
        except Exception:
            _write_json(
                attempt_directory / "response_unavailable.json",
                {
                    "attempt_number": self.attempt_count,
                    "budget_accounting": "counted_as_consumed",
                    "response_status": "unavailable",
                    "recovery_action": "continue_with_next_attempt_if_budget_remains",
                },
            )
            raise
        _write_json(
            attempt_directory / "response.json",
            generation_response_to_payload(response),
        )
        return response


def _registration_contract(
    registration_path: Path,
) -> tuple[Mapping[str, Any], Mapping[str, Any], list[Mapping[str, Any]]]:
    registration = _read_json(registration_path)
    required = {
        "experiment_id",
        "authoring_model",
        "source_manifest",
        "status",
    }
    if not isinstance(registration, dict) or not required <= set(registration):
        raise ValueError("registration is missing required fields")
    if registration["experiment_id"] != "EXP-TEMPORAL-AUTHORING-001":
        raise ValueError("unexpected experiment_id")
    if registration.get("cohort_size") != 37:
        raise ValueError("registration must freeze exactly 37 papers")
    model = registration["authoring_model"]
    required_model = {
        "provider",
        "api",
        "endpoint",
        "model_id",
        "checkpoint_or_snapshot_id",
        "knowledge_cutoff",
        "thinking",
        "temperature",
        "top_p",
        "max_output_tokens",
        "reasoning_effort",
        "timeout_s",
    }
    if not isinstance(model, dict) or set(model) != required_model:
        raise ValueError("registration authoring_model contract is incomplete")
    manifest_path = registration_path.with_name(registration["source_manifest"])
    manifest = _read_json(manifest_path)
    if (
        not isinstance(manifest, dict)
        or manifest.get("experiment_id") != registration["experiment_id"]
        or manifest.get("cohort_size") != 37
        or not isinstance(manifest.get("sources"), list)
        or len(manifest["sources"]) != 37
    ):
        raise ValueError("source manifest must freeze exactly 37 entries")
    sources = manifest["sources"]
    paper_ids = [item.get("paper_id") for item in sources]
    orders = [item.get("order") for item in sources]
    if len(set(paper_ids)) != 37 or orders != list(range(1, 38)):
        raise ValueError("source manifest paper IDs and order must be unique and fixed")
    required_source = {
        "order",
        "paper_id",
        "source_citation",
        "journal_doi",
        "arxiv_versioned_id",
        "source_packet_path",
        "baseline_batch",
        "max_total_attempts",
    }
    for item in sources:
        if set(item) != required_source:
            raise ValueError("every source entry must use the frozen manifest schema")
        if item["max_total_attempts"] not in {2, 4}:
            raise ValueError("historical per-paper call cap must be two or four")
    batch_budget = {
        ("family_generation", 2): 17,
        ("expansion_family_generation", 4): 20,
    }
    observed_batch_budget = {
        key: sum(
            item["baseline_batch"] == key[0]
            and item["max_total_attempts"] == key[1]
            for item in sources
        )
        for key in batch_budget
    }
    if observed_batch_budget != batch_budget:
        raise ValueError(
            "source manifest must preserve the historical 17-by-2 and 20-by-4 budgets"
        )
    registered_budget = registration.get("call_budget")
    if (
        not isinstance(registered_budget, dict)
        or registered_budget.get("maximum_attempts_total")
        != sum(item["max_total_attempts"] for item in sources)
    ):
        raise ValueError("registration and source-level call budgets disagree")
    return registration, manifest, sources


def _source_path(raw_path: str) -> Path:
    if not isinstance(raw_path, str) or not raw_path.strip():
        raise ValueError("source_packet_path must be non-empty text")
    path = Path(raw_path)
    if not path.is_absolute():
        path = Path(__file__).resolve().parents[1] / path
    resolved = path.resolve()
    if not resolved.is_file():
        raise ValueError("frozen source packet does not exist: %s" % resolved)
    return resolved


def _registered_live_snapshot(
    registration: Mapping[str, Any],
    supplied_snapshot: str,
) -> str:
    """Return the provider-callable snapshot for the registered comparison."""

    model = registration.get("authoring_model")
    baseline = registration.get("historical_baseline")
    if not isinstance(model, Mapping) or not isinstance(baseline, Mapping):
        raise ValueError("registration is missing the model snapshot contract")
    registered = model.get("checkpoint_or_snapshot_id")
    historical = baseline.get("authoring_model_checkpoint_or_snapshot_id")
    if (
        not isinstance(registered, str)
        or not registered.strip()
        or registered == "unknown"
    ):
        raise ValueError("live execution requires a registered immutable model snapshot")
    if historical != registered:
        raise ValueError(
            "the registered authoring snapshot must exactly match the historical snapshot"
        )
    if baseline.get("comparison_status") != "controlled":
        raise ValueError(
            "live execution requires a registration marked as a controlled comparison"
        )
    if supplied_snapshot != registered:
        raise ValueError(
            "authoring snapshot must exactly match the experiment registration"
        )
    return registered


def _freeze_config(
    output: Path,
    registration_path: Path,
    registration: Mapping[str, Any],
    manifest: Mapping[str, Any],
    args: argparse.Namespace,
) -> Mapping[str, Any]:
    model = registration["authoring_model"]
    if not isinstance(model, Mapping):
        raise ValueError("authoring_model must be an object")
    historical = registration.get("historical_baseline")
    historical_snapshot = (
        historical.get("authoring_model_checkpoint_or_snapshot_id")
        if isinstance(historical, Mapping)
        else None
    )
    controlled_snapshot_match = bool(
        isinstance(historical, Mapping)
        and historical.get("comparison_status") == "controlled"
        and isinstance(args.authoring_snapshot_id, str)
        and args.authoring_snapshot_id != "unknown"
        and model["checkpoint_or_snapshot_id"] == args.authoring_snapshot_id
        and historical_snapshot == args.authoring_snapshot_id
    )
    payload = {
        "schema": RUN_CONFIG_SCHEMA,
        "experiment_id": registration["experiment_id"],
        "registration": str(registration_path.resolve()),
        "source_manifest": registration["source_manifest"],
        "cohort_size": manifest["cohort_size"],
        "process_all_sources": True,
        "model": {
            "provider": model["provider"],
            "api": model["api"],
            "endpoint": model["endpoint"],
            "model_id": model["model_id"],
            "checkpoint_or_snapshot_id": args.authoring_snapshot_id,
            "provider_request_model": args.authoring_snapshot_id,
            "knowledge_cutoff": model["knowledge_cutoff"],
            "thinking": model["thinking"],
            "reasoning_effort": model["reasoning_effort"],
        },
        "generation": {
            "temperature": model["temperature"],
            "top_p": model["top_p"],
            "max_output_tokens": model["max_output_tokens"],
            "per_source_max_total_attempts": registration["source_manifest"],
        },
        "historical_snapshot_comparable": controlled_snapshot_match,
        "historical_snapshot_limitation": (
            None
            if controlled_snapshot_match
            else "The registration and run do not establish an exact immutable historical-snapshot match for a controlled comparison."
        ),
        "dry_run": bool(args.dry_run),
    }
    path = output / "config.json"
    if path.exists():
        if _read_json(path) != payload:
            raise ValueError("output directory contains a different run config")
    else:
        _write_json(path, payload)
    frozen_registration = output / "registration.json"
    if frozen_registration.exists():
        if _read_json(frozen_registration) != registration:
            raise ValueError("output directory contains a different registration")
    else:
        _write_json(frozen_registration, registration)
    frozen_manifest = output / "frozen_sources.json"
    if frozen_manifest.exists():
        if _read_json(frozen_manifest) != manifest:
            raise ValueError("output directory contains a different source manifest")
    else:
        _write_json(frozen_manifest, manifest)
    return payload


def _load_card(path: Path, source: Mapping[str, Any], line_count: int) -> Any:
    card = parse_minimal_science_card_json(path.read_text(encoding="utf-8"))
    identity = (
        card.source.citation,
        card.source.journal_doi,
        card.source.arxiv_versioned_id,
    )
    expected = (
        source["source_citation"],
        source["journal_doi"],
        source["arxiv_versioned_id"],
    )
    if identity != expected:
        raise ValueError("recorded minimal ScienceCard identifies another source")
    validate_minimal_science_card_lineage(card, line_count)
    return card


def _validate_case(spec: Any) -> Mapping[str, Any]:
    cells = []
    for track in (BenchmarkTrack.IDENTIFICATION, BenchmarkTrack.DISCOVERY):
        case = make_source_case(spec, track)
        portfolio = HypothesisPortfolio(
            (
                Hypothesis(
                    hypothesis_id="H1",
                    statement="Known-truth Temporal case canary.",
                    confidence=1.0,
                ),
            )
        )
        episode = Episode(case)
        episode.apply(
            PlayerAction.submit_final(
                portfolio,
                source_truth_submission(spec, track),
            )
        )
        outcome = episode.outcome
        passed = bool(
            outcome.active_pass
            and outcome.protocol_completed
            and outcome.evaluation.success
            and outcome.evaluation.scores.get("predictive_model_pass") == 1.0
        )
        cells.append({"track": track.value, "truth_passes": passed})
    if not all(item["truth_passes"] for item in cells):
        raise RuntimeError("compiled source case failed its two task-setting canary")
    return {"all_pass": True, "cells": cells}


def _paper_result(path: Path, paper_id: str, status: str, **details: Any) -> Dict[str, Any]:
    payload = {"paper_id": paper_id, "status": status, **details}
    _write_json(path, payload)
    return payload


def _rate(numerator: int, denominator: int) -> float:
    return numerator / denominator


def _metrics(
    results: Sequence[Mapping[str, Any]],
    actual_calls: int,
    *,
    historical_snapshot_comparable: bool = False,
) -> Mapping[str, Any]:
    if not isinstance(historical_snapshot_comparable, bool):
        raise ValueError("historical_snapshot_comparable must be boolean")
    total = len(results)
    structural = sum(
        bool(item.get("structural_valid") and item.get("nonempty_relation"))
        for item in results
    )
    first = sum(
        bool(
            item.get("first_attempt_structural_valid")
            and item.get("nonempty_relation")
        )
        for item in results
    )
    schema_valid = sum(bool(item.get("schema_valid")) for item in results)
    nonempty = sum(bool(item.get("nonempty_relation")) for item in results)
    reviewed = sum(bool(item.get("source_review_completed")) for item in results)
    admitted = sum(item.get("status") in {"case_accepted", "construction_rejected"} for item in results)
    revision = sum(item.get("status") == "card_revision_required" for item in results)
    rejected = sum(item.get("status") == "source_review_rejected" for item in results)
    accepted = sum(item.get("status") == "case_accepted" for item in results)
    reviews_complete = reviewed == nonempty
    return {
        "schema": METRICS_SCHEMA,
        "cohort_size": total,
        "actual_science_card_calls": actual_calls,
        "provider_response_schema_validity": {
            "count": schema_valid,
            "denominator": total,
            "rate": _rate(schema_valid, total),
        },
        "first_attempt_structural_validity": {
            "count": first,
            "denominator": total,
            "rate": _rate(first, total),
        },
        "post_repair_structural_validity": {
            "count": structural,
            "denominator": total,
            "rate": _rate(structural, total),
        },
        "nonempty_relation": {
            "count": nonempty,
            "denominator": total,
            "rate": _rate(nonempty, total),
        },
        "source_review": {
            "complete": reviews_complete,
            "completed_count": reviewed,
            "eligible_count": admitted,
            "card_revision_required_count": revision,
            "rejected_count": rejected,
            "conditional_retention_rate": (
                _rate(admitted, nonempty) if reviews_complete and nonempty else None
            ),
            "unconditional_retention_rate": (
                _rate(admitted, total) if reviews_complete else None
            ),
        },
        "final_acceptance": {
            "count": accepted,
            "denominator": total,
            "rate": _rate(accepted, total) if reviews_complete else None,
        },
        "historical_snapshot_comparable": historical_snapshot_comparable,
    }


def run(
    args: argparse.Namespace,
    *,
    backend: Optional[TextGenerationBackend] = None,
) -> int:
    registration_path = Path(args.registration).resolve()
    registration, manifest, sources = _registration_contract(registration_path)
    registered_snapshot = registration["authoring_model"].get(
        "checkpoint_or_snapshot_id"
    )
    if not args.dry_run:
        if registration["status"] != "ready_for_execution":
            raise ValueError(
                "live execution is blocked by the experiment registration: %s"
                % registration["status"]
            )
        registered_snapshot = _registered_live_snapshot(
            registration,
            args.authoring_snapshot_id,
        )
    output = Path(args.output_directory)
    output.mkdir(parents=True, exist_ok=True)
    papers_directory = output / "papers"
    papers_directory.mkdir(exist_ok=True)
    reviews_directory = (
        Path(args.reviews_directory)
        if args.reviews_directory
        else output / "reviews"
    )
    reviews_directory.mkdir(parents=True, exist_ok=True)
    config_payload = _freeze_config(
        output,
        registration_path,
        registration,
        manifest,
        args,
    )

    paths = [_source_path(item["source_packet_path"]) for item in sources]
    if args.dry_run:
        plan = {
            "experiment_id": registration["experiment_id"],
            "cohort_size": len(paths),
            "paper_ids": [item["paper_id"] for item in sources],
            "process_all_sources": True,
            "total_call_cap": sum(item["max_total_attempts"] for item in sources),
            "status": "validated_without_provider_calls",
        }
        _write_json(output / "plan.json", plan)
        print(json.dumps(plan, ensure_ascii=False, indent=2, sort_keys=True))
        return 0

    model = registration["authoring_model"]
    provider = backend or DeepSeekChatBackend(
        endpoint=model["endpoint"],
        api_key=_api_key(args),
        # The provider request is bound to the registered immutable snapshot;
        # the mutable model_id is retained only as descriptive model-family metadata.
        model=registered_snapshot,
        thinking=model["thinking"],
        reasoning_effort=model["reasoning_effort"],
        timeout_s=model["timeout_s"],
    )
    generation_config = GenerationConfig(
        max_output_tokens=model["max_output_tokens"],
        temperature=model["temperature"],
        top_p=model["top_p"],
    )
    results = []
    for source, source_path in zip(sources, paths):
        index = source["order"]
        paper_id = source["paper_id"]
        paper_directory = papers_directory / ("%02d_%s" % (index, paper_id))
        paper_directory.mkdir(exist_ok=True)
        result_path = paper_directory / "result.json"
        source_text = source_path.read_text(encoding="utf-8")
        normalized_line_count = len(normalize_source_packet(source_text).splitlines())
        result_context = {
            "baseline_batch": source["baseline_batch"],
            "max_total_attempts": source["max_total_attempts"],
        }
        card_path = paper_directory / "science_card.json"
        attempts_path = paper_directory / "science_card_attempts.json"
        if result_path.exists() and not card_path.exists():
            prior_result = _read_json(result_path)
            if prior_result.get("status") != "science_card_generation_failed":
                raise RuntimeError(
                    "paper result without a ScienceCard has an invalid resume state"
                )
            results.append(prior_result)
            continue
        if card_path.exists():
            card = _load_card(card_path, source, normalized_line_count)
            attempt_record = _read_json(attempts_path)
            attempt_count = attempt_record["attempt_count"]
            completed_response_count = attempt_record["completed_response_count"]
            first_attempt_structural_valid = attempt_record[
                "first_completed_response_structural_valid"
            ]
        else:
            stage_directory = paper_directory / "science_card"
            stage_directory.mkdir(exist_ok=True)
            recorder = _RecordingBackend(
                provider,
                stage_directory,
                max_total_attempts=source["max_total_attempts"],
            )
            try:
                extraction = extract_minimal_science_card(
                    recorder,
                    source_text,
                    source_citation=source["source_citation"],
                    journal_doi=source["journal_doi"],
                    arxiv_versioned_id=source["arxiv_versioned_id"],
                    config=generation_config,
                    max_total_attempts=source["max_total_attempts"],
                    source_format="source_packet",
                )
            except MinimalScienceCardError as exc:
                failure = {
                    "attempt_count": recorder.attempt_count,
                    "error": str(exc),
                    "error_code": exc.code,
                    "error_path": exc.path,
                    "error_detail": exc.detail,
                }
                _write_json(stage_directory / "failure.json", failure)
                result = _paper_result(
                    result_path,
                    paper_id,
                    "science_card_generation_failed",
                    schema_valid=False,
                    structural_valid=False,
                    first_attempt_structural_valid=False,
                    nonempty_relation=False,
                    source_review_completed=False,
                    attempt_count=recorder.attempt_count,
                    failure=failure,
                    **result_context,
                )
                results.append(result)
                continue
            card = extraction.card
            attempt_count = recorder.attempt_count
            completed_response_count = extraction.attempt_count
            first_attempt_structural_valid = bool(
                extraction.attempt_count == 1 and card.relations
            )
            if attempt_count != recorder._existing_attempt_count:
                raise RuntimeError(
                    "recorded ScienceCard attempts remain after the accepted response"
                )
            _write_json(card_path, minimal_science_card_to_payload(card))
            _write_json(
                attempts_path,
                {
                    "attempt_count": attempt_count,
                    "completed_response_count": completed_response_count,
                    "first_completed_response_structural_valid": (
                        first_attempt_structural_valid
                    ),
                    "max_total_attempts": source["max_total_attempts"],
                },
            )

        common = {
            "schema_valid": True,
            "structural_valid": bool(card.relations),
            "first_attempt_structural_valid": first_attempt_structural_valid,
            "nonempty_relation": bool(card.relations),
            "attempt_count": attempt_count,
            "completed_response_count": completed_response_count,
            **result_context,
        }
        if not card.relations:
            result = _paper_result(
                result_path,
                paper_id,
                "no_relation_extracted",
                source_review_completed=False,
                **common,
            )
            results.append(result)
            continue
        review_request_path = paper_directory / "source_review_request.json"
        _write_json(
            review_request_path,
            temporal_admission_review_request_payload(card, paper_id=paper_id),
        )
        review_path = reviews_directory / (paper_id + ".json")
        if not review_path.exists():
            result = _paper_result(
                result_path,
                paper_id,
                "awaiting_source_review",
                review_path=str(review_path),
                source_review_completed=False,
                **common,
            )
            results.append(result)
            continue
        try:
            review_text = review_path.read_text(encoding="utf-8")
            review = parse_temporal_admission_review_json(review_text)
            admission = assess_temporal_admission(
                card,
                review,
                paper_id=paper_id,
                source_line_count=normalized_line_count,
            )
        except TemporalAdmissionError as exc:
            result = _paper_result(
                result_path,
                paper_id,
                "invalid_source_review",
                source_review_completed=False,
                review_error=str(exc),
                **common,
            )
            results.append(result)
            continue
        consumed_review = paper_directory / "source_review.json"
        if consumed_review.exists():
            if consumed_review.read_text(encoding="utf-8") != review_text:
                raise RuntimeError("source review changed after it was consumed")
        else:
            consumed_review.write_text(review_text, encoding="utf-8")
        if not admission.admitted:
            status = admission.disposition
            result = _paper_result(
                result_path,
                paper_id,
                status,
                source_review_completed=True,
                issues=[
                    {
                        "code": item.code,
                        "detail": item.detail,
                        "blocking": item.blocking,
                    }
                    for item in admission.issues
                ],
                **common,
            )
            results.append(result)
            continue
        try:
            build = compile_temporal_source_case(admission, case_index=index)
            case_directory = paper_directory / "cases"
            case_path = write_temporal_source_case_module(
                admission,
                case_directory / (build.spec.family + ".py"),
                case_index=index,
            )
            _write_json(paper_directory / "provenance.json", build.provenance)
            validation = _validate_case(build.spec)
            _write_json(case_path.with_suffix(".validation.json"), validation)
        except (TemporalCaseConstructionError, RuntimeError, ValueError) as exc:
            result = _paper_result(
                result_path,
                paper_id,
                "construction_rejected",
                source_review_completed=True,
                construction_error=str(exc),
                **common,
            )
            results.append(result)
            continue
        result = _paper_result(
            result_path,
            paper_id,
            "case_accepted",
            source_review_completed=True,
            case_path=str(case_path),
            validation_path=str(case_path.with_suffix(".validation.json")),
            **common,
        )
        results.append(result)

    # Resumed cards made no calls in this invocation; report cumulative calls
    # from immutable per-paper attempt records instead of only new calls.
    cumulative_calls = sum(int(item.get("attempt_count", 0)) for item in results)
    metrics = _metrics(
        results,
        cumulative_calls,
        historical_snapshot_comparable=bool(
            config_payload["historical_snapshot_comparable"]
        ),
    )
    _write_json(output / "metrics.json", metrics)
    report = {
        "experiment_id": config_payload["experiment_id"],
        "metrics": metrics,
        "paper_results": results,
        "status": (
            "complete"
            if metrics["source_review"]["complete"]
            else "awaiting_source_reviews"
        ),
    }
    _write_json(output / "result.json", report)
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report["status"] == "complete" else 3


def main(argv: Optional[Sequence[str]] = None) -> int:
    return run(_parser().parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
