"""Run the temporal acceptance coordinator to a requested acceptance target.

This is the only runner allowed to render an accepted case.  The cohort,
non-secret runtime configuration, and every textual source packet are frozen before the
first provider call. Each paper receives one initial science-card call plus at
most three allowlisted mechanical card repairs, followed after source review by
one initial case-draft call plus at most three allowlisted mechanical draft repairs.
Both generation stages therefore have a four-call hard limit. Paper and
family source reviews are external gates.  Existing completed artifacts are
replayed on resume; a provider failure requires an explicit human skip
disposition or a new run directory.

A ``card_revision_required`` source verdict terminates the frozen run without
drafting or advancing the cohort. A later invocation may explicitly defer that
already-recorded paper to a separate revision run and continue the frozen
cohort; consumed artifacts in the current run remain immutable. For a
single-paper cohort, the new run may supply the prior card and its structured
issues as explicitly non-authoritative revision context; the new card still
requires a new independent source review.

An artifact/schema ``draft_generation_failed`` result may receive one explicit
``--retry-draft PAPER_ID`` disposition. The coordinator revalidates the frozen
reviewed ScienceCard, source review, and eligibility, preserves the original
attempts, and records the new calls below ``case_draft/retry/``.
"""

from __future__ import annotations

import argparse
import json
import runpy
import tempfile
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence

from experiments.run_pendulum_matrix import DeepSeekChatBackend
from experiments.run_temporal_authoring import (
    DEFAULT_API_KEY_ENV,
    DEFAULT_ENDPOINT,
    DEFAULT_MODEL,
    _CaseDraftRecordingBackend,
    _RecordingBackend,
    _ScienceCardRecordingBackend,
    _api_key,
    _freeze_runtime_config,
    _write_json,
)
from role_benchmark import (
    BenchmarkTrack,
    Episode,
    GenerationConfig,
    Hypothesis,
    HypothesisPortfolio,
    PlayerAction,
    TextGenerationBackend,
)
from role_benchmark.cases.matched import truth_submission
from role_benchmark.wire import canonical_json_dumps
from role_benchmark.temporal import (
    CaseDraftError,
    RETRYABLE_CASE_DRAFT_ERROR_CODES,
    ScienceCardError,
    WarmupContractError,
    assess_family_source_closure,
    assess_paper_eligibility,
    author_case_draft,
    case_draft_batch_to_payload,
    condition_partition_bindings_to_payload,
    filter_candidate,
    family_review_request_payload,
    load_latex,
    load_source_packet,
    normalize_latex,
    normalize_source_packet,
    parse_case_draft_batch_json,
    parse_family_source_review_json,
    parse_science_card_json,
    public_prose_normalizations_to_payload,
    relationship_direction_bindings_to_payload,
    parse_science_card_payload,
    parse_source_review_json,
    parse_warmup_cohort_json,
    prefilter_papers,
    render_candidate_module,
    review_request_payload,
    science_card_to_payload,
    validate_case_draft_batch,
    validate_acquisition_cohort_handoff,
    validate_science_card_lineage,
    write_candidate_module,
    extract_science_card,
)


DEFAULT_MAX_OUTPUT_TOKENS = 32768
EXIT_ACCEPTED = 0
EXIT_FAILED = 2
EXIT_AWAITING_REVIEW = 3
EXIT_AWAITING_DISPOSITION = 4
EXIT_EXHAUSTED = 5
EXIT_CARD_REVISION_REQUIRED = 6


class ProviderStageFailure(RuntimeError):
    """A no-retry provider call failed before producing a stage artifact."""


def _same_json(left: Any, right: Any) -> bool:
    """Compare two JSON trees exactly without serializing the whole value.

    Mapping order is irrelevant and tuples are treated as JSON arrays, matching
    the prior canonical-serialization behavior. Scalar Python types remain
    distinct, so ``True``, ``1``, and ``1.0`` cannot compare equal. The
    iterative walk also avoids both the wire codec's message-size node limit
    and Python recursion limits for large frozen acquisition records.
    """

    pending = [(left, right)]
    while pending:
        left_value, right_value = pending.pop()

        if isinstance(left_value, Mapping):
            if not isinstance(right_value, Mapping):
                return False
            left_keys = tuple(left_value.keys())
            right_keys = tuple(right_value.keys())
            if any(type(key) is not str for key in left_keys + right_keys):
                return False
            if len(left_keys) != len(right_keys) or set(left_keys) != set(
                right_keys
            ):
                return False
            pending.extend(
                (left_value[key], right_value[key]) for key in left_keys
            )
            continue

        if isinstance(left_value, (list, tuple)):
            if not isinstance(right_value, (list, tuple)):
                return False
            if len(left_value) != len(right_value):
                return False
            pending.extend(zip(left_value, right_value))
            continue

        if type(left_value) is not type(right_value):
            return False
        if left_value != right_value:
            return False
        if type(left_value) not in {type(None), bool, int, float, str}:
            return False

        # JSON serialization distinguishes the two signed representations of
        # zero. Preserve that immutability property without importing a codec.
        if type(left_value) is float and left_value == 0.0:
            if str(left_value) != str(right_value):
                return False

    return True


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Process a frozen paper cohort in order and stop after the requested "
            "number of independently reviewed, filtered, rendered, and four-cell "
            "validated cases. This coordinator is the sole acceptance authority."
        ),
        epilog=(
            "A card_revision_required source verdict stops the frozen run. "
            "Create a new output directory for the revised ScienceCard, or "
            "explicitly defer that recorded paper and continue this cohort."
        ),
    )
    parser.add_argument("cohort")
    parser.add_argument("output_directory")
    parser.add_argument(
        "--target-accepted",
        type=int,
        default=1,
        help="stop after this many accepted families (default: 1)",
    )
    parser.add_argument(
        "--reviews-directory",
        help=(
            "directory containing <paper_id>.json card reviews and "
            "<paper_id>.family.json family-closure reviews; "
            "defaults to <output_directory>/reviews"
        ),
    )
    parser.add_argument("--endpoint", default=DEFAULT_ENDPOINT)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--timeout-s", type=float, default=180.0)
    parser.add_argument(
        "--max-output-tokens", type=int, default=DEFAULT_MAX_OUTPUT_TOKENS
    )
    credential = parser.add_mutually_exclusive_group()
    credential.add_argument("--api-key", help="runtime credential; never persisted")
    credential.add_argument(
        "--api-key-stdin", action="store_true", help="read one credential line"
    )
    credential.add_argument(
        "--prompt-api-key", action="store_true", help="prompt without echo"
    )
    parser.add_argument("--api-key-env", default=DEFAULT_API_KEY_ENV)
    parser.add_argument(
        "--science-card-focus",
        help=(
            "optional source-section routing hint for a single-paper cohort; "
            "the model must still verify every fact against the frozen source packet"
        ),
    )
    parser.add_argument(
        "--science-card-review-guidance",
        help=(
            "path to the frozen source_review.json from a prior single-paper "
            "run whose decision is card_revision_required; its reviewed prior "
            "ScienceCard and projected issues are revision context, not evidence"
        ),
    )
    parser.add_argument(
        "--skip-provider-failure",
        action="append",
        default=[],
        metavar="PAPER_ID",
        help=(
            "explicitly skip a paper already recorded as provider_failed; "
            "repeat for more than one paper"
        ),
    )
    parser.add_argument(
        "--defer-card-revision",
        action="append",
        default=[],
        metavar="PAPER_ID",
        help=(
            "continue past a paper already recorded as card_revision_required; "
            "the paper must be revised in a separate run; repeat for multiple papers"
        ),
    )
    parser.add_argument(
        "--retry-draft",
        action="append",
        default=[],
        metavar="PAPER_ID",
        help=(
            "retry only the CaseDraft stage for a paper already recorded as "
            "draft_generation_failed; the frozen reviewed ScienceCard and strict "
            "source review are revalidated; repeat for multiple papers"
        ),
    )
    return parser


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError("%s must contain valid JSON" % path) from exc


