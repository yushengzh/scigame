from __future__ import annotations

import contextlib
import io
import json
import tarfile
import tempfile
import unittest
from datetime import date, datetime, timezone
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

from role_benchmark.temporal import (
    ArxivPaper,
    ArxivResolution,
    CensusPaper,
    CensusSnapshot,
    LatexBundle,
    LatexSourceFile,
    MAX_COORDINATOR_COHORT_SIZE,
    acquire_census_snapshot,
    parse_warmup_cohort_json,
    validate_acquisition_cohort_handoff,
)
from role_benchmark.temporal.cli import main as temporal_cli_main


def _paper(doi, title, venue, *, citations=4):
    return CensusPaper(
        doi=doi,
        title=title,
        venue=venue,
        publication_date=date(2026, 7, 2),
        article_type="journal-article",
        citation_count=citations,
        url="https://doi.org/%s" % doi,
        first_author="Ada Lovelace",
        first_author_family="Lovelace",
    )


def _feed(doi="10.1103/example", versioned_id="2607.01234v2"):
    doi_xml = "<arxiv:doi>%s</arxiv:doi>" % doi if doi else ""
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<feed xmlns="http://www.w3.org/2005/Atom" '
        'xmlns:arxiv="http://arxiv.org/schemas/atom">'
        '<entry><id>https://arxiv.org/abs/%s</id>'
        '<published>2026-06-30T12:34:56Z</published>'
        '<updated>2026-07-01T01:02:03Z</updated>'
        '<title>A research result</title>'
        '<author><name>Ada Lovelace</name></author>'
        '%s</entry></feed>' % (versioned_id, doi_xml)
    ).encode("utf-8")


def _archive(files):
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w:gz") as archive:
        for path, payload in files:
            raw = payload if isinstance(payload, bytes) else payload.encode("utf-8")
            member = tarfile.TarInfo(path)
            member.size = len(raw)
            archive.addfile(member, io.BytesIO(raw))
    return output.getvalue()


def _reconciliation(doi="10.1103/example"):
    return {
        doi: {
            "category": "Letter",
            "original_research": True,
            "publication_date": "2026-07-02",
            "withdrawn_or_retracted": False,
        }
    }


