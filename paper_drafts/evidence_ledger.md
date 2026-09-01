# Evidence ledger for manuscript drafting

Snapshot date: 2026-08-26. This ledger is the claim boundary for all manuscript
variants in this directory.

## A. Established by the current implementation

| ID | Defensible statement | Evidence | Allowed wording |
| --- | --- | --- | --- |
| A1 | The main episode has two roles: a tested Player and an Oracle. Evaluation occurs after a Player terminal outcome and is not an interactive role. | `src/role_benchmark/protocols.py`, `src/role_benchmark/episode.py`; `docs/evaluation_policy.md` | “The interaction comprises a Player and an Oracle; deterministic evaluation is post hoc.” |
| A2 | Valid numerical evidence is computed by a case `WorldModel`; an optional Oracle LLM can only present the authoritative response. | `src/role_benchmark/protocols.py`; `src/role_benchmark/llm_oracle.py`; evaluation policy, lines 293–299 | “Evidence is grounded in an executable world model rather than generated freely by the Oracle LLM.” |
| A3 | The public registry contains 20 matched families, each instantiated as historical/counterfactual x identification/discovery, for 80 public development cells. | `docs/evaluation_policy.md`, lines 114–125; `docs/case_catalog.md` | “The public development suite contains 20 matched families and 80 cells.” |
| A4 | Identification discloses the model family and asks for unknown parameters; discovery withholds the truth-specific family and requires an executable predictor in a common expression representation. | `docs/evaluation_policy.md`, lines 74–112 | Use the standard descriptions “fixed-family active system identification” and “predictive law induction with the family withheld.” |
| A5 | Within a world, both tracks share the truth, `WorldModel`, measurement contract, budget, and held-out interventions. | `docs/evaluation_policy.md`, lines 127–131 | “The evidence environment is matched within each world.” |
| A6 | The present tracks do not isolate family disclosure alone because identification submits named parameters while discovery submits an expression tree. | `docs/evaluation_policy.md`, lines 132–135 | Must be stated as a design limitation, not hidden in an appendix. |
| A7 | The primary deterministic outcome is `predictive_model_pass`, based on numerical prediction at held-out interventions. Natural-language explanation and scope are currently unscored. | `docs/evaluation_policy.md`, lines 151–185 | “Primary outcome: held-out predictive pass.” Never use the removed name `explanation_correct`. |
| A8 | Every experiment action contains at least two named hypotheses and an ex-ante numeric forecast for every requested readout under every current hypothesis. `OTHER` is disallowed. | `src/role_benchmark/models.py`; `src/role_benchmark/llm.py`; evaluation policy, lines 34–38 and 193–197 | “The protocol records explicit competing hypotheses and forecasts before evidence is returned.” |
| A9 | Outcome, protocol completion, forecast separation, and evidence-aligned support movement are separate quantities; process diagnostics do not alter predictive pass. | `src/role_benchmark/trajectory.py`; evaluation policy, lines 187–212 and 237–271 | Do not call forecast separation expected information gain or confidences Bayesian posteriors. |
| A10 | The current formal private pack contains zero families and zero cells. Formal use requires the active truth, evaluator, and held-out conditions to remain outside the Player process. | `docs/evaluation_policy.md`, lines 273–299 | “Public development evaluation,” never “formal/private benchmark result.” |
| A11 | The provider-neutral adapter, strict action decoding, ordinary JSONL events, and replay paths are implemented. | `src/role_benchmark/llm.py`, `wire.py`, `runlog.py`, `runner.py`; `README.md` | These are implementation properties, not the paper's scientific novelty. |
| A12 | On this snapshot, `PYTHONPATH=src python3 -m unittest discover -s tests -q` ran 226 tests successfully. | Local verification on 2026-08-26 | “The current implementation passes 226 unit tests.” This does not establish benchmark validity. |

## B. Observed in the archived 20-family development run

Source directory: `runs/deepseek_20_family_80_20260825/`.

The configuration scheduled 20 families x 2 worlds x 2 tracks x 5 repeats =
400 episodes. Only the first 80-cell repeat block was completed. Both Player and
Oracle presentation used `deepseek-v4-flash`, temperature 0, top-p 1, thinking
disabled; the Player profile allowed one format-regeneration attempt. The
Oracle LLM did not determine measurements.

