"""Condition semantics shared by benchmark registries and result schemas.

The contract deliberately separates authored historical/counterfactual pairs
from source-reported temporal conditions.  Runtime storage keys are not
scientific condition roles and therefore do not belong in this module.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, Iterable, Optional, Tuple


CONDITION_DESCRIPTOR_SCHEMA_VERSION = "role_benchmark.condition_descriptor.v1"
_IDENTIFIER = re.compile(r"^[a-z][a-z0-9_]*$")
_NON_NEUTRAL_TEMPORAL_TOKENS = frozenset(
    {"historical", "counterfactual", "easy", "hard"}
)


class DatasetKind(str, Enum):
    """The scientific design represented by a set of conditions."""

    HISTORICAL_COUNTERFACTUAL = "historical_counterfactual"
    TEMPORAL = "temporal"


class ConditionRole(str, Enum):
    """A condition's scientific role, independent of runtime storage."""

    HISTORICAL = "historical"
    COUNTERFACTUAL = "counterfactual"
    SOURCE_REPORTED = "source_reported"


def _require_identifier(value: str, label: str) -> None:
    if not isinstance(value, str) or _IDENTIFIER.fullmatch(value) is None:
        raise ValueError("%s must be a non-empty lower-snake identifier" % label)


@dataclass(frozen=True)
class ConditionDescriptor:
    """One condition in a versioned family variant.

    ``condition_id`` is the stable benchmark key.  Temporal IDs must remain
    neutral with respect to H/C and intended difficulty.  Their source-facing
    identity is recorded separately as ``source_condition_id``.
    """

    dataset_kind: DatasetKind
    family_id: str
    variant_id: str
    condition_id: str
    condition_role: ConditionRole
    source_condition_id: Optional[str] = None

    def __post_init__(self) -> None:
        if not isinstance(self.dataset_kind, DatasetKind):
            raise ValueError("dataset_kind must be a DatasetKind")
        if not isinstance(self.condition_role, ConditionRole):
            raise ValueError("condition_role must be a ConditionRole")
        _require_identifier(self.family_id, "family_id")
        _require_identifier(self.variant_id, "variant_id")
        _require_identifier(self.condition_id, "condition_id")

        if self.dataset_kind is DatasetKind.HISTORICAL_COUNTERFACTUAL:
            if self.condition_role not in (
                ConditionRole.HISTORICAL,
                ConditionRole.COUNTERFACTUAL,
            ):
                raise ValueError(
                    "historical_counterfactual conditions must have a historical "
                    "or counterfactual role"
                )
            if self.source_condition_id is not None:
                raise ValueError(
                    "historical_counterfactual conditions must not set "
                    "source_condition_id"
                )
            return

        if self.condition_role is not ConditionRole.SOURCE_REPORTED:
            raise ValueError("temporal conditions must have source_reported role")
        if self.source_condition_id is None:
            raise ValueError("temporal conditions require source_condition_id")
        _require_identifier(self.source_condition_id, "source_condition_id")
        condition_tokens = frozenset(self.condition_id.split("_"))
        if condition_tokens & _NON_NEUTRAL_TEMPORAL_TOKENS:
            raise ValueError(
                "temporal condition_id must not encode H/C or easy/hard semantics"
            )


def validate_condition_descriptors(
    descriptors: Iterable[ConditionDescriptor],
) -> Tuple[ConditionDescriptor, ...]:
    """Validate one complete two-condition family variant."""

    result = tuple(descriptors)
    if len(result) != 2:
        raise ValueError("a condition contract must contain exactly two conditions")
    if any(not isinstance(item, ConditionDescriptor) for item in result):
        raise ValueError("conditions must be ConditionDescriptor values")

    first = result[0]
    for item in result[1:]:
        if item.dataset_kind is not first.dataset_kind:
            raise ValueError("conditions must share one dataset_kind")
        if item.family_id != first.family_id:
            raise ValueError("conditions must share one family_id")
        if item.variant_id != first.variant_id:
            raise ValueError("conditions must share one variant_id")

    condition_ids = tuple(item.condition_id for item in result)
    if len(set(condition_ids)) != len(condition_ids):
        raise ValueError("condition_id values must be unique within a variant")

    if first.dataset_kind is DatasetKind.HISTORICAL_COUNTERFACTUAL:
        roles = {item.condition_role for item in result}
        if roles != {ConditionRole.HISTORICAL, ConditionRole.COUNTERFACTUAL}:
            raise ValueError(
                "historical_counterfactual variants require exactly one historical "
                "and one counterfactual condition"
            )
    else:
        if any(
            item.condition_role is not ConditionRole.SOURCE_REPORTED
            for item in result
        ):
            raise ValueError("temporal variants require two source_reported conditions")
        source_ids = tuple(item.source_condition_id for item in result)
        if len(set(source_ids)) != len(source_ids):
            raise ValueError(
                "source_condition_id values must be unique within a temporal variant"
            )
    return result


def condition_descriptor_to_payload(
    descriptor: ConditionDescriptor,
) -> Dict[str, Any]:
    """Return the strict JSON-compatible representation of a descriptor."""

    if not isinstance(descriptor, ConditionDescriptor):
        raise ValueError("descriptor must be a ConditionDescriptor")
    return {
        "schema_version": CONDITION_DESCRIPTOR_SCHEMA_VERSION,
        "dataset_kind": descriptor.dataset_kind.value,
        "family_id": descriptor.family_id,
        "variant_id": descriptor.variant_id,
        "condition_id": descriptor.condition_id,
        "condition_role": descriptor.condition_role.value,
        "source_condition_id": descriptor.source_condition_id,
    }


__all__ = [
    "CONDITION_DESCRIPTOR_SCHEMA_VERSION",
    "ConditionDescriptor",
    "ConditionRole",
    "DatasetKind",
    "condition_descriptor_to_payload",
    "validate_condition_descriptors",
]
