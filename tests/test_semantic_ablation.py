"""Numerical identity and public leak guards for paired context ablations."""
from dataclasses import asdict, replace
import json
import math
import unittest

from experiments.semantic_ablation import adapt_case, adapt_prepared_case, opaque_case_id
from role_benchmark import BenchmarkTrack, ExperimentProposal, FinalSubmission, GenerationConfig
from role_benchmark.cases import CASE_SPECS
from role_benchmark.cases.matched import make_matched_case, truth_submission
from role_benchmark.evaluation_methods import prepare_evaluation_case, ADAPTIVE_EXPERIMENTAL_DESIGN, PRIOR_ONLY_BASELINE
from role_benchmark.expression import EXPRESSION_MODEL
from role_benchmark.episode import Episode
from role_benchmark.llm import build_generation_request, PLAYER_PROMPT_VERSION_V5_PERFORMANCE
from role_benchmark.models import ExperimentEvidence
from role_benchmark.protocols import CaseOracle, WorldModelContractError
from role_benchmark.temporal_cases import TEMPORAL_CASE_SPECS


FIXED4 = "fixed experimental design (4 observations)"


def proposal(spec, condition):
    return ExperimentProposal("Measure the system", spec.apparatus_name, condition,
        tuple(item.name for item in spec.readouts), spec.max_replicates,
        {"h1": {item.name: 0.0 for item in spec.readouts}})


