from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from role_benchmark import (
    EVALUATOR_SCORE_AXES,
    DISCOVERY_SCORE_AXES,
    GenerationConfig,
    GenerationResponse,
    JSONLRunLog,
    LLMEvaluatorOutputError,
    LoadedRunLog,
    PostHocLLMEvaluator,
    TokenUsage,
    evaluator_transcript_projection,
    llm_evaluation_from_json,
    load_run_log,
)
from role_benchmark.wire import WireDecodeError


def _events():
    payloads = (
        (
            "run.started",
            {"case": {"case_id": "public.case"}, "policy": {"max_actions": 2}},
        ),
        (
            "model.completed",
            {
                "status": "ok",
                "response": {"text": "raw player output", "model": "player-model"},
            },
        ),
        (
            "action.parse_failed",
            {"wire_error": {"code": "invalid_json"}},
        ),
        (
            "model.completed",
            {
                "status": "ok",
                "response": {"text": "raw repaired output", "model": "player-model"},
            },
        ),
        (
            "action.decoded",
            {"action_index": 1, "action": {"kind": "experiment", "portfolio": {
                "hypotheses": [{"statement": "The response is linear in x within the tested range."}],
            }}},
        ),
        (
            "protocol.transition",
            {
                "action_index": 1,
                "outcome_kind": "experiment_evidence",
                "outcome": {"oracle_response": {"evidence": [{"value": 2.0}]}},
            },
        ),
        (
            "episode.terminal",
            {
                "evaluation": {
                    "success": False,
                    "scores": {"predictive_model_pass": 0.0},
                }
            },
        ),
        ("run.ended", {"status": "evaluated"}),
    )
    return tuple(
        {
            "sequence": index,
            "event_type": event_type,
            "payload": payload,
        }
        for index, (event_type, payload) in enumerate(payloads)
    )


def _log():
    return LoadedRunLog(run_id="run-1", events=_events(), complete=True)


def _valid_result(**overrides):
    result = {
        "scores": {axis: 0.5 for axis in EVALUATOR_SCORE_AXES},
        "findings": [
            {
                "code": "evidence_not_used",
                "stage": "evidence_interpretation",
                "action_index": 1,
                "message": "The conclusion did not follow the returned value.",
                "event_sequences": [5],
            }
        ],
        "summary": "The experiment produced usable evidence, but it was not used.",
    }
    result.update(overrides)
    return result


def _reference():
    return {"case_id": "public.case", "understanding_criteria": [
        {"id": "relation", "question": "Does the claim recover the scientific relation?"},
        {"id": "comparison", "question": "Are its variable dependencies understood?"},
        {"id": "scope", "question": "Is its scope supported?"},
    ]}


def _discovery_result():
    return {"understanding": {"items": [
        {"criterion_id": row["id"], "before_score": None, "after_score": 0.5,
         "before_claim": None, "after_claim": "The response is linear in x within the tested range.",
         "rationale": "The relation and scope are stated but incompletely supported."}
        for row in _reference()["understanding_criteria"]]},
        "findings": [], "summary": "Only final expressed understanding is available."}


class _Backend:
    def __init__(self, text):
        self.text = text
        self.request = None

    def generate(self, request):
        self.request = request
        return GenerationResponse(
            text=self.text,
            provider="test",
            model="judge-model",
            usage=TokenUsage(input_tokens=20, output_tokens=10),
        )


class LLMEvaluatorTests(unittest.TestCase):
    def test_historical_projection_preserves_its_original_observable_record(self):
        projection = evaluator_transcript_projection(_log())
        serialized = json.dumps(projection)
        self.assertIn("raw player output", serialized)
        self.assertIn("raw repaired output", serialized)
        self.assertIn('"value": 2.0', serialized)
        self.assertNotIn("model.requested", serialized)
        self.assertEqual(
            [item["sequence"] for item in projection["observable_transcript"]],
            list(range(8)),
        )

    def test_projection_accepts_zero_based_events_written_by_jsonl_run_log(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "sealed.jsonl"
            with JSONLRunLog(str(path), run_id="run-zero") as writer:
                writer.append("run.started", {"case": {"case_id": "public.case"}})
                writer.append("run.ended", {"status": "evaluated"})
            projection = evaluator_transcript_projection(load_run_log(str(path)))
        self.assertEqual(
            [item["sequence"] for item in projection["observable_transcript"]],
            [0, 1],
        )

    def test_post_hoc_evaluator_returns_separate_strict_axes(self):
        backend = _Backend(json.dumps(_discovery_result()))
        evaluator = PostHocLLMEvaluator(
            backend,
            config=GenerationConfig(max_output_tokens=512),
        )
        run = evaluator.evaluate(_log(), reference=_reference())
        self.assertEqual(set(run.evaluation.scores), set(DISCOVERY_SCORE_AXES))
        self.assertEqual(run.evaluation.scores["understanding_after"], 0.5)
        self.assertIsNone(run.evaluation.scores["understanding_gain"])
        self.assertEqual(run.evaluation.details["understanding"]["status"], "final_only")
        self.assertNotIn("active_pass", run.evaluation.scores)
        self.assertNotIn("predictive_model_pass", run.evaluation.scores)
        self.assertEqual(backend.request.metadata["purpose"], "post_hoc_transcript_evaluation")

    def test_decoder_rejects_extra_fields_nonfinite_and_out_of_range(self):
        extra = _valid_result(success=True)
        with self.assertRaises(WireDecodeError):
            llm_evaluation_from_json(json.dumps(extra))

        nonfinite = _valid_result()
        nonfinite["scores"]["evidence_use"] = float("nan")
        with self.assertRaises(WireDecodeError):
            llm_evaluation_from_json(json.dumps(nonfinite))

        out_of_range = _valid_result()
        out_of_range["scores"]["evidence_use"] = 1.1
        with self.assertRaises(WireDecodeError):
            llm_evaluation_from_json(json.dumps(out_of_range))

    def test_unknown_event_reference_is_rejected(self):
        result = _discovery_result()
        result["findings"] = [{"code": "F4", "rationale": "A claimed relation is unsupported.", "event_sequences": [999]}]
        backend = _Backend(json.dumps(result))
        evaluator = PostHocLLMEvaluator(backend)
        with self.assertRaises(LLMEvaluatorOutputError) as raised:
            evaluator.evaluate(_log(), reference=_reference())
        self.assertIs(raised.exception.request, backend.request)
        self.assertEqual(raised.exception.response.text, json.dumps(result))

    def test_invalid_evaluator_json_retains_request_and_raw_response(self):
        backend = _Backend("not-json")
        evaluator = PostHocLLMEvaluator(backend)
        with self.assertRaises(LLMEvaluatorOutputError) as raised:
            evaluator.evaluate(_log(), reference=_reference())
        self.assertIs(raised.exception.request, backend.request)
        self.assertEqual(raised.exception.response.text, "not-json")


if __name__ == "__main__":
    unittest.main()
