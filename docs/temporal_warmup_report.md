# Temporal paper-to-case warm-up report

Date: 2026-08-26

Current-policy status:

- formal source-only temporal cases accepted: **0**;
- latest recorded provider-backed coordinator result: `accepted_case = null`;
- legacy rendered cases counted as current accepted cases: **0**.

## Current formal focused trials

Four single-paper cohorts have now been exercised through the formal
acquisition handoff and the source-review boundary with
`deepseek-v4-flash`.  The optional focus text only routes the extractor to one
candidate evidence cluster; the frozen TeX remains the sole scientific
authority.  These are purposive development trials, not a conversion-rate
sample.

| Formal run | Stage reached | Current-policy result |
| --- | --- | --- |
| `runs/temporal_trial_colloid_filtration_2026-07-22/warmup_supplement_cluster/` | ScienceCard + independent review | Rejected. Fixed and exponentially distributed pore lengths are real analytic branches, but the proposed card reversed the meaning of `alpha_0`, invented control/parameter values, and did not close one common numeric readout. |
| `runs/temporal_trial_spectral_form_factor_2025-01-02/warmup/` | ScienceCard generation | Rejected before review. The model correctly described the missing plateau-time/domain evidence, but its JSON encoded fixed branch settings as zero-width controls and remained schema-invalid after the one bounded validation repair. |
| `runs/temporal_trial_kibble_zurek_energy_2026-07-07/warmup/` | ScienceCard + independent review | Rejected. Both temperature fits, uncertainties, realization counts and weighted fit convention were extracted correctly, but the `10–1000` quench-time interval belongs to the vortex-count claim and cannot be borrowed for the energy fits. Realization count and fit method are statistical provenance, not hidden physical conditions. |
| `runs/temporal_trial_optical_lattices_2025-01-02/warmup/` | ScienceCard + independent review | Rejected. The 3D/1D branches and 54/220 ms lifetimes are source-reported, but frozen TeX supplies neither the initial atom-count amplitudes nor a finite common fit interval. The configurations also change several experimental conditions together, so the result cannot be presented as an isolated dimensionality effect. |

All four final run-level artifacts record `accepted_case = null`; no draft was
rendered and no current-policy temporal four-cell family was produced.  The
negative outcomes are useful evidence that the review boundary is rejecting
domain transfer, causal overinterpretation and underdetermined Oracle
responses instead of completing them from model memory.

The extractor now receives one additional explicit separation prompted by the
Kibble–Zurek review: sample size, ensemble count, aggregation, fit method and
uncertainty convention must remain claim-level statistical provenance and
must not become hidden-world fixed conditions.

After these changes, `PYTHONPATH=src:. python -m unittest discover -s tests`
passes all **289** repository tests.  A credential-prefix scan also confirms
that the runtime API key was not persisted in the project artifacts.

Two bounded source pre-screens then inspected four additional 2025 candidates
and four additional 2026 candidates; **0/8** met the same strict contract.
This purposive count is not a yield estimate.  The closest new 2026 candidate,
*Phase Separation Induces Oscillations in Negative Feedback Loops*, reports
two analytic phase-separation regimes, but its natural intervention `N` is an
integer, the finite `N=3..19` sweep is only in author companion code, and no
matching fixed-version arXiv TeX source was established.  The current
continuous-control, TeX-only path must therefore reject it rather than silently
import a second evidence source or expose nonphysical real-valued `N` queries.
This is a concrete possible future extension—author-associated source bundles
plus discrete controls—not evidence for relaxing the present acceptance rule.

## Earlier provider-backed stop-first run

This is the latest recorded real provider-backed run, not a rerun of the current
acquisition/coordinator implementation. It predates the formal `acquire`
handoff, `config.json`, `frozen_acquisition.json`, `frozen_sources/`, explicit
provider-failure disposition and adjacent four-cell validation artifacts. Its
input freezes ten purposively selected source papers
in `runs/temporal_stop_first_10_2026-08-26/cohort.json` and processes them in
that order. It is a pipeline smoke test, not a representative sample and not a
paper-to-case conversion-rate estimate. Admission now requires both an
independent paper-level source review and a post-filter family source-closure
review. The LLM's own `case_authoring_ready` field is only a hint.

The stopping rule used by that earlier run was:

```text
ordered cohort (at most 10 papers)
  → one ScienceCard proposal per paper
  → independent paper eligibility review
  → one no-retry matched draft proposal
  → strict lineage + deterministic filter
  → independent family source-closure review
  → render → deterministic four-cell known-truth Episode/evaluator canary
  → STOP at the first accepted case
```

