from __future__ import annotations

import json
import unittest

from role_benchmark import GenerationResponse
from role_benchmark.cases.matched import MatchedFamilySpec
from role_benchmark.cases.source import (
    SourceFamilySpec,
    make_source_case,
    source_truth_submission,
)
from role_benchmark.models import BenchmarkTrack
from role_benchmark.temporal.admission import (
    TEMPORAL_ADMISSION_PRECOMPILE_CHECKS_V2,
    TEMPORAL_ADMISSION_REVIEW_SCHEMA,
    TEMPORAL_ADMISSION_REVIEW_SCHEMA_V2,
    TemporalAdmissionError,
    assess_temporal_admission,
    parse_temporal_admission_review_payload,
    temporal_admission_review_to_payload,
    temporal_admission_review_v2_request_payload,
)
from role_benchmark.temporal.counterfactual_construction import (
    TemporalCounterfactualRequest,
    construct_temporal_counterfactual_variants,
)
from role_benchmark.temporal.minimal_card_extract import (
    RETRYABLE_MINIMAL_CARD_ERROR_CODES,
    build_minimal_science_card_request,
    extract_minimal_science_card,
)
from role_benchmark.temporal.minimal_science_card import (
    MinimalScienceCardError,
    minimal_science_card_provider_payload,
    minimal_science_card_to_payload,
    parse_minimal_science_card_payload,
    parse_minimal_science_card_provider_json,
    parse_minimal_science_card_provider_payload,
    validate_minimal_science_card_lineage,
)
from role_benchmark.temporal.science_card import ScienceSource
from role_benchmark.temporal.source_case import (
    TEMPORAL_PROVENANCE_SCHEMA,
    TemporalCaseConstructionError,
    compile_temporal_source_case,
    render_temporal_source_case_module,
)


_CITATION = "A. Author et al., Example Journal (2026)"
_DOI = "10.0000/example"
_ARXIV_ID = "2607.01234v2"
_SOURCE_TEXT = "\n".join(
    (
        "The central relation is response_y = scale input_x with scale = 2.0.",
        "The input input_x is controlled from 1.0 to 9.0 arbitrary units.",
        "The readout response_y is reported in arbitrary units.",
        "The relation applies at fixed temperature.",
    )
)


def _anchor(line: int) -> dict[str, int]:
    return {"line_start": line, "line_end": line}


def _provider_payload() -> dict:
    """Return exactly the six model-authored fields for one relation."""

    return {
        "relations": [
            {
                "formula": {
                    "outputs": {
                        "response_y": {
                            "op": "multiply",
                            "args": [
                                {"param": "scale"},
                                {"var": "input_x"},
                            ],
                        }
                    }
                },
                "parameters": [
                    {
                        "name": "scale",
                        "value": 2.0,
                        "unit": "1",
                        "anchors": [_anchor(1)],
                    }
                ],
                "controls": [
                    {
                        "name": "input_x",
                        "definition": "The numeric input controlled by the study.",
                        "unit": "a.u.",
                        "anchors": [_anchor(2)],
                    }
                ],
                "readouts": [
                    {
                        "name": "response_y",
                        "definition": (
                            "The quantitative response reported by the study."
                        ),
                        "unit": "a.u.",
                        "anchors": [_anchor(3)],
                    }
                ],
                "domain": {
                    "controls": [
                        {
                            "control_name": "input_x",
                            "domain_kind": "continuous_interval",
                            "minimum": 1.0,
                            "maximum": 9.0,
                            "allowed_values": [],
                            "anchors": [_anchor(2)],
                        }
                    ],
                    "applicability": [
                        {
                            "statement": "The temperature is fixed.",
                            "anchors": [_anchor(4)],
                        }
                    ],
                },
                "anchors": [_anchor(1)],
            }
        ]
    }


def _source() -> ScienceSource:
    return ScienceSource(
        citation=_CITATION,
        journal_doi=_DOI,
        arxiv_versioned_id=_ARXIV_ID,
    )


def _card():
    return parse_minimal_science_card_provider_payload(
        _provider_payload(),
        source=_source(),
    )


