# Matched Worlds: Separating Parameter Identification from Structural Discovery in Interactive Scientific Agents

> **Working ICLR draft — Sections 2 and 3.** Repository snapshot: 31 August
> 2026. This editorial note is not part of the manuscript. The current public
> development release contains 20 historically anchored matched families and 9
> paper-derived temporal task families. It does not yet contain a private
> evaluation pack. Statements below distinguish the implemented protocol from
> preregistered extensions.

## 2 Background

### 2.1 Active scientific inference under controlled information

Scientific inference is not a single task. Even in a deterministic and
low-dimensional system, an agent may need to choose an intervention, predict
what competing explanations imply, interpret the resulting evidence, and
commit to a model that generalizes beyond the observed conditions. Which of
these operations is difficult depends critically on what is known before the
first experiment.

We distinguish two settings. In **active system identification**, the response
family is supplied and the unknown object is a finite parameter vector. Given
controls \(x\in\mathcal X\), readouts \(y\in\mathcal Y\), and a public model
\(g(x;\theta)\), the task is to select experiments and estimate \(\theta\).
This usage follows system identification, where the candidate model set,
estimation procedure, experiment design, and validation distribution are
separate parts of the problem \citep{schoukens2019nonlinear}. In **structural
law discovery**, the truth-specific functional family is not supplied. The
agent must instead construct an executable predictor \(\hat g\) from a common
representation class. The latter is related to symbolic regression and sparse
dynamics discovery \citep{schmidt2009distilling,brunton2016sindy,udrescu2020aifeynman},
but differs from their usual static-data setting because the agent chooses the
measurements it receives.

The distinction matters because informative experimental design is conditional
on a hypothesis class. Classical optimal design selects observations to
discriminate among candidate models or reduce expected uncertainty
\citep{atkinson1974discriminating,mackay1992information,chaloner1995bayesian}.
When that class is correct and disclosed, the agent can concentrate on
parameter-sensitive interventions. When the class is withheld or misspecified,
the same policy may be uninformative for structural alternatives. Active
symbolic system identification has long combined model search with experiments
chosen to separate candidate dynamics \citep{bongard2007automated}; therefore,
neither active experimentation nor equation discovery alone is the novelty at
issue here.

Historical familiarity introduces a second, logically distinct information
channel. A language model may reproduce a canonical relation without using the
episode's evidence, whereas a minimally altered world may conflict with that
prior. Conversely, failure in an altered world can arise from numerical
estimation, experiment choice, protocol compliance, or model construction
rather than from resistance to counterevidence. A historical--counterfactual
comparison therefore does not by itself identify structural discovery, and an
identification--discovery comparison does not by itself identify reliance on
familiar science. Our benchmark crosses these two axes within matched
executable worlds.

The episode exposes only observable commitments. Candidate generation may be
abductive, deriving forecasts from a candidate is deductive, and revising a
general rule from evidence is inductive. We do not infer these operations from
private chain-of-thought. Instead, the Player states concrete hypotheses and
their numerical forecasts before an experiment, receives evidence, and later
reports an updated portfolio and an executable final predictor. This makes a
narrow class of evidence--belief consistency checks reproducible without
treating model-generated rationales as privileged access to reasoning.

### 2.2 Related work

#### Interactive scientific discovery and shifted worlds

Interactive environments have already established the broader scientific-agent
setting. DiscoveryWorld evaluates end-to-end hypothesis formation,
experimentation, and explanation in text-based virtual laboratories
\citep{jansen2024discoveryworld}. Auto-Discovery-Bench uses deterministic
Oracle-guided interventions for hidden causal, relational, and symbolic
structures \citep{chen2025autobench}, while FALSIFYBENCH studies explicit
Player--Oracle rule-discovery games and the use of falsifying tests
\citep{bertolazzi2026falsifybench}. These works motivate interactive evidence
collection and trajectory analysis, but their terminal objects are not paired
parameter-identification and open-form predictors of the same numerical world.

