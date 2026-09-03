# Separating Prior Alignment from Model-Family Disclosure in Interactive Scientific Law Induction

**Working paper draft A — recommended direction.** This version is written as
an eight-page main-conference manuscript nucleus. Bracketed statements marked
`[REQUIRES NEW EVIDENCE]` are placeholders for experiments that do not yet
exist; they are not claims about the present repository.

## Abstract

Interactive benchmarks for scientific agents often combine several sources of
difficulty: the target law may conflict with familiar science, the functional
family may be hidden, and the agent must choose experiments under a budget. A
single success rate cannot determine which difficulty caused failure. We
present a paired diagnostic protocol that crosses two factors: whether the
simulated world follows a familiar historical relationship or a minimally
modified counterfactual relationship, and whether the correct model family is
disclosed or withheld. The resulting tasks distinguish fixed-family active
system identification from predictive law induction with the family withheld.
Within each world, the two tasks share the apparatus, experiment budget,
authoritative world model, evidence, and held-out interventions. The protocol
also requires named competing hypotheses and numerical forecasts before each
experiment, permitting outcome and observable evidence use to be reported
separately. We implement 20 matched public-development families, yielding 80
cells. In an archived, exploratory 80-episode run with one language model,
unconditional predictive pass rates were 12/20, 4/20, 4/20, and 1/20 for
historical identification, historical induction, counterfactual identification,
and counterfactual induction, respectively; 30/80 episodes ended without a
protocol-valid submission. These numbers demonstrate the evaluation surface,
not a formal capability estimate: the run has one repeat, uses public cases,
predates the current source snapshot, and the two tracks currently use
different final encodings. We therefore treat the work as a measurement design
and identify the experiments required to test whether the paired contrast adds
diagnostic value beyond existing scientific-agent benchmarks.

## 1. Introduction

An agent that rediscovers a familiar formula may have reasoned from evidence,
recalled the formula, or simply filled parameters into a supplied template. An
agent that fails in a counterfactual world may have resisted evidence because
of a strong prior, but it may instead have failed to fit numbers, produce valid
code, or satisfy an output schema. These explanations imply different
scientific capabilities and different interventions for improving the agent.
Yet they are often collapsed into one task-success score.

Recent benchmarks have made interactive scientific discovery substantially
more concrete. DiscoveryWorld evaluates complete hypothesis–experiment–action
cycles in simulated environments (Jansen et al., 2024). PhysGym varies how much
prior information a physics agent receives (Y. Chen et al., 2025). NewtonBench
places altered physical laws inside systems of increasing complexity (Zheng et
al., 2025). LLM-AutoSciLab couples explicit hypotheses to active experiment
selection (Kabra et al., 2026), while DiscoverPhysics asks agents to submit
executable laws for counterfactual N-body worlds and evaluates them on held-out
trajectories (Wiemann et al., 2026). FALSIFYBENCH studies Player–Oracle hidden
rule discovery and shows the importance of negative tests (Bertolazzi et al.,
2026). These works rule out broad priority claims based on interaction,
counterfactual laws, controlled priors, executable predictions, or trajectory
analysis individually.

The narrower unresolved question is whether two conceptually different factors
can be separated in a matched experiment: **alignment with a model's familiar
scientific priors** and **disclosure of the correct functional family**. A
historical versus counterfactual comparison manipulates the first factor only
if the worlds are otherwise matched. A family-disclosed versus family-withheld
comparison manipulates the second factor only if both methods query the same
world. Crossing the factors yields a direct diagnostic: does the historical
advantage grow specifically when the agent must infer the functional form, or
does it persist even when the correct family is supplied?

We develop an operational protocol for that comparison. We use
**identification** for tasks that disclose a parameterized model family and ask
the agent to estimate its unknown parameters. We use **predictive law
induction** for tasks that withhold the truth-specific family and require an
executable predictor in a common representation. This terminology avoids
calling parameter fitting “discovery” and avoids claiming unrestricted
mechanism discovery from a finite interactive task.

