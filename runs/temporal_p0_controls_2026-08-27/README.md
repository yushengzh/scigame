# Temporal P0 control rerun

Date: 2026-08-27

## Question and invariant

The benchmark is intended to measure whether a Player can recover a scientific relationship by choosing experiments and updating its beliefs from Oracle evidence. For a paper-derived case, the minimal admissibility witness is

```text
(X, Y, A0, A1, Q, C, r0, r1, F0, F1)
```

where `X` is the paper-manipulated control set, `Y` is the operational numeric readout set, `A0/A1` are the source-supported applicability domains, `Q` is the benchmark query set with `Q ⊆ A0 ∩ A1`, `C` is the common fixed context, `r0/r1` are two source-reported branches, and `F0/F1: Q -> Y` are parameter-closed response formulas. The Oracle may evaluate only these reviewed formulas; neither the abstractor nor the case author may supply missing scientific facts from model knowledge.

## Changes exercised by this rerun

- Source applicability and benchmark queries are distinct. A claim can report a continuous interval, finite numeric values, a fixed value, a symbolic condition, or an unreported domain. Only a source-supported interval or at least two finite values may become a Player control.
- `Q` may be a strict source-supported subset of `A0 ∩ A1`; equality is not required.
- The source packet includes fixed-version UTF-8 `.tex/.csv/.tsv/.dat/.txt` members with file boundaries and global line locators. A reviewer-authored figure addendum may transcribe only conservative facts tied to a named asset in the fixed archive.
- TeX comments are removed while preserving line count; non-TeX textual attachments remain unchanged. This prevents deleted or draft formulas in comments from becoming evidence.
- The extraction and repair prompts contain an explicit domain-field truth table and treat an unspecified fit-uncertainty convention as missing metadata rather than a formula contradiction.

The clean packets were freshly acquired after comment removal. Their line counts remained unchanged: KZ 1118, optical lattice 188, and Kramers 581.

## Final clean-packet controls

| Control paper | Paper-level matched-formula witness | Pipeline result | Interpretation |
| --- | --- | --- | --- |
| Kibble-Zurek turbulence | Yes | `awaiting_source_review` | The card correctly extracted `tau_Q ∈ [100,1000]`, one `E_i` readout, and the two fits `197740*tau_Q^-0.971` and `95430*tau_Q^-0.935`, including all four branch parameters. It still needs card revision: an uncertainty-only ambiguity is incorrectly blocking; two temperature glosses and WLS lack exact supporting anchors; and an unnecessary common simulation condition contains a branch-specific temperature. The paper is not ineligible, so no false rejection review was submitted. |
| 3D/1D optical lattice decay | No, for the requested absolute-count readout | `exhausted` at ScienceCard validation | The source reports exponential lifetimes 54 ms and 220 ms, but not `N0`; therefore `N(t)=N0 exp(-t/tau)` cannot generate absolute atom counts. The clean run also ignored the addendum's finite 100/200/300 ms candidates, invented a one-sided continuous domain, and exhausted its repair on IDs beginning with digits. A normalized readout was deliberately not invented. |
| Kramers ion cluster | No | `source_review_rejected`, then `exhausted` | The identical-ion branch has a quantitative Kramers-Langer inversion-rate relation. The isotope branch reports qualitative locking near `alpha≈1.09` and a roughly 270 mK activation barrier, but no second inversion-rate formula over a shared `alpha` domain. Independent source review rejected the requested pairing even though the extractor self-reported `case_authoring_ready=true`. |

Formal accepted cases in this three-paper control are therefore **0**. This is not evidence that all three papers are scientifically unusable: KZ has a valid paper-level witness but its current generated card is not yet source-closed. It is evidence that extractor self-assessment cannot be an admission authority.

## What the controls isolate

1. P0 fixes the original domain error: a paper's applicability set is no longer forced to equal the benchmark query set, and finite figure-supported settings need not be fabricated as an interval.
2. The source-packet boundary is now adequate for text and reviewer-transcribed figure facts, and excludes non-rendered TeX comments.
3. The remaining positive-control bottleneck is formula representation and card correction, not source acquisition. Free-text `quantitative_form` can contain the right formula while the machine-readable parameter graph or anchors remain incomplete.
4. A binary paper review cannot honestly distinguish “the paper lacks a case” from “the generated card needs correction.” KZ demonstrates why a card-revision disposition is needed before a larger temporal run.
5. Temperature zero does not make provider output deterministic: repeated optical/Kramers extractions changed schema and readiness decisions. Admission therefore has to depend on reviewed structured evidence, not a single model verdict.

## Next minimal correction

The next change should make each selected claim's Oracle response a structured expression over declared controls and source parameters, reusing the project's existing expression grammar. The displayed LaTeX formula can remain for reviewers, but it must not be the machine truth. This directly enforces formula closure without natural-language regular expressions.

In the same review boundary, add a `card_revision_required` disposition so source-supported papers can return for correction without being mislabeled as ineligible. Anchor semantics should remain an independent source-review responsibility, with the review request showing the exact cited source lines. These are pipeline corrections, not benchmark contributions.

## Artifacts

- KZ: `kz/acquired_clean_packet/` and `kz/warmup_clean_packet/`
- Optical lattice: `optical/acquired_clean_packet/` and `optical/warmup_clean_packet/`
- Kramers: `kramers/acquired_clean_packet/` and `kramers/warmup_clean_packet/`
- Kramers independent verdict: `kramers/warmup_clean_packet/reviews/paper_2601_04883v1.json`

No API credential is stored in these artifacts.
