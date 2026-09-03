"""First LLM stage: extract a private card from a line-numbered source packet."""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from typing import Any, Mapping, Optional, Sequence, Tuple

from role_benchmark.llm import (
    GenerationConfig,
    GenerationRequest,
    GenerationResponse,
    Message,
    TextGenerationBackend,
)
from role_benchmark.wire import canonical_json_dumps

from .arxiv import parse_versioned_arxiv_id
from .census import canonicalize_doi
from .latex import normalize_latex, normalize_source_packet
from .science_card import (
    ScienceCard,
    ScienceCardError,
    parse_science_card_json,
    science_card_json_schema,
    validate_science_card_lineage,
)


RETRYABLE_SCIENCE_CARD_ERROR_CODES = frozenset(
    {
        "science_card.locator",
        "science_card.schema",
    }
)


_SYSTEM_PROMPT = """You are a scientific evidence extractor. Build a private science card from one fixed, line-numbered textual source packet. You are not authoring a benchmark case.
Return exactly one JSON object matching the supplied schema, without Markdown or extra text.
Use only the supplied source. Do not use outside knowledge or infer missing facts from citations.
Copy the supplied citation, canonical journal DOI, and versioned arXiv ID exactly.
Except for mechanism.variable_names, names and IDs must be ASCII snake-style identifiers. Source-significant uppercase segments such as E_i or T_low may be retained; the next deterministic stage lowercases them for runtime use. mechanism.variable_names may preserve arbitrary raw paper notation.
Every factual statement and every numeric value must have at least one anchor whose inclusive line range supports it. Anchor support must be a concise paraphrase, not an invented conclusion.
Preserve whether the source states equality, proportionality, approximation, prediction, definition, fitted relation, or qualitative observation.
Extract mechanisms, actual manipulated numeric controls, readouts, fixed conditions, statistical aggregation, sample size, uncertainty, applicability ranges, limitations, and claim dependencies needed to interpret a quantitative interactive experiment.
A control is a numeric quantity the study actually manipulates. A readout is a measured or computed observable. Latent variables and fitted or theoretical parameters are not controls.
Sample size, ensemble count, averaging rule, fit method, and uncertainty convention are statistical provenance, not physical fixed conditions and never a hidden-world discriminator. Record them in ScienceReadout.statistic/uncertainty and claim.statistical_basis/uncertainty instead of fixed_conditions. These fields describe the source data; they will not be copied onto a deterministic Oracle query.
Represent source support without inventing continuity: use domain_kind continuous_interval only for a source-supported nonzero interval, numeric_values for explicitly reported discrete manipulated settings, fixed_value for one setting, symbolic for a stated nonnumeric domain, and unreported when the source does not provide one. Only continuous_interval and numeric_values can later compile to Player controls. A fixed value belongs to the experimental context, not a range with equal endpoints. The quantity that distinguishes the two selected source-reported branches is private regime context, not a Player control: represent each branch value or limit as its own branch-specific fixed condition, and make the corresponding claim cite only its branch condition. Two isolated reported condition values do not license interpolation. Never borrow a numeric domain from one claim for another claim merely because they use the same symbol.
Use this exact domain-field table for every control and claim domain: continuous_interval => numeric minimum, numeric maximum with minimum < maximum, allowed_values=[]; numeric_values => minimum=null, maximum=null, at least two unique allowed_values; fixed_value => minimum=null, maximum=null, exactly one allowed_value; symbolic or unreported => minimum=null, maximum=null, allowed_values=[], and a non-empty domain_statement. A one-sided or otherwise non-numeric source condition is not a continuous_interval with a null endpoint. When a reviewer figure-evidence addendum conservatively identifies a finite query set but not a continuous source interval, encode those supported values as numeric_values.
For every quantitative response that could become an Oracle equation, record each fitted coefficient and exponent as a named ScienceParameter under its linked mechanism. The parameter value is the central value; put the paper's uncertainty text in uncertainty. Never leave a numeric coefficient or exponent only inside claim.quantitative_form. If the meaning of a reported plus/minus value is not specified, write source_unspecified; do not guess standard error or confidence interval.
For every retained claim, encode the central-value control-to-readout relation in claim.oracle_outputs using the supplied expression AST. Output keys must exactly equal that claim's readout_names. A {"var": ...} leaf must name one of that claim's control_names. A {"param": ...} leaf must name a ScienceParameter belonging to one of that claim's mechanism_ids. Every scientific constant, including zero or one when it occurs in the source equation, must be a named, anchored ScienceParameter referenced by a param leaf. Numeric literals are forbidden in ScienceClaim oracle_outputs; structural selector literals are added only by the deterministic case binder. Keep quantitative_form as a human-readable rendering of the same relation. Do not put uncertainty ranges into oracle_outputs: the executable Oracle evaluates only source-reported central parameter values. Keep source aggregation, data-point error bars, fit-parameter uncertainty, and their conventions in the provenance fields; they are not uncertainty on each deterministic query result.
An unspecified plus/minus convention is missing metadata, not a contradiction: do not create a source_ambiguity solely because the paper omits whether a quoted fit uncertainty is a standard error, confidence interval, or another convention. Preserve the numeric plus/minus values in the quantitative form and parameter records, mark their meaning source_unspecified, and keep point error bars such as one standard deviation separate when the source defines them.
Parameter names must be globally unique, including after lowercasing. Qualify names by readout and regime when the paper reports several amplitudes, exponents, or other quantities of the same kind.
Keep variable_names in the paper's recognizable notation when useful (for example tau_Q); unlike executable parameter names, they need not be lower_snake_case.
Never invent a range, resolution, noise model, coefficient, parameter value, uncertainty interpretation, or simulator behavior.
Keep general mechanisms and linked empirical claims together rather than atomizing every equation into an unrelated mini-case. claim.mechanism_ids cites mechanisms. claim.depends_on may cite only other claim_ids, never mechanism_ids; use an empty array when a claim has no claim-level prerequisite.
Extract only the single best complete quantitative cluster for this authoring run; do not catalogue a second, unrelated experiment. Prefer two source-reported regimes that can use the same one-to-five controls and one-or-two readouts. If no such pair exists, extract the best single response faithfully and set case_authoring_ready false. Include every fixed condition, statistic, uncertainty, applicability limit, and branch parameter needed to reproduce the selected responses. Every quantitative claim must cite every selected mechanism that supplies a coefficient, exponent, or equation used by that claim. If the same paper symbol has a different meaning or source-supported domain in another experiment, omit that other experiment rather than merging or widening the selected control. Do not exhaust the output budget cataloguing unrelated qualitative results.
Do not bundle a condition that changes between reported regimes into a common fixed condition. Split the common apparatus settings from each regime-specific value, and link each claim only to compatible conditions.
Include only fixed conditions needed to interpret the selected discovery formula. Omit global simulation or acquisition settings that do not enter the selected response, especially when their locator contains a branch-specific value incompatible with the other branch.
Preserve operational definitions separately from captions and fitted relations. A readout anchor must cover how the observable is defined; claim anchors must additionally cover the equation, domain, aggregation, and uncertainty convention they assert. For each claim, control_domains must give one separately anchored source-applicability domain for every cited control, preserving whether it is an interval, discrete values, fixed value, symbolic statement, or unreported; never substitute the broader paper-level control domain. For each readout, resolution is either a separately anchored measurement_resolution/reporting_increment object or null when the source supports neither. Do not infer resolution from uncertainty or silently treat decimal formatting as instrument resolution.
When the paper overloads notation or distinguishes a crossing-relative quantity from an absolute one, create separate readouts or claims and record the ambiguity. Never combine their equations or speculate why one presentation differs.
When main text, caption, appendix, or supplement uses materially different definitions or formulas, record the issue in source_ambiguities and do not silently reconcile it. Link every ambiguity to all affected claims, mechanisms, controls, readouts, and fixed conditions; leave all reference arrays empty only when the ambiguity affects the paper globally.
Set case_authoring_ready true only when the extracted evidence can support at least one numeric control, one numeric readout, one quantitative mechanism, and an objective response supported by source evidence within an explicit domain.
Do not generate Player background, initial observations, episode budgets, diagnostic or hidden conditions, counterfactuals, or code. The claim.oracle_outputs source relation is the only expression tree requested at this extraction stage.
"""


