# EXP-TEMPORAL-AUTHORING-001

This directory registers the controlled rerun of Temporal case authoring after two protocol changes: Temporal admission now requires one source-supported executable quantitative relation, and the authoring model extracts only the minimal ScienceCard fields. Counterfactual construction is a separate optional pipeline.

The registration is intentionally marked `blocked_pending_snapshot_and_credentials`. The historical runs record the mutable model alias `deepseek-v4-flash`, but they do not record an immutable checkpoint or snapshot identifier. The runtime credential is also absent. Running the same alias at a later date would not hold model state constant and therefore would not identify the effect of the pipeline change.

## Frozen inputs and budget

[`frozen_sources.json`](frozen_sources.json) contains all 37 source packets in fixed order:

- 17 papers from `family_generation`, with at most two total ScienceCard attempts per paper;
- 20 disjoint papers from `expansion_family_generation`, with at most four total ScienceCard attempts per paper.

Every listed paper must be processed exactly once. Sources may not be selected again, replaced, extended, reordered, or excluded after observing an output. Unused attempts may not be transferred between papers. The maximum registered authoring budget is 114 provider calls.

A provider request whose response is unavailable is conservatively charged to that paper's call limit, but it is not treated as a structurally invalid model response. The next numbered call may be used only if budget remains. If the unavailable response consumes the final slot, the study remains incomplete because of missing infrastructure data and cannot enter the comparison.

## Registered outcomes

The analysis unit is the paper, and every primary denominator is 37.

| Outcome | Numerator |
|---|---|
| First-attempt structural validity rate | Papers whose first response passes minimal ScienceCard validation and contains exactly one nonempty relation |
| Post-repair structural validity rate | Papers that meet the same condition within their registered total-attempt limit |
| Source-review retention rate | Papers for which independent review confirms at least one source-supported executable quantitative relation eligible for Temporal construction |
| Final acceptance rate | Papers yielding at least one complete Temporal case that passes deterministic construction, Temporal admission, and final family validation |

The complete operational definitions, failure handling, and stopping rule are frozen in [`registration.json`](registration.json). A paper counts no more than once in a primary numerator.

## Historical evidence and interpretation

The descriptive historical record is 3/37 first-attempt structurally valid, 13/37 structurally valid after bounded repair, 0/37 eligible at source review, and 0/37 finally accepted. Among the 13 reviewed cards, six required card revision and seven were rejected. Revision-required cards are reported separately and are not counted as retained. Because the previous reviews used the paired-condition admission contract, they cannot retrospectively establish eligibility under the new single-relation contract.

These historical values do not constitute a controlled baseline while the historical immutable model snapshot remains unknown. Percentage-point differences may be reported descriptively. They must not be attributed causally to the pipeline revision unless the exact historical snapshot is identified, callable, and used with the registered settings and budgets.

Before any API call, an immutable, provider-callable checkpoint or snapshot must be recovered. In a documented pre-execution amendment, record the same identifier in `authoring_model.checkpoint_or_snapshot_id` and `historical_baseline.authoring_model_checkpoint_or_snapshot_id`, change `historical_baseline.comparison_status` to `controlled`, change the experiment status to `ready_for_execution`, and commit the amendment. The runner uses this identifier—not the mutable alias—as the provider request's `model` value. Supply the credential only at runtime and do not write it to repository artifacts. If only the mutable model alias is available, use a separately registered descriptive replication rather than modifying or presenting this experiment as the controlled comparison.
