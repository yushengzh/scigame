import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from experiments.run_temporal_authoring import (
    _CaseDraftRecordingBackend,
    _ScienceCardRecordingBackend,
    run,
)
from role_benchmark import (
    GenerationConfig,
    GenerationRequest,
    GenerationResponse,
    Message,
)


class _SequentialBackend:
    def __init__(self):
        self.requests = []

    def generate(self, request):
        self.requests.append(request)
        if len(self.requests) == 1:
            payload = {
                "assessment": "The source does not support a matched regime pair.",
                "case_authoring_ready": False,
                "source": {
                    "citation": "A. Author et al., A paper, Journal (2025)",
                    "journal_doi": "10.0000/example",
                    "arxiv_versioned_id": "2501.01234v1",
                },
                "paper_scope": "A minimal source used to test the runner.",
                "mechanisms": [],
                "fixed_conditions": [],
                "controls": [],
                "readouts": [],
                "claims": [],
                "source_ambiguities": [],
            }
            purpose = "temporal_science_card"
        elif len(self.requests) == 2:
            payload = {
                "assessment": "No source-reported alternate regime is available.",
                "status": "not_authorable",
                "drafts": [],
            }
            purpose = "temporal_case_authoring"
        else:
            raise AssertionError("the runner retried a generation stage")
        self._assert_purpose(request, purpose)
        return GenerationResponse(
            text=json.dumps(payload),
            provider="fake",
            model="fake-model",
            finish_reason="stop",
        )

    def _assert_purpose(self, request, purpose):
        if request.metadata["purpose"] != purpose:
            raise AssertionError("unexpected generation stage")


class TemporalAuthoringRunnerTests(unittest.TestCase):
    def test_science_card_recorder_preserves_four_numbered_attempts(self):
        class Backend:
            def generate(self, request):
                return GenerationResponse(
                    text='{"ok":true}',
                    provider="fake",
                    model="fake-model",
                    finish_reason="stop",
                )

        request = GenerationRequest(
            messages=(Message("user", "test"),),
            response_schema={"type": "object"},
            config=GenerationConfig(),
            metadata={"purpose": "temporal_science_card"},
        )
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            recorder = _ScienceCardRecordingBackend(Backend(), directory)
            for _ in range(4):
                recorder.generate(request)
            with self.assertRaises(RuntimeError):
                recorder.generate(request)

            self.assertTrue((directory / "request.json").is_file())
            self.assertTrue((directory / "response.json").is_file())
            for repair_index in range(1, 4):
                repair = directory / ("repair_%02d" % repair_index)
                self.assertTrue((repair / "request.json").is_file())
                self.assertTrue((repair / "response.json").is_file())
            self.assertEqual(recorder.attempt_count, 4)

    def test_case_draft_recorder_preserves_four_numbered_attempts(self):
        class Backend:
            def generate(self, request):
                return GenerationResponse(
                    text='{"ok":true}',
                    provider="fake",
                    model="fake-model",
                    finish_reason="stop",
                )

        request = GenerationRequest(
            messages=(Message("user", "test"),),
            response_schema={"type": "object"},
            config=GenerationConfig(),
            metadata={"purpose": "temporal_case_authoring"},
        )
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            recorder = _CaseDraftRecordingBackend(Backend(), directory)
            for _ in range(4):
                recorder.generate(request)
            with self.assertRaises(RuntimeError):
                recorder.generate(request)

            self.assertTrue((directory / "request.json").is_file())
            self.assertTrue((directory / "response.json").is_file())
            for repair_index in range(1, 4):
                repair = directory / ("repair_%02d" % repair_index)
                self.assertTrue((repair / "request.json").is_file())
                self.assertTrue((repair / "response.json").is_file())
            self.assertEqual(recorder.attempt_count, 4)

    def test_records_two_no_retry_stages_without_a_credential(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            tex = root / "paper.tex"
            tex.write_text("\\documentclass{article}\n", encoding="utf-8")
            output = root / "output"
            args = SimpleNamespace(
                tex=str(tex),
                output_directory=str(output),
                source_citation="A. Author et al., A paper, Journal (2025)",
                journal_doi="10.0000/example",
                arxiv_versioned_id="2501.01234v1",
                paper_id="example_paper",
                endpoint="https://api.example.invalid/chat/completions",
                model="fake-model",
                timeout_s=10.0,
                max_output_tokens=8192,
                api_key=None,
                api_key_stdin=False,
                prompt_api_key=False,
                api_key_env="UNUSED_API_KEY",
            )
            backend = _SequentialBackend()
            with contextlib.redirect_stdout(io.StringIO()):
                status = run(args, backend=backend)

            self.assertEqual(status, 0)
            self.assertEqual(len(backend.requests), 2)
            self.assertEqual(
                backend.requests[0].metadata["purpose"], "temporal_science_card"
            )
            self.assertEqual(
                backend.requests[1].metadata["purpose"], "temporal_case_authoring"
            )
            self.assertTrue((output / "normalized_source.tex").is_file())
            self.assertTrue((output / "science_card" / "request.json").is_file())
            self.assertTrue((output / "science_card" / "response.json").is_file())
            self.assertTrue((output / "case_draft" / "request.json").is_file())
            self.assertTrue((output / "case_draft" / "response.json").is_file())
            self.assertTrue((output / "science_card.json").is_file())
            self.assertTrue((output / "draft.json").is_file())
            self.assertTrue((output / "filter.json").is_file())
            self.assertTrue((output / "config.json").is_file())
            self.assertFalse((output / "cases").exists())
            report = json.loads((output / "result.json").read_text())
            self.assertEqual(report["status"], "not_authorable")
            self.assertEqual(report["draft_count"], 0)
            self.assertEqual(report["eligible_count"], 0)
            self.assertFalse(report["case_rendered"])


if __name__ == "__main__":
    unittest.main()
