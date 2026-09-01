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

## Current manuscript position

The most defensible primary claim is the matched measurement design:

> Compare family-disclosed parameter identification with family-withheld
> structural discovery in the same executable world, then cross that comparison
> with historically familiar and minimally authored counterfactual laws.

The scientific contribution is the joint pairing, not Player--Oracle
interaction, active experimentation, counterfactual physics, controlled prior
information, executable prediction, LLM judging, or paper-to-case conversion
individually. The main historically anchored cohort contains 20 families / 80
cells. Nine source-grounded temporal families / 36 cells form a separate
transfer and authoring extension; they are not automatically valid members of
the historical-prior factorial contrast.

## Submission-critical gaps

The prose can be organized to ICLR standards now, but an oral/spotlight-level
empirical claim still requires:

1. one final executable representation shared by Identification and Discovery;
2. a prior-only manipulation check and experiment-using reference baselines;
3. a frozen multi-model, repeated, randomly interleaved evaluation analyzed at
   the family level;
4. a private case/evaluator service for formal rather than public-development
   results;
5. human calibration and sensitivity analysis before treating process or LLM
   judge scores as validated constructs; and
6. a genuinely independent truth-conditioned generative Oracle implementation
   before the deterministic-versus-generative Oracle ablation.

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

- [Matched diagnostic draft](draft_a_matched_diagnostic.md)
- [Forecast-grounded process draft](draft_b_forecast_grounded_process.md)
- [Source-grounded authoring draft](draft_c_source_grounded_authoring.md)
- [Evidence ledger](evidence_ledger.md)
- [Figures and tables](figures_and_tables.md)
- [Adversarial review loop](adversarial_review_loop.md)
- [Framing debate](framing_debate.md)

These archival files use the 2026-08-26 snapshot (20 families and zero accepted
temporal cases) and must not be cited for current corpus counts.
