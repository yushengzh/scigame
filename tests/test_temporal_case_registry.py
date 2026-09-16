from __future__ import annotations

import unittest

from role_benchmark.cases import CASE_FAMILIES
from role_benchmark.models import BenchmarkTrack, ExperimentProposal, OracleStatus
from role_benchmark.protocols import CaseOracle
from role_benchmark.temporal_cases import (
    TEMPORAL_CASE_FAMILIES, TEMPORAL_CASE_SPECS,
    TEMPORAL_CONDITIONS, TEMPORAL_CONDITION_RUNTIME_MAP,
    TEMPORAL_SOURCE_PAPER_IDS, make_temporal_case,
)


class TemporalCaseRegistryTests(unittest.TestCase):
    def test_current_registry_is_complete_and_distinct_from_historical(self):
        self.assertEqual(len(TEMPORAL_CASE_FAMILIES), 30)
        self.assertEqual(tuple(TEMPORAL_CASE_SPECS), TEMPORAL_CASE_FAMILIES)
        self.assertEqual(len(set(TEMPORAL_SOURCE_PAPER_IDS.values())), 29)
        self.assertTrue(set(TEMPORAL_CASE_FAMILIES).isdisjoint(CASE_FAMILIES))
        self.assertIn("temporal_enriched_104003", TEMPORAL_CASE_FAMILIES)
        self.assertNotIn("kz_incompressible_energy_temperature_regimes", TEMPORAL_CASE_FAMILIES)

    def test_all_families_instantiate_both_worlds_and_tracks(self):
        for family in TEMPORAL_CASE_FAMILIES:
            for descriptor in TEMPORAL_CONDITIONS[family]:
                for track in BenchmarkTrack:
                    with self.subTest(family=family, condition=descriptor.condition_id, track=track):
                        case = make_temporal_case(family, descriptor.condition_id, track)
                        self.assertIs(case.definition.track, track)
                        self.assertTrue(case.definition.case_id.startswith("temporal."))
                        self.assertEqual(descriptor.variant_id, "canonical")
                        self.assertEqual(descriptor.dataset_kind.value, "temporal_counterfactual")
            self.assertEqual(TEMPORAL_CONDITION_RUNTIME_MAP[family], {
                "source_reported": "historical", "counterfactual": "counterfactual",
            })

    def test_observations_repeat_and_are_shared_across_task_settings(self):
        for family, spec in TEMPORAL_CASE_SPECS.items():
            for condition in ("source_reported", "counterfactual"):
                with self.subTest(family=family, condition=condition):
                    cases = [make_temporal_case(family, condition, track) for track in BenchmarkTrack]
                    proposal = ExperimentProposal(
                        intent="Measure the relation at a declared experimental condition.",
                        apparatus=spec.apparatus_name,
                        controls=dict(spec.diagnostic_conditions[0]),
                        readouts=tuple(item.name for item in spec.readouts),
                        replicates=1,
                    )
                    oracles = [CaseOracle(case.definition, case.world_model) for case in cases]
                    responses = [oracle.respond(proposal) for oracle in oracles]
                    self.assertTrue(all(item.status is OracleStatus.VALID for item in responses))
                    self.assertEqual(responses[0].evidence, responses[1].evidence)
                    self.assertEqual(oracles[0].respond(proposal).evidence, responses[0].evidence)


if __name__ == "__main__":
    unittest.main()
