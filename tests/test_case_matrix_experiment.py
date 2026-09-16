from __future__ import annotations

import argparse
import contextlib
import io
import json
import re
import tempfile
import threading
import time
import unittest
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from role_benchmark import (
    ADAPTIVE_EXPERIMENTAL_DESIGN,
    BenchmarkTrack,
    DEFAULT_ORACLE_PROMPT_VERSION,
    EVALUATION_METHODS,
    FIXED_EXPERIMENTAL_DESIGN,
    FinalSubmission,
    GenerationConfig,
    GenerationRequest,
    GenerationResponse,
    JSONLRunLog,
    LLMPlayerBackend,
    Message,
    ORACLE_PROMPT_VERSION_V2_JSON_HARDENED,
    ProviderTransportError,
    TerminationKind,
    TokenUsage,
)
from role_benchmark.discovery_evaluation import DISCOVERY_PROMPT_VERSION, _claim_text
from role_benchmark.llm import PLAYER_PROMPT_VERSION_V5_PERFORMANCE
from role_benchmark.performance import PERFORMANCE_PROTOCOL
from experiments.core160_pack import (
    CORE160_TEMPORAL_COUNTERFACTUAL_CONDITION_ID,
    CORE160_TEMPORAL_SOURCE_CONDITION_ID,
    CORE160_TEMPORAL_SOURCE_RELATION_ID,
    CORE160_TEMPORAL_VARIANT_ID,
)
from experiments.run_case_matrix import (
    ACCEPTED_TEMPORAL_CASE_FAMILIES,
    BOTH_CASE_FAMILIES,
    CASE_PACKS,
    CASE_SPECS,
    DEFAULT_SCHEDULE_SEED,
    DETERMINISTIC_ORACLE,
    EPISODE_RESULT_SCHEMA,
    EXPERIMENT_SCHEMA,
    GEMINI_API_KEY_ENV,
    GEMINI_ENDPOINT_TEMPLATE,
    GEMINI_MODEL,
    IFM_API_KEY_ENV,
    HISTORICAL_CASE_FAMILIES,
    HISTORICAL_CONDITION_IDS,
    LEGACY_TEMPORAL_CASE_FAMILIES,
    LLM_PRESENTATION_ORACLE,
    OPENAI_API_KEY_ENV,
    OPENAI_ENDPOINT,
    TASK_SETTINGS,
    TEMPORAL_CASE_FAMILIES,
    CaseMatrixDeepSeekBackend,
    ConcurrencyLimitedBackend,
    _arxiv_base_id,
    _config_payload,
    _evaluated_result,
    _infrastructure_failed_result,
    _make_case,
    _merge_unique_temporal_identities,
    _parser,
    _provider_payload,
    _resolve_api_key,
    _resolve_api_keys,
    _run_evaluator,
    _run_one_episode,
    _runtime_profile,
    build_plan,
    load_backends,
    main,
    prepare_output,
    run_matrix,
    select_plan,
    write_summaries,
)
from experiments.run_pendulum_matrix import DeepSeekChatBackend
from experiments.openai_responses import OpenAIResponsesBackend
from experiments.ifm_chat_completions import (
    DEFAULT_IFM_CHAT_COMPLETIONS_ENDPOINT,
    DEFAULT_IFM_MODEL,
    DEFAULT_IFM_PLATFORM_ENDPOINT,
    DEFAULT_IFM_PLATFORM_MODEL,
    IFMChatCompletionsBackend,
)


def _args(output_dir):
    return argparse.Namespace(
        output_dir=str(output_dir),
        experiment_id="EXP-TEST-001",
        case_pack="historical",
        player_provider="openai",
        player_endpoint="https://player.invalid/chat/completions",
        player_model="gpt-5.6",
        player_snapshot_id="unknown",
        player_thinking=None,
        player_reasoning_effort="none",
        player_timeout_s=1.0,
        player_concurrency=None,
        player_api_key=None,
        player_api_key_stdin=False,
        player_prompt_api_key=False,
        player_api_key_env="PLAYER_API_KEY",
        oracle_provider="deepseek",
        oracle_endpoint="https://oracle.invalid/chat/completions",
        oracle_model="deepseek-v4-flash",
        oracle_snapshot_id="unknown",
        oracle_thinking="disabled",
        oracle_reasoning_effort=None,
        oracle_timeout_s=2.0,
        oracle_concurrency=None,
        oracle_api_key=None,
        oracle_api_key_stdin=False,
        oracle_prompt_api_key=False,
        oracle_api_key_env="ORACLE_API_KEY",
        evaluator_provider="deepseek",
        evaluator_endpoint="https://evaluator.invalid/chat/completions",
        evaluator_model="deepseek-v4-flash",
        evaluator_snapshot_id="unknown",
        evaluator_thinking="disabled",
        evaluator_reasoning_effort=None,
        evaluator_timeout_s=3.0,
        evaluator_concurrency=None,
        evaluator_api_key=None,
        evaluator_api_key_stdin=False,
        evaluator_prompt_api_key=False,
        evaluator_api_key_env="EVALUATOR_API_KEY",
        family=None,
        variant=None,
        condition=None,
        task_setting=None,
        evaluation_method=None,
        repeat=None,
        repeats=5,
        schedule_seed=DEFAULT_SCHEDULE_SEED,
        oracle_mode=DETERMINISTIC_ORACLE,
        player_max_output_tokens=8192,
        max_repair_attempts=1,
        oracle_max_output_tokens=256,
        evaluator_max_output_tokens=2048,
        max_actions=16,
        workers=1,
        dry_run=False,
    )


def _runtime_keys():
    return {
        "player_api_key": "player-secret",
        "oracle_api_key": "oracle-secret",
        "evaluator_api_key": "evaluator-secret",
    }


def _scientific_answer(request):
    projection = json.loads(request.messages[1].content)
    window = projection["understanding_window"]
    events = {event["sequence"]: event for event in projection["observable_transcript"]}
    def claim(endpoint):
        sequence = window[endpoint + "_sequence"]
        return _claim_text(events[sequence]["payload"]["action"])[0] if sequence is not None else None
    before, after = claim("before"), claim("after")
    items = [{"criterion_id": criterion["id"],
              "before_score": 0.5 if before else None, "after_score": 1 if after else None,
              "before_claim": before, "after_claim": after,
              "rationale": "Fixture rating of the same scientific question at both endpoints."}
             for criterion in projection["active_world_reference"]["understanding_criteria"]]
    return GenerationResponse(text=json.dumps({"understanding": {"items": items},
        "findings": [], "summary": "Independent scientific measurements."}),
        provider="fixture", model="judge", finish_reason="stop")


def _fake_evaluator_payload(spec):
    return {
        "schema": "role_benchmark.case_matrix_llm_evaluation",
        "episode_id": spec.episode_id,
        "run_id": spec.episode_id,
        "evaluator_profile": "evaluator",
        "evaluator_prompt_version": DISCOVERY_PROMPT_VERSION,
        "evaluator_provider": "test",
        "evaluator_model": "judge-model",
        "status": "evaluated",
        "started_at": "2026-08-25T00:00:00Z",
        "ended_at": "2026-08-25T00:00:01Z",
        "elapsed_s": 1.0,
        "request": {},
        "response": {},
        "evaluation": {
            "scores": {"understanding_before": None, "understanding_after": 0.5, "understanding_gain": None},
            "details": {"understanding": {"items": [], "before_score": None,
                "after_score": 0.5, "delta": None, "status": "final_only",
                "window": {}, "transitions": []}, "findings": []},
            "findings": [],
            "summary": "Observable process rating.",
        },
        "llm_stats": {
            "generation_calls": 1,
            "input_tokens": 10,
            "output_tokens": 5,
        },
        "error_type": None,
        "error_message": None,
    }


def _fake_run(
    spec,
    *,
    kind=TerminationKind.SUBMITTED,
    success=True,
):
    submitted = kind == TerminationKind.SUBMITTED
    code = {
        TerminationKind.SUBMITTED: "submitted",
        TerminationKind.PLAYER_OUTPUT_INVALID: "invalid_json",
        TerminationKind.ACTION_REJECTED: "action_rejected",
        TerminationKind.ACTION_LIMIT: "max_actions_reached",
    }[kind]
    final = (
        FinalSubmission(
            explanation="A fitted executable relationship.",
            model="fitted_model",
            parameters={"coefficient": 1.25},
            scope_conditions=("within the declared controls",),
        )
        if submitted
        else None
    )
    outcome = SimpleNamespace(
        case_id="public.case",
        termination=SimpleNamespace(kind=kind, code=code, message=code),
        active_pass=submitted and success,
        scientifically_evaluable=submitted,
        protocol_completed=submitted,
        evaluation=SimpleNamespace(
            success=submitted and success,
            message="passed" if submitted and success else "did not pass",
            scores=(
                {"predictive_model_pass": float(success)}
                if submitted
                else {"active_pass": 0.0}
            ),
        ),
        attempts_used=2,
        final_submission=final,
        trajectory_scores={"experiment_discriminativeness_mean": 1.5},
        protocol_violations=(),
    )
    return SimpleNamespace(
        run_id=spec.episode_id,
        outcome=outcome,
        llm_stats=None,
        oracle_llm_stats=None,
    )


