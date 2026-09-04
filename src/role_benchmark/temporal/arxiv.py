"""High-precision journal-record resolution and source retrieval from arXiv."""

from __future__ import annotations

import html
import re
import time
import unicodedata
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Mapping, Optional, Tuple, Union
from urllib.parse import quote, urlencode, urlparse
from urllib.request import Request, urlopen

from .census import CensusPaper, canonicalize_doi
from .latex import LatexBundle, NoTexSourceError, latex_bundle_from_tar_gz


ARXIV_API_URL = "https://export.arxiv.org/api/query"
ARXIV_SOURCE_URL = "https://arxiv.org/src"

ArxivTransport = Callable[[str, float], bytes]

_ATOM = "http://www.w3.org/2005/Atom"
_ARXIV = "http://arxiv.org/schemas/atom"
_VERSIONED_ID = re.compile(
    r"(?P<base>(?:[0-9]{4}\.[0-9]{4,5}|[A-Za-z0-9_.-]+/[0-9]{7}))"
    r"v[1-9][0-9]*"
)
_RELATION_TARGET_ID = re.compile(
    r"(?P<base>(?:[0-9]{4}\.[0-9]{4,5}|[A-Za-z0-9_.-]+/[0-9]{7}))"
    r"(?P<version>v[1-9][0-9]*)?"
)


@dataclass(frozen=True)
class ArxivPaper:
    """The arXiv metadata needed for conservative record linkage."""

    versioned_id: str
    title: str
    first_author: Optional[str]
    first_author_family: Optional[str]
    doi: Optional[str]
    entry_url: str
    first_submitted_at: datetime
    version_updated_at: datetime


@dataclass(frozen=True)
class ArxivResolution:
    """A resolved or fail-closed linkage result with recalled candidates."""

    status: str
    paper: Optional[ArxivPaper]
    candidates: Tuple[ArxivPaper, ...]
    match_method: Optional[str]
    recalled_count: int
    failure_reason: Optional[str] = None
    doi_recalled_count: Optional[int] = None
    title_recalled_count: Optional[int] = None
    doi_recall_limit_reached: Optional[bool] = None
    title_recall_limit_reached: Optional[bool] = None

    def __post_init__(self) -> None:
        if self.status not in {
            "resolved",
            "not_found",
            "ambiguous",
            "manual_review_required",
        }:
            raise ValueError("unknown arXiv resolution status: %s" % self.status)
        if (
            isinstance(self.recalled_count, bool)
            or not isinstance(self.recalled_count, int)
            or self.recalled_count < len(self.candidates)
        ):
            raise ValueError("arXiv recalled_count cannot be smaller than candidates")
        if self.status == "resolved":
            if self.paper is None or len(self.candidates) != 1:
                raise ValueError("resolved arXiv result must contain one paper")
            if self.match_method not in {
                "crossref_has_preprint_doi",
                "doi",
                "manual_review",
            }:
                raise ValueError("resolved arXiv result must identify its match method")
            if self.failure_reason is not None:
                raise ValueError("resolved arXiv result cannot have a failure reason")
        elif self.paper is not None or self.match_method is not None:
            raise ValueError("unresolved arXiv result cannot contain a selected paper")
        if self.failure_reason is not None and (
            not isinstance(self.failure_reason, str) or not self.failure_reason.strip()
        ):
            raise ValueError("arXiv failure reason must be null or non-empty text")
        for field, count in (
            ("doi_recalled_count", self.doi_recalled_count),
            ("title_recalled_count", self.title_recalled_count),
        ):
            if count is not None and (
                isinstance(count, bool) or not isinstance(count, int) or count < 0
            ):
                raise ValueError("arXiv %s must be null or non-negative" % field)
        for field, value, count in (
            (
                "doi_recall_limit_reached",
                self.doi_recall_limit_reached,
                self.doi_recalled_count,
            ),
            (
                "title_recall_limit_reached",
                self.title_recall_limit_reached,
                self.title_recalled_count,
            ),
        ):
            if value is not None and not isinstance(value, bool):
                raise ValueError("arXiv %s must be null or boolean" % field)
            if value is not None and count is None:
                raise ValueError("arXiv %s requires its channel count" % field)
        if self.status == "not_found" and self.candidates:
            raise ValueError("not_found arXiv result cannot contain candidates")
        if self.status == "ambiguous" and len(self.candidates) < 2:
            raise ValueError("ambiguous arXiv result must contain multiple candidates")
        if self.status == "manual_review_required":
            if not self.candidates:
                raise ValueError("manual-review arXiv result must contain candidates")
            if self.failure_reason is None:
                raise ValueError("manual-review arXiv result must state a reason")


