"""Metadata enrichment and prefiltering after a raw paper census."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import Enum
from typing import Iterable, Mapping, Optional, Tuple


TARGET_VENUES = ("Nature", "Science", "Physical Review Letters")


@dataclass(frozen=True)
class SourcePaper:
    doi: str
    title: str
    venue: str
    publication_date: date
    earliest_public_date: date
    article_type: str
    citation_count: Optional[int]
    latex_available: bool
    withdrawn_or_retracted: bool = False


class PaperRejectionCode(str, Enum):
    WRONG_VENUE = "paper.wrong_venue"
    OUTSIDE_WINDOW = "paper.outside_window"
    PREEXISTING_PUBLIC_VERSION = "paper.preexisting_public_version"
    NOT_ORIGINAL_RESEARCH = "paper.not_original_research"
    LATEX_UNAVAILABLE = "paper.latex_unavailable"
    WITHDRAWN_OR_RETRACTED = "paper.withdrawn_or_retracted"


NATURE_MAGAZINE_DOI_PREFIX = "10.1038/d41586-"


def original_research_rejection_code(
    *, venue: str, doi: str, article_type: str
) -> Optional[str]:
    """Return a deterministic reason when metadata clearly excludes research.

    Crossref's broad ``journal-article`` type also covers Nature news,
    editorials, and other magazine content.  The ``d41586`` DOI namespace is a
    venue-specific, objective exclusion.  Records not rejected here remain
    candidates for later publisher reconciliation; this helper does not claim
    that metadata alone proves original research.
    """

    if article_type != "journal-article":
        return "paper.not_original_research.article_type"
    if venue == "Nature" and doi.lower().startswith(NATURE_MAGAZINE_DOI_PREFIX):
        return "paper.not_original_research.nature_magazine_content"
    return None


@dataclass(frozen=True)
class PaperPrefilterResult:
    accepted: Tuple[SourcePaper, ...]
    rejected: Mapping[str, Tuple[str, ...]]


def prefilter_papers(
    papers: Iterable[SourcePaper],
    *,
    start: date,
    end: date,
    earliest_public_not_before: Optional[date] = None,
) -> PaperPrefilterResult:
    """Apply metadata-only gates before expensive LaTeX extraction."""

    if end < start:
        raise ValueError("end must not precede start")
    accepted = []
    rejected = {}
    for paper in papers:
        reasons = []
        if paper.venue not in TARGET_VENUES:
            reasons.append(PaperRejectionCode.WRONG_VENUE.value)
        if not start <= paper.publication_date <= end:
            reasons.append(PaperRejectionCode.OUTSIDE_WINDOW.value)
        if (
            earliest_public_not_before is not None
            and paper.earliest_public_date < earliest_public_not_before
        ):
            reasons.append(PaperRejectionCode.PREEXISTING_PUBLIC_VERSION.value)
        if original_research_rejection_code(
            venue=paper.venue,
            doi=paper.doi,
            article_type=paper.article_type,
        ) is not None:
            reasons.append(PaperRejectionCode.NOT_ORIGINAL_RESEARCH.value)
        if not paper.latex_available:
            reasons.append(PaperRejectionCode.LATEX_UNAVAILABLE.value)
        if paper.withdrawn_or_retracted:
            reasons.append(PaperRejectionCode.WITHDRAWN_OR_RETRACTED.value)
        if reasons:
            rejected[paper.doi] = tuple(reasons)
        else:
            accepted.append(paper)
    return PaperPrefilterResult(tuple(accepted), rejected)


def rank_papers(papers: Iterable[SourcePaper], *, limit: int = 30) -> Tuple[SourcePaper, ...]:
    """Rank an already eligible cohort by frozen citation count, then DOI."""

    if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
        raise ValueError("limit must be a positive integer")
    materialized = tuple(papers)
    if any(item.citation_count is None for item in materialized):
        raise ValueError("citation ranking requires a count for every paper")
    return tuple(
        sorted(
            materialized,
            key=lambda item: (
                -int(item.citation_count),
                item.publication_date,
                item.doi,
            ),
        )[:limit]
    )


__all__ = [
    "PaperPrefilterResult",
    "PaperRejectionCode",
    "NATURE_MAGAZINE_DOI_PREFIX",
    "SourcePaper",
    "original_research_rejection_code",
    "TARGET_VENUES",
    "prefilter_papers",
    "rank_papers",
]
