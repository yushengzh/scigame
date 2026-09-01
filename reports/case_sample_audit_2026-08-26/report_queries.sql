-- Reviewed audit datasets used by the portable report.
-- Primary inputs:
--   runs/deepseek_20_family_80_20260825/episodes.json
--   runs/deepseek_20_family_80_20260825/episodes/*.jsonl
--   src/role_benchmark/cases/*.py
--
-- Funnel counts. "scientific_evaluator_input" means a protocol-valid final
-- submission reached the case-specific evaluator.
WITH funnel(stage_order, stage, episode_count) AS (
  VALUES
    (1, 'terminal outcome recorded', 80),
    (2, 'scientific evaluator input', 50),
    (3, 'scientific pass', 21)
)
SELECT stage_order, stage, episode_count
FROM funnel
ORDER BY stage_order;

-- Why 30 terminal outcomes did not reach the case-specific evaluator.
WITH reasons(reason, episode_count) AS (
  VALUES
    ('invalid_json', 14),
    ('model_invariant', 5),
    ('duplicate_key', 1),
    ('final_confidence_mismatch', 9),
    ('experiment_budget_exhausted', 1)
)
SELECT reason, episode_count
FROM reasons
ORDER BY episode_count DESC, reason;

-- Result categories for the full 80-cell smoke denominator.
WITH outcomes(category, episode_count) AS (
  VALUES
    ('pass', 21),
    ('scientific_failure', 29),
    ('player_generation_failure', 20),
    ('player_protocol_failure', 10)
)
SELECT category, episode_count
FROM outcomes
ORDER BY episode_count DESC, category;

-- Exact reviewed rows embedded in the canonical report artifact. The artifact
-- is produced by build_report_artifact.py directly from the primary files
-- listed above; these DuckDB queries expose each table at its reported grain.
SELECT item.*
FROM read_json_auto(
  'reports/case_sample_audit_2026-08-26/artifact.json'
) AS report,
UNNEST(report.snapshot.datasets.case_audit) AS rows(item)
ORDER BY priority, family;

SELECT item.*
FROM read_json_auto(
  'reports/case_sample_audit_2026-08-26/artifact.json'
) AS report,
UNNEST(report.snapshot.datasets.version_drift) AS rows(item)
ORDER BY changed_cells DESC, family;

SELECT item.*
FROM read_json_auto(
  'reports/case_sample_audit_2026-08-26/artifact.json'
) AS report,
UNNEST(report.snapshot.datasets.cell_breakdown) AS rows(item)
ORDER BY active_pass DESC, world, track;

SELECT item.*
FROM read_json_auto(
  'reports/case_sample_audit_2026-08-26/artifact.json'
) AS report,
UNNEST(report.snapshot.datasets.no_science_detail) AS rows(item)
ORDER BY schedule_index;
