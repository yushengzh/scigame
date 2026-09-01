"""Build the bounded report artifact for the 2026-08-26 case/sample audit."""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from role_benchmark import Episode
from role_benchmark.cases import make_case
from role_benchmark.models import BenchmarkTrack
from role_benchmark.wire import episode_view_to_payload


ROOT = Path(__file__).resolve().parents[2]
REPORT_DIR = Path(__file__).resolve().parent
RUN_DIR = ROOT / "runs" / "deepseek_20_family_80_20260825"
TITLE = "当前 case 与 DeepSeek 80-cell bench sample 复核"


CASE_REVIEWS = {
    "beer_lambert": (
        1,
        "阻塞",
        "历史指数与数值正确；共享 note 直接给出 historical path exponent=1 和 0.6 标定。",
        "删除共享历史答案，只保留中性单位和仪器条件。",
    ),
    "boyle_j_tube": (
        2,
        "需收紧",
        "反比律正确；理想气体、准静态、无 dead volume 等精确适用条件未写全，thermal_condition 只有一个可选值。",
        "补固定理想条件；把单值 thermal_condition 从 control 移到 fixed condition。",
    ),
    "brownian_diffusion": (
        1,
        "阻塞",
        "历史 MSD 和半径标度正确；公开文本定义为 Brownian 且明写 historical 4Dt，却以 t² 作为反事实。",
        "改为中性 stochastic tracer motion，移除共享历史公式并固定温度、黏度和有效时间域。",
    ),
    "coulomb_force": (
        2,
        "需收紧",
        "22.47 µN 标定正确；共享 note 暴露 historical branch，交换位置后 deflection reverses 的装置语义含混。",
        "删除 branch 提示并改写初始观察。",
    ),
    "faraday_induction": (
        3,
        "可保留",
        "20 mV 标定、单位、线性 ramp、均匀法向磁场与 readout 一致。",
        "无必改项。",
    ),
    "galileo_inclined_plane": (
        3,
        "可保留",
        "滚动球、水钟代理及 t∝sqrt(s/sinθ) 的历史关系和单位一致。",
        "无必改项。",
    ),
    "hooke_spring": (
        2,
        "需收紧",
        "历史 x=F/k 与 5 cm 标定正确；反事实下 calibrated stiffness 不再等于零载荷 tangent stiffness。",
        "将 control 明确为 nominal stiffness scale。",
    ),
    "kepler_orbit": (
        3,
        "可保留",
        "固定中心星下 P∝a^(3/2) 且与 eccentricity 无关；单位和表达式一致。",
        "无必改项。",
    ),
    "michaelis_menten": (
        2,
        "需收紧",
        "历史饱和律和 substrate-inhibition twin 正确；字段 _um_per_min 实际单位是 uM/min，和微米命名冲突。",
        "改为 micromolar_per_min。",
    ),
    "newton_cooling": (
        1,
        "阻塞",
        "历史单指数正确；共享 spatially uniform、constant coefficient/capacity 条件与双指数反事实不相容，并暴露 historical model class。",
        "共享背景改成可含多个线性热 mode 的 aggregate readout；单 mode 仅保留为私有历史 truth。",
    ),
    "ohm_circuit": (
        1,
        "阻塞",
        "历史 I=V/R 和 10 mA 标定正确；ideal ohmic resistor/calibrated resistance 的定义与 R^-1/2 反事实冲突。",
        "改用不含定义关系的 material/construction setting，或更换反事实机制。",
    ),
    "pendulum": (
        3,
        "可保留",
        "小角理想化、长度平方根和质量零指数正确；10° 有限振幅误差低于当前读数分辨率尺度。",
        "无必改项。",
    ),
    "photoelectric": (
        3,
        "可保留",
        "阈值、stopping potential、absorbed photon flux 电流关系和 h/e 数值一致。",
        "无必改项。",
    ),
    "poiseuille_flow": (
        1,
        "阻塞",
        "历史数值正确；共享 Newtonian/no-slip/steady/fully-developed circular 条件锁定 r^4，却以 r^3 为反事实；入口段定义也需收紧。",
        "用 pressure taps 明确充分发展测量段；共享描述中移除分支决定性前提，或给出具体非牛顿/滑移机制。",
    ),
    "radioactive_decay": (
        1,
        "阻塞",
        "历史指数衰变正确；same specific activity、固定效率、无自吸收/死时间与 mass^0.7 反事实定义性冲突。",
        "改动时间规律，或明确引入质量依赖探测机制。",
    ),
    "rc_discharge": (
        2,
        "需收紧",
        "广义指数表达式和 RC 单位换算正确；β=2 不应称 stretched exponential。",
        "模型名改为 generalized_rc_discharge 或 weibull_rc_discharge。",
    ),
    "rutherford_scattering": (
        2,
        "需收紧",
        "Z²、areal density 和 csc^4(θ/2) 正确；exposure_relative 不应改变 count rate。",
        "改为 incident_alpha_flux_relative，并补充弹性、非相对论、未屏蔽适用域。",
    ),
    "stefan_boltzmann": (
        1,
        "阻塞",
        "历史 σA(T⁴-Ta⁴) 和面积换算正确；公开 ideal blackbody/emissivity-one/radiation-only 条件强烈锁定 T⁴，却以 T³ 为反事实。",
        "共享对象改成未知谱律的 radiative emitter，或明确反事实改变 density of states/dispersion。",
    ),
    "torricelli_efflux": (
        1,
        "阻塞",
        "4.43 m/s 标定正确；Player-visible note 明写 sqrt(2gh)，同时反事实 truth 使用 h¹。",
        "立即删除公开公式，并把共享前提改成不预先决定分支的操作条件。",
    ),
    "young_double_slit": (
        2,
        "需收紧",
        "历史 λL/d 与 1.10 mm 标定正确；blocking either slit removes the regular band pattern 过于绝对。",
        "改为 removes the fine two-slit fringe train, leaving any single-slit envelope。",
    ),
}


