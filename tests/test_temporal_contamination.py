from __future__ import annotations

import json
import unittest
from dataclasses import replace
from datetime import date, datetime, timezone
from typing import Optional

from role_benchmark import (
    TEMPORAL_CONTAMINATION_SCHEMA_VERSION,
    DisclosureKind,
    PreEvaluationBenchmarkExposure,
    PreEvaluationExposureStatus,
    PublicDisclosure,
    TemporalContaminationRecord,
    TemporalExposureAssessment,
    TrainingDataCutoff,
    TrainingDataCutoffStatus,
    assess_temporal_exposure,
    temporal_contamination_record_to_payload,
    validate_temporal_contamination_rows,
)


def _record(
    *,
    model_profile_id: str = "player_profile",
    benchmark_instance_id: str = "temporal_family.condition_a.instance_1",
    cutoff: Optional[TrainingDataCutoff] = None,
    exposure: Optional[PreEvaluationBenchmarkExposure] = None,
) -> TemporalContaminationRecord:
    return TemporalContaminationRecord(
        experiment_id="sg_p0_6_001",
        benchmark_release_id="role_benchmark_0_7_0",
        benchmark_instance_id=benchmark_instance_id,
        source_paper_id="paper_2607_01234v2",
        source_version_id="2607.01234v2",
        public_disclosures=(
            PublicDisclosure(
                kind=DisclosureKind.JOURNAL,
                public_at=date(2026, 7, 10),
                evidence_locator="publisher metadata",
            ),
            PublicDisclosure(
                kind=DisclosureKind.ARXIV_V1,
                public_at=date(2026, 7, 1),
                evidence_locator="arXiv version history",
            ),
        ),
        model_profile_id=model_profile_id,
        provider="example_provider",
        model_id="example_model",
        checkpoint_or_snapshot_id="snapshot_2026_06_01",
        training_data_cutoff=cutoff
        or TrainingDataCutoff(
            status=TrainingDataCutoffStatus.DOCUMENTED,
            cutoff_date=date(2026, 6, 1),
            evidence_locator="provider model card",
            uncertainty="The provider reports a day-level cutoff.",
        ),
        evaluated_at=datetime(2026, 8, 1, 12, 0, tzinfo=timezone.utc),
        network_access=False,
        retrieval_access=False,
        pre_evaluation_benchmark_exposure=exposure
        or PreEvaluationBenchmarkExposure(
            status=PreEvaluationExposureStatus.NONE_DOCUMENTED,
            evidence="No exposure was documented in the evaluation record.",
        ),
    )


class TemporalContaminationContractTests(unittest.TestCase):
    def test_payload_derives_earliest_disclosure_and_post_checkpoint_assessment(self):
        record = _record()
        payload = temporal_contamination_record_to_payload(
            record,
            minimum_buffer_days=14,
        )
        self.assertEqual(
            payload["schema_version"], TEMPORAL_CONTAMINATION_SCHEMA_VERSION
        )
        self.assertEqual(payload["earliest_public_at"], "2026-07-01")
        self.assertEqual(payload["assessment"], "post_checkpoint_eligible")
        self.assertEqual(payload["minimum_buffer_days"], 14)
        self.assertEqual(payload["model_profile_id"], "player_profile")
        self.assertEqual(
            payload["benchmark_instance_id"],
            "temporal_family.condition_a.instance_1",
        )

    def test_unknown_cutoff_or_exposure_stays_exposure_unknown(self):
        unknown_cutoff = TrainingDataCutoff(
            status=TrainingDataCutoffStatus.UNKNOWN,
            cutoff_date=None,
            evidence_locator=None,
            uncertainty="The provider has not documented an exact cutoff.",
        )
        record = _record(cutoff=unknown_cutoff)
        self.assertIs(
            assess_temporal_exposure(record, minimum_buffer_days=0),
            TemporalExposureAssessment.EXPOSURE_UNKNOWN,
        )
        payload = temporal_contamination_record_to_payload(
            record,
            minimum_buffer_days=0,
        )
        serialized = json.dumps(payload, sort_keys=True)
        self.assertEqual(payload["training_data_cutoff"]["date"], None)
        self.assertEqual(payload["assessment"], "exposure_unknown")
        self.assertNotIn("unseen", serialized.lower())
        self.assertNotIn("contamination_free", serialized.lower())

        unknown_exposure = PreEvaluationBenchmarkExposure(
            status=PreEvaluationExposureStatus.UNKNOWN,
            evidence="Pre-evaluation benchmark exposure was not recorded.",
        )
        record = _record(exposure=unknown_exposure)
        self.assertIs(
            assess_temporal_exposure(record, minimum_buffer_days=0),
            TemporalExposureAssessment.EXPOSURE_UNKNOWN,
        )

    def test_known_exposure_overrides_publication_timing(self):
        record = _record(
            exposure=PreEvaluationBenchmarkExposure(
                status=PreEvaluationExposureStatus.KNOWN,
                evidence="The model-development team received the case before evaluation.",
            )
        )
        self.assertIs(
            assess_temporal_exposure(record, minimum_buffer_days=14),
            TemporalExposureAssessment.KNOWN_EXPOSED,
        )

    def test_same_day_cutoff_is_not_post_checkpoint(self):
        record = _record(
            cutoff=TrainingDataCutoff(
                status=TrainingDataCutoffStatus.DOCUMENTED,
                cutoff_date=date(2026, 7, 1),
                evidence_locator="provider model card",
                uncertainty="The provider reports a day-level cutoff.",
            )
        )
        self.assertIs(
            assess_temporal_exposure(record, minimum_buffer_days=0),
            TemporalExposureAssessment.NOT_POST_CHECKPOINT,
        )

    def test_rows_require_one_record_per_model_profile_and_instance(self):
        models = ("player_profile", "comparison_profile")
        instances = (
            "temporal_family.condition_a.instance_1",
            "temporal_family.condition_b.instance_1",
        )
        rows = tuple(
            replace(
                _record(),
                model_profile_id=model,
                benchmark_instance_id=instance,
            )
            for model in models
            for instance in instances
        )
        self.assertEqual(
            validate_temporal_contamination_rows(
                rows,
                model_profile_ids=models,
                benchmark_instance_ids=instances,
            ),
            rows,
        )

        with self.assertRaisesRegex(ValueError, "Cartesian product"):
            validate_temporal_contamination_rows(
                rows[:-1],
                model_profile_ids=models,
                benchmark_instance_ids=instances,
            )
        with self.assertRaisesRegex(ValueError, "duplicate model-profile"):
            validate_temporal_contamination_rows(
                rows + (rows[0],),
                model_profile_ids=models,
                benchmark_instance_ids=instances,
            )

    def test_cutoff_and_timestamp_cannot_claim_missing_precision(self):
        with self.assertRaisesRegex(ValueError, "must not invent"):
            TrainingDataCutoff(
                status=TrainingDataCutoffStatus.UNKNOWN,
                cutoff_date=date(2026, 6, 1),
                evidence_locator=None,
                uncertainty="The exact cutoff is not documented.",
            )
        with self.assertRaisesRegex(ValueError, "UTC offset"):
            replace(_record(), evaluated_at=datetime(2026, 8, 1, 12, 0))


if __name__ == "__main__":
    unittest.main()
