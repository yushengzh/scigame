"""Scientific endpoint comparison remains independent from episode success."""
import copy
from dataclasses import replace
import json
import unittest

from role_benchmark import LoadedRunLog
from role_benchmark.discovery_evaluation import (
    DISCOVERY_PROMPT_VERSION, decode_discovery_evaluation, discovery_json_schema,
    discovery_projection,
)
from role_benchmark.wire import WireDecodeError


BEFORE = "The observed response is linear in x, with positive coefficient and no offset."
AFTER = "The observations instead support quadratic x dependence, a positive coefficient and no offset."
QUADRATIC = {"op": "power", "args": [{"var": "x"}, 2]}
CRITERIA = [
    {"id": "dependence", "question": "Is the dependence on x correctly described?"},
    {"id": "coefficient", "question": "Is the coefficient role correctly described?"},
    {"id": "scope", "question": "Are the conditions and zero offset correctly described?"},
]


def episode(*, observations=True, before=BEFORE, after=AFTER, final=True):
    action_before = {"kind": "experiment", "portfolio": {"hypotheses": [{"statement": before}]},
                     "experiment": {"intent": ""}}
    action_after = ({"kind": "final", "final": {"explanation": after,
                                                 "parameters": {"outputs": {"y": copy.deepcopy(QUADRATIC)}}}}
                    if final else {"kind": "experiment", "portfolio": {"hypotheses": [{"statement": after}]}})
    payloads = [
        ("run.started", {"case": {"case_id": "test-case"},
                         "run_metadata": {"player_model": "HIDDEN_MODEL"}}),
        ("action.decoded", {"action_index": 1, "action": action_before}),
        ("protocol.transition", {"action_index": 1, "outcome_kind": "experiment_evidence",
                                 "outcome": {"oracle_response": {"status": "VALID" if observations else "INVALID",
                                                                 "evidence": {"observations": {"y": 4}}}}}),
        ("action.decoded", {"action_index": 2, "action": action_after}),
        ("protocol.transition", {"action_index": 2, "outcome_kind": "final_evaluation",
                                 "outcome": {"evaluation": {"success": False, "scores": {"error": 0.1}}}}),
        ("run.ended", {"status": "evaluated" if final else "incomplete"}),
    ]
    return LoadedRunLog("private-model-run", tuple({"sequence": index, "event_type": kind, "payload": payload}
                                                   for index, (kind, payload) in enumerate(payloads)), complete=True)


def reference():
    return {"case_id": "test-case", "predictor": {"outputs": {"y": copy.deepcopy(QUADRATIC)}},
            "understanding_criteria": copy.deepcopy(CRITERIA)}


def answer(before=(0, 1, 1), after=(1, 1, 1), before_claim=BEFORE, after_claim=AFTER):
    return {"understanding": {"items": [
        {"criterion_id": criterion["id"], "before_score": before[index], "after_score": after[index],
         "before_claim": before_claim if before[index] is not None else None,
         "after_claim": after_claim if after[index] is not None else None,
         "rationale": "Compare the expressed relation with the active world and available evidence."}
        for index, criterion in enumerate(CRITERIA)]}, "findings": [],
        "summary": "A scientific relation changed after observing the case."}


