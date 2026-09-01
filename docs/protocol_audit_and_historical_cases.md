# Protocol notes and historical case experiments

> **P0 resolution (2026-08-24; implementation status updated 2026-08-25).**
> The repository has explicit `identification`/`discovery` track metadata. The
> initial P0 implementation covered pendulum and Young double slit; the current
> registry contains 20 complete historical/counterfactual ×
> identification/discovery families. The built-in numeric metric is named
> `predictive_model_pass`; and the formal evaluation boundary is fixed in
> [`evaluation_policy.md`](evaluation_policy.md). That policy supersedes the
> brainstormed P0 options below whenever wording differs.
> The current experiment-portfolio contract also removes the residual `OTHER`
> bucket and requires at least two explicitly named, concrete, testable
> hypotheses with unique IDs and normalized confidence. A final portfolio may
> converge to one hypothesis.

This note reviews the seven priority concerns identified in the initial code
reading and records the original historically inspired prototypes implemented
without changing the episode interaction protocol. The current 20-family
inventory is maintained separately in [`case_catalog.md`](case_catalog.md). The goal is to distinguish runtime
bugs, benchmark validity risks, deliberate scope choices, and missing product
infrastructure.

The historical cases are idealized experimental worlds.  Their sources motivate
the apparatus and scientific question; their exact constants, rounding rules,
hidden conditions, and scoring policies are benchmark-author choices.

## Summary

| # | Concern | Verdict | Priority for a public benchmark |
| --- | --- | --- | --- |
| 1 | Truth and label leakage | P0 policy fixed; private deployment remains future infrastructure | P0 resolved by contract |
| 2 | Public model family narrows discovery to parameter fitting | Identification and discovery are separate contracts; all 20 current families implement both | P0 resolved |
| 3 | Natural-language explanation is not scored | Numeric metric renamed; prose explicitly unscored | P0 resolved |
| 4 | Frozen dataclasses contain mutable mappings | Valid result-integrity bug | P1 |
| 5 | Schema and runtime contracts are incomplete | Valid robustness bug family | P1 |
| 6 | `max_turns` documentation and behavior differ | Valid protocol/API bug | P1 |
| 7 | No LLM adapter, persistence, CI, or broad negative testing | MVP/product-readiness gap | P1/P2 |

## 1. Truth and label leakage

### Finding

The current boundary is capability-oriented, not security-oriented.  A normal
`PlayerBackend` receives only `EpisodeView`, but the same Python distribution
also contains the truth parameters, hidden conditions, and each family's mapping
from the `historical`/`counterfactual` authoring arguments to counterbalanced
`instance_1`/`instance_2` public identifiers.

Consequently, an in-process agent with filesystem or import access can inspect
`case.world_model._truth`; a model that has memorized the open repository can
use the stable public case ID as an answer key. A lookup player can submit the
known parameters at zero experiments because the episode permits an immediate
final submission when the selected portfolio confidence reaches the threshold.

This is severe for a public leaderboard, but much less severe for a transparent
teaching fixture where the LLM is prompt-only and the source is intentionally
visible.

### Brainstormed options

1. Keep the current cases as explicitly public development fixtures.
2. Run Oracle and evaluator in a separate trusted service; give the Player only
   serialized public views and opaque per-run handles.
3. Give matched worlds the same public family metadata and use per-family
   counterbalanced opaque instance tokens; the current development pack now does
   this deterministically, while a private service may use per-run tokens.
4. Sample private worlds from a parameterized family on the evaluation service.
5. Rotate held-out case packs and publish them only after retirement.
6. Add zero-observation and lookup baselines rather than relying solely on final
   accuracy.  A forced minimum experiment count is weak protection because a
   cheating player can submit meaningless experiments.

### P0 resolution and acceptance criteria

All cases shipped in this repository are now declared public development
fixtures. The normative threat model defines a serialized boundary between an
untrusted Player side and a separately deployed trusted Oracle/evaluator side.
The current in-process runtime remains suitable for development only; it must
not be reported as a formal private benchmark result.

