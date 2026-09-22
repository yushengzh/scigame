# SciGame

SciGame is an interactive benchmark for scientific identification and discovery through experimentation. The **Player** proposes experiments, revises explicit scientific hypotheses, and submits an executable predictor with an explanation. A deterministic `WorldModel` supplies measurements for legal experiments.

The binary episode outcome is `active_pass = protocol_completion && evaluation_success`. Independent metrics report normalized prediction error, mathematical expression equivalence, and expressed scientific understanding before and after interaction. Failed episodes receive F1–F5 scientific failure labels where the evidence supports them. By default, the runner calls the scientific Judge after each episode. Add `--defer-evaluator` to collect benchmark results first and run the LLM Judge separately later. These metrics are not combined into a weighted score, and the Judge cannot change the binary outcome. See [Scientific post-evaluation](docs/SCIENTIFIC_POSTEVALUATION.md) for definitions and coverage limits.

## Player, Oracle, and Evaluator

| Component | Implementation | Responsibility |
| --- | --- | --- |
| Player | LLM in the experiment runners | Propose experiments, revise hypotheses, and submit a predictor and explanation |
| Oracle | Deterministic by default | Validate experimental controls and return measurements computed by the private `WorldModel` |
| Case evaluator | Deterministic code | Score the submitted predictor against held-out conditions and determine scientific success |
| Post-hoc Evaluator / Judge | LLM, immediately or in a separate later run | Assess expressed scientific understanding from the transcript and an active-world reference |

The Oracle has three modes. `deterministic` makes no Oracle model calls. `llm_presentation` calls a model but requires an exact copy of the authoritative feedback. `llm_semantic` adds an LLM legality review after hard validation. In every mode, experimental measurements come from the deterministic world model. Player, optional LLM Oracle, and post-hoc Evaluator can use independently configured models.

## Repository layout

- `src/role_benchmark/`: benchmark protocol, case families, deterministic Oracle/evaluator, LLM adapters, and private evaluation service.
- `experiments/`: matrix runners, analysis utilities, provider bindings, and experiment registrations.
- `datasets/`: dataset manifests and the shared fixed-observation design.
- `docs/`: current scientific evaluation and running guides.
- `examples/`: small runnable examples.
- `tests/`: automated tests.

Generated runs, result tables, paper drafts, internal reports, and private case packs are intentionally not published in this repository. The published cases and their scoring functions are public development data; the presence of a private evaluation service does not make them private test data.

## Requirements

Python 3.9 or newer; the package itself uses the standard library.

```bash
python3 -m pip install -e .
```

Run commands from the repository root. The fixed-design loader reads [`datasets/fixed_budget_design.json`](datasets/fixed_budget_design.json) from the checkout, so use this editable installation. A standalone wheel currently omits that required file.

## Run the benchmark

Inspect available selectors and role-specific API options:

```bash
PYTHONPATH=src:. python3 -m experiments.run_case_matrix --help
```

The development packs are `historical` (20 families / 80 cases), `temporal` (33 / 132), and `both` (53 / 212). Each family contains two conditions and two task settings, Identification and Discovery. Run size is `cases × selected evaluation methods × repeats`.

Both datasets use stable names and one current definition:

| Pack | Scientific content | Dataset guide and manifest |
| --- | --- | --- |
| `historical` | 20 classical scientific idealizations, each paired with a three-step structural counterfactual | [Guide](docs/HISTORICAL_DATASET.md), [manifest](datasets/historical/manifest.json) |
| `temporal` | 33 relations from 32 source papers, each paired with an authored counterfactual | [Guide](docs/TEMPORAL_DATASET.md), [manifest](datasets/temporal/manifest.json) |
| `both` | The current Historical and Temporal datasets together | 53 families / 212 cases |

Each pack uses `--variant canonical`. Historical conditions are `historical` / `counterfactual`; Temporal conditions are `source_reported` / `counterfactual`. All current Temporal families have an authored counterfactual; the earlier public Temporal mixture of source A/B pairs and parameter twins is retired. Earlier results retain their original dataset definitions and cannot become current results by renaming them.

