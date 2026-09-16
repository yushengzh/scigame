"""Build frozen and versioned Temporal matched benchmark packs.

The source-family release remains authoritative for family order and source
identity.  The two counterfactual-authoring artifacts supply exactly one
same-unit parameter request per family.  Only the constructor's full-target
``easy`` specification is selected; its midpoint ``hard`` canary is validated
in the authoring artifact but is not another core variant.

Request values and runtime truth-key mappings are private assembly metadata.
They must not be copied into a Player-facing prompt.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, replace
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping, Optional, Tuple, Union

from experiments.core160_release import (
    load_accepted_temporal_release,
    load_core20_temporal_release,
)
from role_benchmark.cases.matched import MatchedFamilySpec
from role_benchmark.conditions import (
    ConditionDescriptor,
    ConditionRole,
    DatasetKind,
    validate_condition_descriptors,
)
from role_benchmark.temporal.counterfactual_construction import (
    TemporalCounterfactualRequest,
    construct_temporal_counterfactual_variants,
)


CORE160_TEMPORAL_AUTHORING_SCHEMA = (
    "role_benchmark.temporal_counterfactual_authoring.v1"
)
CORE160_TEMPORAL_VARIANT_ID = "authored_v1"
CORE160_TEMPORAL_SOURCE_CONDITION_ID = "source_reported"
CORE160_TEMPORAL_COUNTERFACTUAL_CONDITION_ID = (
    "benchmark_authored_counterfactual"
)
CORE160_TEMPORAL_CONDITION_IDS = (
    CORE160_TEMPORAL_SOURCE_CONDITION_ID,
    CORE160_TEMPORAL_COUNTERFACTUAL_CONDITION_ID,
)
CORE160_TEMPORAL_SOURCE_RELATION_ID = "paper_relation_v1"
CORE160_TEMPORAL_COUNTERFACTUAL_ARTIFACTS: Tuple[Path, ...] = (
    Path(
        "runs/EXP-TEMPORAL-VALIDATION-002/"
        "counterfactual_authoring_core_a.json"
    ),
    Path(
        "runs/EXP-TEMPORAL-VALIDATION-002/"
        "counterfactual_authoring_core_b.json"
    ),
)
ACCEPTED_TEMPORAL_COUNTERFACTUAL_ARTIFACTS: Tuple[Path, ...] = (
    *CORE160_TEMPORAL_COUNTERFACTUAL_ARTIFACTS,
    Path(
        "runs/EXP-TEMPORAL-VALIDATION-002/"
        "counterfactual_authoring_extension.json"
    ),
)
_DEFAULT_REPO_ROOT = Path(__file__).resolve().parents[1]
_SOURCE_TRUTH_KEY = "historical"
_COUNTERFACTUAL_TRUTH_KEY = "counterfactual"
_SELECTED_EASY_ROLE = "selected_full_target_second_condition"
_EXPECTED_CONSTRUCTOR = (
    "role_benchmark.temporal.counterfactual_construction."
    "construct_temporal_counterfactual_variants"
)


class Core160TemporalPackError(ValueError):
    """A Temporal matched pack cannot be assembled as declared."""


@dataclass(frozen=True)
class Core160CounterfactualRequest:
    """Authoring metadata for one selected full-target condition."""

    artifact_path: Path
    parameter_name: str
    target_value: float
    unit: str


@dataclass(frozen=True)
class Core160TemporalPackFamily:
    """One release-ordered Temporal source/counterfactual matched family."""

    release_order: int
    family_id: str
    paper_id: str
    arxiv_versioned_id: str
    variant_id: str
    request: Core160CounterfactualRequest
    spec: MatchedFamilySpec
    conditions: Tuple[ConditionDescriptor, ...]
    runtime_truth_keys: Mapping[str, str]


@dataclass(frozen=True)
class Core160TemporalPack:
    """Immutable runner-ready view of an ordered Temporal matched release."""

    source_release_experiment_id: str
    records: Tuple[Core160TemporalPackFamily, ...]

    @property
    def family_ids(self) -> Tuple[str, ...]:
        return tuple(item.family_id for item in self.records)

    @property
    def variant_ids(self) -> Tuple[str, ...]:
        return tuple(item.variant_id for item in self.records)

    @property
    def spec_by_family(self) -> Mapping[str, MatchedFamilySpec]:
        return MappingProxyType(
            {item.family_id: item.spec for item in self.records}
        )

    @property
    def specifications(
        self,
    ) -> Mapping[str, Mapping[str, MatchedFamilySpec]]:
        """Return the nesting consumed by ``CasePackDefinition``."""

        return MappingProxyType(
            {
                item.family_id: MappingProxyType(
                    {item.variant_id: item.spec}
                )
                for item in self.records
            }
        )

    @property
    def conditions_by_family(
        self,
    ) -> Mapping[str, Tuple[ConditionDescriptor, ...]]:
        return MappingProxyType(
            {item.family_id: item.conditions for item in self.records}
        )

    @property
    def conditions(
        self,
    ) -> Mapping[str, Mapping[str, Tuple[ConditionDescriptor, ...]]]:
        """Return release-ordered descriptors with runner-compatible nesting."""

        return MappingProxyType(
            {
                item.family_id: MappingProxyType(
                    {item.variant_id: item.conditions}
                )
                for item in self.records
            }
        )

    @property
    def source_paper_ids(self) -> Mapping[str, str]:
        return MappingProxyType(
            {item.family_id: item.paper_id for item in self.records}
        )

    @property
    def source_version_ids(self) -> Mapping[str, str]:
        return MappingProxyType(
            {
                item.family_id: item.arxiv_versioned_id
                for item in self.records
            }
        )

    @property
    def requests(self) -> Mapping[str, Core160CounterfactualRequest]:
        return MappingProxyType(
            {item.family_id: item.request for item in self.records}
        )

    @property
    def request_by_family(
        self,
    ) -> Mapping[str, Core160CounterfactualRequest]:
        return self.requests

    @property
    def runtime_truth_keys(self) -> Mapping[str, Mapping[str, str]]:
        return MappingProxyType(
            {
                item.family_id: item.runtime_truth_keys
                for item in self.records
            }
        )


@dataclass(frozen=True)
class _AuthoredEntry:
    family_id: str
    paper_id: str
    request: Core160CounterfactualRequest
    source_value: float
    recorded_easy_value: float
    recorded_easy_separation: float


def _require_object(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        raise Core160TemporalPackError("%s must be an object" % label)
    return value


def _require_array(value: Any, label: str) -> list[Any]:
    if not isinstance(value, list):
        raise Core160TemporalPackError("%s must be an array" % label)
    return value


def _require_text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise Core160TemporalPackError("%s must be non-empty text" % label)
    return value.strip()


def _require_number(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise Core160TemporalPackError("%s must be numeric" % label)
    result = float(value)
    if not math.isfinite(result):
        raise Core160TemporalPackError("%s must be finite" % label)
    return result


def _require_integer(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise Core160TemporalPackError("%s must be an integer" % label)
    return value


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise Core160TemporalPackError(
            "cannot read counterfactual authoring artifact %s" % path
        ) from exc


def _load_artifact_entries(
    repo_root: Path,
    artifact_path: Path,
) -> Tuple[_AuthoredEntry, ...]:
    document = _require_object(
        _read_json(repo_root / artifact_path),
        str(artifact_path),
    )
    if document.get("schema") != CORE160_TEMPORAL_AUTHORING_SCHEMA:
        raise Core160TemporalPackError(
            "%s has an unsupported authoring schema" % artifact_path
        )
    status = _require_text(document.get("status"), "%s.status" % artifact_path)
    if not status.endswith("_counterfactual_authoring_complete"):
        raise Core160TemporalPackError(
            "%s is not a completed authoring artifact" % artifact_path
        )
    contract = _require_object(
        document.get("authoring_contract"),
        "%s.authoring_contract" % artifact_path,
    )
    if contract.get("performance_selection_used") is not False:
        raise Core160TemporalPackError(
            "%s must explicitly declare performance_selection_used=false"
            % artifact_path
        )
    if contract.get("constructor") != _EXPECTED_CONSTRUCTOR:
        raise Core160TemporalPackError(
            "%s names an unexpected counterfactual constructor" % artifact_path
        )

    raw_families = _require_array(
        document.get("families"), "%s.families" % artifact_path
    )
    summary = _require_object(
        document.get("summary"), "%s.summary" % artifact_path
    )
    expected_count = len(raw_families)
    for field in (
        "families_targeted",
        "families_constructed",
        "selected_full_target_second_conditions",
    ):
        if _require_integer(
            summary.get(field), "%s.summary.%s" % (artifact_path, field)
        ) != expected_count:
            raise Core160TemporalPackError(
                "%s summary count does not match its family entries" % artifact_path
            )
    if _require_integer(
        summary.get("families_blocked"),
        "%s.summary.families_blocked" % artifact_path,
    ) != 0:
        raise Core160TemporalPackError(
            "%s must explicitly contain zero blocked families" % artifact_path
        )

    entries = []
    for index, raw in enumerate(raw_families):
        label = "%s.families[%d]" % (artifact_path, index)
        item = _require_object(raw, label)
        family_id = _require_text(item.get("family_id"), label + ".family_id")
        paper_id = _require_text(item.get("paper_id"), label + ".paper_id")
        request_payload = _require_object(
            item.get("request"), label + ".request"
        )
        parameter_name = _require_text(
            request_payload.get("parameter_name"),
            label + ".request.parameter_name",
        )
        target_value = _require_number(
            request_payload.get("target_value"),
            label + ".request.target_value",
        )
        unit = _require_text(
            request_payload.get("unit"), label + ".request.unit"
        )
        source_value = _require_number(
            request_payload.get("source_value"),
            label + ".request.source_value",
        )

        construction = _require_object(
            item.get("construction"), label + ".construction"
        )
        if construction.get("status") != "pass":
            raise Core160TemporalPackError(
                "%s must have construction.status=pass" % label
            )
        variants = _require_object(
            construction.get("variants"), label + ".construction.variants"
        )
        easy = _require_object(variants.get("easy"), label + ".variants.easy")
        if easy.get("role") != _SELECTED_EASY_ROLE:
            raise Core160TemporalPackError(
                "%s easy variant is not the selected full-target condition" % label
            )
        fraction = _require_number(
            easy.get("counterfactual_fraction"),
            label + ".variants.easy.counterfactual_fraction",
        )
        if fraction != 1.0:
            raise Core160TemporalPackError(
                "%s selected easy variant must use fraction 1.0" % label
            )
        easy_value = _require_number(
            easy.get("counterfactual_value"),
            label + ".variants.easy.counterfactual_value",
        )
        if easy_value != target_value:
            raise Core160TemporalPackError(
                "%s selected easy value must equal request.target_value" % label
            )
        if easy.get("matched_spec_validation") != "pass":
            raise Core160TemporalPackError(
                "%s selected easy MatchedFamilySpec was not validated" % label
            )
        known_truth = _require_object(
            easy.get("known_truth_validation"),
            label + ".variants.easy.known_truth_validation",
        )
        expected_known_truth = {
            "source_identification",
            "source_discovery",
            "counterfactual_identification",
            "counterfactual_discovery",
        }
        if set(known_truth) != expected_known_truth or any(
            known_truth[name] != "pass" for name in expected_known_truth
        ):
            raise Core160TemporalPackError(
                "%s selected easy known-truth checks must all pass" % label
            )
        separation = _require_number(
            easy.get("fixed_design_separation"),
            label + ".variants.easy.fixed_design_separation",
        )
        if separation <= 0.0:
            raise Core160TemporalPackError(
                "%s selected easy separation must be positive" % label
            )
        entries.append(
            _AuthoredEntry(
                family_id=family_id,
                paper_id=paper_id,
                request=Core160CounterfactualRequest(
                    artifact_path=artifact_path,
                    parameter_name=parameter_name,
                    target_value=target_value,
                    unit=unit,
                ),
                source_value=source_value,
                recorded_easy_value=easy_value,
                recorded_easy_separation=separation,
            )
        )
    return tuple(entries)


def _conditions(family_id: str) -> Tuple[ConditionDescriptor, ...]:
    return validate_condition_descriptors(
        (
            ConditionDescriptor(
                dataset_kind=DatasetKind.TEMPORAL_COUNTERFACTUAL,
                family_id=family_id,
                variant_id=CORE160_TEMPORAL_VARIANT_ID,
                condition_id=CORE160_TEMPORAL_SOURCE_CONDITION_ID,
                condition_role=ConditionRole.SOURCE_REPORTED,
                source_condition_id=CORE160_TEMPORAL_SOURCE_RELATION_ID,
            ),
            ConditionDescriptor(
                dataset_kind=DatasetKind.TEMPORAL_COUNTERFACTUAL,
                family_id=family_id,
                variant_id=CORE160_TEMPORAL_VARIANT_ID,
                condition_id=CORE160_TEMPORAL_COUNTERFACTUAL_CONDITION_ID,
                condition_role=ConditionRole.COUNTERFACTUAL,
                source_condition_id=None,
            ),
        )
    )


def _load_temporal_pack(
    root: Path,
    *,
    release: Any,
    artifact_paths: Tuple[Path, ...],
    case_id_namespace: str,
) -> Core160TemporalPack:
    """Build one matched pack from an ordered release and authored requests."""

    authored = tuple(
        entry
        for artifact_path in artifact_paths
        for entry in _load_artifact_entries(root, artifact_path)
    )
    authored_ids = tuple(item.family_id for item in authored)
    expected_count = len(release.records)
    if (
        len(authored) != expected_count
        or len(set(authored_ids)) != expected_count
    ):
        raise Core160TemporalPackError(
            "counterfactual artifacts must contain every family exactly once"
        )
    if authored_ids != release.family_ids:
        raise Core160TemporalPackError(
            "counterfactual artifact family order must exactly match the release"
        )

    records = []
    for source_record, authored_entry in zip(release.records, authored):
        if authored_entry.paper_id != source_record.paper_id:
            raise Core160TemporalPackError(
                "%s paper_id does not match the release"
                % source_record.family_id
            )
        parameter_name = authored_entry.request.parameter_name
        if parameter_name not in source_record.spec.truth.parameters:
            raise Core160TemporalPackError(
                "%s counterfactual parameter is absent from the source model"
                % source_record.family_id
            )
        actual_source_value = float(
            source_record.spec.truth.parameters[parameter_name]
        )
        if actual_source_value != authored_entry.source_value:
            raise Core160TemporalPackError(
                "%s authoring source value does not match the release replay"
                % source_record.family_id
            )
        variants = construct_temporal_counterfactual_variants(
            source_record.spec,
            TemporalCounterfactualRequest(
                parameter_name=parameter_name,
                target_value=authored_entry.request.target_value,
                unit=authored_entry.request.unit,
            ),
        )
        selected = variants["easy"]
        if selected.counterfactual_fraction != 1.0:
            raise Core160TemporalPackError(
                "%s constructor easy variant is not the full target"
                % source_record.family_id
            )
        selected_value = float(
            selected.spec.truths[_COUNTERFACTUAL_TRUTH_KEY].parameters[
                parameter_name
            ]
        )
        if selected_value != authored_entry.recorded_easy_value:
            raise Core160TemporalPackError(
                "%s replayed full target differs from the authoring artifact"
                % source_record.family_id
            )
        if not math.isclose(
            selected.fixed_design_separation,
            authored_entry.recorded_easy_separation,
            rel_tol=1.0e-12,
            abs_tol=1.0e-12,
        ):
            raise Core160TemporalPackError(
                "%s replayed separation differs from the authoring artifact"
                % source_record.family_id
            )

        # Replacing these two identifiers triggers MatchedFamilySpec validation
        # again while removing truth-bearing condition words from case IDs.
        matched_spec = replace(
            selected.spec,
            family=source_record.family_id,
            case_id_prefix=(
                "%s.family_%02d.%s"
                % (
                    case_id_namespace,
                    source_record.release_order,
                    CORE160_TEMPORAL_VARIANT_ID,
                )
            ),
        )
        conditions = _conditions(source_record.family_id)
        truth_keys = MappingProxyType(
            {
                CORE160_TEMPORAL_SOURCE_CONDITION_ID: _SOURCE_TRUTH_KEY,
                CORE160_TEMPORAL_COUNTERFACTUAL_CONDITION_ID: (
                    _COUNTERFACTUAL_TRUTH_KEY
                ),
            }
        )
        records.append(
            Core160TemporalPackFamily(
                release_order=source_record.release_order,
                family_id=source_record.family_id,
                paper_id=source_record.paper_id,
                arxiv_versioned_id=source_record.arxiv_versioned_id,
                variant_id=CORE160_TEMPORAL_VARIANT_ID,
                request=authored_entry.request,
                spec=matched_spec,
                conditions=conditions,
                runtime_truth_keys=truth_keys,
            )
        )
    return Core160TemporalPack(
        source_release_experiment_id=release.experiment_id,
        records=tuple(records),
    )


def load_core160_temporal_pack(
    repo_root: Optional[Union[str, Path]] = None,
) -> Core160TemporalPack:
    """Replay the frozen 20-family Temporal half of legacy ``core160``."""

    root = (
        _DEFAULT_REPO_ROOT
        if repo_root is None
        else Path(repo_root).expanduser().resolve()
    )
    return _load_temporal_pack(
        root,
        release=load_core20_temporal_release(root),
        artifact_paths=CORE160_TEMPORAL_COUNTERFACTUAL_ARTIFACTS,
        case_id_namespace="core160",
    )


def load_accepted_temporal_pack(
    repo_root: Optional[Union[str, Path]] = None,
) -> Core160TemporalPack:
    """Replay every family in the accepted Temporal release."""

    root = (
        _DEFAULT_REPO_ROOT
        if repo_root is None
        else Path(repo_root).expanduser().resolve()
    )
    return _load_temporal_pack(
        root,
        release=load_accepted_temporal_release(root),
        artifact_paths=ACCEPTED_TEMPORAL_COUNTERFACTUAL_ARTIFACTS,
        case_id_namespace="temporal",
    )


__all__ = [
    "CORE160_TEMPORAL_AUTHORING_SCHEMA",
    "CORE160_TEMPORAL_CONDITION_IDS",
    "CORE160_TEMPORAL_COUNTERFACTUAL_ARTIFACTS",
    "CORE160_TEMPORAL_COUNTERFACTUAL_CONDITION_ID",
    "CORE160_TEMPORAL_SOURCE_CONDITION_ID",
    "CORE160_TEMPORAL_SOURCE_RELATION_ID",
    "CORE160_TEMPORAL_VARIANT_ID",
    "ACCEPTED_TEMPORAL_COUNTERFACTUAL_ARTIFACTS",
    "Core160CounterfactualRequest",
    "Core160TemporalPack",
    "Core160TemporalPackError",
    "Core160TemporalPackFamily",
    "load_core160_temporal_pack",
    "load_accepted_temporal_pack",
]
