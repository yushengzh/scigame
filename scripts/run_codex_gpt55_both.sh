#!/bin/bash
# Complete current Temporal33 + Historical20 matrix, one repeat.
set -euo pipefail
cd "$(dirname "$0")/.."
export PYTHONPATH=src:.
run_dir=runs/EXP-CODEX-GPT55-BOTH-R1-20260917
mkdir -p "$run_dir"
python3 -B -u -m experiments.run_case_matrix \
  --case-pack both --repeats 1 --schedule-seed 20260825 \
  --oracle-mode deterministic \
  --player-provider codex --player-model gpt-5.5 \
  --player-reasoning-effort high --player-timeout-s 900 \
  --evaluator-provider codex --evaluator-model gpt-5.5 \
  --evaluator-reasoning-effort high --evaluator-timeout-s 900 \
  --player-max-output-tokens 8192 --evaluator-max-output-tokens 8192 \
  --max-repair-attempts 0 --workers 32 \
  --experiment-id EXP-CODEX-GPT55-BOTH-R1-20260917 \
  --output-dir "$run_dir" "$@" 2>&1 | tee -a "$run_dir/console.log"
