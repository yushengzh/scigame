from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from experiments.run_temporal_case_draft import DEFAULT_MODEL, run
from role_benchmark import GenerationResponse
from role_benchmark.llm import generation_response_to_payload


def _not_ready_science_card():
    return {
        "assessment": "The source has no matched pair of reported regimes.",
        "case_authoring_ready": False,
        "source": {
            "citation": "A. Author et al., A paper, Journal (2025)",
            "journal_doi": "10.0000/example",
            "arxiv_versioned_id": "2501.01234v1",
        },
        "paper_scope": "A minimal source without an authorable regime pair.",
        "mechanisms": [],
        "fixed_conditions": [],
        "controls": [],
        "readouts": [],
        "claims": [],
        "source_ambiguities": [],
    }


class _NotAuthorableBackend:
    def __init__(self):
        self.requests = []

    def generate(self, request):
        self.requests.append(request)
        if len(self.requests) != 1:
            raise AssertionError("the stage-two runner retried the model call")
        if request.metadata != {
            "purpose": "temporal_case_authoring",
            "source_mode": "science_card_only",
        }:
            raise AssertionError("unexpected request metadata")
        return GenerationResponse(
            text=json.dumps(
                {
                    "assessment": (
                        "No source-reported alternate regime is available."
                    ),
                    "status": "not_authorable",
                    "drafts": [],
                }
            ),
            provider="fake",
            model="fake-case-author",
            finish_reason="stop",
        )


