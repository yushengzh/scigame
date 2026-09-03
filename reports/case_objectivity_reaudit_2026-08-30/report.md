# Matched scientific case quality review

Review date: 2026-08-31. The unit of admission is a case family, not each of its four matched cells.

## Technical summary

**The currently admitted corpus contains 29 families / 116 matched cells: 20 built-in and 9 temporal. All 29 pass the current scientific, information-boundary, deterministic-Oracle, evaluator, and minimum evaluability gates.** Two temporal candidates remain rejected and are not counted.

This conclusion is deliberately narrower than “the benchmark is perfect.” It means each admitted case is faithful to its cited source or explicitly labelled benchmark idealization, its selected-world private truth is sufficient to answer legal experiments, and its executable components agree. It does not yet test the effect of deterministic versus probabilistic Oracle implementations.

| Cohort | Admitted families | Matched cells | Revise | Block/rejected in cohort |
| --- | ---: | ---: | ---: | ---: |
| Built-in | 20 | 80 | 0 | 0 |
| Temporal (KZ warmup + accepted batch) | 9 | 36 | 0 | 0 |
| **Total admitted** | **29** | **116** | **0** | **0** |

Two additional temporal candidates are retained only as rejected provenance: `lyapunov_scaling` and `quantum_control_threshold`.

## The executable case contract is closed

For every admitted family, the review instantiated historical/counterfactual × identification/discovery and checked the same selected-world truth through the public experiment surface, deterministic WorldModel, and evaluator.

| Check | Result |
| --- | ---: |
| Known-truth submissions accepted | 116 / 116 |
| Predictors from the paired condition rejected | 116 / 116 |
| Sampled valid Oracle queries finite and unit-consistent | 1242 / 1242 |
| Repeated deterministic responses identical | 1242 / 1242 |
| Runtime-registered admitted families | 29 / 29 |
| Unit tests | 410 passed / 0 failed |

These machine checks establish implementation consistency. Source fidelity was reviewed separately against each case credit or temporal source packet; self-consistency alone was not treated as proof of scientific correctness.

## The repairs address scientific meaning, not cosmetic engineering

- The 13 previously revisable hand-authored task families received the missing applicability, fixed-condition, wording, quantity, and unit corrections. `poiseuille_flow` now declares a conditioned inlet distance and fully developed laminar scope; `torricelli_efflux` no longer contradicts its legal orifice-area control. The remaining six hand-authored task families received explicit selected-world applicability and fixed conditions for a future LLM-based Oracle.
- Identification now has one shared structured parameter contract: name, meaning, unit, and admissible finite-real domain. Non-finite and out-of-domain submissions are rejected.
- Temporal anti-unification now publishes constants common to both worlds as fixed constants and exposes only world-varying scientific coordinates. It no longer turns values such as π, 1, or 2 into artificial unknowns.
- The temporal filter rejects a case when its free parameters exceed the number of available scalar observations. For an all-discrete control domain, the budget must also be smaller than the number of possible control settings, so Discovery cannot degenerate into complete lookup.
- `trxas_lorentzian_fit` was narrowed to the source-defined third UHB Lorentzian component. The two unknowns are its center and linewidth; two diagnostic energies give full local rank and one of the three source-supported energies remains held out.
- `self_similar_spreading_radius_ratio` now compares `k=3` and `k=1` inside the same source-reported two-dimensional deterministic simulation, eliminating the former experiment-versus-simulation modality confound.
- `statistical_mean_field_effective_detuning` uses the source relation at representative `d_H=1.5` versus its homogeneous two-dimensional `d_H=2` limit, with budget two over a three-setting domain.

No accepted repair changed an already-correct source coefficient merely to make a test pass.

## Family-level admission

