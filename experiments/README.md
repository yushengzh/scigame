# Temporal authoring conversion study

`EXP-TEMPORAL-AUTHORING-001` registers the revised Temporal authoring pipeline. Temporal admission requires at least one source-supported executable quantitative relation. A second source-reported condition is optional. Counterfactual variants are constructed only by the separate counterfactual construction pipeline when explicitly requested.

The authoring model returns only a minimal ScienceCard containing `formula`, `parameters`, `controls`, `readouts`, `domain`, and `anchors`. Deterministic code generates the observation budget, diagnostic conditions, held-out conditions, public template, and provenance mapping.

The experiment reuses all 37 source packets from the two historical runs in their registered order. It does not reacquire or replace papers. The first 17 papers retain a maximum of two total ScienceCard calls per paper; the remaining 20 retain a maximum of four. The four registered paper-level rates all use 37 as their denominator:

- first-attempt structural validity;
- post-repair structural validity;
- source-review retention;
- final acceptance.

The protocol and exact source manifest are in [`registrations/EXP-TEMPORAL-AUTHORING-001/`](registrations/EXP-TEMPORAL-AUTHORING-001/). The historical descriptive values are 3/37 first-attempt valid, 13/37 valid after repair, 0/37 eligible at source review, and 0/37 finally accepted. Of the 13 structurally valid cards, the old paired-condition review requested revision for 6 and rejected 7. Revision-required cards are reported separately and are not counted as retained; the old decisions also cannot be retrospectively reclassified under the new admission rule.

The experiment is currently blocked and has not been run. The historical artifacts saved the mutable model alias `deepseek-v4-flash`, but not an immutable checkpoint or snapshot identifier, and the runtime credential is unavailable. Therefore a later run against the same alias would be descriptive only and could not identify a causal effect of the pipeline revision.

The following command validates the registration, all 37 paths, source order, and the 114-call upper bound without loading credentials or calling a provider:

```bash
PYTHONPATH=src:. python experiments/run_temporal_conversion.py \
  /tmp/temporal-authoring-dry-run \
  --registration experiments/registrations/EXP-TEMPORAL-AUTHORING-001/registration.json \
  --authoring-snapshot-id unknown \
  --dry-run
```

If the exact historical immutable snapshot becomes available and is callable by the provider, complete a documented pre-execution registration amendment before any model call: record the same snapshot in both snapshot fields, set the historical comparison status to `controlled`, set the experiment status to `ready_for_execution`, and commit that amendment. The runner sends the registered snapshot identifier as the provider's `model` value; the mutable alias is metadata only. Then run:

```bash
PYTHONPATH=src:. python experiments/run_temporal_conversion.py \
  runs/EXP-TEMPORAL-AUTHORING-001 \
  --registration experiments/registrations/EXP-TEMPORAL-AUTHORING-001/registration.json \
  --authoring-snapshot-id SNAPSHOT_ID
```

Do not use `unknown` for this registered controlled comparison. If only the model alias can be matched, create a separate registration for a descriptive replication. Never write the credential to repository artifacts.

After all independent source reviews and deterministic case validations are complete, generate the registered descriptive comparison with:

```bash
PYTHONPATH=src:. python experiments/compare_temporal_conversion.py \
  runs/EXP-TEMPORAL-AUTHORING-001
```

## Pendulum minimal validation

This directory runs one preregistered matrix:

```text
3 Player profiles x 2 worlds x 2 tracks x 5 repeats = 60 episodes
```

The three Player slots are:

| Profile | Base model | Thinking | Effort |
|---|---|---|---|
| `player_1` | `deepseek-v4-flash` | disabled | — |
| `player_2` | `deepseek-v4-flash` | disabled | — |
| `player_3` | `deepseek-v4-flash` | disabled | — |

Each slot loads its own provider backend object.  The three slots currently have
the same model and inference settings, so they are independently instantiated
replicate groups, **not three model treatments**.  A stateless hosted API cannot
guarantee three distinct server-side weight instances.  The loader boundary can
later bind each slot to a different local model or API without changing the case
or episode protocol.

The Oracle presentation backend is loaded separately and is fixed as
`deepseek-v4-flash` with thinking disabled.  Authoritative measurements still
come from the case WorldModel, not from the Oracle LLM.

The two worlds are `historical` and `counterfactual`; the two information
contracts are `identification` and `discovery`.  Player generation is fixed at
temperature 0, no client-side model seed is sent, and at most one fully logged
schema-directed regeneration is allowed per Player turn.  The five repeats
therefore measure provider-side stochastic variation.  Thinking is disabled for
all three Players, so the common output limit bounds visible JSON rather than an
unobserved and condition-dependent reasoning trace.

Execution uses a seeded randomized-complete-block schedule.  Each consecutive
12-episode block contains every `Player × world × track` cell exactly once, in a
seeded random order.  The default schedule seed is `20260824`; the seed and exact
60-episode order are frozen in `config.json`.  Formal execution is sequential so
the dispatch order equals the frozen order. Resume skips evaluated sidecars and
preserves the relative order of the remaining episodes; changing the seed causes
a config mismatch before any provider call.

All requests use Chat Completions JSON mode. Each episode has its own JSONL log.
`config.json`, `episodes.csv`, `episodes.json`, and per-episode result JSON files
are updated as episodes finish. Every Player terminal state consumes its formal
schedule position and has `status=evaluated`: `submitted`,
`player_output_invalid`, `action_rejected`, or `action_limit`. Only a submitted
outcome is scientifically evaluable. The summary category distinguishes
`pass`, `scientific_failure`, `player_generation_failure`, and
`player_protocol_failure`, while `termination_kind` preserves the exact stop.

