# KZ registered temporal family objectivity audit

## Verdict

**PASS.** The registered family is scientifically closed against the frozen paper source, including the historical world. Its runtime Oracle evaluates the source-reported central fitted laws correctly and labels the returned value correctly: it is a deterministic fitted-curve value, not a newly sampled ensemble observation.

Audited family: `src/role_benchmark/temporal_cases/kz_incompressible_energy_temperature_regimes.py`

Sole scientific authority:

- `runs/temporal_kz_source_truth_closure_2026-08-27/frozen_sources/01_paper_2506_21670v3.txt`
- `tmp/pdfs/kz_source_review/2506.21670v3.pdf`

## Source-to-case closure

| Item | Registered truth | Paper support | Result |
|---|---|---|---|
| Historical branch | `T=10^-6`; `E_i = 197740 tau_Q^-0.971` | Figure 4 caption at line 390; fitted law at line 443 | PASS |
| Historical provenance | 2,000 realizations; plotted point error bars are 1 SD; fit `+/- 5.010e4`, `+/- 0.052` | lines 390 and 443 | PASS |
| Alternate branch | `T=1`; `E_i = 95430 tau_Q^-0.935` | Figure 4 caption at line 390; fitted law at line 443 | PASS |
| Alternate provenance | 1,000 realizations; plotted point error bars are 1 SD; fit `+/- 2.951e4`, `+/- 0.068` | lines 390 and 443 | PASS |
| Fit method | weighted least squares, inverse-variance weights | line 445 | PASS |
| Control | dimensionless quench duration of the linear chemical-potential ramp | lines 148-157 and 460 | PASS |
| Readout | total incompressible kinetic energy of the solenoidal density-weighted velocity at `t_eq` | lines 187-200 and 394-413 | PASS |
| Equilibration time | source-defined operational time from the condensate-growth crossover | lines 167-172 and 514-517 | PASS |
| Common settings | homogeneous periodic box and source-reported relaxation/ramp/interaction/damping/cutoff settings | lines 154-157 and 491-507 | PASS |
| Query domain | common conservative interval `tau_Q in [100,1000]` | Figure 4 on PDF page 8; packet lines 1110-1112 | PASS |

The original paper reports the formulas with fit-parameter `+/-` values but does not name the statistical convention for those parameter uncertainties. The case therefore keeps them as private provenance and returns only the central fitted curve. This is the minimal source-faithful choice; it does not manufacture a sampling distribution.

## Historical-world Oracle verification

The independent reference was evaluated at 60-digit decimal precision from the source formula and converted once to binary64. The runtime path was the actual `CaseOracle.respond`, not a direct call to a helper function.

Source central law:

`E_i = 197740 * tau_q^(-0.971)`

| `tau_q` | CaseOracle | high-precision decimal reference | absolute error vs rounded binary64 | ULP error |
|---:|---:|---:|---:|---:|
| 100 | 2259.9276192132947 | 2259.9276192132945486875... | 0 | 0 |
| 271.828 | 855.8445147557965 | 855.8445147557962161986... | 2.274e-13 | 2 |
| 300 | 777.6958679812643 | 777.6958679812641623834... | 1.137e-13 | 1 |
| 1000 | 241.59866480100177 | 241.5986648010017442951... | 2.842e-14 | 1 |

The 0-2 ULP differences are ordinary binary64 operation-order rounding; the runtime evaluates exactly the registered central formula.

## Alternate source branch verification

The branch registered under the benchmark world name `counterfactual` is not an invented law. It is the paper's real `T=1` comparison branch, used counterfactually only relative to the historical `T=10^-6` condition.

Source central law:

`E_i = 95430 * tau_q^(-0.935)`

| `tau_q` | CaseOracle | high-precision decimal reference | absolute error vs rounded binary64 | ULP error |
|---:|---:|---:|---:|---:|
| 100 | 1287.3152788572147 | 1287.3152788572150393053... | 2.274e-13 | 1 |
| 271.828 | 505.3821008121195 | 505.3821008121196426688... | 1.137e-13 | 2 |
| 300 | 460.867996160474 | 460.8679961604741232555... | 1.705e-13 | 3 |
| 1000 | 149.5150546204206 | 149.5150546204206692155... | 5.684e-14 | 2 |

## Oracle response contract

For both worlds and both tracks:

- repeated identical queries returned byte-for-byte equal typed responses;
- Identification and Discovery returned identical evidence for the same world and control;
- the unit was `dimensionless`;
- the uncertainty text said that source-reported fit-parameter values are not propagated;
- the message identified the value as the central source-defined weighted-least-squares fit;
- requests below 100, above 1000, or with `replicates=2` returned `OUT_OF_RANGE` and no evidence.

The known-truth structured submissions passed all four matched cells with zero hidden-test error.

## Public/private isolation

The historical and alternate-world public payloads are identical except for their opaque `instance_1`/`instance_2` identifiers. Neither track exposes temperature, ensemble count, central coefficients, exponents, selector, or private branch. Identification exposes only the power-law skeleton required by that track; Discovery exposes no candidate law family.

For a private evaluation pack, the instance-to-world mapping must remain private. This is an isolation requirement, not a scientific mismatch in the case.

## Residual scope limits

- The Oracle is an analytic interpolation/evaluation of the source fit, not a replay of raw data.
- Fit-parameter uncertainty is not propagated because the source does not specify its convention.
- `[100,1000]` is intentionally a conservative common fitted-curve interval; it is not presented as the full raw sampling grid.
- No claim is made that the source's `T=1` comparison is a physically nonexistent world.

Machine-readable evidence, including exact numerical comparisons, is in `audit.json` in this directory.
