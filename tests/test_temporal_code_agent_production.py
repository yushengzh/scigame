from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from experiments.run_temporal_code_agent_production import (
    compile_cases,
    prepare,
    summarize,
    validate_cards,
)


def _write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _manifest(
    source_packet: Path, *, count: int = 1, family_index_offset: int = 0
) -> dict:
    sources = []
    for index in range(1, count + 1):
        sources.append(
            {
                "order": index,
                "paper_id": "paper_%02d" % index,
                "source_citation": "A. Author, Example relation, Nature (2026)",
                "journal_doi": "10.0000/example-%02d" % index,
                "arxiv_versioned_id": "2601.%05dv1" % index,
                "local_source_packet_path": str(source_packet),
                "venue_priority_rank": 1,
                "journal_publication_date": "2026-01-15",
                "arxiv_first_submitted_date": "2026-01-12",
                "earliest_public_date": "2026-01-12",
                "linkage_method": "doi",
                "linkage_evidence": {
                    "journal_doi": "10.0000/example-%02d" % index,
                    "arxiv_doi": "10.0000/example-%02d" % index,
                },
            }
        )
    manifest = {"cohort_size": count, "sources": sources}
    if family_index_offset:
        manifest["family_index_offset"] = family_index_offset
    return manifest


def _provider_payload() -> dict:
    anchor_1 = [{"line_start": 1, "line_end": 1}]
    anchor_2 = [{"line_start": 2, "line_end": 2}]
    anchor_3 = [{"line_start": 3, "line_end": 3}]
    anchor_4 = [{"line_start": 4, "line_end": 4}]
    return {
        "relations": [
            {
                "formula": {
                    "outputs": {
                        "response_y": {
                            "op": "multiply",
                            "args": [
                                {"param": "scale"},
                                {"var": "input_x"},
                            ],
                        }
                    }
                },
                "parameters": [
                    {
                        "name": "scale",
                        "value": 2.0,
                        "unit": "dimensionless",
                        "anchors": anchor_1,
                    }
                ],
                "controls": [
                    {
                        "name": "input_x",
                        "definition": "Controlled numeric input.",
                        "unit": "arbitrary_unit",
                        "anchors": anchor_2,
                    }
                ],
                "readouts": [
                    {
                        "name": "response_y",
                        "definition": "Measured numeric response.",
                        "unit": "arbitrary_unit",
                        "anchors": anchor_3,
                    }
                ],
                "domain": {
                    "controls": [
                        {
                            "control_name": "input_x",
                            "domain_kind": "continuous_interval",
                            "minimum": 1.0,
                            "maximum": 9.0,
                            "allowed_values": [],
                            "anchors": anchor_2,
                        }
                    ],
                    "applicability": [
                        {
                            "statement": "Fixed experimental context.",
                            "anchors": anchor_4,
                        }
                    ],
                },
                "anchors": anchor_1,
            }
        ]
    }


