from __future__ import annotations

import contextlib
import io
import json
import unittest
from datetime import date
from unittest.mock import patch
from urllib.parse import parse_qs, unquote, urlparse

from role_benchmark.temporal import (
    CROSSREF_VENUE_ISSNS,
    CensusPaper,
    canonicalize_doi,
    census_paper_from_payload,
    census_paper_to_payload,
    collect_crossref_census,
    collect_crossref_census_snapshot,
)
from role_benchmark.temporal.cli import main as temporal_cli_main


def _item(
    doi,
    title,
    day,
    *,
    citations=0,
    url=None,
    given="Ada",
    family="Lovelace",
    relation=None,
):
    item = {
        "DOI": doi,
        "title": [title],
        "published": {"date-parts": [[2026, 6, day]]},
        "type": "journal-article",
        "is-referenced-by-count": citations,
        "author": [{"given": given, "family": family}],
    }
    if url is not None:
        item["URL"] = url
    if relation is not None:
        item["relation"] = relation
    return item


class _PagedTransport:
    def __init__(self, pages):
        self.pages = pages
        self.calls = []

    def __call__(self, url, timeout):
        parsed = urlparse(url)
        issn = unquote(parsed.path.split("/")[-2])
        query = parse_qs(parsed.query)
        cursor = query["cursor"][0]
        self.calls.append((issn, cursor, query, timeout))
        return self.pages[(issn, cursor)]


