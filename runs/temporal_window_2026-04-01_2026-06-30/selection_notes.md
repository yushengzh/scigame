# Temporal source-pool selection notes

## Scope and status

- Requested publication window: **2026-04-01 through 2026-06-30, inclusive**. The requested end date `2026-06-31` does not exist, so this run uses the last valid day of June.
- Frozen census grain: one journal record per DOI. The snapshot contains 2,319 records: 1,134 from *Nature*, 664 from *Physical Review Letters* (PRL), and 521 from *Science*.
- This file records **source selection**, not benchmark-case acceptance. A selected paper can still fail source normalization, claim extraction, source review, matched-family closure, or deterministic case validation.
- Transformability was the gate: a paper needed a compact, source-supported quantitative relation or mechanism that could plausibly become an interactive case. The frozen Crossref citation count was only an impact tie-break and was not a threshold.

## Publisher reconciliation rule

The accompanying `publisher_reconciliation.json` contains only records for which the official APS article page was readable on 2026-08-27 and agreed with the frozen census on DOI, title, and publication date. Each included page is a normal PRL research Letter with authors, abstract, received/accepted history, journal citation, DOI, and a Crossmark entry. No withdrawal or retraction notice was displayed on the current article record. The abstract reports new analysis, theory, simulation, or experiment rather than an editorial, news item, correction, comment, or review.

For arXiv evidence, title and author identity were checked against the official arXiv API. The version listed below was the latest version returned on 2026-08-27. Each official arXiv source endpoint returned a gzip source archive, and its archive listing contained at least one `.tex` file. This establishes source availability; it does **not** establish that the paper will yield a valid benchmark family.

## Reconciled pool

The pool contains 17 PRL Letters: 11 primary candidates from the independent quantitative-case triage and 6 backups. All dates below are the dates displayed by APS and lie inside the inclusive window.

