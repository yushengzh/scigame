"""The current Temporal dataset: source relations and authored counterfactuals."""

from __future__ import annotations

from functools import partial

from role_benchmark.conditions import (
    ConditionDescriptor,
    ConditionRole,
    DatasetKind,
    validate_condition_descriptors,
)
from .temporal import (
    DATASET_ID,
    DATASET_STATUS,
    TEMPORAL_CASE_FAMILIES,
    TEMPORAL_CASE_SPECS,
    TEMPORAL_SCIENCE_CARDS,
    make_temporal_case,
)

TEMPORAL_CASE_FACTORIES = {
    family: partial(make_temporal_case, family) for family in TEMPORAL_CASE_FAMILIES
}
TEMPORAL_CONDITIONS = {
    family: validate_condition_descriptors((
        ConditionDescriptor(
            dataset_kind=DatasetKind.TEMPORAL_COUNTERFACTUAL,
            family_id=family,
            variant_id="canonical",
            condition_id="source_reported",
            condition_role=ConditionRole.SOURCE_REPORTED,
            source_condition_id="paper_relation",
        ),
        ConditionDescriptor(
            dataset_kind=DatasetKind.TEMPORAL_COUNTERFACTUAL,
            family_id=family,
            variant_id="canonical",
            condition_id="counterfactual",
            condition_role=ConditionRole.COUNTERFACTUAL,
        ),
    ))
    for family in TEMPORAL_CASE_FAMILIES
}
TEMPORAL_CONDITION_RUNTIME_MAP = {
    family: {"source_reported": "historical", "counterfactual": "counterfactual"}
    for family in TEMPORAL_CASE_FAMILIES
}
TEMPORAL_SOURCE_VERSION_IDS = {
    family: card["publication"].get("source_arxiv_version")
    for family, card in TEMPORAL_SCIENCE_CARDS.items()
}
TEMPORAL_SOURCE_PAPER_IDS = {
    family: (
        "doi:" + card["publication"]["doi"]
        if card["publication"].get("doi") else
        "arxiv:" + card["publication"]["arxiv_id"]
    )
    for family, card in TEMPORAL_SCIENCE_CARDS.items()
}

from .defect_sre import make_defect_sre_case
from .uamo_lyapunov import make_uamo_lyapunov_case
from .viscous_inertial_rheology import make_viscous_inertial_rheology_case

__all__ = [
    "DATASET_ID", "DATASET_STATUS", "TEMPORAL_CASE_FACTORIES",
    "TEMPORAL_CASE_FAMILIES", "TEMPORAL_CASE_SPECS", "TEMPORAL_SCIENCE_CARDS",
    "TEMPORAL_CONDITIONS", "TEMPORAL_CONDITION_RUNTIME_MAP",
    "TEMPORAL_SOURCE_PAPER_IDS", "TEMPORAL_SOURCE_VERSION_IDS",
    "make_temporal_case", "make_defect_sre_case", "make_uamo_lyapunov_case",
    "make_viscous_inertial_rheology_case",
]
