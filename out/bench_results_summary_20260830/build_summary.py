#!/usr/bin/env python3
"""Build a denominator-safe summary of the local benchmark run artifacts."""

from __future__ import annotations

import json
import math
from collections import Counter, defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
from statistics import median
from statistics import mean, stdev


ROOT = Path(__file__).resolve().parents[2]
RUNS = ROOT / "out" / "runs"
OUTPUT = Path(__file__).resolve().parent / "summary.json"

FINAL_RUNS = (
    "gpt-5.6-sol-final",
    "claude-opus-4-7-final",
    "kimi-k3-final",
    "qwen3.8-max-final",
)

CLASSIFICATION = {
    "gpt-5.6-sol-final": ("formal_complete", "唯一完整的 400-episode 主矩阵"),
    "claude-opus-4-7-final": ("formal_partial", "351/400 个持久化结果；目录索引存在混合快照"),
    "kimi-k3-final": ("formal_partial", "36/400，首个基础设施错误后停止"),
    "qwen3.8-max-final": ("formal_partial", "36/400，首个超时后停止"),
    "deepseek_20_family_80_20260825": ("matched_pilot", "20 families × 4 cells × 1 repeat"),
    "deepseek_case_matrix_20260825": ("legacy_pilot", "旧 58-case 非平衡矩阵"),
    "pendulum_minimal_validation_20260824_v3": ("legacy_warmup", "旧 schema 的 60-episode pendulum warmup"),
    "pendulum_minimal_validation_20260824": ("superseded_partial", "被 v3 取代"),
    "pendulum_minimal_validation_20260824_v2": ("superseded_partial", "被 v3 取代"),
    "openai_gpt56_case_matrix_20260825": ("empty_or_failed", "0 个结果"),
    "packyapi_claude_haiku_4_5_20251001_case_matrix_20260825": ("stopped_api_test", "58/58 均为 player generation failure"),
    "packyapi_claude_opus_4_8_case_matrix_20260825": ("stopped_api_test", "1 个基础设施失败"),
    "deepseek_case_matrix_smoke_20260825": ("diagnostic", "单例 smoke"),
    "claude-opus-4-7-det-limit1": ("diagnostic", "单例输出限制诊断"),
    "gpt-5.6-sol-det-limit1": ("diagnostic", "单例输出限制诊断"),
    "kimi-k3-det-limit1": ("diagnostic", "单例输出限制诊断"),
    "qwen3.8-max-det-limit1": ("diagnostic", "单例输出限制诊断"),
    "claude-opus-4-7-gateway": ("diagnostic", "gateway 失败诊断"),
    "claude-opus-4-7-gateway-v2": ("diagnostic", "gateway 失败诊断"),
    "gpt-5.6-sol-gateway": ("diagnostic", "gateway 失败诊断"),
    "gpt-5.6-sol-chat-gateway": ("diagnostic", "gateway 小样本诊断"),
    "kimi-k3-gateway": ("diagnostic", "gateway 单例诊断"),
    "qwen3.8-max-gateway": ("diagnostic", "gateway 单例诊断"),
    "kimi-nothink-test": ("diagnostic", "thinking 参数诊断"),
    "qwen-nothink-test": ("diagnostic", "thinking 参数诊断"),
    "temporal_warmup_2025-01-02": ("non_benchmark", "temporal census/pipeline 输出"),
    "temporal_warmup_2026-07": ("non_benchmark", "temporal census/pipeline 输出"),
}


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def result_rows(run_name: str):
    directory = RUNS / run_name / "results"
    return [load_json(path) for path in sorted(directory.glob("*.result.json"))]


def config_for(run_name: str):
    path = RUNS / run_name / "config.json"
    return load_json(path) if path.exists() else {}


def profile_model(config, role: str):
    design = config.get("design") or {}
    profile = design.get(role + "_profile") or {}
    if profile.get("model"):
        return profile["model"]
    profiles = config.get("profiles") or []
    if role == "player" and profiles:
        values = [item.get("model") for item in profiles if item.get("model")]
        return ", ".join(dict.fromkeys(values))
    return None


