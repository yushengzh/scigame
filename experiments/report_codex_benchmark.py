"""Produce an offline Chinese progress report without changing benchmark results.

The frozen schedule is the denominator for progress. Scientific aggregates reuse
the official analysis implementation; missing observations never become scores.
Codex call audits include retries and failures, independently of episode status.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import tempfile
import time
from typing import Any, Mapping, Optional, Sequence

from experiments.analyze_case_matrix import _group_summary
from experiments.offline_adjudications import apply_adjudications, is_adjudicated


def _read(path: Path, warnings: list[str], *, required: bool = False) -> Any:
    if not path.exists():
        if required:
            raise ValueError("Required report input is missing: " + str(path))
        return None
    error_type = "unknown"
    retry_delays = (0.1, 0.2, 0.4, 0.8)
    for attempt in range(len(retry_delays) + 1):
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
            error_type = type(exc).__name__
            if attempt < len(retry_delays):
                time.sleep(retry_delays[attempt])
    message = "读取快照失败：%s (%s)" % (path.name, error_type)
    if required:
        raise ValueError(message)
    warnings.append(message)
    return None


def _number(value: Any) -> Optional[float]:
    return float(value) if type(value) in (int, float) and math.isfinite(value) else None


def _sum_known(values: Sequence[Any], denominator: int) -> dict:
    known = [value for value in values if _number(value) is not None]
    return {"sum": sum(known) if known else None, "covered_n": len(known),
            "eligible_n": denominator, "missing_n": denominator - len(known)}


def _slug(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "-", value.strip()).strip("-._").lower()


def _dataset(row: Mapping[str, Any], family_kinds: Mapping[str, str]) -> str:
    kind = str(row.get("dataset_kind") or "")
    if kind.startswith("historical"):
        return "historical"
    if kind.startswith("temporal"):
        return "temporal"
    return family_kinds.get(str(row.get("case_family")), "unknown")


def _plan(config: Mapping[str, Any], rows: list[dict], warnings: list[str]) -> list[dict]:
    design = config.get("design", {})
    family_kinds = {}
    for family, variants in design.get("condition_semantics", {}).items():
        for descriptors in variants.values():
            for descriptor in descriptors:
                family_kinds[family] = _dataset(descriptor, {})
    methods = {_slug(method): method for method in design.get("evaluation_methods", [])}
    by_id = {row["episode_id"]: row for row in rows}
    order = config.get("schedule", {}).get("execution_order", [])
    if not order:
        warnings.append("冻结执行顺序缺失；预计数量只能使用已记录 episode，无法判断完整覆盖。")
        order = list(by_id)
    if len(order) != len(set(order)):
        raise ValueError("Frozen schedule contains duplicate episode IDs")
    extra = set(by_id) - set(order)
    if extra:
        raise ValueError("Result episodes are outside the frozen schedule: " + ", ".join(sorted(extra)))
    planned = []
    for episode_id in order:
        pieces = episode_id.split("__")
        if len(pieces) != 6:
            raise ValueError("Cannot identify frozen episode cell: " + episode_id)
        family, variant, condition, task, method, repeat = pieces
        row = by_id.get(episode_id, {})
        item = {"episode_id": episode_id, "case_family": family,
                "condition_id": condition,
                "evaluation_method": methods.get(method, method), "task_setting": task,
                "dataset": _dataset(row or {"case_family": family}, family_kinds)}
        if row and (row.get("case_family") != family or row.get("task_setting") != task
                    or _slug(str(row.get("evaluation_method"))) != method):
            raise ValueError("Result identity differs from frozen schedule: " + episode_id)
        if item["dataset"] == "unknown":
            warnings.append("无法确认 dataset：" + family)
        planned.append(item)
    return planned


def _summary(planned: list[dict], rows: list[dict]) -> dict:
    official = _group_summary(rows)
    completed = [row for row in rows if row.get("status") == "evaluated"]
    adjudicated = [row for row in rows if is_adjudicated(row)]
    adjudicated_n = len(adjudicated)
    decisions = [row for row in completed if type(row.get("active_pass")) is bool]
    success = sum(row["active_pass"] for row in decisions)
    judge_infra = sum(row.get("llm_evaluation_status") in
                      {"infrastructure_failed", "infrastructure_error"} for row in completed)
    return {
        "planned_n": len(planned), "recorded_n": len(rows), "completed_n": len(completed) + adjudicated_n,
        "machine_completed_n": len(completed), "user_adjudicated_failure_n": adjudicated_n,
        "pending_n": len(planned) - len(rows), "unfinished_n": len(planned) - len(completed) - adjudicated_n,
        "infrastructure_n": sum(row.get("status") in
                                {"infrastructure_failed", "infrastructure_error"} and not is_adjudicated(row) for row in rows),
        "raw_infrastructure_n": sum(row.get("status") in
                                    {"infrastructure_failed", "infrastructure_error"} for row in rows),
        "other_recorded_status_n": sum(row.get("status") not in
            {"evaluated", "infrastructure_failed", "infrastructure_error"} for row in rows),
        "active_pass_n": success, "active_fail_n": len(decisions) - success + adjudicated_n,
        "active_pass_denominator": len(decisions) + adjudicated_n,
        "active_pass_rate": success / (len(decisions) + adjudicated_n) if decisions or adjudicated_n else None,
        "outcome_missing_n": len(completed) - len(decisions),
        "metrics_complete_n": sum(row.get("metrics_complete") is True for row in completed),
        "metrics_pending_n": sum(row.get("metrics_complete") is not True for row in completed),
        "adjudicated_metrics_unavailable_n": adjudicated_n,
        "judge_infrastructure_n": judge_infra,
        "scientific_postevaluation": official["scientific_postevaluation"],
        "active_episode_elapsed_s": _sum_known([row.get("elapsed_s") for row in rows], len(rows)),
    }


def _audit(root: Path, warnings: list[str]) -> dict:
    calls = []
    for directory in sorted((root / "codex_calls").glob("*")):
        if not directory.is_dir():
            continue
        request = _read(directory / "request.json", warnings) or {}
        response = _read(directory / "response.json", warnings)
        failure = _read(directory / "failure.json", warnings)
        tokens = _read(directory / "token_usage.json", warnings) or {}
        receipt = _read(directory / "thread_start_receipt.json", warnings) or {}
        metadata = (response or {}).get("metadata", {})
        total = tokens.get("total", {})
        usage = (response or {}).get("usage", {})
        elapsed = metadata.get("elapsed_s") if response else (failure or {}).get("elapsed_s")
        started_epoch = (receipt.get("thread") or {}).get("createdAt")
        values = {
            "input_tokens": total.get("inputTokens", usage.get("input_tokens")),
            "output_tokens": total.get("outputTokens", usage.get("output_tokens")),
            "total_tokens": total.get("totalTokens"),
            "cached_input_tokens": total.get("cachedInputTokens", metadata.get("cached_input_tokens")),
            "reasoning_output_tokens": total.get("reasoningOutputTokens", metadata.get("reasoning_tokens")),
        }
        if values["total_tokens"] is None and all(_number(values[k]) is not None
                                                 for k in ("input_tokens", "output_tokens")):
            values["total_tokens"] = values["input_tokens"] + values["output_tokens"]
        calls.append({"call_id": directory.name, "role": request.get("role", directory.name.split("-")[0]),
                      "status": "completed" if response else "failed" if failure else "pending",
                      "error_type": (failure or {}).get("error_type"), "elapsed_s": elapsed,
                      "started_epoch": started_epoch,
                      "requested_model": request.get("model"),
                      "reported_model": metadata.get("returned_model", receipt.get("model")),
                      "usage": values})
    def summarize(items):
        return {"calls_n": len(items), "status_counts": dict(Counter(x["status"] for x in items)),
                "error_type_counts": dict(Counter(x["error_type"] for x in items if x["error_type"])),
                "reported_model_counts": dict(Counter(x["reported_model"] for x in items if x["reported_model"])),
                "model_evidence_missing_n": sum(not x["reported_model"] for x in items),
                "elapsed_s": _sum_known([x["elapsed_s"] for x in items], len(items)),
                "usage": {name: _sum_known([x["usage"][name] for x in items], len(items))
                          for name in ("input_tokens", "output_tokens", "total_tokens",
                                       "cached_input_tokens", "reasoning_output_tokens")}}
    starts = [x["started_epoch"] for x in calls if _number(x["started_epoch"]) is not None]
    ends = [x["started_epoch"] + x["elapsed_s"] for x in calls
            if _number(x["started_epoch"]) is not None and _number(x["elapsed_s"]) is not None]
    return {**summarize(calls), "approximate_first_thread_started_epoch": min(starts) if starts else None,
        "approximate_last_call_ended_epoch": max(ends) if ends else None, "by_role": {
        role: summarize([x for x in calls if x["role"] == role])
        for role in sorted({x["role"] for x in calls})},
        "semantics": "All audited calls, including retries/failures; known partial totals with coverage. "
                     "Cached input and reasoning output are subsets, not additional tokens. "
                     "Model evidence is thread/start receipt, not per-turn execution telemetry."}


def _source_snapshot() -> dict:
    repo = Path(__file__).resolve().parents[1]
    names = ("experiments/run_case_matrix.py", "experiments/codex_structured_backend.py",
             "experiments/analyze_case_matrix.py", "experiments/report_codex_benchmark.py",
             "experiments/offline_adjudications.py",
             "src/role_benchmark/performance.py", "src/role_benchmark/postevaluation.py",
             "datasets/historical/manifest.json", "datasets/temporal/manifest.json",
             "src/role_benchmark/cases/historical_cards.json",
             "src/role_benchmark/temporal_cases/temporal_cards.json")
    return {"semantics": "Files at report generation time; not proof of run-start source identity.",
            "sha256": {name: hashlib.sha256((repo / name).read_bytes()).hexdigest()
                       for name in names if (repo / name).is_file()}}


def _timestamp(value: Any) -> Optional[datetime]:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return None


def build_report(root: Path) -> dict:
    root = root.resolve()
    warnings: list[str] = []
    config = _read(root / "config.json", warnings, required=True)
    episodes_path = root / "episodes.json"
    episodes = _read(episodes_path, warnings, required=episodes_path.exists()) or {"episodes": []}
    rows = episodes.get("episodes", [])
    if not isinstance(rows, list) or any(not isinstance(row, dict) or not row.get("episode_id") for row in rows):
        raise ValueError("episodes.json must contain identifiable episode records")
    if len({row["episode_id"] for row in rows}) != len(rows):
        raise ValueError("episodes.json contains duplicate episode IDs")
    if episodes.get("experiment_id", config.get("experiment_id")) != config.get("experiment_id"):
        raise ValueError("Run input experiment IDs differ")
    rows = apply_adjudications(root, rows)
    planned = _plan(config, rows, warnings)
    by_id = {row["episode_id"]: row for row in rows}
    groups = []
    grouped = defaultdict(list)
    for item in planned:
        grouped[(item["dataset"], item["evaluation_method"], item["task_setting"])].append(item)
    for (dataset, method, task), items in sorted(grouped.items()):
        groups.append({"dataset": dataset, "evaluation_method": method, "task_setting": task,
                       **_summary(items, [by_id[x["episode_id"]] for x in items if x["episode_id"] in by_id])})
    condition_groups = []
    grouped_conditions = defaultdict(list)
    for item in planned:
        grouped_conditions[(item["dataset"], item["condition_id"], item["evaluation_method"], item["task_setting"])].append(item)
    for (dataset, condition, method, task), items in sorted(grouped_conditions.items()):
        condition_groups.append({"dataset": dataset, "condition_id": condition,
                                 "evaluation_method": method, "task_setting": task,
                                 **_summary(items, [by_id[x["episode_id"]] for x in items if x["episode_id"] in by_id])})
    overall = _summary(planned, rows)
    science_file = _read(root / "scientific_postevaluation.json", warnings)
    science = overall["scientific_postevaluation"]
    # The preserved machine-only summary intentionally excludes user adjudication.
    raw_science = _group_summary([{k: v for k, v in row.items() if k not in
                                  {"user_adjudication", "effective_active_pass", "outcome_source"}} for row in rows])["scientific_postevaluation"]
    agreement = (all(science_file.get(key) == raw_science.get(key) for key in raw_science)
                 if isinstance(science_file, dict) else None)
    if agreement is False:
        warnings.append("scientific_postevaluation.json 与 episode 快照不同步；本报告使用同一 episode 快照按官方逻辑重算。")
    now = datetime.now(timezone.utc)
    starts = [stamp for row in rows if (stamp := _timestamp(row.get("started_at"))) is not None]
    ends = [stamp for row in rows if (stamp := _timestamp(row.get("ended_at"))) is not None]
    complete = overall["completed_n"] == overall["planned_n"] and overall["metrics_pending_n"] == 0
    last = max(ends) if complete and ends else now
    audit = _audit(root, warnings)
    audit_start = audit["approximate_first_thread_started_epoch"]
    audit_end = audit["approximate_last_call_ended_epoch"] if complete else now.timestamp()
    timeout_path = root / "recovery_history" / "timeout_override_provenance.json"
    timeout_override = _read(timeout_path, warnings, required=timeout_path.exists())
    if timeout_override is not None:
        if timeout_override.get("config_sha256") != hashlib.sha256((root / "config.json").read_bytes()).hexdigest():
            warnings.append("行政超时例外记录的 config SHA-256 与当前冻结配置不一致。")
        timeout_override = {key: timeout_override.get(key) for key in (
            "schema", "created_at", "completed_at", "status", "reason", "active_retry_ids",
            "judge_only_retry_ids", "original_player_timeout_s", "actual_player_timeout_s",
            "actual_evaluator_timeout_s", "scientific_parameters_unchanged", "new_call_ids",
            "sealed_outcomes_preserved")}
    return {
        "schema": "role_benchmark.codex_benchmark_status.v1", "experiment_id": config.get("experiment_id"),
        "generated_at": now.isoformat(timespec="seconds"), "run_dir": str(root),
        "complete": complete, "overall": overall, "groups": groups, "condition_groups": condition_groups,
        "complete_semantics": "All planned binary outcomes are resolved and machine episodes have finished post-evaluation; explicit user failure retains unavailable scientific measurements.",
        "execution_ended": overall["unfinished_n"] == 0 and audit["status_counts"].get("pending", 0) == 0,
        "adjudications": [row["user_adjudication"] for row in rows if is_adjudicated(row)],
        "administrative_timeout_override": timeout_override,
        "scientific_summary_file_agrees_with_snapshot": agreement,
        "configuration": {"case_pack": config.get("design", {}).get("case_pack"),
            "repeats": config.get("design", {}).get("repeats"),
            "schedule_seed": config.get("schedule", {}).get("seed"),
            "execution": config.get("execution"), "providers": config.get("providers"),
            "profiles": {role: config.get("design", {}).get(role + "_profile")
                         for role in ("player", "oracle", "evaluator")},
            "generation": {role: config.get(role + "_generation") for role in ("player", "oracle", "evaluator")}},
        "codex_audit": audit,
        "elapsed": {"first_recorded_episode_started_at": min(starts).isoformat() if starts else None,
                    "active_episode_wall_span_s": max(0, (last - min(starts)).total_seconds()) if starts else None,
                    "approximate_audited_wall_span_s": max(0, audit_end - audit_start)
                        if audit_start is not None and audit_end is not None else None,
                    "semantics": "Completed run: first active start to last active end; otherwise to report time. "
                                 "Audited wall span includes Judge, approximated from thread timestamps and call elapsed time. "
                                 "Concurrent call durations are reported separately."},
        "source_snapshot": _source_snapshot(), "warnings": sorted(set(warnings)),
    }


def _fmt(value: Any) -> str:
    return "—" if value is None else format(value, ".4g") if isinstance(value, float) else str(value)


def _pct(value: Any) -> str:
    return "—" if value is None else "%.1f%%" % (value * 100)


def _table(headers: Sequence[str], rows: Sequence[Sequence[Any]]) -> str:
    def line(items):
        return "| " + " | ".join(_fmt(x).replace("|", "\\|").replace("\n", " ") for x in items) + " |"
    return "\n".join([line(headers), line(["---"] * len(headers)), *[line(row) for row in rows]])


def _metric_cell(value: Mapping[str, Any]) -> str:
    return "%s；%d/%d (%s)" % (_fmt(value["mean"]), value["scored_n"],
                                 value["eligible_n"], _pct(value["coverage"]))


def render_report(status: Mapping[str, Any]) -> str:
    overall = status["overall"]
    science = overall["scientific_postevaluation"]
    config = status["configuration"]
    lines = ["# Codex benchmark 运行报告", "", "实验：`%s`。生成时间：%s。" %
             (status["experiment_id"], status["generated_at"]), "",
             "状态：%s；预计 %d，已定二元结果 %d，通过 %d/%d（%s），待形成结果 %d，未裁定 active INFRA %d，机器 episode 后评估缺测 %d。" %
             ("执行已结束" if status.get("execution_ended") else "尚未全部结束", overall["planned_n"], overall["completed_n"],
              overall["active_pass_n"], overall["active_pass_denominator"], _pct(overall["active_pass_rate"]),
              overall["pending_n"], overall["infrastructure_n"], overall["metrics_pending_n"]), "",
             *_adjudication_notes(status.get("adjudications", []), overall),
             "pending 包含尚未启动或正在执行的 episode，不计失败。active pass 分母含机器明确二元结果及下述用户明确裁定；未裁定 INFRA 单列。科学均值仅使用非缺测样本，覆盖分母含人工失败的缺测记录；缺失值显示“—”，不补零。", "",
             "本轮属于 public development benchmark：cases 与 truth 均公开，不能称为 private 或 contamination-resistant evaluation。同一 family 的四个 cases（两种条件 × identification/discovery）是配对单元，不是四个独立 family。fixed 与 adaptive 的停止规则不同，因此不是同预算比较。", "",
             "## 配置与覆盖", "", "数据包 `%s`，repeats=%s，调度种子=%s，并发 workers=%s。详见 [config.json](config.json)。" %
             (config["case_pack"], config["repeats"], config["schedule_seed"], (config["execution"] or {}).get("workers")), "",
             _table(["角色", "Provider", "请求模型", "Reasoning", "API", "冻结配置请求超时(s)"], [
                 [role, (config["providers"].get(role) or {}).get("name"),
                  (config["profiles"].get(role) or {}).get("model"),
                  (config["profiles"].get(role) or {}).get("reasoning_effort"),
                  (config["providers"].get(role) or {}).get("api"),
                  (config["providers"].get(role) or {}).get("timeout_s")]
                 for role in ("player", "oracle", "evaluator")]), "",
             *_timeout_notes(status.get("administrative_timeout_override")),
             "Codex 的 temperature、top_p、max_output_tokens 未由 app-server 暴露或强制；config 中 requested_generation 仅记录逻辑请求值。返回模型依据 thread/start 回执，不等于逐 turn 执行遥测。", "",
             _table(["Dataset", "Method", "Task", "预计", "已定结果", "通过/有结果", "通过率", "pending", "未裁定 INFRA", "Judge INFRA", "机器指标待补"], [
                 [g["dataset"], g["evaluation_method"], g["task_setting"], g["planned_n"], g["completed_n"],
                  "%d/%d" % (g["active_pass_n"], g["active_pass_denominator"]), _pct(g["active_pass_rate"]),
                  g["pending_n"], g["infrastructure_n"], g["judge_infrastructure_n"], g["metrics_pending_n"]]
                 for g in status["groups"]]), "",
             "原世界与反事实分列如下。明确失败包括机器 active_pass=false 与用户明确裁定；其余待形成结果、INFRA 和缺失判定不推断为失败。", "",
             _table(["Dataset", "Condition", "Method", "Task", "预计", "已定结果", "明确通过", "明确失败", "其中用户裁定", "有二元结果", "通过率", "pending", "未裁定 INFRA", "机器完成但判定缺失"], [
                 [g["dataset"], g["condition_id"], g["evaluation_method"], g["task_setting"],
                  g["planned_n"], g["completed_n"], g["active_pass_n"], g["active_fail_n"],
                  g["user_adjudicated_failure_n"], g["active_pass_denominator"], _pct(g["active_pass_rate"]), g["pending_n"],
                  g["infrastructure_n"], g["outcome_missing_n"]]
                 for g in status["condition_groups"]]), "", "## 科学指标", ""]
    metrics = [("归一化误差", science["normalized_error"]), ("表达式等价", science["expression_match"]),
               *[("理解 " + key, science["understanding"][key]) for key in ("before", "after", "delta")]]
    lines += [_table(["指标", "非缺测均值", "scored / eligible", "缺测", "覆盖率"], [
        [name, value["mean"], "%d/%d" % (value["scored_n"], value["eligible_n"]),
         value["eligible_n"] - value["scored_n"], _pct(value["coverage"])] for name, value in metrics]), "",
        "理解配对样本 n=%s；before=%s，after=%s，Δ=%s。固定设计与 prior 常无前测；前后分数的非配对均值不能直接相减作为理解增量。" %
        tuple(_fmt(science["understanding"]["paired"][k]) for k in ("n", "before_mean", "after_mean", "delta_mean")), "",
        "下表每个指标单元为“非缺测均值；scored/eligible（覆盖率）”。eligible 包含缺测 episode。", "",
        _table(["Dataset", "Method", "Task", "归一化误差", "表达式等价", "理解 before", "理解 after", "理解 Δ"], [
            [g["dataset"], g["evaluation_method"], g["task_setting"],
             _metric_cell(g["scientific_postevaluation"]["normalized_error"]),
             _metric_cell(g["scientific_postevaluation"]["expression_match"]),
             *[_metric_cell(g["scientific_postevaluation"]["understanding"][k]) for k in ("before", "after", "delta")]]
            for g in status["groups"]]), "",
        _table(["失败标签", "数量/全部失败", "比例"], [[code, "%d/%d" % (v["n"], v["failed_n"]), _pct(v["rate"])]
            for code, v in science["failure_modes"].items()]), "",
        "未分类失败 %d。F1–F5 为非互斥标签，分母含全部明确失败（含无标签的用户裁定失败），比例之和可超过 100%%。分组完整科学指标见 [benchmark_status.json](benchmark_status.json)。" % science["unclassified_failed_n"], "",
        "## 调用、用量与耗时", "",
        "审计包含所有已记录 Codex 调用及基础设施重试，不局限于成功 episode。tokens 为已有遥测的部分总和，缺测调用另报；缓存输入和 reasoning 输出分别是输入/输出子集，不额外相加。", ""]
    audits = [("全部", status["codex_audit"]), *status["codex_audit"]["by_role"].items()]
    lines += [_table(["角色", "调用", "完成", "失败", "pending", "已知 input", "已知 output", "已知 total", "用量覆盖调用", "已知调用耗时(s)"], [
        [role, a["calls_n"], a["status_counts"].get("completed", 0), a["status_counts"].get("failed", 0),
         a["status_counts"].get("pending", 0), a["usage"]["input_tokens"]["sum"], a["usage"]["output_tokens"]["sum"],
         a["usage"]["total_tokens"]["sum"], "%d/%d" % (a["usage"]["total_tokens"]["covered_n"], a["calls_n"]),
         a["elapsed_s"]["sum"]] for role, a in audits]), "",
        "已记录 active episode 墙钟跨度：%s 秒；含 Judge 的审计调用墙钟跨度约 %s 秒（由 thread 时间戳和调用耗时估算，未完成时截至报告时间）。并发调用耗时为累加量，不等于墙钟时间。模型回执分布：`%s`。" %
        (_fmt(status["elapsed"]["active_episode_wall_span_s"]), _fmt(status["elapsed"]["approximate_audited_wall_span_s"]),
         json.dumps(status["codex_audit"]["reported_model_counts"], ensure_ascii=False)), "",
        "## 证据与源码", "", "输入：[episodes.json](episodes.json)、[scientific_postevaluation.json](scientific_postevaluation.json)、[codex_calls](codex_calls/)。科学汇总文件与 episode 快照一致性：%s。" %
        ("一致" if status["scientific_summary_file_agrees_with_snapshot"] is True else "不一致或未提供"), "",
        "运行启动时的来源记录与源码快照见 [provenance.json](provenance.json) 和 [source_snapshot.tar.gz](source_snapshot.tar.gz)（如该运行已保存）。以下 SHA-256 是报告生成时的本地文件快照，不证明运行启动时使用了相同源码；复现本轮运行应优先使用已保存的启动时快照。", "",
        _table(["文件", "SHA-256"], list(status["source_snapshot"]["sha256"].items()))]
    if status["warnings"]:
        lines += ["", "## 快照说明", "", *["- " + message for message in status["warnings"]]]
    return "\n".join(lines) + "\n"


def _timeout_notes(override: Optional[Mapping[str, Any]]) -> list[str]:
    if override is None:
        return []
    targets = override.get("active_retry_ids") or []
    new_calls = override.get("new_call_ids")
    return [
        "行政等待超时例外见 [timeout_override_provenance.json](recovery_history/timeout_override_provenance.json)。"
        "冻结 config 的 Player 超时仍为 %s 秒；仅下列 active_retry_ids 目标在该次恢复中的 Player 单次请求实际等待上限为 %s 秒，"
        "其余 Player 调用沿用原配置，所有 Judge 请求仍为 %s 秒。上表展示冻结配置；实际恢复请求同时适用本例外记录。" % (
            _fmt(override.get("original_player_timeout_s")), _fmt(override.get("actual_player_timeout_s")),
            _fmt(override.get("actual_evaluator_timeout_s"))), "",
        *["- `" + str(episode_id) + "`" for episode_id in targets], "",
        "本例外只延长传输等待时间；模型、high reasoning、提示、科学规则、采样和动作字节上限保持原值。"
        "恢复状态：`%s`；新增调用 ID %s。原因记录：%s" % (
            override.get("status", "unknown"),
            ("共 %d 个，已写入上述 provenance" % len(new_calls)) if isinstance(new_calls, list)
            else "清单尚未封存，等待恢复结束",
            override.get("reason") or "未提供"), "",
    ]


def _adjudication_notes(records: Sequence[Mapping[str, Any]], overall: Mapping[str, Any]) -> list[str]:
    if not records:
        return []
    return [
        "%d 个二元判定：%d 个机器结果 + %d 个用户指定失败；科学指标缺测保留。" %
        (overall["active_pass_denominator"], overall["machine_completed_n"], overall["user_adjudicated_failure_n"]), "",
        "用户人工裁定：%d 个 episode 按用户明确指令计为失败（user-adjudicated failure），纳入完整二元结果分母；"
        "机器评估完成数仍为 %d。该例因超大输出未形成合法 final，已终止且不再调用模型。"
        "原始 result/evaluation/log 保持不变，原机器状态仍为 infrastructure_failed、active_pass=null。"
        "这里没有生成科学预测分数、表达式判断、Judge 评分或 F1–F5 标签；这些指标继续缺测。" %
        (overall["user_adjudicated_failure_n"], overall["machine_completed_n"]), "",
        *["- `" + str(record["episode_id"]) + "`：" + str(record["reason"]) for record in records], "",
        "决定与证据见 [adjudications.json](adjudications.json)，案例说明见 [CASE_FAILURE.md](CASE_FAILURE.md)。"
        "人工裁定只应用于本报告和离线 analysis；[episodes.json](episodes.json) 与原科学汇总仍保留机器原始状态。", "",
    ]


def _atomic_write(path: Path, content: str) -> None:
    descriptor, temporary = tempfile.mkstemp(prefix="." + path.name + ".", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(content)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_dir", type=Path)
    args = parser.parse_args(argv)
    status = build_report(args.run_dir)
    root = args.run_dir.resolve()
    _atomic_write(root / "benchmark_status.json", json.dumps(status, ensure_ascii=False, indent=2, allow_nan=False) + "\n")
    _atomic_write(root / "REPORT.md", render_report(status))
    print(root / "REPORT.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
