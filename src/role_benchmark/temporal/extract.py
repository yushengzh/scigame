"""Provider-neutral LLM abstraction step from one paper to zero or more cases."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Optional

from role_benchmark.llm import (
    GenerationConfig,
    GenerationRequest,
    GenerationResponse,
    Message,
    TextGenerationBackend,
)
from role_benchmark.wire import canonical_json_dumps

from .candidate import (
    CandidateDecodeError,
    PaperAbstraction,
    parse_paper_abstraction_json,
    temporal_paper_abstraction_json_schema,
)
from .arxiv import parse_versioned_arxiv_id
from .census import canonicalize_doi
from .latex import normalize_latex


_SYSTEM_PROMPT = """You abstract one scientific paper from its LaTeX source into zero or more paper-grounded interactive-science case candidates.
Return exactly one JSON object matching the supplied schema, without Markdown or extra text.
Copy the supplied authoritative citation, canonical journal DOI, and versioned arXiv ID verbatim into every candidate source object.
In assessment, briefly explain which quantitative claims are or are not abstractable under this contract. This assessment is advisory; it is not an eligibility verdict.
Return candidates=[] when the paper does not support any candidate under the contract. Never invent or return a closest fallback.
Create one candidate for each distinct quantitative claim that can independently define an experimental world; do not duplicate one mechanism merely because it appears in several equations or figures.
For every candidate, extract only a central quantitative claim supported at the stated source locator.
Use lower_snake_case for every machine identifier: family, apparatus name, control and readout names, expression variables and parameters, output keys, parameter keys, and condition keys.
Use 1-5 genuinely controllable numeric inputs and 1-2 numeric readouts with explicit units and ranges.
The oracle kind must be closed_form. Encode each output as an arithmetic expression template:
numbers are constants; {"var":"name"} is a public control; {"param":"name"} is a named private parameter;
and {"op":"...","args":[...]} uses only schema-listed operators.
The only allowed operator names are add, subtract, multiply, divide, power, negate, exp, log, sin, maximum, and step. Encode sqrt(x) as power(x, 0.5); never emit another operator name.
Paper parameters must reproduce the cited result. Counterfactual parameters must copy the complete paper-parameter key set and values, then change exactly one used parameter value;
every named parameter must occur in at least one output expression. Do not attribute that authored change to the paper.
Across the diagnostic conditions, give every control at least two distinct values while staying in range and fitting
within the proposed experiment budget, plus distinct hidden evaluation conditions. Keep public background minimal
and do not put the answer, equation, paper title, DOI, author names, or unique source phrases in public fields.
You propose candidates only. A deterministic filter will independently decide the eligibility of every candidate.
"""


@dataclass(frozen=True)
class PaperAbstractionResult:
    abstraction: PaperAbstraction
    response: GenerationResponse


def _source_identity(
    source_citation: str,
    journal_doi: str,
    arxiv_versioned_id: str,
) -> tuple[str, str, str]:
    citation = source_citation.strip() if isinstance(source_citation, str) else ""
    if not citation:
        raise ValueError("source_citation must be non-empty text")
    if not isinstance(journal_doi, str):
        raise ValueError("journal_doi must be text")
    canonical_doi = canonicalize_doi(journal_doi)
    if canonical_doi != journal_doi:
        raise ValueError("journal_doi must use its canonical DOI form")
    versioned_id = parse_versioned_arxiv_id(arxiv_versioned_id)
    return citation, canonical_doi, versioned_id


def validate_paper_abstraction_source(
    abstraction: PaperAbstraction,
    *,
    source_citation: str,
    journal_doi: str,
    arxiv_versioned_id: str,
) -> None:
    """Require every proposal to preserve the caller-supplied paper identity."""

    identity = _source_identity(source_citation, journal_doi, arxiv_versioned_id)
    for index, candidate in enumerate(abstraction.candidates):
        if candidate.source.citation != identity[0]:
            raise CandidateDecodeError(
                "abstraction.source_identity",
                "$.candidates[%d].source.citation" % index,
                "must equal the authoritative source citation",
            )
        if candidate.source.journal_doi != identity[1]:
            raise CandidateDecodeError(
                "abstraction.source_identity",
                "$.candidates[%d].source.journal_doi" % index,
                "must equal the authoritative journal DOI",
            )
        if candidate.source.arxiv_versioned_id != identity[2]:
            raise CandidateDecodeError(
                "abstraction.source_identity",
                "$.candidates[%d].source.arxiv_versioned_id" % index,
                "must equal the fixed arXiv source version",
            )


def build_paper_abstraction_request(
    latex_source: str,
    *,
    source_citation: str,
    journal_doi: str,
    arxiv_versioned_id: str,
    config: Optional[GenerationConfig] = None,
) -> GenerationRequest:
    """Build one paper-level abstraction request for any text backend."""

    normalized = normalize_latex(latex_source)
    identity = _source_identity(source_citation, journal_doi, arxiv_versioned_id)
    schema = temporal_paper_abstraction_json_schema()
    system_prompt = (
        _SYSTEM_PROMPT
        + "\nPaperAbstraction JSON Schema:\n"
        + canonical_json_dumps(schema)
    )
    user_parts = [
        "Authoritative source identity; copy these three values exactly into "
        "every candidate source object:\n"
        + json.dumps(
            {
                "arxiv_versioned_id": identity[2],
                "citation": identity[0],
                "journal_doi": identity[1],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    ]
    user_parts.append("LaTeX source follows:\n\n" + normalized)
    return GenerationRequest(
        messages=(
            Message("system", system_prompt),
            Message("user", "\n\n".join(user_parts)),
        ),
        response_schema=schema,
        config=config
        or GenerationConfig(max_output_tokens=8192, temperature=0.0, top_p=1.0),
        metadata={"purpose": "temporal_paper_abstraction", "source_format": "latex"},
    )


def extract_paper_abstraction(
    backend: TextGenerationBackend,
    latex_source: str,
    *,
    source_citation: str,
    journal_doi: str,
    arxiv_versioned_id: str,
    config: Optional[GenerationConfig] = None,
) -> PaperAbstractionResult:
    """Ask once for zero or more proposals and strictly parse the response."""

    response = backend.generate(
        build_paper_abstraction_request(
            latex_source,
            source_citation=source_citation,
            journal_doi=journal_doi,
            arxiv_versioned_id=arxiv_versioned_id,
            config=config,
        )
    )
    finish_reason = response.finish_reason.strip().lower()
    if finish_reason in {
        "length",
        "max_tokens",
        "max_output_tokens",
        "incomplete",
    } or finish_reason.startswith("incomplete:"):
        raise CandidateDecodeError(
            "abstraction.incomplete_generation",
            "$",
            "provider generation did not complete (%s)" % response.finish_reason,
        )
    abstraction = parse_paper_abstraction_json(response.text)
    validate_paper_abstraction_source(
        abstraction,
        source_citation=source_citation,
        journal_doi=journal_doi,
        arxiv_versioned_id=arxiv_versioned_id,
    )
    return PaperAbstractionResult(
        abstraction=abstraction,
        response=response,
    )


__all__ = [
    "PaperAbstractionResult",
    "build_paper_abstraction_request",
    "extract_paper_abstraction",
    "validate_paper_abstraction_source",
]
