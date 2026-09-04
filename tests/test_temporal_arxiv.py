from __future__ import annotations

import contextlib
import io
import json
import tempfile
import tarfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse
from xml.sax.saxutils import escape

from role_benchmark.temporal import (
    ArxivResolution,
    CensusPaper,
    FigureEvidenceAddendum,
    FigureEvidenceEntry,
    LatexBundle,
    NoTexSourceError,
    TexDecodeError,
    append_figure_evidence_addendum,
    arxiv_paper_to_payload,
    arxiv_resolution_to_payload,
    arxiv_search_url,
    arxiv_source_url,
    census_paper_to_payload,
    download_arxiv_source,
    normalize_arxiv_title,
    parse_arxiv_feed,
    parse_versioned_arxiv_id,
    resolve_arxiv_paper,
    resolve_manually_reviewed_arxiv_paper,
)
from role_benchmark.temporal.cli import main as temporal_cli_main


def _feed(*entries):
    body = []
    for versioned_id, title, author, doi in entries:
        doi_xml = "<arxiv:doi>%s</arxiv:doi>" % escape(doi) if doi else ""
        body.append(
            """
            <entry>
              <id>https://arxiv.org/abs/{versioned_id}</id>
              <published>2026-06-30T12:34:56Z</published>
              <updated>2026-07-01T01:02:03Z</updated>
              <title>{title}</title>
              <author><name>{author}</name></author>
              {doi_xml}
            </entry>
            """.format(
                versioned_id=escape(versioned_id),
                title=escape(title),
                author=escape(author),
                doi_xml=doi_xml,
            )
        )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<feed xmlns="http://www.w3.org/2005/Atom" '
        'xmlns:arxiv="http://arxiv.org/schemas/atom">%s</feed>' % "".join(body)
    ).encode("utf-8")


def _paper(**overrides):
    values = {
        "doi": "10.1000/paper",
        "title": "A precise scientific result",
        "venue": "Nature",
        "publication_date": date(2026, 7, 2),
        "article_type": "journal-article",
        "citation_count": 0,
        "url": "https://doi.org/10.1000/paper",
        "first_author": "Ada Lovelace",
        "first_author_family": "Lovelace",
    }
    values.update(overrides)
    return CensusPaper(**values)


def _tar_gz(files):
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w:gz") as archive:
        for path, content in files:
            payload = content if isinstance(content, bytes) else content.encode("utf-8")
            member = tarfile.TarInfo(path)
            member.size = len(payload)
            archive.addfile(member, io.BytesIO(payload))
    return output.getvalue()


