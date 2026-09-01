from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from role_benchmark import GenerationResponse
from role_benchmark.wire import canonical_json_dumps
from role_benchmark.temporal.candidate import (
    CandidateDecodeError,
    paper_abstraction_to_payload,
    parse_paper_abstraction_json,
    temporal_paper_abstraction_json_schema,
)
from role_benchmark.temporal.extract import (
    build_paper_abstraction_request,
    extract_paper_abstraction,
)
from role_benchmark.temporal.cli import _parser as temporal_cli_parser
from role_benchmark.temporal.cli import main as temporal_cli_main


def _candidate_payload(family: str = "paper_response"):
    return {
        "family": family,
        "title": "Controlled response",
        "claim": "The response follows a reported two-control relation.",
        "source": {
            "citation": "A. Author et al., Example Journal (2026)",
            "journal_doi": "10.0000/example",
            "arxiv_versioned_id": "2607.01234v2",
            "locator": "Equation 3 and Figure 2",
            "role": "The equation and fitted values define the paper world.",
        },
        "apparatus": {
            "name": "response_apparatus",
            "description": "Two independently adjustable numeric inputs.",
        },
        "background": "A response changes when either input is adjusted.",
        "initial_observations": ["Both inputs can be controlled independently."],
        "common_fixed_conditions": [],
        "controls": [
            {
                "name": "input_x",
                "description": "First input.",
                "unit": "a.u.",
                "minimum": 1.0,
                "maximum": 9.0,
            },
            {
                "name": "input_y",
                "description": "Second input.",
                "unit": "a.u.",
                "minimum": 1.0,
                "maximum": 5.0,
            },
        ],
        "readouts": [
            {
                "name": "response",
                "description": "Measured response.",
                "unit": "a.u.",
                "resolution": 0.01,
                "statistic": "Deterministic response.",
                "uncertainty": "source_unspecified",
                "resolution_kind": "reporting_increment",
            }
        ],
        "oracle": {
            "kind": "closed_form",
            "outputs": {
                "response": {
                    "op": "multiply",
                    "args": [
                        {"param": "scale"},
                        {"var": "input_x"},
                        {"var": "input_y"},
                    ],
                }
            },
            "paper_parameters": {"scale": 2.0},
            "counterfactual_parameters": {"scale": 3.0},
            "paper_applicability": ["Reported candidate domain."],
            "counterfactual_applicability": ["Reported candidate domain."],
            "paper_fixed_conditions": [],
            "counterfactual_fixed_conditions": [],
        },
        "diagnostic_conditions": [
            {"input_x": 1.0, "input_y": 1.0},
            {"input_x": 9.0, "input_y": 5.0},
        ],
        "hidden_conditions": [{"input_x": 4.0, "input_y": 3.0}],
        "budget": 4,
        "max_replicates": 2,
        "confidence_threshold": 0.9,
        "relative_tolerance": 0.05,
        "notes": ["Keep nuisance variables fixed."],
        "counterfactual_change": "Only scale changes from 2.0 to 3.0.",
    }


def _abstraction_payload(*candidates):
    return {
        "assessment": "The paper supports the listed quantitative claims.",
        "candidates": list(candidates),
    }


_SOURCE_ARGS = [
    "--source-citation",
    "A. Author et al., Example Journal (2026)",
    "--journal-doi",
    "10.0000/example",
    "--arxiv-versioned-id",
    "2607.01234v2",
]


class _FakeBackend:
    def __init__(self, payload, *, finish_reason=""):
        self.payload = payload
        self.finish_reason = finish_reason
        self.requests = []

    def generate(self, request):
        self.requests.append(request)
        return GenerationResponse(
            text=json.dumps(self.payload),
            provider="fake",
            model="fake-abstractor",
            finish_reason=self.finish_reason,
        )


