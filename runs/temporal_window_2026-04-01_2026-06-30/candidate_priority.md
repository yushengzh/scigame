# Frozen-source candidate priority for the remaining cohort

Date: 2026-08-27

Scope: only the frozen textual packets under
`acquired_bench_cohort/papers/<paper_id>/source_packet.txt` were used.  A paper
is ranked highly only when the packet itself supports all of the following:

1. one shared, manipulable public control and one shared numerical readout;
2. two source-grounded private branches under that same interface;
3. a unique finite numerical output expressible with the existing arithmetic
   expression grammar, without reading values from an untranscribed figure or
   inventing a prefactor.

The ranking is about conversion readiness, not scientific importance.

## Summary

| Priority | Paper | Decision | Main reason |
| ---: | --- | --- | --- |
| 1 | `paper_2505_04242v1` | **Best candidate; one figure-support check remains** | Same normalized-friction readout has explicit square-root fits for several private interparticle-friction branches, including all coefficients. |
| 2 | `paper_2512_17777v2` | **Good theoretical/simulation candidate** | Same initial power-imbalance control and anomalous-correlation growth-rate readout support a zero-growth WT branch and an explicit thresholded AC-KE branch. |
| 3 | `paper_2509_22773v1` | **Promising, but numeric time domain needs closure** | Ground-state and finite-temperature preparations give different closed normalized decay laws for the same TFIM energy observable; the packet states only asymptotic domain inequalities. |
| 4 | `paper_2509_17085v1` | **Not authorable as an active case yet** | The two branches have exact limiting S-matrix values, but no source-grounded finite-detuning numerical law. |
| 5 | `paper_2504_05380v2` | **Not authorable under the unique-output gate** | It gives robust stretching exponents, but only bounds/scaling with unknown constants and not one identical statistic in both branches. |
| 6 | `paper_2601_07810v4` | **Not authorable under the unique-output gate** | Critical exponents are explicit, but the scaling functions/prefactors are not; the candidate branches also use different readouts. |
| 7 | `paper_2507_00684v1` | **Not authorable** | The Gaussian velocity model is executable, but the packet supplies only one branch; the order–diffusion correlation lacks an intercept and a second law. |

## 1. `paper_2505_04242v1`: dense frictional suspension

### Minimal matched family

- Public control: Stokes number (s=St=I^2/J).
- Public readout: normalized macroscopic friction (r=\mu/\mu_c).
- Shared fixed condition: pressure-imposed rheology at
  (K_\phi=J+0.1I^2=0.065).
- Private branch A: microscopic friction (\mu_f=0.15), with
  (a_\mu=14.3) and (\alpha_\mu=0.029).
- Private branch B: microscopic friction (\mu_f=0.80), with
  (a_\mu=26.5) and (\alpha_\mu=0.00875).

The source fit is

\[
K_\mu=J+\alpha_\mu I^2,\qquad
r=1+a_\mu\sqrt{K_\mu}.
\]

At fixed (K_\phi=0.065), eliminating (J) and (I^2) gives the one-control
Oracle law

\[
J(s)=\frac{0.065}{1+0.1s},\qquad
K_\mu(s)=0.065\frac{1+\alpha_\mu s}{1+0.1s},\qquad
r(s)=1+a_\mu\sqrt{K_\mu(s)}.
\]

This uses only `add`, `multiply`, `divide`, and `power(..., 0.5)`.

### Domain and locators

- Source domain: (0.01\le St\le300): lines 236–238.
- Definitions (J), (I^2), (St=I^2/J), and (K=J+\alpha I^2): lines
  113–125.
- The fixed-(K=0.065) comparison and two observed Stokes numbers: lines
  274–276.
- The normalized-friction fit form: lines 340–348.
- All branch parameters, including uncertainties in (\mu_c): lines 352–360.
- The paper explicitly says (\mu_f) changes the (\mu) transition while the
  (\phi) transition remains fixed: lines 365–373.

### Remaining narrow check

The textual packet states the overall (St) range and the fit coefficients,
but it does not transcribe the plotted (K_\mu) support for each (\mu_f).
Before acceptance, a reviewer should confirm from the frozen source figure that
the proposed fixed-(K_\phi=0.065) curve stays inside the fitted support for
both selected branches.  If that cannot be established, keep (J) and (I^2)
as two public controls and obtain their plotted numeric bounds through a
reviewer-authored figure-evidence addendum.  No formula revision is needed.

## 2. `paper_2512_17777v2`: anomalous-correlator instability

