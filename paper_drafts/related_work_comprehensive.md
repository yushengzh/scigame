---
title: "Related Work: Diagnosing Scientific Law Induction in Interactive Language-Model Agents"
date: 2026-09-01
bibliography: references.bib
link-citations: true
---

> **Purpose and status.** This document is a submission-ready related-work foundation for Role Benchmark. It asks whether the project is necessary, why the measurement problem matters, and what the project adds beyond the closest prior work. The review covers work available through 1 September 2026. It treats the repository's 29 task families and 116 benchmark instances as a public development set, not as a contamination-resistant formal benchmark.

## Review scope and organizing question

The relevant literature is distributed across communities that often use the word *discovery* for different objects. We therefore organized the review around the evaluated object rather than the system's marketing label. The five main strata are: static scientific question answering; interactive scientific environments; system identification and symbolic law recovery; active experimental design; and end-to-end research agents. We separately reviewed work on counterfactual or temporally refreshed evaluation, process-level scientific reasoning, and paper-to-task compilation because these dimensions bear directly on Role Benchmark's validity.

The review is guided by one measurement question:

> Can an evaluation distinguish retrieval of familiar science, parameter estimation inside a disclosed family, and family-withheld predictive law induction from actively acquired evidence?

This question is narrower than whether an agent can “do science.” It is also not answered by showing that a model solves hard science questions, completes laboratory tasks, fits equations, or generates a plausible paper. Each of those outcomes may be valuable, but each leaves different alternative explanations open.

## Scientific knowledge and problem-solving benchmarks

Scientific evaluation first became prominent through static problems with fixed inputs and objectively checkable answers. SciBench collects college-level mathematics, chemistry and physics problems, while GPQA contains expert-written graduate-level multiple-choice questions in biology, physics and chemistry [@rein2023gpqa]. LAB-Bench shifts toward practical biology research skills, including literature reasoning, database use, figure interpretation and sequence manipulation [@laurent2024labbench]. These benchmarks are important measures of knowledge and single-shot reasoning. Their fixed-question format, however, does not require an agent to choose an intervention, state what competing hypotheses predict before seeing an outcome, or revise a model over an evidence trajectory.

This boundary is substantive. A model can answer a difficult physics question by retrieving a learned relation or applying a familiar solution pattern. Conversely, a model can fail an interactive task because of action formatting, state tracking or a poor experiment even when it knows the canonical law. Static accuracy and active inference are therefore complementary measurements rather than interchangeable proxies.

General agent benchmarks make the complementary limitation visible. AgentBench evaluates multi-turn decision-making across eight environments [@liu2023agentbench], but its breadth does not isolate scientific inference. ScienceWorld is more directly scientific: agents manipulate a text-based world to complete elementary-science tasks, and its original results show that interactive grounding reveals weaknesses hidden by static question answering [@wang2022scienceworld]. Yet task completion in ScienceWorld usually asks the agent to enact or demonstrate a known concept. It does not systematically cross whether a law is familiar with whether its functional family is disclosed.

## Interactive scientific environments

DiscoveryWorld is a major step toward evaluating full cycles of automated discovery. Its 120 text-based challenges span eight topics and require hypothesis formation, experiment design, observation and action [@jansen2024discoveryworld]. The environment prioritizes ecological richness and end-to-end competence, scoring task completion, relevant actions and explanatory knowledge. This realism is valuable, but it makes failures multiply determined: a low score may reflect navigation, planning, tool use, observation integration or scientific inference. Role Benchmark occupies the diagnostic end of this realism–control spectrum. Its environments are intentionally low-dimensional so that family disclosure and prior alignment can be manipulated without changing the apparatus or scoring conditions.

Auto-Discovery-Bench takes a more controlled approach. It uses deterministic Oracle-guided cycles to test recovery of directed graphs, undirected relations and symbolic equations, and its trajectory-tracking diagnostic isolates long-range structured state maintenance as a prerequisite for discovery [@chen2025autobench]. FALSIFYBENCH similarly studies Player–Oracle hidden-rule games inspired by Wason's 2–4–6 task [@wason1960failure; @bertolazzi2026falsifybench]. It shows that negative testing is strongly associated with success and analyzes behavior turn by turn. These benchmarks are close in interaction protocol and diagnostic intent. Their terminal objects, however, are hidden structures or semantic rules rather than paired parameter-identification and family-withheld numerical predictors evaluated on the same world.