def _review_guidance_payload(
    path: Path,
    *,
    paper: Any,
    normalized_source: str,
) -> Mapping[str, Any]:
    """Validate and project one prior card-revision verdict into routing data."""

    if not path.is_file():
        raise ValueError("--science-card-review-guidance must name a JSON file")
    review = parse_source_review_json(path.read_text(encoding="utf-8"))
    expected_source = {
        "citation": paper.source_citation,
        "journal_doi": paper.journal_doi,
        "arxiv_versioned_id": paper.arxiv_versioned_id,
    }
    actual_source = {
        "citation": review.source.citation,
        "journal_doi": review.source.journal_doi,
        "arxiv_versioned_id": review.source.arxiv_versioned_id,
    }
    if review.paper_id != paper.paper_id or actual_source != expected_source:
        raise ValueError(
            "science-card review guidance must identify the single cohort paper "
            "and source exactly"
        )
    if review.decision != "card_revision_required":
        raise ValueError(
            "science-card review guidance decision must be card_revision_required"
        )
    if not review.issues:
        raise ValueError("science-card review guidance must contain issues")

    try:
        reviewed_card = parse_science_card_payload(review.review_material)
        validate_science_card_lineage(
            reviewed_card, len(normalized_source.splitlines())
        )
    except ScienceCardError as exc:
        raise ValueError(
            "science-card review guidance contains invalid review_material: %s" % exc
        ) from exc
    reviewed_source = {
        "citation": reviewed_card.source.citation,
        "journal_doi": reviewed_card.source.journal_doi,
        "arxiv_versioned_id": reviewed_card.source.arxiv_versioned_id,
    }
    if reviewed_source != expected_source:
        raise ValueError(
            "science-card review guidance review_material identifies a different source"
        )

    source_line_count = len(normalized_source.splitlines())
    issues = []
    for issue in review.issues:
        line_ranges = []
        for line_range in issue.line_ranges:
            if line_range.line_end > source_line_count:
                raise ValueError(
                    "science-card review guidance line range exceeds the current "
                    "frozen source coordinate system"
                )
            line_ranges.append(
                {
                    "line_start": line_range.line_start,
                    "line_end": line_range.line_end,
                }
            )
        issues.append(
            {
                "code": issue.code,
                "detail": issue.detail,
                "line_ranges": line_ranges,
            }
        )
    return {
        "decision": review.decision,
        "issues": issues,
        "paper_id": review.paper_id,
        "previous_science_card": review.review_material,
        "source": expected_source,
    }


def _freeze_review_guidance(
    output_directory: Path,
    payload: Mapping[str, Any],
) -> None:
    path = output_directory / "science_card_review_guidance.json"
    if path.exists():
        if not _same_json(_read_json(path), payload):
            raise ValueError(
                "the review guidance differs from this output directory's frozen guidance"
            )
    else:
        _write_json(path, payload)


def _paper_result(
    paper_directory: Path,
    paper_id: str,
    status: str,
    **details: Any,
) -> Mapping[str, Any]:
    payload = {"paper_id": paper_id, "status": status, **details}
    _write_json(paper_directory / "result.json", payload)
    return payload


def _run_result(
    output_directory: Path,
    *,
    status: str,
    papers: Sequence[Mapping[str, Any]],
    accepted_cases: Sequence[Mapping[str, Any]] = (),
    target_accepted: int = 1,
    awaiting_review_for: Optional[str] = None,
    awaiting_disposition_for: Optional[str] = None,
    failure: Optional[Mapping[str, Any]] = None,
) -> Mapping[str, Any]:
    accepted = list(accepted_cases)
    payload = {
        # Keep the singular field as the last accepted case for consumers of
        # the original one-case coordinator result.
        "accepted_case": accepted[-1] if accepted else None,
        "accepted_cases": accepted,
        "accepted_count": len(accepted),
        "awaiting_disposition_for": awaiting_disposition_for,
        "awaiting_review_for": awaiting_review_for,
        "paper_results": list(papers),
        "processed_count": len(papers),
        "status": status,
        "target_accepted": target_accepted,
        "target_reached": len(accepted) >= target_accepted,
    }
    if failure is not None:
        payload["failure"] = failure
    _write_json(output_directory / "result.json", payload)
    return payload


def _filter_payload(candidate: Any, filtered: Any) -> Mapping[str, Any]:
    return {
        "eligible": filtered.eligible,
        "family": candidate.family,
        "issues": [
            {"code": item.code, "message": item.message, "path": item.path}
            for item in filtered.issues
        ],
    }


def _issue_payload(issue: Any) -> Mapping[str, Any]:
    return {
        "code": issue.code,
        "detail": issue.detail,
        "line_ranges": [
            {"line_start": item.line_start, "line_end": item.line_end}
            for item in issue.line_ranges
        ],
    }


def _paper_eligibility_payload(card: Any, eligibility: Any) -> Mapping[str, Any]:
    return {
        "card_case_authoring_ready_hint": card.case_authoring_ready,
        "decision_authority": "independent_source_review",
        "eligible_for_drafting": eligibility.eligible_for_drafting,
        "issues": [_issue_payload(item) for item in eligibility.issues],
        "primary_disposition": eligibility.primary_disposition,
    }