Dataset changes are recorded in Git, without numbered dataset names or selectable older packs. Scientific cards ship with the Python package, so running cases does not require downloading the source papers. These are executable, source-grounded worlds. Some source papers have preprints from before 2026; the pack is not a claim that all 33 relations first appeared in 2026. Publication dates do not establish that a model has never encountered their scientific relations.

### Evaluation methods and run size

The main runner selects **five methods** when `--evaluation-method` is omitted:

| Exact method name | Observations |
| --- | --- |
| `prior-only baseline` | No experimental observations |
| `fixed experimental design (2 observations)` | First 2 observations from the fixed design |
| `fixed experimental design (4 observations)` | First 4 observations from the same design |
| `fixed experimental design (8 observations)` | All 8 observations from the same design |
| `adaptive experimental design` | Player-selected experiments with no preset observation budget, until confidence reaches or exceeds the public threshold |

Fixed methods receive their observations before final submission. Their ordered, nested control sequences are recorded in [`fixed_budget_design.json`](datasets/fixed_budget_design.json). Fixed and adaptive methods have different stopping rules; this is not an equal-budget comparison. Confidence determines when to stop, while the case evaluator determines whether the predictor is correct.

| Pack | All five methods, one repeat | Discovery only, all five methods, one repeat |
| --- | ---: | ---: |
| `historical` | 400 episodes | 200 episodes |
| `temporal` | 660 episodes | 330 episodes |
| `both` | 1,060 episodes | 530 episodes |

The default is **five repeats**, so an unfiltered `both` run has 5,300 episodes. Set `--repeats 1` for an initial run. Repeat `--evaluation-method` to choose a subset; use the exact names above. A three-method comparison of prior-only, fixed-4, and adaptive must select those three explicitly.

### Collect benchmark results, then run the Judge

First plan one case with `--defer-evaluator`. This saves the benchmark trajectory, deterministic outcome, and offline formula comparison when executed, without configuring or calling an LLM Evaluator. The following `--dry-run` makes no API calls:

```bash
PYTHONPATH=src:. python3 -m experiments.run_case_matrix \
  --case-pack historical \
  --family pendulum \
  --condition historical \
  --task-setting discovery \
  --evaluation-method "prior-only baseline" \
  --repeats 1 \
  --oracle-mode deterministic \
  --player-provider openai \
  --player-model PLAYER_MODEL \
  --player-api-key-env BENCH_PLAYER_API_KEY \
  --defer-evaluator \
  --experiment-id EXP-EXAMPLE-001 \
  --output-dir runs/EXP-EXAMPLE-001 \
  --dry-run
```

Replace `PLAYER_MODEL` with an exact provider model ID, set `BENCH_PLAYER_API_KEY` in the environment, and remove `--dry-run` to collect the result. The deterministic Oracle needs no API key. Deferred collection needs no Evaluator model, endpoint, credential, or backend. Its Judge status is `deferred` and `metrics_complete=false` intentionally; the deterministic episode result remains available. `--defer-evaluator` defaults to false, so omitting it retains immediate evaluation.

After collecting the desired runs, configure the Evaluator and judge the saved record in a separate output directory:

```bash
PYTHONPATH=src:. python3 -m experiments.postevaluate_science \
  --run-dir runs/EXP-EXAMPLE-001 \
  --output-dir runs/EXP-EXAMPLE-001-postevaluation \
  --judge \
  --evaluator-provider openai \
  --evaluator-model EVALUATOR_MODEL \
  --evaluator-api-key-env BENCH_EVALUATOR_API_KEY \
  --evaluator-max-output-tokens 8192
```

Replace `EVALUATOR_MODEL` and set `BENCH_EVALUATOR_API_KEY` before this second step. It calls only the Judge, preserves the source results and logs, and reuses compatible completed assessments when resumed. No Player or Oracle episode is replayed. Use the same compatible code and scientific dataset snapshot for collection and post-evaluation.