The distinction matters because evidence collection is only one component of scientific modelling. A benchmark may reveal whether an agent asks falsifying questions without testing whether its final mathematical model extrapolates. Conversely, an equation-recovery benchmark may test the final model without exposing whether the agent selected informative measurements. Role Benchmark requires both an observable experimental trajectory and an executable final predictor, while keeping the two score families separate.

## Interactive physics and scientific-law discovery

The closest prior work lies in interactive physics. Gravity-Bench-v1 requires agents to collect data under a budget in gravitational simulations and includes out-of-distribution physical regimes [@koblischke2025gravity]. PhysGym provides interactive simulations and explicitly varies the amount of prior knowledge supplied to the agent [@chen2025physgym]. Its controlled-prior design is an important precedent: Role Benchmark cannot claim priority for varying prior information. The distinction is that PhysGym grades levels of contextual support, whereas Role Benchmark pairs a family-disclosed parameter contract and a family-withheld expression contract for the same hidden response function.

NewtonBench is still closer. It contains 324 interactive law-discovery tasks across 12 physics domains and uses systematic counterfactual shifts of canonical laws to reduce direct memorization [@zheng2026newtonbench]. It combines scientific relevance, scale and executable evaluation, and therefore rules out broad novelty claims based on counterfactual physics, interactive probing or symbolic law scoring alone. DiscoverPhysics constructs 22 counterfactual N-body worlds, allows several rounds of experiments, and evaluates submitted Python laws on held-out trajectories as well as explanations through a rubric-based judge [@wiemann2026discoverphysics]. It is the nearest precedent for blind executable discovery in an unfamiliar physical world.

LLM-AutoSciLab adds explicit hypothesis-conditioned experimentation. Its ActiveSciBench suite includes enzyme-kinetics and gene-regulatory-network tasks and evaluates closed-loop mechanism refinement under a measurement budget [@kabra2026autoscience]. This work establishes that coupling hypotheses to adaptive experiment selection and comparing sample efficiency are already active research directions. Role Benchmark's contribution is therefore not “closed-loop discovery” or “hypothesis-guided experimentation.” Its narrower goal is a controlled contrast: if an agent performs worse in a counterfactual world, does the gap arise mainly when it must infer structure, or does it remain even when the correct family is disclosed?

These nearest benchmarks jointly cover nearly every ingredient used by Role Benchmark: active querying, budgeted experiments, altered laws, controlled context, executable submissions and held-out prediction. The remaining gap is experimental-design rather than feature novelty. None of the reviewed systems jointly implements a within-family (2\times2) comparison that crosses historical versus minimally changed counterfactual worlds with family-disclosed identification versus family-withheld law induction while holding the apparatus, budget, evidence generator and test interventions fixed.

## System identification and symbolic regression

Role Benchmark's track distinction inherits a long-standing separation between estimating parameters and searching model structure. In system identification, the model set, experiment design, parameter estimator and validation distribution are conceptually distinct [@schoukens2019nonlinear]. If the functional family is supplied, selecting inputs and estimating a finite parameter vector is an identification problem even when the experiments are active.

Symbolic regression expands the target from coefficients to functional form. Early work combined active experiments with automated reverse engineering of nonlinear dynamical systems [@bongard2007automated]. Genetic-programming approaches recovered compact natural laws from experimental data [@schmidt2009distilling]; SINDy selects sparse governing terms from a supplied library [@brunton2016sindy]; and AI Feynman exploits physical regularities to decompose symbolic-regression problems [@udrescu2020aifeynman]. LLM-SRBench directly evaluates language-model equation discovery using 239 transformed or synthetic problems designed to reduce trivial recall [@shojaee2025llmsrbench].

This literature prevents two overclaims. First, an expression abstract syntax tree is a submission language, not a new law-discovery algorithm. Second, “family withheld” never means assumption-free discovery. The public controls, readouts, legal operators, dimensional conventions, budget and test domain all constrain the hypothesis space. Role Benchmark should therefore use *predictive law induction with the truth-specific family withheld*, not unrestricted discovery.

