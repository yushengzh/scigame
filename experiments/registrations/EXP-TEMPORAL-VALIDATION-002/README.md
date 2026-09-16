# EXP-TEMPORAL-VALIDATION-002

This record consolidates the targeted scientific validation performed after `EXP-TEMPORAL-SOURCE-REVIEW-001`. It does not modify the old frozen artifacts and does not register any family in the public benchmark package.

## Outcome

- 27 distinct source-paper families were targeted: the original 22 candidates and five replacement candidates drawn from the already frozen production cohorts.
- 21 are release candidates: 16 corrected or revalidated original candidates plus five replacements.
- Six original candidates are excluded because the proposed Player control is not an actually manipulated quantity.
- The first 20 accepted families in frozen acquisition order are `core20`; the 21st is retained as an extension. No model-performance result was used for this designation.

The exact family list, source identifiers, ScienceCard location, per-family admission-v2 checks, replay results, exclusions, and uniqueness checks are in [`release_manifest.json`](../../../runs/EXP-TEMPORAL-VALIDATION-002/release_manifest.json). A concise Chinese account is in [`report_zh.md`](../../../runs/EXP-TEMPORAL-VALIDATION-002/report_zh.md).

## Acceptance contract

An accepted family must satisfy all of the following:

1. Each numeric control is actually set or manipulated in the reported experiment, computation, or protocol.
2. All eight admission-v2 precompile checks pass: source coverage, quantitative-relation support, formula fidelity, parameter support, control support, readout support, domain support, and anchor accuracy.
3. The reviewed card parses with source lineage, is admitted by `role_benchmark.temporal_admission_review.v2`, and compiles deterministically.
4. The deterministic known-truth submission passes held-out evaluation in both Identification and Discovery.

All 21 accepted cards were replayed through that path. Both task settings returned `predictive_model_pass = 1.0`, `held_out_prediction_score = 1.0`, and zero hidden-test scaled error. These are development canaries for target and evaluator consistency, not scores from a tested LLM.

## Scope boundary

This is a source-reported-family release-candidate record. It does **not** contain the separately authored counterfactual variants needed for four cases per Temporal family. Consequently, it does not establish that the requested 160-case core suite is runnable. Public registry integration, counterfactual construction, and the unified benchmark manifest remain later steps.

The scientific review is model-based process separation, not independent human/domain-expert certification. It also does not establish that the sources are post-cutoff, unseen, or contamination-free.
