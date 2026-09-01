from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path

from role_benchmark.temporal import (
    parse_warmup_cohort_json,
    select_temporal_cohort,
    validate_acquisition_cohort_handoff,
)


def _entry(index: int):
    paper_id = "paper_2604_%05dv1" % index
    return {
        "article_type": "journal-article",
        "arxiv_versioned_id": "2604.%05dv1" % index,
        "citation_count": 10 - index,
        "earliest_public_date": "2026-03-%02d" % index,
        "journal_doi": "10.1103/example%d" % index,
        "latex_available": True,
        "paper_id": paper_id,
        "publication_date": "2026-04-%02d" % index,
        "source_citation": "A. Author, Paper %d, PRL (2026)" % index,
        "source_packet_path": "papers/%s/source_packet.txt" % paper_id,
        "tex_path": "papers/%s/source.tex" % paper_id,
        "title": "Paper %d" % index,
        "venue": "Physical Review Letters",
        "withdrawn_or_retracted": False,
    }


def _result(entry, rank):
    return {
        "cohort_entry": copy.deepcopy(entry),
        "disposition": "source_acquired",
        "journal": {
            "doi": entry["journal_doi"],
            "title": entry["title"],
        },
        "publisher_reconciliation": {
            "verification_status": "publisher_reconciled"
        },
        "reason_code": None,
        "resolution": {"status": "resolved"},
        "selection": {
            "policy": "citation_rank",
            "rank": rank,
            "selected": True,
            "status": "selected",
        },
        "source": {
            "arxiv_versioned_id": entry["arxiv_versioned_id"],
            "member_count": 1,
            "publisher_verification_status": "publisher_reconciled",
            "source_packet_path": entry["source_packet_path"],
            "tex_path": entry["tex_path"],
        },
    }


def _write_handoff(directory: Path, count: int = 3):
    entries = [_entry(index) for index in range(1, count + 1)]
    provenance = {
        "acquisition_schema": "role_benchmark.temporal_acquisition",
        "coordinator_ready": True,
        "handoff_status": "coordinator_ready",
        "retrieved_at": "2026-08-27T00:00:00+00:00",
        "selected_count": len(entries),
        "selection_policy": "citation_rank",
    }
    cohort = {
        "papers": entries,
        "provenance": provenance,
        "window": {
            "earliest_public_not_before": None,
            "end": "2026-06-30",
            "start": "2026-04-01",
        },
    }
    results = [_result(entry, rank) for rank, entry in enumerate(entries, 1)]
    results.append(
        {
            "cohort_entry": None,
            "disposition": "not_original_research",
            "journal": {"doi": "10.1103/ineligible"},
            "publisher_reconciliation": {"verification_status": "publisher_reconciled"},
            "reason_code": "paper.not_original_research",
            "resolution": None,
            "selection": {
                "policy": "citation_rank",
                "rank": None,
                "selected": False,
                "status": "ineligible",
            },
            "source": None,
        }
    )
    acquisition = {
        "census": {"papers": [{"doi": entry["journal_doi"]} for entry in entries]},
        "cohort": cohort,
        "paper_results": results,
        "publisher_reconciliation": {
            "records": {entry["journal_doi"]: {"checked": True} for entry in entries},
            "required_for_cohort": True,
        },
        "retrieved_at": provenance["retrieved_at"],
        "schema": "role_benchmark.temporal_acquisition",
        "selection": {"cohort_limit": len(entries), "policy": "citation_rank"},
        "selection_counts": {
            "ineligible": 1,
            "not_selected": 0,
            "selected": len(entries),
        },
        "warmup_handoff": copy.deepcopy(provenance),
    }
    directory.mkdir()
    for index, entry in enumerate(entries, 1):
        paper_directory = directory / "papers" / entry["paper_id"]
        paper_directory.mkdir(parents=True)
        (paper_directory / "source.tex").write_text(
            "paper %d tex\n" % index, encoding="utf-8"
        )
        (paper_directory / "source_packet.txt").write_text(
            "paper %d packet\n" % index, encoding="utf-8"
        )
        (paper_directory / "paper.json").write_text(
            json.dumps(results[index - 1]), encoding="utf-8"
        )
    (directory / "cohort.json").write_text(
        json.dumps(cohort), encoding="utf-8"
    )
    (directory / "acquisition.json").write_text(
        json.dumps(acquisition), encoding="utf-8"
    )
    validate_acquisition_cohort_handoff(cohort, acquisition)
    return cohort, acquisition


