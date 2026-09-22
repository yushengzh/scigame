"""Compare two frozen Codex benchmark runs without making model calls.

Only config and result/evaluator sidecars are read. The frozen schedule remains
the denominator, including when an entire dataset or repeat has not started.
Run with ``PYTHONPATH=src:. python -m experiments.compare_codex_models ...``.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from copy import deepcopy
import csv
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import re
from typing import Any, Mapping, Sequence

from role_benchmark.discovery_evaluation import DISCOVERY_PROMPT_VERSION
from role_benchmark.metrics import HELD_OUT_PREDICTION_SCORE
from role_benchmark.postevaluation import science_postevaluation


SCHEMA = "scigame.codex_model_comparison.v1"
INFRA = {"infrastructure_failed", "infrastructure_error"}
GROUP_FIELDS = ("dataset", "evaluation_method", "task_setting", "condition_id")
CELL_FIELDS = ("dataset", "case_family", "variant_id", "condition_id",
               "task_setting", "evaluation_method")
METRICS = ("held_out_prediction_score", "normalized_error", "expression_match",
           "understanding_before", "understanding_after", "understanding_gain")


def _read(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("Expected JSON object: " + str(path))
    return value


def _number(value: Any):
    return float(value) if type(value) in (int, float) and math.isfinite(value) else None


def _rate(n: int, denominator: int):
    return n / denominator if denominator else None


def _metric(values, eligible_n: int) -> dict:
    values = [number for value in values if (number := _number(value)) is not None]
    return {"mean": sum(values) / len(values) if values else None,
            "scored_n": len(values), "eligible_n": eligible_n,
            "missing_n": eligible_n - len(values), "coverage": _rate(len(values), eligible_n)}


def _slug(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "-", value.strip()).strip("-._").lower()


def _dataset(kind: str) -> str:
    return next((name for name in ("historical", "temporal") if kind.startswith(name)), "unknown")


def _models(config: Mapping) -> dict:
    return {role: config.get("design", {}).get(role + "_profile", {}).get("model",
                config.get("providers", {}).get(role, {}).get("model"))
            for role in ("player", "oracle", "evaluator")}


def _plan(config: dict) -> list[dict]:
    design = config.get("design", {})
    repeats = design.get("repeats")
    if type(repeats) is not int or repeats < 1:
        raise ValueError("config.design.repeats must be a positive integer")
    order = config.get("schedule", {}).get("execution_order")
    if not isinstance(order, list) or not order or any(not isinstance(x, str) for x in order):
        raise ValueError("A nonempty frozen config.schedule.execution_order is required")
    if len(set(order)) != len(order):
        raise ValueError("Frozen schedule contains duplicate episode IDs")
    if design.get("total_episodes", len(order)) != len(order):
        raise ValueError("Frozen schedule size differs from design.total_episodes")
    descriptors = {}
    for family, variants in design.get("condition_semantics", {}).items():
        for variant, conditions in variants.items():
            for condition in conditions:
                key = (family, variant, condition["condition_id"])
                if key in descriptors:
                    raise ValueError("Duplicate condition descriptor: " + repr(key))
                descriptors[key] = condition
    methods = {_slug(method): method for method in design.get("evaluation_methods", [])}
    planned = []
    for index, episode_id in enumerate(order):
        pieces = episode_id.split("__")
        if (len(pieces) != 6 or "/" in episode_id or "\\" in episode_id
                or not re.fullmatch(r"r\d+", pieces[-1])):
            raise ValueError("Cannot identify frozen episode: " + episode_id)
        family, variant, condition, task, method, repeat = pieces
        repeat = int(repeat[1:])
        if not 1 <= repeat <= repeats:
            raise ValueError("Repeat is outside configured range: " + episode_id)
        descriptor = descriptors.get((family, variant, condition))
        if descriptor is None or _dataset(str(descriptor.get("dataset_kind", ""))) == "unknown":
            raise ValueError("Frozen dataset descriptor is missing: " + episode_id)
        if method not in methods:
            raise ValueError("Frozen method is undeclared: " + episode_id)
        planned.append({"episode_id": episode_id, "schedule_index": index,
                        "dataset": _dataset(descriptor["dataset_kind"]),
                        "dataset_kind": descriptor["dataset_kind"], "case_family": family,
                        "variant_id": variant, "condition_id": condition,
                        "condition_role": descriptor.get("condition_role"),
                        "task_setting": task, "evaluation_method": methods[method], "repeat": repeat})
    cells = defaultdict(set)
    for item in planned:
        cells[tuple(item[field] for field in CELL_FIELDS)].add(item["repeat"])
    if any(values != set(range(1, repeats + 1)) for values in cells.values()):
        raise ValueError("Frozen schedule must contain repeats 1..N for every cell")
    return planned


def _identity_errors(row: dict, item: dict, config: dict, *, evaluator: bool = False) -> list[str]:
    errors = []
    fields = ("episode_id", "case_family", "variant_id", "condition_id", "task_setting",
              "evaluation_method", "dataset_kind")
    for field in fields:
        if row.get(field) != item[field]:
            errors.append(item["episode_id"] + ": identity mismatch " + field)
    if not evaluator and row.get("repeat") != item["repeat"]:
        errors.append(item["episode_id"] + ": identity mismatch repeat")
    if row.get("experiment_id") != config.get("experiment_id"):
        errors.append(item["episode_id"] + ": experiment_id mismatch")
    if not evaluator and config.get("protocol_revision") is not None and row.get("protocol_revision") != config["protocol_revision"]:
        errors.append(item["episode_id"] + ": protocol_revision mismatch")
    return errors


def _attach_judge(root: Path, row: dict, item: dict, config: dict, errors: list[str]):
    row = deepcopy(row)
    row["metrics_complete"] = False
    row["llm_evaluation"] = None
    deferred = config.get("evaluator_generation", {}).get("mode") == "deferred_unconfigured"
    row["llm_evaluation_status"] = ("not_applicable" if row.get("status") != "evaluated"
                                    else "deferred_unconfigured" if deferred else "pending")
    row["evaluator_llm_stats"] = None
    path = root / "evaluations" / (item["episode_id"] + ".evaluation.json")
    if not path.exists() or row.get("status") != "evaluated":
        return row, None
    judge = _read(path)
    errors.extend(_identity_errors(judge, item, config, evaluator=True))
    if judge.get("run_id") != row.get("run_id"):
        errors.append(item["episode_id"] + ": evaluator run_id mismatch")
    row["llm_evaluation_status"] = judge.get("status", "unknown")
    row["llm_evaluation"] = judge.get("evaluation")
    row["evaluator_llm_stats"] = judge.get("llm_stats")
    if deferred:
        errors.append(item["episode_id"] + ": Judge sidecar exists although configuration defers Judge")
    elif judge.get("evaluator_prompt_version") != config.get("evaluator_generation", {}).get("prompt_version"):
        errors.append(item["episode_id"] + ": evaluator prompt differs from config")
    details = (judge.get("evaluation") or {}).get("details") or {}
    row["metrics_complete"] = (
        (row.get("formula_consistency") or {}).get("status") in
        {"equivalent", "not_equivalent", "inconclusive", "unavailable"}
        and judge.get("status") == "evaluated"
        and judge.get("evaluator_prompt_version") == DISCOVERY_PROMPT_VERSION
        and isinstance(details.get("understanding"), dict))
    return row, judge


def _measurements(row: dict) -> dict:
    if row.get("status") != "evaluated":
        return {name: None for name in METRICS}
    scientific = science_postevaluation(row)
    understanding = scientific.get("understanding") or {}
    return {"held_out_prediction_score": _number((row.get("scores") or {}).get(HELD_OUT_PREDICTION_SCORE)),
            "normalized_error": scientific.get("normalized_error"),
            "expression_match": scientific.get("expression_match"),
            "understanding_before": understanding.get("before_score"),
            "understanding_after": understanding.get("after_score"),
            "understanding_gain": understanding.get("delta") if understanding.get("status") == "paired" else None}


def load_run(root: Path) -> dict:
    root = root.resolve()
    config = _read(root / "config.json")
    planned = _plan(config)
    models = _models(config)
    errors = []
    for role, model in models.items():
        provider = config.get("providers", {}).get(role, {})
        deferred = role == "evaluator" and config.get("evaluator_generation", {}).get("mode") == "deferred_unconfigured"
        if role != "oracle" and not deferred and not isinstance(model, str):
            errors.append("Missing configured " + role + " model identity")
        if "model" in provider and provider["model"] != model:
            errors.append("Provider/profile model identity mismatch: " + role)
    by_id = {}
    observed_models = {role: Counter() for role in models}
    model_evidence_missing = Counter()
    for item in planned:
        path = root / "results" / (item["episode_id"] + ".result.json")
        if not path.exists():
            continue
        row = _read(path)
        errors.extend(_identity_errors(row, item, config))
        row, judge = _attach_judge(root, row, item, config, errors)
        for role in models:
            evidence = judge if role == "evaluator" else row
            if models[role] is None or evidence is None:
                continue
            actual = evidence.get(role + "_model")
            if actual is None:
                model_evidence_missing[role] += 1
                errors.append(item["episode_id"] + ": missing " + role + " model identity")
            else:
                observed_models[role][str(actual)] += 1
                if actual != models[role]:
                    errors.append(item["episode_id"] + ": unexpected " + role + " model " + str(actual))
        row["measurements"] = _measurements(row)
        by_id[item["episode_id"]] = row
    planned_ids = {item["episode_id"] for item in planned}
    extra = [path.name for path in (root / "results").glob("*.result.json")
             if path.name[:-len(".result.json")] not in planned_ids]
    if extra:
        errors.append("Result sidecars outside frozen schedule: " + ", ".join(sorted(extra)))
    return {"run_dir": str(root), "config": config, "planned": planned, "rows": by_id,
            "models": models, "audit": {"passed": not errors, "errors": errors,
                "observed_models": {role: dict(counts) for role, counts in observed_models.items()},
                "model_evidence_missing_n": dict(model_evidence_missing),
                "model_evidence_scope": "Configured and sidecar identity; no per-turn execution telemetry audit.",
                "config_sha256": hashlib.sha256((root / "config.json").read_bytes()).hexdigest(),
                "adjudications_present_but_not_applied": (root / "adjudications.json").exists()}}


def _resolved(row: dict) -> bool:
    return row.get("status") == "evaluated" and type(row.get("active_pass")) is bool


def _resources(recorded: Sequence[dict], planned_n: int) -> dict:
    paths = {"elapsed_s": ("elapsed_s",), "experiment_attempts": ("attempts_used",),
             "player_turns": ("player_llm_stats", "player_turns"),
             "decoded_actions": ("player_llm_stats", "decoded_actions"),
             "player_primary_calls": ("player_llm_stats", "primary_calls"),
             "player_repair_calls": ("player_llm_stats", "repair_calls")}
    for role in ("player", "oracle", "evaluator"):
        for kind in ("input_tokens", "output_tokens"):
            paths[role + "_" + kind] = (role + "_llm_stats", kind)
    result = {}
    for name, path in paths.items():
        values = []
        for row in recorded:
            value = row
            for key in path:
                value = value.get(key) if isinstance(value, Mapping) else None
            values.append(value)
        metric = _metric(values, planned_n)
        metric["known_sum"] = sum(_number(value) for value in values if _number(value) is not None) if metric["scored_n"] else None
        result[name] = metric
    return result


def _summary(planned: Sequence[dict], rows: Mapping[str, dict], required_repeats: int) -> dict:
    recorded = [rows[item["episode_id"]] for item in planned if item["episode_id"] in rows]
    resolved = [row for row in recorded if _resolved(row)]
    passed_n = sum(row["active_pass"] for row in resolved)
    cells = defaultdict(list)
    for item in planned:
        cells[tuple(item[field] for field in CELL_FIELDS)].append(item)
    complete = []
    for items in cells.values():
        if {item["repeat"] for item in items} != set(range(1, required_repeats + 1)):
            continue
        observations = [rows.get(item["episode_id"], {}) for item in items]
        if all(_resolved(row) for row in observations):
            complete.append(observations)
    complete_mean = _metric(
        (sum(row["active_pass"] for row in cell) / required_repeats for cell in complete), len(cells))["mean"]
    return {"planned_n": len(planned), "recorded_n": len(recorded),
            "missing_sidecar_n": len(planned) - len(recorded),
            "scored_n": len(resolved), "pass_n": passed_n, "fail_n": len(resolved) - passed_n,
            "pass_rate": _rate(passed_n, len(resolved)),
            "outcome_coverage": _rate(len(resolved), len(planned)),
            "unresolved_n": len(planned) - len(resolved),
            "infrastructure_n": sum(row.get("status") in INFRA for row in recorded),
            "status_counts": dict(Counter(row.get("status", "unknown") for row in recorded)),
            "judge_evaluated_n": sum(row.get("llm_evaluation_status") == "evaluated" for row in recorded),
            "judge_pending_n": sum(row.get("llm_evaluation_status") == "pending" for row in recorded),
            "judge_deferred_n": sum(row.get("llm_evaluation_status") == "deferred_unconfigured" for row in recorded),
            "judge_infrastructure_n": sum(row.get("llm_evaluation_status") in INFRA for row in recorded),
            "metrics_complete_n": sum(row.get("metrics_complete") is True for row in recorded),
            "metrics_unfinished_n": len(planned) - sum(row.get("metrics_complete") is True for row in recorded),
            "metrics": {name: _metric((row["measurements"].get(name) for row in recorded), len(planned))
                        for name in METRICS},
            "resources": _resources(recorded, len(planned)),
            "required_repeats": required_repeats, "planned_cells_n": len(cells),
            "complete_repeat_cells_n": len(complete),
            "complete_repeat_coverage": _rate(len(complete), len(cells)),
            "complete_cell_mean_pass_rate": complete_mean,
            "full_repeat_matrix_pass_rate": complete_mean if len(complete) == len(cells) else None,
            "complete_cell_any_pass_n": sum(any(row["active_pass"] for row in cell) for cell in complete),
            "complete_cell_any_pass_rate": _rate(sum(any(row["active_pass"] for row in cell) for cell in complete), len(complete)),
            "complete_cell_all_pass_n": sum(all(row["active_pass"] for row in cell) for cell in complete),
            "complete_cell_all_pass_rate": _rate(sum(all(row["active_pass"] for row in cell) for cell in complete), len(complete))}


def _groups(run: dict, fields: Sequence[str], *, prefix: int | None = None) -> list[dict]:
    groups = defaultdict(list)
    for item in run["planned"]:
        if prefix is None or item["repeat"] <= prefix:
            groups[tuple(item[field] for field in fields)].append(item)
    return [{**dict(zip(fields, key)), **_summary(items, run["rows"],
                prefix or run["config"]["design"]["repeats"])}
            for key, items in sorted(groups.items())]


def _protocol(config: dict, *, judge: bool = False) -> dict:
    design = deepcopy(config.get("design", {}))
    design.pop("evaluator_profile", None)
    player = design.get("player_profile", {})
    for key in ("model", "checkpoint_or_snapshot_id"):
        player.pop(key, None)
    providers = deepcopy(config.get("providers", {}))
    providers.pop("evaluator", None)
    for key in ("model", "checkpoint_or_snapshot_id"):
        providers.get("player", {}).pop(key, None)
    result = {"design": design, "providers": providers, "schema": config.get("schema"),
              "metrics_protocol": config.get("metrics_protocol"),
              "protocol_revision": config.get("protocol_revision"),
              "binary_aggregation": config.get("binary_aggregation"),
              "player_generation": config.get("player_generation"),
              "oracle_generation": config.get("oracle_generation"),
              "schedule": config.get("schedule")}
    if judge:
        result = {"evaluator_generation": config.get("evaluator_generation"),
                  "evaluator_profile": config.get("design", {}).get("evaluator_profile"),
                  "evaluator_provider": config.get("providers", {}).get("evaluator")}
    return result


def _differences(left: Any, right: Any, prefix: str = "") -> list[str]:
    if isinstance(left, dict) and isinstance(right, dict):
        result = []
        for key in sorted(set(left) | set(right)):
            name = prefix + "." + key if prefix else key
            if key not in left or key not in right:
                result.append(name)
            else:
                result.extend(_differences(left[key], right[key], name))
        return result
    return [] if left == right else [prefix]


def _paired(left: dict, right: dict, protocol_ok: bool, judge_ok: bool) -> list[dict]:
    left_cells = {tuple(item[field] for field in CELL_FIELDS) + (item["repeat"],): item for item in left["planned"]}
    right_cells = {tuple(item[field] for field in CELL_FIELDS) + (item["repeat"],): item for item in right["planned"]}
    result = []
    for key in sorted(set(left_cells) | set(right_cells)):
        a_item, b_item = left_cells.get(key), right_cells.get(key)
        a = left["rows"].get(a_item["episode_id"], {}) if a_item else {}
        b = right["rows"].get(b_item["episode_id"], {}) if b_item else {}
        scored = bool(a_item and b_item and _resolved(a) and _resolved(b))
        item = {**dict(zip((*CELL_FIELDS, "repeat"), key)),
                "left_episode_id": a_item["episode_id"] if a_item else None,
                "right_episode_id": b_item["episode_id"] if b_item else None,
                "left_status": a.get("status", "missing"), "right_status": b.get("status", "missing"),
                "left_pass": a.get("active_pass") if _resolved(a) else None,
                "right_pass": b.get("active_pass") if _resolved(b) else None,
                "both_scored": scored, "comparable": protocol_ok,
                "pass_delta_right_minus_left": int(b["active_pass"]) - int(a["active_pass"]) if scored and protocol_ok else None}
        for name in METRICS:
            av = _number(a.get("measurements", {}).get(name))
            bv = _number(b.get("measurements", {}).get(name))
            eligible = protocol_ok and (judge_ok or not name.startswith("understanding_"))
            item[name + "_delta_right_minus_left"] = bv - av if eligible and av is not None and bv is not None else None
        result.append(item)
    return result


def _paired_cells(pairs: Sequence[dict], required_repeats: int) -> list[dict]:
    groups = defaultdict(list)
    for pair in pairs:
        groups[tuple(pair[field] for field in CELL_FIELDS)].append(pair)
    result = []
    for key, items in sorted(groups.items()):
        complete = ({item["repeat"] for item in items} == set(range(1, required_repeats + 1))
                    and all(item["both_scored"] for item in items))
        comparable = complete and all(item["comparable"] for item in items)
        left_rate = sum(item["left_pass"] for item in items) / required_repeats if complete else None
        right_rate = sum(item["right_pass"] for item in items) / required_repeats if complete else None
        result.append({**dict(zip(CELL_FIELDS, key)), "required_repeats": required_repeats,
                       "both_complete": complete, "comparable": comparable,
                       "left_pass_rate": left_rate, "right_pass_rate": right_rate,
                       "pass_rate_delta_right_minus_left": right_rate - left_rate if comparable else None})
    return result


def build_comparison(run_dirs: Sequence[Path]) -> dict:
    if len(run_dirs) != 2 or run_dirs[0].resolve() == run_dirs[1].resolve():
        raise ValueError("Provide two distinct run directories")
    runs = [load_run(Path(path)) for path in run_dirs]
    protocol_differences = _differences(_protocol(runs[0]["config"]), _protocol(runs[1]["config"]))
    judge_differences = _differences(_protocol(runs[0]["config"], judge=True), _protocol(runs[1]["config"], judge=True))
    comparable = not protocol_differences and all(run["audit"]["passed"] for run in runs)
    judge_configured = all(run["models"]["evaluator"] is not None for run in runs)
    judge_comparable = comparable and not judge_differences and judge_configured
    paired = _paired(*runs, comparable, judge_comparable)
    paired_cells = _paired_cells(paired, runs[0]["config"]["design"]["repeats"])
    reports = []
    for run in runs:
        repeats = run["config"]["design"]["repeats"]
        reports.append({"run_dir": run["run_dir"], "experiment_id": run["config"].get("experiment_id"),
                        "models": run["models"], "audit": run["audit"],
                        "overall": _summary(run["planned"], run["rows"], repeats),
                        "by_dataset": _groups(run, ("dataset",)),
                        "by_method_task": _groups(run, GROUP_FIELDS[:-1]),
                        "by_condition": _groups(run, GROUP_FIELDS),
                        "by_repeat": _groups(run, (*GROUP_FIELDS, "repeat")),
                        "repeat_prefixes": [dict(repeat_prefix=n, **item)
                            for n in range(1, repeats + 1)
                            for item in _groups(run, GROUP_FIELDS, prefix=n)],
                        "cells": _groups(run, CELL_FIELDS)})
    grouped_pairs = defaultdict(list)
    for pair in paired:
        grouped_pairs[tuple(pair[field] for field in GROUP_FIELDS)].append(pair)
    paired_groups = [{**dict(zip(GROUP_FIELDS, key)), "planned_union_n": len(items),
                      "both_scored_n": sum(item["both_scored"] for item in items),
                      "pass_delta": _metric((item["pass_delta_right_minus_left"] for item in items), len(items)),
                      "metric_deltas": {name: _metric((item[name + "_delta_right_minus_left"] for item in items), len(items))
                                        for name in METRICS}}
                     for key, items in sorted(grouped_pairs.items())]
    return {"schema": SCHEMA, "generated_at": datetime.now(timezone.utc).isoformat(),
            "semantics": {"denominator": "Frozen schedules, including missing sidecars; missing values are null, never zero.",
                "case": "One family/variant/condition/task/method cell; primary rate is arithmetic mean of repeat outcomes, then equal case weight. complete_cell_mean_pass_rate describes only the complete-cell subset; full_repeat_matrix_pass_rate is null until every planned cell has every repeat 1..N resolved.",
                "repeat_prefixes": "At prefix k, case rates require every repeat 1..k, independently for each model.",
                "paired": "Right minus left on exactly the same cell and repeat, only with both measurements observed.",
                "judge": "A completed Player episode does not imply a completed Judge or full scientific metrics.",
                "resources": "Latest sidecars only, not all historical attempts/calls. Known sums retain coverage; experiment_attempts includes predefined observations; decoded_actions are decoded, not necessarily executed actions.",
                "snapshot": "Read-only live sidecar snapshot; files may progress during report generation.",
                "adjudication": "Machine outcomes only; manual adjudications are disclosed, not applied.",
                "model_identity": "Sidecar/config identities only; actual per-turn model execution is not independently verified."},
            "comparability": {"deterministic_comparable": comparable,
                "scientific_judge_comparable": judge_comparable, "judge_configured": judge_configured,
                "protocol_differences": protocol_differences, "judge_differences": judge_differences,
                "operational_differences": _differences(runs[0]["config"].get("execution", {}), runs[1]["config"].get("execution", {})),
                "same_player_model": runs[0]["models"]["player"] == runs[1]["models"]["player"]},
            "runs": reports, "paired_summary": {
                "planned_union_n": len(paired), "both_scored_n": sum(item["both_scored"] for item in paired),
                "pass_delta": _metric((item["pass_delta_right_minus_left"] for item in paired), len(paired)),
                "planned_union_cells_n": len(paired_cells),
                "both_complete_repeat_cells_n": sum(item["both_complete"] for item in paired_cells),
                "complete_cell_pass_rate_delta": _metric(
                    (item["pass_rate_delta_right_minus_left"] for item in paired_cells), len(paired_cells))},
            "paired_groups": paired_groups, "paired_episodes": paired, "paired_cells": paired_cells}


def _format(value: Any, *, percent: bool = False) -> str:
    if value is None:
        return "—"
    return ("%.1f%%" % (value * 100)) if percent else ("%.4f" % value if isinstance(value, float) else str(value))


def render_markdown(report: dict) -> str:
    audit = report["comparability"]
    left, right = report["runs"]
    lines = ["# Codex 两模型 benchmark 比较", "", "生成时间：" + report["generated_at"], "",
             "比较方向：`%s` − `%s`。" % (right["models"]["player"], left["models"]["player"]), "",
             "计划数以 config.json 冻结日程为准。缺失、基础设施失败和待完成 Judge 均单独统计；缺失值不补零。",
             "同一 case 指 family × variant × condition × task × method；完整重复率要求 1..N 全部取得机器二元结果。",
             "主要通过率先对每个 case 的 N 次结果取算术均值，再对 case 等权平均；N=3 时为 (p1+p2+p3)/3。",
             "全矩阵/全分组均值仅在所有计划 case 的 N 次结果完整后报告；未完整时为 —。已完整 case 子集均值仅描述该子集，不代表全矩阵。", "",
             "确定性指标协议可比：**%s**；Judge 指标可比：**%s**。" %
             ("是" if audit["deterministic_comparable"] else "否", "是" if audit["scientific_judge_comparable"] else "否")]
    if audit["protocol_differences"]:
        lines += ["", "协议差异（已停用配对差值）：" + ", ".join(audit["protocol_differences"])]
    if audit["judge_differences"]:
        lines += ["", "Judge 配置不同，科学理解差异不能归因于 Player；已停用相应配对差值。差异：" + ", ".join(audit["judge_differences"])]
    if not audit["judge_configured"]:
        lines += ["", "Judge 尚未配置；本报告不代表科学理解评审或全部指标已完成。"]
    for run in report["runs"]:
        summary = run["overall"]
        lines += ["", "## " + str(run["models"]["player"]), "", "运行目录：`" + run["run_dir"] + "`", "",
                  "计划 %d；机器二元结果 %d；通过 %d；缺失结果文件 %d；Player 基础设施失败 %d。" %
                  (summary["planned_n"], summary["scored_n"], summary["pass_n"], summary["missing_sidecar_n"], summary["infrastructure_n"]),
                  "Judge 完成 %d；待评 %d；明确延后 %d；Judge 基础设施失败 %d；全部指标完成 %d/%d。" %
                  (summary["judge_evaluated_n"], summary["judge_pending_n"], summary["judge_deferred_n"], summary["judge_infrastructure_n"], summary["metrics_complete_n"], summary["planned_n"]), "",
                  "**全矩阵 %d 次重复算术均值：%s**。完整重复 case %d/%d（覆盖 %s）；已完整 case 子集均值：%s。" %
                  (summary["required_repeats"], _format(summary["full_repeat_matrix_pass_rate"], percent=True),
                   summary["complete_repeat_cells_n"], summary["planned_cells_n"], _format(summary["complete_repeat_coverage"], percent=True),
                   _format(summary["complete_cell_mean_pass_rate"], percent=True)), "",
                  "| Dataset | 方法 | Task | Condition | 通过/已评分/计划 | 已评分通过率 | 完整重复 case/计划 | 已完整 case 子集均值 | 全分组重复均值 |",
                  "|---|---|---|---|---:|---:|---:|---:|---:|"]
        for item in run["by_condition"]:
            lines.append("| %s | %s | %s | %s | %d/%d/%d | %s | %d/%d | %s | %s |" %
                (*(str(item[field]) for field in GROUP_FIELDS), item["pass_n"], item["scored_n"], item["planned_n"],
                 _format(item["pass_rate"], percent=True), item["complete_repeat_cells_n"], item["planned_cells_n"],
                 _format(item["complete_cell_mean_pass_rate"], percent=True), _format(item["full_repeat_matrix_pass_rate"], percent=True)))
        lines += ["", "| 指标 | 已观测均值 | 已评分/计划 |", "|---|---:|---:|"]
        for name, metric in summary["metrics"].items():
            lines.append("| %s | %s | %d/%d |" % (name, _format(metric["mean"]), metric["scored_n"], metric["eligible_n"]))
        lines += ["", "| 耗时/次数/token | 已知合计 | 有数据/计划 |", "|---|---:|---:|"]
        for name, metric in summary["resources"].items():
            lines.append("| %s | %s | %d/%d |" % (name, _format(metric["known_sum"]), metric["scored_n"], metric["eligible_n"]))
        lines += ["", "资源统计仅来自当前结果文件，不覆盖所有历史尝试；experiment_attempts 包含预设观测，decoded_actions 表示已解析动作。"]
        if run["audit"]["errors"]:
            lines += ["", "身份审计失败，已停用配对差值："] + ["- " + error for error in run["audit"]["errors"]]
        if run["audit"]["adjudications_present_but_not_applied"]:
            lines += ["", "存在人工裁决文件；本报告仅使用机器结果，未将人工裁决写入评分。"]
    delta = report["paired_summary"]["pass_delta"]
    cell_delta = report["paired_summary"]["complete_cell_pass_rate_delta"]
    lines += ["", "## 同 case、同 repeat 配对", "",
              "双方均有二元结果 %d/%d；可比配对 %d；平均通过率差值 %s。" %
              (report["paired_summary"]["both_scored_n"], report["paired_summary"]["planned_union_n"], delta["scored_n"], _format(delta["mean"], percent=True)),
              "双方完整重复 case %d/%d；已共同完整 case 子集的等 case 权重平均通过率差值 %s（仅描述该子集）。" %
              (report["paired_summary"]["both_complete_repeat_cells_n"], report["paired_summary"]["planned_union_cells_n"], _format(cell_delta["mean"], percent=True)),
              "", "分组、逐 repeat、累计 1..k、逐 case 与配对明细见 JSON/CSV。不同缺失覆盖的原始通过率不用于模型排名。",
              "模型审计依据冻结配置与结果文件；未遍历调用日志，未独立验证每轮实际执行模型。报告为只读快照，运行中的结果可能继续增加。", ""]
    return "\n".join(lines)


def _flatten(value: Mapping, prefix: str = "") -> dict:
    result = {}
    for key, item in value.items():
        name = prefix + "." + key if prefix else key
        if isinstance(item, Mapping):
            result.update(_flatten(item, name))
        elif isinstance(item, list):
            result[name] = json.dumps(item, ensure_ascii=False)
        else:
            result[name] = item
    return result


def _csv(path: Path, rows: list[dict]):
    flattened = [_flatten(row) for row in rows]
    fields = list(dict.fromkeys(key for row in flattened for key in row))
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(flattened)


def write_report(report: dict, output_dir: Path):
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "comparison.json").write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    (output_dir / "comparison.md").write_text(render_markdown(report), encoding="utf-8")
    rows = []
    for run in report["runs"]:
        for grouping in ("by_dataset", "by_method_task", "by_condition", "by_repeat", "repeat_prefixes", "cells"):
            rows.extend({"model": run["models"]["player"], "run_dir": run["run_dir"], "grouping": grouping, **row}
                        for row in run[grouping])
    _csv(output_dir / "groups.csv", rows)
    _csv(output_dir / "paired_groups.csv", report["paired_groups"])
    _csv(output_dir / "paired_episodes.csv", report["paired_episodes"])
    _csv(output_dir / "paired_cells.csv", report["paired_cells"])


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, action="append", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    report = build_comparison(args.run_dir)
    write_report(report, args.output_dir)
    print(args.output_dir / "comparison.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