The complete episode should not be assigned one exclusive philosophical label:
generating candidate explanations can be abductive, deriving numerical
forecasts is deductive, updating a general law from observations is inductive,
and experiments may be chosen to falsify an alternative. Our protocol records
the observable interfaces among these steps rather than claiming access to a
model's private reasoning.

Our contributions are deliberately scoped:

1. We specify a paired 2 x 2 design crossing prior alignment and whether the
   correct model family is disclosed. Each family supplies historical and
   counterfactual worlds, and each world supplies identification and induction
   views over a shared evidence environment.
2. We define a two-role interaction in which an authoritative executable world
   model produces evidence, the Player records competing hypotheses and
   forecasts before observing that evidence, and evaluation is post hoc.
3. We separate unconditional held-out predictive success, protocol completion,
   and narrow process metrics based on pre-experiment predictions, with explicit full
   denominators for invalid or rejected Player actions.
4. We implement 20 public development families and use one archived 80-episode
   block to expose practical failure surfaces. We do not treat that block as a
   confirmatory benchmark evaluation.

The contribution is the matched measurement design, not any one of its
components. Its empirical value remains an open hypothesis until the two tracks
share a final representation and the protocol is evaluated across models,
repeats, baselines, and private variants.

## 2. Related work

### Interactive rule and scientific discovery

The Wason 2–4–6 task established a simple experimental paradigm in which a
participant proposes tests and receives rule-consistency feedback (Wason,
1960). Recent LLM studies adapt this structure directly. Failing to Falsify
reports confirmation-seeking behavior in numerical rule games (Jhaveri et al.,
2026). FALSIFYBENCH scales semantic rule-discovery games to 100 curated targets
and analyzes how hypotheses relate to the hidden category across turns
(Bertolazzi et al., 2026). Auto-Bench uses deterministic Oracle interaction for
hidden causal and structural relations (T. Chen et al., 2025). Our Player–Oracle
loop is therefore not novel by itself. The relevant difference is that evidence
comes from a numerical `WorldModel`, the terminal object is an executable
predictor evaluated on held-out interventions, and the same world is presented
under two information contracts.

DiscoveryWorld provides a broader virtual laboratory with 120 tasks spanning
eight topics and evaluates task completion, relevant actions, and explanatory
knowledge (Jansen et al., 2024). Its strength is end-to-end agency in a richer
environment. Our design is intentionally smaller: controlled interventions and
paired worlds trade environmental breadth for a targeted factorial contrast.

### Prior knowledge, shifted laws, and executable prediction

PhysGym explicitly controls the amount of prior knowledge provided to agents
across interactive physics problems (Y. Chen et al., 2025). We therefore make
no priority claim for manipulating scientific priors. Our proposed
factorization differs: whether a world agrees with familiar science and whether
the target family is disclosed are crossed rather than treated as a single
information continuum.

NewtonBench introduces systematic alterations of canonical laws across 324
tasks and 12 physics domains (Zheng et al., 2025). DiscoverPhysics similarly
constructs 22 counterfactual N-body worlds, asks agents to design experiments,
and scores submitted Python laws on held-out trajectories (Wiemann et al.,
2026). LLM-SRBench tests equation discovery under transformed and synthetic
laws from fixed data (Shojaee et al., 2025). These papers establish that shifted
laws, resistance to simple memorization, and executable predictive evaluation
are already central community concerns. Our narrower question is whether the
same shifted law can be used to compare family-disclosed identification with
family-withheld induction while holding the evidence environment fixed.

### Hypothesis-guided experiments and process evaluation

Choosing experiments to discriminate between models has a long statistical
history (Atkinson and Cox, 1974). LLM-AutoSciLab operationalizes
hypothesis-conditioned acquisition in enzyme-kinetics and gene-regulatory
tasks (Kabra et al., 2026). The present protocol does not claim to invent
hypothesis-guided experimentation. It requires the Player to state numerical
forecasts for every named hypothesis before the Oracle returns evidence. This
commitment makes a limited class of transcript-level comparisons mechanically
checkable.

