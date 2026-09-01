# Adversarial review loop

Target standard: an eight-page ICML/NeurIPS/ICLR main-conference paper. Overall
status is `ACCEPTABLE` only if all three independent review lenses return
`ACCEPTABLE` for the same manuscript and evidence package.

Because this side conversation cannot launch subagents, the three reviews below
were performed as explicitly separated passes with non-overlapping primary
criteria. They should be replaced by genuinely independent reviewers before a
submission decision.

## Writing pass before review

The drafts already incorporate the writing-fixable objections most likely to
arise:

- no “first,” “novel scientific reasoner,” “contamination resistant,” or
  state-of-the-art claim;
- direct comparison with FALSIFYBENCH, PhysGym, NewtonBench,
  LLM-AutoSciLab/ActiveSciBench, DiscoverPhysics, DiscoveryWorld, and Corral;
- public development results clearly separated from formal private evaluation;
- all denominators and terminal categories reported;
- the current identification/discovery encoding mismatch placed in the main
  text;
- trajectory quantities described as narrow observable diagnostics rather than
  hidden reasoning, Bayesian posteriors, or expected information gain;
- the archived 80-cell block described as exploratory and not bound to the
  current source release;
- the current temporal authoring result reported as zero accepted cases.

These revisions improve honesty and readability but cannot create missing
experimental evidence.

## Reviewer 1 — novelty and positioning

**Verdict: NOT ACCEPTABLE (technical/evidentiary blocker).**

### Strengths

- Draft A identifies a crisp design question: cross prior alignment with whether
  the correct model family is disclosed while matching the evidence environment.
- The related-work discussion does not erase direct predecessors. In particular,
  it acknowledges that PhysGym controls prior information, NewtonBench shifts
  laws, DiscoverPhysics scores executable laws on held-out trajectories, and
  FALSIFYBENCH studies Player–Oracle rule discovery and negative testing.
- The identification/discovery distinction is operational rather than
  rhetorical.

### Blocking concerns

1. The central claimed factor is not isolated in the implementation. The two
   tracks differ both in family disclosure and final representation: named
   parameters versus a recursive expression tree. A performance interaction may
   be caused by representation or schema burden.
2. No experiment shows that the proposed 2 x 2 combination yields diagnostic
   information unavailable from PhysGym- or NewtonBench-style analyses. A design
   diagram alone is not an empirical contribution at the target venues.
3. Draft B's forecast-grounded trace is useful but insufficiently differentiated
   from prior process analyses, especially FALSIFYBENCH and Corral, until it is
   validated and shown to predict or explain failures beyond simpler transcript
   features.
4. Draft C has an intelligible source-grounding boundary, but staged extraction,
   deterministic filtering, and expert review are inherited ideas. With zero
   current-policy accepted cases, the proposed combination is not yet a
   demonstrated method.

### Writing-only requests

- Keep “predictive law induction” rather than using “discovery” as a blanket
  label.
- State the nearest-work comparison in the introduction rather than relying on
  a table.
- Retain one sentence explaining that the complete reasoning loop includes
  hypothesis generation, deductive prediction, and inductive updating; do not
  argue that it is exclusively abductive.

The drafts already implement these requests. The blocking items require design
changes and experiments, so further prose iteration cannot make this reviewer
acceptable.

## Reviewer 2 — construct validity and methodology

**Verdict: NOT ACCEPTABLE (technical/evidentiary blocker).**

### Strengths

- Primary prediction, protocol completion, and process diagnostics are separated.
- Player-side invalid actions remain in the full denominator.
- Oracle measurements are authoritative `WorldModel` outputs, avoiding an LLM
  judge as the source of numerical evidence.
- The formal threat model is small and relevant: keep active truth and scoring
  outside the Player process and use a serialized interface.

### Blocking concerns

1. The existing 80-cell run uses public truths and held-out conditions stored in
   the same repository. It cannot support a formal capability estimate.