The closest physics benchmarks already cover most ingredients individually.
Gravity-Bench evaluates budgeted experimentation in simulated gravitational
systems \citep{koblischke2025gravity}. PhysGym varies the amount of prior
information provided for interactive physics tasks \citep{chen2025physgym}; it
therefore precedes us in controlled-prior evaluation. NewtonBench modifies
canonical laws inside model systems of varying complexity and scores discovered
equations numerically and symbolically \citep{zheng2026newtonbench}.
DiscoverPhysics provides 22 counterfactual \(N\)-body worlds, allows iterative
experimentation, and evaluates submitted Python laws on held-out trajectories
\citep{wiemann2026discoverphysics}. LLM-SRBench studies transformed and
synthetic equations to reduce direct recall, but supplies a fixed dataset
rather than an experimental interface \citep{shojaee2025llmsrbench}. Thus,
counterfactual laws, active querying, controlled context, executable
submissions, and held-out prediction are all established ideas.

Our narrower target is their intersection. For one hidden response function,
we pair a family-disclosed identification contract with a family-withheld
structural-discovery contract while holding the apparatus, legal interventions,
evidence budget, hidden test conditions, and numerical scoring rule fixed. We
then cross this within-world comparison with historically familiar and
minimally authored counterfactual laws. To our knowledge, the nearest
benchmarks do not jointly instantiate this paired \(2\times2\) contrast. This
is a claim about the combined measurement design, not priority for any of its
components.

#### System identification, symbolic regression, and experimental design

The terminology above prevents three tasks from being collapsed. Estimating
coefficients of a disclosed law is parameter identification. Selecting terms
from a supplied dictionary, as in SINDy \citep{brunton2016sindy}, is constrained
structure selection. Searching a more general expression language, as in
symbolic regression \citep{schmidt2009distilling,udrescu2020aifeynman}, is a
broader form of structural induction. None is unrestricted scientific
discovery: the controls, observables, representation, and allowed experiments
still define a strong inductive bias.

The active-design literature also clarifies what our process measures do not
establish. An experiment can be optimal only relative to a model class,
utility, and noise model. Our Player's forecast separation measures whether its
own current hypotheses predict different outcomes at the chosen intervention;
it does not compare that intervention against every legal alternative and is
not expected information gain. This conservative interpretation is important
when the Player's reported supports are not calibrated Bayesian posteriors.

#### Outcome and process evaluation

Scientific task completion and scientific process need not coincide. Corral
reports large gaps between successful outcomes and evidence-responsive
behavior in automated-science traces \citep{riosgarcia2026corral};
FALSIFYBENCH similarly analyzes testing strategy across turns rather than only
the final rule. Our contribution is not the general outcome--process
distinction. We operationalize two particularly local diagnostics: whether the
Player chose an intervention for which its named hypotheses made separated
forecasts, and whether its next support report moved toward the hypothesis with
the smaller observed forecast error.

LLM judges are useful for dimensions that deterministic prediction cannot
capture, but they are not a truth source. DiscoverPhysics uses a rubric-based
judge for explanations alongside held-out trajectory error, and PaperBench
constructs a separate evaluation set for its replication judge
\citep{wiemann2026discoverphysics,starace2025paperbench}. More generally, LLM
judges exhibit position, verbosity, and self-preference biases
\citep{zheng2023judging}. We therefore make executable held-out prediction the
primary scientific endpoint. A post-hoc judge may score experimental design,
evidence use, revision, stopping, claim--evidence consistency, and explanation
quality, but its scores remain separate and require human calibration.

#### Paper-derived and temporal scientific benchmarks

Recent work grounds agent tasks in scientific papers. ScienceAgentBench derives
102 executable data-science tasks from 44 peer-reviewed papers
\citep{chen2024scienceagentbench}; DiscoveryBench derives real and synthetic
discovery tasks from fixed scientific datasets \citep{majumder2024discoverybench};
EXP-Bench converts recent machine-learning papers and repositories into
experimental subtasks \citep{kon2026expbench}; and PaperBench evaluates
end-to-end replication of 20 recent machine-learning papers
\citep{starace2025paperbench}. RealMath and LiveMathematicianBench use recent
research artifacts to construct continuously refreshed mathematical
evaluations \citep{zhang2025realmath,he2026livemathematicianbench}. These works
preclude a claim that paper-to-task conversion or temporal evaluation is new.

Our temporal extension has a different target: a paper is not reproduced and
its reported answer is not posed as a question. Instead, a source-supported
quantitative relation is compiled into a hidden, queryable response function,
so that the Player can intervene on declared controls and infer the relation.
An LLM extracts a provenance-bearing science card and proposes a case scaffold,
but cannot author the executable truth after source review. This pipeline is a
case-acquisition mechanism, not an automatic certificate of scientific
correctness or contamination resistance.

