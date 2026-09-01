# Temporal paper-to-case validation report (2026-08-27)

## Decision

The current pipeline can produce a benchmark-ready temporal case from a retrieved paper. The first end-to-end control is `kz_incompressible_energy_temperature_regimes`, derived from Seong-Ho Shinn et al., *Spontaneous Quantum Turbulence in a Newborn Bose-Einstein Condensate via the Kibble-Zurek Mechanism* (PRL, 2026; arXiv `2506.21670v3`; DOI `10.1103/b16v-hwp2`). The formal coordinator returned `case_accepted` and its four-cell canary returned `all_pass=true`.

This is a development acceptance under the repository's explicit source-review contracts. It is not yet evidence for a high population-level conversion rate, because only one paper family has completed all gates. The source packet's figure-domain transcription was independently checked in this run, but its own metadata still requests human confirmation before a public release.

## Reviewed scientific truth

The frozen source reports the following two central fitted laws on the conservatively reviewed common fitted-curve interval `tau_q in [100, 1000]`:

```text
T = 10^-6:  e_i = 197740 * tau_q^-0.971
T = 1:      e_i =  95430 * tau_q^-0.935
```

The fit uncertainties remain metadata; they are not sampled into Oracle truth. The source review also closes the dimensionless units, density-weighted incompressible-energy definition, equilibration-time definition, branch temperatures, ensemble sizes (`R=2000` and `R=1000`), one-standard-deviation error bars, inverse-variance weighted least squares, simulation settings, and the common fitted-curve domain.

The human-readable `quantitative_form`, structured `oracle_outputs`, parameter values, and source locators were compared claim by claim. The exact reviewed ScienceCard is preserved in `kz_energy.revised_science_card.json`, and `kz_energy.source_review.json.review_material` reproduces it exactly.

## Runtime information boundary

The private Oracle retains the complete reviewed selector program and both source branches. Only `temperature_regime_selector` differs between the two private parameter maps.

Identification no longer exposes that selector, inactive-branch parameters, the internal family name, or a temperature-regime label. It exposes one common scaffold:

```text
e_i = e_i_scale * tau_q^e_i_exponent
```

The two active laws map to the public slots as follows:

| Private world storage key | `e_i_scale` | `e_i_exponent` |
| --- | ---: | ---: |
| `historical` (paper branch A) | 197740 | -0.971 |
| `counterfactual` (paper branch B) | 95430 | -0.935 |

The runtime model token is the neutral `case_specific_closed_form`; the public case ID repeats only the already-public apparatus name plus `instance_1` or `instance_2`. After masking the opaque instance ID, the two worlds' initial Player payloads are exactly equal in each track. Across all diagnostic and hidden conditions, the private Oracle, projected Identification predictor, and Discovery expression return the same value for a given world.

Structurally heterogeneous source branches now fail closed with `identification.no_common_skeleton`. The projection follows the established anti-unification / least-general-generalization idea but deliberately uses a narrower same-tree and parameter-identity-bijection policy; the motivation and credit are documented in `docs/temporal_case_pipeline.md`.

## Acceptance artifacts

- Coordinator result: `../../runs/temporal_kz_source_closed_2026-08-27/result.json`
- Accepted case module: `../../runs/temporal_kz_source_closed_2026-08-27/papers/01_paper_2506_21670v3/cases/kz_incompressible_energy_temperature_regimes.py`
- Four-cell canary: `../../runs/temporal_kz_source_closed_2026-08-27/papers/01_paper_2506_21670v3/cases/kz_incompressible_energy_temperature_regimes.validation.json`
- Reviewed ScienceCard: `kz_energy.revised_science_card.json`
- Source-level review: `kz_energy.source_review.json`
- Bound matched draft: `kz_energy.bound_draft.json`
- Family source-closure review: `kz_energy.family_source_review.json`

The corrected coordinator input is a derived copy that changes only bibliographic credit to `Seong-Ho Shinn et al.` and uses absolute paths to the original frozen source files. The original acquisition packet remains unchanged.

## Verification

- Strict ScienceCard parsing with required structured Oracle outputs: pass.
- Source-card lineage and exact source-review material binding: pass.
- Bound-draft source fidelity and family review material binding: pass.
- Deterministic candidate filter and selector-free Identification projection: pass.
- Historical/counterfactual by Identification/Discovery known-truth canary: 4/4 pass.
- Complete repository test suite: 323/323 pass.
- Runtime private-token scan for family, selector, branch parameters, arXiv ID, and DOI: no matches.

## Scope of the conclusion

The validated claim is existential: the pipeline can transform at least one retrieved paper into an accepted interactive matched family without adding scientific information outside the source packet. It does not yet establish how often arbitrary Nature/Science/PRL papers are transformable, inter-reviewer agreement, or model-evaluation validity. Those require a larger frozen paper sample and should be reported as retention and review statistics rather than inferred from this control.
