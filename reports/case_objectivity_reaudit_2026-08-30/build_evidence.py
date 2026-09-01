"""Build reproducible evidence for the currently admitted scientific cases.

This script intentionally checks only benchmark-relevant contracts: the four
matched cells, Player-visible information, private truth, Oracle behavior, and
evaluator behavior.  Source fidelity remains a scientific-review judgement and
is joined to this evidence separately.
"""

from __future__ import annotations

import importlib.util
import itertools
import json
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping, Sequence


ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from role_benchmark.cases import CASE_FAMILIES, CASE_SPECS, make_case  # noqa: E402
from role_benchmark.cases.matched import (  # noqa: E402
    MATCHED_WORLDS,
    MatchedFamilySpec,
    make_matched_case,
    truth_submission,
)
from role_benchmark.models import (  # noqa: E402
    BenchmarkTrack,
    ExperimentProposal,
    OracleStatus,
)
from role_benchmark.protocols import CaseOracle  # noqa: E402
from role_benchmark.temporal_cases import (  # noqa: E402
    TEMPORAL_CASE_FAMILIES,
    TEMPORAL_CASE_SPECS,
)


ACCEPTED = (
    ROOT
    / "runs/temporal_window_2026-04-01_2026-06-30"
    / "objectivity_and_generation_report/accepted_families.json"
)
OUTPUT = Path(__file__).with_name("machine_evidence.json")

PLACEHOLDER_PHRASES = (
    "use controlled measurements to characterize the observed phenomenon",
    "a measurable response is present under the stated conditions",
    "interactive measurement study",
)


def _load_temporal_specs() -> tuple[Dict[str, MatchedFamilySpec], Dict[str, str]]:
    payload = json.loads(ACCEPTED.read_text(encoding="utf-8"))
    # Include the independently registered warm-up case as well as the cases
    # admitted from the later ten-paper generation batch.
    specs: Dict[str, MatchedFamilySpec] = dict(TEMPORAL_CASE_SPECS)
    paths: Dict[str, str] = {
        family: "src/role_benchmark/temporal_cases/%s.py" % family
        for family in TEMPORAL_CASE_SPECS
    }
    for index, item in enumerate(payload["families"], start=1):
        family = item["family"]
        case_path = ROOT / item["case_path"]
        module_spec = importlib.util.spec_from_file_location(
            "_temporal_audit_%02d" % index, case_path
        )
        if module_spec is None or module_spec.loader is None:
            raise RuntimeError("cannot import %s" % case_path)
        module = importlib.util.module_from_spec(module_spec)
        module_spec.loader.exec_module(module)
        candidates = [
            value
            for value in vars(module).values()
            if isinstance(value, MatchedFamilySpec) and value.family == family
        ]
        if len(candidates) != 1:
            raise RuntimeError(
                "%s exposes %d matching MatchedFamilySpec objects"
                % (case_path, len(candidates))
            )
        # The accepted index is the provenance authority; after promotion its
        # eight entries also exist in the runtime registry.  Reloading the
        # canonical module here is harmless and keeps the indexed path in the
        # evidence row.
        specs[family] = candidates[0]
        paths[family] = str(case_path.relative_to(ROOT))
    return specs, paths