def _assert_clean_unfinished_stage(directory: Path, completed: Path) -> None:
    if completed.exists():
        return
    artifacts = [directory / "request.json", directory / "response.json"]
    if any(path.exists() for path in artifacts):
        raise ProviderStageFailure(
            "unfinished model stage already has request/response artifacts; "
            "refusing an automatic retry"
        )


def _frozen_source_path(
    frozen_directory: Path,
    index: int,
    paper_id: str,
    *,
    source_format: str,
) -> Path:
    suffix = ".txt" if source_format == "source_packet" else ".tex"
    return frozen_directory / ("%02d_%s%s" % (index, paper_id, suffix))


def _freeze_all_sources(cohort: Any, output_directory: Path) -> Mapping[str, str]:
    """Snapshot every cohort source input before processing the first paper."""

    frozen_directory = output_directory / "frozen_sources"
    expected = [
        (
            paper.paper_id,
            _frozen_source_path(
                frozen_directory,
                index,
                paper.paper_id,
                source_format=(
                    "source_packet"
                    if paper.source_packet_path is not None
                    else "latex"
                ),
            ),
            paper,
        )
        for index, paper in enumerate(cohort.papers, start=1)
    ]
    if frozen_directory.exists():
        missing = [str(path) for _, path, _ in expected if not path.is_file()]
        if missing:
            raise RuntimeError(
                "frozen source snapshot is incomplete; start a new run directory"
            )
        return {
            paper_id: (
                load_source_packet(path)
                if paper.source_packet_path is not None
                else load_latex(path)
            )
            for paper_id, path, paper in expected
        }

    # Read every source before writing any snapshot so a bad cohort input cannot
    # leave a seemingly complete partial freeze.
    raw_sources = {}
    normalized = {}
    for paper_id, _, paper in expected:
        source_path = Path(paper.source_packet_path or paper.tex_path)
        raw = source_path.read_text(encoding="utf-8")
        raw_sources[paper_id] = raw
        if paper.source_packet_path is not None:
            normalized[paper_id] = normalize_source_packet(raw)
        else:
            if source_path.suffix.lower() != ".tex":
                raise ValueError("temporal source must be one .tex file")
            normalized[paper_id] = normalize_latex(raw)
    frozen_directory.mkdir()
    for paper_id, path, _ in expected:
        path.write_text(raw_sources[paper_id], encoding="utf-8")
    return normalized


def _recorded_provider_failure(result: Mapping[str, Any]) -> bool:
    if result.get("status") == "provider_failed":
        return True
    # Read the pre-disposition artifact shape emitted by the earlier runner.
    failure = result.get("failure")
    return bool(
        result.get("status") == "run_failed"
        and isinstance(failure, Mapping)
        and failure.get("stage") in {"science_card", "case_draft"}
        and failure.get("error_type") in {"RuntimeError", "ProviderStageFailure"}
    )


def _validation_payload(namespace: Mapping[str, Any], family: str) -> Mapping[str, Any]:
    factory_name = "make_%s_case" % family
    spec_name = family.upper() + "_SPEC"
    factory = namespace.get(factory_name)
    spec = namespace.get(spec_name)
    if not callable(factory):
        raise RuntimeError("rendered case does not expose %s" % factory_name)
    if spec is None:
        raise RuntimeError("rendered case does not expose %s" % spec_name)

    cells = []
    for world in ("historical", "counterfactual"):
        for track in (
            BenchmarkTrack.IDENTIFICATION,
            BenchmarkTrack.DISCOVERY,
        ):
            case = factory(world, track)
            submission = truth_submission(spec, world, track)
            portfolio = HypothesisPortfolio(
                (
                    Hypothesis(
                        hypothesis_id="H1",
                        statement="Known-truth temporal case canary.",
                        confidence=1.0,
                    ),
                )
            )
            episode = Episode(case)
            episode.apply(PlayerAction.submit_final(portfolio, submission))
            outcome = episode.outcome
            passed = bool(
                outcome.active_pass
                and outcome.protocol_completed
                and outcome.evaluation.success
                and outcome.evaluation.scores.get("predictive_model_pass") == 1.0
            )
            cells.append(
                {
                    "active_pass": bool(outcome.active_pass),
                    "evaluation_success": bool(outcome.evaluation.success),
                    "protocol_completed": bool(outcome.protocol_completed),
                    "track": track.value,
                    "truth_passes": passed,
                    "world": world,
                }
            )
    if not all(item["truth_passes"] for item in cells):
        raise RuntimeError(
            "rendered case failed the four-cell episode/evaluator canary"
        )
    return {"all_pass": True, "cells": cells}


def _persist_validation(case_path: Path, validation: Mapping[str, Any]) -> Path:
    validation_path = case_path.with_suffix(".validation.json")
    if validation_path.exists():
        if not _same_json(_read_json(validation_path), validation):
            raise RuntimeError("existing case validation differs from the canary")
    else:
        _write_json(validation_path, validation)
    return validation_path


def _load_recorded_card(path: Path, normalized_source: str, paper: Any) -> Any:
    card = parse_science_card_json(path.read_text(encoding="utf-8"))
    identity = (
        card.source.citation,
        card.source.journal_doi,
        card.source.arxiv_versioned_id,
    )
    expected = (
        paper.source_citation,
        paper.journal_doi,
        paper.arxiv_versioned_id,
    )
    if identity != expected:
        raise WarmupContractError(
            "warmup.card_identity",
            "$.source",
            "recorded science card does not identify the current paper",
        )
    validate_science_card_lineage(card, len(normalized_source.splitlines()))
    return card