class TemporalCodeAgentProductionTests(unittest.TestCase):
    def test_end_to_end_adapter_reuses_minimal_pipeline_and_two_task_checks(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source_packet = root / "source_packet.txt"
            source_packet.write_text(
                "The relation is response_y = 2 input_x.\n"
                "The controlled input_x ranges from 1 to 9 arbitrary units.\n"
                "The response_y readout is reported in arbitrary units.\n"
                "The relation applies in a fixed experimental context.\n",
                encoding="utf-8",
            )
            manifest_path = root / "frozen_sources.json"
            _write_json(
                manifest_path,
                _manifest(source_packet, family_index_offset=1000),
            )
            output = root / "run"

            preparation = prepare(manifest_path, output)
            self.assertEqual(preparation["prepared_count"], 1)
            paper = output / "papers" / "001_paper_01"
            request = json.loads(
                (paper / "authoring" / "request.json").read_text(encoding="utf-8")
            )
            self.assertEqual(
                request["metadata"]["purpose"], "temporal_minimal_science_card"
            )
            execution = json.loads(
                (paper / "authoring" / "execution.json").read_text(encoding="utf-8")
            )
            self.assertFalse(execution["api_invoked_by_adapter"])
            self.assertIsNone(execution["immutable_model_snapshot_id"])
            frozen_source = json.loads(
                (paper / "source.json").read_text(encoding="utf-8")
            )
            self.assertEqual(frozen_source["venue_priority_rank"], 1)
            self.assertEqual(frozen_source["linkage_method"], "doi")

            _write_json(
                paper / "authoring" / "raw_response.json", _provider_payload()
            )
            validation = validate_cards(output)
            self.assertEqual(validation["completed_count"], 1)
            self.assertEqual(validation["failed_count"], 0)

            review = json.loads(
                (paper / "source_review_request.json").read_text(encoding="utf-8")
            )
            review.update(
                {
                    "reviewer": "Code Agent source review in a separate context",
                    "decision": "eligible_for_temporal_case",
                    "assessment": (
                        "The cited lines support the executable relation and domain."
                    ),
                    "checks": {
                        "source_support_confirmed": True,
                        "cartesian_domain_supported": True,
                        "deterministic_central_value_appropriate": True,
                    },
                    "issues": [],
                }
            )
            _write_json(paper / "source_review.json", review)

            construction = compile_cases(output)
            self.assertEqual(construction["failed_count"], 0)
            self.assertEqual(construction["completed"][0]["status"], "case_accepted")
            self.assertEqual(
                construction["completed"][0]["family"], "temporal_source_1001"
            )
            canary = json.loads(
                (paper / "construction" / "validation.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(
                [cell["track"] for cell in canary["cells"]],
                ["identification", "discovery"],
            )
            self.assertTrue(all(cell["known_truth_passes"] for cell in canary["cells"]))

            summary = summarize(output, target_family_count=1)
            self.assertTrue(summary["target_met"])
            self.assertEqual(summary["fixed_denominator"], 1)
            self.assertEqual(summary["distinct_family_count"], 1)
            self.assertEqual(summary["family_index_offset"], 1000)
            self.assertEqual(summary["funnel"]["final_acceptance"]["rate"], 1.0)
            self.assertFalse(
                summary["review_independence"]["established_by_adapter"]
            )

    def test_invalid_provider_shape_is_recorded_without_scientific_repair(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source_packet = root / "source_packet.txt"
            source_packet.write_text("One source line.\n", encoding="utf-8")
            manifest_path = root / "frozen_sources.json"
            _write_json(manifest_path, _manifest(source_packet))
            output = root / "run"
            prepare(manifest_path, output)
            paper = output / "papers" / "001_paper_01"
            _write_json(
                paper / "authoring" / "raw_response.json",
                {"relations": [], "unexpected": "must fail"},
            )

            validation = validate_cards(output)
            self.assertEqual(validation["completed_count"], 0)
            self.assertEqual(validation["failed_count"], 1)
            self.assertFalse((paper / "science_card.json").exists())
            failure = json.loads(
                (paper / "authoring" / "validation_failure.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(failure["status"], "card_validation_failed")
            self.assertEqual(failure["error_code"], "minimal_science_card.schema")

    def test_summary_keeps_unprocessed_papers_in_the_fixed_denominator(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source_packet = root / "source_packet.txt"
            source_packet.write_text("One source line.\n", encoding="utf-8")
            manifest_path = root / "frozen_sources.json"
            _write_json(manifest_path, _manifest(source_packet, count=2))
            output = root / "run"
            prepare(manifest_path, output)

            summary = summarize(output, target_family_count=1)
            self.assertEqual(summary["fixed_denominator"], 2)
            self.assertEqual(summary["funnel"]["source_prepared"]["count"], 2)
            self.assertEqual(
                summary["funnel"]["authoring_response_present"]["count"], 0
            )
            self.assertEqual(summary["funnel"]["final_acceptance"]["denominator"], 2)
            self.assertEqual(summary["funnel"]["final_acceptance"]["rate"], 0.0)


if __name__ == "__main__":
    unittest.main()
