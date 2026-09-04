from __future__ import annotations

import contextlib
import io
import tempfile
import unittest
from pathlib import Path

from experiments.run_temporal_conversion import (
    DEFAULT_REGISTRATION,
    _RecordingBackend,
    _metrics,
    _parser,
    _registered_live_snapshot,
    _registration_contract,
    run,
)
from role_benchmark import (
    GenerationConfig,
    GenerationRequest,
    GenerationResponse,
    Message,
)


class _NoCallBackend:
    def __init__(self):
        self.call_count = 0

    def generate(self, request):
        self.call_count += 1
        raise AssertionError("provider must not be called")


class _ResponseBackend:
    def __init__(self, response):
        self.response = response
        self.call_count = 0

    def generate(self, request):
        self.call_count += 1
        return self.response


class _InterruptedBackend:
    def __init__(self):
        self.call_count = 0

    def generate(self, request):
        self.call_count += 1
        raise RuntimeError("provider connection interrupted")


def _request(label="fixed"):
    return GenerationRequest(
        messages=(Message("user", label),),
        response_schema={"type": "object"},
        config=GenerationConfig(max_output_tokens=32, temperature=0.0, top_p=1.0),
        metadata={"purpose": "test"},
    )


class TemporalConversionRunnerTests(unittest.TestCase):
    def test_live_provider_model_is_the_registered_historical_snapshot(self):
        registration = {
            "authoring_model": {
                "model_id": "mutable-model-alias",
                "checkpoint_or_snapshot_id": "snapshot-123",
            },
            "historical_baseline": {
                "comparison_status": "controlled",
                "authoring_model_checkpoint_or_snapshot_id": "snapshot-123",
            },
        }
        self.assertEqual(
            _registered_live_snapshot(registration, "snapshot-123"),
            "snapshot-123",
        )
        with self.assertRaisesRegex(ValueError, "exactly match"):
            _registered_live_snapshot(registration, "mutable-model-alias")

    def test_resume_counts_request_without_response_and_uses_next_attempt(self):
        response = GenerationResponse(
            text='{"relations":[]}',
            provider="test-provider",
            model="immutable-snapshot",
            finish_reason="stop",
            response_id="response-2",
        )
        with tempfile.TemporaryDirectory() as directory:
            stage = Path(directory)
            interrupted = _InterruptedBackend()
            first = _RecordingBackend(
                interrupted,
                stage,
                max_total_attempts=2,
            )
            with self.assertRaisesRegex(RuntimeError, "connection interrupted"):
                first.generate(_request())
            self.assertEqual(first.attempt_count, 1)
            self.assertTrue((stage / "attempt_01" / "request.json").is_file())
            self.assertFalse((stage / "attempt_01" / "response.json").exists())

            provider = _ResponseBackend(response)
            resumed = _RecordingBackend(
                provider,
                stage,
                max_total_attempts=2,
            )
            self.assertEqual(resumed.generate(_request()), response)
            self.assertEqual(provider.call_count, 1)
            self.assertEqual(resumed.attempt_count, 2)
            self.assertTrue((stage / "attempt_02" / "response.json").is_file())

            no_call = _NoCallBackend()
            replayed = _RecordingBackend(
                no_call,
                stage,
                max_total_attempts=2,
            )
            self.assertEqual(replayed.generate(_request()), response)
            self.assertEqual(replayed.attempt_count, 2)
            self.assertEqual(no_call.call_count, 0)

    def test_resume_does_not_retry_unknown_response_after_budget_exhaustion(self):
        with tempfile.TemporaryDirectory() as directory:
            stage = Path(directory)
            first = _RecordingBackend(
                _InterruptedBackend(),
                stage,
                max_total_attempts=1,
            )
            with self.assertRaises(RuntimeError):
                first.generate(_request())

            no_call = _NoCallBackend()
            resumed = _RecordingBackend(
                no_call,
                stage,
                max_total_attempts=1,
            )
            with self.assertRaisesRegex(
                RuntimeError,
                "missing infrastructure data",
            ):
                resumed.generate(_request())
            self.assertEqual(resumed.attempt_count, 1)
            self.assertEqual(no_call.call_count, 0)

    def test_resume_rejects_a_different_request_before_provider_call(self):
        response = GenerationResponse(
            text='{"relations":[]}',
            provider="test-provider",
            model="immutable-snapshot",
        )
        with tempfile.TemporaryDirectory() as directory:
            stage = Path(directory)
            original = _RecordingBackend(
                _ResponseBackend(response),
                stage,
                max_total_attempts=2,
            )
            original.generate(_request("original"))

            no_call = _NoCallBackend()
            resumed = _RecordingBackend(
                no_call,
                stage,
                max_total_attempts=2,
            )
            with self.assertRaisesRegex(RuntimeError, "differs"):
                resumed.generate(_request("changed"))
            self.assertEqual(no_call.call_count, 0)

    def test_real_registration_freezes_the_37_paper_budget(self):
        registration, manifest, sources = _registration_contract(
            DEFAULT_REGISTRATION
        )
        self.assertEqual(registration["experiment_id"], "EXP-TEMPORAL-AUTHORING-001")
        self.assertEqual(manifest["cohort_size"], 37)
        self.assertEqual(len(sources), 37)
        self.assertEqual(
            sum(item["max_total_attempts"] for item in sources),
            114,
        )

    def test_dry_run_validates_every_source_without_a_provider_call(self):
        backend = _NoCallBackend()
        with tempfile.TemporaryDirectory() as directory:
            args = _parser().parse_args(
                [
                    directory,
                    "--registration",
                    str(DEFAULT_REGISTRATION),
                    "--authoring-snapshot-id",
                    "unknown",
                    "--dry-run",
                ]
            )
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(run(args, backend=backend), 0)
            self.assertTrue((Path(directory) / "plan.json").is_file())
        self.assertEqual(backend.call_count, 0)

    def test_blocked_registration_stops_before_a_provider_call(self):
        backend = _NoCallBackend()
        with tempfile.TemporaryDirectory() as directory:
            args = _parser().parse_args(
                [
                    directory,
                    "--registration",
                    str(DEFAULT_REGISTRATION),
                    "--authoring-snapshot-id",
                    "unknown",
                ]
            )
            with self.assertRaisesRegex(ValueError, "blocked by the experiment"):
                run(args, backend=backend)
        self.assertEqual(backend.call_count, 0)

    def test_empty_abstentions_are_schema_valid_but_not_structural_successes(self):
        results = [
            {
                "paper_id": "paper_%02d" % index,
                "status": "no_relation_extracted",
                "schema_valid": True,
                "structural_valid": False,
                "first_attempt_structural_valid": False,
                "nonempty_relation": False,
                "source_review_completed": False,
                "attempt_count": 1,
            }
            for index in range(1, 38)
        ]
        metrics = _metrics(results, actual_calls=37)
        self.assertEqual(
            metrics["provider_response_schema_validity"]["count"],
            37,
        )
        self.assertEqual(
            metrics["first_attempt_structural_validity"]["count"],
            0,
        )
        self.assertEqual(
            metrics["post_repair_structural_validity"]["count"],
            0,
        )
        self.assertEqual(metrics["final_acceptance"]["count"], 0)


if __name__ == "__main__":
    unittest.main()