2. The study has one Player model and one completed repeat. It cannot separate
   model-specific behavior, provider stochasticity, family heterogeneity, or
   order effects.
3. There is no prior-only baseline to test whether historical labels actually
   induce stronger priors, and no legitimate experiment-using baseline to show
   that success requires using returned evidence.
4. The intended unit of generalization is the matched family, not individual
   cells or forecast pairs. The current sample is too small for a reliable
   factorial interaction, and the analysis plan has not been executed on an
   independent run.
5. Support weights are model self-reports over natural-language hypotheses that
   need not be exclusive or exhaustive. The current evidence-alignment measure
   is therefore a diagnostic of recorded commitments, not a validated measure
   of belief revision or scientific reasoning.
6. The repair-enabled Player profile changes the generation policy and must not
   be pooled with a no-repair baseline without explicit treatment.

### Writing-only requests

- Report unconditional success before conditional-on-submission success.
- Never use confidence intervals that assume 80 independent cases.
- Explain why same-model Player and Oracle presentation do not make the Oracle's
  numbers subjective, while still reporting the shared-provider trust
  assumption.

The drafts implement these requests. The six blocking concerns require new
implementation and data.

## Reviewer 3 — empirical sufficiency, reproducibility, and clarity

**Verdict: NOT ACCEPTABLE (technical/evidentiary blocker).**

### Strengths

- The paper alternatives are readable and make their estimands explicit.
- Exact counts are recoverable from ordinary JSONL/result files.
- The counterfactual-pendulum vignette is a clear example of why outcome-only
  evaluation misses a useful failure pattern.
- The current code passes 226 unit tests in the inspected environment.

### Blocking concerns

1. The configured 400-episode study stopped after the first 80-cell block. The
   resulting cell rates have one observation per family/cell and are not a
   completed experiment.
2. That run predates current case/source changes and lacks a readable release ID
   binding it to the current implementation. Unit tests on current code do not
   make the old episode outcomes current.
3. The paper lacks a current-source behavioral replay and an independently
   reproduced run. Exact JSONL logging is necessary but not sufficient for
   reproducibility across hosted API behavior.
4. Draft B aggregates 681 hypothesis-pair updates as though they were a large
   evidence base, but those pairs are nested within 80 episodes and 20 families.
   They cannot substitute for independent experimental units.
5. Draft C's latest run processed only part of a purposive cohort, produced no
   accepted case, and ended on infrastructure failure. It supports a failure
   analysis, not a general authoring result.

### Writing-only requests

- Put the “archived exploratory run” qualifier in the abstract whenever its
  numbers appear.
- Use one compact table rather than a narrative list of all 20 families in the
  main text.
- Move transport details and full schemas to the appendix.

The drafts implement these requests. The first five concerns cannot be fixed by
editing.

## Loop decision

| Review lens | Verdict | Can writing alone resolve it? |
| --- | --- | --- |
| Novelty and positioning | NOT ACCEPTABLE | No |
| Construct validity and methodology | NOT ACCEPTABLE | No |
| Empirical sufficiency and reproducibility | NOT ACCEPTABLE | No |
| **Overall** | **NOT ACCEPTABLE** | **Stop the writing-only loop** |

The loop terminates under the user's technical-defect exception. Continuing to
rewrite until the labels change would conceal missing evidence rather than
improve the science.

## Smallest path to restart the loop

1. Unify the final predictor representation across tracks.
2. Freeze a readable release and complete a new 80-cell smoke run with replay.
3. Add prior-only and experiment-using baselines.
4. Run prespecified repeats across several genuinely different Player models
   with a fixed deterministic Oracle or fixed Oracle presentation profile.
5. Validate process labels against blinded human annotations.
6. Only if claiming formal capability, add a private isolated pack.

After those data exist, revise Draft A first and submit the same version to all
three review lenses again. Draft B should be reconsidered only if process-label
validation is strong; Draft C only after the current source-only pipeline yields
a representative accepted cohort.

