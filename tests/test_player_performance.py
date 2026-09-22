"""Scientific metrics must be separate, evidence-grounded and replayable."""
import contextlib
import json
import io
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from role_benchmark import (
    BenchmarkTrack, ControlSpec, GenerationResponse, replay_run_log,
)
from role_benchmark.cases.matched import truth_submission
from role_benchmark.expression import EXPRESSION_OPERATOR_ARITIES
from role_benchmark.formula_consistency import compare_formulas
from role_benchmark.llm import PLAYER_PROMPT_VERSION_V5_PERFORMANCE
from role_benchmark.performance import PERFORMANCE_PROTOCOL, formula_metric
from role_benchmark.discovery_evaluation import DISCOVERY_PROMPT_VERSION
from role_benchmark.structured_actions import structured_action_to_payload
from role_benchmark.wire import WireDecodeError
from experiments import run_case_matrix as matrix
import test_case_matrix_experiment as matrix_fixtures
import test_unlimited_adaptive as action_fixtures


def op(name, *args):
    return {"op": name, "args": list(args)}


class FormulaTests(unittest.TestCase):
    def compare(self, a, b, lo=1, hi=4, **kwargs):
        return compare_formulas({"outputs": {"y": a}}, {"outputs": {"y": b}},
            (ControlSpec("x", "control", minimum=lo, maximum=hi),), **kwargs)

    def test_factoring_order_and_rational_equivalence(self):
        x = {"var": "x"}
        pairs = [(op("multiply", 2, x), op("add", x, x)),
            (op("add", op("power", x, 2), op("multiply", 2, x), 1),
             op("power", op("add", x, 1), 2)),
            (op("divide", op("multiply", x, x), x), x),
            (op("sin", op("multiply", 2, x)), op("sin", op("add", x, x)))]
        for a, b in pairs:
            with self.subTest(a=a):
                self.assertEqual(self.compare(a, b)["status"], "equivalent")

    def test_parameter_error_is_not_hidden_by_structure_match(self):
        result = self.compare(op("multiply", 2, {"var": "x"}), op("multiply", 3, {"var": "x"}))
        self.assertEqual(result["status"], "not_equivalent")
        self.assertTrue(result["operator_structure_match"])
        self.assertIn("counterexample", result)

    def test_cancellation_must_preserve_domain(self):
        result = self.compare(op("divide", {"var": "x"}, {"var": "x"}), 1, -1, 1)
        self.assertEqual(result["status"], "not_equivalent")
        self.assertEqual(result["method"], "domain_counterexample")
        self.assertEqual(result["counterexample"]["controls"], {"x": 0})

    def test_probe_agreement_is_not_proof(self):
        x = {"var": "x"}
        # Valid identity outside the deliberately small algebra engine.
        result = self.compare(op("add", op("power", op("sin", x), 2),
            op("power", op("cos", x), 2)), 1)
        self.assertEqual(result["status"], "inconclusive")
        self.assertGreater(result["probes_checked"], 0)
        # An interpolant matching all default probes is also inconclusive.
        polynomial = op("multiply", x, op("subtract", x, 1), op("subtract", x, 2))
        self.assertEqual(self.compare(polynomial, 0, 0, 2)["status"], "inconclusive")
        self.assertEqual(self.compare(polynomial, 0, 0, 2, probes=({"x": .5},))["status"], "not_equivalent")

    def test_invalid_contract_and_unbounded_domain_fail_conservatively(self):
        self.assertEqual(self.compare({"var": "private"}, 1)["method"], "invalid_predictor_contract")
        self.assertEqual(self.compare(True, 1)["method"], "invalid_predictor_contract")
        result = compare_formulas({"outputs": {"y": op("add", 1, 1)}},
            {"outputs": {"y": 2}}, (ControlSpec("x", "unbounded"),))
        self.assertEqual(result["status"], "inconclusive")

    def test_deep_functions_and_expansion_are_bounded(self):
        nested = {"var": "x"}
        for _ in range(40):
            nested = op("sin", nested)
        self.assertEqual(self.compare(op("add", nested, 0), nested)["status"], "equivalent")
        huge = op("power", op("add", {"var": "x"}, 1), 8)
        for _ in range(3):
            huge = op("power", huge, 8)
        self.assertIn(self.compare(huge, 0, 0, .01)["status"], ("inconclusive", "not_equivalent"))

    def test_all_operators_accept_identical_valid_programs(self):
        for name, (arity, _) in EXPRESSION_OPERATOR_ARITIES.items():
            with self.subTest(operator=name):
                expression = op(name, *([1] * arity))
                self.assertEqual(self.compare(expression, expression)["status"], "equivalent")

    def test_every_registered_world_truth_matches_its_reference(self):
        checked = set()
        for pack in matrix.CASE_PACKS.values():
            for variants in pack.specifications.values():
                for spec in variants.values():
                    if id(spec) in checked:
                        continue
                    checked.add(id(spec))
                    for world in spec.truths:
                        submission = truth_submission(spec, world, BenchmarkTrack.DISCOVERY)
                        self.assertEqual(formula_metric(submission, spec, world)["status"], "equivalent")
        self.assertEqual(len(checked), 53)


class PerformanceIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.fixture = action_fixtures.UnlimitedAdaptiveTests()
        self.fixture.setUp()

    def args_and_spec(self, directory):
        args = matrix_fixtures._args(directory)
        args.family = ["pendulum"]
        args.repeats = 1
        args.task_setting = ["discovery"]
        args.evaluation_method = [matrix.ADAPTIVE_EXPERIMENTAL_DESIGN]
        args.condition = ["historical"]
        plan = matrix.build_plan(args.schedule_seed, families=args.family, repeats=1,
            case_pack="historical", task_settings=args.task_setting,
            evaluation_methods=args.evaluation_method, conditions=args.condition)
        return args, plan[0]

    def player(self):
        backend = mock.Mock(supports_strict_action_schema=True)
        backend.generate.side_effect = [GenerationResponse(
            text=json.dumps(structured_action_to_payload(action)), provider="test", model="player", finish_reason="stop")
            for action in (self.fixture.experiment(), self.fixture.final())]
        return backend

    def test_independent_scientific_metrics_and_episode_replay(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            args, spec = self.args_and_spec(root)
            backend = self.player()
            log_path = root / "episode.jsonl"
            result = matrix._run_one_episode(args, player_backend=backend, oracle_backend=None,
                output_dir=root, spec=spec, log_path=log_path)
            self.assertEqual(result["status"], "evaluated", result)
            self.assertTrue(result["evaluation_success"])
            self.assertEqual(result["formula_consistency"]["status"], "equivalent")
            self.assertEqual(result["failure_analysis"]["status"], "passed_analyzed")
            replay = replay_run_log(str(log_path), matrix._prepare_case(spec).case)
            self.assertTrue(replay.outcome.evaluation.success)
            self.assertIn("formula consistency", backend.generate.call_args_list[0].args[0].messages[0].content)
            self.assertEqual(matrix._prompt_version(args, "player"), PLAYER_PROMPT_VERSION_V5_PERFORMANCE)
            self.assertEqual(matrix._prompt_version(args, "evaluator"), DISCOVERY_PROMPT_VERSION)
            judge = mock.Mock()
            judge.generate.side_effect = matrix_fixtures._scientific_answer
            evaluated = matrix._run_evaluator(args, evaluator_backend=judge, output_dir=root, spec=spec, episode_result=result)
            self.assertEqual(evaluated["status"], "evaluated", evaluated)
            self.assertEqual(set(evaluated["evaluation"]["scores"]),
                             {"understanding_before", "understanding_after", "understanding_gain"})
            self.assertEqual(evaluated["evaluation"]["details"]["understanding"]["status"], "paired")
            self.assertTrue(result["evaluation_success"])

    def test_metric_failures_preserve_science_score(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            args, spec = self.args_and_spec(root)
            with mock.patch.object(matrix, "formula_metric", side_effect=RuntimeError("metric bug")), \
                    mock.patch.object(matrix, "analyze_failure_events", side_effect=RuntimeError("diagnostic bug")):
                result = matrix._run_one_episode(args, player_backend=self.player(), oracle_backend=None,
                    output_dir=root, spec=spec, log_path=root / "episode.jsonl")
            self.assertEqual(result["status"], "evaluated", result)
            self.assertTrue(result["evaluation_success"])
            self.assertEqual(result["formula_consistency"]["status"], "infrastructure_failed")
            self.assertEqual(matrix._formula_result(spec, result)["status"], "equivalent")
            judge = mock.Mock()
            judge.generate.side_effect = RuntimeError("provider unavailable")
            evaluation = matrix._run_evaluator(args, evaluator_backend=judge, output_dir=root, spec=spec, episode_result=result)
            self.assertEqual(evaluation["status"], "infrastructure_failed")
            self.assertTrue(result["evaluation_success"])

    def test_resource_limits_are_not_reported_as_model_format_failures(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            args, spec = self.args_and_spec(root)
            args.player_max_action_bytes = 32
            result = matrix._run_one_episode(args, player_backend=self.player(), oracle_backend=None,
                output_dir=root, spec=spec, log_path=root / "episode.jsonl")
            self.assertEqual(result["active_pass_category"], "resource_limit_failure", result)
            self.assertEqual(result["formula_consistency"]["status"], "unavailable")
            self.assertFalse(result["scientifically_evaluable"])

    def test_semantic_oracle_configuration_and_native_capability_check(self):
        args, _ = self.args_and_spec("unused")
        args.oracle_mode = matrix.LLM_SEMANTIC_ORACLE
        self.assertEqual(matrix._prompt_version(args, "oracle"), matrix.ORACLE_PROMPT_VERSION_V3_SEMANTIC)
        backend = mock.Mock(supports_strict_action_schema=False)
        with self.assertRaises(ValueError):
            matrix.load_role_backend(args, "player", loader=lambda: backend)
        backend.generate.assert_not_called()
        for role in matrix.ROLES:
            setattr(args, role + "_provider", "ifm")
            setattr(args, role + "_thinking", None)
            setattr(args, role + "_reasoning_effort", "medium")
            self.assertEqual(matrix._role_runtime(args, role).response_format, "native_json_schema_local_validation")

    def test_three_role_run_retries_metrics_without_replaying_player(self):
        with tempfile.TemporaryDirectory() as directory, contextlib.redirect_stdout(io.StringIO()):
            root = Path(directory)
            args, spec = self.args_and_spec(root)
            args.oracle_mode = matrix.LLM_SEMANTIC_ORACLE
            player = self.player()
            oracle = mock.Mock()
            oracle.generate.return_value = GenerationResponse(
                text=json.dumps({"status": "VALID", "reason": "", "constraint_ids": []}),
                provider="test", model="oracle", finish_reason="stop")
            judge = mock.Mock()
            judge.generate.side_effect = RuntimeError("judge unavailable")
            with mock.patch.object(matrix, "formula_metric", side_effect=RuntimeError("metric unavailable")):
                with self.assertRaisesRegex(RuntimeError, "evaluator failure"):
                    matrix.run_matrix(args, player_backend_loader=lambda: player,
                        oracle_backend_loader=lambda: oracle, evaluator_backend_loader=lambda: judge)
            stored = json.loads((root / "results" / (spec.episode_id + ".result.json")).read_text())
            self.assertTrue(stored["evaluation_success"])
            self.assertEqual(stored["formula_consistency"]["status"], "infrastructure_failed")
            self.assertEqual(player.generate.call_count, 2)
            self.assertEqual(oracle.generate.call_count, 1)
            oracle_request = oracle.generate.call_args.args[0]
            self.assertNotIn("active_world_reference", oracle_request.messages[1].content)
            self.assertEqual(oracle_request.metadata["prompt_version"], matrix.ORACLE_PROMPT_VERSION_V3_SEMANTIC)
            judge.generate.side_effect = matrix_fixtures._scientific_answer
            no_active = mock.Mock(side_effect=AssertionError("active backend must not load during metric-only retry"))
            rows = matrix.run_matrix(args, player_backend_loader=no_active,
                oracle_backend_loader=no_active, evaluator_backend_loader=lambda: judge)
            no_active.assert_not_called()
            self.assertEqual(len(rows), 1)
            self.assertTrue(rows[0]["metrics_complete"])
            self.assertEqual(rows[0]["formula_consistency"]["status"], "equivalent")
            self.assertEqual(rows[0]["scores"], stored["scores"])
            attempts = sorted((root / "evaluations" / "attempts" / rows[0]["episode_id"]).glob("*.json"))
            self.assertEqual(len(attempts), 2)
            self.assertEqual(json.loads(attempts[0].read_text())["status"], "infrastructure_failed")
            self.assertEqual(json.loads(attempts[1].read_text())["status"], "evaluated")
            # After every metric is present, even the judge must stay idle.
            matrix.run_matrix(args, player_backend_loader=no_active,
                oracle_backend_loader=no_active, evaluator_backend_loader=no_active)
            no_active.assert_not_called()
            self.assertEqual(len(list(attempts[0].parent.glob("*.json"))), 2)
            config = json.loads((root / "config.json").read_text())
            self.assertEqual(config["oracle_generation"]["mode"], matrix.LLM_SEMANTIC_ORACLE)
            self.assertEqual(config["metrics_protocol"], PERFORMANCE_PROTOCOL)


class RoleCompletionTests(unittest.TestCase):
    def test_oracles_reject_incomplete_valid_json(self):
        from role_benchmark.llm_oracle import LLMOracle, OracleOutputError
        from role_benchmark.protocols import CaseOracle
        from role_benchmark.semantic_oracle import LLMSemanticOracle
        fixture = action_fixtures.UnlimitedAdaptiveTests()
        fixture.setUp()
        case = fixture.case
        proposal = fixture.experiment().experiment
        expected = CaseOracle(case.definition, case.world_model).respond(proposal)
        for oracle_class, answer in ((LLMOracle, {"message": expected.message}),
            (LLMSemanticOracle, {"status": "VALID", "reason": "", "constraint_ids": []})):
            for reason in ("length", "MAX_TOKENS", "incomplete:max_output_tokens", "content_filter", "unknown_reason"):
                backend = mock.Mock()
                backend.generate.return_value = GenerationResponse(text=json.dumps(answer),
                    provider="test", model="oracle", finish_reason=reason)
                with self.subTest(role=oracle_class.__name__, reason=reason), self.assertRaises(OracleOutputError):
                    oracle_class(case.definition, case.world_model, backend).respond(proposal)

    def test_deepseek_missing_status_and_refusal_are_not_normal_answers(self):
        import test_ifm_chat_completions as http_fixtures
        from experiments.run_pendulum_matrix import DeepSeekChatBackend
        from role_benchmark.llm import validate_generation_completion
        def backend(message, finish):
            return DeepSeekChatBackend(api_key="test-secret", model="fixture",
                endpoint="https://fixture.invalid/v1/chat/completions", thinking="disabled", reasoning_effort=None,
                urlopen=lambda *a, **k: http_fixtures._FakeHTTPResponse({"choices": [
                    {"message": message, "finish_reason": finish}]}))
        with self.assertRaisesRegex(RuntimeError, "omitted completion status"):
            backend({"content": "{}"}, None).generate(http_fixtures._request())
        response = backend({"content": "{}", "refusal": "Declined"}, "stop").generate(http_fixtures._request())
        with self.assertRaises(WireDecodeError) as caught:
            validate_generation_completion(response)
        self.assertEqual(caught.exception.code, "provider_refusal")


if __name__ == "__main__":
    unittest.main()
