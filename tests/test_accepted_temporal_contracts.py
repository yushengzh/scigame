"""Acceptance contracts for the temporal cohort reviewed against its sources."""

from __future__ import annotations

import importlib.util
import json
import math
import unittest
from dataclasses import replace
from pathlib import Path

from role_benchmark.cases.matched import (
    MATCHED_WORLDS,
    MatchedFamilySpec,
    make_matched_case,
    truth_submission,
)
from role_benchmark.models import BenchmarkTrack, ExperimentProposal
from role_benchmark.protocols import CaseOracle
from role_benchmark.temporal_cases import TEMPORAL_CASE_SPECS


TRACKS = (BenchmarkTrack.IDENTIFICATION, BenchmarkTrack.DISCOVERY)


def _proposal(spec, condition):
    return ExperimentProposal(
        intent="Exercise a declared temporal-family condition.",
        apparatus=spec.apparatus_name,
        controls=dict(condition),
        readouts=tuple(readout.name for readout in spec.readouts),
        replicates=1,
    )


class AcceptedTemporalContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.specs = tuple(TEMPORAL_CASE_SPECS.items())

    def test_identification_parameter_contract_is_complete_and_public(self):
        for family, spec in self.specs:
            with self.subTest(family=family):
                contracts = spec.identification_parameter_specs
                self.assertLessEqual(
                    len(contracts), spec.budget * len(spec.readouts)
                )
                if all(control.allowed_values for control in spec.controls):
                    unique_conditions = math.prod(
                        len(control.allowed_values) for control in spec.controls
                    )
                    # Fixed observation coverage must leave unobserved inputs.
                    # The episode resource cap is not an observation design.
                    self.assertGreater(unique_conditions, len(spec.diagnostic_conditions))
                    self.assertLessEqual(
                        len(contracts), unique_conditions * len(spec.readouts)
                    )
                self.assertEqual(
                    tuple(item.name for item in contracts),
                    spec.identification_parameters,
                )
                self.assertTrue(all(item.description.strip() for item in contracts))
                self.assertTrue(all(item.unit.strip() for item in contracts))
                self.assertTrue(all(not item.contains(math.inf) for item in contracts))
                for truth in spec.truths.values():
                    values = truth.identification_values or truth.parameters
                    self.assertEqual(set(values), set(spec.identification_parameters))
                    for parameter in contracts:
                        value = float(values[parameter.name])
                        self.assertTrue(math.isfinite(value))
                        self.assertTrue(parameter.contains(value))

                case = make_matched_case(
                    spec, "historical", BenchmarkTrack.IDENTIFICATION
                )
                public_notes = " ".join(case.definition.resources.notes)
                for parameter in contracts:
                    self.assertIn(parameter.name, public_notes)
                    self.assertIn(parameter.description, public_notes)
                    self.assertIn("unit: %s" % parameter.unit, public_notes)
                self.assertIn("admissible:", public_notes)

                def condition_key(condition):
                    return tuple(condition[item.name] for item in spec.controls)

                diagnostic = {
                    condition_key(item) for item in spec.diagnostic_conditions
                }
                hidden = {condition_key(item) for item in spec.hidden_conditions}
                self.assertFalse(diagnostic & hidden)

    def test_truth_passes_false_twin_fails_and_nonfinite_expression_is_rejected(self):
        for family, spec in self.specs:
            for world, twin in (
                ("historical", "counterfactual"),
                ("counterfactual", "historical"),
            ):
                for track in TRACKS:
                    with self.subTest(family=family, world=world, track=track.value):
                        evaluator = make_matched_case(spec, world, track).evaluator
                        self.assertTrue(
                            evaluator.evaluate(truth_submission(spec, world, track)).success
                        )
                        self.assertFalse(
                            evaluator.evaluate(truth_submission(spec, twin, track)).success
                        )

                submission = truth_submission(
                    spec, world, BenchmarkTrack.IDENTIFICATION
                )
                with self.assertRaisesRegex(ValueError, "finite"):
                    replace(
                        submission,
                        parameters={
                            "outputs": {
                                spec.readouts[0].name: math.inf,
                            }
                        },
                    )

    def test_world_model_is_track_invariant_and_matches_private_predictor(self):
        for family, spec in self.specs:
            for world in MATCHED_WORLDS:
                identification = make_matched_case(
                    spec, world, BenchmarkTrack.IDENTIFICATION
                )
                discovery = make_matched_case(
                    spec, world, BenchmarkTrack.DISCOVERY
                )
                identification_oracle = CaseOracle(
                    identification.definition, identification.world_model
                )
                discovery_oracle = CaseOracle(
                    discovery.definition, discovery.world_model
                )
                truth = spec.truths[world]
                for index, condition in enumerate(
                    spec.diagnostic_conditions + spec.hidden_conditions
                ):
                    with self.subTest(family=family, world=world, condition=index):
                        proposal = _proposal(spec, condition)
                        left = identification_oracle.respond(proposal)
                        right = discovery_oracle.respond(proposal)
                        self.assertEqual(left.evidence, right.evidence)
                        exact = spec.predict(truth.parameters, condition)
                        for readout in spec.readouts:
                            observed = left.evidence.measurements[readout.name]
                            allowance = float(readout.resolution or 0.0) / 2.0
                            self.assertTrue(
                                math.isclose(
                                    observed,
                                    exact[readout.name],
                                    rel_tol=1.0e-12,
                                    abs_tol=allowance + 1.0e-12,
                                )
                            )
                            self.assertEqual(
                                left.evidence.units[readout.name], readout.unit
                            )


if __name__ == "__main__":
    unittest.main()
