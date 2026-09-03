# Process Evaluation of LLM-Based Scientific Agents Using Pre-Experiment Predictions

**Working paper draft B — process-evaluation alternative.** This framing should
not be submitted until the proposed diagnostics have been validated against
independent human annotations and evaluated across models.

## Abstract

Scientific-agent benchmarks commonly score a final answer, program, or task
outcome. A correct endpoint, however, does not show whether an agent designed an
informative experiment or changed its model in response to the resulting
evidence. Conversely, free-form rationales are difficult to score reliably and
need not reveal the process that produced an answer. We study a middle ground:
observable commitments made before and after an experiment. Before evidence is
returned, a Player must name at least two concrete hypotheses, assign support
weights, and forecast every requested readout under every hypothesis. After
evidence is returned, the next portfolio exposes whether those public
commitments changed. An executable world model, rather than a language model,
determines the measurements. We define narrow deterministic diagnostics for
forecast separation, evidence-aligned movement of support, hypothesis rewrite,
and duplicate experiments, while keeping them separate from held-out predictive
success. In an archived exploratory run of 80 public development episodes with
one model, 681 persistent-hypothesis pairs were scorable: 124 moved toward the
lower-error hypothesis, 516 were unchanged, and 41 moved away. A detailed
pendulum episode shows an agent performing repeated mass interventions yet
submitting a mass-invariant law contradicted by its own measurements. These
observations demonstrate the value of logs containing pre-experiment predictions for failure
localization, but not a validated measure of scientific reasoning: support
weights are self-reports, pairs are nested within episodes, and the run has one
model and one repeat. We specify the human-validation and experimental design
needed to turn the protocol into a defensible process evaluation.

## 1. Introduction

What evidence supports the claim that an AI agent reasoned scientifically? A
correct final result is insufficient. It may reflect recall, a supplied model
family, fortunate exploration, or a reasoning process that ignored inconvenient
measurements. A fluent explanation is also insufficient: it can be written
after the answer is chosen, and language-model judges may reward plausibility
without testing whether the explanation tracks the actual experimental record.

This problem is visible across scientific-agent research. DiscoveryWorld scores
task completion, relevant actions, and explanatory knowledge rather than using
only one endpoint (Jansen et al., 2024). FALSIFYBENCH relates turn-level
hypotheses and tests to a hidden semantic rule and finds that negative testing
is associated with success (Bertolazzi et al., 2026). Corral analyzes more than
25,000 scientific-agent runs and reports substantial separation between outcome
performance and evidence-responsive behavior (Ríos-García et al., 2026).
LLM-AutoSciLab makes hypotheses explicit and uses them to guide data acquisition
(Kabra et al., 2026). We therefore do not claim that process evaluation,
hypothesis-driven experiments, or outcome–process separation is new.

We ask a narrower measurement question: **what is the smallest public record
that makes one step of evidence use mechanically auditable?** Our answer is an
ex-ante numerical forecast associated with each current hypothesis, followed by
an ex-post report over hypotheses with stable identities. If hypotheses predict
different measurements, the returned evidence provides an observable basis for
preferring one over another. The evaluator need not reconstruct hidden
chain-of-thought or decide whether a retrospective narrative sounds scientific.

This design captures only part of scientific reasoning. Hypothesis generation
is often abductive, turning candidate explanations into forecasts is deductive,
generalizing from repeated observations is inductive, and rejecting a failed
alternative is falsificatory. We use these standard terms rather than labeling
the complete loop exclusively abductive or inductive. The protocol measures
recorded commitments at the prediction-and-update boundary; it does not claim
to identify a model's private cognitive operation.

The paper makes four scoped contributions:

1. a strict interaction record linking named hypotheses, support weights,
   experiments, and per-hypothesis numerical forecasts before evidence;
2. an evidence boundary in which a deterministic `WorldModel` produces
   measurements and an optional Oracle LLM can only present them;
3. deterministic, coverage-aware diagnostics of forecast separation and
   support movement that remain separate from held-out predictive success; and
4. an exploratory failure analysis over 80 public development episodes,
   accompanied by an explicit validation agenda.

The intended contribution is an auditable protocol, not a scalar
“scientific-reasoning score.”

