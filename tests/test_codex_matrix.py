"""Codex transport identity and unsupported controls survive matrix execution."""

import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest import mock

from experiments import run_case_matrix as matrix
from role_benchmark import GenerationResponse
from role_benchmark.structured_actions import structured_action_to_payload
import test_postevaluation_pipeline as pipeline_fixtures
import test_unlimited_adaptive as action_fixtures


def codex_args(directory, *extra):
    return matrix._parser().parse_args([
        "--case-pack", "both", "--output-dir", str(directory),
        "--player-provider", "codex", "--evaluator-provider", "codex",
        "--repeats", "1", "--workers", "4", *extra,
    ])


class CodexMatrixTests(unittest.TestCase):
    def test_full_plan_and_frozen_config_distinguish_actual_and_requested_controls(self):
        with tempfile.TemporaryDirectory() as directory, contextlib.redirect_stdout(io.StringIO()):
            args = codex_args(directory, "--dry-run")
            with mock.patch.object(matrix, "_resolve_api_key", side_effect=AssertionError("no key")), \
                    mock.patch.object(matrix, "load_role_backend", side_effect=AssertionError("no backend")):
                self.assertEqual(matrix.run_matrix(args), [])
            config = json.loads((Path(directory) / "config.json").read_text())
            self.assertEqual(config["design"]["total_episodes"], 1060)
            self.assertIn('fixed_budget_design', config)
            self.assertIn('reaches or exceeds threshold',
                          config['design']['observation_budget_policy'][matrix.ADAPTIVE_EXPERIMENTAL_DESIGN])
            for family, variants in config['design']['fixed_experimental_designs'].items():
                for fixed_plans in variants.values():
                    self.assertEqual(set(fixed_plans), {
                        'fixed experimental design (2 observations)',
                        'fixed experimental design (4 observations)',
                        'fixed experimental design (8 observations)',
                    })
                    for method, fixed_plan in fixed_plans.items():
                        budget = config['design']['observation_budget_policy'][method]
                        self.assertEqual(fixed_plan['observation_budget'], budget)
                        self.assertEqual(len(fixed_plan['fixed_experiments']), budget)
                        self.assertEqual(
                            [proposal['controls'] for proposal in fixed_plan['fixed_experiments']],
                            config['fixed_budget_design']['families'][family]['conditions'][:budget],
                        )
            self.assertEqual(config["execution"]["workers"], 4)
            for role in ("player", "evaluator"):
                provider = config["providers"][role]
                self.assertEqual(provider["name"], "codex")
                self.assertEqual(provider["api"], "app_server_jsonrpc")
                self.assertEqual(provider["endpoint"], "stdio://codex-app-server")
                self.assertEqual(provider["binding_id"], "case_matrix.codex_app_server")
                generation = config[role + "_generation"]
                self.assertEqual(generation["requested_generation"]["temperature"], 0.0)
                self.assertGreater(generation["requested_generation"]["max_output_tokens"], 0)
                for field in ("temperature", "top_p", "max_output_tokens", "seed"):
                    self.assertIsNone(generation[field])
                    self.assertIsNone(generation["actual_generation"][field])
                    self.assertFalse(generation["enforced"][field])
            self.assertEqual(config["oracle_generation"]["llm_calls"], 0)
            self.assertNotIn("requested_generation", config["oracle_generation"])
            runtime = matrix._runtime_profile(args).player
            self.assertEqual(runtime.model, "gpt-5.5")
            self.assertEqual(runtime.reasoning_effort, "high")

    def test_codex_constructs_independent_roles_without_api_credentials(self):
        with tempfile.TemporaryDirectory() as directory:
            args = codex_args(directory, "--oracle-provider", "codex",
                              "--oracle-mode", "llm_presentation", "--player-timeout-s", "900")
            constructor = mock.Mock(side_effect=lambda **kwargs: mock.Mock(supports_strict_action_schema=True))
            module = types.ModuleType("experiments.codex_structured_backend")
            module.CodexStructuredBackend = constructor
            with mock.patch.dict(sys.modules, {module.__name__: module}), \
                    mock.patch.object(matrix, "_resolve_api_key", side_effect=AssertionError("no key")):
                backends = []
                for role in matrix.ROLES:
                    self.assertIsNone(matrix._key_for_backend(args, role, None, None))
                    backends.append(matrix.load_role_backend(args, role))
            self.assertEqual(len({id(backend) for backend in backends}), 3)
            self.assertEqual(constructor.call_args_list[0].kwargs, {
                "model": "gpt-5.5", "reasoning_effort": "high", "timeout_s": 900.0,
                "audit_dir": Path(directory).resolve() / "codex_calls", "role": "player",
            })
            config = matrix._config_payload(args, matrix.build_plan(case_pack="both", repeats=1))
            self.assertIsNone(config["oracle_generation"]["max_output_tokens"])

    def test_codex_rejects_misleading_endpoint_and_api_credentials(self):
        for options in (("--player-endpoint", "https://example.invalid/responses"),
                        ("--player-api-key-env", "UNUSED_KEY"),
                        ("--player-api-key", "unused-key"),
                        ("--player-thinking", "enabled")):
            with self.subTest(options=options), tempfile.TemporaryDirectory() as directory:
                with self.assertRaises(ValueError):
                    matrix._runtime_profile(codex_args(directory, *options))

    def test_codex_role_models_are_preserved_in_runtime_and_frozen_config(self):
        for model in ('gpt-5.6-sol', 'gpt-6-astra'):
            with self.subTest(model=model), tempfile.TemporaryDirectory() as directory:
                args = codex_args(directory, '--player-model', model,
                                  '--evaluator-model', model, '--oracle-provider', 'codex',
                                  '--oracle-model', model, '--oracle-mode', 'llm_presentation')
                runtime = matrix._runtime_profile(args)
                config = matrix._config_payload(args, matrix.build_plan(case_pack='both', repeats=1))
                for role in matrix.ROLES:
                    self.assertEqual(runtime.for_role(role).model, model)
                    self.assertEqual(runtime.for_role(role).reasoning_effort, 'high')
                    self.assertEqual(config['design'][role + '_profile']['model'], model)

    def test_codex_unsupported_model_and_effort_are_rejected_during_configuration(self):
        for role in matrix.ROLES:
            for field, value in (('model', 'gpt-5.6'), ('model', 'gpt-6'),
                                 ('model', 'gpt-6-astra-latest'), ('reasoning-effort', 'none')):
                with self.subTest(role=role, field=field, value=value), \
                        tempfile.TemporaryDirectory() as directory:
                    args = codex_args(directory, '--oracle-provider', 'codex',
                                      '--%s-%s' % (role, field), value)
                    with self.assertRaises(ValueError):
                        matrix._runtime_profile(args)

    def test_episode_and_judge_keep_codex_identity_and_resume_without_regeneration(self):
        fixture = action_fixtures.UnlimitedAdaptiveTests()
        fixture.setUp()
        with tempfile.TemporaryDirectory() as directory, contextlib.redirect_stdout(io.StringIO()):
            root = Path(directory)
            args = codex_args(root, "--family", "pendulum", "--condition", "historical",
                              "--task-setting", "discovery", "--evaluation-method",
                              matrix.ADAPTIVE_EXPERIMENTAL_DESIGN)
            player = mock.Mock(supports_strict_action_schema=True)
            player.generate.side_effect = [GenerationResponse(
                text=json.dumps(structured_action_to_payload(action)), provider="codex",
                model="gpt-5.5", finish_reason="stop")
                for action in (fixture.experiment(), fixture.final())]
            judge = mock.Mock()
            judge.generate.side_effect = pipeline_fixtures.scientific_answer
            rows = matrix.run_matrix(args, player_backend_loader=lambda: player,
                                     evaluator_backend_loader=lambda: judge)
            row = rows[0]
            self.assertTrue(row["metrics_complete"])
            self.assertTrue(row["active_pass"])
            self.assertEqual(row["player_provider"], "codex")
            self.assertEqual(row["evaluator_provider"], "codex")
            self.assertEqual(row["oracle_provider"], "deterministic")
            evaluation = json.loads((root / row["evaluator_result_path"]).read_text())
            self.assertFalse(evaluation["generation_controls"]["enforced"]["max_output_tokens"])
            log = (root / row["log_path"]).read_text()
            self.assertIn('"generation_controls"', log)
            self.assertIn('"not_exposed_by_app_server"', log)
            no_backend = mock.Mock(side_effect=AssertionError("completed role must not rerun"))
            repeated = matrix.run_matrix(args, player_backend_loader=no_backend,
                                         evaluator_backend_loader=no_backend)
            self.assertEqual(repeated[0]["active_pass"], row["active_pass"])
            no_backend.assert_not_called()
            self.assertEqual(player.generate.call_count, 2)
            self.assertEqual(judge.generate.call_count, 1)


if __name__ == "__main__":
    unittest.main()
