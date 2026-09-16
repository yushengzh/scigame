from __future__ import annotations

import unittest

from role_benchmark import (
    CONDITION_DESCRIPTOR_SCHEMA_VERSION,
    ConditionDescriptor,
    ConditionRole,
    DatasetKind,
    condition_descriptor_to_payload,
    validate_condition_descriptors,
)
from role_benchmark.temporal_cases import (
    TEMPORAL_CASE_FAMILIES,
    TEMPORAL_CONDITIONS,
    TEMPORAL_CONDITION_RUNTIME_MAP,
    TEMPORAL_SCIENCE_CARDS,
    TEMPORAL_SOURCE_PAPER_IDS,
    TEMPORAL_SOURCE_VERSION_IDS,
)


def _descriptor(
    role: ConditionRole,
    *,
    condition_id: str,
) -> ConditionDescriptor:
    return ConditionDescriptor(
        dataset_kind=DatasetKind.HISTORICAL_COUNTERFACTUAL,
        family_id="example_family",
        variant_id="test_variant",
        condition_id=condition_id,
        condition_role=role,
    )


class ConditionContractTests(unittest.TestCase):
    def test_curated_pair_requires_one_historical_and_one_counterfactual(self):
        pair = validate_condition_descriptors(
            (
                _descriptor(ConditionRole.HISTORICAL, condition_id="historical"),
                _descriptor(
                    ConditionRole.COUNTERFACTUAL,
                    condition_id="counterfactual",
                ),
            )
        )
        self.assertEqual(
            {item.condition_role for item in pair},
            {ConditionRole.HISTORICAL, ConditionRole.COUNTERFACTUAL},
        )
        payload = condition_descriptor_to_payload(pair[0])
        self.assertEqual(
            payload,
            {
                "schema_version": CONDITION_DESCRIPTOR_SCHEMA_VERSION,
                "dataset_kind": "historical_counterfactual",
                "family_id": "example_family",
                "variant_id": "test_variant",
                "condition_id": "historical",
                "condition_role": "historical",
                "source_condition_id": None,
            },
        )

        with self.assertRaisesRegex(ValueError, "exactly one historical"):
            validate_condition_descriptors(
                (
                    _descriptor(
                        ConditionRole.HISTORICAL,
                        condition_id="condition_a",
                    ),
                    _descriptor(
                        ConditionRole.HISTORICAL,
                        condition_id="condition_b",
                    ),
                )
            )
        with self.assertRaisesRegex(ValueError, "historical or counterfactual"):
            ConditionDescriptor(
                dataset_kind=DatasetKind.HISTORICAL_COUNTERFACTUAL,
                family_id="example_family",
                variant_id="test_variant",
                condition_id="condition_a",
                condition_role=ConditionRole.SOURCE_REPORTED,
            )

    def test_temporal_conditions_require_source_role_and_neutral_ids(self):
        with self.assertRaisesRegex(ValueError, "source_reported"):
            ConditionDescriptor(
                dataset_kind=DatasetKind.TEMPORAL,
                family_id="example_family",
                variant_id="source_reported_v1",
                condition_id="condition_a",
                condition_role=ConditionRole.HISTORICAL,
                source_condition_id="source_condition_a",
            )
        for condition_id in (
            "historical",
            "counterfactual_branch",
            "easy_condition",
            "hard_condition",
        ):
            with self.subTest(condition_id=condition_id):
                with self.assertRaisesRegex(ValueError, "must not encode"):
                    ConditionDescriptor(
                        dataset_kind=DatasetKind.TEMPORAL,
                        family_id="example_family",
                        variant_id="source_reported_v1",
                        condition_id=condition_id,
                        condition_role=ConditionRole.SOURCE_REPORTED,
                        source_condition_id="source_condition_a",
                    )

    def test_temporal_registry_has_source_and_authored_conditions_per_family(self):
        self.assertEqual(tuple(TEMPORAL_CONDITIONS), TEMPORAL_CASE_FAMILIES)
        self.assertEqual(
            tuple(TEMPORAL_CONDITION_RUNTIME_MAP), TEMPORAL_CASE_FAMILIES
        )
        self.assertEqual(tuple(TEMPORAL_SOURCE_PAPER_IDS), TEMPORAL_CASE_FAMILIES)
        self.assertEqual(tuple(TEMPORAL_SOURCE_VERSION_IDS), TEMPORAL_CASE_FAMILIES)
        for family_id in TEMPORAL_CASE_FAMILIES:
            with self.subTest(family_id=family_id):
                descriptors = TEMPORAL_CONDITIONS[family_id]
                self.assertEqual(
                    tuple(item.condition_id for item in descriptors),
                    ("source_reported", "counterfactual"),
                )
                self.assertTrue(
                    all(
                        item.dataset_kind is DatasetKind.TEMPORAL_COUNTERFACTUAL
                        and item.family_id == family_id
                        for item in descriptors
                    )
                )
                runtime_map = TEMPORAL_CONDITION_RUNTIME_MAP[family_id]
                self.assertEqual(set(runtime_map), {"source_reported", "counterfactual"})
                self.assertEqual(
                    [item.condition_role for item in descriptors],
                    [ConditionRole.SOURCE_REPORTED, ConditionRole.COUNTERFACTUAL],
                )
                # Runtime world keys do not alter the source/authored distinction.
                self.assertEqual(
                    set(runtime_map.values()),
                    {"historical", "counterfactual"},
                )
                publication = TEMPORAL_SCIENCE_CARDS[family_id]["publication"]
                self.assertEqual(TEMPORAL_SOURCE_PAPER_IDS[family_id],
                                 "doi:" + publication["doi"])
                self.assertEqual(TEMPORAL_SOURCE_VERSION_IDS[family_id],
                                 publication.get("source_arxiv_version"))
                version = TEMPORAL_SOURCE_VERSION_IDS[family_id]
                if version is not None:
                    self.assertRegex(version, r"^[0-9]{4}\.[0-9]{4,5}v[0-9]+$")

        self.assertEqual(len(set(TEMPORAL_SOURCE_PAPER_IDS.values())), 29)

    def test_temporal_counterfactual_pair_has_distinct_source_and_authored_roles(self):
        source = ConditionDescriptor(
            dataset_kind=DatasetKind.TEMPORAL_COUNTERFACTUAL,
            family_id="example_family",
            variant_id="temporal_counterfactual_v1",
            condition_id="source_reported",
            condition_role=ConditionRole.SOURCE_REPORTED,
            source_condition_id="paper_relation",
        )
        authored = ConditionDescriptor(
            dataset_kind=DatasetKind.TEMPORAL_COUNTERFACTUAL,
            family_id="example_family",
            variant_id="temporal_counterfactual_v1",
            condition_id="counterfactual",
            condition_role=ConditionRole.COUNTERFACTUAL,
        )

        pair = validate_condition_descriptors((source, authored))

        self.assertEqual(
            tuple(item.condition_role for item in pair),
            (ConditionRole.SOURCE_REPORTED, ConditionRole.COUNTERFACTUAL),
        )
        self.assertEqual(
            condition_descriptor_to_payload(source),
            {
                "schema_version": CONDITION_DESCRIPTOR_SCHEMA_VERSION,
                "dataset_kind": "temporal_counterfactual",
                "family_id": "example_family",
                "variant_id": "temporal_counterfactual_v1",
                "condition_id": "source_reported",
                "condition_role": "source_reported",
                "source_condition_id": "paper_relation",
            },
        )
        self.assertIsNone(
            condition_descriptor_to_payload(authored)["source_condition_id"]
        )

    def test_temporal_counterfactual_descriptor_enforces_provenance_boundary(self):
        with self.assertRaisesRegex(ValueError, "require source_condition_id"):
            ConditionDescriptor(
                dataset_kind=DatasetKind.TEMPORAL_COUNTERFACTUAL,
                family_id="example_family",
                variant_id="temporal_counterfactual_v1",
                condition_id="source_reported",
                condition_role=ConditionRole.SOURCE_REPORTED,
            )
        with self.assertRaisesRegex(ValueError, "must not set source_condition_id"):
            ConditionDescriptor(
                dataset_kind=DatasetKind.TEMPORAL_COUNTERFACTUAL,
                family_id="example_family",
                variant_id="temporal_counterfactual_v1",
                condition_id="counterfactual",
                condition_role=ConditionRole.COUNTERFACTUAL,
                source_condition_id="paper_relation",
            )
        with self.assertRaisesRegex(ValueError, "source condition_id"):
            ConditionDescriptor(
                dataset_kind=DatasetKind.TEMPORAL_COUNTERFACTUAL,
                family_id="example_family",
                variant_id="temporal_counterfactual_v1",
                condition_id="historical",
                condition_role=ConditionRole.SOURCE_REPORTED,
                source_condition_id="paper_relation",
            )
        with self.assertRaisesRegex(ValueError, "source_reported or counterfactual"):
            ConditionDescriptor(
                dataset_kind=DatasetKind.TEMPORAL_COUNTERFACTUAL,
                family_id="example_family",
                variant_id="temporal_counterfactual_v1",
                condition_id="condition_a",
                condition_role=ConditionRole.HISTORICAL,
            )

    def test_temporal_counterfactual_pair_requires_one_of_each_role(self):
        source_a = ConditionDescriptor(
            dataset_kind=DatasetKind.TEMPORAL_COUNTERFACTUAL,
            family_id="example_family",
            variant_id="temporal_counterfactual_v1",
            condition_id="condition_a",
            condition_role=ConditionRole.SOURCE_REPORTED,
            source_condition_id="paper_relation_a",
        )
        source_b = ConditionDescriptor(
            dataset_kind=DatasetKind.TEMPORAL_COUNTERFACTUAL,
            family_id="example_family",
            variant_id="temporal_counterfactual_v1",
            condition_id="condition_b",
            condition_role=ConditionRole.SOURCE_REPORTED,
            source_condition_id="paper_relation_b",
        )
        with self.assertRaisesRegex(ValueError, "exactly one source_reported"):
            validate_condition_descriptors((source_a, source_b))

    def test_condition_sets_reject_duplicate_or_mismatched_descriptors(self):
        historical = _descriptor(
            ConditionRole.HISTORICAL,
            condition_id="condition_a",
        )
        with self.assertRaisesRegex(ValueError, "condition_id values must be unique"):
            validate_condition_descriptors(
                (
                    historical,
                    _descriptor(
                        ConditionRole.COUNTERFACTUAL,
                        condition_id="condition_a",
                    ),
                )
            )
        with self.assertRaisesRegex(ValueError, "variant_id"):
            validate_condition_descriptors(
                (
                    historical,
                    ConditionDescriptor(
                        dataset_kind=DatasetKind.HISTORICAL_COUNTERFACTUAL,
                        family_id="example_family",
                        variant_id="alternate_v1",
                        condition_id="condition_b",
                        condition_role=ConditionRole.COUNTERFACTUAL,
                    ),
                )
            )


if __name__ == "__main__":
    unittest.main()
