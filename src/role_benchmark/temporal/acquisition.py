"""Deterministic journal-record to fixed-TeX cohort acquisition."""

from __future__ import annotations

import json
import re
import time
from collections import Counter
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Optional, Tuple, Union

from role_benchmark.wire import canonical_json_dumps

from .arxiv import (
    ArxivTransport,
    arxiv_base_id,
    arxiv_resolution_to_payload,
    download_arxiv_source,
    parse_versioned_arxiv_id,
    resolve_arxiv_paper,
    resolve_manually_reviewed_arxiv_paper,
)
from .census import (
    CensusPaper,
    CensusSnapshot,
    CrossrefTransport,
    canonicalize_doi,
    census_paper_to_payload,
    census_snapshot_to_payload,
    collect_crossref_census_snapshot,
)
from .latex import (
    FigureEvidenceAddendum,
    FigureEvidenceEntry,
    NoTexSourceError,
    TexDecodeError,
    append_figure_evidence_addendum,
)
from .metadata import TARGET_VENUES, original_research_rejection_code


ACQUISITION_SCHEMA = "role_benchmark.temporal_acquisition"
MAX_COORDINATOR_COHORT_SIZE = 60
Pause = Callable[[float], None]
_COHORT_PROVENANCE_KEYS = {
    "acquisition_schema",
    "coordinator_ready",
    "handoff_status",
    "retrieved_at",
    "selected_count",
    "selection_policy",
}


def _same_json(left: Any, right: Any) -> bool:
    return canonical_json_dumps(left) == canonical_json_dumps(right)


def _utc_timestamp(value: Optional[datetime]) -> datetime:
    result = value or datetime.now(timezone.utc)
    if result.tzinfo is None or result.utcoffset() is None:
        raise ValueError("retrieved_at must include a timezone")
    return result.astimezone(timezone.utc)


def _paper_id(versioned_id: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "_", versioned_id.casefold()).strip("_")
    if not normalized:
        raise ValueError("cannot derive paper_id from arXiv versioned ID")
    return "paper_%s" % normalized


def _source_citation(paper: CensusPaper, publication_date: date) -> str:
    prefix = "%s, " % paper.first_author if paper.first_author else ""
    return "%s%s, %s (%d), DOI:%s" % (
        prefix,
        paper.title,
        paper.venue,
        publication_date.year,
        paper.doi,
    )


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _paper_result(
    paper: CensusPaper,
    disposition: str,
    *,
    reason_code: Optional[str] = None,
    resolution: Optional[Mapping[str, Any]] = None,
    source: Optional[Mapping[str, Any]] = None,
    cohort_entry: Optional[Mapping[str, Any]] = None,
    publisher_reconciliation: Optional[Mapping[str, Any]] = None,
) -> Mapping[str, Any]:
    return {
        "cohort_entry": dict(cohort_entry) if cohort_entry is not None else None,
        "disposition": disposition,
        "journal": census_paper_to_payload(paper),
        "reason_code": reason_code,
        "resolution": dict(resolution) if resolution is not None else None,
        "source": dict(source) if source is not None else None,
        "publisher_reconciliation": (
            dict(publisher_reconciliation)
            if publisher_reconciliation is not None
            else None
        ),
    }