| Tier | DOI and official record | APS date | Exact arXiv source | Candidate quantitative hook (screening only) |
|---|---|---:|---|---|
| Primary | [10.1103/1dj2-zw28](https://journals.aps.org/prl/abstract/10.1103/1dj2-zw28) | 2026-05-27 | [2505.09538v1](https://arxiv.org/abs/2505.09538v1), 1 TeX file | Turbulent Lyapunov exponent scaling, `lambda ~ Re^alpha`, with a reported exponent and uncertainty. |
| Primary | [10.1103/66pp-4rdj](https://journals.aps.org/prl/abstract/10.1103/66pp-4rdj) | 2026-06-16 | [2505.04242v1](https://arxiv.org/abs/2505.04242v1), 1 TeX file | Viscous-inertial transition near a reported Stokes number and its dependence on friction/contact state. |
| Primary | [10.1103/4vh7-2ztw](https://journals.aps.org/prl/abstract/10.1103/4vh7-2ztw) | 2026-04-29 | [2508.10802v2](https://arxiv.org/abs/2508.10802v2), 1 TeX file | Analytical snap-through-time relations across slenderness, imperfection, and buckling regimes. |
| Primary | [10.1103/qxzs-1t1l](https://journals.aps.org/prl/abstract/10.1103/qxzs-1t1l) | 2026-05-27 | [2511.07664v2](https://arxiv.org/abs/2511.07664v2), 1 TeX file | Average shock-time asymptotic relation `(p sqrt(log p))^-1`. |
| Primary | [10.1103/nqcw-pz8v](https://journals.aps.org/prl/abstract/10.1103/nqcw-pz8v) | 2026-06-17 | [2601.07810v4](https://arxiv.org/abs/2601.07810v4), 1 TeX file | Magnetic Gruneisen-ratio critical scaling around a reported critical endpoint. |
| Primary | [10.1103/twbt-z82z](https://journals.aps.org/prl/abstract/10.1103/twbt-z82z) | 2026-05-12 | [2510.10391v3](https://arxiv.org/abs/2510.10391v3), 1 TeX file | Lorenz ratio scaling as the square root of chain length. |
| Primary | [10.1103/3hs9-dz3d](https://journals.aps.org/prl/abstract/10.1103/3hs9-dz3d) | 2026-05-18 | [2510.15228v1](https://arxiv.org/abs/2510.15228v1), 1 TeX file | Finite-frequency fluctuation-response inequality and source-defined equality cases. |
| Primary | [10.1103/dgx2-mwrk](https://journals.aps.org/prl/abstract/10.1103/dgx2-mwrk) | 2026-05-08 | [2509.22773v1](https://arxiv.org/abs/2509.22773v1), 1 TeX file | Universal scaling functions for shallow global quenches and critical relaxation. |
| Primary | [10.1103/g9dh-ymx9](https://journals.aps.org/prl/abstract/10.1103/g9dh-ymx9) | 2026-05-27 | [2503.11604v1](https://arxiv.org/abs/2503.11604v1), 1 TeX file | Saddle-node, excitability, and self-oscillation regimes as fueling/reaction controls change. |
| Primary | [10.1103/sq25-hfsb](https://journals.aps.org/prl/abstract/10.1103/sq25-hfsb) | 2026-06-23 | [2512.08761v2](https://arxiv.org/abs/2512.08761v2), 1 TeX file | Exact hydrodynamic wetting transition plus spontaneous ratchet-current mechanism. |
| Primary | [10.1103/tyrf-2yf7](https://journals.aps.org/prl/abstract/10.1103/tyrf-2yf7) | 2026-04-29 | [2502.16884v1](https://arxiv.org/abs/2502.16884v1), 1 TeX file | Distinct localization/ergodic times and finite-time critical scaling. |
| Backup | [10.1103/tgtw-qnyq](https://journals.aps.org/prl/abstract/10.1103/tgtw-qnyq) | 2026-04-29 | [2512.17777v2](https://arxiv.org/abs/2512.17777v2), 1 TeX file | Correlator-mediated separation between irreversible thermalization and reversible oscillation regimes. |
| Backup | [10.1103/7mcs-xyzs](https://journals.aps.org/prl/abstract/10.1103/7mcs-xyzs) | 2026-06-02 | [2507.00684v1](https://arxiv.org/abs/2507.00684v1), 1 TeX file | Diffusion length versus hexatic order, cluster size, and silo height. |
| Backup | [10.1103/fyx7-jb1d](https://journals.aps.org/prl/abstract/10.1103/fyx7-jb1d) | 2026-04-07 | [2601.12642v1](https://arxiv.org/abs/2601.12642v1), 1 TeX file | Unified Reynolds-Darcy model across three shear-thickening impact regimes. |
| Backup | [10.1103/393g-z21y](https://journals.aps.org/prl/abstract/10.1103/393g-z21y) | 2026-05-15 | [2504.05380v2](https://arxiv.org/abs/2504.05380v2), 2 TeX files | Subexponential local-correlation decay `exp[-O(t^alpha)]` with a bounded exponent. |
| Backup | [10.1103/tz2n-lqxx](https://journals.aps.org/prl/abstract/10.1103/tz2n-lqxx) | 2026-05-21 | [2508.08255v1](https://arxiv.org/abs/2508.08255v1), 2 TeX files | Controlled localization and spectral transitions in a photonic quantum-walk realization. |
| Backup | [10.1103/2mvc-8tc4](https://journals.aps.org/prl/abstract/10.1103/2mvc-8tc4) | 2026-06-18 | [2509.17085v1](https://arxiv.org/abs/2509.17085v1), 1 TeX file | Universal two-excitation scattering and block-diagonal scattering structure near critical points. |

## Deliberately withheld records

Two independently triaged *Science* papers have exact arXiv matches and TeX source archives, but their official Science article pages returned HTTP 403 in this environment. They are therefore **not** present in `publisher_reconciliation.json`; Crossref and arXiv metadata are not being substituted for publisher verification.

| DOI | Frozen census date | Exact arXiv source | Missing gate |
|---|---:|---|---|
| `10.1126/science.adu3916` | 2026-06-11 | [2606.18410v1](https://arxiv.org/abs/2606.18410v1), 1 TeX file | Official category and current publication-status page could not be inspected. |
| `10.1126/science.aeb4154` | 2026-04-09 | [2506.15521v1](https://arxiv.org/abs/2506.15521v1), 1 TeX file | Official category and current publication-status page could not be inspected. |

## Downstream interpretation

The 17 reconciled rows are eligible inputs to acquisition, not accepted cases. The next gates must still establish exact journal-to-arXiv identity, decode the fixed source bundle, extract a source-located quantitative claim, independently review the science card, close all four matched cells, and validate the deterministic Oracle. No claim in this note should be counted as a generated family.
