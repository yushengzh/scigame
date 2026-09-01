from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from experiments.run_temporal_science_card import (
    DEFAULT_MAX_OUTPUT_TOKENS,
    DEFAULT_MODEL,
    run,
)
from role_benchmark import GenerationResponse


_CITATION = "A. Author et al., A paper, Journal (2025)"
_DOI = "10.0000/example"
_ARXIV_ID = "2501.01234v1"


def _science_card_payload(*, citation: str = _CITATION):
    return {
        "assessment": "The source has no authorable quantitative response.",
        "case_authoring_ready": False,
        "source": {
            "citation": citation,
            "journal_doi": _DOI,
            "arxiv_versioned_id": _ARXIV_ID,
        },
        "paper_scope": "A minimal source used to test stage-one extraction.",
        "mechanisms": [],
        "fixed_conditions": [],
        "controls": [],
        "readouts": [],
        "claims": [],
        "source_ambiguities": [],
    }


class _FakeBackend:
    def __init__(self, payload):
        self.payload = payload
        self.requests = []

    def generate(self, request):
        self.requests.append(request)
        if len(self.requests) != 1:
            raise AssertionError("the science-card runner retried the model call")
        if request.metadata != {
            "purpose": "temporal_science_card",
            "source_format": "latex",
        }:
            raise AssertionError("unexpected request metadata")
        if request.config.max_output_tokens != DEFAULT_MAX_OUTPUT_TOKENS:
            raise AssertionError("unexpected output-token limit")
        return GenerationResponse(
            text=json.dumps(self.payload),
            provider="fake",
            model="fake-science-card-extractor",
            finish_reason="stop",
        )


class _QueuedBackend:
    def __init__(self, payloads):
        self.payloads = list(payloads)
        self.requests = []

    def generate(self, request):
        self.requests.append(request)
        if not self.payloads:
            raise AssertionError("science-card runner exceeded queued calls")
        return GenerationResponse(
            text=json.dumps(self.payloads.pop(0)),
            provider="fake",
            model="fake-science-card-extractor",
            finish_reason="stop",
        )


def _args(tex: Path, output: Path, *, secret: str):
    return SimpleNamespace(
        tex=str(tex),
        output_directory=str(output),
        source_citation=_CITATION,
        journal_doi=_DOI,
        arxiv_versioned_id=_ARXIV_ID,
        endpoint="https://api.example.invalid/chat/completions",
        model="fake-science-card-extractor",
        timeout_s=10.0,
        max_output_tokens=DEFAULT_MAX_OUTPUT_TOKENS,
        api_key=secret,
        api_key_stdin=False,
        prompt_api_key=False,
        api_key_env="UNUSED_API_KEY",
    )


class TemporalScienceCardRunnerTests(unittest.TestCase):
    def test_records_one_successful_science_card_call(self):
        self.assertEqual(DEFAULT_MODEL, "deepseek-v4-flash")
        self.assertEqual(DEFAULT_MAX_OUTPUT_TOKENS, 32768)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            tex = root / "paper.tex"
            tex.write_text(
                "\\documentclass{article}\n\\begin{document}Source.\\end{document}\n",
                encoding="utf-8",
            )
            output = root / "output"
            secret = "runtime-only-test-secret"
            backend = _FakeBackend(_science_card_payload())
            with contextlib.redirect_stdout(io.StringIO()):
                status = run(_args(tex, output, secret=secret), backend=backend)

            self.assertEqual(status, 0)
            self.assertEqual(len(backend.requests), 1)
            for name in (
                "normalized_source.tex",
                "request.json",
                "response.json",
                "science_card.json",
                "result.json",
            ):
                self.assertTrue((output / name).is_file(), name)
            self.assertFalse((output / "failure.json").exists())

            card = json.loads((output / "science_card.json").read_text())
            self.assertEqual(card, _science_card_payload())
            report = json.loads((output / "result.json").read_text())
            self.assertEqual(report["status"], "complete")
            self.assertEqual(report["attempt_count"], 1)
            self.assertFalse(report["case_authoring_ready"])
            self.assertEqual(report["claim_count"], 0)
            self.assertEqual(report["mechanism_count"], 0)

            persisted = "\n".join(
                path.read_text(encoding="utf-8")
                for path in output.rglob("*")
                if path.is_file()
            )
            self.assertNotIn(secret, persisted)

    def test_records_a_bounded_schema_repair_separately(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            tex = root / "paper.tex"
            tex.write_text("\\documentclass{article}\n", encoding="utf-8")
            output = root / "output"
            backend = _QueuedBackend(({"invalid": "card"}, _science_card_payload()))

            with contextlib.redirect_stdout(io.StringIO()):
                status = run(_args(tex, output, secret="unused"), backend=backend)

            self.assertEqual(status, 0)
            self.assertEqual(len(backend.requests), 2)
            self.assertTrue((output / "request.json").is_file())
            self.assertTrue((output / "response.json").is_file())
            self.assertTrue((output / "repair_01" / "request.json").is_file())
            self.assertTrue((output / "repair_01" / "response.json").is_file())
            report = json.loads((output / "result.json").read_text())
            self.assertEqual(report["attempt_count"], 2)

    def test_science_card_validation_failure_is_recorded(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            tex = root / "paper.tex"
            tex.write_text("\\documentclass{article}\n", encoding="utf-8")
            output = root / "output"
            backend = _FakeBackend(
                _science_card_payload(citation="Different source identity")
            )
            with contextlib.redirect_stdout(io.StringIO()):
                status = run(_args(tex, output, secret="unused"), backend=backend)

            self.assertEqual(status, 2)
            self.assertEqual(len(backend.requests), 1)
            failure = json.loads((output / "failure.json").read_text())
            self.assertEqual(failure["status"], "failed")
            self.assertEqual(failure["stage"], "science_card")
            self.assertIn("source_identity", failure["error"])
            self.assertFalse((output / "science_card.json").exists())
            self.assertFalse((output / "result.json").exists())


if __name__ == "__main__":
    unittest.main()