Table 1 summarizes the nearest design axes. A check mark denotes a substantive
component of the cited benchmark, not identical implementation.

| Benchmark | Active evidence | Shifted or unfamiliar laws | Controlled information | Executable held-out outcome | Relation to this work |
| --- | :---: | :---: | :---: | :---: | --- |
| DiscoveryWorld | yes | partial | difficulty levels | no | Rich end-to-end laboratory; no paired ID/Discovery predictor contract |
| PhysGym | yes | partial | yes | partial | Strong prior-control precedent; uses graded context rather than a matched structural/parametric split |
| NewtonBench | yes | yes | system complexity | yes | Counterfactual law discovery; no same-world identification method |
| DiscoverPhysics | yes | yes | fixed blind setting | yes | Closest blind executable discovery setting; no historical/identification pairing |
| FALSIFYBENCH | yes | semantic rules | fixed | no | Player--Oracle falsification and trajectory analysis, not numerical extrapolation |
| ScienceAgentBench / EXP-Bench | tool use | no | knowledge/task conditions | executable task artifacts | Paper-derived analysis or reproduction, not an intervenable hidden law |
| **Ours** | yes | matched historical/counterfactual | paired ID/Discovery contracts | yes | Targets the factorial interaction while keeping the evidence environment fixed |

## 3 Methodology

### 3.1 Problem formulation: active predictive law inference

A case family \(f\) defines

\[
\mathcal C_f =
(\mathcal X_f,\mathcal Y_f,\mathcal A_f,B_f,
 g_{f,H},g_{f,C},\mathcal Q_f^{\mathrm{diag}},
 \mathcal Q_f^{\mathrm{test}}).
\]

Here \(\mathcal X_f\) is the legal control domain, \(\mathcal Y_f\) is the set
of typed readouts, \(\mathcal A_f\) is the apparatus and resource contract,
\(B_f\) is an experiment budget, and
\(g_{f,w}:\mathcal X_f\rightarrow\mathcal Y_f\) is the private response
function for world \(w\in\{H,C\}\). The diagnostic conditions
\(\mathcal Q_f^{\mathrm{diag}}\) certify during case construction that the two
worlds can be distinguished with legal experiments; they are not supplied as
a solution. The disjoint set \(\mathcal Q_f^{\mathrm{test}}\) is reserved for
terminal evaluation.

An episode contains a tested **Player** and an evidence-providing **Oracle**.
Evaluation occurs after termination and is not a third interactive role. At
turn \(t\), the Player reports a hypothesis portfolio \(\Pi_t\), proposes an
experiment \(x_t\), and gives a forecast
\(\widehat y_{t,h,r}\) for every current hypothesis \(h\) and requested readout
\(r\). The Oracle returns \(y_t=g_{f,w}(x_t)\), subject to the public
measurement contract. The observable trajectory is

\[
\tau = \left\{(\Pi_t,x_t,\widehat y_t,y_t)\right\}_{t=1}^{T},
       \Pi_{T+1},s,
\]

where \(s\) is the final structured submission and \(T\le B_f\) counts
budget-consuming interactions. The measured capability is deliberately
narrow: can the Player choose interventions, revise explicit hypotheses from
returned evidence, and submit an executable predictor that generalizes to
held-out interventions? Exact recovery of an author's algebraic spelling and
unrestricted real-world discovery are outside the construct.

### 3.2 Matched \(2\times2\) design

Each historically anchored family yields four cells by crossing world
\(w\in\{H,C\}\) with track \(d\in\{I,D\}\). \(H\) follows a canonical
scientific relation under a declared modern idealization; it is not a literal
reconstruction of the original experiment. \(C\) changes one private mechanism
coordinate while preserving the apparatus and reference scale. The Player sees
only an opaque instance identifier, not the labels “historical” or
“counterfactual.” \(I\) denotes family-disclosed identification and \(D\)
denotes family-withheld predictive law induction.

The family constructor enforces five matching conditions.

1. The two worlds have the same public background, initial qualitative
   observations, controls, readouts, units, ranges, measurement semantics, and
   experiment budget, apart from an opaque instance ID.