def normalize_arxiv_title(value: str) -> str:
    """Apply narrow normalization for title-candidate matching.

    Scientific punctuation, digits, subscripts, superscripts, and markup are
    intentionally retained.  Broader display normalization is suitable only
    for candidate retrieval followed by manual adjudication.
    """

    if not isinstance(value, str):
        raise ValueError("arXiv title must be text")
    normalized = unicodedata.normalize("NFC", html.unescape(value)).casefold()
    return " ".join(normalized.split())


def parse_versioned_arxiv_id(value: str) -> str:
    """Extract and validate the immutable ``...vN`` identifier from an arXiv URL."""

    if not isinstance(value, str) or not value.strip():
        raise ValueError("arXiv entry has no identifier")
    raw = value.strip()
    parsed = urlparse(raw)
    if parsed.scheme or parsed.netloc:
        path = parsed.path
        for prefix in ("/abs/", "/pdf/", "/src/"):
            if path.startswith(prefix):
                raw = path[len(prefix) :]
                break
        else:
            raise ValueError("arXiv identifier URL has an unsupported path")
    raw = raw.removesuffix(".pdf") if hasattr(raw, "removesuffix") else (
        raw[:-4] if raw.endswith(".pdf") else raw
    )
    if not _VERSIONED_ID.fullmatch(raw):
        raise ValueError("arXiv identifier must include a concrete version")
    return raw


def _normalized_name_tokens(value: str) -> Tuple[str, ...]:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    return tuple(
        "".join(character if character.isalnum() else " " for character in normalized).split()
    )


def _author_family(author: Optional[str]) -> Optional[str]:
    if not author:
        return None
    if "," in author:
        family = author.split(",", 1)[0].strip()
        return family or None
    tokens = author.split()
    return tokens[-1].strip() if tokens else None


def _first_author_matches_family(author: Optional[str], family: str) -> bool:
    if not author:
        return False
    author_tokens = _normalized_name_tokens(author)
    family_tokens = _normalized_name_tokens(family)
    if not author_tokens or not family_tokens:
        return False
    if "," in author:
        return _normalized_name_tokens(author.split(",", 1)[0]) == family_tokens
    return len(author_tokens) >= len(family_tokens) and author_tokens[
        -len(family_tokens) :
    ] == family_tokens


def _stdlib_transport(url: str, timeout: float) -> bytes:
    request = Request(
        url,
        headers={
            "Accept": "application/atom+xml, application/octet-stream",
            "User-Agent": "role-benchmark/temporal-arxiv",
        },
    )
    with urlopen(request, timeout=timeout) as response:
        return response.read()


def _atom_timestamp(
    value: Optional[str], *, field: str, versioned_id: str
) -> datetime:
    if not value or not value.strip():
        raise ValueError(
            "arXiv entry %s has no %s timestamp" % (versioned_id, field)
        )
    raw = value.strip()
    iso_value = raw[:-1] + "+00:00" if raw.endswith("Z") else raw
    try:
        parsed = datetime.fromisoformat(iso_value)
    except ValueError as exc:
        raise ValueError(
            "arXiv entry %s has an invalid %s timestamp" % (versioned_id, field)
        ) from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(
            "arXiv entry %s %s timestamp must include a timezone"
            % (versioned_id, field)
        )
    return parsed.astimezone(timezone.utc)


