"""Derive a smaller coordinator-ready cohort from a validated acquisition."""

from __future__ import annotations

import copy
import json
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence, Tuple, Union

from role_benchmark.wire import canonical_json_dumps

from .acquisition import (
    MAX_COORDINATOR_COHORT_SIZE,
    validate_acquisition_cohort_handoff,
)
from .warmup import parse_warmup_cohort_json


PathLike = Union[str, Path]


def _read_object(path: Path) -> Mapping[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("cannot read JSON object: %s" % path) from exc
    if not isinstance(payload, Mapping):
        raise ValueError("expected a JSON object: %s" % path)
    return payload


def _write_object(path: Path, payload: Mapping[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _cohort_path(value: PathLike) -> Path:
    path = Path(value).resolve()
    if path.is_dir():
        path = path / "cohort.json"
    if not path.is_file():
        raise ValueError("input cohort does not exist: %s" % path)
    return path


def _selected_ids(
    paper_ids: Iterable[str], available_ids: Sequence[str]
) -> Tuple[str, ...]:
    requested = tuple(paper_ids)
    if not 1 <= len(requested) <= MAX_COORDINATOR_COHORT_SIZE:
        raise ValueError(
            "paper_ids must contain between 1 and %d ids"
            % MAX_COORDINATOR_COHORT_SIZE
        )
    if any(not isinstance(paper_id, str) or not paper_id for paper_id in requested):
        raise ValueError("paper_ids must be non-empty strings")
    duplicate_ids = sorted(
        paper_id
        for paper_id, count in Counter(requested).items()
        if count > 1
    )
    if duplicate_ids:
        raise ValueError("duplicate paper_ids: %s" % ", ".join(duplicate_ids))
    available = set(available_ids)
    unknown_ids = sorted(set(requested) - available)
    if unknown_ids:
        raise ValueError("unknown paper_ids: %s" % ", ".join(unknown_ids))
    requested_set = set(requested)
    # A cohort is already an ordered scientific input.  Selecting a subset must
    # not make its order depend on the order of repeated CLI flags.
    return tuple(paper_id for paper_id in available_ids if paper_id in requested_set)


def _source_path(base_directory: Path, raw_path: Any, field: str) -> Path:
    if not isinstance(raw_path, str) or not raw_path:
        raise ValueError("selected paper has invalid %s" % field)
    path = Path(raw_path)
    if not path.is_absolute():
        path = base_directory / path
    path = path.resolve()
    if not path.is_file():
        raise ValueError("selected paper source is missing: %s" % path)
    return path


def _source_acquired_results(
    acquisition: Mapping[str, Any],
) -> Tuple[Mapping[str, Any], ...]:
    raw_results = acquisition.get("paper_results")
    if not isinstance(raw_results, list):
        raise ValueError("acquisition paper_results must be an array")
    results = tuple(
        result
        for result in raw_results
        if isinstance(result, Mapping)
        and result.get("disposition") == "source_acquired"
    )
    dois = []
    for result in results:
        journal = result.get("journal")
        doi = journal.get("doi") if isinstance(journal, Mapping) else None
        if not isinstance(doi, str) or not doi:
            raise ValueError("source-acquired paper result has no journal DOI")
        dois.append(doi)
    if len(set(dois)) != len(dois):
        raise ValueError("source-acquired paper result DOI values must be unique")
    return results


def _build_selected_handoff(
    cohort: Mapping[str, Any],
    acquisition: Mapping[str, Any],
    *,
    input_directory: Path,
    paper_ids: Iterable[str],
) -> Tuple[Mapping[str, Any], Mapping[str, Any], Tuple[Tuple[Path, str], ...]]:
    raw_papers = cohort.get("papers")
    if not isinstance(raw_papers, list):
        raise ValueError("cohort papers must be an array")
    available_ids = [paper.get("paper_id") for paper in raw_papers]
    if any(not isinstance(paper_id, str) for paper_id in available_ids):
        raise ValueError("cohort paper_id values must be text")
    selected_ids = _selected_ids(paper_ids, available_ids)
    selected_set = set(selected_ids)

    selected_entries = []
    copies = []
    by_doi = {}
    original_entry_by_doi = {}
    for raw_entry in raw_papers:
        if raw_entry["paper_id"] not in selected_set:
            continue
        entry = copy.deepcopy(raw_entry)
        paper_id = entry["paper_id"]
        tex_source = _source_path(input_directory, entry.get("tex_path"), "tex_path")
        tex_relative = "papers/%s/source.tex" % paper_id
        entry["tex_path"] = tex_relative
        copies.append((tex_source, tex_relative))
        if entry.get("source_packet_path") is not None:
            packet_source = _source_path(
                input_directory,
                entry["source_packet_path"],
                "source_packet_path",
            )
            packet_relative = "papers/%s/source_packet.txt" % paper_id
            entry["source_packet_path"] = packet_relative
            copies.append((packet_source, packet_relative))
        selected_entries.append(entry)
        by_doi[entry["journal_doi"]] = entry
        original_entry_by_doi[entry["journal_doi"]] = raw_entry

    output_acquisition = copy.deepcopy(acquisition)
    policy = output_acquisition["selection"]["policy"]
    acquired_results = _source_acquired_results(output_acquisition)
    chosen_dois = [entry["journal_doi"] for entry in selected_entries]
    chosen_doi_set = set(chosen_dois)

    indexed_remaining = []
    for index, result in enumerate(acquired_results):
        journal = result["journal"]
        doi = journal["doi"]
        if doi in chosen_doi_set:
            continue
        selection = result.get("selection")
        old_rank = selection.get("rank") if isinstance(selection, Mapping) else None
        rank_key = (
            old_rank
            if isinstance(old_rank, int) and not isinstance(old_rank, bool)
            else 10**12
        )
        indexed_remaining.append((rank_key, index, doi))
    ranked_dois = chosen_dois + [
        doi for _, _, doi in sorted(indexed_remaining)
    ]
    rank_by_doi = {doi: rank for rank, doi in enumerate(ranked_dois, start=1)}

    selected_result_by_doi = {}
    for result in output_acquisition["paper_results"]:
        if result.get("disposition") != "source_acquired":
            result["selection"] = {
                "policy": policy,
                "rank": None,
                "selected": False,
                "status": "ineligible",
            }
            continue
        doi = result["journal"]["doi"]
        is_selected = doi in chosen_doi_set
        result["selection"] = {
            "policy": policy,
            "rank": rank_by_doi[doi] if policy == "citation_rank" else None,
            "selected": is_selected,
            "status": "selected" if is_selected else "not_selected",
        }
        if not is_selected:
            result["cohort_entry"] = None
            continue
        entry = copy.deepcopy(by_doi[doi])
        source = result.get("source")
        if not isinstance(source, Mapping):
            raise ValueError("selected paper has no source provenance")
        original_entry = original_entry_by_doi[doi]
        if source.get("tex_path") != original_entry.get("tex_path"):
            raise ValueError(
                "selected paper source tex_path differs from its cohort entry"
            )
        if source.get("source_packet_path") != original_entry.get(
            "source_packet_path"
        ):
            raise ValueError(
                "selected paper source_packet_path differs from its cohort entry"
            )
        source = dict(source)
        source["tex_path"] = entry["tex_path"]
        if "source_packet_path" in entry:
            source["source_packet_path"] = entry["source_packet_path"]
        elif "source_packet_path" in source:
            source.pop("source_packet_path")
        result["source"] = source
        result["cohort_entry"] = entry
        selected_result_by_doi[doi] = result

    if set(selected_result_by_doi) != chosen_doi_set:
        raise ValueError("selected cohort papers are missing acquisition results")

    provenance = copy.deepcopy(cohort["provenance"])
    provenance.update(
        {
            "coordinator_ready": True,
            "handoff_status": "coordinator_ready",
            "selected_count": len(selected_entries),
        }
    )
    output_cohort = {
        "papers": selected_entries,
        "provenance": provenance,
        "window": copy.deepcopy(cohort["window"]),
    }
    output_acquisition["cohort"] = output_cohort
    output_acquisition["warmup_handoff"] = copy.deepcopy(provenance)
    output_acquisition["selection"]["cohort_limit"] = len(selected_entries)
    counts = Counter(
        result["selection"]["status"]
        for result in output_acquisition["paper_results"]
    )
    output_acquisition["selection_counts"] = {
        "ineligible": counts.get("ineligible", 0),
        "not_selected": counts.get("not_selected", 0),
        "selected": counts.get("selected", 0),
    }
    validate_acquisition_cohort_handoff(output_cohort, output_acquisition)
    return output_cohort, output_acquisition, tuple(copies)


def _expected_files(
    acquisition: Mapping[str, Any], copies: Sequence[Tuple[Path, str]]
) -> Mapping[str, bytes]:
    expected = {relative: source.read_bytes() for source, relative in copies}
    for result in acquisition["paper_results"]:
        selection = result.get("selection")
        if not isinstance(selection, Mapping) or selection.get("status") != "selected":
            continue
        paper_id = result["cohort_entry"]["paper_id"]
        expected["papers/%s/paper.json" % paper_id] = (
            json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        ).encode("utf-8")
    return expected


def _materialize(
    directory: Path,
    cohort: Mapping[str, Any],
    acquisition: Mapping[str, Any],
    copies: Sequence[Tuple[Path, str]],
) -> None:
    directory.mkdir(parents=True, exist_ok=False)
    for relative, payload in _expected_files(acquisition, copies).items():
        path = directory / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
    _write_object(directory / "cohort.json", cohort)
    _write_object(directory / "acquisition.json", acquisition)
    validate_acquisition_cohort_handoff(cohort, acquisition)
    parse_warmup_cohort_json(
        (directory / "cohort.json").read_text(encoding="utf-8"),
        base_directory=directory,
    )


def _compatible_output(
    directory: Path,
    cohort: Mapping[str, Any],
    acquisition: Mapping[str, Any],
    copies: Sequence[Tuple[Path, str]],
) -> bool:
    try:
        existing_cohort = _read_object(directory / "cohort.json")
        existing_acquisition = _read_object(directory / "acquisition.json")
        validate_acquisition_cohort_handoff(existing_cohort, existing_acquisition)
        parse_warmup_cohort_json(
            (directory / "cohort.json").read_text(encoding="utf-8"),
            base_directory=directory,
        )
    except (OSError, ValueError):
        return False
    if canonical_json_dumps(existing_cohort) != canonical_json_dumps(cohort):
        return False
    if canonical_json_dumps(existing_acquisition) != canonical_json_dumps(
        acquisition
    ):
        return False
    expected = _expected_files(acquisition, copies)
    actual_paths = {
        path.relative_to(directory).as_posix()
        for path in directory.rglob("*")
        if path.is_file() and path.name not in {"cohort.json", "acquisition.json"}
    }
    if actual_paths != set(expected):
        return False
    return all(
        (directory / relative).read_bytes() == payload
        for relative, payload in expected.items()
    )


def select_temporal_cohort(
    input_cohort: PathLike,
    output_directory: PathLike,
    *,
    paper_ids: Iterable[str],
) -> Mapping[str, Any]:
    """Select an ordered subset without reacquiring or changing paper facts.

    The input must be a validated ``cohort.json`` with a sibling
    ``acquisition.json``.  The returned mapping is the derived acquisition
    payload.  Repeating the exact operation is idempotent; any other non-empty
    output is refused.
    """

    cohort_path = _cohort_path(input_cohort)
    input_directory = cohort_path.parent
    acquisition_path = input_directory / "acquisition.json"
    if not acquisition_path.is_file():
        raise ValueError("input cohort must be accompanied by acquisition.json")
    cohort_text = cohort_path.read_text(encoding="utf-8")
    cohort = _read_object(cohort_path)
    acquisition = _read_object(acquisition_path)
    validate_acquisition_cohort_handoff(cohort, acquisition)
    parse_warmup_cohort_json(cohort_text, base_directory=input_directory)

    selected_cohort, selected_acquisition, copies = _build_selected_handoff(
        cohort,
        acquisition,
        input_directory=input_directory,
        paper_ids=paper_ids,
    )
    output = Path(output_directory).resolve()
    if output.exists():
        if not output.is_dir():
            raise ValueError("output exists and is not a directory: %s" % output)
        if any(output.iterdir()):
            if _compatible_output(output, selected_cohort, selected_acquisition, copies):
                return selected_acquisition
            raise ValueError("existing output is incompatible: %s" % output)

    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix=".%s-" % output.name,
        dir=str(output.parent),
    ) as temporary:
        staged = Path(temporary) / "selected"
        _materialize(staged, selected_cohort, selected_acquisition, copies)
        if output.exists():
            output.rmdir()
        staged.rename(output)

    written_cohort = _read_object(output / "cohort.json")
    written_acquisition = _read_object(output / "acquisition.json")
    validate_acquisition_cohort_handoff(written_cohort, written_acquisition)
    parse_warmup_cohort_json(
        (output / "cohort.json").read_text(encoding="utf-8"),
        base_directory=output,
    )
    return written_acquisition


__all__ = ["select_temporal_cohort"]