def validate_acquisition_cohort_handoff(
    cohort: Mapping[str, Any], acquisition: Mapping[str, Any]
) -> None:
    """Validate the plain-JSON acquisition record behind a warm-up cohort."""

    if not isinstance(cohort, Mapping) or not isinstance(acquisition, Mapping):
        raise ValueError("cohort and acquisition provenance must be JSON objects")
    if acquisition.get("schema") != ACQUISITION_SCHEMA:
        raise ValueError("cohort requires a temporal acquisition record")
    if not _same_json(acquisition.get("cohort"), cohort):
        raise ValueError("cohort does not match its acquisition record")
    provenance = cohort.get("provenance")
    if not isinstance(provenance, Mapping) or set(provenance) != _COHORT_PROVENANCE_KEYS:
        raise ValueError("cohort has invalid acquisition provenance")
    if not _same_json(acquisition.get("warmup_handoff"), provenance):
        raise ValueError("cohort provenance does not match its acquisition handoff")
    papers = cohort.get("papers")
    if not isinstance(papers, list):
        raise ValueError("cohort papers must be an array")
    selected_count = provenance.get("selected_count")
    if (
        isinstance(selected_count, bool)
        or not isinstance(selected_count, int)
        or selected_count != len(papers)
    ):
        raise ValueError("cohort selected_count does not match its papers")
    if provenance.get("acquisition_schema") != ACQUISITION_SCHEMA:
        raise ValueError("cohort provenance names an unknown acquisition schema")
    if provenance.get("retrieved_at") != acquisition.get("retrieved_at"):
        raise ValueError("cohort retrieved_at does not match its acquisition record")
    selection = acquisition.get("selection")
    if not isinstance(selection, Mapping) or provenance.get(
        "selection_policy"
    ) != selection.get("policy"):
        raise ValueError("cohort selection policy does not match its acquisition record")
    ready = 1 <= len(papers) <= MAX_COORDINATOR_COHORT_SIZE
    expected_status = (
        "coordinator_ready"
        if ready
        else "empty_cohort"
        if not papers
        else "cohort_exceeds_coordinator_limit"
    )
    if (
        provenance.get("coordinator_ready") is not ready
        or provenance.get("handoff_status") != expected_status
    ):
        raise ValueError("cohort coordinator-readiness metadata is inconsistent")
    if not ready:
        raise ValueError("acquisition cohort is not coordinator-ready")

    results = acquisition.get("paper_results")
    if not isinstance(results, list):
        raise ValueError("acquisition paper_results must be an array")
    selected_results = []
    actual_selection_counts = Counter()
    for result in results:
        if not isinstance(result, Mapping):
            raise ValueError("acquisition paper result must be an object")
        result_selection = result.get("selection")
        if not isinstance(result_selection, Mapping):
            raise ValueError("acquisition paper result has no selection status")
        status = result_selection.get("status")
        if status not in {"selected", "not_selected", "ineligible"}:
            raise ValueError("acquisition paper result has an unknown selection status")
        actual_selection_counts[status] += 1
        if result_selection.get("policy") != selection.get("policy"):
            raise ValueError("paper selection policy differs from acquisition policy")
        if status == "selected":
            if (
                result_selection.get("selected") is not True
                or result.get("disposition") != "source_acquired"
                or not isinstance(result.get("cohort_entry"), Mapping)
            ):
                raise ValueError("selected paper has inconsistent acquisition state")
            reconciliation = result.get("publisher_reconciliation")
            source = result.get("source")
            if (
                not isinstance(reconciliation, Mapping)
                or reconciliation.get("verification_status")
                != "publisher_reconciled"
                or not isinstance(source, Mapping)
                or source.get("publisher_verification_status")
                != "publisher_reconciled"
            ):
                raise ValueError("selected paper lacks publisher reconciliation")
            selected_results.append(result)
        else:
            if result_selection.get("selected") is not False:
                raise ValueError("non-selected paper has inconsistent selection status")
            if result.get("cohort_entry") is not None:
                raise ValueError("non-selected paper cannot retain a cohort entry")
            if status == "not_selected" and result.get("disposition") != "source_acquired":
                raise ValueError("not-selected paper was not successfully acquired")
            if status == "ineligible" and result.get("disposition") == "source_acquired":
                raise ValueError("acquired source must receive a selection outcome")
    selected_entries = {
        item["cohort_entry"].get("journal_doi"): dict(item["cohort_entry"])
        for item in selected_results
    }
    if (
        len(selected_entries) != len(papers)
        or any(
            not isinstance(paper, Mapping)
            or not _same_json(
                selected_entries.get(paper.get("journal_doi")), paper
            )
            for paper in papers
        )
    ):
        raise ValueError("selected paper results do not exactly reproduce the cohort")
    counts = acquisition.get("selection_counts")
    expected_counts = {
        "ineligible": actual_selection_counts.get("ineligible", 0),
        "not_selected": actual_selection_counts.get("not_selected", 0),
        "selected": actual_selection_counts.get("selected", 0),
    }
    if not isinstance(counts, Mapping) or not _same_json(
        dict(counts), expected_counts
    ):
        raise ValueError("selection counts do not match the cohort")


def _canonical_reconciliations(
    payload: Optional[Mapping[str, Any]],
) -> Mapping[str, Any]:
    if payload is None:
        return {}
    if not isinstance(payload, Mapping):
        raise ValueError("publisher_reconciliation must be a DOI-keyed JSON object")
    result = {}
    for raw_doi, record in payload.items():
        if not isinstance(raw_doi, str):
            raise ValueError("publisher reconciliation DOI keys must be text")
        doi = canonicalize_doi(raw_doi)
        if doi in result:
            raise ValueError("duplicate canonical publisher reconciliation DOI: %s" % doi)
        result[doi] = record
    return result


