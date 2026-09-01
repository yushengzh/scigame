"""Run the bounded temporal drafting diagnostic.

The first stage extracts a private science card from line-numbered TeX. The
second stage receives only the strictly validated card and proposes at most one
matched case draft. Each stage permits one proposal plus at most three recorded,
allowlisted mechanical repairs. This standalone runner can emit
only a draft, filter result, and family review request; it never renders or
accepts a case. The warm-up coordinator is the sole acceptance authority because it
enforces both external review gates.  Credentials are accepted only at runtime
and are not included in any persisted artifact.
"""

from __future__ import annotations

import argparse
import getpass
import json
import os
import sys
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence

from experiments.run_pendulum_matrix import DeepSeekChatBackend
from role_benchmark import (
    GenerationConfig,
    GenerationRequest,
    GenerationResponse,
    TextGenerationBackend,
)
from role_benchmark.llm import (
    generation_request_to_payload,
    generation_response_to_payload,
)
from role_benchmark.temporal import (
    CaseDraftError,
    ScienceCardError,
    author_case_draft,
    case_draft_batch_to_payload,
    condition_partition_bindings_to_payload,
    extract_science_card,
    family_review_request_payload,
    filter_candidate,
    load_latex,
    public_prose_normalizations_to_payload,
    relationship_direction_bindings_to_payload,
    science_card_to_payload,
)


DEFAULT_ENDPOINT = "https://api.deepseek.com/chat/completions"
DEFAULT_MODEL = "deepseek-v4-flash"
DEFAULT_API_KEY_ENV = "DEEPSEEK_API_KEY"
RUNTIME_CONFIG_SCHEMA = "role_benchmark.temporal_runner_config"


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _runtime_config_payload(
    args: argparse.Namespace,
    *,
    runner: str,
    additions: Optional[Mapping[str, Any]] = None,
) -> Mapping[str, Any]:
    """Return the non-secret provider contract frozen for one runner output."""

    timeout_s = float(args.timeout_s)
    if timeout_s <= 0.0:
        raise ValueError("timeout_s must be positive")
    max_output_tokens = args.max_output_tokens
    if (
        isinstance(max_output_tokens, bool)
        or not isinstance(max_output_tokens, int)
        or max_output_tokens < 1
    ):
        raise ValueError("max_output_tokens must be a positive integer")
    payload = {
        "generation": {
            "max_output_tokens": max_output_tokens,
            "temperature": 0.0,
            "top_p": 1.0,
        },
        "provider": {
            "api": "chat_completions",
            "endpoint": args.endpoint,
            "model": args.model,
            "reasoning_effort": None,
            "thinking": "disabled",
            "timeout_s": timeout_s,
        },
        "runner": runner,
        "schema": RUNTIME_CONFIG_SCHEMA,
    }
    science_card_focus = getattr(args, "science_card_focus", None)
    if science_card_focus is not None:
        payload["science_card_focus"] = science_card_focus.strip()
    target_accepted = getattr(args, "target_accepted", None)
    if target_accepted is not None:
        payload["target_accepted"] = target_accepted
    if additions:
        collisions = sorted(set(payload).intersection(additions))
        if collisions:
            raise ValueError(
                "runtime config additions collide with existing keys: %s"
                % ", ".join(collisions)
            )
        payload.update(additions)
    return payload


def _freeze_runtime_config(
    output_directory: Path,
    args: argparse.Namespace,
    *,
    runner: str,
    additions: Optional[Mapping[str, Any]] = None,
) -> Mapping[str, Any]:
    """Persist or verify one ordinary JSON config without any credential."""

    payload = _runtime_config_payload(args, runner=runner, additions=additions)
    path = output_directory / "config.json"
    if path.exists():
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError("existing config.json must contain valid JSON") from exc
        if existing != payload:
            raise ValueError("output directory contains a different runtime config")
    else:
        _write_json(path, payload)
    return payload


class _RecordingBackend:
    """Record one stage's provider-neutral request and raw response."""

    def __init__(self, backend: TextGenerationBackend, directory: Path) -> None:
        self._backend = backend
        self._directory = directory

    def generate(self, request: GenerationRequest) -> GenerationResponse:
        _write_json(
            self._directory / "request.json",
            generation_request_to_payload(request),
        )
        response = self._backend.generate(request)
        _write_json(
            self._directory / "response.json",
            generation_response_to_payload(response),
        )
        return response


class _ScienceCardRecordingBackend:
    """Record one ScienceCard proposal and up to three bounded repairs."""

    def __init__(self, backend: TextGenerationBackend, directory: Path) -> None:
        self._backend = backend
        self._directory = directory
        self.attempt_count = 0

    def generate(self, request: GenerationRequest) -> GenerationResponse:
        if self.attempt_count >= 4:
            raise RuntimeError("science-card extraction exceeded its four-call limit")
        self.attempt_count += 1
        if self.attempt_count == 1:
            attempt_directory = self._directory
        else:
            attempt_directory = self._directory / (
                "repair_%02d" % (self.attempt_count - 1)
            )
            attempt_directory.mkdir(exist_ok=False)
        return _RecordingBackend(self._backend, attempt_directory).generate(request)