def _eligible_review_payload(card) -> dict:
    return {
        "schema": TEMPORAL_ADMISSION_REVIEW_SCHEMA,
        "paper_id": "paper-001",
        "source": {
            "citation": _CITATION,
            "journal_doi": _DOI,
            "arxiv_versioned_id": _ARXIV_ID,
        },
        "review_material": minimal_science_card_to_payload(card),
        "reviewer": "independent-source-reviewer",
        "decision": "eligible_for_temporal_case",
        "assessment": (
            "The fixed source supports the executable relation and its declared domain."
        ),
        "checks": {
            "source_support_confirmed": True,
            "cartesian_domain_supported": True,
            "deterministic_central_value_appropriate": True,
        },
        "issues": [
            {
                "code": "source.limitations_noted",
                "detail": "The relation is restricted to the stated fixed condition.",
                "blocking": False,
                "line_ranges": [_anchor(4)],
            }
        ],
    }


def _eligible_v2_review_payload(card) -> dict:
    payload = dict(
        temporal_admission_review_v2_request_payload(
            card,
            paper_id="paper-001",
        )
    )
    payload.update(
        {
            "reviewer": "independent-source-reviewer",
            "decision": "eligible_for_temporal_case",
            "assessment": (
                "All eight pre-compile checks pass against the fixed source."
            ),
            "checks": {
                name: "pass" for name in TEMPORAL_ADMISSION_PRECOMPILE_CHECKS_V2
            },
            "issues": [
                {
                    "code": "source.limitations_noted",
                    "detail": "The relation is restricted to the fixed condition.",
                    "blocking": False,
                    "line_ranges": [_anchor(4)],
                }
            ],
        }
    )
    return payload


def _admission(card=None):
    selected = card or _card()
    review = parse_temporal_admission_review_payload(
        _eligible_review_payload(selected)
    )
    return assess_temporal_admission(
        selected,
        review,
        paper_id="paper-001",
        source_line_count=4,
    )


class _FakeBackend:
    def __init__(self, payload):
        self.payload = payload
        self.requests = []

    def generate(self, request):
        self.requests.append(request)
        return GenerationResponse(
            text=json.dumps(self.payload),
            provider="fake",
            model="frozen-authoring-snapshot",
            finish_reason="stop",
        )