def planned_count(config):
    selection = config.get("selection") or {}
    indexes = selection.get("schedule_indexes") or []
    if indexes:
        return len(indexes)
    limit = selection.get("limit")
    if isinstance(limit, int):
        return limit
    design = config.get("design") or {}
    value = design.get("total_episodes")
    if isinstance(value, int):
        return value
    return None


def ratio(numerator, denominator):
    return numerator / denominator if denominator else None


def pct(value):
    return round(value * 100, 2) if value is not None else None


def episode_summary(rows, planned=None):
    evaluated = [row for row in rows if row.get("status") == "evaluated"]
    completed_legacy = [row for row in rows if row.get("status") == "completed"]
    pass_count = sum(row.get("active_pass") is True for row in evaluated)
    evaluation_success = sum(row.get("evaluation_success") is True for row in rows)
    protocol = sum(row.get("protocol_completion") is True for row in evaluated)
    scientific = sum(row.get("scientifically_evaluable") is True for row in evaluated)
    submitted = sum(row.get("termination_kind") == "submitted" for row in evaluated)
    categories = Counter(
        row.get("active_pass_category") for row in evaluated if row.get("active_pass_category")
    )
    statuses = Counter(str(row.get("status")) for row in rows)
    elapsed = [float(row.get("elapsed_s") or 0.0) for row in evaluated]
    input_tokens = sum(
        int((row.get("player_llm_stats") or {}).get("input_tokens") or 0)
        for row in evaluated
    )
    output_tokens = sum(
        int((row.get("player_llm_stats") or {}).get("output_tokens") or 0)
        for row in evaluated
    )
    repair_calls = sum(
        int((row.get("player_llm_stats") or {}).get("repair_calls") or 0)
        for row in evaluated
    )
    return {
        "planned": planned,
        "result_records": len(rows),
        "coverage_pct": pct(ratio(len(rows), planned)),
        "evaluated": len(evaluated),
        "legacy_completed": len(completed_legacy),
        "infrastructure_failed": statuses.get("infrastructure_failed", 0),
        "unattempted_or_not_durable": max(planned - len(rows), 0) if planned else None,
        "active_pass": pass_count,
        "active_pass_rate_evaluated_pct": pct(ratio(pass_count, len(evaluated))),
        "evaluation_success": evaluation_success,
        "protocol_completion": protocol,
        "protocol_completion_rate_evaluated_pct": pct(ratio(protocol, len(evaluated))),
        "scientifically_evaluable": scientific,
        "scientifically_evaluable_rate_evaluated_pct": pct(ratio(scientific, len(evaluated))),
        "submitted": submitted,
        "conditional_scientific_pass_pct": pct(ratio(pass_count, scientific)),
        "pass": categories.get("pass", 0),
        "scientific_failure": categories.get("scientific_failure", 0),
        "player_generation_failure": categories.get("player_generation_failure", 0),
        "player_protocol_failure": categories.get("player_protocol_failure", 0),
        "status_counts": dict(sorted(statuses.items())),
        "elapsed_hours_evaluated": round(sum(elapsed) / 3600, 3),
        "median_elapsed_seconds": round(median(elapsed), 3) if elapsed else None,
        "player_input_tokens": input_tokens,
        "player_output_tokens": output_tokens,
        "repair_calls": repair_calls,
    }


def final_run_row(run_name: str):
    config = config_for(run_name)
    rows = result_rows(run_name)
    out = episode_summary(rows, planned_count(config))
    out.update(
        {
            "run": run_name,
            "model": profile_model(config, "player") or (rows[0].get("player_model") if rows else None),
            "oracle": profile_model(config, "oracle") or (rows[0].get("oracle_model") if rows else None),
            "evaluator": profile_model(config, "evaluator"),
            "result_status": "complete" if len(rows) == planned_count(config) else "partial",
        }
    )
    return out