Process evaluation is also established. FALSIFYBENCH analyzes testing strategy
and movement through a semantic hypothesis space. Corral reports that
outcome-successful scientific-agent traces can still ignore evidence and argues
that outcomes alone do not establish scientific reasoning (Ríos-García et al.,
2026). Our process diagnostics are narrower: they compare the Player's own
forecasts with the returned measurements and its next reported support weights.
They neither recover hidden chain-of-thought nor subsume broader epistemic
practice.

## 3. Task definition

### 3.1 Two roles and one post-hoc evaluator

An episode contains a **Player** and an **Oracle**. The Player receives a public
case view: minimal background, initial observations, controls, readouts, units,
ranges, measurement resolution, experiment budget, and the track-specific
submission contract. It chooses an experiment or commits a final model.

The Oracle validates the proposed setup and returns evidence. Valid
measurements, units, and uncertainty are computed by the case's executable
`WorldModel`. A language model may serve as a presentation layer, but it cannot
add or alter measurements. This distinction matters because an LLM judge's
semantic decision is not interchangeable with a simulated physical
measurement.

The evaluator is not a third interactive role. After the Player commits—or
terminates without a valid commitment—the runtime assigns outcomes. An
optional transcript judge could be run later, but it cannot change the primary
predictive result.

### 3.2 Identification and predictive law induction

The tracks differ in what is unknown before interaction.

| Contract | Identification | Predictive law induction |
| --- | --- | --- |
| Unknown object | Parameters of a disclosed family | Functional family and parameters |
| Public model information | Formula skeleton, parameter meanings, admissible ranges | Executable representation shared across task families and a complexity bound |
| Experimental information | Controls, readouts, ranges, resolution, budget | The same |
| Final object | Parameters or equivalent executable predictor | Executable predictor |
| Primary criterion | Held-out predictive loss | Held-out predictive loss |

Selecting among a public finite list of families is constrained model
selection, which we group with identification. Conversely, predicting only at
prompted points without submitting an executable rule is active black-box
modeling rather than law induction. Neither track measures unrestricted
scientific creativity or real-world causal-mechanism discovery.

### 3.3 Observable Player commitments

At every turn the Player reports a portfolio of two to six concrete hypotheses
with unique IDs and support weights summing to one. A residual “other” category
is not accepted because it cannot be associated with a testable forecast. For
an experiment action, the Player supplies the apparatus, complete control
settings, requested readouts, replicate count, and a numerical prediction for
every requested readout under every current hypothesis. These predictions are
recorded before evidence is computed.

After receiving the evidence, the Player may retain, revise, remove, or add
hypotheses. Reusing an ID for a rewritten statement is recorded and excluded
from persistent-hypothesis update calculations. The protocol observes public
commitments only; it neither requests nor attempts to infer private
chain-of-thought.

## 4. Matched benchmark construction

### 4.1 Paired 2 x 2 design

For family \(f\), world \(w\in\{H,C\}\), and track
\(t\in\{I,D\}\), one cell is denoted \((f,w,t)\). `H` is a modern
idealized world motivated by a familiar historical relationship. `C` is a
benchmark-authored world that changes one declared mechanism coordinate while
preserving the apparatus and reference scale. The historical label does not
mean a literal reconstruction of the original experiment.

Within a world, identification and induction reuse the same `WorldModel`,
controls, readouts, budget, resolution, and held-out conditions. Only the public
model information and final contract differ. Across worlds, the case author
changes one mechanism coordinate and verifies that an allowed, budget-feasible
intervention separates both worlds at the declared resolution.

This construction supports four comparisons:

- historical minus counterfactual performance within identification;
- historical minus counterfactual performance within induction;
- identification minus induction within each world; and
- their interaction.

Let \(P_{wt}\) be the probability of unconditional held-out prediction success. We prespecify the
paired factorial contrast

\[
\Delta=(P_{HD}-P_{CD})-(P_{HI}-P_{CI}).
\]

Positive \(\Delta\) would mean that historical alignment helps more when the
family is withheld than when it is disclosed. We use the algebra of a
difference-in-differences contrast but make no parallel-trends or observational
causal claim. A prior-only baseline is required as a manipulation check: without
it, “historical” need not imply a stronger model prior.