| Quantity | Count | Rate |
| --- | ---: | ---: |
| Evaluated terminal outcomes | 80 / 80 completed cells | 100% of the completed block |
| Protocol-valid submissions | 50 / 80 | 62.5% |
| Unconditional active passes | 21 / 80 | 26.25% |
| Passes conditional on a valid submission | 21 / 50 | 42.0% |
| Player output invalid after enabled calls | 20 / 80 | 25.0% |
| Decoded action rejected by protocol | 10 / 80 | 12.5% |
| Valid submission failing scientific evaluation | 29 / 80 | 36.25% |

Cell-level unconditional outcomes:

| World | Track | Pass / 20 | Protocol-valid / 20 |
| --- | --- | ---: | ---: |
| Historical | Identification | 12 | 17 |
| Historical | Discovery | 4 | 12 |
| Counterfactual | Identification | 4 | 11 |
| Counterfactual | Discovery | 1 | 10 |

For success probability, the exploratory paired factorial contrast is

\[
\Delta=(P_{HD}-P_{CD})-(P_{HI}-P_{CI})=-0.25.
\]

There is one observation per family/cell and no inferential uncertainty model;
this number is descriptive only. It is not a causal estimate and does not test
the intended scientific hypothesis.

The run recorded 1,331 forecast pairs and 681 scorable persistent-hypothesis
pairs. Of the latter, 124 support gaps moved toward the hypothesis with lower
forecast error, 516 were unchanged, and 41 moved in the opposite direction.
The records also contain 77 confidence shifts when compared forecasts were tied
under the implemented rule, 19 pairs excluded because a hypothesis statement
was rewritten under the same ID, and 28 duplicate setups. These are counts from
the implemented diagnostic, not externally validated labels of scientific
reasoning quality.

Among the 29 scientific failures, 28 terminated at held-out generalization and
one at final model specification. Across all failed episodes, the deterministic
first-observed-misstep summary records 20 action-generation failures, 10
stopping/commitment failures, 28 belief-update mismatches, and one held-out
generalization mismatch. “First observed” does not mean psychological or causal
root cause.

### Run-version caveat

This run was produced on 2026-08-25; case and temporal source files were edited
on 2026-08-26, and the run does not contain a human-readable source release ID
that binds it to the current implementation. It must therefore remain an
archived exploratory development result. It must not be appended to a future
current-source confirmatory dataset.

## C. Observed in temporal case authoring

The latest ordered cohort is
`runs/temporal_stop_first_10_2026-08-26/`. It contains ten purposively selected
papers and stops at the first accepted case, or on provider/runtime failure.

- Six papers received a ScienceCard-stage outcome.
- Two of the six yielded schema-parseable cards.
- Neither parseable card passed independent source review.
- Four outputs failed the strict ScienceCard schema.
- Processing stopped at paper 7 because of a provider connection failure before
  a response; papers 8–10 were not attempted.
- No case reached the matched-draft stage and no case was accepted.

The four schema failures do not establish scientific ineligibility, and the
transport failure says nothing about the paper. The sample is purposive and
incomplete, so no population conversion rate is estimable.

An earlier monolithic authoring path rendered one development family,
`kz_vortex_scaling`, but it used a benchmark-authored counterfactual and is
ineligible under the current source-only temporal policy. It demonstrates an
older pipeline path, not a current-policy accepted case.

## D. Claims that are not established

The following claims are prohibited in the current drafts:

- state-of-the-art performance or model ranking;
- statistically reliable historical, counterfactual, identification, discovery,
  or interaction effects;
- causal isolation of whether the correct model family is disclosed;
- general scientific-discovery, creativity, or causal-mechanism ability;
- contamination resistance or a formal private evaluation result;
- validated measurement of scientific reasoning quality from the current
  trajectory heuristics;
- autonomous, reliable, or representative paper-to-case conversion;
- priority for Player–Oracle interaction, counterfactual physics, active
  experimentation, controlled prior information, executable final laws,
  held-out prediction, or process/outcome separation.

## E. Evidence required before a main-conference submission

1. Freeze a human-readable evaluation release and generate a new current-source
   80-cell smoke run; verify behavioral replay before scaling.
2. Make the final predictor encoding common across identification and discovery
   if the claim is specifically about family disclosure.
3. Add a zero-observation/prior-only baseline and at least one legitimate
   experiment-using baseline.
4. Evaluate several genuinely different Player models with prespecified repeats;
   hold the Oracle presentation policy fixed or use the deterministic Oracle
   directly.
5. Analyze at the matched-family level with a prespecified factorial contrast,
   missingness policy, and uncertainty calculation.
6. Validate the trajectory diagnostics against blinded human annotations and
   report coverage/reliability rather than only aggregate scores.
7. For formal claims, deploy a private case service and private variants whose
   truths and held-out conditions are inaccessible to the Player process.

