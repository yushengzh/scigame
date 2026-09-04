# Model-based scientific source-review rubric

## Scope

The reviewer must use only the frozen `source_packet.txt` to judge scientific support. `science_card.json`, `construction/provenance.json`, and the generated case are claims to be checked, not evidence. Existing source-review decisions must not be treated as authority.

The locator mode is `structure-grounded`: source-packet line ranges and identifiable equations, sections, figures, or tables may be cited. PDF page numbers must not be invented.

## Required checks

1. **Source coverage**: determine whether the packet contains enough main-text, equation, table, caption, and supplementary context to judge the relation.
2. **Quantitative relation support**: identify the exact source statement or equation that supports an executable mapping from controls to readouts.
3. **Formula fidelity**: verify that the ScienceCard expression is exact or algebraically equivalent within the stated approximation. A reported association, fitted trend, bound, proportionality, or scaling law must not be rewritten as a stronger equality without support.
4. **Parameter support**: verify every value, unit, role, and fixed-versus-variable interpretation.
5. **Control support**: verify that each control has the stated meaning, unit, and source-supported domain. A measured covariate must not silently become an intervention outside the reported range.
6. **Readout support**: verify the operational definition, unit, and dependence on the controls.
7. **Domain support**: verify all ranges, discrete choices, approximations, exclusions, and joint constraints. Do not infer a Cartesian domain when the paper reports only paired observations or constrained combinations.
8. **Anchor accuracy**: inspect every declared line range and enough surrounding context to decide whether it supports the mapped field.
9. **Constructed-case fidelity**: check that deterministic construction did not change units, formula semantics, parameter values, or the source-supported domain.

## Decisions

- `retain`: every required field for at least one executable relation is supported; no blocking issue.
- `revision_required`: a usable source relation exists, but a formula, parameter, control, readout, domain, anchor, or construction field must be corrected.
- `reject`: the proposed relation is not source-supported, or fixing it would require a materially different relation.
- `not_assessable`: missing source material prevents a required judgment.

When uncertain between `retain` and `revision_required`, use `revision_required`. When uncertain between `revision_required` and `reject`, state the exact missing evidence and use `not_assessable` if the source packet is incomplete.

## Required review record

Each review must report:

- family and paper identifiers;
- primary analytical lens: `methods`, `discovery`, or `materials`;
- source coverage and locator mode;
- one result for every required check: `pass`, `fail`, or `not_assessable`;
- a claim–evidence matrix with source-packet line ranges;
- every issue with severity, affected fields, evidence, and a correction supported by the source when possible;
- one of the four dispositions and a concise decision basis;
- reviewer metadata stating `gpt-5.6-sol`, reasoning effort `ultra`, `language_model`, and `human_domain_expert=false`.

The reviewer must not claim novelty, use external literature to repair the ScienceCard, or describe itself as an independent human/domain expert.
