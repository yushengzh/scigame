"""Run the draft-only science-card-to-matched-draft diagnostic stage.

The input is an already extracted science-card JSON file. The model receives
that card, never the paper source, and makes one proposal call. A complete
response with a strict JSON schema, public-lineage, or public-leakage error may receive up to
three recorded mechanical repair calls, for four total CaseDraft calls.
This standalone runner may write a draft, filter result, and family review
request, but it never renders or accepts a case.  Only
``run_temporal_warmup.py`` has acceptance authority.  Credentials are accepted
only at runtime and are not persisted.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence

from experiments.run_pendulum_matrix import DeepSeekChatBackend
from experiments.run_temporal_authoring import (
    DEFAULT_API_KEY_ENV,
    DEFAULT_ENDPOINT,
    DEFAULT_MODEL,
    _CaseDraftRecordingBackend,
    _api_key,
    _freeze_runtime_config,
    _write_json,
)
from role_benchmark import GenerationConfig, TextGenerationBackend
from role_benchmark.temporal import (
    CaseDraftError,
    ScienceCardError,
    author_case_draft,
    case_draft_batch_to_payload,
    condition_partition_bindings_to_payload,
    family_review_request_payload,
    filter_candidate,
    parse_science_card_json,
    public_prose_normalizations_to_payload,
    relationship_direction_bindings_to_payload,
    science_card_to_payload,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Draft-only diagnostic: run one strict science-card-to-matched-"
            "case proposal with at most three bounded mechanical repairs (four "
            "total calls); never render or accept a case."
        )
    )
    parser.add_argument("science_card")
    parser.add_argument("output_directory")
    parser.add_argument(
        "--paper-id",
        required=True,
        help="lower_snake_case paper identifier used by review artifacts",
    )
    parser.add_argument(
        "--response-envelope",
        action="store_true",
        help=(
            "read science_card as a recorded generation-response JSON envelope "
            "and parse its text field"
        ),
    )
    parser.add_argument("--endpoint", default=DEFAULT_ENDPOINT)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--timeout-s", type=float, default=180.0)
    parser.add_argument("--max-output-tokens", type=int, default=32768)
    credential = parser.add_mutually_exclusive_group()
    credential.add_argument("--api-key", help="runtime credential; never persisted")
    credential.add_argument(
        "--api-key-stdin", action="store_true", help="read one credential line"
    )
    credential.add_argument(
        "--prompt-api-key", action="store_true", help="prompt without echo"
    )
    parser.add_argument("--api-key-env", default=DEFAULT_API_KEY_ENV)
    return parser


def _science_card_text(path: Path, *, response_envelope: bool) -> str:
    text = path.read_text(encoding="utf-8")
    if not response_envelope:
        return text
    try:
        payload: Any = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError("response envelope must be valid JSON") from exc
    if not isinstance(payload, Mapping) or not isinstance(payload.get("text"), str):
        raise ValueError("response envelope must contain a text field")
    return payload["text"]


def run(
    args: argparse.Namespace,
    *,
    backend: Optional[TextGenerationBackend] = None,
) -> int:
    output_directory = Path(args.output_directory)
    output_directory.mkdir(parents=True, exist_ok=False)
    stage = "science_card"
    try:
        _freeze_runtime_config(
            output_directory,
            args,
            runner="temporal_case_draft",
        )
        card = parse_science_card_json(
            _science_card_text(
                Path(args.science_card),
                response_envelope=args.response_envelope,
            )
        )
        _write_json(
            output_directory / "science_card.json",
            science_card_to_payload(card),
        )
        provider = backend or DeepSeekChatBackend(
            endpoint=args.endpoint,
            api_key=_api_key(args),
            model=args.model,
            thinking="disabled",
            reasoning_effort=None,
            timeout_s=args.timeout_s,
        )

        stage = "case_draft"
        result = author_case_draft(
            _CaseDraftRecordingBackend(provider, output_directory),
            card,
            config=GenerationConfig(
                max_output_tokens=args.max_output_tokens,
                temperature=0.0,
                top_p=1.0,
            ),
            strict_source_only=True,
            max_total_attempts=4,
        )
        _write_json(
            output_directory / "draft.json",
            case_draft_batch_to_payload(result.batch),
        )
        _write_json(
            output_directory / "prose_normalizations.json",
            public_prose_normalizations_to_payload(
                getattr(result, "prose_normalizations", ())
            ),
        )
        _write_json(
            output_directory / "relationship_direction_bindings.json",
            relationship_direction_bindings_to_payload(
                getattr(result, "relationship_direction_bindings", ())
            ),
        )
        _write_json(
            output_directory / "condition_partition_bindings.json",
            condition_partition_bindings_to_payload(
                getattr(result, "condition_partition_bindings", ())
            ),
        )

        stage = "filter_and_review_request"
        candidates = []
        review_requests = []
        for draft in result.batch.drafts:
            candidate = draft.candidate
            filtered = filter_candidate(candidate)
            candidates.append(
                {
                    "eligible": filtered.eligible,
                    "family": candidate.family,
                    "issues": [
                        {
                            "code": issue.code,
                            "message": issue.message,
                            "path": issue.path,
                        }
                        for issue in filtered.issues
                    ],
                }
            )
            if filtered.eligible:
                request_path = output_directory / "family_review_request.json"
                _write_json(
                    request_path,
                    family_review_request_payload(
                        draft,
                        paper_id=args.paper_id,
                    ),
                )
                review_requests.append(
                    {"family": candidate.family, "path": str(request_path)}
                )

        eligible_count = sum(item["eligible"] for item in candidates)
        if result.batch.status == "not_authorable":
            status = "not_authorable"
        elif eligible_count == len(candidates):
            status = "awaiting_family_review"
        else:
            status = "candidate_rejected"
        filter_report = {
            "candidate_count": len(candidates),
            "candidates": candidates,
            "eligible_count": eligible_count,
            "status": status,
        }
        _write_json(output_directory / "filter.json", filter_report)

        report = {
            "draft_assessment": result.batch.assessment,
            "draft_count": len(result.batch.drafts),
            "eligible_count": eligible_count,
            "case_rendered": False,
            "model": result.response.model,
            "provider": result.response.provider,
            "review_requests": review_requests,
            "status": status,
        }
        _write_json(output_directory / "result.json", report)
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
        if status == "awaiting_family_review":
            return 3
        return 0 if status == "not_authorable" else 2
    except (CaseDraftError, ScienceCardError, OSError, RuntimeError, ValueError) as exc:
        failure = {
            "error": str(exc),
            "error_type": type(exc).__name__,
            "stage": stage,
            "status": "failed",
        }
        _write_json(output_directory / "failure.json", failure)
        print(json.dumps(failure, ensure_ascii=False, indent=2, sort_keys=True))
        return 2


def main(argv: Optional[Sequence[str]] = None) -> int:
    return run(_parser().parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