### Minimal matched family

- Public control: nonnegative initial normalized power imbalance
  (x=\Delta N^0/N\), (0\le x\le1).
- Public readout: dimensionless maximum anomalous-correlator growth rate
  (g=\operatorname{Re}[\lambda(0)]L_{nl}).
- Shared fixed conditions: initially uncorrelated Gaussian spectra,
  (M(0)\simeq0), homogeneous mode (\Omega=0), weak nonlinearity,
  (\kappa=2/3), and (a=\alpha L_{nl}=0.2).
- Private branch A, standard WT mechanism: anomalous correlations are excluded,
  so (g_{WT}(x)=0).
- Private branch B, AC-KE mechanism:

\[
g_{AC}(x)=2\sqrt{\max\{0,\;a(2x/3-a)\}},\qquad a=0.2.
\]

The branches coincide for (x\le0.3) and separate for (x>0.3).  The formula
is directly representable with `maximum` and `power(..., 0.5)`.

### Domain and locators

- Standard WT assumes (m=0) at every propagation distance: lines 211–224;
  its irreversibility and entropy-growth statement are at lines 234–234.
- Definition of (x), Gaussian initially uncorrelated spectra, and the
  homogeneous-mode stability calculation: lines 325–341.
- Exact growth rate and threshold: lines 344–357.
- (a=0.2), (\kappa=2/3), (L_{nl}=1/(\gamma N)), and the validated
  (x=0.6) simulation setting: lines 364–370.
- The AC-KE branch is reversible and conserves
  (\Delta N^2+4|M|^2): lines 374–388.
- The experiment can tune relative polarization power and measure (M,N_x,N_y):
  lines 400–407.  The thermalizing (x=0) case and a measured stable case are
  described at lines 410–420.

### Interpretation boundary

This is strongest as a theoretical/numerical active world.  The paper says the
physical experiment could not directly prepare a large imbalance together with
negligible initial (M) (lines 462–467).  The case must therefore say that the
Oracle evaluates the paper's NLSE/kinetic model, not claim that every query was
realized in the reported fiber experiment.  Also, branch A is the paper's
standard-WT mechanism/closure, not a second empirical fit.

## 3. `paper_2509_22773v1`: shallow TFIM critical quenches

### Minimal possible family

Use the same TFIM energy-primary observable (\epsilon_I), the same evolution
time control (t), and report its value normalized to a source-valid reference
time (t_0).  The private fixed condition is the initial preparation.

- Ground-state preparation:

\[
R_{GS}(t;t_0)=
\frac{\langle\epsilon_I(t)\rangle}{\langle\epsilon_I(t_0)\rangle}
=\sqrt{\frac{t_0}{t}}\exp[-4Jg(t-t_0)].
\]

- Finite-temperature (\epsilon)-perturbed preparation, where (x_\Phi=1)
  removes the linear-in-(t) term:

\[
R_{FT}(t;t_0)=\exp[-2\pi(t-t_0)/\beta].
\]

Normalization removes the time-independent amplitudes rather than inventing
them.  Both laws fit the existing `exp`/`power` grammar.

### Domain and locators

- The two source preparations and their distinct scaling forms: lines 96–108.
- Exact ground-state TFIM (\sigma_I) and (\epsilon_I) formulas: lines
  250–274, especially 266–272.
- The reported finite-temperature (\epsilon)-quench depth is
  (g_\epsilon=5.62\times10^{-3}): lines 287–304.
- Finite-temperature assumptions (\beta J\gg1) and
  (g\ll1/(\beta J)): lines 322–340.
- First-order finite-temperature law and constants: lines 356–367.
- For (x_\Phi=1), (B\propto\sin(\pi x_\Phi)=0), leaving pure exponential
  decay: lines 390–395; the longer derivation is at lines 842–860.

### Why it is not ready yet

The source gives asymptotic conditions rather than a finite numeric interval:
ground-state scaling takes (g\to0) before the late-time limit, while the
finite-temperature expression requires (2\pi t\gg\beta).  The packet gives no
single numerical (\beta) and no common, explicitly supported interval for
(t_0,t).  A figure/table source review must first bind those values.  Choosing
an arbitrary interpretation of “\(\gg\)” would make the Oracle domain
author-created rather than paper-grounded.

## 4. `paper_2509_17085v1`: two-excitation atomic-array scattering

The cleanest two source branches are the band maximum and saddle point:

\[
L(E\pm i0)\propto
\begin{cases}
-\log|E-E_{max}|,&E\to E_{max},\\
\pm i\log|E-E_{sadd}|,&E\to E_{sadd},
\end{cases}
\qquad
s\to\begin{cases}+1,&E\to E_{max},\\-1,&E\to E_{sadd}.
\end{cases}
\]

Locators: critical-point definitions and the two (L) branches are lines
207–218; the exact limiting S-matrix values and interpretation are lines
221–231.  The displayed validation fixes total momentum (P=0) at line 229.

**Decision:** not authorable as a useful active case.  The only unique outputs
are the two values at asymptotic points.  At finite detuning, the proportionality
constants and the dispersion integral are required.  The cross-section formula
at lines 253–265 likewise requires (a_\alpha,v_g,L_\beta), and the scaling
table is an untranscribed figure (lines 294–298).  Returning only (+1) or
(-1) would reduce the task to a one-query discrete label test rather than an
active relationship-discovery case.

## 5. `paper_2504_05380v2`: diffusion-limited dephasing

The tempting pair is

- random charge-conserving circuits with finite void diffusivity:
  (Z(t)\sim\exp[-O(t^{1/2})]);
- translation-invariant Floquet/Hamiltonian dynamics with divergent low-density
  diffusivity: (C(t)\gtrsim\exp[-O(t^{2/3})]).

Locators: the two mechanisms and exponents are summarized at lines 510–517;
the random-circuit statistic and lower bound are lines 537–567; the
translation-invariant argument, transport equation, and (2/3) result are
lines 589–612.  Extrinsic dephasing produces exponential decay, but its rate is
not supplied (supplement lines 109–120).

**Decision:** fail the unique-output gate.  The source states bounds/scaling
with unknown constants, not an equality with a numerical coefficient.  It also
uses the circuit-averaged second moment (Z) in one branch and the correlation
amplitude (C) in the other.  It is an excellent future relationship-only
case if the benchmark later admits exponent scoring, but setting a unit
prefactor now would alter the paper's claim.

## 6. `paper_2601_07810v4`: Ising supercritical magnetocalorics

The source provides the explicit exponents

\[
h\propto t^{\beta+\gamma}=t^{1.563},\qquad
\Gamma_H^{peak/dip}\propto t^{1-\beta-\gamma}=t^{-0.563},
\]

for (t>0), with (t=(T-T_c)/T_c), (h=(H-H_c)/H_c),
(H_c\simeq1.04\) T, and (T_c\simeq0.30\) K.  Locators: lines 112–114 and
140–170 for the measured definitions and exponents; the free-energy,
susceptibility, and Grüneisen scaling derivation is at lines 265–288.

**Decision:** fail the unique-output/two-branch gate.  The functions
(\phi_C,\phi_\chi,\phi_\Gamma), the crossover constants, and the peak/dip
amplitudes are not numerically specified in the textual packet.  The two
explicit power laws concern different readouts, so they cannot serve as matched
private branches.  The 195 mK and 586 mK cooling outcomes at lines 186–191 are
isolated protocol results, not a queryable law.

## 7. `paper_2507_00684v1`: granular structural order

The packet contains one executable velocity law,

\[
v_y(x,y)=\frac{Q}{\sqrt{4\pi by}}
\exp\left(-\frac{x^2}{4by}\right),
\]

at lines 84–91.  It also reports (b/d=4.5) for the most crystalline case
(lines 91–93), an order threshold near (\langle|\psi_6|\rangle_t=0.6)
(lines 104–108), and an order–diffusion correlation (r=0.942) with fitted
slope 4.8 (lines 110–116).

**Decision:** not authorable.  The amorphous-branch (b), the line intercept,
and a second velocity law are absent from the text; the relevant values live in
figures.  The crystalline plug-flow component is described qualitatively but
not given a formula.  Combining (b/d=4.5), a possible order value of 0.75,
and slope 4.8 as though they were one matched data point would be unsupported.

## Recommended next action

Run fresh single-paper ScienceCard extraction in this order:

1. `paper_2505_04242v1`, focused only on (K_\phi,K_\mu,\mu/\mu_c) and the
   three (\mu_f) rows; require reviewer confirmation of numeric fit support.
2. `paper_2512_17777v2`, focused only on the (\Omega=0) anomalous-correlator
   growth rate and WT-versus-AC closure; label it a theoretical/simulation
   environment.
3. `paper_2509_22773v1` only if a source review first binds a finite common time
   interval for the normalized (\epsilon_I) readout.

Do not spend provider calls on the remaining four papers under the current
unique-numerical-Oracle contract.
