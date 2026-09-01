#!/usr/bin/env python3
"""Build the canonical portable-report artifact from summary.json."""

from __future__ import annotations

import json
from pathlib import Path


HERE = Path(__file__).resolve().parent
SUMMARY_PATH = HERE / "summary.json"
ARTIFACT_PATH = HERE / "artifact.json"
CHART_MAP_PATH = HERE / "chart_map.json"
SOURCE_PATH = "out/bench_results_summary_20260830/summary.json"

MODEL_LABELS = {
    "gpt-5.6-sol": "GPT-5.6 Sol",
    "claude-opus-4-7": "Claude Opus 4.7",
    "kimi-k3": "Kimi K3",
    "qwen3.8-max": "Qwen 3.8 Max",
}

FAMILY_LABELS = {
    "beer_lambert": "Beer–Lambert",
    "boyle_j_tube": "Boyle J-tube",
    "brownian_diffusion": "Brownian diffusion",
    "coulomb_force": "Coulomb force",
    "faraday_induction": "Faraday induction",
    "galileo_inclined_plane": "Galileo inclined plane",
    "hooke_spring": "Hooke spring",
    "kepler_orbit": "Kepler orbit",
    "michaelis_menten": "Michaelis–Menten",
    "newton_cooling": "Newton cooling",
    "ohm_circuit": "Ohm circuit",
    "pendulum": "Pendulum",
    "photoelectric": "Photoelectric",
    "poiseuille_flow": "Poiseuille flow",
    "radioactive_decay": "Radioactive decay",
    "rc_discharge": "RC discharge",
    "rutherford_scattering": "Rutherford scattering",
    "stefan_boltzmann": "Stefan–Boltzmann",
    "torricelli_efflux": "Torricelli efflux",
    "young_double_slit": "Young double slit",
}

CELL_LABELS = {
    "H/I": "Historical / Identification",
    "H/D": "Historical / Discovery",
    "C/I": "Counterfactual / Identification",
    "C/D": "Counterfactual / Discovery",
}


def source(source_id, label, description, sql, executed_at, definitions=()):
    return {
        "id": source_id,
        "label": label,
        "path": SOURCE_PATH,
        "query": {
            "engine": "sqlite",
            "language": "sql",
            "description": description,
            "executed_at": executed_at,
            "sql": sql,
            "filters": ["Persisted results/*.result.json sidecars only; resume JSONL files are not episodes."],
            "metric_definitions": list(definitions),
        },
    }


def doc_prefix(path):
    return (
        "WITH document AS (SELECT CAST(readfile('" + SOURCE_PATH + "') AS TEXT) AS body), "
        + "items AS (SELECT value FROM document, json_each(body, '" + path + "')) "
    )