def _validate_draft_retry(
    *,
    paper: Any,
    paper_directory: Path,
    reviews_directory: Path,
    normalized_source: str,
) -> Mapping[str, Any]:
    """Revalidate every frozen gate before allowing one explicit draft retry."""

    result_path = paper_directory / "result.json"
    recorded = _read_json(result_path) if result_path.is_file() else {}
    if (
        not isinstance(recorded, Mapping)
        or set(recorded) != {"failure", "paper_id", "status"}
        or recorded.get("paper_id") != paper.paper_id
        or recorded.get("status") != "draft_generation_failed"
    ):
        raise ValueError(
            "--retry-draft requires an existing immutable "
            "draft_generation_failed result for %s" % paper.paper_id
        )

    original_failure_path = paper_directory / "case_draft" / "failure.json"
    if not original_failure_path.is_file():
        raise ValueError(
            "--retry-draft requires the recorded CaseDraft failure for %s"
            % paper.paper_id
        )
    original_failure = _read_json(original_failure_path)
    if not _same_json(recorded.get("failure"), original_failure):
        raise RuntimeError(
            "recorded draft_generation_failed result changed for %s"
            % paper.paper_id
        )
    if (
        original_failure.get("error_type") != "CaseDraftError"
        or original_failure.get("stage") != "case_draft"
        or original_failure.get("status") != "generation_failed"
    ):
        raise ValueError(
            "--retry-draft requires a strict CaseDraft artifact/schema failure "
            "for %s" % paper.paper_id
        )
    retry_code = original_failure.get("error_code")
    retry_path = original_failure.get("error_path")
    retry_detail = original_failure.get("error_detail")
    if retry_code not in RETRYABLE_CASE_DRAFT_ERROR_CODES:
        raise ValueError(
            "--retry-draft permits only deterministic schema, public-lineage, "
            "or public-leakage failures for %s" % paper.paper_id
        )
    if not all(
        isinstance(value, str) and value.strip()
        for value in (retry_code, retry_path, retry_detail)
    ):
        raise ValueError(
            "--retry-draft requires complete error code/path/detail for %s"
            % paper.paper_id
        )
    retry_error = CaseDraftError(retry_code, retry_path, retry_detail)
    if original_failure.get("error") != str(retry_error):
        raise RuntimeError(
            "recorded CaseDraft failure diagnostic changed for %s"
            % paper.paper_id
        )
    if (paper_directory / "draft.json").exists():
        raise RuntimeError(
            "a failed CaseDraft result cannot already contain draft.json for %s"
            % paper.paper_id
        )
    if (paper_directory / "case_draft" / "retry").exists():
        raise ValueError(
            "--retry-draft has already been attempted for %s" % paper.paper_id
        )

    science_card_path = paper_directory / "science_card.json"
    reviewed_card_path = paper_directory / "reviewed_science_card.json"
    eligibility_path = paper_directory / "paper_eligibility.json"
    review_copy_path = paper_directory / "source_review.json"
    current_review_path = reviews_directory / (paper.paper_id + ".json")
    required_paths = (
        science_card_path,
        reviewed_card_path,
        eligibility_path,
        review_copy_path,
        current_review_path,
    )
    if not all(path.is_file() for path in required_paths):
        raise ValueError(
            "--retry-draft requires the frozen reviewed ScienceCard, source review, "
            "and paper eligibility for %s" % paper.paper_id
        )
    review_text = review_copy_path.read_text(encoding="utf-8")
    if current_review_path.read_text(encoding="utf-8") != review_text:
        raise RuntimeError("source review changed after it was consumed")

    card = _load_recorded_card(science_card_path, normalized_source, paper)
    review = parse_source_review_json(review_text)
    eligibility = assess_paper_eligibility(
        card,
        review,
        paper_id=paper.paper_id,
    )
    if not eligibility.eligible_for_drafting or eligibility.reviewed_card is None:
        raise ValueError(
            "--retry-draft requires a still-eligible strict source review for %s"
            % paper.paper_id
        )
    if eligibility.selected_cluster is None:
        raise RuntimeError("eligible review did not preserve its branch partition")

    expected_eligibility = _paper_eligibility_payload(card, eligibility)
    if not _same_json(_read_json(eligibility_path), expected_eligibility):
        raise RuntimeError(
            "recorded paper eligibility changed for %s" % paper.paper_id
        )
    reviewed_card = _load_recorded_card(
        reviewed_card_path,
        normalized_source,
        paper,
    )
    expected_reviewed_card = science_card_to_payload(eligibility.reviewed_card)
    if not _same_json(
        science_card_to_payload(reviewed_card),
        expected_reviewed_card,
    ):
        raise RuntimeError(
            "recorded reviewed ScienceCard changed for %s" % paper.paper_id
        )
    return {
        "original_failure": original_failure,
        "retry_error": retry_error,
    }


def _draft_retry_reference(
    *,
    attempt_count: int,
    failed: bool = False,
) -> Mapping[str, Any]:
    retry = {
        "attempt_count": attempt_count,
        "attempts_directory": "case_draft/retry",
        "disposition": "explicit_draft_retry",
        "original_failure_path": "case_draft/failure.json",
    }
    if failed:
        retry["failure_path"] = "case_draft/retry/failure.json"
    else:
        retry["draft_path"] = "draft.json"
    return retry


def _persist_rendered_candidate(candidate: Any, output: Path) -> Path:
    expected = render_candidate_module(candidate)
    if output.exists():
        if output.read_text(encoding="utf-8") != expected:
            raise RuntimeError("existing rendered case differs from the accepted draft")
        path = output
        validation = _validation_payload(runpy.run_path(str(path)), candidate.family)
    else:
        output.parent.mkdir(parents=True, exist_ok=True)
        handle = tempfile.NamedTemporaryFile(
            dir=str(output.parent),
            prefix=".%s.canary." % output.stem,
            suffix=".py",
            delete=False,
        )
        handle.close()
        canary_path = Path(handle.name)
        try:
            write_candidate_module(candidate, canary_path)
            validation = _validation_payload(
                runpy.run_path(str(canary_path)), candidate.family
            )
        finally:
            canary_path.unlink(missing_ok=True)
        path = write_candidate_module(candidate, output)
    _persist_validation(path, validation)
    return path


