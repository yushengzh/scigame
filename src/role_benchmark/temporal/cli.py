"""Command-line entry points for the temporal case pipeline."""

from __future__ import annotations

import argparse
import json
import time
from datetime import date
from pathlib import Path
from typing import Optional, Sequence

from role_benchmark.llm import generation_request_to_payload

from .arxiv import (
    arxiv_resolution_to_payload,
    download_arxiv_source,
    resolve_arxiv_paper,
)
from .acquisition import acquire_temporal_window
from .candidate import (
    CandidateDecodeError,
    parse_paper_abstraction_json,
)
from .census import (
    census_paper_from_payload,
    census_paper_to_payload,
    collect_crossref_census,
)
from .extract import (
    build_paper_abstraction_request,
    validate_paper_abstraction_source,
)
from .filter import filter_candidate
from .latex import load_latex
from .metadata import TARGET_VENUES


def _paper_abstraction(path: str):
    return parse_paper_abstraction_json(Path(path).read_text(encoding="utf-8"))


def _census(path: str):
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError("census input must be a JSON array")
    return tuple(census_paper_from_payload(item) for item in payload)


def _json_object(path: str):
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("JSON input must be an object: %s" % path)
    return payload


def _filter_report(abstraction):
    candidates = []
    for candidate in abstraction.candidates:
        result = filter_candidate(candidate)
        candidates.append(
            {
                "eligible": result.eligible,
                "family": candidate.family,
                "issues": [
                    {"code": item.code, "path": item.path, "message": item.message}
                    for item in result.issues
                ],
            }
        )
    return {
        "assessment": abstraction.assessment,
        "candidate_count": len(candidates),
        "eligible_count": sum(item["eligible"] for item in candidates),
        "candidates": candidates,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m role_benchmark.temporal",
        description=(
            "Acquire temporal sources and inspect legacy abstractions. "
            "Accepted cases are rendered only by run_temporal_warmup.py."
        ),
    )
    commands = parser.add_subparsers(dest="command", required=True)
    census = commands.add_parser(
        "census", help="enumerate a fixed inclusive publication-date window"
    )
    census.add_argument("--start", required=True, help="inclusive date (YYYY-MM-DD)")
    census.add_argument("--end", required=True, help="inclusive date (YYYY-MM-DD)")
    census.add_argument(
        "--venue",
        action="append",
        choices=TARGET_VENUES,
        help="target venue; repeat to select more than one (default: all)",
    )
    census.add_argument("--rows", type=int, default=1000)
    census.add_argument("--mailto")
    acquire = commands.add_parser(
        "acquire",
        help="derive an arXiv-linked textual-source cohort from one journal window",
    )
    acquire.add_argument("output_directory")
    acquire.add_argument("--start", required=True, help="inclusive date (YYYY-MM-DD)")
    acquire.add_argument("--end", required=True, help="inclusive date (YYYY-MM-DD)")
    acquire.add_argument(
        "--venue",
        action="append",
        choices=TARGET_VENUES,
        help="target venue; repeat to select more than one (default: all)",
    )
    acquire.add_argument("--rows", type=int, default=1000)
    acquire.add_argument("--mailto")
    acquire.add_argument("--max-results", type=int, default=20)
    acquire.add_argument(
        "--selection-policy",
        choices=("all", "citation_rank"),
        default="all",
    )
    acquire.add_argument("--cohort-limit", type=int)
    acquire.add_argument("--earliest-public-not-before")
    acquire.add_argument(
        "--publisher-reconciliation",
        required=True,
        help=(
            "DOI-keyed JSON with category, original_research, publication_date, "
            "and withdrawn_or_retracted"
        ),
    )
    acquire.add_argument(
        "--figure-evidence-addenda",
        help=(
            "optional DOI-keyed reviewer-authored JSON transcriptions of facts "
            "visible in named assets from the fixed arXiv source archive"
        ),
    )
    acquire.add_argument(
        "--manual-linkage-reviews",
        help=(
            "optional DOI-keyed JSON with frozen match decisions for candidates "
            "found through offline title or search-engine retrieval, or with a "
            "reviewed source version for the same arXiv work"
        ),
    )
    arxiv_match = commands.add_parser(
        "arxiv-match",
        help="resolve every journal record in a census JSON array against arXiv",
    )
    arxiv_match.add_argument("census")
    arxiv_match.add_argument("--max-results", type=int, default=20)
    arxiv_source = commands.add_parser(
        "arxiv-source",
        help="emit the merged TeX corpus for one fixed arXiv version",
    )
    arxiv_source.add_argument("versioned_id")
    request = commands.add_parser(
        "request",
        help="emit a legacy diagnostic paper-abstraction request; never accept a case",
    )
    request.add_argument("tex")
    request.add_argument("--source-citation", required=True)
    request.add_argument("--journal-doi", required=True)
    request.add_argument("--arxiv-versioned-id", required=True)
    validate_abstraction = commands.add_parser(
        "validate-abstraction",
        help="inspect a legacy abstraction without rendering or accepting it",
    )
    validate_abstraction.add_argument("abstraction")
    validate_abstraction.add_argument("--source-citation", required=True)
    validate_abstraction.add_argument("--journal-doi", required=True)
    validate_abstraction.add_argument("--arxiv-versioned-id", required=True)
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "census":
            papers = collect_crossref_census(
                start=date.fromisoformat(args.start),
                end=date.fromisoformat(args.end),
                venues=args.venue or TARGET_VENUES,
                rows=args.rows,
                mailto=args.mailto,
            )
            print(
                json.dumps(
                    [census_paper_to_payload(paper) for paper in papers],
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                )
            )
            return 0

        if args.command == "acquire":
            reconciliation = (
                _json_object(args.publisher_reconciliation)
                if args.publisher_reconciliation
                else None
            )
            figure_evidence_addenda = (
                _json_object(args.figure_evidence_addenda)
                if args.figure_evidence_addenda
                else None
            )
            manual_linkage_reviews = (
                _json_object(args.manual_linkage_reviews)
                if args.manual_linkage_reviews
                else None
            )
            acquisition = acquire_temporal_window(
                start=date.fromisoformat(args.start),
                end=date.fromisoformat(args.end),
                output_directory=args.output_directory,
                venues=args.venue or TARGET_VENUES,
                rows=args.rows,
                mailto=args.mailto,
                earliest_public_not_before=(
                    date.fromisoformat(args.earliest_public_not_before)
                    if args.earliest_public_not_before
                    else None
                ),
                selection_policy=args.selection_policy,
                cohort_limit=args.cohort_limit,
                max_results=args.max_results,
                publisher_reconciliation=reconciliation,
                figure_evidence_addenda=figure_evidence_addenda,
                manual_linkage_reviews=manual_linkage_reviews,
                pause=time.sleep,
            )
            print(json.dumps(acquisition, ensure_ascii=False, indent=2, sort_keys=True))
            return 0

        if args.command == "arxiv-match":
            papers = _census(args.census)
            matches = []
            for index, paper in enumerate(papers):
                resolution = resolve_arxiv_paper(
                    paper,
                    max_results=args.max_results,
                    pause=time.sleep,
                    request_interval_s=3.0,
                )
                matches.append(
                    {
                        "journal": census_paper_to_payload(paper),
                        "resolution": arxiv_resolution_to_payload(resolution),
                    }
                )
                if index + 1 < len(papers):
                    # arXiv asks clients making repeated API calls to wait three seconds.
                    time.sleep(3.0)
            print(json.dumps(matches, ensure_ascii=False, indent=2, sort_keys=True))
            return 0

        if args.command == "arxiv-source":
            bundle = download_arxiv_source(args.versioned_id)
            print(bundle.merged_text, end="")
            return 0

        if args.command == "request":
            request = build_paper_abstraction_request(
                load_latex(args.tex),
                source_citation=args.source_citation,
                journal_doi=args.journal_doi,
                arxiv_versioned_id=args.arxiv_versioned_id,
            )
            print(
                json.dumps(
                    generation_request_to_payload(request),
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                )
            )
            return 0

        if args.command == "validate-abstraction":
            abstraction = _paper_abstraction(args.abstraction)
            validate_paper_abstraction_source(
                abstraction,
                source_citation=args.source_citation,
                journal_doi=args.journal_doi,
                arxiv_versioned_id=args.arxiv_versioned_id,
            )
            report = _filter_report(abstraction)
            all_eligible = report["eligible_count"] == report["candidate_count"]
            print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
            return 0 if all_eligible else 2
        raise ValueError("unknown temporal command: %s" % args.command)
    except (CandidateDecodeError, OSError, ValueError) as exc:
        if isinstance(exc, CandidateDecodeError):
            report = {
                "eligible": False,
                "issues": [
                    {"code": exc.code, "path": exc.path, "message": exc.detail}
                ],
            }
            print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
        else:
            print(str(exc))
        return 2


__all__ = ["main"]