2. Within a world, the two tracks share the same response function, Oracle,
   interventions, evidence, and hidden evaluation conditions.
3. If \(\theta_{f,H}\) and \(\theta_{f,C}\) are the private mechanism
   coordinates, then \(\lVert\theta_{f,H}-\theta_{f,C}\rVert_0=1\).
4. At least one allowed set of interventions within budget separates the worlds
   beyond the declared scoring tolerance.
5. The executable truth from either world fails the other world's hidden test
   in at least one condition. Thus, a predictor from one condition cannot pass both.

For Player model \(m\), let \(Y_{f,w,d,m,k}\) be unconditional held-out prediction success on
repeat \(k\), including protocol-invalid terminations as failures. Repeats are
first averaged within a cell. The prespecified family-level interaction is

\[
\Delta_m = \mathbb E_f\!\left[
 (\bar Y_{f,H,D,m}-\bar Y_{f,C,D,m})
 -(\bar Y_{f,H,I,m}-\bar Y_{f,C,I,m})
\right].
\]

A positive value means that agreement with familiar science helps more when
the functional family must be induced than when it is supplied. This is a
paired factorial interaction, not an observational difference-in-differences
claim. Families—not episodes or within-trajectory forecast pairs—are the units
of generalization and resampling. A prior-only manipulation check is required
before interpreting \(H-C\) as a familiarity effect for a particular model.

### 3.3 Two information contracts

The tracks differ in the object left unknown before interaction.

| Component | Identification \(I\) | Discovery \(D\) |
| --- | --- | --- |
| Public model information | Formula specification; parameter names, meanings, units, and finite domains | An executable expression grammar shared across task families; no target model or parameter slots |
| Unknown object | \(\theta\) in \(g_f(x;\theta)\) | Functional structure and constants of \(\hat g(x)\) |
| Experimental interface | Controls, readouts, resolution, and budget | Identical within the same world |
| Final structured object | Family-specific named parameters | One expression program for each readout |
| Primary criterion | Hidden predictive behavior | The same hidden predictive behavior |

Identification submissions must name exactly the public parameter slots and
place finite values within their declared domains. Discovery submissions use a
shared abstract-syntax-tree language over public controls. Its implemented
operators are numeric constants, variables, addition, subtraction,
multiplication, division, power, negation, exponential, logarithm, sine,
maximum, and step; programs are limited to depth 24 and 256 nodes. Both tracks
are evaluated behaviorally, so an algebraically different predictor may pass
if it is accurate on every prespecified held-out intervention.

The current development release contains an important representation confound:
Identification returns family-specific named parameters, whereas Discovery
returns a general expression tree. The observed track contrast therefore
measures an end-to-end **information-and-representation contract**, not a pure
causal effect of disclosing the family. A confirmatory claim about family
disclosure requires a common final predictor representation in both tracks,
with only the instantiable scaffold hidden in \(D\). We retain the present
encoding in the development release because it is strictly executable, but do
not hide this limitation in an appendix.

### 3.4 Player--Oracle episode protocol

The public case view contains minimal scientific background, qualitative
initial observations, the apparatus, legal controls and readouts, units and
ranges, measurement resolution or reporting increment, budget, stopping
threshold, and the track-specific submission contract. It contains no active
world label, private parameters, diagnostic conditions, or terminal test
conditions.

Every experiment action must provide

\[
a_t = \left(\Pi_t,x_t,
\{\widehat y_{t,h,r}:h\in\Pi_t,r\in R_t\}\right)
\]

before the Oracle computes evidence. During experimentation, \(\Pi_t\) must
contain between two and the public maximum (six in the current suite) concrete
hypotheses with unique identifiers; a residual `OTHER` entry is rejected
because it has no testable forecast. Reported support
weights must be finite, lie in \([0,1]\), and sum to one. Forecast keys must
match exactly the current hypotheses and requested readouts. The Player may add,
remove, or rewrite hypotheses after seeing evidence, but a reused identifier
with a changed statement is treated as a rewrite rather than as a posterior
update to the same hypothesis.

A final portfolio may converge to one hypothesis. There is no duplicate
confidence field in the final submission: stopping confidence is read only
from the selected portfolio entry. A protocol-valid final either reaches the
public confidence threshold or exhausts the experiment budget. Crucially, if a
final scientific model is strictly decodable but its portfolio or stopping
metadata is inconsistent, the model still enters scientific evaluation; the
protocol violation is reported separately. This prevents a potentially valid
scientific prediction from disappearing into a format score.

