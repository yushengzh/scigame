"""Run one legacy no-retry abstraction as a diagnostic only.

The credential is accepted only at runtime.  The output directory contains the
logical request, raw provider response, parsed abstraction, and filter result;
none of those artifacts contains the credential.  This legacy one-stage path
never renders or accepts a case.  Formal acceptance belongs exclusively to
``run_temporal_warmup.py``.
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
    CandidateDecodeError,
    extract_paper_abstraction,
    filter_candidate,
    load_latex,
    paper_abstraction_to_payload,
)


DEFAULT_ENDPOINT = "https://api.deepseek.com/chat/completions"
DEFAULT_MODEL = "deepseek-v4-flash"
DEFAULT_API_KEY_ENV = "DEEPSEEK_API_KEY"


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


class _RecordingBackend:
    """Persist the exact request/response around one underlying generation."""

    def __init__(self, backend: TextGenerationBackend, output_directory: Path) -> None:
        self._backend = backend
        self._output_directory = output_directory

    def generate(self, request: GenerationRequest) -> GenerationResponse:
        _write_json(
            self._output_directory / "request.json",
            generation_request_to_payload(request),
        )
        response = self._backend.generate(request)
        _write_json(
            self._output_directory / "response.json",
            generation_response_to_payload(response),
        )
        return response


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run one legacy temporal abstraction for diagnosis only; never "
            "render or accept a case."
        )
    )
    parser.add_argument("tex")
    parser.add_argument("output_directory")
    parser.add_argument("--source-citation", required=True)
    parser.add_argument("--journal-doi", required=True)
    parser.add_argument("--arxiv-versioned-id", required=True)
    parser.add_argument("--endpoint", default=DEFAULT_ENDPOINT)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--timeout-s", type=float, default=180.0)
    parser.add_argument("--max-output-tokens", type=int, default=8192)
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


def run(args: argparse.Namespace, *, backend: Optional[TextGenerationBackend] = None) -> int:
    output_directory = Path(args.output_directory)
    output_directory.mkdir(parents=True, exist_ok=False)
    try:
        provider = backend or DeepSeekChatBackend(
            endpoint=args.endpoint,
            api_key=_api_key(args),
            model=args.model,
            thinking="disabled",
            reasoning_effort=None,
            timeout_s=args.timeout_s,
        )
        result = extract_paper_abstraction(
            _RecordingBackend(provider, output_directory),
            load_latex(args.tex),
            source_citation=args.source_citation,
            journal_doi=args.journal_doi,
            arxiv_versioned_id=args.arxiv_versioned_id,
            config=GenerationConfig(
                max_output_tokens=args.max_output_tokens,
                temperature=0.0,
                top_p=1.0,
            ),
        )
        abstraction_payload = paper_abstraction_to_payload(result.abstraction)
        _write_json(output_directory / "abstraction.json", abstraction_payload)

        candidates = []
        for candidate in result.abstraction.candidates:
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
        eligible_count = sum(item["eligible"] for item in candidates)
        complete = eligible_count == len(candidates)
        report = {
            "assessment": result.abstraction.assessment,
            "candidate_count": len(candidates),
            "candidates": candidates,
            "eligible_count": eligible_count,
            "model": result.response.model,
            "case_rendered": False,
            "provider": result.response.provider,
            "status": "diagnostic_complete" if complete else "candidate_rejected",
        }
        _write_json(output_directory / "result.json", report)
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
        return 0 if complete else 2
    except (CandidateDecodeError, OSError, RuntimeError, ValueError) as exc:
        failure = {
            "error": str(exc),
            "error_type": type(exc).__name__,
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