@dataclass(frozen=True)
class ScienceCardResult:
    card: ScienceCard
    response: GenerationResponse
    normalized_source: str
    attempt_count: int = 1


def _source_identity(
    source_citation: str,
    journal_doi: str,
    arxiv_versioned_id: str,
) -> Tuple[str, str, str]:
    citation = source_citation.strip() if isinstance(source_citation, str) else ""
    if not citation:
        raise ValueError("source_citation must be non-empty text")
    if not isinstance(journal_doi, str):
        raise ValueError("journal_doi must be text")
    canonical_doi = canonicalize_doi(journal_doi)
    if canonical_doi != journal_doi:
        raise ValueError("journal_doi must use its canonical DOI form")
    return citation, canonical_doi, parse_versioned_arxiv_id(arxiv_versioned_id)


def _numbered_source(normalized_source: str) -> str:
    return "\n".join(
        "L%06d\t%s" % (index, line)
        for index, line in enumerate(normalized_source.splitlines(), start=1)
    )


def build_science_card_request(
    latex_source: str,
    *,
    source_citation: str,
    journal_doi: str,
    arxiv_versioned_id: str,
    authoring_focus: Optional[str] = None,
    previous_science_card: Optional[Mapping[str, Any]] = None,
    review_guidance_issues: Optional[Sequence[Mapping[str, Any]]] = None,
    config: Optional[GenerationConfig] = None,
    source_format: str = "latex",
) -> GenerationRequest:
    if source_format not in {"latex", "source_packet"}:
        raise ValueError("source_format must be latex or source_packet")
    normalized = (
        normalize_source_packet(latex_source)
        if source_format == "source_packet"
        else normalize_latex(latex_source)
    )
    identity = _source_identity(
        source_citation, journal_doi, arxiv_versioned_id
    )
    schema = science_card_json_schema()
    system = (
        _SYSTEM_PROMPT
        + "\nScienceCard JSON Schema:\n"
        + canonical_json_dumps(schema)
    )
    focus = authoring_focus.strip() if isinstance(authoring_focus, str) else ""
    if authoring_focus is not None and not focus:
        raise ValueError("authoring_focus must be non-empty text when provided")
    routing = ""
    if focus:
        routing = (
            "\n\nSource-grounded routing hint from pre-screening:\n"
            + focus
            + "\nThis hint only selects a part of the supplied source for "
            "inspection. Verify every extracted fact against that source and "
            "provide exact locators; the source remains the sole authority. "
            "If the hinted cluster is unsupported or incomplete, represent it "
            "faithfully and set case_authoring_ready false."
        )
    guidance = ""
    guidance_reminder = ""
    if (previous_science_card is None) != (review_guidance_issues is None):
        raise ValueError(
            "previous_science_card and review_guidance_issues must be provided together"
        )
    if review_guidance_issues is not None:
        if not isinstance(previous_science_card, Mapping):
            raise ValueError("previous_science_card must be a JSON object")
        issue_payload = list(review_guidance_issues)
        if not issue_payload:
            raise ValueError("review_guidance_issues must not be empty")
        for index, issue in enumerate(issue_payload):
            path = "review_guidance_issues[%d]" % index
            if not isinstance(issue, Mapping) or set(issue) != {
                "code",
                "detail",
                "line_ranges",
            }:
                raise ValueError(
                    "%s must contain exactly code, detail, and line_ranges" % path
                )
            if not isinstance(issue["code"], str) or not issue["code"].strip():
                raise ValueError("%s.code must be non-empty text" % path)
            if not isinstance(issue["detail"], str) or not issue["detail"].strip():
                raise ValueError("%s.detail must be non-empty text" % path)
            ranges = issue["line_ranges"]
            if not isinstance(ranges, list) or not ranges:
                raise ValueError("%s.line_ranges must be a non-empty list" % path)
            for range_index, line_range in enumerate(ranges):
                range_path = "%s.line_ranges[%d]" % (path, range_index)
                if not isinstance(line_range, Mapping) or set(line_range) != {
                    "line_start",
                    "line_end",
                }:
                    raise ValueError(
                        "%s must contain exactly line_start and line_end" % range_path
                    )
                start = line_range["line_start"]
                end = line_range["line_end"]
                if (
                    isinstance(start, bool)
                    or not isinstance(start, int)
                    or isinstance(end, bool)
                    or not isinstance(end, int)
                    or start < 1
                    or end < start
                ):
                    raise ValueError(
                        "%s must satisfy 1 <= line_start <= line_end" % range_path
                    )
        guidance = (
            "\n\nRevision context from an independent review of a prior "
            "ScienceCard:\n"
            + canonical_json_dumps(
                {
                    "issues": issue_payload,
                    "previous_science_card": previous_science_card,
                }
            )
            + "\nThe previous ScienceCard is an editable rejected draft, not a "
            "source of new scientific facts. Use it as the baseline so supported "
            "content is not lost, but recheck every retained field against the "
            "supplied source. Address every listed issue by inspecting its line "
            "ranges, remove or revise unsupported content, and do not assume the "
            "review or prior draft is correct. The supplied source remains the "
            "sole authority. Return one complete revised ScienceCard for a new "
            "independent review."
        )
        # The numbered source packet can be long enough to separate the model's
        # final output from the review issues by many thousands of tokens.  Repeat
        # only the frozen issue checklist after the source so a revision cannot
        # silently reproduce the rejected field.  The prior card is deliberately
        # not repeated here, and the reminder adds no evidence or new facts.
        guidance_reminder = (
            "\n\nFinal revision checklist (routing context, not evidence):\n"
            + canonical_json_dumps({"issues": issue_payload})
            + "\nBefore returning the complete revised ScienceCard, verify that "
            "every listed issue is addressed in the output. Do not copy any "
            "rejected draft text that conflicts with an issue. The numbered "
            "source above remains the sole authority."
        )
    user = (
        "Authoritative source identity:\n"
        + json.dumps(
            {
                "arxiv_versioned_id": identity[2],
                "citation": identity[0],
                "journal_doi": identity[1],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        + routing
        + guidance
        + "\n\nThe line numbers below are the only valid global locator coordinate system. File boundary markers preserve the original packet member path; textual data attachments contain reported values or metadata.\n\n"
        + _numbered_source(normalized)
        + guidance_reminder
    )
    return GenerationRequest(
        messages=(Message("system", system), Message("user", user)),
        response_schema=schema,
        config=config
        or GenerationConfig(max_output_tokens=32768, temperature=0.0, top_p=1.0),
        metadata={"purpose": "temporal_science_card", "source_format": source_format},
    )


def build_science_card_repair_request(
    primary_request: GenerationRequest,
    previous_output: str,
    validation_error: ScienceCardError,
    *,
    attempt_number: int,
) -> GenerationRequest:
    """Build one bounded mechanical repair after strict validation fails.

    The original source prompt, response schema, and generation config remain
    unchanged. The only dynamic repair context is the immediately preceding
    output and its exact structured validator diagnostic, so every call is
    recordable and replayable.
    """

    if primary_request.metadata.get("purpose") != "temporal_science_card":
        raise ValueError("primary_request must be a temporal science-card request")
    if not isinstance(previous_output, str):
        raise ValueError("previous_output must be text")
    if not isinstance(validation_error, ScienceCardError):
        raise ValueError("validation_error must be a ScienceCardError")
    if validation_error.code not in RETRYABLE_SCIENCE_CARD_ERROR_CODES:
        raise ValueError("only a schema or locator error is mechanically repairable")
    if (
        isinstance(attempt_number, bool)
        or not isinstance(attempt_number, int)
        or attempt_number < 2
        or attempt_number > 4
    ):
        raise ValueError("attempt_number must be between 2 and 4")
    repair_payload = {
        "repair": {
            "instruction": (
                "Return one corrected complete ScienceCard JSON object for the "
                "same authoritative source. This is a bounded mechanical repair: "
                "change only the field or fields needed to satisfy the exact "
                "schema/locator diagnostic below. Preserve every other scientific "
                "statement, equation, numeric value, uncertainty, domain, claim, "
                "source ID, dependency, and locator from the rejected response. "
                "Reconcile an unknown reference only with an entity supported by source evidence "
                "already represented in the response and source; do not invent a "
                "new scientific entity or fact. For a locator error, use only an "
                "exact supporting range in the unchanged numbered source. Return "
                "the complete JSON object without Markdown or commentary."
            ),
            "previous_output": previous_output,
            "validation_error": {
                "code": validation_error.code,
                "detail": validation_error.detail,
                "path": validation_error.path,
            },
        }
    }
    metadata = dict(primary_request.metadata)
    metadata.update(
        {
            "generation_attempt": attempt_number,
            "repair_reason": validation_error.code,
        }
    )
    return GenerationRequest(
        messages=primary_request.messages
        + (Message("user", canonical_json_dumps(repair_payload)),),
        response_schema=primary_request.response_schema,
        config=primary_request.config,
        metadata=metadata,
    )


def _reject_incomplete(response: GenerationResponse) -> None:
    reason = response.finish_reason.strip().lower()
    if reason in {
        "length",
        "max_tokens",
        "max_output_tokens",
        "incomplete",
    } or reason.startswith("incomplete:"):
        raise ScienceCardError(
            "science_card.incomplete_generation",
            "$",
            "provider generation did not complete (%s)" % response.finish_reason,
        )


def _validate_response(
    response: GenerationResponse,
    *,
    expected_identity: Tuple[str, str, str],
    source_line_count: int,
) -> ScienceCard:
    _reject_incomplete(response)
    card = parse_science_card_json(response.text, require_oracle_outputs=True)
    if (
        " ".join(card.source.citation.split())
        != " ".join(expected_identity[0].split())
        or card.source.journal_doi != expected_identity[1]
        or card.source.arxiv_versioned_id != expected_identity[2]
    ):
        raise ScienceCardError(
            "science_card.source_identity",
            "$.source",
            "must equal the authoritative source identity",
        )
    # Citation whitespace is presentation, not model-authored evidence.  Some
    # providers normalize journal typography such as thin spaces; restore the
    # frozen acquisition string after confirming whitespace-equivalent text.
    card = replace(
        card,
        source=replace(card.source, citation=expected_identity[0]),
    )
    validate_science_card_lineage(card, source_line_count)
    return card


def extract_science_card(
    backend: TextGenerationBackend,
    latex_source: str,
    *,
    source_citation: str,
    journal_doi: str,
    arxiv_versioned_id: str,
    authoring_focus: Optional[str] = None,
    previous_science_card: Optional[Mapping[str, Any]] = None,
    review_guidance_issues: Optional[Sequence[Mapping[str, Any]]] = None,
    config: Optional[GenerationConfig] = None,
    max_total_attempts: int = 1,
    source_format: str = "latex",
) -> ScienceCardResult:
    """Extract a card with one proposal and at most three mechanical repairs."""

    if (
        isinstance(max_total_attempts, bool)
        or not isinstance(max_total_attempts, int)
        or max_total_attempts < 1
        or max_total_attempts > 4
    ):
        raise ValueError("max_total_attempts must be an integer between 1 and 4")

    if source_format not in {"latex", "source_packet"}:
        raise ValueError("source_format must be latex or source_packet")
    normalized = (
        normalize_source_packet(latex_source)
        if source_format == "source_packet"
        else normalize_latex(latex_source)
    )
    request = build_science_card_request(
        normalized,
        source_citation=source_citation,
        journal_doi=journal_doi,
        arxiv_versioned_id=arxiv_versioned_id,
        authoring_focus=authoring_focus,
        previous_science_card=previous_science_card,
        review_guidance_issues=review_guidance_issues,
        config=config,
        source_format=source_format,
    )
    expected = _source_identity(
        source_citation, journal_doi, arxiv_versioned_id
    )
    source_line_count = len(normalized.splitlines())
    primary_request = request
    for attempt_count in range(1, max_total_attempts + 1):
        response = backend.generate(request)
        try:
            card = _validate_response(
                response,
                expected_identity=expected,
                source_line_count=source_line_count,
            )
        except ScienceCardError as error:
            if (
                error.code not in RETRYABLE_SCIENCE_CARD_ERROR_CODES
                or attempt_count >= max_total_attempts
            ):
                raise
            request = build_science_card_repair_request(
                primary_request,
                response.text,
                error,
                attempt_number=attempt_count + 1,
            )
            continue
        return ScienceCardResult(
            card=card,
            response=response,
            normalized_source=normalized,
            attempt_count=attempt_count,
        )
    raise RuntimeError("unreachable ScienceCard extraction state")


__all__ = [
    "ScienceCardResult",
    "RETRYABLE_SCIENCE_CARD_ERROR_CODES",
    "build_science_card_repair_request",
    "build_science_card_request",
    "extract_science_card",
]
