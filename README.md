# SciGame

SciGame is an interactive benchmark for scientific identification and discovery with active experimentation.

The evaluated **Player** proposes experiments and submits an executable predictor. Experimental truth is produced by a deterministic `WorldModel`. An optional Oracle LLM may present an already-authoritative observation, and an optional post-hoc Evaluator LLM may add non-gating diagnostics. Deterministic held-out evaluation remains authoritative.

## Repository layout

- `src/role_benchmark/`: benchmark protocol, case families, deterministic Oracle/evaluator, LLM adapters, and private evaluation service.
- `experiments/`: matrix runners, analysis utilities, provider bindings, and frozen experiment registrations.
- `examples/`: small runnable examples.
- `tests/`: deterministic test suite.

Generated runs, result tables, paper drafts, internal reports, and private case packs are intentionally not published in this repository.

## Requirements and test

Python 3.9 or newer; the package itself uses the standard library.

```bash
python3 -m pip install -e .
PYTHONPATH=src:. python3 -m unittest discover -s tests -v
```

The current published snapshot passes 545 tests.

## Run the benchmark

Inspect all available selectors and role-specific API options:

```bash
PYTHONPATH=src:. python3 -m experiments.run_case_matrix --help
```

Credentials should be supplied through separate environment variables:

```bash
export BENCH_PLAYER_API_KEY='...'
export BENCH_ORACLE_API_KEY='...'
export BENCH_EVALUATOR_API_KEY='...'
```

Example with three independently initialized OpenAI Responses backends:

```bash
PYTHONPATH=src:. python3 -m experiments.run_case_matrix \
  --case-pack curated \
  --oracle-mode llm_presentation \
  --player-provider openai \
  --player-model PLAYER_MODEL \
  --player-endpoint https://api.openai.com/v1/responses \
  --player-api-key-env BENCH_PLAYER_API_KEY \
  --oracle-provider openai \
  --oracle-model ORACLE_MODEL \
  --oracle-endpoint https://api.openai.com/v1/responses \
  --oracle-api-key-env BENCH_ORACLE_API_KEY \
  --evaluator-provider openai \
  --evaluator-model EVALUATOR_MODEL \
  --evaluator-endpoint https://api.openai.com/v1/responses \
  --evaluator-api-key-env BENCH_EVALUATOR_API_KEY \
  --player-prompt-version role_benchmark.player_prompt.v2_json_hardened \
  --oracle-prompt-version role_benchmark.oracle_prompt.v2_json_hardened \
  --evaluator-prompt-version role_benchmark.evaluator_prompt.v2_json_hardened \
  --experiment-id EXP-EXAMPLE-001 \
  --output-dir runs/EXP-EXAMPLE-001
```

Built-in transports are `openai` (Responses API) and `deepseek` (Chat Completions). A custom provider can implement the `TextGenerationBackend` contract.

Use `--dry-run` before a full matrix run. A deterministic Oracle does not require an Oracle API key; enable `--oracle-mode llm_presentation` only when the optional presentation model is part of the registered experiment.
