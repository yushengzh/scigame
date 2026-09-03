# P0 evaluation policy: tracks, score semantics, and isolation

Status: normative for this repository from 2026-09-03. This document is the
single source of truth for claims about what a case measures and when a result
may be called a formal evaluation result.

## 1. Scientific decision rules

Every case starts from four questions, in this order:

1. What is unknown to the Player before interaction?
2. Which interventions can produce evidence about it?
3. What machine-verifiable object must the Player finally submit?
4. Which observable, reproducible property makes that submission pass?

The benchmark name, historical story, evaluator, and metric must follow those
answers.  They cannot be used to define the construct after implementation.

Every research-facing change note therefore records six short fields before
implementation: `problem/construct`, `nearest primary work`, `inherited versus
changed elements`, `claim status` (reuse, adaptation, synthesis, or untested
hypothesis), `minimal warm-up`, and `falsifier/decision rule`. This is a project
research-practice requirement, not a benchmark contribution.

The following rules apply to all research work in this project:

- **Separate evidence from interpretation.** Oracle responses carry case-world
  evidence. A model, mechanism, historical claim, or natural-language
  rationale is a distinct inference and is not correct merely because a numeric
  predictor passes.
- **Make claims falsifiable.** The allowed resources and budget must permit at
  least one intervention that separates material competing hypotheses at the
  declared measurement resolution.
- **Name every live alternative.** Every experiment portfolio contains at least
  two concrete, testable hypotheses with unique IDs (for example `H1` and
  `H2`). Their confidences sum to 1. A final portfolio may converge to one
  hypothesis. A residual `OTHER` bucket is not a hypothesis: if an alternative
  matters to the decision, the Player must state it explicitly so an allowed
  experiment could distinguish it.
- **Define the decision rule before evaluation.** Public evaluation domain, loss, threshold,
  budget policy, and measured construct are fixed before a formal run. Specific
  private instances, seeds, and held-out conditions remain secret.
- **Trace intellectual provenance before proposing novelty.** Every protocol,
  metric, case-construction, or analysis change is accompanied by a scoped
  related-work check. Existing ideas credit their original or closest primary
  sources; a new combination names its inherited components. If no direct
  precedent is found, the proposal states its first-principles motivation, a
  minimal warm-up, and a result that would count against it. Absence found in a
  scoped search is not evidence of priority.
