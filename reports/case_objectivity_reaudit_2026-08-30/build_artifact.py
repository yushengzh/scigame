"""Build the bounded report artifact for the current case-quality review."""

from __future__ import annotations

import json
from pathlib import Path


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
FINDINGS_PATH = HERE / "scientific_findings.json"
OUTPUT_PATH = HERE / "artifact.json"
GENERATED_AT = "2026-08-31T20:00:00+04:00"
TITLE = "29 个 Matched Scientific Families / 116 Cells 质量复审"


def _label_pack(value: str) -> str:
    return {"built_in": "Built-in", "temporal": "Temporal"}[value]


def _label_status(value: str) -> str:
    return {"pass": "Pass", "revise": "Revise", "block": "Block"}[value]


def build() -> dict:
    findings = json.loads(FINDINGS_PATH.read_text(encoding="utf-8"))
    families = findings["families"]
    chart_rows = [
        {
            "pack": _label_pack(pack),
            "families": sum(row["pack"] == pack for row in families),
            "cells": 4 * sum(row["pack"] == pack for row in families),
        }
        for pack in ("built_in", "temporal")
    ]
    table_rows = []
    for sequence, row in enumerate(families, start=1):
        table_rows.append(
            {
                "sequence": sequence,
                "family": row["family"],
                "pack": _label_pack(row["pack"]),
                "status": _label_status(row["status"]),
                "scientific_truth": row["scientific_truth"],
                "player_information": row["player_information"],
                "oracle_information": row["deterministic_oracle_information"],
                "severity": row["severity"],
                "runtime_registered": row["runtime_registered"],
                "finding": row["finding"],
                "action": row["action"],
            }
        )

    findings_rel = str(FINDINGS_PATH.relative_to(ROOT))
    machine_rel = str((HERE / "machine_evidence.json").relative_to(ROOT))
    report_rel = str((HERE / "report.md").relative_to(ROOT))
    manifest = {
        "title": TITLE,
        "description": "Family-level scientific correctness, Player/Oracle information completeness, and dual-Oracle readiness review.",
        "version": 1,
        "surface": "report",
        "generatedAt": GENERATED_AT,
        "filters": [],
        "cards": [],
        "charts": [
            {
                "id": "admitted_family_counts",
                "title": "Admitted families by case pack",
                "subtitle": "29 admitted families / 116 matched cells; two rejected temporal candidates are excluded.",
                "type": "bar",
                "dataset": "admitted_family_counts",
                "sourceId": "admission_count_sql",
                "valueFormat": "number",
                "encodings": {
                    "x": {"field": "pack", "type": "nominal", "label": "Case pack"},
                    "y": {"field": "families", "type": "quantitative", "label": "Admitted families"},
                    "tooltip": [
                        {"field": "families", "type": "quantitative", "label": "Families", "format": "number"},
                        {"field": "cells", "type": "quantitative", "label": "Matched cells", "format": "number"}
                    ]
                }
            }
        ],
        "tables": [
            {
                "id": "family_findings_table",
                "title": "Family-level scientific and information findings",
                "subtitle": "Pass covers the declared scientific scope, Player information, deterministic Oracle truth, and evaluator contract.",
                "dataset": "family_findings",
                "sourceId": "family_table_sql",
                "defaultSort": {"field": "sequence", "direction": "asc"},
                "columns": [
                    {"field": "sequence", "label": "#", "type": "number"},
                    {"field": "family", "label": "Family", "type": "text"},
                    {"field": "pack", "label": "Pack", "type": "text"},
                    {"field": "status", "label": "Decision", "type": "text"},
                    {"field": "scientific_truth", "label": "Scientific truth", "type": "text"},
                    {"field": "player_information", "label": "Player info", "type": "text"},
                    {"field": "oracle_information", "label": "Deterministic Oracle info", "type": "text"},
                    {"field": "severity", "label": "Severity", "type": "text"},
                    {"field": "runtime_registered", "label": "Registered", "type": "boolean"},
                    {"field": "finding", "label": "Finding", "type": "text"},
                    {"field": "action", "label": "Minimum action", "type": "text"}
                ]
            }
        ],
        "blocks": [
            {"id": "title", "type": "markdown", "body": "# " + TITLE + "\n\n审查单位是 family；四个 matched cells 不被当成四个统计独立样本。"},
            {
                "id": "executive_summary",
                "type": "markdown",
                "sourceId": "scientific_findings",
                "body": "## Technical Summary\n\n**当前正式准入 29 个 family / 116 个 matched cells：20 个 built-in 与 9 个 temporal，均为 pass。** 116/116 真值提交通过 evaluator，116/116 false twins 被拒；1,242 次采样的确定性 Oracle 查询全部有限、单位一致且可重放。全部 29 个 family 已注册。\n\n另有两个 temporal candidates 被明确排除：它们的数值关系本身不必然错误，但不满足严格 matched-world 的同一科学对象与 evidence modality。确定性与概率性 Oracle 的差异仍是后续 ablation，不属于本轮 case 准入。"
            },
            {"id": "admission_chart", "type": "chart", "chartId": "admitted_family_counts"},
            {"id": "findings_table_block", "type": "table", "tableId": "family_findings_table"},
            {
                "id": "shared_gates",
                "type": "markdown",
                "sourceId": "machine_evidence",
                "body": "## Shared admission gates\n\n1. **Identification contract — pass:** public names, meanings, units, and finite-real domains are explicit; common temporal constants are no longer artificial unknowns.\n2. **Active information capacity — pass:** free parameters fit within the observation capacity, and finite domains cannot be completely enumerated within budget.\n3. **Runtime registration — pass:** all 20 built-in and 9 temporal families are addressable by their separate registries.\n4. **Oracle ablation — not evaluated here:** case truth was frozen independently of Oracle implementation."
            },
            {
                "id": "player_completeness",
                "type": "markdown",
                "sourceId": "scientific_findings",
                "body": "## Player information completeness\n\nAll admitted families expose apparatus, legal controls, readouts, units, domains/resolution, and budget. Historical and counterfactual public surfaces match apart from opaque IDs. Identification additionally exposes its complete scaffold; Discovery exposes only the shared expression grammar. No admitted Discovery payload reveals its sibling-world label or Identification skeleton."
            },
            {
                "id": "oracle_completeness",
                "type": "markdown",
                "sourceId": "machine_evidence",
                "body": "## Deterministic Oracle information completeness\n\nEvery selected world now carries non-empty applicability and fixed-condition context. The WorldModel returns the declared statistic, unit, resolution, and uncertainty wording, and both tracks receive identical evidence in the same world. Temporal fit uncertainty is retained as provenance when the Oracle evaluates only a central fitted curve."
            },
            {
                "id": "dual_oracle",
                "type": "markdown",
                "body": "## Oracle modes are a later ablation\n\nThe two modes must be separate implementations behind the same proposal/response contract: `deterministic` uses CaseOracle + WorldModel, while `probabilistic` lets a God LLM read the complete selected-world private science and generate evidence. This review neither implements nor compares that ablation. The existing exact-copy LLM presentation layer is not the probabilistic God Oracle."
            },
            {
                "id": "methodology",
                "type": "markdown",
                "sourceId": "machine_evidence",
                "body": "## Methodology\n\nThe review combined four-cell instantiation, boundary/midpoint Oracle queries, evaluator truth/false-twin checks, source-level family review, observation-capacity checks, and local numerical rank checks. Three independent reviewers covered built-in science, temporal source fidelity, and shared contracts. Full unit tests passed 410/410. Tests support implementation consistency; source review supports scientific fidelity within each declared idealization."
            },
            {
                "id": "limits",
                "type": "markdown",
                "body": "## Evidence boundary\n\nVerified means faithful to the cited source or explicitly disclosed benchmark idealization; it is not an independent experimental replication. A counterfactual need not exist in our world, but it must be clearly authored, internally coherent, comparable under the shared apparatus, and never presented as a source-observed historical regime."
            },
            {
                "id": "next_steps",
                "type": "markdown",
                "body": "## Next step\n\nThe 29 registered families can now be used for deterministic-Oracle development evaluation. Next, implement the probabilistic God Oracle as a genuinely independent path and preregister the deterministic-versus-probabilistic comparison. Do not change case truth while estimating that ablation effect."
            }
        ],
        "sources": [
            {"id": "scientific_findings", "label": "Family-level scientific adjudication", "path": findings_rel},
            {"id": "machine_evidence", "label": "Reproducible machine contract evidence", "path": machine_rel},
            {"id": "full_report", "label": "Detailed Markdown review", "path": report_rel},
            {
                "id": "admission_count_sql",
                "label": "Admitted family counts by pack",
                "path": findings_rel,
                "query": {
                    "engine": "sqlite",
                    "language": "sql",
                    "description": "Counts admitted family-level PASS decisions in the built-in and temporal packs; rejected candidates are stored outside $.families.",
                    "executed_at": GENERATED_AT,
                    "sql": "WITH document AS (SELECT CAST(readfile('" + findings_rel + "') AS TEXT) AS body), families AS (SELECT value FROM document, json_each(body, '$.families')) SELECT CASE json_extract(value, '$.pack') WHEN 'built_in' THEN 'Built-in' ELSE 'Temporal' END AS pack, count(*) AS families, 4*count(*) AS cells FROM families GROUP BY json_extract(value, '$.pack') ORDER BY CASE json_extract(value, '$.pack') WHEN 'built_in' THEN 1 ELSE 2 END;"
                }
            },
            {
                "id": "family_table_sql",
                "label": "Family-level adjudication rows",
                "path": findings_rel,
                "query": {
                    "engine": "sqlite",
                    "language": "sql",
                    "description": "Extracts the 29 admitted family decisions and their Player/Oracle completeness findings in source order.",
                    "executed_at": GENERATED_AT,
                    "sql": "WITH document AS (SELECT CAST(readfile('" + findings_rel + "') AS TEXT) AS body), families AS (SELECT key, value FROM document, json_each(body, '$.families')) SELECT CAST(key AS INTEGER)+1 AS sequence, json_extract(value, '$.family') AS family, CASE json_extract(value, '$.pack') WHEN 'built_in' THEN 'Built-in' ELSE 'Temporal' END AS pack, CASE json_extract(value, '$.status') WHEN 'pass' THEN 'Pass' WHEN 'revise' THEN 'Revise' ELSE 'Block' END AS status, json_extract(value, '$.scientific_truth') AS scientific_truth, json_extract(value, '$.player_information') AS player_information, json_extract(value, '$.deterministic_oracle_information') AS oracle_information, json_extract(value, '$.severity') AS severity, json_extract(value, '$.runtime_registered') AS runtime_registered, json_extract(value, '$.finding') AS finding, json_extract(value, '$.action') AS action FROM families ORDER BY CAST(key AS INTEGER);"
                }
            }
        ]
    }
    return {
        "surface": "report",
        "manifest": manifest,
        "snapshot": {
            "version": 1,
            "generatedAt": GENERATED_AT,
            "status": "ready",
            "datasets": {
                "admitted_family_counts": chart_rows,
                "family_findings": table_rows,
            },
        },
        "sources": manifest["sources"],
    }


if __name__ == "__main__":
    OUTPUT_PATH.write_text(
        json.dumps(build(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
