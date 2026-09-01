"""Fixed-window Crossref census for the temporal case pipeline.

One call enumerates every Crossref journal article returned for an inclusive
date window.  It is a snapshot operation, not a daemon or scheduler.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from typing import Any, Callable, Dict, Iterable, Mapping, Optional, Sequence, Tuple
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

from .metadata import TARGET_VENUES


CROSSREF_API_URL = "https://api.crossref.org"
CROSSREF_VENUE_ISSNS: Mapping[str, Tuple[str, ...]] = {
    "Nature": ("0028-0836", "1476-4687"),
    "Science": ("0036-8075", "1095-9203"),
    "Physical Review Letters": ("0031-9007", "1079-7114"),
}

CrossrefTransport = Callable[[str, float], Mapping[str, Any]]


@dataclass(frozen=True)
class CensusPaper:
    """Metadata known at census time, without downstream enrichment fields."""

    doi: str
    title: str
    venue: str
    publication_date: date
    article_type: str
    citation_count: Optional[int]
    url: Optional[str]
    first_author: Optional[str] = None
    first_author_family: Optional[str] = None


@dataclass(frozen=True)
class CensusRecordDisposition:
    """One Crossref item excluded without aborting the rest of the census."""

    disposition: str
    venue: str
    issn: str
    doi: Optional[str]
    detail: str


@dataclass(frozen=True)
class CensusDuplicateConflict:
    """Metadata fields that disagreed across records sharing one DOI."""

    doi: str
    fields: Tuple[str, ...]
    selected_issn: str
    alternate_issn: str
    selected_record: CensusPaper
    alternate_record: CensusPaper


@dataclass(frozen=True)
class CensusSnapshot:
    """Usable papers plus explicit item-level exclusions and DOI conflicts."""

    papers: Tuple[CensusPaper, ...]
    dispositions: Tuple[CensusRecordDisposition, ...]
    duplicate_conflicts: Tuple[CensusDuplicateConflict, ...]


def canonicalize_doi(value: str) -> str:
    """Return the stable DOI key used to deduplicate Crossref pages."""

    doi = value.strip()
    lowered = doi.lower()
    for prefix in (
        "https://doi.org/",
        "http://doi.org/",
        "https://dx.doi.org/",
        "http://dx.doi.org/",
        "doi:",
    ):
        if lowered.startswith(prefix):
            doi = doi[len(prefix) :].strip()
            break
    doi = doi.lower()
    if not doi:
        raise ValueError("Crossref item has an empty DOI")
    return doi


def census_paper_to_payload(paper: CensusPaper) -> Mapping[str, Any]:
    """Convert one census record to its stable JSON representation."""

    return {
        "article_type": paper.article_type,
        "citation_count": paper.citation_count,
        "doi": paper.doi,
        "first_author": paper.first_author,
        "first_author_family": paper.first_author_family,
        "publication_date": paper.publication_date.isoformat(),
        "title": paper.title,
        "url": paper.url,
        "venue": paper.venue,
    }


def census_snapshot_to_payload(snapshot: CensusSnapshot) -> Mapping[str, Any]:
    """Convert a census snapshot to a plain, reviewable JSON object."""

    return {
        "duplicate_conflicts": [
            {
                "alternate_issn": item.alternate_issn,
                "doi": item.doi,
                "fields": list(item.fields),
                "selected_issn": item.selected_issn,
                "selected_record": census_paper_to_payload(item.selected_record),
                "alternate_record": census_paper_to_payload(item.alternate_record),
            }
            for item in snapshot.duplicate_conflicts
        ],
        "papers": [census_paper_to_payload(paper) for paper in snapshot.papers],
        "record_dispositions": [
            {
                "detail": item.detail,
                "disposition": item.disposition,
                "doi": item.doi,
                "issn": item.issn,
                "venue": item.venue,
            }
            for item in snapshot.dispositions
        ],
    }


def census_paper_from_payload(payload: Mapping[str, Any]) -> CensusPaper:
    """Parse the exact JSON record emitted by :func:`census_paper_to_payload`."""

    if not isinstance(payload, Mapping):
        raise ValueError("census paper must be a JSON object")
    expected = {
        "article_type",
        "citation_count",
        "doi",
        "first_author",
        "first_author_family",
        "publication_date",
        "title",
        "url",
        "venue",
    }
    if any(not isinstance(key, str) for key in payload):
        raise ValueError("census paper field names must be text")
    actual = set(payload)
    missing = sorted(expected - actual)
    extra = sorted(actual - expected)
    if missing:
        raise ValueError("census paper is missing fields: %s" % ", ".join(missing))
    if extra:
        raise ValueError("census paper has unknown fields: %s" % ", ".join(extra))

    def required_text(field: str) -> str:
        value = payload[field]
        if not isinstance(value, str) or not value.strip():
            raise ValueError("census paper %s must be non-empty text" % field)
        return value.strip()

    def optional_text(field: str) -> Optional[str]:
        value = payload[field]
        if value is None:
            return None
        if not isinstance(value, str) or not value.strip():
            raise ValueError("census paper %s must be null or non-empty text" % field)
        return value.strip()

    raw_date = payload["publication_date"]
    if not isinstance(raw_date, str):
        raise ValueError("census paper publication_date must be an ISO date")
    try:
        publication_date = date.fromisoformat(raw_date)
    except ValueError as exc:
        raise ValueError("census paper publication_date must be an ISO date") from exc
    if publication_date.isoformat() != raw_date:
        raise ValueError("census paper publication_date must use YYYY-MM-DD")

    citation_count = payload["citation_count"]
    if citation_count is not None and (
        isinstance(citation_count, bool)
        or not isinstance(citation_count, int)
        or citation_count < 0
    ):
        raise ValueError("census paper citation_count must be null or non-negative")

    doi = canonicalize_doi(required_text("doi"))
    venue = required_text("venue")
    if venue not in CROSSREF_VENUE_ISSNS:
        raise ValueError("census paper has unknown venue: %s" % venue)
    return CensusPaper(
        doi=doi,
        title=required_text("title"),
        venue=venue,
        publication_date=publication_date,
        article_type=required_text("article_type"),
        citation_count=citation_count,
        url=optional_text("url"),
        first_author=optional_text("first_author"),
        first_author_family=optional_text("first_author_family"),
    )


def _stdlib_transport(url: str, timeout: float) -> Mapping[str, Any]:
    request = Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": "role-benchmark/temporal-census",
        },
    )
    with urlopen(request, timeout=timeout) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Crossref response must be a JSON object")
    return payload


def _crossref_date(item: Mapping[str, Any]) -> date:
    for field in ("published", "published-online", "published-print", "issued"):
        value = item.get(field)
        if not isinstance(value, Mapping):
            continue
        groups = value.get("date-parts")
        if (
            not isinstance(groups, Sequence)
            or isinstance(groups, (str, bytes))
            or not groups
        ):
            continue
        parts = groups[0]
        if (
            not isinstance(parts, Sequence)
            or isinstance(parts, (str, bytes))
            or len(parts) < 3
        ):
            continue
        try:
            return date(int(parts[0]), int(parts[1]), int(parts[2]))
        except (TypeError, ValueError):
            continue
    doi = item.get("DOI", "<unknown DOI>")
    raise ValueError("Crossref item %s has no complete publication date" % doi)


def _crossref_title(item: Mapping[str, Any]) -> str:
    values = item.get("title")
    if isinstance(values, str):
        title = values.strip()
        if title:
            return title
    if isinstance(values, Sequence) and not isinstance(values, (str, bytes)):
        for value in values:
            if isinstance(value, str) and value.strip():
                return value.strip()
    doi = item.get("DOI", "<unknown DOI>")
    raise ValueError("Crossref item %s has no title" % doi)


def _crossref_first_author(
    item: Mapping[str, Any],
) -> Tuple[Optional[str], Optional[str]]:
    authors = item.get("author")
    if not isinstance(authors, Sequence) or isinstance(authors, (str, bytes)):
        return None, None
    first = next((author for author in authors if isinstance(author, Mapping)), None)
    if first is None:
        return None, None

    given = first.get("given")
    family = first.get("family")
    name = first.get("name")
    given = given.strip() if isinstance(given, str) and given.strip() else None
    family = family.strip() if isinstance(family, str) and family.strip() else None
    name = name.strip() if isinstance(name, str) and name.strip() else None
    display = " ".join(part for part in (given, family) if part) or name
    return display, family


def _paper_from_item(item: Mapping[str, Any], *, venue: str) -> CensusPaper:
    raw_doi = item.get("DOI")
    if not isinstance(raw_doi, str):
        raise ValueError("Crossref item has no DOI")
    article_type = item.get("type")
    if not isinstance(article_type, str) or not article_type:
        raise ValueError("Crossref item %s has no work type" % raw_doi)
    raw_count = item.get("is-referenced-by-count")
    citation_count = (
        raw_count
        if isinstance(raw_count, int) and not isinstance(raw_count, bool)
        else None
    )
    raw_url = item.get("URL")
    paper_url = raw_url if isinstance(raw_url, str) and raw_url else None
    first_author, first_author_family = _crossref_first_author(item)
    return CensusPaper(
        doi=canonicalize_doi(raw_doi),
        title=_crossref_title(item),
        venue=venue,
        publication_date=_crossref_date(item),
        article_type=article_type,
        citation_count=citation_count,
        url=paper_url,
        first_author=first_author,
        first_author_family=first_author_family,
    )


def _paper_completeness(paper: CensusPaper) -> int:
    return sum(
        value is not None
        for value in (
            paper.citation_count,
            paper.url,
            paper.first_author,
            paper.first_author_family,
        )
    )


def _paper_conflict_fields(
    left: CensusPaper, right: CensusPaper
) -> Tuple[str, ...]:
    fields = (
        "title",
        "venue",
        "publication_date",
        "article_type",
        "citation_count",
        "url",
        "first_author",
        "first_author_family",
    )
    return tuple(name for name in fields if getattr(left, name) != getattr(right, name))


def _item_doi_for_disposition(item: Mapping[str, Any]) -> Optional[str]:
    raw = item.get("DOI")
    if not isinstance(raw, str):
        return None
    try:
        return canonicalize_doi(raw)
    except ValueError:
        return raw.strip() or None


def _response_page(payload: Mapping[str, Any]) -> Tuple[Sequence[Any], Optional[str]]:
    message = payload.get("message")
    if not isinstance(message, Mapping):
        raise ValueError("Crossref response has no message object")
    items = message.get("items")
    if not isinstance(items, Sequence) or isinstance(items, (str, bytes)):
        raise ValueError("Crossref response message has no items array")
    next_cursor = message.get("next-cursor")
    if next_cursor is not None and not isinstance(next_cursor, str):
        raise ValueError("Crossref next-cursor must be a string")
    return items, next_cursor


def _query_url(
    *,
    issn: str,
    start: date,
    end: date,
    rows: int,
    cursor: str,
    mailto: Optional[str],
) -> str:
    query = [
        (
            "filter",
            "from-pub-date:%s,until-pub-date:%s,type:journal-article"
            % (start.isoformat(), end.isoformat()),
        ),
        ("rows", str(rows)),
        ("cursor", cursor),
    ]
    if mailto:
        query.append(("mailto", mailto))
    return "%s/journals/%s/works?%s" % (
        CROSSREF_API_URL,
        quote(issn, safe=""),
        urlencode(query),
    )


def collect_crossref_census_snapshot(
    *,
    start: date,
    end: date,
    venues: Iterable[str] = TARGET_VENUES,
    rows: int = 1000,
    mailto: Optional[str] = None,
    timeout: float = 30.0,
    transport: Optional[CrossrefTransport] = None,
) -> CensusSnapshot:
    """Enumerate a window while retaining item exclusions and DOI conflicts."""

    if end < start:
        raise ValueError("end must not precede start")
    if isinstance(rows, bool) or not isinstance(rows, int) or not 1 <= rows <= 1000:
        raise ValueError("rows must be an integer between 1 and 1000")
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or timeout <= 0:
        raise ValueError("timeout must be positive")

    selected = tuple(venues)
    unknown = tuple(venue for venue in selected if venue not in CROSSREF_VENUE_ISSNS)
    if unknown:
        raise ValueError("unknown venue: %s" % ", ".join(unknown))
    if not selected:
        raise ValueError("at least one venue is required")

    fetch = transport or _stdlib_transport
    by_doi: Dict[str, Tuple[CensusPaper, str]] = {}
    dispositions = []
    conflicts = []
    for venue in TARGET_VENUES:
        if venue not in selected:
            continue
        for issn in CROSSREF_VENUE_ISSNS[venue]:
            cursor = "*"
            seen_cursors = set()
            while True:
                if cursor in seen_cursors:
                    raise ValueError("Crossref repeated a cursor for ISSN %s" % issn)
                seen_cursors.add(cursor)
                payload = fetch(
                    _query_url(
                        issn=issn,
                        start=start,
                        end=end,
                        rows=rows,
                        cursor=cursor,
                        mailto=mailto,
                    ),
                    float(timeout),
                )
                items, next_cursor = _response_page(payload)
                if not items:
                    break
                for raw_item in items:
                    if not isinstance(raw_item, Mapping):
                        dispositions.append(
                            CensusRecordDisposition(
                                disposition="crossref_metadata_incomplete",
                                venue=venue,
                                issn=issn,
                                doi=None,
                                detail="Crossref item is not a JSON object",
                            )
                        )
                        continue
                    try:
                        paper = _paper_from_item(raw_item, venue=venue)
                    except ValueError as exc:
                        dispositions.append(
                            CensusRecordDisposition(
                                disposition="crossref_metadata_incomplete",
                                venue=venue,
                                issn=issn,
                                doi=_item_doi_for_disposition(raw_item),
                                detail=str(exc),
                            )
                        )
                        continue
                    if not start <= paper.publication_date <= end:
                        dispositions.append(
                            CensusRecordDisposition(
                                disposition="outside_window",
                                venue=venue,
                                issn=issn,
                                doi=paper.doi,
                                detail=(
                                    "parsed publication date %s is outside [%s, %s]"
                                    % (
                                        paper.publication_date.isoformat(),
                                        start.isoformat(),
                                        end.isoformat(),
                                    )
                                ),
                            )
                        )
                        continue
                    previous = by_doi.get(paper.doi)
                    if previous is None:
                        by_doi[paper.doi] = (paper, issn)
                        continue
                    previous_paper, previous_issn = previous
                    differing = _paper_conflict_fields(previous_paper, paper)
                    if not differing:
                        continue
                    if _paper_completeness(paper) > _paper_completeness(previous_paper):
                        selected_issn = issn
                        alternate_issn = previous_issn
                        selected_record = paper
                        alternate_record = previous_paper
                        by_doi[paper.doi] = (paper, issn)
                    else:
                        selected_issn = previous_issn
                        alternate_issn = issn
                        selected_record = previous_paper
                        alternate_record = paper
                    conflicts.append(
                        CensusDuplicateConflict(
                            doi=paper.doi,
                            fields=differing,
                            selected_issn=selected_issn,
                            alternate_issn=alternate_issn,
                            selected_record=selected_record,
                            alternate_record=alternate_record,
                        )
                    )
                if len(items) < rows:
                    break
                if not next_cursor:
                    break
                cursor = next_cursor

    papers = tuple(
        sorted(
            (item[0] for item in by_doi.values()),
            key=lambda paper: (paper.publication_date, paper.venue, paper.doi),
        )
    )
    return CensusSnapshot(papers, tuple(dispositions), tuple(conflicts))


def collect_crossref_census(
    *,
    start: date,
    end: date,
    venues: Iterable[str] = TARGET_VENUES,
    rows: int = 1000,
    mailto: Optional[str] = None,
    timeout: float = 30.0,
    transport: Optional[CrossrefTransport] = None,
) -> Tuple[CensusPaper, ...]:
    """Return usable papers from an inclusive Crossref census snapshot."""

    return collect_crossref_census_snapshot(
        start=start,
        end=end,
        venues=venues,
        rows=rows,
        mailto=mailto,
        timeout=timeout,
        transport=transport,
    ).papers


__all__ = [
    "CROSSREF_API_URL",
    "CROSSREF_VENUE_ISSNS",
    "CensusPaper",
    "CensusDuplicateConflict",
    "CensusRecordDisposition",
    "CensusSnapshot",
    "CrossrefTransport",
    "canonicalize_doi",
    "census_paper_from_payload",
    "census_paper_to_payload",
    "census_snapshot_to_payload",
    "collect_crossref_census",
    "collect_crossref_census_snapshot",
]