- **Keep exploratory changes exploratory.** A metric or threshold devised after
  inspecting outcomes may diagnose that run, but cannot replace its frozen
  primary outcome. It becomes confirmatory only after its contract and analysis
  are fixed before an independent run. This follows the standard distinction
  between preregistered confirmatory and explicitly labelled exploratory
  analyses ([Wagenmakers et al., 2012](https://doi.org/10.1177/1745691612463078)).
- **Use the smallest sufficient design.** Add a field, scorer, assumption, or
  model class only when an observable requirement needs it. The small
  `expression` grammar exists only because blind-family discovery needs one
  truth-neutral executable submission contract; it is not a symbolic-search
  algorithm. P0 does not add an LLM judge, a composite score, or a new world
  generator.
- **Apply Occam's razor after empirical adequacy.** Prefer fewer assumptions or
  a shorter representation only between models that are indistinguishable on
  the preregistered predictive criterion. Simplicity cannot rescue a wrong
  predictor. There is no complexity score in the current protocol.
- **Keep evidence layers distinct.** Historical facts, facts available at the
  chosen historical cutoff, apparatus calibration, modern idealization, and
  private benchmark truth are recorded separately. A historically inspired
  case is not a literal historical replay.
- **Test simpler explanations of success.** Formal reports include at least a
  zero-observation or prior-only baseline and a legitimate experiment-using
  baseline. Memorization or a truth-correlated identifier must not explain a
  claimed scientific capability.

## 2. Identification and discovery are different tracks

The two track labels are mutually exclusive contracts, not difficulty levels.

| Contract | `identification` | `discovery` |
| --- | --- | --- |
| Full name | fixed-family active system identification | blind-family predictive law induction |
| Unknown before interaction | parameters of a public model family | the truth-specific functional family and its parameters |
| Public model information | complete family, parameter meanings, admissible ranges | only an executable representation and complexity ceiling shared across task families |
| Public experimental information | controls, readouts, units, ranges, resolution/noise, budget | the same |
| Private information | truth parameters, assignment, seed, specific held-out conditions | truth family, truth parameters, assignment, seed, specific held-out conditions |
| Final scored object | parameters or an equivalent executable predictor | an executable predictor in the common representation |
| Primary correctness criterion | predictive loss on held-out interventions | predictive loss on held-out interventions |
| Optional diagnostics | identifiable parameter error, attempts, calibration | canonical family recovery when defined, attempts, calibration |

The continuous `held_out_prediction_score` does not require the Player to reproduce the
benchmark reference expression, the same algebraic spelling, or exact hidden
parameters. It tests numerical predictions on the declared evaluation domain.
Formula-family or parameter agreement, when available, remains a separately
named diagnostic; finitely many successful interventions do not prove global
equivalence or complete law recovery.

Rules that resolve ambiguous cases:

- If the public payload supplies a truth-equivalent formula, transformation,
  model name, or parameter slots and only their values are unknown, the case is
  `identification`.
- Selecting from an explicit finite list of public candidate families is
  constrained model selection. Under this two-track P0 taxonomy it belongs with
  `identification`; it must not be presented as blind-family discovery.
- A dynamic hypothesis portfolio, more experiment turns, historical fame, or a
  counterfactual twin does not change the track.
- A `discovery` case may publish one safe representation grammar shared across
  the track, but must not publish truth-specific operators, transformations,
  parameter names, candidate lists, titles, error messages, or IDs.
- If the submission contains only predictions at prompted points and no
  executable rule, call the task active black-box modelling, not law discovery.
- Neither track measures general scientific creativity, real-world causal
  mechanism discovery, or originality.

### Current implementation status

The P0.1--P0.6 core contracts are implemented. The public curated registry
contains 20 H/C case families. Every family is built through
`make_case(name, world, track)` and exposes the four-cell design formed by two
condition roles (`historical`, `counterfactual`) and two task settings
(`identification`, `discovery`). The repository therefore contains 80 public
curated development instances.

A separate Temporal registry reviewed against the cited sources contains 9 additional families
and 36 instances, addressed through `make_temporal_case`. Each family retains
two source-reported conditions and crosses them with the two task settings.
Both Temporal conditions have the role `source_reported` and use semantically
neutral condition IDs. They are not H/C conditions; any legacy runtime selector
is an implementation compatibility detail, not a scientific label.

| Family group | Registered families | Cells per family |
| --- | --- | --- |
| Historically anchored core | `pendulum`, `young_double_slit`, `galileo_inclined_plane`, `boyle_j_tube`, `photoelectric`, `faraday_induction`, `radioactive_decay`, `rutherford_scattering` | 4 |
| Expanded matched set | `hooke_spring`, `torricelli_efflux`, `ohm_circuit`, `rc_discharge`, `stefan_boltzmann`, `newton_cooling`, `beer_lambert`, `michaelis_menten`, `coulomb_force`, `kepler_orbit`, `brownian_diffusion`, `poiseuille_flow` | 4 |

Within a curated family, each counterfactual changes one declared mechanism
coordinate. Within a condition, identification and discovery reuse the same
truth, WorldModel, measurement contract, held-out interventions, and final
executable `expression` representation; identification only discloses the
family-specific model and parameter slots. This holds the evidence and output
contracts fixed while changing family disclosure.

Each curated pair has two complete H/C variants. `easy` uses the original
counterfactual coordinate and `hard` uses the midpoint between the historical
and original counterfactual coordinates. Units, formula form, the single changed
mechanism coordinate, interface, fixed experimental design, budget, and scorer
remain unchanged. Four Temporal topics also have derived H/C variants in a
separate benchmark-authored pack: `self_similar_spreading_radius_ratio`,
`statistical_mean_field_effective_detuning`,
`stealthy_hyperuniform_localization_scaling`, and `uamo_lyapunov`. Their `easy`
and `hard` strength fractions are `0.75` and `0.5`. These authored variants do
not relabel or modify the original Temporal source conditions. NewtonBench is
used only as a design reference for law mutation, dimensional consistency, and
experiment budgets; its difficulty definitions are not adopted here.

All 29 registered families remain public development data: 20 H/C families
with 80 instances and 9 Temporal families with 36 source-condition instances.
The P0.6 contamination record stores only source/model-instance facts and an
explicit unknown state. Unknown exposure must not be inferred as unseen or
contamination-free. The private test set contains 0 families and 0 instances;
results on the 116 public instances are therefore not contamination-resistant
formal benchmark results. Breadth alone does not establish cross-domain
validity, evidence-following, or scientific discovery ability.

The three implemented evaluation methods are prior-only baseline, fixed
experimental design, and adaptive experimental design. Fixed and adaptive
methods use the same family-specific observation budget \(B\), and all three
methods share the final representation, held-out conditions, and scorer.

## 3. Score names state what was measured

The deterministic built-in evaluators use the continuous primary outcome:

```text
scores["held_out_prediction_score"]
```

For each held-out prediction, absolute error is divided by the case tolerance
(`absolute_tolerance + relative_tolerance * abs(target)`). The primary score is
`1 / (1 + mean scaled error)`, lies in `[0,1]`, and is higher when held-out
prediction is better. An invalid or missing Player submission receives 0;
infrastructure failure is missing and is retried. Binary
`predictive_model_pass` is a separately reported secondary outcome.

For the current cases:

- `held_out_prediction_score` is the preregistered continuous primary outcome;
- `EvaluationResult.success` and `predictive_model_pass` are the case's
  predictive pass/fail diagnostics;
- `explanation` and `scope_conditions` are required/free-form submission data
  but are not scored;
- the dynamic hypothesis portfolio and ex-ante forecasts are observable process
  data; narrowly defined deterministic trajectory diagnostics are reported, but
  they are not a Bayesian belief trace. Because natural-language hypotheses need
  not be mutually exclusive and exhaustive, their normalized `confidence`
  values are treated as reported support weights, not validated posterior
  probabilities;
- `selected_portfolio_confidence` and `confidence_threshold_reached` are derived
  only from the uniquely selected final portfolio entry. They record a protocol
  stopping condition, not calibrated confidence or evidence sufficiency;
- parameter errors are diagnostics, not a universal definition of correctness.

“Held out” in a public development instance only means not passed through the
normal Player API. In a formal evaluation it additionally means inaccessible
from the Player execution environment and fixed only by the trusted service.

If future work scores claims or scope, it must add separately named axes such as
claim/model consistency, claim truth, and scope validity. A language judge must
not alter `held_out_prediction_score` or the secondary binary pass.

The same rule applies to process evaluation. A transcript-aware Judge may score
observable experiment choice, evidence use, hypothesis revision, and stopping
decisions after the interaction. Those axes remain separate from the
deterministic predictive criterion, and hidden chain-of-thought is neither an
available nor a required benchmark input.

Every experiment action must forecast every requested numerical readout under
every current hypothesis before Oracle evidence is returned. After final commit,
the runtime reports forecast separation and evidence-aligned movement, together
with explicit `aligned`, `inert`, `opposed`, `unsupported_confidence_shift`,
hypothesis-rewrite exclusion, and duplicate-setup counts. The two retained
aggregate names are:

- `experiment_discriminativeness_mean`: a legacy implementation key whose value
  is the mean pairwise relative separation of the Player's self-reported ex-ante
  forecasts on valid experiments; it is not expected information gain and does
  not compare the chosen experiment with available alternatives;
- `evidence_aligned_belief_update_rate`: fraction of persistent hypothesis pairs
  whose confidence gap moves toward the hypothesis with lower normalized
  forecast error; unchanged gaps receive 0.5.

The accompanying pair counts make unscorable episodes explicit. These values
are never fed back to the Player and are not combined with the continuous
predictive score or binary pass.
In particular, `scorable_belief_pair_count = 0` means the update diagnostic is
unscorable; its stored aggregate default must not be interpreted as zero
scientific quality.

For every evaluated failure, the post-hoc failure analyzer separately reports:

- `terminal_failure`: the terminal contract or evaluator failure;
- `first_observed_misstep`: the earliest recorded step meeting a deterministic
  failure rule, not a claim about an internal root cause;
- all detected modes with action/turn indices, JSONL event references, the
  localization basis, and small observed/expected numeric details;
- recovered formatting incidents separately from episode failures;
- coverage showing which analyses were unscorable.

The core deterministic stages are `action_generation`, `protocol`,
`stopping_and_commitment`, `belief_update`, `final_synthesis`,
`final_model_specification`, and `held_out_generalization`. A confidence need
not become zero after one observation. As an exploratory post-hoc diagnostic,
the failure analyzer compares each hypothesis pair's realized forecast errors
against the returned evidence. Only when their mean error gap exceeds one public
measurement-resolution unit does it label an unchanged support gap `inert` or a
movement toward the worse forecast `opposed`; a final predictor is separately
checked against evidence already shown to the Player. This resolution-aware
convention is a warm-up heuristic, not part of primary pass/fail and not yet the
same rule used by the legacy trajectory aggregate. Natural-language claim
semantics remain unscored unless a separately declared Judge is used.

### Terminal outcomes and reporting denominators

Every Player-side stop in the logged benchmark is an evaluated terminal
outcome, with one of four machine-readable kinds:

- `submitted`: the Player supplied a strictly decoded final model and parameters,
  which were scientifically evaluated; separately recorded portfolio/stopping
  violations may still make `protocol_completion = 0`;
- `player_output_invalid`: the enabled generation calls produced no strictly
  decodable action;
- `action_rejected`: an action decoded, but violated an episode invariant;
- `action_limit`: the Player did not submit within the action horizon.

Only `submitted` contains a final scientific object and invokes the
case-specific evaluator. Its scientific result and protocol completion are
reported separately. The other three outcomes receive deterministic zeros for
`active_pass`, `protocol_completion`, and `submission_available`; they do not
receive an invented or repaired scientific answer. A decoded rejected action
may remain in the record as observable process evidence, but is never committed
as a final submission.

Provider transport, Oracle presentation, evaluator-runtime, storage, or local
runner failures are infrastructure failures rather than Player outcomes. They
do not consume a planned experimental cell and must be retried at the same
schedule position.

Reports use the full planned denominator and keep the following quantities
separate:

- evaluated-terminal coverage over scheduled cells;
- unconditional continuous held-out prediction score, with Player-side invalid
  or missing submissions scored as 0;
- protocol-completion (valid-final) rate;
- unconditional task success, represented by `active_pass = submitted AND
  protocol_completion AND EvaluationResult.success`;
- scientific success conditional on a scientifically evaluable final, if
  reported as a diagnostic.

The conditional quantity must never replace unconditional task success. Thus a
JSON/schema failure, rejected action, or action-limit stop remains in the
denominator instead of disappearing before evaluation.

## 4. Formal evaluation boundary

The repository currently implements public development evaluation: 20 H/C
families (80 instances) and 9 Temporal source-condition families (36 instances)
are public, while the private test set contains 0 families and 0 instances. A
result is formal only when the active case pack is kept outside the Player
process and the Player communicates with it through the serialized protocol.

The minimum formal boundary has four rules:

1. The service, not the Player, holds the active truth, WorldModel, evaluator,
   and held-out conditions.
2. The Player receives only the public `EpisodeView`, then sends validated
   `PlayerAction` values and receives ordinary `OracleResponse` values.
3. Case assignment and truth-specific identifiers are not exposed before the
   interaction.
4. The final structured submission is evaluated under the previously defined
   predictive rule; any optional process Judge runs only after the interaction
   on the recorded observable transcript.

The deterministic `CaseOracle` is the primary interface. An optional LLM
presentation layer may strictly present an observation already produced by the
WorldModel, but it must not change response status, measurements, units, or
uncertainty. That optional path still requires an Oracle accuracy audit and
must not be used for primary results before the audit is complete. The Player
receives only public case information and returned evidence; any presentation
model remains a separate role with separate prompts, conversations, and
information access.

These rules separate development fixtures from private evaluation without
adding mechanisms unrelated to the scientific interaction. They do not imply
originality, historical authenticity, causal-mechanism correctness, prose
quality, or general scientific creativity.

## 5. Minimal case-author gate

Before merging a case, its author records:

- the unknown object, allowed evidence, final scored object, and pass property;
- the explicit `BenchmarkTrack` and the information that justifies it;
- public evaluation domain/loss/threshold and private instance fields;
- at least two materially competing hypotheses and a budget-feasible
  discriminating intervention;
- readout units, ranges, resolution/noise, and whether replicates add information;
- historical sources, knowledge cutoff, calibration, modern idealization,
  and benchmark truth as separate layers;
- zero-observation and experiment-using baselines;
- hidden tests covering declared boundaries, interactions, and threshold sides;
- accurate metric names and an explicit list of unscored fields.

Discovery cases have two additional gates: at least several viable functional
families behind the same public interface, and one executable
submission representation shared across the track. Until both exist and the
formal boundary is deployed, a case remains an identification or development
fixture rather than a discovery benchmark.