class TemporalMinimalPipelineTests(unittest.TestCase):
    def test_v1_admission_review_remains_replay_compatible(self):
        payload = _eligible_review_payload(_card())
        review = parse_temporal_admission_review_payload(payload)

        self.assertEqual(
            TEMPORAL_ADMISSION_REVIEW_SCHEMA,
            "role_benchmark.temporal_admission_review.v1",
        )
        self.assertEqual(review.schema, TEMPORAL_ADMISSION_REVIEW_SCHEMA)
        self.assertIsNone(review.precompile_checks)
        self.assertEqual(temporal_admission_review_to_payload(review), payload)

    def test_v2_admission_requires_exactly_eight_passing_precompile_checks(self):
        card = _card()
        request = temporal_admission_review_v2_request_payload(
            card,
            paper_id="paper-001",
        )
        self.assertEqual(request["schema"], TEMPORAL_ADMISSION_REVIEW_SCHEMA_V2)
        self.assertEqual(
            set(request["checks"]),
            set(TEMPORAL_ADMISSION_PRECOMPILE_CHECKS_V2),
        )
        self.assertEqual(set(request["checks"].values()), {"not_assessable"})
        self.assertNotIn("constructed_case_fidelity", request["checks"])

        payload = _eligible_v2_review_payload(card)
        review = parse_temporal_admission_review_payload(payload)
        self.assertEqual(review.schema, TEMPORAL_ADMISSION_REVIEW_SCHEMA_V2)
        self.assertEqual(
            review.precompile_checks,
            {name: "pass" for name in TEMPORAL_ADMISSION_PRECOMPILE_CHECKS_V2},
        )
        self.assertIsNone(review.source_support_confirmed)
        self.assertEqual(temporal_admission_review_to_payload(review), payload)

        result = assess_temporal_admission(
            card,
            review,
            paper_id="paper-001",
            source_line_count=4,
        )
        self.assertTrue(result.admitted)

        incomplete = _eligible_v2_review_payload(card)
        incomplete["checks"]["control_support"] = "not_assessable"
        with self.assertRaises(TemporalAdmissionError) as raised:
            parse_temporal_admission_review_payload(incomplete)
        self.assertEqual(raised.exception.code, "temporal_admission.decision")

        revision = _eligible_v2_review_payload(card)
        revision["decision"] = "card_revision_required"
        revision["checks"]["control_support"] = "fail"
        revision["issues"][0]["blocking"] = True
        parsed_revision = parse_temporal_admission_review_payload(revision)
        self.assertEqual(parsed_revision.decision, "card_revision_required")
        revision["issues"][0]["blocking"] = False
        with self.assertRaises(TemporalAdmissionError) as raised:
            parse_temporal_admission_review_payload(revision)
        self.assertEqual(raised.exception.code, "temporal_admission.decision")

    def test_v2_admission_rejects_invalid_or_postcompile_checks(self):
        invalid_status = _eligible_v2_review_payload(_card())
        invalid_status["checks"]["anchor_accuracy"] = "pending"
        with self.assertRaises(TemporalAdmissionError) as raised:
            parse_temporal_admission_review_payload(invalid_status)
        self.assertEqual(raised.exception.path, "$.checks.anchor_accuracy")

        postcompile = _eligible_v2_review_payload(_card())
        postcompile["checks"]["constructed_case_fidelity"] = "pass"
        with self.assertRaises(TemporalAdmissionError) as raised:
            parse_temporal_admission_review_payload(postcompile)
        self.assertEqual(raised.exception.path, "$.checks")

    def test_repair_allowlist_matches_the_historical_mechanical_policy(self):
        self.assertEqual(
            RETRYABLE_MINIMAL_CARD_ERROR_CODES,
            {
                "minimal_science_card.schema",
                "minimal_science_card.locator",
            },
        )

    def test_minimal_card_round_trip_and_acquisition_source_injection(self):
        provider_payload = _provider_payload()
        card = parse_minimal_science_card_provider_json(
            json.dumps(provider_payload),
            source=_source(),
        )

        self.assertEqual(card.source, _source())
        self.assertEqual(
            set(provider_payload["relations"][0]),
            {"formula", "parameters", "controls", "readouts", "domain", "anchors"},
        )
        self.assertNotIn("source", minimal_science_card_provider_payload(card))
        self.assertEqual(
            parse_minimal_science_card_payload(minimal_science_card_to_payload(card)),
            card,
        )

        request = build_minimal_science_card_request(
            _SOURCE_TEXT,
            source_citation=_CITATION,
            journal_doi=_DOI,
            arxiv_versioned_id=_ARXIV_ID,
        )
        self.assertEqual(set(request.response_schema["properties"]), {"relations"})
        self.assertNotIn("source", request.response_schema["properties"])

        backend = _FakeBackend(provider_payload)
        result = extract_minimal_science_card(
            backend,
            _SOURCE_TEXT,
            source_citation=_CITATION,
            journal_doi=_DOI,
            arxiv_versioned_id=_ARXIV_ID,
        )
        self.assertEqual(result.card, card)
        self.assertEqual(result.attempt_count, 1)
        self.assertEqual(len(backend.requests), 1)

    def test_empty_relations_is_a_valid_abstention_but_not_an_admitted_case(self):
        card = parse_minimal_science_card_provider_payload(
            {"relations": []},
            source=_source(),
        )
        self.assertEqual(card.relations, ())
        self.assertEqual(
            minimal_science_card_provider_payload(card),
            {"relations": []},
        )

        review = parse_temporal_admission_review_payload(
            _eligible_review_payload(card)
        )
        with self.assertRaises(TemporalAdmissionError) as raised:
            assess_temporal_admission(
                card,
                review,
                paper_id="paper-001",
                source_line_count=4,
            )
        self.assertEqual(
            raised.exception.code,
            "temporal_admission.relation_required",
        )
        with self.assertRaises(TypeError):
            compile_temporal_source_case(card, case_index=1)

    def test_nonstructural_numeric_literal_is_rejected(self):
        payload = _provider_payload()
        payload["relations"][0]["formula"]["outputs"]["response_y"] = {
            "op": "multiply",
            "args": [2.0, {"var": "input_x"}],
        }
        with self.assertRaises(MinimalScienceCardError) as raised:
            parse_minimal_science_card_provider_payload(payload, source=_source())
        self.assertEqual(raised.exception.code, "minimal_science_card.schema")
        self.assertIn("structural zero and one", raised.exception.detail)

    def test_every_declared_control_and_parameter_must_be_used(self):
        unused_parameter = _provider_payload()
        unused_parameter["relations"][0]["formula"]["outputs"]["response_y"] = {
            "var": "input_x"
        }
        with self.assertRaises(MinimalScienceCardError) as parameter_error:
            parse_minimal_science_card_provider_payload(
                unused_parameter,
                source=_source(),
            )
        self.assertEqual(parameter_error.exception.path, "$.relations[0].parameters")
        self.assertIn("must occur", parameter_error.exception.detail)

        unused_control = _provider_payload()
        unused_control["relations"][0]["formula"]["outputs"]["response_y"] = {
            "param": "scale"
        }
        with self.assertRaises(MinimalScienceCardError) as control_error:
            parse_minimal_science_card_provider_payload(
                unused_control,
                source=_source(),
            )
        self.assertEqual(control_error.exception.path, "$.relations[0].controls")
        self.assertIn("must occur", control_error.exception.detail)

    def test_source_locator_must_resolve_within_the_fixed_packet(self):
        card = _card()
        validate_minimal_science_card_lineage(card, source_line_count=4)
        with self.assertRaises(MinimalScienceCardError) as raised:
            validate_minimal_science_card_lineage(card, source_line_count=3)
        self.assertEqual(raised.exception.code, "minimal_science_card.locator")
        self.assertIn("exceeds the 3-line model input", raised.exception.detail)

    def test_admission_needs_one_reviewed_relation_not_a_second_condition(self):
        card = _card()
        review_payload = _eligible_review_payload(card)
        relation = review_payload["review_material"]["relations"][0]
        self.assertEqual(
            set(relation),
            {"formula", "parameters", "controls", "readouts", "domain", "anchors"},
        )
        self.assertNotIn("conditions", relation)

        review = parse_temporal_admission_review_payload(review_payload)
        result = assess_temporal_admission(
            card,
            review,
            paper_id="paper-001",
            source_line_count=4,
        )
        self.assertTrue(result.admitted)
        self.assertEqual(result.disposition, "eligible_for_temporal_case")
        self.assertIs(result.card, card)
        self.assertEqual(len(result.issues), 1)
        self.assertFalse(result.issues[0].blocking)

    def test_deterministic_compiler_generates_disjoint_design_and_provenance(self):
        card = _card()
        admission = _admission(card)
        first = compile_temporal_source_case(admission, case_index=7)
        second = compile_temporal_source_case(admission, case_index=7)

        self.assertIsInstance(first.spec, SourceFamilySpec)
        self.assertEqual(first.spec.family, "temporal_source_007")
        self.assertEqual(first.spec.model_outputs, second.spec.model_outputs)
        self.assertEqual(
            first.spec.diagnostic_conditions,
            second.spec.diagnostic_conditions,
        )
        self.assertEqual(first.spec.hidden_conditions, second.spec.hidden_conditions)
        self.assertEqual(first.provenance, second.provenance)
        self.assertEqual(
            render_temporal_source_case_module(admission, case_index=7),
            render_temporal_source_case_module(admission, case_index=7),
        )

        control_names = tuple(item.name for item in first.spec.controls)

        def condition_key(item):
            return tuple(item[name] for name in control_names)

        diagnostic = {condition_key(item) for item in first.spec.diagnostic_conditions}
        hidden = {condition_key(item) for item in first.spec.hidden_conditions}
        self.assertTrue(diagnostic)
        self.assertTrue(hidden)
        self.assertFalse(diagnostic & hidden)
        self.assertEqual(first.spec.budget, len(first.spec.diagnostic_conditions))

        self.assertEqual(first.provenance["schema"], TEMPORAL_PROVENANCE_SCHEMA)
        self.assertEqual(first.provenance["source"]["arxiv_versioned_id"], _ARXIV_ID)
        origins = {item["origin"] for item in first.provenance["mappings"]}
        self.assertEqual(origins, {"source", "deterministic_code"})
        formula_mapping = next(
            item
            for item in first.provenance["mappings"]
            if item["field"] == "oracle.formula"
        )
        self.assertEqual(formula_mapping["line_ranges"], [_anchor(1)])

    def test_compiler_canonicalizes_source_control_names_in_generated_conditions(self):
        payload = _provider_payload()
        relation = payload["relations"][0]
        relation["formula"]["outputs"] = {
            "ResponseY": {
                "op": "multiply",
                "args": [
                    {"param": "Scale"},
                    {"var": "InputX"},
                ],
            }
        }
        relation["parameters"][0]["name"] = "Scale"
        relation["controls"][0]["name"] = "InputX"
        relation["readouts"][0]["name"] = "ResponseY"
        relation["domain"]["controls"][0]["control_name"] = "InputX"
        card = parse_minimal_science_card_provider_payload(
            payload,
            source=_source(),
        )

        build = compile_temporal_source_case(_admission(card), case_index=7)

        self.assertEqual(tuple(item.name for item in build.spec.controls), ("inputx",))
        self.assertEqual(tuple(item.name for item in build.spec.readouts), ("responsey",))
        self.assertTrue(
            all(set(condition) == {"inputx"} for condition in build.spec.diagnostic_conditions)
        )
        self.assertTrue(
            all(set(condition) == {"inputx"} for condition in build.spec.hidden_conditions)
        )

    def test_compiler_does_not_publish_model_authored_free_text(self):
        payload = _provider_payload()
        leaked_text = "The fitted scale equals 2.0."
        payload["relations"][0]["controls"][0]["definition"] = leaked_text
        payload["relations"][0]["readouts"][0]["definition"] = leaked_text
        payload["relations"][0]["domain"]["applicability"][0][
            "statement"
        ] = leaked_text
        card = parse_minimal_science_card_provider_payload(
            payload,
            source=_source(),
        )
        build = compile_temporal_source_case(_admission(card), case_index=7)
        case = make_source_case(build.spec, BenchmarkTrack.DISCOVERY)
        public_text = json.dumps(
            {
                "background": case.definition.background,
                "initial_observations": case.definition.initial_observations,
                "resources": {
                    "controls": [item.description for item in build.spec.controls],
                    "readouts": [item.description for item in build.spec.readouts],
                    "notes": case.definition.resources.notes,
                },
            }
        )
        self.assertNotIn(leaked_text, public_text)

    def test_compiler_rejects_a_domain_without_any_held_out_condition(self):
        payload = _provider_payload()
        domain = payload["relations"][0]["domain"]["controls"][0]
        domain.update(
            {
                "domain_kind": "numeric_values",
                "minimum": None,
                "maximum": None,
                "allowed_values": [1.0, 9.0],
            }
        )
        card = parse_minimal_science_card_provider_payload(
            payload,
            source=_source(),
        )
        with self.assertRaisesRegex(
            TemporalCaseConstructionError,
            "no held-out condition",
        ):
            compile_temporal_source_case(_admission(card), case_index=7)

    def test_eligible_review_requires_domain_and_execution_checks(self):
        payload = _eligible_review_payload(_card())
        payload["checks"]["cartesian_domain_supported"] = False
        with self.assertRaises(TemporalAdmissionError) as raised:
            parse_temporal_admission_review_payload(payload)
        self.assertEqual(raised.exception.code, "temporal_admission.decision")

    def test_admission_rejects_review_locators_outside_the_source_packet(self):
        card = _card()
        payload = _eligible_review_payload(card)
        payload["issues"][0]["line_ranges"] = [_anchor(5)]
        review = parse_temporal_admission_review_payload(payload)
        with self.assertRaises(TemporalAdmissionError) as raised:
            assess_temporal_admission(
                card,
                review,
                paper_id="paper-001",
                source_line_count=4,
            )
        self.assertEqual(raised.exception.code, "temporal_admission.locator")

    def test_parameter_free_relation_is_not_an_identification_case(self):
        payload = _provider_payload()
        relation = payload["relations"][0]
        relation["parameters"] = []
        relation["formula"]["outputs"]["response_y"] = {"var": "input_x"}
        relation["domain"]["applicability"] = []
        card = parse_minimal_science_card_provider_payload(
            payload,
            source=_source(),
        )
        with self.assertRaisesRegex(
            TemporalCaseConstructionError,
            "supports Discovery but not",
        ):
            compile_temporal_source_case(_admission(card), case_index=7)

    def test_compiler_rejects_locally_nonidentifiable_parameters(self):
        payload = _provider_payload()
        relation = payload["relations"][0]
        relation["parameters"] = [
            {
                "name": name,
                "value": value,
                "unit": "1",
                "anchors": [_anchor(1)],
            }
            for name, value in (
                ("first_scale", 1.0),
                ("second_scale", 2.0),
                ("third_scale", 3.0),
            )
        ]
        relation["formula"]["outputs"]["response_y"] = {
            "op": "multiply",
            "args": [
                {
                    "op": "add",
                    "args": [
                        {"param": "first_scale"},
                        {"param": "second_scale"},
                        {"param": "third_scale"},
                    ],
                },
                {"var": "input_x"},
            ],
        }
        card = parse_minimal_science_card_provider_payload(
            payload,
            source=_source(),
        )
        with self.assertRaisesRegex(
            TemporalCaseConstructionError,
            "not locally identifiable",
        ):
            compile_temporal_source_case(_admission(card), case_index=7)

    def test_compiler_expands_diagnostics_for_identifiable_parameters(self):
        payload = _provider_payload()
        relation = payload["relations"][0]
        relation["parameters"] = [
            {
                "name": name,
                "value": value,
                "unit": "1",
                "anchors": [_anchor(1)],
            }
            for name, value in (
                ("constant", 1.0),
                ("linear", 2.0),
                ("quadratic", 3.0),
                ("cubic", 4.0),
            )
        ]
        x = {"var": "input_x"}
        relation["formula"]["outputs"]["response_y"] = {
            "op": "add",
            "args": [
                {"param": "constant"},
                {
                    "op": "multiply",
                    "args": [{"param": "linear"}, x],
                },
                {
                    "op": "multiply",
                    "args": [{"param": "quadratic"}, x, x],
                },
                {
                    "op": "multiply",
                    "args": [{"param": "cubic"}, x, x, x],
                },
            ],
        }
        card = parse_minimal_science_card_provider_payload(
            payload,
            source=_source(),
        )

        build = compile_temporal_source_case(_admission(card), case_index=7)

        self.assertEqual(len(build.spec.diagnostic_conditions), 4)
        self.assertEqual(build.spec.budget, 4)
        self.assertEqual(len(build.spec.hidden_conditions), 1)
        self.assertFalse(
            {
                tuple(sorted(condition.items()))
                for condition in build.spec.diagnostic_conditions
            }
            & {
                tuple(sorted(condition.items()))
                for condition in build.spec.hidden_conditions
            }
        )

    def test_compiler_reserves_held_out_before_expanding_diagnostics(self):
        payload = _provider_payload()
        relation = payload["relations"][0]
        relation["parameters"] = [
            {
                "name": name,
                "value": value,
                "unit": "1",
                "anchors": [_anchor(1)],
            }
            for name, value in (
                ("constant", 1.0),
                ("linear", 2.0),
                ("quadratic", 3.0),
                ("cubic", 4.0),
            )
        ]
        x = {"var": "input_x"}
        relation["formula"]["outputs"]["response_y"] = {
            "op": "add",
            "args": [
                {"param": "constant"},
                {
                    "op": "multiply",
                    "args": [{"param": "linear"}, x],
                },
                {
                    "op": "multiply",
                    "args": [{"param": "quadratic"}, x, x],
                },
                {
                    "op": "multiply",
                    "args": [{"param": "cubic"}, x, x, x],
                },
            ],
        }
        relation["domain"]["controls"][0].update(
            {
                "domain_kind": "numeric_values",
                "minimum": None,
                "maximum": None,
                "allowed_values": [1.0, 2.0, 3.0],
            }
        )
        card = parse_minimal_science_card_provider_payload(
            payload,
            source=_source(),
        )

        with self.assertRaisesRegex(
            TemporalCaseConstructionError,
            "no held-out condition.*minimum diagnostic observations",
        ):
            compile_temporal_source_case(_admission(card), case_index=7)

    def test_compiler_rejects_an_interior_singularity_in_the_query_domain(self):
        payload = _provider_payload()
        relation = payload["relations"][0]
        relation["parameters"].append(
            {
                "name": "offset",
                "value": 4.0,
                "unit": "a.u.",
                "anchors": [_anchor(1)],
            }
        )
        relation["formula"]["outputs"]["response_y"] = {
            "op": "divide",
            "args": [
                {"param": "scale"},
                {
                    "op": "subtract",
                    "args": [
                        {"var": "input_x"},
                        {"param": "offset"},
                    ],
                },
            ],
        }
        card = parse_minimal_science_card_provider_payload(
            payload,
            source=_source(),
        )
        with self.assertRaisesRegex(
            TemporalCaseConstructionError,
            "not total on the public query domain",
        ):
            compile_temporal_source_case(_admission(card), case_index=7)

    def test_generated_source_case_truth_passes_both_task_settings(self):
        namespace = {}
        source = render_temporal_source_case_module(_admission(), case_index=7)
        exec(compile(source, "<generated-temporal-case>", "exec"), namespace)
        spec = namespace["TEMPORAL_SOURCE_007_SPEC"]
        self.assertIn("TEMPORAL_SOURCE_007_PROVENANCE", namespace)
        factory = namespace["make_temporal_source_007_case"]
        for track in (BenchmarkTrack.IDENTIFICATION, BenchmarkTrack.DISCOVERY):
            with self.subTest(track=track.value):
                case = factory(track)
                result = case.evaluator.evaluate(source_truth_submission(spec, track))
                self.assertTrue(result.success, result.message)

    def test_counterfactual_variant_is_created_only_by_an_explicit_request(self):
        source_spec = compile_temporal_source_case(_admission(), case_index=7).spec
        self.assertIsInstance(source_spec, SourceFamilySpec)
        self.assertNotIsInstance(source_spec, MatchedFamilySpec)
        self.assertFalse(hasattr(source_spec, "truths"))

        with self.assertRaisesRegex(ValueError, "TemporalCounterfactualRequest"):
            construct_temporal_counterfactual_variants(source_spec, None)

        variants = construct_temporal_counterfactual_variants(
            source_spec,
            TemporalCounterfactualRequest(
                parameter_name="scale",
                target_value=4.0,
                unit="1",
            ),
        )
        self.assertEqual(tuple(variants), ("easy", "hard"))
        self.assertEqual(variants["easy"].counterfactual_fraction, 1.0)
        self.assertEqual(variants["hard"].counterfactual_fraction, 0.5)
        self.assertAlmostEqual(
            variants["easy"].spec.truths["counterfactual"].parameters["scale"],
            4.0,
        )
        self.assertAlmostEqual(
            variants["hard"].spec.truths["counterfactual"].parameters["scale"],
            3.0,
        )
        self.assertEqual(
            variants["easy"].spec.truths["historical"].parameters,
            source_spec.truth.parameters,
        )
        self.assertIn(
            "not a source-reported condition",
            " ".join(variants["easy"].spec.common_notes),
        )
        self.assertGreater(
            variants["easy"].fixed_design_separation,
            variants["hard"].fixed_design_separation,
        )
        self.assertGreater(variants["hard"].fixed_design_separation, 0.0)

    def test_counterfactual_difficulty_uses_observed_separation_order(self):
        payload = _provider_payload()
        payload["relations"][0]["formula"]["outputs"]["response_y"] = {
            "op": "sin",
            "args": [
                {
                    "op": "multiply",
                    "args": [
                        {"param": "scale"},
                        {"var": "input_x"},
                    ],
                }
            ],
        }
        card = parse_minimal_science_card_provider_payload(
            payload,
            source=_source(),
        )
        source_spec = compile_temporal_source_case(
            _admission(card),
            case_index=7,
        ).spec
        variants = construct_temporal_counterfactual_variants(
            source_spec,
            TemporalCounterfactualRequest(
                parameter_name="scale",
                target_value=-10.0,
                unit="1",
            ),
        )
        self.assertGreater(
            variants["easy"].fixed_design_separation,
            variants["hard"].fixed_design_separation,
        )


if __name__ == "__main__":
    unittest.main()