### 4.2 Public development suite

The implementation contains 20 families spanning mechanics, waves, gases,
electromagnetism, radiation, circuits, heat transfer, optics, kinetics,
diffusion, and fluid transport. Each family contributes four cells, producing
80 public development cells. Counterfactuals use minimal changes such as a
single exponent substitution, activating one nonlinear term, or changing one
mode weight. Full formulas, domains, and historical sources are documented in
the public case catalogue.

These families establish implementation breadth, not 80 independent scientific
problems. The unit of generalization is the matched family. Moreover, all
truths and evaluator conditions ship with the repository. Results are suitable
for protocol development and planning later studies, not a contamination-resistant
leaderboard.

### 4.3 Current representation confound

The present implementation violates one requirement for a pure
family-disclosure contrast. Identification returns named parameters in a
family-specific model; induction returns a recursive expression tree. The
induction method therefore has additional representation and parsing burden. Any
observed track effect is an end-to-end contract effect, not solely the effect of
withholding the family. A confirmatory version must use one final executable
representation in both methods, with identification differing only by disclosure
of an instantiable skeleton. `[REQUIRES NEW EVIDENCE]`

## 5. Evaluation

### 5.1 Outcomes and denominators

The primary case outcome is `predictive_model_pass`: whether the committed
structured predictor meets a prespecified numerical tolerance on held-out
interventions. Algebraic identity with the author formula is not required.
Natural-language explanation and scope conditions are recorded but unscored.

Every Player-side terminal event remains in the active denominator:

- `submitted`: a protocol-valid final object is scientifically evaluated;
- `player_output_invalid`: enabled generation calls never produced a strictly
  decodable action;
- `action_rejected`: a decoded action violated an episode invariant; and
- `action_limit`: no final submission was produced within the action horizon.

We report evaluated-terminal coverage, protocol completion, unconditional
unconditional held-out prediction success, and—only as a diagnostic—success conditional on a valid
submission. Provider, storage, or evaluator-runtime failures are infrastructure
failures and retry the same prespecified schedule position.

### 5.2 Process measures based on pre-experiment predictions

For valid evidence, forecast separation is the mean pairwise relative
difference among hypotheses' numerical predictions. This is a property of the
Player's reported forecasts; it is not expected information gain and does not
compare the chosen experiment with available alternatives.

For persistent hypotheses, the runtime compares normalized forecast error with
the next reported support gap. A pair is `aligned` if support moves toward the
lower-error hypothesis, `opposed` if it moves away, and `inert` if it is
unchanged. Rewritten hypotheses and unscorable pairs are counted separately.
Because the hypotheses may overlap and their support weights are not validated
posteriors, these quantities are observable trajectory diagnostics rather than
a general score of scientific reasoning.

### 5.3 Formal evaluation boundary

A result is formal only if the active truth, evaluator, assignments, private
instances, and held-out conditions are outside the Player process. The Player
must communicate with that service solely through the serialized episode
interface. The current repository contains zero private families. A future
private service is required for formal capability claims. Ordinary ordered logs
support transcript replay; isolation supplies the relevant secrecy boundary.

## 6. Exploratory development study

### 6.1 Setup

The archived run configured 20 families, four cells per family, and five
provider-stochastic repeats, for 400 planned episodes. Only repeat 1—the first
80-cell block—completed. Both the Player and optional Oracle presentation layer
used `deepseek-v4-flash` with temperature 0, top-p 1, and thinking disabled. The
Player allowed one schema-directed regeneration after invalid output. Evidence
was always generated by the deterministic world model.

The run is not bound to the current source snapshot: it was created on
2026-08-25, while case and temporal files changed on 2026-08-26. We report it
only to illustrate the protocol and observed failure surfaces.

### 6.2 Outcomes

Of 80 episodes, 50 produced valid final submissions and 21 passed held-out
prediction. Thus unconditional success was 21/80 (26.25%), protocol completion
was 50/80 (62.5%), and conditional success was 21/50 (42.0%). Twenty episodes
ended after invalid Player output, ten after a decoded action was rejected, and
29 after a valid submission failed scientific evaluation.

