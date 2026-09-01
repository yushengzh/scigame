# ScienceCard generation failures 6--9: source-grounded triage

## Scope and decision rule

This note independently checks the frozen TeX, both recorded attempts when a
repair attempt exists, and the terminal error for:

- `paper_2503_11604v1`;
- `paper_2511_07664v2`;
- `paper_2512_08761v2`; and
- `paper_2508_10802v2`.

The decision is deliberately narrower than “does the paper contain an
interesting equation?”.  Category **A** requires one source-contained family
with all of the following:

1. two distinguishable branches or regimes explicitly reported by the paper;
2. the same operational readout in both branches;
3. at least one common, source-supported numeric Player control domain (a
   nonzero interval or at least two reported values); and
4. a finite point response that the current Oracle can evaluate uniquely from
   the frozen source using the existing scalar expression grammar, without
   setting an unreported prefactor to one or turning `~`, `\propto`, an
   inequality, or an asymptotic order into an equality.

Under this rule, all four papers are **B for the current benchmark and frozen
source packets**.  This does not mean that their science is weak.  It means
that the information retained in the packet does not close a two-branch,
point-valued Oracle family.

| Paper | Decision | Exact reason |
|---|---|---|
| `2503.11604v1`, active droplets | **B** | The candidate response is only `Omega proportional to k2`; its prefactor and a multi-point `k2` domain are absent, and no second point-valued branch is reported. |
| `2511.07664v2`, FPUT shock time | **B (current packet)** | Coherent/random phases are a real branch pair, but both laws are asymptotic, the random-branch prefactor is absent, and frozen TeX gives no common finite `p` query set. |
| `2512.08761v2`, active wetting | **B** | The ratchet-current result lacks a scalar prefactor/profile closure; the exact minimal-model instability threshold is one finite-size law plus its limit, not two reported worlds. |
| `2508.10802v2`, arch snap-through | **B (current Oracle)** | Two real formulas exist, but their modal coefficients are not supplied as scalar values or elementary functions, their `lambda` domains are disjoint, and no common executable query domain is reported. |

There is consequently no scientifically valid `--science-card-focus` retry to
recommend for these four packets.  A narrower prompt can stop the two runaway
generations, but it cannot create missing source values or a missing second
branch.

## 6. `paper_2503_11604v1` — Excitability and Oscillations of Active Droplets

### Recorded generation failure

The initial call and the one bounded repair call both completed with
`finish_reason=stop`.  The terminal parser error is:

```text
science_card.schema at $.controls[0].allowed_values:
must contain at least two unique values
```

The repair response is textually unchanged from the initial response.  The
response itself correctly says `case_authoring_ready=false` and records that
the cycle-frequency constant is missing, but nevertheless inserts
`cycle_freq_proportionality_constant=1.0` and compiles
`Omega = C * k2`.  That scalar is not in the paper and must not be retained.

Artifacts:

- frozen TeX: `family_generation/frozen_sources/06_paper_2503_11604v1.txt`;
- initial and repair exchanges:
  `family_generation/papers/06_paper_2503_11604v1/science_card/`;
- terminal error:
  `family_generation/papers/06_paper_2503_11604v1/science_card/failure.json`.

### Source check

The paper says only that the oscillation frequency follows
`Omega proportional to k2` and that the second reaction is rate-limiting
(frozen-source lines 315--317 and 387--396).  It gives neither an absolute
frequency nor the proportionality constant.  Table 1 reports `k2/k1=1.0` and
`delta=4` for several fixed Figure 4 panels, while the row for the frequency
scan in Figure 4(c) contains dashes for both quantities (lines 636--647).  The
TeX therefore does not provide two exact `k2` settings, a finite interval, or
the plotted values.

The other equations do not close a matched family:

- the critical fuel relation is approximate and contains `Theta`, which is a
  function of thermodynamic parameters rather than a supplied scalar
  coefficient (lines 241--250);
- an excitable fixed point versus an oscillatory state is a qualitative state
  distinction, not two finite cycle-frequency laws; and
- entropy production with versus without the second reaction is described as
  constant versus increasing with fuel, but the paper gives no pair of
  point-valued response functions (lines 406--418).

### Decision

