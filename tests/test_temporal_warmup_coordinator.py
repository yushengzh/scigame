from __future__ import annotations

import contextlib
import copy
import io
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from experiments.run_temporal_warmup import (
    DEFAULT_MODEL,
    _parser,
    _persist_rendered_candidate,
    _same_json,
    run,
)
from role_benchmark import (
    BenchmarkTrack,
    GenerationConfig,
    GenerationRequest,
    GenerationResponse,
    Message,
)
from role_benchmark.temporal import (
    ACQUISITION_SCHEMA,
    MAX_COORDINATOR_COHORT_SIZE,
    CaseDraftError,
    WarmupContractError,
    assess_paper_eligibility,
    parse_science_card_payload,
    parse_source_review_payload,
    parse_warmup_cohort_payload,
    review_request_payload,
)


def _anchor(support: str):
    return {"line_start": 1, "line_end": 2, "support": support}


def _card_payload(citation: str, doi: str, arxiv_id: str, *, ready: bool = False):
    return {
        "assessment": "Two source-reported regimes share a control and readout.",
        "case_authoring_ready": ready,
        "source": {
            "citation": citation,
            "journal_doi": doi,
            "arxiv_versioned_id": arxiv_id,
        },
        "paper_scope": "The source reports two branches of one response.",
        "mechanisms": [
            {
                "mechanism_id": "response_mechanism",
                "statement": "A reported regime changes the response relation.",
                "equations": ["branch a: y=a*x", "branch b: y=b*x^2"],
                "variable_names": ["x", "y"],
                "parameters": [
                    {
                        "name": "a_scale",
                        "value": 2.0,
                        "uncertainty": "source_unspecified",
                        "unit": "dimensionless",
                        "role": "Branch-a scale.",
                        "anchors": [_anchor("The source reports the scale.")],
                    },
                    {
                        "name": "b_scale",
                        "value": 3.0,
                        "uncertainty": "source_unspecified",
                        "unit": "dimensionless",
                        "role": "Branch-b scale.",
                        "anchors": [_anchor("The source reports the scale.")],
                    },
                ],
                "anchors": [_anchor("The source reports both equations.")],
            }
        ],
        "fixed_conditions": [
            {
                "condition_id": "common_apparatus",
                "statement": "The apparatus is common to both regimes.",
                "anchors": [_anchor("The apparatus is held fixed.")],
            },
            {
                "condition_id": "regime_a",
                "statement": "The source reports regime A.",
                "anchors": [_anchor("Regime A is reported.")],
            },
            {
                "condition_id": "regime_b",
                "statement": "The source reports regime B.",
                "anchors": [_anchor("Regime B is reported.")],
            },
        ],
        "controls": [
            {
                "name": "input_x",
                "definition": "The manipulated input.",
                "unit": "a.u.",
                "minimum": 1.0,
                "maximum": 5.0,
                "anchors": [_anchor("The input domain is reported.")],
            }
        ],
        "readouts": [
            {
                "name": "response_y",
                "definition": "The reported aggregate response.",
                "unit": "a.u.",
                "statistic": "Central aggregate.",
                "uncertainty": "source_unspecified",
                "resolution": None,
                "anchors": [_anchor("The readout is defined.")],
            }
        ],
        "claims": [
            {
                "claim_id": "branch_a_claim",
                "statement": "Regime A follows its reported relation.",
                "quantitative_form": "y=a*x",
                "oracle_outputs": {
                    "response_y": {
                        "op": "multiply",
                        "args": [
                            {"param": "a_scale"},
                            {"var": "input_x"},
                        ],
                    }
                },
                "mechanism_ids": ["response_mechanism"],
                "control_names": ["input_x"],
                "control_domains": [
                    {
                        "control_name": "input_x",
                        "minimum": 1.0,
                        "maximum": 5.0,
                        "anchors": [_anchor("The claim uses the reported input domain.")],
                    }
                ],
                "readout_names": ["response_y"],
                "fixed_condition_ids": ["common_apparatus", "regime_a"],
                "applicability": "The reported input domain.",
                "statistical_basis": "Central aggregate.",
                "uncertainty": "source_unspecified",
                "depends_on": [],
                "anchors": [_anchor("The branch-A relation is reported.")],
            },
            {
                "claim_id": "branch_b_claim",
                "statement": "Regime B follows its reported relation.",
                "quantitative_form": "y=b*x^2",
                "oracle_outputs": {
                    "response_y": {
                        "op": "multiply",
                        "args": [
                            {"param": "b_scale"},
                            {"var": "input_x"},
                            {"var": "input_x"},
                        ],
                    }
                },
                "mechanism_ids": ["response_mechanism"],
                "control_names": ["input_x"],
                "control_domains": [
                    {
                        "control_name": "input_x",
                        "minimum": 1.0,
                        "maximum": 5.0,
                        "anchors": [_anchor("The claim uses the reported input domain.")],
                    }
                ],
                "readout_names": ["response_y"],
                "fixed_condition_ids": ["common_apparatus", "regime_b"],
                "applicability": "The reported input domain.",
                "statistical_basis": "Central aggregate.",
                "uncertainty": "source_unspecified",
                "depends_on": [],
                "anchors": [_anchor("The branch-B relation is reported.")],
            },
        ],
        "source_ambiguities": [],
    }


def _review_payload(
    paper_id: str,
    citation: str,
    doi: str,
    arxiv_id: str,
    *,
    eligible: bool,
    review_material=None,
):
    source = {
        "citation": citation,
        "journal_doi": doi,
        "arxiv_versioned_id": arxiv_id,
    }
    material = copy.deepcopy(
        review_material
        if review_material is not None
        else _card_payload(citation, doi, arxiv_id)
    )
    if not eligible:
        return {
            "paper_id": paper_id,
            "source": source,
            "review_material": material,
            "reviewer": "independent source reviewer",
            "decision": "ineligible_for_bench",
            "assessment": "The locators do not close a usable matched pair.",
            "selected_cluster": None,
            "issues": [
                {
                    "code": "paper.no_valid_reported_regime_twin",
                    "detail": "No common public experiment is supported.",
                    "line_ranges": [{"line_start": 1, "line_end": 2}],
                }
            ],
        }
    return {
        "paper_id": paper_id,
        "source": source,
        "review_material": material,
        "reviewer": "independent source reviewer",
        "decision": "eligible_for_drafting",
        "assessment": "Every selected fact and locator supports a closed pair.",
        "selected_cluster": {
            "mechanism_ids": ["response_mechanism"],
            "branch_a_claim_ids": ["branch_a_claim"],
            "branch_b_claim_ids": ["branch_b_claim"],
            "public_control_names": ["input_x"],
            "public_readout_names": ["response_y"],
            "common_fixed_condition_ids": ["common_apparatus"],
            "branch_a_fixed_condition_ids": ["regime_a"],
            "branch_b_fixed_condition_ids": ["regime_b"],
        },
        "issues": [],
    }


def _card_revision_review_payload(
    paper_id: str,
    citation: str,
    doi: str,
    arxiv_id: str,
    *,
    review_material=None,
):
    payload = _review_payload(
        paper_id,
        citation,
        doi,
        arxiv_id,
        eligible=False,
        review_material=review_material,
    )
    payload["decision"] = "card_revision_required"
    payload["assessment"] = (
        "The paper may support the target, but the current ScienceCard omits "
        "source-backed information required to decide."
    )
    payload["issues"] = [
        {
            "code": "card.missing_source_backed_domain",
            "detail": "Revise the card before deciding paper eligibility.",
            "line_ranges": [{"line_start": 1, "line_end": 2}],
        }
    ]
    return payload


def _paper(index: int, *, venue: str = "Physical Review Letters"):
    return {
        "paper_id": "paper_%d" % index,
        "title": "Paper %d" % index,
        "source_citation": "A. Author, Paper %d, PRL (2026)" % index,
        "journal_doi": "10.0000/paper%d" % index,
        "arxiv_versioned_id": "2607.%05dv1" % index,
        "tex_path": "paper_%d.tex" % index,
        "venue": venue,
        "publication_date": "2026-07-10",
        "earliest_public_date": "2026-07-01",
        "article_type": "journal-article",
        "citation_count": 0,
        "latex_available": True,
        "withdrawn_or_retracted": False,
    }


def _family_review_payload(
    paper, family, *, accepted=True, review_material=None
):
    issues = []
    decision = "source_closed"
    if not accepted:
        decision = "source_closure_rejected"
        issues = [
            {
                "code": "family.player_fact_not_closed",
                "detail": "A Player-visible fact is not supported by the selected card.",
                "line_ranges": [{"line_start": 1, "line_end": 2}],
            }
        ]
    return {
        "paper_id": paper["paper_id"],
        "family": family,
        "source": {
            "citation": paper["source_citation"],
            "journal_doi": paper["journal_doi"],
            "arxiv_versioned_id": paper["arxiv_versioned_id"],
        },
        "review_material": copy.deepcopy(
            review_material
            if review_material is not None
            else {"test_fixture": family}
        ),
        "reviewer": "independent family source reviewer",
        "decision": decision,
        "assessment": "The final family was checked against the reviewed card.",
        "issues": issues,
    }


def _cohort(papers):
    ready = 1 <= len(papers) <= MAX_COORDINATOR_COHORT_SIZE
    return {
        "provenance": {
            "acquisition_schema": ACQUISITION_SCHEMA,
            "coordinator_ready": ready,
            "handoff_status": (
                "coordinator_ready"
                if ready
                else "empty_cohort"
                if not papers
                else "cohort_exceeds_coordinator_limit"
            ),
            "retrieved_at": "2026-08-01T00:00:00+00:00",
            "selected_count": len(papers),
            "selection_policy": "all",
        },
        "window": {
            "start": "2026-07-01",
            "end": "2026-07-31",
            "earliest_public_not_before": None,
        },
        "papers": papers,
    }