Deferred collection supports serial and parallel runs (`--workers`); resume collection with the same command, including `--defer-evaluator`. Each source run needs its own post-evaluation directory. A [batch example](docs/SCIENTIFIC_POSTEVALUATION.md#5-已有结果独立补评) processes several collected runs after collection finishes.

### API configuration

The standard entry point is `experiments.run_case_matrix`, configured with API credentials, exact model IDs, and complete request endpoints. It runs independently of the Codex desktop app. The two steps above use the OpenAI Responses API for Player and Evaluator separately; they may use the same API account or different accounts.

| Provider | API contract | Current structured Player support |
| --- | --- | --- |
| `openai` | Responses API | Yes, native recursive JSON Schema |
| `ifm` | Chat Completions, IFM Platform mode | Yes, native JSON Schema and local validation |
| `deepseek` | Chat Completions | Oracle / Evaluator only with the current Player protocol |
| `gemini` | Native `generateContent` | Oracle / Evaluator only with the current Player protocol |

Configure each used role with the same argument pattern, replacing `ROLE` with `player`, `evaluator`, or `oracle`:

| Argument | Meaning |
| --- | --- |
| `--ROLE-provider` | Select the API adapter from the table above |
| `--ROLE-model` | Exact model ID accepted by that service |
| `--ROLE-api-key-env` | Name of the environment variable containing the API key |
| `--ROLE-endpoint` | Optional complete request URL, including `/v1/responses`, `/chat/completions`, or the native method path |
| `--ROLE-max-output-tokens` | Per-call output limit sent through the selected API adapter |
| `--ROLE-timeout-s` | Per-call timeout; defaults to 120 seconds |

Set `BENCH_PLAYER_API_KEY` for collection and `BENCH_EVALUATOR_API_KEY` for the later Judge. Credentials are read independently for each used role. The deterministic Oracle needs no credentials. Model names and endpoint URLs are CLI settings; they are not inferred from arbitrary `MODEL` or `BASE_URL` environment variables. For immediate evaluation, omit `--defer-evaluator` and pass the Evaluator settings to `run_case_matrix` alongside the Player settings.

An endpoint override must implement the selected adapter's complete request and response contract. A service that advertises OpenAI compatibility may support only Chat Completions, which cannot be used through the `openai` Responses adapter. The Player also requires native recursive structured output; JSON-only prompting is insufficient. The runner defaults to OpenAI for Player and DeepSeek for Evaluator, so explicitly select providers in reproducible commands.

For active experiments, three-role configurations, concurrency, and resume behavior, see the [case-matrix running guide](docs/RUN_CASE_MATRIX.md) and [IFM running guide](docs/RUN_IFM_THREE_ROLE_BENCH.md). Experiment entry points are summarized in [experiments/README.md](experiments/README.md).

## Add scientific metrics to existing results

```bash
PYTHONPATH=src:. python3 -m experiments.postevaluate_science \
  --run-dir runs/existing_case_matrix \
  --output-dir runs/existing_scientific_postevaluation
```

This computes the available offline metrics and reuses compatible Judge results without rerunning Player or Oracle. Missing measurements remain missing. Add `--judge` with explicit Evaluator settings to generate missing scientific assessments. The source run remains unchanged; see the [post-evaluation guide](docs/SCIENTIFIC_POSTEVALUATION.md).

Both immediate and deferred standard matrix results use this post-evaluation command. Specialized experiment drivers have their own scheduling and resume rules; see the [experiment entry points](experiments/README.md).

## Optional local adapter

`--ROLE-provider codex` is available for local experiments using an existing Codex login. It has separate runtime requirements and does not enforce the same generation controls as the API adapters. See the [optional Codex configuration](experiments/README.md#optional-local-codex-adapter).

## Tests

```bash
PYTHONPATH=src:. python3 -m unittest discover -s tests
```

The full suite currently has unresolved failures, including assertions for older budget and confidence rules and tests that depend on unpublished fixtures. Local HTTP tests also require permission to bind a loopback port. A full test run should not be assumed to pass on this snapshot.
