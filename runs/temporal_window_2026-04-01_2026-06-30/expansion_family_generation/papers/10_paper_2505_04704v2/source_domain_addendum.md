# Fig. S5 source-domain addendum

## Scope

This addendum answers one narrow source question for arXiv `2505.04704v2`: what positive-time domain is directly supported by the plotted GI and SS fit curves in Fig. S5? It does not revise the ScienceCard or infer an unreported regression-training interval.

## Fixed source material

- Official immutable source archive: `https://arxiv.org/src/2505.04704v2`
- TeX in that archive: `manuscript.tex`
- Figure asset in that archive: `figures/figS5_entropy_GI_SS.pdf`
- Local extracted copy used for visual and vector inspection: `tmp/pdfs/nonabelian_source_review/figures/figS5_entropy_GI_SS.pdf`
- Local 4x render used for visual inspection: `tmp/pdfs/nonabelian_source_review/figS5_entropy_GI_SS.png`
- Existing frozen textual packet: `runs/temporal_window_2026-04-01_2026-06-30/expansion_family_generation/frozen_sources/10_paper_2505_04704v2.txt`, especially lines 763-776.

The arXiv archive contains the TeX and PDF figure assets, but no plotting script or numerical data table for Fig. S5.

## TeX evidence

The supplement states that Fig. S5 shows time-averaged half-chain bipartite entanglement entropy with averaging window `Delta t = 2.5`, fixed `m = 1`, and `g^2` ranging from 0 to 15. Its caption identifies the cyan curves as the fits of the `g^2 = 15` branches:

- GI: `S_GI(t) = 0.386(6) t + 0.43(2)`
- SS: `S_SS(t) = 2.94(2) log(t) + 1.33(3)`

This establishes the formulae and common conditions, but the prose does not state the fit-window endpoints.

## Figure-domain evidence

The PDF is a vector figure. Both panels have labelled time ticks from `t = 0` through `t = 10`. Inspection of the cyan path coordinates against those tick coordinates gives:

| branch | cyan path visible in the panel | coordinate evidence |
|---|---:|---|
| GI | `t = 1.4` through approximately `t = 5.99` | tick-zero x coordinate `34.8347435`, one-time-unit spacing `20.0255241`; cyan x endpoints `62.8704758` and `154.787674`, mapping to `1.3999999` and `5.9900020` |
| SS | `t = 2.0` through `t = 10.0` | tick-zero x coordinate `263.6063232`, one-time-unit spacing `20.0254517`; cyan starts at x `303.657349`, mapping to `2.0000061`, and remains visible to the panel boundary at the `t = 10` tick |

The SS vector path continues beyond the clipped right panel boundary to approximately `t = 10.9`. Because that portion is not displayed inside the axes, it is not evidence for extending the source-supported plotted domain beyond `t = 10`.

## Conservative conclusion for a matched case

The intersection directly supported by both plotted fit curves is therefore approximately `t in [2.0, 5.99]`. For a simple, strictly interior machine-query domain, `t in [2.0, 5.0]` is source-supported for both branches and avoids treating a rendered path endpoint as a separately reported scientific boundary.

This evidence supports evaluating the two captioned fitted curves at common positive times inside that interval. It does **not** establish that the underlying regression used exactly those endpoints or that either formula should be extrapolated outside its displayed cyan segment.