| Condition | Task setting | Held-out prediction success | Valid final |
| --- | --- | ---: | ---: |
| Historical | Identification | 12/20 | 17/20 |
| Historical | Induction | 4/20 | 12/20 |
| Counterfactual | Identification | 4/20 | 11/20 |
| Counterfactual | Induction | 1/20 | 10/20 |

The descriptive interaction is \(\Delta=-0.25\). With one model, one
observation per family/cell, different track encodings, and no manipulation
check, neither its magnitude nor sign should be interpreted scientifically.

The trajectory analyzer recorded 1,331 forecast pairs and 681 scorable
persistent-hypothesis pairs: 124 aligned, 516 inert, and 41 opposed. It also
recorded 77 support shifts for tied forecasts, 19 rewritten pairs excluded from
the comparison, and 28 duplicate setups. These nested pair counts are not 681
independent experimental units.

### 6.3 Illustrative failure: relevant experiments without evidence uptake

In the counterfactual pendulum induction episode, the true period retained the
square-root length dependence but increased with bob mass. The Player measured
2.52 s at 0.5 kg, 1.69 s at 0.1 kg, and 1.42 s at 0.05 kg while holding length
at 1 m. These measurements clearly contradicted a mass-invariant rule over the
declared 0.01 s resolution. Nevertheless, the Player left its support weights
unchanged across several mass interventions and finally assigned 0.9 support to
a mass-invariant predictor. The predictor failed held-out evaluation.

This episode shows why a terminal score alone is incomplete: the transcript
localizes a mismatch between the Player's own experimental record and its final
model. It does not establish why the language model behaved this way, nor how
often the pattern occurs beyond this run.

## 7. What would constitute a valid test?

A confirmatory study should make the smallest changes needed by the estimand.
First, both tracks must use the same final predictor representation. Second,
the evaluation release, prompts, schedule, retry policy, and analysis must be
frozen before a new run. Third, a prior-only baseline must verify that historical
and counterfactual worlds elicit different pre-evidence expectations, while an
experiment-using baseline must establish solvability under the budget. Fourth,
several genuinely different Player models and prespecified repeats must be
evaluated with a fixed deterministic Oracle or fixed Oracle presentation
policy. Fifth, inference must treat family as the matched unit. Finally, process
diagnostics require blinded human validation and reliability estimates.

For a formal capability claim, the same design must then be instantiated with
private variants served outside the Player environment. The public suite should
remain a development pack rather than be relabeled private.

## 8. Limitations and broader impact

The current families are idealized low-dimensional systems. They test active
predictive modeling, not the social, instrumental, and theoretical complexity
of real science. Historical labels may correlate with many features besides
memorized formulas; the prior-only check can measure but not fully explain those
priors. Minimal counterfactuals improve matching but need not be physically
plausible theories. Deterministic evidence removes noise-management demands and
may overestimate real laboratory performance.

The protocol also rewards compliance with a structured interface. This is
appropriate when the scored object must be executable, but formatting ability
should be reported separately from scientific evaluation. Process fields can
encourage more explicit evidence tracking, yet they can also become targets for
performative self-report. They should support diagnosis, not be collapsed into
a single scientificity score.

## 9. Conclusion

Interactive law-induction benchmarks should distinguish what an agent must
infer from how the task is presented. A paired design crossing prior alignment
with model-family disclosure offers one way to do so while holding the evidence
environment fixed. The present implementation establishes that this protocol
can be executed and audited across 20 public families. It does not yet establish
the intended interaction effect. The next scientific result must come from a
common output representation, explicit baselines, multiple models and repeats,
family-level inference, and—if formal capability is claimed—private isolated
cases.

## Proposed eight-page allocation

| Section | Pages |
| --- | ---: |
| Abstract and Introduction | 1.25 |
| Related work | 0.90 |
| Task definition | 1.20 |
| Matched construction | 1.35 |
| Evaluation | 1.05 |
| Development study | 1.25 |
| Validity, limitations, conclusion | 1.00 |
| **Total** | **8.00** |