A provider-transport, Oracle, evaluator, storage, or local runner failure has
`status=infrastructure_failed`, stops the run immediately, and is retried at the
same schedule index on resume. Its prior JSONL is retained and a replacement log
gets a `resume-N` suffix. This keeps Player failures in the full task denominator
without treating infrastructure downtime as model behavior.

Paid execution accepts only a continuous prefix of the currently remaining
frozen order.  For example, `--repeat 1` runs the first randomized 12-cell block.
A later invocation without selectors uses the same output directory, skips those
12 consumed positions, and fills the remaining 48 episodes.  Arbitrary
`--profile`, `--world`, or `--track` subsets are rejected unless they happen to
form that next prefix; this prevents a selector from silently destroying the
temporal randomization.  Selectors remain available for inspecting a dry-run.

Dry-run the plan without a credential:

```bash
PYTHONPATH=src python -m experiments.run_pendulum_matrix \
  --output-dir runs/pendulum-validation-20260825 \
  --dry-run
```

For a real run, prefer a process environment variable:

```bash
DEEPSEEK_API_KEY='...' PYTHONPATH=src \
python -m experiments.run_pendulum_matrix \
  --output-dir runs/pendulum-validation-20260825
```

Alternatively use `--prompt-api-key`, `--api-key-stdin`, or `--api-key`.  The
credential is used only in the HTTP Authorization header and is never written
to the config, logs, summaries, or result metadata.

The existing 2026-08-24 pilot under `runs/` remains a frozen development
artifact. Its raw outputs and sidecars are not rewritten into the current
terminal schema; a new run must use a fresh output directory.

## Cross-case three-LLM evaluation

`run_case_matrix.py` is the current cross-case runner. Its frozen development
schedule has 400 episodes: all 20 families contribute
`2 worlds × 2 tracks × 5 repeats`. Each repeat is a seeded, randomly ordered
complete block of 80 matched cells. Player, Oracle, and post-hoc Evaluator each
have independent provider/model/endpoint/credential/reasoning/timeout settings.
The Oracle LLM still does not create measurements: the private WorldModel
computes authoritative evidence and the Oracle model only presents it. The LLM
Evaluator is called after the episode JSONL is sealed and cannot change the
deterministic scientific score.

The Responses transport requests JSON-object output. The full benchmark action
schema remains in the prompt and the local strict decoder remains normative.
It is not sent as OpenAI strict Structured Outputs because the public action
contract intentionally contains dynamic control, forecast, and parameter keys
plus conditional and recursive expression structures outside that API's strict
schema subset. This preserves the same bench action contract instead of
weakening it for one provider.

Validate the complete schedule without a credential:

```bash
PYTHONPATH=src python -m experiments.run_case_matrix \
  --player-provider deepseek \
  --oracle-provider openai \
  --evaluator-provider openai \
  --output-dir runs/openai_gpt56_case_matrix_20260825 \
  --dry-run
```

Run with three independently injected runtime credentials:

```bash
PYTHONPATH=src python -m experiments.run_case_matrix \
  --player-provider deepseek \
  --player-model deepseek-v4-flash \
  --player-api-key-env BENCH_PLAYER_API_KEY \
  --oracle-provider openai \
  --oracle-model gpt-5.6 \
  --oracle-reasoning-effort none \
  --oracle-api-key-env BENCH_ORACLE_API_KEY \
  --evaluator-provider openai \
  --evaluator-model gpt-5.6 \
  --evaluator-reasoning-effort high \
  --evaluator-api-key-env BENCH_EVALUATOR_API_KEY \
  --output-dir runs/openai_gpt56_case_matrix_20260825
```

Then produce the aggregate scores, failure-mode tables, and one left/right
Player–Oracle page per canonical episode log:

```bash
PYTHONPATH=src python -m experiments.analyze_case_matrix \
  runs/openai_gpt56_case_matrix_20260825

PYTHONPATH=src python -m experiments.analyze_failure_modes \
  runs/openai_gpt56_case_matrix_20260825/episodes.json \
  runs/openai_gpt56_case_matrix_20260825/analysis/failure_modes

PYTHONPATH=src python -m experiments.render_case_matrix \
  runs/openai_gpt56_case_matrix_20260825/episodes.json \
  ../role_benchmark_visualizations/openai_gpt56_case_matrix_20260825
```

The requested model IDs, provider-returned IDs, response IDs and token usage are
recorded without credentials. Evaluator request/response/decoded output is kept
under `evaluations/`; evaluator failure preserves the completed active episode
and resume retries only the evaluator. Full parameter and scoring semantics are
documented in [`docs/THREE_LLM_EVALUATION.md`](../docs/THREE_LLM_EVALUATION.md).

## Failure-mode analysis

After a completed run, analyze every episode without changing its frozen
primary result:

```bash
PYTHONPATH=src python -m experiments.analyze_failure_modes \
  runs/completed-run/episodes.json \
  runs/completed-run/analysis/failure_modes
```

The output contains one episode-grain JSON record, one compact CSV row per
episode, stage/code occurrence counts, distinct episode counts per mode, and
diagnostic coverage denominators. Failed episodes distinguish terminal failure
from the earliest observable misstep and cite exact action/turn and JSONL event
locations. Recovered format incidents remain separate from failures. The
analysis is diagnostic and never changes `predictive_model_pass`.
