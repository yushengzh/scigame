from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from types import MappingProxyType
from unittest import mock

import experiments.core160_pack as core160_pack
from experiments.core160_pack import (
    ACCEPTED_TEMPORAL_COUNTERFACTUAL_ARTIFACTS,
    CORE160_TEMPORAL_COUNTERFACTUAL_CONDITION_ID,
    CORE160_TEMPORAL_SOURCE_CONDITION_ID,
    CORE160_TEMPORAL_SOURCE_RELATION_ID,
    CORE160_TEMPORAL_VARIANT_ID,
    Core160TemporalPackError,
    load_accepted_temporal_pack,
    load_core160_temporal_pack,
)
from experiments.core160_release import load_core20_temporal_release
from role_benchmark.cases.matched import (
    MatchedFamilySpec,
    make_matched_case,
    truth_submission,
)
from role_benchmark.conditions import ConditionRole, DatasetKind
from role_benchmark.models import BenchmarkTrack


REPO_ROOT = Path(__file__).resolve().parents[1]


class Core160TemporalPackTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.release = load_core20_temporal_release(REPO_ROOT)
        cls.pack = load_core160_temporal_pack(REPO_ROOT)

    def test_family_order_identity_and_runner_mappings_match_the_release(self):
        pack = self.pack
        release = self.release
        self.assertEqual(len(pack.records), 20)
        self.assertEqual(pack.family_ids, release.family_ids)
        self.assertEqual(len(set(pack.family_ids)), 20)
        self.assertEqual(pack.variant_ids, (CORE160_TEMPORAL_VARIANT_ID,) * 20)

        for mapping in (
            pack.spec_by_family,
            pack.specifications,
            pack.conditions_by_family,
            pack.conditions,
            pack.source_paper_ids,
            pack.source_version_ids,
            pack.requests,
            pack.runtime_truth_keys,
        ):
            self.assertIsInstance(mapping, MappingProxyType)
            self.assertEqual(tuple(mapping), release.family_ids)

        self.assertEqual(tuple(pack.source_paper_ids.values()), release.paper_ids)
        self.assertEqual(
            tuple(pack.source_version_ids.values()),
            release.arxiv_versioned_ids,
        )
        for family_id in pack.family_ids:
            self.assertEqual(
                tuple(pack.specifications[family_id]),
                (CORE160_TEMPORAL_VARIANT_ID,),
            )
            self.assertIs(
                pack.specifications[family_id][CORE160_TEMPORAL_VARIANT_ID],
                pack.spec_by_family[family_id],
            )

    def test_requests_select_one_parameter_and_only_the_full_target_spec(self):
        source_specs = self.release.spec_by_family
        for record in self.pack.records:
            with self.subTest(family=record.family_id):
                self.assertIsInstance(record.spec, MatchedFamilySpec)
                self.assertEqual(record.spec.family, record.family_id)
                self.assertEqual(record.variant_id, CORE160_TEMPORAL_VARIANT_ID)
                self.assertTrue(record.request.parameter_name)
                self.assertTrue(record.request.unit)
                self.assertEqual(
                    record.request.artifact_path,
                    next(
                        path
                        for path in core160_pack.CORE160_TEMPORAL_COUNTERFACTUAL_ARTIFACTS
                        if record.family_id
                        in {
                            item["family_id"]
                            for item in json.loads(
                                (REPO_ROOT / path).read_text(encoding="utf-8")
                            )["families"]
                        }
                    ),
                )

                source = source_specs[record.family_id]
                self.assertEqual(
                    record.spec.truths["historical"].parameters,
                    source.truth.parameters,
                )
                changed = tuple(
                    name
                    for name in source.truth.parameters
                    if source.truth.parameters[name]
                    != record.spec.truths["counterfactual"].parameters[name]
                )
                self.assertEqual(changed, (record.request.parameter_name,))
                self.assertEqual(
                    record.spec.truths["counterfactual"].parameters[
                        record.request.parameter_name
                    ],
                    record.request.target_value,
                )
                parameter = next(
                    item
                    for item in record.spec.identification_parameter_specs
                    if item.name == record.request.parameter_name
                )
                self.assertEqual(parameter.unit, record.request.unit)
                self.assertEqual(record.spec.controls, source.controls)
                self.assertEqual(record.spec.readouts, source.readouts)
                self.assertEqual(
                    record.spec.identification_formula,
                    source.identification_formula,
                )
                self.assertEqual(
                    record.spec.diagnostic_conditions,
                    source.diagnostic_conditions,
                )
                self.assertEqual(
                    record.spec.hidden_conditions,
                    source.hidden_conditions,
                )

    def test_exactly_forty_temporal_counterfactual_conditions_are_declared(self):
        self.assertEqual(
            sum(len(item.conditions) for item in self.pack.records),
            40,
        )
        for record in self.pack.records:
            with self.subTest(family=record.family_id):
                source, counterfactual = record.conditions
                self.assertEqual(
                    source.dataset_kind,
                    DatasetKind.TEMPORAL_COUNTERFACTUAL,
                )
                self.assertEqual(source.family_id, record.family_id)
                self.assertEqual(source.variant_id, CORE160_TEMPORAL_VARIANT_ID)
                self.assertEqual(
                    source.condition_id,
                    CORE160_TEMPORAL_SOURCE_CONDITION_ID,
                )
                self.assertEqual(
                    source.condition_role,
                    ConditionRole.SOURCE_REPORTED,
                )
                self.assertEqual(
                    source.source_condition_id,
                    CORE160_TEMPORAL_SOURCE_RELATION_ID,
                )
                self.assertEqual(
                    counterfactual.dataset_kind,
                    DatasetKind.TEMPORAL_COUNTERFACTUAL,
                )
                self.assertEqual(counterfactual.family_id, record.family_id)
                self.assertEqual(
                    counterfactual.variant_id,
                    CORE160_TEMPORAL_VARIANT_ID,
                )
                self.assertEqual(
                    counterfactual.condition_id,
                    CORE160_TEMPORAL_COUNTERFACTUAL_CONDITION_ID,
                )
                self.assertEqual(
                    counterfactual.condition_role,
                    ConditionRole.COUNTERFACTUAL,
                )
                self.assertIsNone(counterfactual.source_condition_id)
                self.assertEqual(
                    dict(record.runtime_truth_keys),
                    {
                        CORE160_TEMPORAL_SOURCE_CONDITION_ID: "historical",
                        CORE160_TEMPORAL_COUNTERFACTUAL_CONDITION_ID: (
                            "counterfactual"
                        ),
                    },
                )

    def test_all_eighty_known_truth_cells_pass_with_neutral_case_ids(self):
        forbidden_case_id_tokens = (
            "historical",
            "counterfactual",
            "source_reported",
            "easy",
            "hard",
        )
        checked = 0
        for record in self.pack.records:
            for condition in record.conditions:
                world = record.runtime_truth_keys[condition.condition_id]
                for track in (
                    BenchmarkTrack.IDENTIFICATION,
                    BenchmarkTrack.DISCOVERY,
                ):
                    with self.subTest(
                        family=record.family_id,
                        condition=condition.condition_id,
                        track=track.value,
                    ):
                        case = make_matched_case(record.spec, world, track)
                        expected_instance = 1 if world == "historical" else 2
                        self.assertEqual(
                            case.definition.case_id,
                            "core160.family_%02d.authored_v1.instance_%d"
                            % (record.release_order, expected_instance),
                        )
                        for token in forbidden_case_id_tokens:
                            self.assertNotIn(token, case.definition.case_id)
                        result = case.evaluator.evaluate(
                            truth_submission(record.spec, world, track)
                        )
                        self.assertTrue(result.success, result.message)
                        self.assertEqual(
                            result.scores["predictive_model_pass"], 1.0
                        )
                        self.assertEqual(
                            result.scores["held_out_prediction_score"], 1.0
                        )
                        self.assertEqual(
                            result.scores["hidden_test_mean_scaled_error"], 0.0
                        )
                        self.assertEqual(
                            result.scores["hidden_test_max_scaled_error"], 0.0
                        )
                        checked += 1
        self.assertEqual(checked, 80)

    def test_nonzero_blocked_summary_is_rejected(self):
        first, second = core160_pack.CORE160_TEMPORAL_COUNTERFACTUAL_ARTIFACTS
        payload = json.loads((REPO_ROOT / first).read_text(encoding="utf-8"))
        payload["summary"]["families_blocked"] = 1
        with tempfile.TemporaryDirectory() as directory:
            changed = Path(directory) / "changed.json"
            changed.write_text(json.dumps(payload), encoding="utf-8")
            with mock.patch.object(
                core160_pack,
                "CORE160_TEMPORAL_COUNTERFACTUAL_ARTIFACTS",
                (changed, REPO_ROOT / second),
            ):
                with self.assertRaisesRegex(
                    Core160TemporalPackError,
                    "zero blocked families",
                ):
                    load_core160_temporal_pack(REPO_ROOT)


class AcceptedTemporalPackTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pack = load_accepted_temporal_pack(REPO_ROOT)

    def test_all_twenty_one_accepted_families_and_artifacts_are_present(self):
        pack = self.pack
        self.assertEqual(len(pack.records), 21)
        self.assertEqual(len(set(pack.family_ids)), 21)
        self.assertIn("temporal_source_3047", pack.family_ids)
        self.assertEqual(pack.family_ids[-1], "temporal_source_3047")
        self.assertEqual(
            {
                record.request.artifact_path
                for record in pack.records
            },
            set(ACCEPTED_TEMPORAL_COUNTERFACTUAL_ARTIFACTS),
        )
        self.assertEqual(
            sum(len(record.conditions) for record in pack.records),
            42,
        )

    def test_all_eighty_four_accepted_known_truth_cells_pass(self):
        forbidden_case_id_tokens = (
            "historical",
            "counterfactual",
            "source_reported",
            "easy",
            "hard",
        )
        checked_by_family = {family_id: 0 for family_id in self.pack.family_ids}
        for record in self.pack.records:
            self.assertEqual(
                tuple(condition.condition_id for condition in record.conditions),
                (
                    CORE160_TEMPORAL_SOURCE_CONDITION_ID,
                    CORE160_TEMPORAL_COUNTERFACTUAL_CONDITION_ID,
                ),
            )
            for condition in record.conditions:
                world = record.runtime_truth_keys[condition.condition_id]
                for track in (
                    BenchmarkTrack.IDENTIFICATION,
                    BenchmarkTrack.DISCOVERY,
                ):
                    with self.subTest(
                        family=record.family_id,
                        condition=condition.condition_id,
                        track=track.value,
                    ):
                        case = make_matched_case(record.spec, world, track)
                        expected_instance = 1 if world == "historical" else 2
                        self.assertEqual(
                            case.definition.case_id,
                            "temporal.family_%02d.authored_v1.instance_%d"
                            % (record.release_order, expected_instance),
                        )
                        for token in forbidden_case_id_tokens:
                            self.assertNotIn(token, case.definition.case_id)
                        result = case.evaluator.evaluate(
                            truth_submission(record.spec, world, track)
                        )
                        self.assertTrue(result.success, result.message)
                        self.assertEqual(
                            result.scores["predictive_model_pass"], 1.0
                        )
                        self.assertEqual(
                            result.scores["held_out_prediction_score"], 1.0
                        )
                        self.assertEqual(
                            result.scores["hidden_test_mean_scaled_error"], 0.0
                        )
                        self.assertEqual(
                            result.scores["hidden_test_max_scaled_error"], 0.0
                        )
                        checked_by_family[record.family_id] += 1

        self.assertEqual(set(checked_by_family.values()), {4})
        self.assertEqual(sum(checked_by_family.values()), 84)


if __name__ == "__main__":
    unittest.main()
