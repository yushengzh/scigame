# Manuscript drafts: reading guide

Status: ICLR working materials, repository snapshot 2026-08-31.

## Canonical draft

[ICLR draft](iclr_draft.md) is the current manuscript source. It is written in
Markdown and currently contains:

- Section 2, **Background**, with Section 2.2 as a scoped Related Work review;
- Section 3, **Methodology**, aligned to the implemented case, episode, Oracle,
  evaluator, failure-analysis, and temporal-authoring contracts; and
- explicit boundaries between implemented methods, public-development evidence,
  and preregistered extensions.

The draft uses LaTeX math syntax and BibTeX keys from
[references.bib](references.bib). Conversion to the official ICLR LaTeX style
should happen after the scientific narrative and experiment tables are frozen.

## 2026-09-01 review and report deliverables

- [Comprehensive related work](related_work_comprehensive.md) reviews the
  scientific-agent, interactive-discovery, law-induction, active-design,
  process-evaluation, temporal-benchmark, and autonomous-laboratory literature.
  It includes the necessity argument, nearest-work matrix, precise novelty
  boundary, and search/verification note.
- [Technical report](technical_report.md) documents version 0.8.0 as a complete
  system: construct, matched design, architecture, action protocol, Oracle,
  scoring, corpus, temporal authoring, replay, verification, threats to
  validity, and formal-evaluation requirements.
- [中文 Technical Report](technical_report_zh.md) provides the complete Chinese
  version with a fixed terminology ledger and the same evidence boundaries.
- [中文 Related Work](related_work_comprehensive_zh.md) provides the corresponding
  Chinese literature review and nearest-work comparison.

These files use the shared [references.bib](references.bib) and the current
29-family / 116-instance audit snapshot.

## Current manuscript position

The most defensible primary claim is the matched measurement design:

> Compare model-family-disclosed parameter identification with model-family-withheld
> law induction under the same data-generating condition, then cross that comparison
> with paired Historical and Counterfactual conditions.

The scientific contribution is the joint pairing, not Player--Oracle
interaction, active experimentation, counterfactual physics, controlled prior
information, executable prediction, LLM judging, or paper-to-case conversion
individually. The main historically anchored cohort contains 20 families / 80
conditions. Nine paper-derived temporal task families / 36 conditions form a separate
transfer and authoring extension; they are not automatically valid members of
the historical-prior factorial contrast.

## Submission-critical gaps

The prose can be organized to ICLR standards now, but an oral/spotlight-level
empirical claim still requires:

1. execution of the frozen method pilot before scaling the evaluation;
2. a frozen multi-model, repeated, randomly interleaved evaluation analyzed at
   the family or source-paper level;
3. a private case/evaluator service for formal rather than public-development
   results;
4. human calibration and sensitivity analysis before treating process or LLM
   judge scores as validated constructs; and
5. complete Temporal exposure records and immutable model snapshots before any
   post-checkpoint claim.

## ICLR 2027 production constraints

The official [ICLR 2027 Author
Guidelines](https://iclr.cc/Conferences/2027/AuthorGuidelines) specify a
9-page main-text limit at submission, double-blind review, an abstract deadline
of 18 September 2026 AOE, and a full-paper deadline of 25 September 2026 AOE.
References and appendices do not count toward the main limit, although reviewers
need not read appendices. The submission must also include the required AI-use
statement; that statement should accurately disclose the use of language models
for ideation and manuscript drafting, with authors retaining responsibility for
the scientific content.

## Archived framing studies

The following files are retained as dated reasoning records, not current
manuscript text:

- [Matched-pairs evaluation draft](draft_a_matched_pairs_evaluation.md)
- [Process-evaluation draft](draft_b_process_evaluation.md)
- [Paper-derived task-construction draft](draft_c_paper_derived_task_construction.md)
- [Evidence ledger](evidence_ledger.md)
- [Figures and tables](figures_and_tables.md)
- [Adversarial review loop](adversarial_review_loop.md)
- [Framing debate](framing_debate.md)

These archival files use the 2026-08-26 snapshot (20 families and zero accepted
temporal cases) and must not be cited for current corpus counts.
