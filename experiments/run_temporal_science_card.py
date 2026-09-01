"""Run one bounded TeX-to-science-card temporal extraction stage.

The credential is accepted only at runtime.  The output directory records the
normalized model input, provider-neutral request, raw provider response,
strictly parsed science card, and a compact result without persisting the key.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Optional, Sequence

from experiments.run_pendulum_matrix import DeepSeekChatBackend
from experiments.run_temporal_authoring import (
    DEFAULT_API_KEY_ENV,
    DEFAULT_ENDPOINT,
    DEFAULT_MODEL,
    _ScienceCardRecordingBackend,
    _api_key,
    _write_json,
)
from role_benchmark import GenerationConfig, TextGenerationBackend
from role_benchmark.temporal import (
    ScienceCardError,
    extract_science_card,
    load_latex,
    science_card_to_payload,
)


DEFAULT_MAX_OUTPUT_TOKENS = 32768


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run one strict temporal science-card extraction with at most three "
            "bounded mechanical repairs."
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
    parser.add_argument(
        "--max-output-tokens", type=int, default=DEFAULT_MAX_OUTPUT_TOKENS
    )
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


def run(
    args: argparse.Namespace,
    *,
    backend: Optional[TextGenerationBackend] = None,
) -> int:
    output_directory = Path(args.output_directory)
    output_directory.mkdir(parents=True, exist_ok=False)
    stage = "source_normalization"
    try:
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

        stage = "science_card"
        result = extract_science_card(
            _ScienceCardRecordingBackend(provider, output_directory),
            normalized_source,
            source_citation=args.source_citation,
            journal_doi=args.journal_doi,
            arxiv_versioned_id=args.arxiv_versioned_id,
            config=GenerationConfig(
                max_output_tokens=args.max_output_tokens,
                temperature=0.0,
                top_p=1.0,
            ),
            max_total_attempts=4,
        )
        _write_json(
            output_directory / "science_card.json",
            science_card_to_payload(result.card),
        )
        report = {
            "attempt_count": result.attempt_count,
            "case_authoring_ready": result.card.case_authoring_ready,
            "claim_count": len(result.card.claims),
            "mechanism_count": len(result.card.mechanisms),
            "model": result.response.model,
            "provider": result.response.provider,
            "status": "complete",
        }
        _write_json(output_directory / "result.json", report)
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    except (ScienceCardError, OSError, RuntimeError, ValueError) as exc:
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