def _canonical_manual_linkage_reviews(
    payload: Optional[Mapping[str, Any]],
) -> Mapping[str, Mapping[str, str]]:
    """Validate frozen positive record-linkage decisions keyed by journal DOI."""

    if payload is None:
        return {}
    if not isinstance(payload, Mapping):
        raise ValueError("manual_linkage_reviews must be a DOI-keyed JSON object")
    required = {
        "arxiv_versioned_id",
        "decision",
        "evidence_locator",
        "rationale",
        "reviewer",
    }
    result = {}
    for raw_doi, raw_review in payload.items():
        if not isinstance(raw_doi, str):
            raise ValueError("manual linkage review DOI keys must be text")
        doi = canonicalize_doi(raw_doi)
        if doi in result:
            raise ValueError("duplicate canonical manual linkage review DOI: %s" % doi)
        if not isinstance(raw_review, Mapping) or set(raw_review) != required:
            raise ValueError(
                "manual linkage review for %s must contain exactly %s"
                % (doi, ", ".join(sorted(required)))
            )
        values = {}
        for field in ("evidence_locator", "rationale", "reviewer"):
            value = raw_review[field]
            if not isinstance(value, str) or not value.strip():
                raise ValueError(
                    "manual linkage review %s for %s must be non-empty text"
                    % (field, doi)
                )
            values[field] = value.strip()
        if raw_review["decision"] != "match":
            raise ValueError(
                "manual linkage review decision for %s must be match" % doi
            )
        values["decision"] = "match"
        values["arxiv_versioned_id"] = parse_versioned_arxiv_id(
            raw_review["arxiv_versioned_id"]
        )
        result[doi] = values
    return result


def _canonical_figure_evidence_addenda(
    payload: Optional[Mapping[str, Any]],
) -> Mapping[str, FigureEvidenceAddendum]:
    if payload is None:
        return {}
    if not isinstance(payload, Mapping):
        raise ValueError("figure_evidence_addenda must be a DOI-keyed JSON object")
    result = {}
    for raw_doi, raw_addendum in payload.items():
        if not isinstance(raw_doi, str):
            raise ValueError("figure evidence DOI keys must be text")
        doi = canonicalize_doi(raw_doi)
        if doi in result:
            raise ValueError("duplicate canonical figure evidence DOI: %s" % doi)
        if not isinstance(raw_addendum, Mapping) or set(raw_addendum) != {
            "entries",
            "reviewer",
        }:
            raise ValueError(
                "figure evidence for %s must contain exactly reviewer and entries"
                % doi
            )
        reviewer = raw_addendum["reviewer"]
        raw_entries = raw_addendum["entries"]
        if not isinstance(raw_entries, list):
            raise ValueError("figure evidence entries for %s must be an array" % doi)
        entries = []
        for index, raw_entry in enumerate(raw_entries):
            if not isinstance(raw_entry, Mapping) or set(raw_entry) != {
                "semantics",
                "source_asset",
                "transcription",
            }:
                raise ValueError(
                    "figure evidence entry %d for %s has invalid fields"
                    % (index, doi)
                )
            values = {}
            for key in ("semantics", "source_asset", "transcription"):
                value = raw_entry[key]
                if not isinstance(value, str) or not value.strip():
                    raise ValueError(
                        "figure evidence %s for %s must be non-empty text"
                        % (key, doi)
                    )
                values[key] = value.strip()
            entries.append(FigureEvidenceEntry(**values))
        reviewer_text = reviewer.strip() if isinstance(reviewer, str) else reviewer
        result[doi] = FigureEvidenceAddendum(
            reviewer=reviewer_text,
            entries=tuple(entries),
        )
    return result


def _figure_evidence_payload(
    addenda: Mapping[str, FigureEvidenceAddendum],
) -> Mapping[str, Any]:
    return {
        doi: {
            "entries": [
                {
                    "semantics": entry.semantics,
                    "source_asset": entry.source_asset,
                    "transcription": entry.transcription,
                }
                for entry in addendum.entries
            ],
            "reviewer": addendum.reviewer,
        }
        for doi, addendum in sorted(addenda.items())
    }