An artifact/schema failure was attributed to that paper's model output and the
coordinator moves to the next paper. In this recorded run, a provider failure
was stored as `run_failed`. The current coordinator records `provider_failed`,
never implicitly recalls that provider stage in the same run, and requires an
explicit `--skip-provider-failure PAPER_ID` disposition or a new run directory.
Review gates pause and resume from ordinary JSON artifacts without recalling
completed model stages.

This run stopped at paper 7 because the provider connection failed before a
response was recorded. No accepted case was produced, and papers 8–10 were not
attempted. The observed outcomes are:

| Order | Paper | Outcome | Interpretation |
| ---: | --- | --- | --- |
| 1 | Kibble–Zurek turbulence | `source_review_rejected` | Parseable card, but no source-supported common numeric domain for the paired energy branches; fixed conditions, compressible-energy parameters/readout definition and uncertainty semantics were not closed. |
| 2 | Nuclear-spin cooling | `science_card_generation_failed` | Strict schema rejected a nonnumeric control maximum; this is not evidence that the paper is scientifically ineligible. |
| 3 | Colloid filtration | `science_card_generation_failed` | Strict schema rejected an invalid control interval. |
| 4 | Optical lattices | `science_card_generation_failed` | Strict schema rejected a non-ASCII-snake condition identifier. |
| 5 | Excitonic population inversion | `science_card_generation_failed` | Strict schema rejected a nonnumeric control minimum. |
| 6 | Kramers–Langer activation | `source_review_rejected` | Parseable card, but the isotope branch is only qualitative at one approximate aspect ratio and the reported Kramers–Langer expression lacks the source functions/parameters needed for an executable shared-domain response. |
| 7 | Static friction of liquid marbles | `run_failed` | Provider connection failure before any model response; the paper was not scientifically assessed by this run. |

Thus the current denominators are deliberately separate: 6 papers have a
ScienceCard-stage outcome, 2/6 produced parseable cards, 0/2 passed source
review, and 0 cases reached drafting. It would be incorrect to report the four
schema failures or the transport failure as paper-ineligibility decisions.

Primary artifacts:

- frozen ordered input: `runs/temporal_stop_first_10_2026-08-26/cohort.json`;
- run-level status: `runs/temporal_stop_first_10_2026-08-26/result.json`;
- exact requests/responses and per-paper results:
  `runs/temporal_stop_first_10_2026-08-26/papers/`;
- independent source verdicts:
  `runs/temporal_stop_first_10_2026-08-26/reviews/`.

This negative smoke result motivated improving ScienceCard generation
reliability before estimating scientific conversion yield. It did not justify
loosening numeric types, source domains, uncertainty semantics or the
source-only two-branch requirement.

## Separate Kibble–Zurek two-stage diagnostic (rejected; 0 accepted)

The Kibble–Zurek paper was rerun through the new contract with
`deepseek-v4-flash`:

```text
line-numbered paper.tex
  → private ScienceCard proposal
  → strict schema and locator checks
  → source-level scientific review
  → STOP: card rejected; accepted case count = 0
```

The run used `temperature=0`, `top_p=1`, thinking disabled, a 32,768 visible
output-token cap, and no automatic repair retry. During development, four
stage-1 calls exposed successive contract problems: source-native symbol names,
invalid claim dependencies, one truncated response, and finally a complete
schema-parseable response. The complete proposal was preserved rather than
silently edited. Its locators were in bounds, but independent comparison with
the source rejected the card for scientific reasons:

- all eight claims omitted their mechanism dependencies;
- the two total-incompressible-energy fits needed for the intended temperature
  pairing were omitted;
- two reported temperature regimes (`T=1` and `T=10^-6`) were widened into an
  unsupported continuous Player control;
- a `T=1` fixed condition was attached to claims about `T=10^-6`;
- crossing-relative equilibration delay and absolute equilibration time were
  conflated;
- a proportionality was strengthened into an equality;
- uncertainty semantics and applicability ranges were propagated beyond what
  their locators establish; and
- several readout definitions cited nearby results rather than the lines that
  operationally define the quantities.

Before that source review returned, one stage-2 diagnostic call was made from
the schema-parseable card. It is retained as diagnostic evidence, not as a
formal authoring step. The draft failed strict lineage because it cited a line
range not present in the card. Direct review also found undeclared expression
variables, identical world parameter maps, an absent private selector, leakage
of the hidden regime into Player-visible notes, and an initial observation that
already stated the answer direction. It was not repaired or rendered.