def _diff_paths(left: Any, right: Any, path: str = "$") -> list[str]:
    if type(left) is not type(right):
        return [path]
    if isinstance(left, dict):
        result: list[str] = []
        for key in sorted(set(left) | set(right)):
            child = f"{path}.{key}"
            if key not in left or key not in right:
                result.append(child)
            else:
                result.extend(_diff_paths(left[key], right[key], child))
        return result
    if isinstance(left, list):
        result = [f"{path}.length"] if len(left) != len(right) else []
        for index, (old, new) in enumerate(zip(left, right)):
            result.extend(_diff_paths(old, new, f"{path}[{index}]"))
        return result
    return [] if left == right else [path]


def _logged_case(log_path: Path) -> dict[str, Any]:
    with log_path.open(encoding="utf-8") as handle:
        event = json.loads(next(handle))
    return event["payload"]["case"]


def _current_case(row: dict[str, Any]) -> dict[str, Any]:
    case = make_case(
        row["case_family"],
        row["world"],
        BenchmarkTrack(row["track"]),
    )
    return episode_view_to_payload(Episode(case).view())["case"]


def build() -> dict[str, Any]:
    summary = json.loads((RUN_DIR / "episodes.json").read_text(encoding="utf-8"))
    episodes = summary["episodes"]
    no_science = [row for row in episodes if not row["scientifically_evaluable"]]

    categories = Counter(row["active_pass_category"] for row in episodes)
    reasons = Counter(row["reason_code"] for row in no_science)
    submitted = sum(row["scientifically_evaluable"] for row in episodes)
    passed = sum(row["active_pass"] for row in episodes)

    funnel = [
        {"stage_order": 1, "stage": "terminal outcome recorded", "episode_count": len(episodes)},
        {"stage_order": 2, "stage": "scientific evaluator input", "episode_count": submitted},
        {"stage_order": 3, "stage": "scientific pass", "episode_count": passed},
    ]
    reason_rows = [
        {
            "reason": reason,
            "episode_count": reasons[reason],
            "share_of_80": reasons[reason] / len(episodes),
        }
        for reason in (
            "invalid_json",
            "final_confidence_mismatch",
            "model_invariant",
            "duplicate_key",
            "experiment_budget_exhausted",
        )
    ]
    outcome_rows = [
        {
            "category": category,
            "episode_count": categories[category],
            "share_of_80": categories[category] / len(episodes),
        }
        for category in (
            "pass",
            "scientific_failure",
            "player_generation_failure",
            "player_protocol_failure",
        )
    ]

    case_rows = [
        {
            "priority": review[0],
            "family": family,
            "verdict": review[1],
            "finding": review[2],
            "minimum_fix": review[3],
        }
        for family, review in CASE_REVIEWS.items()
    ]

    drift_cells: dict[str, list[set[str]]] = defaultdict(list)
    for row in episodes:
        logged = _logged_case(RUN_DIR / row["log_path"])
        current = _current_case(row)
        paths = set(_diff_paths(logged, current))
        if paths:
            drift_cells[row["case_family"]].append(paths)
    drift_rows = []
    for family, cells in sorted(drift_cells.items()):
        union = set().union(*cells)
        drift_rows.append(
            {
                "family": family,
                "changed_cells": len(cells),
                "unique_changed_fields": len(union),
                "example_fields": ", ".join(sorted(union)[:4]),
            }
        )

    cell_groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in episodes:
        cell_groups[(row["world"], row["track"])].append(row)
    cell_rows = []
    for (world, track), rows in sorted(cell_groups.items()):
        cell_rows.append(
            {
                "world": world,
                "track": track,
                "episodes": len(rows),
                "scientifically_evaluable": sum(row["scientifically_evaluable"] for row in rows),
                "active_pass": sum(row["active_pass"] for row in rows),
            }
        )

    no_science_rows = [
        {
            "schedule_index": row["schedule_index"],
            "episode_id": row["episode_id"],
            "category": row["active_pass_category"],
            "reason": row["reason_code"],
            "attempts_used": row["attempts_used"],
        }
        for row in no_science
    ]

    generated_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    source_rows = [
        {
            "id": "episodes_summary",
            "label": "DeepSeek 80-cell canonical episode summary",
            "path": "runs/deepseek_20_family_80_20260825/episodes.json",
        },
        {
            "id": "episode_logs",
            "label": "DeepSeek Player/Oracle JSONL trajectories",
            "path": "runs/deepseek_20_family_80_20260825/episodes/",
        },
        {
            "id": "case_sources",
            "label": "Current matched family source files",
            "path": "src/role_benchmark/cases/",
        },
        {
            "id": "contract_tests",
            "label": "Current benchmark tests",
            "path": "tests/",
        },
        {
            "id": "audit_builder",
            "label": "Reproducible audit extraction",
            "path": "reports/case_sample_audit_2026-08-26/build_report_artifact.py",
        },
        {
            "id": "audit_sql",
            "label": "Reviewed report dataset queries",
            "path": "reports/case_sample_audit_2026-08-26/report_queries.sql",
        },
    ]

    return {
        "surface": "report",
        "manifest": {
            "version": 1,
            "surface": "report",
            "title": TITLE,
            "description": "20 个 matched family、当前四格定义与 DeepSeek 80-cell 开发 run 的科学与评测漏斗复核。",
            "generatedAt": generated_at,
            "cards": [],
            "charts": [
                {
                    "id": "evaluation_funnel",
                    "title": "DeepSeek 80-cell 评测漏斗",
                    "subtitle": "80 个 terminal outcomes 中，50 个有协议有效 final，21 个通过科学 evaluator。",
                    "type": "funnel",
                    "dataset": "funnel",
                    "sourceId": "audit_sql",
                    "encodings": {
                        "x": {"field": "stage", "type": "ordinal", "label": "stage"},
                        "y": {"field": "episode_count", "type": "quantitative", "label": "episodes"},
                        "tooltip": [
                            {"field": "episode_count", "type": "quantitative", "label": "episodes"}
                        ],
                    },
                    "valueFormat": "number",
                }
            ],
            "tables": [
                {
                    "id": "failure_reasons",
                    "title": "未进入科学 evaluator 的直接原因",
                    "subtitle": "30/80 个 terminal outcomes；精确 episode 见后续明细。",
                    "dataset": "failure_reasons",
                    "sourceId": "audit_sql",
                    "defaultSort": {"field": "episode_count", "direction": "desc"},
                    "columns": [
                        {"field": "reason", "label": "reason", "type": "text"},
                        {"field": "episode_count", "label": "episodes", "type": "number"},
                        {"field": "share_of_80", "label": "share of 80", "format": "percent"},
                    ],
                },
                {
                    "id": "case_audit",
                    "title": "20 个 family 的当前科学与公开条件判定",
                    "subtitle": "阻塞表示修复前不宜把该 family 纳入新的可比 run。",
                    "dataset": "case_audit",
                    "sourceId": "audit_sql",
                    "density": "comfortable",
                    "defaultSort": {"field": "priority", "direction": "asc"},
                    "columns": [
                        {"field": "priority", "label": "priority", "type": "number"},
                        {"field": "family", "label": "family", "type": "text"},
                        {"field": "verdict", "label": "verdict", "type": "text"},
                        {"field": "finding", "label": "finding", "type": "text"},
                        {"field": "minimum_fix", "label": "minimum fix", "type": "text"},
                    ],
                },
                {
                    "id": "version_drift",
                    "title": "旧 run 与当前 Player-visible case 的漂移",
                    "subtitle": "16/20 个 family、62/80 个 cell 的公开 payload 已变化。",
                    "dataset": "version_drift",
                    "sourceId": "audit_sql",
                    "density": "compact",
                    "defaultSort": {"field": "changed_cells", "direction": "desc"},
                    "columns": [
                        {"field": "family", "label": "family", "type": "text"},
                        {"field": "changed_cells", "label": "changed cells", "type": "number"},
                        {"field": "unique_changed_fields", "label": "changed fields", "type": "number"},
                        {"field": "example_fields", "label": "example fields", "type": "text"},
                    ],
                },
                {
                    "id": "cell_breakdown",
                    "title": "四格提交与通过计数",
                    "subtitle": "每格 20 个 family、每个 family 仅一个 repeat；只作描述，不作统计推断。",
                    "dataset": "cell_breakdown",
                    "sourceId": "audit_sql",
                    "defaultSort": {"field": "active_pass", "direction": "desc"},
                    "columns": [
                        {"field": "world", "label": "world", "type": "text"},
                        {"field": "track", "label": "track", "type": "text"},
                        {"field": "episodes", "label": "episodes", "type": "number"},
                        {"field": "scientifically_evaluable", "label": "scientific input", "type": "number"},
                        {"field": "active_pass", "label": "pass", "type": "number"},
                    ],
                },
                {
                    "id": "no_science_detail",
                    "title": "30 个未进入科学 evaluator 的 episode",
                    "subtitle": "所有行都有 terminal result；此表说明缺少的是 case-specific scientific score。",
                    "dataset": "no_science_detail",
                    "sourceId": "audit_sql",
                    "density": "compact",
                    "defaultSort": {"field": "schedule_index", "direction": "asc"},
                    "columns": [
                        {"field": "schedule_index", "label": "index", "type": "number"},
                        {"field": "episode_id", "label": "episode", "type": "text"},
                        {"field": "category", "label": "category", "type": "text"},
                        {"field": "reason", "label": "reason", "type": "text"},
                        {"field": "attempts_used", "label": "experiments", "type": "number"},
                    ],
                },
            ],
            "sources": source_rows,
            "blocks": [
                {"id": "title", "type": "markdown", "body": f"# {TITLE}"},
                {
                    "id": "technical_summary",
                    "type": "markdown",
                    "body": (
                        "## 结论：历史公式基本可靠，但当前 matched pack 与旧 80-cell run 均不能直接作为正式结果\n\n"
                        "当前 20 个 family 的历史 executable truth 没有发现实质公式或 SI 标定错误；然而按共享公开信息是否中性、两 world 是否逻辑相容来判定，只有 **5 个可直接保留**，"
                        "**7 个需措辞或命名收紧**，另有 **8 个阻塞项**。此外，固定 `.world_a/.world_b` 映射在公开代码中可被反查，不满足正式 blind pack。\n\n"
                        "DeepSeek smoke 的 80 个 episode 全都有 terminal result；其中 **50 个**提交了协议有效 final 并进入 case-specific evaluator，"
                        "**30 个**只得到协议层失败记录。旧 run 的 62/80 个 Player-visible case payload 已与当前源码不同，因此 21/80 pass 只能描述当时的开发快照。"
                    ),
                },
                {
                    "id": "funnel_finding",
                    "type": "markdown",
                    "sourceId": "episodes_summary",
                    "body": (
                        "## 30 个样本不是文件缺失，而是没有协议有效 final\n\n"
                        "主分母是全部 80 个 terminal outcomes。协议完成率为 **50/80（62.5%）**，全分母科学通过率为 **21/80（26.25%）**；"
                        "仅在已提交样本中计算的条件通过率是 **21/50（42%）**，不能替代主指标。"
                    ),
                },
                {"id": "funnel_chart", "type": "chart", "chartId": "evaluation_funnel"},
                {
                    "id": "failure_reason_interpretation",
                    "type": "markdown",
                    "sourceId": "episodes_summary",
                    "body": (
                        "### 大多数 non-completion 来自生成/协议结构，而不是 Oracle\n\n"
                        "20 个是 Player action 无法严格解码，10 个是已解码 action 被 episode invariant 拒绝。14 个 malformed JSON 中只有 2 个碰到 8192-token 上限；"
                        "其余主要是少括号、重复 key 或模型级 invariant。9 个 final confidence mismatch 来自 final 与 portfolio 的重复置信度字段不一致。"
                    ),
                },
                {"id": "failure_reason_table", "type": "table", "tableId": "failure_reasons"},
                {
                    "id": "case_finding",
                    "type": "markdown",
                    "sourceId": "case_sources",
                    "body": (
                        "## 8 个 family 的 shared public surface 需要先修\n\n"
                        "最明确的直接泄露是 Torricelli、Beer、Brownian 和 Poiseuille 的共享 note 写出了历史关系；"
                        "Newton cooling、Ohm、radioactive decay 和 Stefan–Boltzmann 则用公开定义或固定条件锁定历史机制，同时又声明不相容的反事实 truth。"
                    ),
                },
                {"id": "case_table", "type": "table", "tableId": "case_audit"},
                {
                    "id": "global_case_issue",
                    "type": "markdown",
                    "sourceId": "case_sources",
                    "body": (
                        "### 全局 blind-world 问题\n\n"
                        "当前 factory 固定将 historical 映射为 `.world_a`、counterfactual 映射为 `.world_b`。开发 pack 中可接受，但正式私有评测应使用与 world 无关的 opaque case ID，映射仅由隔离的 case service 持有。"
                    ),
                },
                {
                    "id": "drift_finding",
                    "type": "markdown",
                    "sourceId": "audit_builder",
                    "body": (
                        "## 旧 80-cell run 不是当前 case pack 的量化结果\n\n"
                        "逐 cell 比较 JSONL 首条 `run.started.case` 与当前 factory，发现 **16/20 family、62/80 cell** 的 Player-visible payload 已变化。"
                        "部分变化不只是措辞：Poiseuille 的控制域与 reference、Rutherford 的 control 语义、Photoelectric 的 control/parameter 命名均已改变。"
                    ),
                },
                {"id": "drift_table", "type": "table", "tableId": "version_drift"},
                {
                    "id": "cell_finding",
                    "type": "markdown",
                    "sourceId": "episodes_summary",
                    "body": (
                        "### 四格差异只能作为旧快照的描述\n\n"
                        "historical identification 的提交率和通过数最高，counterfactual discovery 最低；但每个 family×cell 只有一个 episode，且 case 定义已漂移，不能据此估计稳定模型差异或 difference-in-differences。"
                    ),
                },
                {"id": "cell_table", "type": "table", "tableId": "cell_breakdown"},
                {
                    "id": "oracle_finding",
                    "type": "markdown",
                    "sourceId": "episode_logs",
                    "body": (
                        "## Oracle 不是这 30 个样本缺少科学评分的原因\n\n"
                        "对 81 个 log attempts（含一次已恢复的 provider attempt）中的 **441** 条链路逐字段核对：authoritative response → LLM-presented Oracle response → Player-visible transition 的 status/evidence 均为 **0 mismatch**。"
                        "LLM 只参与 message 表达，测量、单位和不确定度仍来自 deterministic world model。"
                    ),
                },
                {
                    "id": "method_definitions",
                    "type": "markdown",
                    "sourceId": "audit_builder",
                    "body": (
                        "## 口径与检查方法\n\n"
                        "- **family**：一套历史/反事实 truth、统一实验资源和两个 track。\n"
                        "- **cell**：family × world × track；当前注册表应有 20×2×2=80。\n"
                        "- **terminal outcome recorded**：Player-side episode 已结束并写 result，不等于科学 evaluator 已调用。\n"
                        "- **scientifically evaluable**：存在协议有效 final，case-specific evaluator 实际运行。\n"
                        "- **科学复核**：检查历史公式、单位、reference 数值、公开固定条件、反事实内部一致性和 source credit；counterfactual 不要求在现实世界存在。\n\n"
                        "当前完整测试套件 **226 项通过**，证明结构、四格实例化、Oracle/evaluator 契约和 wire 行为一致；这些测试不能替代语义科学审查。"
                    ),
                },
                {
                    "id": "limitations",
                    "type": "markdown",
                    "body": (
                        "## 限制与稳健性\n\n"
                        "这是一轮源码、日志和 primary/authoritative source 的一致性复核，不是对历史实验的复现。"
                        "反事实 world 的判据是明确标注、内部可执行、与共享公开条件相容；它不声称是真实自然规律。"
                        "本 run 标记为 `public_development_fixture`，不是隔离的 private formal evaluation。"
                        "config 保存了 5-repeat/400-episode 完整计划，但当前目录实际只包含 r01 的 80-cell smoke；其余 320 个是未执行，不是失败。"
                    ),
                },
                {
                    "id": "recommendations",
                    "type": "markdown",
                    "body": (
                        "## 最小下一步\n\n"
                        "1. 先修 8 个阻塞 family、7 个轻微问题和 opaque world ID，再冻结新的 80-cell development pack。\n"
                        "2. 删除 `FinalSubmission.confidence` 与 portfolio confidence 的重复来源；final 阶段允许 portfolio 收敛为一个 hypothesis。\n"
                        "3. 只要 final model/parameters 可严格解码，就运行 scientific evaluator；portfolio/commitment 矛盾另记 process/protocol score。malformed JSON 仍不猜测补全。\n"
                        "4. failure-mode analyzer 对所有已有 experiment turns 做 evidence–belief 分析，再附 terminal failure；不要因 final 未提交而把过程 coverage 清零。\n"
                        "5. 在新 run directory 重跑当前 80 cells；通过后再补 3–5 repeats。"
                    ),
                },
                {
                    "id": "details",
                    "type": "markdown",
                    "sourceId": "episodes_summary",
                    "body": (
                        "## 逐 episode 查找\n\n"
                        "下表列出全部 30 个科学未评分 episode。它们都已有 terminal result，`reason` 是未进入 case-specific evaluator 的最直接机器原因。"
                    ),
                },
                {"id": "detail_table", "type": "table", "tableId": "no_science_detail"},
                {
                    "id": "further_questions",
                    "type": "markdown",
                    "body": (
                        "## 仍需明确的研究选择\n\n"
                        "最关键的问题是反事实 world 的语义边界：允许改变基本定律，但 shared public surface 应只描述操作对象、可控量和定性现象，"
                        "不应使用定义上已经蕴含历史定律的标签。采用这一条最小规则后，当前 8 个阻塞项都有直接、局部的修法。"
                    ),
                },
            ],
        },
        "snapshot": {
            "version": 1,
            "generatedAt": generated_at,
            "status": "ready",
            "datasets": {
                "funnel": funnel,
                "failure_reasons": reason_rows,
                "outcomes": outcome_rows,
                "case_audit": case_rows,
                "version_drift": drift_rows,
                "cell_breakdown": cell_rows,
                "no_science_detail": no_science_rows,
            },
        },
        "sources": source_rows,
        "package_info": {
            "chart_map": [
                {
                    "section": "evaluation funnel",
                    "question": "How many terminal outcomes reached scientific evaluation and passed?",
                    "type": "funnel",
                    "fields": ["stage", "episode_count"],
                    "takeaway": "80 terminal outcomes narrowed to 50 scientific inputs and 21 passes.",
                    "palette_policy": "single-root preferred",
                }
            ],
            "notes": [
                "Exact case and episode audit questions use tables; additional charts were omitted because they would obscure exact lookup.",
                "Required technical-report structure is preserved; key findings are split into case validity, evaluation funnel, version drift, and Oracle integrity.",
            ],
        },
    }


if __name__ == "__main__":
    output = REPORT_DIR / "artifact.json"
    output.write_text(
        json.dumps(build(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(output)
