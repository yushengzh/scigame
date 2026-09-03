# Journal–arXiv title and numeric linkage audit

Audit date: 2026-09-03

Unit of analysis: one journal–arXiv candidate pair
Descriptive denominator: **14 pairs**

## Scope and denominator

This artifact audits every pair with complete journal title, official arXiv title, and DOI/author evidence in the existing five-record EXP-001 linkage adjudication, together with all eight accepted and one unresolved complete pairs in the existing EXP-002 Nature/Science candidate audit. The EXP-002 records are contextual comparison cases; including them here does not modify either experiment's frozen manifest or cohort.

Records lacking a journal–arXiv title pair or author evidence are excluded rather than retrospectively reconstructed. Specifically, EXP-002 rejection entries that preserve only identifiers and a source-availability disposition, false-positive examples without a corresponding journal candidate, and manifest entries containing only one title or a Boolean title-consistency assertion are outside the denominator.

This is a **descriptive complete-case sample**, not a random or exhaustive sample of all retrieved candidates, all journal records, or all missed arXiv records. Consequently, neither linkage precision nor recall can be estimated from these counts.

## Decision and classification policy

Identity evidence is ordered as follows: exact canonical journal DOI in official arXiv metadata; explicit publisher/repository publication or preprint relation; then documented manual adjudication using official titles, author lists, and abstract or method content. A title, shared topic, matching number, or matching formula is never sufficient by itself.

Digits, decimal points, signs, percentages, chemical stoichiometric numbers, subscripts, superscripts, and mathematical symbols may be converted only into retrieval or display variants. Such conversion has no automatic identity authority. A substantive numerical disagreement must remain a conflict.

The title-difference labels are descriptive:

- **exact**: no scientific-content difference after Unicode NFC, case, whitespace, and visibly equivalent typographic dash/apostrophe display comparison;
- **typographic numeric/math only**: remaining difference is only equivalent numeric or mathematical layout or spacing, with unchanged values and mathematical roles;
- **substantive rewrite**: scientific wording is added, removed, abbreviated, reordered, or materially rephrased;
- **substantive numeric conflict**: a corresponding value, sign, exponent, dimension, percentage, or stoichiometric number differs.

These labels describe titles; they do not decide linkage.

## Summary

| Measure | Count |
| --- | ---: |
| Complete candidate pairs | 14 |
| EXP-001 linkage-adjudication pairs | 5 |
| Contextual EXP-002 pairs | 9 |
| exact | 8 |
| typographic numeric/math only | 1 |
| substantive rewrite | 5 |
| substantive numeric conflict | 0 |
| confirmed by exact DOI | 7 |
| confirmed by official-metadata/manual adjudication | 5 |
| rejected linkage | 1 |
| unresolved | 1 |

The zero count for substantive numeric conflict is only an observation in this small complete-case sample. It does not show that numerical conflicts are absent in the broader retrieval population.

## Pair-level audit

