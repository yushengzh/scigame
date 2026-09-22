# Experiment entry points

## Current case-matrix runner

`run_case_matrix.py` runs public development cases with independently configured Player, Oracle, and post-hoc Evaluator roles. The packs are `historical` (20 families / 80 cases), `temporal` (33 / 132), and `both` (53 / 212). Each family contributes two conditions × identification/discovery.

`historical` selects twenty classical relations with three-step structural counterfactuals. `temporal` selects 33 relations from 32 papers, each with an authored counterfactual. `both` includes exactly these two current datasets. Both use variant `canonical`. Historical conditions are `historical` / `counterfactual`; Temporal conditions are `source_reported` / `counterfactual`.

Names and manifest paths stay fixed: [Historical manifest](../datasets/historical/manifest.json), [Temporal manifest](../datasets/temporal/manifest.json). Git records their evolution. Earlier datasets are retired; the old public Temporal mixture of source A/B pairs and parameter twins is not the current 33-family dataset. Older experiment outputs retain their original scientific meaning. See [Historical dataset](../docs/HISTORICAL_DATASET.md) and [Temporal dataset](../docs/TEMPORAL_DATASET.md).

```text
episodes = cases × selected evaluation methods × repeats
```

With all five methods and one repeat, Historical contains 400 episodes, Temporal contains 660, and `both` contains 1,060. Selecting only Discovery gives 200, 330, and 530 episodes, respectively. The default is five repeats, so unfiltered `both` selects 5,300 episodes.

The five methods selected by default are:

- `prior-only baseline`: no experimental observations;
- `fixed experimental design (2 observations)`: the first two observations from the shared fixed design;
- `fixed experimental design (4 observations)`: the first four observations;
- `fixed experimental design (8 observations)`: all eight observations;
- `adaptive experimental design`: Player-selected experiments, with no preset observation budget, until the selected confidence reaches or exceeds the public threshold.

Use these exact names with repeated `--evaluation-method` arguments. The older bare `fixed experimental design` label is not a current matrix CLI choice. Fixed sequences are stored in [`datasets/fixed_budget_design.json`](../datasets/fixed_budget_design.json).

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

This selects 212 episodes. For a real run, begin with one case and explicitly configure the model and credential for each used role:

```bash
PYTHONPATH=src:. python3 -m experiments.run_case_matrix \
  --case-pack temporal \
  --family defect_sre \
  --variant canonical \
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

The current Player uses a strict structured action schema and does not regenerate malformed output. Player defaults to OpenAI; Oracle and Evaluator provider settings default to DeepSeek, so specify all used roles explicitly. Oracle mode defaults to `deterministic`, which makes no Oracle model calls. `llm_presentation` requires the model to copy authoritative feedback; `llm_semantic` adds an LLM legality review. Measurements always come from the case `WorldModel`. The case evaluator computes scientific success, while the separate LLM Evaluator assesses the recorded scientific explanation.

The standard integration is API-based. Each used role takes a provider, exact model ID, API-key environment-variable name, and optional complete request endpoint. Player currently requires the OpenAI Responses or IFM Platform native structured-output binding. Oracle and Evaluator can also use DeepSeek or Gemini. See the [API configuration reference](../README.md#api-configuration).

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

- `run_codex_dataset_benchmark.py` runs fresh Player trials with a deterministic Oracle and deferred Judge. `--profile main3` selects prior-only, fixed-4, and adaptive; `--profile five` selects all five methods. Existing attempts are sealed and resume schedules only never-attempted episodes. Configure `--model` and `--output-dir` explicitly; defaults are three repeats and 16 workers.
- `run_astra_postevaluation.py` runs the separate Codex Judge over an existing prepared post-evaluation directory. Inspect `--help` for retry and resume options.
- `run_semantic_ablation.py` runs the semantic-information ablation study; `analyze_semantic_ablation.py` analyzes its results.
- `report_codex_benchmark.py` and `compare_codex_models.py` summarize recorded Codex experiment outcomes.
- `recover_codex_failed.py`, `resume_codex_long_output.py`, and `retry_codex_remaining_judge.py` are recovery tools for a specific recorded experiment. Their frozen identifiers and assumptions are not a general resume interface.
- `run_pendulum_matrix.py` retains the separate pendulum validation experiment.
- `run_temporal_conversion.py` and `compare_temporal_conversion.py` support the registered temporal authoring conversion study.
- [EXP-TEMPORAL-AUTHORING-001](registrations/EXP-TEMPORAL-AUTHORING-001/) records the source cohort and comparison assumptions.
- [EXP-TEMPORAL-VALIDATION-002](registrations/EXP-TEMPORAL-VALIDATION-002/) records the temporal validation protocol.
- [EXP-METHOD-PILOT-001](registrations/EXP-METHOD-PILOT-001/) is archived. Its earlier case-pack commands are historical records, not current CLI examples.

Read each registration before using its dedicated entry point. Generated runs, local datasets, and unpublished manuscript results are not implied to be included or validated by this code release.

## Optional local Codex adapter

All roles also accept `--ROLE-provider codex` through the local app-server binding. This requires `codex` on `PATH` and an existing ChatGPT login; API-key arguments are rejected. Each call creates a fresh isolated, tool-free session with native structured output.

The adapter permits `gpt-5.5`, `gpt-5.6-sol`, and `gpt-6-astra`, with effort `low`, `medium`, `high`, or `xhigh`. Availability depends on the local account and runtime. Temperature, top-p, seed, and output-token-limit controls are recorded as unavailable. These local sessions should not be assumed to share the API adapters' generation settings.