## 2. Related work

### Outcome-based scientific-agent evaluation

Scientific-agent environments evaluate diverse endpoints. DiscoveryWorld uses
task completion, action relevance, and explanatory knowledge (Jansen et al.,
2024). NewtonBench evaluates recovery of altered physical laws through
interactive simulation (Zheng et al., 2025). DiscoverPhysics asks for both a
Python law and natural-language explanation, scoring held-out trajectory error
and rubric-based explanation quality (Wiemann et al., 2026). LLM-SRBench scores
symbolic equation recovery under transformed and synthetic problems (Shojaee
et al., 2025). These endpoints test useful capabilities, but do not by
themselves localize when evidence ceased to influence an agent's public model.

Our primary endpoint remains held-out prediction. The process record is a
separate diagnostic layer. This separation avoids allowing a plausible process
score to rescue a wrong predictor or allowing a correct predictor to erase
clear transcript-level contradictions.

### Experimental strategy and falsification

The logic of testing alternatives predates LLM agents. Wason's rule-discovery
task exposed systematic confirmation-seeking (Wason, 1960), and optimal design
has long studied experiments that discriminate between models (Atkinson and
Cox, 1974). Failing to Falsify and FALSIFYBENCH apply related ideas to language
models (Jhaveri et al., 2026; Bertolazzi et al., 2026). Our forecast-separation
diagnostic is more limited than an optimal-design criterion: it measures only
how different the Player's stated predictions were at the selected experiment.
It does not evaluate unchosen experiments, compute expected information gain,
or know whether the hypothesis set is adequate.

### Process and rationale evaluation

Natural-language rationales can expose useful information but introduce
semantic ambiguity and judge dependence. Corral instead codes broader
epistemic patterns across observable agent trajectories (Ríos-García et al.,
2026). FALSIFYBENCH analyzes the set relationship between a current hypothesis
and the hidden rule (Bertolazzi et al., 2026). Our environment cannot generally
map free-form physical hypotheses to formal sets. We therefore exploit the
narrow numerical commitment shared by an experiment and its evidence. This
choice increases mechanical reproducibility at the cost of construct breadth.

## 3. Protocol

### 3.1 Player, Oracle, and evidence authority

The Player receives public case information and a transcript of previous
experiments. The Oracle validates each setup and returns an ordinary structured
response. A private executable `WorldModel` determines valid measurements,
units, and uncertainty. If an Oracle language model is used, it receives the
authoritative response and returns only a concise presentation message. It is
not permitted to invent readings, infer hidden facts, or score the Player.

Evaluation occurs after the interaction. The primary evaluator runs the final
structured predictor on held-out interventions. A future transcript-aware LLM
judge may add separately named process dimensions, but it must not alter
predictive pass.

### 3.2 Hypothesis portfolio

Each Player action includes two to six hypotheses. Hypothesis \(h\) has a
stable ID, a concise testable statement, and a reported support weight
\(c_h\in[0,1]\), with \(\sum_h c_h=1\). The schema disallows a residual
`OTHER` item: every alternative that affects a decision must be stated concretely
enough to forecast an allowed measurement.

The weights are not assumed to be posterior probabilities. Natural-language
hypotheses may overlap and need not cover the full possibility space. We use
“reported support” throughout and reserve “belief update” for the name of an
implementation field, not a claim of Bayesian semantics.

### 3.3 Ex-ante forecasts

For experiment \(x_t\) with requested readouts \(R_t\), every current
hypothesis must provide a finite prediction \(\hat y_{t,h,r}\) for every
\(r\in R_t\). The runtime validates the hypothesis and readout keys before the
Oracle computes \(y_{t,r}\). This ordering creates the minimal record needed to
ask whether the evidence favored one public alternative over another.

A valid experiment produces the tuple

\[
(H_t, c_t, x_t, \hat y_t, y_t, H_{t+1}, c_{t+1}),
\]

where \(H_{t+1}\) may add, remove, or rewrite hypotheses. If an ID is reused
with a changed statement, the pair is counted as a rewrite rather than a
confidence update for the same hypothesis.

## 4. Deterministic diagnostics

### 4.1 Forecast separation

For two hypotheses \(i,j\) and readout \(r\), the implementation computes