def run(
    args: argparse.Namespace,
    *,
    backend: Optional[TextGenerationBackend] = None,
) -> int:
    cohort_path = Path(args.cohort).resolve()
    output_directory = Path(args.output_directory)
    output_directory.mkdir(parents=True, exist_ok=True)
    papers_directory = output_directory / "papers"
    papers_directory.mkdir(exist_ok=True)
    reviews_directory = (
        Path(args.reviews_directory)
        if args.reviews_directory
        else output_directory / "reviews"
    )
    reviews_directory.mkdir(parents=True, exist_ok=True)
    stage = "cohort"
    paper_directory = output_directory
    current_paper_id: Optional[str] = None
    paper_results = []
    accepted_cases = []
    target_accepted = getattr(args, "target_accepted", 1)
    try:
        if (
            isinstance(target_accepted, bool)
            or not isinstance(target_accepted, int)
            or target_accepted < 1
        ):
            raise ValueError("--target-accepted must be a positive integer")
        cohort_text = cohort_path.read_text(encoding="utf-8")
        cohort_payload = _read_json(cohort_path)
        acquisition_path = cohort_path.with_name("acquisition.json")
        if not acquisition_path.is_file():
            raise WarmupContractError(
                "warmup.acquisition_required",
                "$.provenance",
                "cohort must be accompanied by acquisition.json",
            )
        acquisition_payload = _read_json(acquisition_path)
        validate_acquisition_cohort_handoff(cohort_payload, acquisition_payload)
        cohort = parse_warmup_cohort_json(
            cohort_text, base_directory=cohort_path.parent
        )
        science_card_focus = getattr(args, "science_card_focus", None)
        if science_card_focus is not None:
            if not isinstance(science_card_focus, str) or not science_card_focus.strip():
                raise ValueError("--science-card-focus must be non-empty text")
            if len(cohort.papers) != 1:
                raise ValueError(
                    "--science-card-focus requires a single-paper cohort"
                )
        review_guidance_path = getattr(args, "science_card_review_guidance", None)
        review_guidance = None
        if review_guidance_path is not None:
            if (
                not isinstance(review_guidance_path, str)
                or not review_guidance_path.strip()
            ):
                raise ValueError(
                    "--science-card-review-guidance must be a non-empty path"
                )
            if len(cohort.papers) != 1:
                raise ValueError(
                    "--science-card-review-guidance requires a single-paper cohort"
                )
            guidance_paper = cohort.papers[0]
            if guidance_paper.source_packet_path is not None:
                current_source = load_source_packet(guidance_paper.source_packet_path)
            else:
                current_source = load_latex(guidance_paper.tex_path)
            review_guidance = _review_guidance_payload(
                Path(review_guidance_path),
                paper=guidance_paper,
                normalized_source=current_source,
            )
        frozen_path = output_directory / "frozen_cohort.json"
        if frozen_path.exists():
            if not _same_json(_read_json(frozen_path), cohort_payload):
                raise ValueError(
                    "the input cohort differs from this output directory's frozen cohort"
                )
        else:
            _write_json(frozen_path, cohort_payload)
        frozen_acquisition_path = output_directory / "frozen_acquisition.json"
        if frozen_acquisition_path.exists():
            if not _same_json(
                _read_json(frozen_acquisition_path), acquisition_payload
            ):
                raise ValueError(
                    "the acquisition record differs from this output directory's "
                    "frozen acquisition record"
                )
        else:
            _write_json(frozen_acquisition_path, acquisition_payload)

        _freeze_runtime_config(
            output_directory,
            args,
            runner="temporal_warmup",
            additions=(
                {"science_card_review_guidance": review_guidance}
                if review_guidance is not None
                else None
            ),
        )
        if review_guidance is not None:
            _freeze_review_guidance(output_directory, review_guidance)
        stage = "source_freeze"
        frozen_sources = _freeze_all_sources(cohort, output_directory)

        skip_provider_failures = set(args.skip_provider_failure or ())
        paper_ids = {paper.paper_id for paper in cohort.papers}
        unknown_skip_ids = skip_provider_failures - paper_ids
        if unknown_skip_ids:
            raise ValueError(
                "--skip-provider-failure names unknown paper(s): %s"
                % ", ".join(sorted(unknown_skip_ids))
            )
        for index, paper in enumerate(cohort.papers, start=1):
            if paper.paper_id not in skip_provider_failures:
                continue
            recorded_path = papers_directory / (
                "%02d_%s" % (index, paper.paper_id)
            ) / "result.json"
            recorded = _read_json(recorded_path) if recorded_path.exists() else {}
            if not (
                _recorded_provider_failure(recorded)
                or recorded.get("status") == "provider_failure_skipped"
            ):
                raise ValueError(
                    "--skip-provider-failure requires an existing provider failure "
                    "for %s" % paper.paper_id
                )

        stage = "revision_disposition"
        deferred_card_revisions = set(
            getattr(args, "defer_card_revision", None) or ()
        )
        unknown_revision_ids = deferred_card_revisions - paper_ids
        if unknown_revision_ids:
            raise ValueError(
                "--defer-card-revision names unknown paper(s): %s"
                % ", ".join(sorted(unknown_revision_ids))
            )
        revision_dispositions = {}
        for index, paper in enumerate(cohort.papers, start=1):
            if paper.paper_id not in deferred_card_revisions:
                continue
            recorded_directory = papers_directory / (
                "%02d_%s" % (index, paper.paper_id)
            )
            recorded_result_path = recorded_directory / "result.json"
            recorded = (
                _read_json(recorded_result_path)
                if recorded_result_path.exists()
                else {}
            )
            if recorded.get("status") not in {
                "card_revision_required",
                "card_revision_deferred",
            }:
                raise ValueError(
                    "--defer-card-revision requires an existing "
                    "card_revision_required verdict for %s" % paper.paper_id
                )
            if (
                recorded.get("status") == "card_revision_deferred"
                and recorded.get("disposition") != "explicit_separate_revision"
            ):
                raise ValueError(
                    "recorded card revision disposition is invalid for %s"
                    % paper.paper_id
                )

            review_copy = recorded_directory / "source_review.json"
            current_review = reviews_directory / (paper.paper_id + ".json")
            card_path = recorded_directory / "science_card.json"
            if not review_copy.is_file() or not current_review.is_file():
                raise ValueError(
                    "--defer-card-revision requires the existing strict source "
                    "review for %s" % paper.paper_id
                )
            review_text = review_copy.read_text(encoding="utf-8")
            if current_review.read_text(encoding="utf-8") != review_text:
                raise RuntimeError("source review changed after it was consumed")
            if not card_path.is_file():
                raise ValueError(
                    "--defer-card-revision requires the reviewed ScienceCard for %s"
                    % paper.paper_id
                )
            card = _load_recorded_card(
                card_path,
                frozen_sources[paper.paper_id],
                paper,
            )
            review = parse_source_review_json(review_text)
            eligibility = assess_paper_eligibility(
                card,
                review,
                paper_id=paper.paper_id,
            )
            if (
                eligibility.eligible_for_drafting
                or eligibility.primary_disposition != "card_revision_required"
            ):
                raise ValueError(
                    "--defer-card-revision requires a strict "
                    "card_revision_required review for %s" % paper.paper_id
                )
            eligibility_payload = _paper_eligibility_payload(card, eligibility)
            if not _same_json(recorded.get("eligibility"), eligibility_payload):
                raise RuntimeError(
                    "recorded card_revision_required eligibility changed for %s"
                    % paper.paper_id
                )
            revision_dispositions[paper.paper_id] = {
                "eligibility": eligibility_payload,
                "revision_review": {
                    "decision": "card_revision_required",
                    "issues": eligibility_payload["issues"],
                    "path": str(review_copy),
                },
            }

        stage = "draft_retry_disposition"
        retry_draft_ids = set(getattr(args, "retry_draft", None) or ())
        unknown_retry_ids = retry_draft_ids - paper_ids
        if unknown_retry_ids:
            raise ValueError(
                "--retry-draft names unknown paper(s): %s"
                % ", ".join(sorted(unknown_retry_ids))
            )
        draft_retries = {}
        for index, paper in enumerate(cohort.papers, start=1):
            if paper.paper_id not in retry_draft_ids:
                continue
            retry_paper_directory = papers_directory / (
                "%02d_%s" % (index, paper.paper_id)
            )
            draft_retries[paper.paper_id] = _validate_draft_retry(
                paper=paper,
                paper_directory=retry_paper_directory,
                reviews_directory=reviews_directory,
                normalized_source=frozen_sources[paper.paper_id],
            )

        provider: Optional[TextGenerationBackend] = backend

        def model_backend() -> TextGenerationBackend:
            nonlocal provider
            if provider is None:
                provider = DeepSeekChatBackend(
                    endpoint=args.endpoint,
                    api_key=_api_key(args),
                    model=args.model,
                    thinking="disabled",
                    reasoning_effort=None,
                    timeout_s=args.timeout_s,
                )
            return provider

        config = GenerationConfig(
            max_output_tokens=args.max_output_tokens,
            temperature=0.0,
            top_p=1.0,
        )

        for index, paper in enumerate(cohort.papers, start=1):
            current_paper_id = paper.paper_id
            paper_directory = papers_directory / ("%02d_%s" % (index, paper.paper_id))
            paper_directory.mkdir(exist_ok=True)
            previous_result_path = paper_directory / "result.json"
            if previous_result_path.exists():
                previous = _read_json(previous_result_path)
                if (
                    previous.get("status") == "card_revision_required"
                    and paper.paper_id in revision_dispositions
                ):
                    disposition = revision_dispositions[paper.paper_id]
                    deferred = _paper_result(
                        paper_directory,
                        paper.paper_id,
                        "card_revision_deferred",
                        disposition="explicit_separate_revision",
                        eligibility=disposition["eligibility"],
                        revision_review=disposition["revision_review"],
                    )
                    paper_results.append(deferred)
                    continue
                if _recorded_provider_failure(previous):
                    if paper.paper_id in skip_provider_failures:
                        skipped = _paper_result(
                            paper_directory,
                            paper.paper_id,
                            "provider_failure_skipped",
                            disposition="explicit_human_skip",
                            original_failure=previous.get("failure"),
                        )
                        paper_results.append(skipped)
                        continue
                    paper_results.append(previous)
                    report = _run_result(
                        output_directory,
                        status="awaiting_provider_failure_disposition",
                        papers=paper_results,
                        accepted_cases=accepted_cases,
                        target_accepted=target_accepted,
                        awaiting_disposition_for=paper.paper_id,
                        failure=previous.get("failure"),
                    )
                    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
                    return EXIT_AWAITING_DISPOSITION
                if previous.get("status") in {
                    "metadata_ineligible",
                    "science_card_generation_failed",
                    "source_review_rejected",
                    "draft_retry_failed",
                    "draft_not_authorable",
                    "candidate_rejected",
                    "family_source_closure_rejected",
                    "provider_failure_skipped",
                    "card_revision_deferred",
                }:
                    paper_results.append(previous)
                    continue
                if (
                    previous.get("status") == "draft_generation_failed"
                    and paper.paper_id not in draft_retries
                ):
                    paper_results.append(previous)
                    continue

            stage = "metadata_precheck"
            precheck = prefilter_papers(
                (paper.source_paper,),
                start=cohort.start,
                end=cohort.end,
                earliest_public_not_before=cohort.earliest_public_not_before,
            )
            reasons = list(precheck.rejected.get(paper.journal_doi, ()))
            precheck_payload = {
                "eligible": not reasons,
                "paper_id": paper.paper_id,
                "reasons": reasons,
            }
            _write_json(paper_directory / "metadata_precheck.json", precheck_payload)
            if reasons:
                result = _paper_result(
                    paper_directory,
                    paper.paper_id,
                    "metadata_ineligible",
                    reasons=reasons,
                )
                paper_results.append(result)
                continue

            stage = "source_normalization"
            normalized_source = frozen_sources[paper.paper_id]
            source_format = (
                "source_packet"
                if paper.source_packet_path is not None
                else "latex"
            )
            normalized_path = paper_directory / (
                "normalized_source.txt"
                if source_format == "source_packet"
                else "normalized_source.tex"
            )
            if normalized_path.exists():
                if normalized_path.read_text(encoding="utf-8") != normalized_source:
                    raise RuntimeError("source packet changed after this warm-up began")
            else:
                normalized_path.write_text(normalized_source, encoding="utf-8")

            stage = "science_card"
            science_card_path = paper_directory / "science_card.json"
            science_card_stage = paper_directory / "science_card"
            science_card_stage.mkdir(exist_ok=True)
            standalone_card_path = science_card_stage / "science_card.json"
            standalone_failure_path = science_card_stage / "failure.json"
            if science_card_path.exists():
                card = _load_recorded_card(
                    science_card_path, normalized_source, paper
                )
            elif standalone_card_path.exists():
                card = _load_recorded_card(
                    standalone_card_path, normalized_source, paper
                )
                _write_json(science_card_path, science_card_to_payload(card))
            elif standalone_failure_path.exists():
                failure = _read_json(standalone_failure_path)
                if failure.get("error_type") != "ScienceCardError":
                    raise RuntimeError(
                        "recorded standalone science-card failure was not an "
                        "artifact/schema failure"
                    )
                result = _paper_result(
                    paper_directory,
                    paper.paper_id,
                    "science_card_generation_failed",
                    failure=failure,
                )
                paper_results.append(result)
                continue
            else:
                _assert_clean_unfinished_stage(science_card_stage, science_card_path)
                recording_backend = _ScienceCardRecordingBackend(
                    model_backend(), science_card_stage
                )
                try:
                    card_result = extract_science_card(
                        recording_backend,
                        normalized_source,
                        source_citation=paper.source_citation,
                        journal_doi=paper.journal_doi,
                        arxiv_versioned_id=paper.arxiv_versioned_id,
                        authoring_focus=science_card_focus,
                        previous_science_card=(
                            review_guidance["previous_science_card"]
                            if review_guidance is not None
                            else None
                        ),
                        review_guidance_issues=(
                            review_guidance["issues"]
                            if review_guidance is not None
                            else None
                        ),
                        config=config,
                        max_total_attempts=4,
                        source_format=source_format,
                    )
                except ScienceCardError as exc:
                    failure = {
                        "attempt_count": recording_backend.attempt_count,
                        "error": str(exc),
                        "error_code": exc.code,
                        "error_detail": exc.detail,
                        "error_path": exc.path,
                        "error_type": type(exc).__name__,
                        "stage": "science_card",
                        "status": "generation_failed",
                    }
                    _write_json(science_card_stage / "failure.json", failure)
                    result = _paper_result(
                        paper_directory,
                        paper.paper_id,
                        "science_card_generation_failed",
                        failure=failure,
                    )
                    paper_results.append(result)
                    continue
                except RuntimeError as exc:
                    raise ProviderStageFailure(str(exc)) from exc
                card = card_result.card
                _write_json(
                    science_card_stage / "attempts.json",
                    {"attempt_count": card_result.attempt_count},
                )
                _write_json(science_card_path, science_card_to_payload(card))
            _write_json(
                paper_directory / "review_request.json",
                review_request_payload(card, paper_id=paper.paper_id),
            )

            stage = "source_review"
            review_path = reviews_directory / (paper.paper_id + ".json")
            if not review_path.exists():
                result = _paper_result(
                    paper_directory,
                    paper.paper_id,
                    "awaiting_source_review",
                    card_case_authoring_ready_hint=card.case_authoring_ready,
                    review_path=str(review_path),
                )
                paper_results.append(result)
                report = _run_result(
                    output_directory,
                    status="awaiting_source_review",
                    papers=paper_results,
                    accepted_cases=accepted_cases,
                    target_accepted=target_accepted,
                    awaiting_review_for=paper.paper_id,
                )
                print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
                return EXIT_AWAITING_REVIEW

            review_text = review_path.read_text(encoding="utf-8")
            review = parse_source_review_json(review_text)
            eligibility = assess_paper_eligibility(
                card, review, paper_id=paper.paper_id
            )
            review_copy = paper_directory / "source_review.json"
            if review_copy.exists() and review_copy.read_text(encoding="utf-8") != review_text:
                raise RuntimeError("source review changed after it was consumed")
            if not review_copy.exists():
                review_copy.write_text(review_text, encoding="utf-8")
            eligibility_payload = _paper_eligibility_payload(card, eligibility)
            paper_eligibility_path = paper_directory / "paper_eligibility.json"
            if paper_eligibility_path.exists():
                if not _same_json(
                    _read_json(paper_eligibility_path), eligibility_payload
                ):
                    raise RuntimeError("paper eligibility changed on resume")
            else:
                _write_json(paper_eligibility_path, eligibility_payload)
            if not eligibility.eligible_for_drafting:
                if eligibility.primary_disposition == "card_revision_required":
                    result = _paper_result(
                        paper_directory,
                        paper.paper_id,
                        "card_revision_required",
                        eligibility=eligibility_payload,
                    )
                    paper_results.append(result)
                    report = _run_result(
                        output_directory,
                        status="card_revision_required",
                        papers=paper_results,
                        accepted_cases=accepted_cases,
                        target_accepted=target_accepted,
                    )
                    print(
                        json.dumps(
                            report,
                            ensure_ascii=False,
                            indent=2,
                            sort_keys=True,
                        )
                    )
                    return EXIT_CARD_REVISION_REQUIRED
                result = _paper_result(
                    paper_directory,
                    paper.paper_id,
                    "source_review_rejected",
                    eligibility=eligibility_payload,
                )
                paper_results.append(result)
                continue
            reviewed_card = eligibility.reviewed_card
            if reviewed_card is None:
                raise RuntimeError("eligible review did not produce a reviewed card")
            selected_cluster = eligibility.selected_cluster
            if selected_cluster is None:
                raise RuntimeError("eligible review did not preserve its branch partition")
            reviewed_branch_claim_ids = (
                selected_cluster.branch_a_claim_ids,
                selected_cluster.branch_b_claim_ids,
            )
            reviewed_card_path = paper_directory / "reviewed_science_card.json"
            reviewed_payload = science_card_to_payload(reviewed_card)
            if reviewed_card_path.exists():
                if not _same_json(
                    _read_json(reviewed_card_path), reviewed_payload
                ):
                    raise RuntimeError("reviewed science-card scope changed on resume")
            else:
                _write_json(reviewed_card_path, reviewed_payload)

            stage = "case_draft"
            draft_path = paper_directory / "draft.json"
            initial_draft_stage = paper_directory / "case_draft"
            retrying_draft = paper.paper_id in draft_retries
            draft_stage = (
                initial_draft_stage / "retry"
                if retrying_draft
                else initial_draft_stage
            )
            draft_stage.mkdir(exist_ok=True)
            _assert_clean_unfinished_stage(draft_stage, draft_path)
            if draft_path.exists():
                batch = parse_case_draft_batch_json(
                    draft_path.read_text(encoding="utf-8")
                )
                validate_case_draft_batch(
                    batch,
                    reviewed_card,
                    strict_source_only=True,
                    reviewed_branch_claim_ids=reviewed_branch_claim_ids,
                )
            else:
                recording_backend = _CaseDraftRecordingBackend(
                    model_backend(), draft_stage
                )
                try:
                    draft_result = author_case_draft(
                        recording_backend,
                        reviewed_card,
                        config=config,
                        strict_source_only=True,
                        reviewed_branch_claim_ids=reviewed_branch_claim_ids,
                        max_total_attempts=4,
                        retry_artifact_error=(
                            draft_retries[paper.paper_id]["retry_error"]
                            if retrying_draft
                            else None
                        ),
                    )
                except CaseDraftError as exc:
                    failure = {
                        "attempt_count": recording_backend.attempt_count,
                        "error": str(exc),
                        "error_code": exc.code,
                        "error_detail": exc.detail,
                        "error_path": exc.path,
                        "error_type": type(exc).__name__,
                        "stage": "case_draft",
                        "status": "generation_failed",
                    }
                    _write_json(draft_stage / "failure.json", failure)
                    if retrying_draft:
                        original_failure = draft_retries[paper.paper_id][
                            "original_failure"
                        ]
                        result = _paper_result(
                            paper_directory,
                            paper.paper_id,
                            "draft_retry_failed",
                            draft_retry=_draft_retry_reference(
                                attempt_count=recording_backend.attempt_count,
                                failed=True,
                            ),
                            failure=failure,
                            original_failure=original_failure,
                        )
                        paper_results.append(result)
                        continue
                    result = _paper_result(
                        paper_directory,
                        paper.paper_id,
                        "draft_generation_failed",
                        failure=failure,
                    )
                    paper_results.append(result)
                    continue
                except RuntimeError as exc:
                    raise ProviderStageFailure(str(exc)) from exc
                batch = draft_result.batch
                _write_json(
                    draft_stage / "attempts.json",
                    {
                        "attempt_count": getattr(
                            draft_result,
                            "attempt_count",
                            recording_backend.attempt_count,
                        )
                    },
                )
                _write_json(
                    draft_stage / "prose_normalizations.json",
                    public_prose_normalizations_to_payload(
                        getattr(draft_result, "prose_normalizations", ())
                    ),
                )
                _write_json(
                    draft_stage / "relationship_direction_bindings.json",
                    relationship_direction_bindings_to_payload(
                        getattr(
                            draft_result,
                            "relationship_direction_bindings",
                            (),
                        )
                    ),
                )
                _write_json(
                    draft_stage / "condition_partition_bindings.json",
                    condition_partition_bindings_to_payload(
                        getattr(
                            draft_result,
                            "condition_partition_bindings",
                            (),
                        )
                    ),
                )
                _write_json(draft_path, case_draft_batch_to_payload(batch))
            draft_result_details = {}
            retry_attempts_path = initial_draft_stage / "retry" / "attempts.json"
            if retry_attempts_path.is_file():
                retry_attempts = _read_json(retry_attempts_path)
                if set(retry_attempts) != {"attempt_count"}:
                    raise RuntimeError("recorded draft retry attempts are invalid")
                retry_attempt_count = retry_attempts["attempt_count"]
                if (
                    isinstance(retry_attempt_count, bool)
                    or not isinstance(retry_attempt_count, int)
                    or retry_attempt_count not in {1, 2, 3, 4}
                ):
                    raise RuntimeError("recorded draft retry attempt count is invalid")
                if not (initial_draft_stage / "failure.json").is_file():
                    raise RuntimeError("recorded draft retry has no original failure")
                draft_result_details = {
                    "draft_retry": _draft_retry_reference(
                        attempt_count=retry_attempt_count,
                    )
                }
            if batch.status == "not_authorable":
                _write_json(
                    paper_directory / "filter.json",
                    {
                        "candidate_count": 0,
                        "candidates": [],
                        "eligible_count": 0,
                        "status": "not_authorable",
                    },
                )
                result = _paper_result(
                    paper_directory,
                    paper.paper_id,
                    "draft_not_authorable",
                    assessment=batch.assessment,
                    **draft_result_details,
                )
                paper_results.append(result)
                continue

            stage = "filter"
            candidate = batch.drafts[0].candidate
            filtered = filter_candidate(candidate)
            candidate_report = _filter_payload(candidate, filtered)
            _write_json(
                paper_directory / "filter.json",
                {
                    "candidate_count": 1,
                    "candidates": [candidate_report],
                    "eligible_count": int(filtered.eligible),
                    "status": "complete" if filtered.eligible else "candidate_rejected",
                },
            )
            if not filtered.eligible:
                result = _paper_result(
                    paper_directory,
                    paper.paper_id,
                    "candidate_rejected",
                    candidate=candidate_report,
                    **draft_result_details,
                )
                paper_results.append(result)
                continue

            stage = "family_source_review"
            _write_json(
                paper_directory / "family_review_request.json",
                family_review_request_payload(
                    batch.drafts[0],
                    paper_id=paper.paper_id,
                ),
            )
            family_review_path = reviews_directory / (
                paper.paper_id + ".family.json"
            )
            if not family_review_path.exists():
                result = _paper_result(
                    paper_directory,
                    paper.paper_id,
                    "awaiting_family_review",
                    family=candidate.family,
                    review_path=str(family_review_path),
                    **draft_result_details,
                )
                paper_results.append(result)
                report = _run_result(
                    output_directory,
                    status="awaiting_family_review",
                    papers=paper_results,
                    accepted_cases=accepted_cases,
                    target_accepted=target_accepted,
                    awaiting_review_for=paper.paper_id,
                )
                print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
                return EXIT_AWAITING_REVIEW
            family_review_text = family_review_path.read_text(encoding="utf-8")
            family_review = parse_family_source_review_json(family_review_text)
            source_closed = assess_family_source_closure(
                batch.drafts[0],
                family_review,
                paper_id=paper.paper_id,
            )
            family_review_copy = paper_directory / "family_source_review.json"
            if (
                family_review_copy.exists()
                and family_review_copy.read_text(encoding="utf-8")
                != family_review_text
            ):
                raise RuntimeError("family source review changed after it was consumed")
            if not family_review_copy.exists():
                family_review_copy.write_text(family_review_text, encoding="utf-8")
            if not source_closed:
                result = _paper_result(
                    paper_directory,
                    paper.paper_id,
                    "family_source_closure_rejected",
                    family=candidate.family,
                    issues=[_issue_payload(item) for item in family_review.issues],
                    **draft_result_details,
                )
                paper_results.append(result)
                continue

            case_path = _persist_rendered_candidate(
                candidate,
                paper_directory / "cases" / (candidate.family + ".py"),
            )
            accepted_case = {
                "family": candidate.family,
                "paper_id": paper.paper_id,
                "path": str(case_path),
                "validation_path": str(case_path.with_suffix(".validation.json")),
            }
            result = _paper_result(
                paper_directory,
                paper.paper_id,
                "case_accepted",
                accepted_case=accepted_case,
                **draft_result_details,
            )
            paper_results.append(result)
            accepted_cases.append(accepted_case)
            if len(accepted_cases) >= target_accepted:
                report = _run_result(
                    output_directory,
                    status="case_accepted",
                    papers=paper_results,
                    accepted_cases=accepted_cases,
                    target_accepted=target_accepted,
                )
                print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
                return EXIT_ACCEPTED

        report = _run_result(
            output_directory,
            status="exhausted",
            papers=paper_results,
            accepted_cases=accepted_cases,
            target_accepted=target_accepted,
        )
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
        return EXIT_EXHAUSTED
    except (
        CaseDraftError,
        ScienceCardError,
        WarmupContractError,
        OSError,
        RuntimeError,
        ValueError,
    ) as exc:
        provider_failed = isinstance(exc, ProviderStageFailure)
        failure = {
            "error": str(exc),
            "error_type": type(exc).__name__,
            "stage": stage,
            "status": "provider_failed" if provider_failed else "failed",
        }
        if provider_failed:
            failure["disposition_required"] = "skip_or_new_run"
        _write_json(paper_directory / "failure.json", failure)
        _write_json(output_directory / "failure.json", failure)
        if (
            current_paper_id is not None
            and paper_directory != output_directory
            and not any(item.get("paper_id") == current_paper_id for item in paper_results)
        ):
            failed_paper = _paper_result(
                paper_directory,
                current_paper_id,
                "provider_failed" if provider_failed else "run_failed",
                failure=failure,
            )
            paper_results.append(failed_paper)
        _run_result(
            output_directory,
            status="provider_failed" if provider_failed else "failed",
            papers=paper_results,
            accepted_cases=accepted_cases,
            target_accepted=(
                target_accepted
                if isinstance(target_accepted, int) and not isinstance(target_accepted, bool)
                else 1
            ),
            awaiting_disposition_for=(
                current_paper_id if provider_failed else None
            ),
            failure=failure,
        )
        print(json.dumps(failure, ensure_ascii=False, indent=2, sort_keys=True))
        return EXIT_FAILED


def main(argv: Optional[Sequence[str]] = None) -> int:
    return run(_parser().parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
