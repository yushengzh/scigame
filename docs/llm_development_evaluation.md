# LLM development evaluation loop

This document defines the runnable development profile implemented by
`role_benchmark.llm`, `role_benchmark.wire`, and `role_benchmark.runlog`.
It does not weaken the formal isolation requirements in
[`evaluation_policy.md`](evaluation_policy.md).

## 1. Scope and claim boundary

The loop answers one narrow question:

> Can a specific model + provider binding + prompt + parser/second-generation
> policy drive the public Player protocol on a transparent identification or
> discovery fixture, with a recorded parse path and checkable supplied-runtime
> behavior?

Every run is labelled:

```text
evaluation_profile = public_development_fixture
track = identification | discovery
```

It is suitable for integration testing, prompt/protocol iteration, and pilot
comparisons. It is not a formal private evaluation or discovery result. Current
truth, evaluator, and held-out conditions remain in the public source tree.

The implementation follows the minimum sufficient design:

```text
EpisodeView
    -> canonical public JSON + strict action schema
    -> provider-neutral text generation call
    -> in-limit raw response recorded (oversized output: size only)
    -> strict PlayerAction decode (no second generation by default)
    -> existing Episode / Oracle / evaluator
    -> structured terminal outcome + plain JSONL event log
```

When `oracle_backend` is supplied, each experiment additionally follows one
minimal presentation step:

```text
CaseOracle / WorldModel -> authoritative status + evidence
                         -> Oracle LLM returns only {"message": "..."}
                         -> combined OracleResponse enters EpisodeView
```

The Oracle LLM cannot replace status, measurements, units, uncertainty, or
budget semantics.

There is no hidden planner, tool use, best-of-N selection, semantic correction,
formula fitter, LLM judge, or transcript summarizer.

## 2. Provider-neutral binding

A provider binding implements one method:

```python
from role_benchmark import (
    GenerationResponse,
    TextGenerationBackend,
    TokenUsage,
)


class MyProviderBinding(TextGenerationBackend):
    def generate(self, request):
        # Map request.messages, request.response_schema, and request.config to
        # the selected provider SDK. Do not add unrecorded prompts or tools.
        provider_result = call_provider(...)
        return GenerationResponse(
            text=provider_result.assistant_text,
            provider="provider-name",
            model=provider_result.returned_model,
            finish_reason=provider_result.finish_reason,
            response_id=provider_result.request_id,
            usage=TokenUsage(
                input_tokens=provider_result.input_tokens,
                output_tokens=provider_result.output_tokens,
            ),
            metadata={
                "binding_id": "my-binding",
                "structured_output_transport": False,
            },
        )
```

`GenerationRequest` contains:

- two logical messages: a fixed system instruction and the complete
  canonical `EpisodeView`;
- the full public JSON Schema for one action;
- `max_output_tokens`, temperature, top-p, and optional seed;
- schema, case, track, purpose, and Player-turn metadata.

The binding must record the actual returned provider/model identity. If it maps
roles, enables provider-native structured output, retries transport failures, or
adds provider options, that policy belongs in response/run metadata. API keys,
Authorization headers, and cookies must never enter metadata.

A deployment may bind both interactive roles to the same provider and model
ID. That does not merge their contexts. The Player call receives the public
`EpisodeView`. The implemented `LLMOracle` first asks `CaseOracle` for the
authoritative response, then gives the Oracle LLM only the public case,
proposal, and that response; its strict output contains only `message`.
Evidence values, units, uncertainty, status, and budget behavior never come
from the language model. The model name alone therefore never makes an Oracle
response based on the benchmark simulator.

The baseline transport is text in/text out with
`structured_output_transport=False` and no format-regeneration call. Function
calling, provider-native structured output, tools, streaming, memory, multimodal
input, fallback models, and provider-specific prompt tuning are different agent
profiles and must not be silently mixed with baseline runs.

## 3. Strict action wire schema

The current wire contract uses one stable set of identifiers:

```text
role_benchmark.episode_view
role_benchmark.player_action
```

Every action has exactly five top-level fields:

```json
{
  "wire_schema": "role_benchmark.player_action",
  "kind": "experiment",
  "portfolio": {"hypotheses": [
    {"hypothesis_id": "H1", "statement": "At fixed mass and small angle, pendulum period is proportional to length^0.5.", "confidence": 0.5},
    {"hypothesis_id": "H2", "statement": "At fixed mass and small angle, pendulum period is proportional to length^1.0.", "confidence": 0.5}
  ]},
  "experiment": {
    "intent": "Distinguish H1 from H2 by measuring period at a new length.",
    "apparatus": "simple_pendulum",
    "controls": {"length_m": 1.0, "bob_mass_kg": 0.2, "release_angle_deg": 5.0},
    "readouts": ["period_s"],
    "replicates": 5,
    "forecasts": {
      "H1": {"period_s": 2.01},
      "H2": {"period_s": 2.84}
    }
  },
  "final": null
}
```

For a final action, `experiment` is `null` and `final` is the complete object.
Both branch fields are always present, producing one canonical shape. For an
experiment, forecast keys must exactly equal the current hypothesis IDs, and
each hypothesis must predict every requested readout before evidence is returned.

