from __future__ import annotations

import copy
import contextlib
import importlib.util
import io
import json
import tempfile
import unittest
from datetime import date
from pathlib import Path

from role_benchmark import ExperimentProposal, GenerationResponse
from role_benchmark.cases.matched import make_matched_case, truth_submission
from role_benchmark.models import BenchmarkTrack
from role_benchmark.temporal import (
    CandidateDecodeError,
    SourcePaper,
    candidate_to_payload,
    extract_paper_abstraction,
    filter_candidate,
    normalize_latex,
    parse_candidate_json,
    prefilter_papers,
    rank_papers,
    build_matched_spec,
    render_candidate_module,
    temporal_candidate_json_schema,
)
from role_benchmark.temporal.cli import main as temporal_cli_main


def _candidate_payload():
    return {
        "family": "paper_response",
        "title": "the controlled response",
        "claim": "The response follows the reported two-control power law.",
        "source": {
            "citation": "A. Author et al., Example Journal (2026)",
            "journal_doi": "10.0000/example",
            "arxiv_versioned_id": "2607.01234v2",
            "locator": "Equation 3 and Figure 2",
            "role": "Equation and fitted values define the paper-grounded world.",
        },
        "apparatus": {
            "name": "response_apparatus",
            "description": "An apparatus with two independently adjustable inputs.",
        },
        "background": "A measurable response changes when either available input is adjusted.",
        "initial_observations": ["Both controls can be set independently."],
        "common_fixed_conditions": [],
        "controls": [
            {
                "name": "input_x",
                "description": "First controlled input.",
                "unit": "a.u.",
                "minimum": 1.0,
                "maximum": 9.0,
            },
            {
                "name": "input_y",
                "description": "Second controlled input.",
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
                        {
                            "op": "power",
                            "args": [{"var": "input_x"}, {"param": "x_exponent"}],
                        },
                        {"var": "input_y"},
                    ],
                }
            },
            "paper_parameters": {"scale": 2.0, "x_exponent": 1.0},
            "counterfactual_parameters": {"scale": 2.0, "x_exponent": 0.5},
            "paper_applicability": ["Reported candidate domain."],
            "counterfactual_applicability": ["Reported candidate domain."],
            "paper_fixed_conditions": [],
            "counterfactual_fixed_conditions": [],
        },
        "diagnostic_conditions": [
            {"input_x": 1.0, "input_y": 1.0},
            {"input_x": 4.0, "input_y": 3.0},
            {"input_x": 9.0, "input_y": 5.0},
        ],
        "hidden_conditions": [
            {"input_x": 2.0, "input_y": 2.0},
            {"input_x": 6.0, "input_y": 4.0},
            {"input_x": 8.0, "input_y": 1.5},
        ],
        "budget": 6,
        "max_replicates": 4,
        "confidence_threshold": 0.9,
        "relative_tolerance": 0.05,
        "notes": ["Keep unlisted nuisance factors fixed."],
        "counterfactual_change": "Only x_exponent changes from 1.0 to 0.5.",
    }


def _candidate_json(payload=None):
    return json.dumps(payload or _candidate_payload())


class _FakeBackend:
    def __init__(self, output):
        self.output = output
        self.requests = []

    def generate(self, request):
        self.requests.append(request)
        return GenerationResponse(
            text=self.output,
            provider="fake",
            model="fake-extractor",
        )