def cell_rows(rows):
    output = []
    for world in ("historical", "counterfactual"):
        for track in ("identification", "discovery"):
            selected = [
                row
                for row in rows
                if row.get("status") == "evaluated"
                and row.get("world") == world
                and row.get("track") == track
            ]
            passed = sum(row.get("active_pass") is True for row in selected)
            protocol = sum(row.get("protocol_completion") is True for row in selected)
            scientific = sum(row.get("scientifically_evaluable") is True for row in selected)
            output.append(
                {
                    "world": world,
                    "track": track,
                    "cell": ("H" if world == "historical" else "C") + "/" + ("I" if track == "identification" else "D"),
                    "n": len(selected),
                    "active_pass": passed,
                    "active_pass_rate_pct": pct(ratio(passed, len(selected))),
                    "protocol_completion": protocol,
                    "protocol_completion_rate_pct": pct(ratio(protocol, len(selected))),
                    "scientifically_evaluable": scientific,
                    "conditional_scientific_pass_pct": pct(ratio(passed, scientific)),
                }
            )
    return output


def did_from_cells(cells):
    rates = {(item["world"], item["track"]): item["active_pass_rate_pct"] for item in cells}
    value = (
        rates[("historical", "discovery")]
        - rates[("counterfactual", "discovery")]
        - rates[("historical", "identification")]
        + rates[("counterfactual", "identification")]
    )
    return round(value, 2)


def family_rows(rows):
    grouped = defaultdict(list)
    for row in rows:
        if row.get("status") == "evaluated":
            grouped[row.get("case_family")].append(row)
    output = []
    for family, selected in grouped.items():
        passed = sum(row.get("active_pass") is True for row in selected)
        protocol = sum(row.get("protocol_completion") is True for row in selected)
        output.append(
            {
                "family": family,
                "n": len(selected),
                "active_pass": passed,
                "active_pass_rate_pct": pct(ratio(passed, len(selected))),
                "protocol_completion": protocol,
                "protocol_completion_rate_pct": pct(ratio(protocol, len(selected))),
            }
        )
    return sorted(output, key=lambda item: (-item["active_pass_rate_pct"], item["family"]))


def family_did_rows(rows):
    grouped = defaultdict(list)
    for row in rows:
        if row.get("status") == "evaluated":
            grouped[row.get("case_family")].append(row)
    output = []
    for family, selected in grouped.items():
        cells = cell_rows(selected)
        output.append(
            {
                "family": family,
                "delta_pp": did_from_cells(cells),
                "historical_identification_pct": next(item["active_pass_rate_pct"] for item in cells if item["cell"] == "H/I"),
                "historical_discovery_pct": next(item["active_pass_rate_pct"] for item in cells if item["cell"] == "H/D"),
                "counterfactual_identification_pct": next(item["active_pass_rate_pct"] for item in cells if item["cell"] == "C/I"),
                "counterfactual_discovery_pct": next(item["active_pass_rate_pct"] for item in cells if item["cell"] == "C/D"),
            }
        )
    return sorted(output, key=lambda item: (-item["delta_pp"], item["family"]))


def terminal_code(row):
    analysis = row.get("failure_analysis") or {}
    terminal = analysis.get("terminal_failure") or {}
    return terminal.get("code")


def first_misstep_code(row):
    analysis = row.get("failure_analysis") or {}
    first = analysis.get("first_observed_misstep") or {}
    return first.get("code")


def failure_rows(rows, accessor, limit=None):
    counts = Counter(accessor(row) for row in rows if accessor(row))
    values = [
        {"code": code, "episodes": count}
        for code, count in counts.most_common(limit)
    ]
    return values


