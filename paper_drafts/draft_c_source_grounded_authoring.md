# From Recent Papers to Executable Experimental Worlds: A Source-Grounded Authoring Pipeline and Its Failure Modes

**Working paper draft C — benchmark-authoring alternative.** This draft reports
the current negative result. It is not ready for a main-conference submission
because the latest source-only pipeline has produced no accepted case.

## Abstract

Recent scientific papers are attractive sources for continuously refreshed
benchmarks, but a paper does not directly define an interactive environment.
Turning a published result into a case requires selecting manipulable controls,
operational readouts, fixed conditions, an executable response, and a valid
evaluation domain without adding facts that the source does not support. We
present a source-grounded authoring pipeline that separates record acquisition,
scientific evidence extraction, case design, deterministic validation, and
scientific review. A fixed journal record is resolved to a versioned arXiv TeX
source. One language-model call proposes a line-anchored private `ScienceCard`;
after independent source review, a second call sees only the reviewed card and
may propose a matched case. Deterministic checks enforce source lineage,
Player–Oracle information boundaries, executability, and distinguishability;
an independent family review precedes template-based rendering. The language
model proposes structured artifacts but never serves as scientific authority.
Our development evidence is predominantly negative. In an ordered purposive
cohort of ten papers, six reached a ScienceCard outcome, only two outputs were
schema-parseable, neither passed source review, and a provider failure stopped
the run before paper seven returned a response. No case reached drafting. An
earlier monolithic path rendered one development family, but that family is
ineligible under the current source-only policy because its counterfactual was
benchmark-authored. These results identify concrete failure modes—invalid
numeric domains, conflated experimental regimes, missing executable parameters,
and unsupported uncertainty semantics—but do not establish conversion yield or
autonomous benchmark generation. We argue that reliable paper-derived
interactive benchmarks require complete source support and rejection as a
first-class outcome.

## 1. Introduction

Static benchmarks built from familiar scientific equations face two related
problems. Their answers may be represented in model training data, and their
fixed task distribution ages as models improve. Continuously refreshed
benchmarks address part of this problem by drawing from recent research. RealMath
derives verifiable research-level mathematics tasks from papers and forums
(Zhang et al., 2025), while LiveMathematicianBench constructs theorem-grounded
questions from recent arXiv papers (He et al., 2026). In the broader scientific
workflow, ScienceAgentBench extracts executable data-driven tasks from 44
peer-reviewed publications and validates them with domain experts (Chen et al.,
2024). These works show both the promise of paper-derived tasks and the need for
quality control.

Interactive scientific-law benchmarks introduce an additional transformation.
A paper reports claims under a particular apparatus, analysis, and set of
conditions. An interactive case must answer arbitrary allowed interventions,
which requires a closed response function over a declared domain. It must also
decide which facts the Player sees, which facts remain private to the Oracle,
and how a final model is evaluated. If an authoring model fills a missing domain
from memory, turns a qualitative comparison into a numerical branch, or treats
a nearby caption as evidence for an operational definition, the resulting
environment may be executable but scientifically unsupported.

The central authoring question is therefore not “can an LLM generate a case
file?” It is: **can every scientific quantity needed by the executable Oracle be
traced to an identified source claim under compatible conditions?** We call
this requirement **complete source support**. It is a concrete admission rule,
not a claim of complete scientific truth: every response function, parameter,
domain, fixed condition, readout definition, and uncertainty interpretation
used by the case must be supported by the frozen source or explicitly labeled
as benchmark-authored. Under a strict source-only policy, the latter category is
not allowed.

We implement a staged pipeline around this rule. Structured metadata and
identity resolution use deterministic code. A first language-model call maps
line-numbered TeX into a private evidence graph. A scientific reviewer decides
whether that graph supports a compatible pair of response branches. Only then
does a second language-model call propose a matched case from the reviewed
card. Deterministic validation and a second source review precede rendering.
The episode benchmark itself still has only Player and Oracle roles; authoring
models operate offline.

This draft makes three limited contributions:

1. an implemented two-stage authoring contract that separates source extraction
   from case design and prevents the second model call from supplementing the
   source from memory;
2. explicit admission gates for source lineage, shared experimental domains,
   Player–Oracle information boundaries, executable response functions, and
   matched-case distinguishability; and
3. a transparent negative development study that distinguishes schema failure,
   source-review rejection, deterministic rejection, and infrastructure
   failure.

