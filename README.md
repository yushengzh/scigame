# SciGame

SciGame is an interactive benchmark for scientific identification and discovery through experimentation. The **Player** proposes experiments, revises explicit scientific hypotheses, and submits an executable predictor with an explanation. A deterministic `WorldModel` supplies measurements for legal experiments.

Standard case-matrix runs use one current scientific post-evaluation flow. The binary episode outcome remains `active_pass = protocol_completion && evaluation_success`. Independent metrics report normalized prediction error, mathematical expression equivalence, and expressed scientific understanding before and after interaction. Failed episodes receive F1–F5 scientific failure labels where the evidence supports them. These metrics are not combined into a weighted score, and the post-hoc Judge cannot change the binary outcome. See [Scientific post-evaluation](docs/SCIENTIFIC_POSTEVALUATION.md) for definitions and coverage limits.

## Repository layout

- `src/role_benchmark/`: benchmark protocol, case families, deterministic Oracle/evaluator, LLM adapters, and private evaluation service.
- `experiments/`: matrix runners, analysis utilities, provider bindings, and experiment registrations.
- `docs/`: current scientific evaluation and running guides.
- `examples/`: small runnable examples.
- `tests/`: automated tests.

Generated runs, result tables, paper drafts, internal reports, and private case packs are intentionally not published in this repository. The published cases and their scoring functions are public development data; the presence of a private evaluation service does not make them private test data.

## Requirements

Python 3.9 or newer; the package itself uses the standard library.

```bash
python3 -m pip install -e .
```

## Run the benchmark

Inspect available selectors and role-specific API options:

```bash
PYTHONPATH=src:. python3 -m experiments.run_case_matrix --help
```

The main development packs are `historical` (20 families / 80 cases), `temporal` (30 / 120), and `both` (50 / 200). Each family contains two conditions and two task settings. Run size is `cases × selected evaluation methods × repeats`; `--help` lists additional registered packs and selectors.

Start with a one-case plan that makes no API calls:

```bash
PYTHONPATH=src:. python3 -m experiments.run_case_matrix \
  --case-pack historical \
  --family pendulum \
  --condition historical \
  --task-setting discovery \
  --evaluation-method "prior-only baseline" \
  --repeats 1 \
  --player-provider openai \
  --player-model PLAYER_MODEL \
  --player-api-key-env BENCH_PLAYER_API_KEY \
  --evaluator-provider openai \
  --evaluator-model EVALUATOR_MODEL \
  --evaluator-api-key-env BENCH_EVALUATOR_API_KEY \
  --evaluator-max-output-tokens 8192 \
  --experiment-id EXP-EXAMPLE-001 \
  --output-dir runs/EXP-EXAMPLE-001 \
  --dry-run
```

Use exact provider model IDs in place of `PLAYER_MODEL` and `EVALUATOR_MODEL`. After inspecting the plan, supply the corresponding environment variables and remove `--dry-run` to execute it. The deterministic Oracle needs no API key. Player and Evaluator use the current prompts automatically; no metric-version selector is required.

The runner supports `openai` (Responses API), `deepseek` and `ifm` (Chat Completions), and `gemini` (native `generateContent`). The current Player requires a backend that enforces its structured action schema; the OpenAI and IFM Platform bindings provide this capability. Oracle and Evaluator have independent model and credential settings.

For active experiments, three-role configurations, concurrency, and resume behavior, see the [case-matrix running guide](docs/RUN_CASE_MATRIX.md) and [IFM running guide](docs/RUN_IFM_THREE_ROLE_BENCH.md). Experiment entry points are summarized in [experiments/README.md](experiments/README.md).

## Add scientific metrics to existing results

```bash
PYTHONPATH=src:. python3 -m experiments.postevaluate_science \
  --run-dir runs/existing_case_matrix \
  --output-dir runs/existing_scientific_postevaluation
```

This computes the available offline metrics and reuses compatible Judge results without rerunning Player or Oracle. Missing measurements remain missing. Add `--judge` with explicit Evaluator settings to generate missing scientific assessments. The source run remains unchanged; see the [post-evaluation guide](docs/SCIENTIFIC_POSTEVALUATION.md).