class TemporalArxivTests(unittest.TestCase):
    def test_title_search_does_not_require_first_author_order(self):
        url = arxiv_search_url(
            title='A "quoted" title', first_author_family="Lovelace", max_results=12
        )
        query = parse_qs(urlparse(url).query)
        search_query = query["search_query"][0]
        self.assertIn('ti:"A \\"quoted\\" title"', search_query)
        self.assertIn('ti:"\\"quoted\\" title"', search_query)
        self.assertNotIn("au:", search_query)
        self.assertNotIn("10.", search_query)
        self.assertEqual(query["start"], ["0"])
        self.assertEqual(query["max_results"], ["12"])

    def test_parses_versioned_atom_entries(self):
        papers = parse_arxiv_feed(
            _feed(
                (
                    "2607.01234v3",
                    "  A precise\n scientific result ",
                    "Ada Lovelace",
                    "https://doi.org/10.1000/PAPER",
                )
            )
        )
        self.assertEqual(len(papers), 1)
        self.assertEqual(papers[0].versioned_id, "2607.01234v3")
        self.assertEqual(papers[0].title, "A precise scientific result")
        self.assertEqual(papers[0].first_author_family, "Lovelace")
        self.assertEqual(papers[0].doi, "10.1000/paper")
        self.assertEqual(
            papers[0].first_submitted_at.isoformat(), "2026-06-30T12:34:56+00:00"
        )
        self.assertEqual(
            papers[0].version_updated_at.isoformat(), "2026-07-01T01:02:03+00:00"
        )
        self.assertEqual(
            arxiv_paper_to_payload(papers[0])["first_submitted_at"],
            "2026-06-30T12:34:56+00:00",
        )
        self.assertEqual(
            arxiv_paper_to_payload(papers[0])["version_updated_at"],
            "2026-07-01T01:02:03+00:00",
        )

    def test_prefers_versioned_alternate_when_atom_id_is_unversioned(self):
        payload = b"""<?xml version="1.0" encoding="UTF-8"?>
        <feed xmlns="http://www.w3.org/2005/Atom">
          <entry>
            <id>https://arxiv.org/abs/2607.01234</id>
            <link href="https://arxiv.org/abs/2607.01234v4" rel="alternate" type="text/html" />
            <published>2026-06-30T12:34:56Z</published>
            <updated>2026-07-03T01:02:03Z</updated>
            <title>A precise scientific result</title>
            <author><name>Ada Lovelace</name></author>
          </entry>
        </feed>"""
        paper = parse_arxiv_feed(payload)[0]
        self.assertEqual(paper.versioned_id, "2607.01234v4")
        self.assertEqual(
            paper.entry_url, "https://arxiv.org/abs/2607.01234v4"
        )

    def test_rejects_unzoned_first_submission_timestamp(self):
        payload = _feed(
            ("2607.01234v1", "A title", "Ada Lovelace", None)
        ).replace(b"2026-06-30T12:34:56Z", b"2026-06-30T12:34:56")
        with self.assertRaisesRegex(ValueError, "must include a timezone"):
            parse_arxiv_feed(payload)

    def test_resolves_unique_doi_before_title(self):
        response = _feed(
            ("2607.00001v1", "A different title", "Someone Else", "10.1000/paper"),
            (
                "2607.00002v2",
                "A precise scientific result",
                "Ada Lovelace",
                None,
            ),
        )
        calls = []

        def transport(url, timeout):
            calls.append((url, timeout))
            return response

        result = resolve_arxiv_paper(_paper(), transport=transport)
        self.assertEqual(result.status, "resolved")
        self.assertEqual(result.match_method, "doi")
        self.assertEqual(result.paper.versioned_id, "2607.00001v1")
        query = parse_qs(urlparse(calls[0][0]).query)
        self.assertIn('all:"10.1000/paper"', query["search_query"][0])
        self.assertNotIn('au:"Lovelace"', query["search_query"][0])
        self.assertNotIn("ti:", query["search_query"][0])
        self.assertNotIn("doi:", query["search_query"][0])
        self.assertEqual(result.doi_recalled_count, 2)
        self.assertEqual(result.title_recalled_count, 0)
        self.assertEqual(calls[0][1], 30.0)

    def test_crossref_has_preprint_relation_precedes_title_search(self):
        response = _feed(
            (
                "2601.05846v2",
                "A substantially revised preprint title",
                "Ada Lovelace",
                None,
            )
        )
        calls = []
        result = resolve_arxiv_paper(
            _paper(
                has_preprint_arxiv_id="2601.05846",
                has_preprint_asserted_by="object",
                has_preprint_identifier_type="doi",
            ),
            transport=lambda url, timeout: calls.append((url, timeout)) or response,
        )

        self.assertEqual(result.status, "resolved")
        self.assertEqual(result.match_method, "crossref_has_preprint_doi")
        self.assertEqual(result.paper.versioned_id, "2601.05846v2")
        query = parse_qs(urlparse(calls[0][0]).query)
        self.assertEqual(query["id_list"], ["2601.05846"])
        self.assertEqual(query["max_results"], ["1"])
        self.assertNotIn("search_query", query)
        self.assertEqual(len(calls), 1)

    def test_crossref_relation_doi_conflict_fails_without_title_fallback(self):
        response = _feed(
            (
                "2601.05846v1",
                "A precise scientific result",
                "Ada Lovelace",
                "10.1000/different-paper",
            )
        )
        calls = []
        result = resolve_arxiv_paper(
            _paper(
                has_preprint_arxiv_id="2601.05846",
                has_preprint_asserted_by="subject",
                has_preprint_identifier_type="doi",
            ),
            transport=lambda url, timeout: calls.append(url) or response,
        )

        self.assertEqual(result.status, "manual_review_required")
        self.assertEqual(
            result.failure_reason,
            "crossref_relation_journal_doi_conflict",
        )
        self.assertEqual(len(result.candidates), 1)
        self.assertEqual(
            result.candidates[0].doi,
            "10.1000/different-paper",
        )
        payload = arxiv_resolution_to_payload(result)
        self.assertEqual(
            payload["candidates"][0]["versioned_id"],
            "2601.05846v1",
        )
        self.assertEqual(result.recalled_count, 1)
        self.assertEqual(len(calls), 1)
        self.assertIn("id_list=2601.05846", calls[0])
        self.assertNotIn("search_query", calls[0])

    def test_crossref_non_doi_relation_requires_manual_review(self):
        response = _feed(
            (
                "2601.05846v1",
                "A precise scientific result",
                "Grace Hopper",
                None,
            )
        )
        result = resolve_arxiv_paper(
            _paper(
                has_preprint_arxiv_id="2601.05846",
                has_preprint_asserted_by="subject",
                has_preprint_identifier_type="arxiv",
            ),
            transport=lambda url, timeout: response,
        )

        self.assertEqual(result.status, "manual_review_required")
        self.assertEqual(
            result.failure_reason,
            "crossref_non_doi_relation_requires_manual_review",
        )
        self.assertIsNone(result.paper)
        self.assertEqual(result.candidates[0].versioned_id, "2601.05846v1")

    def test_non_doi_relation_can_be_confirmed_by_exact_journal_doi(self):
        response = _feed(
            (
                "2601.05846v1",
                "A substantially revised title",
                "Grace Hopper",
                "10.1000/paper",
            )
        )
        result = resolve_arxiv_paper(
            _paper(
                has_preprint_arxiv_id="2601.05846",
                has_preprint_asserted_by="subject",
                has_preprint_identifier_type="arxiv",
            ),
            transport=lambda url, timeout: response,
        )

        self.assertEqual(result.status, "resolved")
        self.assertEqual(result.match_method, "doi")

    def test_relation_without_complete_provenance_requires_manual_review(self):
        response = _feed(
            (
                "2601.05846v1",
                "A precise scientific result",
                "Ada Lovelace",
                None,
            )
        )
        result = resolve_arxiv_paper(
            _paper(has_preprint_arxiv_id="2601.05846"),
            transport=lambda url, timeout: response,
        )

        self.assertEqual(result.status, "manual_review_required")
        self.assertEqual(
            result.failure_reason,
            "crossref_relation_provenance_incomplete",
        )

    def test_versioned_relation_target_is_not_silently_upgraded(self):
        response = _feed(
            (
                "2601.05846v3",
                "A precise scientific result",
                "Ada Lovelace",
                None,
            )
        )
        calls = []
        result = resolve_arxiv_paper(
            _paper(
                has_preprint_arxiv_id="2601.05846v2",
                has_preprint_asserted_by="subject",
                has_preprint_identifier_type="doi",
            ),
            transport=lambda url, timeout: calls.append(url) or response,
        )

        self.assertEqual(result.status, "not_found")
        self.assertEqual(
            result.failure_reason,
            "crossref_relation_target_not_returned",
        )
        self.assertIn("id_list=2601.05846v2", calls[0])

    def test_manually_reviewed_candidate_requires_exact_version_and_no_doi_conflict(self):
        calls = []
        resolved = resolve_manually_reviewed_arxiv_paper(
            _paper(),
            versioned_id="2601.05846v2",
            transport=lambda url, timeout: calls.append(url)
            or _feed(
                (
                    "2601.05846v2",
                    "A substantially revised title",
                    "Grace Hopper",
                    None,
                )
            ),
        )
        self.assertEqual(resolved.status, "resolved")
        self.assertEqual(resolved.match_method, "manual_review")
        self.assertIn("id_list=2601.05846v2", calls[0])

        conflict = resolve_manually_reviewed_arxiv_paper(
            _paper(),
            versioned_id="2601.05846v2",
            transport=lambda url, timeout: _feed(
                (
                    "2601.05846v2",
                    "A substantially revised title",
                    "Grace Hopper",
                    "10.1000/different-paper",
                )
            ),
        )
        self.assertEqual(conflict.status, "manual_review_required")
        self.assertEqual(
            conflict.failure_reason,
            "manual_linkage_journal_doi_conflict",
        )

    def test_crossref_relation_requires_the_returned_arxiv_id(self):
        response = _feed(
            (
                "2601.99999v1",
                "A precise scientific result",
                "Ada Lovelace",
                None,
            )
        )
        result = resolve_arxiv_paper(
            _paper(
                has_preprint_arxiv_id="2601.05846",
                has_preprint_asserted_by="object",
                has_preprint_identifier_type="doi",
            ),
            transport=lambda url, timeout: response,
        )

        self.assertEqual(result.status, "not_found")
        self.assertEqual(
            result.failure_reason,
            "crossref_relation_target_not_returned",
        )
        self.assertEqual(
            result.failure_reason,
            arxiv_resolution_to_payload(result)["failure_reason"],
        )

    def test_mathml_crossref_title_uses_the_exact_doi_recall_only(self):
        url = arxiv_search_url(
            title=(
                'A response in <mml:math><mml:msub><mml:mi>Nd</mml:mi>'
                '<mml:mn>3</mml:mn></mml:msub></mml:math>'
            ),
            first_author_family="Liu",
            doi="10.1103/example",
        )
        query = parse_qs(urlparse(url).query)["search_query"][0]
        self.assertEqual(query, '(all:"10.1103/example")')
        self.assertNotIn("mml", query)

    def test_doi_and_title_recall_are_separate_and_title_can_recover_exact_doi(self):
        paper = _paper(
            doi="10.1103/physrevlett.134.010402",
            title=(
                "Measuring the Spectral Form Factor in Many-Body Chaotic and "
                "Localized Phases of Quantum Processors"
            ),
            first_author="Hang Dong",
            first_author_family="Dong",
        )
        response = _feed(
            (
                "2403.16935v1",
                "Measuring Spectral Form Factor in Many-Body Chaotic and "
                "Localized Phases of Quantum Processors",
                "Hang Dong",
                "10.1103/PhysRevLett.134.010402",
            )
        )
        calls = []
        pauses = []

        def transport(url, timeout):
            calls.append(url)
            query = parse_qs(urlparse(url).query)["search_query"][0]
            return _feed() if "all:" in query else response

        result = resolve_arxiv_paper(
            paper,
            transport=transport,
            pause=pauses.append,
            request_interval_s=3.0,
        )

        self.assertEqual(result.status, "resolved")
        self.assertEqual(result.match_method, "doi")
        self.assertEqual(len(calls), 2)
        doi_query = parse_qs(urlparse(calls[0]).query)["search_query"][0]
        query = parse_qs(urlparse(calls[1]).query)["search_query"][0]
        self.assertEqual(doi_query, '(all:"10.1103/physrevlett.134.010402")')
        self.assertNotIn("10.1103/physrevlett", query)
        self.assertIn(
            'ti:"Measuring Spectral Form Factor in Many-Body Chaotic and '
            'Localized Phases of Quantum Processors"',
            query,
        )
        self.assertNotIn("au:", query)
        self.assertEqual(result.doi_recalled_count, 0)
        self.assertEqual(result.title_recalled_count, 1)
        self.assertEqual(pauses, [3.0])

    def test_single_relation_lookup_does_not_pause(self):
        pauses = []
        result = resolve_arxiv_paper(
            _paper(
                has_preprint_arxiv_id="2601.05846",
                has_preprint_asserted_by="subject",
                has_preprint_identifier_type="doi",
            ),
            transport=lambda url, timeout: _feed(
                (
                    "2601.05846v1",
                    "A precise scientific result",
                    "Ada Lovelace",
                    None,
                )
            ),
            pause=pauses.append,
        )

        self.assertEqual(result.status, "resolved")
        self.assertEqual(pauses, [])

    def test_rejects_invalid_request_interval(self):
        with self.assertRaisesRegex(ValueError, "request_interval_s"):
            resolve_arxiv_paper(
                _paper(),
                transport=lambda url, timeout: _feed(),
                request_interval_s=-1,
            )

    def test_exact_normalized_title_and_author_requires_manual_review(self):
        response = _feed(
            (
                "2607.00002v2",
                "  A PRECISE\n scientific result ",
                "Ada Lovelace",
                None,
            ),
            ("2607.00003v1", "A near scientific result", "Ada Lovelace", None),
        )
        calls = []

        def transport(url, timeout):
            calls.append(url)
            query = parse_qs(urlparse(url).query)["search_query"][0]
            return _feed() if "all:" in query else response

        result = resolve_arxiv_paper(
            _paper(title="A precise scientific result"), transport=transport
        )
        self.assertEqual(result.status, "manual_review_required")
        self.assertIsNone(result.match_method)
        self.assertIsNone(result.paper)
        self.assertEqual(result.candidates[0].versioned_id, "2607.00002v2")
        self.assertEqual(
            result.failure_reason,
            "exact_title_first_author_requires_manual_review",
        )
        self.assertEqual(len(calls), 2)
        self.assertEqual(
            normalize_arxiv_title("  A precise\nscientific result "),
            normalize_arxiv_title("A PRECISE scientific result"),
        )

    def test_title_search_candidate_is_retained_when_author_order_changed(self):
        candidate = _feed(
            (
                "2607.00002v2",
                "A related preprint title",
                "Grace Hopper",
                None,
            )
        )

        def transport(url, timeout):
            query = parse_qs(urlparse(url).query)["search_query"][0]
            return _feed() if "all:" in query else candidate

        result = resolve_arxiv_paper(_paper(), transport=transport)
        self.assertEqual(result.status, "manual_review_required")
        self.assertEqual(
            result.failure_reason,
            "title_search_candidates_require_manual_review",
        )
        self.assertEqual(result.candidates[0].versioned_id, "2607.00002v2")

    def test_identity_title_normalization_preserves_scientific_symbols(self):
        distinct_pairs = (
            ("H₂", "H²"),
            ("CuO_{2}", "CuO^{2}"),
            ("CuO<sub>2</sub>", "CuO<sup>2</sup>"),
            ("10%", "10"),
            ("0.10", "010"),
            ("Fe2+", "Fe2-"),
            ("2D", "two-dimensional"),
        )
        for left, right in distinct_pairs:
            with self.subTest(left=left, right=right):
                self.assertNotEqual(
                    normalize_arxiv_title(left), normalize_arxiv_title(right)
                )

    def test_explicit_doi_conflict_blocks_title_author_fallback(self):
        response = _feed(
            (
                "2607.00002v2",
                "A precise scientific result",
                "Ada Lovelace",
                "10.1000/different-paper",
            )
        )
        result = resolve_arxiv_paper(
            _paper(), transport=lambda url, timeout: response
        )
        self.assertEqual(result.status, "manual_review_required")
        self.assertEqual(
            result.failure_reason,
            "exact_title_first_author_requires_manual_review",
        )
        self.assertEqual(result.candidates[0].doi, "10.1000/different-paper")
        self.assertEqual(result.recalled_count, 2)

    def test_manual_title_candidates_include_doi_conflicts_and_missing_doi(self):
        title_response = _feed(
            (
                "2607.00002v2",
                "A precise scientific result",
                "Ada Lovelace",
                "10.1000/different-paper",
            ),
            (
                "2607.00003v1",
                "A precise scientific result",
                "Ada Lovelace",
                None,
            ),
        )

        def transport(url, timeout):
            query = parse_qs(urlparse(url).query)["search_query"][0]
            return _feed() if "all:" in query else title_response

        result = resolve_arxiv_paper(_paper(), transport=transport)

        self.assertEqual(result.status, "manual_review_required")
        self.assertEqual(
            [candidate.versioned_id for candidate in result.candidates],
            ["2607.00002v2", "2607.00003v1"],
        )
        self.assertEqual(
            [candidate.doi for candidate in result.candidates],
            ["10.1000/different-paper", None],
        )

    def test_doi_recall_at_result_limit_cannot_establish_uniqueness(self):
        response = _feed(
            (
                "2607.00001v1",
                "A different title",
                "Someone Else",
                "10.1000/paper",
            ),
            (
                "2607.00002v1",
                "Another result",
                "Grace Hopper",
                None,
            ),
        )
        calls = []
        result = resolve_arxiv_paper(
            _paper(),
            max_results=2,
            transport=lambda url, timeout: calls.append(url) or response,
        )

        self.assertEqual(result.status, "manual_review_required")
        self.assertEqual(result.failure_reason, "doi_recall_limit_reached")
        self.assertTrue(result.doi_recall_limit_reached)
        self.assertEqual(result.doi_recalled_count, 2)
        self.assertEqual(result.title_recalled_count, 0)
        self.assertEqual(len(result.candidates), 2)
        self.assertEqual(len(calls), 1)

    def test_resolved_status_rejects_title_author_as_automatic_evidence(self):
        candidate = parse_arxiv_feed(
            _feed(
                (
                    "2607.00002v1",
                    "A precise scientific result",
                    "Ada Lovelace",
                    None,
                )
            )
        )[0]
        with self.assertRaisesRegex(ValueError, "match method"):
            ArxivResolution(
                "resolved",
                candidate,
                (candidate,),
                "normalized_exact_title_first_author_family",
                1,
            )

    def test_reports_multiple_title_candidates_for_manual_review(self):
        duplicate_matches = _feed(
            (
                "2607.00002v1",
                "A precise scientific result",
                "Ada Lovelace",
                None,
            ),
            (
                "2607.00003v1",
                "A precise scientific result",
                "Ada Lovelace",
                None,
            ),
        )
        unresolved = resolve_arxiv_paper(
            _paper(), transport=lambda url, timeout: duplicate_matches
        )
        self.assertEqual(unresolved.status, "manual_review_required")
        self.assertEqual(len(unresolved.candidates), 2)
        self.assertIsNone(unresolved.paper)

        absent = resolve_arxiv_paper(
            _paper(),
            transport=lambda url, timeout: _feed(
                ("2607.00004v1", "An unrelated result", "Grace Hopper", None)
            ),
        )
        self.assertEqual(absent.status, "manual_review_required")
        self.assertEqual(
            absent.failure_reason,
            "title_search_candidates_require_manual_review",
        )
        self.assertEqual(len(absent.candidates), 1)
        self.assertEqual(absent.recalled_count, 2)

    def test_multiple_doi_matches_require_manual_review_even_if_one_title_matches(self):
        response = _feed(
            (
                "2607.00005v1",
                "A precise scientific result",
                "Ada Lovelace",
                "10.1000/paper",
            ),
            ("2607.00006v2", "An earlier title", "Ada Lovelace", "10.1000/paper"),
        )
        result = resolve_arxiv_paper(_paper(), transport=lambda url, timeout: response)
        self.assertEqual(result.status, "manual_review_required")
        self.assertEqual(len(result.candidates), 2)
        self.assertIsNone(result.match_method)
        self.assertEqual(result.failure_reason, "multiple_exact_journal_doi_matches")

    def test_requires_and_preserves_an_arxiv_version(self):
        self.assertEqual(
            parse_versioned_arxiv_id("https://arxiv.org/abs/hep-th/9901001v3"),
            "hep-th/9901001v3",
        )
        with self.assertRaisesRegex(ValueError, "concrete version"):
            parse_versioned_arxiv_id("2607.01234")
        self.assertEqual(
            arxiv_source_url("2607.01234v2"),
            "https://arxiv.org/src/2607.01234v2",
        )

    def test_downloads_path_sorted_tex_bundle_with_file_markers(self):
        archive = _tar_gz(
            [
                ("sections/z.tex", "Z content\n"),
                ("figure.pdf", "not tex"),
                ("main.tex", "\\documentclass{article}\n"),
            ]
        )
        calls = []

        def transport(url, timeout):
            calls.append((url, timeout))
            return archive

        bundle = download_arxiv_source(
            "2607.01234v2", timeout=9, transport=transport
        )
        self.assertEqual([item.path for item in bundle.files], ["main.tex", "sections/z.tex"])
        self.assertIn("===== BEGIN FILE: main.tex =====", bundle.merged_text)
        self.assertIn("\\documentclass{article}", bundle.merged_text)
        self.assertIn("===== BEGIN FILE: sections/z.tex =====", bundle.merged_text)
        self.assertEqual(
            [(item.path, item.merged_line_start, item.merged_line_end) for item in bundle.member_locators],
            [("main.tex", 2, 2), ("sections/z.tex", 6, 6)],
        )
        self.assertEqual(calls, [("https://arxiv.org/src/2607.01234v2", 9.0)])

    def test_source_packet_adds_only_utf8_textual_attachments_with_stable_locators(self):
        archive = _tar_gz(
            [
                ("notes.txt", "The reported efficiency is 90%.\n"),
                ("main.tex", "Equation $y=ax$.\n"),
                ("data/results.csv", "x,y\n1,2\n"),
                ("data/binary.dat", b"\xff\x00"),
                ("figure.pdf", b"%PDF mock"),
            ]
        )
        bundle = download_arxiv_source(
            "2607.01234v2", transport=lambda url, timeout: archive
        )

        self.assertEqual([item.path for item in bundle.files], ["main.tex"])
        self.assertNotIn("results.csv", bundle.merged_text)
        self.assertEqual(
            [item.path for item in bundle.packet_files],
            ["data/results.csv", "main.tex", "notes.txt"],
        )
        self.assertIn("The reported efficiency is 90%.", bundle.packet_text)
        self.assertNotIn("binary.dat", bundle.packet_text)
        self.assertNotIn("figure.pdf", bundle.packet_text)
        self.assertEqual(
            [
                (
                    item.path,
                    item.format,
                    item.file_line_start,
                    item.file_line_end,
                    item.global_line_start,
                    item.global_line_end,
                )
                for item in bundle.packet_member_locators
            ],
            [
                ("data/results.csv", "csv", 1, 2, 2, 3),
                ("main.tex", "latex", 1, 1, 7, 7),
                ("notes.txt", "text", 1, 1, 11, 11),
            ],
        )

    def test_source_packet_removes_tex_comments_but_preserves_other_percent_text(self):
        archive = _tar_gz(
            [
                (
                    "main.tex",
                    "Published relation $y=ax$. % obsolete relation $y=x^2$\n"
                    "Efficiency is 90\\%.\n",
                ),
                ("data/results.csv", "label,value\nefficiency,90%\n"),
            ]
        )
        bundle = download_arxiv_source(
            "2607.01234v2", transport=lambda url, timeout: archive
        )

        self.assertIn("Published relation $y=ax$.", bundle.packet_text)
        self.assertNotIn("obsolete relation", bundle.packet_text)
        self.assertIn("Efficiency is 90\\%.", bundle.packet_text)
        self.assertIn("efficiency,90%", bundle.packet_text)
        tex_locator = next(
            item
            for item in bundle.packet_member_locators
            if item.path == "main.tex"
        )
        self.assertEqual(
            tex_locator.global_line_end - tex_locator.global_line_start,
            1,
        )

    def test_reviewer_figure_addendum_names_a_real_fixed_source_asset(self):
        archive = _tar_gz(
            [
                ("main.tex", "See Figure 2.\n"),
                ("figures/figure2.pdf", b"%PDF mock"),
            ]
        )
        bundle = download_arxiv_source(
            "2607.01234v2", transport=lambda url, timeout: archive
        )
        addendum = FigureEvidenceAddendum(
            reviewer="Scientific reviewer A",
            entries=(
                FigureEvidenceEntry(
                    source_asset="figures/figure2.pdf",
                    transcription="Horizontal axis: time (ms), shown from 0 to 200.",
                    semantics="The axis is the manipulated evolution time.",
                ),
            ),
        )
        expanded = append_figure_evidence_addendum(bundle, addendum)

        self.assertNotIn("reviewer_figure_evidence", expanded.merged_text)
        self.assertIn("reviewer_figure_evidence", expanded.packet_text)
        self.assertIn("Scientific reviewer A", expanded.packet_text)
        self.assertEqual(
            expanded.packet_member_locators[-1].format,
            "reviewer_figure_evidence",
        )
        self.assertEqual(
            expanded.packet_member_locators[-1].file_line_start,
            1,
        )
        with self.assertRaisesRegex(ValueError, "not in the fixed arXiv archive"):
            append_figure_evidence_addendum(
                bundle,
                FigureEvidenceAddendum(
                    reviewer="Scientific reviewer A",
                    entries=(
                        FigureEvidenceEntry(
                            source_asset="figures/missing.pdf",
                            transcription="An unavailable transcription.",
                            semantics="An unavailable axis.",
                        ),
                    ),
                ),
            )

    def test_rejects_non_utf8_tex_instead_of_replacing_bytes(self):
        archive = _tar_gz([("main.tex", b"valid prefix\n\xff")])
        with self.assertRaisesRegex(TexDecodeError, "main.tex is not valid UTF-8"):
            download_arxiv_source(
                "2607.01234v1", transport=lambda url, timeout: archive
            )

    def test_no_tex_is_a_stable_normal_outcome(self):
        archive = _tar_gz([("paper.pdf", "pdf bytes")])
        with self.assertRaisesRegex(NoTexSourceError, "contains no \\.tex files"):
            download_arxiv_source(
                "2607.01234v1", transport=lambda url, timeout: archive
            )

        with self.assertRaisesRegex(NoTexSourceError, "PDF-only"):
            download_arxiv_source(
                "2607.01234v1",
                transport=lambda url, timeout: b"%PDF-1.7\nmock pdf bytes",
            )

        with self.assertRaisesRegex(ValueError, "valid gzip-compressed tar"):
            download_arxiv_source(
                "2607.01234v1", transport=lambda url, timeout: b"not an archive"
            )

    def test_cli_matches_a_census_array_and_respects_the_api_interval(self):
        journal_papers = (_paper(), _paper(doi="10.1000/second"))
        arxiv_paper = parse_arxiv_feed(
            _feed(
                (
                    "2607.01234v2",
                    "A precise scientific result",
                    "Ada Lovelace",
                    "10.1000/paper",
                )
            )
        )[0]
        resolution = ArxivResolution(
            "resolved", arxiv_paper, (arxiv_paper,), "doi", 1
        )
        with tempfile.TemporaryDirectory() as directory:
            census = Path(directory) / "papers.json"
            census.write_text(
                json.dumps(
                    [census_paper_to_payload(item) for item in journal_papers]
                ),
                encoding="utf-8",
            )
            stdout = io.StringIO()
            with patch(
                "role_benchmark.temporal.cli.resolve_arxiv_paper",
                return_value=resolution,
            ) as resolve, patch(
                "role_benchmark.temporal.cli.time.sleep"
            ) as pause, contextlib.redirect_stdout(stdout):
                code = temporal_cli_main(
                    ["arxiv-match", str(census), "--max-results", "7"]
                )

        self.assertEqual(code, 0)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(len(payload), 2)
        self.assertEqual(payload[0]["resolution"]["status"], "resolved")
        self.assertEqual(payload[0]["resolution"]["recalled_count"], 1)
        self.assertEqual(
            payload[0]["resolution"]["paper"]["versioned_id"],
            "2607.01234v2",
        )
        self.assertEqual(resolve.call_count, 2)
        self.assertEqual(resolve.call_args.kwargs["max_results"], 7)
        pause.assert_called_once_with(3.0)

    def test_cli_emits_the_merged_source_corpus(self):
        stdout = io.StringIO()
        with patch(
            "role_benchmark.temporal.cli.download_arxiv_source",
            return_value=LatexBundle(files=(), merged_text="paper source\n"),
        ) as download, contextlib.redirect_stdout(stdout):
            code = temporal_cli_main(["arxiv-source", "2607.01234v2"])
        self.assertEqual(code, 0)
        self.assertEqual(stdout.getvalue(), "paper source\n")
        download.assert_called_once_with("2607.01234v2")


if __name__ == "__main__":
    unittest.main()