We do not claim an autonomous generator, a representative conversion rate, or a
formal temporal benchmark. The latest pipeline accepted zero cases.

## 2. Related work

### Recent and continuously refreshed benchmarks

RealMath constructs a continuously refreshed evaluation from research papers
and mathematical forums, emphasizing verifiable answers and resistance to
simple benchmark saturation (Zhang et al., 2025). LiveMathematicianBench uses
recent theorems and proof-sketch-guided distractors for research-level
mathematical reasoning (He et al., 2026). These projects establish temporal
source acquisition as an important benchmark strategy. Recent publication,
however, does not prove absence from training data, and their fixed-answer or
multiple-choice tasks do not require compiling a source into an active numeric
world.

### Paper-derived scientific tasks and claim–evidence links

ScienceAgentBench extracts 102 executable tasks from 44 publications and uses
multiple rounds of annotator and subject-matter-expert validation (Chen et al.,
2024). CLAIM-BENCH directly evaluates whether models can link scientific claims
to supporting evidence across long papers (Javaji et al., 2025). We inherit two
principles: paper-derived tasks require expert authority, and claims should be
linked to their supporting evidence rather than generated as ungrounded
summaries. Our additional constraint is executability: the linked information
must be sufficient to answer all allowed experimental queries, not only to
justify a textual claim.

### Interactive law discovery

DiscoveryWorld, PhysGym, NewtonBench, LLM-AutoSciLab, and DiscoverPhysics provide
interactive environments in which agents gather evidence and infer mechanisms
(Jansen et al., 2024; Y. Chen et al., 2025; Zheng et al., 2025; Kabra et al., 2026;
Wiemann et al., 2026). These works establish the benchmark target that the
authoring pipeline aims to populate. Our contribution cannot be “interactive
scientific discovery” itself. The proposed increment is a source-traceable path
from a recent paper to a small executable world, which remains unvalidated at
scale.

## 3. Design principles

### 3.1 A paper is not a case

A paper may yield zero, one, or several candidate families. Scientific impact
and authorability are different properties. A suitable candidate needs at least
one controllable input, a quantitative readout, a closed response over a numeric
domain, and two compatible branches if the target benchmark requires matched
worlds. A qualitative mechanism contrast at one setting is not an executable
branch. A fitted coefficient without a stated domain cannot safely support
arbitrary queries. A response that depends on an unreported function is not
closed even if the governing equation is printed.

Consequently, rejection is an expected scientific outcome. The pipeline must
not widen ranges, invent nuisance controls, add unsupported operators, or turn
an approximate relation into an exact law to meet a target case count.

### 3.2 Source-only and synthetic-counterfactual policies are distinct

Two defensible authoring modes should not be conflated. In a **source-only**
mode, both response branches and all their parameters must be reported in the
paper under compatible conditions. This supports a paper-grounded regime
comparison but may yield few cases. In a **synthetic-counterfactual** mode, a
reviewer may deliberately change one mechanism coordinate to build a matched
world. That can be useful for testing familiar priors, but the changed law is a
benchmark construct and must not be attributed to the paper.

The current temporal pipeline adopts the stricter source-only policy. An older
development artifact used a synthetic counterfactual and is retained only as a
record of the earlier policy.

### 3.3 Authority by information type

The smallest sufficient division of labor is:

| Operation | Method | Authority |
| --- | --- | --- |
| Enumerate journal records in a fixed date window | Metadata API and deterministic pagination | Journal/Crossref record |
| Resolve a paper to a versioned arXiv source | DOI-first identity rules and exact fallback | Deterministic resolver |
| Extract claims, conditions, controls, readouts, and parameters from TeX | LLM proposal over line-numbered source | Independent source review |
| Propose a matched interactive case | LLM proposal over reviewed card only | Deterministic filter plus independent family review |
| Generate executable case code | Template renderer | Validated structured draft |

The language model is useful for semantic mapping across equations, captions,
methods, and supplements. It is not allowed to approve its own extraction or
generate executable Python directly.

## 4. Pipeline

### 4.1 Frozen source recruitment

The acquisition stage begins from a prespecified set of journals and an
inclusive date interval. The current implementation supports Nature, Science,
and Physical Review Letters records through Crossref. It exhausts the interval
rather than stopping when a target count is reached. Title and first-author
surname are used to retrieve arXiv candidates, but identity is resolved by a
unique matching DOI whenever available. Exact normalized title plus first-author
surname is permitted only when the candidate declares no DOI. A conflicting DOI
cannot be overridden by textual similarity.