def _search_term(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _article_stripped_title(value: str) -> str:
    """Return a recall-only title variant without standalone English articles."""

    tokens = value.split()
    kept = [
        token
        for token in tokens
        if token.casefold().strip(".,:;!?()[]{}") not in {"a", "an", "the"}
    ]
    return " ".join(kept)


def _entry_identity(entry: ET.Element) -> Tuple[str, str]:
    """Prefer the versioned alternate link; tolerate a versioned Atom id."""

    for link in entry.findall("{%s}link" % _ATOM):
        if link.get("rel") != "alternate":
            continue
        href = (link.get("href") or "").strip()
        if not href:
            continue
        try:
            return parse_versioned_arxiv_id(href), href
        except ValueError:
            continue
    entry_url = (entry.findtext("{%s}id" % _ATOM) or "").strip()
    return parse_versioned_arxiv_id(entry_url), entry_url


def arxiv_search_url(
    *,
    title: str,
    first_author_family: Optional[str],
    doi: Optional[str] = None,
    max_results: int = 20,
) -> str:
    """Build one DOI-string or title-only candidate-retrieval query.

    The retained ``doi`` parameter is backward compatible, but selects a
    DOI-string query over arXiv's searchable text fields.  The API has no DOI
    search field, so this is candidate retrieval rather than DOI metadata
    lookup.  It is never OR-combined with the title query because an API
    result limit would make apparent DOI uniqueness unsafe.
    """

    if isinstance(max_results, bool) or not isinstance(max_results, int) or max_results < 1:
        raise ValueError("max_results must be a positive integer")
    if not isinstance(title, str) or not title.strip():
        raise ValueError("title must be non-empty text")
    if doi is not None:
        if not isinstance(doi, str):
            raise ValueError("doi must be text")
        search_query = '(all:"%s")' % _search_term(canonicalize_doi(doi))
        return "%s?%s" % (
            ARXIV_API_URL,
            urlencode(
                (
                    ("search_query", search_query),
                    ("start", "0"),
                    ("max_results", str(max_results)),
                )
            ),
        )
    raw_title = title.strip()
    # Author order and group-author metadata can change between a preprint and
    # journal article.  Keep the title query broad enough for candidate recall;
    # author metadata is inspected only after retrieval and never auto-matches.
    title_query = 'ti:"%s"' % _search_term(raw_title)
    recall_queries = ["(%s)" % title_query]
    article_stripped = _article_stripped_title(raw_title)
    if article_stripped and article_stripped != raw_title:
        stripped_query = 'ti:"%s"' % _search_term(article_stripped)
        recall_queries.append("(%s)" % stripped_query)
    search_query = (
        title_query
        if len(recall_queries) == 1
        else " OR ".join(recall_queries)
    )
    return "%s?%s" % (
        ARXIV_API_URL,
        urlencode(
            (
                ("search_query", search_query),
                ("start", "0"),
                ("max_results", str(max_results)),
            )
        ),
    )


def parse_arxiv_feed(payload: bytes) -> Tuple[ArxivPaper, ...]:
    """Parse arXiv Atom entries and pin every result to the returned version."""

    if not isinstance(payload, bytes) or not payload:
        raise ValueError("arXiv search response must be non-empty bytes")
    try:
        root = ET.fromstring(payload)
    except ET.ParseError as exc:
        raise ValueError("arXiv search response is not valid Atom XML") from exc

    papers = {}
    for entry in root.findall("{%s}entry" % _ATOM):
        versioned_id, entry_url = _entry_identity(entry)
        title = " ".join((entry.findtext("{%s}title" % _ATOM) or "").split())
        if not title:
            raise ValueError("arXiv entry %s has no title" % versioned_id)
        author_node = entry.find("{%s}author" % _ATOM)
        first_author = None
        if author_node is not None:
            name = author_node.findtext("{%s}name" % _ATOM)
            first_author = " ".join(name.split()) if name and name.strip() else None
        raw_doi = entry.findtext("{%s}doi" % _ARXIV)
        doi = canonicalize_doi(raw_doi) if raw_doi and raw_doi.strip() else None
        first_submitted_at = _atom_timestamp(
            entry.findtext("{%s}published" % _ATOM),
            field="published",
            versioned_id=versioned_id,
        )
        version_updated_at = _atom_timestamp(
            entry.findtext("{%s}updated" % _ATOM),
            field="updated",
            versioned_id=versioned_id,
        )
        papers.setdefault(
            versioned_id,
            ArxivPaper(
                versioned_id=versioned_id,
                title=title,
                first_author=first_author,
                first_author_family=_author_family(first_author),
                doi=doi,
                entry_url=entry_url,
                first_submitted_at=first_submitted_at,
                version_updated_at=version_updated_at,
            ),
        )
    return tuple(papers.values())


def search_arxiv_papers(
    *,
    title: str,
    first_author_family: Optional[str],
    doi: Optional[str] = None,
    max_results: int = 20,
    timeout: float = 30.0,
    transport: Optional[ArxivTransport] = None,
) -> Tuple[ArxivPaper, ...]:
    """Run one DOI-string or title-only candidate-retrieval request."""

    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or timeout <= 0:
        raise ValueError("timeout must be positive")
    url = arxiv_search_url(
        title=title,
        first_author_family=first_author_family,
        doi=doi,
        max_results=max_results,
    )
    payload = (transport or _stdlib_transport)(url, float(timeout))
    return parse_arxiv_feed(payload)


def _search_arxiv_relation_target(
    arxiv_id: str,
    *,
    timeout: float,
    transport: Optional[ArxivTransport],
) -> Tuple[ArxivPaper, ...]:
    """Retrieve one explicit Crossref relation target from the official API."""

    if (
        not isinstance(arxiv_id, str)
        or _RELATION_TARGET_ID.fullmatch(arxiv_id) is None
    ):
        raise ValueError("Crossref has-preprint target is not a canonical arXiv ID")
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or timeout <= 0:
        raise ValueError("timeout must be positive")
    url = "%s?%s" % (
        ARXIV_API_URL,
        urlencode(
            (
                ("id_list", arxiv_id),
                ("start", "0"),
                ("max_results", "1"),
            )
        ),
    )
    payload = (transport or _stdlib_transport)(url, float(timeout))
    return parse_arxiv_feed(payload)


def arxiv_base_id(value: str) -> str:
    """Return the arXiv identifier without its mandatory version suffix."""

    value = parse_versioned_arxiv_id(value)
    match = _VERSIONED_ID.fullmatch(value)
    if match is None:
        raise ValueError("arXiv identifier must include a concrete version")
    return match.group("base").lower()


def _relation_target_matches(versioned_id: str, relation_target: str) -> bool:
    """Respect an explicit relation version; otherwise compare work identifiers."""

    match = _RELATION_TARGET_ID.fullmatch(relation_target)
    if match is None:
        raise ValueError("Crossref has-preprint target is not a canonical arXiv ID")
    if match.group("version") is not None:
        return versioned_id.casefold() == relation_target.casefold()
    return arxiv_base_id(versioned_id) == match.group("base").casefold()


def _unique_papers(*groups: Tuple[ArxivPaper, ...]) -> Tuple[ArxivPaper, ...]:
    """Preserve API order while deduplicating records recalled by both channels."""

    papers = {}
    for group in groups:
        for paper in group:
            papers.setdefault(paper.versioned_id, paper)
    return tuple(papers.values())


def resolve_arxiv_paper(
    paper: CensusPaper,
    *,
    max_results: int = 20,
    timeout: float = 30.0,
    transport: Optional[ArxivTransport] = None,
    pause: Optional[Callable[[float], None]] = None,
    request_interval_s: float = 3.0,
) -> ArxivResolution:
    """Resolve a Crossref relation before DOI-string/title candidate retrieval."""

    if isinstance(max_results, bool) or not isinstance(max_results, int) or max_results < 1:
        raise ValueError("max_results must be a positive integer")
    if (
        isinstance(request_interval_s, bool)
        or not isinstance(request_interval_s, (int, float))
        or request_interval_s < 0
    ):
        raise ValueError("request_interval_s must be non-negative")
    journal_doi = canonicalize_doi(paper.doi)
    relation_target = paper.has_preprint_arxiv_id
    if relation_target is not None:
        recalled = _search_arxiv_relation_target(
            relation_target,
            timeout=timeout,
            transport=transport,
        )
        relation_matches = tuple(
            candidate
            for candidate in recalled
            if _relation_target_matches(candidate.versioned_id, relation_target)
        )
        if len(relation_matches) > 1:
            return ArxivResolution(
                "ambiguous",
                None,
                relation_matches,
                None,
                len(recalled),
                failure_reason="crossref_relation_multiple_arxiv_records",
            )
        if not relation_matches:
            return ArxivResolution(
                "not_found",
                None,
                (),
                None,
                len(recalled),
                failure_reason="crossref_relation_target_not_returned",
            )
        candidate = relation_matches[0]
        if candidate.doi is not None and candidate.doi != journal_doi:
            return ArxivResolution(
                "manual_review_required",
                None,
                relation_matches,
                None,
                len(recalled),
                failure_reason="crossref_relation_journal_doi_conflict",
            )
        if candidate.doi == journal_doi:
            return ArxivResolution(
                "resolved",
                candidate,
                relation_matches,
                "doi",
                len(recalled),
            )
        if paper.has_preprint_asserted_by not in {"subject", "object"} or (
            paper.has_preprint_identifier_type not in {"doi", "arxiv"}
        ):
            return ArxivResolution(
                "manual_review_required",
                None,
                relation_matches,
                None,
                len(recalled),
                failure_reason="crossref_relation_provenance_incomplete",
            )
        if paper.has_preprint_identifier_type != "doi":
            return ArxivResolution(
                "manual_review_required",
                None,
                relation_matches,
                None,
                len(recalled),
                failure_reason="crossref_non_doi_relation_requires_manual_review",
            )
        return ArxivResolution(
            "resolved",
            candidate,
            relation_matches,
            "crossref_has_preprint_doi",
            len(recalled),
        )

    doi_recalled = search_arxiv_papers(
        title=paper.title,
        first_author_family=paper.first_author_family,
        doi=paper.doi,
        max_results=max_results,
        timeout=timeout,
        transport=transport,
    )
    doi_recalled_count = len(doi_recalled)
    doi_recall_limit_reached = doi_recalled_count >= max_results
    doi_matches = tuple(
        candidate for candidate in doi_recalled if candidate.doi == journal_doi
    )
    if doi_recall_limit_reached:
        return ArxivResolution(
            "manual_review_required",
            None,
            doi_recalled,
            None,
            doi_recalled_count,
            failure_reason="doi_recall_limit_reached",
            doi_recalled_count=doi_recalled_count,
            title_recalled_count=0,
            doi_recall_limit_reached=True,
            title_recall_limit_reached=False,
        )
    if len(doi_matches) == 1:
        return ArxivResolution(
            "resolved",
            doi_matches[0],
            doi_matches,
            "doi",
            doi_recalled_count,
            doi_recalled_count=doi_recalled_count,
            title_recalled_count=0,
            doi_recall_limit_reached=False,
            title_recall_limit_reached=False,
        )
    if len(doi_matches) > 1:
        return ArxivResolution(
            "manual_review_required",
            None,
            doi_matches,
            None,
            doi_recalled_count,
            failure_reason="multiple_exact_journal_doi_matches",
            doi_recalled_count=doi_recalled_count,
            title_recalled_count=0,
            doi_recall_limit_reached=False,
            title_recall_limit_reached=False,
        )

    # JATS/MathML is not a title phrase. Retaining it in an API query can fail
    # at transport time and, even if returned, cannot support exact text
    # comparison without a separately specified markup parser.
    if "<" in paper.title or ">" in paper.title:
        return ArxivResolution(
            "not_found",
            None,
            (),
            None,
            doi_recalled_count,
            failure_reason="title_recall_unavailable_embedded_markup",
            doi_recalled_count=doi_recalled_count,
            title_recalled_count=0,
            doi_recall_limit_reached=False,
            title_recall_limit_reached=False,
        )

    effective_pause = pause
    if effective_pause is None and transport is None:
        effective_pause = time.sleep
    if effective_pause is not None:
        effective_pause(float(request_interval_s))
    title_recalled = search_arxiv_papers(
        title=paper.title,
        first_author_family=paper.first_author_family,
        max_results=max_results,
        timeout=timeout,
        transport=transport,
    )
    title_recalled_count = len(title_recalled)
    title_recall_limit_reached = title_recalled_count >= max_results
    recalled = _unique_papers(doi_recalled, title_recalled)
    if title_recall_limit_reached:
        return ArxivResolution(
            "manual_review_required",
            None,
            recalled,
            None,
            doi_recalled_count + title_recalled_count,
            failure_reason="title_recall_limit_reached",
            doi_recalled_count=doi_recalled_count,
            title_recalled_count=title_recalled_count,
            doi_recall_limit_reached=False,
            title_recall_limit_reached=True,
        )

    doi_matches = tuple(
        candidate for candidate in recalled if candidate.doi == journal_doi
    )
    if len(doi_matches) == 1:
        return ArxivResolution(
            "resolved",
            doi_matches[0],
            doi_matches,
            "doi",
            doi_recalled_count + title_recalled_count,
            doi_recalled_count=doi_recalled_count,
            title_recalled_count=title_recalled_count,
            doi_recall_limit_reached=False,
            title_recall_limit_reached=False,
        )
    if len(doi_matches) > 1:
        return ArxivResolution(
            "manual_review_required",
            None,
            doi_matches,
            None,
            doi_recalled_count + title_recalled_count,
            failure_reason="multiple_exact_journal_doi_matches",
            doi_recalled_count=doi_recalled_count,
            title_recalled_count=title_recalled_count,
            doi_recall_limit_reached=False,
            title_recall_limit_reached=False,
        )

    title = normalize_arxiv_title(paper.title)
    title_author_matches = tuple(
        candidate
        for candidate in recalled
        if paper.first_author_family
        and normalize_arxiv_title(candidate.title) == title
        and _first_author_matches_family(
            candidate.first_author, paper.first_author_family
        )
    )
    recalled_count = doi_recalled_count + title_recalled_count
    if title_recalled:
        reason = (
            "exact_title_first_author_requires_manual_review"
            if title_author_matches
            else "title_search_candidates_require_manual_review"
        )
        return ArxivResolution(
            "manual_review_required",
            None,
            title_recalled,
            None,
            recalled_count,
            failure_reason=reason,
            doi_recalled_count=doi_recalled_count,
            title_recalled_count=title_recalled_count,
            doi_recall_limit_reached=False,
            title_recall_limit_reached=title_recall_limit_reached,
        )
    return ArxivResolution(
        "not_found",
        None,
        (),
        None,
        recalled_count,
        doi_recalled_count=doi_recalled_count,
        title_recalled_count=title_recalled_count,
        doi_recall_limit_reached=False,
        title_recall_limit_reached=False,
    )


def resolve_manually_reviewed_arxiv_paper(
    paper: CensusPaper,
    *,
    versioned_id: str,
    timeout: float = 30.0,
    transport: Optional[ArxivTransport] = None,
) -> ArxivResolution:
    """Verify a frozen manual record-linkage decision against official metadata.

    The reviewer supplies a concrete arXiv version found through an external
    candidate-retrieval channel.  This function verifies that exact identifier
    through the official Atom API and refuses an explicit journal-DOI conflict;
    it does not reproduce or replace the review itself.
    """

    exact_id = parse_versioned_arxiv_id(versioned_id)
    recalled = _search_arxiv_relation_target(
        exact_id,
        timeout=timeout,
        transport=transport,
    )
    matches = tuple(
        candidate
        for candidate in recalled
        if candidate.versioned_id.casefold() == exact_id.casefold()
    )
    if len(matches) > 1:
        return ArxivResolution(
            "ambiguous",
            None,
            matches,
            None,
            len(recalled),
            failure_reason="manual_linkage_multiple_arxiv_records",
        )
    if not matches:
        return ArxivResolution(
            "not_found",
            None,
            (),
            None,
            len(recalled),
            failure_reason="manual_linkage_target_not_returned",
        )
    candidate = matches[0]
    journal_doi = canonicalize_doi(paper.doi)
    if candidate.doi is not None and candidate.doi != journal_doi:
        return ArxivResolution(
            "manual_review_required",
            None,
            matches,
            None,
            len(recalled),
            failure_reason="manual_linkage_journal_doi_conflict",
        )
    return ArxivResolution(
        "resolved",
        candidate,
        matches,
        "manual_review",
        len(recalled),
    )


def arxiv_source_url(paper_or_id: Union[ArxivPaper, str]) -> str:
    """Return the official source endpoint for one immutable arXiv version."""

    raw_id = (
        paper_or_id.versioned_id
        if isinstance(paper_or_id, ArxivPaper)
        else paper_or_id
    )
    versioned_id = parse_versioned_arxiv_id(raw_id)
    return "%s/%s" % (ARXIV_SOURCE_URL, quote(versioned_id, safe="/."))


def download_arxiv_source(
    paper_or_id: Union[ArxivPaper, str],
    *,
    timeout: float = 60.0,
    transport: Optional[ArxivTransport] = None,
) -> LatexBundle:
    """Download one pinned arXiv archive and return its textual source packet."""

    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or timeout <= 0:
        raise ValueError("timeout must be positive")
    payload = (transport or _stdlib_transport)(
        arxiv_source_url(paper_or_id), float(timeout)
    )
    if payload[:1024].lstrip().startswith(b"%PDF-"):
        raise NoTexSourceError(
            "arXiv source endpoint returned PDF-only content with no .tex files"
        )
    return latex_bundle_from_tar_gz(payload)


def arxiv_paper_to_payload(paper: ArxivPaper) -> Mapping[str, Optional[str]]:
    return {
        "doi": paper.doi,
        "entry_url": paper.entry_url,
        "first_author": paper.first_author,
        "first_author_family": paper.first_author_family,
        "first_submitted_at": paper.first_submitted_at.isoformat(),
        "title": paper.title,
        "versioned_id": paper.versioned_id,
        "version_updated_at": paper.version_updated_at.isoformat(),
    }


def arxiv_resolution_to_payload(resolution: ArxivResolution) -> Mapping[str, object]:
    payload = {
        "candidates": [arxiv_paper_to_payload(item) for item in resolution.candidates],
        "match_method": resolution.match_method,
        "paper": (
            arxiv_paper_to_payload(resolution.paper) if resolution.paper else None
        ),
        "recalled_count": resolution.recalled_count,
        "status": resolution.status,
    }
    if resolution.failure_reason is not None:
        payload["failure_reason"] = resolution.failure_reason
    for field in (
        "doi_recalled_count",
        "title_recalled_count",
        "doi_recall_limit_reached",
        "title_recall_limit_reached",
    ):
        value = getattr(resolution, field)
        if value is not None:
            payload[field] = value
    return payload


__all__ = [
    "ARXIV_API_URL",
    "ARXIV_SOURCE_URL",
    "ArxivPaper",
    "ArxivResolution",
    "ArxivTransport",
    "arxiv_base_id",
    "arxiv_paper_to_payload",
    "arxiv_resolution_to_payload",
    "arxiv_search_url",
    "arxiv_source_url",
    "download_arxiv_source",
    "normalize_arxiv_title",
    "parse_arxiv_feed",
    "parse_versioned_arxiv_id",
    "resolve_arxiv_paper",
    "resolve_manually_reviewed_arxiv_paper",
    "search_arxiv_papers",
]