def _values_for_control(control: Any) -> tuple[Any, ...]:
    if control.allowed_values:
        values = tuple(control.allowed_values)
        if len(values) <= 3:
            return values
        return (values[0], values[len(values) // 2], values[-1])
    if control.minimum is None or control.maximum is None:
        raise ValueError("unbounded numeric control %s" % control.name)
    low = float(control.minimum)
    high = float(control.maximum)
    return (low, (low + high) / 2.0, high)


def _grid(spec: MatchedFamilySpec) -> Iterable[Mapping[str, Any]]:
    values = [_values_for_control(control) for control in spec.controls]
    names = [control.name for control in spec.controls]
    for row in itertools.product(*values):
        yield dict(zip(names, row))


def _public_core(case: Any, *, remove_track: bool, remove_instance: bool) -> Any:
    payload = asdict(case.definition)
    if remove_track:
        payload.pop("track", None)
        title = payload["title"]
        payload["title"] = title.removeprefix("Identify ").removeprefix("Discover ")
        notes = payload["resources"]["notes"]
        payload["resources"]["notes"] = tuple(notes[:-1])
    if remove_instance:
        payload.pop("case_id", None)
    return payload


def _semantic_flags(spec: MatchedFamilySpec, source_kind: str) -> list[str]:
    flags: list[str] = []
    if not spec.common_fixed_conditions and not spec.common_notes:
        flags.append("no_public_condition_or_note")
    if not all(
        item.description.strip()
        and (
            item.unit.strip()
            or item.allowed_values
            or "dimensionless" in item.description.lower()
        )
        for item in spec.controls
    ):
        flags.append("incomplete_control_description_or_unit")
    if not all(
        item.allowed_values
        or (item.minimum is not None and item.maximum is not None)
        for item in spec.controls
    ):
        flags.append("unbounded_player_control")
    if not all(item.description.strip() and item.unit.strip() for item in spec.readouts):
        flags.append("incomplete_readout_description_or_unit")
    if source_kind == "temporal" and not all(
        item.statistic.strip() and item.uncertainty.strip() for item in spec.readouts
    ):
        flags.append("temporal_readout_missing_statistic_or_uncertainty")
    for world, truth in spec.truths.items():
        if (
            source_kind == "temporal"
            and not truth.applicability
            and not truth.fixed_conditions
            and not spec.common_fixed_conditions
        ):
            flags.append("temporal_oracle_missing_conditions:%s" % world)
    if not spec.credits:
        flags.append("missing_source_credit")
    return flags


def _presentation_warnings(spec: MatchedFamilySpec) -> list[str]:
    """Record non-blocking neutral prose emitted by the leakage compiler."""

    public_text = " ".join(
        (
            spec.response_title,
            spec.background,
            spec.apparatus_description,
            *spec.initial_observations,
        )
    ).lower()
    warnings = [
        "canonical_neutral_player_text:%s" % phrase
        for phrase in PLACEHOLDER_PHRASES
        if phrase in public_text
    ]
    if len(set(spec.initial_observations)) != len(spec.initial_observations):
        warnings.append("duplicate_initial_observation")
    return warnings


def _invalid_controls(spec: MatchedFamilySpec) -> Dict[str, Any]:
    condition = dict(next(iter(_grid(spec))))
    condition.pop(spec.controls[0].name)
    return condition


def _audit_family(
    family: str,
    spec: MatchedFamilySpec,
    source_kind: str,
    registered: bool,
    case_path: str,
) -> Dict[str, Any]:
    make = (
        (lambda world, track: make_case(family, world, track))
        if source_kind == "built_in"
        else (lambda world, track: make_matched_case(spec, world, track))
    )
    cells: Dict[tuple[str, str], Any] = {}
    truth_pass = 0
    false_twin_rejected = 0
    valid_queries = 0
    repeat_matches = 0
    invalid_queries_without_evidence = 0
    finite_measurements = True
    unit_contract = True

    for world in MATCHED_WORLDS:
        for track in BenchmarkTrack:
            case = make(world, track)
            cells[(world, track.value)] = case
            result = case.evaluator.evaluate(truth_submission(spec, world, track))
            truth_pass += int(result.success)
            twin = "counterfactual" if world == "historical" else "historical"
            twin_result = case.evaluator.evaluate(truth_submission(spec, twin, track))
            false_twin_rejected += int(not twin_result.success)

        case = cells[(world, BenchmarkTrack.IDENTIFICATION.value)]
        oracle = CaseOracle(case.definition, case.world_model)
        for controls in _grid(spec):
            proposal = ExperimentProposal(
                intent="audit the declared response",
                apparatus=spec.apparatus_name,
                controls=controls,
                readouts=tuple(item.name for item in spec.readouts),
                replicates=1,
            )
            first = oracle.respond(proposal)
            second = oracle.respond(proposal)
            valid_queries += 1
            if first.status is not OracleStatus.VALID or first.evidence is None:
                finite_measurements = False
                continue
            repeat_matches += int(first == second)
            finite_measurements = finite_measurements and all(
                isinstance(value, (int, float))
                and not isinstance(value, bool)
                and value == value
                and abs(float(value)) != float("inf")
                for value in first.evidence.measurements.values()
            )
            unit_contract = unit_contract and first.evidence.units == {
                item.name: item.unit for item in spec.readouts
            }
        invalid = ExperimentProposal(
            intent="invalid audit probe",
            apparatus=spec.apparatus_name,
            controls=_invalid_controls(spec),
            readouts=tuple(item.name for item in spec.readouts),
            replicates=1,
        )
        response = oracle.respond(invalid)
        invalid_queries_without_evidence += int(
            response.status is not OracleStatus.VALID and response.evidence is None
        )

    track_pairs_equal = all(
        _public_core(
            cells[(world, BenchmarkTrack.IDENTIFICATION.value)],
            remove_track=True,
            remove_instance=False,
        )
        == _public_core(
            cells[(world, BenchmarkTrack.DISCOVERY.value)],
            remove_track=True,
            remove_instance=False,
        )
        for world in MATCHED_WORLDS
    )
    world_surfaces_equal = _public_core(
        cells[("historical", BenchmarkTrack.IDENTIFICATION.value)],
        remove_track=False,
        remove_instance=True,
    ) == _public_core(
        cells[("counterfactual", BenchmarkTrack.IDENTIFICATION.value)],
        remove_track=False,
        remove_instance=True,
    )
    public_text = json.dumps(
        asdict(cells[("historical", BenchmarkTrack.IDENTIFICATION.value)].definition),
        ensure_ascii=False,
        default=str,
    ).lower()
    leakage_terms = [
        term for term in ("historical", "counterfactual") if term in public_text
    ]
    changed_parameters = [
        key
        for key in spec.truths["historical"].parameters
        if spec.truths["historical"].parameters[key]
        != spec.truths["counterfactual"].parameters[key]
    ]
    parameter_names_match = (
        tuple(item.name for item in spec.identification_parameter_specs)
        == spec.identification_parameters
    )
    parameter_meanings_structured = bool(
        spec.identification_parameter_specs
    ) and all(
        item.name.strip() and item.description.strip()
        for item in spec.identification_parameter_specs
    )
    # ``None`` is the explicit unbounded side of the domain, so a pair of
    # ``None`` bounds means "any finite real", not missing metadata.
    parameter_domains_structured = bool(
        spec.identification_parameter_specs
    ) and all(
        all(
            item.contains(
                float(
                    (truth.identification_values or truth.parameters)[item.name]
                )
            )
            for truth in spec.truths.values()
        )
        for item in spec.identification_parameter_specs
    )
    flags = _semantic_flags(spec, source_kind)
    presentation_warnings = _presentation_warnings(spec)
    machine_pass = all(
        (
            truth_pass == 4,
            false_twin_rejected == 4,
            repeat_matches == valid_queries,
            invalid_queries_without_evidence == 2,
            finite_measurements,
            unit_contract,
            track_pairs_equal,
            world_surfaces_equal,
            len(changed_parameters) == 1,
            parameter_names_match,
            parameter_meanings_structured,
            parameter_domains_structured,
        )
    )
    return {
        "family": family,
        "source_kind": source_kind,
        "case_path": case_path,
        "registered_in_current_runtime": registered,
        "matched_cells_instantiated": 4,
        "known_truth_cells_passed": truth_pass,
        "false_twin_cells_rejected": false_twin_rejected,
        "sampled_valid_oracle_queries": valid_queries,
        "repeated_oracle_responses_identical": repeat_matches,
        "invalid_queries_without_evidence": invalid_queries_without_evidence,
        "finite_measurements": finite_measurements,
        "unit_contract": unit_contract,
        "track_pair_public_surface_equal_except_contract": track_pairs_equal,
        "world_public_surface_equal_except_opaque_id": world_surfaces_equal,
        "public_world_label_leakage_terms": leakage_terms,
        "changed_private_parameters": changed_parameters,
        "identification_contract": {
            "model_and_parameter_names_published": True,
            "parameter_names_match_specs": parameter_names_match,
            "parameter_meanings_structured": parameter_meanings_structured,
            "parameter_admissible_ranges_structured": parameter_domains_structured,
            "unbounded_sides_mean": "any finite real value",
        },
        "private_scientific_context": {
            "historical_applicability_entries": len(
                spec.truths["historical"].applicability
            ),
            "historical_fixed_condition_entries": len(
                spec.truths["historical"].fixed_conditions
            ),
            "counterfactual_applicability_entries": len(
                spec.truths["counterfactual"].applicability
            ),
            "counterfactual_fixed_condition_entries": len(
                spec.truths["counterfactual"].fixed_conditions
            ),
            "common_fixed_condition_entries": len(spec.common_fixed_conditions),
            "common_note_entries": len(spec.common_notes),
        },
        "diagnostic_condition_count": len(spec.diagnostic_conditions),
        "hidden_condition_count": len(spec.hidden_conditions),
        "budget": spec.budget,
        "semantic_completeness_flags": flags,
        "nonblocking_presentation_warnings": presentation_warnings,
        "machine_contract_pass": machine_pass,
    }


def main() -> None:
    temporal_specs, temporal_paths = _load_temporal_specs()
    rows = []
    for family in CASE_FAMILIES:
        rows.append(
            _audit_family(
                family,
                CASE_SPECS[family],
                "built_in",
                True,
                "src/role_benchmark/cases/%s.py" % (
                    "galileo" if family == "galileo_inclined_plane" else
                    "boyle" if family == "boyle_j_tube" else family
                ),
            )
        )
    for family, spec in temporal_specs.items():
        rows.append(
            _audit_family(
                family,
                spec,
                "temporal",
                family in TEMPORAL_CASE_FAMILIES,
                temporal_paths[family],
            )
        )

    payload = {
        "schema": "role_benchmark.case_objectivity_machine_evidence",
        "audit_date": "2026-08-31",
        "scope": {
            "family_count": len(rows),
            "built_in_family_count": len(CASE_FAMILIES),
            "temporal_accepted_family_count": len(temporal_specs),
            "matched_cell_count": 4 * len(rows),
        },
        "headline": {
            "machine_contract_pass": sum(row["machine_contract_pass"] for row in rows),
            "runtime_registered": sum(
                row["registered_in_current_runtime"] for row in rows
            ),
            "known_truth_cells_passed": sum(
                row["known_truth_cells_passed"] for row in rows
            ),
            "known_truth_cells_checked": 4 * len(rows),
            "false_twin_cells_rejected": sum(
                row["false_twin_cells_rejected"] for row in rows
            ),
            "false_twin_cells_checked": 4 * len(rows),
            "sampled_valid_oracle_queries": sum(
                row["sampled_valid_oracle_queries"] for row in rows
            ),
            "repeated_oracle_responses_identical": sum(
                row["repeated_oracle_responses_identical"] for row in rows
            ),
            "invalid_queries_without_evidence": sum(
                row["invalid_queries_without_evidence"] for row in rows
            ),
            "invalid_queries_checked": 2 * len(rows),
            "families_with_semantic_completeness_flags": sum(
                bool(row["semantic_completeness_flags"]) for row in rows
            ),
            "families_with_nonblocking_presentation_warnings": sum(
                bool(row["nonblocking_presentation_warnings"]) for row in rows
            ),
            "families_missing_structured_identification_parameter_ranges": sum(
                not row["identification_contract"][
                    "parameter_admissible_ranges_structured"
                ]
                for row in rows
            ),
            "families_with_no_truth_specific_applicability_or_fixed_conditions": sum(
                not any(
                    (
                        row["private_scientific_context"][
                            "historical_applicability_entries"
                        ],
                        row["private_scientific_context"][
                            "historical_fixed_condition_entries"
                        ],
                        row["private_scientific_context"][
                            "counterfactual_applicability_entries"
                        ],
                        row["private_scientific_context"][
                            "counterfactual_fixed_condition_entries"
                        ],
                    )
                )
                for row in rows
            ),
        },
        "oracle_interface_audit": {
            "deterministic_case_oracle_available": True,
            "deterministic_world_model_available": True,
            "authoritative_exact_copy_llm_presentation_available": True,
            "free_private_truth_god_llm_available": False,
            "finding": (
                "The current LLMOracle receives the already computed authoritative "
                "response and may only copy its message exactly. It is not a "
                "probabilistic God LLM that reads the full private scientific truth "
                "and generates evidence."
            ),
            "required_comparison_modes": [
                "deterministic CaseOracle + WorldModel",
                "probabilistic full-private-truth God LLM",
            ],
        },
        "families": rows,
        "interpretation": {
            "machine_contract": (
                "Executable consistency is necessary but not sufficient for source-level "
                "scientific correctness."
            ),
            "semantic_flags": (
                "Flags identify missing contract information that requires scientific "
                "review; they are not automatically formula errors."
            ),
            "presentation_warnings": (
                "Canonical neutral prose emitted by the public-leakage compiler is a "
                "presentation note, not a scientific or information-completeness failure "
                "when controls and readouts remain operationally explicit."
            ),
        },
    }
    OUTPUT.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(payload["headline"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