def main():
    summary = json.loads(SUMMARY_PATH.read_text(encoding="utf-8"))
    generated_at = summary["generated_at"]
    final = summary["final_matrix"]
    aggregate = final["aggregate_artifact_status"]
    gpt = final["gpt_complete"]
    family_did = gpt["family_difference_in_differences"]

    headline = [
        {
            "complete_formal_runs": sum(item["result_status"] == "complete" for item in final["runs"]),
            "formal_models": len(final["runs"]),
            "final_result_coverage": aggregate["result_records"] / aggregate["planned"],
            "gpt_active_pass_rate": final["runs"][0]["active_pass_rate_evaluated_pct"] / 100.0,
            "gpt_did_pp": gpt["difference_in_differences_pp"],
        }
    ]

    final_status = []
    for item in final["runs"]:
        row = {
            key: value
            for key, value in item.items()
            if isinstance(value, (str, int, float, bool)) or value is None
        }
        row["model_label"] = MODEL_LABELS.get(item["model"], item["model"])
        row["status_label"] = "完整" if item["result_status"] == "complete" else "未完成"
        final_status.append(row)

    common = []
    for item in final["common_evaluated_subset"]["runs"]:
        row = dict(item)
        row["model_label"] = MODEL_LABELS.get(item["model"], item["model"])
        common.append(row)
    common.sort(key=lambda item: -item["active_pass_rate_pct"])

    gpt_cells = []
    for item in gpt["cells"]:
        row = dict(item)
        row["cell_label"] = CELL_LABELS[item["cell"]]
        gpt_cells.append(row)

    pass_by_family = {item["family"]: item for item in gpt["families"]}
    gpt_families = []
    for item in family_did["rows"]:
        family = item["family"]
        row = dict(item)
        row.update(pass_by_family[family])
        row["family_label"] = FAMILY_LABELS.get(family, family.replace("_", " "))
        gpt_families.append(row)

    terminal = {item["code"]: item["episodes"] for item in summary["failure_modes"]["final_matrix_terminal"]}
    first = {item["code"]: item["episodes"] for item in summary["failure_modes"]["final_matrix_first_misstep"]}
    failure_modes = [
        {
            "code": code,
            "terminal_episodes": terminal.get(code, 0),
            "first_misstep_episodes": first.get(code, 0),
        }
        for code in sorted(set(terminal) | set(first), key=lambda code: (-(terminal.get(code, 0) + first.get(code, 0)), code))
    ]

    pilots = [
        {
            "run": "DeepSeek 20-family / 1 repeat",
            "n": summary["pilots"]["deepseek_20_family_80"]["summary"]["result_records"],
            "pass": summary["pilots"]["deepseek_20_family_80"]["summary"]["active_pass"],
            "all_denominator_pass_pct": summary["pilots"]["deepseek_20_family_80"]["summary"]["active_pass_rate_evaluated_pct"],
            "conditional_pass_pct": summary["pilots"]["deepseek_20_family_80"]["summary"]["conditional_scientific_pass_pct"],
            "comparability": "Matched one-repeat pilot; LLM Oracle presentation",
        },
        {
            "run": "DeepSeek legacy 58",
            "n": summary["pilots"]["deepseek_legacy_58"]["summary"]["result_records"],
            "pass": summary["pilots"]["deepseek_legacy_58"]["summary"]["active_pass"],
            "all_denominator_pass_pct": summary["pilots"]["deepseek_legacy_58"]["summary"]["active_pass_rate_evaluated_pct"],
            "conditional_pass_pct": summary["pilots"]["deepseek_legacy_58"]["summary"]["conditional_scientific_pass_pct"],
            "comparability": "Unbalanced legacy matrix",
        },
        {
            "run": "Pendulum warmup v3",
            "n": summary["pilots"]["pendulum_warmup_60"]["summary"]["result_records"],
            "pass": summary["pilots"]["pendulum_warmup_60"]["summary"]["evaluation_success"],
            "all_denominator_pass_pct": summary["pilots"]["pendulum_warmup_60"]["summary"]["evaluation_success"] * 100.0 / 60,
            "conditional_pass_pct": summary["pilots"]["pendulum_warmup_60"]["conditional_pass_pct"],
            "comparability": "Legacy pendulum schema",
        },
    ]

    inventory = summary["run_inventory"]

    sql_headline = (
        "WITH document AS (SELECT CAST(readfile('" + SOURCE_PATH + "') AS TEXT) AS body) "
        "SELECT (SELECT count(*) FROM document, json_each(body, '$.final_matrix.runs') "
        "WHERE json_extract(value, '$.result_status') = 'complete') AS complete_formal_runs, "
        "json_extract(body, '$.final_matrix.aggregate_artifact_status.result_records') * 1.0 / "
        "json_extract(body, '$.final_matrix.aggregate_artifact_status.planned') AS final_result_coverage, "
        "json_extract(body, '$.final_matrix.runs[0].active_pass_rate_evaluated_pct') / 100.0 AS gpt_active_pass_rate, "
        "json_extract(body, '$.final_matrix.gpt_complete.difference_in_differences_pp') AS gpt_did_pp FROM document;"
    )
    sql_final = doc_prefix("$.final_matrix.runs") + (
        "SELECT json_extract(value, '$.model') AS model, json_extract(value, '$.result_status') AS result_status, "
        "json_extract(value, '$.planned') AS planned, json_extract(value, '$.result_records') AS result_records, "
        "json_extract(value, '$.coverage_pct') AS coverage_pct, json_extract(value, '$.evaluated') AS evaluated, "
        "json_extract(value, '$.infrastructure_failed') AS infrastructure_failed, "
        "json_extract(value, '$.unattempted_or_not_durable') AS unattempted_or_not_durable, "
        "json_extract(value, '$.active_pass') AS active_pass, "
        "json_extract(value, '$.active_pass_rate_evaluated_pct') AS active_pass_rate_pct, "
        "json_extract(value, '$.protocol_completion_rate_evaluated_pct') AS protocol_completion_rate_pct, "
        "json_extract(value, '$.conditional_scientific_pass_pct') AS conditional_scientific_pass_pct, "
        "json_extract(value, '$.scientific_failure') AS scientific_failure, "
        "json_extract(value, '$.player_generation_failure') AS player_generation_failure, "
        "json_extract(value, '$.player_protocol_failure') AS player_protocol_failure, "
        "json_extract(value, '$.median_elapsed_seconds') AS median_elapsed_seconds FROM items ORDER BY coverage_pct DESC;"
    )
    sql_common = doc_prefix("$.final_matrix.common_evaluated_subset.runs") + (
        "SELECT json_extract(value, '$.model') AS model, json_extract(value, '$.n') AS n, "
        "json_extract(value, '$.active_pass') AS active_pass, "
        "json_extract(value, '$.active_pass_rate_pct') AS active_pass_rate_pct, "
        "json_extract(value, '$.protocol_completion_rate_pct') AS protocol_completion_rate_pct, "
        "json_extract(value, '$.scientifically_evaluable') AS scientifically_evaluable, "
        "json_extract(value, '$.conditional_scientific_pass_pct') AS conditional_scientific_pass_pct, "
        "json_extract(value, '$.scientific_failure') AS scientific_failure, "
        "json_extract(value, '$.player_generation_failure') AS player_generation_failure, "
        "json_extract(value, '$.player_protocol_failure') AS player_protocol_failure FROM items "
        "ORDER BY active_pass_rate_pct DESC;"
    )
    sql_cells = doc_prefix("$.final_matrix.gpt_complete.cells") + (
        "SELECT json_extract(value, '$.cell') AS cell, json_extract(value, '$.world') AS world, "
        "json_extract(value, '$.track') AS track, json_extract(value, '$.n') AS n, "
        "json_extract(value, '$.active_pass') AS active_pass, "
        "json_extract(value, '$.active_pass_rate_pct') AS active_pass_rate_pct, "
        "json_extract(value, '$.protocol_completion_rate_pct') AS protocol_completion_rate_pct, "
        "json_extract(value, '$.scientifically_evaluable') AS scientifically_evaluable, "
        "json_extract(value, '$.conditional_scientific_pass_pct') AS conditional_scientific_pass_pct FROM items;"
    )
    sql_family = doc_prefix("$.final_matrix.gpt_complete.family_difference_in_differences.rows") + (
        "SELECT json_extract(value, '$.family') AS family, json_extract(value, '$.delta_pp') AS delta_pp, "
        "json_extract(value, '$.historical_identification_pct') AS historical_identification_pct, "
        "json_extract(value, '$.historical_discovery_pct') AS historical_discovery_pct, "
        "json_extract(value, '$.counterfactual_identification_pct') AS counterfactual_identification_pct, "
        "json_extract(value, '$.counterfactual_discovery_pct') AS counterfactual_discovery_pct FROM items "
        "ORDER BY delta_pp DESC, family;"
    )
    sql_failures = (
        "WITH document AS (SELECT CAST(readfile('" + SOURCE_PATH + "') AS TEXT) AS body), "
        "terminal AS (SELECT json_extract(value, '$.code') AS code, json_extract(value, '$.episodes') AS n "
        "FROM document, json_each(body, '$.failure_modes.final_matrix_terminal')), "
        "first_step AS (SELECT json_extract(value, '$.code') AS code, json_extract(value, '$.episodes') AS n "
        "FROM document, json_each(body, '$.failure_modes.final_matrix_first_misstep')), "
        "codes AS (SELECT code FROM terminal UNION SELECT code FROM first_step) "
        "SELECT codes.code, coalesce(terminal.n, 0) AS terminal_episodes, "
        "coalesce(first_step.n, 0) AS first_misstep_episodes FROM codes "
        "LEFT JOIN terminal USING (code) LEFT JOIN first_step USING (code) "
        "ORDER BY terminal_episodes + first_misstep_episodes DESC, codes.code;"
    )
    sql_pilots = (
        "WITH document AS (SELECT CAST(readfile('" + SOURCE_PATH + "') AS TEXT) AS body) "
        "SELECT 'DeepSeek 20-family / 1 repeat' AS run, "
        "json_extract(body, '$.pilots.deepseek_20_family_80.summary.result_records') AS n, "
        "json_extract(body, '$.pilots.deepseek_20_family_80.summary.active_pass') AS pass, "
        "json_extract(body, '$.pilots.deepseek_20_family_80.summary.active_pass_rate_evaluated_pct') AS all_denominator_pass_pct, "
        "json_extract(body, '$.pilots.deepseek_20_family_80.summary.conditional_scientific_pass_pct') AS conditional_pass_pct FROM document "
        "UNION ALL SELECT 'DeepSeek legacy 58', json_extract(body, '$.pilots.deepseek_legacy_58.summary.result_records'), "
        "json_extract(body, '$.pilots.deepseek_legacy_58.summary.active_pass'), "
        "json_extract(body, '$.pilots.deepseek_legacy_58.summary.active_pass_rate_evaluated_pct'), "
        "json_extract(body, '$.pilots.deepseek_legacy_58.summary.conditional_scientific_pass_pct') FROM document "
        "UNION ALL SELECT 'Pendulum warmup v3', json_extract(body, '$.pilots.pendulum_warmup_60.summary.result_records'), "
        "json_extract(body, '$.pilots.pendulum_warmup_60.summary.evaluation_success'), "
        "json_extract(body, '$.pilots.pendulum_warmup_60.summary.evaluation_success') * 100.0 / 60.0, "
        "json_extract(body, '$.pilots.pendulum_warmup_60.conditional_pass_pct') FROM document;"
    )
    sql_inventory = doc_prefix("$.run_inventory") + (
        "SELECT json_extract(value, '$.run') AS run, json_extract(value, '$.classification') AS classification, "
        "json_extract(value, '$.planned') AS planned, json_extract(value, '$.result_records') AS result_records, "
        "json_extract(value, '$.evaluated') AS evaluated, json_extract(value, '$.legacy_completed') AS legacy_completed, "
        "json_extract(value, '$.infrastructure_failed') AS infrastructure_failed, "
        "json_extract(value, '$.active_pass') AS active_pass, json_extract(value, '$.evaluation_success') AS evaluation_success, "
        "json_extract(value, '$.raw_jsonl') AS raw_jsonl, json_extract(value, '$.resume_jsonl') AS resume_jsonl, "
        "json_extract(value, '$.note') AS note FROM items ORDER BY classification, run;"
    )

    sources = [
        {
            "id": "summary_data",
            "label": "Denominator-safe benchmark run summary",
            "path": SOURCE_PATH,
        },
        {
            "id": "summary_builder",
            "label": "Run-summary transformation",
            "path": "out/bench_results_summary_20260830/build_summary.py",
        },
        {
            "id": "current_submission_contract",
            "label": "Current FinalSubmission contract",
            "path": "src/role_benchmark/models.py",
        },
        source(
            "headline_sql",
            "Headline benchmark metrics",
            "Extracts formal-run completion, artifact coverage, the complete GPT active-pass rate, and paired-axis interaction.",
            sql_headline,
            generated_at,
            (
                "Final result coverage = persisted final-matrix result sidecars / 1,600 planned episodes.",
                "Active pass = protocol-valid completion and deterministic held-out scientific success.",
                "Delta is expressed in percentage points.",
            ),
        ),
        source("final_status_sql", "Formal matrix run status", "Extracts completion, pass, protocol, and failure counts for the four formal Player runs.", sql_final, generated_at),
        source("common_sql", "Four-model common evaluated subset", "Extracts outcomes on the 35 episode IDs evaluated by all four formal Player runs.", sql_common, generated_at),
        source("gpt_cells_sql", "GPT four-cell outcomes", "Extracts the balanced Historical/Counterfactual × Identification/Discovery outcomes for the complete GPT run.", sql_cells, generated_at),
        source("gpt_family_sql", "GPT family-level paired effects", "Extracts the 20 family-level difference-in-differences values and four cell rates.", sql_family, generated_at),
        source("failure_sql", "Formal matrix failure modes", "Combines terminal failure codes with the first localized process misstep for 820 evaluated formal episodes.", sql_failures, generated_at),
        source("pilot_sql", "Legacy and pilot outcomes", "Extracts three non-comparable pilot/warmup summaries without pooling them.", sql_pilots, generated_at),
        source("inventory_sql", "Run directory inventory", "Extracts all 27 direct out/runs subdirectories and their canonical artifact counts.", sql_inventory, generated_at),
    ]

    cards = [
        {
            "id": "complete_runs_card",
            "dataset": "headline",
            "sourceId": "headline_sql",
            "description": "四个正式 Player 中完成全部 400 episodes 的数量。",
            "metrics": [
                {"label": "完整主矩阵", "field": "complete_formal_runs", "format": "number"},
                {"label": "正式模型数", "field": "formal_models", "format": "number"},
            ],
        },
        {
            "id": "coverage_card",
            "dataset": "headline",
            "sourceId": "headline_sql",
            "description": "四模型正式矩阵中已持久化的结果覆盖率。",
            "metrics": [{"label": "正式结果覆盖", "field": "final_result_coverage", "format": "percent"}],
        },
        {
            "id": "gpt_pass_card",
            "dataset": "headline",
            "sourceId": "headline_sql",
            "description": "唯一完整正式 run 的 active-pass rate。",
            "metrics": [{"label": "GPT active pass", "field": "gpt_active_pass_rate", "format": "percent"}],
        },
        {
            "id": "gpt_did_card",
            "dataset": "headline",
            "sourceId": "headline_sql",
            "description": "(H,D − C,D) − (H,I − C,I)，单位为百分点。",
            "metrics": [{"label": "GPT Δ (pp)", "field": "gpt_did_pp", "format": "number", "signed": True}],
        },
    ]

    charts = [
        {
            "id": "coverage_chart",
            "title": "四个正式 Player run 的结果覆盖率",
            "subtitle": "持久化 result sidecars / 每模型计划 400 episodes；仅 GPT 完整。",
            "type": "bar",
            "dataset": "final_status",
            "sourceId": "final_status_sql",
            "valueFormat": "number",
            "unit": "%",
            "encodings": {
                "x": {"field": "model_label", "type": "nominal", "label": "Player"},
                "y": {"field": "coverage_pct", "type": "quantitative", "label": "结果覆盖率", "unit": "%"},
                "tooltip": [
                    {"field": "result_records", "type": "quantitative", "label": "持久化结果", "format": "number"},
                    {"field": "planned", "type": "quantitative", "label": "计划数", "format": "number"},
                    {"field": "active_pass", "type": "quantitative", "label": "Active pass", "format": "number"},
                ],
            },
        },
        {
            "id": "common_pass_chart",
            "title": "四模型共同 35 episodes 的 active-pass rate",
            "subtitle": "完全相同的 schedule 1–35；只覆盖 repeat 1 的不平衡随机前缀。",
            "type": "bar",
            "dataset": "common_35",
            "sourceId": "common_sql",
            "valueFormat": "number",
            "unit": "%",
            "encodings": {
                "x": {"field": "model_label", "type": "nominal", "label": "Player"},
                "y": {"field": "active_pass_rate_pct", "type": "quantitative", "label": "Active-pass rate", "unit": "%"},
                "tooltip": [
                    {"field": "active_pass", "type": "quantitative", "label": "Pass", "format": "number"},
                    {"field": "n", "type": "quantitative", "label": "N", "format": "number"},
                    {"field": "conditional_scientific_pass_pct", "type": "quantitative", "label": "提交后科学通过", "format": "number", "unit": "%"},
                ],
            },
        },
        {
            "id": "gpt_cells_chart",
            "title": "GPT-5.6 Sol 在四个 matched cells 的 active-pass rate",
            "subtitle": "每个 cell 100 episodes；H/C 为 historical/counterfactual，I/D 为 identification/discovery。",
            "type": "bar",
            "dataset": "gpt_cells",
            "sourceId": "gpt_cells_sql",
            "valueFormat": "number",
            "unit": "%",
            "encodings": {
                "x": {"field": "cell_label", "type": "nominal", "label": "Matched cell"},
                "y": {"field": "active_pass_rate_pct", "type": "quantitative", "label": "Active-pass rate", "unit": "%"},
                "tooltip": [
                    {"field": "active_pass", "type": "quantitative", "label": "Pass", "format": "number"},
                    {"field": "n", "type": "quantitative", "label": "N", "format": "number"},
                    {"field": "protocol_completion_rate_pct", "type": "quantitative", "label": "Protocol completion", "format": "number", "unit": "%"},
                ],
            },
        },
        {
            "id": "family_did_chart",
            "title": "GPT-5.6 Sol 的 family-level difference-in-differences",
            "subtitle": "20 个 family；正值表示 historical advantage 在 discovery 轨更大。",
            "type": "horizontalBar",
            "dataset": "gpt_families",
            "sourceId": "gpt_family_sql",
            "valueFormat": "number",
            "unit": "pp",
            "encodings": {
                "x": {"field": "family_label", "type": "nominal", "label": "Case family"},
                "y": {"field": "delta_pp", "type": "quantitative", "label": "Δ", "unit": "pp"},
                "tooltip": [
                    {"field": "delta_pp", "type": "quantitative", "label": "Δ", "format": "number", "unit": "pp"},
                    {"field": "active_pass_rate_pct", "type": "quantitative", "label": "总体 pass", "format": "number", "unit": "%"},
                ],
            },
        },
    ]

    tables = [
        {
            "id": "final_status_table",
            "title": "正式四模型矩阵的持久化结果",
            "subtitle": "主通过率分母仅含 evaluated；未运行或基础设施失败单列。",
            "dataset": "final_status",
            "sourceId": "final_status_sql",
            "density": "spacious",
            "defaultSort": {"field": "result_records", "direction": "desc"},
            "columns": [
                {"field": "model_label", "label": "Player", "type": "text"},
                {"field": "status_label", "label": "状态", "type": "text"},
                {"field": "result_records", "label": "结果 / 400", "type": "number"},
                {"field": "evaluated", "label": "Evaluated", "type": "number"},
                {"field": "active_pass", "label": "Pass", "type": "number"},
                {"field": "active_pass_rate_evaluated_pct", "label": "Pass %", "type": "number"},
                {"field": "protocol_completion_rate_evaluated_pct", "label": "Protocol %", "type": "number"},
                {"field": "conditional_scientific_pass_pct", "label": "提交后科学通过 %", "type": "number"},
                {"field": "infrastructure_failed", "label": "Infra", "type": "number"},
                {"field": "unattempted_or_not_durable", "label": "未运行/未持久化", "type": "number"},
            ],
        },
        {
            "id": "common_table",
            "title": "共同 35 episodes 的同题比较",
            "subtitle": "相同 episode IDs；N 小且四格不平衡，不能替代完整矩阵。",
            "dataset": "common_35",
            "sourceId": "common_sql",
            "density": "spacious",
            "defaultSort": {"field": "active_pass_rate_pct", "direction": "desc"},
            "columns": [
                {"field": "model_label", "label": "Player", "type": "text"},
                {"field": "n", "label": "N", "type": "number"},
                {"field": "active_pass", "label": "Pass", "type": "number"},
                {"field": "active_pass_rate_pct", "label": "Pass %", "type": "number"},
                {"field": "protocol_completion_rate_pct", "label": "Protocol %", "type": "number"},
                {"field": "conditional_scientific_pass_pct", "label": "提交后科学通过 %", "type": "number"},
                {"field": "scientific_failure", "label": "Science fail", "type": "number"},
                {"field": "player_generation_failure", "label": "Generation fail", "type": "number"},
                {"field": "player_protocol_failure", "label": "Protocol fail", "type": "number"},
            ],
        },
        {
            "id": "gpt_cells_table",
            "title": "GPT 四格的分母与条件通过率",
            "subtitle": "每格 N=100；protocol completion 基本平衡，主要差异发生在科学通过。",
            "dataset": "gpt_cells",
            "sourceId": "gpt_cells_sql",
            "density": "spacious",
            "columns": [
                {"field": "cell_label", "label": "Cell", "type": "text"},
                {"field": "n", "label": "N", "type": "number"},
                {"field": "active_pass", "label": "Pass", "type": "number"},
                {"field": "active_pass_rate_pct", "label": "Pass %", "type": "number"},
                {"field": "protocol_completion_rate_pct", "label": "Protocol %", "type": "number"},
                {"field": "scientifically_evaluable", "label": "科学可评", "type": "number"},
                {"field": "conditional_scientific_pass_pct", "label": "提交后科学通过 %", "type": "number"},
            ],
        },
        {
            "id": "gpt_family_table",
            "title": "GPT 的 20 个 family 结果",
            "subtitle": "每 family N=20；Δ 以 family 为统计独立单位。",
            "dataset": "gpt_families",
            "sourceId": "gpt_family_sql",
            "density": "dense",
            "defaultSort": {"field": "delta_pp", "direction": "desc"},
            "columns": [
                {"field": "family_label", "label": "Family", "type": "text"},
                {"field": "active_pass", "label": "Pass / 20", "type": "number"},
                {"field": "active_pass_rate_pct", "label": "Pass %", "type": "number"},
                {"field": "protocol_completion_rate_pct", "label": "Protocol %", "type": "number"},
                {"field": "delta_pp", "label": "Δ (pp)", "type": "number", "movement": True},
                {"field": "historical_identification_pct", "label": "H/I %", "type": "number"},
                {"field": "historical_discovery_pct", "label": "H/D %", "type": "number"},
                {"field": "counterfactual_identification_pct", "label": "C/I %", "type": "number"},
                {"field": "counterfactual_discovery_pct", "label": "C/D %", "type": "number"},
            ],
        },
        {
            "id": "failure_modes_table",
            "title": "正式矩阵的细粒度 failure modes",
            "subtitle": "Terminal 是最终失败原因；first misstep 是 failure analyzer 最早定位到的过程错误。",
            "dataset": "failure_modes",
            "sourceId": "failure_sql",
            "density": "dense",
            "defaultSort": {"field": "terminal_episodes", "direction": "desc"},
            "columns": [
                {"field": "code", "label": "Failure code", "type": "text"},
                {"field": "terminal_episodes", "label": "Terminal episodes", "type": "number"},
                {"field": "first_misstep_episodes", "label": "First-misstep episodes", "type": "number"},
            ],
        },
        {
            "id": "pilots_table",
            "title": "Pilot 与旧 schema 结果（不池化）",
            "subtitle": "三行的 Oracle、设计或结果 schema 不同，只报告各自分母内结果。",
            "dataset": "pilots",
            "sourceId": "pilot_sql",
            "density": "spacious",
            "columns": [
                {"field": "run", "label": "Run", "type": "text"},
                {"field": "n", "label": "N", "type": "number"},
                {"field": "pass", "label": "Pass", "type": "number"},
                {"field": "all_denominator_pass_pct", "label": "全分母 pass %", "type": "number"},
                {"field": "conditional_pass_pct", "label": "条件 pass %", "type": "number"},
                {"field": "comparability", "label": "可比性边界", "type": "text"},
            ],
        },
        {
            "id": "inventory_table",
            "title": "out/runs 的 27 个直接子目录",
            "subtitle": "result_records 是 canonical episode sidecars；raw JSONL 含 resume attempts。",
            "dataset": "inventory",
            "sourceId": "inventory_sql",
            "density": "dense",
            "defaultSort": {"field": "classification", "direction": "asc"},
            "columns": [
                {"field": "run", "label": "目录", "type": "text"},
                {"field": "classification", "label": "分类", "type": "text"},
                {"field": "planned", "label": "计划", "type": "number"},
                {"field": "result_records", "label": "Result", "type": "number"},
                {"field": "evaluated", "label": "Evaluated", "type": "number"},
                {"field": "legacy_completed", "label": "Legacy completed", "type": "number"},
                {"field": "infrastructure_failed", "label": "Infra", "type": "number"},
                {"field": "raw_jsonl", "label": "Raw logs", "type": "number"},
                {"field": "resume_jsonl", "label": "Resume logs", "type": "number"},
                {"field": "note", "label": "口径说明", "type": "text"},
            ],
        },
    ]

    blocks = [
        {"id": "title", "type": "markdown", "body": "# Role Benchmark 本地运行结果汇总"},
        {
            "id": "technical_summary",
            "type": "markdown",
            "sourceId": "summary_data",
            "body": (
                "## 结论：目前只有一个完整正式矩阵，差异化信号存在但还不能做四模型正式排名\n\n"
                "- **可用主结果只有 GPT-5.6 Sol 的完整 400 episodes。** 它取得 223/400 active pass（55.75%），371/400 protocol completion（92.75%），提交后的条件科学通过率为 60.11%。\n"
                "- **paired-axis 信号在该完整 run 上清楚。** H/I、H/D、C/I、C/D 分别为 66%、75%、50%、32%，所以预设 Δ 为 +27 pp；20 个 family 中 15 个为正，family-level 平均同为 +27 pp，描述性 95% t 区间为 +11.43 至 +42.57 pp。\n"
                "- **其余三个正式模型没有跑完。** Claude 保存 351/400、Kimi 36/400、Qwen 36/400；四者共同可比的只有相同 35 episodes，结果只能视为 pilot。\n"
                "- **这批结果不是当前最新三角色 API 管线的正式输出。** 四个 final run 使用 deterministic case Oracle 和规则 held-out evaluator，没有 LLM judge artifact；全部 652 个已提交 final 仍含后来删除的 `FinalSubmission.confidence`。"
            ),
        },
        {"id": "headline_metrics", "type": "metric-strip", "cardIds": ["complete_runs_card", "coverage_card", "gpt_pass_card", "gpt_did_card"]},
        {
            "id": "completion_finding",
            "type": "markdown",
            "sourceId": "final_status_sql",
            "body": (
                "## 四模型计划只完成了 823/1,600 个持久化结果\n\n"
                "GPT 跑满 400；Claude、Kimi、Qwen 分别在基础设施错误后停止。四个目录合计有 820 个 evaluated、3 个 infrastructure failed，另有 777 个计划 episode 没有本地持久化结果。因此不能用各目录当前 observed pass rate 直接排列四模型。"
            ),
        },
        {"id": "coverage_chart_block", "type": "chart", "chartId": "coverage_chart"},
        {"id": "final_status_table_block", "type": "table", "tableId": "final_status_table"},
        {
            "id": "common_finding",
            "type": "markdown",
            "sourceId": "common_sql",
            "body": (
                "## 同题比较的 35 episodes 只给出初步顺序\n\n"
                "在四个模型都完成的相同 schedule 1–35 上，Claude、GPT、Kimi、Qwen 的 active-pass rate 分别为 65.71%、54.29%、40.00%、25.71%。失败组成差异很大：Claude 的主要损失来自 generation/protocol，GPT 则主要是提交后的科学失败。该子集只含 repeat 1 的随机前缀，四格样本为 H/I=6、H/D=10、C/I=11、C/D=8，不能替代完整 matched matrix。"
            ),
        },
        {"id": "common_chart_block", "type": "chart", "chartId": "common_pass_chart"},
        {"id": "common_table_block", "type": "table", "tableId": "common_table"},
        {
            "id": "gpt_cell_finding",
            "type": "markdown",
            "sourceId": "gpt_cells_sql",
            "body": (
                "## GPT 的 counterfactual penalty 在 Discovery 轨明显放大\n\n"
                "Historical 相对 Counterfactual 的差距在 Identification 是 16 pp（66%−50%），在 Discovery 是 43 pp（75%−32%），所以 Δ=(H,D−C,D)−(H,I−C,I)=+27 pp。四格 protocol completion 均在 92%–94%，说明该差异主要来自科学评分，而不是某一格更容易触发协议失败。"
            ),
        },
        {"id": "gpt_cells_chart_block", "type": "chart", "chartId": "gpt_cells_chart"},
        {"id": "gpt_cells_table_block", "type": "table", "tableId": "gpt_cells_table"},
        {
            "id": "family_finding",
            "type": "markdown",
            "sourceId": "gpt_family_sql",
            "body": (
                "## +27 pp 不是由单个 family 独占，但 family 间异质性很大\n\n"
                "把 family 作为统计独立单位，15/20 的 Δ 为正、2 个为零、3 个为负；均值 +27 pp，中位数 +20 pp，描述性 95% t 区间为 +11.43 至 +42.57 pp。这个结果为 matched-axis 差异化命题提供单模型支持，但仍需要其他完整 Player run 复现，且不能把 5 次 repeat 当作 100 个独立 family。"
            ),
        },
        {"id": "family_chart_block", "type": "chart", "chartId": "family_did_chart"},
        {"id": "family_table_block", "type": "table", "tableId": "gpt_family_table"},
        {
            "id": "failure_finding",
            "type": "markdown",
            "sourceId": "failure_sql",
            "body": (
                "## 失败既包括科学错误，也包括旧协议与 action generation 错误\n\n"
                "820 个 evaluated 正式 episodes 中有 457 pass、195 scientific failure、124 player generation failure、44 player protocol failure。Terminal failure 以 held-out prediction error（187）最多；failure analyzer 还把 32 个 episode 的第一处错误定位为 final model misses observed evidence、19 个定位为 belief update opposes evidence、18 个定位为 belief update omitted。与此同时，33 个 terminal failure 来自后来已删除的 final-confidence mismatch，因此这部分不应被当作当前协议下的模型能力失败。"
            ),
        },
        {"id": "failure_table_block", "type": "table", "tableId": "failure_modes_table"},
        {
            "id": "pilot_finding",
            "type": "markdown",
            "sourceId": "pilot_sql",
            "body": (
                "## DeepSeek 与 pendulum 结果只能作为各自 pilot 解读\n\n"
                "DeepSeek 20-family 单 repeat 为 21/80 active pass（26.25%，提交后 42.00%）；旧 58-case 为 23/58（39.66%）；pendulum v3 旧 schema 为 33/60 evaluation success（55.00%，completed 后 84.62%）。它们的 Oracle、cell 平衡或 schema 不同，不能与 final 四模型池化。"
            ),
        },
        {"id": "pilot_table_block", "type": "table", "tableId": "pilots_table"},
        {
            "id": "scope_definitions",
            "type": "markdown",
            "sourceId": "summary_data",
            "body": (
                "## 统计口径\n\n"
                "- **Episode 单位**：一个已持久化的 `results/*.result.json`；35 个 `.resume-N.jsonl` 是同一 episode 的重试，不重复计数。\n"
                "- **Active pass**：Player 完成协议且规则 evaluator 的 held-out scientific evaluation 成功。\n"
                "- **条件科学通过率**：active pass / scientifically evaluable，即只在具有严格可解码 final model 的 episodes 上计算。\n"
                "- **H/C/I/D**：Historical、Counterfactual、Identification、Discovery。\n"
                "- **Difference-in-differences**：Δ=(P_H,D−P_C,D)−(P_H,I−P_C,I)；正值表示 historical advantage 在 Discovery 轨更大。"
            ),
        },
        {
            "id": "methodology",
            "type": "markdown",
            "sourceId": "summary_data",
            "body": (
                "## 复算与验证方法\n\n"
                "枚举了 `out/runs` 的 27 个直接子目录，其中 25 个是 bench-like，2 个是 temporal census/pipeline 输出。所有跨 case 汇总只使用布尔 active-pass、protocol-completion 和 scientific-evaluable 字段；没有平均不同 family 的专用误差分数。四模型比较取 evaluated episode ID 的交集；主 Δ 在完整 GPT run 上先按四格计算，再以 20 个 family 的 Δ 作为独立单位复核。SQLite 查询结果与两条独立脚本复算一致。"
            ),
        },
        {
            "id": "limitations",
            "type": "markdown",
            "sourceId": "summary_data",
            "body": (
                "## 局限与版本边界\n\n"
                "1. **只有 GPT 完整。** 另外三个模型的 observed rows 是同一随机 schedule 的前缀，缺失不是随机完成后的普通 sampling noise。\n"
                "2. **结果来自旧 submission contract。** 四个 final run 的 652 个已提交记录都含现在已经删除的 `FinalSubmission.confidence`，并有 33 个 terminal final-confidence mismatch。\n"
                "3. **没有 LLM evaluator 结果。** `evaluator` 配置为空，也没有 `evaluations/*.evaluation.json`；现有 active pass 来自规则 held-out evaluator。\n"
                "4. **Oracle 条件不同。** 四个 final run 使用 deterministic `case_world_model`，DeepSeek 80-run 使用 LLM presentation over authoritative world model。\n"
                "5. **Claude 目录是混合快照。** `episodes.json` 声明 351 但数组有 356 条，后 5 条没有完整本地 sidecars；本报告只采信 351 个持久化 result 文件。\n"
                "6. **Active pass 偏向完整可执行预测。** 如果项目要主测关系发现，应在未来 run 前把 structured relation recovery 注册为独立 endpoint，而不是继续依赖少量 post-hoc probes。"
            ),
        },
        {
            "id": "inventory_intro",
            "type": "markdown",
            "sourceId": "inventory_sql",
            "body": (
                "## 目录全量盘点\n\n"
                "本地共有 1,110 个 result sidecars 和 1,149 个 JSONL；这些数字包含 superseded warmup、gateway/API 诊断和不同设计的 pilot，因此只用于说明存量，不构成一个统计总体。下表给出逐目录归类。"
            ),
        },
        {"id": "inventory_table_block", "type": "table", "tableId": "inventory_table"},
        {
            "id": "next_steps",
            "type": "markdown",
            "body": (
                "## 下一步：先让当前协议产生一组可比较的新结果\n\n"
                "1. 用当前已删除 final confidence、允许单 hypothesis 收敛、严格可解码即科学评分的协议，重新跑至少一个完整 20-family × 4-cell × 5-repeat matrix。\n"
                "2. Player、Oracle、Evaluator 的 provider/model 参数独立写入每个 run config；机器 held-out score 保留为主科学分数，LLM judge 只作为过程评分的独立层。\n"
                "3. 若关系恢复是目标能力，将 direction/shape 或结构化 law relation 变成预先声明的提交与评分字段，再启动多模型正式比较。"
            ),
        },
        {
            "id": "further_questions",
            "type": "markdown",
            "body": (
                "## 仍需固定的评测选择\n\n"
                "- 正式 primary endpoint 是完整 held-out prediction，还是结构化 relationship recovery？二者应分开报告，不能事后互换。\n"
                "- 正式 Oracle 是否统一为 deterministic world model，LLM 只负责自然语言呈现？若不同 Player 使用不同 Oracle transport，模型间比较会混入 Oracle 方差。\n"
                "- LLM judge 是否只量化 evidence use、belief update 与最终解释，并明确不覆盖机器可判定的科学真值分数？"
            ),
        },
    ]

    artifact = {
        "surface": "report",
        "manifest": {
            "version": 1,
            "surface": "report",
            "title": "Role Benchmark 本地运行结果汇总",
            "description": "对 out/runs 的正式矩阵、可比子集、pilot 与 failure modes 做分母一致的统计汇总。",
            "generatedAt": generated_at,
            "filters": [],
            "cards": cards,
            "charts": charts,
            "tables": tables,
            "sources": sources,
            "blocks": blocks,
        },
        "snapshot": {
            "version": 1,
            "generatedAt": generated_at,
            "status": "ready",
            "datasets": {
                "headline": headline,
                "final_status": final_status,
                "common_35": common,
                "gpt_cells": gpt_cells,
                "gpt_families": gpt_families,
                "failure_modes": failure_modes,
                "pilots": pilots,
                "inventory": inventory,
            },
            "accessIssues": [],
        },
        "sources": sources,
    }
    ARTIFACT_PATH.write_text(json.dumps(artifact, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    chart_map = {
        "generated_at": generated_at,
        "charts": [
            {
                "section": "Formal run completion",
                "question": "How much of each 400-episode run is persisted?",
                "family": "Comparison & Ranking",
                "type": "bar",
                "fields": ["model_label", "coverage_pct", "result_records", "planned"],
                "takeaway": "Only GPT is complete; other model rates are partial.",
                "palette_policy": "single-root preferred",
                "artifact": "report.html#coverage_chart",
            },
            {
                "section": "Common evaluated subset",
                "question": "How do four Players compare on identical episode IDs?",
                "family": "Comparison & Ranking",
                "type": "bar",
                "fields": ["model_label", "active_pass_rate_pct", "active_pass", "n"],
                "takeaway": "The 35-episode order is preliminary and not a full ranking.",
                "palette_policy": "single-root preferred",
                "artifact": "report.html#common_pass_chart",
            },
            {
                "section": "GPT matched cells",
                "question": "How does active pass vary across the 2×2 matched design?",
                "family": "Comparison & Ranking",
                "type": "bar",
                "fields": ["cell_label", "active_pass_rate_pct", "protocol_completion_rate_pct"],
                "takeaway": "Counterfactual Discovery is the hardest cell and yields Δ=+27 pp.",
                "palette_policy": "single-root preferred",
                "artifact": "report.html#gpt_cells_chart",
            },
            {
                "section": "Family-level paired effects",
                "question": "Is the aggregate Δ broad-based across families?",
                "family": "Uncertainty & Benchmark",
                "type": "signed horizontal bar",
                "fields": ["family_label", "delta_pp", "active_pass_rate_pct"],
                "takeaway": "15/20 family deltas are positive, with substantial heterogeneity.",
                "palette_policy": "hard two-root cap",
                "artifact": "report.html#family_did_chart",
            },
        ],
    }
    CHART_MAP_PATH.write_text(json.dumps(chart_map, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
