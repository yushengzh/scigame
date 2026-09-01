import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from experiments.run_temporal_abstraction import run
from role_benchmark import GenerationResponse


class _FakeBackend:
    def generate(self, request):
        return GenerationResponse(
            text=json.dumps(
                {
                    "assessment": "No claim satisfies the case contract.",
                    "candidates": [],
                }
            ),
            provider="fake",
            model="fake-model",
            finish_reason="stop",
        )


class TemporalWarmupRunnerTests(unittest.TestCase):
    def test_records_one_no_retry_abstraction_without_a_credential(self):
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
                endpoint="https://api.example.invalid/chat/completions",
                model="fake-model",
                timeout_s=10.0,
                max_output_tokens=8192,
                api_key=None,
                api_key_stdin=False,
                prompt_api_key=False,
                api_key_env="UNUSED_API_KEY",
            )
            with contextlib.redirect_stdout(io.StringIO()):
                status = run(args, backend=_FakeBackend())

            self.assertEqual(status, 0)
            self.assertTrue((output / "request.json").is_file())
            self.assertTrue((output / "response.json").is_file())
            self.assertEqual(
                json.loads((output / "abstraction.json").read_text())["candidates"],
                [],
            )
            report = json.loads((output / "result.json").read_text())
            self.assertEqual(report["status"], "diagnostic_complete")
            self.assertEqual(report["candidate_count"], 0)
            self.assertFalse(report["case_rendered"])
            self.assertFalse((output / "cases").exists())


if __name__ == "__main__":
    unittest.main()
