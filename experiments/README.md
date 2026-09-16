# Experiment entry points

## Current case-matrix runner

`run_case_matrix.py` runs public development cases with independently configured Player, Oracle, and post-hoc Evaluator roles. The packs are `historical` (20 families / 80 cases), `temporal` (30 / 120), and `both` (50 / 200). Each family contributes two conditions × identification/discovery.

`historical` selects the current Historical dataset with three-step structural counterfactuals. `both` includes exactly this Historical dataset plus Temporal. The name and [manifest path](../datasets/historical/manifest.json) stay fixed; Git records dataset evolution. Earlier Historical packs are retired, and older experiment outputs retain their original scientific meaning. See [Historical dataset](../docs/HISTORICAL_DATASET.md).

```text
episodes = cases × selected evaluation methods × repeats
```

The three methods are:

- `prior-only baseline`: no experimental observations;
- `fixed experimental design`: the family's predefined diagnostic observations;
- `adaptive experimental design`: Player-selected experiments, with no preset observation budget, until the public confidence stopping rule is met.

The methods share the final predictor representation and deterministic evaluation conditions. Fixed and adaptive currently have different stopping rules; their results must not be described as an equal-budget comparison.

Standard case-matrix runs automatically produce the current scientific post-evaluation:

- binary `active_pass = protocol_completion && evaluation_success`;
- normalized error;
- mathematical expression equivalence;
- expressed understanding before/after, and change when both endpoints are observable;
- F1–F5 multi-label failure distributions among failed episodes.

These measurements remain independent. The scientific Judge does not change the binary outcome. Missing evidence stays missing, and infrastructure failures are reported separately. Definitions and denominators are maintained in [Scientific post-evaluation](../docs/SCIENTIFIC_POSTEVALUATION.md).

## Plan and run

Validate the complete adaptive schedule without credentials or model calls:

```bash
PYTHONPATH=src:. python3 -m experiments.run_case_matrix \
  --case-pack both \
  --evaluation-method "adaptive experimental design" \
  --repeats 1 \
  --player-provider openai \
  --oracle-provider openai \
  --evaluator-provider openai \
  --output-dir runs/both_case_matrix_dry_run \
  --dry-run
```

This selects 200 episodes. For a real run, begin with one case and explicitly configure the model and credential for each used role:

```bash
PYTHONPATH=src:. python3 -m experiments.run_case_matrix \
  --case-pack temporal \
  --family temporal_source_007 \
  --condition source_reported \
  --task-setting identification \
  --evaluation-method "adaptive experimental design" \
  --repeats 1 \
  --oracle-mode llm_presentation \
  --player-provider openai \
  --player-model PLAYER_MODEL \
  --player-api-key-env BENCH_PLAYER_API_KEY \
  --oracle-provider openai \
  --oracle-model ORACLE_MODEL \
  --oracle-api-key-env BENCH_ORACLE_API_KEY \
  --evaluator-provider openai \
  --evaluator-model EVALUATOR_MODEL \
  --evaluator-api-key-env BENCH_EVALUATOR_API_KEY \
  --player-max-output-tokens 8192 \
  --oracle-max-output-tokens 8192 \
  --evaluator-max-output-tokens 8192 \
  --output-dir runs/three_llm_smoke \
  --dry-run
```

Replace the model placeholders with exact provider IDs. Inspect the plan, then remove `--dry-run` with the same settings to execute. Credentials are read from the named environment variables and are not written to run artifacts.

The current Player uses a strict structured action schema and does not regenerate malformed output. Player defaults to OpenAI; Oracle and Evaluator default to DeepSeek, so specify all used roles explicitly. The Oracle LLM presents observations computed by the case `WorldModel`; it does not generate experimental measurements. `--oracle-mode deterministic` omits the Oracle model call.

The [running guide](../docs/RUN_CASE_MATRIX.md) covers provider configuration, current command options, concurrency, and resume behavior. [IFM instructions](../docs/RUN_IFM_THREE_ROLE_BENCH.md) cover the IFM Platform binding.

## Scientific post-evaluation of existing runs

```bash
PYTHONPATH=src:. python3 -m experiments.postevaluate_science \
  --run-dir runs/existing_case_matrix \
  --output-dir runs/existing_scientific_postevaluation
```

This offline command computes available expression comparisons, reuses compatible scientific Judge outputs, and reports missing coverage. Add `--judge` and explicit Evaluator provider/model/credential options to fill missing Judge results. It supports standard case-matrix result directories and preserves the source outcomes and logs.

Completed Player episodes are reused during resume. Only missing or failed post-evaluation stages are retried; scientific failures are not rerun to obtain better scores. Requested and returned model identities, token usage, Judge output, and metric coverage remain inspectable in the run artifacts.

## Analysis and episode views

```bash
PYTHONPATH=src:. python3 -m experiments.analyze_case_matrix \
  runs/three_llm_smoke

PYTHONPATH=src:. python3 -m experiments.render_case_matrix \
  runs/three_llm_smoke/episodes.json \
  /tmp/scigame_episode_views
```

`scientific_postevaluation.json` reports the scientific dimensions and failure-label rates. The older `analyze_failure_modes.py` utility reports observable protocol/stage diagnostics; these are distinct from the F1–F5 scientific labels and do not replace them.

## Other entry points and registrations

- `run_pendulum_matrix.py` retains the separate pendulum validation experiment.
- `run_temporal_conversion.py` and `compare_temporal_conversion.py` support the registered temporal authoring conversion study.
- [EXP-TEMPORAL-AUTHORING-001](registrations/EXP-TEMPORAL-AUTHORING-001/) records the source cohort and comparison assumptions.
- [EXP-TEMPORAL-VALIDATION-002](registrations/EXP-TEMPORAL-VALIDATION-002/) records the temporal validation protocol.
- [EXP-METHOD-PILOT-001](registrations/EXP-METHOD-PILOT-001/) is archived. Its earlier case-pack commands are historical records, not current CLI examples.

Read each registration before using its dedicated entry point. Generated runs, local datasets, and unpublished manuscript results are not implied to be included or validated by this code release.
