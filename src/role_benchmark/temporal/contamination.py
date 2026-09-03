"""Minimal P0.6 exposure records for source-reported temporal cases.

Each record is one model-profile by temporal benchmark-instance row.  The
contract records what is known and deliberately has no ``unseen`` or
``contamination_free`` state: missing cutoff or exposure evidence remains
explicitly unknown.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from enum import Enum
from typing import Any, Dict, Iterable, Optional, Sequence, Tuple


TEMPORAL_CONTAMINATION_SCHEMA_VERSION = (
    "role_benchmark.temporal_contamination.v1"
)


class DisclosureKind(str, Enum):
    ARXIV_V1 = "arxiv_v1"
    JOURNAL = "journal"
    CONFERENCE = "conference"
    CODE = "code"
    DATA = "data"
    OTHER = "other"


class TrainingDataCutoffStatus(str, Enum):
    DOCUMENTED = "documented"
    UNKNOWN = "unknown"


class PreEvaluationExposureStatus(str, Enum):
    KNOWN = "known"
    NONE_DOCUMENTED = "none_documented"
    UNKNOWN = "unknown"


class TemporalExposureAssessment(str, Enum):
    POST_CHECKPOINT_ELIGIBLE = "post_checkpoint_eligible"
    NOT_POST_CHECKPOINT = "not_post_checkpoint"
    KNOWN_EXPOSED = "known_exposed"
    EXPOSURE_UNKNOWN = "exposure_unknown"


def _require_text(value: str, label: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("%s must be non-empty text" % label)


def _require_date(value: date, label: str) -> None:
    if type(value) is not date:
        raise ValueError("%s must be a date" % label)


@dataclass(frozen=True)
class PublicDisclosure:
    kind: DisclosureKind
    public_at: date
    evidence_locator: str

    def __post_init__(self) -> None:
        if not isinstance(self.kind, DisclosureKind):
            raise ValueError("disclosure kind must be a DisclosureKind")
        _require_date(self.public_at, "public_at")
        _require_text(self.evidence_locator, "evidence_locator")


@dataclass(frozen=True)
class TrainingDataCutoff:
    status: TrainingDataCutoffStatus
    cutoff_date: Optional[date]
    evidence_locator: Optional[str]
    uncertainty: str

    def __post_init__(self) -> None:
        if not isinstance(self.status, TrainingDataCutoffStatus):
            raise ValueError("cutoff status must be a TrainingDataCutoffStatus")
        _require_text(self.uncertainty, "cutoff uncertainty")
        if self.status is TrainingDataCutoffStatus.DOCUMENTED:
            if self.cutoff_date is None:
                raise ValueError("documented cutoff requires cutoff_date")
            _require_date(self.cutoff_date, "cutoff_date")
            if self.evidence_locator is None:
                raise ValueError("documented cutoff requires evidence_locator")
            _require_text(self.evidence_locator, "cutoff evidence_locator")
            return
        if self.cutoff_date is not None or self.evidence_locator is not None:
            raise ValueError(
                "unknown cutoff must not invent a date or evidence locator"
            )


@dataclass(frozen=True)
class PreEvaluationBenchmarkExposure:
    status: PreEvaluationExposureStatus
    evidence: str

    def __post_init__(self) -> None:
        if not isinstance(self.status, PreEvaluationExposureStatus):
            raise ValueError(
                "exposure status must be a PreEvaluationExposureStatus"
            )
        _require_text(self.evidence, "pre-evaluation exposure evidence")


@dataclass(frozen=True)
class TemporalContaminationRecord:
    """One model-profile by temporal benchmark-instance exposure row."""

    experiment_id: str
    benchmark_release_id: str
    benchmark_instance_id: str
    source_paper_id: str
    source_version_id: str
    public_disclosures: Tuple[PublicDisclosure, ...]
    model_profile_id: str
    provider: str
    model_id: str
    checkpoint_or_snapshot_id: str
    training_data_cutoff: TrainingDataCutoff
    evaluated_at: datetime
    network_access: bool
    retrieval_access: bool
    pre_evaluation_benchmark_exposure: PreEvaluationBenchmarkExposure

    def __post_init__(self) -> None:
        for label in (
            "experiment_id",
            "benchmark_release_id",
            "benchmark_instance_id",
            "source_paper_id",
            "source_version_id",
            "model_profile_id",
            "provider",
            "model_id",
            "checkpoint_or_snapshot_id",
        ):
            _require_text(getattr(self, label), label)
        if (
            not isinstance(self.public_disclosures, tuple)
            or not self.public_disclosures
        ):
            raise ValueError("public_disclosures must be a non-empty tuple")
        if any(
            not isinstance(item, PublicDisclosure)
            for item in self.public_disclosures
        ):
            raise ValueError("public_disclosures must contain PublicDisclosure values")
        if len(set(self.public_disclosures)) != len(self.public_disclosures):
            raise ValueError("public_disclosures must not contain duplicate rows")
        if not isinstance(self.training_data_cutoff, TrainingDataCutoff):
            raise ValueError("training_data_cutoff must be a TrainingDataCutoff")
        if not isinstance(self.evaluated_at, datetime):
            raise ValueError("evaluated_at must be a datetime")
        if self.evaluated_at.tzinfo is None or self.evaluated_at.utcoffset() is None:
            raise ValueError("evaluated_at must include a UTC offset")
        if type(self.network_access) is not bool:
            raise ValueError("network_access must be boolean")
        if type(self.retrieval_access) is not bool:
            raise ValueError("retrieval_access must be boolean")
        if not isinstance(
            self.pre_evaluation_benchmark_exposure,
            PreEvaluationBenchmarkExposure,
        ):
            raise ValueError(
                "pre_evaluation_benchmark_exposure must be a "
                "PreEvaluationBenchmarkExposure"
            )
        if self.evaluated_at.date() < self.earliest_public_at:
            raise ValueError("evaluated_at must not precede earliest_public_at")

    @property
    def earliest_public_at(self) -> date:
        return min(item.public_at for item in self.public_disclosures)


def assess_temporal_exposure(
    record: TemporalContaminationRecord,
    *,
    minimum_buffer_days: int,
) -> TemporalExposureAssessment:
    """Classify one row without converting missing evidence into non-exposure."""

    if not isinstance(record, TemporalContaminationRecord):
        raise ValueError("record must be a TemporalContaminationRecord")
    if (
        isinstance(minimum_buffer_days, bool)
        or not isinstance(minimum_buffer_days, int)
        or minimum_buffer_days < 0
    ):
        raise ValueError("minimum_buffer_days must be a non-negative integer")

    exposure = record.pre_evaluation_benchmark_exposure.status
    if exposure is PreEvaluationExposureStatus.KNOWN:
        return TemporalExposureAssessment.KNOWN_EXPOSED
    if exposure is PreEvaluationExposureStatus.UNKNOWN:
        return TemporalExposureAssessment.EXPOSURE_UNKNOWN

    cutoff = record.training_data_cutoff
    if cutoff.status is TrainingDataCutoffStatus.UNKNOWN:
        return TemporalExposureAssessment.EXPOSURE_UNKNOWN
    if cutoff.cutoff_date is None:  # Guard the invariant for static type checkers.
        raise AssertionError("documented cutoff is missing cutoff_date")
    elapsed_days = (record.earliest_public_at - cutoff.cutoff_date).days
    eligible_at = cutoff.cutoff_date + timedelta(days=minimum_buffer_days)
    if elapsed_days > 0 and record.earliest_public_at >= eligible_at:
        return TemporalExposureAssessment.POST_CHECKPOINT_ELIGIBLE
    return TemporalExposureAssessment.NOT_POST_CHECKPOINT


def temporal_contamination_record_to_payload(
    record: TemporalContaminationRecord,
    *,
    minimum_buffer_days: int,
) -> Dict[str, Any]:
    """Serialize one self-contained P0.6 row."""

    assessment = assess_temporal_exposure(
        record, minimum_buffer_days=minimum_buffer_days
    )
    cutoff = record.training_data_cutoff
    exposure = record.pre_evaluation_benchmark_exposure
    return {
        "schema_version": TEMPORAL_CONTAMINATION_SCHEMA_VERSION,
        "experiment_id": record.experiment_id,
        "benchmark_release_id": record.benchmark_release_id,
        "benchmark_instance_id": record.benchmark_instance_id,
        "source_paper_id": record.source_paper_id,
        "source_version_id": record.source_version_id,
        "public_disclosures": [
            {
                "kind": item.kind.value,
                "public_at": item.public_at.isoformat(),
                "evidence_locator": item.evidence_locator,
            }
            for item in record.public_disclosures
        ],
        "earliest_public_at": record.earliest_public_at.isoformat(),
        "model_profile_id": record.model_profile_id,
        "provider": record.provider,
        "model_id": record.model_id,
        "checkpoint_or_snapshot_id": record.checkpoint_or_snapshot_id,
        "training_data_cutoff": {
            "date": (
                cutoff.cutoff_date.isoformat()
                if cutoff.cutoff_date is not None
                else None
            ),
            "status": cutoff.status.value,
            "evidence_locator": cutoff.evidence_locator,
            "uncertainty": cutoff.uncertainty,
        },
        "evaluated_at": record.evaluated_at.isoformat(),
        "network_access": record.network_access,
        "retrieval_access": record.retrieval_access,
        "pre_evaluation_benchmark_exposure": {
            "status": exposure.status.value,
            "evidence": exposure.evidence,
        },
        "minimum_buffer_days": minimum_buffer_days,
        "assessment": assessment.value,
    }


def validate_temporal_contamination_rows(
    records: Iterable[TemporalContaminationRecord],
    *,
    model_profile_ids: Sequence[str],
    benchmark_instance_ids: Sequence[str],
) -> Tuple[TemporalContaminationRecord, ...]:
    """Require exactly one row for every expected model-instance pair."""

    result = tuple(records)
    models = tuple(model_profile_ids)
    instances = tuple(benchmark_instance_ids)
    if not models or not instances:
        raise ValueError(
            "expected model profiles and temporal instances must be non-empty"
        )
    for label, values in (
        ("model_profile_ids", models),
        ("benchmark_instance_ids", instances),
    ):
        if any(not isinstance(value, str) or not value.strip() for value in values):
            raise ValueError("%s must contain non-empty text" % label)
        if len(set(values)) != len(values):
            raise ValueError("%s must not contain duplicates" % label)
    if any(not isinstance(item, TemporalContaminationRecord) for item in result):
        raise ValueError("records must contain TemporalContaminationRecord values")

    pairs = tuple(
        (item.model_profile_id, item.benchmark_instance_id) for item in result
    )
    if len(set(pairs)) != len(pairs):
        raise ValueError("duplicate model-profile by benchmark-instance row")
    expected = {(model, instance) for model in models for instance in instances}
    actual = set(pairs)
    if actual != expected:
        missing = sorted(expected - actual)
        unexpected = sorted(actual - expected)
        raise ValueError(
            "contamination rows do not match the expected Cartesian product "
            "(missing=%r, unexpected=%r)" % (missing, unexpected)
        )
    if len({item.experiment_id for item in result}) != 1:
        raise ValueError("contamination rows must share one experiment_id")
    if len({item.benchmark_release_id for item in result}) != 1:
        raise ValueError("contamination rows must share one benchmark_release_id")
    return result


__all__ = [
    "TEMPORAL_CONTAMINATION_SCHEMA_VERSION",
    "DisclosureKind",
    "PreEvaluationBenchmarkExposure",
    "PreEvaluationExposureStatus",
    "PublicDisclosure",
    "TemporalContaminationRecord",
    "TemporalExposureAssessment",
    "TrainingDataCutoff",
    "TrainingDataCutoffStatus",
    "assess_temporal_exposure",
    "temporal_contamination_record_to_payload",
    "validate_temporal_contamination_rows",
]
