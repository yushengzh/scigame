"""Prepare and validate an emergency Code Agent Temporal production run.

This adapter does not call an LLM API.  It freezes the ordinary minimal
ScienceCard request so a Code Agent session can place the provider-facing JSON
object in ``authoring/raw_response.json``.  All parsing, source review,
admission, case construction, and task-setting checks reuse the main Temporal
implementation.

The API-backed production runner remains ``experiments/run_temporal_conversion.py``.
This file is a separate execution adapter and does not replace that runner.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping, Optional, Sequence

from role_benchmark import (
    BenchmarkTrack,
    Episode,
    Hypothesis,
    HypothesisPortfolio,
    PlayerAction,
)
from role_benchmark.cases.source import (
    make_source_case,
    source_truth_submission,
)
from role_benchmark.llm import generation_request_to_payload
from role_benchmark.temporal import (
    ScienceSource,
    assess_temporal_admission,
    build_minimal_science_card_request,
    canonicalize_doi,
    compile_temporal_source_case,
    download_arxiv_source,
    minimal_science_card_to_payload,
    normalize_latex,
    normalize_source_packet,
    parse_minimal_science_card_json,
    parse_minimal_science_card_provider_payload,
    parse_temporal_admission_review_json,
    parse_versioned_arxiv_id,
    render_temporal_source_case_module,
    temporal_admission_review_request_payload,
    validate_minimal_science_card_lineage,
)


PREPARATION_SCHEMA = "role_benchmark.temporal_code_agent_preparation.v1"
EXECUTION_SCHEMA = "role_benchmark.temporal_code_agent_execution.v1"
CARD_VALIDATION_SCHEMA = "role_benchmark.temporal_code_agent_card_validation.v1"
CONSTRUCTION_SCHEMA = "role_benchmark.temporal_code_agent_construction.v1"
SUMMARY_SCHEMA = "role_benchmark.temporal_code_agent_summary.v1"
DEFAULT_MODEL_LABEL = "gpt-5.6-fast"
_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_PAPER_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")


class ProductionAdapterError(ValueError):
    """An emergency-production artifact violates the adapter contract."""


def _decode_json_text(text: str, *, description: str) -> Any:
    def reject_constant(value: str) -> None:
        raise ValueError("non-finite JSON constant %s" % value)

    def unique_object(pairs: Iterable[tuple[str, Any]]) -> Dict[str, Any]:
        result: Dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate object key %s" % key)
            result[key] = value
        return result

    try:
        return json.loads(
            text,
            parse_constant=reject_constant,
            object_pairs_hook=unique_object,
        )
    except (json.JSONDecodeError, ValueError) as exc:
        raise ProductionAdapterError(
            "%s must contain exactly one strict JSON value" % description
        ) from exc


def _read_json(path: Path, *, description: Optional[str] = None) -> Any:
    if not path.is_file():
        raise ProductionAdapterError("required artifact is missing: %s" % path)
    return _decode_json_text(
        path.read_text(encoding="utf-8"),
        description=description or str(path),
    )


def _render_json(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_render_json(payload), encoding="utf-8")


def _write_once_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_text(encoding="utf-8") != text:
            raise ProductionAdapterError(
                "frozen artifact differs from the existing file: %s" % path
            )
        return
    path.write_text(text, encoding="utf-8")


def _write_once_json(path: Path, payload: Any) -> None:
    _write_once_text(path, _render_json(payload))


def _error_payload(stage: str, error: BaseException) -> Mapping[str, Any]:
    payload: Dict[str, Any] = {
        "stage": stage,
        "error_type": type(error).__name__,
        "error": str(error),
    }
    for name in ("code", "path", "detail"):
        value = getattr(error, name, None)
        if value is not None:
            payload["error_" + name] = value
    return payload


def _source_value(source: Mapping[str, Any], *names: str) -> str:
    for name in names:
        value = source.get(name)
        if isinstance(value, str) and value.strip():
            return value.strip()
    raise ProductionAdapterError(
        "source is missing required field %s" % " or ".join(names)
    )


def _source_identity(source: Mapping[str, Any]) -> ScienceSource:
    citation = _source_value(source, "source_citation", "citation")
    doi = _source_value(source, "journal_doi")
    if canonicalize_doi(doi) != doi:
        raise ProductionAdapterError(
            "journal_doi must already use the canonical DOI form"
        )
    arxiv_id = _source_value(source, "arxiv_versioned_id")
    if parse_versioned_arxiv_id(arxiv_id) != arxiv_id:
        raise ProductionAdapterError(
            "arxiv_versioned_id must be an exact versioned identifier"
        )
    return ScienceSource(
        citation=citation,
        journal_doi=doi,
        arxiv_versioned_id=arxiv_id,
    )


def _validate_manifest(payload: Any) -> list[Mapping[str, Any]]:
    if not isinstance(payload, dict) or not isinstance(payload.get("sources"), list):
        raise ProductionAdapterError("frozen source manifest must contain sources")
    family_index_offset = payload.get("family_index_offset", 0)
    if (
        isinstance(family_index_offset, bool)
        or not isinstance(family_index_offset, int)
        or family_index_offset < 0
    ):
        raise ProductionAdapterError(
            "family_index_offset must be a non-negative integer"
        )
    sources = payload["sources"]
    if not sources:
        raise ProductionAdapterError("frozen source manifest must not be empty")
    if "cohort_size" in payload and payload["cohort_size"] != len(sources):
        raise ProductionAdapterError("cohort_size differs from the source count")
    paper_ids = []
    orders = []
    for source in sources:
        if not isinstance(source, dict):
            raise ProductionAdapterError("every frozen source must be an object")
        paper_id = _source_value(source, "paper_id")
        if _PAPER_ID.fullmatch(paper_id) is None:
            raise ProductionAdapterError("paper_id contains unsupported characters")
        order = source.get("order")
        if isinstance(order, bool) or not isinstance(order, int) or order < 1:
            raise ProductionAdapterError("source order must be a positive integer")
        _source_identity(source)
        priority = source.get("venue_priority_rank")
        if (
            isinstance(priority, bool)
            or not isinstance(priority, int)
            or priority < 1
        ):
            raise ProductionAdapterError(
                "venue_priority_rank must be a positive integer"
            )
        dates = {}
        for field in (
            "journal_publication_date",
            "arxiv_first_submitted_date",
            "earliest_public_date",
        ):
            raw_date = source.get(field)
            if not isinstance(raw_date, str):
                raise ProductionAdapterError("%s must be an ISO date" % field)
            try:
                dates[field] = date.fromisoformat(raw_date)
            except ValueError as exc:
                raise ProductionAdapterError(
                    "%s must be an ISO calendar date" % field
                ) from exc
        if dates["earliest_public_date"] != min(
            dates["journal_publication_date"],
            dates["arxiv_first_submitted_date"],
        ):
            raise ProductionAdapterError(
                "earliest_public_date must equal the earlier journal or arXiv date"
            )
        _source_value(source, "linkage_method")
        evidence = source.get("linkage_evidence")
        if not isinstance(evidence, dict) or not evidence:
            raise ProductionAdapterError("linkage_evidence must be a non-empty object")
        paper_ids.append(paper_id)
        orders.append(order)
    if len(set(paper_ids)) != len(paper_ids):
        raise ProductionAdapterError("paper_id values must be unique")
    if orders != list(range(1, len(sources) + 1)):
        raise ProductionAdapterError(
            "manifest sources must remain in contiguous frozen order"
        )
    return sources


def _load_frozen_sources(output: Path) -> tuple[Mapping[str, Any], list[Mapping[str, Any]]]:
    payload = _read_json(
        output / "frozen_sources.json", description="frozen source manifest"
    )
    return payload, _validate_manifest(payload)


def _paper_directory(output: Path, source: Mapping[str, Any]) -> Path:
    return output / "papers" / ("%03d_%s" % (source["order"], source["paper_id"]))


def _select_sources(
    sources: Sequence[Mapping[str, Any]], paper_ids: Sequence[str]
) -> list[Mapping[str, Any]]:
    if not paper_ids:
        return list(sources)
    requested = set(paper_ids)
    available = {str(source["paper_id"]) for source in sources}
    missing = sorted(requested - available)
    if missing:
        raise ProductionAdapterError(
            "paper_id is absent from the frozen manifest: %s" % ", ".join(missing)
        )
    return [source for source in sources if source["paper_id"] in requested]


def _resolve_local_source_path(
    source: Mapping[str, Any], manifest_path: Path
) -> Optional[Path]:
    raw = source.get("local_source_packet_path", source.get("source_packet_path"))
    if raw is None:
        return None
    if not isinstance(raw, str) or not raw.strip():
        raise ProductionAdapterError(
            "local_source_packet_path must be non-empty text when supplied"
        )
    path = Path(raw)
    if path.is_absolute():
        return path.resolve()
    candidates = [
        (_PROJECT_ROOT / path).resolve(),
        (manifest_path.parent / path).resolve(),
    ]
    existing = []
    for candidate in candidates:
        if candidate.is_file() and candidate not in existing:
            existing.append(candidate)
    if len(existing) > 1:
        raise ProductionAdapterError(
            "relative source path is ambiguous between project and manifest roots"
        )
    return existing[0] if existing else candidates[0]


def _execution_skeleton(model_label: str) -> Mapping[str, Any]:
    if not isinstance(model_label, str) or not model_label.strip():
        raise ProductionAdapterError("model label must be non-empty text")
    return {
        "schema": EXECUTION_SCHEMA,
        "interface": "interactive_code_agent",
        "requested_model_label": model_label.strip(),
        "api_invoked_by_adapter": False,
        "immutable_model_snapshot_id": None,
        "documented_knowledge_cutoff": {
            "status": "not_recorded",
            "date": None,
            "evidence_locator": None,
        },
        "request_artifact": "request.json",
        "raw_response_artifact": "raw_response.json",
        "execution_started_at": None,
        "execution_completed_at": None,
        "token_usage": None,
        "response_identifier": None,
        "recording_instruction": (
            "Populate only observed execution metadata. Place exactly the "
            "provider-facing {relations: [...]} JSON object in raw_response.json."
        ),
    }


def prepare(
    manifest_path: Path,
    output: Path,
    *,
    model_label: str = DEFAULT_MODEL_LABEL,
    offline: bool = False,
) -> Mapping[str, Any]:
    manifest_path = manifest_path.resolve()
    manifest = _read_json(manifest_path, description="source manifest")
    sources = _validate_manifest(manifest)
    output.mkdir(parents=True, exist_ok=True)
    _write_once_json(output / "frozen_sources.json", manifest)
    failures = []
    prepared = []
    for source in sources:
        paper_directory = _paper_directory(output, source)
        paper_directory.mkdir(parents=True, exist_ok=True)
        try:
            identity = _source_identity(source)
            _write_once_json(paper_directory / "source.json", dict(source))
            local_path = _resolve_local_source_path(source, manifest_path)
            source_tex: Optional[str] = None
            if local_path is not None and local_path.is_file():
                raw = local_path.read_text(encoding="utf-8")
                if local_path.suffix.lower() == ".tex":
                    source_tex = normalize_latex(raw)
                    source_packet = source_tex
                    retrieval = "local_latex"
                else:
                    source_packet = normalize_source_packet(raw)
                    retrieval = "local_source_packet"
                retrieval_record: Mapping[str, Any] = {
                    "method": retrieval,
                    "input_path": str(local_path),
                    "arxiv_versioned_id": identity.arxiv_versioned_id,
                }
            else:
                if offline:
                    if local_path is None:
                        detail = "no local source packet is declared"
                    else:
                        detail = "local source packet does not exist: %s" % local_path
                    raise ProductionAdapterError(
                        "%s and network retrieval is disabled" % detail
                    )
                bundle = download_arxiv_source(identity.arxiv_versioned_id)
                source_tex = normalize_source_packet(bundle.merged_text)
                source_packet = normalize_source_packet(bundle.source_packet_text)
                retrieval_record = {
                    "method": "arxiv_exact_version_source_download",
                    "input_path": None,
                    "arxiv_versioned_id": identity.arxiv_versioned_id,
                }
            if source_tex is not None:
                _write_once_text(paper_directory / "source.tex", source_tex)
            _write_once_text(paper_directory / "source_packet.txt", source_packet)
            request = build_minimal_science_card_request(
                source_packet,
                source_citation=identity.citation,
                journal_doi=identity.journal_doi,
                arxiv_versioned_id=identity.arxiv_versioned_id,
                source_format="source_packet",
            )
            authoring = paper_directory / "authoring"
            _write_once_json(
                authoring / "request.json", generation_request_to_payload(request)
            )
            _write_once_json(
                authoring / "execution.json", _execution_skeleton(model_label)
            )
            preparation = {
                "schema": PREPARATION_SCHEMA,
                "paper_id": source["paper_id"],
                "order": source["order"],
                "status": "prepared",
                "source_line_count": len(source_packet.splitlines()),
                "retrieval": retrieval_record,
                "authoring_request": "authoring/request.json",
                "authoring_execution": "authoring/execution.json",
            }
            _write_json(paper_directory / "preparation.json", preparation)
            prepared.append(source["paper_id"])
        except Exception as exc:
            failure = {
                "schema": PREPARATION_SCHEMA,
                "paper_id": source.get("paper_id"),
                "order": source.get("order"),
                "status": "preparation_failed",
                **_error_payload("prepare", exc),
            }
            _write_json(paper_directory / "preparation_failure.json", failure)
            failures.append(failure)
    result = {
        "schema": PREPARATION_SCHEMA,
        "cohort_size": len(sources),
        "prepared_count": len(prepared),
        "failed_count": len(failures),
        "prepared_paper_ids": prepared,
        "failures": failures,
        "authoring_model_label": model_label,
        "api_invoked_by_adapter": False,
    }
    _write_json(output / "preparation_result.json", result)
    return result


def _load_card_for_source(
    paper_directory: Path, source: Mapping[str, Any], source_line_count: int
) -> Any:
    card = parse_minimal_science_card_json(
        (paper_directory / "science_card.json").read_text(encoding="utf-8")
    )
    expected = _source_identity(source)
    if card.source != expected:
        raise ProductionAdapterError("minimal ScienceCard identifies another source")
    validate_minimal_science_card_lineage(card, source_line_count)
    return card


def validate_cards(
    output: Path, *, paper_ids: Sequence[str] = ()
) -> Mapping[str, Any]:
    _, sources = _load_frozen_sources(output)
    selected = _select_sources(sources, paper_ids)
    completed = []
    skipped = []
    failures = []
    for source in selected:
        paper_directory = _paper_directory(output, source)
        raw_response = paper_directory / "authoring" / "raw_response.json"
        if not raw_response.is_file() and not paper_ids:
            skipped.append(source["paper_id"])
            continue
        try:
            if not raw_response.is_file():
                raise ProductionAdapterError(
                    "Code Agent response is missing: %s" % raw_response
                )
            source_packet = normalize_source_packet(
                (paper_directory / "source_packet.txt").read_text(encoding="utf-8")
            )
            payload = _read_json(
                raw_response, description="Code Agent provider-facing response"
            )
            card = parse_minimal_science_card_provider_payload(
                payload,
                source=_source_identity(source),
            )
            validate_minimal_science_card_lineage(card, len(source_packet.splitlines()))
            _write_once_json(
                paper_directory / "science_card.json",
                minimal_science_card_to_payload(card),
            )
            _write_once_json(
                paper_directory / "source_review_request.json",
                temporal_admission_review_request_payload(
                    card, paper_id=str(source["paper_id"])
                ),
            )
            validation = {
                "schema": CARD_VALIDATION_SCHEMA,
                "paper_id": source["paper_id"],
                "status": (
                    "structurally_valid_nonempty_relation"
                    if card.relations
                    else "valid_abstention"
                ),
                "response_schema_valid": True,
                "source_lineage_valid": True,
                "nonempty_relation": bool(card.relations),
            }
            _write_json(paper_directory / "authoring" / "validation.json", validation)
            completed.append(validation)
        except Exception as exc:
            failure = {
                "schema": CARD_VALIDATION_SCHEMA,
                "paper_id": source.get("paper_id"),
                "status": "card_validation_failed",
                **_error_payload("validate-card", exc),
            }
            _write_json(
                paper_directory / "authoring" / "validation_failure.json", failure
            )
            failures.append(failure)
    return {
        "schema": CARD_VALIDATION_SCHEMA,
        "selected_count": len(selected),
        "completed_count": len(completed),
        "skipped_missing_response_count": len(skipped),
        "failed_count": len(failures),
        "completed": completed,
        "skipped_paper_ids": skipped,
        "failures": failures,
    }


def _validate_case(spec: Any) -> Mapping[str, Any]:
    cells = []
    for track in (BenchmarkTrack.IDENTIFICATION, BenchmarkTrack.DISCOVERY):
        case = make_source_case(spec, track)
        portfolio = HypothesisPortfolio(
            (
                Hypothesis(
                    hypothesis_id="H1",
                    statement="Known-truth Temporal case validation.",
                    confidence=1.0,
                ),
            )
        )
        episode = Episode(case)
        episode.apply(
            PlayerAction.submit_final(
                portfolio,
                source_truth_submission(spec, track),
            )
        )
        outcome = episode.outcome
        passed = bool(
            outcome.active_pass
            and outcome.protocol_completed
            and outcome.evaluation.success
            and outcome.evaluation.scores.get("predictive_model_pass") == 1.0
        )
        cells.append({"track": track.value, "known_truth_passes": passed})
    if not all(cell["known_truth_passes"] for cell in cells):
        raise RuntimeError(
            "compiled source case failed Identification or Discovery validation"
        )
    return {"all_pass": True, "cells": cells}


def compile_cases(
    output: Path, *, paper_ids: Sequence[str] = ()
) -> Mapping[str, Any]:
    manifest, sources = _load_frozen_sources(output)
    family_index_offset = int(manifest.get("family_index_offset", 0))
    selected = _select_sources(sources, paper_ids)
    completed = []
    skipped = []
    failures = []
    for source in selected:
        paper_directory = _paper_directory(output, source)
        review_path = paper_directory / "source_review.json"
        if not review_path.is_file() and not paper_ids:
            skipped.append(source["paper_id"])
            continue
        admission = None
        try:
            if not review_path.is_file():
                raise ProductionAdapterError(
                    "source review is missing: %s" % review_path
                )
            source_packet = normalize_source_packet(
                (paper_directory / "source_packet.txt").read_text(encoding="utf-8")
            )
            line_count = len(source_packet.splitlines())
            card = _load_card_for_source(paper_directory, source, line_count)
            review = parse_temporal_admission_review_json(
                review_path.read_text(encoding="utf-8")
            )
            admission = assess_temporal_admission(
                card,
                review,
                paper_id=str(source["paper_id"]),
                source_line_count=line_count,
            )
            if not admission.admitted:
                result = {
                    "schema": CONSTRUCTION_SCHEMA,
                    "paper_id": source["paper_id"],
                    "status": admission.disposition,
                    "source_review_completed": True,
                    "source_review_retained": False,
                    "review_independence_established_by_adapter": False,
                    "issues": [
                        {
                            "code": issue.code,
                            "detail": issue.detail,
                            "blocking": issue.blocking,
                        }
                        for issue in admission.issues
                    ],
                }
                _write_json(paper_directory / "construction" / "result.json", result)
                completed.append(result)
                continue
            case_index = family_index_offset + int(source["order"])
            build = compile_temporal_source_case(admission, case_index=case_index)
            module = render_temporal_source_case_module(
                admission, case_index=case_index
            )
            construction = paper_directory / "construction"
            module_path = construction / "cases" / (build.spec.family + ".py")
            _write_once_text(module_path, module)
            _write_once_json(construction / "provenance.json", build.provenance)
            validation = _validate_case(build.spec)
            _write_once_json(construction / "validation.json", validation)
            result = {
                "schema": CONSTRUCTION_SCHEMA,
                "paper_id": source["paper_id"],
                "status": "case_accepted",
                "source_review_completed": True,
                "source_review_retained": True,
                "reviewer": review.reviewer,
                "review_independence_established_by_adapter": False,
                "family": build.spec.family,
                "case_module": str(module_path.relative_to(paper_directory)),
                "provenance": "construction/provenance.json",
                "validation": "construction/validation.json",
            }
            _write_json(construction / "result.json", result)
            completed.append(result)
        except Exception as exc:
            if admission is not None and admission.admitted:
                result = {
                    "schema": CONSTRUCTION_SCHEMA,
                    "paper_id": source.get("paper_id"),
                    "status": "construction_rejected",
                    "source_review_completed": True,
                    "source_review_retained": True,
                    "reviewer": admission.review.reviewer,
                    "review_independence_established_by_adapter": False,
                    **_error_payload("compile", exc),
                }
                _write_json(
                    paper_directory / "construction" / "result.json", result
                )
                completed.append(result)
                continue
            failure = {
                "schema": CONSTRUCTION_SCHEMA,
                "paper_id": source.get("paper_id"),
                "status": "construction_failed",
                **_error_payload("compile", exc),
            }
            _write_json(
                paper_directory / "construction" / "failure.json", failure
            )
            failures.append(failure)
    return {
        "schema": CONSTRUCTION_SCHEMA,
        "selected_count": len(selected),
        "completed_count": len(completed),
        "skipped_missing_review_count": len(skipped),
        "failed_count": len(failures),
        "completed": completed,
        "skipped_paper_ids": skipped,
        "failures": failures,
    }


def _rate(count: int, denominator: int) -> Mapping[str, Any]:
    return {
        "count": count,
        "denominator": denominator,
        "rate": count / denominator,
    }


def summarize(output: Path, *, target_family_count: int = 20) -> Mapping[str, Any]:
    if (
        isinstance(target_family_count, bool)
        or not isinstance(target_family_count, int)
        or target_family_count < 1
    ):
        raise ProductionAdapterError("target family count must be positive")
    manifest, sources = _load_frozen_sources(output)
    family_index_offset = int(manifest.get("family_index_offset", 0))
    denominator = len(sources)
    prepared = 0
    responses = 0
    response_schema_valid = 0
    nonempty = 0
    reviews_completed = 0
    retained = 0
    accepted = 0
    families = []
    dispositions: Dict[str, int] = {}
    papers = []
    model_labels = set()
    for source in sources:
        paper_directory = _paper_directory(output, source)
        status = "source_preparation_missing"
        packet_path = paper_directory / "source_packet.txt"
        packet = None
        if packet_path.is_file():
            prepared += 1
            status = "authoring_response_missing"
            try:
                packet = normalize_source_packet(
                    packet_path.read_text(encoding="utf-8")
                )
            except Exception:
                status = "source_packet_invalid"
        execution_path = paper_directory / "authoring" / "execution.json"
        if execution_path.is_file():
            execution = _read_json(execution_path)
            label = execution.get("requested_model_label")
            if isinstance(label, str) and label.strip():
                model_labels.add(label.strip())
        raw_response = paper_directory / "authoring" / "raw_response.json"
        response_card = None
        if raw_response.is_file():
            responses += 1
            status = "authoring_response_invalid"
            if packet is not None:
                try:
                    response_card = parse_minimal_science_card_provider_payload(
                        _read_json(
                            raw_response,
                            description="Code Agent provider-facing response",
                        ),
                        source=_source_identity(source),
                    )
                    validate_minimal_science_card_lineage(
                        response_card, len(packet.splitlines())
                    )
                    response_schema_valid += 1
                    if response_card.relations:
                        nonempty += 1
                        status = "card_validation_missing"
                    else:
                        status = "no_relation_extracted"
                except Exception:
                    response_card = None
        card_path = paper_directory / "science_card.json"
        card = None
        if card_path.is_file() and response_card is not None:
            try:
                card = _load_card_for_source(
                    paper_directory, source, len(packet.splitlines())
                )
                if minimal_science_card_to_payload(card) != minimal_science_card_to_payload(
                    response_card
                ):
                    raise ProductionAdapterError(
                        "ScienceCard differs from the current raw response"
                    )
                if card.relations:
                    status = "source_review_missing"
                else:
                    status = "no_relation_extracted"
            except Exception:
                card = None
                status = "card_artifact_invalid"
        construction_path = paper_directory / "construction" / "result.json"
        if construction_path.is_file():
            construction = _read_json(construction_path)
            if construction.get("source_review_completed") is True:
                reviews_completed += 1
            if construction.get("source_review_retained") is True:
                retained += 1
            status = str(construction.get("status", "invalid_construction_result"))
            if status == "case_accepted":
                family = construction.get("family")
                validation_path = paper_directory / "construction" / "validation.json"
                module_path = paper_directory / str(construction.get("case_module", ""))
                validation = (
                    _read_json(validation_path) if validation_path.is_file() else {}
                )
                if (
                    isinstance(family, str)
                    and family.strip()
                    and module_path.is_file()
                    and validation.get("all_pass") is True
                ):
                    accepted += 1
                    families.append(family)
                else:
                    status = "accepted_artifacts_incomplete"
        failure_path = paper_directory / "construction" / "failure.json"
        if failure_path.is_file() and not construction_path.is_file():
            status = "construction_failed"
        dispositions[status] = dispositions.get(status, 0) + 1
        papers.append({"paper_id": source["paper_id"], "status": status})
    if len(families) != len(set(families)):
        raise ProductionAdapterError("accepted family identifiers are not distinct")
    summary = {
        "schema": SUMMARY_SCHEMA,
        "cohort_size": denominator,
        "fixed_denominator": denominator,
        "family_index_offset": family_index_offset,
        "authoring_interface": "interactive_code_agent",
        "authoring_model_labels": sorted(model_labels),
        "api_invoked_by_adapter": False,
        "funnel": {
            "source_prepared": _rate(prepared, denominator),
            "authoring_response_present": _rate(responses, denominator),
            "authoring_response_schema_valid": _rate(
                response_schema_valid, denominator
            ),
            "nonempty_relation": _rate(nonempty, denominator),
            "source_review_completed": _rate(reviews_completed, denominator),
            "source_review_retained": _rate(retained, denominator),
            "final_acceptance": _rate(accepted, denominator),
        },
        "source_review_conditional_retention_rate": (
            retained / reviews_completed if reviews_completed else None
        ),
        "distinct_family_count": len(families),
        "distinct_families": sorted(families),
        "target_family_count": target_family_count,
        "target_met": len(families) >= target_family_count,
        "dispositions": dict(sorted(dispositions.items())),
        "papers": papers,
        "review_independence": {
            "established_by_adapter": False,
            "interpretation": (
                "The adapter records the reviewer field but does not establish "
                "human independence. A separate Code Agent context is process "
                "separation, not independent human review."
            ),
        },
    }
    _write_json(output / "summary.json", summary)
    return summary


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Prepare and validate a separate Code Agent Temporal production run; "
            "the main API runner is unchanged."
        )
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    prepare_parser = subparsers.add_parser("prepare")
    prepare_parser.add_argument("frozen_sources")
    prepare_parser.add_argument("output_directory")
    prepare_parser.add_argument("--model-label", default=DEFAULT_MODEL_LABEL)
    prepare_parser.add_argument(
        "--offline",
        action="store_true",
        help="fail instead of downloading a missing local source packet",
    )

    for name in ("validate-card", "compile"):
        command = subparsers.add_parser(name)
        command.add_argument("output_directory")
        command.add_argument("--paper-id", action="append", default=[])

    summarize_parser = subparsers.add_parser("summarize")
    summarize_parser.add_argument("output_directory")
    summarize_parser.add_argument("--target-family-count", type=int, default=20)
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "prepare":
        result = prepare(
            Path(args.frozen_sources),
            Path(args.output_directory),
            model_label=args.model_label,
            offline=args.offline,
        )
        exit_status = 0 if result["failed_count"] == 0 else 2
    elif args.command == "validate-card":
        result = validate_cards(
            Path(args.output_directory), paper_ids=args.paper_id
        )
        exit_status = 0 if result["failed_count"] == 0 else 2
    elif args.command == "compile":
        result = compile_cases(
            Path(args.output_directory), paper_ids=args.paper_id
        )
        exit_status = 0 if result["failed_count"] == 0 else 2
    else:
        result = summarize(
            Path(args.output_directory),
            target_family_count=args.target_family_count,
        )
        exit_status = 0 if result["target_met"] else 3
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return exit_status


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(2)