Player actions form a strict JSON union between `experiment` and `final`.
Unknown or missing fields, duplicate keys, non-finite numbers, inconsistent
forecast maps, and invalid expression programs are rejected rather than
silently repaired. Provider-native JSON schemas may constrain generation, but
the provider-neutral decoder is the normative boundary. An evaluation profile
must freeze whether zero or one schema-directed regeneration is allowed,
because a second generation can change scientific content as well as format.
The ordered event log stores the public view, raw completion, decoded action,
Oracle response, state transition, termination, and usage needed for parser and
runtime replay; logging is a reproducibility property, not a scientific
contribution.

### 3.5 Evidence authority and Oracle realizations

The scientific truth is a property of the case, not of the language model
presenting it. In the implemented deterministic path, a `CaseOracle` first
validates the apparatus, controls, ranges, requested readouts, and replicate
count. A private `WorldModel` then computes the selected-world response,
applies any declared reporting resolution, and returns measurements with exact
units and uncertainty semantics. The Oracle verifies that the returned fields
match the public measurement contract. Its possible statuses are valid,
needs-clarification, unavailable-instrument, out-of-range, and invalid-setup.
Only a clarification request is free; other failed experimental attempts
consume budget so that invalid probing is not an unlimited side channel.

We separate two conceptually different Oracle realizations behind the same
proposal/response interface:

- **Deterministic Oracle:** resource validation followed by the executable
  `WorldModel`. This is the current scientific evidence path.
- **Truth-conditioned generative Oracle:** a language model receives the
  complete selected-world private specification and freely renders an answer
  to a legal experiment. This is a planned ablation for studying evidence
  fidelity and downstream Player sensitivity, not an implemented result in the
  present snapshot.

The existing LLM Oracle wrapper is deliberately not the second condition. It
must copy the authoritative deterministic response exactly and cannot create or
alter measurements, units, uncertainty, or status. It tests presentation/API
behavior only. A future deterministic-versus-generative ablation must use two
independent runtime paths, hold the Player, case truth, proposals, and evaluator
fixed, and score the generative Oracle's evidence fidelity before attributing
any Player difference to Oracle style.

### 3.6 Terminal scientific evaluation

Let \(s\) decode to a predictor \(\hat g_s\). For readout \(r\) and hidden
condition \(x\in\mathcal Q_f^{\mathrm{test}}\), the evaluator computes

\[
z_{f,w,r}(x;s)=
\frac{|\hat g_s^r(x)-g_{f,w}^r(x)|}
{a_{f,r}+\lambda_f|g_{f,w}^r(x)|},
\]

where \(a_{f,r}\) is a case-specific absolute allowance (defaulting to the
declared readout resolution, or \(10^{-9}\) when neither is supplied) and
\(\lambda_f\) is the prespecified relative tolerance. The primary deterministic
criterion is

\[
\operatorname{PredictivePass}(s)=
\mathbb 1\!\left[
\max_{x\in\mathcal Q_f^{\mathrm{test}},r}z_{f,w,r}(x;s)\le 1
\right].
\]

Identification parameter errors are reported diagnostically, but parameter
equality is not the headline criterion. Natural-language explanations and scope
statements are recorded but do not determine scientific correctness.

We keep scientific evaluation and protocol completion distinct:

\[
\operatorname{ActivePass}
=\operatorname{PredictivePass}\land\operatorname{ProtocolComplete}.
\]

Every scheduled Player episode remains in the denominator. Terminal outcomes
are: a submitted model, invalid Player output after the allowed generations, a
decoded action rejected by the episode protocol, or reaching the action horizon
without submission. We report submission availability, protocol completion,
unconditional held-out prediction success, and—only as a diagnostic—held-out prediction success conditional
on submission. Provider transport or storage failures are infrastructure
events; they do not become Player failures and must rerun the same prespecified
schedule position.

### 3.7 Process measures based on pre-experiment predictions and failure modes

For each valid turn, the experiment-discriminativeness diagnostic averages the
pairwise normalized separation of the Player's ex-ante forecasts:

\[
D(\tau)=\operatorname{mean}_{t,r,h<h'}
\frac{|\widehat y_{t,h,r}-\widehat y_{t,h',r}|}
{\max(|\widehat y_{t,h,r}|,|\widehat y_{t,h',r}|,\rho_r,\epsilon)},
\]

where \(\rho_r\) is the declared readout resolution and \(\epsilon=10^{-12}\).
This measures separation among the forecasts the Player actually reported. It
does not establish that the chosen experiment was optimal.

For a hypothesis \(h\) that persists with an unchanged statement, its observed
forecast error at turn \(t\) is

\[
e_{t,h}=\operatorname{mean}_{r}
\frac{|\widehat y_{t,h,r}-y_{t,r}|}
{\max(|\widehat y_{t,h,r}|,|y_{t,r}|,\rho_r,\epsilon)}.
\]

For every non-tied pair, the next reported support gap receives 1 if it moves
toward the lower-error hypothesis, 0 if it moves in the opposite direction,
and 0.5 if it is unchanged. Their mean is the evidence-aligned belief-update
rate. Tied forecasts with unsupported support shifts, rewritten hypotheses,
duplicate setups, and unscorable pairs are counted separately. These values are
observable transcript diagnostics—not Bayesian posteriors, calibrated beliefs,
or a general score of scientific reasoning—and never alter PredictivePass.

The deterministic failure analyzer localizes the first observed failure stage
among action generation, protocol, evidence--belief update, stopping,
final-model specification, and held-out generalization. It also analyzes
evidence--belief behavior in episodes that never submit, using only experiments
that actually occurred. For submitted Discovery expressions, the final
predictor can be replayed on observed controls to detect whether it ignores,
reverses, or invents an observed effect. This replay currently has incomplete
coverage for Identification because case-specific final decoders exist for only
a subset of families; uncovered cases are reported as missing coverage rather
than assigned a semantic diagnosis.

An optional post-hoc LLM evaluator reads a sealed, observable transcript and
scores six axes: experimental design, evidence use, hypothesis revision,
stopping decision, claim--evidence consistency, and explanation quality. It
cannot overwrite or be averaged into deterministic predictive or protocol
outcomes. Until its rubric is calibrated against blinded domain-expert labels
and judge sensitivity is reported, these scores are exploratory.

### 3.8 Family construction and executable quality gates

A hand-authored task family starts from a scientific relation supported by a cited source and an explicit
modern idealization. Authors specify the public apparatus, controls, readouts,
fixed conditions, diagnostic interventions, hidden interventions, a
family-specific identification scaffold, and two private executable truths.
The counterfactual changes one declared mechanism coordinate—for example an
exponent, a mode weight, or the activation of one nonlinear term—rather than
adding unrelated complexity. Plausibility is useful for interpretation but is
not sufficient for admission; the executable contract must close.

Admission applies the following deterministic gates:

1. controls and readouts are typed, finite on their declared domains, and
   consistent across the four cells;
2. the Identification scaffold and Discovery expression for each world agree
   numerically with its private `WorldModel` on diagnostic and hidden
   conditions;
3. diagnostic conditions fit inside the public budget and vary every
   non-constant numerical control needed by the relation;
4. diagnostic and hidden conditions are disjoint, with hidden continuous
   conditions placed in the domain interior;
5. the two worlds differ in exactly one private mechanism coordinate, are
   distinguishable at the declared resolution, and reject each other's false
   twin on hidden tests; and
6. the number and diversity of available observations meet a necessary
   capacity check. This is not presented as a proof of global identifiability.

The current public development suite contains 20 historically anchored
families (80 cells) across mechanics, waves, gases, electromagnetism,
radiation, circuits, heat transfer, optics, kinetics, diffusion, and fluid
transport. A separate registry contains 9 temporal task families derived from recent papers
(36 cells), for 29 admitted families and 116 cells in total. Contract canaries
accept the known truth and reject the predictor from the paired condition in all 116
cells; 1,242 sampled legal deterministic queries return finite, unit-consistent,
repeat-identical evidence, and the current repository test suite passes 410
tests. These checks establish executable consistency. They do not substitute
for source review, experimental replication, or a model evaluation.

### 3.9 Construction of temporal evaluation instances from recent papers

The temporal path is designed to enlarge scientific provenance without letting
an LLM invent the case truth. A release begins with a fixed date interval and a
journal-first census. Publisher records are reconciled by DOI and publication
status, then matched conservatively to a versioned arXiv record. A TeX-bearing
source archive is required for the automated path; missing TeX, ambiguous
identity, or missing publisher reconciliation are explicit exclusion outcomes
rather than invitations to infer content from memory.

The authoring pipeline is

\[
\begin{aligned}
&\text{journal census}\rightarrow\text{versioned source packet}
\rightarrow\text{ScienceCard extraction}\\
&\rightarrow\text{independent source review}
\rightarrow\text{matched scaffold proposal}
\rightarrow\text{deterministic truth binding}\\
&\rightarrow\text{hard eligibility gates}
\rightarrow\text{family source-closure review}
\rightarrow\text{four-cell canary}.
\end{aligned}
\]

In stage one, an LLM reads only a line-numbered textual source packet and
extracts mechanisms, quantitative claims, variables and parameters, controls,
readouts, fixed conditions, statistics, uncertainty, applicability ranges,
claim dependencies, and source locators. Each usable quantitative claim stores
its Oracle outputs in the same validated expression grammar used by the
benchmark. A scientific reviewer checks the expression against its quoted
quantitative form and locator. The reviewer may return
`eligible_for_drafting`, `card_revision_required`, or `ineligible_for_bench`;
the middle state repairs an incomplete card without misclassifying the paper as
scientifically unsuitable.

In stage two, a separate LLM sees only the reviewed ScienceCard, not the paper,
and either proposes a matched public scaffold or returns `not_authorable`. It
cannot transcribe or rewrite the executable formulas. A deterministic binder
compiles the selected reviewed claims into both private response functions and
inserts source-supported parameter values. Subsequent filters check source
lineage, public/private information boundaries, expression totality,
observation capacity, diagnostic separability, predictors drawn from paired conditions, and
matched controls, readouts, and evidence modality. A final reviewer verifies
that the family closes against the original source.

The 9 admitted temporal families mostly compare two source-reported regimes in
the same paper. We denote these regimes \(A/B\) in the scientific analysis,
even though the current storage interface reuses the two-world field. They do
not automatically manipulate historical familiarity and therefore must not be
pooled into the primary \(H/C\) interaction defined in Section 3.2. They
support a separate
separate analysis of the Identification--Discovery contrast on paper-derived temporal tasks.
Two additional candidates are retained as rejected provenance because their
proposed branches did not define mutually exclusive worlds under a shared
observable. Source-reported uncertainty is preserved as provenance, while the
current deterministic Oracle returns the central relation rather than sampling
experimental noise.

### 3.10 Evaluation boundary and confirmatory analysis

The public suite is a development instrument: its truths and held-out
conditions ship with the repository. It can test protocol behavior and support
reproducible exploratory runs, but it is not contamination-resistant and does
not currently constitute a formal private benchmark. A formal evaluation must
serve the active world, evaluator, assignments, private variants, and hidden
conditions outside the Player process; the Player communicates only through
the serialized episode interface. Ordinary transcript replay supports
reproducibility, whereas process separation supplies the relevant information
boundary.

For a confirmatory study, the case release, common submission representation,
model prompts and tools, budgets, generation-repair policy, retry policy,
Oracle realization, schedules, and analysis must be frozen before running
models. When a component is model-backed, the Player, Oracle presentation or
truth-conditioned Oracle, and post-hoc judge use independent provider and model
configurations; assigning the same model ID does not share prompts, context, or
credentials across roles. Cells should be randomly interleaved, with repeated
samples averaged within each family--world--track cell. Uncertainty for the
Section 3.2 interaction should resample or
model families as the independent units; temporal siblings from the same paper
should additionally be clustered by source. Random-query, prior-only,
experiment-using system-identification, symbolic-regression, and reference
solver policies provide manipulation and solvability checks. The deterministic
versus truth-conditioned generative Oracle comparison is a separate ablation,
not a change to the benchmark truth.

The present draft therefore supports a precise methodological claim: the
repository implements a matched evaluation surface for active identification
and predictive law induction, plus a documented procedure for constructing tasks from recent
relations. Claims about model rankings, the magnitude of the factorial
interaction, calibrated scientific process, or formal private performance
require the preregistered multi-model study rather than the public development
artifacts alone.
