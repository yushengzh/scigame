"""Replay frozen core-20 or complete accepted Temporal source releases.

The release manifest remains the single source of ordering and source identity.
The loaders turn manifest entries into runtime ``SourceFamilySpec`` objects
through the Temporal admission-v2 and compilation contracts.  The legacy view
keeps exactly 20; the versioned public view derives its size from all accepted
records.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping, Optional, Tuple, Union

from role_benchmark.cases.source import SourceFamilySpec
from role_benchmark.temporal.admission import (
    TEMPORAL_ADMISSION_PRECOMPILE_CHECKS_V2,
    TEMPORAL_ADMISSION_REVIEW_SCHEMA_V2,
    assess_temporal_admission,
    parse_temporal_admission_review_payload,
)
from role_benchmark.temporal.minimal_science_card import (
    parse_minimal_science_card_payload,
)
from role_benchmark.temporal.science_card import ScienceSource
from role_benchmark.temporal.source_case import compile_temporal_source_case


CORE20_TEMPORAL_RELEASE_SCHEMA = (
    "role_benchmark.temporal_release_candidate_manifest.v1"
)
CORE20_TEMPORAL_RELEASE_MANIFEST = Path(
    "runs/EXP-TEMPORAL-VALIDATION-002/release_manifest.json"
)
_DEFAULT_REPO_ROOT = Path(__file__).resolve().parents[1]
_FAMILY_ID = re.compile(r"^temporal_source_([0-9]+)$")


class Core20TemporalReleaseError(ValueError):
    """The declared Temporal release cannot be replayed."""


@dataclass(frozen=True)
class Core20TemporalFamily:
    """One manifest identity and its replayed runtime source specification."""

    release_order: int
    family_id: str
    paper_id: str
    arxiv_versioned_id: str
    source: ScienceSource
    source_directory: Path
    source_line_count: int
    spec: SourceFamilySpec
    provenance: Mapping[str, Any]


@dataclass(frozen=True)
class Core20TemporalRelease:
    """Immutable, release-ordered runtime view of the Temporal core 20."""

    manifest_schema: str
    experiment_id: str
    records: Tuple[Core20TemporalFamily, ...]

    @property
    def family_ids(self) -> Tuple[str, ...]:
        return tuple(item.family_id for item in self.records)

    @property
    def paper_ids(self) -> Tuple[str, ...]:
        return tuple(item.paper_id for item in self.records)

    @property
    def arxiv_versioned_ids(self) -> Tuple[str, ...]:
        return tuple(item.arxiv_versioned_id for item in self.records)

    @property
    def specs(self) -> Tuple[SourceFamilySpec, ...]:
        return tuple(item.spec for item in self.records)

    @property
    def spec_by_family(self) -> Mapping[str, SourceFamilySpec]:
        return MappingProxyType(
            {item.family_id: item.spec for item in self.records}
        )


@dataclass(frozen=True)
class AcceptedTemporalRelease:
    """Immutable, release-ordered view of every accepted Temporal family."""

    manifest_schema: str
    experiment_id: str
    records: Tuple[Core20TemporalFamily, ...]

    @property
    def family_ids(self) -> Tuple[str, ...]:
        return tuple(item.family_id for item in self.records)

    @property
    def paper_ids(self) -> Tuple[str, ...]:
        return tuple(item.paper_id for item in self.records)

    @property
    def arxiv_versioned_ids(self) -> Tuple[str, ...]:
        return tuple(item.arxiv_versioned_id for item in self.records)

    @property
    def specs(self) -> Tuple[SourceFamilySpec, ...]:
        return tuple(item.spec for item in self.records)

    @property
    def spec_by_family(self) -> Mapping[str, SourceFamilySpec]:
        return MappingProxyType(
            {item.family_id: item.spec for item in self.records}
        )


def _require_object(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        raise Core20TemporalReleaseError("%s must be an object" % label)
    return value


def _require_text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise Core20TemporalReleaseError("%s must be non-empty text" % label)
    return value.strip()


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise Core20TemporalReleaseError(
            "cannot read JSON release artifact %s" % path
        ) from exc


def _resolve_json_pointer(document: Any, pointer: str, *, label: str) -> Any:
    if not isinstance(pointer, str) or not pointer.startswith("/"):
        raise Core20TemporalReleaseError("%s must be an absolute JSON pointer" % label)
    current = document
    for raw_token in pointer[1:].split("/"):
        token = raw_token.replace("~1", "/").replace("~0", "~")
        if isinstance(current, dict):
            if token not in current:
                raise Core20TemporalReleaseError(
                    "%s does not resolve at %s" % (label, token)
                )
            current = current[token]
        elif isinstance(current, list):
            if not token.isdigit():
                raise Core20TemporalReleaseError(
                    "%s does not resolve at %s" % (label, token)
                )
            index = int(token)
            if index >= len(current):
                raise Core20TemporalReleaseError(
                    "%s does not resolve at %s" % (label, token)
                )
            current = current[index]
        else:
            raise Core20TemporalReleaseError(
                "%s traverses a scalar at %s" % (label, token)
            )
    return current


def _source_payload(source: ScienceSource) -> Mapping[str, str]:
    return {
        "citation": source.citation,
        "journal_doi": source.journal_doi,
        "arxiv_versioned_id": source.arxiv_versioned_id,
    }


def _release_order(entry: Mapping[str, Any]) -> int:
    value = entry.get("release_order")
    if isinstance(value, bool) or not isinstance(value, int):
        raise Core20TemporalReleaseError("release_order must be an integer")
    return value


def _load_record(repo_root: Path, raw: Any) -> Core20TemporalFamily:
    entry = _require_object(raw, "accepted entry")
    family_id = _require_text(entry.get("family_id"), "family_id")
    match = _FAMILY_ID.fullmatch(family_id)
    if match is None:
        raise Core20TemporalReleaseError(
            "family_id must match temporal_source_<numeric suffix>"
        )
    release_order = _release_order(entry)
    paper_id = _require_text(entry.get("paper_id"), "paper_id")

    source_payload = _require_object(entry.get("source"), "source")
    source = ScienceSource(
        citation=_require_text(source_payload.get("citation"), "source.citation"),
        journal_doi=_require_text(
            source_payload.get("journal_doi"), "source.journal_doi"
        ),
        arxiv_versioned_id=_require_text(
            source_payload.get("arxiv_versioned_id"),
            "source.arxiv_versioned_id",
        ),
    )

    science_card = _require_object(entry.get("science_card"), "science_card")
    batch_path = repo_root / _require_text(
        science_card.get("batch"), "science_card.batch"
    )
    pointer = _require_text(
        science_card.get("json_pointer"), "science_card.json_pointer"
    )
    card_payload = _resolve_json_pointer(
        _read_json(batch_path),
        pointer,
        label="science_card.json_pointer",
    )
    card = parse_minimal_science_card_payload(card_payload)
    if _source_payload(card.source) != _source_payload(source):
        raise Core20TemporalReleaseError(
            "%s ScienceCard source does not match the release manifest" % family_id
        )

    acquisition = _require_object(entry.get("acquisition"), "acquisition")
    source_directory = repo_root / _require_text(
        acquisition.get("source_directory"), "acquisition.source_directory"
    )
    source_packet_path = source_directory / "source_packet.txt"
    try:
        source_line_count = len(
            source_packet_path.read_text(encoding="utf-8").splitlines()
        )
    except OSError as exc:
        raise Core20TemporalReleaseError(
            "cannot read source packet %s" % source_packet_path
        ) from exc
    if source_line_count < 1:
        raise Core20TemporalReleaseError(
            "source packet must contain at least one line: %s" % source_packet_path
        )

    admission_v2 = _require_object(entry.get("admission_v2"), "admission_v2")
    if admission_v2.get("schema") != TEMPORAL_ADMISSION_REVIEW_SCHEMA_V2:
        raise Core20TemporalReleaseError(
            "%s must declare the admission-v2 schema" % family_id
        )
    checks = _require_object(
        admission_v2.get("precompile_checks"),
        "admission_v2.precompile_checks",
    )
    if set(checks) != set(TEMPORAL_ADMISSION_PRECOMPILE_CHECKS_V2) or any(
        checks[name] != "pass"
        for name in TEMPORAL_ADMISSION_PRECOMPILE_CHECKS_V2
    ):
        raise Core20TemporalReleaseError(
            "%s requires all eight manifest admission-v2 checks to pass"
            % family_id
        )
    replay = _require_object(admission_v2.get("replay"), "admission_v2.replay")
    if replay.get("admitted") is not True:
        raise Core20TemporalReleaseError(
            "%s is not admitted by the frozen manifest replay" % family_id
        )

    review = parse_temporal_admission_review_payload(
        {
            "schema": TEMPORAL_ADMISSION_REVIEW_SCHEMA_V2,
            "paper_id": paper_id,
            "source": dict(_source_payload(source)),
            "review_material": card_payload,
            "reviewer": "core20-release-manifest-replay",
            "decision": "eligible_for_temporal_case",
            "assessment": (
                "The frozen release manifest records all eight admission-v2 "
                "pre-compile checks as pass."
            ),
            "checks": {
                name: checks[name]
                for name in TEMPORAL_ADMISSION_PRECOMPILE_CHECKS_V2
            },
            "issues": [],
        }
    )
    admission = assess_temporal_admission(
        card,
        review,
        paper_id=paper_id,
        source_line_count=source_line_count,
    )
    if not admission.admitted:
        raise Core20TemporalReleaseError(
            "%s admission-v2 replay did not admit the ScienceCard" % family_id
        )
    build = compile_temporal_source_case(
        admission,
        case_index=int(match.group(1)),
    )
    if build.spec.family != family_id:
        raise Core20TemporalReleaseError(
            "compiled family %s does not match manifest family %s"
            % (build.spec.family, family_id)
        )

    return Core20TemporalFamily(
        release_order=release_order,
        family_id=family_id,
        paper_id=paper_id,
        arxiv_versioned_id=source.arxiv_versioned_id,
        source=source,
        source_directory=source_directory,
        source_line_count=source_line_count,
        spec=build.spec,
        provenance=MappingProxyType(dict(build.provenance)),
    )


def load_core20_temporal_release(
    repo_root: Optional[Union[str, Path]] = None,
) -> Core20TemporalRelease:
    """Load and deterministically replay the 20 ``core20`` manifest entries.

    When ``repo_root`` is omitted, paths are resolved from this module rather
    than the process working directory.
    """

    root = (
        _DEFAULT_REPO_ROOT
        if repo_root is None
        else Path(repo_root).expanduser().resolve()
    )
    manifest = _require_object(
        _read_json(root / CORE20_TEMPORAL_RELEASE_MANIFEST),
        "release manifest",
    )
    schema = _require_text(manifest.get("schema"), "manifest.schema")
    if schema != CORE20_TEMPORAL_RELEASE_SCHEMA:
        raise Core20TemporalReleaseError("unsupported Temporal release schema")
    experiment_id = _require_text(
        manifest.get("experiment_id"), "manifest.experiment_id"
    )
    accepted = manifest.get("accepted")
    if not isinstance(accepted, list):
        raise Core20TemporalReleaseError("manifest.accepted must be an array")
    selected = [
        item
        for item in accepted
        if isinstance(item, dict) and item.get("designation") == "core20"
    ]
    if len(selected) != 20:
        raise Core20TemporalReleaseError(
            "the release manifest must contain exactly 20 core20 entries"
        )
    selected.sort(key=_release_order)
    records = tuple(_load_record(root, item) for item in selected)
    if tuple(item.release_order for item in records) != tuple(range(1, 21)):
        raise Core20TemporalReleaseError(
            "core20 release_order must be exactly 1 through 20"
        )
    for label, values in (
        ("family_id", tuple(item.family_id for item in records)),
        ("paper_id", tuple(item.paper_id for item in records)),
        (
            "arxiv_versioned_id",
            tuple(item.arxiv_versioned_id for item in records),
        ),
    ):
        if len(set(values)) != 20:
            raise Core20TemporalReleaseError(
                "core20 %s values must be unique" % label
            )

    selection = _require_object(manifest.get("selection"), "manifest.selection")
    if selection.get("core20_family_ids") != [
        item.family_id for item in records
    ]:
        raise Core20TemporalReleaseError(
            "manifest selection order does not match core20 release entries"
        )
    return Core20TemporalRelease(
        manifest_schema=schema,
        experiment_id=experiment_id,
        records=records,
    )


def load_accepted_temporal_release(
    repo_root: Optional[Union[str, Path]] = None,
) -> AcceptedTemporalRelease:
    """Load and replay every accepted family in manifest release order.

    Unlike :func:`load_core20_temporal_release`, this view has no frozen
    cardinality.  The manifest's complete ``accepted`` array must use unique,
    contiguous release orders beginning at one.  Its order must also equal the
    declared ``core20_family_ids`` followed by ``extension_family_ids``.
    """

    root = (
        _DEFAULT_REPO_ROOT
        if repo_root is None
        else Path(repo_root).expanduser().resolve()
    )
    manifest = _require_object(
        _read_json(root / CORE20_TEMPORAL_RELEASE_MANIFEST),
        "release manifest",
    )
    schema = _require_text(manifest.get("schema"), "manifest.schema")
    if schema != CORE20_TEMPORAL_RELEASE_SCHEMA:
        raise Core20TemporalReleaseError("unsupported Temporal release schema")
    experiment_id = _require_text(
        manifest.get("experiment_id"), "manifest.experiment_id"
    )
    accepted = manifest.get("accepted")
    if not isinstance(accepted, list):
        raise Core20TemporalReleaseError("manifest.accepted must be an array")
    if not accepted:
        raise Core20TemporalReleaseError("manifest.accepted must not be empty")

    ordered_entries = [
        _require_object(item, "manifest.accepted[%d]" % index)
        for index, item in enumerate(accepted)
    ]
    ordered_entries.sort(key=_release_order)
    release_orders = tuple(_release_order(item) for item in ordered_entries)
    if release_orders != tuple(range(1, len(ordered_entries) + 1)):
        raise Core20TemporalReleaseError(
            "accepted release_order values must be unique and contiguous from 1"
        )

    records = tuple(_load_record(root, item) for item in ordered_entries)
    record_count = len(records)
    for label, values in (
        ("family_id", tuple(item.family_id for item in records)),
        ("paper_id", tuple(item.paper_id for item in records)),
        (
            "arxiv_versioned_id",
            tuple(item.arxiv_versioned_id for item in records),
        ),
    ):
        if len(set(values)) != record_count:
            raise Core20TemporalReleaseError(
                "accepted %s values must be unique" % label
            )

    selection = _require_object(manifest.get("selection"), "manifest.selection")
    raw_core_ids = selection.get("core20_family_ids")
    raw_extension_ids = selection.get("extension_family_ids")
    if not isinstance(raw_core_ids, list):
        raise Core20TemporalReleaseError(
            "manifest.selection.core20_family_ids must be an array"
        )
    if not isinstance(raw_extension_ids, list):
        raise Core20TemporalReleaseError(
            "manifest.selection.extension_family_ids must be an array"
        )
    core_ids = tuple(
        _require_text(value, "manifest.selection.core20_family_ids[%d]" % index)
        for index, value in enumerate(raw_core_ids)
    )
    extension_ids = tuple(
        _require_text(
            value,
            "manifest.selection.extension_family_ids[%d]" % index,
        )
        for index, value in enumerate(raw_extension_ids)
    )
    declared_ids = core_ids + extension_ids
    if len(set(declared_ids)) != len(declared_ids):
        raise Core20TemporalReleaseError(
            "manifest selection family IDs must be unique"
        )

    accepted_core_ids = tuple(
        record.family_id
        for entry, record in zip(ordered_entries, records)
        if entry.get("designation") == "core20"
    )
    accepted_extension_ids = tuple(
        record.family_id
        for entry, record in zip(ordered_entries, records)
        if entry.get("designation") == "extension"
    )
    if any(
        entry.get("designation") not in ("core20", "extension")
        for entry in ordered_entries
    ):
        raise Core20TemporalReleaseError(
            "accepted entries must be designated core20 or extension"
        )
    if core_ids != accepted_core_ids:
        raise Core20TemporalReleaseError(
            "manifest core20 selection order does not match accepted entries"
        )
    if extension_ids != accepted_extension_ids:
        raise Core20TemporalReleaseError(
            "manifest extension selection order does not match accepted entries"
        )
    if declared_ids != tuple(item.family_id for item in records):
        raise Core20TemporalReleaseError(
            "manifest core20+extension selection order does not match "
            "accepted release order"
        )

    return AcceptedTemporalRelease(
        manifest_schema=schema,
        experiment_id=experiment_id,
        records=records,
    )


__all__ = [
    "AcceptedTemporalRelease",
    "CORE20_TEMPORAL_RELEASE_MANIFEST",
    "CORE20_TEMPORAL_RELEASE_SCHEMA",
    "Core20TemporalFamily",
    "Core20TemporalRelease",
    "Core20TemporalReleaseError",
    "load_accepted_temporal_release",
    "load_core20_temporal_release",
]
