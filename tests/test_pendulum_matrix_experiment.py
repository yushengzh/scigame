from __future__ import annotations

import argparse
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from role_benchmark import (
    GenerationConfig,
    GenerationRequest,
    Hypothesis,
    HypothesisPortfolio,
    Message,
    TerminationKind,
)

from experiments.run_pendulum_matrix import (
    DEFAULT_SCHEDULE_SEED,
    DeepSeekChatBackend,
    EPISODE_RESULT_SCHEMA,
    EXPERIMENT_SCHEMA,
    PLAYER_PROFILES,
    _config_payload,
    _evaluated_result,
    _infrastructure_failed_result,
    _run_one_episode,
    build_plan,
    load_oracle_backend,
    load_player_backends,
    prepare_output,
    run_matrix,
    select_plan,
    write_summaries,
)


class _FakeHTTPResponse:
    def __init__(self, payload):
        self._payload = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return None

    def read(self):
        return self._payload


def _args(output_dir):
    return argparse.Namespace(
        output_dir=str(output_dir),
        endpoint="https://provider.invalid/chat/completions",
        max_output_tokens=8192,
        max_repair_attempts=1,
        oracle_max_output_tokens=256,
        max_actions=16,
        timeout_s=1.0,
        workers=1,
        schedule_seed=DEFAULT_SCHEDULE_SEED,
        profile=None,
        world=None,
        track=None,
        repeat=None,
        dry_run=False,
    )


def _fake_run(
    *,
    kind=TerminationKind.SUBMITTED,
    success=True,
    message=None,
    attempts_used=3,
    selected_portfolio_confidence=0.9,
    trajectory_scores=None,
    run_id="run-1",
):
    submitted = kind == TerminationKind.SUBMITTED
    reason_codes = {
        TerminationKind.SUBMITTED: "submitted",
        TerminationKind.PLAYER_OUTPUT_INVALID: "invalid_json",
        TerminationKind.ACTION_REJECTED: "experiment_budget_exhausted",
        TerminationKind.ACTION_LIMIT: "max_actions_reached",
    }
    termination_messages = {
        TerminationKind.SUBMITTED: "Player committed a protocol-valid final submission.",
        TerminationKind.PLAYER_OUTPUT_INVALID: "Player output is not valid JSON.",
        TerminationKind.ACTION_REJECTED: "Experiment budget is exhausted.",
        TerminationKind.ACTION_LIMIT: "Player did not commit within max_actions.",
    }
    evaluation_message = message or (
        "passed"
        if submitted and success
        else "hidden prediction error exceeded tolerance"
        if submitted
        else "No protocol-valid final submission was available."
    )
    scores = (
        {"predictive_model_pass": float(success)}
        if submitted
        else {
            "active_pass": 0.0,
            "protocol_completion": 0.0,
            "submission_available": 0.0,
        }
    )
    outcome = SimpleNamespace(
        termination=SimpleNamespace(
            kind=kind,
            code=reason_codes[kind],
            message=termination_messages[kind],
        ),
        active_pass=submitted and success,
        scientifically_evaluable=submitted,
        protocol_completed=submitted,
        evaluation=SimpleNamespace(
            success=submitted and success,
            message=evaluation_message,
            scores=scores,
        ),
        attempts_used=attempts_used,
        final_submission=(
            SimpleNamespace(hypothesis_id="H1") if submitted else None
        ),
        final_portfolio=(
            HypothesisPortfolio(
                (
                    Hypothesis(
                        "H1",
                        "Selected quantitative relationship.",
                        selected_portfolio_confidence,
                    ),
                    Hypothesis(
                        "H2",
                        "Competing quantitative relationship.",
                        1.0 - selected_portfolio_confidence,
                    ),
                )
            )
            if submitted
            else None
        ),
        trajectory_scores=trajectory_scores or {},
        protocol_violations=(),
    )
    return SimpleNamespace(
        run_id=run_id,
        llm_stats=None,
        oracle_llm_stats=None,
        outcome=outcome,
    )


