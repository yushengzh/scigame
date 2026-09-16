"""Regression tests for deterministic, counterbalanced public instance IDs."""

import unittest
from collections import Counter

from role_benchmark import BenchmarkTrack
from role_benchmark.cases import CASE_FAMILIES, CASE_SPECS, MATCHED_WORLDS, make_case


class WorldNeutralCaseIdTest(unittest.TestCase):
    def test_instance_ids_share_world_across_tracks_and_are_counterbalanced(self):
        historical_suffixes = []
        counterfactual_suffixes = []
        for family in CASE_FAMILIES:
            ids = {}
            for world in MATCHED_WORLDS:
                identification = make_case(
                    family, world, BenchmarkTrack.IDENTIFICATION
                ).definition.case_id
                discovery = make_case(
                    family, world, BenchmarkTrack.DISCOVERY
                ).definition.case_id
                self.assertEqual(identification.rsplit(".", 1)[0], discovery.rsplit(".", 1)[0])
                self.assertTrue(identification.endswith(".identification"))
                self.assertTrue(discovery.endswith(".discovery"))
                self.assertNotIn("world", identification.lower())
                self.assertNotIn(world, identification.lower().split(".")[2:])
                ids[world] = identification

            self.assertNotEqual(ids["historical"], ids["counterfactual"])
            historical_suffixes.append(ids["historical"].split(".")[-2])
            counterfactual_suffixes.append(ids["counterfactual"].split(".")[-2])

        expected = Counter({"instance_1": 10, "instance_2": 10})
        self.assertEqual(Counter(historical_suffixes), expected)
        self.assertEqual(Counter(counterfactual_suffixes), expected)
        self.assertEqual(
            sum(spec.swap_public_instance_ids for spec in CASE_SPECS.values()),
            10,
        )


if __name__ == "__main__":
    unittest.main()
