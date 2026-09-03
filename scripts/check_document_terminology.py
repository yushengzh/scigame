#!/usr/bin/env python3
"""Reject project-specific terminology that has an established alternative."""

from __future__ import annotations

import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DOCUMENT_SUFFIXES = {".md", ".tex", ".txt"}
EXCLUDED_PARTS = {".git", ".venv", "out", "runs", "tmp"}
ALLOW_MARKER = "terminology-check: allow"

PROHIBITED = {
    "arm used for an evaluation method": re.compile(r"\barms?\b", re.IGNORECASE),
    "project-specific Oracle label": re.compile(
        r"\bGod[-– ]?(?:LLM|Oracle)\b", re.IGNORECASE
    ),
    "named project-specific framework": re.compile(
        r"Calibration\s*[-–—]\s*Falsification\s*[-–—]\s*Frontier",
        re.IGNORECASE,
    ),
    "project-specific method abbreviation": re.compile(r"\bZ/P/A\b"),
    "project-specific ledger label": re.compile(
        r"\bchronology ledger\b", re.IGNORECASE
    ),
    "project-specific gain label": re.compile(
        r"\b(?:evidence gain|active[- ]design gain)\b", re.IGNORECASE
    ),
    "project-specific cohort or pilot label": re.compile(
        r"\b(?:falsification pilot|frontier cohort)\b", re.IGNORECASE
    ),
    "project-specific compound adjective": re.compile(
        r"\b(?:truth-grounded|forecast-grounded|family-neutral|world-neutral|source-grounded)\b",
        re.IGNORECASE,
    ),
    "project-specific data-set label": re.compile(
        r"\b(?:public[- ]development fixture|transparent development fixture|formal private pack|private formal pack)\b",
        re.IGNORECASE,
    ),
    "project-specific diagnostic label": re.compile(
        r"\b(?:matched diagnostic|false[- ]twin|active[- ]pass(?:es|ed)?)\b",
        re.IGNORECASE,
    ),
    "project-specific Chinese threshold label": re.compile(r"奥卡姆门槛"),
    "project-specific Chinese methodological label": re.compile(r"三角测量"),
}


def iter_documents() -> list[Path]:
    return sorted(
        path
        for path in ROOT.rglob("*")
        if path.is_file()
        and path.suffix.lower() in DOCUMENT_SUFFIXES
        and not EXCLUDED_PARTS.intersection(path.relative_to(ROOT).parts)
    )


def main() -> int:
    findings: list[str] = []
    for path in iter_documents():
        relative = path.relative_to(ROOT)
        for line_number, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(), start=1
        ):
            if ALLOW_MARKER in line:
                continue
            for description, pattern in PROHIBITED.items():
                if pattern.search(line):
                    findings.append(
                        f"{relative}:{line_number}: {description}: {line.strip()}"
                    )

    if findings:
        print("Terminology check failed:")
        print("\n".join(findings))
        return 1

    print("Terminology check passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
