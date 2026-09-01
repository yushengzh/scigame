# Frozen-census source-pool expansion

Verdict: **PASS**. The unchanged 2026-04-01 through 2026-06-30 census yielded 43 new, coordinator-ready PRL source packets, with no overlap with the existing 17-paper pool. This is more than the requested 20-candidate priority target.

## Minimal selection and identity rule

The pass started from 55 new PRL Letter records whose titles indicate a quantitative mechanism, law, scaling, dynamics, transition, transport, fluctuation, or response. It excluded the existing 17 records and titles marking Comments, Replies, Errata, Retractions, Withdrawals, or Corrections. Publication dates and venue membership remain those of the frozen census; the window was not widened. Nature/Science magazine, news, commentary, and correction records were not used.

The existing acquisition identity rule was retained unchanged: a unique exact arXiv DOI match, otherwise a normalized exact title plus first-author-family match. A selected source also had to return decodable TeX from the pinned arXiv source endpoint. This produced:

- 43 `source_acquired` and selected: 34 DOI matches and 9 normalized-title/first-author matches.
- 10 `arxiv_not_found`.
- 2 exact identity resolutions whose source endpoint was PDF-only, hence `no_tex_source`.
- 20 especially conservative candidates where normalized title, first-author family, and DOI all agree simultaneously.

All 43 moved source paths were checked after installation, the acquisition handoff validator passed, and the warm-up cohort parser accepted all 43 entries. Their deterministic TeX display-environment counts range from 2 to 200 (median 28). That count is only a formula-density screening signal, not evidence that a paper can already support a matched family.

## Conservative 20-paper priority set

| DOI | arXiv source | Display markers | Title |
|---|---:|---:|---|
| 10.1103/z8v9-f8j2 | 2502.12233v2 | 39 | Quantum Critical Dynamics Induced by Topological Zero Modes |
| 10.1103/b7s9-4l4q | 2511.18947v2 | 12 | Conservation Laws and Slow Dynamics Determine the Universality Class of Interfaces in Active Matter |
| 10.1103/3wgy-sgkz | 2602.21375v1 | 5 | Passive Freeze-Out of the Richtmyer-Meshkov Instability |
| 10.1103/g6l8-wbt1 | 2602.21922v1 | 3 | Universal Persistent Brownian Motions in Confluent Tissues |
| 10.1103/nl7n-bqn4 | 2509.13502v3 | 40 | Effective Delocalization in the One-Dimensional Anderson Model with Stealthy Disorder |
| 10.1103/fsdt-d3p9 | 2507.23667v2 | 180 | Universal Time Evolution of Holographic and Quantum Complexity |
| 10.1103/wytr-kd9j | 2507.23753v3 | 8 | Compatible Instability: Gauge Constraints of Elasticity Inherited by Electronic Nematic Criticality |
| 10.1103/ytqg-v1j8 | 2510.07467v2 | 15 | Weakly Turbulent Saturation of the Nonlinear Scalar Ergoregion Instability |
| 10.1103/8nch-ld18 | 2311.14592v2 | 13 | Chaotic Fluctuations in a Universal Set of Transmon Qubit Gates |
| 10.1103/fhfy-dh85 | 2505.04704v2 | 40 | Disorder-Free Localization and Fragmentation in a Non-Abelian Lattice Gauge Theory |
| 10.1103/tfcx-kzqx | 2503.01962v2 | 104 | Curvature Perturbations from First-Order Phase Transitions: Implications to Black Holes and Gravitational Waves |
| 10.1103/2z9s-5d7w | 2511.12574v3 | 154 | Symmetry-Based Nonlinear Fluctuating Hydrodynamics in One Dimension |
| 10.1103/g41t-8456 | 2605.11401v1 | 2 | Superconductivity Reinforces Charge-Density-Wave Phase Coherence across Cuprates |
| 10.1103/5z1m-122d | 2511.08754v3 | 28 | Exact Floquet Dynamics of Strongly Damped Driven Quantum Systems |
| 10.1103/6f98-tvb8 | 2301.05687v2 | 67 | Mixed-State Topological Order and the Errorfield Double Formulation of Decoherence-Induced Transitions |
| 10.1103/kdhy-66b6 | 2510.26325v2 | 95 | Weak-Memory Dynamics in Discrete Time |
| 10.1103/9y2v-ybdb | 2511.07305v1 | 35 | Persistence of the Berezinskii-Kosterlitz-Thouless Transition with Long-Range Couplings |
| 10.1103/j3s5-gjpf | 2602.17656v2 | 2 | Exotic Critical States as Fractional Fermi Seas in the One-Dimensional Bose Gas |
| 10.1103/1jkm-kybr | 2506.19637v2 | 23 | Long-Range Order in a Strictly Short-Range Quasi-2D XY Model: When Critical Fluctuations Matter |
| 10.1103/7g5s-hsd6 | 2512.06081v3 | 19 | Entanglement Transition in Unitary System-Bath Dynamics |

The other 23 selected records remain valid under the existing exact identity rule, but have a publication-title variant, a harmless first-author-family typography variant, or no DOI field in arXiv with exact normalized title/author fallback. Their full journal/arXiv evidence is recorded per paper in `acquisition.json` and `papers/*/paper.json`.

## Failed candidates

| DOI | Disposition | Checkable reason |
|---|---|---|
| 10.1103/d2br-hl5x | `arxiv_not_found` | no unique configured exact match |
| 10.1103/tjm4-gjx8 | `arxiv_not_found` | no unique configured exact match |
| 10.1103/sqkj-9x8n | `no_tex_source` | resolved arXiv source endpoint returned PDF only |
| 10.1103/37kj-vjq6 | `arxiv_not_found` | no unique configured exact match |
| 10.1103/v62d-g9vz | `arxiv_not_found` | no unique configured exact match |
| 10.1103/gkvs-4vsb | `no_tex_source` | resolved arXiv source endpoint returned PDF only |
| 10.1103/7zxr-j397 | `arxiv_not_found` | no unique configured exact match |
| 10.1103/y9qj-g447 | `arxiv_not_found` | no unique configured exact match |
| 10.1103/t6vf-lw69 | `arxiv_not_found` | no unique configured exact match |
| 10.1103/bl3z-8krg | `arxiv_not_found` | no unique configured exact match |
| 10.1103/6msd-mdw4 | `arxiv_not_found` | no unique configured exact match |
| 10.1103/rbzb-km7n | `arxiv_not_found` | no unique configured exact match |

This expansion is deliberately only a source-ready pool. It makes no claim that all 43 papers can support the benchmark's common-control/readout and two-private-mechanism structure. ScienceCard extraction and source review remain the next scientific filter. No LLM authoring was run here.