The literature also exposes a present confound in the repository. Identification ends in named, case-specific parameters, whereas discovery ends in a common expression representation. An end-to-end track difference can consequently reflect model-family information, representation construction or parser compliance. The current design still diagnoses practical performance under two information contracts, but it does not yet identify family disclosure as the sole causal factor. A decisive ablation would place both tracks in a common final representation and vary only the information supplied before interaction.

## Active experiment design and falsification

Classical experimental design formalizes why a scientific agent should choose some measurements rather than others. Model-discrimination design selects experiments that separate candidate explanations [@atkinson1974discriminating]. Bayesian design treats an experiment as a decision under uncertainty and optimizes expected utility [@chaloner1995bayesian]. Information-based active selection chooses measurements expected to reduce uncertainty, while also making clear that informativeness depends on the assumed hypothesis space [@mackay1992information].

Role Benchmark records a much weaker quantity. `experiment_discriminativeness_mean` measures the pairwise separation of the Player's own ex-ante numerical forecasts at experiments it actually chose. It does not enumerate alternative legal experiments, integrate over outcomes, or compute expected information gain. Likewise, `evidence_aligned_belief_update_rate` measures whether reported support moves toward a persistent hypothesis with lower normalized forecast error. Because the hypotheses need not be mutually exclusive or exhaustive, reported confidences are support weights rather than validated Bayesian posteriors.

This limited operationalization is still useful. Wason's classic work showed systematic difficulty in seeking disconfirming evidence [@wason1960failure], and FALSIFYBENCH finds negative testing to be a major correlate of successful rule discovery [@bertolazzi2026falsifybench]. Requiring numerical forecasts before evidence arrives makes at least one element of test informativeness auditable without asking for private chain-of-thought. It cannot establish optimal experimental design, calibrated belief revision or scientific rationality in general.

## Outcome versus scientific process

Outcome-only evaluation can hide epistemically weak behavior. FALSIFYBENCH demonstrates that turn-level testing strategy predicts hidden-rule success [@bertolazzi2026falsifybench]. Corral broadens this concern across more than 25,000 scientific-agent runs: the study reports frequent evidence neglect and a substantial separation between task performance and refutation-driven revision [@riosgarcia2026corral]. FIRE-Bench similarly evaluates full-cycle rediscovery of findings from recent machine-learning papers and finds recurring failures in planning and evidence-based analysis even when execution artifacts can be produced [@wang2026firebench].

Role Benchmark responds with observable commitments rather than inferred cognition. Before each valid experiment, the Player must maintain multiple concrete hypotheses and provide a numerical forecast for every requested readout under each one. After evidence is returned, the transcript records which hypotheses persisted, changed or disappeared and how support weights moved. These records allow local tests of forecast separation and evidence-aligned movement. They do not reveal the model's private reasoning, and the report should avoid language such as “the model believed” unless it explicitly means “the model reported support.”

Final scientific correctness remains deterministic and separate. A submitted predictor is executed on hidden interventions and receives `predictive_model_pass` only if it satisfies the case-specific numerical criterion. An optional post-hoc LLM evaluator may score design quality, evidence use, revision, stopping and explanation, but those exploratory axes cannot override the executable outcome. This separation is important because LLM judges exhibit order, verbosity and self-preference biases [@zheng2023judging], and PaperBench found it necessary to construct a separate validation benchmark for its replication judge [@starace2025paperbench].

## Paper-derived and temporally refreshed scientific evaluation

Several benchmarks derive realistic tasks from scientific papers. DiscoveryBench contains 264 real-data tasks across six domains plus 903 synthetic tasks, formalizing multi-step data-driven discovery from a supplied dataset [@majumder2024discoverybench]. ScienceAgentBench extracts 102 executable tasks from 44 peer-reviewed papers across four disciplines, uses expert validation and scores self-contained Python programs [@chen2024scienceagentbench]. EXP-Bench derives 461 experimental tasks from 51 AI papers and tests design, implementation, execution and analysis [@kon2026expbench]. PaperBench asks agents to replicate 20 ICML papers and evaluates thousands of author-informed rubric items [@starace2025paperbench]. FIRE-Bench withholds the original method and asks agents to rediscover verified paper findings from a high-level research question [@wang2026firebench].