def inventory_row(directory: Path):
    name = directory.name
    config = config_for(name)
    rows = result_rows(name)
    category, note = CLASSIFICATION.get(name, ("unclassified", ""))
    summary = episode_summary(rows, planned_count(config)) if rows else episode_summary([], planned_count(config))
    episodes_path = directory / "episodes.json"
    declared = None
    array_count = None
    if episodes_path.exists():
        try:
            episodes = load_json(episodes_path)
            declared = episodes.get("episode_count")
            array_count = len(episodes.get("episodes") or [])
        except (ValueError, TypeError):
            pass
    jsonl = list(directory.glob("episodes/*.jsonl"))
    output = {
        "run": name,
        "classification": category,
        "planned": planned_count(config),
        "result_records": len(rows),
        "evaluated": summary["evaluated"],
        "legacy_completed": summary["legacy_completed"],
        "infrastructure_failed": summary["infrastructure_failed"],
        "active_pass": summary["active_pass"],
        "evaluation_success": summary["evaluation_success"],
        "player": profile_model(config, "player"),
        "oracle": profile_model(config, "oracle"),
        "evaluator": profile_model(config, "evaluator"),
        "raw_jsonl": len(jsonl),
        "resume_jsonl": sum(".resume-" in path.name for path in jsonl),
        "episodes_declared": declared,
        "episodes_array_rows": array_count,
        "note": note,
    }
    return output


