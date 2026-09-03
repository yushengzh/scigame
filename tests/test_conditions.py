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
    TEMPORAL_SOURCE_CONDITIONS,
    TEMPORAL_SOURCE_CONDITION_RUNTIME_MAP,
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
        variant_id="public_v1",
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
                "variant_id": "public_v1",
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
                variant_id="public_v1",
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

    def test_temporal_registry_has_two_source_reported_conditions_per_family(self):
        self.assertEqual(tuple(TEMPORAL_SOURCE_CONDITIONS), TEMPORAL_CASE_FAMILIES)
        self.assertEqual(
            tuple(TEMPORAL_SOURCE_CONDITION_RUNTIME_MAP), TEMPORAL_CASE_FAMILIES
        )
        self.assertEqual(tuple(TEMPORAL_SOURCE_PAPER_IDS), TEMPORAL_CASE_FAMILIES)
        self.assertEqual(tuple(TEMPORAL_SOURCE_VERSION_IDS), TEMPORAL_CASE_FAMILIES)
        for family_id in TEMPORAL_CASE_FAMILIES:
            with self.subTest(family_id=family_id):
                descriptors = TEMPORAL_SOURCE_CONDITIONS[family_id]
                self.assertEqual(
                    tuple(item.condition_id for item in descriptors),
                    ("condition_a", "condition_b"),
                )
                self.assertTrue(
                    all(
                        item.dataset_kind is DatasetKind.TEMPORAL
                        and item.condition_role is ConditionRole.SOURCE_REPORTED
                        and item.family_id == family_id
                        for item in descriptors
                    )
                )
                runtime_map = TEMPORAL_SOURCE_CONDITION_RUNTIME_MAP[family_id]
                self.assertEqual(set(runtime_map), {"condition_a", "condition_b"})
                # Old storage values do not alter the descriptors' source roles.
                self.assertEqual(
                    set(runtime_map.values()),
                    {"historical", "counterfactual"},
                )
                self.assertTrue(TEMPORAL_SOURCE_PAPER_IDS[family_id].startswith("arxiv:"))
                self.assertRegex(
                    TEMPORAL_SOURCE_VERSION_IDS[family_id],
                    r"^[0-9]{4}\.[0-9]{4,5}v[0-9]+$",
                )

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