class TemporalCohortSelectionTests(unittest.TestCase):
    def test_selects_ordered_subset_and_preserves_provenance(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            input_cohort, input_acquisition = _write_handoff(source)
            frozen_input = copy.deepcopy(input_acquisition)
            output = root / "selected"

            result = select_temporal_cohort(
                source / "cohort.json",
                output,
                paper_ids=("paper_2604_00003v1", "paper_2604_00001v1"),
            )

            self.assertEqual(
                [paper["paper_id"] for paper in result["cohort"]["papers"]],
                ["paper_2604_00001v1", "paper_2604_00003v1"],
            )
            self.assertEqual(result["selection"]["cohort_limit"], 2)
            self.assertEqual(
                result["selection_counts"],
                {"ineligible": 1, "not_selected": 1, "selected": 2},
            )
            self.assertEqual(result["warmup_handoff"]["selected_count"], 2)
            self.assertEqual(result["census"], input_acquisition["census"])
            self.assertEqual(
                result["publisher_reconciliation"],
                input_acquisition["publisher_reconciliation"],
            )
            by_doi = {item["journal"]["doi"]: item for item in result["paper_results"]}
            self.assertEqual(by_doi["10.1103/example1"]["selection"]["rank"], 1)
            self.assertEqual(by_doi["10.1103/example3"]["selection"]["rank"], 2)
            self.assertEqual(
                by_doi["10.1103/example2"]["selection"],
                {
                    "policy": "citation_rank",
                    "rank": 3,
                    "selected": False,
                    "status": "not_selected",
                },
            )
            self.assertIsNone(by_doi["10.1103/example2"]["cohort_entry"])
            self.assertEqual(input_acquisition, frozen_input)
            self.assertEqual(
                (output / "papers/paper_2604_00003v1/source.tex").read_text(),
                "paper 3 tex\n",
            )
            self.assertFalse((output / "papers/paper_2604_00002v1").exists())
            self.assertEqual(
                json.loads(
                    (output / "papers/paper_2604_00001v1/paper.json").read_text()
                ),
                by_doi["10.1103/example1"],
            )
            on_disk_cohort = json.loads((output / "cohort.json").read_text())
            on_disk_acquisition = json.loads((output / "acquisition.json").read_text())
            validate_acquisition_cohort_handoff(on_disk_cohort, on_disk_acquisition)
            parsed = parse_warmup_cohort_json(
                (output / "cohort.json").read_text(), base_directory=output
            )
            self.assertEqual(len(parsed.papers), 2)
            self.assertTrue(all(paper.tex_path.is_file() for paper in parsed.papers))

            # An exact rerun is a no-op and returns the same validated payload.
            rerun = select_temporal_cohort(
                source,
                output,
                paper_ids=("paper_2604_00001v1", "paper_2604_00003v1"),
            )
            self.assertEqual(rerun, result)
            self.assertEqual(input_cohort["window"], result["cohort"]["window"])

    def test_refuses_duplicate_unknown_and_oversized_id_sets(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            _write_handoff(source)
            with self.assertRaisesRegex(ValueError, "duplicate paper_ids"):
                select_temporal_cohort(
                    source,
                    root / "duplicate",
                    paper_ids=("paper_2604_00001v1", "paper_2604_00001v1"),
                )
            with self.assertRaisesRegex(ValueError, "unknown paper_ids"):
                select_temporal_cohort(
                    source,
                    root / "unknown",
                    paper_ids=("paper_unknown",),
                )
            with self.assertRaisesRegex(ValueError, "between 1 and 60"):
                select_temporal_cohort(
                    source,
                    root / "oversized",
                    paper_ids=("paper_%d" % index for index in range(61)),
                )

    def test_refuses_existing_incompatible_output_without_overwriting_it(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            _write_handoff(source)
            output = root / "selected"
            output.mkdir()
            marker = output / "keep.txt"
            marker.write_text("user data\n", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "existing output is incompatible"):
                select_temporal_cohort(
                    source,
                    output,
                    paper_ids=("paper_2604_00001v1",),
                )
            self.assertEqual(marker.read_text(encoding="utf-8"), "user data\n")


if __name__ == "__main__":
    unittest.main()
