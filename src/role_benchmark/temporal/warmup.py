"""Frozen-cohort and independent source-review contracts for warm-up authoring."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, replace
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Tuple, Union

from role_benchmark.expression import evaluate_expression_program
from role_benchmark.wire import canonical_json_dumps

from .acquisition import ACQUISITION_SCHEMA, MAX_COORDINATOR_COHORT_SIZE
from .arxiv import parse_versioned_arxiv_id
from .author import case_draft_to_payload
from .census import canonicalize_doi
from .filter import materialize_outputs
from .metadata import SourcePaper
from .render import build_matched_spec
from .science_card import (
    ScienceCard,
    ScienceCardError,
    ScienceSource,
    canonical_science_name,
    parse_science_card_payload,
    science_card_to_payload,
)


_PAPER_ID = re.compile(r"^[a-z][a-z0-9_]*$")
_COHORT_KEYS = {"window", "papers", "provenance"}
_WINDOW_KEYS = {"start", "end", "earliest_public_not_before"}
_COHORT_PROVENANCE_KEYS = {
    "acquisition_schema",
    "coordinator_ready",
    "handoff_status",
    "retrieved_at",
    "selected_count",
    "selection_policy",
}
_PAPER_KEYS = {
    "paper_id",
    "title",
    "source_citation",
    "journal_doi",
    "arxiv_versioned_id",
    "tex_path",
    "venue",
    "publication_date",
    "earliest_public_date",
    "article_type",
    "citation_count",
    "latex_available",
    "withdrawn_or_retracted",
}
_PAPER_OPTIONAL_KEYS = {"source_packet_path"}
_REVIEW_KEYS = {
    "paper_id",
    "source",
    "review_material",
    "reviewer",
    "decision",
    "assessment",
    "selected_cluster",
    "issues",
}
_SOURCE_KEYS = {"citation", "journal_doi", "arxiv_versioned_id"}
_CLUSTER_KEYS = {
    "mechanism_ids",
    "branch_a_claim_ids",
    "branch_b_claim_ids",
    "public_control_names",
    "public_readout_names",
    "common_fixed_condition_ids",
    "branch_a_fixed_condition_ids",
    "branch_b_fixed_condition_ids",
}
_ISSUE_KEYS = {"code", "detail", "line_ranges"}
_LINE_RANGE_KEYS = {"line_start", "line_end"}
_FAMILY_REVIEW_KEYS = {
    "paper_id",
    "family",
    "source",
    "review_material",
    "reviewer",
    "decision",
    "assessment",
    "issues",
}


class WarmupContractError(ValueError):
    """A frozen input or independent review does not satisfy its contract."""

    def __init__(self, code: str, path: str, detail: str) -> None:
        self.code = code
        self.path = path
        self.detail = detail
        super().__init__("%s at %s: %s" % (code, path, detail))


@dataclass(frozen=True)
class WarmupPaper:
    paper_id: str
    title: str
    source_citation: str
    journal_doi: str
    arxiv_versioned_id: str
    tex_path: Path
    source_paper: SourcePaper
    source_packet_path: Optional[Path] = None


@dataclass(frozen=True)
class WarmupCohortProvenance:
    acquisition_schema: str
    coordinator_ready: bool
    handoff_status: str
    retrieved_at: datetime
    selected_count: int
    selection_policy: str


@dataclass(frozen=True)
class WarmupCohort:
    start: date
    end: date
    earliest_public_not_before: Optional[date]
    papers: Tuple[WarmupPaper, ...]
    provenance: WarmupCohortProvenance


@dataclass(frozen=True)
class ReviewLineRange:
    line_start: int
    line_end: int


@dataclass(frozen=True)
class SourceReviewIssue:
    code: str
    detail: str
    line_ranges: Tuple[ReviewLineRange, ...]


@dataclass(frozen=True)
class ReviewedCluster:
    mechanism_ids: Tuple[str, ...]
    branch_a_claim_ids: Tuple[str, ...]
    branch_b_claim_ids: Tuple[str, ...]
    public_control_names: Tuple[str, ...]
    public_readout_names: Tuple[str, ...]
    common_fixed_condition_ids: Tuple[str, ...]
    branch_a_fixed_condition_ids: Tuple[str, ...]
    branch_b_fixed_condition_ids: Tuple[str, ...]


@dataclass(frozen=True)
class SourceReview:
    paper_id: str
    source: ScienceSource
    review_material: Mapping[str, Any]
    reviewer: str
    decision: str
    assessment: str
    selected_cluster: Optional[ReviewedCluster]
    issues: Tuple[SourceReviewIssue, ...]


@dataclass(frozen=True)
class FamilySourceReview:
    paper_id: str
    family: str
    source: ScienceSource
    review_material: Mapping[str, Any]
    reviewer: str
    decision: str
    assessment: str
    issues: Tuple[SourceReviewIssue, ...]


@dataclass(frozen=True)
class PaperEligibilityResult:
    eligible_for_drafting: bool
    primary_disposition: str
    issues: Tuple[SourceReviewIssue, ...]
    selected_cluster: Optional[ReviewedCluster]
    reviewed_card: Optional[ScienceCard]


def _error(path: str, detail: str, code: str = "warmup.schema") -> None:
    raise WarmupContractError(code, path, detail)


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


def _object_with_optional(
    value: Any,
    path: str,
    required_keys: set[str],
    optional_keys: set[str],
) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        _error(path, "must be an object")
    actual = set(value)
    missing = required_keys - actual
    extra = actual - required_keys - optional_keys
    if missing or extra:
        _error(
            path,
            "keys are invalid (missing=%s, extra=%s)"
            % (sorted(missing), sorted(extra)),
        )
    return value


def _array(value: Any, path: str) -> list[Any]:
    if not isinstance(value, list):
        _error(path, "must be an array")
    return value


def _review_material(value: Any, path: str) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        _error(path, "must be an object")
    if not value:
        _error(path, "must contain the exact object presented for review")
    return value


def _same_json(left: Any, right: Any) -> bool:
    """Compare exact JSON types and values."""

    return canonical_json_dumps(left) == canonical_json_dumps(right)


def _text(value: Any, path: str) -> str:
    if not isinstance(value, str) or not value.strip():
        _error(path, "must be non-empty text")
    return value.strip()


def _identifier(value: Any, path: str) -> str:
    result = _text(value, path)
    if _PAPER_ID.fullmatch(result) is None:
        _error(path, "must be lower_snake_case")
    return result


def _identifier_array(value: Any, path: str) -> Tuple[str, ...]:
    result = tuple(
        _text(item, "%s[%d]" % (path, index))
        for index, item in enumerate(_array(value, path))
    )
    if len(set(result)) != len(result):
        _error(path, "must not contain duplicates")
    return result


def _boolean(value: Any, path: str) -> bool:
    if not isinstance(value, bool):
        _error(path, "must be a boolean")
    return value


def _integer(value: Any, path: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        _error(path, "must be an integer")
    return value


def _date(value: Any, path: str) -> date:
    raw = _text(value, path)
    try:
        return date.fromisoformat(raw)
    except ValueError as exc:
        raise WarmupContractError(
            "warmup.schema", path, "must be an ISO YYYY-MM-DD date"
        ) from exc


def _optional_date(value: Any, path: str) -> Optional[date]:
    if value is None:
        return None
    return _date(value, path)


def _timestamp(value: Any, path: str) -> datetime:
    raw = _text(value, path)
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError as exc:
        raise WarmupContractError(
            "warmup.schema", path, "must be an ISO timestamp"
        ) from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        _error(path, "must include a timezone")
    return parsed


def _decode_json(text: str) -> Any:
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
        raise WarmupContractError(
            "warmup.invalid_json", "$", "expected exactly one strict JSON value"
        ) from exc


def parse_warmup_cohort_payload(
    payload: Any, *, base_directory: Union[str, Path]
) -> WarmupCohort:
    """Parse a frozen, ordered cohort within the coordinator limit."""

    root = _object(payload, "$", _COHORT_KEYS)
    window = _object(root["window"], "$.window", _WINDOW_KEYS)
    raw_provenance = _object(
        root["provenance"], "$.provenance", _COHORT_PROVENANCE_KEYS
    )
    start = _date(window["start"], "$.window.start")
    end = _date(window["end"], "$.window.end")
    if end < start:
        _error("$.window", "end must not precede start")
    earliest = _optional_date(
        window["earliest_public_not_before"],
        "$.window.earliest_public_not_before",
    )
    raw_papers = _array(root["papers"], "$.papers")
    if not 1 <= len(raw_papers) <= MAX_COORDINATOR_COHORT_SIZE:
        _error(
            "$.papers",
            "must contain between one and %d papers"
            % MAX_COORDINATOR_COHORT_SIZE,
        )
    selected_count = _integer(
        raw_provenance["selected_count"], "$.provenance.selected_count"
    )
    if selected_count != len(raw_papers):
        _error(
            "$.provenance.selected_count",
            "must equal the number of cohort papers",
        )
    acquisition_schema = _text(
        raw_provenance["acquisition_schema"],
        "$.provenance.acquisition_schema",
    )
    if acquisition_schema != ACQUISITION_SCHEMA:
        _error("$.provenance.acquisition_schema", "unknown acquisition schema")
    coordinator_ready = _boolean(
        raw_provenance["coordinator_ready"],
        "$.provenance.coordinator_ready",
    )
    handoff_status = _text(
        raw_provenance["handoff_status"], "$.provenance.handoff_status"
    )
    if not coordinator_ready or handoff_status != "coordinator_ready":
        _error("$.provenance", "cohort is not coordinator-ready")
    selection_policy = _text(
        raw_provenance["selection_policy"],
        "$.provenance.selection_policy",
    )
    if selection_policy not in {"all", "citation_rank"}:
        _error("$.provenance.selection_policy", "unknown selection policy")
    provenance = WarmupCohortProvenance(
        acquisition_schema=acquisition_schema,
        coordinator_ready=coordinator_ready,
        handoff_status=handoff_status,
        retrieved_at=_timestamp(
            raw_provenance["retrieved_at"], "$.provenance.retrieved_at"
        ),
        selected_count=selected_count,
        selection_policy=selection_policy,
    )

    directory = Path(base_directory)
    papers = []
    for index, raw in enumerate(raw_papers):
        path = "$.papers[%d]" % index
        item = _object_with_optional(
            raw,
            path,
            _PAPER_KEYS,
            _PAPER_OPTIONAL_KEYS,
        )
        paper_id = _identifier(item["paper_id"], path + ".paper_id")
        doi = _text(item["journal_doi"], path + ".journal_doi")
        if canonicalize_doi(doi) != doi:
            _error(path + ".journal_doi", "must use canonical DOI form")
        arxiv_id = parse_versioned_arxiv_id(
            _text(item["arxiv_versioned_id"], path + ".arxiv_versioned_id")
        )
        raw_citation_count = item["citation_count"]
        if raw_citation_count is None:
            citation_count = None
        else:
            citation_count = _integer(
                raw_citation_count, path + ".citation_count"
            )
            if citation_count < 0:
                _error(path + ".citation_count", "must not be negative")
        tex_path = Path(_text(item["tex_path"], path + ".tex_path"))
        if not tex_path.is_absolute():
            tex_path = directory / tex_path
        raw_source_packet_path = item.get("source_packet_path")
        if raw_source_packet_path is None:
            source_packet_path = None
        else:
            source_packet_path = Path(
                _text(
                    raw_source_packet_path,
                    path + ".source_packet_path",
                )
            )
            if not source_packet_path.is_absolute():
                source_packet_path = directory / source_packet_path
        source = SourcePaper(
            doi=doi,
            title=_text(item["title"], path + ".title"),
            venue=_text(item["venue"], path + ".venue"),
            publication_date=_date(
                item["publication_date"], path + ".publication_date"
            ),
            earliest_public_date=_date(
                item["earliest_public_date"], path + ".earliest_public_date"
            ),
            article_type=_text(item["article_type"], path + ".article_type"),
            citation_count=citation_count,
            latex_available=_boolean(
                item["latex_available"], path + ".latex_available"
            ),
            withdrawn_or_retracted=_boolean(
                item["withdrawn_or_retracted"],
                path + ".withdrawn_or_retracted",
            ),
        )
        papers.append(
            WarmupPaper(
                paper_id=paper_id,
                title=source.title,
                source_citation=_text(
                    item["source_citation"], path + ".source_citation"
                ),
                journal_doi=doi,
                arxiv_versioned_id=arxiv_id,
                tex_path=tex_path,
                source_paper=source,
                source_packet_path=source_packet_path,
            )
        )

    paper_ids = [paper.paper_id for paper in papers]
    dois = [paper.journal_doi for paper in papers]
    if len(set(paper_ids)) != len(paper_ids):
        _error("$.papers", "paper_id values must be unique")
    if len(set(dois)) != len(dois):
        _error("$.papers", "journal DOI values must be unique")
    return WarmupCohort(start, end, earliest, tuple(papers), provenance)


def parse_warmup_cohort_json(
    text: str, *, base_directory: Union[str, Path]
) -> WarmupCohort:
    return parse_warmup_cohort_payload(
        _decode_json(text), base_directory=base_directory
    )


def _review_line_ranges(value: Any, path: str) -> Tuple[ReviewLineRange, ...]:
    result = []
    for index, raw in enumerate(_array(value, path)):
        item_path = "%s[%d]" % (path, index)
        item = _object(raw, item_path, _LINE_RANGE_KEYS)
        start = _integer(item["line_start"], item_path + ".line_start")
        end = _integer(item["line_end"], item_path + ".line_end")
        if start < 1 or end < start:
            _error(item_path, "must satisfy 1 <= line_start <= line_end")
        result.append(ReviewLineRange(start, end))
    if not result:
        _error(path, "must contain at least one source locator")
    return tuple(result)


def _review_issue(value: Any, path: str) -> SourceReviewIssue:
    item = _object(value, path, _ISSUE_KEYS)
    return SourceReviewIssue(
        code=_text(item["code"], path + ".code"),
        detail=_text(item["detail"], path + ".detail"),
        line_ranges=_review_line_ranges(item["line_ranges"], path + ".line_ranges"),
    )


def _reviewed_cluster(value: Any, path: str) -> ReviewedCluster:
    item = _object(value, path, _CLUSTER_KEYS)
    return ReviewedCluster(
        mechanism_ids=_identifier_array(
            item["mechanism_ids"], path + ".mechanism_ids"
        ),
        branch_a_claim_ids=_identifier_array(
            item["branch_a_claim_ids"], path + ".branch_a_claim_ids"
        ),
        branch_b_claim_ids=_identifier_array(
            item["branch_b_claim_ids"], path + ".branch_b_claim_ids"
        ),
        public_control_names=_identifier_array(
            item["public_control_names"], path + ".public_control_names"
        ),
        public_readout_names=_identifier_array(
            item["public_readout_names"], path + ".public_readout_names"
        ),
        common_fixed_condition_ids=_identifier_array(
            item["common_fixed_condition_ids"],
            path + ".common_fixed_condition_ids",
        ),
        branch_a_fixed_condition_ids=_identifier_array(
            item["branch_a_fixed_condition_ids"],
            path + ".branch_a_fixed_condition_ids",
        ),
        branch_b_fixed_condition_ids=_identifier_array(
            item["branch_b_fixed_condition_ids"],
            path + ".branch_b_fixed_condition_ids",
        ),
    )


def parse_source_review_payload(payload: Any) -> SourceReview:
    """Parse an external review; this module never manufactures an approval."""

    root = _object(payload, "$", _REVIEW_KEYS)
    source = _object(root["source"], "$.source", _SOURCE_KEYS)
    decision = _text(root["decision"], "$.decision")
    if decision not in {
        "eligible_for_drafting",
        "card_revision_required",
        "ineligible_for_bench",
    }:
        _error(
            "$.decision",
            "must be eligible_for_drafting, card_revision_required, "
            "or ineligible_for_bench",
        )
    selected = root["selected_cluster"]
    if decision == "eligible_for_drafting":
        if selected is None:
            _error("$.selected_cluster", "an eligible review must select a cluster")
        cluster = _reviewed_cluster(selected, "$.selected_cluster")
    else:
        if selected is not None:
            _error(
                "$.selected_cluster",
                "a non-eligible review cannot select a cluster",
            )
        cluster = None
    issues = tuple(
        _review_issue(item, "$.issues[%d]" % index)
        for index, item in enumerate(_array(root["issues"], "$.issues"))
    )
    if (
        decision in {"card_revision_required", "ineligible_for_bench"}
        and not issues
    ):
        _error(
            "$.issues",
            "a non-eligible review must state at least one issue",
        )
    if decision == "eligible_for_drafting" and issues:
        _error("$.issues", "an eligible review cannot retain unresolved issues")
    reviewer = _text(root["reviewer"], "$.reviewer")
    if reviewer == "REQUIRED_INDEPENDENT_SOURCE_REVIEWER":
        _error("$.reviewer", "replace the review-request placeholder")
    return SourceReview(
        paper_id=_identifier(root["paper_id"], "$.paper_id"),
        source=ScienceSource(
            citation=_text(source["citation"], "$.source.citation"),
            journal_doi=_text(source["journal_doi"], "$.source.journal_doi"),
            arxiv_versioned_id=_text(
                source["arxiv_versioned_id"], "$.source.arxiv_versioned_id"
            ),
        ),
        review_material=_review_material(
            root["review_material"], "$.review_material"
        ),
        reviewer=reviewer,
        decision=decision,
        assessment=_text(root["assessment"], "$.assessment"),
        selected_cluster=cluster,
        issues=issues,
    )


def parse_source_review_json(text: str) -> SourceReview:
    return parse_source_review_payload(_decode_json(text))


def parse_family_source_review_payload(payload: Any) -> FamilySourceReview:
    """Parse an independent source-closure verdict for one filtered family."""

    root = _object(payload, "$", _FAMILY_REVIEW_KEYS)
    source = _object(root["source"], "$.source", _SOURCE_KEYS)
    decision = _text(root["decision"], "$.decision")
    if decision not in {"source_closed", "source_closure_rejected"}:
        _error(
            "$.decision",
            "must be source_closed or source_closure_rejected",
        )
    issues = tuple(
        _review_issue(item, "$.issues[%d]" % index)
        for index, item in enumerate(_array(root["issues"], "$.issues"))
    )
    if decision == "source_closed" and issues:
        _error("$.issues", "a source-closed family cannot retain unresolved issues")
    if decision == "source_closure_rejected" and not issues:
        _error("$.issues", "a rejected family must state at least one issue")
    reviewer = _text(root["reviewer"], "$.reviewer")
    if reviewer == "REQUIRED_INDEPENDENT_SOURCE_REVIEWER":
        _error("$.reviewer", "replace the review-request placeholder")
    return FamilySourceReview(
        paper_id=_identifier(root["paper_id"], "$.paper_id"),
        family=_identifier(root["family"], "$.family"),
        source=ScienceSource(
            citation=_text(source["citation"], "$.source.citation"),
            journal_doi=_text(source["journal_doi"], "$.source.journal_doi"),
            arxiv_versioned_id=_text(
                source["arxiv_versioned_id"], "$.source.arxiv_versioned_id"
            ),
        ),
        review_material=_review_material(
            root["review_material"], "$.review_material"
        ),
        reviewer=reviewer,
        decision=decision,
        assessment=_text(root["assessment"], "$.assessment"),
        issues=issues,
    )


def parse_family_source_review_json(text: str) -> FamilySourceReview:
    return parse_family_source_review_payload(_decode_json(text))


def assess_family_source_closure(
    draft: Any,
    review: FamilySourceReview,
    *,
    paper_id: str,
) -> bool:
    """Bind a post-filter verdict to the exact family review material."""

    candidate = draft.candidate

    expected_source = (
        candidate.source.citation,
        candidate.source.journal_doi,
        candidate.source.arxiv_versioned_id,
    )
    actual_source = (
        review.source.citation,
        review.source.journal_doi,
        review.source.arxiv_versioned_id,
    )
    if (
        review.paper_id != paper_id
        or review.family != candidate.family
        or actual_source != expected_source
    ):
        _error(
            "$.source",
            "family review must identify the current paper, family, and source",
            "warmup.family_review_identity",
        )
    expected_material = _family_review_material(draft)
    if not _same_json(review.review_material, expected_material):
        _error(
            "$.review_material",
            "family review must reproduce the exact candidate, boundary, and predictions",
            "warmup.family_review_material",
        )
    return review.decision == "source_closed"


def _require_nonempty(values: Tuple[str, ...], path: str) -> None:
    if not values:
        _error(path, "must not be empty", "warmup.review_scope")


def _require_subset(
    values: Tuple[str, ...], allowed: set[str], path: str
) -> None:
    unknown = sorted(set(values) - allowed)
    if unknown:
        _error(
            path,
            "contains unknown science-card identifiers: %s" % ", ".join(unknown),
            "warmup.review_scope",
        )


def assess_paper_eligibility(
    card: ScienceCard,
    review: SourceReview,
    *,
    paper_id: str,
) -> PaperEligibilityResult:
    """Apply an independent source verdict and return only its reviewed cluster.

    ``card.case_authoring_ready`` is deliberately not consulted: it is an LLM
    self-assessment, whereas ``review`` is the explicit admission authority.
    """

    expected_source = (
        card.source.citation,
        card.source.journal_doi,
        card.source.arxiv_versioned_id,
    )
    actual_source = (
        review.source.citation,
        review.source.journal_doi,
        review.source.arxiv_versioned_id,
    )
    if review.paper_id != paper_id or actual_source != expected_source:
        _error(
            "$.source",
            "review must identify the current paper and science card exactly",
            "warmup.review_identity",
        )
    try:
        reviewed_material = science_card_to_payload(
            parse_science_card_payload(review.review_material)
        )
    except ScienceCardError as exc:
        _error(
            "$.review_material",
            "source review contains an invalid science card: %s" % exc,
            "warmup.review_material",
        )
    if not _same_json(reviewed_material, science_card_to_payload(card)):
        _error(
            "$.review_material",
            "source review must reproduce the exact science card it reviewed",
            "warmup.review_material",
        )
    if review.decision == "ineligible_for_bench":
        return PaperEligibilityResult(
            eligible_for_drafting=False,
            primary_disposition="source_review_rejected",
            issues=review.issues,
            selected_cluster=None,
            reviewed_card=None,
        )
    if review.decision == "card_revision_required":
        return PaperEligibilityResult(
            eligible_for_drafting=False,
            primary_disposition="card_revision_required",
            issues=review.issues,
            selected_cluster=None,
            reviewed_card=None,
        )

    cluster = review.selected_cluster
    if cluster is None:  # guarded by the strict parser; keeps typed callers honest
        _error("$.selected_cluster", "eligible review is missing its cluster")
    for values, path in (
        (cluster.mechanism_ids, "$.selected_cluster.mechanism_ids"),
        (cluster.branch_a_claim_ids, "$.selected_cluster.branch_a_claim_ids"),
        (cluster.branch_b_claim_ids, "$.selected_cluster.branch_b_claim_ids"),
        (cluster.public_control_names, "$.selected_cluster.public_control_names"),
        (cluster.public_readout_names, "$.selected_cluster.public_readout_names"),
        (
            cluster.branch_a_fixed_condition_ids,
            "$.selected_cluster.branch_a_fixed_condition_ids",
        ),
        (
            cluster.branch_b_fixed_condition_ids,
            "$.selected_cluster.branch_b_fixed_condition_ids",
        ),
    ):
        _require_nonempty(values, path)
    selected_claim_ids = set(cluster.branch_a_claim_ids) | set(
        cluster.branch_b_claim_ids
    )
    selected_mechanism_ids = set(cluster.mechanism_ids)
    selected_control_names = set(cluster.public_control_names)
    selected_readout_names = set(cluster.public_readout_names)
    selected_condition_ids_for_ambiguity = (
        set(cluster.common_fixed_condition_ids)
        | set(cluster.branch_a_fixed_condition_ids)
        | set(cluster.branch_b_fixed_condition_ids)
    )
    if not 1 <= len(cluster.public_control_names) <= 5:
        issue = SourceReviewIssue(
            code="paper.control_count_out_of_scope",
            detail="A benchmark family must expose between one and five controls.",
            line_ranges=tuple(
                ReviewLineRange(anchor.line_start, anchor.line_end)
                for item in card.controls
                if item.name in cluster.public_control_names
                for anchor in item.anchors
            ),
        )
        return PaperEligibilityResult(
            False,
            "bench_resource_shape_out_of_scope",
            (issue,),
            cluster,
            None,
        )
    if not 1 <= len(cluster.public_readout_names) <= 2:
        issue = SourceReviewIssue(
            code="paper.readout_count_out_of_scope",
            detail="A benchmark family must expose one or two readouts.",
            line_ranges=tuple(
                ReviewLineRange(anchor.line_start, anchor.line_end)
                for item in card.readouts
                if item.name in cluster.public_readout_names
                for anchor in item.anchors
            ),
        )
        return PaperEligibilityResult(
            False,
            "bench_resource_shape_out_of_scope",
            (issue,),
            cluster,
            None,
        )
    selected_ambiguities = tuple(
        item
        for item in card.source_ambiguities
        if (
            not (
                item.claim_ids
                or item.mechanism_ids
                or item.control_names
                or item.readout_names
                or item.fixed_condition_ids
            )
            or set(item.claim_ids) & selected_claim_ids
            or set(item.mechanism_ids) & selected_mechanism_ids
            or {
                canonical_science_name(name) for name in item.control_names
            }
            & {
                canonical_science_name(name) for name in selected_control_names
            }
            or {
                canonical_science_name(name) for name in item.readout_names
            }
            & {
                canonical_science_name(name) for name in selected_readout_names
            }
            or set(item.fixed_condition_ids)
            & selected_condition_ids_for_ambiguity
        )
    )
    if selected_ambiguities:
        issues = tuple(
            SourceReviewIssue(
                code="paper.unresolved_source_ambiguity",
                detail=item.statement,
                line_ranges=tuple(
                    ReviewLineRange(anchor.line_start, anchor.line_end)
                    for anchor in item.anchors
                ),
            )
            for item in selected_ambiguities
        )
        return PaperEligibilityResult(
            False,
            "unresolved_source_ambiguity",
            issues,
            cluster,
            None,
        )
    if set(cluster.branch_a_claim_ids) & set(cluster.branch_b_claim_ids):
        _error(
            "$.selected_cluster",
            "the two branch claim sets must be disjoint",
            "warmup.review_scope",
        )
    if set(cluster.branch_a_fixed_condition_ids) & set(
        cluster.branch_b_fixed_condition_ids
    ):
        _error(
            "$.selected_cluster",
            "the two branch-specific condition sets must be disjoint",
            "warmup.review_scope",
        )
    common_conditions = set(cluster.common_fixed_condition_ids)
    if common_conditions & (
        set(cluster.branch_a_fixed_condition_ids)
        | set(cluster.branch_b_fixed_condition_ids)
    ):
        _error(
            "$.selected_cluster",
            "common and branch-specific conditions must be disjoint",
            "warmup.review_scope",
        )

    mechanism_ids = {item.mechanism_id for item in card.mechanisms}
    claim_ids = {item.claim_id for item in card.claims}
    control_names = {item.name for item in card.controls}
    readout_names = {item.name for item in card.readouts}
    condition_ids = {item.condition_id for item in card.fixed_conditions}
    selected_condition_ids = (
        set(cluster.common_fixed_condition_ids)
        | set(cluster.branch_a_fixed_condition_ids)
        | set(cluster.branch_b_fixed_condition_ids)
    )
    for values, allowed, path in (
        (cluster.mechanism_ids, mechanism_ids, "$.selected_cluster.mechanism_ids"),
        (tuple(selected_claim_ids), claim_ids, "$.selected_cluster.*_claim_ids"),
        (
            cluster.public_control_names,
            control_names,
            "$.selected_cluster.public_control_names",
        ),
        (
            cluster.public_readout_names,
            readout_names,
            "$.selected_cluster.public_readout_names",
        ),
        (
            tuple(selected_condition_ids),
            condition_ids,
            "$.selected_cluster.*_fixed_condition_ids",
        ),
    ):
        _require_subset(values, allowed, path)

    selected_claims = tuple(
        item for item in card.claims if item.claim_id in selected_claim_ids
    )
    missing_programs = tuple(
        item.claim_id
        for item in selected_claims
        if item.oracle_outputs is None
    )
    if missing_programs:
        _error(
            "$.selected_cluster.*_claim_ids",
            "eligible review requires structured oracle_outputs for every selected claim; use card_revision_required before drafting (missing=%s)"
            % ", ".join(missing_programs),
            "warmup.review_scope",
        )
    selected_mechanisms = tuple(
        item for item in card.mechanisms if item.mechanism_id in cluster.mechanism_ids
    )
    for claim in selected_claims:
        _require_subset(
            claim.mechanism_ids,
            set(cluster.mechanism_ids),
            "$.claims.%s.mechanism_ids" % claim.claim_id,
        )
        _require_subset(
            claim.control_names,
            set(cluster.public_control_names),
            "$.claims.%s.control_names" % claim.claim_id,
        )
        _require_subset(
            claim.readout_names,
            set(cluster.public_readout_names),
            "$.claims.%s.readout_names" % claim.claim_id,
        )
        _require_subset(
            claim.fixed_condition_ids,
            selected_condition_ids,
            "$.claims.%s.fixed_condition_ids" % claim.claim_id,
        )
        _require_subset(
            claim.depends_on,
            selected_claim_ids,
            "$.claims.%s.depends_on" % claim.claim_id,
        )

    branch_a_conditions = set(cluster.branch_a_fixed_condition_ids)
    branch_b_conditions = set(cluster.branch_b_fixed_condition_ids)
    branch_a_claims = [
        item for item in selected_claims if item.claim_id in cluster.branch_a_claim_ids
    ]
    branch_b_claims = [
        item for item in selected_claims if item.claim_id in cluster.branch_b_claim_ids
    ]
    if not any(set(item.fixed_condition_ids) & branch_a_conditions for item in branch_a_claims):
        _error(
            "$.selected_cluster.branch_a_fixed_condition_ids",
            "at least one branch-a claim must cite a branch-a condition",
            "warmup.review_scope",
        )
    if not any(set(item.fixed_condition_ids) & branch_b_conditions for item in branch_b_claims):
        _error(
            "$.selected_cluster.branch_b_fixed_condition_ids",
            "at least one branch-b claim must cite a branch-b condition",
            "warmup.review_scope",
        )
    for claims, own_conditions, other_conditions, branch in (
        (branch_a_claims, branch_a_conditions, branch_b_conditions, "branch_a"),
        (branch_b_claims, branch_b_conditions, branch_a_conditions, "branch_b"),
    ):
        claim_controls = {name for item in claims for name in item.control_names}
        claim_readouts = {name for item in claims for name in item.readout_names}
        claim_conditions = {
            name for item in claims for name in item.fixed_condition_ids
        }
        if claim_controls != set(cluster.public_control_names):
            _error(
                "$.selected_cluster.%s_claim_ids" % branch,
                "each branch must support exactly the selected public controls",
                "warmup.review_scope",
            )
        if claim_readouts != set(cluster.public_readout_names):
            _error(
                "$.selected_cluster.%s_claim_ids" % branch,
                "each branch must support exactly the selected public readouts",
                "warmup.review_scope",
            )
        if claim_conditions & other_conditions:
            _error(
                "$.selected_cluster.%s_claim_ids" % branch,
                "a branch cannot cite the other branch's private condition",
                "warmup.review_scope",
            )
        if not own_conditions <= claim_conditions:
            _error(
                "$.selected_cluster.%s_fixed_condition_ids" % branch,
                "every selected branch condition must be cited by that branch",
                "warmup.review_scope",
            )
        if not common_conditions <= claim_conditions:
            _error(
                "$.selected_cluster.common_fixed_condition_ids",
                "both branches must cite every selected common condition",
                "warmup.review_scope",
            )
    used_mechanisms = {
        name for item in selected_claims for name in item.mechanism_ids
    }
    if used_mechanisms != set(cluster.mechanism_ids):
        _error(
            "$.selected_cluster.mechanism_ids",
            "selected mechanisms must be used by the selected claims",
            "warmup.review_scope",
        )

    reviewed_card = replace(
        card,
        case_authoring_ready=True,
        mechanisms=selected_mechanisms,
        fixed_conditions=tuple(
            item
            for item in card.fixed_conditions
            if item.condition_id in selected_condition_ids
        ),
        controls=tuple(
            item for item in card.controls if item.name in cluster.public_control_names
        ),
        readouts=tuple(
            item for item in card.readouts if item.name in cluster.public_readout_names
        ),
        claims=selected_claims,
        source_ambiguities=(),
    )
    reviewed_card = parse_science_card_payload(
        science_card_to_payload(reviewed_card),
        require_oracle_outputs=True,
    )
    return PaperEligibilityResult(
        eligible_for_drafting=True,
        primary_disposition="eligible_source_contained_regime_pair",
        issues=review.issues,
        selected_cluster=cluster,
        reviewed_card=reviewed_card,
    )


def review_request_payload(card: ScienceCard, *, paper_id: str) -> Mapping[str, Any]:
    """Emit a fail-closed blank decision shape, never an approval.

    A reviewer may replace the decision with ``eligible_for_drafting``,
    ``card_revision_required``, or ``ineligible_for_bench``.  Card revision
    terminates the frozen run; the revised card must use a new output directory.
    """

    return {
        "paper_id": paper_id,
        "source": {
            "citation": card.source.citation,
            "journal_doi": card.source.journal_doi,
            "arxiv_versioned_id": card.source.arxiv_versioned_id,
        },
        "review_material": science_card_to_payload(card),
        "reviewer": "REQUIRED_INDEPENDENT_SOURCE_REVIEWER",
        "decision": "ineligible_for_bench",
        "assessment": "REPLACE_AFTER_CHECKING_THE_TEX_AND_EVERY_SELECTED_LOCATOR",
        "selected_cluster": None,
        "issues": [
            {
                "code": "review.pending",
                "detail": (
                    "No independent source verdict has been supplied. Choose "
                    "eligible_for_drafting, card_revision_required, or "
                    "ineligible_for_bench; a revised card requires a new output "
                    "directory."
                ),
                "line_ranges": [],
            }
        ],
    }


def _family_review_material(draft: Any) -> Mapping[str, Any]:
    """Return the ordinary JSON object that a family reviewer must preserve."""
    candidate = draft.candidate
    spec = build_matched_spec(candidate)
    programs = {
        "paper": {
            "outputs": materialize_outputs(
                candidate.oracle.outputs, candidate.oracle.paper_parameters
            )
        },
        "alternate": {
            "outputs": materialize_outputs(
                candidate.oracle.outputs,
                candidate.oracle.counterfactual_parameters,
            )
        },
    }
    control_names = tuple(item.name for item in candidate.controls)
    readout_names = tuple(item.name for item in candidate.readouts)
    prediction_payload = []
    for group, conditions in (
        ("diagnostic", candidate.diagnostic_conditions),
        ("hidden", candidate.hidden_conditions),
    ):
        for index, condition in enumerate(conditions):
            prediction_payload.append(
                {
                    "group": group,
                    "index": index,
                    "controls": dict(condition),
                    "paper": evaluate_expression_program(
                        programs["paper"],
                        condition,
                        allowed_variables=control_names,
                        required_outputs=readout_names,
                    ),
                    "alternate": evaluate_expression_program(
                        programs["alternate"],
                        condition,
                        allowed_variables=control_names,
                        required_outputs=readout_names,
                    ),
                }
            )

    identification_contract = {
        "model": spec.identification_model,
        "parameters": list(spec.identification_parameters),
        "formula": spec.identification_formula,
        "historical_values": dict(
            spec.truths["historical"].identification_values or {}
        ),
        "counterfactual_values": dict(
            spec.truths["counterfactual"].identification_values or {}
        ),
    }
    return {
        **case_draft_to_payload(draft),
        "identification_contract": identification_contract,
        "predictions": prediction_payload,
    }


def family_review_request_payload(
    draft: Any, *, paper_id: str
) -> Mapping[str, Any]:
    """Emit a deliberately non-approving family source-closure template."""

    candidate = draft.candidate

    return {
        "paper_id": paper_id,
        "family": candidate.family,
        "source": {
            "citation": candidate.source.citation,
            "journal_doi": candidate.source.journal_doi,
            "arxiv_versioned_id": candidate.source.arxiv_versioned_id,
        },
        "review_material": _family_review_material(draft),
        "reviewer": "REQUIRED_INDEPENDENT_SOURCE_REVIEWER",
        "decision": "source_closure_rejected",
        "assessment": "REPLACE_AFTER_CHECKING_PLAYER_AND_ORACLE_SOURCE_CLOSURE",
        "issues": [
            {
                "code": "review.pending",
                "detail": "No independent family source-closure verdict supplied.",
                "line_ranges": [],
            }
        ],
    }


__all__ = [
    "FamilySourceReview",
    "PaperEligibilityResult",
    "ReviewedCluster",
    "ReviewLineRange",
    "SourceReview",
    "SourceReviewIssue",
    "WarmupContractError",
    "WarmupCohort",
    "WarmupCohortProvenance",
    "WarmupPaper",
    "assess_paper_eligibility",
    "assess_family_source_closure",
    "family_review_request_payload",
    "parse_family_source_review_json",
    "parse_family_source_review_payload",
    "parse_source_review_json",
    "parse_source_review_payload",
    "parse_warmup_cohort_json",
    "parse_warmup_cohort_payload",
    "review_request_payload",
]