| Family | Pack | Decision | Runtime |
| --- | --- | --- | --- |
| `pendulum` | built-in | PASS | registered |
| `young_double_slit` | built-in | PASS | registered |
| `galileo_inclined_plane` | built-in | PASS | registered |
| `boyle_j_tube` | built-in | PASS | registered |
| `photoelectric` | built-in | PASS | registered |
| `faraday_induction` | built-in | PASS | registered |
| `radioactive_decay` | built-in | PASS | registered |
| `rutherford_scattering` | built-in | PASS | registered |
| `hooke_spring` | built-in | PASS | registered |
| `torricelli_efflux` | built-in | PASS | registered |
| `ohm_circuit` | built-in | PASS | registered |
| `rc_discharge` | built-in | PASS | registered |
| `stefan_boltzmann` | built-in | PASS | registered |
| `newton_cooling` | built-in | PASS | registered |
| `beer_lambert` | built-in | PASS | registered |
| `michaelis_menten` | built-in | PASS | registered |
| `coulomb_force` | built-in | PASS | registered |
| `kepler_orbit` | built-in | PASS | registered |
| `brownian_diffusion` | built-in | PASS | registered |
| `poiseuille_flow` | built-in | PASS | registered |
| `kz_incompressible_energy_temperature_regimes` | temporal | PASS | registered |
| `viscous_inertial_rheology` | temporal | PASS | registered |
| `rilw_msd_scaling` | temporal | PASS | registered |
| `defect_sre` | temporal | PASS | registered |
| `trxas_lorentzian_fit` | temporal | PASS | registered |
| `self_similar_spreading_radius_ratio` | temporal | PASS | registered |
| `stealthy_hyperuniform_localization_scaling` | temporal | PASS | registered |
| `uamo_lyapunov` | temporal | PASS | registered |
| `statistical_mean_field_effective_detuning` | temporal | PASS | registered |

## Why the two candidates remain rejected

- `lyapunov_scaling`: The alpha=0.59 plus-or-minus 0.04 branch is a DNS result, whereas alpha=0.5 is a Kolmogorov/Ruelle theoretical comparator rather than a second paper-reported DNS regime. Minimum redesign: Retain this as a single-world uncertainty-aware case, or source a genuinely distinct paper-reported turbulent regime with the same public control and readout before reconstructing a matched family.
- `quantum_control_threshold`: n=1 and n=2 are simultaneously defined operator or moment orders of the same stochastic channel, not mutually exclusive scientific worlds. Minimum redesign: Represent p_1_star and p_2_star as two readouts in a single world, or find a source-reported alternative channel mechanism that changes the same threshold readout under the same public controls.

The rejection is about matched-family semantics, not whether the cited equations are numerically false. A correct comparator can still be unsuitable as the second world if it changes the observable or evidence modality.

## Identification and Discovery are now minimally evaluable

Identification exposes a complete case-specific model scaffold and only its unknown scalar coordinates. Discovery receives the same apparatus, controls, readouts, units, budget, and selected-world evidence, but only the shared expression grammar. In both tracks the primary outcome remains held-out predictive performance, not exact recovery of the author’s algebraic spelling.

Every admitted family satisfies the necessary observation-capacity check. A numerical local-Jacobian review also found a full-column-rank diagnostic design in both worlds for all 29 families. This is a case-review result, not a brittle universal numerical gate and not a claim that an LLM must estimate every coefficient exactly.

## Oracle implementation is intentionally outside this admission decision

The scientific case is defined independently of how evidence is rendered. The later ablation must compare two separate implementations behind the same proposal/response contract:

1. `deterministic`: `CaseOracle + WorldModel` computes the declared evidence exactly.
2. `probabilistic`: an LLM-based Oracle reads the complete selected-condition data-generating specification and generates the evidence response.

This review did not implement or compare those modes. In particular, the existing LLM presentation layer that copies deterministic simulator outputs exactly must not be mislabeled as a stochastic LLM-based Oracle. Keeping the task truth fixed first prevents Oracle behavior from being confused with task-definition errors.

## Evidence boundary and remaining limitation

PASS means source-faithful or explicitly authored within the stated idealization; it is not an independent experimental replication. Temporal parameter descriptions generated from the AST are executable and non-ambiguous at the formula-position level, but some units remain stated as `expression-defined` rather than source-level physical parameter names. If parameter interpretability becomes a scored construct, the abstractor and reviewer should emit those meanings and units explicitly; AST guessing should not be used.

The benchmark is now ready for development runs on these 29 registered families with the deterministic Oracle. The deterministic-versus-probabilistic Oracle ablation should start only after the probabilistic interface is implemented as a genuinely separate path.
