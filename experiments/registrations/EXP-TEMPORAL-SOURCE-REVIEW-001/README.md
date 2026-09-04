# EXP-TEMPORAL-SOURCE-REVIEW-001

This registration freezes a model-based scientific source review of the 22 Temporal candidate families produced by `EXP-TEMPORAL-PRODUCTION-001` through `004`.

Each family is reviewed in a separate `gpt-5.6-sol` context with reasoning effort `ultra`. The reviewer compares the frozen source packet with the minimal ScienceCard and constructed case. The review checks the quantitative relation, formula, parameters, controls, readouts, domain, and source anchors. It does not assess novelty, benchmark difficulty, model capability, or the correctness of an external software implementation.

The requested model is used as a scientific reviewer, but it is not a human domain expert. The runtime does not expose an immutable model snapshot. Results must therefore be reported as model-based source review and cannot satisfy a requirement for independent human or domain-expert review.

The linkage subtask is separate. It attempts to freeze current official Crossref, arXiv, and publisher metadata for the three relation-only records and the one previously manually linked record identified in the earlier post-hoc linkage review. A linkage status is upgraded only when the newly frozen official records support it.

Frozen inputs and dispositions are defined in `registration.json`, `frozen_manifest.json`, and `review_rubric.md`.