\[
d_{tijr}=\frac{|\hat y_{t,i,r}-\hat y_{t,j,r}|}
{\max(|\hat y_{t,i,r}|,|\hat y_{t,j,r}|,\rho_r,\epsilon)},
\]

where \(\rho_r\) is the public measurement resolution. The episode's
`experiment_discriminativeness_mean` is the mean over valid experiments,
readouts, and hypothesis pairs.

The implementation key predates the present terminology. The quantity is
better described as **selected-experiment forecast separation**. A high value
does not show that the experiment was optimal, that its predictions were
calibrated, or that it distinguishes the unknown true model. All hypotheses
could be wrong together.

### 4.2 Evidence-aligned support movement

For a persistent hypothesis \(h\), normalized forecast error is averaged over
the experiment's observed readouts:

\[
e_{t,h}=\frac{1}{|R_t|}\sum_{r\in R_t}
\frac{|\hat y_{t,h,r}-y_{t,r}|}
{\max(|\hat y_{t,h,r}|,|y_{t,r}|,\rho_r,\epsilon)}.
\]

For each persistent pair with unequal error, let the lower-error hypothesis be
favored. We compare its support gap relative to the other hypothesis before and
after evidence. A larger gap is `aligned`, a smaller gap is `opposed`, and an
unchanged gap is `inert`. The aggregate implementation score assigns 1, 0, and
0.5 respectively. We always report the underlying counts because an average
can conceal both coverage and qualitatively different behavior.

Pairs are excluded when either hypothesis disappears, when the same ID is
rewritten, when evidence is nonnumeric, or when no post-evidence portfolio is
available. Changes between tied-error hypotheses are counted separately as
unsupported under this narrow forecast comparison. Duplicate experimental
setups are also recorded.

### 4.3 Failure localization

A separate post-hoc analyzer locates observable failures across action
generation, protocol, stopping and commitment, evidence update, final model
specification, and held-out generalization. It preserves event indices and
compares predictions only with evidence already shown to the Player. The label
“first observed misstep” is temporal: it is not a claim about a hidden root
cause.

### 4.4 Outcome separation

The primary score is binary held-out predictive pass. Protocol completion is a
separate binary variable. Invalid JSON, rejected actions, and action-limit
termination remain zeros in the denominator of unconditional held-out prediction success. The
process diagnostics neither add to nor subtract from predictive success.

This produces a multi-axis report rather than a composite score:

| Axis | Question | Authority |
| --- | --- | --- |
| Held-out prediction success | Did the final executable model predict held-out interventions within tolerance? | Deterministic evaluator |
| Protocol completion | Did the Player produce a valid committed final object? | Episode state machine |
| Forecast separation | Did stated hypotheses predict different values at the chosen experiment? | Deterministic transcript function |
| Support movement | Did the next stated support gap move toward the lower-error forecast? | Deterministic transcript function |
| Semantic process quality | Was the broader strategy scientifically appropriate? | Not currently scored; requires validated judge/human rubric |

## 5. Development suite and exploratory run

### 5.1 Cases and run configuration

The public suite contains 20 idealized families. Each is instantiated in a
historical and minimally modified counterfactual world, and in a family-disclosed
identification track and a family-withheld induction track. The resulting 80
cells are part of a public development set; the data-generating process and held-out conditions are
available in source.

The archived run planned five repeats but completed only its first 80-cell
block. Player and Oracle presentation both used `deepseek-v4-flash`,
temperature 0, top-p 1, and thinking disabled. The Player could make one
format-regeneration call. The run predates the current source snapshot, so all
results below are exploratory historical artifacts.

### 5.2 Endpoint accounting

Fifty of 80 episodes produced a valid final submission and 21 passed held-out
prediction. Twenty ended after enabled generation calls failed strict decoding;
ten ended when a decoded action violated the protocol; and 29 submitted an
evaluable but scientifically failing model. These counts show why conditional
accuracy alone is insufficient: reporting 21/50 would omit 30 Player-side
terminal failures that occurred under the tested policy.

### 5.3 Aggregate observable updates

