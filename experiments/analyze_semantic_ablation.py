"""Offline, family-paired analysis of the preregistered semantic ablation.

The frozen config declares every episode and result path. This program neither
calls a model nor changes inputs. Example::

    python -m experiments.analyze_semantic_ablation --run-dir STUDY --output-dir REPORT

Each case metric requires all three repeats. The full-study estimand is missing
until all 20 families are complete; available-family estimates remain explicitly
exploratory. Bootstrap units are entire families, never individual repeats.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import csv
from datetime import datetime, timezone
import hashlib
import itertools
import json
import math
from pathlib import Path
import random
from typing import Any, Mapping, Sequence


SCHEMA = "scigame.semantic_ablation_analysis.v1"
MODELS = ("gpt-5.6-sol", "gpt-6-astra")
ARMS = ("familiar", "anonymous")
WORLDS = ("original", "counterfactual")
ADAPTIVE = "adaptive experimental design"
FIXED4 = "fixed experimental design (4 observations)"
METHODS = (ADAPTIVE, FIXED4)
METRICS = ("evaluation_success", "active_pass", "protocol_completion")
CELL_FIELDS = ("player_model", "evaluation_method", "case_family", "world", "semantic_arm")
GROUP_FIELDS = ("player_model", "evaluation_method", "world", "semantic_arm")
IDENTITY_FIELDS = ("episode_id", *CELL_FIELDS, "repeat")
INFRASTRUCTURE = {"infrastructure_failed", "infrastructure_error"}
REPEATS = (1, 2, 3)
FAMILY_COUNT = 20


def _read(path: Path) -> tuple[dict, str]:
    data = path.read_bytes()
    value = json.loads(data)
    if not isinstance(value, dict):
        raise ValueError("Expected a JSON object: " + str(path))
    return value, hashlib.sha256(data).hexdigest()


def _finite(value: Any):
    return float(value) if type(value) in (int, float) and math.isfinite(value) else None


def _mean(values: Sequence[float]):
    return sum(values) / len(values) if values else None


def _rate(n: int, denominator: int):
    return n / denominator if denominator else None


def _exact_members(value: Any, expected: Sequence[str], label: str) -> list[str]:
    if (not isinstance(value, list) or any(not isinstance(x, str) for x in value)
            or len(value) != len(set(value)) or set(value) != set(expected)):
        raise ValueError(label + " must contain exactly " + repr(list(expected)))
    return value


def _result_path(root: Path, value: Any) -> Path:
    if not isinstance(value, str) or not value or Path(value).is_absolute():
        raise ValueError("result_path must be a nonempty relative path")
    path = (root / value).resolve()
    if not path.is_relative_to(root) or path == root:
        raise ValueError("result_path escapes the study directory: " + value)
    if not path.name.endswith(".result.json"):
        raise ValueError("result_path must identify a .result.json sidecar: " + value)
    return path


def validate_plan(config: dict, root: Path) -> list[dict]:
    """Require the declared 20 × 2 × 2 × 2 × 3 × 2 design, regardless of results."""
    if not isinstance(config.get("schema"), str) or not config.get("experiment_id"):
        raise ValueError("Frozen config requires schema and experiment_id")
    design = config.get("design")
    if not isinstance(design, dict):
        raise ValueError("Frozen config requires a design object")
    families = design.get("families")
    if (not isinstance(families, list) or len(families) != FAMILY_COUNT
            or any(not isinstance(family, str) or not family for family in families)
            or len(set(families)) != FAMILY_COUNT):
        raise ValueError("Preregistered design requires exactly 20 distinct families")
    if type(design.get("repeats")) is not int or design["repeats"] != 3:
        raise ValueError("Preregistered design requires exactly three repeats")
    _exact_members(design.get("models"), MODELS, "design.models")
    _exact_members(design.get("semantic_arms"), ARMS, "design.semantic_arms")
    _exact_members(design.get("worlds"), WORLDS, "design.worlds")
    _exact_members(design.get("methods"), METHODS, "design.methods")
    if design.get("task_setting", "discovery") != "discovery":
        raise ValueError("This preregistered study contains discovery only")
    if "task_settings" in design and design["task_settings"] != ["discovery"]:
        raise ValueError("This preregistered study contains discovery only")
    plan = config.get("schedule", {}).get("episodes")
    if not isinstance(plan, list) or len(plan) != 960:
        raise ValueError("Frozen schedule must declare all 960 episodes")
    expected = set(itertools.product(MODELS, METHODS, families, WORLDS, ARMS, REPEATS))
    observed = set()
    identities, paths = set(), set()
    for item in plan:
        if not isinstance(item, dict) or any(field not in item for field in (*IDENTITY_FIELDS, "result_path")):
            raise ValueError("Every scheduled episode requires identity fields and result_path")
        episode_id = item["episode_id"]
        if not isinstance(episode_id, str) or not episode_id or episode_id in identities:
            raise ValueError("Missing or duplicate planned episode_id")
        if type(item["repeat"]) is not int:
            raise ValueError("repeat must be an integer")
        key = tuple(item[field] for field in CELL_FIELDS) + (item["repeat"],)
        if key in observed:
            raise ValueError("Duplicate scheduled family/world/arm/model/method/repeat cell")
        if key not in expected:
            raise ValueError("Scheduled episode is outside the preregistered design: " + episode_id)
        if item.get("task_setting", "discovery") != "discovery":
            raise ValueError("Scheduled task_setting must be discovery")
        path = _result_path(root, item["result_path"])
        if path in paths:
            raise ValueError("Duplicate scheduled result_path")
        identities.add(episode_id)
        paths.add(path)
        observed.add(key)
    if observed != expected:
        raise ValueError("Frozen schedule is not the complete preregistered factorial design")
    return plan


def load_study(run_dir: Path) -> dict:
    root = Path(run_dir).resolve()
    config, config_sha = _read(root / "config.json")
    plan = validate_plan(config, root)
    rows, hashes = {}, {}
    planned_paths = {_result_path(root, item["result_path"]) for item in plan}
    # Only inspect declared result directories, not trajectory/call audit trees.
    directories = {path.parent for path in planned_paths} | {root / "results"}
    extras = sorted(str(path.relative_to(root)) for directory in directories
                    for path in directory.glob("*.result.json") if path.resolve() not in planned_paths)
    if extras:
        raise ValueError("Result files outside the frozen plan: " + ", ".join(extras))
    for item in plan:
        path = _result_path(root, item["result_path"])
        if not path.exists():
            continue
        row, digest = _read(path)
        for field in IDENTITY_FIELDS:
            if row.get(field) != item[field] or (field == "repeat" and type(row.get(field)) is not int):
                raise ValueError(item["episode_id"] + ": result identity mismatch in " + field)
        if row.get("experiment_id") != config["experiment_id"]:
            raise ValueError(item["episode_id"] + ": experiment_id mismatch")
        if row.get("task_setting", "discovery") != "discovery":
            raise ValueError(item["episode_id"] + ": result task_setting is not discovery")
        if not isinstance(row.get("status"), str):
            raise ValueError(item["episode_id"] + ": result status is missing")
        rows[item["episode_id"]] = row
        hashes[item["episode_id"]] = digest
    digest_input = json.dumps(hashes, sort_keys=True, separators=(",", ":")).encode()
    return {"root": str(root), "config": config, "plan": plan, "rows": rows,
            "audit": {"passed": True, "config_sha256": config_sha,
                "result_set_sha256": hashlib.sha256(digest_input).hexdigest(),
                "hashed_result_n": len(hashes), "identity_fields": list(IDENTITY_FIELDS),
                "scope": "Frozen plan and result sidecars; no per-turn model execution or semantic-adapter audit."}}


def _outcome(row: Mapping, metric: str):
    value = row.get(metric)
    return float(value) if row.get("status") == "evaluated" and type(value) is bool else None


def _numeric_summary(values: Sequence[Any], eligible_n: int) -> dict:
    observed = [number for value in values if (number := _finite(value)) is not None]
    return {"mean": _mean(observed), "known_sum": sum(observed) if observed else None,
            "observed_n": len(observed), "eligible_n": eligible_n,
            "coverage": _rate(len(observed), eligible_n)}


def _diagnostics(items: Sequence[dict], rows: Mapping[str, dict]) -> dict:
    recorded = [rows[item["episode_id"]] for item in items if item["episode_id"] in rows]
    evaluated = [row for row in recorded if row.get("status") == "evaluated"]
    violations = Counter()
    for row in evaluated:
        codes = {item.get("code") for item in (row.get("protocol_violations") or [])
                 if isinstance(item, Mapping) and isinstance(item.get("code"), str)}
        violations.update(codes)
    paths = {"attempts_used": ("attempts_used",), "elapsed_s": ("elapsed_s",),
             "initial_max_confidence": ("initial_max_confidence",),
             "final_selected_confidence": ("final_selected_confidence",),
             "player_turns": ("player_llm_stats", "player_turns"),
             "decoded_actions": ("player_llm_stats", "decoded_actions"),
             "input_tokens": ("player_llm_stats", "input_tokens"),
             "output_tokens": ("player_llm_stats", "output_tokens",)}
    numeric = {}
    for name, path in paths.items():
        values = []
        for row in recorded:
            value = row
            for field in path:
                value = value.get(field) if isinstance(value, Mapping) else None
            if "confidence" in name and (_finite(value) is None or not 0 <= value <= 1):
                value = None
            values.append(value)
        numeric[name] = _numeric_summary(values, len(items))
    gating = [row for row in evaluated if all(type(row.get(key)) is bool for key in ("evaluation_success", "active_pass"))]
    inactive = [row for row in evaluated if row.get("world") == "counterfactual"
                and all(type(row.get(key)) is bool for key in ("evaluation_success", "inactive_original_prediction_success"))]
    stop_rows = [row for row in evaluated if row.get("evaluation_method") == ADAPTIVE
                 and row.get("termination_kind") is not None and _finite(row.get("attempts_used")) is not None]
    return {"planned_n": len(items), "recorded_n": len(recorded),
            "missing_sidecar_n": len(items) - len(recorded), "evaluated_n": len(evaluated),
            "infrastructure_n": sum(row.get("status") in INFRASTRUCTURE for row in recorded),
            "status_counts": dict(Counter(row["status"] for row in recorded)),
            "error_type_counts": dict(Counter(row["error_type"] for row in recorded if row.get("error_type"))),
            "protocol_violation_episode_counts": dict(sorted(violations.items())),
            "protocol_violations_observed_n": sum(isinstance(row.get("protocol_violations"), list) for row in evaluated),
            "termination_kind_counts": dict(Counter(row["termination_kind"] for row in evaluated if row.get("termination_kind"))),
            "reason_code_counts": dict(Counter(row["reason_code"] for row in evaluated if row.get("reason_code"))),
            "prediction_pass_active_fail_n": sum(row["evaluation_success"] and not row["active_pass"] for row in gating),
            "prediction_active_joint_observed_n": len(gating),
            "counterfactual_inactive_original_diagnostic": {
                "planned_counterfactual_n": sum(item["world"] == "counterfactual" for item in items),
                "joint_observed_n": len(inactive),
                "active_counterfactual_prediction_pass_n": sum(row["evaluation_success"] for row in inactive),
                "inactive_original_prediction_pass_n": sum(row["inactive_original_prediction_success"] for row in inactive),
                "inactive_original_only_n": sum(row["inactive_original_prediction_success"] and not row["evaluation_success"] for row in inactive),
                "active_counterfactual_only_n": sum(row["evaluation_success"] and not row["inactive_original_prediction_success"] for row in inactive),
                "both_pass_n": sum(row["evaluation_success"] and row["inactive_original_prediction_success"] for row in inactive),
                "neither_pass_n": sum(not row["evaluation_success"] and not row["inactive_original_prediction_success"] for row in inactive),
                "semantics": "Available-episode diagnostic only: a predictor may pass both worlds. Inactive-original success never changes the active-world primary outcome."},
            "adaptive_stop_diagnostic": {
                "submitted_without_observations_n": sum(row.get("termination_kind") == "submitted" and row["attempts_used"] == 0 for row in stop_rows),
                "observable_n": len(stop_rows),
                "definition": "Evaluated adaptive episode submitted with attempts_used == 0; no arbitrary early-stop cutoff inferred."},
            "numeric": numeric}


def summarize_cells(study: dict) -> list[dict]:
    grouped = defaultdict(list)
    for item in study["plan"]:
        grouped[tuple(item[field] for field in CELL_FIELDS)].append(item)
    output = []
    for key, items in sorted(grouped.items()):
        items = sorted(items, key=lambda item: item["repeat"])
        metrics = {}
        for metric in METRICS:
            values = [_outcome(study["rows"].get(item["episode_id"], {}), metric) for item in items]
            available = [value for value in values if value is not None]
            complete = len(available) == len(REPEATS)
            metrics[metric] = {"repeat_values": values, "observed_n": len(available),
                "required_n": len(REPEATS), "complete": complete,
                "pass_n": int(sum(available)), "mean": _mean(available) if complete else None,
                "available_repeat_mean_diagnostic": _mean(available)}
        output.append({**dict(zip(CELL_FIELDS, key)), "metrics": metrics,
                       "diagnostics": _diagnostics(items, study["rows"])})
    return output


def summarize_groups(cells: list[dict], study: dict) -> list[dict]:
    grouped = defaultdict(list)
    plans = defaultdict(list)
    for cell in cells:
        grouped[tuple(cell[field] for field in GROUP_FIELDS)].append(cell)
    for item in study["plan"]:
        plans[tuple(item[field] for field in GROUP_FIELDS)].append(item)
    output = []
    for key, members in sorted(grouped.items()):
        metrics = {}
        for metric in METRICS:
            complete = [cell["metrics"][metric]["mean"] for cell in members if cell["metrics"][metric]["complete"]]
            metrics[metric] = {"planned_families_n": len(members), "complete_families_n": len(complete),
                "complete_family_coverage": _rate(len(complete), len(members)),
                "full_matrix_mean": _mean(complete) if len(complete) == len(members) else None,
                "exploratory_complete_family_mean": _mean(complete),
                "observed_episode_n": sum(cell["metrics"][metric]["observed_n"] for cell in members),
                "pass_episode_n": sum(cell["metrics"][metric]["pass_n"] for cell in members)}
        output.append({**dict(zip(GROUP_FIELDS, key)), "metrics": metrics,
                       "diagnostics": _diagnostics(plans[key], study["rows"])})
    return output


def _percentile(sorted_values: Sequence[float], p: float) -> float:
    index = (len(sorted_values) - 1) * p
    lower = int(index)
    upper = min(lower + 1, len(sorted_values) - 1)
    return sorted_values[lower] + (sorted_values[upper] - sorted_values[lower]) * (index - lower)


def family_bootstrap(values: Sequence[float], *, samples: int, seed: int):
    """Resample paired family-level contrasts, retaining their three-repeat mean."""
    if len(values) < 2:
        return None
    rng = random.Random(seed)
    n = len(values)
    draws = sorted(sum(values[rng.randrange(n)] for _ in range(n)) / n for _ in range(samples))
    return [_percentile(draws, 0.025), _percentile(draws, 0.975)]


def estimate_effects(cells: list[dict], families: Sequence[str], *, samples: int, seed: int) -> list[dict]:
    by_key = {tuple(cell[field] for field in CELL_FIELDS): cell for cell in cells}
    output = []
    for model, method, metric, estimand in itertools.product(
            MODELS, METHODS, METRICS, ("counterfactual_arm_effect", "original_arm_effect", "world_interaction")):
        contrasts = []
        for family in sorted(families):
            rates = {(world, arm): by_key[model, method, family, world, arm]["metrics"][metric]["mean"]
                     for world, arm in itertools.product(WORLDS, ARMS)}
            deltas = {world: rates[world, "anonymous"] - rates[world, "familiar"]
                      if all(rates[world, arm] is not None for arm in ARMS) else None for world in WORLDS}
            value = (deltas["counterfactual"] - deltas["original"]
                     if all(deltas[world] is not None for world in WORLDS) else None) if estimand == "world_interaction" else deltas[
                         "counterfactual" if estimand == "counterfactual_arm_effect" else "original"]
            contrasts.append({"case_family": family, "familiar_original": rates["original", "familiar"],
                "anonymous_original": rates["original", "anonymous"],
                "familiar_counterfactual": rates["counterfactual", "familiar"],
                "anonymous_counterfactual": rates["counterfactual", "anonymous"],
                "original_arm_effect": deltas["original"], "counterfactual_arm_effect": deltas["counterfactual"],
                "contrast": value})
        available = [row["contrast"] for row in contrasts if row["contrast"] is not None]
        fingerprint = "|".join((model, method, metric, estimand))
        contrast_seed = seed + int(hashlib.sha256(fingerprint.encode()).hexdigest()[:8], 16)
        interval = family_bootstrap(available, samples=samples, seed=contrast_seed)
        complete = len(available) == len(families)
        output.append({"player_model": model, "evaluation_method": method, "metric": metric,
            "estimand": estimand, "primary": method == ADAPTIVE and metric == "evaluation_success" and estimand == "counterfactual_arm_effect",
            "planned_families_n": len(families), "complete_families_n": len(available),
            "coverage": _rate(len(available), len(families)), "complete": complete,
            "estimate": _mean(available) if complete else None,
            "ci95": interval if complete else None,
            "exploratory_complete_family_estimate": _mean(available),
            "exploratory_complete_family_ci95": interval,
            "bootstrap_samples": samples, "bootstrap_seed": contrast_seed,
            "family_contrasts": contrasts})
    return output


def build_analysis(run_dir: Path, *, bootstrap_samples: int = 10000, bootstrap_seed: int = 20260920) -> dict:
    if type(bootstrap_samples) is not int or bootstrap_samples < 1000:
        raise ValueError("bootstrap_samples must be at least 1000")
    if type(bootstrap_seed) is not int:
        raise ValueError("bootstrap_seed must be an integer")
    study = load_study(run_dir)
    cells = summarize_cells(study)
    groups = summarize_groups(cells, study)
    effects = estimate_effects(cells, study["config"]["design"]["families"], samples=bootstrap_samples, seed=bootstrap_seed)
    overall = _diagnostics(study["plan"], study["rows"])
    overall["complete_repeat_cells_by_metric"] = {metric: sum(cell["metrics"][metric]["complete"] for cell in cells) for metric in METRICS}
    overall["planned_cells_n"] = len(cells)
    overall["all_primary_endpoints_complete"] = all(effect["complete"] for effect in effects if effect["primary"])
    overall["all_endpoints_complete"] = all(cell["metrics"][metric]["complete"] for cell in cells for metric in METRICS)
    episodes = []
    for item in study["plan"]:
        row = study["rows"].get(item["episode_id"], {})
        episodes.append({**{field: item[field] for field in (*IDENTITY_FIELDS, "result_path")},
            "status": row.get("status", "missing"),
            **{metric: _outcome(row, metric) for metric in METRICS}})
    return {"schema": SCHEMA, "generated_at": datetime.now(timezone.utc).isoformat(),
            "run_dir": study["root"], "experiment_id": study["config"]["experiment_id"],
            "audit": study["audit"], "design": study["config"]["design"],
            "semantics": {
                "scope": "20 specified Historical families, discovery only; 960 planned episodes. No outcome-dependent scope/repeat changes.",
                "primary": "For each model, adaptive counterfactual: anonymous minus familiar on evaluation_success.",
                "interaction": "(anonymous - familiar)_counterfactual - (anonymous - familiar)_original within the same family.",
                "companion_outcomes": "Strict active_pass and protocol_completion remain separate recorded outcomes; prediction diagnosis does not replace protocol scoring.",
                "case_mean": "Every one of the three scheduled repeats must resolve the metric before a case mean exists. Families receive equal weight.",
                "missing": "Absent, infrastructure-failed, or non-boolean metrics remain missing, never zero. No complete-case subset is called the full-study estimate.",
                "bootstrap": "Paired family cluster percentile 95% interval; each family contrast retains all relevant arms, worlds and repeats. Intervals describe resampling sensitivity of this selected family set, not a random population of science tasks.",
                "multiplicity": "Two model-specific primary effects; nominal intervals, not multiplicity-adjusted hypothesis-test decisions. Interactions, fixed4 and diagnostics are supporting analyses.",
                "causal_scope": "The current 20 families under the declared semantic-sidecard intervention and benchmark protocol; not evidence of training contamination or general scientific ability.",
                "budget": "Fixed4 is the equal-observation-budget auxiliary condition. Adaptive resources may differ by arm and are reported separately.",
                "confidence": "Only explicit initial_max_confidence and final_selected_confidence fields are used; missing or invalid values are unmeasured.",
                "inactive_original": "If explicitly recorded for counterfactual episodes, inactive_original_prediction_success is cross-tabulated with active-world prediction as a coverage-labelled diagnostic; it is not a new primary endpoint or evidence of memorization by itself.",
                "resource_scope": "Current sidecars only; latest episode-level recorded measurements, not an all-attempt call ledger.",
                "snapshot": "Read-only sidecar snapshot; running studies may progress during collection."},
            "bootstrap": {"samples": bootstrap_samples, "seed": bootstrap_seed, "unit": "case_family", "interval": "percentile_95"},
            "overall": overall, "groups": groups, "effects": effects, "cells": cells, "episodes": episodes}


def _pct(value: Any) -> str:
    return "—" if value is None else "%.2f%%" % (100 * value)


def _pp(value: Any) -> str:
    return "—" if value is None else "%+.2f pp" % (100 * value)


def _interval(value: Any) -> str:
    return "—" if value is None else "[%+.2f, %+.2f]" % (100 * value[0], 100 * value[1])


def render_markdown(report: dict) -> str:
    total = report["overall"]
    labels = {"evaluation_success": "数值预测通过", "active_pass": "严格 active pass", "protocol_completion": "协议完成"}
    lines = ["# 历史语义先验干扰：同题对照分析", "", "生成时间：" + report["generated_at"], "",
        "冻结计划 960 episodes；已记录 %d；完成 %d；基础设施未解决 %d；缺失结果文件 %d。" %
        (total["recorded_n"], total["evaluated_n"], total["infrastructure_n"], total["missing_sidecar_n"]),
        "每 case 的三轮指标全部已测量后，先取 (p1+p2+p3)/3，再对 20 个 family 等权平均。缺失不计失败。",
        "正式全题集估计须 20/20 family 完整；不足时为 —，可用子集单独标为探索性。", "",
        "主要对照为 Adaptive 反事实世界中 anonymous − familiar 的数值预测通过率。正值表示在该对照中匿名条件更高。",
        "交互为 (anonymous − familiar)反事实 − (anonymous − familiar)原始；同一 family 内配对。严格 active pass、协议完成并列保留。",
        "95% 区间按 family 整簇重采样，保留各臂、世界和全部 repeats；不把重复当独立题目。"]
    by_key = {(effect["player_model"], effect["evaluation_method"], effect["metric"], effect["estimand"]): effect for effect in report["effects"]}
    for method, title in ((ADAPTIVE, "主要 Adaptive 对照"), (FIXED4, "固定四次观测：等观测预算辅助")):
        lines += ["", "## " + title, "",
            "| 模型 | 指标 | 反事实 anonymous−familiar | 95% 区间 (pp) | 完整 family | 世界交互 | 95% 区间 (pp) | 完整 family |",
            "|---|---|---:|---:|---:|---:|---:|---:|"]
        for model, metric in itertools.product(MODELS, METRICS):
            effect = by_key[model, method, metric, "counterfactual_arm_effect"]
            interaction = by_key[model, method, metric, "world_interaction"]
            lines.append("| %s | %s | %s | %s | %d/20 | %s | %s | %d/20 |" %
                (model, labels[metric], _pp(effect["estimate"]), _interval(effect["ci95"]), effect["complete_families_n"],
                 _pp(interaction["estimate"]), _interval(interaction["ci95"]), interaction["complete_families_n"]))
    partial = [effect for effect in report["effects"] if not effect["complete"] and effect["complete_families_n"]]
    if partial:
        lines += ["", "## 探索性完整 family 子集", "", "以下不是全 20-family 估计；不同条目的可用 family 集合可能不同。", "",
            "| 模型 | 方法 | 指标 | 对照 | 子集差值 | 95% 区间 (pp) | family |", "|---|---|---|---|---:|---:|---:|"]
        for effect in partial:
            lines.append("| %s | %s | %s | %s | %s | %s | %d/20 |" % (effect["player_model"], effect["evaluation_method"],
                labels[effect["metric"]], effect["estimand"], _pp(effect["exploratory_complete_family_estimate"]),
                _interval(effect["exploratory_complete_family_ci95"]), effect["complete_families_n"]))
    lines += ["", "## 各实验条件", "",
        "每格给出全题集三轮均值；括号是完整 family/20。", "",
        "| 模型 | 方法 | 世界 | 语义臂 | 数值预测 | 严格 active | 协议完成 | 预测通过但 active 失败 | 实验次数均值 / 可观测 episodes |",
        "|---|---|---|---|---:|---:|---:|---:|---:|"]
    for group in report["groups"]:
        values = ["%s (%d/20)" % (_pct(group["metrics"][metric]["full_matrix_mean"]), group["metrics"][metric]["complete_families_n"]) for metric in METRICS]
        attempts = group["diagnostics"]["numeric"]["attempts_used"]
        lines.append("| %s | %s | %s | %s | %s | %s | %s | %d | %s / %d |" %
            (*(group[field] for field in GROUP_FIELDS), *values, group["diagnostics"]["prediction_pass_active_fail_n"],
             "—" if attempts["mean"] is None else "%.2f" % attempts["mean"], attempts["observed_n"]))
    lines += ["", "## 诊断与解释边界", "",
        "协议违规按 episode 去重统计，预测正确但协议未完成的数量单列。初始/最终 confidence 只使用明确记录值；JSON/CSV 包含其覆盖、终止原因、观测次数和 token。",
        "若记录了反事实提交在非活动原始世界的预测结果，另列其与反事实预测的交叉计数及覆盖；通过原始预测不自动证明记忆干扰，也不改变主评分。",
        "自适应零观测提交仅指已完成 episode 中 termination_kind=submitted 且 attempts_used=0；不从缺失信息推测提前停止。",
        "因果对象是当前 20 个指定 Historical family、此语义 sidecard 干预和已冻结协议。结果不直接证明训练污染，也不外推一般科学能力。",
        "Adaptive 两臂可能使用不同观测次数；Fixed4 提供相同观测预算的辅助对照。两个模型的主要效应分别报告；其余对照为辅助，区间未作多重检验调整。",
        "未独立审计每轮实际模型执行、语义适配器或初始配置冻结时间；身份审计覆盖冻结计划和结果 sidecar。", ""]
    return "\n".join(lines)


def _flatten(value: Mapping, prefix: str = "") -> dict:
    output = {}
    for key, item in value.items():
        name = prefix + "." + key if prefix else key
        if isinstance(item, Mapping):
            output.update(_flatten(item, name))
        elif isinstance(item, list):
            output[name] = json.dumps(item, ensure_ascii=False)
        else:
            output[name] = item
    return output


def _csv(path: Path, rows: Sequence[dict]):
    rows = [_flatten(row) for row in rows]
    fields = list(dict.fromkeys(key for row in rows for key in row))
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def write_analysis(report: dict, output_dir: Path):
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    (output / "analysis.json").write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    (output / "analysis.md").write_text(render_markdown(report), encoding="utf-8")
    _csv(output / "groups.csv", report["groups"])
    _csv(output / "cells.csv", report["cells"])
    _csv(output / "episodes.csv", report["episodes"])
    _csv(output / "effects.csv", [{key: value for key, value in effect.items() if key != "family_contrasts"} for effect in report["effects"]])
    _csv(output / "family_contrasts.csv", [{"player_model": effect["player_model"],
        "evaluation_method": effect["evaluation_method"], "metric": effect["metric"], "estimand": effect["estimand"], **family}
        for effect in report["effects"] for family in effect["family_contrasts"]])


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--bootstrap-samples", type=int, default=10000)
    parser.add_argument("--bootstrap-seed", type=int, default=20260920)
    args = parser.parse_args(argv)
    report = build_analysis(args.run_dir, bootstrap_samples=args.bootstrap_samples, bootstrap_seed=args.bootstrap_seed)
    write_analysis(report, args.output_dir)
    print(args.output_dir / "analysis.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
