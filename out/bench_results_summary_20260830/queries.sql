-- Canonical report queries. Run from the repository root with sqlite3.

-- headline_metrics
WITH document AS (
  SELECT CAST(readfile('out/bench_results_summary_20260830/summary.json') AS TEXT) AS body
)
SELECT
  (SELECT count(*) FROM document, json_each(body, '$.final_matrix.runs')
   WHERE json_extract(value, '$.result_status') = 'complete') AS complete_formal_runs,
  json_extract(body, '$.final_matrix.aggregate_artifact_status.result_records') * 1.0 /
    json_extract(body, '$.final_matrix.aggregate_artifact_status.planned') AS final_result_coverage,
  json_extract(body, '$.final_matrix.runs[0].active_pass_rate_evaluated_pct') / 100.0 AS gpt_active_pass_rate,
  json_extract(body, '$.final_matrix.gpt_complete.difference_in_differences_pp') AS gpt_did_pp
FROM document;

-- final_run_status
WITH document AS (
  SELECT CAST(readfile('out/bench_results_summary_20260830/summary.json') AS TEXT) AS body
), runs AS (
  SELECT value FROM document, json_each(body, '$.final_matrix.runs')
)
SELECT
  json_extract(value, '$.model') AS model,
  json_extract(value, '$.result_status') AS result_status,
  json_extract(value, '$.planned') AS planned,
  json_extract(value, '$.result_records') AS result_records,
  json_extract(value, '$.coverage_pct') AS coverage_pct,
  json_extract(value, '$.evaluated') AS evaluated,
  json_extract(value, '$.infrastructure_failed') AS infrastructure_failed,
  json_extract(value, '$.unattempted_or_not_durable') AS unattempted_or_not_durable,
  json_extract(value, '$.active_pass') AS active_pass,
  json_extract(value, '$.active_pass_rate_evaluated_pct') AS active_pass_rate_pct,
  json_extract(value, '$.protocol_completion_rate_evaluated_pct') AS protocol_completion_rate_pct,
  json_extract(value, '$.conditional_scientific_pass_pct') AS conditional_scientific_pass_pct,
  json_extract(value, '$.scientific_failure') AS scientific_failure,
  json_extract(value, '$.player_generation_failure') AS player_generation_failure,
  json_extract(value, '$.player_protocol_failure') AS player_protocol_failure,
  json_extract(value, '$.median_elapsed_seconds') AS median_elapsed_seconds
FROM runs
ORDER BY CASE model
  WHEN 'gpt-5.6-sol' THEN 1
  WHEN 'claude-opus-4-7' THEN 2
  WHEN 'kimi-k3' THEN 3
  WHEN 'qwen3.8-max' THEN 4
  ELSE 5 END;

-- common_35
WITH document AS (
  SELECT CAST(readfile('out/bench_results_summary_20260830/summary.json') AS TEXT) AS body
), runs AS (
  SELECT value FROM document, json_each(body, '$.final_matrix.common_evaluated_subset.runs')
)
SELECT
  json_extract(value, '$.model') AS model,
  json_extract(value, '$.n') AS n,
  json_extract(value, '$.active_pass') AS active_pass,
  json_extract(value, '$.active_pass_rate_pct') AS active_pass_rate_pct,
  json_extract(value, '$.protocol_completion_rate_pct') AS protocol_completion_rate_pct,
  json_extract(value, '$.scientifically_evaluable') AS scientifically_evaluable,
  json_extract(value, '$.conditional_scientific_pass_pct') AS conditional_scientific_pass_pct,
  json_extract(value, '$.scientific_failure') AS scientific_failure,
  json_extract(value, '$.player_generation_failure') AS player_generation_failure,
  json_extract(value, '$.player_protocol_failure') AS player_protocol_failure
FROM runs
ORDER BY active_pass_rate_pct DESC;

-- gpt_cells
WITH document AS (
  SELECT CAST(readfile('out/bench_results_summary_20260830/summary.json') AS TEXT) AS body
), cells AS (
  SELECT value FROM document, json_each(body, '$.final_matrix.gpt_complete.cells')
)
SELECT
  json_extract(value, '$.cell') AS cell,
  json_extract(value, '$.world') AS world,
  json_extract(value, '$.track') AS track,
  json_extract(value, '$.n') AS n,
  json_extract(value, '$.active_pass') AS active_pass,
  json_extract(value, '$.active_pass_rate_pct') AS active_pass_rate_pct,
  json_extract(value, '$.protocol_completion_rate_pct') AS protocol_completion_rate_pct,
  json_extract(value, '$.scientifically_evaluable') AS scientifically_evaluable,
  json_extract(value, '$.conditional_scientific_pass_pct') AS conditional_scientific_pass_pct
FROM cells
ORDER BY CASE json_extract(value, '$.cell')
  WHEN 'H/I' THEN 1 WHEN 'H/D' THEN 2 WHEN 'C/I' THEN 3 WHEN 'C/D' THEN 4 END;