The matched arXiv record is fixed to a versioned identifier, and the source
archive must contain TeX. Publication date, first public date, article type,
withdrawal status, and source availability are separate gates. Finding a recent
paper or an arXiv record does not imply a usable source bundle.

### 4.2 Stage 1: line-anchored ScienceCard

All TeX files in the source bundle are concatenated in a stable order and given
line numbers. The first model receives only this source and the authoritative
paper identity. It returns a strict `ScienceCard` containing:

- candidate mechanisms and their parameters;
- fixed experimental or simulation conditions;
- controls, readouts, units, and operational definitions;
- quantitative claims, domains, statistical summaries, and uncertainty
  semantics;
- line ranges supporting each item; and
- dependencies linking a claim to the mechanism and conditions it requires.

The card is private authoring material, not a Player prompt. It does not choose
a counterfactual, budget, held-out test, or final case representation. Strict
parsing rejects duplicate keys, unknown fields, nonfinite values, invalid
identifiers, and broken reference graphs.

An independent source reviewer then checks whether each locator supports the
asserted field and whether a pair of claims defines executable response branches
over a common active domain. The model's own readiness field is a triage hint,
not an admission decision.

### 4.3 Stage 2: matched case proposal

Only a reviewed, reviewer-selected evidence cluster enters stage 2. The second
model does not receive the paper text and cannot cite source lines absent from
the card. It returns either `not_authorable` or one `MatchedCaseDraft` specifying
the public apparatus, private branch selector, response expressions, parameter
maps, allowed interventions, diagnostic points, and evaluation conditions.

The source-only contract requires both worlds to reuse card parameters and
claims. Public text must not reveal which branch is active or state the target
relationship. Controls and readouts must correspond to the reviewed evidence
cluster.

### 4.4 Deterministic gates and rendering

The hard filter checks exact lineage, identifier syntax, operator support,
finite evaluation, parameter use, shared public interfaces, one declared branch
difference, and budget-feasible distinguishability in both directions. Hidden
tests must reject each world's false twin. A second independent review checks
that the full family remains supported by the cited source after transformation.

Only an accepted draft is rendered through a fixed template into an importable
case module. The renderer does not execute model-authored code. The resulting
family must instantiate historical/counterfactual by identification/induction
cells under the ordinary benchmark protocol.

### 4.5 Ordered warm-up coordinator

The current warm-up freezes at most ten papers and processes them in order. A
schema or artifact failure is recorded for that paper and processing continues.
A provider/runtime failure stops the run because silently retrying would change
the declared one-call policy. Missing source reviews pause the coordinator and
resume from saved artifacts. The coordinator stops at the first case that
passes both reviews, the deterministic filter, rendering, and four-cell
instantiation.

## 5. Development results

### 5.1 Legacy monolithic path

An earlier implementation asked one model call to extract paper evidence and
design cases together. Seven calls used `deepseek-v4-flash`, temperature 0,
thinking disabled, an 8,192-token output limit, and no repair. Across seven
papers, raw model output produced 12 candidates; none passed the original full
pipeline without later contract or scientific review. Failures included invalid
identifiers, unsupported operators, inconsistent parameters, unused controls,
and proposed functions that did not encode the stated mechanism.

After removing an arbitrary two-control minimum and performing source review,
one Kibble–Zurek vortex-scaling family was rendered and validated across four
development cells. Its second world changed the fitted exponent to a
benchmark-authored value. It therefore demonstrates the older renderer and
matched-case machinery but is ineligible under the current source-only policy.
It must not be counted as a current accepted temporal case.

### 5.2 Two-stage source review on the Kibble–Zurek paper

The same paper was processed under the two-stage contract. A parseable card was
eventually produced, but independent review found that it omitted mechanism
dependencies, missed response branches needed for the intended pairing,
widened discrete temperature regimes into a continuous control, conflated
relative and absolute time quantities, and assigned uncertainty semantics and
domains beyond their cited lines. The card was rejected before valid authoring.

A diagnostic stage-2 call made before that review completed also failed lineage
and leaked private regime information into public fields. It was preserved as a
failure artifact and not repaired or rendered. This example shows that schema
validity and in-range locators do not establish scientific support.

### 5.3 Latest ordered stop-first cohort

The latest run froze ten purposively selected papers. It processed through the
seventh schedule position before a provider connection failure stopped the run.
The denominators are:

| Outcome | Count | Interpretation |
| --- | ---: | --- |
| ScienceCard-stage outcomes | 6 | Papers with a model response that reached strict stage accounting |
| Schema-parseable ScienceCards | 2/6 | Structural success only |
| Paper-level source-review passes | 0/2 | No card supplied a fully source-supported compatible branch pair |
| ScienceCard schema failures | 4/6 | Model-output failure; not paper ineligibility |
| Provider failure before response | 1 | Infrastructure failure; no scientific assessment |
| Unattempted papers after stop | 3 | No outcome |
| Cases reaching draft stage | 0 | — |
| Accepted current-policy cases | 0 | — |

One parseable Kibble–Zurek card lacked a common numeric domain for the paired
energy branches, mixed temperature conditions, omitted compressible-energy fit
parameters, and overstated uncertainty semantics. A parseable Kramers–Langer
card described a qualitative isotope branch at one approximate aspect ratio,
while the quantitative rate required source functions and parameters not
available as an executable response. Both were scientifically rejected.

Four other papers failed strict schema checks, including nonnumeric control
bounds, an inverted numeric interval, and an invalid identifier. These failures
show limitations of the generation contract, not that the underlying papers
cannot support cases. Because the cohort is purposive, incomplete, and stopped
on infrastructure, no conversion-rate estimate is warranted.

## 6. Lessons from rejection

### JSON transport is not constrained decoding

A provider's JSON-object mode can return syntactically valid JSON that violates
the application schema. Including the exact schema and using a strict parser
improves observability but does not guarantee a usable card. Automatic semantic
repair would blur the one-call policy and can change scientific content.

### A locator is not evidence by itself

Line numbers make claims reviewable, but a nearby caption may not support the
asserted operational definition, domain, or uncertainty interpretation. Source
review must examine what the cited lines establish, not only whether the range
exists.

### Shared domain is an executable requirement

Two reported regimes do not automatically form a matched case. Both branches
must answer the same allowed interventions over a common nonzero domain under
compatible fixed conditions. Otherwise, the Oracle requires interpolation or
extrapolation that the source never authorizes.

### Rejection categories must remain separate

Schema failure, scientific ineligibility, deterministic filter failure, missing
review, and provider failure have different denominators and remedies.
Collapsing them into “paper conversion failed” would misrepresent both the model
and the source literature.

### Strict grounding exposes a real policy tradeoff

Source-only cases maximize traceability but require papers with compatible
reported branches. Synthetic counterfactuals expand coverage and can create
clean prior-conflict tests, but their altered laws are author-created. A single
pipeline should not claim both complete source grounding and fictional novelty
for the same branch.

## 7. Evaluation needed for a publishable method

A main-conference empirical study would require a frozen, representative
sampling frame rather than purposive paper selection; complete acquisition
accounting from journal census through TeX availability; prespecified source
review rubrics; multiple independent card and family reviewers with agreement
statistics; and comparison of one-stage, two-stage, and non-LLM or expert
authoring baselines. Outcomes should include parse rate, source-review precision
and recall on a manually annotated subset, reviewer time, accepted-case yield,
and downstream case validity. Sibling families from one source paper must be
clustered at the paper level.

Most importantly, the pipeline must produce enough accepted current-policy
cases to evaluate whether they support reliable Player experiments. An authoring
paper without accepted executable environments can characterize failure modes
but cannot establish an effective benchmark-construction method.

`[REQUIRES NEW EVIDENCE]`

## 8. Limitations and conclusion

TeX availability selects for publication practices and fields that release
source. Low-dimensional executable claims are not representative of all
scientific contributions. Line-based evidence can miss figures, external data,
and tacit apparatus knowledge. Independent source review is expensive and may
require domain specialists. Recent publication reduces some exposure risk but
does not establish contamination resistance.

The current result supports one conclusion: strict source grounding turns
rejection into a necessary part of benchmark authoring. A two-stage card and
case pipeline makes unsupported transformations visible and prevents the
case-design model from freely supplementing the paper. It does not yet generate
a usable cohort under the current policy. The correct next step is to improve
and measure source-faithful extraction on a representative sample, not to relax
domains or invent missing functions until cases pass.

## Proposed eight-page allocation

| Section | Pages |
| --- | ---: |
| Abstract and Introduction | 1.25 |
| Related work | 0.85 |
| Design principles | 1.10 |
| Pipeline | 1.60 |
| Development results | 1.45 |
| Lessons from rejection | 0.80 |
| Evaluation, limitations, conclusion | 0.95 |
| **Total** | **8.00** |