def _acquisition(cohort):
    results = []
    for paper in cohort["papers"]:
        results.append(
            {
                "cohort_entry": paper,
                "disposition": "source_acquired",
                "publisher_reconciliation": {
                    "verification_status": "publisher_reconciled"
                },
                "selection": {
                    "policy": "all",
                    "rank": None,
                    "selected": True,
                    "status": "selected",
                },
                "source": {
                    "publisher_verification_status": "publisher_reconciled"
                },
            }
        )
    return {
        "cohort": cohort,
        "paper_results": results,
        "retrieved_at": cohort["provenance"]["retrieved_at"],
        "schema": ACQUISITION_SCHEMA,
        "selection": {"cohort_limit": None, "policy": "all"},
        "selection_counts": {
            "ineligible": 0,
            "not_selected": 0,
            "selected": len(results),
        },
        "warmup_handoff": cohort["provenance"],
    }


class _QueuedBackend:
    def __init__(self, card_payloads):
        self.card_payloads = list(card_payloads)
        self.requests = []

    def generate(self, request):
        self.requests.append(request)
        if request.metadata["purpose"] != "temporal_science_card":
            raise AssertionError("unexpected model stage")
        return GenerationResponse(
            text=json.dumps(self.card_payloads.pop(0)),
            provider="fake",
            model="fake-card-extractor",
            finish_reason="stop",
        )


class _TransportFailingBackend:
    def __init__(self):
        self.requests = []

    def generate(self, request):
        self.requests.append(request)
        raise RuntimeError("provider connection failed")


class _StageBackend:
    def __init__(self, card_payload):
        self.card_payload = card_payload
        self.requests = []

    def generate(self, request):
        self.requests.append(request)
        purpose = request.metadata["purpose"]
        if purpose == "temporal_science_card":
            text = json.dumps(self.card_payload)
        elif purpose == "temporal_case_draft":
            text = "{}"
        else:
            raise AssertionError("unexpected model stage")
        return GenerationResponse(
            text=text,
            provider="fake",
            model="fake-stage-model",
            finish_reason="stop",
        )


def _draft_recording_request():
    return GenerationRequest(
        messages=(Message(role="user", content="record this draft attempt"),),
        response_schema={},
        config=GenerationConfig(max_output_tokens=32),
        metadata={"purpose": "temporal_case_draft"},
    )


def _args(cohort: Path, output: Path, reviews: Path):
    cohort_payload = json.loads(cohort.read_text(encoding="utf-8"))
    cohort.with_name("acquisition.json").write_text(
        json.dumps(_acquisition(cohort_payload)), encoding="utf-8"
    )
    return SimpleNamespace(
        cohort=str(cohort),
        output_directory=str(output),
        reviews_directory=str(reviews),
        endpoint="https://api.example.invalid/chat/completions",
        model="fake",
        timeout_s=10.0,
        max_output_tokens=32768,
        api_key="runtime-only-test-secret",
        api_key_stdin=False,
        prompt_api_key=False,
        api_key_env="UNUSED_API_KEY",
        defer_card_revision=[],
        retry_draft=[],
        skip_provider_failure=[],
        science_card_focus=None,
        science_card_review_guidance=None,
        target_accepted=1,
    )


class TemporalWarmupContractTests(unittest.TestCase):
    def test_large_frozen_acquisition_resume_comparison_is_exact(self):
        acquisition = {
            "schema": ACQUISITION_SCHEMA,
            "census": {
                "papers": [
                    {
                        "doi": "10.0000/paper_%04d" % index,
                        "journal": {
                            "citation_count": index,
                            "published": "2026-04-01",
                            "title": "Paper %04d" % index,
                        },
                        "selection": {
                            "policy": "fixed_window",
                            "reasons": [
                                "criterion_%02d" % reason for reason in range(40)
                            ],
                            "status": "ineligible",
                        },
                    }
                    for index in range(2400)
                ]
            },
        }
        pending = [acquisition]
        node_count = 0
        while pending:
            value = pending.pop()
            node_count += 1
            if isinstance(value, dict):
                pending.extend(value.values())
            elif isinstance(value, list):
                pending.extend(value)
        self.assertGreater(node_count, 100_000)

        # A JSON round trip changes object construction order but not structure.
        frozen = json.loads(json.dumps(acquisition, sort_keys=True))
        self.assertTrue(_same_json(frozen, acquisition))

        mutated = copy.deepcopy(acquisition)
        mutated["census"]["papers"][1999]["journal"]["citation_count"] = -1
        self.assertFalse(_same_json(frozen, mutated))

        for left, right in (
            (True, 1),
            (1, 1.0),
            (None, "null"),
            ({"value": 0.0}, {"value": -0.0}),
        ):
            with self.subTest(left=left, right=right):
                self.assertFalse(_same_json(left, right))

    def test_cohort_is_ordered_and_limited_to_sixty_papers(self):
        parsed = parse_warmup_cohort_payload(
            _cohort([_paper(2), _paper(1)]), base_directory="/fixed"
        )
        self.assertEqual([item.paper_id for item in parsed.papers], ["paper_2", "paper_1"])
        self.assertEqual(parsed.papers[0].tex_path, Path("/fixed/paper_2.tex"))
        maximum = parse_warmup_cohort_payload(
            _cohort(
                [
                    _paper(index)
                    for index in range(1, MAX_COORDINATOR_COHORT_SIZE + 1)
                ]
            ),
            base_directory="/fixed",
        )
        self.assertEqual(len(maximum.papers), MAX_COORDINATOR_COHORT_SIZE)
        with self.assertRaises(WarmupContractError):
            parse_warmup_cohort_payload(
                _cohort(
                    [
                        _paper(index)
                        for index in range(
                            1, MAX_COORDINATOR_COHORT_SIZE + 2
                        )
                    ]
                ),
                base_directory="/fixed",
            )

    def test_only_independent_review_can_open_the_draft_gate(self):
        citation = "A. Author, Paper, PRL (2026)"
        card = parse_science_card_payload(
            _card_payload(citation, "10.0000/paper", "2607.00001v1", ready=False)
        )
        approved = parse_source_review_payload(
            _review_payload(
                "paper_1",
                citation,
                "10.0000/paper",
                "2607.00001v1",
                eligible=True,
            )
        )
        result = assess_paper_eligibility(card, approved, paper_id="paper_1")
        self.assertTrue(result.eligible_for_drafting)
        self.assertTrue(result.reviewed_card.case_authoring_ready)

        self_reported_ready = parse_science_card_payload(
            _card_payload(citation, "10.0000/paper", "2607.00001v1", ready=True)
        )
        rejected = parse_source_review_payload(
            _review_payload(
                "paper_1",
                citation,
                "10.0000/paper",
                "2607.00001v1",
                eligible=False,
                review_material=_card_payload(
                    citation,
                    "10.0000/paper",
                    "2607.00001v1",
                    ready=True,
                ),
            )
        )
        result = assess_paper_eligibility(
            self_reported_ready, rejected, paper_id="paper_1"
        )
        self.assertFalse(result.eligible_for_drafting)
        request = review_request_payload(self_reported_ready, paper_id="paper_1")
        self.assertEqual(request["decision"], "ineligible_for_bench")
        self.assertIn("new output directory", request["issues"][0]["detail"])

    def test_eligible_review_cannot_promote_a_legacy_opaque_card(self):
        citation = "A. Author, Paper, PRL (2026)"
        payload = _card_payload(
            citation, "10.0000/paper", "2607.00001v1", ready=False
        )
        for claim in payload["claims"]:
            del claim["oracle_outputs"]
        card = parse_science_card_payload(payload)
        review = parse_source_review_payload(
            _review_payload(
                "paper_1",
                citation,
                "10.0000/paper",
                "2607.00001v1",
                eligible=True,
                review_material=payload,
            )
        )
        with self.assertRaises(WarmupContractError) as raised:
            assess_paper_eligibility(card, review, paper_id="paper_1")
        self.assertEqual(raised.exception.code, "warmup.review_scope")
        self.assertIn("use card_revision_required", raised.exception.detail)

    def test_card_revision_required_is_a_distinct_non_drafting_disposition(self):
        citation = "A. Author, Paper, PRL (2026)"
        doi = "10.0000/paper"
        arxiv_id = "2607.00001v1"
        card_payload = _card_payload(citation, doi, arxiv_id, ready=True)
        card = parse_science_card_payload(card_payload)
        revision_payload = _card_revision_review_payload(
            "paper_1",
            citation,
            doi,
            arxiv_id,
            review_material=card_payload,
        )

        review = parse_source_review_payload(revision_payload)
        result = assess_paper_eligibility(card, review, paper_id="paper_1")
        self.assertFalse(result.eligible_for_drafting)
        self.assertEqual(result.primary_disposition, "card_revision_required")
        self.assertIsNone(result.selected_cluster)
        self.assertIsNone(result.reviewed_card)
        self.assertEqual(result.issues[0].code, "card.missing_source_backed_domain")

        empty_issues = copy.deepcopy(revision_payload)
        empty_issues["issues"] = []
        with self.assertRaises(WarmupContractError):
            parse_source_review_payload(empty_issues)

        selected_cluster = copy.deepcopy(revision_payload)
        selected_cluster["selected_cluster"] = _review_payload(
            "paper_1", citation, doi, arxiv_id, eligible=True
        )["selected_cluster"]
        with self.assertRaises(WarmupContractError):
            parse_source_review_payload(selected_cluster)

    def test_source_review_binds_exact_json_types_and_card_content(self):
        citation = "A. Author, Paper, PRL (2026)"
        payload = _card_payload(
            citation, "10.0000/paper", "2607.00001v1", ready=False
        )
        card = parse_science_card_payload(payload)
        review_payload = _review_payload(
            "paper_1",
            citation,
            "10.0000/paper",
            "2607.00001v1",
            eligible=True,
            review_material=payload,
        )
        review_payload["review_material"]["case_authoring_ready"] = 0
        review = parse_source_review_payload(review_payload)
        with self.assertRaises(WarmupContractError) as caught:
            assess_paper_eligibility(card, review, paper_id="paper_1")
        self.assertEqual(caught.exception.code, "warmup.review_material")

    def test_resource_shape_and_source_ambiguity_fail_closed(self):
        citation = "A. Author, Paper, PRL (2026)"
        doi = "10.0000/paper"
        arxiv_id = "2607.00001v1"
        base = _card_payload(citation, doi, arxiv_id)
        review_payload = _review_payload(
            "paper_1", citation, doi, arxiv_id, eligible=True
        )

        too_many = copy.deepcopy(base)
        for index in range(2, 7):
            name = "input_%d" % index
            too_many["controls"].append(
                {
                    "name": name,
                    "definition": "An additional manipulated input.",
                    "unit": "a.u.",
                    "minimum": 1.0,
                    "maximum": 5.0,
                    "anchors": [_anchor("The input domain is reported.")],
                }
            )
            for claim in too_many["claims"]:
                claim["control_names"].append(name)
                claim["control_domains"].append(
                    {
                        "control_name": name,
                        "minimum": 1.0,
                        "maximum": 5.0,
                        "anchors": [_anchor("The claim uses the reported input domain.")],
                    }
                )
            review_payload["selected_cluster"]["public_control_names"].append(name)
        review_payload["review_material"] = copy.deepcopy(too_many)
        result = assess_paper_eligibility(
            parse_science_card_payload(too_many),
            parse_source_review_payload(review_payload),
            paper_id="paper_1",
        )
        self.assertFalse(result.eligible_for_drafting)
        self.assertEqual(result.primary_disposition, "bench_resource_shape_out_of_scope")

        ambiguous = copy.deepcopy(base)
        ambiguous["source_ambiguities"] = [
            {
                "ambiguity_id": "branch_definition_conflict",
                "statement": "Two source sections define the selected response differently.",
                "claim_ids": ["branch_a_claim"],
                "mechanism_ids": ["response_mechanism"],
                "control_names": ["input_x"],
                "readout_names": ["response_y"],
                "fixed_condition_ids": ["common_apparatus", "regime_a"],
                "anchors": [_anchor("The conflicting definitions occur here.")],
            }
        ]
        clean_review = parse_source_review_payload(
            _review_payload(
                "paper_1",
                citation,
                doi,
                arxiv_id,
                eligible=True,
                review_material=ambiguous,
            )
        )
        result = assess_paper_eligibility(
            parse_science_card_payload(ambiguous),
            clean_review,
            paper_id="paper_1",
        )
        self.assertFalse(result.eligible_for_drafting)
        self.assertEqual(result.primary_disposition, "unresolved_source_ambiguity")

    def test_ambiguity_linked_only_to_unselected_resources_does_not_block(self):
        citation = "A. Author, Paper, PRL (2026)"
        doi = "10.0000/paper"
        arxiv_id = "2607.00001v1"
        payload = _card_payload(citation, doi, arxiv_id)
        payload["mechanisms"].append(
            {
                "mechanism_id": "unselected_mechanism",
                "statement": "An unrelated source section reports another mechanism.",
                "equations": ["u=c*v"],
                "variable_names": ["u", "v"],
                "parameters": [],
                "anchors": [_anchor("The unrelated mechanism is reported.")],
            }
        )
        payload["source_ambiguities"] = [
            {
                "ambiguity_id": "unselected_definition_conflict",
                "statement": "The unrelated mechanism has an unresolved definition.",
                "claim_ids": [],
                "mechanism_ids": ["unselected_mechanism"],
                "control_names": [],
                "readout_names": [],
                "fixed_condition_ids": [],
                "anchors": [_anchor("The unrelated definition is ambiguous.")],
            }
        ]
        review = parse_source_review_payload(
            _review_payload(
                "paper_1",
                citation,
                doi,
                arxiv_id,
                eligible=True,
                review_material=payload,
            )
        )
        result = assess_paper_eligibility(
            parse_science_card_payload(payload), review, paper_id="paper_1"
        )
        self.assertTrue(result.eligible_for_drafting)
        self.assertEqual(result.reviewed_card.source_ambiguities, ())

    def test_selected_resource_and_global_ambiguities_still_block(self):
        citation = "A. Author, Paper, PRL (2026)"
        doi = "10.0000/paper"
        arxiv_id = "2607.00001v1"
        for linkage in (
            {"control_names": ["input_x"]},
            {},
        ):
            with self.subTest(linkage=linkage):
                payload = _card_payload(citation, doi, arxiv_id)
                ambiguity = {
                    "ambiguity_id": "selected_or_global_conflict",
                    "statement": "The selected experiment has an unresolved ambiguity.",
                    "claim_ids": [],
                    "mechanism_ids": [],
                    "control_names": [],
                    "readout_names": [],
                    "fixed_condition_ids": [],
                    "anchors": [_anchor("The unresolved issue is reported here.")],
                }
                ambiguity.update(linkage)
                payload["source_ambiguities"] = [ambiguity]
                review = parse_source_review_payload(
                    _review_payload(
                        "paper_1",
                        citation,
                        doi,
                        arxiv_id,
                        eligible=True,
                        review_material=payload,
                    )
                )
                result = assess_paper_eligibility(
                    parse_science_card_payload(payload),
                    review,
                    paper_id="paper_1",
                )
                self.assertFalse(result.eligible_for_drafting)
                self.assertEqual(
                    result.primary_disposition, "unresolved_source_ambiguity"
                )