-- gpt_family_did
WITH document AS (
  SELECT CAST(readfile('out/bench_results_summary_20260830/summary.json') AS TEXT) AS body
), families AS (
  SELECT value FROM document, json_each(body, '$.final_matrix.gpt_complete.family_difference_in_differences.rows')
)
SELECT
  json_extract(value, '$.family') AS family,
  json_extract(value, '$.delta_pp') AS delta_pp,
  json_extract(value, '$.historical_identification_pct') AS historical_identification_pct,
  json_extract(value, '$.historical_discovery_pct') AS historical_discovery_pct,
  json_extract(value, '$.counterfactual_identification_pct') AS counterfactual_identification_pct,
  json_extract(value, '$.counterfactual_discovery_pct') AS counterfactual_discovery_pct
FROM families
ORDER BY delta_pp DESC, family;

-- gpt_family_pass
WITH document AS (
  SELECT CAST(readfile('out/bench_results_summary_20260830/summary.json') AS TEXT) AS body
), families AS (
  SELECT value FROM document, json_each(body, '$.final_matrix.gpt_complete.families')
)
SELECT
  json_extract(value, '$.family') AS family,
  json_extract(value, '$.n') AS n,
  json_extract(value, '$.active_pass') AS active_pass,
  json_extract(value, '$.active_pass_rate_pct') AS active_pass_rate_pct,
  json_extract(value, '$.protocol_completion_rate_pct') AS protocol_completion_rate_pct
FROM families
ORDER BY active_pass_rate_pct DESC, family;

-- terminal_failures
WITH document AS (
  SELECT CAST(readfile('out/bench_results_summary_20260830/summary.json') AS TEXT) AS body
), failures AS (
  SELECT value FROM document, json_each(body, '$.failure_modes.final_matrix_terminal')
)
SELECT
  json_extract(value, '$.code') AS code,
  json_extract(value, '$.episodes') AS episodes
FROM failures
ORDER BY episodes DESC, code;

-- pilots
WITH document AS (
  SELECT CAST(readfile('out/bench_results_summary_20260830/summary.json') AS TEXT) AS body
)
SELECT 'DeepSeek 20-family / 1 repeat' AS run,
       json_extract(body, '$.pilots.deepseek_20_family_80.summary.result_records') AS n,
       json_extract(body, '$.pilots.deepseek_20_family_80.summary.active_pass') AS pass,
       json_extract(body, '$.pilots.deepseek_20_family_80.summary.active_pass_rate_evaluated_pct') AS all_denominator_pass_pct,
       json_extract(body, '$.pilots.deepseek_20_family_80.summary.conditional_scientific_pass_pct') AS conditional_pass_pct,
       'modern case-matrix; LLM oracle presentation' AS comparability
FROM document
UNION ALL
SELECT 'DeepSeek legacy 58',
       json_extract(body, '$.pilots.deepseek_legacy_58.summary.result_records'),
       json_extract(body, '$.pilots.deepseek_legacy_58.summary.active_pass'),
       json_extract(body, '$.pilots.deepseek_legacy_58.summary.active_pass_rate_evaluated_pct'),
       json_extract(body, '$.pilots.deepseek_legacy_58.summary.conditional_scientific_pass_pct'),
       'unbalanced legacy matrix'
FROM document
UNION ALL
SELECT 'Pendulum warmup v3',
       json_extract(body, '$.pilots.pendulum_warmup_60.summary.result_records'),
       json_extract(body, '$.pilots.pendulum_warmup_60.summary.evaluation_success'),
       json_extract(body, '$.pilots.pendulum_warmup_60.summary.evaluation_success') * 100.0 /
         json_extract(body, '$.pilots.pendulum_warmup_60.summary.result_records'),
       json_extract(body, '$.pilots.pendulum_warmup_60.conditional_pass_pct'),
       'legacy pendulum schema'
FROM document;

-- run_inventory
WITH document AS (
  SELECT CAST(readfile('out/bench_results_summary_20260830/summary.json') AS TEXT) AS body
), runs AS (
  SELECT value FROM document, json_each(body, '$.run_inventory')
)
SELECT
  json_extract(value, '$.run') AS run,
  json_extract(value, '$.classification') AS classification,
  json_extract(value, '$.planned') AS planned,
  json_extract(value, '$.result_records') AS result_records,
  json_extract(value, '$.evaluated') AS evaluated,
  json_extract(value, '$.legacy_completed') AS legacy_completed,
  json_extract(value, '$.infrastructure_failed') AS infrastructure_failed,
  json_extract(value, '$.active_pass') AS active_pass,
  json_extract(value, '$.evaluation_success') AS evaluation_success,
  json_extract(value, '$.raw_jsonl') AS raw_jsonl,
  json_extract(value, '$.resume_jsonl') AS resume_jsonl,
  json_extract(value, '$.note') AS note
FROM runs
ORDER BY classification, run;