def main():
    final_rows_by_run = {name: result_rows(name) for name in FINAL_RUNS}
    final_status = [final_run_row(name) for name in FINAL_RUNS]
    evaluated_ids = [
        {row.get("episode_id") for row in rows if row.get("status") == "evaluated"}
        for rows in final_rows_by_run.values()
    ]
    common_ids = set.intersection(*evaluated_ids)
    common_index = sorted(
        row.get("schedule_index")
        for row in final_rows_by_run[FINAL_RUNS[0]]
        if row.get("episode_id") in common_ids
    )
    common_runs = []
    common_cell_counts = Counter()
    for name in FINAL_RUNS:
        selected = [row for row in final_rows_by_run[name] if row.get("episode_id") in common_ids]
        if name == FINAL_RUNS[0]:
            common_cell_counts.update((row.get("world"), row.get("track")) for row in selected)
        passed = sum(row.get("active_pass") is True for row in selected)
        protocol = sum(row.get("protocol_completion") is True for row in selected)
        scientific = sum(row.get("scientifically_evaluable") is True for row in selected)
        categories = Counter(row.get("active_pass_category") for row in selected)
        common_runs.append(
            {
                "model": final_run_row(name)["model"],
                "run": name,
                "n": len(selected),
                "active_pass": passed,
                "active_pass_rate_pct": pct(ratio(passed, len(selected))),
                "protocol_completion": protocol,
                "protocol_completion_rate_pct": pct(ratio(protocol, len(selected))),
                "scientifically_evaluable": scientific,
                "conditional_scientific_pass_pct": pct(ratio(passed, scientific)),
                "pass": categories.get("pass", 0),
                "scientific_failure": categories.get("scientific_failure", 0),
                "player_generation_failure": categories.get("player_generation_failure", 0),
                "player_protocol_failure": categories.get("player_protocol_failure", 0),
            }
        )

    gpt_rows = final_rows_by_run["gpt-5.6-sol-final"]
    gpt_cells = cell_rows(gpt_rows)
    gpt_family_did = family_did_rows(gpt_rows)
    gpt_deltas = [item["delta_pp"] for item in gpt_family_did]
    gpt_delta_se = stdev(gpt_deltas) / math.sqrt(len(gpt_deltas))
    # Two-sided 95% Student-t critical value for 20 family units (df=19).
    gpt_delta_t95 = 2.093024054
    all_final_rows = [row for rows in final_rows_by_run.values() for row in rows]
    all_final_evaluated = [row for row in all_final_rows if row.get("status") == "evaluated"]
    final_categories = Counter(row.get("active_pass_category") for row in all_final_evaluated)
    final_submitted = sum(row.get("termination_kind") == "submitted" for row in all_final_evaluated)

    deepseek80_rows = result_rows("deepseek_20_family_80_20260825")
    deepseek58_rows = result_rows("deepseek_case_matrix_20260825")
    pendulum_rows = result_rows("pendulum_minimal_validation_20260824_v3")
    deepseek80_cells = cell_rows(deepseek80_rows)

    inventory = [inventory_row(path) for path in sorted(RUNS.iterdir()) if path.is_dir()]
    raw_logs = list(RUNS.rglob("*.jsonl"))
    all_result_rows = [row for item in inventory for row in result_rows(item["run"])]
    summary = {
        "schema": "role_benchmark.run_summary",
        "generated_at": datetime.now(timezone(timedelta(hours=4))).isoformat(timespec="seconds"),
        "source_root": "out/runs",
        "canonical_grain": "one persisted results/*.result.json sidecar per episode; resume logs are attempts, not episodes",
        "inventory_summary": {
            "direct_subdirectories": len(inventory),
            "bench_like_directories": sum(item["classification"] != "non_benchmark" for item in inventory),
            "temporal_nonbench_directories": sum(item["classification"] == "non_benchmark" for item in inventory),
            "result_sidecars": sum(item["result_records"] for item in inventory),
            "raw_episode_jsonl": len(raw_logs),
            "resume_jsonl": sum(".resume-" in path.name for path in raw_logs),
        },
        "final_matrix": {
            "design": {
                "families": 20,
                "worlds": ["historical", "counterfactual"],
                "tracks": ["identification", "discovery"],
                "repeats": 5,
                "episodes_per_model": 400,
                "planned_across_models": 1600,
                "shared_schedule": True,
                "oracle": "deterministic case_world_model",
                "evaluator": "deterministic per-case held-out scorer; no LLM evaluator artifact",
            },
            "aggregate_artifact_status": {
                "planned": 1600,
                "result_records": len(all_final_rows),
                "evaluated": len(all_final_evaluated),
                "infrastructure_failed": sum(row.get("status") == "infrastructure_failed" for row in all_final_rows),
                "unattempted_or_not_durable": 1600 - len(all_final_rows),
                "active_pass": final_categories.get("pass", 0),
                "active_pass_rate_evaluated_pct": pct(ratio(final_categories.get("pass", 0), len(all_final_evaluated))),
                "submitted": final_submitted,
                "conditional_scientific_pass_pct": pct(ratio(final_categories.get("pass", 0), final_submitted)),
                "scientific_failure": final_categories.get("scientific_failure", 0),
                "player_generation_failure": final_categories.get("player_generation_failure", 0),
                "player_protocol_failure": final_categories.get("player_protocol_failure", 0),
            },
            "runs": final_status,
            "common_evaluated_subset": {
                "n": len(common_ids),
                "schedule_index_min": min(common_index) if common_index else None,
                "schedule_index_max": max(common_index) if common_index else None,
                "cell_counts": [
                    {"world": world, "track": track, "n": count}
                    for (world, track), count in sorted(common_cell_counts.items())
                ],
                "runs": common_runs,
                "interpretation": "Same 35 randomized schedule entries for all four models; repeat-1 partial and cell-unbalanced, so descriptive only.",
            },
            "gpt_complete": {
                "cells": gpt_cells,
                "difference_in_differences_pp": did_from_cells(gpt_cells),
                "families": family_rows(gpt_rows),
                "family_difference_in_differences": {
                    "n_families": len(gpt_deltas),
                    "mean_pp": round(mean(gpt_deltas), 2),
                    "median_pp": round(median(gpt_deltas), 2),
                    "positive_families": sum(value > 0 for value in gpt_deltas),
                    "zero_families": sum(value == 0 for value in gpt_deltas),
                    "negative_families": sum(value < 0 for value in gpt_deltas),
                    "t95_low_pp": round(mean(gpt_deltas) - gpt_delta_t95 * gpt_delta_se, 2),
                    "t95_high_pp": round(mean(gpt_deltas) + gpt_delta_t95 * gpt_delta_se, 2),
                    "rows": gpt_family_did,
                    "interpretation": "Family is the independent unit; interval is descriptive for this single complete Player run.",
                },
            },
        },
        "pilots": {
            "deepseek_20_family_80": {
                "summary": episode_summary(deepseek80_rows, 80),
                "cells": deepseek80_cells,
                "difference_in_differences_pp": did_from_cells(deepseek80_cells),
                "oracle": "deepseek-v4-flash presentation over authoritative world model",
                "note": "One matched repeat; not comparable to the deterministic-oracle final runs.",
            },
            "deepseek_legacy_58": {
                "summary": episode_summary(deepseek58_rows, 58),
                "note": "Unbalanced legacy design: 28 H/I and 10 in each other cell.",
            },
            "pendulum_warmup_60": {
                "summary": episode_summary(pendulum_rows, 60),
                "conditional_pass_pct": pct(
                    ratio(
                        sum(row.get("evaluation_success") is True for row in pendulum_rows),
                        sum(row.get("status") == "completed" for row in pendulum_rows),
                    )
                ),
                "note": "Legacy pendulum schema; evaluation_success is not the modern active_pass field.",
            },
        },
        "failure_modes": {
            "final_matrix_terminal": failure_rows(all_final_evaluated, terminal_code),
            "final_matrix_first_misstep": failure_rows(all_final_evaluated, first_misstep_code),
            "gpt_terminal": failure_rows(
                [row for row in gpt_rows if row.get("status") == "evaluated"], terminal_code
            ),
            "gpt_first_misstep": failure_rows(
                [row for row in gpt_rows if row.get("status") == "evaluated"], first_misstep_code
            ),
        },
        "data_quality": {
            "claude_mixed_snapshot": {
                "episodes_json_declared": next(item["episodes_declared"] for item in inventory if item["run"] == "claude-opus-4-7-final"),
                "episodes_json_array_rows": next(item["episodes_array_rows"] for item in inventory if item["run"] == "claude-opus-4-7-final"),
                "persisted_result_sidecars": next(item["result_records"] for item in inventory if item["run"] == "claude-opus-4-7-final"),
                "policy": "Use persisted result sidecars for scientific aggregation; extra index-only rows are not durable locally.",
            },
            "resume_logs_not_episodes": sum(".resume-" in path.name for path in raw_logs),
            "old_protocol_evidence": {
                "submitted_final_records_with_deprecated_confidence": sum(
                    isinstance(row.get("final_submission"), dict)
                    and "confidence" in row["final_submission"]
                    for row in all_final_evaluated
                ),
                "terminal_final_confidence_mismatch": sum(
                    terminal_code(row) == "final_confidence_mismatch" for row in all_final_evaluated
                ),
                "current_code_note": "Current FinalSubmission no longer has confidence; these run artifacts predate that protocol correction.",
            },
            "all_sidecars_old_protocol_evidence": {
                "submitted_final_records_with_deprecated_confidence": sum(
                    isinstance(row.get("final_submission"), dict)
                    and "confidence" in row["final_submission"]
                    for row in all_result_rows
                ),
                "terminal_final_confidence_mismatch": sum(
                    terminal_code(row) == "final_confidence_mismatch" for row in all_result_rows
                ),
                "modern_reason_code_final_confidence_mismatch": sum(
                    row.get("reason_code") == "final_confidence_mismatch"
                    for row in all_result_rows
                ),
                "any_record_containing_deprecated_confidence_mismatch": sum(
                    "final_confidence_mismatch" in json.dumps(row)
                    or "final confidence must match" in json.dumps(row)
                    for row in all_result_rows
                ),
            },
            "llm_judge_artifacts": 0,
            "assessment": "Share with caveats: descriptive results are recoverable, but only GPT is complete and all final runs use the superseded final-confidence protocol without an LLM evaluator.",
        },
        "run_inventory": inventory,
    }
    OUTPUT.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
