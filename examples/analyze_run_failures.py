"""Explain where an evaluated Player episode first became observably inconsistent."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Optional, Sequence

from role_benchmark.failure_modes import analyze_failure_events
from role_benchmark.runlog import RunLogFormatError, load_run_log


def analyze_run_log(path: str):
    try:
        events = load_run_log(path).events
    except RunLogFormatError:
        # Early development logs used a zero-based event envelope.  Failure
        # analysis needs only their observable event_type/payload/sequence data.
        events = tuple(
            json.loads(line)
            for line in Path(path).read_text(encoding="utf-8").splitlines()
            if line.strip()
        )
    return analyze_failure_events(events)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Analyze observable failure modes in one Role Benchmark JSONL run."
    )
    parser.add_argument("run_log", help="Evaluated JSONL run log")
    parser.add_argument(
        "--output",
        help="Optional JSON output path; otherwise print the analysis",
    )
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = _parser().parse_args(argv)
    analysis = analyze_run_log(args.run_log)
    rendered = json.dumps(
        analysis,
        allow_nan=False,
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    ) + "\n"
    if args.output:
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(rendered)
        print(output)
    else:
        print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
