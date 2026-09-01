"""Batch failure-mode analysis for a completed case-matrix development run."""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence

from role_benchmark.failure_modes import FAILURE_ANALYSIS_SCHEMA, analyze_failure_events
from role_benchmark.runlog import load_run_log


def _write_json(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )


def analyze_episode_results(episodes_path: Path) -> List[Mapping[str, Any]]:
    payload = json.loads(episodes_path.read_text(encoding="utf-8"))
    rows = payload.get("episodes", [])
    analyses = []
    for row in rows:
        log_path = row.get("log_path")
        if not isinstance(log_path, str) or not log_path:
            analysis = {
                "schema": FAILURE_ANALYSIS_SCHEMA,
                "status": "not_evaluated",
                "terminal_failure": None,
                "first_observed_misstep": None,
                "modes": [],
                "incidents": [],
                "coverage": {},
            }
        else:
            resolved_log = Path(log_path)
            if not resolved_log.is_absolute():
                resolved_log = episodes_path.parent / resolved_log
            analysis = analyze_failure_events(load_run_log(str(resolved_log)).events)
        analyses.append(
            {
                "episode_id": row.get("episode_id"),
                "case_family": row.get("case_family"),
                "world": row.get("world"),
                "track": row.get("track"),
                "repeat": row.get("repeat"),
                "active_pass": row.get("active_pass"),
                "log_path": log_path,
                "failure_analysis": analysis,
            }
        )
    return analyses


def summarize(analyses: Sequence[Mapping[str, Any]]) -> Mapping[str, Any]:
    statuses: Counter[str] = Counter()
    terminal_stages: Counter[str] = Counter()
    terminal_codes: Counter[str] = Counter()
    first_stages: Counter[str] = Counter()
    first_codes: Counter[str] = Counter()
    all_modes: Counter[str] = Counter()
    mode_episodes: Counter[str] = Counter()
    coverage_episode_counts: Counter[str] = Counter()
    coverage_totals: Counter[str] = Counter()
    recovered_incidents = 0
    episodes_with_recovered_incidents = 0

    for row in analyses:
        analysis = row["failure_analysis"]
        statuses[str(analysis.get("status"))] += 1
        terminal = analysis.get("terminal_failure") or {}
        first = analysis.get("first_observed_misstep") or {}
        if terminal:
            terminal_stages[str(terminal.get("stage"))] += 1
            terminal_codes[str(terminal.get("code"))] += 1
        if first:
            first_stages[str(first.get("stage"))] += 1
            first_codes[str(first.get("code"))] += 1
        episode_mode_codes = set()
        for mode in analysis.get("modes", []):
            code = str(mode.get("code"))
            all_modes[code] += 1
            episode_mode_codes.add(code)
        for code in episode_mode_codes:
            mode_episodes[code] += 1
        coverage = analysis.get("coverage", {})
        for key in (
            "forecast_update_turns",
            "controlled_contrasts",
            "observed_prediction_points",
            "hypothesis_rewrite_pairs_excluded",
        ):
            value = coverage.get(key, 0)
            if isinstance(value, int) and not isinstance(value, bool) and value > 0:
                coverage_episode_counts[key] += 1
                coverage_totals[key] += value
        incident_count = len(analysis.get("incidents", []))
        recovered_incidents += incident_count
        if incident_count:
            episodes_with_recovered_incidents += 1

    return {
        "schema": FAILURE_ANALYSIS_SCHEMA,
        "episode_count": len(analyses),
        "status_counts": dict(sorted(statuses.items())),
        "terminal_stage_counts": dict(sorted(terminal_stages.items())),
        "terminal_code_counts": dict(sorted(terminal_codes.items())),
        "first_observed_misstep_stage_counts": dict(sorted(first_stages.items())),
        "first_observed_misstep_code_counts": dict(sorted(first_codes.items())),
        "failure_mode_counts": dict(sorted(all_modes.items())),
        "failure_mode_episode_counts": dict(sorted(mode_episodes.items())),
        "diagnostic_coverage_episode_counts": dict(
            sorted(coverage_episode_counts.items())
        ),
        "diagnostic_coverage_totals": dict(sorted(coverage_totals.items())),
        "recovered_incident_count": recovered_incidents,
        "episodes_with_recovered_incidents": episodes_with_recovered_incidents,
    }


def write_outputs(
    analyses: Sequence[Mapping[str, Any]], output_dir: Path
) -> Mapping[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    summary = summarize(analyses)
    _write_json(
        output_dir / "failure_analysis.json",
        {
            "schema": FAILURE_ANALYSIS_SCHEMA,
            "episode_count": len(analyses),
            "episodes": list(analyses),
        },
    )
    _write_json(output_dir / "failure_summary.json", summary)

    columns = (
        "episode_id",
        "case_family",
        "world",
        "track",
        "repeat",
        "active_pass",
        "analysis_status",
        "terminal_stage",
        "terminal_code",
        "first_misstep_action_index",
        "first_misstep_stage",
        "first_misstep_code",
        "first_misstep_message",
        "mode_count",
        "recovered_incident_count",
        "modes_json",
        "log_path",
    )
    with (output_dir / "failure_modes.csv").open(
        "w", encoding="utf-8", newline=""
    ) as stream:
        writer = csv.DictWriter(stream, fieldnames=columns)
        writer.writeheader()
        for row in analyses:
            analysis = row["failure_analysis"]
            terminal = analysis.get("terminal_failure") or {}
            first = analysis.get("first_observed_misstep") or {}
            writer.writerow(
                {
                    "episode_id": row.get("episode_id"),
                    "case_family": row.get("case_family"),
                    "world": row.get("world"),
                    "track": row.get("track"),
                    "repeat": row.get("repeat"),
                    "active_pass": row.get("active_pass"),
                    "analysis_status": analysis.get("status"),
                    "terminal_stage": terminal.get("stage"),
                    "terminal_code": terminal.get("code"),
                    "first_misstep_action_index": first.get("action_index"),
                    "first_misstep_stage": first.get("stage"),
                    "first_misstep_code": first.get("code"),
                    "first_misstep_message": first.get("message"),
                    "mode_count": len(analysis.get("modes", [])),
                    "recovered_incident_count": len(analysis.get("incidents", [])),
                    "modes_json": json.dumps(
                        analysis.get("modes", []),
                        ensure_ascii=False,
                        sort_keys=True,
                    ),
                    "log_path": row.get("log_path"),
                }
            )
    return summary


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Analyze failure modes for every episode in episodes.json."
    )
    parser.add_argument("episodes_json", help="Completed run's episodes.json")
    parser.add_argument("output_dir", help="Directory for JSON and CSV analyses")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = _parser().parse_args(argv)
    analyses = analyze_episode_results(Path(args.episodes_json))
    summary = write_outputs(analyses, Path(args.output_dir))
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