class PendulumMatrixExperimentTests(unittest.TestCase):
    def test_structured_outcomes_map_to_the_four_evaluated_categories(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            spec = build_plan()[0]
            common = {
                "spec": spec,
                "log_path": root / "episode.jsonl",
                "output_dir": root,
                "started_at": "2026-08-24T00:00:00Z",
                "elapsed_s": 1.0,
            }
            passed = _evaluated_result(
                run=_fake_run(),
                **common,
            )
            scientific = _evaluated_result(
                run=_fake_run(success=False),
                **common,
            )
            generation = _evaluated_result(
                run=_fake_run(kind=TerminationKind.PLAYER_OUTPUT_INVALID),
                **common,
            )
            rejected = _evaluated_result(
                run=_fake_run(kind=TerminationKind.ACTION_REJECTED),
                **common,
            )
            limited = _evaluated_result(
                run=_fake_run(kind=TerminationKind.ACTION_LIMIT),
                **common,
            )
            infrastructure = _infrastructure_failed_result(
                spec=spec,
                log_path=root / "episode.jsonl",
                output_dir=root,
                exc=RuntimeError("provider unavailable"),
                started_at="2026-08-24T00:00:00Z",
                elapsed_s=1.0,
            )
        self.assertEqual(passed["status"], "evaluated")
        self.assertEqual(passed["active_pass_category"], "pass")
        self.assertFalse(scientific["active_pass"])
        self.assertEqual(scientific["active_pass_category"], "scientific_failure")
        self.assertTrue(scientific["scientifically_evaluable"])
        self.assertTrue(scientific["protocol_completion"])
        self.assertEqual(
            scientific["evaluation_message"],
            "hidden prediction error exceeded tolerance",
        )
        self.assertEqual(
            generation["active_pass_category"],
            "player_generation_failure",
        )
        self.assertEqual(generation["termination_kind"], "player_output_invalid")
        self.assertEqual(generation["reason_code"], "invalid_json")
        self.assertFalse(generation["scientifically_evaluable"])
        self.assertFalse(generation["protocol_completion"])
        self.assertIsNone(generation["selected_portfolio_confidence"])
        self.assertEqual(
            rejected["active_pass_category"],
            "player_protocol_failure",
        )
        self.assertEqual(limited["active_pass_category"], "player_protocol_failure")
        self.assertEqual(infrastructure["status"], "infrastructure_failed")
        self.assertIsNone(infrastructure["active_pass_category"])
        self.assertIsNone(infrastructure["active_pass"])
        self.assertIsNone(infrastructure["termination_kind"])
        self.assertIsNone(infrastructure["evaluation_message"])

    def test_run_one_uses_outcome_and_only_exceptions_are_infrastructure(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            args = _args(root)
            spec = build_plan()[0]
            log_path = root / "episode.jsonl"
            player_terminal = _fake_run(
                kind=TerminationKind.PLAYER_OUTPUT_INVALID,
                run_id=spec.episode_id,
            )
            player_terminal.log_path = str(log_path)
            failure_analysis = {
                "schema": "role_benchmark.failure_analysis",
                "status": "failed_analyzed",
            }
            with mock.patch(
                "experiments.run_pendulum_matrix._make_case"
            ), mock.patch(
                "experiments.run_pendulum_matrix.run_llm_episode",
                return_value=player_terminal,
            ) as run_episode, mock.patch(
                "experiments.run_pendulum_matrix.load_run_log",
                return_value=SimpleNamespace(events=()),
            ) as load_log, mock.patch(
                "experiments.run_pendulum_matrix.analyze_failure_events",
                return_value=failure_analysis,
            ):
                evaluated = _run_one_episode(
                    args,
                    player_backend=SimpleNamespace(),
                    oracle_backend=SimpleNamespace(),
                    output_dir=root,
                    spec=spec,
                    log_path=log_path,
                )
            load_log.assert_called_once_with(str(log_path))
            self.assertEqual(evaluated["failure_analysis"], failure_analysis)
            self.assertEqual(
                run_episode.call_args.kwargs["run_metadata"]["provider_binding_id"],
                DeepSeekChatBackend.binding_id,
            )
            with mock.patch(
                "experiments.run_pendulum_matrix._make_case"
            ), mock.patch(
                "experiments.run_pendulum_matrix.run_llm_episode",
                side_effect=RuntimeError("provider unavailable"),
            ):
                infrastructure = _run_one_episode(
                    args,
                    player_backend=SimpleNamespace(),
                    oracle_backend=SimpleNamespace(),
                    output_dir=root,
                    spec=spec,
                    log_path=log_path,
                )

        self.assertEqual(evaluated["status"], "evaluated")
        self.assertEqual(
            evaluated["active_pass_category"],
            "player_generation_failure",
        )
        self.assertEqual(infrastructure["status"], "infrastructure_failed")

    def test_output_directory_requires_equivalent_config_content(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            args = _args(root)
            current = _config_payload(args, build_plan(args.schedule_seed))
            prepare_output(root, current)

            same_content = dict(current)
            same_content["created_at"] = "2099-01-01T00:00:00Z"
            prepare_output(root, same_content)

            different = dict(current)
            different["player_generation"] = {
                **current["player_generation"],
                "max_actions": current["player_generation"]["max_actions"] + 1,
            }
            with self.assertRaisesRegex(ValueError, "different experiment config"):
                prepare_output(root, different)

    def test_plan_is_exactly_sixty_paired_episodes(self):
        plan = build_plan()
        self.assertEqual(len(plan), 60)
        self.assertEqual(len({item.episode_id for item in plan}), 60)
        self.assertEqual({item.world for item in plan}, {"historical", "counterfactual"})
        self.assertEqual({item.track for item in plan}, {"identification", "discovery"})
        self.assertEqual(
            [(profile.model, profile.thinking, profile.reasoning_effort) for profile in PLAYER_PROFILES],
            [("deepseek-v4-flash", "disabled", None)] * 3,
        )
        self.assertEqual(
            [item.schedule_index for item in plan], list(range(1, 61))
        )
        for profile in ("player_1", "player_2", "player_3"):
            profile_items = [item for item in plan if item.player_profile == profile]
            self.assertEqual(len(profile_items), 20)

    def test_schedule_is_seeded_randomized_complete_blocks(self):
        first = build_plan(12345)
        second = build_plan(12345)
        different = build_plan(54321)
        self.assertEqual(
            [item.episode_id for item in first],
            [item.episode_id for item in second],
        )
        self.assertNotEqual(
            [item.episode_id for item in first],
            [item.episode_id for item in different],
        )
        self.assertEqual(
            {item.episode_id for item in first},
            {item.episode_id for item in different},
        )
        expected_cells = {
            (profile.profile_id, world, track)
            for profile in PLAYER_PROFILES
            for world in ("historical", "counterfactual")
            for track in ("identification", "discovery")
        }
        for start in range(0, 60, 12):
            block = first[start : start + 12]
            self.assertEqual({item.repeat for item in block}, {start // 12 + 1})
            self.assertEqual(
                {(item.player_profile, item.world, item.track) for item in block},
                expected_cells,
            )
        adjacent_cells = [
            (
                (left.player_profile, left.world, left.track),
                (right.player_profile, right.world, right.track),
            )
            for left, right in zip(first, first[1:])
        ]
        self.assertTrue(all(left != right for left, right in adjacent_cells))

    def test_repeat_one_selector_is_twelve_formal_cells(self):
        selected = select_plan(build_plan(), repeats=[1])
        self.assertEqual(len(selected), 12)
        self.assertEqual({item.repeat for item in selected}, {1})

    def test_selection_preserves_global_schedule_order(self):
        plan = build_plan(404)
        selected = select_plan(
            plan,
            profiles=["player_2"],
            tracks=["discovery"],
        )
        expected = [
            item
            for item in plan
            if item.player_profile == "player_2" and item.track == "discovery"
        ]
        self.assertEqual(selected, expected)

    def test_player_slots_and_oracle_load_as_distinct_backends(self):
        with tempfile.TemporaryDirectory() as directory:
            args = _args(directory)
            players = load_player_backends(args, api_key="not-persisted")
            oracle = load_oracle_backend(args, api_key="not-persisted")
        self.assertEqual(set(players), {"player_1", "player_2", "player_3"})
        self.assertEqual(len({id(backend) for backend in players.values()}), 3)
        self.assertNotIn(id(oracle), {id(backend) for backend in players.values()})
        self.assertEqual(
            {(backend._model, backend._thinking, backend._reasoning_effort) for backend in players.values()},
            {("deepseek-v4-flash", "disabled", None)},
        )

    def test_nonprefix_selector_is_rejected_before_backend_loading(self):
        with tempfile.TemporaryDirectory() as directory:
            args = _args(directory)
            args.profile = ["player_1"]
            with mock.patch(
                "experiments.run_pendulum_matrix.load_player_backends"
            ) as load_players:
                with self.assertRaisesRegex(ValueError, "prefix"):
                    run_matrix(args, api_key="not-persisted")
            load_players.assert_not_called()

    def test_run_dispatches_the_frozen_schedule_with_one_backend_per_slot(self):
        with tempfile.TemporaryDirectory() as directory:
            args = _args(directory)
            args.repeat = [1]
            observed = []

            def fake_run_one(*unused_args, **kwargs):
                spec = kwargs["spec"]
                observed.append(
                    (
                        spec.schedule_index,
                        spec.player_profile,
                        id(kwargs["player_backend"]),
                        id(kwargs["oracle_backend"]),
                    )
                )
                return _evaluated_result(
                    spec=spec,
                    log_path=kwargs["log_path"],
                    output_dir=Path(directory).resolve(),
                    run=_fake_run(run_id=spec.episode_id),
                    started_at="2026-08-24T00:00:00Z",
                    elapsed_s=0.0,
                )

            with mock.patch(
                "experiments.run_pendulum_matrix._make_case"
            ), mock.patch(
                "experiments.run_pendulum_matrix._run_one_episode",
                side_effect=fake_run_one,
            ):
                run_matrix(args, api_key="not-persisted")

            selected = select_plan(build_plan(args.schedule_seed), repeats=[1])
            self.assertEqual(
                [row[0] for row in observed],
                [spec.schedule_index for spec in selected],
            )
            player_ids = {}
            oracle_ids = set()
            for _, profile, player_id, oracle_id in observed:
                player_ids.setdefault(profile, set()).add(player_id)
                oracle_ids.add(oracle_id)
            self.assertEqual(set(player_ids), {"player_1", "player_2", "player_3"})
            self.assertTrue(all(len(ids) == 1 for ids in player_ids.values()))
            self.assertEqual(len({next(iter(ids)) for ids in player_ids.values()}), 3)
            self.assertEqual(len(oracle_ids), 1)
            self.assertNotIn(next(iter(oracle_ids)), {next(iter(ids)) for ids in player_ids.values()})

    def test_resume_preserves_the_frozen_pending_order(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            args = _args(root)
            args.repeat = [1]
            full_plan = build_plan(args.schedule_seed)
            selected = select_plan(full_plan, repeats=[1])
            prepare_output(root, _config_payload(args, full_plan))
            completed_ids = {selected[0].episode_id, selected[1].episode_id}

            for spec in selected:
                if spec.episode_id not in completed_ids:
                    continue
                payload = {
                    "schema": EPISODE_RESULT_SCHEMA,
                    "schedule_index": spec.schedule_index,
                    "episode_id": spec.episode_id,
                    "status": "evaluated",
                    "active_pass": True,
                    "active_pass_category": "pass",
                    "termination_kind": "submitted",
                    "reason_code": "submitted",
                    "termination_message": (
                        "Player committed a protocol-valid final submission."
                    ),
                    "scientifically_evaluable": True,
                    "protocol_completion": True,
                    "player_profile": spec.player_profile,
                    "player_model": spec.player_model,
                    "thinking": spec.thinking,
                    "reasoning_effort": spec.reasoning_effort,
                    "world": spec.world,
                    "track": spec.track,
                    "repeat": spec.repeat,
                    "log_path": "episodes/already-complete.jsonl",
                    "run_id": spec.episode_id,
                    "evaluation_success": True,
                    "evaluation_message": "passed",
                    "attempts_used": 1,
                    "selected_portfolio_confidence": 0.9,
                    "scores": {"predictive_model_pass": 1.0},
                    "trajectory_scores": {},
                    "player_llm_stats": None,
                    "oracle_llm_stats": None,
                    "elapsed_s": 0.0,
                    "error_type": None,
                    "error_message": None,
                }
                path = root / "results" / (spec.episode_id + ".result.json")
                path.write_text(json.dumps(payload), encoding="utf-8")

            observed = []

            def fake_run_one(*unused_args, **kwargs):
                spec = kwargs["spec"]
                observed.append(spec.episode_id)
                payload = json.loads(
                    (root / "results" / (selected[0].episode_id + ".result.json")).read_text(
                        encoding="utf-8"
                    )
                )
                payload.update(
                    {
                        "schedule_index": spec.schedule_index,
                        "episode_id": spec.episode_id,
                        "player_profile": spec.player_profile,
                        "player_model": spec.player_model,
                        "world": spec.world,
                        "track": spec.track,
                        "repeat": spec.repeat,
                        "run_id": spec.episode_id,
                    }
                )
                return payload

            with mock.patch(
                "experiments.run_pendulum_matrix._make_case"
            ), mock.patch(
                "experiments.run_pendulum_matrix._run_one_episode",
                side_effect=fake_run_one,
            ):
                run_matrix(args, api_key="not-persisted")

            self.assertEqual(
                observed,
                [spec.episode_id for spec in selected if spec.episode_id not in completed_ids],
            )

    def test_infrastructure_failure_halts_and_resume_retries_same_index(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            args = _args(root)
            args.repeat = [1]
            first_attempt = []

            def fail_once(*unused_args, **kwargs):
                spec = kwargs["spec"]
                first_attempt.append(spec.episode_id)
                return _infrastructure_failed_result(
                    spec=spec,
                    log_path=kwargs["log_path"],
                    output_dir=root,
                    exc=RuntimeError("provider unavailable"),
                    started_at="2026-08-24T00:00:00Z",
                    elapsed_s=1.0,
                )

            with mock.patch(
                "experiments.run_pendulum_matrix._make_case"
            ), mock.patch(
                "experiments.run_pendulum_matrix._run_one_episode",
                side_effect=fail_once,
            ):
                with self.assertRaisesRegex(RuntimeError, "infrastructure failure"):
                    run_matrix(args, api_key="not-persisted")

            first_spec = select_plan(
                build_plan(args.schedule_seed), repeats=[1]
            )[0]
            self.assertEqual(first_attempt, [first_spec.episode_id])

            resumed = []

            def succeed(*unused_args, **kwargs):
                spec = kwargs["spec"]
                resumed.append(spec.episode_id)
                return _evaluated_result(
                    spec=spec,
                    log_path=kwargs["log_path"],
                    output_dir=root,
                    run=_fake_run(
                        attempts_used=1,
                        run_id=spec.episode_id,
                    ),
                    started_at="2026-08-24T00:00:00Z",
                    elapsed_s=1.0,
                )

            with mock.patch(
                "experiments.run_pendulum_matrix._make_case"
            ), mock.patch(
                "experiments.run_pendulum_matrix._run_one_episode",
                side_effect=succeed,
            ):
                run_matrix(args, api_key="not-persisted")

            selected = select_plan(build_plan(args.schedule_seed), repeats=[1])
            self.assertEqual(resumed, [spec.episode_id for spec in selected])
            self.assertEqual(resumed[0], first_attempt[0])

    def test_player_failures_consume_cells_and_schedule_continues(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            args = _args(root)
            args.repeat = [1]
            observed = []

            def run_with_player_failures(*unused_args, **kwargs):
                spec = kwargs["spec"]
                observed.append(spec.episode_id)
                if len(observed) <= 2:
                    return _evaluated_result(
                        spec=spec,
                        log_path=kwargs["log_path"],
                        output_dir=root,
                        run=_fake_run(
                            kind=(
                                TerminationKind.PLAYER_OUTPUT_INVALID
                                if len(observed) == 1
                                else TerminationKind.ACTION_REJECTED
                            ),
                            run_id=spec.episode_id,
                        ),
                        started_at="2026-08-24T00:00:00Z",
                        elapsed_s=1.0,
                    )
                return _evaluated_result(
                    spec=spec,
                    log_path=kwargs["log_path"],
                    output_dir=root,
                    run=_fake_run(
                        attempts_used=1,
                        run_id=spec.episode_id,
                    ),
                    started_at="2026-08-24T00:00:00Z",
                    elapsed_s=1.0,
                )

            with mock.patch(
                "experiments.run_pendulum_matrix._make_case"
            ), mock.patch(
                "experiments.run_pendulum_matrix._run_one_episode",
                side_effect=run_with_player_failures,
            ):
                results = run_matrix(args, api_key="not-persisted")

            selected = select_plan(build_plan(args.schedule_seed), repeats=[1])
            self.assertEqual(observed, [spec.episode_id for spec in selected])
            first = next(
                result for result in results if result["episode_id"] == observed[0]
            )
            second = next(
                result for result in results if result["episode_id"] == observed[1]
            )
            self.assertEqual(first["status"], "evaluated")
            self.assertEqual(
                first["active_pass_category"],
                "player_generation_failure",
            )
            self.assertEqual(second["status"], "evaluated")
            self.assertEqual(
                second["active_pass_category"],
                "player_protocol_failure",
            )

    def test_changed_schedule_seed_is_rejected_before_backend_loading(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            args = _args(root)
            full_plan = build_plan(args.schedule_seed)
            prepare_output(root, _config_payload(args, full_plan))
            args.schedule_seed += 1
            with mock.patch(
                "experiments.run_pendulum_matrix.load_player_backends"
            ) as load_players:
                with self.assertRaisesRegex(ValueError, "different experiment config"):
                    run_matrix(args, api_key="not-persisted")
            load_players.assert_not_called()

    def test_persisted_config_has_no_credential_fields(self):
        with tempfile.TemporaryDirectory() as directory:
            args = _args(directory)
            plan = build_plan()
            config = _config_payload(args, plan)
            serialized = json.dumps(config)
            self.assertNotIn("api_key", serialized.lower())
            self.assertNotIn("secret-value", serialized)
            prepare_output(Path(directory), config)
            stored = (Path(directory) / "config.json").read_text(encoding="utf-8")
            self.assertNotIn("api_key", stored.lower())
            self.assertEqual(config["schedule"]["seed"], DEFAULT_SCHEDULE_SEED)
            self.assertEqual(len(config["schedule"]["execution_order"]), 60)
            self.assertEqual(config["execution"]["workers"], 1)
            self.assertEqual(
                config["provider"]["binding_id"],
                DeepSeekChatBackend.binding_id,
            )

    def test_binding_maps_chat_response_without_persisting_key(self):
        captured = {}

        def fake_urlopen(request, timeout):
            captured["authorization"] = request.headers["Authorization"]
            captured["body"] = json.loads(request.data.decode("utf-8"))
            captured["timeout"] = timeout
            return _FakeHTTPResponse(
                {
                    "id": "response-1",
                    "model": "returned-model",
                    "choices": [
                        {
                            "finish_reason": "stop",
                            "message": {"content": '{"ok":true}'},
                        }
                    ],
                    "usage": {"prompt_tokens": 7, "completion_tokens": 3},
                }
            )

        backend = DeepSeekChatBackend(
            endpoint="https://provider.invalid/chat/completions",
            api_key="secret-value",
            model="requested-model",
            thinking="enabled",
            reasoning_effort="high",
            urlopen=fake_urlopen,
        )
        response = backend.generate(
            GenerationRequest(
                messages=(Message("user", "Return JSON."),),
                response_schema={"type": "object"},
                config=GenerationConfig(seed=None),
            )
        )
        self.assertEqual(captured["authorization"], "Bearer secret-value")
        self.assertNotIn("seed", captured["body"])
        self.assertEqual(captured["body"]["response_format"], {"type": "json_object"})
        self.assertEqual(captured["body"]["thinking"], {"type": "enabled"})
        self.assertEqual(captured["body"]["reasoning_effort"], "high")
        self.assertEqual(response.model, "returned-model")
        self.assertEqual(response.usage.input_tokens, 7)
        self.assertEqual(
            response.metadata["binding_id"],
            DeepSeekChatBackend.binding_id,
        )
        self.assertNotIn("secret-value", json.dumps(response.metadata))

    def test_formal_nonthinking_binding_omits_reasoning_effort(self):
        captured = {}

        def fake_urlopen(request, timeout):
            captured["body"] = json.loads(request.data.decode("utf-8"))
            return _FakeHTTPResponse(
                {
                    "choices": [
                        {"finish_reason": "stop", "message": {"content": '{"ok":true}'}}
                    ],
                    "usage": {},
                }
            )

        backend = DeepSeekChatBackend(
            endpoint="https://provider.invalid/chat/completions",
            api_key="secret-value",
            model="deepseek-v4-flash",
            thinking="disabled",
            reasoning_effort=None,
            urlopen=fake_urlopen,
        )
        backend.generate(
            GenerationRequest(
                messages=(Message("user", "Return JSON."),),
                response_schema={"type": "object"},
                config=GenerationConfig(max_output_tokens=8192, seed=None),
            )
        )
        self.assertEqual(captured["body"]["thinking"], {"type": "disabled"})
        self.assertNotIn("reasoning_effort", captured["body"])
        self.assertEqual(captured["body"]["max_tokens"], 8192)

    def test_summaries_are_rebuilt_from_episode_sidecars(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            args = _args(root)
            plan = build_plan()
            config = _config_payload(args, plan)
            prepare_output(root, config)
            result = {
                "schema": EPISODE_RESULT_SCHEMA,
                "schedule_index": plan[0].schedule_index,
                "episode_id": plan[0].episode_id,
                "status": "evaluated",
                "active_pass": True,
                "active_pass_category": "pass",
                "termination_kind": "submitted",
                "reason_code": "submitted",
                "termination_message": (
                    "Player committed a protocol-valid final submission."
                ),
                "scientifically_evaluable": True,
                "protocol_completion": True,
                "player_profile": plan[0].player_profile,
                "player_model": plan[0].player_model,
                "thinking": plan[0].thinking,
                "reasoning_effort": plan[0].reasoning_effort,
                "world": plan[0].world,
                "track": plan[0].track,
                "repeat": plan[0].repeat,
                "log_path": "episodes/test.jsonl",
                "run_id": "run-1",
                "evaluation_success": True,
                "evaluation_message": "passed",
                "attempts_used": 3,
                "selected_portfolio_confidence": 0.9,
                "scores": {"predictive_model_pass": 1.0},
                "trajectory_scores": {
                    "experiment_discriminativeness_mean": 2.5,
                    "evidence_aligned_belief_update_rate": 1.0,
                    "forecast_pair_count": 3.0,
                    "scorable_belief_pair_count": 2.0,
                },
                "player_llm_stats": {"player_turns": 4, "input_tokens": 10, "output_tokens": 5},
                "oracle_llm_stats": None,
                "elapsed_s": 1.0,
                "error_type": None,
                "error_message": None,
            }
            result_path = root / "results" / (plan[0].episode_id + ".result.json")
            result_path.write_text(json.dumps(result), encoding="utf-8")
            results = write_summaries(root)
            self.assertEqual(len(results), 1)
            summary = json.loads((root / "episodes.json").read_text(encoding="utf-8"))
            self.assertEqual(summary["schema"], EXPERIMENT_SCHEMA)
            self.assertEqual(summary["episode_count"], 1)
            csv_text = (root / "episodes.csv").read_text(encoding="utf-8")
            self.assertIn("predictive_model_pass", csv_text)
            self.assertIn("experiment_discriminativeness_mean", csv_text)
            self.assertIn("active_pass_category", csv_text)
            self.assertIn("termination_kind", csv_text)
            self.assertIn("scientifically_evaluable", csv_text)
            self.assertIn("protocol_completion", csv_text)
            self.assertIn("2.5", csv_text)


if __name__ == "__main__":
    unittest.main()
