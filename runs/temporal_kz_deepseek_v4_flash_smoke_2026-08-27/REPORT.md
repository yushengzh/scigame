# KZ temporal family · three-role DeepSeek smoke test

Date: 2026-08-27

This run is a connectivity and protocol smoke test, not a stable model estimate.
It executes one complete matched block:

```text
1 family × 2 worlds × 2 tracks × 1 observed repeat = 4 episodes
```

The frozen temporal plan contains five repeats (20 episodes), but only repeat 1
was selected. Player, Oracle presentation model, and post-hoc Evaluator were
three distinct DeepSeek clients using `deepseek-v4-flash`, thinking disabled,
temperature 0. Credentials were supplied only at runtime and are absent from
the artifacts.

## Outcome

| World | Track | Active category | Experiments completed | Deterministic result |
| --- | --- | --- | ---: | --- |
| counterfactual | identification | scientific failure | 5 | Submitted predictor failed held-out tests |
| counterfactual | discovery | player generation failure | 1 | No decodable final submission |
| historical | discovery | scientific failure | 6 | Submitted predictor failed held-out tests |
| historical | identification | player generation failure | 3 | No decodable final submission |

Summary: 0/4 active pass, 2 scientific failures, 2 Player generation failures,
0 infrastructure failures, and 4/4 completed post-hoc LLM evaluations.

The two scientific failures are substantive:

- Counterfactual identification submitted exponent `-0.5` and scale
  `12873.153`; private truth is exponent `-0.935` and scale `95430`. The Player
  had already observed five valid measurements.
- Historical discovery described the sequence as non-monotonic even though its
  own quoted measurements decrease from `2259.9` at `tau_q=100` to `1524.4` at
  `tau_q=150`. The submitted expression failed all held-out conditions.

The other two episodes are not evidence of scientific failure. They terminated
at the wire boundary with `number_precision_loss`: otherwise valid finite JSON
forecast decimals were rejected by the current exact decimal-to-binary64
round-trip policy, and the one allowed repair repeated the same decimals. This
protocol artifact must be resolved prospectively before the remaining repeats
are used for quantitative comparison.

## Execution checks

- All Player, Oracle, and Evaluator completions report provider `deepseek`,
  model `deepseek-v4-flash`, binding `case_matrix.deepseek_chat`, a non-empty
  response ID, and token usage.
- The four episodes contain 25 Player completions and 15 Oracle presentation
  completions; each episode has exactly one completed Evaluator call.
- All 15 numeric evidence records exactly equal the registered world formula at
  the requested `tau_q`. The Oracle LLM supplied only the natural-language
  presentation; it did not generate or alter measurement values.
- Each Evaluator request contains decoded actions, evidence-bearing protocol
  transitions, the terminal event, and trajectory scores identical to the
  deterministic result sidecar.

## Artifacts

- `config.json`: frozen non-secret run configuration and 20-episode temporal plan
- `episodes/*.jsonl`: replayable Player–Oracle event logs
- `results/*.result.json`: deterministic scientific and trajectory results
- `evaluations/*.evaluation.json`: post-hoc Evaluator requests, responses, and scores
- `episodes.json` / `episodes.csv`: joined summaries
- `failure_analysis/`: episode-level and aggregate failure-mode analysis

Dialogue visualization:

```text
/Users/yushengzh/Workspace/RL/historyllm/role_benchmark_visualizations/
temporal-kz-deepseek-v4-flash-smoke-2026-08-27/index.html
```