class TemporalAcquisitionTests(unittest.TestCase):
    def test_cli_requires_publisher_reconciliation_for_formal_acquisition(self):
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                temporal_cli_main(
                    [
                        "acquire",
                        "output",
                        "--start",
                        "2026-07-01",
                        "--end",
                        "2026-07-31",
                    ]
                )

    def test_cli_hands_one_window_and_reconciliation_to_acquisition(self):
        with tempfile.TemporaryDirectory() as directory:
            reconciliation_path = Path(directory) / "publisher.json"
            reconciliation_path.write_text(
                json.dumps(_reconciliation()), encoding="utf-8"
            )
            addenda = {
                "10.1103/example": {
                    "reviewer": "Scientific reviewer A",
                    "entries": [
                        {
                            "source_asset": "figure.pdf",
                            "transcription": "The labeled time axis spans 0 to 10 ms.",
                            "semantics": "Time is the manipulated control.",
                        }
                    ],
                }
            }
            addenda_path = Path(directory) / "figure_evidence.json"
            addenda_path.write_text(json.dumps(addenda), encoding="utf-8")
            linkage_reviews = {
                "10.1103/example": {
                    "arxiv_versioned_id": "2607.01234v2",
                    "decision": "match",
                    "evidence_locator": "record-linkage-review.json",
                    "rationale": "The official records have the same authors and results.",
                    "reviewer": "Record-linkage reviewer A",
                }
            }
            linkage_path = Path(directory) / "linkage.json"
            linkage_path.write_text(json.dumps(linkage_reviews), encoding="utf-8")
            stdout = io.StringIO()
            with patch(
                "role_benchmark.temporal.cli.acquire_temporal_window",
                return_value={"schema": "role_benchmark.temporal_acquisition"},
            ) as acquire, contextlib.redirect_stdout(stdout):
                code = temporal_cli_main(
                    [
                        "acquire",
                        str(Path(directory) / "output"),
                        "--start",
                        "2026-07-01",
                        "--end",
                        "2026-07-31",
                        "--venue",
                        "Physical Review Letters",
                        "--selection-policy",
                        "citation_rank",
                        "--cohort-limit",
                        "30",
                        "--publisher-reconciliation",
                        str(reconciliation_path),
                        "--figure-evidence-addenda",
                        str(addenda_path),
                        "--manual-linkage-reviews",
                        str(linkage_path),
                    ]
                )
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(stdout.getvalue())["schema"], "role_benchmark.temporal_acquisition")
        self.assertEqual(acquire.call_args.kwargs["cohort_limit"], 30)
        self.assertEqual(
            acquire.call_args.kwargs["publisher_reconciliation"], _reconciliation()
        )
        self.assertEqual(
            acquire.call_args.kwargs["figure_evidence_addenda"], addenda
        )
        self.assertEqual(
            acquire.call_args.kwargs["manual_linkage_reviews"], linkage_reviews
        )

    def test_derives_one_verified_cohort_and_preserves_every_disposition(self):
        research = _paper(
            "10.1103/example",
            "A research result",
            "Physical Review Letters",
            citations=None,
        )
        nature_news = _paper(
            "10.1038/d41586-026-00001-1", "News", "Nature"
        )
        unreconciled = _paper("10.1126/example", "Science item", "Science")
        snapshot = CensusSnapshot((research, nature_news, unreconciled), (), ())
        calls = []

        def arxiv_transport(url, timeout):
            calls.append(url)
            return _feed()

        source = _archive(
            [
                ("main.tex", "Main line\n"),
                ("sections/result.tex", "Result line\n"),
                ("data/points.csv", "time,response\n1,2\n"),
                ("figures/response.pdf", b"%PDF mock"),
            ]
        )
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "acquired"
            result = acquire_census_snapshot(
                snapshot,
                start=date(2026, 7, 1),
                end=date(2026, 7, 31),
                venues=("Nature", "Science", "Physical Review Letters"),
                output_directory=output,
                retrieved_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
                publisher_reconciliation=_reconciliation(),
                figure_evidence_addenda={
                    "10.1103/example": {
                        "reviewer": "Scientific reviewer A",
                        "entries": [
                            {
                                "source_asset": "figures/response.pdf",
                                "transcription": "The time axis runs from 0 to 10 ms.",
                                "semantics": "Time is the manipulated control shown in the figure.",
                            }
                        ],
                    }
                },
                arxiv_transport=arxiv_transport,
                source_transport=lambda url, timeout: source,
                request_interval_s=0,
            )

            cohort = result["cohort"]
            self.assertEqual(len(cohort["papers"]), 1)
            paper = cohort["papers"][0]
            self.assertEqual(paper["paper_id"], "paper_2607_01234v2")
            self.assertEqual(paper["journal_doi"], "10.1103/example")
            self.assertEqual(paper["arxiv_versioned_id"], "2607.01234v2")
            self.assertEqual(paper["publication_date"], "2026-07-02")
            self.assertEqual(paper["earliest_public_date"], "2026-06-30")
            self.assertTrue(paper["latex_available"])
            self.assertFalse(paper["withdrawn_or_retracted"])
            self.assertEqual(
                (output / paper["tex_path"]).read_text(encoding="utf-8").splitlines()[0],
                "===== BEGIN FILE: main.tex =====",
            )
            packet_text = (output / paper["source_packet_path"]).read_text(
                encoding="utf-8"
            )
            self.assertIn("===== BEGIN FILE: data/points.csv =====", packet_text)
            self.assertIn("===== BEGIN FILE: reviewer_figure_evidence.txt =====", packet_text)
            parsed = parse_warmup_cohort_json(
                (output / "cohort.json").read_text(encoding="utf-8"),
                base_directory=output,
            )
            self.assertEqual(parsed.papers[0].journal_doi, "10.1103/example")
            self.assertEqual(
                parsed.papers[0].source_packet_path,
                output / paper["source_packet_path"],
            )
            self.assertIsNone(parsed.papers[0].source_paper.citation_count)
            on_disk = json.loads((output / "acquisition.json").read_text())

        dispositions = [item["disposition"] for item in result["paper_results"]]
        self.assertEqual(
            dispositions,
            [
                "source_acquired",
                "not_original_research",
                "publisher_reconciliation_required",
            ],
        )
        acquired = result["paper_results"][0]
        self.assertEqual(
            result["selection_counts"],
            {"ineligible": 2, "not_selected": 0, "selected": 1},
        )
        self.assertEqual(
            [item["selection"]["status"] for item in result["paper_results"]],
            ["selected", "ineligible", "ineligible"],
        )
        self.assertTrue(result["cohort"]["provenance"]["coordinator_ready"])
        validate_acquisition_cohort_handoff(result["cohort"], result)
        self.assertEqual(
            acquired["source"]["publisher_verification_status"],
            "publisher_reconciled",
        )
        self.assertEqual(
            acquired["source"]["members"],
            [
                {"merged_line_end": 2, "merged_line_start": 2, "path": "main.tex"},
                {
                    "merged_line_end": 6,
                    "merged_line_start": 6,
                    "path": "sections/result.tex",
                },
            ],
        )
        self.assertEqual(acquired["source"]["source_packet_member_count"], 4)
        self.assertEqual(
            [item["format"] for item in acquired["source"]["source_packet_members"]],
            ["csv", "latex", "latex", "reviewer_figure_evidence"],
        )
        self.assertEqual(
            acquired["source"]["figure_evidence_addendum"],
            {
                "reviewer": "Scientific reviewer A",
                "source_assets": ["figures/response.pdf"],
            },
        )
        self.assertEqual(on_disk["retrieved_at"], "2026-08-01T00:00:00+00:00")
        self.assertEqual(on_disk["citation_snapshot_at"], on_disk["retrieved_at"])
        self.assertEqual(
            on_disk["identity"]["automatic_match_methods"],
            ["crossref_has_preprint_doi", "doi"],
        )
        self.assertEqual(
            on_disk["identity"]["manual_review_candidate_sources"],
            [
                "crossref_non_doi_relation",
                "arxiv_title_search",
                "search_engine",
            ],
        )
        self.assertIn("separate DOI-string", on_disk["query"]["arxiv_recall"])
        self.assertIn(
            "never automatic identity adjudication",
            on_disk["query"]["general_search_engine"],
        )
        query = parse_qs(urlparse(calls[0]).query)["search_query"][0]
        self.assertIn('all:"10.1103/example"', query)
        self.assertNotIn("doi:", query)

    def test_decode_failure_is_a_paper_disposition_not_a_batch_failure(self):
        snapshot = CensusSnapshot(
            (
                _paper(
                    "10.1103/example",
                    "A research result",
                    "Physical Review Letters",
                    citations=None,
                ),
            ),
            (),
            (),
        )
        with tempfile.TemporaryDirectory() as directory:
            result = acquire_census_snapshot(
                snapshot,
                start=date(2026, 7, 1),
                end=date(2026, 7, 31),
                venues=("Physical Review Letters",),
                output_directory=Path(directory) / "acquired",
                publisher_reconciliation=_reconciliation(),
                arxiv_transport=lambda url, timeout: _feed(),
                source_transport=lambda url, timeout: _archive(
                    [("main.tex", b"text\n\xff")]
                ),
                request_interval_s=0,
            )
        self.assertEqual(result["cohort"]["papers"], [])
        self.assertEqual(
            result["cohort"]["provenance"]["handoff_status"], "empty_cohort"
        )
        self.assertFalse(result["cohort"]["provenance"]["coordinator_ready"])
        self.assertEqual(
            result["selection_counts"],
            {"ineligible": 1, "not_selected": 0, "selected": 0},
        )
        self.assertEqual(
            result["paper_results"][0]["disposition"], "tex_decode_failed"
        )

    def test_manual_linkage_candidate_is_not_downloaded(self):
        journal_paper = _paper(
            "10.1103/example",
            "A research result",
            "Physical Review Letters",
            citations=None,
        )
        candidate = ArxivPaper(
            versioned_id="2607.01234v2",
            title=journal_paper.title,
            first_author=journal_paper.first_author,
            first_author_family=journal_paper.first_author_family,
            doi=None,
            entry_url="https://arxiv.org/abs/2607.01234v2",
            first_submitted_at=datetime(2026, 6, 30, tzinfo=timezone.utc),
            version_updated_at=datetime(2026, 7, 1, tzinfo=timezone.utc),
        )
        resolution = ArxivResolution(
            "manual_review_required",
            None,
            (candidate,),
            None,
            1,
            failure_reason="exact_title_first_author_requires_manual_review",
            doi_recalled_count=0,
            title_recalled_count=1,
            doi_recall_limit_reached=False,
            title_recall_limit_reached=False,
        )

        with tempfile.TemporaryDirectory() as directory, patch(
            "role_benchmark.temporal.acquisition.resolve_arxiv_paper",
            return_value=resolution,
        ), patch(
            "role_benchmark.temporal.acquisition.download_arxiv_source"
        ) as download:
            result = acquire_census_snapshot(
                CensusSnapshot((journal_paper,), (), ()),
                start=date(2026, 7, 1),
                end=date(2026, 7, 31),
                venues=("Physical Review Letters",),
                output_directory=Path(directory) / "acquired",
                publisher_reconciliation=_reconciliation(),
                request_interval_s=0,
            )

        self.assertEqual(result["cohort"]["papers"], [])
        self.assertEqual(
            result["paper_results"][0]["disposition"],
            "arxiv_manual_review_required",
        )
        self.assertEqual(
            result["paper_results"][0]["resolution"]["candidates"][0][
                "versioned_id"
            ],
            "2607.01234v2",
        )
        download.assert_not_called()

    def test_frozen_manual_linkage_review_reenters_acquisition(self):
        journal_paper = _paper(
            "10.1103/example",
            "A journal title that changed after review",
            "Physical Review Letters",
            citations=None,
        )
        empty_feed = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<feed xmlns="http://www.w3.org/2005/Atom" '
            'xmlns:arxiv="http://arxiv.org/schemas/atom"></feed>'
        ).encode("utf-8")
        calls = []

        def arxiv_transport(url, timeout):
            calls.append(url)
            if "id_list=" in url:
                return _feed(doi=None)
            return empty_feed

        review = {
            journal_paper.doi: {
                "arxiv_versioned_id": "2607.01234v2",
                "decision": "match",
                "evidence_locator": "frozen-linkage-review.json#record-1",
                "rationale": "Official author lists and reported results agree.",
                "reviewer": "Record-linkage reviewer A",
            }
        }
        with tempfile.TemporaryDirectory() as directory:
            result = acquire_census_snapshot(
                CensusSnapshot((journal_paper,), (), ()),
                start=date(2026, 7, 1),
                end=date(2026, 7, 31),
                venues=("Physical Review Letters",),
                output_directory=Path(directory) / "acquired",
                publisher_reconciliation=_reconciliation(),
                manual_linkage_reviews=review,
                arxiv_transport=arxiv_transport,
                source_transport=lambda url, timeout: _archive(
                    [
                        (
                            "main.tex",
                            "\\documentclass{article}\\begin{document}x\\end{document}",
                        )
                    ]
                ),
                request_interval_s=0,
            )

        self.assertEqual(result["selection_counts"]["selected"], 1)
        resolution = result["paper_results"][0]["resolution"]
        self.assertEqual(resolution["match_method"], "manual_review")
        self.assertTrue(resolution["manual_linkage_review_applied"])
        self.assertEqual(resolution["manual_linkage_review"], review[journal_paper.doi])
        self.assertEqual(resolution["automatic_resolution"]["status"], "not_found")
        self.assertTrue(any("id_list=2607.01234v2" in url for url in calls))

    def test_manual_linkage_review_requires_snapshot_doi_and_complete_record(self):
        journal_paper = _paper(
            "10.1103/example",
            "A research result",
            "Physical Review Letters",
            citations=None,
        )
        valid_review = {
            "arxiv_versioned_id": "2607.01234v2",
            "decision": "match",
            "evidence_locator": "frozen-linkage-review.json#record-1",
            "rationale": "Official author lists and reported results agree.",
            "reviewer": "Record-linkage reviewer A",
        }
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, "not present in the census"):
                acquire_census_snapshot(
                    CensusSnapshot((journal_paper,), (), ()),
                    start=date(2026, 7, 1),
                    end=date(2026, 7, 31),
                    venues=("Physical Review Letters",),
                    output_directory=Path(directory) / "unknown-review",
                    publisher_reconciliation=_reconciliation(),
                    manual_linkage_reviews={"10.1103/other": valid_review},
                    request_interval_s=0,
                )

        incomplete = dict(valid_review)
        del incomplete["evidence_locator"]
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, "must contain exactly"):
                acquire_census_snapshot(
                    CensusSnapshot((journal_paper,), (), ()),
                    start=date(2026, 7, 1),
                    end=date(2026, 7, 31),
                    venues=("Physical Review Letters",),
                    output_directory=Path(directory) / "incomplete-review",
                    publisher_reconciliation=_reconciliation(),
                    manual_linkage_reviews={journal_paper.doi: incomplete},
                    request_interval_s=0,
                )

    def test_manual_review_can_select_an_earlier_version_of_resolved_work(self):
        journal_paper = _paper(
            "10.1103/example",
            "A research result",
            "Physical Review Letters",
            citations=None,
        )
        calls = []

        def arxiv_transport(url, timeout):
            calls.append(url)
            if "id_list=2607.01234v1" in url:
                return _feed(versioned_id="2607.01234v1", doi=journal_paper.doi)
            return _feed(versioned_id="2607.01234v3", doi=journal_paper.doi)

        review = {
            journal_paper.doi: {
                "arxiv_versioned_id": "2607.01234v1",
                "decision": "match",
                "evidence_locator": "frozen-linkage-review.json#record-1",
                "rationale": "The first version is the selected source version.",
                "reviewer": "Record-linkage reviewer A",
            }
        }
        with tempfile.TemporaryDirectory() as directory:
            result = acquire_census_snapshot(
                CensusSnapshot((journal_paper,), (), ()),
                start=date(2026, 7, 1),
                end=date(2026, 7, 31),
                venues=("Physical Review Letters",),
                output_directory=Path(directory) / "acquired",
                publisher_reconciliation=_reconciliation(),
                manual_linkage_reviews=review,
                arxiv_transport=arxiv_transport,
                source_transport=lambda url, timeout: _archive(
                    [
                        (
                            "main.tex",
                            "\\documentclass{article}\\begin{document}x\\end{document}",
                        )
                    ]
                ),
                request_interval_s=0,
            )

        resolution = result["paper_results"][0]["resolution"]
        self.assertEqual(resolution["paper"]["versioned_id"], "2607.01234v1")
        self.assertEqual(resolution["match_method"], "manual_review")
        self.assertTrue(resolution["manual_linkage_review_applied"])
        self.assertEqual(
            resolution["automatic_resolution"]["paper"]["versioned_id"],
            "2607.01234v3",
        )
        self.assertTrue(any("id_list=2607.01234v1" in url for url in calls))

    def test_citation_rank_is_explicit_and_limit_is_not_warmup_hard_coded(self):
        snapshot = CensusSnapshot(
            (
                _paper(
                    "10.1103/example",
                    "A research result",
                    "Physical Review Letters",
                ),
            ),
            (),
            (),
        )
        with tempfile.TemporaryDirectory() as directory:
            result = acquire_census_snapshot(
                snapshot,
                start=date(2026, 7, 1),
                end=date(2026, 7, 31),
                venues=("Physical Review Letters",),
                output_directory=Path(directory) / "acquired",
                selection_policy="citation_rank",
                cohort_limit=30,
                publisher_reconciliation=_reconciliation(),
                arxiv_transport=lambda url, timeout: _feed(),
                source_transport=lambda url, timeout: _archive(
                    [("main.tex", "text\n")]
                ),
                request_interval_s=0,
            )
        self.assertEqual(result["selection"], {"cohort_limit": 30, "policy": "citation_rank"})
        self.assertTrue(result["paper_results"][0]["selection"]["selected"])

    def test_ranked_source_acquisition_and_cohort_selection_are_separate_axes(self):
        low = _paper(
            "10.1103/low", "Low impact", "Physical Review Letters", citations=1
        )
        high = _paper(
            "10.1103/high", "High impact", "Physical Review Letters", citations=9
        )
        reconciliations = {}
        for paper in (low, high):
            reconciliations[paper.doi] = {
                "category": "Letter",
                "original_research": True,
                "publication_date": "2026-07-02",
                "withdrawn_or_retracted": False,
            }

        def resolve(paper, **kwargs):
            suffix = "00001" if paper.doi.endswith("low") else "00002"
            arxiv_paper = ArxivPaper(
                versioned_id="2607.%sv1" % suffix,
                title=paper.title,
                first_author=paper.first_author,
                first_author_family=paper.first_author_family,
                doi=paper.doi,
                entry_url="https://arxiv.org/abs/2607.%sv1" % suffix,
                first_submitted_at=datetime(2026, 7, 1, tzinfo=timezone.utc),
                version_updated_at=datetime(2026, 7, 1, tzinfo=timezone.utc),
            )
            return ArxivResolution("resolved", arxiv_paper, (arxiv_paper,), "doi", 1)

        bundle = LatexBundle(
            files=(LatexSourceFile("main.tex", "text\n"),),
            merged_text="===== BEGIN FILE: main.tex =====\ntext\n"
            "===== END FILE: main.tex =====\n",
        )
        with tempfile.TemporaryDirectory() as directory, patch(
            "role_benchmark.temporal.acquisition.resolve_arxiv_paper",
            side_effect=resolve,
        ), patch(
            "role_benchmark.temporal.acquisition.download_arxiv_source",
            return_value=bundle,
        ):
            result = acquire_census_snapshot(
                CensusSnapshot((low, high), (), ()),
                start=date(2026, 7, 1),
                end=date(2026, 7, 31),
                venues=("Physical Review Letters",),
                output_directory=Path(directory) / "acquired",
                selection_policy="citation_rank",
                cohort_limit=1,
                publisher_reconciliation=reconciliations,
                request_interval_s=0,
            )

        self.assertEqual(
            [paper["journal_doi"] for paper in result["cohort"]["papers"]],
            ["10.1103/high"],
        )
        self.assertEqual(
            result["selection_counts"],
            {"ineligible": 0, "not_selected": 1, "selected": 1},
        )
        by_doi = {
            item["journal"]["doi"]: item for item in result["paper_results"]
        }
        self.assertEqual(by_doi["10.1103/low"]["disposition"], "source_acquired")
        self.assertEqual(by_doi["10.1103/low"]["selection"]["status"], "not_selected")
        self.assertIsNone(by_doi["10.1103/low"]["cohort_entry"])
        self.assertEqual(by_doi["10.1103/high"]["selection"]["status"], "selected")
        validate_acquisition_cohort_handoff(result["cohort"], result)

    def test_more_than_sixty_selected_sources_are_not_coordinator_ready(self):
        papers = tuple(
            _paper(
                "10.1103/paper%d" % index,
                "Paper %d" % index,
                "Physical Review Letters",
            )
            for index in range(MAX_COORDINATOR_COHORT_SIZE + 1)
        )
        reconciliations = {
            paper.doi: {
                "category": "Letter",
                "original_research": True,
                "publication_date": "2026-07-02",
                "withdrawn_or_retracted": False,
            }
            for paper in papers
        }

        def resolve(paper, **kwargs):
            index = int(paper.doi.rsplit("paper", 1)[1])
            arxiv_paper = ArxivPaper(
                versioned_id="2607.%05dv1" % index,
                title=paper.title,
                first_author=paper.first_author,
                first_author_family=paper.first_author_family,
                doi=paper.doi,
                entry_url="https://arxiv.org/abs/2607.%05dv1" % index,
                first_submitted_at=datetime(2026, 7, 1, tzinfo=timezone.utc),
                version_updated_at=datetime(2026, 7, 1, tzinfo=timezone.utc),
            )
            return ArxivResolution("resolved", arxiv_paper, (arxiv_paper,), "doi", 1)

        bundle = LatexBundle(
            files=(LatexSourceFile("main.tex", "text\n"),),
            merged_text="===== BEGIN FILE: main.tex =====\ntext\n"
            "===== END FILE: main.tex =====\n",
        )
        with tempfile.TemporaryDirectory() as directory, patch(
            "role_benchmark.temporal.acquisition.resolve_arxiv_paper",
            side_effect=resolve,
        ), patch(
            "role_benchmark.temporal.acquisition.download_arxiv_source",
            return_value=bundle,
        ):
            result = acquire_census_snapshot(
                CensusSnapshot(papers, (), ()),
                start=date(2026, 7, 1),
                end=date(2026, 7, 31),
                venues=("Physical Review Letters",),
                output_directory=Path(directory) / "acquired",
                publisher_reconciliation=reconciliations,
                request_interval_s=0,
            )

        provenance = result["cohort"]["provenance"]
        self.assertEqual(
            provenance["selected_count"], MAX_COORDINATOR_COHORT_SIZE + 1
        )
        self.assertFalse(provenance["coordinator_ready"])
        self.assertEqual(
            provenance["handoff_status"], "cohort_exceeds_coordinator_limit"
        )
        with self.assertRaisesRegex(ValueError, "not coordinator-ready"):
            validate_acquisition_cohort_handoff(result["cohort"], result)


if __name__ == "__main__":
    unittest.main()