class SemanticAblationTests(unittest.TestCase):
    def test_truth_ast_and_multipt_observations_exactly_match_original_worlds(self):
        specs = list(CASE_SPECS.values()) + [TEMPORAL_CASE_SPECS[name] for name in
            ("defect_sre", "temporal_enriched_90016", "temporal_enriched_90018")]
        for spec in specs:
            for world in ("historical", "counterfactual"):
                with self.subTest(family=spec.family, world=world):
                    original = make_matched_case(spec, world, BenchmarkTrack.DISCOVERY)
                    truth = truth_submission(spec, world, BenchmarkTrack.DISCOVERY)
                    oracle = CaseOracle(original.definition, original.world_model)
                    expected_score = original.evaluator.evaluate(truth)
                    for arm in ("anonymous", "familiar"):
                        adapted = adapt_case(original, arm=arm, opaque_id=opaque_case_id(spec.family))
                        neutral_truth = adapted.to_neutral_submission(truth)
                        self.assertEqual(adapted.to_original_submission(neutral_truth), truth)
                        scored = adapted.case.evaluator.evaluate(neutral_truth)
                        self.assertEqual(scored.success, expected_score.success)
                        self.assertEqual(adapted.to_original_scores(scored.scores), expected_score.scores)
                        neutral_oracle = CaseOracle(adapted.case.definition, adapted.case.world_model)
                        for condition in (*spec.diagnostic_conditions[:2], *spec.hidden_conditions[:2]):
                            source = proposal(spec, condition)
                            neutral = adapted.to_neutral_proposal(source)
                            returned = adapted.to_original_proposal(neutral)
                            self.assertEqual(returned.controls, source.controls)
                            self.assertEqual(returned.readouts, source.readouts)
                            self.assertEqual(returned.forecasts, source.forecasts)
                            expected, observed = oracle.respond(source), neutral_oracle.respond(neutral)
                            self.assertEqual(observed.status, expected.status)
                            self.assertEqual({adapted.interface.readouts[k]: v for k, v in expected.evidence.measurements.items()},
                                             observed.evidence.measurements)
                            self.assertEqual(neutral.replicates, source.replicates)

    def test_arms_differ_only_by_background_and_categorical_strings_are_opaque(self):
        spec = CASE_SPECS["boyle_j_tube"]
        original = make_matched_case(spec, "counterfactual", BenchmarkTrack.DISCOVERY)
        anon = adapt_case(original, arm="anonymous", opaque_id="case_abcdef")
        familiar = adapt_case(original, arm="familiar", opaque_id="case_abcdef")
        left, right = asdict(anon.case.definition), asdict(familiar.case.definition)
        self.assertNotEqual(left.pop("background"), right.pop("background"))
        self.assertEqual(left, right)
        public = json.dumps(asdict(anon.case.definition))
        for forbidden in ("Boyle", "mercury", "constant_room_temperature", "thermal_condition", "kPa", "mL",
                          "sealed_j_tube", "instance_", "sibling", "identifiability"):
            self.assertNotIn(forbidden, public)
        self.assertEqual(anon.case.definition.resources.controls[1].allowed_values, ("category_2_1",))
        self.assertIn("constant_room_temperature", familiar.case.definition.background)
        for name in ("faraday_induction", "rutherford_scattering"):
            case = make_matched_case(CASE_SPECS[name], "historical", BenchmarkTrack.DISCOVERY)
            adapted = adapt_case(case, arm="anonymous", opaque_id=opaque_case_id(name))
            for original_control, neutral_control in zip(case.definition.resources.controls, adapted.case.definition.resources.controls):
                self.assertEqual(original_control.allowed_values, neutral_control.allowed_values)

    def test_fixed4_and_method_state_are_preserved_without_semantic_observation_text(self):
        spec = CASE_SPECS["boyle_j_tube"]
        original = make_matched_case(spec, "counterfactual", BenchmarkTrack.DISCOVERY)
        for method in (FIXED4, ADAPTIVE_EXPERIMENTAL_DESIGN, PRIOR_ONLY_BASELINE):
            with self.subTest(method=method):
                prepared = prepare_evaluation_case(original, spec, method, count_all_experiment_attempts=True)
                a = adapt_prepared_case(prepared, arm="anonymous", opaque_id="case_abcd")
                b = adapt_prepared_case(prepared, arm="familiar", opaque_id="case_abcd")
                self.assertEqual(a.prepared.initial_attempts_used, prepared.initial_attempts_used)
                self.assertEqual(a.prepared.plan.observation_budget, prepared.plan.observation_budget)
                self.assertEqual(a.case.definition.budget, prepared.case.definition.budget)
                self.assertEqual(a.case.definition.count_all_experiment_attempts, True)
                self.assertEqual(a.prepared.fixed_observations, b.prepared.fixed_observations)
                self.assertEqual(a.case.definition.initial_observations, b.case.definition.initial_observations)
                self.assertEqual(a.case.definition.resources, b.case.definition.resources)
                for original_obs, neutral_obs in zip(prepared.fixed_observations, a.prepared.fixed_observations):
                    self.assertEqual(a.to_original_proposal(neutral_obs.proposal).controls, original_obs.proposal.controls)
                    self.assertEqual(neutral_obs.response.evidence.measurements,
                        {a.interface.readouts[k]: v for k, v in original_obs.response.evidence.measurements.items()})
                text = json.dumps(asdict(a.case.definition))
                for forbidden in ("added_pressure_kpa", "air_volume_ml", "mL", "constant_room_temperature", "sibling", "identifiability"):
                    self.assertNotIn(forbidden, text)

    def test_illegal_queries_keep_original_status_and_physical_names_are_not_backdoors(self):
        spec = CASE_SPECS["boyle_j_tube"]
        original = make_matched_case(spec, "counterfactual", BenchmarkTrack.DISCOVERY)
        adapted = adapt_case(original, arm="anonymous", opaque_id="case_abcd")
        original_oracle = CaseOracle(original.definition, original.world_model)
        oracle = CaseOracle(adapted.case.definition, adapted.case.world_model)
        valid = proposal(spec, spec.diagnostic_conditions[0])
        invalids = [replace(valid, apparatus=""), replace(valid, apparatus="not_available"),
                    replace(valid, controls={}), replace(valid, readouts=()),
                    replace(valid, replicates=0), replace(valid, readouts=(valid.readouts[0],)*2),
                    replace(valid, controls={**valid.controls, "added_pressure_kpa": -1}),
                    replace(valid, controls={**valid.controls, "thermal_condition": "wrong"})]
        for invalid in invalids:
            self.assertEqual(original_oracle.respond(invalid).status,
                             oracle.respond(adapted.to_neutral_proposal(invalid)).status)
        neutral = adapted.to_neutral_proposal(valid)
        physical_category = replace(neutral, controls={**neutral.controls, "x2": "constant_room_temperature"})
        self.assertNotEqual(oracle.respond(physical_category).status.value, "VALID")
        # A raw old variable name must be rejected, not map through as an alias.
        bad = FinalSubmission("test", EXPRESSION_MODEL, {"outputs": {
            "y1": {"var": "added_pressure_kpa"}, "y2": 1}})
        self.assertFalse(adapted.case.evaluator.evaluate(bad).success)

    def test_complete_llm_request_has_only_sidecard_difference_and_no_original_identity(self):
        spec = CASE_SPECS["boyle_j_tube"]
        original = make_matched_case(spec, "counterfactual", BenchmarkTrack.DISCOVERY)
        prepared = prepare_evaluation_case(original, spec, FIXED4)
        requests = []
        for arm in ("anonymous", "familiar"):
            adapted = adapt_prepared_case(prepared, arm=arm, opaque_id="case_abcd")
            episode = Episode(adapted.case, observation_budget=adapted.prepared.plan.observation_budget,
                initial_attempts_used=adapted.prepared.initial_attempts_used,
                require_budget_exhaustion=adapted.prepared.plan.require_budget_exhaustion)
            requests.append(build_generation_request(episode.view(), player_turn=1,
                config=GenerationConfig(), prompt_version=PLAYER_PROMPT_VERSION_V5_PERFORMANCE))
        anon, familiar = requests
        self.assertEqual(anon.messages[0], familiar.messages[0])
        self.assertEqual(anon.response_schema, familiar.response_schema)
        self.assertEqual(anon.metadata, familiar.metadata)
        self.assertEqual(anon.metadata['case_id'], 'case_abcd')
        left, right = json.loads(anon.messages[1].content), json.loads(familiar.messages[1].content)
        left['episode_view']['case'].pop('background')
        right['episode_view']['case'].pop('background')
        self.assertEqual(left, right)
        serialized = json.dumps(asdict(anon))
        for forbidden in ('boyle', 'mercury', 'thermal_condition', 'constant_room_temperature',
                          'added_pressure_kpa', 'sealed_j_tube', 'instance_', 'sibling', 'identifiability'):
            self.assertNotIn(forbidden, serialized)

    def test_divide_by_zero_and_overflow_predictions_fail_exactly_as_original(self):
        spec = CASE_SPECS["pendulum"]
        original = make_matched_case(spec, "historical", BenchmarkTrack.DISCOVERY)
        adapted = adapt_case(original, arm="anonymous", opaque_id="case_abcdef")
        for tree in ({"op": "divide", "args": [1, 0]}, {"op": "exp", "args": [10000]}, {"var": "unknown"}):
            source = FinalSubmission("test", EXPRESSION_MODEL, {"outputs": {spec.readouts[0].name: tree}})
            expected = original.evaluator.evaluate(source)
            scored = adapted.case.evaluator.evaluate(adapted.to_neutral_submission(source))
            self.assertEqual(expected.success, scored.success)
            self.assertEqual(expected.scores, adapted.to_original_scores(scored.scores))

    def test_world_contract_errors_are_not_repaired_and_private_messages_are_removed(self):
        spec = CASE_SPECS["pendulum"]
        original = make_matched_case(spec, "historical", BenchmarkTrack.DISCOVERY)
        source = proposal(spec, spec.diagnostic_conditions[0])
        class BrokenWorld:
            def run(self, proposal):
                return ExperimentEvidence({}, {}, message="secret pendulum period_s")
        broken = replace(original, world_model=BrokenWorld())
        adapted = adapt_case(broken, arm="anonymous", opaque_id="case_abcd")
        for case, query in ((broken, source), (adapted.case, adapted.to_neutral_proposal(source))):
            with self.assertRaises(WorldModelContractError):
                CaseOracle(case.definition, case.world_model).respond(query)
        class NonfiniteWorld:
            def run(self, proposal):
                return ExperimentEvidence({"period_s": math.inf}, {"period_s": "s"},
                    {"period_s": "secret oscillation uncertainty"}, "secret physical law")
        changed = replace(original, world_model=NonfiniteWorld())
        adapted = adapt_case(changed, arm="anonymous", opaque_id="case_abcd")
        observed = CaseOracle(adapted.case.definition, adapted.case.world_model).respond(adapted.to_neutral_proposal(source))
        self.assertEqual(observed.evidence.measurements["y1"], math.inf)
        self.assertNotIn("secret", str(observed))
        self.assertNotIn("period_s", str(observed))

    def test_identification_and_semantic_case_ids_fail_closed(self):
        source = make_matched_case(CASE_SPECS["pendulum"], "historical", BenchmarkTrack.IDENTIFICATION)
        with self.assertRaisesRegex(ValueError, "DISCOVERY"):
            adapt_case(source, arm="anonymous", opaque_id="case_abcd")
        source = make_matched_case(CASE_SPECS["pendulum"], "historical", BenchmarkTrack.DISCOVERY)
        with self.assertRaisesRegex(ValueError, "opaque_id"):
            adapt_case(source, arm="anonymous", opaque_id="pendulum_counterfactual")


if __name__ == "__main__":
    unittest.main()