These projects preclude a novelty claim for paper-to-task conversion, recent-source evaluation or executable research artifacts. Role Benchmark's temporal pipeline has a different terminal object. It seeks a source-supported quantitative relation that can be compiled into a small queryable world. A first LLM extracts a provenance-bearing ScienceCard from a fixed TeX packet; an independent source review checks every locator; a second LLM proposes at most one matched scaffold using only the reviewed card; deterministic binding, filtering, rendering and canary evaluation then produce the four cells. The LLMs propose structured artifacts but do not certify their own source fidelity or write unconstrained executable truth after review.

Temporally refreshed material helps address, but cannot eliminate, contamination. LiveBench combines recently released sources, periodic refresh and objective scoring [@white2025livebench]. Recent-source tasks can still be exposed through preprints, retrieval tools, benchmark development or later training. Role Benchmark treats all benchmark instances whose data-generating processes and evaluation procedures are public as a development set. A formal claim requires a private test set, trusted execution boundary, fixed release protocol and disclosure of each model's tool and retrieval access.

## Autonomous scientific agents and real laboratories

Systems such as ChemCrow and Coscientist show why rigorous evaluation matters. ChemCrow integrates a language model with 18 chemistry tools and demonstrates planning and execution across synthesis, drug and materials tasks [@bran2024chemcrow]. Coscientist combines language models with search, code execution and laboratory automation and performs multi-stage chemical experiments [@boiko2023coscientist]. The AI Scientist automates idea generation, coding, experimentation, visualization, manuscript writing and simulated review in machine learning [@lu2024aiscientist]. These systems target useful scientific work rather than controlled measurement of one inferential distinction.

Role Benchmark is not a competitor on real-world autonomy. Its importance is upstream: if an agent's success can arise from recalled laws or a supplied family, an end-to-end demonstration alone does not locate its scientific-inference capability. A small, replayable diagnostic can identify failure modes before they are embedded in expensive or safety-relevant laboratory systems. Conversely, success on Role Benchmark cannot establish competence in laboratory safety, literature synthesis, apparatus control, noisy real-world measurement or novel discovery.

## Comparative synthesis

The table summarizes the closest design dimensions. “Partial” means the work contains a related component, not an implementation equivalent to Role Benchmark.

| Benchmark | Active evidence | Unfamiliar or shifted truth | Information control | Executable held-out outcome | Observable process analysis | Paper-derived | Main distinction from Role Benchmark |
| --- | :---: | :---: | :---: | :---: | :---: | :---: | --- |
| ScienceWorld | yes | no | task variants | task state | action traces | no | Grounded task completion, not paired law induction |
| DiscoveryWorld | yes | partial | difficulty/variants | task metrics | relevant-action metrics | no | Rich end-to-end environment with more confounds |
| Auto-Discovery-Bench | yes | synthetic structures | controlled diagnostics | structured recovery | state tracking | no | Graph/relation/equation state tracking, no historical × track pairing |
| FALSIFYBENCH | yes | semantic hidden rules | fixed | rule classification | strong | no | Falsification behavior, not numerical held-out extrapolation |
| Gravity-Bench | yes | yes | task conditions | open-ended reference scoring | partial | no | Gravitational discovery only; no same-world identification method |
| PhysGym | yes | partial | graded priors | model fidelity | partial | no | Controls prior amount, not matched family disclosure |
| NewtonBench | yes | yes | complexity conditions | symbolic/numerical | partial | no | Large counterfactual law suite; no family-disclosed matched method |
| DiscoverPhysics | yes | yes | blind fixed setting | Python law on trajectories | experiment/refinement analysis | no | Closest blind executable physics discovery; no historical/identification pairing |
| ActiveSciBench | yes | mechanism tasks | hypothesis-conditioned | symbolic/graph recovery | active selection | no | Closed-loop method benchmark, not a factorial measurement design |
| DiscoveryBench | fixed datasets | synthetic and real | metadata/goals | facet scoring | workflow facets | yes | Data analysis rather than interventions on a hidden world |
| ScienceAgentBench | tool/code execution | no | expert knowledge conditions | executable program | cost/error facets | yes | Scientific coding tasks, not active law inference |
| EXP-Bench / PaperBench / FIRE-Bench | research execution | recent findings | varied | code/rubric/claim scoring | stage failures | yes | Full-cycle research or replication at much larger scope |
| **Role Benchmark** | **yes** | **historical/counterfactual pairs** | **ID/discovery pairs** | **deterministic predictor tests** | **forecast/update diagnostics** | **9 temporal families** | **Targets the interaction between prior alignment and family disclosure** |