Across the 80 episodes, 1,331 forecast pairs were recorded. Of 681 scorable
persistent-hypothesis pairs, 124 were aligned, 516 inert, and 41 opposed. A
further 77 shifts involved tied forecast errors under the implemented
normalization, 19 pairs were excluded after hypothesis rewrites, and 28 setups
duplicated an earlier experiment in the same episode.

The dominant `inert` count is descriptively striking, but several alternative
explanations remain. A Player may use an evidence interpretation not expressed
by its numerical forecasts; support values may be poorly calibrated or copied
between turns; a hypothesis statement may be too broad for one readout; and
pairs within the same episode are highly dependent. We therefore do not perform
a pair-level significance test or infer a population rate of evidence neglect.

## 6. Case study: mass dependence observed, then omitted

In one counterfactual pendulum induction episode, the period follows the
familiar square-root length relation but has a positive mass exponent. The
Player initially proposed three alternatives: length-only, inverse mass
dependence, and angle dependence. At length 1 m and angle 5 degrees, it measured
2.52 s for a 0.5 kg bob, 1.69 s for 0.1 kg, and 1.42 s for 0.05 kg. The differences
were much larger than the 0.01 s measurement resolution.

The experiments were relevant: changing mass while holding length and angle
fixed directly tested mass invariance. Yet the Player repeatedly kept support
at 0.6 for the mass-invariant hypothesis after the later mass measurements. It
finally raised that hypothesis to 0.9 and submitted
\(T=2.52\sqrt{L}\), with no mass term. The held-out evaluator rejected the
predictor. The trajectory analyzer reported zero aligned pairs, seven inert
pairs, and one opposed pair for the episode.

This vignette separates three observations that an endpoint alone would merge:
the Player chose interventions relevant to mass, observed a repeatable mass
effect, and failed to represent that effect in the terminal law. The log does
not reveal whether this arose from prior anchoring, arithmetic error, deficient
hypothesis generation, or another internal cause.

## 7. Validation study required for a process claim

The current diagnostics should be treated as candidate measurements. A
defensible validation requires at least four components.

**Construct annotation.** Independent reviewers should label whether each
experiment could discriminate the stated hypotheses, whether the evidence
favored an alternative, whether the subsequent public update was reasonable,
and whether the final model was consistent with observed evidence. The rubric
must explicitly distinguish a hypothesis rewrite from an update.

**Reliability and coverage.** Report inter-rater agreement, adjudication rate,
and the fraction of turns that both human and deterministic methods can score.
High agreement on a selected easy subset is insufficient.

**Convergent and discriminant validity.** Test whether deterministic labels
agree with human process-evaluation labels while remaining distinct from JSON
validity, token count, experiment count, and terminal success. Compare against
simpler baselines such as “support changed at all” and textual overlap.

**Predictive utility across models.** With model, family, and repeat treated as
separate levels, ask whether process measures based on pre-experiment predictions explain held-out failure
or expert process ratings beyond protocol completion. The analysis must use
episode- or family-level resampling rather than treating hypothesis pairs as
independent observations.

`[REQUIRES NEW EVIDENCE]`

## 8. Limitations and conclusion

The protocol makes strategic self-report mandatory. A capable model could
produce forecasts that look disciplined without using them internally, and a
less articulate model could reason well while reporting imprecisely. Requiring
forecasts also changes the task rather than passively observing an unprompted
agent. Numeric forecast comparison fits controlled simulators but not all
scientific claims. Finally, a deterministic rule cannot evaluate whether the
hypothesis set contains the right mechanism or whether an unchosen experiment
would have been better.

These limitations motivate a modest conclusion. Ex-ante forecasts create a
useful audit trail between hypothesis, experiment, evidence, and the next
public model state. In the present development run, that audit trail localizes
failures that terminal prediction alone does not explain. It has not yet been
validated as a general measure of scientific reasoning. The next contribution
must be empirical validation across human coders, models, families, and repeated
runs—not a more elaborate composite score.

## Proposed eight-page allocation

| Section | Pages |
| --- | ---: |
| Abstract and Introduction | 1.30 |
| Related work | 0.90 |
| Protocol | 1.20 |
| Diagnostics | 1.55 |
| Development study | 1.05 |
| Case study | 0.75 |
| Validation, limitations, conclusion | 1.25 |
| **Total** | **8.00** |