The decoder rejects:

- Markdown fences, comments, trailing commas, multiple JSON values, or invalid
  UTF-8/JSON;
- duplicate keys at any nesting level;
- missing or unknown fields on closed objects;
- a wrong schema identifier, action kind, branch, or field type;
- `NaN`, Infinity, overflowed exponents, unsafe integers, excessive size/depth,
  and booleans used as numbers;
- invalid experiment-portfolio invariants such as fewer than two hypotheses, a
  reserved residual-bucket ID, duplicate IDs, or non-normalized confidence;
  final portfolios may contain one hypothesis. Empty required text and an
  invalid final model/parameters object remain hard decode failures.

The supplied JSON Schema is a provider-facing structural hint. The strict Python
decoder is normative: it additionally enforces lexical binary64 safety and
cross-field/model invariants that the schema cannot fully express. For experiment
actions these include unique hypothesis IDs and confidence normalization; for a
final action the same portfolio inconsistencies are retained as protocol
violations so a strictly decoded scientific model is still scored. A binding must state
whether the provider merely receives this schema as prompt data or applies a
provider-specific structured-output dialect.

The prompt and protocol require every hypothesis statement to be concrete and
testable. The decoder can enforce count, non-empty text, IDs, and confidence
normalization, but it cannot infer scientific testability from prose; that
observable quality belongs in transcript-aware process evaluation rather than a
claimed syntactic guarantee.

The decoder deliberately accepts schema-valid but scientifically/resource-invalid
experiments. Unknown instruments, missing controls, empty readouts, out-of-range
values, and invalid replicate counts go to `CaseOracle`, preserving the
existing clarification and experiment-budget semantics. It does not test an
action against Oracle for free.

## 4. Second-generation and accounting semantics

The baseline sets `max_repair_attempts=0`. It records the primary raw output,
strictly decodes it, and produces a `player_output_invalid` terminal outcome on
`WireDecodeError`. The adapter does not invent defaults or edit the model's
action.

An experiment may explicitly enable one schema-directed format-regeneration
call. On a primary decode failure, the runner sends the same complete view, the
raw output, and the public error code/path/message to the same backend, then
records and strictly decodes the new output. Despite the historical API name
`repair`, this is a second model generation. It can change the experiment,
hypotheses, confidence, formula, or final/experiment branch; an instruction to
preserve intent cannot guarantee semantic preservation.

Failures caused by action size, nesting, node-count, or invalid-Unicode safety
limits never trigger a second generation; the invalid text is not amplified
into another prompt.

Therefore the auto-recorded `generation_policy` values define separate strata
and their results must not be pooled:

- `plain_text_no_regeneration` (baseline);
- `plain_text_one_schema_directed_regeneration` (optional second generation);
- any provider-native structured-output transport (a separate transport
  profile, with its second-generation policy stated independently).

Post-processing remains intentionally minimal: the adapter either decodes an
entire action or rejects it. It does not normalize beliefs, fill controls, alter
formulae, query Oracle, or select among candidate outputs.

Two protocol budgets and inference accounting remain separate:

- experiment budget: only decoded experiments entering Oracle follow case rules;
- Player action budget: every primary `next_action` decision, including final;
- inference accounting: logical primary/second-generation calls and
  provider-reported tokens are recorded by the runner. Provider-internal
  retries, latency, and cost are not inferred; a binding must record them if a
  comparison depends on them.

A second generation consumes one logical inference call but no experiment and
no extra Player action. First-pass validity and validity after the optional
second generation must be reported separately.

## 5. Running one development episode

```python
from role_benchmark import GenerationConfig, run_llm_episode
from role_benchmark.cases import make_pendulum_case

binding = MyProviderBinding()
run = run_llm_episode(
    binding,
    make_pendulum_case("historical"),
    "runs/pendulum-001.jsonl",  # must not already exist
    config=GenerationConfig(
        max_output_tokens=4096,
        temperature=0.0,
        top_p=1.0,
        seed=7,
    ),
    oracle_backend=binding,
    oracle_config=GenerationConfig(max_output_tokens=512, temperature=0.0),
    max_repair_attempts=0,
    max_actions=100,
    run_metadata={
        "requested_model": "exact-provider-model-id",
        "provider_binding_id": "my-binding",
        "transport_profile": "plain_text",
        "tool_policy": "none",
        "network_policy": "model-api-only",
    },
)

print(run.outcome.termination.kind.value)
print(run.outcome.scientifically_evaluable)
print(run.outcome.active_pass)
print(run.llm_stats)
print(run.oracle_llm_stats)
```

The log uses exclusive creation and never overwrites an existing path. It stores
the exact public case snapshot, logical Player and optional Oracle model
requests, each in-limit raw response, parse/second-generation events, accepted
actions, simulator-based Oracle responses, final evaluation, usage, and
termination reason. Cumulative episode states are bound by the ordered
action/outcome stream and are reconstructed during replay.