class TemporalCensusTests(unittest.TestCase):
    def test_snapshot_skips_bad_items_and_preserves_duplicate_conflicts(self):
        print_issn, online_issn = CROSSREF_VENUE_ISSNS["Nature"]
        incomplete = _item("10.1000/bad", "Bad", 2)
        del incomplete["title"]
        sparse = _item("10.1000/shared", "Sparse title", 2, citations=None)
        rich = _item(
            "https://doi.org/10.1000/SHARED",
            "Publisher title",
            2,
            citations=7,
            url="https://doi.org/10.1000/shared",
        )
        snapshot = collect_crossref_census_snapshot(
            start=date(2026, 6, 1),
            end=date(2026, 6, 30),
            venues=("Nature",),
            transport=_PagedTransport(
                {
                    (print_issn, "*"): {"message": {"items": [incomplete, sparse]}},
                    (online_issn, "*"): {"message": {"items": [rich]}},
                }
            ),
        )

        self.assertEqual([paper.title for paper in snapshot.papers], ["Publisher title"])
        self.assertEqual(snapshot.dispositions[0].doi, "10.1000/bad")
        self.assertEqual(
            snapshot.dispositions[0].disposition, "crossref_metadata_incomplete"
        )
        conflict = snapshot.duplicate_conflicts[0]
        self.assertEqual(conflict.fields, ("title", "citation_count", "url"))
        self.assertEqual(conflict.selected_record.citation_count, 7)
        self.assertIsNone(conflict.alternate_record.citation_count)

    def test_exhausts_cursor_pages_and_deduplicates_canonical_dois(self):
        print_issn, online_issn = CROSSREF_VENUE_ISSNS["Nature"]
        pages = {
            (print_issn, "*"): {
                "message": {
                    "items": [
                        _item(
                            "10.1000/LATER",
                            "Later",
                            3,
                            citations=4,
                            url="https://doi.org/10.1000/later",
                        ),
                        _item("doi:10.1000/first", "First", 1),
                    ],
                    "next-cursor": "print-page-2",
                }
            },
            (print_issn, "print-page-2"): {
                "message": {
                    "items": [_item("10.1000/middle", "Middle", 2)],
                    "next-cursor": "print-page-3",
                }
            },
            (online_issn, "*"): {
                "message": {
                    "items": [
                        _item("https://doi.org/10.1000/LATER", "Duplicate", 3)
                    ],
                    "next-cursor": "online-page-2",
                }
            },
        }
        transport = _PagedTransport(pages)

        papers = collect_crossref_census(
            start=date(2026, 6, 1),
            end=date(2026, 6, 30),
            venues=("Nature",),
            rows=2,
            mailto="researcher@example.org",
            transport=transport,
        )

        self.assertEqual(
            [paper.doi for paper in papers],
            ["10.1000/first", "10.1000/middle", "10.1000/later"],
        )
        self.assertEqual(len(transport.calls), 3)
        self.assertEqual(papers[0].first_author, "Ada Lovelace")
        self.assertEqual(papers[0].first_author_family, "Lovelace")
        for _, _, query, timeout in transport.calls:
            self.assertEqual(
                query["filter"],
                [
                    "from-pub-date:2026-06-01,until-pub-date:2026-06-30,"
                    "type:journal-article"
                ],
            )
            self.assertEqual(query["rows"], ["2"])
            self.assertEqual(query["mailto"], ["researcher@example.org"])
            self.assertEqual(timeout, 30.0)

    def test_keeps_only_inclusive_window_and_preserves_unknown_counts(self):
        science_issns = CROSSREF_VENUE_ISSNS["Science"]
        pages = {
            (science_issns[0], "*"): {
                "message": {
                    "items": [
                        _item("10.2/before", "Before", 1),
                        _item("10.2/start", "Start", 2, citations=None),
                        _item("10.2/end", "End", 4, citations=8),
                    ]
                }
            },
            (science_issns[1], "*"): {"message": {"items": []}},
        }
        pages[(science_issns[0], "*")]["message"]["items"][0]["published"] = {
            "date-parts": [[2026, 5, 31]]
        }
        transport = _PagedTransport(pages)

        papers = collect_crossref_census(
            start=date(2026, 6, 2),
            end=date(2026, 6, 4),
            venues=("Science",),
            transport=transport,
        )

        self.assertEqual([paper.doi for paper in papers], ["10.2/start", "10.2/end"])
        self.assertIsNone(papers[0].citation_count)
        self.assertEqual(papers[1].citation_count, 8)

    def test_validates_window_venue_rows_and_repeated_cursor(self):
        with self.assertRaisesRegex(ValueError, "end must not precede start"):
            collect_crossref_census(
                start=date(2026, 6, 2),
                end=date(2026, 6, 1),
                transport=lambda url, timeout: {},
            )
        with self.assertRaisesRegex(ValueError, "unknown venue"):
            collect_crossref_census(
                start=date(2026, 6, 1),
                end=date(2026, 6, 2),
                venues=("Other",),
                transport=lambda url, timeout: {},
            )
        with self.assertRaisesRegex(ValueError, "rows must be"):
            collect_crossref_census(
                start=date(2026, 6, 1),
                end=date(2026, 6, 2),
                rows=0,
                transport=lambda url, timeout: {},
            )

        issn = CROSSREF_VENUE_ISSNS["Nature"][0]
        transport = _PagedTransport(
            {
                (issn, "*"): {
                    "message": {
                        "items": [_item("10.3/a", "A", 1)],
                        "next-cursor": "*",
                    }
                }
            }
        )
        with self.assertRaisesRegex(ValueError, "repeated a cursor"):
            collect_crossref_census(
                start=date(2026, 6, 1),
                end=date(2026, 6, 2),
                venues=("Nature",),
                rows=1,
                transport=transport,
            )

    def test_canonicalizes_common_doi_forms(self):
        self.assertEqual(canonicalize_doi(" DOI:10.5555/ABC "), "10.5555/abc")
        self.assertEqual(
            canonicalize_doi("https://doi.org/10.5555/ABC"), "10.5555/abc"
        )

    def test_payload_round_trip_is_strict(self):
        paper = CensusPaper(
            doi="10.1/example",
            title="Example",
            venue="Nature",
            publication_date=date(2026, 6, 2),
            article_type="journal-article",
            citation_count=3,
            url="https://doi.org/10.1/example",
            first_author="Ada Lovelace",
            first_author_family="Lovelace",
        )
        self.assertEqual(census_paper_from_payload(census_paper_to_payload(paper)), paper)

        missing = dict(census_paper_to_payload(paper))
        del missing["first_author"]
        with self.assertRaisesRegex(ValueError, "missing fields: first_author"):
            census_paper_from_payload(missing)
        extra = dict(census_paper_to_payload(paper), unexpected=True)
        with self.assertRaisesRegex(ValueError, "unknown fields: unexpected"):
            census_paper_from_payload(extra)
        bad_date = dict(census_paper_to_payload(paper), publication_date="2026-02-30")
        with self.assertRaisesRegex(ValueError, "must be an ISO date"):
            census_paper_from_payload(bad_date)
        orphan_assertion = dict(
            census_paper_to_payload(paper), has_preprint_asserted_by="object"
        )
        with self.assertRaisesRegex(ValueError, "requires arXiv ID"):
            census_paper_from_payload(orphan_assertion)
        orphan_identifier = dict(
            census_paper_to_payload(paper), has_preprint_arxiv_id="2601.05846"
        )
        with self.assertRaisesRegex(ValueError, "requires arXiv ID"):
            census_paper_from_payload(orphan_identifier)

    def test_extracts_member_deposited_crossref_arxiv_relation(self):
        print_issn, online_issn = CROSSREF_VENUE_ISSNS["Physical Review Letters"]
        relation = {
            "has-preprint": [
                {
                    "id-type": "doi",
                    "id": "https://doi.org/10.48550/arXiv.2601.05846",
                    "asserted-by": "subject",
                },
                {
                    "id-type": "doi",
                    "id": "10.1101/2026.01.01.000001",
                    "asserted-by": "subject",
                },
                {
                    "id-type": "arxiv",
                    "id": "arXiv:2601.05846",
                    "asserted-by": "object",
                },
            ]
        }
        papers = collect_crossref_census(
            start=date(2026, 6, 1),
            end=date(2026, 6, 30),
            venues=("Physical Review Letters",),
            transport=_PagedTransport(
                {
                    (print_issn, "*"): {
                        "message": {
                            "items": [
                                _item(
                                    "10.1103/example",
                                    "Explicit relation",
                                    2,
                                    relation=relation,
                                )
                            ]
                        }
                    },
                    (online_issn, "*"): {"message": {"items": []}},
                }
            ),
        )

        self.assertEqual(papers[0].has_preprint_arxiv_id, "2601.05846")
        self.assertEqual(papers[0].has_preprint_asserted_by, "subject")
        self.assertEqual(papers[0].has_preprint_identifier_type, "doi")
        payload = census_paper_to_payload(papers[0])
        self.assertEqual(payload["has_preprint_arxiv_id"], "2601.05846")
        self.assertEqual(payload["has_preprint_asserted_by"], "subject")
        self.assertEqual(payload["has_preprint_identifier_type"], "doi")
        self.assertEqual(census_paper_from_payload(payload), papers[0])

    def test_extracts_object_asserted_reciprocal_arxiv_relation(self):
        print_issn, online_issn = CROSSREF_VENUE_ISSNS["Nature"]
        relation = {
            "has-preprint": [
                {
                    "id-type": "arxiv",
                    "id": "2601.05846",
                    "asserted-by": "object",
                }
            ]
        }
        papers = collect_crossref_census(
            start=date(2026, 6, 1),
            end=date(2026, 6, 30),
            venues=("Nature",),
            transport=_PagedTransport(
                {
                    (print_issn, "*"): {
                        "message": {
                            "items": [
                                _item(
                                    "10.1038/example",
                                    "Reciprocal relation",
                                    2,
                                    relation=relation,
                                )
                            ]
                        }
                    },
                    (online_issn, "*"): {"message": {"items": []}},
                }
            ),
        )

        self.assertEqual(papers[0].has_preprint_arxiv_id, "2601.05846")
        self.assertEqual(papers[0].has_preprint_asserted_by, "object")
        self.assertEqual(papers[0].has_preprint_identifier_type, "arxiv")
        payload = census_paper_to_payload(papers[0])
        self.assertEqual(payload["has_preprint_asserted_by"], "object")
        self.assertEqual(payload["has_preprint_identifier_type"], "arxiv")
        self.assertEqual(census_paper_from_payload(payload), papers[0])

    def test_relation_provenance_is_one_observed_pair(self):
        print_issn, online_issn = CROSSREF_VENUE_ISSNS["Physical Review Letters"]
        relation = {
            "has-preprint": [
                {
                    "id-type": "doi",
                    "id": "10.48550/arXiv.2601.05846",
                    "asserted-by": "object",
                },
                {
                    "id-type": "arxiv",
                    "id": "2601.05846",
                    "asserted-by": "subject",
                },
            ]
        }
        papers = collect_crossref_census(
            start=date(2026, 6, 1),
            end=date(2026, 6, 30),
            venues=("Physical Review Letters",),
            transport=_PagedTransport(
                {
                    (print_issn, "*"): {
                        "message": {
                            "items": [
                                _item(
                                    "10.1103/example",
                                    "Observed provenance pair",
                                    2,
                                    relation=relation,
                                )
                            ]
                        }
                    },
                    (online_issn, "*"): {"message": {"items": []}},
                }
            ),
        )

        self.assertEqual(papers[0].has_preprint_asserted_by, "object")
        self.assertEqual(papers[0].has_preprint_identifier_type, "doi")

    def test_conflicting_subject_asserted_arxiv_relations_fail_closed(self):
        print_issn, online_issn = CROSSREF_VENUE_ISSNS["Physical Review Letters"]
        relation = {
            "has-preprint": [
                {
                    "id-type": "doi",
                    "id": "10.48550/arXiv.2601.05846",
                    "asserted-by": "subject",
                },
                {
                    "id-type": "arxiv",
                    "id": "2601.05847",
                    "asserted-by": "subject",
                },
            ]
        }
        snapshot = collect_crossref_census_snapshot(
            start=date(2026, 6, 1),
            end=date(2026, 6, 30),
            venues=("Physical Review Letters",),
            transport=_PagedTransport(
                {
                    (print_issn, "*"): {
                        "message": {
                            "items": [
                                _item(
                                    "10.1103/conflict",
                                    "Conflicting relation",
                                    2,
                                    relation=relation,
                                )
                            ]
                        }
                    },
                    (online_issn, "*"): {"message": {"items": []}},
                }
            ),
        )

        self.assertEqual(snapshot.papers, ())
        self.assertEqual(
            snapshot.dispositions[0].disposition,
            "crossref_preprint_relation_conflict",
        )

    def test_arxiv_doi_suffix_is_not_parsed_as_an_id_type_arxiv_value(self):
        print_issn, online_issn = CROSSREF_VENUE_ISSNS["Physical Review Letters"]
        relation = {
            "has-preprint": [
                {
                    "id-type": "doi",
                    "id": "10.48550/arXiv.arXiv:2601.05846",
                    "asserted-by": "subject",
                }
            ]
        }
        snapshot = collect_crossref_census_snapshot(
            start=date(2026, 6, 1),
            end=date(2026, 6, 30),
            venues=("Physical Review Letters",),
            transport=_PagedTransport(
                {
                    (print_issn, "*"): {
                        "message": {
                            "items": [
                                _item(
                                    "10.1103/malformed-arxiv-doi",
                                    "Malformed relation DOI",
                                    2,
                                    relation=relation,
                                )
                            ]
                        }
                    },
                    (online_issn, "*"): {"message": {"items": []}},
                }
            ),
        )

        self.assertEqual(snapshot.papers, ())
        self.assertEqual(
            snapshot.dispositions[0].disposition,
            "crossref_preprint_relation_invalid",
        )
        self.assertIn("official arXiv DOI", snapshot.dispositions[0].detail)

    def test_id_type_arxiv_accepts_its_explicit_identifier_prefix(self):
        print_issn, online_issn = CROSSREF_VENUE_ISSNS["Physical Review Letters"]
        relation = {
            "has-preprint": [
                {
                    "id-type": "arxiv",
                    "id": "arXiv:2601.05846v2",
                    "asserted-by": "subject",
                }
            ]
        }
        papers = collect_crossref_census(
            start=date(2026, 6, 1),
            end=date(2026, 6, 30),
            venues=("Physical Review Letters",),
            transport=_PagedTransport(
                {
                    (print_issn, "*"): {
                        "message": {
                            "items": [
                                _item(
                                    "10.1103/arxiv-id",
                                    "Explicit arXiv identifier",
                                    2,
                                    relation=relation,
                                )
                            ]
                        }
                    },
                    (online_issn, "*"): {"message": {"items": []}},
                }
            ),
        )

        self.assertEqual(papers[0].has_preprint_arxiv_id, "2601.05846v2")
        self.assertEqual(papers[0].has_preprint_identifier_type, "arxiv")

    def test_duplicate_crossref_records_merge_one_arxiv_relation(self):
        print_issn, online_issn = CROSSREF_VENUE_ISSNS["Physical Review Letters"]
        relation = {
            "has-preprint": [
                {
                    "id-type": "doi",
                    "id": "10.48550/arXiv.2601.05846",
                    "asserted-by": "subject",
                }
            ]
        }
        snapshot = collect_crossref_census_snapshot(
            start=date(2026, 6, 1),
            end=date(2026, 6, 30),
            venues=("Physical Review Letters",),
            transport=_PagedTransport(
                {
                    (print_issn, "*"): {
                        "message": {
                            "items": [
                                _item(
                                    "10.1103/shared",
                                    "Shared record",
                                    2,
                                    citations=7,
                                    url="https://doi.org/10.1103/shared",
                                )
                            ]
                        }
                    },
                    (online_issn, "*"): {
                        "message": {
                            "items": [
                                _item(
                                    "10.1103/shared",
                                    "Shared record",
                                    2,
                                    citations=None,
                                    relation=relation,
                                )
                            ]
                        }
                    },
                }
            ),
        )

        self.assertEqual(len(snapshot.papers), 1)
        self.assertEqual(snapshot.papers[0].citation_count, 7)
        self.assertEqual(snapshot.papers[0].has_preprint_arxiv_id, "2601.05846")
        self.assertEqual(snapshot.papers[0].has_preprint_asserted_by, "subject")
        self.assertEqual(snapshot.papers[0].has_preprint_identifier_type, "doi")
        conflict = snapshot.duplicate_conflicts[0]
        self.assertIn("has_preprint_arxiv_id", conflict.fields)
        self.assertIsNone(conflict.selected_record.has_preprint_arxiv_id)
        self.assertEqual(
            conflict.alternate_record.has_preprint_arxiv_id,
            "2601.05846",
        )
        self.assertEqual(
            conflict.alternate_record.has_preprint_asserted_by,
            "subject",
        )
        self.assertEqual(
            conflict.alternate_record.has_preprint_identifier_type,
            "doi",
        )

    def test_duplicate_relation_merge_preserves_an_observed_provenance_pair(self):
        print_issn, online_issn = CROSSREF_VENUE_ISSNS["Physical Review Letters"]
        subject_arxiv = {
            "has-preprint": [
                {
                    "id-type": "arxiv",
                    "id": "2601.05846",
                    "asserted-by": "subject",
                }
            ]
        }
        object_doi = {
            "has-preprint": [
                {
                    "id-type": "doi",
                    "id": "10.48550/arXiv.2601.05846",
                    "asserted-by": "object",
                }
            ]
        }
        snapshot = collect_crossref_census_snapshot(
            start=date(2026, 6, 1),
            end=date(2026, 6, 30),
            venues=("Physical Review Letters",),
            transport=_PagedTransport(
                {
                    (print_issn, "*"): {
                        "message": {
                            "items": [
                                _item(
                                    "10.1103/shared",
                                    "Shared record",
                                    2,
                                    relation=subject_arxiv,
                                )
                            ]
                        }
                    },
                    (online_issn, "*"): {
                        "message": {
                            "items": [
                                _item(
                                    "10.1103/shared",
                                    "Shared record",
                                    2,
                                    relation=object_doi,
                                )
                            ]
                        }
                    },
                }
            ),
        )

        paper = snapshot.papers[0]
        self.assertEqual(paper.has_preprint_asserted_by, "object")
        self.assertEqual(paper.has_preprint_identifier_type, "doi")

    def test_cli_outputs_stable_json_and_returns_two_on_error(self):
        papers = (
            CensusPaper(
                doi="10.1/example",
                title="Example",
                venue="Nature",
                publication_date=date(2026, 6, 2),
                article_type="journal-article",
                citation_count=None,
                url=None,
            ),
        )
        stdout = io.StringIO()
        with patch(
            "role_benchmark.temporal.cli.collect_crossref_census",
            return_value=papers,
        ) as collect, contextlib.redirect_stdout(stdout):
            code = temporal_cli_main(
                [
                    "census",
                    "--start",
                    "2026-06-01",
                    "--end",
                    "2026-06-30",
                    "--venue",
                    "Nature",
                    "--rows",
                    "50",
                    "--mailto",
                    "researcher@example.org",
                ]
            )
        self.assertEqual(code, 0)
        self.assertEqual(
            json.loads(stdout.getvalue()),
            [
                {
                    "article_type": "journal-article",
                    "citation_count": None,
                    "doi": "10.1/example",
                    "first_author": None,
                    "first_author_family": None,
                    "publication_date": "2026-06-02",
                    "title": "Example",
                    "url": None,
                    "venue": "Nature",
                }
            ],
        )
        collect.assert_called_once_with(
            start=date(2026, 6, 1),
            end=date(2026, 6, 30),
            venues=["Nature"],
            rows=50,
            mailto="researcher@example.org",
        )

        error_stdout = io.StringIO()
        with patch(
            "role_benchmark.temporal.cli.collect_crossref_census",
            side_effect=ValueError("bad census"),
        ), contextlib.redirect_stdout(error_stdout):
            self.assertEqual(
                temporal_cli_main(
                    [
                        "census",
                        "--start",
                        "2026-06-01",
                        "--end",
                        "2026-06-30",
                    ]
                ),
                2,
            )
        self.assertEqual(error_stdout.getvalue().strip(), "bad census")


if __name__ == "__main__":
    unittest.main()
