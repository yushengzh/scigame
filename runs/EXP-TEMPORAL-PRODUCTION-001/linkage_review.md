# Journal–arXiv record linkage review

Review date: 2026-09-03

Scope: the five frozen records whose `linkage_method` is `manual_web_search_adjudication`
Decision sources: official journal/Crossref metadata and official arXiv records

The field-level record, including complete author lists, queries, official identifiers, observation time, decisions, and unrecoverable retrieval limitations, is in [`linkage_adjudication.json`](linkage_adjudication.json). The original search provider, search time, ranking, and complete returned candidate set were not saved in the frozen manifest and are therefore recorded as missing rather than reconstructed.

## Decision rule

A quoted full-title web search is used only for candidate retrieval. A candidate is confirmed only from official metadata. An exact canonical journal DOI in the arXiv record is sufficient when unique. If the arXiv record does not report the journal DOI, the review requires title consistency, the same first author, strong full-author consistency, and consistent abstract/method content. An explicit DOI conflict, no reasonable author overlap, or only topical or numeric similarity is a linkage failure. A web-search non-hit remains unresolved and is not evidence that no arXiv preprint exists.

Automatic identity matching uses only narrow Unicode, case and whitespace normalization and preserves scientific punctuation, digits, subscripts, superscripts and markup. Display variants such as `CuO2`, `CuO₂` and `CuO_{2}` may broaden candidate retrieval, but without an exact DOI they still require manual adjudication. Numeric agreement alone is never sufficient to establish paper identity.

## Results

| Order | Journal record | Candidate arXiv record | Official DOI evidence | Author evidence | Decision |
| --- | --- | --- | --- | --- | --- |
| 020 | [Nature: Observation of conformal field theory spectra in a quantum simulator](https://doi.org/10.1038/s41586-026-10904-x) | [arXiv:2601.16275v1, Experimental observation of conformal field theory spectra](https://arxiv.org/abs/2601.16275v1) | arXiv did not report the journal DOI at review time | Same first author; all 9 journal authors appear in the arXiv record | Confirmed after manual adjudication |
| 021 | [Nature: Superconducting 2D cuprate with a single CuO2 plane](https://doi.org/10.1038/s41586-026-10857-1) | [arXiv:2602.06389v1, Superconductivity in Isolated Single Copper Oxygen Plane](https://arxiv.org/abs/2602.06389v1) | arXiv does not report the Nature DOI | First authors differ (Hengsheng Luo versus Youngdo Kim); overlap is 0 of 15 journal authors and 0 of 10 arXiv authors; the material and measurement methods also differ | **Rejected: `arxiv_linkage_failed`** |
| 022 | [Nature: Planetary-mass exosatellite detected around the substellar companion of a star](https://doi.org/10.1038/s41586-026-10751-w) | [arXiv:2607.05193v1](https://arxiv.org/abs/2607.05193v1) | Exact journal DOI is present in the current arXiv record | Same first author; all 13 authors correspond after punctuation/diacritic normalization | Confirmed by exact DOI |
| 023 | [Science: Constraining an exoplanet’s magnetic field using star-planet interactions](https://doi.org/10.1126/science.adv3075) | [arXiv:2604.06969v1](https://arxiv.org/abs/2604.06969v1) | Exact journal DOI is present in the arXiv record | Same first author; all 20 authors correspond after punctuation normalization | Confirmed by exact DOI |
| 024 | [Science: Helium escaping from the atmosphere of a nearby rocky exoplanet orbiting in a habitable zone](https://doi.org/10.1126/science.aea9708) | [arXiv:2607.14326v1](https://arxiv.org/abs/2607.14326v1) | Exact journal DOI is present in the arXiv record | Same first author; all 16 authors correspond | Confirmed by exact DOI |

Four of five supplemental candidates are confirmed. Order 021 is retained in the frozen denominator and recorded as linkage attrition; it is not replaced. Its downloaded arXiv source and any downstream authoring artifacts are invalid for the cited Nature paper and cannot contribute a benchmark family.

The order-021 failure demonstrates why search ranking, topic similarity, shared chemical notation, or matching numbers cannot serve as the identity decision. The frozen manifest's Boolean `author_consistent` and `study_content_consistent` fields were unsupported assertions; this review supersedes those assertions without rewriting the frozen manifest.
