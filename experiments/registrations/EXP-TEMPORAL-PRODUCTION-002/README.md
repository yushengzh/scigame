# EXP-TEMPORAL-PRODUCTION-002

This is a separately frozen operational expansion of `EXP-TEMPORAL-PRODUCTION-001`. It was registered after the first cohort produced 7 accepted families, so its conversion rate must be reported separately and cannot be used as a preregistered or causal comparison.

The inclusive source window is 2026-01-01 through 2026-09-03. The 59-source cohort places all eight newly verified Nature and Science candidates first, followed by all 51 eligible PRL TeX candidates in the frozen PRL audit. Every fixed arXiv version was public by the window endpoint. The complete cohort must be processed; no source may be replaced and processing does not stop after reaching the cumulative target of 20 families.

Record linkage separates candidate retrieval from identity adjudication. Crossref `has-preprint` relations and exact journal DOIs in official arXiv metadata are direct identifier evidence. A quoted full-title web search is only a fallback retrieval channel. Search ranking, numeric overlap, scientific-symbol overlap, and topic similarity do not establish identity. A non-hit remains unresolved.

The Code Agent authors only the six minimal ScienceCard components. Existing deterministic code supplies the experimental design, public template, provenance mapping, case module, and task-setting checks. A different Code Agent context performs source review; this establishes process separation, not independent human or domain-expert validation. Accepted artifacts remain candidates pending human review.

Before final cohort compilation, `family_index_offset=1000` was added to prevent order-based family identifiers from colliding with earlier cohorts. This namespace-only correction is recorded in `configuration_amendment_2026-09-03.json`; it changes no source, ScienceCard, review, admission decision, or score.

The requested authoring label is `gpt-5.6-fast`. This interface exposes neither an immutable snapshot nor a documented knowledge cutoff. Consequently, this run cannot establish that any instance is post-cutoff, unseen, or contamination-free.