class TemporalPipelineTests(unittest.TestCase):
    def test_normalizes_single_latex_source_without_destroying_escaped_percent(self):
        source = """\\documentclass{article} % remove this


\\begin{document}
Efficiency is 90\\% accurate. % and this
E = mc^2
\\end{document}
"""
        normalized = normalize_latex(source)
        self.assertIn("Efficiency is 90\\% accurate.", normalized)
        self.assertNotIn("remove this", normalized)
        self.assertNotIn("and this", normalized)
        self.assertNotIn("\n\n\n", normalized)

    def test_strict_json_rejects_fences_trailing_text_and_unknown_fields(self):
        with self.assertRaises(CandidateDecodeError) as fenced:
            parse_candidate_json("```json\n%s\n```" % _candidate_json())
        self.assertEqual(fenced.exception.code, "candidate.invalid_json")

        with self.assertRaises(CandidateDecodeError):
            parse_candidate_json(_candidate_json() + " trailing")

        with self.assertRaises(CandidateDecodeError) as duplicate:
            parse_candidate_json('{"family":"first","family":"second"}')
        self.assertEqual(duplicate.exception.code, "candidate.invalid_json")

        payload = _candidate_payload()
        payload["unexpected"] = True
        with self.assertRaises(CandidateDecodeError) as unknown:
            parse_candidate_json(_candidate_json(payload))
        self.assertEqual(unknown.exception.code, "candidate.schema")

        payload = _candidate_payload()
        payload["oracle"]["outputs"][" response "] = payload["oracle"][
            "outputs"
        ]["response"]
        with self.assertRaises(CandidateDecodeError) as spaced_key:
            parse_candidate_json(_candidate_json(payload))
        self.assertEqual(spaced_key.exception.code, "candidate.schema")
        self.assertEqual(spaced_key.exception.path, "$.oracle.outputs.<key>")

    def test_filter_accepts_closed_form_candidate_and_rejects_bad_domains(self):
        candidate = parse_candidate_json(_candidate_json())
        self.assertTrue(filter_candidate(candidate).eligible)

        payload = _candidate_payload()
        payload["hidden_conditions"][0]["input_x"] = 100.0
        result = filter_candidate(parse_candidate_json(_candidate_json(payload)))
        self.assertFalse(result.eligible)
        self.assertIn("conditions.out_of_range", {issue.code for issue in result.issues})

        payload = _candidate_payload()
        payload["oracle"]["outputs"]["response"]["args"][2] = {
            "var": "undeclared_input"
        }
        result = filter_candidate(parse_candidate_json(_candidate_json(payload)))
        self.assertIn("oracle.unknown_variable", {issue.code for issue in result.issues})

    def test_candidate_resolution_contract_accepts_only_atomic_nullable_pairs(self):
        payload = _candidate_payload()
        payload["readouts"][0]["resolution"] = None
        payload["readouts"][0]["resolution_kind"] = None
        candidate = parse_candidate_json(_candidate_json(payload))
        self.assertIsNone(candidate.readouts[0].resolution)
        self.assertIsNone(candidate.readouts[0].resolution_kind)
        self.assertEqual(
            parse_candidate_json(json.dumps(candidate_to_payload(candidate))),
            candidate,
        )

        readout_schema = temporal_candidate_json_schema()["properties"][
            "readouts"
        ]["items"]
        self.assertEqual(len(readout_schema["oneOf"]), 2)
        self.assertEqual(
            readout_schema["oneOf"][1]["properties"]["resolution"],
            {"type": "null"},
        )

        for resolution, resolution_kind in (
            (None, "reporting_increment"),
            (0.01, None),
        ):
            with self.subTest(
                resolution=resolution, resolution_kind=resolution_kind
            ):
                invalid = _candidate_payload()
                invalid["readouts"][0]["resolution"] = resolution
                invalid["readouts"][0]["resolution_kind"] = resolution_kind
                with self.assertRaises(CandidateDecodeError) as mismatch:
                    parse_candidate_json(_candidate_json(invalid))
                self.assertEqual(mismatch.exception.code, "candidate.schema")

        invalid = _candidate_payload()
        invalid["readouts"][0]["resolution"] = -0.01
        result = filter_candidate(parse_candidate_json(_candidate_json(invalid)))
        self.assertIn(
            "readout.invalid_resolution", {issue.code for issue in result.issues}
        )

    def test_null_resolution_uses_relative_tolerance_for_distinguishability(self):
        def scaled_candidate(counterfactual_scale):
            payload = _candidate_payload()
            payload["readouts"][0]["resolution"] = None
            payload["readouts"][0]["resolution_kind"] = None
            payload["oracle"]["outputs"]["response"] = {
                "op": "multiply",
                "args": [
                    {"param": "scale"},
                    {"var": "input_x"},
                    {"var": "input_y"},
                ],
            }
            payload["oracle"]["paper_parameters"] = {"scale": 2.0}
            payload["oracle"]["counterfactual_parameters"] = {
                "scale": counterfactual_scale
            }
            return parse_candidate_json(_candidate_json(payload))

        below_threshold = filter_candidate(scaled_candidate(2.08))
        self.assertIn(
            "counterfactual.not_distinguishable",
            {issue.code for issue in below_threshold.issues},
        )

        above_threshold = filter_candidate(scaled_candidate(2.12))
        self.assertTrue(above_threshold.eligible, above_threshold.issues)

    def test_filter_accepts_a_genuinely_univariate_claim(self):
        payload = _candidate_payload()
        payload["claim"] = "The response follows a one-control power law."
        payload["controls"] = payload["controls"][:1]
        payload["oracle"]["outputs"]["response"]["args"] = payload["oracle"][
            "outputs"
        ]["response"]["args"][:2]
        payload["diagnostic_conditions"] = [
            {"input_x": item["input_x"]} for item in payload["diagnostic_conditions"]
        ]
        payload["hidden_conditions"] = [
            {"input_x": item["input_x"]} for item in payload["hidden_conditions"]
        ]
        self.assertTrue(
            filter_candidate(parse_candidate_json(_candidate_json(payload))).eligible
        )

    def test_enumerated_control_is_filtered_rendered_and_enforced(self):
        payload = _candidate_payload()
        payload["controls"][0].update(
            {
                "minimum": None,
                "maximum": None,
                "allowed_values": [1.0, 2.0, 4.0, 6.0, 8.0, 9.0],
            }
        )
        candidate = parse_candidate_json(_candidate_json(payload))
        self.assertTrue(filter_candidate(candidate).eligible)
        spec = build_matched_spec(candidate)
        self.assertEqual(
            spec.controls[0].allowed_values,
            (1.0, 2.0, 4.0, 6.0, 8.0, 9.0),
        )
        case = make_matched_case(
            spec, "historical", BenchmarkTrack.IDENTIFICATION
        )
        response = case.world_model.run
        with self.assertRaisesRegex(ValueError, "not an allowed value"):
            response(
                ExperimentProposal(
                    intent="Probe an unsupported setting.",
                    apparatus=spec.apparatus_name,
                    controls={"input_x": 3.0, "input_y": 2.0},
                    readouts=("response",),
                    replicates=1,
                )
            )

        gap_payload = copy.deepcopy(payload)
        original = gap_payload["oracle"]["outputs"]["response"]
        gap_payload["oracle"]["outputs"]["response"] = {
            "op": "divide",
            "args": [
                original,
                {
                    "op": "subtract",
                    "args": [{"var": "input_x"}, 5.0],
                },
            ],
        }
        gap_candidate = parse_candidate_json(_candidate_json(gap_payload))
        self.assertTrue(filter_candidate(gap_candidate).eligible)

    def test_filter_requires_genuinely_held_out_unique_interior_conditions(self):
        payload = _candidate_payload()
        payload["hidden_conditions"][0] = copy.deepcopy(
            payload["diagnostic_conditions"][1]
        )
        result = filter_candidate(parse_candidate_json(_candidate_json(payload)))
        self.assertIn(
            "conditions.hidden_not_held_out", {issue.code for issue in result.issues}
        )

        payload = _candidate_payload()
        payload["hidden_conditions"][1] = copy.deepcopy(
            payload["hidden_conditions"][0]
        )
        result = filter_candidate(parse_candidate_json(_candidate_json(payload)))
        self.assertIn("conditions.duplicate", {issue.code for issue in result.issues})

        payload = _candidate_payload()
        payload["hidden_conditions"][0]["input_x"] = payload["controls"][0][
            "minimum"
        ]
        result = filter_candidate(parse_candidate_json(_candidate_json(payload)))
        self.assertIn(
            "conditions.hidden_not_interior", {issue.code for issue in result.issues}
        )

    def test_multiple_hidden_conditions_vary_every_control(self):
        payload = _candidate_payload()
        for condition in payload["hidden_conditions"]:
            condition["input_y"] = 2.0
        result = filter_candidate(parse_candidate_json(_candidate_json(payload)))
        self.assertIn(
            "conditions.hidden_not_spread", {issue.code for issue in result.issues}
        )

    def test_filter_requires_exactly_one_counterfactual_parameter_change(self):
        payload = _candidate_payload()
        payload["oracle"]["counterfactual_parameters"]["scale"] = 3.0
        result = filter_candidate(parse_candidate_json(_candidate_json(payload)))
        self.assertIn(
            "counterfactual.change_count", {issue.code for issue in result.issues}
        )

        payload = _candidate_payload()
        payload["oracle"]["counterfactual_parameters"] = copy.deepcopy(
            payload["oracle"]["paper_parameters"]
        )
        result = filter_candidate(parse_candidate_json(_candidate_json(payload)))
        self.assertIn(
            "counterfactual.change_count", {issue.code for issue in result.issues}
        )

    def test_filter_rejects_an_interior_singularity_in_the_public_domain(self):
        payload = _candidate_payload()
        original = payload["oracle"]["outputs"]["response"]
        payload["oracle"]["outputs"]["response"] = {
            "op": "divide",
            "args": [
                original,
                {
                    "op": "subtract",
                    "args": [{"var": "input_x"}, 5.0],
                },
            ],
        }
        result = filter_candidate(parse_candidate_json(_candidate_json(payload)))
        self.assertIn("oracle.domain_unsafe", {issue.code for issue in result.issues})

    def test_rendered_module_imports_and_both_tracks_accept_their_truth(self):
        candidate = parse_candidate_json(_candidate_json())
        source = render_candidate_module(candidate)
        compile(source, "generated_case.py", "exec")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "paper_response.py"
            path.write_text(source, encoding="utf-8")
            spec = importlib.util.spec_from_file_location("paper_response", path)
            module = importlib.util.module_from_spec(spec)
            assert spec.loader is not None
            spec.loader.exec_module(module)
            for world in ("historical", "counterfactual"):
                for track in (
                    BenchmarkTrack.IDENTIFICATION,
                    BenchmarkTrack.DISCOVERY,
                ):
                    case = module.make_paper_response_case(world, track)
                    result = case.evaluator.evaluate(
                        truth_submission(module.PAPER_RESPONSE_SPEC, world, track)
                    )
                    self.assertTrue(result.success)

    def test_temporal_world_ids_are_opaque_and_parity_balanced(self):
        even_spec = build_matched_spec(parse_candidate_json(_candidate_json()))
        odd_payload = _candidate_payload()
        odd_payload["source"]["arxiv_versioned_id"] = "2607.01235v2"
        odd_spec = build_matched_spec(
            parse_candidate_json(_candidate_json(odd_payload))
        )
        self.assertFalse(even_spec.swap_public_instance_ids)
        self.assertTrue(odd_spec.swap_public_instance_ids)
        for spec in (even_spec, odd_spec):
            ids = {
                world: make_matched_case(
                    spec, world, BenchmarkTrack.IDENTIFICATION
                ).definition.case_id
                for world in ("historical", "counterfactual")
            }
            self.assertEqual(len(set(ids.values())), 2)
            self.assertTrue(
                all(
                    "historical" not in value and "counterfactual" not in value
                    for value in ids.values()
                )
            )
        self.assertNotEqual(
            make_matched_case(
                even_spec, "historical", BenchmarkTrack.IDENTIFICATION
            ).definition.case_id,
            make_matched_case(
                odd_spec, "historical", BenchmarkTrack.IDENTIFICATION
            ).definition.case_id,
        )

    def test_fake_backend_only_proposes_then_deterministic_filter_decides(self):
        backend = _FakeBackend(
            json.dumps(
                {
                    "assessment": "One quantitative claim can be proposed.",
                    "candidates": [_candidate_payload()],
                }
            )
        )
        extracted = extract_paper_abstraction(
            backend,
            "\\documentclass{article}\n\\begin{document}x\\end{document}",
            source_citation="A. Author et al., Example Journal (2026)",
            journal_doi="10.0000/example",
            arxiv_versioned_id="2607.01234v2",
        )
        candidate = extracted.abstraction.candidates[0]
        self.assertEqual(candidate.family, "paper_response")
        self.assertEqual(len(backend.requests), 1)
        request = backend.requests[0]
        self.assertEqual(request.metadata["purpose"], "temporal_paper_abstraction")
        self.assertFalse(request.response_schema["additionalProperties"])
        self.assertTrue(filter_candidate(candidate).eligible)

    def test_metadata_prefilter_precedes_deterministic_ranking(self):
        papers = (
            SourcePaper(
                doi="10.1/a",
                title="A",
                venue="Nature",
                publication_date=date(2026, 6, 2),
                earliest_public_date=date(2026, 6, 1),
                article_type="journal-article",
                citation_count=4,
                latex_available=True,
            ),
            SourcePaper(
                doi="10.1/b",
                title="B",
                venue="Science",
                publication_date=date(2026, 6, 3),
                earliest_public_date=date(2026, 6, 3),
                article_type="journal-article",
                citation_count=9,
                latex_available=True,
            ),
            SourcePaper(
                doi="10.1/review",
                title="Review",
                venue="Nature",
                publication_date=date(2026, 6, 4),
                earliest_public_date=date(2026, 6, 4),
                article_type="review",
                citation_count=100,
                latex_available=True,
            ),
        )
        result = prefilter_papers(
            papers, start=date(2026, 6, 1), end=date(2026, 6, 30)
        )
        self.assertEqual([item.doi for item in rank_papers(result.accepted)], ["10.1/b", "10.1/a"])
        self.assertEqual(
            result.rejected["10.1/review"], ("paper.not_original_research",)
        )

    def test_candidate_round_trip_is_lossless(self):
        candidate = parse_candidate_json(_candidate_json())
        reparsed = parse_candidate_json(json.dumps(candidate_to_payload(candidate)))
        self.assertEqual(reparsed, candidate)

    def test_cli_request_uses_the_paper_abstraction_contract(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            tex = root / "paper.tex"
            tex.write_text(
                "\\documentclass{article}\n\\begin{document}x\\end{document}\n",
                encoding="utf-8",
            )
            request_stdout = io.StringIO()
            with contextlib.redirect_stdout(request_stdout):
                self.assertEqual(
                    temporal_cli_main(
                        [
                            "request",
                            str(tex),
                            "--source-citation",
                            "A. Author et al., Example Journal (2026)",
                            "--journal-doi",
                            "10.0000/example",
                            "--arxiv-versioned-id",
                            "2607.01234v2",
                        ]
                    ),
                    0,
                )
            request_payload = json.loads(request_stdout.getvalue())
            self.assertEqual(
                request_payload["metadata"]["purpose"],
                "temporal_paper_abstraction",
            )


if __name__ == "__main__":
    unittest.main()
