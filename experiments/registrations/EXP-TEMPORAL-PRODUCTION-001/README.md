# EXP-TEMPORAL-PRODUCTION-001

This is a non-comparative emergency production run for recent-source Temporal benchmark candidates. It is separate from `EXP-TEMPORAL-AUTHORING-001` and leaves the API-backed main runner unchanged.

The inclusive source window is 2026-01-01 through 2026-09-03. Eligibility uses the earliest public date: the earlier of journal publication and the first arXiv submission. The frozen cohort contains 36 papers. Nature and Science sources that pass the arXiv TeX availability check appear first: 19 were linked by exact DOI and five were recovered by full-title web search followed by official-record adjudication. Eligible Physical Review Letters sources form the fixed fallback set. No paper may be replaced after an authoring or review result is observed.

The Code Agent authors only the provider-facing minimal ScienceCard fields. Existing deterministic code supplies the experiment design, public template, provenance mapping, case module, and two task-setting checks. Source review occurs in a separate model context, which provides process separation but is not independent human review. All accepted artifacts therefore remain candidates pending human source review and registry integration.

The requested model label is `gpt-5.6-fast`. Because this interface does not expose an immutable snapshot or a documented knowledge cutoff, this run cannot establish that any candidate is post-cutoff, unseen, or contamination-free.