class TemporalAbstractionTests(unittest.TestCase):
    def test_empty_candidate_list_is_a_valid_paper_result(self):
        abstraction = parse_paper_abstraction_json(
            json.dumps(
                {
                    "assessment": "No supported closed-form experimental claim was found.",
                    "candidates": [],
                }
            )
        )
        self.assertEqual(abstraction.candidates, ())
        self.assertEqual(
            parse_paper_abstraction_json(
                json.dumps(paper_abstraction_to_payload(abstraction))
            ),
            abstraction,
        )

    def test_outer_and_nested_json_are_strict(self):
        with self.assertRaises(CandidateDecodeError) as duplicate:
            parse_paper_abstraction_json(
                '{"assessment":"first","assessment":"second","candidates":[]}'
            )
        self.assertEqual(duplicate.exception.code, "candidate.invalid_json")

        payload = _abstraction_payload()
        payload["unknown"] = True
        with self.assertRaises(CandidateDecodeError) as unknown:
            parse_paper_abstraction_json(json.dumps(payload))
        self.assertEqual(unknown.exception.path, "$")

        candidate = _candidate_payload()
        candidate["unknown"] = True
        with self.assertRaises(CandidateDecodeError) as nested:
            parse_paper_abstraction_json(
                json.dumps(_abstraction_payload(candidate))
            )
        self.assertEqual(nested.exception.path, "$.candidates[0]")

    def test_batch_rejects_duplicate_families(self):
        with self.assertRaises(CandidateDecodeError) as duplicate:
            parse_paper_abstraction_json(
                json.dumps(
                    _abstraction_payload(
                        _candidate_payload("same_family"),
                        _candidate_payload("same_family"),
                    )
                )
            )
        self.assertEqual(duplicate.exception.code, "abstraction.duplicate_family")
        self.assertEqual(duplicate.exception.path, "$.candidates[1].family")

    def test_outer_schema_promotes_candidate_expression_definitions(self):
        schema = temporal_paper_abstraction_json_schema()
        self.assertFalse(schema["additionalProperties"])
        candidates = schema["properties"]["candidates"]
        self.assertEqual(candidates["minItems"], 0)
        self.assertNotIn("maxItems", candidates)
        self.assertEqual(
            candidates["items"]["$ref"], "#/$defs/temporal_case_candidate"
        )
        candidate = schema["$defs"]["temporal_case_candidate"]
        self.assertEqual(candidate["properties"]["controls"]["minItems"], 1)
        self.assertNotIn("$defs", candidate)
        self.assertEqual(
            candidate["properties"]["oracle"]["properties"]["outputs"][
                "additionalProperties"
            ]["$ref"],
            "#/$defs/expression_template",
        )
        identifier_pattern = "^[a-z][a-z0-9_]*$"
        self.assertEqual(candidate["properties"]["family"]["pattern"], identifier_pattern)
        self.assertEqual(
            candidate["properties"]["controls"]["items"]["properties"]["name"][
                "pattern"
            ],
            identifier_pattern,
        )
        self.assertEqual(
            candidate["properties"]["oracle"]["properties"]["paper_parameters"][
                "propertyNames"
            ]["pattern"],
            identifier_pattern,
        )

    def test_canonical_request_and_extraction_are_plural(self):
        payload = _abstraction_payload(
            _candidate_payload("claim_one"),
            _candidate_payload("claim_two"),
        )
        backend = _FakeBackend(payload)
        result = extract_paper_abstraction(
            backend,
            "\\documentclass{article}\n\\begin{document}x\\end{document}",
            source_citation="A. Author et al., Example Journal (2026)",
            journal_doi="10.0000/example",
            arxiv_versioned_id="2607.01234v2",
        )
        self.assertEqual(
            [item.family for item in result.abstraction.candidates],
            ["claim_one", "claim_two"],
        )
        request = backend.requests[0]
        self.assertEqual(request.metadata["purpose"], "temporal_paper_abstraction")
        self.assertIn("candidates=[]", request.messages[0].content)
        self.assertIn("each distinct quantitative claim", request.messages[0].content)
        self.assertIn("Encode sqrt(x) as power(x, 0.5)", request.messages[0].content)
        self.assertIn("copy the complete paper-parameter key set", request.messages[0].content)
        self.assertIn("every named parameter must occur", request.messages[0].content)
        self.assertIn("every control at least two distinct values", request.messages[0].content)

        built = build_paper_abstraction_request(
            "paper",
            source_citation="A. Author et al., Example Journal (2026)",
            journal_doi="10.0000/example",
            arxiv_versioned_id="2607.01234v2",
        )
        self.assertEqual(built.metadata["purpose"], "temporal_paper_abstraction")
        self.assertIn(
            "PaperAbstraction JSON Schema:\n"
            + canonical_json_dumps(built.response_schema),
            built.messages[0].content,
        )

    def test_incomplete_generation_is_rejected_before_parsing(self):
        for finish_reason in ("length", "incomplete:max_output_tokens"):
            with self.subTest(finish_reason=finish_reason):
                with self.assertRaises(CandidateDecodeError) as raised:
                    extract_paper_abstraction(
                        _FakeBackend(
                            _abstraction_payload(), finish_reason=finish_reason
                        ),
                        "paper",
                        source_citation="A. Author et al., Example Journal (2026)",
                        journal_doi="10.0000/example",
                        arxiv_versioned_id="2607.01234v2",
                    )
                self.assertEqual(
                    raised.exception.code, "abstraction.incomplete_generation"
                )

    def test_authoritative_source_identity_is_injected_and_checked(self):
        citation = "A. Author et al., Example Journal (2026)"
        journal_doi = "10.0000/example"
        arxiv_versioned_id = "2607.01234v2"
        request = build_paper_abstraction_request(
            "paper",
            source_citation=citation,
            journal_doi=journal_doi,
            arxiv_versioned_id=arxiv_versioned_id,
        )
        self.assertIn(citation, request.messages[1].content)
        self.assertIn(journal_doi, request.messages[1].content)
        self.assertIn(arxiv_versioned_id, request.messages[1].content)

        result = extract_paper_abstraction(
            _FakeBackend(_abstraction_payload(_candidate_payload())),
            "paper",
            source_citation=citation,
            journal_doi=journal_doi,
            arxiv_versioned_id=arxiv_versioned_id,
        )
        self.assertEqual(
            result.abstraction.candidates[0].source.arxiv_versioned_id,
            arxiv_versioned_id,
        )

        wrong = _candidate_payload()
        wrong["source"]["arxiv_versioned_id"] = "2607.99999v1"
        with self.assertRaises(CandidateDecodeError) as mismatch:
            extract_paper_abstraction(
                _FakeBackend(_abstraction_payload(wrong)),
                "paper",
                source_citation=citation,
                journal_doi=journal_doi,
                arxiv_versioned_id=arxiv_versioned_id,
            )
        self.assertEqual(mismatch.exception.code, "abstraction.source_identity")

    def test_cli_validates_every_candidate_without_rendering(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            abstraction = root / "abstraction.json"
            abstraction.write_text(
                json.dumps(_abstraction_payload(_candidate_payload())),
                encoding="utf-8",
            )
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                code = temporal_cli_main(
                    ["validate-abstraction", str(abstraction), *_SOURCE_ARGS]
                )
            report = json.loads(stdout.getvalue())
            self.assertEqual(code, 0)
            self.assertEqual(report["candidate_count"], 1)
            self.assertEqual(report["eligible_count"], 1)

    def test_cli_accepts_a_paper_with_no_abstractable_cases(self):
        with tempfile.TemporaryDirectory() as directory:
            abstraction = Path(directory) / "abstraction.json"
            abstraction.write_text(
                json.dumps(
                    {
                        "assessment": "No supported experimental claim.",
                        "candidates": [],
                    }
                ),
                encoding="utf-8",
            )
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                code = temporal_cli_main(
                    ["validate-abstraction", str(abstraction), *_SOURCE_ARGS]
                )
        self.assertEqual(code, 0)
        report = json.loads(stdout.getvalue())
        self.assertEqual(report["candidate_count"], 0)
        self.assertEqual(report["eligible_count"], 0)

    def test_main_cli_has_no_unreviewed_render_command(self):
        self.assertNotIn("render-abstraction", temporal_cli_parser().format_help())


if __name__ == "__main__":
    unittest.main()