def _evaluated_payload(spec, root, *, kind=TerminationKind.SUBMITTED, success=True):
    result = _evaluated_result(
        spec=spec,
        log_path=root / "episodes" / (spec.episode_id + ".jsonl"),
        output_dir=root,
        run=_fake_run(spec, kind=kind, success=success),
        started_at="2026-08-25T00:00:00Z",
        elapsed_s=1.0,
    )

    result["formula_consistency"] = {"status": "unavailable", "reason": "No symbolic formula in this runner fixture."}
    return result


class CaseMatrixExperimentTests(unittest.TestCase):
    def test_cli_requires_an_explicit_case_pack_release(self):
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                _parser().parse_args(["--output-dir", "unused", "--dry-run"])

    def test_registry_exposes_only_three_named_case_packs(self):
        self.assertEqual(
            tuple(CASE_PACKS),
            ("historical", "historical_v2", "temporal", "both"),
        )
        historical = CASE_PACKS["historical"]
        temporal = CASE_PACKS["temporal"]
        both = CASE_PACKS["both"]

        self.assertEqual(historical.families, HISTORICAL_CASE_FAMILIES)
        self.assertEqual(len(historical.families), 20)
        self.assertEqual(
            temporal.families,
            LEGACY_TEMPORAL_CASE_FAMILIES + ACCEPTED_TEMPORAL_CASE_FAMILIES,
        )
        self.assertEqual(len(LEGACY_TEMPORAL_CASE_FAMILIES), 9)
        self.assertEqual(len(ACCEPTED_TEMPORAL_CASE_FAMILIES), 21)
        self.assertEqual(
            ACCEPTED_TEMPORAL_CASE_FAMILIES[-1],
            "temporal_source_3047",
        )
        self.assertEqual(len(temporal.families), 30)
        self.assertEqual(both.families, BOTH_CASE_FAMILIES)
        self.assertEqual(
            both.families,
            HISTORICAL_CASE_FAMILIES + TEMPORAL_CASE_FAMILIES,
        )
        self.assertEqual(len(both.families), 50)
        self.assertEqual(len(set(both.families)), 50)

        paper_ids = tuple(temporal.source_paper_ids.values())
        version_ids = tuple(temporal.source_version_ids.values())
        arxiv_base_ids = tuple(
            re.sub(r"v[0-9]+$", "", version_id)
            for version_id in version_ids
        )
        self.assertEqual(len(paper_ids), 30)
        self.assertEqual(len(set(paper_ids)), 30)
        self.assertEqual(len(version_ids), 30)
        self.assertEqual(len(set(arxiv_base_ids)), 30)

        legacy_paper_ids = {
            family: temporal.source_paper_ids[family]
            for family in LEGACY_TEMPORAL_CASE_FAMILIES
        }
        accepted_paper_ids = {
            family: temporal.source_paper_ids[family]
            for family in ACCEPTED_TEMPORAL_CASE_FAMILIES
        }
        duplicated_paper_ids = dict(accepted_paper_ids)
        duplicated_paper_ids[ACCEPTED_TEMPORAL_CASE_FAMILIES[0]] = (
            legacy_paper_ids[LEGACY_TEMPORAL_CASE_FAMILIES[0]]
        )
        with self.assertRaisesRegex(ValueError, "source_paper_id values"):
            _merge_unique_temporal_identities(
                "source_paper_id",
                legacy_paper_ids,
                duplicated_paper_ids,
            )

        legacy_version_ids = {
            family: temporal.source_version_ids[family]
            for family in LEGACY_TEMPORAL_CASE_FAMILIES
        }
        accepted_version_ids = {
            family: temporal.source_version_ids[family]
            for family in ACCEPTED_TEMPORAL_CASE_FAMILIES
        }
        duplicated_version_ids = dict(accepted_version_ids)
        legacy_base_id = _arxiv_base_id(
            legacy_version_ids[LEGACY_TEMPORAL_CASE_FAMILIES[0]]
        )
        duplicated_version_ids[ACCEPTED_TEMPORAL_CASE_FAMILIES[0]] = (
            legacy_base_id + "v999"
        )
        with self.assertRaisesRegex(ValueError, "source_version_id values"):
            _merge_unique_temporal_identities(
                "source_version_id",
                legacy_version_ids,
                duplicated_version_ids,
                normalize=_arxiv_base_id,
            )

        for case_pack in CASE_PACKS:
            parsed = _parser().parse_args(
                [
                    "--output-dir",
                    "unused",
                    "--dry-run",
                    "--case-pack",
                    case_pack,
                ]
            )
            self.assertEqual(parsed.case_pack, case_pack)

        retired_names = (
            "curated",
            "temporal_counterfactual",
            "temporal_v1",
            "public_v1",
            "core160",
        )
        for case_pack in retired_names:
            with self.subTest(case_pack=case_pack):
                with contextlib.redirect_stderr(io.StringIO()):
                    with self.assertRaises(SystemExit):
                        _parser().parse_args(
                            [
                                "--output-dir",
                                "unused",
                                "--dry-run",
                                "--case-pack",
                                case_pack,
                            ]
                        )

    def test_three_case_pack_slices_have_expected_instances(self):
        method = EVALUATION_METHODS[0]
        expected = {
            "historical": (
                80,
                {"historical_counterfactual": 80},
                {"canonical_v1"},
            ),
            "temporal": (
                120,
                {"temporal": 36, "temporal_counterfactual": 84},
                {"source_reported_v1", CORE160_TEMPORAL_VARIANT_ID},
            ),
            "both": (
                200,
                {
                    "historical_counterfactual": 80,
                    "temporal": 36,
                    "temporal_counterfactual": 84,
                },
                {
                    "canonical_v1",
                    "source_reported_v1",
                    CORE160_TEMPORAL_VARIANT_ID,
                },
            ),
        }
        for pack_name, (count, dataset_counts, variants) in expected.items():
            pack = CASE_PACKS[pack_name]
            plan = build_plan(
                repeats=1,
                case_pack=pack_name,
                evaluation_methods=(method,),
            )
            with self.subTest(case_pack=pack_name):
                self.assertEqual(len(plan), count)
                self.assertEqual(
                    len({spec.benchmark_instance_id for spec in plan}),
                    count,
                )
                self.assertEqual(
                    Counter(spec.dataset_kind for spec in plan),
                    dataset_counts,
                )
                self.assertEqual(
                    Counter(spec.case_family for spec in plan),
                    {family: 4 for family in pack.families},
                )
                self.assertEqual({spec.variant_id for spec in plan}, variants)
                for spec in plan:
                    case = _make_case(spec)
                    self.assertIs(
                        case.definition.track,
                        BenchmarkTrack(spec.task_setting),
                    )

        historical = CASE_PACKS["historical"]
        for family in historical.families:
            self.assertIs(
                historical.specifications[family]["canonical_v1"],
                CASE_SPECS[family],
            )

        temporal = CASE_PACKS["temporal"]
        legacy_family = LEGACY_TEMPORAL_CASE_FAMILIES[0]
        legacy_cells = build_plan(
            families=(legacy_family,),
            repeats=1,
            case_pack="temporal",
            evaluation_methods=(method,),
        )
        self.assertEqual(
            {spec.variant_id for spec in legacy_cells},
            {"source_reported_v1"},
        )
        self.assertEqual(
            {spec.condition_role for spec in legacy_cells},
            {"source_reported"},
        )

        accepted_family = ACCEPTED_TEMPORAL_CASE_FAMILIES[0]
        accepted_cells = build_plan(
            families=(accepted_family,),
            repeats=1,
            case_pack="temporal",
            evaluation_methods=(method,),
        )
        self.assertEqual(
            dict(temporal.runtime_condition_ids[accepted_family]),
            {
                CORE160_TEMPORAL_SOURCE_CONDITION_ID: "historical",
                CORE160_TEMPORAL_COUNTERFACTUAL_CONDITION_ID: "counterfactual",
            },
        )
        self.assertEqual(
            {spec.condition_id for spec in accepted_cells},
            {
                CORE160_TEMPORAL_SOURCE_CONDITION_ID,
                CORE160_TEMPORAL_COUNTERFACTUAL_CONDITION_ID,
            },
        )
        for spec in accepted_cells:
            self.assertEqual(spec.dataset_kind, "temporal_counterfactual")
            self.assertEqual(
                spec.source_paper_id,
                temporal.source_paper_ids[accepted_family],
            )
            self.assertEqual(
                spec.source_version_id,
                temporal.source_version_ids[accepted_family],
            )
            if spec.condition_id == CORE160_TEMPORAL_SOURCE_CONDITION_ID:
                self.assertEqual(spec.condition_role, "source_reported")
                self.assertEqual(
                    spec.source_condition_id,
                    CORE160_TEMPORAL_SOURCE_RELATION_ID,
                )
            else:
                self.assertEqual(spec.condition_role, "counterfactual")
                self.assertIsNone(spec.source_condition_id)

    def test_temporal_pack_has_an_independent_complete_plan(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            args = _args(root)
            args.case_pack = "temporal"
            args.repeat = [1]
            args.dry_run = True
            with contextlib.redirect_stdout(io.StringIO()):
                results = run_matrix(args)

            self.assertEqual(results, [])
            config = json.loads((root / "config.json").read_text(encoding="utf-8"))
            self.assertEqual(config["design"]["case_pack"], "temporal")
            self.assertEqual(
                config["design"]["case_families"],
                list(TEMPORAL_CASE_FAMILIES),
            )
            cells_per_repeat = len(TEMPORAL_CASE_FAMILIES) * 4 * 3
            total_episodes = cells_per_repeat * 5
            self.assertEqual(
                config["design"]["cells_per_repeat"], cells_per_repeat
            )
            self.assertEqual(config["design"]["total_episodes"], total_episodes)
            self.assertEqual(
                config["schedule"]["block_sizes"], [cells_per_repeat] * 5
            )
            self.assertEqual(
                len(config["schedule"]["execution_order"]), total_episodes
            )
            temporal_conditions = config["design"]["condition_semantics"][
                TEMPORAL_CASE_FAMILIES[0]
            ]["source_reported_v1"]
            self.assertEqual(
                [item["condition_role"] for item in temporal_conditions],
                ["source_reported", "source_reported"],
            )
            self.assertIsNone(config["design"]["counterfactual_difficulty"])
            self.assertNotIn("worlds", config["design"])
            self.assertNotIn("tracks", config["design"])

    def test_cli_selectors_define_the_frozen_design(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            args = _args(root)
            args.family = ["pendulum"]
            args.variant = ["canonical_v1"]
            args.condition = ["counterfactual"]
            args.task_setting = ["discovery"]
            args.evaluation_method = [FIXED_EXPERIMENTAL_DESIGN]
            args.repeats = 2
            args.dry_run = True
            with contextlib.redirect_stdout(io.StringIO()):
                run_matrix(args)

            config = json.loads((root / "config.json").read_text(encoding="utf-8"))
            self.assertEqual(config["experiment_id"], "EXP-TEST-001")
            self.assertEqual(config["design"]["case_families"], ["pendulum"])
            self.assertEqual(config["design"]["task_settings"], ["discovery"])
            self.assertEqual(
                config["design"]["evaluation_methods"],
                [FIXED_EXPERIMENTAL_DESIGN],
            )
            self.assertEqual(config["design"]["total_episodes"], 2)

    def test_plan_has_exact_family_counts_and_repeat_blocks(self):
        plan = build_plan()
        cells_per_repeat = (
            len(HISTORICAL_CASE_FAMILIES)
            * len(HISTORICAL_CONDITION_IDS)
            * len(TASK_SETTINGS)
            * len(EVALUATION_METHODS)
        )
        total_episodes = cells_per_repeat * 5
        self.assertEqual(cells_per_repeat, 240)
        self.assertEqual(total_episodes, 1200)
        self.assertEqual(len(plan), total_episodes)
        self.assertEqual(len({spec.episode_id for spec in plan}), total_episodes)
        self.assertEqual(
            [spec.schedule_index for spec in plan],
            list(range(1, total_episodes + 1)),
        )
        self.assertEqual(
            [sum(spec.repeat == repeat for spec in plan) for repeat in range(1, 6)],
            [cells_per_repeat] * 5,
        )

        family_counts = Counter(spec.case_family for spec in plan)
        for family in HISTORICAL_CASE_FAMILIES:
            self.assertEqual(family_counts[family], 60)

        matched_cells = {
            (
                family,
                variant,
                condition,
                condition,
                task_setting,
                evaluation_method,
            )
            for family in HISTORICAL_CASE_FAMILIES
            for variant in ("canonical_v1",)
            for condition in HISTORICAL_CONDITION_IDS
            for task_setting in TASK_SETTINGS
            for evaluation_method in EVALUATION_METHODS
        }
        for repeat in range(1, 6):
            block = [spec for spec in plan if spec.repeat == repeat]
            self.assertEqual({spec.cell for spec in block}, matched_cells)
        self.assertTrue(
            all(left.cell != right.cell for left, right in zip(plan, plan[1:]))
        )

    def test_schedule_is_seeded_and_selection_preserves_order(self):
        first = build_plan(123)
        same = build_plan(123)
        different = build_plan(456)
        self.assertEqual(
            [spec.episode_id for spec in first],
            [spec.episode_id for spec in same],
        )
        self.assertNotEqual(
            [spec.episode_id for spec in first],
            [spec.episode_id for spec in different],
        )
        self.assertEqual(
            {spec.episode_id for spec in first},
            {spec.episode_id for spec in different},
        )
        selected = select_plan(
            first,
            families=["young_double_slit"],
            task_settings=["discovery"],
        )
        self.assertEqual(
            selected,
            [
                spec
                for spec in first
                if spec.case_family == "young_double_slit"
                and spec.task_setting == "discovery"
            ],
        )
        self.assertEqual(len(select_plan(first, repeats=[1])), 240)
        self.assertEqual(len(select_plan(first, repeats=[1, 2, 3])), 720)
        self.assertEqual(
            len(
                select_plan(
                    first,
                    evaluation_methods=[EVALUATION_METHODS[0]],
                )
            ),
            400,
        )

    def test_every_declared_cell_instantiates_through_the_generic_factory(self):
        unique = {}
        for spec in build_plan():
            unique.setdefault(spec.cell, spec)
        self.assertEqual(len(unique), 240)
        for spec in unique.values():
            with self.subTest(cell=spec.cell):
                case = _make_case(spec)
                self.assertIs(
                    case.definition.track,
                    BenchmarkTrack(spec.task_setting),
                )

    def test_backend_instances_are_independent_and_reuse_shared_transport(self):
        self.assertTrue(issubclass(CaseMatrixDeepSeekBackend, DeepSeekChatBackend))
        with tempfile.TemporaryDirectory() as directory:
            player, oracle, evaluator = load_backends(
                _args(directory),
                **_runtime_keys(),
            )
        self.assertIsInstance(player, OpenAIResponsesBackend)
        self.assertIsInstance(oracle, CaseMatrixDeepSeekBackend)
        self.assertIsInstance(evaluator, CaseMatrixDeepSeekBackend)
        self.assertEqual(len({id(player), id(oracle), id(evaluator)}), 3)
        self.assertEqual(player._api_key, "player-secret")
        self.assertEqual(oracle._api_key, "oracle-secret")
        self.assertEqual(evaluator._api_key, "evaluator-secret")
        self.assertEqual(player._model, "gpt-5.6")
        self.assertEqual(oracle._model, "deepseek-v4-flash")
        self.assertEqual(evaluator._model, "deepseek-v4-flash")
        self.assertEqual(player._reasoning_effort, "none")
        self.assertEqual(oracle._thinking, "disabled")
        self.assertEqual(evaluator._thinking, "disabled")

    def test_role_profiles_can_mix_providers_models_endpoints_and_credentials(self):
        with tempfile.TemporaryDirectory() as directory:
            args = _args(directory)
            args.oracle_provider = "openai"
            args.oracle_endpoint = None
            args.oracle_model = "gpt-5.6"
            args.oracle_thinking = None
            args.oracle_reasoning_effort = "none"
            args.oracle_api_key_env = None
            args.evaluator_provider = "openai"
            args.evaluator_endpoint = "https://judge.invalid/v1/responses"
            args.evaluator_model = "gpt-5.6-evaluator"
            args.evaluator_thinking = None
            args.evaluator_reasoning_effort = "high"
            runtime = _runtime_profile(args)
            player, oracle, evaluator = load_backends(args, **_runtime_keys())

        self.assertEqual(runtime.oracle.endpoint, OPENAI_ENDPOINT)
        self.assertEqual(runtime.oracle.api_key_env, OPENAI_API_KEY_ENV)
        self.assertEqual(runtime.player.model, "gpt-5.6")
        self.assertEqual(runtime.oracle.model, "gpt-5.6")
        self.assertEqual(runtime.evaluator.model, "gpt-5.6-evaluator")
        self.assertEqual(runtime.oracle.reasoning_effort, "none")
        self.assertEqual(runtime.evaluator.reasoning_effort, "high")
        self.assertIsInstance(player, OpenAIResponsesBackend)
        self.assertIsInstance(oracle, OpenAIResponsesBackend)
        self.assertIsInstance(evaluator, OpenAIResponsesBackend)
        self.assertEqual(len({id(player), id(oracle), id(evaluator)}), 3)
        self.assertEqual(player._model, "gpt-5.6")
        self.assertEqual(oracle._model, "gpt-5.6")
        self.assertEqual(oracle._reasoning_effort, "none")
        self.assertEqual(evaluator._model, "gpt-5.6-evaluator")
        self.assertEqual(evaluator._reasoning_effort, "high")
        self.assertEqual(player._api_key, "player-secret")
        self.assertEqual(oracle._api_key, "oracle-secret")
        self.assertEqual(evaluator._api_key, "evaluator-secret")

    def test_gemini_cli_defaults_to_native_model_endpoint_and_key_env(self):
        with tempfile.TemporaryDirectory() as directory:
            args = _parser().parse_args(
                [
                    "--output-dir",
                    directory,
                    "--case-pack",
                    "historical",
                    "--dry-run",
                    "--player-provider",
                    "gemini",
                ]
            )
            runtime = _runtime_profile(args).player

        self.assertEqual(runtime.provider, "gemini")
        self.assertEqual(runtime.model, GEMINI_MODEL)
        self.assertEqual(runtime.api_key_env, GEMINI_API_KEY_ENV)
        self.assertEqual(
            runtime.endpoint,
            GEMINI_ENDPOINT_TEMPLATE.format(model=GEMINI_MODEL),
        )
        self.assertEqual(runtime.api, "generate_content")
        self.assertEqual(runtime.response_format, "application/json")
        self.assertIsNone(runtime.thinking)
        self.assertIsNone(runtime.reasoning_effort)

    def test_ifm_cli_defaults_to_k2_horizon_and_api_key_env(self):
        with tempfile.TemporaryDirectory() as directory:
            args = _parser().parse_args(
                [
                    "--output-dir",
                    directory,
                    "--case-pack",
                    "historical_v2",
                    "--dry-run",
                    "--player-provider",
                    "ifm",
                ]
            )
            runtime = _runtime_profile(args).player
            backend = load_backends(args, **_runtime_keys())[0]

        self.assertEqual(runtime.provider, "ifm")
        self.assertEqual(runtime.model, DEFAULT_IFM_PLATFORM_MODEL)
        self.assertEqual(runtime.endpoint, DEFAULT_IFM_PLATFORM_ENDPOINT)
        self.assertEqual(runtime.api_key_env, IFM_API_KEY_ENV)
        self.assertEqual(runtime.api, "chat_completions")
        self.assertEqual(runtime.response_format, "native_json_schema_local_validation")
        self.assertEqual(runtime.reasoning_effort, "medium")
        self.assertIsNone(runtime.thinking)
        self.assertIsInstance(backend, IFMChatCompletionsBackend)
        self.assertEqual(backend._api_mode, "ifm_platform")
        self.assertEqual(_provider_payload(runtime)["api_mode"], "ifm_platform")
        self.assertTrue(backend.supports_strict_action_schema)

    def test_ifm_api_modes_select_the_matching_transport_contract(self):
        for mode, endpoint, model, auth_header, auth_value in (
            ("ifm_platform", DEFAULT_IFM_PLATFORM_ENDPOINT, DEFAULT_IFM_PLATFORM_MODEL,
             "authorization", "Bearer oracle-secret"),
            ("core42", DEFAULT_IFM_CHAT_COMPLETIONS_ENDPOINT, DEFAULT_IFM_MODEL,
             "api-key", "oracle-secret"),
        ):
            with self.subTest(mode=mode):
                args = _parser().parse_args([
                    "--output-dir", "unused", "--case-pack", "historical",
                    "--oracle-provider", "ifm", "--oracle-ifm-api-mode", mode,
                    "--oracle-reasoning-effort", "medium" if mode == "ifm_platform" else "minimal",
                ])
                runtime = _runtime_profile(args).oracle
                backend = load_backends(args, **_runtime_keys())[1]
                requests = []

                @contextlib.contextmanager
                def transport(request, timeout):
                    requests.append(request)
                    yield io.BytesIO(json.dumps({"model": model, "choices": [{
                        "message": {"content": "{}"}, "finish_reason": "stop",
                    }]}).encode())

                backend._urlopen = transport
                backend.generate(GenerationRequest(
                    messages=(Message("user", "Return JSON."),),
                    response_schema={"type": "object"}, config=GenerationConfig(),
                ))
                self.assertEqual(runtime.endpoint, endpoint)
                self.assertEqual(runtime.model, model)
                self.assertEqual(runtime.ifm_api_mode, mode)
                self.assertEqual(_provider_payload(runtime)["api_mode"], mode)
                self.assertEqual(requests[0].full_url, endpoint)
                headers = {key.lower(): value for key, value in requests[0].header_items()}
                self.assertEqual(headers[auth_header], auth_value)
                self.assertNotIn("api-key" if mode == "ifm_platform" else "authorization", headers)
                payload = json.loads(requests[0].data)
                self.assertEqual(payload["model"], model)
                if mode == "ifm_platform":
                    self.assertEqual(payload["chat_template_kwargs"], {"reasoning_effort": "medium"})
                    self.assertNotIn("reasoning_effort", payload)
                else:
                    self.assertEqual(payload["reasoning_effort"], "minimal")
                    self.assertNotIn("chat_template_kwargs", payload)

    def test_ifm_modes_can_mix_with_other_role_providers(self):
        args = _parser().parse_args([
            "--output-dir", "unused", "--case-pack", "historical",
            "--player-provider", "ifm", "--player-model", "platform-model",
            "--player-endpoint", "https://player.invalid/v1/chat/completions",
            "--oracle-provider", "openai",
            "--evaluator-provider", "ifm", "--evaluator-ifm-api-mode", "core42",
            "--evaluator-api-key-env", "JUDGE_IFM_KEY",
        ])
        runtime = _runtime_profile(args)
        player, oracle, evaluator = load_backends(args, **_runtime_keys())
        self.assertIsInstance(player, IFMChatCompletionsBackend)
        self.assertIsInstance(oracle, OpenAIResponsesBackend)
        self.assertIsInstance(evaluator, IFMChatCompletionsBackend)
        self.assertEqual(player._api_mode, "ifm_platform")
        self.assertEqual(player._model, "platform-model")
        self.assertEqual(player._endpoint, "https://player.invalid/v1/chat/completions")
        self.assertEqual(oracle._endpoint, OPENAI_ENDPOINT)
        self.assertEqual(evaluator._api_mode, "core42")
        self.assertEqual(evaluator._model, DEFAULT_IFM_MODEL)
        self.assertEqual(runtime.evaluator.api_key_env, "JUDGE_IFM_KEY")
        self.assertEqual(len({id(player), id(oracle), id(evaluator)}), 3)
        self.assertNotIn("secret", json.dumps(_provider_payload(runtime.player)))

    def test_current_player_schema_survives_concurrency_wrapper(self):
        from role_benchmark.structured_actions import structured_action_json_schema

        args = _parser().parse_args([
            "--output-dir", "unused", "--case-pack", "historical",
            "--player-provider", "ifm", "--workers", "2",
            "--max-repair-attempts", "0",
        ])
        runtime = _runtime_profile(args).player
        backend = load_backends(args, **_runtime_keys())[0]
        wrapped = ConcurrencyLimitedBackend(backend, role="player", concurrency_limit=2)
        self.assertEqual(runtime.response_format, "native_json_schema_local_validation")
        self.assertTrue(wrapped.supports_strict_action_schema)
        LLMPlayerBackend(wrapped, prompt_version=PLAYER_PROMPT_VERSION_V5_PERFORMANCE)
        requests = []

        @contextlib.contextmanager
        def transport(request, timeout):
            requests.append(json.loads(request.data))
            yield io.BytesIO(json.dumps({"model": DEFAULT_IFM_PLATFORM_MODEL, "choices": [{
                "message": {"content": "{}"}, "finish_reason": "stop",
            }]}).encode())

        backend._urlopen = transport
        schema = structured_action_json_schema()
        response = wrapped.generate(GenerationRequest(
            messages=(Message("user", "Choose an action."),),
            response_schema=schema, config=GenerationConfig(),
        ))
        self.assertEqual(requests[0]["response_format"], {"type": "json_schema", "json_schema": {
            "name": "role_benchmark_action", "strict": True, "schema": schema,
        }})
        self.assertTrue(response.metadata["provider_schema_enforced"])
        self.assertEqual(response.metadata["structured_output_transport"], runtime.response_format)

        args.player_ifm_api_mode = "core42"
        with self.assertRaisesRegex(ValueError, "structured Player requires IFM Platform"):
            _runtime_profile(args)
        prompt_only = ConcurrencyLimitedBackend(
            IFMChatCompletionsBackend(api_key="fixture", api_mode="core42"),
            role="player", concurrency_limit=2,
        )
        self.assertFalse(prompt_only.supports_strict_action_schema)
        with self.assertRaisesRegex(ValueError, "enforcing provider backend"):
            LLMPlayerBackend(prompt_only, prompt_version=PLAYER_PROMPT_VERSION_V5_PERFORMANCE)

    def test_existing_provider_default_payloads_do_not_acquire_ifm_settings(self):
        for provider, model, endpoint, api, response_format, binding_id in (
            ("deepseek", "deepseek-v4-flash", "https://api.deepseek.com/chat/completions",
             "chat_completions", "json_object", "case_matrix.deepseek_chat"),
            ("openai", "gpt-5.6", OPENAI_ENDPOINT,
             "responses", "responses_json_schema_strict", OpenAIResponsesBackend.binding_id),
            ("gemini", GEMINI_MODEL, GEMINI_ENDPOINT_TEMPLATE.format(model=GEMINI_MODEL),
             "generate_content", "application/json", "case_matrix.gemini_generate_content"),
        ):
            with self.subTest(provider=provider):
                args = _parser().parse_args([
                    "--output-dir", "unused", "--case-pack", "historical",
                    "--player-provider", provider,
                ])
                runtime = _runtime_profile(args).player
                expected = {"name": provider, "binding_id": binding_id, "endpoint": endpoint,
                            "api": api, "response_format": response_format, "timeout_s": 120.0}
                if provider == "openai":
                    expected.update({"store": False, "reasoning_context": "current_turn"})
                self.assertEqual(runtime.model, model)
                self.assertEqual(_provider_payload(runtime), expected)
                self.assertIsNone(runtime.ifm_api_mode)
                args.player_ifm_api_mode = "core42"
                with self.assertRaisesRegex(ValueError, "only defined for IFM"):
                    _runtime_profile(args)

    def test_gemini_role_backends_keep_models_endpoints_and_keys_independent(self):
        class StubBackend:
            supports_strict_action_schema = True

            def generate(self, request):
                raise AssertionError("this test must not make provider calls")

        with tempfile.TemporaryDirectory() as directory:
            args = _args(directory)
            settings = {
                "player": ("gemini-2.5-flash", None),
                "oracle": (
                    "gemini-2.5-pro",
                    "https://gateway.invalid/oracle:generateContent",
                ),
                "evaluator": ("tunedModels/my model", None),
            }
            for role, (model, endpoint) in settings.items():
                setattr(args, role + "_provider", "gemini")
                setattr(args, role + "_model", model)
                setattr(args, role + "_endpoint", endpoint)
                setattr(args, role + "_thinking", None)
                setattr(args, role + "_reasoning_effort", None)
                setattr(args, role + "_api_key_env", None)

            runtime = _runtime_profile(args)
            stubs = [StubBackend(), StubBackend(), StubBackend()]
            with mock.patch(
                "experiments.run_case_matrix.GeminiGenerateContentBackend",
                side_effect=stubs,
            ) as backend_class:
                player, oracle, evaluator = load_backends(
                    args,
                    **_runtime_keys(),
                )

        self.assertEqual(len({id(player), id(oracle), id(evaluator)}), 3)
        self.assertEqual(runtime.player.api_key_env, GEMINI_API_KEY_ENV)
        self.assertEqual(runtime.oracle.api_key_env, GEMINI_API_KEY_ENV)
        self.assertEqual(runtime.evaluator.api_key_env, GEMINI_API_KEY_ENV)
        self.assertEqual(
            runtime.player.endpoint,
            GEMINI_ENDPOINT_TEMPLATE.format(model="gemini-2.5-flash"),
        )
        self.assertEqual(
            runtime.oracle.endpoint,
            "https://gateway.invalid/oracle:generateContent",
        )
        self.assertEqual(
            runtime.evaluator.endpoint,
            GEMINI_ENDPOINT_TEMPLATE.format(
                model="tunedModels%2Fmy%20model"
            ),
        )
        self.assertEqual(
            backend_class.call_args_list,
            [
                mock.call(
                    endpoint=runtime.player.endpoint,
                    api_key="player-secret",
                    model="gemini-2.5-flash",
                    timeout_seconds=1.0,
                ),
                mock.call(
                    endpoint=runtime.oracle.endpoint,
                    api_key="oracle-secret",
                    model="gemini-2.5-pro",
                    timeout_seconds=2.0,
                ),
                mock.call(
                    endpoint=runtime.evaluator.endpoint,
                    api_key="evaluator-secret",
                    model="tunedModels/my model",
                    timeout_seconds=3.0,
                ),
            ],
        )

    def test_openai_config_records_effective_transport_without_credential(self):
        with tempfile.TemporaryDirectory() as directory:
            args = _args(directory)
            args.oracle_mode = LLM_PRESENTATION_ORACLE
            for role in ("player", "oracle", "evaluator"):
                setattr(args, role + "_provider", "openai")
                setattr(args, role + "_endpoint", None)
                setattr(args, role + "_model", "gpt-5.6-" + role)
                setattr(args, role + "_thinking", None)
                setattr(args, role + "_reasoning_effort", "none")
                setattr(args, role + "_api_key", role + "-runtime-secret")
            config = _config_payload(args, build_plan(args.schedule_seed))

        serialized = json.dumps(config)
        for role in ("player", "oracle", "evaluator"):
            self.assertNotIn(role + "-runtime-secret", serialized)
            self.assertEqual(config["providers"][role]["api"], "responses")
            self.assertEqual(
                config["providers"][role]["response_format"],
                "responses_json_schema_strict",
            )
            self.assertIs(config["providers"][role]["store"], False)
            self.assertEqual(
                config["design"][role + "_profile"]["model"],
                "gpt-5.6-" + role,
            )

    def test_config_and_output_never_persist_a_credential(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            args = _args(root)
            args.player_api_key = "player-secret-value"
            args.oracle_api_key = "oracle-secret-value"
            args.evaluator_api_key = "evaluator-secret-value"
            config = _config_payload(args, build_plan(args.schedule_seed))
            serialized = json.dumps(config)
            self.assertEqual(config["evaluator_generation"]["prompt_version"], DISCOVERY_PROMPT_VERSION)
            for secret in (
                args.player_api_key,
                args.oracle_api_key,
                args.evaluator_api_key,
            ):
                self.assertNotIn(secret, serialized)
            self.assertNotIn("api_key", serialized.lower())
            self.assertEqual(config["schedule"]["block_sizes"], [240] * 5)
            self.assertEqual(len(config["schedule"]["execution_order"]), 1200)
            prepare_output(root, config)
            stored = (root / "config.json").read_text(encoding="utf-8")
            for secret in (
                args.player_api_key,
                args.oracle_api_key,
                args.evaluator_api_key,
            ):
                self.assertNotIn(secret, stored)
            self.assertNotIn("api_key", stored.lower())

    def test_current_scientific_protocol_is_the_default_without_version_selectors(self):
        args = _parser().parse_args([
            "--output-dir", "unused", "--case-pack", "historical", "--dry-run",
            "--oracle-mode", LLM_PRESENTATION_ORACLE,
            "--oracle-prompt-version", ORACLE_PROMPT_VERSION_V2_JSON_HARDENED,
        ])
        config = _config_payload(args, build_plan(args.schedule_seed))
        self.assertEqual(config["metrics_protocol"], PERFORMANCE_PROTOCOL)
        self.assertEqual(config["player_generation"]["prompt_version"], PLAYER_PROMPT_VERSION_V5_PERFORMANCE)
        self.assertEqual(config["evaluator_generation"]["prompt_version"], DISCOVERY_PROMPT_VERSION)
        self.assertEqual(config["oracle_generation"]["prompt_version"], ORACLE_PROMPT_VERSION_V2_JSON_HARDENED)
        self.assertFalse(hasattr(args, "metrics_protocol"))
        self.assertFalse(hasattr(args, "player_prompt_version"))
        self.assertFalse(hasattr(args, "evaluator_prompt_version"))

    def test_parallel_cli_records_episode_and_role_concurrency_semantics(self):
        with tempfile.TemporaryDirectory() as directory:
            args = _parser().parse_args(
                [
                    "--output-dir",
                    directory,
                    "--case-pack",
                    "historical",
                    "--dry-run",
                    "--workers",
                    "4",
                    "--player-concurrency",
                    "2",
                    "--oracle-concurrency",
                    "3",
                    "--evaluator-concurrency",
                    "1",
                ]
            )
            config = _config_payload(args, build_plan(args.schedule_seed))
            args.oracle_mode = LLM_PRESENTATION_ORACLE
            llm_oracle_config = _config_payload(
                args, build_plan(args.schedule_seed)
            )

        execution = config["execution"]
        self.assertEqual(execution["workers"], 4)
        self.assertEqual(execution["parallelism_scope"], "independent_episodes")
        self.assertEqual(
            execution["role_concurrency_limits"],
            {"player": 2, "oracle": 0, "evaluator": 1},
        )
        self.assertEqual(execution["deterministic_oracle_llm_calls"], 0)
        self.assertIn(
            "player_oracle_turns_sequential", execution["episode_causality"]
        )
        self.assertIn("completion_order_unconstrained", execution["order_guarantee"])
        self.assertIn("out_of_order_sidecars", execution["resume_policy"])
        self.assertEqual(
            llm_oracle_config["execution"]["role_concurrency_limits"]["oracle"],
            3,
        )

    def test_role_backend_concurrency_limit_is_thread_safe(self):
        class TrackingBackend:
            def __init__(self):
                self.active = 0
                self.peak = 0
                self.lock = threading.Lock()

            def generate(self, request):
                with self.lock:
                    self.active += 1
                    self.peak = max(self.peak, self.active)
                try:
                    time.sleep(0.02)
                    return request
                finally:
                    with self.lock:
                        self.active -= 1

        raw = TrackingBackend()
        limited = ConcurrencyLimitedBackend(
            raw,
            role="player",
            concurrency_limit=2,
        )
        with ThreadPoolExecutor(max_workers=6) as executor:
            responses = list(executor.map(limited.generate, range(12)))

        self.assertEqual(responses, list(range(12)))
        self.assertEqual(raw.peak, 2)

    def test_parallel_episodes_finish_out_of_order_but_evaluate_after_sidecar(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            args = _args(root)
            args.family = ["pendulum"]
            args.workers = 3
            args.player_concurrency = 2
            args.evaluator_concurrency = 1
            specs = build_plan(families=("pendulum",))[:3]
            barrier = threading.Barrier(3)
            release_second = threading.Event()
            release_first = threading.Event()
            finish_order = []
            player_wrappers = set()
            evaluator_wrappers = set()
            observation_lock = threading.Lock()

            def active(*unused_args, **kwargs):
                spec = kwargs["spec"]
                with observation_lock:
                    player_wrappers.add(id(kwargs["player_backend"]))
                barrier.wait(timeout=2.0)
                if spec.schedule_index == 3:
                    with observation_lock:
                        finish_order.append(spec.schedule_index)
                    release_second.set()
                elif spec.schedule_index == 2:
                    self.assertTrue(release_second.wait(timeout=2.0))
                    with observation_lock:
                        finish_order.append(spec.schedule_index)
                    release_first.set()
                else:
                    self.assertTrue(release_first.wait(timeout=2.0))
                    with observation_lock:
                        finish_order.append(spec.schedule_index)
                return _evaluated_payload(spec, root)

            def evaluate(*unused_args, **kwargs):
                spec = kwargs["spec"]
                result_path = root / "results" / (spec.episode_id + ".result.json")
                self.assertTrue(result_path.exists())
                self.assertEqual(
                    json.loads(result_path.read_text(encoding="utf-8"))["status"],
                    "evaluated",
                )
                with observation_lock:
                    evaluator_wrappers.add(id(kwargs["evaluator_backend"]))
                return _fake_evaluator_payload(spec)

            oracle_loader = mock.Mock(
                side_effect=AssertionError("deterministic Oracle must not load an API")
            )
            with mock.patch(
                "experiments.run_case_matrix.select_plan", return_value=specs
            ), mock.patch(
                "experiments.run_case_matrix._run_one_episode", side_effect=active
            ), mock.patch(
                "experiments.run_case_matrix._run_evaluator", side_effect=evaluate
            ), contextlib.redirect_stdout(io.StringIO()):
                results = run_matrix(
                    args,
                    oracle_backend_loader=oracle_loader,
                    **_runtime_keys(),
                )

            oracle_loader.assert_not_called()
            self.assertEqual(finish_order, [3, 2, 1])
            self.assertEqual(len(player_wrappers), 1)
            self.assertEqual(len(evaluator_wrappers), 1)
            self.assertTrue(player_wrappers.isdisjoint(evaluator_wrappers))
            self.assertEqual(
                [result["schedule_index"] for result in results],
                [1, 2, 3],
            )
            summary = json.loads(
                (root / "episodes.json").read_text(encoding="utf-8")
            )
            self.assertEqual(
                [item["schedule_index"] for item in summary["episodes"]],
                [1, 2, 3],
            )

    def test_parallel_resume_accepts_gap_and_retries_only_missing_stages(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            args = _args(root)
            args.family = ["pendulum"]
            args.workers = 3
            args.player_concurrency = 2
            args.evaluator_concurrency = 1
            plan = build_plan(families=("pendulum",))
            specs = plan[:4]
            prepare_output(root, _config_payload(args, plan))

            for spec in (specs[0], specs[3]):
                path = root / "results" / (spec.episode_id + ".result.json")
                path.write_text(
                    json.dumps(_evaluated_payload(spec, root)),
                    encoding="utf-8",
                )
            failed_active = _infrastructure_failed_result(
                spec=specs[2],
                log_path=root / "episodes" / (specs[2].episode_id + ".jsonl"),
                output_dir=root,
                exc=RuntimeError("temporary player failure"),
                started_at="2026-08-25T00:00:00Z",
                elapsed_s=1.0,
            )
            (
                root / "results" / (specs[2].episode_id + ".result.json")
            ).write_text(json.dumps(failed_active), encoding="utf-8")
            first_evaluation = _fake_evaluator_payload(specs[0])
            (
                root
                / "evaluations"
                / (specs[0].episode_id + ".evaluation.json")
            ).write_text(
                json.dumps(first_evaluation),
                encoding="utf-8",
            )
            failed_evaluation = _fake_evaluator_payload(specs[3])
            failed_evaluation.update(
                {
                    "status": "infrastructure_failed",
                    "evaluation": None,
                    "error_type": "RuntimeError",
                    "error_message": "temporary evaluator failure",
                }
            )
            (
                root
                / "evaluations"
                / (specs[3].episode_id + ".evaluation.json")
            ).write_text(
                json.dumps(failed_evaluation),
                encoding="utf-8",
            )

            active_calls = []
            evaluator_calls = []

            def active(*unused_args, **kwargs):
                active_calls.append(kwargs["spec"].episode_id)
                return _evaluated_payload(kwargs["spec"], root)

            def evaluate(*unused_args, **kwargs):
                evaluator_calls.append(kwargs["spec"].episode_id)
                return _fake_evaluator_payload(kwargs["spec"])

            with mock.patch(
                "experiments.run_case_matrix.select_plan", return_value=specs
            ), mock.patch(
                "experiments.run_case_matrix._run_one_episode", side_effect=active
            ), mock.patch(
                "experiments.run_case_matrix._run_evaluator", side_effect=evaluate
            ), contextlib.redirect_stdout(io.StringIO()):
                results = run_matrix(args, **_runtime_keys())

            self.assertEqual(
                set(active_calls),
                {specs[1].episode_id, specs[2].episode_id},
            )
            self.assertEqual(
                set(evaluator_calls),
                {
                    specs[1].episode_id,
                    specs[2].episode_id,
                    specs[3].episode_id,
                },
            )
            self.assertNotIn(specs[0].episode_id, evaluator_calls)
            self.assertEqual(
                [result["schedule_index"] for result in results],
                [1, 2, 3, 4],
            )

    def test_evaluated_sidecar_keeps_family_and_final_relationship(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            (root / "episodes").mkdir()
            spec = build_plan()[0]
            result = _evaluated_payload(spec, root)
            self.assertEqual(result["schema"], EPISODE_RESULT_SCHEMA)
            self.assertEqual(result["case_family"], spec.case_family)
            self.assertEqual(result["case_id"], "public.case")
            self.assertEqual(result["status"], "evaluated")
            self.assertEqual(result["active_pass_category"], "pass")
            self.assertEqual(result["final_submission"]["model"], "fitted_model")
            self.assertEqual(
                result["final_submission"]["parameters"],
                {"coefficient": 1.25},
            )

            player_failure = _evaluated_payload(
                spec,
                root,
                kind=TerminationKind.PLAYER_OUTPUT_INVALID,
            )
            self.assertEqual(player_failure["status"], "evaluated")
            self.assertEqual(
                player_failure["active_pass_category"],
                "player_generation_failure",
            )
            self.assertIsNone(player_failure["final_submission"])

    def test_adaptive_dispatch_has_no_observation_or_action_limit(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            (root / "episodes").mkdir()
            args = _args(root)
            spec = next(item for item in build_plan()
                        if item.evaluation_method == ADAPTIVE_EXPERIMENTAL_DESIGN)
            with mock.patch("experiments.run_case_matrix.run_llm_episode",
                            return_value=_fake_run(spec)) as run:
                result = _run_one_episode(
                    args, player_backend=SimpleNamespace(generate=mock.Mock()),
                    oracle_backend=None, output_dir=root, spec=spec,
                    log_path=root / "episodes" / (spec.episode_id + ".jsonl"),
                )
        keyword = run.call_args.kwargs
        self.assertIsNone(run.call_args.args[1].definition.budget)
        self.assertIsNone(keyword["observation_budget"])
        self.assertIsNone(keyword["max_actions"])
        self.assertFalse(keyword["require_budget_exhaustion"])
        self.assertEqual(keyword["initial_attempts_used"], 0)
        self.assertIsNone(result["observation_budget"])

    def test_fixed_method_dispatches_frozen_observations_through_same_runner(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            (root / "episodes").mkdir()
            args = _args(root)
            spec = next(
                item
                for item in build_plan()
                if item.evaluation_method == FIXED_EXPERIMENTAL_DESIGN
            )
            with mock.patch(
                "experiments.run_case_matrix.run_llm_episode",
                return_value=_fake_run(spec),
            ) as run:
                result = _run_one_episode(
                    args,
                    player_backend=SimpleNamespace(generate=mock.Mock()),
                    oracle_backend=None,
                    output_dir=root,
                    spec=spec,
                    log_path=root / "episodes" / (spec.episode_id + ".jsonl"),
                )

        positional = run.call_args.args
        keyword = run.call_args.kwargs
        budget = keyword["observation_budget"]
        self.assertEqual(spec.evaluation_method, result["evaluation_method"])
        self.assertEqual(result["observation_budget"], budget)
        self.assertEqual(keyword["initial_attempts_used"], budget)
        self.assertIs(keyword["require_budget_exhaustion"], True)
        self.assertEqual(
            len(keyword["run_metadata"]["fixed_observations"]),
            budget,
        )
        self.assertEqual(
            keyword["run_metadata"]["evaluation_method"],
            FIXED_EXPERIMENTAL_DESIGN,
        )
        self.assertIsNone(keyword["oracle_backend"])
        self.assertIsNone(keyword["oracle_config"])
        self.assertEqual(
            keyword["player_prompt_version"], PLAYER_PROMPT_VERSION_V5_PERFORMANCE
        )
        self.assertEqual(
            keyword["oracle_prompt_version"], DEFAULT_ORACLE_PROMPT_VERSION
        )
        self.assertEqual(result["oracle_mode"], DETERMINISTIC_ORACLE)
        self.assertEqual(result["oracle_provider"], "deterministic")
        self.assertNotIn("world", keyword["run_metadata"])
        self.assertNotIn("track", keyword["run_metadata"])
        self.assertGreaterEqual(positional[1].definition.budget, budget)

    def test_llm_presentation_oracle_is_an_explicit_optional_mode(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            (root / "episodes").mkdir()
            args = _args(root)
            args.oracle_mode = LLM_PRESENTATION_ORACLE
            args.oracle_prompt_version = (
                ORACLE_PROMPT_VERSION_V2_JSON_HARDENED
            )
            spec = build_plan()[0]
            oracle_backend = SimpleNamespace(generate=mock.Mock())
            with mock.patch(
                "experiments.run_case_matrix.run_llm_episode",
                return_value=_fake_run(spec),
            ) as run:
                result = _run_one_episode(
                    args,
                    player_backend=SimpleNamespace(generate=mock.Mock()),
                    oracle_backend=oracle_backend,
                    output_dir=root,
                    spec=spec,
                    log_path=root / "episodes" / (spec.episode_id + ".jsonl"),
                )

        self.assertIs(run.call_args.kwargs["oracle_backend"], oracle_backend)
        self.assertIsNotNone(run.call_args.kwargs["oracle_config"])
        self.assertEqual(
            run.call_args.kwargs["player_prompt_version"],
            PLAYER_PROMPT_VERSION_V5_PERFORMANCE,
        )
        self.assertEqual(
            run.call_args.kwargs["oracle_prompt_version"],
            ORACLE_PROMPT_VERSION_V2_JSON_HARDENED,
        )
        self.assertEqual(result["oracle_mode"], LLM_PRESENTATION_ORACLE)
        self.assertEqual(result["oracle_provider"], "deepseek")

    def test_repeat_one_dispatches_all_method_cells_and_player_failures_continue(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            args = _args(root)
            args.family = ["pendulum"]
            args.repeat = [1]
            observed = []

            def fake_run_one(*unused_args, **kwargs):
                spec = kwargs["spec"]
                observed.append(spec.episode_id)
                kind = (
                    TerminationKind.PLAYER_OUTPUT_INVALID
                    if len(observed) == 1
                    else TerminationKind.SUBMITTED
                )
                return _evaluated_payload(spec, root, kind=kind)

            with mock.patch(
                "experiments.run_case_matrix._run_one_episode",
                side_effect=fake_run_one,
            ), mock.patch(
                "experiments.run_case_matrix._run_evaluator",
                side_effect=lambda *unused_args, **kwargs: _fake_evaluator_payload(
                    kwargs["spec"]
                ),
            ), contextlib.redirect_stdout(io.StringIO()):
                results = run_matrix(args, **_runtime_keys())

            selected = select_plan(
                build_plan(families=("pendulum",)), repeats=[1]
            )
            self.assertEqual(observed, [spec.episode_id for spec in selected])
            self.assertEqual(len(observed), 12)
            first = next(
                result for result in results if result["episode_id"] == observed[0]
            )
            self.assertEqual(first["status"], "evaluated")
            self.assertEqual(
                first["active_pass_category"],
                "player_generation_failure",
            )

    def test_nonprefix_selection_is_rejected_before_backend_loading(self):
        with tempfile.TemporaryDirectory() as directory:
            args = _args(directory)
            args.repeat = [4]
            with mock.patch("experiments.run_case_matrix.load_backends") as load:
                with self.assertRaisesRegex(ValueError, "prefix"):
                    run_matrix(args, **_runtime_keys())
            load.assert_not_called()

    def test_infrastructure_failure_is_retried_at_the_same_cell(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            args = _args(root)
            args.family = ["pendulum"]
            args.repeat = [1]
            first_spec = select_plan(
                build_plan(families=("pendulum",)), repeats=[1]
            )[0]

            def fail(*unused_args, **kwargs):
                kwargs["log_path"].write_text("failed\n", encoding="utf-8")
                return _infrastructure_failed_result(
                    spec=kwargs["spec"],
                    log_path=kwargs["log_path"],
                    output_dir=root,
                    exc=RuntimeError("provider unavailable"),
                    started_at="2026-08-25T00:00:00Z",
                    elapsed_s=1.0,
                )

            with mock.patch(
                "experiments.run_case_matrix._run_one_episode", side_effect=fail
            ), contextlib.redirect_stdout(io.StringIO()):
                with self.assertRaisesRegex(RuntimeError, "infrastructure failure"):
                    run_matrix(args, **_runtime_keys())

            resumed = []

            def succeed(*unused_args, **kwargs):
                resumed.append((kwargs["spec"].episode_id, kwargs["log_path"].name))
                return _evaluated_payload(kwargs["spec"], root)

            with mock.patch(
                "experiments.run_case_matrix._run_one_episode",
                side_effect=succeed,
            ), mock.patch(
                "experiments.run_case_matrix._run_evaluator",
                side_effect=lambda *unused_args, **kwargs: _fake_evaluator_payload(
                    kwargs["spec"]
                ),
            ), contextlib.redirect_stdout(io.StringIO()):
                run_matrix(args, **_runtime_keys())

            self.assertEqual(resumed[0][0], first_spec.episode_id)
            self.assertEqual(
                resumed[0][1], first_spec.episode_id + ".resume-1.jsonl"
            )
            stored = json.loads(
                (
                    root
                    / "results"
                    / (first_spec.episode_id + ".result.json")
                ).read_text(encoding="utf-8")
            )
            self.assertEqual(stored["status"], "evaluated")

    def test_evaluator_failure_retries_only_evaluator(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            args = _args(root)
            first_spec = build_plan()[0]
            active_calls = []

            def active(*unused_args, **kwargs):
                active_calls.append(kwargs["spec"].episode_id)
                return _evaluated_payload(kwargs["spec"], root)

            failed_evaluator = _fake_evaluator_payload(first_spec)
            failed_evaluator.update(
                {
                    "status": "infrastructure_failed",
                    "evaluation": None,
                    "llm_stats": None,
                    "error_type": "RuntimeError",
                    "error_message": "post-hoc evaluator call or decoding failed",
                }
            )
            with mock.patch(
                "experiments.run_case_matrix.select_plan",
                return_value=[first_spec],
            ), mock.patch(
                "experiments.run_case_matrix._run_one_episode", side_effect=active
            ), mock.patch(
                "experiments.run_case_matrix._run_evaluator",
                return_value=failed_evaluator,
            ), contextlib.redirect_stdout(io.StringIO()):
                with self.assertRaisesRegex(RuntimeError, "evaluator failure"):
                    run_matrix(args, **_runtime_keys())

            stored_active = json.loads(
                (root / "results" / (first_spec.episode_id + ".result.json")).read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(stored_active["status"], "evaluated")
            self.assertEqual(active_calls, [first_spec.episode_id])

            player_loader = mock.Mock(
                side_effect=AssertionError("Player backend must not be loaded")
            )
            oracle_loader = mock.Mock(
                side_effect=AssertionError("Oracle backend must not be loaded")
            )
            evaluator_loader = mock.Mock(
                return_value=SimpleNamespace(generate=mock.Mock())
            )
            with mock.patch(
                "experiments.run_case_matrix.select_plan",
                return_value=[first_spec],
            ), mock.patch(
                "experiments.run_case_matrix._run_one_episode"
            ) as rerun_active, mock.patch(
                "experiments.run_case_matrix._run_evaluator",
                return_value=_fake_evaluator_payload(first_spec),
            ), mock.patch(
                "experiments.run_case_matrix._resolve_api_key"
            ) as resolve_key, contextlib.redirect_stdout(io.StringIO()):
                results = run_matrix(
                    args,
                    player_backend_loader=player_loader,
                    oracle_backend_loader=oracle_loader,
                    evaluator_backend_loader=evaluator_loader,
                )

            rerun_active.assert_not_called()
            player_loader.assert_not_called()
            oracle_loader.assert_not_called()
            evaluator_loader.assert_called_once_with()
            resolve_key.assert_not_called()
            self.assertEqual(results[0]["status"], "evaluated")
            self.assertEqual(results[0]["llm_evaluation_status"], "evaluated")
            self.assertEqual(results[0]["scores"]["predictive_model_pass"], 1.0)
            self.assertNotIn("predictive_model_pass", results[0]["llm_evaluation"]["scores"])

    def test_invalid_evaluator_output_is_preserved_for_replay(self):
        class InvalidEvaluatorBackend:
            def generate(self, request):
                return GenerationResponse(
                    text="not-json",
                    provider="test",
                    model="judge-model",
                    usage=TokenUsage(input_tokens=7, output_tokens=2),
                )

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            (root / "episodes").mkdir()
            spec = build_plan()[0]
            log_path = root / "episodes" / (spec.episode_id + ".jsonl")
            with JSONLRunLog(str(log_path), run_id=spec.episode_id) as writer:
                writer.append("run.started", {"case": {"case_id": _make_case(spec).definition.case_id}})
                writer.append("run.ended", {"status": "evaluated"})
            result = _run_evaluator(
                _args(root),
                evaluator_backend=InvalidEvaluatorBackend(),
                output_dir=root,
                spec=spec,
                episode_result={
                    "run_id": spec.episode_id,
                    "log_path": str(log_path.relative_to(root)),
                },
            )

        self.assertEqual(result["status"], "infrastructure_failed")
        self.assertEqual(result["error_type"], "LLMEvaluatorOutputError")
        self.assertIsNotNone(result["request"])
        self.assertEqual(result["evaluator_prompt_version"], DISCOVERY_PROMPT_VERSION)
        self.assertEqual(result["request"]["metadata"]["prompt_version"], DISCOVERY_PROMPT_VERSION)
        self.assertEqual(result["response"]["text"], "not-json")
        self.assertEqual(result["llm_stats"]["input_tokens"], 7)
        self.assertEqual(result["llm_stats"]["output_tokens"], 2)

    def test_evaluator_transport_status_is_preserved_without_response_body(self):
        class RateLimitedEvaluatorBackend:
            def generate(self, request):
                raise ProviderTransportError(http_status=429)

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            (root / "episodes").mkdir()
            spec = build_plan()[0]
            log_path = root / "episodes" / (spec.episode_id + ".jsonl")
            with JSONLRunLog(str(log_path), run_id=spec.episode_id) as writer:
                writer.append("run.started", {"case": {"case_id": _make_case(spec).definition.case_id}})
                writer.append("run.ended", {"status": "evaluated"})
            result = _run_evaluator(
                _args(root),
                evaluator_backend=RateLimitedEvaluatorBackend(),
                output_dir=root,
                spec=spec,
                episode_result={
                    "run_id": spec.episode_id,
                    "log_path": str(log_path.relative_to(root)),
                },
            )

        self.assertEqual(result["status"], "infrastructure_failed")
        self.assertEqual(result["error_type"], "LLMEvaluatorTransportError")
        self.assertEqual(
            result["error_message"],
            "LLM evaluator backend failed: provider HTTP status 429",
        )
        self.assertIsNotNone(result["request"])
        self.assertIsNone(result["response"])
        self.assertIsNone(result["llm_stats"])



    def test_summaries_include_family_and_final_parameters(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            args = _args(root)
            prepare_output(root, _config_payload(args, build_plan()))
            spec = build_plan()[0]
            payload = _evaluated_payload(spec, root)
            result_path = root / "results" / (spec.episode_id + ".result.json")
            result_path.write_text(json.dumps(payload), encoding="utf-8")
            results = write_summaries(root)
            self.assertEqual(len(results), 1)
            summary = json.loads((root / "episodes.json").read_text(encoding="utf-8"))
            self.assertEqual(summary["schema"], EXPERIMENT_SCHEMA)
            csv_text = (root / "episodes.csv").read_text(encoding="utf-8")
            self.assertIn("case_family", csv_text)
            self.assertIn("final_parameters_json", csv_text)
            self.assertIn("coefficient", csv_text)

    def test_all_runtime_credential_modes_are_supported(self):
        with tempfile.TemporaryDirectory() as directory:
            args = _args(directory)
            args.player_api_key = "direct-player"
            args.oracle_api_key_stdin = True
            args.evaluator_prompt_api_key = True
            with mock.patch("sys.stdin", io.StringIO("stdin-oracle\n")), mock.patch(
                "getpass.getpass", return_value="prompt-evaluator"
            ):
                keys = _resolve_api_keys(args)
            self.assertEqual(
                keys,
                {
                    "player": "direct-player",
                    "oracle": "stdin-oracle",
                    "evaluator": "prompt-evaluator",
                },
            )

            for role in ("player", "oracle", "evaluator"):
                setattr(args, role + "_provider", "openai")
                setattr(args, role + "_thinking", None)
                setattr(args, role + "_reasoning_effort", "none")
                setattr(args, role + "_api_key", None)
                setattr(args, role + "_api_key_stdin", False)
                setattr(args, role + "_prompt_api_key", False)
                setattr(args, role + "_api_key_env", None)
            with mock.patch.dict(
                "os.environ", {OPENAI_API_KEY_ENV: "shared-openai-env"}
            ):
                self.assertEqual(
                    _resolve_api_key(args, "evaluator"), "shared-openai-env"
                )

    def test_dry_run_does_not_resolve_a_credential(self):
        with tempfile.TemporaryDirectory() as directory:
            with mock.patch(
                "experiments.run_case_matrix._resolve_api_key"
            ) as resolve, contextlib.redirect_stdout(io.StringIO()):
                status = main(
                    [
                        "--output-dir",
                        directory,
                        "--case-pack",
                        "historical",
                        "--dry-run",
                    ]
                )
            self.assertEqual(status, 0)
            resolve.assert_not_called()


if __name__ == "__main__":
    unittest.main()