The paper does contain a potentially authorable **source-contained matched
regime**: Player varies quench time and observes total incompressible and
compressible energies, while the private world selects one of the two reported
temperature regimes. Both incompressible-energy branches decrease roughly
inversely; compressible energy is nearly invariant at `T=1` but decreases at
`T=10^-6`. A corrected card must first capture all four fits and their exact
domains and uncertainty semantics. This pairing is not a fictional synthetic
counterfactual. Under the requirement that every scientific fact come from the
paper, a paper without two compatible reported branches must be marked
`not_authorable` rather than completed with an invented mechanism.

The complete artifacts for this diagnostic are under
`runs/temporal_warmup_2026-07/papers/kibble_zurek_turbulence/authoring/`:

- `science_card/request.json` and `science_card/response.json`: exact stage-1
  exchange;
- `science_card_review.json`: source-level rejection with locators;
- `case_draft/request.json`, `response.json`, `failure.json`, and `review.json`:
  the diagnostic stage-2 exchange and rejection;
- `result.json`: final status, with zero accepted/rendered cases.

No credential is stored in these artifacts.

## Legacy monolithic warm-up result (not current-policy accepted)

The former monolithic path rendered one development artifact:

```text
PRL journal record
  → unique DOI arXiv match
  → fixed-version TeX source
  → one no-retry DeepSeek abstraction
  → strict parse and per-candidate hard filter
  → scientific source review
  → one rendered matched family
  → historical/counterfactual × identification/discovery truth checks
```

The legacy rendered family is `kz_vortex_scaling`, derived from Seong-Ho
Shinn et al., *Spontaneous Quantum Turbulence in a Newborn Bose-Einstein
Condensate via the Kibble-Zurek Mechanism*. It is accepted only for development
warm-up. It is not a private or contamination-fresh evaluation case: arXiv v1
was public in June 2025, and its virtual-world exponent is benchmark-authored.
It is therefore **not eligible under the current source-only temporal policy**;
it remains solely as a reproducible record of the earlier monolithic pipeline.
Current-policy accepted temporal case count remains zero.

This was a purposive pipeline smoke test, not the pre-registered representative
60-paper warm-up described in `temporal_case_pipeline.md`. Conversion rates
below therefore must not be reported as estimates for Nature/Science/PRL.

## Source recruitment

Two fixed census snapshots were used while locating low-dimensional quantitative
claims:

- `2025-01-02`: 22 Crossref records. Three initially selected PRL records all
  resolved to fixed arXiv versions with TeX; two additional records were
  inspected after the initial abstractions failed.
- `2026-07-01..2026-07-31`: 1,005 Crossref records. Only purposively selected
  PRL records were sent through arXiv resolution; the complete 1,005-record
  arXiv funnel was not run.

The raw census, journal/arXiv records, merged TeX sources, model-visible
requests, raw provider responses, parsed abstractions and filter outputs are in:

- `runs/temporal_warmup_2025-01-02/`
- `runs/temporal_warmup_2026-07/`

These snapshots predate the formal `acquire` command. They do not contain a real
`acquisition.json` or evidence of DOI-keyed publisher reconciliation, so they
cannot be treated as formal acquisition cohorts.

## LLM abstraction outcomes

All seven calls used `deepseek-v4-flash`, `temperature=0`, thinking disabled,
8,192 output-token limit, one call per paper and no format-repair retry. The API
credential was entered through a non-echoing runtime prompt and is absent from
the artifacts.

| Paper directory | Raw outcome | Primary reason |
| --- | --- | --- |
| `optical_lattices` | 0/1 hard-filter eligible | Machine identifiers were not lower snake case. This exposed a schema/filter mismatch, which was fixed after the call. |
| `nuclear_spin_cooling` | strict parse failure | The response used an unsupported `sqrt` operator and inconsistent parameter maps. |
| `excitonic_population_inversion` | 0/1 | Unused parameters and a diagnostic design that did not vary every declared control. |
| `fock_space_correlations` | strict parse failure | The proposed relation required unsupported Bessel, sum and product operators; it is outside the current closed-form AST. |
| `kramers_langer_activation` | 0/1 | Temperature was not varied; scientific inspection also showed that the proposed expression did not encode the declared aspect-ratio dependence. |
| `colloid_filtration` | 0/1 | Invalid readout identifier and no actual one-parameter counterfactual change. |
| `kibble_zurek_turbulence` | initially 0/4; 2/4 after justified gate correction | Two source-native one-control laws had been rejected only by an arbitrary two-control minimum. Two other proposals remained rejected. |

