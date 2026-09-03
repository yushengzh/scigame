"""Independent source review and admission for minimal Temporal relations."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Dict, Mapping, Optional, Tuple

from .minimal_science_card import (
    MinimalScienceCard,
    MinimalScienceCardError,
    minimal_science_card_to_payload,
    parse_minimal_science_card_payload,
    validate_minimal_science_card_lineage,
)
from .science_card import ScienceSource


TEMPORAL_ADMISSION_REVIEW_SCHEMA = "role_benchmark.temporal_admission_review.v1"
_DECISIONS = {
    "eligible_for_temporal_case",
    "card_revision_required",
    "ineligible_for_temporal_case",
}


class TemporalAdmissionError(ValueError):
    """A source-review artifact violates the Temporal admission contract."""

    def __init__(self, code: str, path: str, detail: str) -> None:
        self.code = code
        self.path = path
        self.detail = detail
        super().__init__("%s at %s: %s" % (code, path, detail))


@dataclass(frozen=True)
class AdmissionLineRange:
    line_start: int
    line_end: int


@dataclass(frozen=True)
class TemporalAdmissionIssue:
    code: str
    detail: str
    blocking: bool
    line_ranges: Tuple[AdmissionLineRange, ...]


@dataclass(frozen=True)
class TemporalAdmissionReview:
    paper_id: str
    source: ScienceSource
    review_material: Mapping[str, Any]
    reviewer: str
    decision: str
    assessment: str
    source_support_confirmed: bool
    cartesian_domain_supported: bool
    deterministic_central_value_appropriate: bool
    issues: Tuple[TemporalAdmissionIssue, ...]


@dataclass(frozen=True)
class TemporalAdmissionResult:
    admitted: bool
    disposition: str
    card: Optional[MinimalScienceCard]
    review: TemporalAdmissionReview
    paper_id: str
    source_line_count: int
    issues: Tuple[TemporalAdmissionIssue, ...]


def _error(path: str, detail: str, code: str = "temporal_admission.schema") -> None:
    raise TemporalAdmissionError(code, path, detail)


def _object(value: Any, path: str, keys: set[str]) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        _error(path, "must be an object")
    if set(value) != keys:
        _error(
            path,
            "keys must match exactly (missing=%s, extra=%s)"
            % (sorted(keys - set(value)), sorted(set(value) - keys)),
        )
    return value


def _array(value: Any, path: str) -> list[Any]:
    if not isinstance(value, list):
        _error(path, "must be an array")
    return value


def _text(value: Any, path: str) -> str:
    if not isinstance(value, str) or not value.strip():
        _error(path, "must be non-empty text")
    return value.strip()


def _source(value: Any, path: str) -> ScienceSource:
    item = _object(
        value,
        path,
        {"citation", "journal_doi", "arxiv_versioned_id"},
    )
    return ScienceSource(
        citation=_text(item["citation"], path + ".citation"),
        journal_doi=_text(item["journal_doi"], path + ".journal_doi"),
        arxiv_versioned_id=_text(
            item["arxiv_versioned_id"], path + ".arxiv_versioned_id"
        ),
    )


def parse_temporal_admission_review_payload(payload: Any) -> TemporalAdmissionReview:
    root = _object(
        payload,
        "$",
        {
            "schema",
            "paper_id",
            "source",
            "review_material",
            "reviewer",
            "decision",
            "assessment",
            "checks",
            "issues",
        },
    )
    if root["schema"] != TEMPORAL_ADMISSION_REVIEW_SCHEMA:
        _error("$.schema", "unsupported admission-review schema")
    checks = _object(
        root["checks"],
        "$.checks",
        {
            "source_support_confirmed",
            "cartesian_domain_supported",
            "deterministic_central_value_appropriate",
        },
    )
    for name, value in checks.items():
        if not isinstance(value, bool):
            _error("$.checks.%s" % name, "must be a boolean")
    decision = _text(root["decision"], "$.decision")
    if decision not in _DECISIONS:
        _error("$.decision", "unsupported source-review decision")
    if not isinstance(root["review_material"], dict):
        _error("$.review_material", "must be a minimal ScienceCard object")
    try:
        parse_minimal_science_card_payload(root["review_material"])
    except MinimalScienceCardError as exc:
        _error(
            "$.review_material",
            "contains an invalid minimal ScienceCard: %s" % exc,
            "temporal_admission.review_material",
        )

    issues = []
    for index, raw_issue in enumerate(_array(root["issues"], "$.issues")):
        path = "$.issues[%d]" % index
        item = _object(raw_issue, path, {"code", "detail", "blocking", "line_ranges"})
        if not isinstance(item["blocking"], bool):
            _error(path + ".blocking", "must be a boolean")
        line_ranges = []
        for range_index, raw_range in enumerate(
            _array(item["line_ranges"], path + ".line_ranges")
        ):
            range_path = "%s.line_ranges[%d]" % (path, range_index)
            value = _object(raw_range, range_path, {"line_start", "line_end"})
            start = value["line_start"]
            end = value["line_end"]
            if (
                isinstance(start, bool)
                or not isinstance(start, int)
                or isinstance(end, bool)
                or not isinstance(end, int)
                or start < 1
                or end < start
            ):
                _error(
                    range_path,
                    "must satisfy 1 <= line_start <= line_end",
                )
            line_ranges.append(AdmissionLineRange(start, end))
        issues.append(
            TemporalAdmissionIssue(
                code=_text(item["code"], path + ".code"),
                detail=_text(item["detail"], path + ".detail"),
                blocking=item["blocking"],
                line_ranges=tuple(line_ranges),
            )
        )
    blocking = tuple(item for item in issues if item.blocking)
    if decision == "eligible_for_temporal_case" and blocking:
        _error(
            "$.issues",
            "an eligible decision cannot contain a blocking issue",
            "temporal_admission.decision",
        )
    if decision == "eligible_for_temporal_case" and not all(checks.values()):
        _error(
            "$.checks",
            "an eligible decision requires every source-review check to pass",
            "temporal_admission.decision",
        )
    if decision != "eligible_for_temporal_case" and not blocking:
        _error(
            "$.issues",
            "a non-eligible decision requires at least one blocking issue",
            "temporal_admission.decision",
        )
    reviewer = _text(root["reviewer"], "$.reviewer")
    assessment = _text(root["assessment"], "$.assessment")
    if reviewer == "REQUIRED_INDEPENDENT_SOURCE_REVIEWER":
        _error("$.reviewer", "replace the source-reviewer placeholder")
    if assessment == "REPLACE_AFTER_CHECKING_THE_SOURCE_AND_EVERY_LINE_RANGE":
        _error("$.assessment", "replace the source-review assessment placeholder")
    return TemporalAdmissionReview(
        paper_id=_text(root["paper_id"], "$.paper_id"),
        source=_source(root["source"], "$.source"),
        review_material=root["review_material"],
        reviewer=reviewer,
        decision=decision,
        assessment=assessment,
        source_support_confirmed=checks["source_support_confirmed"],
        cartesian_domain_supported=checks["cartesian_domain_supported"],
        deterministic_central_value_appropriate=checks[
            "deterministic_central_value_appropriate"
        ],
        issues=tuple(issues),
    )


def _decode_json(text: str) -> Any:
    if not isinstance(text, str):
        _error("$", "input must be text", "temporal_admission.invalid_json")

    def reject_constant(value: str) -> None:
        raise ValueError("non-finite JSON constant %s" % value)

    def unique_object(pairs: Any) -> Dict[str, Any]:
        result: Dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate object key")
            result[key] = value
        return result

    try:
        return json.loads(
            text,
            parse_constant=reject_constant,
            object_pairs_hook=unique_object,
        )
    except (json.JSONDecodeError, ValueError) as exc:
        raise TemporalAdmissionError(
            "temporal_admission.invalid_json",
            "$",
            "expected exactly one strict JSON value",
        ) from exc


def parse_temporal_admission_review_json(text: str) -> TemporalAdmissionReview:
    return parse_temporal_admission_review_payload(_decode_json(text))


def _source_tuple(source: ScienceSource) -> Tuple[str, str, str]:
    return (source.citation, source.journal_doi, source.arxiv_versioned_id)


def assess_temporal_admission(
    card: MinimalScienceCard,
    review: TemporalAdmissionReview,
    *,
    paper_id: str,
    source_line_count: int,
) -> TemporalAdmissionResult:
    """Admit a paper when one independently reviewed relation is source-supported."""

    if (
        isinstance(source_line_count, bool)
        or not isinstance(source_line_count, int)
        or source_line_count < 1
    ):
        raise ValueError("source_line_count must be a positive integer")
    try:
        validate_minimal_science_card_lineage(card, source_line_count)
    except MinimalScienceCardError as exc:
        _error(
            "$.review_material",
            "contains an unresolved source locator: %s" % exc,
            "temporal_admission.locator",
        )
    for issue_index, issue in enumerate(review.issues):
        for range_index, line_range in enumerate(issue.line_ranges):
            if line_range.line_end > source_line_count:
                _error(
                    "$.issues[%d].line_ranges[%d]" % (issue_index, range_index),
                    "line range exceeds the fixed source packet",
                    "temporal_admission.locator",
                )
    if review.paper_id != paper_id or _source_tuple(review.source) != _source_tuple(
        card.source
    ):
        _error(
            "$.source",
            "review must identify the current paper and source exactly",
            "temporal_admission.review_identity",
        )
    try:
        reviewed_card = parse_minimal_science_card_payload(review.review_material)
    except MinimalScienceCardError as exc:
        _error(
            "$.review_material",
            "contains an invalid minimal ScienceCard: %s" % exc,
            "temporal_admission.review_material",
        )
    if minimal_science_card_to_payload(reviewed_card) != minimal_science_card_to_payload(
        card
    ):
        _error(
            "$.review_material",
            "must reproduce the exact minimal ScienceCard reviewed",
            "temporal_admission.review_material",
        )
    if review.decision == "ineligible_for_temporal_case":
        return TemporalAdmissionResult(
            admitted=False,
            disposition="source_review_rejected",
            card=None,
            review=review,
            paper_id=paper_id,
            source_line_count=source_line_count,
            issues=review.issues,
        )
    if review.decision == "card_revision_required":
        return TemporalAdmissionResult(
            admitted=False,
            disposition="card_revision_required",
            card=None,
            review=review,
            paper_id=paper_id,
            source_line_count=source_line_count,
            issues=review.issues,
        )
    if len(card.relations) != 1:
        _error(
            "$.review_material.relations",
            "eligible admission requires one source-supported executable relation",
            "temporal_admission.relation_required",
        )
    return TemporalAdmissionResult(
        admitted=True,
        disposition="eligible_for_temporal_case",
        card=card,
        review=review,
        paper_id=paper_id,
        source_line_count=source_line_count,
        issues=review.issues,
    )


def temporal_admission_review_to_payload(
    review: TemporalAdmissionReview,
) -> Mapping[str, Any]:
    """Serialize one independent source-review decision."""

    return {
        "schema": TEMPORAL_ADMISSION_REVIEW_SCHEMA,
        "paper_id": review.paper_id,
        "source": {
            "citation": review.source.citation,
            "journal_doi": review.source.journal_doi,
            "arxiv_versioned_id": review.source.arxiv_versioned_id,
        },
        "review_material": dict(review.review_material),
        "reviewer": review.reviewer,
        "decision": review.decision,
        "assessment": review.assessment,
        "checks": {
            "source_support_confirmed": review.source_support_confirmed,
            "cartesian_domain_supported": review.cartesian_domain_supported,
            "deterministic_central_value_appropriate": (
                review.deterministic_central_value_appropriate
            ),
        },
        "issues": [
            {
                "code": item.code,
                "detail": item.detail,
                "blocking": item.blocking,
                "line_ranges": [
                    {
                        "line_start": line_range.line_start,
                        "line_end": line_range.line_end,
                    }
                    for line_range in item.line_ranges
                ],
            }
            for item in review.issues
        ],
    }


def temporal_admission_review_request_payload(
    card: MinimalScienceCard,
    *,
    paper_id: str,
) -> Mapping[str, Any]:
    """Return a non-approving source-review template."""

    return {
        "schema": TEMPORAL_ADMISSION_REVIEW_SCHEMA,
        "paper_id": paper_id,
        "source": {
            "citation": card.source.citation,
            "journal_doi": card.source.journal_doi,
            "arxiv_versioned_id": card.source.arxiv_versioned_id,
        },
        "review_material": minimal_science_card_to_payload(card),
        "reviewer": "REQUIRED_INDEPENDENT_SOURCE_REVIEWER",
        "decision": "ineligible_for_temporal_case",
        "assessment": "REPLACE_AFTER_CHECKING_THE_SOURCE_AND_EVERY_LINE_RANGE",
        "checks": {
            "source_support_confirmed": False,
            "cartesian_domain_supported": False,
            "deterministic_central_value_appropriate": False,
        },
        "issues": [
            {
                "code": "review.pending",
                "detail": "No independent source-review decision has been supplied.",
                "blocking": True,
                "line_ranges": [],
            }
        ],
    }


__all__ = [
    "AdmissionLineRange",
    "TEMPORAL_ADMISSION_REVIEW_SCHEMA",
    "TemporalAdmissionError",
    "TemporalAdmissionIssue",
    "TemporalAdmissionResult",
    "TemporalAdmissionReview",
    "assess_temporal_admission",
    "parse_temporal_admission_review_json",
    "parse_temporal_admission_review_payload",
    "temporal_admission_review_to_payload",
    "temporal_admission_review_request_payload",
]