**B: not suitable for the current point-valued matched Oracle.**  Normalizing
`Omega(k2)` by a reference frequency would cancel an unknown constant, but the
paper packet supplies neither a reference `k2` nor a second source-supported
query value, and still supplies no second reported response branch.  A prompt
repair cannot cure either omission.

## 7. `paper_2511_07664v2` — Random Initial Data and Average Shock Time in the FPUT Chain

### Recorded generation failure

Both calls completed.  The terminal parser error is:

```text
science_card.schema at $.claims[0].oracle_outputs:
... epsilon_power ... is not an allowed parameter
```

The initial response uses an undeclared `epsilon_power`.  The repair response
does not merely miss the repair: it changes the square-root subtree to a power
whose base and exponent are both the undeclared parameter.  Both responses
also invent `p=[20,100,200,400,800]` while explicitly acknowledging that the
shock-time figure's exact `p` values are not listed in the text.

Artifacts:

- frozen TeX: `family_generation/frozen_sources/07_paper_2511_07664v2.txt`;
- initial and repair exchanges:
  `family_generation/papers/07_paper_2511_07664v2/science_card/`;
- terminal error:
  `family_generation/papers/07_paper_2511_07664v2/science_card/failure.json`.

### Source check

This paper does contain a scientifically meaningful pair:

- coherent phases:
  `t_s^{-1} ~ alpha * sqrt(epsilon) * p^(3/2) / N`;
- random phases:
  `<t_s^{-1}> ~ alpha * sqrt(epsilon) * p * sqrt(log p) / N`.

They are reported at frozen-source lines 162--171.  However, `~` is an
asymptotic scaling statement, not an exact point prediction.  The coherent
figure supplies one fitted coefficient, `4.774e-5`, at
`alpha=1`, `beta=0.1`, `epsilon=1e-3`, `N=2048` (lines 174--176).  The random
figure gives only the shape `p sqrt(log p)`, uses `N=16384`, and reports no
coefficient (lines 178--180).  Its mean is over 1,000 phase realizations.

The common domain is also not closed.  The analytic statement says “for large
`p`” without a numeric lower bound (lines 167--171), and the captions do not
enumerate the plotted `p` values.  The `p=20` example elsewhere describes one
energy-spectrum initial condition; it does not establish the five values
invented by the model or a common shock-time query grid.

### Decision

**B for the current frozen packet.**  This is a better scientific candidate
than paper 6 because coherent/random phases are genuine reported branches.
It is still not point-query authorable.  A normalized readout could cancel
branch prefactors only after the source establishes a common reference `p`
and at least one additional common value.  A future figure-evidence addendum
or tabulated data could provide those facts; a narrower LLM focus alone
cannot.

## 8. `paper_2512_08761v2` — Spontaneous Ratchet Currents and Transition Dynamics in Active Wetting

### Recorded generation failure

The only call exhausted the 32,768-token visible-output limit and ended with:

```text
science_card.incomplete_generation at $:
provider generation did not complete (length)
```

This is a response-loop failure, not a large necessary ScienceCard.  The text
repeats the sentence beginning “The minimal model provides an explicit formula
for eta*” 66 times while alternating between the ratchet-current scaling and
the minimal-model threshold.  No repair call is allowed after incomplete
generation.

Artifacts:

- frozen TeX: `family_generation/frozen_sources/08_paper_2512_08761v2.txt`;
- exchange and failure:
  `family_generation/papers/08_paper_2512_08761v2/science_card/`.

### Source check

The main ratchet-current result is exact only as a functional of the complete
steady density profile,

```text
J_ss = -M[rho] integral rho(x) dV/dx dx.
```

The profile is not a scalar Player control or a supplied closed-form
parameter.  After eliminating it, the paper states only
`J_ss ~ ell_s^(-1)` for large systems, without a prefactor or a finite numeric
domain (lines 113--141).  The current's vanishing near `epsilon*` is described
as continuous, but no exponent or point function is reported.

The appendix does give a closed threshold for the minimal model,

```text
eta* = sqrt(2 alpha kappa) /
       [coth(L sqrt(alpha/(8 kappa))) - sqrt(8 kappa/alpha)/L],
```

with the large-`L` limit `sqrt(2 alpha kappa)` (lines 300--336).  This is one
finite-size law and its thermodynamic limit, not two distinguishable
source-reported mechanisms.  The limit is not a second finite world at the
same numeric `L`.  The only explicit illustrative material parameters are
`alpha=kappa=1, eta=2` (lines 187--190), which do not provide a multi-point
control domain.

