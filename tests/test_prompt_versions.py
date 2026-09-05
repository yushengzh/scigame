from __future__ import annotations

import json
import unittest

from role_benchmark import Episode
from role_benchmark.cases import make_pendulum_case
from role_benchmark.llm import (
    AdapterOutputError,
    DEFAULT_PLAYER_PROMPT_VERSION,
    GenerationConfig,
    GenerationResponse,
    LLMPlayerBackend,
    PLAYER_PROMPT_VERSION_V1,
    PLAYER_PROMPT_VERSION_V2_JSON_HARDENED,
    PLAYER_PROMPT_VERSION_V3_CASE_BOUND_JSON,
    PLAYER_REPAIR_PROMPT_VERSION_V2_JSON_HARDENED,
    PLAYER_REPAIR_PROMPT_VERSION_V3_CASE_BOUND_JSON,
    build_generation_request,
    generation_request_to_payload,
)
from role_benchmark.llm_evaluator import (
    DEFAULT_EVALUATOR_PROMPT_VERSION,
    EVALUATOR_SCORE_AXES,
    EVALUATOR_PROMPT_VERSION_V1,
    EVALUATOR_PROMPT_VERSION_V2_JSON_HARDENED,
    PostHocLLMEvaluator,
    build_evaluator_generation_request,
)
from role_benchmark.llm_oracle import (
    DEFAULT_ORACLE_PROMPT_VERSION,
    LLMOracle,
    ORACLE_PROMPT_VERSION_V1,
    ORACLE_PROMPT_VERSION_V2_JSON_HARDENED,
    build_oracle_generation_request,
)
from role_benchmark.protocols import CaseOracle
from role_benchmark.runlog import LoadedRunLog
from role_benchmark.wire import WireDecodeError

from test_wire import experiment_action


_PLAYER_V1_SYSTEM = """You are the Player in an interactive scientific modelling episode.
Use only the public episode view and Oracle responses. Choose exactly one next action.
Return only one JSON object matching the supplied action schema: no Markdown,
commentary, or extra keys. Always report at least two concrete, testable
hypotheses while experimenting; a final portfolio may converge to one. Never
use OTHER or a residual catch-all. Portfolio confidences must sum to 1.
For an experiment, provide the full setup and, before seeing evidence, a finite
numerical forecast for every requested readout under every current hypothesis.
The forecast hypothesis keys must exactly match the portfolio hypothesis_ids.
For a final submission, provide the structured model requested by the public
case resources. The selected hypothesis's portfolio confidence is the sole
final confidence; do not repeat confidence inside final.
The final.explanation field is a concise rationale and is not itself scored.
Do not reveal hidden chain-of-thought;
put only concise, decision-relevant statements in public fields.
"""

_PLAYER_V1_REPAIR = (
    "Generate exactly one valid action for the same episode view. "
    "You received no Oracle response or evidence between calls. "
    "This is a second generation and may differ semantically."
)

_ORACLE_V1_SYSTEM = """You are the Oracle presentation layer in a scientific benchmark.
The authoritative Oracle response in the user message is the only factual source.
Return exactly one JSON object matching the supplied schema, with no Markdown or
extra keys. Set message to an exact character-for-character copy of
authoritative_response.message. Do not paraphrase, summarize, prefix, suffix, or
otherwise rewrite it. JSON escaping may differ, but the decoded string must be
identical. Do not add measurements, infer missing facts, evaluate Player
hypotheses, or reveal hidden formulae. The benchmark runtime, not you, supplies
the authoritative status, message, and experimental evidence.
"""

_EVALUATOR_V1_SYSTEM = """You are a post-hoc evaluator of an interactive scientific benchmark.
The Player--Oracle episode is already complete. Score only the observable record
provided by the user; never infer or request hidden chain-of-thought. The
case-owned deterministic predictive evaluation is authoritative scientific
ground truth. Your ratings are separate diagnostics and must not replace,
average with, or reinterpret predictive_model_pass or active_pass.

For each axis return a number in [0,1], or null when the observable record is
insufficient to score it:
- experiment_design: whether requested experiments were relevant and discriminative;
- evidence_use: whether conclusions tracked the returned evidence;
- hypothesis_revision: whether support changed appropriately after evidence;
- stopping_decision: whether finalization or termination was justified by the record;
- claim_evidence_consistency: whether the final claim, if any, matches observed evidence;
- explanation_quality: whether the submitted explanation, if any, is concise and faithful.

Findings must identify concrete observable errors and cite sequence numbers from
the supplied transcript. Return exactly one JSON object matching the schema,
with no Markdown, hidden reasoning, overall score, pass/fail field, or extra keys.
"""