def _publisher_record(
    paper: CensusPaper,
    reconciliations: Mapping[str, Any],
) -> Tuple[Optional[Mapping[str, Any]], Optional[str], Optional[str]]:
    raw = reconciliations.get(paper.doi)
    if raw is None:
        return (
            None,
            "publisher_reconciliation_required",
            "paper.publisher_reconciliation_required",
        )
    if not isinstance(raw, Mapping):
        return None, "publisher_reconciliation_invalid", "paper.publisher_record_not_object"
    required = {
        "category",
        "original_research",
        "publication_date",
        "withdrawn_or_retracted",
    }
    missing = sorted(required - set(raw))
    if missing:
        return (
            dict(raw),
            "publisher_reconciliation_invalid",
            "paper.publisher_record_missing_%s" % "_".join(missing),
        )
    if not isinstance(raw["category"], str) or not raw["category"].strip():
        return dict(raw), "publisher_reconciliation_invalid", "paper.publisher_category_invalid"
    if not isinstance(raw["original_research"], bool):
        return dict(raw), "publisher_reconciliation_invalid", "paper.publisher_original_research_invalid"
    if not isinstance(raw["withdrawn_or_retracted"], bool):
        return dict(raw), "publisher_reconciliation_invalid", "paper.publisher_retraction_status_invalid"
    raw_date = raw["publication_date"]
    if not isinstance(raw_date, str):
        return dict(raw), "publisher_reconciliation_invalid", "paper.publisher_publication_date_invalid"
    try:
        publication_date = date.fromisoformat(raw_date)
    except ValueError:
        return dict(raw), "publisher_reconciliation_invalid", "paper.publisher_publication_date_invalid"
    if publication_date.isoformat() != raw_date:
        return dict(raw), "publisher_reconciliation_invalid", "paper.publisher_publication_date_invalid"
    record = dict(raw)
    record["category"] = raw["category"].strip()
    record["publication_date"] = publication_date.isoformat()
    record["verification_status"] = "publisher_reconciled"
    record["crossref_publication_date"] = paper.publication_date.isoformat()
    return record, None, None