One safety exception is explicit: a response larger than the configured action
byte limit cannot be valid, so its raw text is not copied into JSONL or a second
prompt. The log records provider/model metadata, byte count, and
`output_rejected`; the run ends as an evaluated `player_output_invalid` outcome. The LLM profile
caps `max_action_bytes` at 1 MiB.

Every Player-side stop is represented explicitly: `submitted`,
`player_output_invalid`, `action_rejected`, or `action_limit`. Only `submitted`
contains a committed final and invokes the case-specific evaluator. The other
three receive deterministic zeros for protocol completion and active task
success; no missing final is reconstructed. Infrastructure failures still
raise, do not become evaluated Player outcomes, and should be retried at the
same planned cell.

`run.started` records the action schema, generation config, action byte limit,
second-generation policy, action limit, and caller-supplied run metadata as
ordinary fields. The exact logical requests are recorded, so separate prompt,
separate adapter, decoder, prompt, and runner labels would duplicate evidence already in
the log and are intentionally absent.

The SDK-free integration example is runnable with:

```bash
python examples/run_fake_llm_development.py --log /tmp/role-benchmark-demo.jsonl
```

That fake backend is an interface test, not a model result.

## 6. Loading and replay

```python
from role_benchmark import load_run_log, replay_run_log
from role_benchmark.cases import make_pendulum_case

loaded = load_run_log("runs/pendulum-001.jsonl")
replay = replay_run_log(
    "runs/pendulum-001.jsonl",
    make_pendulum_case("historical"),
)
```

`load_run_log` performs no LLM/Oracle/evaluator call. It checks strict canonical
JSON, contiguous sequence numbers, one run ID, truncation, and the absence of
events after `run.ended`.

`replay_run_log` accepts the single current terminal grammar and performs these
checks without calling the LLM. Historical logs remain raw, readable artifacts;
the current runtime does not carry compatibility branches for them.

1. causal grammar: every Player and optional Oracle request, completion,
   failed/successful parse, action, and transition must occur in the only
   permitted physical order;
2. request/parser replay: the prompt renderer reconstructs each logical request,
   every claimed failed parse must fail with the same public error, and every
   successful raw response must decode to the same recorded `PlayerAction`;
3. supplied-runtime behavioral re-execution: decoded actions run through the
   case object supplied by the caller and must reproduce every authoritative
   Oracle response, recorded Oracle message, attempt count, terminal reason,
   evaluation, and `EpisodeOutcome`; replay never calls either LLM backend.

The third check establishes compatibility with the case supplied at replay
time. It makes no claim about where the original case came from.

Recontacting an LLM is never deterministic replay, even when a provider accepts
a seed. It creates a new run or trajectory fork.

Logs contain exact prompts and raw model outputs. Treat them as sensitive run
artifacts; do not put credentials, private truth, personal data, or proprietary
provider payloads in metadata.

## 7. Post-hoc process evaluation status

The JSONL already contains the observable inputs needed by a process evaluator:
every in-limit raw Player completion (including parse failures and an optional
second generation), decoded portfolios/actions, experiment proposals, Oracle
evidence, final submission, usage, and termination. Provider-private hidden
reasoning is not observable and is not part of the contract.

A transcript-aware `PostHocLLMEvaluator` now consumes a projection of the sealed
record and emits separately named process/result axes, findings with event
references, and a summary. The case-specific
`FinalEvaluator.evaluate(submission)` remains authoritative whenever final
model/parameters are strictly decoded and still sees only the
`FinalSubmission`. Portfolio, selection, and stopping violations are recorded
separately and prevent `active_pass`, while the scientific evaluation remains
available. Player output failures remain Judge-visible terminal outcomes but do
not receive a fabricated scientific score. LLM axes never overwrite or average
into `predictive_model_pass`; they remain exploratory until calibrated against
independent human ratings.

This preserves two interactive roles only: Player and Oracle. Evaluators and
Judges consume a completed record; they never answer Player experiments or
change the trajectory.

## 8. Minimum development report

Report the evaluated system as the whole tuple, not only a model name:

```text
model + provider binding + returned model revision + exact recorded prompt
+ action schema/parser + second-generation policy + generation config
+ transport/tool/network policy
```

At minimum report:

- evaluation profile and track;
- evaluated-terminal coverage, protocol completion, and termination reason;
- unconditional `active_pass` over the full planned denominator;
- scientific pass conditional on a scientifically evaluable final, only if clearly labelled as a
  diagnostic;
- `predictive_model_pass`;
- first-pass valid actions, actions valid only after a second generation, and
  second-generation calls, reported as separate strata;
- attempts, Player actions, model calls, and available token usage;
- public case ID and exact runtime/configuration fields needed to reproduce the profile.

Do not infer explanation correctness, Bayesian belief quality, confidence
calibration, originality, general discovery ability, or contamination resistance
from these public fixtures.

## 9. Remaining gate to formal evaluation

This loop supplies the transport, strict schema, recorded trajectory, and
behavioral replay needed for development. Formal use remains a separate stage:
deploy the Oracle/evaluator service independently and evaluate on a private
case pack. Until then, outputs remain development evaluation artifacts.