## Is this work necessary?

The literature supports a qualified **yes**. The project is necessary as a diagnostic measurement study, not because interactive scientific discovery is unevaluated. Existing work already measures rich laboratory behavior, altered physical laws, controlled priors, symbolic recovery, falsification, paper-derived research and executable outputs. What remains difficult is causal attribution: a single success rate usually cannot tell whether a familiar law was recalled, whether the functional family made the problem easy, whether an experiment was informative, or whether the agent used the returned evidence.

The matched (2\times2) design directly targets that ambiguity. Within a family, historical and counterfactual worlds differ in one declared mechanism coordinate; within a world, identification and discovery share the apparatus, interventions, budget, WorldModel and hidden prediction tests. The scientifically interesting statistic is not a raw leaderboard position but the interaction

\[
\Delta_m = \mathbb{E}_f\left[
(Y_{H,D,m}-Y_{C,D,m})-(Y_{H,I,m}-Y_{C,I,m})
\right],
\]

where (Y) is unconditional predictive success after averaging repeats within a cell. A positive interaction would be consistent with familiar scientific priors helping specifically when the family must be inferred. It would not, by itself, prove that the model recalled a formula or reasoned scientifically; trajectory and ablation evidence would still be required.

## Why is the question important?

First, it improves construct validity. “Scientific discovery” is too broad to diagnose from one aggregate score. Separating prior alignment from family disclosure produces a result that can guide model and agent design: parameter-estimation failure, structural-induction failure, confirmation bias and protocol failure call for different remedies.

Second, it makes evidence use auditable. Ex-ante forecasts turn a vague rationale into a falsifiable public commitment. A benchmark can then distinguish a lucky final fit from a trajectory that selected separating experiments and moved reported support toward better predictions.

Third, the design is compatible with objective replay. Deterministic worlds, strict actions, canonical JSONL logs and executable held-out tests support regression testing and failure analysis without making an LLM judge the truth source.

Fourth, the temporal authoring pipeline addresses breadth and staleness while preserving provenance. Its fail-closed gates are particularly valuable because automated case generation can otherwise convert extraction errors into benchmark “ground truth.” The value lies in the auditable compilation process, not in claiming that recency alone prevents contamination.

## Precise contribution boundary

The most defensible positioning is:

> Role Benchmark uses a matched-pairs design for interactive scientific law discovery. It compares historical and counterfactual conditions and system identification with scientific law discovery, requires hypothesis-specific predictions before observations, and reports held-out prediction separately from process-evaluation measures.

The project should **not** claim to introduce the first interactive science benchmark, the first counterfactual-physics benchmark, the first controlled-prior benchmark, the first active equation-discovery system, the first process evaluation of scientific agents, or the first paper-derived temporal benchmark. The reviewed literature supplies clear precedents for each component.

The current implementation also does not yet justify three stronger claims. It has no private formal case pack, so public-run results are development diagnostics rather than contamination-resistant capability estimates. Its two tracks use different final encodings, so track differences do not isolate information disclosure alone. Finally, all current Oracles are deterministic case simulators; the proposed deterministic-versus-probabilistic Oracle ablation has not been implemented.

## Search and verification note

The review used concept queries and exact-title verification across arXiv, OpenReview, ACL Anthology, publisher pages and DOI landing pages. Search clusters covered: interactive scientific discovery benchmarks; counterfactual physics and law induction; symbolic regression and system identification; Bayesian and discriminative experimental design; scientific-agent process evaluation; paper-derived research benchmarks; temporal/contamination-limited evaluation; and autonomous laboratory agents. Primary papers or official publisher records were preferred. Exact metadata for the closest works was verified against their current arXiv, OpenReview, ACL or publisher record on 1 September 2026. The bibliography is maintained in `references.bib`.

## References

References are resolved from [references.bib](references.bib). The comparison is scoped to work found and verified by 1 September 2026; a camera-ready manuscript should repeat the exact-title search immediately before submission.