def acquire_census_snapshot(
    snapshot: CensusSnapshot,
    *,
    start: date,
    end: date,
    venues: Iterable[str],
    output_directory: Union[str, Path],
    retrieved_at: Optional[datetime] = None,
    earliest_public_not_before: Optional[date] = None,
    selection_policy: str = "all",
    cohort_limit: Optional[int] = None,
    max_results: int = 20,
    timeout: float = 60.0,
    arxiv_transport: Optional[ArxivTransport] = None,
    source_transport: Optional[ArxivTransport] = None,
    pause: Optional[Pause] = None,
    request_interval_s: float = 3.0,
    publisher_reconciliation: Optional[Mapping[str, Any]] = None,
    figure_evidence_addenda: Optional[Mapping[str, Any]] = None,
    manual_linkage_reviews: Optional[Mapping[str, Any]] = None,
) -> Mapping[str, Any]:
    """Acquire fixed sources and emit the only cohort rows downstream may use.

    Identity, dates, TeX availability, and source paths are derived from the
    journal record, resolved arXiv entry, and successfully decoded source
    bundle.  The caller cannot provide those fields independently.
    """

    if end < start:
        raise ValueError("end must not precede start")
    selected_venues: Tuple[str, ...] = tuple(venues)
    if not selected_venues or any(item not in TARGET_VENUES for item in selected_venues):
        raise ValueError("venues must be a non-empty subset of target venues")
    if selection_policy not in {"all", "citation_rank"}:
        raise ValueError("selection_policy must be all or citation_rank")
    if cohort_limit is not None and (
        isinstance(cohort_limit, bool)
        or not isinstance(cohort_limit, int)
        or cohort_limit < 1
    ):
        raise ValueError("cohort_limit must be null or a positive integer")
    if selection_policy == "all" and cohort_limit is not None:
        raise ValueError("cohort_limit requires selection_policy=citation_rank")
    if (
        isinstance(request_interval_s, bool)
        or not isinstance(request_interval_s, (int, float))
        or request_interval_s < 0
    ):
        raise ValueError("request_interval_s must be non-negative")
    if pause is None and arxiv_transport is None:
        pause = time.sleep

    acquired_at = _utc_timestamp(retrieved_at)
    output = Path(output_directory)
    output.mkdir(parents=True, exist_ok=False)
    papers_directory = output / "papers"
    papers_directory.mkdir()
    results = []
    acquired_entries = []
    used_paper_ids = set()
    reconciliations = _canonical_reconciliations(publisher_reconciliation)
    figure_addenda = _canonical_figure_evidence_addenda(
        figure_evidence_addenda
    )
    linkage_reviews = _canonical_manual_linkage_reviews(manual_linkage_reviews)
    unknown_addendum_dois = sorted(
        set(figure_addenda) - {paper.doi for paper in snapshot.papers}
    )
    if unknown_addendum_dois:
        raise ValueError(
            "figure evidence DOI is not present in the census snapshot: %s"
            % ", ".join(unknown_addendum_dois)
        )
    unknown_linkage_review_dois = sorted(
        set(linkage_reviews) - {paper.doi for paper in snapshot.papers}
    )
    if unknown_linkage_review_dois:
        raise ValueError(
            "manual linkage review DOI is not present in the census snapshot: %s"
            % ", ".join(unknown_linkage_review_dois)
        )

    papers = snapshot.papers
    for index, paper in enumerate(papers):
        if paper.venue not in selected_venues or not start <= paper.publication_date <= end:
            results.append(
                _paper_result(
                    paper,
                    "outside_acquisition_window",
                    reason_code="paper.outside_window",
                )
            )
            continue

        research_rejection = original_research_rejection_code(
            venue=paper.venue,
            doi=paper.doi,
            article_type=paper.article_type,
        )
        if research_rejection is not None:
            results.append(
                _paper_result(
                    paper,
                    "not_original_research",
                    reason_code=research_rejection,
                )
            )
            continue

        publisher_record, publisher_disposition, publisher_reason = _publisher_record(
            paper, reconciliations
        )
        if publisher_disposition is not None:
            results.append(
                _paper_result(
                    paper,
                    publisher_disposition,
                    reason_code=publisher_reason,
                    publisher_reconciliation=publisher_record,
                )
            )
            continue
        assert publisher_record is not None
        publication_date = date.fromisoformat(publisher_record["publication_date"])
        if not start <= publication_date <= end:
            results.append(
                _paper_result(
                    paper,
                    "outside_acquisition_window",
                    reason_code="paper.publisher_date_outside_window",
                    publisher_reconciliation=publisher_record,
                )
            )
            continue
        if publisher_record["original_research"] is not True:
            results.append(
                _paper_result(
                    paper,
                    "not_original_research",
                    reason_code="paper.publisher_category_not_original_research",
                    publisher_reconciliation=publisher_record,
                )
            )
            continue
        if publisher_record["withdrawn_or_retracted"] is True:
            results.append(
                _paper_result(
                    paper,
                    "withdrawn_or_retracted",
                    reason_code="paper.publisher_withdrawn_or_retracted",
                    publisher_reconciliation=publisher_record,
                )
            )
            continue
        if selection_policy == "citation_rank" and paper.citation_count is None:
            results.append(
                _paper_result(
                    paper,
                    "citation_snapshot_incomplete",
                    reason_code="paper.citation_count_missing_for_ranking",
                    publisher_reconciliation=publisher_record,
                )
            )
            continue

        resolution = resolve_arxiv_paper(
            paper,
            max_results=max_results,
            timeout=timeout,
            transport=arxiv_transport,
            pause=pause,
            request_interval_s=request_interval_s,
        )
        automatic_resolution_payload = arxiv_resolution_to_payload(resolution)
        linkage_review = linkage_reviews.get(paper.doi)
        linkage_review_applied = False
        if resolution.status != "resolved" and linkage_review is not None:
            if pause is not None:
                pause(float(request_interval_s))
            resolution = resolve_manually_reviewed_arxiv_paper(
                paper,
                versioned_id=linkage_review["arxiv_versioned_id"],
                timeout=timeout,
                transport=arxiv_transport,
            )
            linkage_review_applied = True
        elif resolution.status == "resolved" and linkage_review is not None:
            assert resolution.paper is not None
            automatic_id = resolution.paper.versioned_id
            reviewed_id = linkage_review["arxiv_versioned_id"]
            if arxiv_base_id(automatic_id) != arxiv_base_id(reviewed_id):
                raise ValueError(
                    "manual linkage review for %s conflicts with automatic arXiv work identity"
                    % paper.doi
                )
            if automatic_id.casefold() != reviewed_id.casefold():
                if pause is not None:
                    pause(float(request_interval_s))
                resolution = resolve_manually_reviewed_arxiv_paper(
                    paper,
                    versioned_id=reviewed_id,
                    timeout=timeout,
                    transport=arxiv_transport,
                )
                linkage_review_applied = True
        resolution_payload = arxiv_resolution_to_payload(resolution)
        if linkage_review is not None:
            resolution_payload["manual_linkage_review"] = dict(linkage_review)
            resolution_payload["manual_linkage_review_applied"] = (
                linkage_review_applied
            )
            resolution_payload["automatic_resolution"] = automatic_resolution_payload
        if resolution.status != "resolved" or resolution.paper is None:
            results.append(
                _paper_result(
                    paper,
                    "arxiv_%s" % resolution.status,
                    resolution=resolution_payload,
                    publisher_reconciliation=publisher_record,
                )
            )
            if pause is not None and index + 1 < len(papers):
                pause(float(request_interval_s))
            continue

        arxiv_paper = resolution.paper
        paper_id = _paper_id(arxiv_paper.versioned_id)
        if paper_id in used_paper_ids:
            results.append(
                _paper_result(
                    paper,
                    "duplicate_arxiv_source",
                    reason_code="paper.duplicate_arxiv_source",
                    resolution=resolution_payload,
                    publisher_reconciliation=publisher_record,
                )
            )
            if pause is not None and index + 1 < len(papers):
                pause(float(request_interval_s))
            continue
        earliest_public_date = min(
            publication_date,
            arxiv_paper.first_submitted_at.date(),
        )
        if (
            earliest_public_not_before is not None
            and earliest_public_date < earliest_public_not_before
        ):
            results.append(
                _paper_result(
                    paper,
                    "preexisting_public_version",
                    reason_code="paper.preexisting_public_version",
                    resolution=resolution_payload,
                    publisher_reconciliation=publisher_record,
                )
            )
            if pause is not None and index + 1 < len(papers):
                pause(float(request_interval_s))
            continue
        if pause is not None:
            pause(float(request_interval_s))
        try:
            bundle = download_arxiv_source(
                arxiv_paper,
                timeout=timeout,
                transport=source_transport,
            )
            figure_addendum = figure_addenda.get(paper.doi)
            if figure_addendum is not None:
                bundle = append_figure_evidence_addendum(
                    bundle,
                    figure_addendum,
                )
        except NoTexSourceError as exc:
            results.append(
                _paper_result(
                    paper,
                    "no_tex_source",
                    reason_code="paper.latex_unavailable",
                    resolution=resolution_payload,
                    source={"detail": str(exc)},
                    publisher_reconciliation=publisher_record,
                )
            )
            if pause is not None and index + 1 < len(papers):
                pause(float(request_interval_s))
            continue
        except TexDecodeError as exc:
            results.append(
                _paper_result(
                    paper,
                    "tex_decode_failed",
                    reason_code="paper.tex_decode_failed",
                    resolution=resolution_payload,
                    source={"detail": str(exc)},
                    publisher_reconciliation=publisher_record,
                )
            )
            if pause is not None and index + 1 < len(papers):
                pause(float(request_interval_s))
            continue
        except ValueError as exc:
            results.append(
                _paper_result(
                    paper,
                    "source_invalid",
                    reason_code="paper.source_invalid",
                    resolution=resolution_payload,
                    source={"detail": str(exc)},
                    publisher_reconciliation=publisher_record,
                )
            )
            if pause is not None and index + 1 < len(papers):
                pause(float(request_interval_s))
            continue

        used_paper_ids.add(paper_id)
        paper_directory = papers_directory / paper_id
        paper_directory.mkdir()
        tex_path = paper_directory / "source.tex"
        tex_path.write_text(bundle.merged_text, encoding="utf-8")
        relative_tex_path = tex_path.relative_to(output).as_posix()
        source_packet_path = paper_directory / "source_packet.txt"
        source_packet_path.write_text(
            bundle.source_packet_text,
            encoding="utf-8",
        )
        relative_source_packet_path = source_packet_path.relative_to(
            output
        ).as_posix()
        cohort_entry = {
            "article_type": paper.article_type,
            "arxiv_versioned_id": arxiv_paper.versioned_id,
            "citation_count": paper.citation_count,
            "earliest_public_date": earliest_public_date.isoformat(),
            "journal_doi": paper.doi,
            "latex_available": True,
            "paper_id": paper_id,
            "publication_date": publication_date.isoformat(),
            "source_citation": _source_citation(paper, publication_date),
            "source_packet_path": relative_source_packet_path,
            "tex_path": relative_tex_path,
            "title": paper.title,
            "venue": paper.venue,
            "withdrawn_or_retracted": publisher_record["withdrawn_or_retracted"],
        }
        source_payload = {
            "arxiv_versioned_id": arxiv_paper.versioned_id,
            "entry_url": arxiv_paper.entry_url,
            "first_submitted_at": arxiv_paper.first_submitted_at.isoformat(),
            "figure_evidence_addendum": (
                {
                    "reviewer": figure_addendum.reviewer,
                    "source_assets": [
                        item.source_asset for item in figure_addendum.entries
                    ],
                }
                if figure_addendum is not None
                else None
            ),
            "member_count": len(bundle.files),
            "members": [
                {
                    "merged_line_end": item.merged_line_end,
                    "merged_line_start": item.merged_line_start,
                    "path": item.path,
                }
                for item in bundle.member_locators
            ],
            "publisher_verification_status": "publisher_reconciled",
            "source_packet_member_count": len(bundle.source_packet_files),
            "source_packet_members": [
                {
                    "file_line_end": item.file_line_end,
                    "file_line_start": item.file_line_start,
                    "format": item.format,
                    "global_line_end": item.global_line_end,
                    "global_line_start": item.global_line_start,
                    "path": item.path,
                }
                for item in bundle.packet_member_locators
            ],
            "source_packet_path": relative_source_packet_path,
            "tex_path": relative_tex_path,
            "version_updated_at": arxiv_paper.version_updated_at.isoformat(),
        }
        result = _paper_result(
            paper,
            "source_acquired",
            resolution=resolution_payload,
            source=source_payload,
            cohort_entry=cohort_entry,
            publisher_reconciliation=publisher_record,
        )
        results.append(result)
        acquired_entries.append((cohort_entry, result))
        if pause is not None and index + 1 < len(papers):
            pause(float(request_interval_s))

    if selection_policy == "citation_rank":
        ordered = sorted(
            acquired_entries,
            key=lambda item: (
                -item[0]["citation_count"],
                item[0]["publication_date"],
                item[0]["journal_doi"],
            ),
        )
        selected_entries = ordered if cohort_limit is None else ordered[:cohort_limit]
    else:
        ordered = acquired_entries
        selected_entries = ordered
    selected_dois = {item[0]["journal_doi"] for item in selected_entries}
    for result in results:
        result["selection"] = {
            "policy": selection_policy,
            "rank": None,
            "selected": False,
            "status": "ineligible",
        }
    for rank, (entry, result) in enumerate(ordered, start=1):
        selected = entry["journal_doi"] in selected_dois
        result["selection"] = {
            "policy": selection_policy,
            "rank": rank if selection_policy == "citation_rank" else None,
            "selected": selected,
            "status": "selected" if selected else "not_selected",
        }
        if not selected:
            result["cohort_entry"] = None
        _write_json(
            papers_directory / entry["paper_id"] / "paper.json",
            result,
        )

    selected_count = len(selected_entries)
    coordinator_ready = 1 <= selected_count <= MAX_COORDINATOR_COHORT_SIZE
    handoff_status = (
        "coordinator_ready"
        if coordinator_ready
        else "empty_cohort"
        if selected_count == 0
        else "cohort_exceeds_coordinator_limit"
    )
    provenance = {
        "acquisition_schema": ACQUISITION_SCHEMA,
        "coordinator_ready": coordinator_ready,
        "handoff_status": handoff_status,
        "retrieved_at": acquired_at.isoformat(),
        "selected_count": selected_count,
        "selection_policy": selection_policy,
    }
    cohort = {
        "papers": [item[0] for item in selected_entries],
        "provenance": provenance,
        "window": {
            "earliest_public_not_before": (
                earliest_public_not_before.isoformat()
                if earliest_public_not_before is not None
                else None
            ),
            "end": end.isoformat(),
            "start": start.isoformat(),
        },
    }
    counts = Counter(item["disposition"] for item in results)
    selection_counts = Counter(item["selection"]["status"] for item in results)
    acquisition = {
        "axes": {
            "disposition": "source acquisition outcome; not cohort membership",
            "selection": "cohort membership after the configured selection policy",
        },
        "cohort": cohort,
        "census": census_snapshot_to_payload(snapshot),
        "citation_snapshot_at": acquired_at.isoformat(),
        "disposition_counts": dict(sorted(counts.items())),
        "identity": {
            "journal_key": "canonical_doi",
            "arxiv_key": "versioned_id",
            "automatic_match_methods": ["crossref_has_preprint_doi", "doi"],
            "reviewed_match_method": "manual_review",
            "manual_review_candidate_sources": [
                "crossref_non_doi_relation",
                "arxiv_title_search",
                "search_engine",
            ],
            "match_rule": (
                "crossref_arxiv_doi_relation_or_unique_exact_arxiv_journal_doi"
            ),
        },
        "figure_evidence_addenda": _figure_evidence_payload(figure_addenda),
        "manual_linkage_reviews": {
            "application_rule": (
                "used when automatic identity resolution is unresolved or to select "
                "a reviewed version of the same arXiv work"
            ),
            "records": dict(linkage_reviews),
        },
        "paper_results": results,
        "publisher_reconciliation": {
            "records": dict(reconciliations),
            "required_for_cohort": True,
        },
        "query": {
            "arxiv_max_results": max_results,
            "arxiv_recall": (
                "Crossref has-preprint id_list candidate retrieval first; non-DOI relation "
                "targets require manual review unless independently confirmed by exact journal DOI; "
                "otherwise separate DOI-string and title-only API requests for plain-text titles; "
                "embedded-markup titles use DOI-string recall only"
            ),
            "general_search_engine": (
                "offline candidate retrieval only; never automatic identity adjudication"
            ),
        },
        "retrieved_at": acquired_at.isoformat(),
        "schema": ACQUISITION_SCHEMA,
        "selection": {
            "cohort_limit": cohort_limit,
            "policy": selection_policy,
        },
        "selection_counts": {
            "ineligible": selection_counts.get("ineligible", 0),
            "not_selected": selection_counts.get("not_selected", 0),
            "selected": selection_counts.get("selected", 0),
        },
        "warmup_handoff": provenance,
        "window": {
            "end": end.isoformat(),
            "start": start.isoformat(),
            "venues": list(selected_venues),
        },
    }
    _write_json(output / "acquisition.json", acquisition)
    _write_json(output / "cohort.json", cohort)
    return acquisition


