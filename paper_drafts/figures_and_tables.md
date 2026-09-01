# Figure and table plan

The priority labels refer to Draft A, the recommended manuscript nucleus. A
figure should be drawn only after its source run is bound to the evaluated code
release. Current archived counts may be used in a visibly marked exploratory
mock-up, not silently promoted to the final empirical figure.

## Main-text figures

### Figure 1 — What is matched, and what is manipulated (required)

**Form:** a 2 x 2 grid with rows `historical` and `counterfactual`, columns
`identification` and `discovery`. A shared apparatus block below each row points
to the same `WorldModel`, controls, budget, evidence, and held-out interventions.
The identification cells show a disclosed parameterized skeleton; the discovery
cells show only a family-neutral expression interface. Highlight the one
mechanism coordinate changed between historical and counterfactual worlds.

**Message:** prior alignment and whether the family is disclosed are distinct
design axes. The figure must also contain a warning badge that current final
encodings differ across columns, so the column contrast is not yet a pure
family-disclosure effect.

**Source:** case specs and `docs/evaluation_policy.md`, lines 114–143.

### Figure 2 — Observable episode protocol (required)

**Form:** a horizontal sequence:

`public EpisodeView → named hypotheses + support weights → proposed experiment + per-hypothesis forecasts → WorldModel evidence → revised portfolio → ... → executable predictor → deterministic held-out evaluation`.

Place the optional Oracle language layer between WorldModel response and Player,
with a thin arrow showing that it can paraphrase but not create measurements.
Place process analysis below the transcript and outside the interaction loop.

**Message:** the benchmark records observable commitments before evidence and
keeps the post-hoc evaluator out of the Player–Oracle interaction.

**Source:** `models.py`, `protocols.py`, `episode.py`, `trajectory.py`.

### Figure 3 — Development outcomes by cell and terminal category (required after rerun)

**Form:** two panels. Panel A is a four-cell dot-and-interval plot of
unconditional active-pass rates, with family as the analysis unit. Panel B is a
stacked bar for each cell showing `pass`, `scientific failure`, `action rejected`,
and `player output invalid`. Display raw counts next to every mark.

**Message:** protocol completion and scientific prediction are separate failure
surfaces. The denominator includes Player-side format and protocol failures.

**Current mock-up values:** HI 12/20, HD 4/20, CI 4/20, CD 1/20; only one repeat
and one model, so no confirmatory interval or significance marker is permitted.

**Final source required:** a new frozen-release run with prespecified models and
repeats. Do not mix the archived 2026-08-25 block with that run.

### Figure 4 — A forecast-grounded evidence-use vignette (optional for Draft A, required for Draft B)

**Form:** transcript timeline for
`pendulum__counterfactual__discovery__r01`. The top panel shows mass settings and
measured period; the middle panel shows each named hypothesis's forecast; the
bottom panel shows reported support weights and the final predictor. Annotate
the measurements at length 1 m: period 2.52 s at 0.5 kg, 1.69 s at 0.1 kg, and
1.42 s at 0.05 kg. The final mass-invariant law receives 0 on held-out
prediction.

**Message:** an agent can design relevant interventions yet fail to incorporate
their evidence into its stated hypotheses and final predictor.

**Risk:** one vignette illustrates a failure mode but cannot estimate its
frequency or establish a cognitive mechanism.

### Figure 5 — Outcome and process are different axes (Draft B only, after validation)

**Form:** each episode is a point with held-out prediction outcome on one axis
and a validated evidence-use score on the other, faceted by track and world.
Marginal bars show unscorable coverage.

**Message:** successful prediction need not imply an evidence-responsive
trajectory, and a well-updated trajectory may still fail numerically.

**Blocker:** the current process metric has no external validation. Do not draw
this as a main result until blinded human coding and inter-rater reliability are
available.

### Figure 6 — Source-grounded temporal authoring funnel (Draft C only)

**Form:** `journal census → arXiv identity resolution → fixed TeX → ScienceCard
proposal → independent source review → matched draft → deterministic filter →
family source review → render`. At each transition distinguish metadata rules,
LLM proposal, deterministic checks, and scientific-review authority by color.

**Message:** language models propose structured abstractions; they do not decide
source truth or case eligibility.

**Current result annotation:** 10 papers frozen; 6 ScienceCard outcomes; 2
parseable; 0 source-review passes; transport stopped before paper 7 response;
0 drafts and 0 accepted current-policy cases.

## Main-text tables

### Table 1 — Nearest-work comparison (required)

Rows: FALSIFYBENCH, DiscoveryWorld, Auto-Bench, PhysGym, NewtonBench,
LLM-AutoSciLab/ActiveSciBench, DiscoverPhysics, Corral, and this project.

Columns:

1. environment and evidence source;
2. active experiment selection;
3. manipulation of prior information;
4. counterfactual/shifted laws;
5. final executable predictor and held-out prediction;
6. forecast-grounded process record;
7. matched prior-alignment x family-disclosure design.

The caption must state that most individual components already exist and that
the proposed contribution is the matched combination, whose diagnostic value
remains to be established empirically.

### Table 2 — Task and score contract (required)

Side-by-side identification and discovery definitions: unknown object, public
model information, private information, final representation, primary outcome,
and optional diagnostics. Add a final row stating that current output
representations differ and must be unified for a pure disclosure contrast.

### Table 3 — Development-run accounting (required for any empirical draft)

Rows: scheduled, evaluated terminal, valid final, active pass, generation
failure, protocol rejection, scientific failure. Columns: overall and four
cells. Report counts before percentages and include the one-format-regeneration
profile in the caption.

### Table 4 — Technical validity checklist (recommended)

Rows: current-source release, behavioral replay, multiple Player models,
prespecified repeats, prior-only baseline, experiment-using baseline, common
final encoding, private isolation, process-label validation. Columns: current
status, required for which claim, and planned evidence. This makes the paper's
claim boundary easy to audit.

## Appendix figures and tables

- **Per-family outcome matrix:** 20 rows x four cells, with terminal category
  and pass; never treat the 80 cells as independent families.
- **Family catalogue:** domain, controls, readouts, budget, historical relation,
  and the single changed counterfactual coordinate.
- **Prompt and schema summary:** public Player prompt, strict action schema, and
  discovery expression grammar; full machine-readable forms remain in code.
- **Trajectory coverage:** forecast pairs, scorable update pairs, rewritten
  pairs, tied-forecast shifts, duplicate setups, and episodes with zero coverage.
- **Replay/version statement:** source release ID, model IDs, prompts, provider
  settings, retry rule, order, and infrastructure-failure policy. A readable
  release record is sufficient; no cryptographic machinery is proposed.
- **Temporal rejection disposition:** separate schema-generation failure,
  scientific source rejection, deterministic filter rejection, reviewer pause,
  and infrastructure failure. These categories must never be collapsed into
  “paper was not authorable.”