class _CaseDraftRecordingBackend:
    """Record one primary CaseDraft call and up to three bounded repairs."""

    def __init__(self, backend: TextGenerationBackend, directory: Path) -> None:
        self._backend = backend
        self._directory = directory
        self.attempt_count = 0

    def generate(self, request: GenerationRequest) -> GenerationResponse:
        if self.attempt_count >= 4:
            raise RuntimeError("case-draft authoring exceeded its four-call limit")
        self.attempt_count += 1
        if self.attempt_count == 1:
            attempt_directory = self._directory
        else:
            attempt_directory = self._directory / (
                "repair_%02d" % (self.attempt_count - 1)
            )
            attempt_directory.mkdir(exist_ok=False)
        return _RecordingBackend(self._backend, attempt_directory).generate(request)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Draft-only diagnostic: run bounded TeX-to-science-card and "
            "science-card-to-draft stages. Each permits one proposal plus at most "
            "three allowlisted mechanical repairs; never render or accept a case."
        )
    )
    parser.add_argument("tex")
    parser.add_argument("output_directory")
    parser.add_argument("--source-citation", required=True)
    parser.add_argument("--journal-doi", required=True)
    parser.add_argument("--arxiv-versioned-id", required=True)
    parser.add_argument(
        "--paper-id",
        required=True,
        help="lower_snake_case paper identifier used by review artifacts",
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


def _api_key(args: argparse.Namespace) -> str:
    if args.api_key is not None:
        value = args.api_key
    elif args.api_key_stdin:
        value = sys.stdin.readline().rstrip("\r\n")
    elif args.prompt_api_key:
        value = getpass.getpass("DeepSeek API key: ")
    else:
        value = os.environ.get(args.api_key_env, "")
    if not value.strip():
        raise ValueError(
            "missing API key: use --api-key, --api-key-stdin, "
            "--prompt-api-key, or set %s" % args.api_key_env
        )
    return value


def run(
    args: argparse.Namespace,
    *,
    backend: Optional[TextGenerationBackend] = None,
) -> int:
    output_directory = Path(args.output_directory)
    output_directory.mkdir(parents=True, exist_ok=False)
    science_card_stage = output_directory / "science_card"
    case_draft_stage = output_directory / "case_draft"
    science_card_stage.mkdir()
    case_draft_stage.mkdir()
    stage = "source_normalization"

    try:
        _freeze_runtime_config(
            output_directory,
            args,
            runner="temporal_authoring",
        )
        normalized_source = load_latex(args.tex)
        (output_directory / "normalized_source.tex").write_text(
            normalized_source,
            encoding="utf-8",
        )
        provider = backend or DeepSeekChatBackend(
            endpoint=args.endpoint,
            api_key=_api_key(args),
            model=args.model,
            thinking="disabled",
            reasoning_effort=None,
            timeout_s=args.timeout_s,
        )
        config = GenerationConfig(
            max_output_tokens=args.max_output_tokens,
            temperature=0.0,
            top_p=1.0,
        )

        stage = "science_card"
        card_result = extract_science_card(
            _ScienceCardRecordingBackend(provider, science_card_stage),
            normalized_source,
            source_citation=args.source_citation,
            journal_doi=args.journal_doi,
            arxiv_versioned_id=args.arxiv_versioned_id,
            config=config,
            max_total_attempts=4,
        )
        _write_json(
            output_directory / "science_card.json",
            science_card_to_payload(card_result.card),
        )

        stage = "case_draft"
        draft_result = author_case_draft(
            _CaseDraftRecordingBackend(provider, case_draft_stage),
            card_result.card,
            config=config,
            strict_source_only=True,
            max_total_attempts=4,
        )
        _write_json(
            output_directory / "draft.json",
            case_draft_batch_to_payload(draft_result.batch),
        )
        _write_json(
            case_draft_stage / "prose_normalizations.json",
            public_prose_normalizations_to_payload(
                getattr(draft_result, "prose_normalizations", ())
            ),
        )
        _write_json(
            case_draft_stage / "relationship_direction_bindings.json",
            relationship_direction_bindings_to_payload(
                getattr(draft_result, "relationship_direction_bindings", ())
            ),
        )
        _write_json(
            case_draft_stage / "condition_partition_bindings.json",
            condition_partition_bindings_to_payload(
                getattr(draft_result, "condition_partition_bindings", ())
            ),
        )

        stage = "filter_and_review_request"
        candidates = []
        review_requests = []
        for draft in draft_result.batch.drafts:
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
        if draft_result.batch.status == "not_authorable":
            filter_status = "not_authorable"
        elif eligible_count == len(candidates):
            filter_status = "awaiting_family_review"
        else:
            filter_status = "candidate_rejected"
        filter_report = {
            "candidate_count": len(candidates),
            "candidates": candidates,
            "eligible_count": eligible_count,
            "status": filter_status,
        }
        _write_json(output_directory / "filter.json", filter_report)

        report = {
            "case_authoring_ready": card_result.card.case_authoring_ready,
            "case_rendered": False,
            "draft_assessment": draft_result.batch.assessment,
            "draft_count": len(draft_result.batch.drafts),
            "eligible_count": eligible_count,
            "review_requests": review_requests,
            "stages": {
                "case_draft": {
                    "model": draft_result.response.model,
                    "provider": draft_result.response.provider,
                },
                "science_card": {
                    "model": card_result.response.model,
                    "provider": card_result.response.provider,
                },
            },
            "status": filter_status,
        }
        _write_json(output_directory / "result.json", report)
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
        if filter_status == "awaiting_family_review":
            return 3
        return 0 if filter_status == "not_authorable" else 2
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
    args = _parser().parse_args(argv)
    return run(args)


if __name__ == "__main__":
    raise SystemExit(main())
