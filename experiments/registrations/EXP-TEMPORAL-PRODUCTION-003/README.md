# EXP-TEMPORAL-PRODUCTION-003

This is a separately frozen operational production cohort registered after the earlier Temporal production cohorts had yielded 12 cumulative accepted families. Its purpose is to obtain at least eight additional accepted families and reach a cumulative total of 20. Because the earlier outcomes were already observed, this cohort's conversion rate must be reported separately and cannot be interpreted as a preregistered or causal comparison.

The inclusive source window is 2026-01-01 through 2026-09-03. The source audit used the official Crossref Physical Review Letters ISSN census and retained subject-asserted `has-preprint` relations pointing to 2026 arXiv records. Of 105 such records, 11 overlapped the frozen EXP-001 or EXP-002 cohorts. Official arXiv `id_list` metadata resolved all 94 remaining relation targets exactly. Three fixed versioned source responses were PDF-only; the other 91 contained at least one TeX file and are frozen in the audit's accepted order.

Record linkage uses the subject-asserted Crossref `has-preprint` relation together with exact resolution of its target in official arXiv metadata. If arXiv reports a related journal DOI, it must equal the Crossref journal DOI; a missing arXiv DOI is recorded as missing evidence rather than treated as a conflict. Numeric overlap, title overlap or similarity, search results, search ranking, and topic similarity do not establish identity.

Every fixed arXiv version was public by the window endpoint. `family_index_offset=2000` maps the 91 frozen source orders to `temporal_source_2001` through `temporal_source_2091`. The complete cohort must be processed. No source may be replaced, and processing must not stop after eight new families or after the cumulative target of 20 is reached.

After the cohort was frozen, source order 54 was identified as a PRL Comment rather than an original research article. It was rejected during source review. It remains in the frozen denominator and was not replaced. The deviation and the prospective article-type rule are recorded in `source_eligibility_amendment_2026-09-03.json`.

The Code Agent authors only the six minimal ScienceCard components: formula, parameters, controls, readouts, domain, and anchors. Deterministic code supplies the budget, diagnostic and held-out conditions, public template, provenance mapping, case construction, and task-setting checks. A Code Agent context that did not author a card performs source review; this provides process separation, not independent human or domain-expert validation. Human source review remains required before public release.

The requested authoring model label is `gpt-5.6-fast`. This interface exposes neither an immutable snapshot nor a documented knowledge cutoff. Consequently, this run cannot establish that any instance is post-cutoff, unseen, or contamination-free.

The main API runner remains `experiments/run_temporal_conversion.py`. The non-API adapter `experiments/run_temporal_code_agent_production.py` is an emergency execution path for this experiment only and does not replace the main runner.
