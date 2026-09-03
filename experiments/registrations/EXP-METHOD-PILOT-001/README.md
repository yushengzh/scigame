# EXP-METHOD-PILOT-001

This frozen development pilot tests the three evaluation methods; it is not a model capability evaluation. The authoritative configuration is [`registration.json`](registration.json). Temporal source dates and the rule for creating post-evaluation exposure records are in [`temporal_sources.json`](temporal_sources.json).

The primary configuration uses the deterministic Oracle. The `llm_presentation` Oracle remains available through the runner but is excluded here until its accuracy has been evaluated.

## Validate the frozen schedules

Run these commands from the repository root. `--dry-run` writes and validates the exact randomized schedule without reading credentials or calling an API.

```bash
PYTHONPATH=src:. python3 experiments/run_case_matrix.py \
  --output-dir /tmp/EXP-METHOD-PILOT-001-curated \
  --experiment-id EXP-METHOD-PILOT-001 \
  --case-pack curated \
  --family pendulum \
  --family young_double_slit \
  --family radioactive_decay \
  --family ohm_circuit \
  --family michaelis_menten \
  --family poiseuille_flow \
  --repeats 2 \
  --schedule-seed 20260825 \
  --oracle-mode deterministic \
  --player-provider deepseek \
  --player-model deepseek-v4-flash \
  --player-snapshot-id unknown \
  --player-thinking disabled \
  --evaluator-provider deepseek \
  --evaluator-model deepseek-v4-flash \
  --evaluator-snapshot-id unknown \
  --evaluator-thinking disabled \
  --dry-run

PYTHONPATH=src:. python3 experiments/run_case_matrix.py \
  --output-dir /tmp/EXP-METHOD-PILOT-001-temporal \
  --experiment-id EXP-METHOD-PILOT-001 \
  --case-pack temporal \
  --family kz_incompressible_energy_temperature_regimes \
  --family viscous_inertial_rheology \
  --family self_similar_spreading_radius_ratio \
  --repeats 2 \
  --schedule-seed 20260825 \
  --oracle-mode deterministic \
  --player-provider deepseek \
  --player-model deepseek-v4-flash \
  --player-snapshot-id unknown \
  --player-thinking disabled \
  --evaluator-provider deepseek \
  --evaluator-model deepseek-v4-flash \
  --evaluator-snapshot-id unknown \
  --evaluator-thinking disabled \
  --dry-run
```

For an actual development run, use a new empty output directory, remove `--dry-run`, and provide the Player and Evaluator credentials through their configured environment variables or interactive prompts. Do not change any registered argument. The deterministic Oracle does not require a credential.

The API alias in this registration has no immutable snapshot ID in the available records. Preserve all raw responses and report that limitation; do not interpret the Temporal results as evidence that the model had not encountered the source material.
