"""Select a smaller temporal cohort without reacquiring paper sources."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Optional, Sequence

from role_benchmark.temporal import select_temporal_cohort


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Derive a coordinator-ready subset from an existing validated "
            "cohort/acquisition handoff."
        )
    )
    parser.add_argument("input_cohort", help="cohort.json or its directory")
    parser.add_argument("output_directory")
    parser.add_argument(
        "--paper-id",
        action="append",
        required=True,
        dest="paper_ids",
        help="paper_id from the input cohort; repeat for 1--60 papers",
    )
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = _parser().parse_args(argv)
    try:
        acquisition = select_temporal_cohort(
            args.input_cohort,
            args.output_directory,
            paper_ids=args.paper_ids,
        )
    except (OSError, ValueError) as exc:
        _parser().error(str(exc))
    summary = {
        "cohort": str(Path(args.output_directory).resolve() / "cohort.json"),
        "paper_ids": [
            paper["paper_id"] for paper in acquisition["cohort"]["papers"]
        ],
        "selected_count": acquisition["selection_counts"]["selected"],
        "status": "coordinator_ready",
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