| Pair | Journal title | Official arXiv title | DOI evidence | Author evidence | Title difference | Linkage decision |
| --- | --- | --- | --- | --- | --- | --- |
| exp001_order_020 | Observation of conformal field theory spectra in a quantum simulator | Experimental observation of conformal field theory spectra | arXiv DOI not reported | same first author; correspondence 9/9 journal and 9/9 arXiv authors | substantive rewrite | confirmed — official-metadata/manual adjudication |
| exp001_order_021 | Superconducting 2D cuprate with a single CuO2 plane | Superconductivity in Isolated Single Copper Oxygen Plane | arXiv DOI not reported | different first author; overlap 0/15 journal and 0/10 arXiv authors | substantive rewrite | rejected — linkage failed |
| exp001_order_022 | Planetary-mass exosatellite detected around the substellar companion of a star | Planetary-mass exosatellite detected around the substellar companion of a star | exact DOI (10.1038/s41586-026-10751-w) | same first author; correspondence 13/13 journal and 13/13 arXiv authors | exact | confirmed — exact DOI |
| exp001_order_023 | Constraining an exoplanet’s magnetic field using star-planet interactions | Constraining an exoplanet’s magnetic field using star-planet interactions | exact DOI (10.1126/science.adv3075) | same first author; correspondence 20/20 journal and 20/20 arXiv authors | exact | confirmed — exact DOI |
| exp001_order_024 | Helium escaping from the atmosphere of a nearby rocky exoplanet orbiting in a habitable zone | Helium escaping from the atmosphere of a nearby rocky exoplanet orbiting in a habitable zone | exact DOI (10.1126/science.aea9708) | same first author; correspondence 16/16 journal and 16/16 arXiv authors | exact | confirmed — exact DOI |
| exp002_2601.19978v1 | An X-ray-emitting protocluster at z ≈ 5.7 reveals rapid structure growth | An X-ray-Emitting Proto-Cluster at z≈5.7 Reveals Rapid Structure Growth | exact DOI (10.1038/s41586-025-09973-1) | First authors agree after diacritic normalization; all four authors agree according to the source audit. | typographic numeric/math only | confirmed — exact DOI |
| exp002_2602.08472v1 | Long-lived remote ion–ion entanglement for scalable quantum repeaters | A building block of quantum repeaters for scalable quantum networks | exact DOI (10.1038/s41586-026-10177-4) | The first author and the 29-author list agree according to the source audit. | substantive rewrite | confirmed — exact DOI |
| exp002_2604.23926v2 | A distant brown dwarf coplanar to a warm Jupiter and a hot super-Earth | A distant brown dwarf coplanar to a warm Jupiter and a hot super-Earth | exact DOI (10.1038/s41586-026-10586-5) | The first author and complete author list agree according to the source audit. | exact | confirmed — exact DOI |
| exp002_2607.12664v1 | Discovery of a star sensitive to the spin of Sagittarius A* | Discovery of a star sensitive to the spin of Sgr A* | arXiv DOI not reported | The first author and large collaboration author list agree according to the source audit. | substantive rewrite | confirmed — official-metadata/manual adjudication |
| exp002_2608.11443v1 | Numerous bow shocks in the outer Helix Nebula | Numerous bow shocks in the outer Helix Nebula | arXiv DOI not reported | The first author and all eight authors agree according to the source audit. | exact | confirmed — official-metadata/manual adjudication |
| exp002_2606.15497v1 | Towards end-to-end automation of AI research | Towards End-to-End Automation of AI Research | arXiv DOI not reported | The same eight-author set is present; author order differs between the records. | exact | confirmed — official-metadata/manual adjudication |
| exp002_2602.11271v1 | Gas-depleted planet formation occurred in the four-planet system around the red dwarf LHS 1903 | Gas-depleted planet formation occurred in the four-planet system around the red dwarf LHS 1903 | exact DOI (10.1126/science.adl2348) | The first author and collaboration author list agree according to the source audit. | exact | confirmed — exact DOI |
| exp002_2601.07825v1 | Mechanical resonator–based quantum computing | Mechanical Resonator-based Quantum Computing | arXiv DOI not reported | The first author and the complete 14-author list agree according to the source audit. | exact | confirmed — official-metadata/manual adjudication |
| exp002_2606.07754v1 | Nuclear shell structure governs short-range nucleon pairing | Short-range correlated pair formation and nuclear shell structure | arXiv DOI not reported | The first author and nearly complete author set overlap according to the source audit. | substantive rewrite | unresolved |

## Interpretation

The sample demonstrates three distinct points:

1. An exact DOI can confirm identity despite a substantive title rewrite.
2. Equivalent mathematical typography can explain a display difference, but does not itself confirm identity.
3. Similar scientific wording and chemical or dimensional notation can retrieve a wrong candidate: EXP-001 order 021 has no author overlap and different material and measurement methods, so it is rejected despite topical and notation similarity.

The complete structured evidence, category detail, original decision basis, and record locator for every row are retained in `title_numeric_linkage_audit.json`.

## Source artifacts

- [EXP-001 frozen source manifest](frozen_sources.json)
- [EXP-001 official-metadata linkage adjudication](linkage_adjudication.json)
- [EXP-001 linkage review](linkage_review.md)
- [EXP-002 Nature/Science candidate audit](../EXP-TEMPORAL-PRODUCTION-002/nature_science_candidate_audit.json)