class _RecordingBackend:
    def __init__(self, outputs=()):
        self.outputs = list(outputs)
        self.requests = []

    def generate(self, request):
        self.requests.append(request)
        if not self.outputs:
            raise AssertionError("backend received an unexpected generation call")
        return GenerationResponse(
            text=self.outputs.pop(0),
            provider="test",
            model="fixture",
        )


def _view():
    return Episode(make_pendulum_case("historical")).view()


def _evaluator_log():
    return LoadedRunLog(
        run_id="prompt-version-test",
        events=(
            {
                "sequence": 0,
                "event_type": "run.started",
                "payload": {"case": {"case_id": "public.case"}},
            },
            {
                "sequence": 1,
                "event_type": "run.ended",
                "payload": {"status": "evaluated"},
            },
        ),
        complete=True,
    )


class PromptVersionTests(unittest.TestCase):
    def test_player_default_and_explicit_v1_requests_are_identical(self):
        default = build_generation_request(
            _view(),
            player_turn=1,
            config=GenerationConfig(),
        )
        explicit = build_generation_request(
            _view(),
            player_turn=1,
            config=GenerationConfig(),
            prompt_version=PLAYER_PROMPT_VERSION_V1,
        )

        self.assertEqual(DEFAULT_PLAYER_PROMPT_VERSION, PLAYER_PROMPT_VERSION_V1)
        self.assertEqual(
            generation_request_to_payload(default),
            generation_request_to_payload(explicit),
        )
        self.assertEqual(
            default.messages[0].content.split("\nAction JSON Schema:\n", 1)[0],
            _PLAYER_V1_SYSTEM,
        )
        self.assertNotIn("prompt_version", default.metadata)
        self.assertNotIn(
            "prompt_version",
            LLMPlayerBackend(_RecordingBackend()).run_config,
        )

    def test_player_v2_is_opt_in_and_hardens_primary_and_repair_prompts(self):
        primary = build_generation_request(
            _view(),
            player_turn=1,
            config=GenerationConfig(),
            prompt_version=PLAYER_PROMPT_VERSION_V2_JSON_HARDENED,
        )
        repair = build_generation_request(
            _view(),
            player_turn=1,
            config=GenerationConfig(),
            purpose="repair_action",
            prompt_version=PLAYER_PROMPT_VERSION_V2_JSON_HARDENED,
            invalid_output='{"wire_schema":',
            wire_error=WireDecodeError(
                "invalid_json",
                "$",
                "unterminated object",
            ),
        )

        self.assertEqual(
            primary.metadata["prompt_version"],
            PLAYER_PROMPT_VERSION_V2_JSON_HARDENED,
        )
        self.assertIn(
            "Serialization preflight is mandatory",
            primary.messages[0].content,
        )
        self.assertIn("its confidence must be exactly 1.0", primary.messages[0].content)
        self.assertIn(
            '{"op":"<allowed operator>","args":[...]}',
            primary.messages[0].content,
        )
        repair_payload = json.loads(repair.messages[1].content)["repair"]
        self.assertIn("Rebuild a fresh JSON value", repair_payload["instruction"])
        self.assertIn(
            "reconstruct nodes from the leaves upward",
            repair_payload["instruction"],
        )
        self.assertNotIn("may differ semantically", repair_payload["instruction"])
        self.assertEqual(
            repair.metadata["repair_prompt_version"],
            PLAYER_REPAIR_PROMPT_VERSION_V2_JSON_HARDENED,
        )
        self.assertEqual(primary.response_schema, repair.response_schema)

        v1_repair = build_generation_request(
            _view(),
            player_turn=1,
            config=GenerationConfig(),
            purpose="repair_action",
            invalid_output="not json",
            wire_error=WireDecodeError("invalid_json", "$", "invalid JSON"),
        )
        self.assertEqual(
            json.loads(v1_repair.messages[1].content)["repair"]["instruction"],
            _PLAYER_V1_REPAIR,
        )

        run_config = LLMPlayerBackend(
            _RecordingBackend(),
            prompt_version=PLAYER_PROMPT_VERSION_V2_JSON_HARDENED,
        ).run_config
        self.assertEqual(
            run_config["prompt_version"],
            PLAYER_PROMPT_VERSION_V2_JSON_HARDENED,
        )
        self.assertEqual(
            run_config["repair_prompt_version"],
            PLAYER_REPAIR_PROMPT_VERSION_V2_JSON_HARDENED,
        )

    def test_player_v2_does_not_silently_repair_invalid_output(self):
        backend = _RecordingBackend(("not json",))
        player = LLMPlayerBackend(
            backend,
            max_repair_attempts=0,
            prompt_version=PLAYER_PROMPT_VERSION_V2_JSON_HARDENED,
        )

        with self.assertRaises(AdapterOutputError) as raised:
            player.next_action(_view())

        self.assertEqual(raised.exception.attempts, 1)
        self.assertEqual(len(backend.requests), 1)

    def test_player_v3_is_separately_versioned_and_case_bound(self):
        request = build_generation_request(
            _view(),
            player_turn=1,
            config=GenerationConfig(),
            prompt_version=PLAYER_PROMPT_VERSION_V3_CASE_BOUND_JSON,
        )
        repair = build_generation_request(
            _view(),
            player_turn=1,
            config=GenerationConfig(),
            purpose="repair_action",
            prompt_version=PLAYER_PROMPT_VERSION_V3_CASE_BOUND_JSON,
            invalid_output="not json",
            wire_error=WireDecodeError("invalid_json", "$", "invalid JSON"),
        )

        self.assertEqual(
            request.metadata["prompt_version"],
            PLAYER_PROMPT_VERSION_V3_CASE_BOUND_JSON,
        )
        self.assertEqual(
            repair.metadata["repair_prompt_version"],
            PLAYER_REPAIR_PROMPT_VERSION_V3_CASE_BOUND_JSON,
        )
        self.assertIn("$defs", request.response_schema)
        controls = request.response_schema["properties"]["experiment"][
            "properties"
        ]["controls"]
        self.assertTrue(controls["required"])
        self.assertNotEqual(
            request.response_schema,
            build_generation_request(
                _view(),
                player_turn=1,
                config=GenerationConfig(),
                prompt_version=PLAYER_PROMPT_VERSION_V2_JSON_HARDENED,
            ).response_schema,
        )

        run_config = LLMPlayerBackend(
            _RecordingBackend(),
            prompt_version=PLAYER_PROMPT_VERSION_V3_CASE_BOUND_JSON,
        ).run_config
        self.assertEqual(
            run_config["repair_prompt_version"],
            PLAYER_REPAIR_PROMPT_VERSION_V3_CASE_BOUND_JSON,
        )

    def test_oracle_default_is_unchanged_and_v2_is_marked(self):
        case = make_pendulum_case("historical")
        proposal = experiment_action().experiment
        self.assertIsNotNone(proposal)
        authoritative = CaseOracle(case.definition, case.world_model).respond(proposal)
        default = build_oracle_generation_request(
            case.definition,
            proposal,
            authoritative,
            oracle_turn=1,
            config=GenerationConfig(),
        )
        explicit = build_oracle_generation_request(
            case.definition,
            proposal,
            authoritative,
            oracle_turn=1,
            config=GenerationConfig(),
            prompt_version=ORACLE_PROMPT_VERSION_V1,
        )
        hardened = build_oracle_generation_request(
            case.definition,
            proposal,
            authoritative,
            oracle_turn=1,
            config=GenerationConfig(),
            prompt_version=ORACLE_PROMPT_VERSION_V2_JSON_HARDENED,
        )

        self.assertEqual(DEFAULT_ORACLE_PROMPT_VERSION, ORACLE_PROMPT_VERSION_V1)
        self.assertEqual(
            generation_request_to_payload(default),
            generation_request_to_payload(explicit),
        )
        self.assertEqual(
            default.messages[0].content.split(
                "\nOracle Message JSON Schema:\n",
                1,
            )[0],
            _ORACLE_V1_SYSTEM,
        )
        self.assertNotIn("prompt_version", default.metadata)
        self.assertEqual(default.messages[1], hardened.messages[1])
        self.assertEqual(default.response_schema, hardened.response_schema)
        self.assertIn("serialize it with JSON", hardened.messages[0].content)
        self.assertIn("already-serialized punctuation", hardened.messages[0].content)
        self.assertEqual(
            hardened.metadata["prompt_version"],
            ORACLE_PROMPT_VERSION_V2_JSON_HARDENED,
        )
        default_config = LLMOracle(
            case.definition,
            case.world_model,
            _RecordingBackend(),
        ).run_config
        hardened_config = LLMOracle(
            case.definition,
            case.world_model,
            _RecordingBackend(),
            prompt_version=ORACLE_PROMPT_VERSION_V2_JSON_HARDENED,
        ).run_config
        self.assertNotIn("prompt_version", default_config)
        self.assertEqual(
            hardened_config["prompt_version"],
            ORACLE_PROMPT_VERSION_V2_JSON_HARDENED,
        )

    def test_evaluator_default_is_unchanged_and_v2_is_marked(self):
        log = _evaluator_log()
        default = build_evaluator_generation_request(
            log,
            config=GenerationConfig(),
        )
        explicit = build_evaluator_generation_request(
            log,
            config=GenerationConfig(),
            prompt_version=EVALUATOR_PROMPT_VERSION_V1,
        )
        hardened = build_evaluator_generation_request(
            log,
            config=GenerationConfig(),
            prompt_version=EVALUATOR_PROMPT_VERSION_V2_JSON_HARDENED,
        )

        self.assertEqual(
            DEFAULT_EVALUATOR_PROMPT_VERSION,
            EVALUATOR_PROMPT_VERSION_V1,
        )
        self.assertEqual(
            generation_request_to_payload(default),
            generation_request_to_payload(explicit),
        )
        self.assertEqual(
            default.messages[0].content.split("\nEvaluator JSON Schema:\n", 1)[0],
            _EVALUATOR_V1_SYSTEM,
        )
        self.assertNotIn("prompt_version", default.metadata)
        self.assertEqual(default.messages[1], hardened.messages[1])
        self.assertEqual(default.response_schema, hardened.response_schema)
        self.assertIn(
            "scores must contain exactly these six keys",
            hardened.messages[0].content,
        )
        self.assertIn("copied only from sequence fields", hardened.messages[0].content)
        self.assertEqual(
            hardened.metadata["prompt_version"],
            EVALUATOR_PROMPT_VERSION_V2_JSON_HARDENED,
        )

        evaluator_backend = _RecordingBackend(
            (
                json.dumps(
                    {
                        "scores": {axis: None for axis in EVALUATOR_SCORE_AXES},
                        "findings": [],
                        "summary": "The minimal transcript is insufficient to score.",
                    }
                ),
            )
        )
        evaluator = PostHocLLMEvaluator(
            evaluator_backend,
            prompt_version=EVALUATOR_PROMPT_VERSION_V2_JSON_HARDENED,
        )
        evaluated = evaluator.evaluate(log)
        self.assertEqual(
            evaluated.request.metadata["prompt_version"],
            EVALUATOR_PROMPT_VERSION_V2_JSON_HARDENED,
        )
        self.assertEqual(len(evaluator_backend.requests), 1)

    def test_unknown_prompt_versions_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "unsupported Player prompt_version"):
            build_generation_request(
                _view(),
                player_turn=1,
                config=GenerationConfig(),
                prompt_version="unknown",
            )
        case = make_pendulum_case("historical")
        proposal = experiment_action().experiment
        self.assertIsNotNone(proposal)
        authoritative = CaseOracle(case.definition, case.world_model).respond(proposal)
        with self.assertRaisesRegex(ValueError, "unsupported Oracle prompt_version"):
            build_oracle_generation_request(
                case.definition,
                proposal,
                authoritative,
                oracle_turn=1,
                config=GenerationConfig(),
                prompt_version="unknown",
            )
        with self.assertRaisesRegex(ValueError, "unsupported Evaluator prompt_version"):
            build_evaluator_generation_request(
                _evaluator_log(),
                config=GenerationConfig(),
                prompt_version="unknown",
            )


if __name__ == "__main__":
    unittest.main()