class TemporalCaseDraftRunnerTests(unittest.TestCase):
    def test_eligible_standalone_draft_stops_at_family_review_request(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            science_card = root / "science_card.json"
            science_card.write_text(
                json.dumps(_not_ready_science_card()), encoding="utf-8"
            )
            output = root / "output"
            candidate = SimpleNamespace(family="draft_only_family")
            batch = SimpleNamespace(
                assessment="One machine-eligible draft.",
                status="authored",
                drafts=(
                    SimpleNamespace(
                        candidate=candidate,
                        information_boundary=SimpleNamespace(),
                    ),
                ),
            )
            generated = GenerationResponse(
                text="{}", provider="fake", model="fake-case-author"
            )
            args = SimpleNamespace(
                science_card=str(science_card),
                output_directory=str(output),
                paper_id="example_paper",
                response_envelope=False,
                endpoint="https://api.example.invalid/chat/completions",
                model="fake-case-author",
                timeout_s=10.0,
                max_output_tokens=8192,
                api_key=None,
                api_key_stdin=False,
                prompt_api_key=False,
                api_key_env="UNUSED_API_KEY",
            )

            with (
                patch(
                    "experiments.run_temporal_case_draft.author_case_draft",
                    return_value=SimpleNamespace(batch=batch, response=generated),
                ),
                patch(
                    "experiments.run_temporal_case_draft.case_draft_batch_to_payload",
                    return_value={
                        "assessment": "draft",
                        "status": "authored",
                        "drafts": [],
                    },
                ),
                patch(
                    "experiments.run_temporal_case_draft.filter_candidate",
                    return_value=SimpleNamespace(eligible=True, issues=()),
                ),
                patch(
                    "experiments.run_temporal_case_draft.family_review_request_payload",
                    return_value={
                        "paper_id": "example_paper",
                        "family": "draft_only_family",
                    },
                ),
                contextlib.redirect_stdout(io.StringIO()),
            ):
                status = run(args, backend=_NotAuthorableBackend())

            self.assertEqual(status, 3)
            self.assertTrue((output / "family_review_request.json").is_file())
            self.assertEqual(
                json.loads(
                    (output / "prose_normalizations.json").read_text()
                ),
                {"normalizations": []},
            )
            self.assertEqual(
                json.loads(
                    (output / "relationship_direction_bindings.json").read_text()
                ),
                {"bindings": []},
            )
            self.assertEqual(
                json.loads(
                    (output / "condition_partition_bindings.json").read_text()
                ),
                {"bindings": []},
            )
            self.assertFalse((output / "cases").exists())
            report = json.loads((output / "result.json").read_text())
            self.assertEqual(report["status"], "awaiting_family_review")
            self.assertFalse(report["case_rendered"])

    def test_records_one_not_authorable_call_without_tex_or_credential(self):
        self.assertEqual(DEFAULT_MODEL, "deepseek-v4-flash")
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            science_card = root / "science_card.json"
            science_card.write_text(
                json.dumps(_not_ready_science_card()), encoding="utf-8"
            )
            output = root / "output"
            secret = "runtime-only-test-secret"
            args = SimpleNamespace(
                science_card=str(science_card),
                output_directory=str(output),
                paper_id="example_paper",
                response_envelope=False,
                endpoint="https://api.example.invalid/chat/completions",
                model="fake-case-author",
                timeout_s=10.0,
                max_output_tokens=8192,
                api_key=secret,
                api_key_stdin=False,
                prompt_api_key=False,
                api_key_env="UNUSED_API_KEY",
            )
            backend = _NotAuthorableBackend()
            with contextlib.redirect_stdout(io.StringIO()):
                status = run(args, backend=backend)

            self.assertEqual(status, 0)
            self.assertEqual(len(backend.requests), 1)
            self.assertTrue((output / "request.json").is_file())
            self.assertTrue((output / "response.json").is_file())
            self.assertTrue((output / "science_card.json").is_file())
            self.assertTrue((output / "draft.json").is_file())
            self.assertTrue((output / "filter.json").is_file())
            self.assertTrue((output / "result.json").is_file())
            self.assertTrue((output / "config.json").is_file())
            self.assertFalse((output / "cases").exists())
            self.assertFalse((output / "normalized_source.tex").exists())

            request = json.loads((output / "request.json").read_text())
            self.assertEqual(
                request["metadata"]["purpose"], "temporal_case_authoring"
            )
            self.assertEqual(
                request["metadata"]["source_mode"], "science_card_only"
            )
            self.assertNotIn("LaTeX source follows", request["messages"][1]["content"])

            draft = json.loads((output / "draft.json").read_text())
            self.assertEqual(draft["status"], "not_authorable")
            self.assertEqual(draft["drafts"], [])
            filtered = json.loads((output / "filter.json").read_text())
            self.assertEqual(filtered["status"], "not_authorable")
            self.assertEqual(filtered["candidate_count"], 0)
            report = json.loads((output / "result.json").read_text())
            self.assertEqual(report["status"], "not_authorable")
            self.assertEqual(report["draft_count"], 0)
            self.assertEqual(report["eligible_count"], 0)

            persisted = "\n".join(
                path.read_text(encoding="utf-8")
                for path in output.rglob("*")
                if path.is_file()
            )
            self.assertNotIn(secret, persisted)

    def test_resumes_from_a_recorded_science_card_response_envelope(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            card_payload = _not_ready_science_card()
            envelope = generation_response_to_payload(
                GenerationResponse(
                    text=json.dumps(card_payload),
                    provider="fake-stage-one",
                    model="fake-science-card-extractor",
                    finish_reason="stop",
                )
            )
            response_path = root / "stage_one_response.json"
            response_path.write_text(json.dumps(envelope), encoding="utf-8")
            output = root / "output"
            args = SimpleNamespace(
                science_card=str(response_path),
                output_directory=str(output),
                paper_id="example_paper",
                response_envelope=True,
                endpoint="https://api.example.invalid/chat/completions",
                model="fake-case-author",
                timeout_s=10.0,
                max_output_tokens=8192,
                api_key=None,
                api_key_stdin=False,
                prompt_api_key=False,
                api_key_env="UNUSED_API_KEY",
            )
            backend = _NotAuthorableBackend()
            with contextlib.redirect_stdout(io.StringIO()):
                status = run(args, backend=backend)

            self.assertEqual(status, 0)
            self.assertEqual(len(backend.requests), 1)
            self.assertEqual(
                json.loads((output / "science_card.json").read_text()),
                card_payload,
            )
            self.assertEqual(
                json.loads((output / "result.json").read_text())["status"],
                "not_authorable",
            )


if __name__ == "__main__":
    unittest.main()