Other apparent pairs also fail closure: the three transition stages have
unspecified amplitudes/rates, and full-to-partial versus partial-to-full
pathways are quantitative versus qualitative rather than two common-readout
laws (lines 154--170).

### Decision

**B: not suitable for the current matched-family contract.**  The exact
minimal-model threshold could support a valuable single-law benchmark if the
benchmark later admits a one-world theorem-discovery task and a source-backed
numeric domain.  It cannot supply the required two reported worlds now.

## 9. `paper_2508_10802v2` — Snap-Through Time of Arches Is Controlled by Slenderness and Imperfections

### Recorded generation failure

The only call also exhausted 32,768 output tokens and terminated as incomplete.
Its opening assessment identifies the two relevant formulas and explicitly
notes that `r_B`, `q_B`, `r_LP`, and `q_LP` have no numeric values in the
source.  It then repeats the sentence that the bifurcation snap-through time
is given by Eq. 9 159 times instead of returning the JSON object.

Artifacts:

- frozen TeX: `family_generation/frozen_sources/09_paper_2508_10802v2.txt`;
- exchange and failure:
  `family_generation/papers/09_paper_2508_10802v2/science_card/`.

### Source check

This is the closest of the four papers to category A.  It reports two genuine
snap-time formulas for two buckling mechanisms:

```text
t_B  = lambda / sqrt(r_B DeltaP)
       * log[(4/p0_A) sqrt(2 r_B/(q_B DeltaP))]

t_LP = [3/(64 pi^2 r_LP q_LP DeltaP)]^(1/4)
       * Gamma(1/4)^2.
```

The main-text locators are lines 393--417 and 510--529.  The two regimes are
also physically distinct: limit-point buckling occupies approximately
`3.9 < lambda < 10`, whereas bifurcation buckling occupies `lambda > 10`
(lines 228--243).  Imperfection affects the latter but not the former
(lines 307--321).

Three independent blockers prevent a current Oracle family:

1. **No common `lambda` domain.**  The two formulas apply on opposite sides of
   the hill-top threshold.  The explicit examples `lambda=6` and `lambda=12`
   are branch conditions, not two values of one common Player control.
2. **The other common domain is not numeric.**  Both analyses assume
   `DeltaP << 1`; the TeX supplies one explicit demonstration value,
   `DeltaP=1e-2`, but no nonzero interval or second shared value
   (lines 261--273 and 228--233).
3. **The response coefficients are not scalar-closed.**  `r_LP` and `q_LP`
   are modal inner products (lines 1160--1188).  `r_B` and `q_B` depend on
   infinite eigenfunction sums or inner products involving solutions of
   linear boundary-value problems (lines 1480--1521).  Their trends appear in
   referenced figures, but the frozen packet contains TeX only, not tabulated
   coefficient values.  Those objects cannot be represented as fixed
   source-valued parameters or evaluated by the current elementary scalar
   grammar.

The `p0_A=0` limit does not solve this: it produces infinite snap time in the
bifurcation branch (lines 428--439), not a finite point readout.  Replacing the
modal coefficients with one, or replacing the two formulas by only their
`DeltaP^(-1/4)` and `DeltaP^(-1/2)` orders, would change the paper's claim.

### Decision

**B for the current Oracle and frozen packet.**  This paper should be retained
as a high-priority future candidate, but not accepted now.  It becomes
reconsiderable only if a source packet supplies verified scalar tables or a
deterministic source-derived solver for all four modal coefficients at fixed
branch-specific slendernesses, together with a common numeric query set.  A
prompt-only `science-card-focus` cannot provide those quantities.

## Run-level disposition

The schema errors for papers 6 and 7 are real, but fixing their first parser
paths would not make the underlying cards scientifically executable.  The
length failures for papers 8 and 9 are genuine model-output pathologies, but a
shorter response would likewise not close the missing branch/domain/coefficient
facts.

Recommended treatment for this run:

- record all four as source-ineligible under the current point-valued matched
  Oracle contract;
- do not spend another generation call on the same frozen packets;
- retain papers 7 and 9 as candidates for a future, explicitly versioned
  source-packet expansion rather than weakening the present truth contract.
