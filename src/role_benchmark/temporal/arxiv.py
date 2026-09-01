"""High-precision journal-record resolution and source retrieval from arXiv."""

from __future__ import annotations

import html
import re
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
    r"(?:[0-9]{4}\.[0-9]{4,5}|[A-Za-z0-9_.-]+/[0-9]{7})v[1-9][0-9]*"
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
    """A resolved, absent, or ambiguous match plus candidate-recall count."""

    status: str
    paper: Optional[ArxivPaper]
    candidates: Tuple[ArxivPaper, ...]
    match_method: Optional[str]
    recalled_count: int

    def __post_init__(self) -> None:
        if self.status not in {"resolved", "not_found", "ambiguous"}:
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
                "doi",
                "normalized_exact_title_first_author_family",
            }:
                raise ValueError("resolved arXiv result must identify its match method")
        elif self.paper is not None or self.match_method is not None:
            raise ValueError("unresolved arXiv result cannot contain a selected paper")
        if self.status == "not_found" and self.candidates:
            raise ValueError("not_found arXiv result cannot contain candidates")
        if self.status == "ambiguous" and len(self.candidates) < 2:
            raise ValueError("ambiguous arXiv result must contain multiple candidates")


def normalize_arxiv_title(value: str) -> str:
    """Normalize presentation-only title differences; this is not fuzzy matching."""

    if not isinstance(value, str):
        raise ValueError("arXiv title must be text")
    normalized = unicodedata.normalize("NFKC", html.unescape(value)).casefold()
    return " ".join(
        "".join(character if character.isalnum() else " " for character in normalized).split()
    )


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
    """Build one standards-compliant DOI-or-title candidate-recall query."""

    if isinstance(max_results, bool) or not isinstance(max_results, int) or max_results < 1:
        raise ValueError("max_results must be a positive integer")
    if not isinstance(title, str) or not title.strip():
        raise ValueError("title must be non-empty text")
    raw_title = title.strip()
    title_query = 'ti:"%s"' % _search_term(raw_title)
    family = first_author_family.strip() if first_author_family else ""
    if family:
        title_query += ' AND au:"%s"' % _search_term(family)
    search_query = title_query
    if doi is not None:
        if not isinstance(doi, str):
            raise ValueError("doi must be text")
        recall_queries = ['(all:"%s")' % _search_term(canonicalize_doi(doi))]
        # Some Crossref titles contain embedded JATS/MathML.  Sending that XML as
        # an arXiv title phrase can produce an HTTP 400 and cannot support exact
        # title matching in any case.  Prefer the exact DOI recall path for those
        # records; ordinary plain-text records retain the title/author fallback.
        if "<" not in raw_title and ">" not in raw_title:
            recall_queries.append("(%s)" % title_query)
            article_stripped = _article_stripped_title(raw_title)
            if article_stripped and article_stripped != raw_title:
                stripped_query = 'ti:"%s"' % _search_term(article_stripped)
                if family:
                    stripped_query += ' AND au:"%s"' % _search_term(family)
                recall_queries.append("(%s)" % stripped_query)
        search_query = " OR ".join(recall_queries)
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
    """Recall candidate preprints by journal title and first-author family."""

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
def resolve_arxiv_paper(
    paper: CensusPaper,
    *,
    max_results: int = 20,
    timeout: float = 30.0,
    transport: Optional[ArxivTransport] = None,
) -> ArxivResolution:
    """Resolve by unique DOI first, then unique exact title-plus-author match."""

    recalled = search_arxiv_papers(
        title=paper.title,
        first_author_family=paper.first_author_family,
        doi=paper.doi,
        max_results=max_results,
        timeout=timeout,
        transport=transport,
    )
    journal_doi = canonicalize_doi(paper.doi)
    doi_matches = tuple(
        candidate for candidate in recalled if candidate.doi == journal_doi
    )
    if len(doi_matches) == 1:
        return ArxivResolution(
            "resolved", doi_matches[0], doi_matches, "doi", len(recalled)
        )
    if len(doi_matches) > 1:
        return ArxivResolution(
            "ambiguous", None, doi_matches, None, len(recalled)
        )

    title = normalize_arxiv_title(paper.title)
    title_author_matches = tuple(
        candidate
        for candidate in recalled
        if paper.first_author_family
        and candidate.doi is None
        and normalize_arxiv_title(candidate.title) == title
        and _first_author_matches_family(
            candidate.first_author, paper.first_author_family
        )
    )
    if len(title_author_matches) == 1:
        return ArxivResolution(
            "resolved",
            title_author_matches[0],
            title_author_matches,
            "normalized_exact_title_first_author_family",
            len(recalled),
        )
    if len(title_author_matches) > 1:
        return ArxivResolution(
            "ambiguous", None, title_author_matches, None, len(recalled)
        )
    return ArxivResolution("not_found", None, (), None, len(recalled))


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
    return {
        "candidates": [arxiv_paper_to_payload(item) for item in resolution.candidates],
        "match_method": resolution.match_method,
        "paper": (
            arxiv_paper_to_payload(resolution.paper) if resolution.paper else None
        ),
        "recalled_count": resolution.recalled_count,
        "status": resolution.status,
    }


__all__ = [
    "ARXIV_API_URL",
    "ARXIV_SOURCE_URL",
    "ArxivPaper",
    "ArxivResolution",
    "ArxivTransport",
    "arxiv_paper_to_payload",
    "arxiv_resolution_to_payload",
    "arxiv_search_url",
    "arxiv_source_url",
    "download_arxiv_source",
    "normalize_arxiv_title",
    "parse_arxiv_feed",
    "parse_versioned_arxiv_id",
    "resolve_arxiv_paper",
    "search_arxiv_papers",
]
