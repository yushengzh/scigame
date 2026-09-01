# Triage of the first three ScienceCard generation failures

## Outcome

Two papers are recoverable with a much narrower scientific target; one is not suitable for the benchmark's current point-valued matched Oracle.

| Paper | Compact matched relation? | Failure diagnosis | Fresh single-paper action |
|---|---|---|---|
| `2601.12642v1`, shear-thickening drop impact | Yes: inertial-dilatant number with fitted `beta0=44°` vs `41°` branches | Overbroad extraction plus many schema violations | Retry on the ID relation only |
| `2510.15228v1`, finite-frequency FRI | No under the current contract | Inequality was incorrectly converted to an exact response; source lacks two numeric curves | Mark ineligible; do not spend another generation call |
| `2505.09538v1`, turbulent Lyapunov scaling | Yes after source-faithful normalization: exponent `0.59` vs mean-field `0.5` | Unreported prefactors were inserted into executable truth | Retry on normalized DNS scaling only |

All three repair attempts returned the same first validator failure as the initial attempt. The failures therefore were not caused by a too-strict one-pass parser: the repair model did not remove the invalid construction.

## 1. `paper_2601_12642v1`

### Scientific suitability

The source contains a complete, distinguishable two-branch relation within the existing expression grammar:

`ID = rho * kappa * U0 / (A * mu_w * (phi - phi_c) * D0)`

The common equations define `rho(phi)`, `kappa(phi)`, the dilatancy angle and effective friction coefficient `A`. The source gives two fitted central friction angles: `beta0=44°` for Regime 2 and `beta0=41°` for Regime 3. Changing only that private parameter creates a source-grounded matched pair. Relevant source lines are 101, 148-174 and 217-232.

No unsupported `abs` or `derivative` operation is needed for this target. `tan(beta)` can be expressed using the supported `sin`, `power`, arithmetic and `exp` operations.

### Why both attempts failed

Initial and repair parser failure:

`$.claims[1].oracle_outputs.F.args[1].args[1].args[1].args[1].args[1].op: unsupported expression operator`

Both responses retained `abs` and `derivative`. They also contained additional latent violations: undeclared `D_0`, `rho`, `t`, `h`, `kappa`, `r_c`, `F_i`, `F_d`, and `w_F` variables; unlinked parameters; and an `ID` claim whose readout was not declared. This was not a bad paper. It was an overbroad and internally inconsistent extraction.

### Narrow retry

Use only:

- controls: `phi in [0.38,0.43]` and `impact_velocity in [0.5,7.2] m/s`;
- readout: `inertial_dilatant_number`;
- laws: permeability, friction coefficient, and Eq. 6;
- branches: central `beta0=44°` and `beta0=41°`;
- provenance: retain `+/-2°` and `+/-5°`, without uncertainty propagation.

Exclude transient force, contact geometry, time derivatives, the unified weighting function and `t_ratio`.

## 2. `paper_2510_15228v1`

### Scientific suitability

The compact source result is an inequality:

`|R(omega)|^2 <= A S(omega)`.

This does not determine a unique response at a queried frequency. The equilibrium and non-equilibrium periodic-potential examples obey the same inequality, while the source packet contains no tabulated spectral curves. Linear dynamics gives equality, but the equality is again the same in and out of equilibrium and therefore supplies no distinguishable matched branches.

### Why both attempts failed

Initial and repair parser failure:

`$.claims[0].oracle_outputs: ... velocity_power_spectral_density ... is not a public control`

The response attempted to use both readouts as input variables and self-referenced the response output. More seriously, it assigned `A=1.0` while acknowledging that the demonstration did not report a numeric `A`, invented the frequency interval `[0,10]`, and treated an upper bound as an exact response value.

### Narrow disposition

Do not retry it as an accepted family. A single-paper disposition run should focus on lines 125-149 and 203-209 and return `case_authoring_ready=false`. Reconsider only if the benchmark gains an inequality-valued truth contract or the source packet gains numeric `S_v(omega)` and `R_v(omega)` data for two conditions.

## 3. `paper_2505_09538v1`

### Scientific suitability

The paper reports the observed intermittency-corrected relation `lambda proportional to Re^0.59` with exponent `0.59 +/- 0.04`, and explicitly contrasts it with the Kolmogorov mean-field prediction `lambda proportional to Re^0.5`. The missing multiplicative amplitude can be removed without inventing data by querying a normalized relationship:

`lambda(Re) / lambda(50) = (Re / 50)^alpha`, for `50 <= Re <= 1400`.

This yields a clean matched pair: historical `alpha=0.59`, source-motivated counterfactual `alpha=0.5`. It uses only `divide` and `power`.

### Why both attempts failed

Initial and repair parser failure:

`$.claims[0].oracle_outputs: ... prefactor_DNS ... is not an allowed parameter`

The source reports no absolute prefactor. The response explicitly acknowledged this, yet both attempts retained four invented executable parameters: `prefactor_DNS`, `prefactor_GOY`, `prefactor_gamma3_std`, and `prefactor_mean_gamma3`. The GOY curve is also explicitly rescaled by an unspecified constant in the paper, so it cannot provide an absolute Oracle branch.

### Narrow retry

Use only the DNS cluster at source lines 43-48, 75-86, 365-400, 460-488 and 629-635:

- control: `reynolds_number in [50,1400]`;
- fixed reference: `reference_reynolds_number=50`;
- readout: `relative_lyapunov_rate`;
- historical law: `(Re/50)^0.59`;
- counterfactual law: `(Re/50)^0.5`;
- keep `+/-0.04` as provenance only.

Exclude GOY absolute values, all gamma readouts and every free prefactor.

## Recommended order

Retry the Lyapunov paper first: its normalized AST is the smallest and least ambiguous. Retry the drop-impact paper second: it is source-complete but has a deeper expression tree. Do not retry the finite-frequency FRI paper under the current Oracle contract.

The companion JSON contains the exact parser paths and machine-readable decisions.