The raw-call success rate was therefore 0/7 papers and 0/12 proposed candidates.
This is an important negative result: JSON-object mode plus a schema in the
prompt is not constrained decoding, and the monolithic abstractor should not be
described as autonomous case generation.

## Warm-up corrections

Only contract-level corrections supported by observed failures were made:

1. The exact `PaperAbstraction` schema is now included in the provider-neutral
   prompt, because the DeepSeek JSON-object transport does not enforce the
   application schema.
2. Explicitly incomplete provider finishes are rejected before JSON parsing.
3. Lower-snake-case identifier patterns and the existing operator whitelist are
   visible in the schema and prompt.
4. The prompt states existing invariants: identical parameter key sets, one
   changed value, every parameter used, and every declared control varied in
   the diagnostic set.
5. PDF-only `/src` responses are classified as `NoTexSourceError`, not as corrupt
   tar archives.
6. The temporal control-count gate is now 1–5 instead of 2–5. A univariate law
   remains an active experiment: the Player chooses the next value of its one
   intervention variable. Forcing an unrelated second input changes the source
   claim or induces nuisance controls. This removes an arbitrary restriction;
   it is not a contribution. It is consistent with equation-discovery tasks such
   as [LLM-SRBench](https://arxiv.org/abs/2504.10415), which define inputs from
   the target equation rather than treating variable count as a validity rule.

No operator was added merely to rescue a paper, no rejected response was
silently repaired, and no source formula or domain was widened to increase the
pass rate.

## Legacy rendered development artifact

The raw Kibble-Zurek abstraction proposed four candidates. With the corrected
1–5 control contract, `kz_vortex_scaling` and `kz_equilibration_time` passed the
machine filter. Source review then rejected the latter because it conflated the
crossing-relative equilibration delay with the absolute equilibration time. The
supplement does report the linear term `0.078 tau_Q`; the error was assigning
that absolute-time expression to a crossing-relative readout, not inventing the
term.

For `kz_vortex_scaling`, the historical development review recorded:

- exact DOI linkage to arXiv `2506.21670v3`;
- the source fit `n_v = (249.036 ± 44.999) tau_q^(-0.534 ± 0.047)`;
- the reported quench-duration domain `10..1000`;
- recomputed anchor values near 73, 21 and 6 vortices at `tau_q` 10, 100 and
  1000;
- a benchmark-authored counterfactual that changes only the exponent to `-0.25`,
  outside the reported fit uncertainty; this is precisely why it fails the
  current source-only policy;
- no fitted law in the public title, background or notes;
- successful import and structured-truth evaluation in all four matched cells.

The raw response is preserved unchanged. The separate
`reviewed_abstraction.json` records the scientific-review revision, and
`source_review.json` records the evidence and limitations. This follows the
expert-validation pattern credited in the main design document; it means the
demonstrated pipeline is LLM-assisted authoring with human scientific authority,
not autonomous truth construction.

## Artifacts for the legacy rendered family

- Source and journal/arXiv identity:
  `runs/temporal_warmup_2026-07/papers/kibble_zurek_turbulence/paper.json`
- Raw LLM request, response and filter result:
  `runs/temporal_warmup_2026-07/papers/kibble_zurek_turbulence/abstraction/`
- Scientific-review revision:
  `runs/temporal_warmup_2026-07/papers/kibble_zurek_turbulence/reviewed_abstraction.json`
- Source review and anchor calculations:
  `runs/temporal_warmup_2026-07/papers/kibble_zurek_turbulence/source_review.json`
- Rendered family:
  `runs/temporal_warmup_2026-07/papers/kibble_zurek_turbulence/reviewed_cases/kz_vortex_scaling.py`
- Four-cell validation:
  `runs/temporal_warmup_2026-07/papers/kibble_zurek_turbulence/case_validation.json`

## What these runs establish—and what they do not

Established: the repository can acquire a real published paper, bind it to a
fixed TeX source, preserve real LLM proposals, represent locator-linked evidence,
separate evidence extraction from case design, and reject both a structurally
valid but scientifically unsupported card and an invalid downstream draft. The
legacy path also demonstrates deterministic rendering and four-cell execution,
but not compliance with the current source-only policy.

Not established: representative conversion yield, autonomous extraction,
publisher-complete census, contamination resistance, or readiness for a formal
leaderboard. Those claims require the pre-registered full warm-up and a private
rotating cohort.