Formal use requires keeping the active truth, WorldModel, evaluator, and held-out
conditions outside the Player process. See
[`evaluation_policy.md`](evaluation_policy.md#4-formal-evaluation-boundary).

## 2. Public model family changes the task

### Finding

Every current family exposes its parameterized model skeleton and evaluator
parameter names in the identification view. Those views are therefore
fixed-family active system identification: choose experiments and estimate
named parameters, not discover a functional form.

`CaseDefinition.track` is required and enum-typed. Every historical and
counterfactual world can be instantiated as either track. Discovery views remove
the family-specific skeleton and truth-specific parameter slots and accept the
track-wide `expression` representation instead.

### Brainstormed options

1. Rename the current track to **fixed-family identification** and score
   parameter error, experiment efficiency, and calibration.
2. Add a separate **discovery track** whose public resources contain controls,
   readouts, units, and ranges but no unique formula or truth-specific parameter
   names.
3. For discovery, score numeric predictions on hidden interventions rather than
   symbolic equality.
4. Use the safe `expression` AST/DSL with whitelisted public variables and
   operators; do not execute submitted source code.
5. Put several functional families—linear, inverse, power, saturation, threshold,
   interaction, and piecewise—behind the same public resources.
6. Reveal an output schema only after the evidence-gathering phase, so it cannot
   dictate the Player's initial hypothesis space.

### P0 resolution and acceptance criteria

All 20 current families implement the full historical/counterfactual ×
identification/discovery matrix. Their generic acceptance tests require matched
public payloads, identical same-world evidence across tracks, budget-feasible
diagnostics, truth-pass and bidirectional false-twin failure. This exercises the
public protocol but does not satisfy the formal private-pack gate or establish
broad cross-domain validity. A formal discovery pack still needs private
variants and an experiment-using baseline that succeeds across private seeds.

The upgrade was not a mechanical wrapper: every family records a minimally
authored counterfactual, source credit, public range and resolution, diagnostic
conditions and matched hidden interventions. These internal checks are
necessary but do not replace external scientific review.

## 3. Natural-language explanation is not evaluated

### Finding

`FinalSubmission.explanation` is checked only for non-emptiness. All built-in
evaluators read `model` and `parameters`, not `explanation`
or `scope_conditions`. A numerically correct model with deliberately opposite
prose therefore still passes; `tests/test_historical_cases.py` intentionally
locks this behaviour as the current construct boundary.

The formerly misleading `explanation_correct` score has been removed from all
built-in evaluator paths. Its replacement, `predictive_model_pass`, names the
actual hidden-condition numeric prediction test. No compatibility alias is
emitted because that would preserve the false semantic claim.

### Brainstormed options

1. Rename the current score to `predictive_model_pass` and state explicitly that
   free text is not scored.
2. Add typed `StructuredClaims`: dependent variables, monotonic directions,
   exponents/interactions, mechanism claims, and evidence references.
3. Replace free-form scope strings with machine-readable ranges and assumptions.
4. Score predictive accuracy, claim/model consistency, truth accuracy, and scope
   validity as separate axes.
5. Optionally add a blind rubric-based human or LLM language score, but keep it
   separate from deterministic numeric scoring until calibrated against human
   annotations and hardened against prompt injection.
6. Generate a canonical explanation from a structured model when explanation
   quality is outside the intended construct.

### P0 resolution and acceptance criteria

The metric terminology is fixed and prose is explicitly unscored. If future
work adds structured claims or machine-readable scope, prediction, claim/model
consistency, claim truth, and scope validity must remain separately named axes.
A language judge must not silently change the predictive metric.

## 4. Frozen objects are only shallowly frozen

### Finding

Several frozen dataclasses retain caller-owned mutable objects:

- `ExperimentProposal.controls`
- `ExperimentEvidence.measurements`, `units`, and `uncertainty`
- `FinalSubmission.parameters`
- `EvaluationResult.scores`

`Episode` records the same references.  Mutating a source dictionary after an
experiment can therefore rewrite an existing transcript; mutating final
parameters or scores can make a successful result internally inconsistent.
Turning the outer turn list into a tuple does not prevent this.

### Brainstormed options

1. `deepcopy` at boundaries removes aliases but leaves public objects mutable.
2. `MappingProxyType(dict(value))` gives shallow read-only mappings but complicates
   some serializers and does not freeze nested values.
3. Introduce a recursive JSON-compatible `freeze_json` and `thaw_json`, with a
   small immutable mapping type and list-to-tuple conversion.
4. Add explicit `to_dict`/`from_dict` codecs rather than relying on
   `dataclasses.asdict`.
5. Snapshot actions and responses again inside `Episode.apply` as defense in depth
   against custom implementations.

### Recommendation and acceptance criteria

Design recursive freezing and serialization together.  Tests must show that
mutating original or nested containers cannot change proposals, evidence,
history, submissions, or scores, while canonical JSON round-trips remain
available.

## 5. Schema and runtime contracts are incomplete

### Finding

There are three distinct boundaries currently mixed together.

1. Static case-author schema: resource names are checked for duplicates, but
   references, empty names, finite ordered ranges, positive resolution, and
   strict integer budget fields are not fully validated.
2. Player input: `ExperimentProposal` has no constructor validation and
   `CaseOracle` calls
   operations such as `.strip()`, `set()`, and `float()` directly.  Malformed
   values can leak `AttributeError`, `TypeError`, or `OverflowError` rather than
   produce a declared response.
3. WorldModel/evaluator output: `CaseOracle` checks measurement keys but not unit
   equality, value type/finiteness, uncertainty shape, or return type. `NaN`, a
   wrong unit, or an arbitrary object can enter a `VALID` transcript.

The original pendulum evaluator also lets a very large integer escape as
`OverflowError`.  The historical case-level evaluators catch this input and return
a failed `EvaluationResult`, but that local defense does not fix the core API.

### Brainstormed options

1. Add strict `__post_init__` validation and cross-reference checks to resource
   schemas; fail fast when a case is authored incorrectly.
2. Put a wire decoder in front of `PlayerAction` to validate JSON shape and types.
   Parsing/repair policy should be explicit and separate from experiment budget.
3. Keep Oracle semantic statuses for well-formed but incomplete, unsupported, or
   out-of-range proposals.
4. Add declared readout kinds, shapes, units, and nullability plus optional
   case-specific value validators.
5. Wrap WorldModel/evaluator defects in dedicated infrastructure errors; they
   should neither consume Player budget nor look like a failed scientific answer.
6. Add property/fuzz tests asserting that any JSON-compatible Player input yields
   a declared response or declared parse error, never an accidental exception.

### Recommendation and acceptance criteria

Implement the three layers separately: wire/schema decoding, Oracle semantic
validation, and private implementation contracts. Every valid evidence object
must conform to its declared readout schema; huge numbers, booleans, non-finite
values, wrong containers, duplicate entries, and bad units need regression tests.

## 6. `max_turns` does not mean what its documentation says

### Finding

The runner says `max_turns` only prevents infinite clarification requests, but
the loop counts every `next_action` call: valid experiments, invalid attempts,
clarifications, and the final action.  A budget of `B` can require `B + 1` actions
to exhaust the budget and then submit.  Thus `max_turns <= B` can reject a fully
legal trajectory.  Positive floats and booleans also lack a clean validation
contract.

### Brainstormed options

1. Minimal compatibility change: rename it `max_actions`, document that final is
   included, and keep a deprecated `max_turns` alias.
2. Implement the original intent as `max_clarifications`; consuming attempts are
   already bounded by the case budget.
3. Optionally retain a larger `max_total_actions` safety valve, with a distinct
   error and partial transcript.
4. Define “turn,” “attempt,” “action,” and “clarification” once and use those
   terms consistently in data models, docs, and metrics.

### Recommendation and acceptance criteria

Prefer `max_clarifications` plus an optional total-action guard.  Tests should
cover exactly `B` consuming attempts followed by final, exact clarification
limits, early final, strict positive-integer parameters, and auditable state on
termination.

## 7. Missing LLM and operational infrastructure

### Finding

> Status after the development-loop milestone: the original gap below has been
> partially resolved. The repository now has a provider-neutral LLM adapter,
> recorded prompt and strict decoder, explicit optional second-generation
> policy, plain JSONL logging, inference-call and available-token
> accounting, causal/parser replay, supplied-runtime behavioral re-execution,
> and a network-free fake integration test. It still has no checkpoint/resume,
> latency/cost accounting, CI matrix, lint/type gate, or formal isolated runner.

At the time of the initial audit, `PlayerBackend` was only a Protocol and the
example was explicitly scripted. There was no prompt renderer, action JSON
schema, provider adapter, event log, or fake-model integration test.

This is appropriate for a small protocol prototype.  It blocks reproducible
claims about real LLM benchmark performance.

### Brainstormed options

1. Define provider-neutral `StructuredModel` and `LLMPlayerBackend` ports.
2. Record the exact prompt and use one strict PlayerAction wire schema.
3. Add a bounded parsing policy and record raw response, parsed action, errors,
   and any schema-directed second generation. Decide its experiment and
   inference accounting before collecting results.
4. Add a JSONL event log with the public case, model
   settings, seeds, actions, responses, evaluation, usage, latency, and stop reason.
5. Keep private truth data separate from Player-visible transcripts.
6. Test adapters with a deterministic fake model; keep real-provider integration
   tests gated and separate.
7. Add CI for clean install, unit tests, build/import smoke tests, lint/type checks,
   and all supported Python interpreters before imposing a coverage threshold.

### Recommendation and acceptance criteria

First build the immutable codec and validation layers from issues 4 and 5; both
the event log and LLM adapter depend on them.  Then add persistence, a fake-backed
adapter, and CI before introducing provider-specific code.

## Historical case prototypes

All current factories are available through the unified registry:

```python
from role_benchmark.cases import CASE_FAMILIES, make_case

for family in CASE_FAMILIES:
    case = make_case(family, world="historical")
```

They run through the existing `CaseOracle`, `Episode`, and evaluator
interfaces. P0 added explicit track metadata and corrected built-in score names;
the interaction shape remains the same, while the portfolio invariant now
requires at least two concrete alternatives instead of a residual `OTHER`
bucket.

### Galileo inclined plane

Factory: `make_galileo_inclined_plane_case()`

Historical basis: Galileo's *Two New Sciences* describes a grooved inclined
plane, round ball, water clock, repeated descents, and comparison of collected
water weights.  Sources include the [public-domain translated work](https://oll.libertyfund.org/titles/galilei-dialogues-concerning-two-new-sciences)
and the [Rice Galileo Project reconstruction](https://galileo.library.rice.edu/lib/student_work/experiment95/inclined_plane.html).

Implemented public experiment, shared by both worlds and both tracks:

- controls: travel distance, incline angle, and ball mass;
- readout: collected water mass, used as an elapsed-time proxy;
- budget: 9; maximum replicates: 12;
- structured final model: normalized power law.

Private benchmark truth:

```text
W = 24 g
  * (distance / 1 m)^0.5
  * (sin(angle) / sin(5 deg))^-0.5
  * (mass / 0.20 kg)^0
```

The 24 g reference value and deterministic balance rounding are benchmark
calibration, not claimed historical measurements.  This case fits the current
protocol well, but the protocol cannot naturally represent intermediate bell
events, raw repeated measurements, derived controls such as `sin(angle)`, or
rolling/slipping state.

### Boyle J-tube

Factory: `make_boyle_j_tube_case()`

Historical basis: Boyle and Hooke compressed trapped air with mercury and
compared pressure with volume.  The case credits the [Royal Society archive's
1661 experimental account](https://makingscience.royalsociety.org/items/rbo_1_22/an-experimentall-account-of-the-compression-of-aire-made-by-mr-boyle),
later published in 1662. Boyle's 1660 pneumatic work is broader historical
background, not the source attribution for the implemented inverse law.

Implemented public experiment:

- controls: added pressure and a categorical constant-temperature condition;
- readouts: trapped-air volume and absolute pressure, requestable separately or
  together;
- budget: 8; maximum replicates: 10;
- structured final model: normalized pressure power law.

Private benchmark truth:

```text
P = 101.3 kPa + added_pressure
V = 48.0 mL * (P / 101.3 kPa)^-1
```

This case exposes a modeling compromise: physically, adding mercury jointly
changes pressure and volume until equilibrium; the protocol represents added
pressure as an independent control.  It also has no natural place for waiting,
hysteresis, leakage, or apparatus history.

### Photoelectric effect

Factory: `make_photoelectric_case()`

Historical basis: the prototype combines Einstein's frequency law with the type
of quantitative vacuum-phototube test associated with Millikan.  The Nobel
Foundation's [1921 presentation discussion](https://www.nobelprize.org/prizes/physics/1921/ceremony-speech/)
summarizes the different roles of frequency and intensity, and Millikan's
[Nobel lecture](https://www.nobelprize.org/uploads/2018/06/millikan-lecture.pdf)
describes the experimental validation and direct determination of Planck's
constant.

Implemented public experiment:

- controls: light frequency and relative intensity;
- readouts: stopping potential and saturation photocurrent;
- budget: 10; maximum replicates: 15;
- structured final model: thresholded Einstein photoelectric relation plus a
  deliberately idealized linear current response.

Private benchmark truth for a clean-sodium idealization:

```text
stopping_potential = max(0, 4.135667696e-15 * frequency_hz - 2.28) V
saturation_current = 0 below threshold, otherwise 3.0 * relative_intensity uA
```

The exact work function and current coefficient are benchmark choices.  Below
threshold, the implementation returns numeric zero for stopping potential even
though “stopping potential” is more naturally undefined when no electrons are
emitted.  This reveals missing readout dtype/nullability and conditional-validity
metadata.  An automatic stopping-potential scan also hides a multistep operation
inside a single budget unit.

### Young optical interference

Factory: `make_young_double_slit_case()`

Historical basis: Young's Bakerian lecture describes optical-interference
observations and calculations. The Royal Society preserves the [1803 manuscript
record](https://makingscience.royalsociety.org/items/l-and-p_12_60/paper-experiments-and-observations-relative-to-physical-optica-bakerian-lecture-by-thomas-young),
and a scan of the published 1804 paper is available through [Wikimedia
Commons](https://commons.wikimedia.org/wiki/File:The_Bakerian_Lecture-_Experiments_and_Calculations_Relative_to_Physical_Optics_(IA_jstor-107135).pdf).

Implemented public experiment:

- controls: wavelength, slit-to-screen distance, and slit separation;
- readout: adjacent bright-fringe spacing;
- budget: 8; maximum replicates: 12;
- identification submission: normalized three-variable power law;
- discovery submission: the track-wide family-neutral `expression` grammar.

The historical-law private truth is:

```text
spacing = 1.10 mm
  * (wavelength / 550 nm)^1
  * (screen distance / 1 m)^1
  * (slit separation / 0.50 mm)^-1
```

The counterfactual twin changes exactly one normalized exponent:

```text
spacing = 1.10 mm
  * (wavelength / 550 nm)^1
  * (screen distance / 1 m)^1
  * (slit separation / 0.50 mm)^-0.5
```

`make_young_double_slit_case(world, track)` therefore generates four cells:
historical identification, historical discovery, counterfactual identification,
and counterfactual discovery. Within each world the tracks share one
`WorldModel`, the experiment interface, budget, and seven held-out conditions;
only the public model-family contract changes.

```python
from role_benchmark import BenchmarkTrack
from role_benchmark.cases import make_young_double_slit_case

historical_identification = make_young_double_slit_case(
    "historical", BenchmarkTrack.IDENTIFICATION
)
historical_discovery = make_young_double_slit_case(
    "historical", BenchmarkTrack.DISCOVERY
)
counterfactual_identification = make_young_double_slit_case(
    "counterfactual", BenchmarkTrack.IDENTIFICATION
)
counterfactual_discovery = make_young_double_slit_case(
    "counterfactual", BenchmarkTrack.DISCOVERY
)
```

The normalized ratios are dimensionless and the reference spacing carries the
output unit. The modern two-slit geometry and metric calibration are
intentionally cleaner than Young's historical apparatus. “Historical” here
means a historically inspired idealized law world, not raw archive data,
historical reconstruction fidelity, or a literal replay of Young's apparatus.

### Faraday electromagnetic induction

Factory: `make_faraday_induction_case()`

Historical basis: Faraday's *Experimental Researches in Electricity* reports
induced currents from changing magnetic relations; the [full first volume is
available from Project Gutenberg](https://www.gutenberg.org/files/14986/14986-h/14986-h.htm),
and the Royal Society preserves the [1832 manuscript of the third
series](https://makingscience.royalsociety.org/items/pt_21_1/paper-experimental-researches-on-electricity-third-series-by-michael-faraday).

Implemented public experiment:

- controls: coil turns, loop area, magnetic-field change, and change time;
- readout: peak induced-voltage magnitude;
- budget: 10; maximum replicates: 10;
- structured final model: normalized magnetic-flux-change power law.

Private benchmark truth:

```text
emf = 20.0 mV
  * (turns / 100)^1
  * (area / 20 cm^2)^1
  * (field change / 10 mT)^1
  * (change time / 100 ms)^-1
```

The case deliberately scores magnitude only. Direction, waveform shape,
resistance, mutual inductance, and core hysteresis would require richer controls
and time-series readouts.

### Rutherford--Soddy radioactive decay

Factory: `make_radioactive_decay_case()`

Historical basis: Rutherford and Soddy published *The Cause and Nature of
Radioactivity* in 1902 ([original journal record and
DOI](https://www.tandfonline.com/doi/abs/10.1080/14786440209462856)).
Rutherford's 1904 article states that many radioactive products diminish
according to an [exponential law with
time](https://www.nature.com/articles/070161a0).

Implemented public experiment:

- controls: elapsed time after isolation and sample mass;
- readout: background-inclusive mean count rate;
- budget: 8; maximum replicates: 20;
- structured final model: single exponential with background and mass scaling.

Private benchmark truth:

```text
rate = 20 counts/min
  + 800 counts/min * (sample mass / 1 mg)^1
  * 2^(-elapsed time / 60 min)
```

The Oracle returns deterministic mean rates. A historically and statistically
richer implementation should expose finite counting intervals and sampled counts, which
requires a declared randomness and replay policy.

### Geiger--Marsden/Rutherford scattering

Factory: `make_rutherford_scattering_case()`

Historical basis: Geiger and Marsden's 1909 paper reports diffuse reflection of
alpha particles and explicitly compares metals, foil thickness, and reflected
fractions ([Royal Society DOI and
abstract](https://doi.org/10.1098/rspa.1909.0054)). Rutherford's 1911 paper then
develops the central-scattering model and angular relation ([original journal
record and DOI](https://www.tandfonline.com/doi/abs/10.1080/14786440508637080)).

Implemented public experiment:

- controls: scattering angle, foil atomic number, thickness, and exposure;
- readout: scattered alpha count rate;
- budget: 10; maximum replicates: 15;
- structured final model: normalized thin-foil angular scattering law.

Private benchmark truth:

```text
rate = 120 counts/min
  * (atomic number / 79)^2
  * (thickness / 0.50 um)^1
  * exposure^1
  * (sin(angle / 2) / sin(30 deg))^-4
```

This idealization combines Geiger--Marsden's experimental comparisons with
Rutherford's later quantitative model. Multiple scattering, energy loss,
detector solid angle, and stochastic scintillation counts are outside the world.

## What the prototypes teach us

The unchanged protocol handles these common elements well:

- public resources separated from private outcome generation;
- continuous and categorical controls;
- single or multiple readout subsets;
- deterministic scalar evidence with units and uncertainty strings;
- case-specific final evaluators;
- domain-independent episode budgeting and dynamic hypotheses.

The pressure points recur across domains:

1. Historically realistic experiments are often stateful and multistage; the
   current proposal is a single stateless control mapping.
2. Instrument modes, sweeps, waiting, calibration, and unequal experiment costs
   have no first-class representation.
3. Readouts have no declared type, shape, nullability, or conditional validity.
4. Replicates produce only an aggregate and currently add no stochastic evidence.
5. Public evaluator schemas leak the model family.
6. Prediction scoring does not establish a correct mechanism or explanation.
7. Historical evidence and author-only notes need a private sidecar; putting
   them in `CaseDefinition` would reveal author information to the Player.

## Brainstormed next cases

The following discoveries were considered but not added to the first batch:

| Candidate | Bench opportunity | Missing or avoidable complication |
| --- | --- | --- |
| Hooke spring law | clean force-extension baseline | mostly duplicates existing one-exponent identification |
| Ohm conduction law | voltage, geometry, and material interventions | temperature and self-heating make a credible world stateful |
| Cavendish torsion balance | inverse-square gravitation | equilibration time and torsional dynamics are hidden multistep operations |
| Mendelian segregation | competing inheritance ratios | credible evidence needs sampled integer offspring and seeded randomness |
| Brownian motion/Perrin | infer diffusion from particle trajectories | needs distribution- or trajectory-valued evidence, not one scalar mean |
| Michelson--Morley | informative null result and precision reasoning | needs systematic uncertainty and equivalence-aware null scoring |
| Blackbody radiation | discriminate curve families and recover temperature law | needs spectrum-valued readouts and curve prediction |
| Pasteur swan-neck flasks | intervention-based causal reasoning | contamination, waiting, and vessel history require a stateful WorldModel |
| Lavoisier closed-vessel combustion | conservation under gas capture | open/closed vessel state and multiple mass transfers need staged operations |
| Herschel infrared experiment | discovery beyond the visible spectrum | requires spatially indexed multi-readout measurements and calibration controls |

The next protocol extension should be chosen by a retained case, not added in
the abstract. Mendel is the smallest useful driver for seeded stochastic
evidence; blackbody radiation is the smallest useful driver for array-valued
readouts; Pasteur is the clearest driver for stateful multi-stage experiments.

## Suggested implementation order

1. **Completed in P0:** clarify task names, metric names, and formal boundary;
   mark current cases as public development fixtures with explicit tracks.
2. **Completed for the development boundary:** add negative characterization
   tests, recursive detached codecs, strict decoding, and explicit error classes.
3. Correct action/clarification limits; plain transcript persistence is complete,
   while checkpoint/resume remains open.
4. **Completed for development evaluation:** add a provider-neutral LLM adapter
   with a strict wire schema, recorded configuration, replay, and fake-model
   tests.
5. Introduce typed/conditional readouts, instrument operations and costs, raw
   replicate evidence, and optional stateful WorldModels.
6. **Completed for two development families:** add a held-out discovery track
   using the safe expression DSL; broader families and structured explanation
   claims remain open.

## Verification

```bash
python -m pip install -e .
python -m unittest discover -s tests -v
python examples/probe_historical_cases.py
```

The current verification suite includes explicit track typing/classification,
new score names on success and failure, matched Young/pendulum evaluator checks, registry
freshness, one full Episode per historical case, and characterization of the
current prose-scoring boundary. Run it rather than relying on a stale recorded
test count.