def acquire_temporal_window(
    *,
    start: date,
    end: date,
    output_directory: Union[str, Path],
    venues: Iterable[str] = TARGET_VENUES,
    rows: int = 1000,
    mailto: Optional[str] = None,
    retrieved_at: Optional[datetime] = None,
    earliest_public_not_before: Optional[date] = None,
    selection_policy: str = "all",
    cohort_limit: Optional[int] = None,
    max_results: int = 20,
    timeout: float = 60.0,
    crossref_transport: Optional[CrossrefTransport] = None,
    arxiv_transport: Optional[ArxivTransport] = None,
    source_transport: Optional[ArxivTransport] = None,
    pause: Optional[Pause] = None,
    request_interval_s: float = 3.0,
    publisher_reconciliation: Optional[Mapping[str, Any]] = None,
    figure_evidence_addenda: Optional[Mapping[str, Any]] = None,
    manual_linkage_reviews: Optional[Mapping[str, Any]] = None,
) -> Mapping[str, Any]:
    """Run census, linkage, source acquisition, and cohort derivation once."""

    selected_venues = tuple(venues)
    snapshot = collect_crossref_census_snapshot(
        start=start,
        end=end,
        venues=selected_venues,
        rows=rows,
        mailto=mailto,
        timeout=timeout,
        transport=crossref_transport,
    )
    return acquire_census_snapshot(
        snapshot,
        start=start,
        end=end,
        venues=selected_venues,
        output_directory=output_directory,
        retrieved_at=retrieved_at,
        earliest_public_not_before=earliest_public_not_before,
        selection_policy=selection_policy,
        cohort_limit=cohort_limit,
        max_results=max_results,
        timeout=timeout,
        arxiv_transport=arxiv_transport,
        source_transport=source_transport,
        pause=pause,
        request_interval_s=request_interval_s,
        publisher_reconciliation=publisher_reconciliation,
        figure_evidence_addenda=figure_evidence_addenda,
        manual_linkage_reviews=manual_linkage_reviews,
    )


__all__ = [
    "ACQUISITION_SCHEMA",
    "acquire_census_snapshot",
    "acquire_temporal_window",
    "validate_acquisition_cohort_handoff",
]
