"""Cross-family acceptance tests for the complete matched case registry.

These tests exercise only information that is deliberately available to case
authors.  The Player-facing checks always go through the canonical EpisodeView
wire payload, while scientific truth is used only for evaluator contract tests.
"""

import copy
import json
import math
import unittest
from collections.abc import Mapping

from role_benchmark import (
    BenchmarkTrack,
    CaseOracle,
    Episode,
    ExperimentProposal,
    FinalSubmission,
    Hypothesis,
    HypothesisPortfolio,
    OracleStatus,
    PlayerAction,
)
from role_benchmark.cases import (
    CASE_FAMILIES,
    CASE_SPECS,
    MATCHED_WORLDS,
    make_case,
)
from role_benchmark.cases.matched import truth_submission
from role_benchmark.expression import EXPRESSION_MODEL, EXPRESSION_OPERATOR_ARITIES
from role_benchmark.wire import (
    episode_view_to_payload,
    player_action_from_json,
    player_action_json_schema,
    player_action_to_json,
)


TRACKS = (BenchmarkTrack.IDENTIFICATION, BenchmarkTrack.DISCOVERY)


def _proposal(spec, condition):
    return ExperimentProposal(
        intent="Run a declared matched-family contract probe.",
        apparatus=spec.apparatus_name,
        controls=dict(condition),
        readouts=tuple(readout.name for readout in spec.readouts),
        replicates=1,
    )


def _initial_player_payload(case):
    return episode_view_to_payload(Episode(case).view())


def _without_case_id(payload):
    normalized = copy.deepcopy(payload)
    normalized["case"]["case_id"] = "opaque-world-id"
    return normalized


def _nested_keys(value):
    keys = set()
    if isinstance(value, Mapping):
        for key, nested in value.items():
            keys.add(key)
            keys.update(_nested_keys(nested))
    elif isinstance(value, (list, tuple)):
        for nested in value:
            keys.update(_nested_keys(nested))
    return keys


def _provider_operator_arities():
    expression_schema = player_action_json_schema()["$defs"]["expression"]
    result = {}
    for branch in expression_schema["oneOf"]:
        properties = branch.get("properties", {})
        if "op" not in properties:
            continue
        arguments = properties["args"]
        bounds = (arguments["minItems"], arguments.get("maxItems"))
        for operator in properties["op"]["enum"]:
            result[operator] = bounds
    return result


def _assert_expression_fits_provider_schema(test, expression, operator_arities):
    if isinstance(expression, (int, float)) and not isinstance(expression, bool):
        return
    if set(expression) == {"var"}:
        test.assertIsInstance(expression["var"], str)
        test.assertTrue(expression["var"].strip())
        return
    test.assertEqual(set(expression), {"op", "args"})
    operator = expression["op"]
    test.assertIn(operator, operator_arities)
    minimum, maximum = operator_arities[operator]
    arguments = expression["args"]
    test.assertGreaterEqual(len(arguments), minimum)
    if maximum is not None:
        test.assertLessEqual(len(arguments), maximum)
    for argument in arguments:
        _assert_expression_fits_provider_schema(
            test, argument, operator_arities
        )