class TemporalWarmupCoordinatorTests(unittest.TestCase):
    def test_coordinator_prefers_source_packet_and_marks_the_model_request(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            paper = _paper(1)
            paper["source_packet_path"] = "paper_1.source_packet.txt"
            packet = (
                "===== BEGIN FILE: main.tex =====\n"
                "The source reports a controlled response.\n"
                "===== END FILE: main.tex =====\n\n"
                "===== BEGIN FILE: data/points.csv =====\n"
                "input,response\n1,2\n"
                "===== END FILE: data/points.csv =====\n"
            )
            (root / paper["source_packet_path"]).write_text(
                packet, encoding="utf-8"
            )
            cohort = root / "cohort.json"
            cohort.write_text(json.dumps(_cohort([paper])), encoding="utf-8")
            output = root / "output"
            backend = _QueuedBackend(
                [
                    _card_payload(
                        paper["source_citation"],
                        paper["journal_doi"],
                        paper["arxiv_versioned_id"],
                    )
                ]
            )

            with contextlib.redirect_stdout(io.StringIO()):
                status = run(
                    _args(cohort, output, root / "reviews"), backend=backend
                )

            self.assertEqual(status, 3)
            self.assertEqual(backend.requests[0].metadata["source_format"], "source_packet")
            self.assertIn(
                "data/points.csv",
                backend.requests[0].messages[1].content,
            )
            self.assertEqual(
                (output / "frozen_sources" / "01_paper_1.txt").read_text(
                    encoding="utf-8"
                ),
                packet,
            )
            self.assertTrue(
                (output / "papers" / "01_paper_1" / "normalized_source.txt").is_file()
            )

    def test_preseeded_case_accepted_status_cannot_skip_the_review_chain(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            paper = _paper(1)
            (root / paper["tex_path"]).write_text(
                "\\documentclass{article}\n\\begin{document}source\\end{document}\n",
                encoding="utf-8",
            )
            cohort = root / "cohort.json"
            cohort.write_text(json.dumps(_cohort([paper])), encoding="utf-8")
            output = root / "output"
            paper_output = output / "papers" / "01_paper_1"
            paper_output.mkdir(parents=True)
            (paper_output / "result.json").write_text(
                json.dumps(
                    {
                        "paper_id": "paper_1",
                        "status": "case_accepted",
                        "accepted_case": {
                            "family": "unreviewed_family",
                            "paper_id": "paper_1",
                            "path": str(root / "does_not_exist.py"),
                        },
                    }
                ),
                encoding="utf-8",
            )
            backend = _QueuedBackend(
                [
                    _card_payload(
                        paper["source_citation"],
                        paper["journal_doi"],
                        paper["arxiv_versioned_id"],
                    )
                ]
            )

            with contextlib.redirect_stdout(io.StringIO()):
                status = run(
                    _args(cohort, output, root / "reviews"), backend=backend
                )

            self.assertEqual(status, 3)
            self.assertEqual(len(backend.requests), 1)
            self.assertEqual(
                _read(paper_output / "result.json")["status"],
                "awaiting_source_review",
            )

    def test_rejects_missing_or_misaligned_acquisition_provenance(self):
        for mode in ("missing", "misaligned"):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                paper = _paper(1)
                (root / paper["tex_path"]).write_text(
                    "\\documentclass{article}\n", encoding="utf-8"
                )
                cohort = root / "cohort.json"
                cohort.write_text(json.dumps(_cohort([paper])), encoding="utf-8")
                output = root / "output"
                args = _args(cohort, output, root / "reviews")
                acquisition_path = root / "acquisition.json"
                if mode == "missing":
                    acquisition_path.unlink()
                else:
                    acquisition = _read(acquisition_path)
                    acquisition["cohort"]["papers"][0]["title"] = "Different paper"
                    acquisition_path.write_text(
                        json.dumps(acquisition), encoding="utf-8"
                    )
                backend = _QueuedBackend([])
                with contextlib.redirect_stdout(io.StringIO()):
                    status = run(args, backend=backend)

                self.assertEqual(status, 2)
                self.assertEqual(backend.requests, [])
                failure = _read(output / "failure.json")
                self.assertEqual(failure["stage"], "cohort")

    def test_exhausted_cohort_is_a_non_success_automation_status(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            paper = _paper(1, venue="Not a target venue")
            (root / paper["tex_path"]).write_text(
                "\\documentclass{article}\n", encoding="utf-8"
            )
            cohort = root / "cohort.json"
            cohort.write_text(json.dumps(_cohort([paper])), encoding="utf-8")
            output = root / "output"
            backend = _QueuedBackend([])

            args = _args(cohort, output, root / "reviews")
            args.target_accepted = 2
            with contextlib.redirect_stdout(io.StringIO()):
                status = run(args, backend=backend)

            self.assertEqual(status, 5)
            self.assertEqual(backend.requests, [])
            report = _read(output / "result.json")
            self.assertEqual(report["status"], "exhausted")
            self.assertEqual(report["accepted_cases"], [])
            self.assertEqual(report["accepted_count"], 0)
            self.assertEqual(report["target_accepted"], 2)
            self.assertFalse(report["target_reached"])

    def test_target_accepted_must_be_a_positive_integer(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            paper = _paper(1, venue="Not a target venue")
            (root / paper["tex_path"]).write_text("source\n", encoding="utf-8")
            cohort = root / "cohort.json"
            cohort.write_text(json.dumps(_cohort([paper])), encoding="utf-8")
            output = root / "output"
            args = _args(cohort, output, root / "reviews")
            args.target_accepted = 0

            with contextlib.redirect_stdout(io.StringIO()):
                status = run(args, backend=_QueuedBackend([]))

            self.assertEqual(status, 2)
            self.assertIn(
                "positive integer", _read(output / "failure.json")["error"]
            )

    def test_transport_failure_stops_run_and_replaces_stale_status(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            papers = [_paper(1), _paper(2)]
            for paper in papers:
                (root / paper["tex_path"]).write_text(
                    "\\documentclass{article}\n\\begin{document}source\\end{document}\n",
                    encoding="utf-8",
                )
            cohort = root / "cohort.json"
            cohort.write_text(json.dumps(_cohort(papers)), encoding="utf-8")
            output = root / "output"
            backend = _TransportFailingBackend()

            with contextlib.redirect_stdout(io.StringIO()):
                status = run(
                    _args(cohort, output, root / "reviews"), backend=backend
                )

            self.assertEqual(status, 2)
            self.assertEqual(len(backend.requests), 1)
            report = _read(output / "result.json")
            self.assertEqual(report["status"], "provider_failed")
            self.assertEqual(report["processed_count"], 1)
            self.assertEqual(report["paper_results"][0]["status"], "provider_failed")
            self.assertEqual(report["awaiting_disposition_for"], "paper_1")
            self.assertEqual(report["failure"]["stage"], "science_card")
            self.assertEqual(
                report["failure"]["disposition_required"], "skip_or_new_run"
            )
            self.assertFalse((output / "papers" / "02_paper_2").exists())

            with contextlib.redirect_stdout(io.StringIO()):
                resumed = run(
                    _args(cohort, output, root / "reviews"), backend=backend
                )
            self.assertEqual(resumed, 4)
            self.assertEqual(len(backend.requests), 1)
            self.assertEqual(
                _read(output / "result.json")["status"],
                "awaiting_provider_failure_disposition",
            )
            self.assertEqual(
                _read(output / "result.json")["awaiting_disposition_for"],
                "paper_1",
            )
            self.assertIsNone(
                _read(output / "result.json")["awaiting_review_for"]
            )

            disposition_args = _args(cohort, output, root / "reviews")
            disposition_args.skip_provider_failure = ["paper_1"]
            with contextlib.redirect_stdout(io.StringIO()):
                skipped = run(disposition_args, backend=backend)
            self.assertEqual(skipped, 2)
            self.assertEqual(len(backend.requests), 2)
            self.assertEqual(
                _read(output / "papers" / "01_paper_1" / "result.json")["status"],
                "provider_failure_skipped",
            )

            with contextlib.redirect_stdout(io.StringIO()):
                idempotent = run(disposition_args, backend=backend)
            self.assertEqual(idempotent, 4)
            self.assertEqual(len(backend.requests), 2)

    def test_pauses_after_card_when_independent_review_is_missing(self):
        self.assertEqual(DEFAULT_MODEL, "deepseek-v4-flash")
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            paper = _paper(1)
            (root / paper["tex_path"]).write_text(
                "\\documentclass{article}\n\\begin{document}source\\end{document}\n",
                encoding="utf-8",
            )
            cohort = root / "cohort.json"
            cohort.write_text(json.dumps(_cohort([paper])), encoding="utf-8")
            reviews = root / "reviews"
            output = root / "output"
            backend = _QueuedBackend(
                [
                    _card_payload(
                        paper["source_citation"],
                        paper["journal_doi"],
                        paper["arxiv_versioned_id"],
                    )
                ]
            )
            with contextlib.redirect_stdout(io.StringIO()):
                status = run(_args(cohort, output, reviews), backend=backend)

            self.assertEqual(status, 3)
            self.assertEqual(len(backend.requests), 1)
            self.assertEqual(_read(output / "result.json")["status"], "awaiting_source_review")
            self.assertEqual(
                len(list((output / "frozen_sources").glob("*.tex"))), 1
            )
            config = _read(output / "config.json")
            self.assertEqual(config["provider"]["model"], "fake")
            self.assertNotIn("runtime-only-test-secret", json.dumps(config))
            paper_dir = output / "papers" / "01_paper_1"
            self.assertTrue((paper_dir / "review_request.json").is_file())
            self.assertFalse((paper_dir / "case_draft").exists())

            frozen_path = output / "frozen_sources" / "01_paper_1.tex"
            frozen_text = frozen_path.read_text(encoding="utf-8")
            (root / paper["tex_path"]).write_text(
                "\\documentclass{article}\n\\begin{document}changed\\end{document}\n",
                encoding="utf-8",
            )
            with contextlib.redirect_stdout(io.StringIO()):
                resumed = run(_args(cohort, output, reviews), backend=backend)
            self.assertEqual(resumed, 3)
            self.assertEqual(len(backend.requests), 1)
            self.assertEqual(
                frozen_path.read_text(encoding="utf-8"), frozen_text
            )

            changed_config = _args(cohort, output, reviews)
            changed_config.model = "different-model"
            with contextlib.redirect_stdout(io.StringIO()):
                rejected = run(changed_config, backend=backend)
            self.assertEqual(rejected, 2)
            self.assertEqual(len(backend.requests), 1)
            self.assertIn(
                "different runtime config",
                _read(output / "failure.json")["error"],
            )

    def test_card_revision_required_stops_and_replays_without_provider_calls(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            papers = [_paper(1), _paper(2)]
            for paper in papers:
                (root / paper["tex_path"]).write_text(
                    "\\documentclass{article}\n\\begin{document}source\\end{document}\n",
                    encoding="utf-8",
                )
            cohort = root / "cohort.json"
            cohort.write_text(json.dumps(_cohort(papers)), encoding="utf-8")
            reviews = root / "reviews"
            output = root / "output"
            backend = _QueuedBackend(
                [
                    _card_payload(
                        papers[0]["source_citation"],
                        papers[0]["journal_doi"],
                        papers[0]["arxiv_versioned_id"],
                    ),
                    _card_payload(
                        papers[1]["source_citation"],
                        papers[1]["journal_doi"],
                        papers[1]["arxiv_versioned_id"],
                    ),
                ]
            )

            with contextlib.redirect_stdout(io.StringIO()):
                initial = run(_args(cohort, output, reviews), backend=backend)
            self.assertEqual(initial, 3)
            self.assertEqual(len(backend.requests), 1)

            paper_dir = output / "papers" / "01_paper_1"
            review = _read(paper_dir / "review_request.json")
            review.update(
                {
                    "reviewer": "independent source reviewer",
                    "decision": "card_revision_required",
                    "assessment": (
                        "The paper may remain usable, but this frozen ScienceCard "
                        "must be revised before eligibility can be decided."
                    ),
                    "selected_cluster": None,
                    "issues": [
                        {
                            "code": "card.missing_source_backed_domain",
                            "detail": "Add the omitted source-backed domain.",
                            "line_ranges": [
                                {"line_start": 1, "line_end": 2}
                            ],
                        }
                    ],
                }
            )
            (reviews / "paper_1.json").write_text(
                json.dumps(review), encoding="utf-8"
            )

            with contextlib.redirect_stdout(io.StringIO()):
                resumed = run(_args(cohort, output, reviews), backend=backend)
            self.assertEqual(resumed, 6)
            self.assertEqual(len(backend.requests), 1)
            report = _read(output / "result.json")
            self.assertEqual(report["status"], "card_revision_required")
            self.assertEqual(report["processed_count"], 1)
            self.assertEqual(
                report["paper_results"][0]["status"],
                "card_revision_required",
            )
            eligibility = report["paper_results"][0]["eligibility"]
            self.assertFalse(eligibility["eligible_for_drafting"])
            self.assertEqual(
                eligibility["primary_disposition"], "card_revision_required"
            )
            self.assertEqual(
                eligibility["issues"][0]["code"],
                "card.missing_source_backed_domain",
            )
            self.assertFalse((paper_dir / "case_draft").exists())
            self.assertFalse((output / "papers" / "02_paper_2").exists())

            with contextlib.redirect_stdout(io.StringIO()):
                replayed = run(_args(cohort, output, reviews), backend=backend)
            self.assertEqual(replayed, 6)
            self.assertEqual(len(backend.requests), 1)
            self.assertEqual(
                _read(output / "result.json")["status"],
                "card_revision_required",
            )

            frozen_config = (output / "config.json").read_text(encoding="utf-8")
            disposition_args = _args(cohort, output, reviews)
            disposition_args.defer_card_revision = ["paper_1"]
            with contextlib.redirect_stdout(io.StringIO()):
                continued = run(disposition_args, backend=backend)
            self.assertEqual(continued, 3)
            self.assertEqual(len(backend.requests), 2)
            self.assertEqual(
                (output / "config.json").read_text(encoding="utf-8"),
                frozen_config,
            )
            deferred = _read(paper_dir / "result.json")
            self.assertEqual(deferred["status"], "card_revision_deferred")
            self.assertEqual(
                deferred["disposition"], "explicit_separate_revision"
            )
            self.assertEqual(
                deferred["revision_review"]["decision"],
                "card_revision_required",
            )
            self.assertEqual(
                deferred["revision_review"]["issues"][0]["code"],
                "card.missing_source_backed_domain",
            )
            self.assertEqual(
                Path(deferred["revision_review"]["path"]),
                paper_dir / "source_review.json",
            )
            self.assertEqual(
                _read(output / "result.json")["status"],
                "awaiting_source_review",
            )
            self.assertTrue((output / "papers" / "02_paper_2").is_dir())

            with contextlib.redirect_stdout(io.StringIO()):
                idempotent = run(disposition_args, backend=backend)
            self.assertEqual(idempotent, 3)
            self.assertEqual(len(backend.requests), 2)
            self.assertEqual(
                _read(paper_dir / "result.json")["status"],
                "card_revision_deferred",
            )

    def test_card_revision_defer_rejects_unknown_or_unreviewed_paper(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            paper = _paper(1)
            (root / paper["tex_path"]).write_text(
                "\\documentclass{article}\n\\begin{document}source\\end{document}\n",
                encoding="utf-8",
            )
            cohort = root / "cohort.json"
            cohort.write_text(json.dumps(_cohort([paper])), encoding="utf-8")

            no_verdict_args = _args(
                cohort, root / "no_verdict", root / "reviews_no_verdict"
            )
            no_verdict_args.defer_card_revision = ["paper_1"]
            with contextlib.redirect_stdout(io.StringIO()):
                no_verdict = run(no_verdict_args, backend=_QueuedBackend([]))
            self.assertEqual(no_verdict, 2)
            self.assertIn(
                "requires an existing card_revision_required verdict",
                _read(root / "no_verdict" / "failure.json")["error"],
            )

            unknown_args = _args(
                cohort, root / "unknown", root / "reviews_unknown"
            )
            unknown_args.defer_card_revision = ["missing_paper"]
            with contextlib.redirect_stdout(io.StringIO()):
                unknown = run(unknown_args, backend=_QueuedBackend([]))
            self.assertEqual(unknown, 2)
            self.assertIn(
                "names unknown paper(s): missing_paper",
                _read(root / "unknown" / "failure.json")["error"],
            )

    def test_single_paper_focus_is_recorded_in_request_and_config(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            paper = _paper(1)
            (root / paper["tex_path"]).write_text(
                "\\documentclass{article}\n\\begin{document}source\\end{document}\n",
                encoding="utf-8",
            )
            cohort = root / "cohort.json"
            cohort.write_text(json.dumps(_cohort([paper])), encoding="utf-8")
            output = root / "output"
            args = _args(cohort, output, root / "reviews")
            args.science_card_focus = "Inspect the source-reported branch pair."
            backend = _QueuedBackend(
                [
                    _card_payload(
                        paper["source_citation"],
                        paper["journal_doi"],
                        paper["arxiv_versioned_id"],
                    )
                ]
            )

            with contextlib.redirect_stdout(io.StringIO()):
                status = run(args, backend=backend)

            self.assertEqual(status, 3)
            self.assertIn(
                "Inspect the source-reported branch pair.",
                backend.requests[0].messages[1].content,
            )
            self.assertEqual(
                _read(output / "config.json")["science_card_focus"],
                "Inspect the source-reported branch pair.",
            )

    def test_focus_rejects_multi_paper_cohort_before_provider_call(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            papers = [_paper(1), _paper(2)]
            for paper in papers:
                (root / paper["tex_path"]).write_text(
                    "\\documentclass{article}\n",
                    encoding="utf-8",
                )
            cohort = root / "cohort.json"
            cohort.write_text(json.dumps(_cohort(papers)), encoding="utf-8")
            output = root / "output"
            args = _args(cohort, output, root / "reviews")
            args.science_card_focus = "A paper-specific source section."
            backend = _QueuedBackend([])

            with contextlib.redirect_stdout(io.StringIO()):
                status = run(args, backend=backend)

            self.assertEqual(status, 2)
            self.assertEqual(backend.requests, [])
            self.assertIn("single-paper cohort", _read(output / "failure.json")["error"])

    def test_card_revision_guidance_is_validated_frozen_and_requires_new_review(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            paper = _paper(1)
            (root / paper["tex_path"]).write_text(
                "\\documentclass{article}\n\\begin{document}source\\end{document}\n",
                encoding="utf-8",
            )
            cohort = root / "cohort.json"
            cohort.write_text(json.dumps(_cohort([paper])), encoding="utf-8")
            prior_review = _card_revision_review_payload(
                paper["paper_id"],
                paper["source_citation"],
                paper["journal_doi"],
                paper["arxiv_versioned_id"],
                review_material=_card_payload(
                    paper["source_citation"],
                    paper["journal_doi"],
                    paper["arxiv_versioned_id"],
                ),
            )
            prior_path = (
                root
                / "prior_output"
                / "papers"
                / "01_paper_1"
                / "source_review.json"
            )
            prior_path.parent.mkdir(parents=True)
            prior_path.write_text(json.dumps(prior_review), encoding="utf-8")

            output = root / "new_output"
            args = _args(cohort, output, root / "new_reviews")
            args.science_card_focus = "Inspect the source-reported branch pair."
            args.science_card_review_guidance = str(prior_path)
            backend = _QueuedBackend(
                [
                    _card_payload(
                        paper["source_citation"],
                        paper["journal_doi"],
                        paper["arxiv_versioned_id"],
                    )
                ]
            )

            with contextlib.redirect_stdout(io.StringIO()):
                status = run(args, backend=backend)

            self.assertEqual(status, 3)
            self.assertEqual(len(backend.requests), 1)
            request_text = backend.requests[0].messages[1].content
            self.assertIn("Source-grounded routing hint", request_text)
            self.assertIn("Revision context from an independent review", request_text)
            self.assertIn('"previous_science_card":', request_text)
            self.assertIn("card.missing_source_backed_domain", request_text)
            self.assertIn("editable rejected draft", request_text)
            self.assertIn("Address every listed issue", request_text)
            self.assertIn("supplied source remains the sole authority", request_text)
            self.assertNotIn(prior_review["assessment"], request_text)
            self.assertNotIn(prior_review["reviewer"], request_text)

            frozen = _read(output / "science_card_review_guidance.json")
            self.assertEqual(frozen["decision"], "card_revision_required")
            self.assertEqual(frozen["paper_id"], paper["paper_id"])
            self.assertEqual(frozen["source"], prior_review["source"])
            self.assertEqual(frozen["issues"], prior_review["issues"])
            self.assertEqual(
                frozen["previous_science_card"], prior_review["review_material"]
            )
            self.assertEqual(
                _read(output / "config.json")["science_card_review_guidance"],
                frozen,
            )
            self.assertEqual(
                _read(output / "result.json")["status"],
                "awaiting_source_review",
            )
            self.assertTrue(
                (output / "papers" / "01_paper_1" / "review_request.json").is_file()
            )
            self.assertFalse(
                (output / "papers" / "01_paper_1" / "source_review.json").exists()
            )

    def test_card_revision_guidance_rejects_wrong_identity_or_decision(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            paper = _paper(1)
            (root / paper["tex_path"]).write_text(
                "\\documentclass{article}\n\\begin{document}source\\end{document}\n",
                encoding="utf-8",
            )
            cohort = root / "cohort.json"
            cohort.write_text(json.dumps(_cohort([paper])), encoding="utf-8")
            base_review = _card_revision_review_payload(
                paper["paper_id"],
                paper["source_citation"],
                paper["journal_doi"],
                paper["arxiv_versioned_id"],
                review_material=_card_payload(
                    paper["source_citation"],
                    paper["journal_doi"],
                    paper["arxiv_versioned_id"],
                ),
            )

            for label, mutate, expected in (
                (
                    "identity",
                    lambda payload: payload.update({"paper_id": "different_paper"}),
                    "identify the single cohort paper",
                ),
                (
                    "decision",
                    lambda payload: payload.update(
                        {
                            "decision": "ineligible_for_bench",
                            "assessment": "The current paper is not eligible.",
                        }
                    ),
                    "decision must be card_revision_required",
                ),
            ):
                with self.subTest(label=label):
                    review = copy.deepcopy(base_review)
                    mutate(review)
                    guidance_path = root / (label + ".json")
                    guidance_path.write_text(json.dumps(review), encoding="utf-8")
                    output = root / ("output_" + label)
                    args = _args(cohort, output, root / ("reviews_" + label))
                    args.science_card_review_guidance = str(guidance_path)
                    backend = _QueuedBackend([])
                    with contextlib.redirect_stdout(io.StringIO()):
                        status = run(args, backend=backend)
                    self.assertEqual(status, 2)
                    self.assertEqual(backend.requests, [])
                    self.assertIn(expected, _read(output / "failure.json")["error"])

    def test_card_revision_guidance_rejects_multi_paper_cohort(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            papers = [_paper(1), _paper(2)]
            for paper in papers:
                (root / paper["tex_path"]).write_text(
                    "\\documentclass{article}\n", encoding="utf-8"
                )
            cohort = root / "cohort.json"
            cohort.write_text(json.dumps(_cohort(papers)), encoding="utf-8")
            guidance = root / "guidance.json"
            guidance.write_text("{}", encoding="utf-8")
            output = root / "output"
            args = _args(cohort, output, root / "reviews")
            args.science_card_review_guidance = str(guidance)
            backend = _QueuedBackend([])

            with contextlib.redirect_stdout(io.StringIO()):
                status = run(args, backend=backend)

            self.assertEqual(status, 2)
            self.assertEqual(backend.requests, [])
            self.assertIn("single-paper cohort", _read(output / "failure.json")["error"])

    def test_default_target_continues_negative_papers_and_stops_at_first_case(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            papers = [
                _paper(1, venue="Not a target venue"),
                _paper(2),
                _paper(3),
                _paper(4),
            ]
            for paper in papers:
                (root / paper["tex_path"]).write_text(
                    "\\documentclass{article}\n\\begin{document}source\\end{document}\n",
                    encoding="utf-8",
                )
            cohort = root / "cohort.json"
            cohort.write_text(json.dumps(_cohort(papers)), encoding="utf-8")
            reviews = root / "reviews"
            reviews.mkdir()
            for paper, eligible in ((papers[1], False), (papers[2], True)):
                (reviews / (paper["paper_id"] + ".json")).write_text(
                    json.dumps(
                        _review_payload(
                            paper["paper_id"],
                            paper["source_citation"],
                            paper["journal_doi"],
                            paper["arxiv_versioned_id"],
                            eligible=eligible,
                        )
                    ),
                    encoding="utf-8",
                )
            (reviews / "paper_3.family.json").write_text(
                json.dumps(
                    _family_review_payload(
                        papers[2], "first_accepted_family"
                    )
                ),
                encoding="utf-8",
            )
            backend = _QueuedBackend(
                [
                    _card_payload(
                        paper["source_citation"],
                        paper["journal_doi"],
                        paper["arxiv_versioned_id"],
                    )
                    for paper in papers[1:3]
                ]
            )
            fake_candidate = SimpleNamespace(
                family="first_accepted_family",
                source=SimpleNamespace(
                    citation=papers[2]["source_citation"],
                    journal_doi=papers[2]["journal_doi"],
                    arxiv_versioned_id=papers[2]["arxiv_versioned_id"],
                ),
            )
            fake_batch = SimpleNamespace(
                assessment="A reviewed matched pair was drafted.",
                status="authored",
                drafts=(
                    SimpleNamespace(
                        candidate=fake_candidate,
                        information_boundary=SimpleNamespace(),
                    ),
                ),
            )
            output = root / "output"

            def render(candidate, path):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("accepted\n", encoding="utf-8")
                return path

            with (
                patch(
                    "experiments.run_temporal_warmup.author_case_draft",
                    return_value=SimpleNamespace(batch=fake_batch),
                ) as author,
                patch(
                    "experiments.run_temporal_warmup.case_draft_batch_to_payload",
                    return_value={
                        "assessment": "A reviewed matched pair was drafted.",
                        "status": "authored",
                        "drafts": [],
                    },
                ),
                patch(
                    "experiments.run_temporal_warmup.filter_candidate",
                    return_value=SimpleNamespace(eligible=True, issues=()),
                ),
                patch(
                    "experiments.run_temporal_warmup.family_review_request_payload",
                    return_value={"paper_id": "paper_3"},
                ),
                patch(
                    "experiments.run_temporal_warmup.assess_family_source_closure",
                    return_value=True,
                ),
                patch(
                    "experiments.run_temporal_warmup._persist_rendered_candidate",
                    side_effect=render,
                ) as persist,
                contextlib.redirect_stdout(io.StringIO()),
            ):
                status = run(_args(cohort, output, reviews), backend=backend)

            self.assertEqual(status, 0)
            self.assertEqual(len(backend.requests), 2)
            author.assert_called_once()
            persist.assert_called_once()
            report = _read(output / "result.json")
            self.assertEqual(report["status"], "case_accepted")
            self.assertEqual(report["accepted_case"]["paper_id"], "paper_3")
            self.assertEqual(
                [item["paper_id"] for item in report["accepted_cases"]],
                ["paper_3"],
            )
            self.assertEqual(report["accepted_count"], 1)
            self.assertEqual(report["target_accepted"], 1)
            self.assertTrue(report["target_reached"])
            self.assertFalse((output / "papers" / "04_paper_4").exists())
            self.assertEqual(
                len(list((output / "frozen_sources").glob("*.tex"))), 4
            )

    def test_target_two_accumulates_two_accepted_families_before_stopping(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            papers = [_paper(1), _paper(2), _paper(3)]
            for paper in papers:
                (root / paper["tex_path"]).write_text(
                    "\\documentclass{article}\n"
                    "\\begin{document}source\\end{document}\n",
                    encoding="utf-8",
                )
            cohort = root / "cohort.json"
            cohort.write_text(json.dumps(_cohort(papers)), encoding="utf-8")
            reviews = root / "reviews"
            reviews.mkdir()
            families = ["accepted_family_one", "accepted_family_two"]
            for paper, family in zip(papers[:2], families):
                (reviews / (paper["paper_id"] + ".json")).write_text(
                    json.dumps(
                        _review_payload(
                            paper["paper_id"],
                            paper["source_citation"],
                            paper["journal_doi"],
                            paper["arxiv_versioned_id"],
                            eligible=True,
                        )
                    ),
                    encoding="utf-8",
                )
                (reviews / (paper["paper_id"] + ".family.json")).write_text(
                    json.dumps(_family_review_payload(paper, family)),
                    encoding="utf-8",
                )
            backend = _QueuedBackend(
                [
                    _card_payload(
                        paper["source_citation"],
                        paper["journal_doi"],
                        paper["arxiv_versioned_id"],
                    )
                    for paper in papers[:2]
                ]
            )
            batches = []
            for paper, family in zip(papers[:2], families):
                candidate = SimpleNamespace(
                    family=family,
                    source=SimpleNamespace(
                        citation=paper["source_citation"],
                        journal_doi=paper["journal_doi"],
                        arxiv_versioned_id=paper["arxiv_versioned_id"],
                    ),
                )
                batches.append(
                    SimpleNamespace(
                        assessment="A reviewed matched pair was drafted.",
                        status="authored",
                        drafts=(
                            SimpleNamespace(
                                candidate=candidate,
                                information_boundary=SimpleNamespace(),
                            ),
                        ),
                    )
                )
            output = root / "output"
            args = _args(cohort, output, reviews)
            args.target_accepted = 2

            def render(candidate, path):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(candidate.family + "\n", encoding="utf-8")
                return path

            with (
                patch(
                    "experiments.run_temporal_warmup.author_case_draft",
                    side_effect=[
                        SimpleNamespace(batch=batch) for batch in batches
                    ],
                ) as author,
                patch(
                    "experiments.run_temporal_warmup.case_draft_batch_to_payload",
                    return_value={
                        "assessment": "A reviewed matched pair was drafted.",
                        "status": "authored",
                        "drafts": [],
                    },
                ),
                patch(
                    "experiments.run_temporal_warmup.filter_candidate",
                    return_value=SimpleNamespace(eligible=True, issues=()),
                ),
                patch(
                    "experiments.run_temporal_warmup.family_review_request_payload",
                    return_value={"review": "requested"},
                ),
                patch(
                    "experiments.run_temporal_warmup.assess_family_source_closure",
                    return_value=True,
                ),
                patch(
                    "experiments.run_temporal_warmup._persist_rendered_candidate",
                    side_effect=render,
                ) as persist,
                contextlib.redirect_stdout(io.StringIO()),
            ):
                status = run(args, backend=backend)

            self.assertEqual(status, 0)
            self.assertEqual(len(backend.requests), 2)
            self.assertEqual(author.call_count, 2)
            self.assertEqual(persist.call_count, 2)
            report = _read(output / "result.json")
            self.assertEqual(report["status"], "case_accepted")
            self.assertEqual(report["accepted_count"], 2)
            self.assertEqual(report["target_accepted"], 2)
            self.assertTrue(report["target_reached"])
            self.assertEqual(
                [item["paper_id"] for item in report["accepted_cases"]],
                ["paper_1", "paper_2"],
            )
            self.assertEqual(report["accepted_case"]["paper_id"], "paper_2")
            self.assertEqual(_read(output / "config.json")["target_accepted"], 2)
            self.assertFalse((output / "papers" / "03_paper_3").exists())

    def test_validation_repair_is_recorded_separately_and_replayed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            paper = _paper(1)
            (root / paper["tex_path"]).write_text(
                "\\documentclass{article}\n\\begin{document}source\\end{document}\n",
                encoding="utf-8",
            )
            cohort = root / "cohort.json"
            cohort.write_text(json.dumps(_cohort([paper])), encoding="utf-8")
            repaired = _card_payload(
                paper["source_citation"],
                paper["journal_doi"],
                paper["arxiv_versioned_id"],
            )
            backend = _QueuedBackend(
                [{"invalid": "science card"}, repaired]
            )
            output = root / "output"
            args = _args(cohort, output, root / "reviews")

            with contextlib.redirect_stdout(io.StringIO()):
                status = run(args, backend=backend)

            self.assertEqual(status, 3)
            self.assertEqual(len(backend.requests), 2)
            stage = output / "papers" / "01_paper_1" / "science_card"
            primary_response = _read(stage / "response.json")
            repair_response = _read(stage / "repair_01" / "response.json")
            self.assertEqual(
                json.loads(primary_response["text"]),
                {"invalid": "science card"},
            )
            self.assertEqual(json.loads(repair_response["text"]), repaired)
            self.assertEqual(_read(stage / "attempts.json")["attempt_count"], 2)
            repair_request = _read(stage / "repair_01" / "request.json")
            self.assertEqual(repair_request["metadata"]["generation_attempt"], 2)
            self.assertFalse((stage / "failure.json").exists())

            with contextlib.redirect_stdout(io.StringIO()):
                resumed = run(args, backend=backend)
            self.assertEqual(resumed, 3)
            self.assertEqual(len(backend.requests), 2)

    def test_model_artifact_failure_continues_after_bounded_repairs(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            papers = [_paper(1), _paper(2)]
            for paper in papers:
                (root / paper["tex_path"]).write_text(
                    "\\documentclass{article}\n\\begin{document}source\\end{document}\n",
                    encoding="utf-8",
                )
            cohort = root / "cohort.json"
            cohort.write_text(json.dumps(_cohort(papers)), encoding="utf-8")
            backend = _QueuedBackend(
                [
                    {"invalid": "science card"},
                    {"invalid": "science card repair one"},
                    {"invalid": "science card repair two"},
                    {"invalid": "science card repair three"},
                    _card_payload(
                        papers[1]["source_citation"],
                        papers[1]["journal_doi"],
                        papers[1]["arxiv_versioned_id"],
                    ),
                ]
            )
            output = root / "output"
            with contextlib.redirect_stdout(io.StringIO()):
                status = run(
                    _args(cohort, output, root / "reviews"), backend=backend
                )

            self.assertEqual(status, 3)
            self.assertEqual(len(backend.requests), 5)
            self.assertEqual(
                _read(output / "papers" / "01_paper_1" / "result.json")["status"],
                "science_card_generation_failed",
            )
            first_stage = output / "papers" / "01_paper_1" / "science_card"
            self.assertTrue((first_stage / "request.json").is_file())
            self.assertTrue((first_stage / "response.json").is_file())
            for repair_index in range(1, 4):
                repair = first_stage / ("repair_%02d" % repair_index)
                self.assertTrue((repair / "request.json").is_file())
                self.assertTrue((repair / "response.json").is_file())
            failure = _read(first_stage / "failure.json")
            self.assertEqual(failure["attempt_count"], 4)
            self.assertEqual(failure["error_type"], "ScienceCardError")
            self.assertEqual(
                _read(output / "papers" / "02_paper_2" / "result.json")["status"],
                "awaiting_source_review",
            )

    def test_reuses_completed_standalone_science_card_stages(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            papers = [_paper(1), _paper(2)]
            source = "\\documentclass{article}\n\\begin{document}source\\end{document}\n"
            for paper in papers:
                (root / paper["tex_path"]).write_text(source, encoding="utf-8")
            cohort = root / "cohort.json"
            cohort.write_text(json.dumps(_cohort(papers)), encoding="utf-8")
            output = root / "output"
            first_stage = output / "papers" / "01_paper_1" / "science_card"
            first_stage.mkdir(parents=True)
            (first_stage / "failure.json").write_text(
                json.dumps(
                    {
                        "error": "generated value violates the schema",
                        "error_type": "ScienceCardError",
                        "stage": "science_card",
                        "status": "failed",
                    }
                ),
                encoding="utf-8",
            )
            second_stage = output / "papers" / "02_paper_2" / "science_card"
            second_stage.mkdir(parents=True)
            (second_stage / "science_card.json").write_text(
                json.dumps(
                    _card_payload(
                        papers[1]["source_citation"],
                        papers[1]["journal_doi"],
                        papers[1]["arxiv_versioned_id"],
                    )
                ),
                encoding="utf-8",
            )
            backend = _QueuedBackend([])

            with contextlib.redirect_stdout(io.StringIO()):
                status = run(
                    _args(cohort, output, root / "reviews"), backend=backend
                )

            self.assertEqual(status, 3)
            self.assertEqual(backend.requests, [])
            self.assertEqual(
                _read(output / "papers" / "01_paper_1" / "result.json")["status"],
                "science_card_generation_failed",
            )
            self.assertEqual(
                _read(output / "papers" / "02_paper_2" / "result.json")["status"],
                "awaiting_source_review",
            )
            self.assertTrue(
                (output / "papers" / "02_paper_2" / "science_card.json").is_file()
            )

    def test_draft_artifact_failure_continues_to_the_next_paper(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            papers = [_paper(1), _paper(2)]
            for paper in papers:
                (root / paper["tex_path"]).write_text(
                    "\\documentclass{article}\n\\begin{document}source\\end{document}\n",
                    encoding="utf-8",
                )
            cohort = root / "cohort.json"
            cohort.write_text(json.dumps(_cohort(papers)), encoding="utf-8")
            reviews = root / "reviews"
            reviews.mkdir()
            (reviews / "paper_1.json").write_text(
                json.dumps(
                    _review_payload(
                        "paper_1",
                        papers[0]["source_citation"],
                        papers[0]["journal_doi"],
                        papers[0]["arxiv_versioned_id"],
                        eligible=True,
                    )
                ),
                encoding="utf-8",
            )
            backend = _QueuedBackend(
                [
                    _card_payload(
                        paper["source_citation"],
                        paper["journal_doi"],
                        paper["arxiv_versioned_id"],
                    )
                    for paper in papers
                ]
            )
            output = root / "output"
            with (
                patch(
                    "experiments.run_temporal_warmup.author_case_draft",
                    side_effect=CaseDraftError(
                        "case_draft.schema", "$", "invalid generated draft"
                    ),
                ) as author,
                contextlib.redirect_stdout(io.StringIO()),
            ):
                status = run(_args(cohort, output, reviews), backend=backend)

            self.assertEqual(status, 3)
            self.assertEqual(author.call_count, 1)
            self.assertEqual(len(backend.requests), 2)
            self.assertEqual(
                _read(output / "papers" / "01_paper_1" / "result.json")["status"],
                "draft_generation_failed",
            )
            self.assertEqual(
                _read(output / "papers" / "02_paper_2" / "result.json")["status"],
                "awaiting_source_review",
            )

    def test_explicit_draft_retry_preserves_failed_attempt_and_reuses_reviewed_card(self):
        parsed = _parser().parse_args(
            [
                "cohort.json",
                "output",
                "--retry-draft",
                "paper_1",
                "--retry-draft",
                "paper_2",
            ]
        )
        self.assertEqual(parsed.retry_draft, ["paper_1", "paper_2"])

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            paper = _paper(1)
            (root / paper["tex_path"]).write_text(
                "\\documentclass{article}\n\\begin{document}source\\end{document}\n",
                encoding="utf-8",
            )
            cohort = root / "cohort.json"
            cohort.write_text(json.dumps(_cohort([paper])), encoding="utf-8")
            reviews = root / "reviews"
            reviews.mkdir()
            (reviews / "paper_1.json").write_text(
                json.dumps(
                    _review_payload(
                        "paper_1",
                        paper["source_citation"],
                        paper["journal_doi"],
                        paper["arxiv_versioned_id"],
                        eligible=True,
                    )
                ),
                encoding="utf-8",
            )
            backend = _StageBackend(
                _card_payload(
                    paper["source_citation"],
                    paper["journal_doi"],
                    paper["arxiv_versioned_id"],
                )
            )
            output = root / "output"

            def fail_after_one_recorded_call(recording_backend, *_args, **_kwargs):
                recording_backend.generate(_draft_recording_request())
                raise CaseDraftError(
                    "case_draft.schema", "$.drafts[0]", "invalid generated draft"
                )

            with (
                patch(
                    "experiments.run_temporal_warmup.author_case_draft",
                    side_effect=fail_after_one_recorded_call,
                ),
                contextlib.redirect_stdout(io.StringIO()),
            ):
                initial = run(_args(cohort, output, reviews), backend=backend)

            self.assertEqual(initial, 5)
            paper_directory = output / "papers" / "01_paper_1"
            original_failure = (
                paper_directory / "case_draft" / "failure.json"
            ).read_bytes()
            frozen_artifacts = {
                name: (paper_directory / name).read_bytes()
                for name in (
                    "science_card.json",
                    "reviewed_science_card.json",
                    "source_review.json",
                    "paper_eligibility.json",
                )
            }
            frozen_config = (output / "config.json").read_bytes()

            candidate = SimpleNamespace(
                family="retried_family",
                source=SimpleNamespace(
                    citation=paper["source_citation"],
                    journal_doi=paper["journal_doi"],
                    arxiv_versioned_id=paper["arxiv_versioned_id"],
                ),
            )
            batch = SimpleNamespace(
                assessment="A source-closed family was drafted.",
                status="authored",
                drafts=(
                    SimpleNamespace(
                        candidate=candidate,
                        information_boundary=SimpleNamespace(),
                    ),
                ),
            )

            def succeed_after_one_recorded_call(recording_backend, *_args, **_kwargs):
                recording_backend.generate(_draft_recording_request())
                return SimpleNamespace(batch=batch, attempt_count=1)

            retry_args = _args(cohort, output, reviews)
            retry_args.retry_draft = ["paper_1"]
            with (
                patch(
                    "experiments.run_temporal_warmup.author_case_draft",
                    side_effect=succeed_after_one_recorded_call,
                ) as author,
                patch(
                    "experiments.run_temporal_warmup.case_draft_batch_to_payload",
                    return_value={
                        "assessment": "draft",
                        "status": "authored",
                        "drafts": [],
                    },
                ),
                patch(
                    "experiments.run_temporal_warmup.filter_candidate",
                    return_value=SimpleNamespace(eligible=True, issues=()),
                ),
                patch(
                    "experiments.run_temporal_warmup.family_review_request_payload",
                    return_value={"paper_id": "paper_1"},
                ),
                contextlib.redirect_stdout(io.StringIO()),
            ):
                retried = run(retry_args, backend=backend)

            self.assertEqual(retried, 3)
            self.assertEqual(author.call_count, 1)
            self.assertTrue(author.call_args.kwargs["strict_source_only"])
            self.assertEqual(author.call_args.kwargs["max_total_attempts"], 4)
            self.assertEqual(
                author.call_args.kwargs["reviewed_branch_claim_ids"],
                (("branch_a_claim",), ("branch_b_claim",)),
            )
            retry_error = author.call_args.kwargs["retry_artifact_error"]
            self.assertIsInstance(retry_error, CaseDraftError)
            self.assertEqual(retry_error.code, "case_draft.schema")
            self.assertEqual(retry_error.path, "$.drafts[0]")
            self.assertEqual(retry_error.detail, "invalid generated draft")
            self.assertEqual(
                paper_directory.joinpath("case_draft", "failure.json").read_bytes(),
                original_failure,
            )
            for name, content in frozen_artifacts.items():
                self.assertEqual((paper_directory / name).read_bytes(), content)
            self.assertEqual((output / "config.json").read_bytes(), frozen_config)
            retry_directory = paper_directory / "case_draft" / "retry"
            self.assertTrue((retry_directory / "request.json").is_file())
            self.assertTrue((retry_directory / "response.json").is_file())
            self.assertEqual(
                _read(retry_directory / "attempts.json"), {"attempt_count": 1}
            )
            self.assertTrue((paper_directory / "draft.json").is_file())
            paper_result = _read(paper_directory / "result.json")
            self.assertEqual(paper_result["status"], "awaiting_family_review")
            self.assertEqual(
                paper_result["draft_retry"],
                {
                    "attempt_count": 1,
                    "attempts_directory": "case_draft/retry",
                    "disposition": "explicit_draft_retry",
                    "draft_path": "draft.json",
                    "original_failure_path": "case_draft/failure.json",
                },
            )
            self.assertEqual(
                [request.metadata["purpose"] for request in backend.requests],
                [
                    "temporal_science_card",
                    "temporal_case_draft",
                    "temporal_case_draft",
                ],
            )

            calls_before_repeated_retry = len(backend.requests)
            with contextlib.redirect_stdout(io.StringIO()):
                repeated = run(retry_args, backend=backend)
            self.assertEqual(repeated, 2)
            self.assertEqual(len(backend.requests), calls_before_repeated_retry)
            self.assertIn(
                "requires an existing immutable draft_generation_failed result",
                _read(output / "failure.json")["error"],
            )

    def test_draft_retry_fails_closed_if_reviewed_gate_artifacts_change(self):
        for changed_artifact in (
            "non_retryable_failure",
            "result",
            "source_review",
            "paper_eligibility",
            "reviewed_science_card",
        ):
            with self.subTest(changed_artifact=changed_artifact), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                paper = _paper(1)
                (root / paper["tex_path"]).write_text(
                    "\\documentclass{article}\nsource\n",
                    encoding="utf-8",
                )
                cohort = root / "cohort.json"
                cohort.write_text(json.dumps(_cohort([paper])), encoding="utf-8")
                reviews = root / "reviews"
                reviews.mkdir()
                review_path = reviews / "paper_1.json"
                review_path.write_text(
                    json.dumps(
                        _review_payload(
                            "paper_1",
                            paper["source_citation"],
                            paper["journal_doi"],
                            paper["arxiv_versioned_id"],
                            eligible=True,
                        )
                    ),
                    encoding="utf-8",
                )
                backend = _StageBackend(
                    _card_payload(
                        paper["source_citation"],
                        paper["journal_doi"],
                        paper["arxiv_versioned_id"],
                    )
                )
                output = root / "output"

                def fail_after_one_recorded_call(recording_backend, *_args, **_kwargs):
                    recording_backend.generate(_draft_recording_request())
                    raise CaseDraftError(
                        "case_draft.schema", "$", "invalid generated draft"
                    )

                with (
                    patch(
                        "experiments.run_temporal_warmup.author_case_draft",
                        side_effect=fail_after_one_recorded_call,
                    ),
                    contextlib.redirect_stdout(io.StringIO()),
                ):
                    self.assertEqual(
                        run(_args(cohort, output, reviews), backend=backend),
                        5,
                    )

                paper_directory = output / "papers" / "01_paper_1"
                if changed_artifact == "non_retryable_failure":
                    failure_path = paper_directory / "case_draft" / "failure.json"
                    failure = _read(failure_path)
                    failure.update(
                        {
                            "error": "case_draft.source_fidelity at $: scientific drift",
                            "error_code": "case_draft.source_fidelity",
                            "error_detail": "scientific drift",
                            "error_path": "$",
                        }
                    )
                    failure_path.write_text(json.dumps(failure), encoding="utf-8")
                    result_path = paper_directory / "result.json"
                    result = _read(result_path)
                    result["failure"] = failure
                    result_path.write_text(json.dumps(result), encoding="utf-8")
                elif changed_artifact == "result":
                    payload = _read(paper_directory / "result.json")
                    payload["status"] = "candidate_rejected"
                    (paper_directory / "result.json").write_text(
                        json.dumps(payload), encoding="utf-8"
                    )
                elif changed_artifact == "source_review":
                    payload = _read(review_path)
                    payload["assessment"] = "changed after consumption"
                    review_path.write_text(json.dumps(payload), encoding="utf-8")
                elif changed_artifact == "paper_eligibility":
                    path = paper_directory / "paper_eligibility.json"
                    payload = _read(path)
                    payload["card_case_authoring_ready_hint"] = True
                    path.write_text(json.dumps(payload), encoding="utf-8")
                else:
                    path = paper_directory / "reviewed_science_card.json"
                    payload = _read(path)
                    payload["assessment"] = "changed after review"
                    path.write_text(json.dumps(payload), encoding="utf-8")

                retry_args = _args(cohort, output, reviews)
                retry_args.retry_draft = ["paper_1"]
                calls_before_retry = len(backend.requests)
                with (
                    patch(
                        "experiments.run_temporal_warmup.author_case_draft"
                    ) as author,
                    contextlib.redirect_stdout(io.StringIO()),
                ):
                    status = run(retry_args, backend=backend)

                self.assertEqual(status, 2)
                author.assert_not_called()
                self.assertEqual(len(backend.requests), calls_before_retry)
                self.assertFalse(
                    (paper_directory / "case_draft" / "retry").exists()
                )

    def test_missing_family_review_pauses_and_resume_does_not_recall_draft(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            paper = _paper(1)
            (root / paper["tex_path"]).write_text(
                "\\documentclass{article}\n\\begin{document}source\\end{document}\n",
                encoding="utf-8",
            )
            cohort = root / "cohort.json"
            cohort.write_text(json.dumps(_cohort([paper])), encoding="utf-8")
            reviews = root / "reviews"
            reviews.mkdir()
            (reviews / "paper_1.json").write_text(
                json.dumps(
                    _review_payload(
                        "paper_1",
                        paper["source_citation"],
                        paper["journal_doi"],
                        paper["arxiv_versioned_id"],
                        eligible=True,
                    )
                ),
                encoding="utf-8",
            )
            backend = _QueuedBackend(
                [
                    _card_payload(
                        paper["source_citation"],
                        paper["journal_doi"],
                        paper["arxiv_versioned_id"],
                    )
                ]
            )
            candidate = SimpleNamespace(
                family="resumable_family",
                source=SimpleNamespace(
                    citation=paper["source_citation"],
                    journal_doi=paper["journal_doi"],
                    arxiv_versioned_id=paper["arxiv_versioned_id"],
                ),
            )
            batch = SimpleNamespace(
                assessment="A source-closed family was drafted.",
                status="authored",
                drafts=(
                    SimpleNamespace(
                        candidate=candidate,
                        information_boundary=SimpleNamespace(),
                    ),
                ),
            )
            output = root / "output"
            with (
                patch(
                    "experiments.run_temporal_warmup.author_case_draft",
                    return_value=SimpleNamespace(batch=batch),
                ) as author,
                patch(
                    "experiments.run_temporal_warmup.case_draft_batch_to_payload",
                    return_value={"assessment": "draft", "status": "authored", "drafts": []},
                ),
                patch(
                    "experiments.run_temporal_warmup.parse_case_draft_batch_json",
                    return_value=batch,
                ),
                patch("experiments.run_temporal_warmup.validate_case_draft_batch"),
                patch(
                    "experiments.run_temporal_warmup.filter_candidate",
                    return_value=SimpleNamespace(eligible=True, issues=()),
                ),
                patch(
                    "experiments.run_temporal_warmup.family_review_request_payload",
                    return_value={"paper_id": "paper_1"},
                ),
                patch(
                    "experiments.run_temporal_warmup.assess_family_source_closure",
                    return_value=True,
                ),
                patch(
                    "experiments.run_temporal_warmup._persist_rendered_candidate",
                    side_effect=lambda _candidate, path: path,
                ),
                contextlib.redirect_stdout(io.StringIO()),
            ):
                first = run(_args(cohort, output, reviews), backend=backend)
                self.assertEqual(first, 3)
                self.assertEqual(_read(output / "result.json")["status"], "awaiting_family_review")
                (reviews / "paper_1.family.json").write_text(
                    json.dumps(_family_review_payload(paper, "resumable_family")),
                    encoding="utf-8",
                )
                second = run(_args(cohort, output, reviews), backend=backend)

            self.assertEqual(second, 0)
            self.assertEqual(author.call_count, 1)
            self.assertEqual(len(backend.requests), 1)

    def test_render_validation_instantiates_all_four_matched_cells(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = root / "four_cells.py"
            candidate = SimpleNamespace(family="four_cells")
            calls = []

            def factory(world, track):
                calls.append((world, track))
                return object()

            def writer(_candidate, output):
                output.write_text("generated\n", encoding="utf-8")
                return output

            class CanaryEpisode:
                def __init__(self, case):
                    self.case = case
                    self.outcome = None

                def apply(self, action):
                    self.outcome = SimpleNamespace(
                        active_pass=True,
                        protocol_completed=True,
                        evaluation=SimpleNamespace(
                            success=True,
                            scores={"predictive_model_pass": 1.0},
                        ),
                    )

            with (
                patch(
                    "experiments.run_temporal_warmup.render_candidate_module",
                    return_value="generated\n",
                ),
                patch(
                    "experiments.run_temporal_warmup.write_candidate_module",
                    side_effect=writer,
                ),
                patch(
                    "experiments.run_temporal_warmup.runpy.run_path",
                    return_value={
                        "FOUR_CELLS_SPEC": object(),
                        "make_four_cells_case": factory,
                    },
                ),
                patch(
                    "experiments.run_temporal_warmup.truth_submission",
                    return_value=SimpleNamespace(hypothesis_id="H1"),
                ),
                patch(
                    "experiments.run_temporal_warmup.Episode",
                    CanaryEpisode,
                ),
            ):
                _persist_rendered_candidate(candidate, path)

            self.assertEqual(
                calls,
                [
                    ("historical", BenchmarkTrack.IDENTIFICATION),
                    ("historical", BenchmarkTrack.DISCOVERY),
                    ("counterfactual", BenchmarkTrack.IDENTIFICATION),
                    ("counterfactual", BenchmarkTrack.DISCOVERY),
                ],
            )
            validation = _read(path.with_suffix(".validation.json"))
            self.assertTrue(validation["all_pass"])
            self.assertEqual(len(validation["cells"]), 4)

    def test_failed_canary_does_not_publish_a_case_module(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "rejected.py"
            candidate = SimpleNamespace(family="rejected")

            def writer(_candidate, path):
                path.write_text("generated\n", encoding="utf-8")
                return path

            class FailingEpisode:
                def __init__(self, case):
                    self.case = case
                    self.outcome = None

                def apply(self, action):
                    self.outcome = SimpleNamespace(
                        active_pass=False,
                        protocol_completed=True,
                        evaluation=SimpleNamespace(
                            success=False,
                            scores={"predictive_model_pass": 0.0},
                        ),
                    )

            with (
                patch(
                    "experiments.run_temporal_warmup.render_candidate_module",
                    return_value="generated\n",
                ),
                patch(
                    "experiments.run_temporal_warmup.write_candidate_module",
                    side_effect=writer,
                ),
                patch(
                    "experiments.run_temporal_warmup.runpy.run_path",
                    return_value={
                        "REJECTED_SPEC": object(),
                        "make_rejected_case": lambda world, track: object(),
                    },
                ),
                patch(
                    "experiments.run_temporal_warmup.truth_submission",
                    return_value=SimpleNamespace(hypothesis_id="H1"),
                ),
                patch("experiments.run_temporal_warmup.Episode", FailingEpisode),
            ):
                with self.assertRaisesRegex(RuntimeError, "four-cell"):
                    _persist_rendered_candidate(candidate, output)

            self.assertFalse(output.exists())
            self.assertFalse(output.with_suffix(".validation.json").exists())


def _read(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