class DiscoveryEvaluationTests(unittest.TestCase):
    def setUp(self):
        self.projection = discovery_projection(episode(), reference())

    def decode(self, value, projection=None):
        return decode_discovery_evaluation(json.dumps(value), projection or self.projection)

    def test_improvement_and_retention_are_derived_from_the_same_criteria(self):
        value = answer()
        value["understanding"]["items"].reverse()
        result = self.decode(value)
        understanding = result["understanding"]
        self.assertEqual(understanding["status"], "paired")
        self.assertAlmostEqual(understanding["before_score"], 2 / 3)
        self.assertEqual(understanding["after_score"], 1)
        self.assertAlmostEqual(understanding["delta"], 1 / 3)
        self.assertEqual([row["criterion_id"] for row in understanding["items"]], [row["id"] for row in CRITERIA])
        self.assertEqual([row["kind"] for row in understanding["transitions"]],
                         ["gained", "retained_correct", "retained_correct"])
        self.assertNotIn("success", result)
        self.assertNotIn("pass", result)

    def test_correct_retention_is_not_required_to_improve(self):
        projection = discovery_projection(episode(before=AFTER), reference())
        result = self.decode(answer(before=(1, 1, 1), before_claim=AFTER), projection)
        self.assertEqual(result["understanding"]["delta"], 0)
        self.assertTrue(all(row["kind"] == "retained_correct" for row in result["understanding"]["transitions"]))

    def test_explicitly_unresolved_relation_can_be_learned_without_a_reasoning_error(self):
        before = "I have not identified the x dependence; the coefficient is positive and there is no offset."
        projection = discovery_projection(episode(before=before), reference())
        result = self.decode(answer(before=(0, 1, 1), before_claim=before), projection)
        self.assertAlmostEqual(result["understanding"]["delta"], 1 / 3)
        self.assertEqual(result["understanding"]["transitions"][0]["kind"], "gained")
        self.assertEqual(result["understanding"]["items"][0]["before_claim"], before)
        self.assertEqual(result["findings"], [])
        unresolved = self.decode(answer(before=(0, 1, 1), after=(0, 1, 1),
                                        before_claim=before, after_claim=before),
                                 discovery_projection(episode(before=before, after=before), reference()))
        self.assertEqual(unresolved["understanding"]["transitions"][0]["kind"],
                         "unchanged_unresolved_or_incorrect")

    def test_losing_a_valid_relationship_remains_visible(self):
        result = self.decode(answer(before=(1, 1, 1), after=(1, 0.5, 0)))
        self.assertEqual(result["understanding"]["delta"], -0.5)
        self.assertEqual([row["kind"] for row in result["understanding"]["transitions"]],
                         ["retained_correct", "degraded", "degraded"])

    def test_invalid_query_does_not_erase_two_expressed_endpoints(self):
        projection = discovery_projection(episode(observations=False), reference())
        window = projection["understanding_window"]
        self.assertEqual(window["before_sequence"], 1)
        self.assertEqual(window["after_sequence"], 3)
        self.assertFalse(window["has_new_observation"])
        self.assertEqual(window["evidence_condition"], "no_new_observation")
        result = self.decode(answer(), projection)
        self.assertEqual(result["understanding"]["status"], "paired")
        self.assertAlmostEqual(result["understanding"]["delta"], 1 / 3)

    def test_review_without_new_observations_can_have_measurable_change(self):
        log = episode()
        events = [copy.deepcopy(event) for event in log.events if event["sequence"] != 2]
        events[0]["payload"]["run_metadata"]["fixed_observations"] = [
            {"x": 1, "y": 1}, {"x": 2, "y": 4}, {"x": 3, "y": 9}]
        projection = discovery_projection(replace(log, events=tuple(events)), reference())
        window = projection["understanding_window"]
        self.assertEqual(window["before_sequence"], 1)
        self.assertEqual(window["fixed_observation_count"], 3)
        self.assertEqual(window["observation_sequences"], [])
        self.assertEqual(window["evidence_condition"], "no_new_observation")
        result = self.decode(answer(), projection)
        self.assertEqual(result["understanding"]["status"], "paired")
        self.assertAlmostEqual(result["understanding"]["delta"], 1 / 3)

    def test_only_one_scientific_endpoint_has_no_measurable_change(self):
        projection = discovery_projection(episode(before=""), reference())
        self.assertIsNone(projection["understanding_window"]["before_sequence"])
        result = self.decode(answer(before=(None, None, None)), projection)
        self.assertEqual(result["understanding"]["status"], "final_only")
        self.assertIsNone(result["understanding"]["delta"])
        with self.assertRaises(WireDecodeError):
            self.decode(answer(), projection)

    def test_missing_one_criterion_cannot_be_silently_removed_from_the_mean(self):
        result = self.decode(answer(before=(0, None, 1), after=(1, 1, None)))
        self.assertIsNone(result["understanding"]["before_score"])
        self.assertIsNone(result["understanding"]["after_score"])
        self.assertIsNone(result["understanding"]["delta"])
        self.assertEqual(result["understanding"]["transitions"][0]["kind"], "gained")
        self.assertEqual(result["understanding"]["transitions"][1]["kind"], "unmeasured")

    def test_fixed_observations_and_a_final_report_do_not_create_a_prior_claim(self):
        log = episode()
        events = [copy.deepcopy(log.events[index]) for index in (0, 3, 4, 5)]
        events[0]["payload"]["run_metadata"]["fixed_observations"] = [{"x": 2, "y": 4}]
        projection = discovery_projection(replace(log, events=tuple(events)), reference())
        self.assertEqual(projection["understanding_window"]["after_sequence"], 3)
        self.assertIsNone(projection["understanding_window"]["before_sequence"])
        self.assertEqual(projection["understanding_window"]["observation_sequences"], [])
        self.assertEqual(projection["understanding_window"]["fixed_observation_count"], 1)
        self.assertEqual(projection["understanding_window"]["prior_valid_observation_count"], 0)
        result = self.decode(answer(before=(None, None, None)), projection)
        self.assertEqual(result["understanding"]["after_score"], 1)
        self.assertIsNone(result["understanding"]["delta"])

    def test_failed_episode_can_use_last_nonfinal_scientific_action(self):
        projection = discovery_projection(episode(final=False), reference())
        self.assertEqual(projection["understanding_window"]["after_sequence"], 3)
        self.assertEqual(self.decode(answer(), projection)["understanding"]["after_score"], 1)

    def test_no_scientific_text_is_unmeasured(self):
        projection = discovery_projection(episode(before="", after=""), reference())
        result = self.decode(answer(before=(None, None, None), after=(None, None, None)), projection)
        self.assertEqual(result["understanding"]["status"], "unmeasured")
        self.assertIsNone(result["understanding"]["after_score"])
        self.assertIsNone(projection["understanding_window"]["after_sequence"])

    def test_first_scientific_action_is_fixed_before_the_judge_scores_it(self):
        log = episode()
        events = list(copy.deepcopy(log.events))
        events.insert(3, {"sequence": 2.5, "event_type": "action.decoded", "payload": {
            "action_index": 2, "action": {"portfolio": {"hypotheses": [{"statement": "A worse intermediate claim."}]}}}})
        for index, event in enumerate(events):
            event["sequence"] = index
        projection = discovery_projection(replace(log, events=tuple(events)), reference())
        self.assertEqual(projection["understanding_window"], {
            "before_sequence": 1, "after_sequence": 4, "observation_sequences": [2],
            "has_new_observation": True, "evidence_condition": "new_observation",
            "baseline_kind": "within_episode_first_expressed_claim",
            "fixed_observation_count": 0, "prior_valid_observation_count": 0})

    def test_evidence_seen_before_first_expressed_claim_is_counted(self):
        log = episode()
        events = list(copy.deepcopy(log.events))
        events[0]["payload"]["run_metadata"]["fixed_observations"] = [{"x": 1, "y": 1}]
        earlier_observation = copy.deepcopy(events[2])
        earlier_observation["payload"]["action_index"] = 0
        earlier_action = {"sequence": -1, "event_type": "action.decoded", "payload": {
            "action_index": 0, "action": {"kind": "experiment", "experiment": {"intent": ""}}}}
        events[1:1] = [earlier_action, earlier_observation]
        for index, event in enumerate(events):
            event["sequence"] = index
        projection = discovery_projection(replace(log, events=tuple(events)), reference())
        window = projection["understanding_window"]
        self.assertEqual(window["before_sequence"], 3)
        self.assertEqual(window["baseline_kind"], "within_episode_first_expressed_claim")
        self.assertEqual(window["fixed_observation_count"], 1)
        self.assertEqual(window["prior_valid_observation_count"], 1)
        self.assertEqual(window["observation_sequences"], [4])

    def test_quotes_and_criteria_must_refer_to_fixed_endpoints(self):
        modifications = [
            lambda value: value["understanding"]["items"][0].update(before_claim=AFTER),
            lambda value: value["understanding"]["items"][0].update(after_claim=None),
            lambda value: value["understanding"]["items"][0].update(criterion_id="other"),
            lambda value: value["understanding"]["items"][0].update(criterion_id="coefficient"),
            lambda value: value["understanding"]["items"].pop(),
        ]
        for modify in modifications:
            value = answer()
            modify(value)
            with self.subTest(modification=modify), self.assertRaises(WireDecodeError):
                self.decode(value)

    def test_scientific_findings_allow_multiple_types_but_need_actual_actions(self):
        log = episode()
        events = copy.deepcopy(log.events)
        events[3]["payload"]["action"]["final"]["parameters"]["outputs"]["y"] = {"var": "x"}
        projection = discovery_projection(replace(log, events=events), reference())
        value = answer()
        value["findings"] = [
            {"code": "F2", "rationale": "The submitted linear expression misses quadratic dependence.", "event_sequences": [3]},
            {"code": "F5", "rationale": "The final quadratic explanation contradicts its linear expression.", "event_sequences": [3]},
        ]
        self.assertEqual(self.decode(value, projection)["findings"], value["findings"])
        value["findings"][1]["code"] = "F2"
        with self.assertRaises(WireDecodeError):
            self.decode(value)

    def test_submitted_relation_findings_require_the_final_submission(self):
        no_final = discovery_projection(episode(final=False), reference())
        for code in ("F2", "F3", "F5"):
            value = answer()
            value["findings"] = [{"code": code, "rationale": "A proposed defect in the submitted relation.",
                                  "event_sequences": [1]}]
            with self.subTest(code=code, condition="earlier_claim"), self.assertRaises(WireDecodeError):
                self.decode(value)
            value["findings"][0]["event_sequences"] = [3]
            with self.subTest(code=code, condition="no_final"), self.assertRaises(WireDecodeError):
                self.decode(value, no_final)

    def test_explanation_finding_requires_the_endpoint_with_the_remaining_problem(self):
        value = answer()
        value["findings"] = [{"code": "F4", "rationale": "The earlier claim was mistaken.",
                              "event_sequences": [1, 2]}]
        with self.assertRaises(WireDecodeError):
            self.decode(value)
        value["findings"][0].update(rationale="The endpoint still asserts a contradicted condition.",
                                    event_sequences=[1, 2, 3])
        self.assertEqual(self.decode(value)["findings"], value["findings"])
        value["findings"] = [{"code": "F4", "rationale": "Observed quantity.", "event_sequences": [2]}]
        with self.assertRaises(WireDecodeError):
            self.decode(value)

    def test_projection_uses_scientific_material_without_model_or_episode_outcome(self):
        serialized = json.dumps(self.projection)
        self.assertNotIn("HIDDEN_MODEL", serialized)
        self.assertNotIn("private-model-run", serialized)
        self.assertNotIn("success", serialized)
        self.assertNotIn('"error"', serialized)
        self.assertEqual(DISCOVERY_PROMPT_VERSION, "role_benchmark.evaluator_prompt.discovery")
        self.assertEqual(set(discovery_json_schema()["properties"]), {"understanding", "findings", "summary"})


if __name__ == "__main__":
    unittest.main()