class MatchedFamilyContractTest(unittest.TestCase):
    def test_every_truth_submission_uses_the_provider_expression_schema(self):
        provider_arities = _provider_operator_arities()
        self.assertEqual(
            provider_arities,
            dict(EXPRESSION_OPERATOR_ARITIES),
            "provider schema and executable expression grammar must share one operator set",
        )
        portfolio = HypothesisPortfolio(
            (
                Hypothesis("H1", "The development truth law.", 0.95),
                Hypothesis("H2", "A distinct alternative law.", 0.05),
            )
        )
        for family in CASE_FAMILIES:
            spec = CASE_SPECS[family]
            for world in MATCHED_WORLDS:
                with self.subTest(family=family, world=world):
                    submissions = tuple(
                        truth_submission(spec, world, track) for track in TRACKS
                    )
                    self.assertEqual(submissions[0], submissions[1])
                    final = submissions[0]
                    self.assertEqual(final.model, EXPRESSION_MODEL)
                    action = PlayerAction.submit_final(portfolio, final)
                    decoded = player_action_from_json(player_action_to_json(action))
                    self.assertEqual(decoded.final.parameters, final.parameters)
                    for expression in final.parameters["outputs"].values():
                        _assert_expression_fits_provider_schema(
                            self, expression, provider_arities
                        )

    def test_registry_contains_twenty_complete_four_cell_families(self):
        self.assertEqual(len(CASE_FAMILIES), 20)
        self.assertEqual(tuple(CASE_SPECS), CASE_FAMILIES)

        for family in CASE_FAMILIES:
            with self.subTest(family=family):
                spec = CASE_SPECS[family]
                self.assertEqual(spec.family, family)
                cells = {
                    (world, track): make_case(family, world, track)
                    for world in MATCHED_WORLDS
                    for track in TRACKS
                }
                self.assertEqual(len(cells), 4)
                for (world, track), case in cells.items():
                    self.assertIs(case.definition.track, track)
                    self.assertNotIn(world, case.definition.case_id.lower())

                for world in MATCHED_WORLDS:
                    self.assertEqual(
                        cells[(world, BenchmarkTrack.IDENTIFICATION)].definition.case_id,
                        cells[(world, BenchmarkTrack.DISCOVERY)].definition.case_id,
                    )
                self.assertNotEqual(
                    cells[("historical", BenchmarkTrack.IDENTIFICATION)].definition.case_id,
                    cells[("counterfactual", BenchmarkTrack.IDENTIFICATION)].definition.case_id,
                )

    def test_historical_and_counterfactual_public_payloads_are_matched(self):
        for family in CASE_FAMILIES:
            for track in TRACKS:
                with self.subTest(family=family, track=track.value):
                    historical = _initial_player_payload(
                        make_case(family, "historical", track)
                    )
                    counterfactual = _initial_player_payload(
                        make_case(family, "counterfactual", track)
                    )
                    self.assertEqual(
                        _without_case_id(historical),
                        _without_case_id(counterfactual),
                    )

    def test_identification_and_discovery_share_experimental_resources(self):
        for family in CASE_FAMILIES:
            spec = CASE_SPECS[family]
            for world in MATCHED_WORLDS:
                with self.subTest(family=family, world=world):
                    identification = make_case(
                        family, world, BenchmarkTrack.IDENTIFICATION
                    ).definition
                    discovery = make_case(
                        family, world, BenchmarkTrack.DISCOVERY
                    ).definition

                    self.assertEqual(identification.case_id, discovery.case_id)
                    self.assertEqual(identification.background, discovery.background)
                    self.assertEqual(
                        identification.initial_observations,
                        discovery.initial_observations,
                    )
                    self.assertEqual(
                        identification.resources.instruments,
                        discovery.resources.instruments,
                    )
                    self.assertEqual(
                        identification.resources.controls,
                        discovery.resources.controls,
                    )
                    self.assertEqual(
                        identification.resources.readouts,
                        discovery.resources.readouts,
                    )
                    self.assertEqual(
                        identification.resources.max_replicates,
                        discovery.resources.max_replicates,
                    )
                    self.assertEqual(
                        identification.resources.notes[:-1],
                        discovery.resources.notes,
                    )
                    self.assertIn(
                        "Model specification:",
                        identification.resources.notes[-1],
                    )
                    self.assertIn(
                        "FinalSubmission.model must equal '%s'" % EXPRESSION_MODEL,
                        discovery.resources.notes[-1],
                    )
                    self.assertEqual(
                        discovery.resources.notes[:-1],
                        spec.common_fixed_conditions + spec.common_notes,
                    )
                    self.assertEqual(identification.budget, discovery.budget)
                    self.assertEqual(
                        identification.confidence_threshold,
                        discovery.confidence_threshold,
                    )
                    self.assertEqual(
                        identification.max_hypotheses,
                        discovery.max_hypotheses,
                    )

    def test_complete_discovery_player_payload_does_not_leak_private_contract(self):
        private_keys = {
            "truths",
            "diagnostic_conditions",
            "hidden_conditions",
            "counterfactual_change",
            "world_model",
            "evaluator",
            "_truth",
            "_spec",
            "identification_model",
            "identification_parameters",
            "identification_parameter_specs",
        }
        for family in CASE_FAMILIES:
            spec = CASE_SPECS[family]
            for world in MATCHED_WORLDS:
                with self.subTest(family=family, world=world):
                    payload = _initial_player_payload(
                        make_case(family, world, BenchmarkTrack.DISCOVERY)
                    )
                    self.assertTrue(private_keys.isdisjoint(_nested_keys(payload)))
                    serialized = json.dumps(
                        payload,
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    ).lower()
                    self.assertNotIn(spec.identification_model.lower(), serialized)
                    for parameter in spec.identification_parameters:
                        self.assertNotIn(parameter.lower(), serialized)
                    self.assertNotIn(
                        spec.counterfactual_change.strip().lower(), serialized
                    )

    def test_identification_model_specification_is_public_and_legacy_submission_is_rejected(self):
        for family in CASE_FAMILIES:
            spec = CASE_SPECS[family]
            with self.subTest(family=family):
                contracts = spec.identification_parameter_specs
                self.assertLessEqual(
                    len(contracts), spec.budget * len(spec.readouts)
                )
                self.assertEqual(
                    tuple(item.name for item in contracts),
                    spec.identification_parameters,
                )
                self.assertTrue(all(item.description.strip() for item in contracts))
                self.assertTrue(all(item.unit.strip() for item in contracts))
                self.assertTrue(all(not item.contains(math.inf) for item in contracts))
                for truth in spec.truths.values():
                    values = (
                        truth.parameters
                        if truth.identification_values is None
                        else truth.identification_values
                    )
                    self.assertEqual(set(values), set(spec.identification_parameters))
                    for parameter in contracts:
                        self.assertTrue(
                            parameter.contains(float(values[parameter.name])),
                            "%s truth is outside the public domain" % parameter.name,
                        )

                identification = make_case(
                    family, "historical", BenchmarkTrack.IDENTIFICATION
                )
                public_notes = " ".join(identification.definition.resources.notes)
                self.assertIn(spec.identification_model, public_notes)
                self.assertIn(spec.identification_formula, public_notes)
                for parameter in contracts:
                    self.assertIn(parameter.name, public_notes)
                    self.assertIn(parameter.description, public_notes)

                legacy_parameters = (
                    spec.truths["historical"].identification_values
                    or spec.truths["historical"].parameters
                )
                result = identification.evaluator.evaluate(
                    FinalSubmission(
                        explanation="A legacy named-parameter submission.",
                        model=spec.identification_model,
                        parameters=dict(legacy_parameters),
                    )
                )
                self.assertFalse(result.success)
                self.assertIn("executable expression representation", result.message)

    def test_same_world_identification_and_discovery_return_identical_evidence(self):
        for family in CASE_FAMILIES:
            spec = CASE_SPECS[family]
            conditions = spec.diagnostic_conditions + spec.hidden_conditions
            for world in MATCHED_WORLDS:
                identification = make_case(
                    family, world, BenchmarkTrack.IDENTIFICATION
                )
                discovery = make_case(family, world, BenchmarkTrack.DISCOVERY)
                identification_oracle = CaseOracle(
                    identification.definition, identification.world_model
                )
                discovery_oracle = CaseOracle(
                    discovery.definition, discovery.world_model
                )
                for condition_index, condition in enumerate(conditions):
                    with self.subTest(
                        family=family,
                        world=world,
                        condition=condition_index,
                    ):
                        proposal = _proposal(spec, condition)
                        identification_response = identification_oracle.respond(proposal)
                        discovery_response = discovery_oracle.respond(proposal)
                        self.assertEqual(
                            identification_response.status, OracleStatus.VALID
                        )
                        self.assertEqual(
                            discovery_response.status, OracleStatus.VALID
                        )
                        self.assertEqual(
                            identification_response.evidence,
                            discovery_response.evidence,
                        )

    def test_truth_passes_and_both_false_twins_fail_in_both_tracks(self):
        for family in CASE_FAMILIES:
            spec = CASE_SPECS[family]
            for target_world, twin_world in (
                ("historical", "counterfactual"),
                ("counterfactual", "historical"),
            ):
                truth = truth_submission(
                    spec, target_world, BenchmarkTrack.IDENTIFICATION
                )
                false_twin = truth_submission(
                    spec, twin_world, BenchmarkTrack.DISCOVERY
                )
                results = []
                false_twin_results = []
                for track in TRACKS:
                    with self.subTest(
                        family=family,
                        world=target_world,
                        track=track.value,
                    ):
                        evaluator = make_case(
                            family, target_world, track
                        ).evaluator
                        result = evaluator.evaluate(truth)
                        false_result = evaluator.evaluate(false_twin)
                        self.assertTrue(result.success)
                        self.assertEqual(
                            result.scores["predictive_model_pass"], 1.0
                        )
                        self.assertFalse(false_result.success)
                        self.assertEqual(
                            false_result.scores["predictive_model_pass"], 0.0
                        )
                        results.append(result)
                        false_twin_results.append(false_result)
                self.assertEqual(results[0], results[1])
                self.assertEqual(false_twin_results[0], false_twin_results[1])

    def test_diagnostics_fit_the_budget_and_distinguish_the_two_worlds(self):
        for family in CASE_FAMILIES:
            spec = CASE_SPECS[family]
            historical_parameters = spec.truths["historical"].parameters
            counterfactual_parameters = spec.truths["counterfactual"].parameters
            self.assertEqual(
                sum(
                    historical_parameters[name] != counterfactual_parameters[name]
                    for name in spec.identification_parameters
                ),
                1,
                "%s must change exactly one private mechanism coordinate" % family,
            )
            historical = make_case(
                family, "historical", BenchmarkTrack.IDENTIFICATION
            )
            counterfactual = make_case(
                family, "counterfactual", BenchmarkTrack.IDENTIFICATION
            )
            self.assertGreater(len(spec.diagnostic_conditions), 0)
            self.assertLessEqual(
                len(spec.diagnostic_conditions),
                min(historical.definition.budget, counterfactual.definition.budget),
            )
            historical_oracle = CaseOracle(
                historical.definition, historical.world_model
            )
            counterfactual_oracle = CaseOracle(
                counterfactual.definition, counterfactual.world_model
            )
            distinguishable = False
            for condition_index, condition in enumerate(spec.diagnostic_conditions):
                with self.subTest(family=family, condition=condition_index):
                    proposal = _proposal(spec, condition)
                    historical_response = historical_oracle.respond(proposal)
                    counterfactual_response = counterfactual_oracle.respond(proposal)
                    self.assertEqual(historical_response.status, OracleStatus.VALID)
                    self.assertEqual(counterfactual_response.status, OracleStatus.VALID)
                    for readout in spec.readouts:
                        left = float(
                            historical_response.evidence.measurements[readout.name]
                        )
                        right = float(
                            counterfactual_response.evidence.measurements[readout.name]
                        )
                        resolution = float(readout.resolution or 0.0)
                        if not math.isclose(
                            left,
                            right,
                            rel_tol=0.0,
                            abs_tol=resolution / 2.0,
                        ):
                            distinguishable = True
            self.assertTrue(
                distinguishable,
                "%s has no budget-feasible diagnostic that survives measurement resolution"
                % family,
            )

    def test_oracle_units_and_measurement_resolution_match_public_resources(self):
        for family in CASE_FAMILIES:
            spec = CASE_SPECS[family]
            expected_units = {}
            for readout in spec.readouts:
                self.assertIsInstance(readout.unit, str)
                self.assertTrue(readout.unit.strip())
                self.assertIsNotNone(readout.resolution)
                self.assertTrue(math.isfinite(float(readout.resolution)))
                self.assertGreater(float(readout.resolution), 0.0)
                expected_units[readout.name] = readout.unit

            for world in MATCHED_WORLDS:
                for track in TRACKS:
                    case = make_case(family, world, track)
                    oracle = CaseOracle(case.definition, case.world_model)
                    for condition_index, condition in enumerate(
                        spec.diagnostic_conditions + spec.hidden_conditions
                    ):
                        with self.subTest(
                            family=family,
                            world=world,
                            track=track.value,
                            condition=condition_index,
                        ):
                            response = oracle.respond(_proposal(spec, condition))
                            self.assertEqual(response.status, OracleStatus.VALID)
                            evidence = response.evidence
                            self.assertEqual(evidence.units, expected_units)
                            self.assertEqual(
                                set(evidence.measurements), set(expected_units)
                            )
                            self.assertEqual(
                                set(evidence.uncertainty), set(expected_units)
                            )
                            for readout in spec.readouts:
                                value = evidence.measurements[readout.name]
                                self.assertIsInstance(value, (int, float))
                                self.assertNotIsInstance(value, bool)
                                self.assertTrue(math.isfinite(float(value)))
                                resolution = float(readout.resolution)
                                quotient = float(value) / resolution
                                self.assertTrue(
                                    math.isclose(
                                        quotient,
                                        round(quotient),
                                        rel_tol=0.0,
                                        abs_tol=1.0e-7,
                                    ),
                                    "%s.%s=%r is not aligned to resolution %r"
                                    % (
                                        family,
                                        readout.name,
                                        value,
                                        readout.resolution,
                                    ),
                                )


if __name__ == "__main__":
    unittest.main()
