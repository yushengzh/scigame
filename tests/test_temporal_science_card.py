from __future__ import annotations

import copy
import json
import unittest

from role_benchmark import GenerationResponse
from role_benchmark.temporal.card_extract import (
    RETRYABLE_SCIENCE_CARD_ERROR_CODES,
    build_science_card_request,
    extract_science_card,
)
from role_benchmark.temporal.science_card import (
    ScienceCardError,
    canonical_science_name,
    parse_science_card_json,
    science_card_json_schema,
    science_card_to_payload,
)
from role_benchmark.wire import canonical_json_dumps


_CITATION = "A. Author et al., Example Journal (2026)"
_DOI = "10.0000/example"
_ARXIV_ID = "2607.01234v2"
_SOURCE = "\n".join(
    (
        "The response follows a controlled scaling law.",
        "The input is varied between 1 and 9 units.",
        "The measured response is an ensemble mean reported to 0.01 units.",
        "The apparatus is held at a fixed temperature.",
        "A fitted claim agrees with the mechanism.",
    )
)


def _anchor(line: int = 1):
    return {
        "line_start": line,
        "line_end": line,
        "support": "The cited line supports this item.",
    }


def _card_payload():
    return {
        "assessment": "The source supports one linked quantitative response.",
        "case_authoring_ready": True,
        "source": {
            "citation": _CITATION,
            "journal_doi": _DOI,
            "arxiv_versioned_id": _ARXIV_ID,
        },
        "paper_scope": "A controlled response in a fixed apparatus.",
        "mechanisms": [
            {
                "mechanism_id": "response_scaling",
                "statement": "The response scales with the controlled input.",
                "equations": ["y = a x"],
                "variable_names": ["input_x", "response_y"],
                "parameters": [
                    {
                        "name": "scale",
                        "value": 2.0,
                        "uncertainty": "source_unspecified",
                        "unit": "a.u.",
                        "role": "Fitted proportionality coefficient.",
                        "anchors": [_anchor(1)],
                    }
                ],
                "anchors": [_anchor(1)],
            }
        ],
        "fixed_conditions": [
            {
                "condition_id": "fixed_temperature",
                "statement": "Temperature is held fixed.",
                "anchors": [_anchor(4)],
            }
        ],
        "controls": [
            {
                "name": "input_x",
                "definition": "The numeric input manipulated by the study.",
                "unit": "a.u.",
                "minimum": 1.0,
                "maximum": 9.0,
                "anchors": [_anchor(2)],
            }
        ],
        "readouts": [
            {
                "name": "response_y",
                "definition": "The measured response.",
                "unit": "a.u.",
                "statistic": "Ensemble mean.",
                "uncertainty": "source_unspecified",
                "resolution": {
                    "value": 0.01,
                    "kind": "reporting_increment",
                    "anchors": [_anchor(3)],
                },
                "anchors": [_anchor(3)],
            }
        ],
        "claims": [
            {
                "claim_id": "mechanistic_prediction",
                "statement": "The mechanism predicts a linear response.",
                "quantitative_form": "response_y is proportional to input_x.",
                "oracle_outputs": {
                    "response_y": {
                        "op": "multiply",
                        "args": [
                            {"param": "scale"},
                            {"var": "input_x"},
                        ],
                    }
                },
                "mechanism_ids": ["response_scaling"],
                "control_names": ["input_x"],
                "control_domains": [
                    {
                        "control_name": "input_x",
                        "minimum": 1.0,
                        "maximum": 9.0,
                        "anchors": [_anchor(2)],
                    }
                ],
                "readout_names": ["response_y"],
                "fixed_condition_ids": ["fixed_temperature"],
                "applicability": "For input_x between 1 and 9 a.u.",
                "statistical_basis": "A theoretical mechanism.",
                "uncertainty": "No uncertainty is assigned to the prediction.",
                "depends_on": [],
                "anchors": [_anchor(1)],
            },
            {
                "claim_id": "reported_fit",
                "statement": "The fitted response agrees with the mechanism.",
                "quantitative_form": "response_y = 2.0 input_x.",
                "oracle_outputs": {
                    "response_y": {
                        "op": "multiply",
                        "args": [
                            {"param": "scale"},
                            {"var": "input_x"},
                        ],
                    }
                },
                "mechanism_ids": ["response_scaling"],
                "control_names": ["input_x"],
                "control_domains": [
                    {
                        "control_name": "input_x",
                        "minimum": 1.0,
                        "maximum": 9.0,
                        "anchors": [_anchor(2)],
                    }
                ],
                "readout_names": ["response_y"],
                "fixed_condition_ids": ["fixed_temperature"],
                "applicability": "For input_x between 1 and 9 a.u.",
                "statistical_basis": "An ensemble-mean fit.",
                "uncertainty": "The source does not identify the fit uncertainty.",
                "depends_on": ["mechanistic_prediction"],
                "anchors": [_anchor(5)],
            },
        ],
        "source_ambiguities": [
            {
                "ambiguity_id": "uncertainty_semantics",
                "statement": "The source does not define the reported fit uncertainty.",
                "claim_ids": ["reported_fit"],
                "mechanism_ids": ["response_scaling"],
                "control_names": ["input_x"],
                "readout_names": ["response_y"],
                "fixed_condition_ids": ["fixed_temperature"],
                "anchors": [_anchor(5)],
            }
        ],
    }


class _FakeBackend:
    def __init__(self, payload=None, *, text=None, finish_reason="stop"):
        self.payload = payload
        self.text = text
        self.finish_reason = finish_reason
        self.requests = []

    def generate(self, request):
        self.requests.append(request)
        text = self.text if self.text is not None else json.dumps(self.payload)
        return GenerationResponse(
            text=text,
            provider="fake",
            model="fake-science-card",
            finish_reason=self.finish_reason,
        )


class _QueuedBackend:
    def __init__(self, payloads):
        self.payloads = list(payloads)
        self.requests = []

    def generate(self, request):
        self.requests.append(request)
        if not self.payloads:
            raise AssertionError("science-card extraction made an extra call")
        payload = self.payloads.pop(0)
        text = payload if isinstance(payload, str) else json.dumps(payload)
        return GenerationResponse(
            text=text,
            provider="fake",
            model="fake-science-card",
            finish_reason="stop",
        )


class TemporalScienceCardTests(unittest.TestCase):
    def test_mechanical_repair_allowlist_is_explicit_and_narrow(self):
        self.assertEqual(
            RETRYABLE_SCIENCE_CARD_ERROR_CODES,
            {"science_card.schema", "science_card.locator"},
        )

    def test_valid_card_round_trips_through_strict_payload(self):
        card = parse_science_card_json(
            json.dumps(_card_payload()), require_oracle_outputs=True
        )
        self.assertTrue(card.case_authoring_ready)
        self.assertEqual(card.claims[1].depends_on, ("mechanistic_prediction",))
        self.assertEqual(
            card.claims[1].oracle_outputs["response_y"]["args"][0],
            {"param": "scale"},
        )
        self.assertEqual(
            parse_science_card_json(
                json.dumps(science_card_to_payload(card)),
                require_oracle_outputs=True,
            ),
            card,
        )

    def test_legacy_card_reading_is_explicitly_separate_from_strict_extraction(self):
        legacy = copy.deepcopy(_card_payload())
        for claim in legacy["claims"]:
            claim.pop("oracle_outputs")

        card = parse_science_card_json(json.dumps(legacy))
        self.assertTrue(card.case_authoring_ready)
        self.assertTrue(all(item.oracle_outputs is None for item in card.claims))
        self.assertNotIn(
            "oracle_outputs", science_card_to_payload(card)["claims"][0]
        )

        with self.assertRaises(ScienceCardError) as raised:
            parse_science_card_json(
                json.dumps(legacy), require_oracle_outputs=True
            )
        self.assertEqual(raised.exception.path, "$.claims[0].oracle_outputs")
        self.assertIn("authoring-ready", raised.exception.detail)

    def test_claim_oracle_outputs_are_bound_to_claim_resources(self):
        mutations = []

        wrong_output = copy.deepcopy(_card_payload())
        wrong_output["claims"][0]["oracle_outputs"] = {
            "other_readout": {"var": "input_x"}
        }
        mutations.append((wrong_output, "readouts exactly"))

        wrong_variable = copy.deepcopy(_card_payload())
        wrong_variable["claims"][0]["oracle_outputs"]["response_y"] = {
            "var": "other_control"
        }
        mutations.append((wrong_variable, "not a public control"))

        unlinked_parameter = copy.deepcopy(_card_payload())
        other_mechanism = copy.deepcopy(unlinked_parameter["mechanisms"][0])
        other_mechanism["mechanism_id"] = "other_mechanism"
        other_mechanism["parameters"][0]["name"] = "other_scale"
        unlinked_parameter["mechanisms"].append(other_mechanism)
        unlinked_parameter["claims"][0]["oracle_outputs"]["response_y"] = {
            "param": "other_scale"
        }
        mutations.append((unlinked_parameter, "not an allowed parameter"))

        scientific_literal = copy.deepcopy(_card_payload())
        scientific_literal["claims"][0]["oracle_outputs"]["response_y"] = {
            "op": "multiply",
            "args": [2.0, {"var": "input_x"}],
        }
        mutations.append((scientific_literal, "numeric literal is not allowed"))

        invalid_arity = copy.deepcopy(_card_payload())
        invalid_arity["claims"][0]["oracle_outputs"]["response_y"] = {
            "op": "power",
            "args": [{"var": "input_x"}],
        }
        mutations.append((invalid_arity, "power requires 2 argument"))

        for payload, detail in mutations:
            with self.subTest(detail=detail):
                with self.assertRaises(ScienceCardError) as raised:
                    parse_science_card_json(
                        json.dumps(payload), require_oracle_outputs=True
                    )
                self.assertEqual(
                    raised.exception.path, "$.claims[0].oracle_outputs"
                )
                self.assertIn(detail, raised.exception.detail)

    def test_claim_oracle_outputs_forbid_all_numeric_literals(self):
        for literal in (0.0, 1.0, 2.0):
            with self.subTest(literal=literal):
                payload = copy.deepcopy(_card_payload())
                payload["claims"][0]["oracle_outputs"]["response_y"] = {
                    "op": "multiply",
                    "args": [literal, {"var": "input_x"}],
                }
                with self.assertRaises(ScienceCardError) as raised:
                    parse_science_card_json(
                        json.dumps(payload), require_oracle_outputs=True
                    )
                self.assertIn(
                    "numeric literal is not allowed", raised.exception.detail
                )

    def test_source_program_reserves_selector_compiler_headroom(self):
        def nested_negates(count):
            expression = {"param": "scale"}
            for _ in range(count):
                expression = {"op": "negate", "args": [expression]}
            return expression

        payload = copy.deepcopy(_card_payload())
        payload["claims"][0]["oracle_outputs"]["response_y"] = nested_negates(22)
        parse_science_card_json(
            json.dumps(payload), require_oracle_outputs=True
        )

        payload["claims"][0]["oracle_outputs"]["response_y"] = nested_negates(23)
        with self.assertRaises(ScienceCardError) as raised:
            parse_science_card_json(
                json.dumps(payload), require_oracle_outputs=True
            )
        self.assertIn("exceeds depth 22", raised.exception.detail)

    def test_schema_and_parser_reject_extra_or_duplicate_fields(self):
        schema = science_card_json_schema()
        self.assertFalse(schema["additionalProperties"])
        self.assertEqual(set(schema["required"]), set(schema["properties"]))
        self.assertEqual(
            schema["properties"]["mechanisms"]["items"]["properties"]
            ["mechanism_id"]["pattern"],
            "^[A-Za-z][A-Za-z0-9_]*$",
        )
        self.assertEqual(
            schema["properties"]["claims"]["items"]["properties"]["anchors"]
            ["minItems"],
            1,
        )
        claim_schema = schema["properties"]["claims"]["items"]
        self.assertIn("oracle_outputs", claim_schema["required"])
        self.assertEqual(
            claim_schema["properties"]["oracle_outputs"]["additionalProperties"],
            {"$ref": "#/$defs/science_expression"},
        )
        self.assertIn(
            "central-value control-to-readout relation",
            claim_schema["properties"]["oracle_outputs"]["description"],
        )
        readout_schema = schema["properties"]["readouts"]["items"]
        self.assertIn(
            "source data",
            readout_schema["properties"]["statistic"]["description"],
        )
        self.assertIn(
            "not per-query Oracle uncertainty",
            readout_schema["properties"]["uncertainty"]["description"],
        )
        self.assertFalse(
            any(
                item.get("type") == "number"
                for item in schema["$defs"]["science_expression"]["anyOf"]
            )
        )

        extra = _card_payload()
        extra["claims"][0]["unsupported_field"] = True
        with self.assertRaises(ScienceCardError) as raised:
            parse_science_card_json(json.dumps(extra))
        self.assertEqual(raised.exception.code, "science_card.schema")
        self.assertEqual(raised.exception.path, "$.claims[0]")

        with self.assertRaises(ScienceCardError) as duplicate:
            parse_science_card_json(
                '{"assessment":"first","assessment":"second"}'
            )
        self.assertEqual(duplicate.exception.code, "science_card.invalid_json")

    def test_source_significant_case_is_canonicalized_only_at_runtime_boundary(self):
        payload = _card_payload()
        payload["mechanisms"][0]["parameters"][0]["name"] = "E_i_Exponent_Tlow"
        for claim in payload["claims"]:
            claim["oracle_outputs"]["response_y"]["args"][0]["param"] = (
                "E_i_Exponent_Tlow"
            )
        card = parse_science_card_json(json.dumps(payload))
        self.assertEqual(
            canonical_science_name(card.mechanisms[0].parameters[0].name),
            "e_i_exponent_tlow",
        )

    def test_claim_and_ambiguity_references_must_exist(self):
        mutations = (
            ("mechanism_ids", ["missing_mechanism"]),
            ("control_names", ["missing_control"]),
            ("readout_names", ["missing_readout"]),
            ("fixed_condition_ids", ["missing_condition"]),
            ("depends_on", ["missing_claim"]),
        )
        for field, value in mutations:
            with self.subTest(field=field):
                payload = copy.deepcopy(_card_payload())
                payload["claims"][1][field] = value
                with self.assertRaises(ScienceCardError) as raised:
                    parse_science_card_json(json.dumps(payload))
                self.assertEqual(raised.exception.code, "science_card.schema")
                self.assertEqual(raised.exception.path, "$.claims[1]." + field)

        payload = copy.deepcopy(_card_payload())
        payload["source_ambiguities"][0]["claim_ids"] = ["missing_claim"]
        with self.assertRaises(ScienceCardError) as raised:
            parse_science_card_json(json.dumps(payload))
        self.assertEqual(raised.exception.path, "$.source_ambiguities[0].claim_ids")

    def test_claim_dependencies_must_form_a_dag(self):
        self_dependency = copy.deepcopy(_card_payload())
        self_dependency["claims"][0]["depends_on"] = ["mechanistic_prediction"]
        with self.assertRaises(ScienceCardError) as raised:
            parse_science_card_json(json.dumps(self_dependency))
        self.assertEqual(raised.exception.path, "$.claims[0].depends_on")

        cycle = copy.deepcopy(_card_payload())
        cycle["claims"][0]["depends_on"] = ["reported_fit"]
        with self.assertRaises(ScienceCardError) as raised:
            parse_science_card_json(json.dumps(cycle))
        self.assertEqual(raised.exception.path, "$.claims")
        self.assertIn("directed acyclic graph", raised.exception.detail)

    def test_claim_domains_and_readout_resolution_are_anchored_contracts(self):
        card = parse_science_card_json(json.dumps(_card_payload()))
        self.assertEqual(
            (
                card.claims[0].control_domains[0].minimum,
                card.claims[0].control_domains[0].maximum,
            ),
            (1.0, 9.0),
        )
        self.assertEqual(card.readouts[0].resolution.kind, "reporting_increment")
        self.assertEqual(card.readouts[0].resolution.anchors[0].line_start, 3)

        missing_domain = copy.deepcopy(_card_payload())
        missing_domain["claims"][0]["control_domains"] = []
        with self.assertRaises(ScienceCardError) as missing:
            parse_science_card_json(json.dumps(missing_domain))
        self.assertIn("exactly one source applicability domain", missing.exception.detail)

        wider_than_source = copy.deepcopy(_card_payload())
        wider_than_source["claims"][0]["control_domains"][0]["maximum"] = 10.0
        with self.assertRaises(ScienceCardError) as wider:
            parse_science_card_json(json.dumps(wider_than_source))
        self.assertIn("exceeds", wider.exception.detail)

        unsupported_resolution = copy.deepcopy(_card_payload())
        unsupported_resolution["readouts"][0]["resolution"]["kind"] = (
            "guessed_precision"
        )
        with self.assertRaises(ScienceCardError) as resolution:
            parse_science_card_json(json.dumps(unsupported_resolution))
        self.assertIn("measurement_resolution", resolution.exception.detail)

    def test_source_domains_preserve_interval_values_fixed_and_unknown_states(self):
        base = science_card_to_payload(
            parse_science_card_json(json.dumps(_card_payload()))
        )
        variants = (
            ("continuous_interval", 1.0, 9.0, [], ""),
            ("numeric_values", None, None, [1.0, 3.0, 9.0], "Reported settings."),
            ("fixed_value", None, None, [3.0], "One reported setting."),
            ("symbolic", None, None, [], "The source states x > x_c."),
            ("unreported", None, None, [], "No numeric applicability was reported."),
        )
        for kind, minimum, maximum, values, statement in variants:
            with self.subTest(kind=kind):
                payload = copy.deepcopy(base)
                for domain in (
                    payload["controls"][0],
                    payload["claims"][0]["control_domains"][0],
                    payload["claims"][1]["control_domains"][0],
                ):
                    domain["domain_kind"] = kind
                    domain["minimum"] = minimum
                    domain["maximum"] = maximum
                    domain["allowed_values"] = values
                    domain["domain_statement"] = statement
                card = parse_science_card_json(json.dumps(payload))
                self.assertEqual(card.controls[0].domain_kind, kind)
                self.assertEqual(card.controls[0].allowed_values, tuple(values))

        invalid = copy.deepcopy(base)
        invalid["controls"][0].update(
            {
                "domain_kind": "symbolic",
                "minimum": 1.0,
                "maximum": 9.0,
                "allowed_values": [],
                "domain_statement": "x > x_c",
            }
        )
        with self.assertRaises(ScienceCardError):
            parse_science_card_json(json.dumps(invalid))

    def test_extraction_enforces_authoritative_source_identity(self):
        backend = _FakeBackend(_card_payload())
        result = extract_science_card(
            backend,
            _SOURCE,
            source_citation=_CITATION,
            journal_doi=_DOI,
            arxiv_versioned_id=_ARXIV_ID,
        )
        self.assertEqual(result.card.source.journal_doi, _DOI)

        typographic_citation = _CITATION.replace("A. Author", "A.\u2009Author")
        typographic = extract_science_card(
            _FakeBackend(_card_payload()),
            _SOURCE,
            source_citation=typographic_citation,
            journal_doi=_DOI,
            arxiv_versioned_id=_ARXIV_ID,
        )
        self.assertEqual(typographic.card.source.citation, typographic_citation)

        wrong_source = copy.deepcopy(_card_payload())
        wrong_source["source"]["journal_doi"] = "10.0000/wrong"
        with self.assertRaises(ScienceCardError) as raised:
            extract_science_card(
                _FakeBackend(wrong_source),
                _SOURCE,
                source_citation=_CITATION,
                journal_doi=_DOI,
                arxiv_versioned_id=_ARXIV_ID,
            )
        self.assertEqual(raised.exception.code, "science_card.source_identity")
        self.assertEqual(raised.exception.path, "$.source")

    def test_extraction_requires_structured_outputs_for_a_ready_card(self):
        legacy = copy.deepcopy(_card_payload())
        for claim in legacy["claims"]:
            claim.pop("oracle_outputs")

        with self.assertRaises(ScienceCardError) as raised:
            extract_science_card(
                _FakeBackend(legacy),
                _SOURCE,
                source_citation=_CITATION,
                journal_doi=_DOI,
                arxiv_versioned_id=_ARXIV_ID,
            )
        self.assertEqual(raised.exception.path, "$.claims[0].oracle_outputs")

    def test_extraction_rejects_a_locator_beyond_model_visible_source(self):
        payload = copy.deepcopy(_card_payload())
        payload["claims"][1]["anchors"][0]["line_end"] = 6
        with self.assertRaises(ScienceCardError) as raised:
            extract_science_card(
                _FakeBackend(payload),
                _SOURCE,
                source_citation=_CITATION,
                journal_doi=_DOI,
                arxiv_versioned_id=_ARXIV_ID,
            )
        self.assertEqual(raised.exception.code, "science_card.locator")
        self.assertEqual(raised.exception.path, "$.claims[1].anchors[0]")
        self.assertIn("exceeds the 5-line model input", raised.exception.detail)

    def test_bounded_validation_repair_reuses_source_schema_and_error(self):
        invalid = copy.deepcopy(_card_payload())
        invalid["claims"][1]["mechanism_ids"] = ["missing_mechanism"]
        invalid_text = json.dumps(invalid)
        backend = _QueuedBackend((invalid_text, _card_payload()))

        result = extract_science_card(
            backend,
            _SOURCE,
            source_citation=_CITATION,
            journal_doi=_DOI,
            arxiv_versioned_id=_ARXIV_ID,
            max_total_attempts=2,
        )

        self.assertEqual(result.attempt_count, 2)
        self.assertEqual(len(backend.requests), 2)
        primary, repair = backend.requests
        self.assertEqual(repair.response_schema, primary.response_schema)
        self.assertEqual(repair.config, primary.config)
        self.assertEqual(repair.messages[:2], primary.messages)
        self.assertEqual(repair.metadata["generation_attempt"], 2)
        self.assertEqual(
            repair.metadata["repair_reason"],
            "science_card.schema",
        )
        repair_payload = json.loads(repair.messages[2].content)
        self.assertEqual(repair_payload["repair"]["previous_output"], invalid_text)
        self.assertIn(
            "bounded mechanical repair",
            repair_payload["repair"]["instruction"],
        )
        self.assertIn(
            "change only the field or fields needed",
            repair_payload["repair"]["instruction"],
        )
        self.assertIn(
            "do not invent a new scientific entity or fact",
            repair_payload["repair"]["instruction"],
        )
        self.assertEqual(
            repair_payload["repair"]["validation_error"],
            {
                "code": "science_card.schema",
                "detail": "unknown identifier(s): missing_mechanism",
                "path": "$.claims[1].mechanism_ids",
            },
        )

    def test_configured_two_call_limit_is_terminal(self):
        invalid = copy.deepcopy(_card_payload())
        invalid["claims"][1]["mechanism_ids"] = ["missing_mechanism"]
        backend = _QueuedBackend((invalid, invalid, _card_payload()))

        with self.assertRaises(ScienceCardError) as raised:
            extract_science_card(
                backend,
                _SOURCE,
                source_citation=_CITATION,
                journal_doi=_DOI,
                arxiv_versioned_id=_ARXIV_ID,
                max_total_attempts=2,
            )

        self.assertEqual(raised.exception.path, "$.claims[1].mechanism_ids")
        self.assertEqual(len(backend.requests), 2)
        self.assertEqual(len(backend.payloads), 1)

    def test_four_call_loop_repairs_serial_unknown_references(self):
        missing_mechanism = copy.deepcopy(_card_payload())
        missing_mechanism["claims"][1]["mechanism_ids"] = [
            "missing_mechanism"
        ]

        missing_control = copy.deepcopy(_card_payload())
        missing_control["claims"][1]["control_names"] = ["missing_control"]

        missing_parameter = copy.deepcopy(_card_payload())
        missing_parameter["claims"][1]["oracle_outputs"]["response_y"][
            "args"
        ][0] = {"param": "missing_scale"}

        corrected = _card_payload()
        outputs = (
            missing_mechanism,
            missing_control,
            missing_parameter,
            corrected,
        )
        backend = _QueuedBackend(outputs)
        result = extract_science_card(
            backend,
            _SOURCE,
            source_citation=_CITATION,
            journal_doi=_DOI,
            arxiv_versioned_id=_ARXIV_ID,
            max_total_attempts=4,
        )

        self.assertEqual(result.attempt_count, 4)
        self.assertEqual(len(backend.requests), 4)
        expected_paths = (
            "$.claims[1].mechanism_ids",
            "$.claims[1].control_names",
            "$.claims[1].oracle_outputs",
        )
        primary = backend.requests[0]
        for attempt_number, (request, previous, expected_path) in enumerate(
            zip(backend.requests[1:], outputs, expected_paths),
            start=2,
        ):
            self.assertEqual(request.messages[:2], primary.messages)
            self.assertEqual(len(request.messages), 3)
            repair = json.loads(request.messages[2].content)["repair"]
            self.assertEqual(
                set(repair),
                {"instruction", "previous_output", "validation_error"},
            )
            self.assertEqual(repair["previous_output"], json.dumps(previous))
            self.assertEqual(
                repair["validation_error"]["code"], "science_card.schema"
            )
            self.assertEqual(
                repair["validation_error"]["path"], expected_path
            )
            self.assertEqual(
                request.metadata["generation_attempt"], attempt_number
            )
            self.assertEqual(
                request.metadata["repair_reason"], "science_card.schema"
            )
        self.assertEqual(backend.payloads, [])

    def test_fourth_mechanical_failure_is_terminal(self):
        invalid = copy.deepcopy(_card_payload())
        invalid["claims"][1]["mechanism_ids"] = ["missing_mechanism"]
        backend = _QueuedBackend((invalid, invalid, invalid, invalid, _card_payload()))

        with self.assertRaises(ScienceCardError) as raised:
            extract_science_card(
                backend,
                _SOURCE,
                source_citation=_CITATION,
                journal_doi=_DOI,
                arxiv_versioned_id=_ARXIV_ID,
                max_total_attempts=4,
            )

        self.assertEqual(raised.exception.code, "science_card.schema")
        self.assertEqual(len(backend.requests), 4)
        self.assertEqual(len(backend.payloads), 1)

    def test_locator_error_is_mechanically_repairable(self):
        invalid = copy.deepcopy(_card_payload())
        invalid["claims"][1]["anchors"][0]["line_end"] = 6
        backend = _QueuedBackend((invalid, _card_payload()))

        result = extract_science_card(
            backend,
            _SOURCE,
            source_citation=_CITATION,
            journal_doi=_DOI,
            arxiv_versioned_id=_ARXIV_ID,
            max_total_attempts=2,
        )

        self.assertEqual(result.attempt_count, 2)
        repair = backend.requests[1]
        self.assertEqual(repair.metadata["repair_reason"], "science_card.locator")
        diagnostic = json.loads(repair.messages[2].content)["repair"][
            "validation_error"
        ]
        self.assertEqual(diagnostic["code"], "science_card.locator")
        self.assertEqual(diagnostic["path"], "$.claims[1].anchors[0]")

    def test_invalid_json_and_source_identity_are_not_repaired(self):
        wrong_source = copy.deepcopy(_card_payload())
        wrong_source["source"]["journal_doi"] = "10.0000/wrong"
        for first, expected_code in (
            ("not json", "science_card.invalid_json"),
            (wrong_source, "science_card.source_identity"),
        ):
            with self.subTest(expected_code=expected_code):
                backend = _QueuedBackend((first, _card_payload()))
                with self.assertRaises(ScienceCardError) as raised:
                    extract_science_card(
                        backend,
                        _SOURCE,
                        source_citation=_CITATION,
                        journal_doi=_DOI,
                        arxiv_versioned_id=_ARXIV_ID,
                        max_total_attempts=4,
                    )
                self.assertEqual(raised.exception.code, expected_code)
                self.assertEqual(len(backend.requests), 1)
                self.assertEqual(len(backend.payloads), 1)

    def test_max_total_attempts_is_bounded(self):
        for value in (True, 0, 5, 1.5):
            with self.subTest(value=value), self.assertRaises(ValueError):
                extract_science_card(
                    _FakeBackend(_card_payload()),
                    _SOURCE,
                    source_citation=_CITATION,
                    journal_doi=_DOI,
                    arxiv_versioned_id=_ARXIV_ID,
                    max_total_attempts=value,
                )

    def test_incomplete_generation_does_not_trigger_validation_repair(self):
        backend = _FakeBackend(text="not json", finish_reason="length")
        with self.assertRaises(ScienceCardError) as raised:
            extract_science_card(
                backend,
                _SOURCE,
                source_citation=_CITATION,
                journal_doi=_DOI,
                arxiv_versioned_id=_ARXIV_ID,
                max_total_attempts=4,
            )
        self.assertEqual(
            raised.exception.code,
            "science_card.incomplete_generation",
        )
        self.assertEqual(len(backend.requests), 1)

    def test_request_contains_canonical_schema_and_line_numbered_source(self):
        request = build_science_card_request(
            _SOURCE,
            source_citation=_CITATION,
            journal_doi=_DOI,
            arxiv_versioned_id=_ARXIV_ID,
        )
        self.assertEqual(request.metadata["purpose"], "temporal_science_card")
        self.assertIn(
            "ScienceCard JSON Schema:\n"
            + canonical_json_dumps(request.response_schema),
            request.messages[0].content,
        )
        self.assertIn(
            "statistical provenance, not physical fixed conditions",
            request.messages[0].content,
        )
        self.assertIn(
            "These fields describe the source data",
            request.messages[0].content,
        )
        self.assertIn(
            "not uncertainty on each deterministic query result",
            request.messages[0].content,
        )
        self.assertIn(
            "continuous_interval => numeric minimum",
            request.messages[0].content,
        )
        self.assertIn(
            "missing metadata, not a contradiction",
            request.messages[0].content,
        )
        self.assertIn(
            "claim.oracle_outputs using the supplied expression AST",
            request.messages[0].content,
        )
        self.assertIn(
            "Numeric literals are forbidden in ScienceClaim oracle_outputs",
            request.messages[0].content,
        )
        user = request.messages[1].content
        self.assertIn("L000001\tThe response follows", user)
        self.assertIn("L000005\tA fitted claim", user)
        self.assertNotIn("L000006\t", user)
        self.assertIn(_CITATION, user)
        self.assertIn(_DOI, user)
        self.assertIn(_ARXIV_ID, user)

    def test_optional_focus_routes_but_keeps_source_authoritative(self):
        request = build_science_card_request(
            _SOURCE,
            source_citation=_CITATION,
            journal_doi=_DOI,
            arxiv_versioned_id=_ARXIV_ID,
            authoring_focus="Inspect the two source-reported pore-length regimes.",
        )
        user = request.messages[1].content
        self.assertIn("Source-grounded routing hint", user)
        self.assertIn("two source-reported pore-length regimes", user)
        self.assertIn("source remains the sole authority", user)
        self.assertLess(user.index("routing hint"), user.index("L000001"))

    def test_optional_focus_must_be_non_empty(self):
        with self.assertRaisesRegex(ValueError, "non-empty"):
            build_science_card_request(
                _SOURCE,
                source_citation=_CITATION,
                journal_doi=_DOI,
                arxiv_versioned_id=_ARXIV_ID,
                authoring_focus="   ",
            )

    def test_review_revision_context_preserves_prior_card_and_source_authority(self):
        previous = _card_payload()
        request = build_science_card_request(
            _SOURCE,
            source_citation=_CITATION,
            journal_doi=_DOI,
            arxiv_versioned_id=_ARXIV_ID,
            authoring_focus="Inspect the reported response pair.",
            previous_science_card=previous,
            review_guidance_issues=[
                {
                    "code": "card.wrong_domain",
                    "detail": "Recheck the claim domain against the source.",
                    "line_ranges": [{"line_start": 2, "line_end": 4}],
                }
            ],
        )
        user = request.messages[1].content
        self.assertIn("Source-grounded routing hint", user)
        self.assertIn("Revision context from an independent review", user)
        self.assertIn('"previous_science_card":', user)
        self.assertIn('"paper_scope":"A controlled response', user)
        self.assertIn('"code":"card.wrong_domain"', user)
        self.assertIn('"line_start":2', user)
        self.assertIn("editable rejected draft", user)
        self.assertIn("Address every listed issue", user)
        self.assertIn("supplied source remains the sole authority", user)
        self.assertIn("Final revision checklist (routing context, not evidence)", user)
        self.assertIn("Do not copy any rejected draft text", user)
        self.assertNotIn("reviewer", user)
        self.assertLess(user.index("Revision context"), user.index("L000001"))
        self.assertGreater(user.index("Final revision checklist"), user.index("L000005"))

    def test_review_guidance_requires_nonempty_strict_issue_objects(self):
        with self.assertRaisesRegex(ValueError, "must not be empty"):
            build_science_card_request(
                _SOURCE,
                source_citation=_CITATION,
                journal_doi=_DOI,
                arxiv_versioned_id=_ARXIV_ID,
                previous_science_card=_card_payload(),
                review_guidance_issues=[],
            )
        with self.assertRaisesRegex(ValueError, "exactly code"):
            build_science_card_request(
                _SOURCE,
                source_citation=_CITATION,
                journal_doi=_DOI,
                arxiv_versioned_id=_ARXIV_ID,
                previous_science_card=_card_payload(),
                review_guidance_issues=[
                    {
                        "code": "card.issue",
                        "detail": "Check it.",
                        "line_ranges": [{"line_start": 1, "line_end": 1}],
                        "assessment": "must not be routed",
                    }
                ],
            )
        with self.assertRaisesRegex(ValueError, "must be provided together"):
            build_science_card_request(
                _SOURCE,
                source_citation=_CITATION,
                journal_doi=_DOI,
                arxiv_versioned_id=_ARXIV_ID,
                review_guidance_issues=[
                    {
                        "code": "card.issue",
                        "detail": "Check it.",
                        "line_ranges": [{"line_start": 1, "line_end": 1}],
                    }
                ],
            )

    def test_incomplete_generation_is_rejected_before_json_parsing(self):
        for finish_reason in ("length", "incomplete:max_output_tokens"):
            with self.subTest(finish_reason=finish_reason):
                with self.assertRaises(ScienceCardError) as raised:
                    extract_science_card(
                        _FakeBackend(text="not json", finish_reason=finish_reason),
                        _SOURCE,
                        source_citation=_CITATION,
                        journal_doi=_DOI,
                        arxiv_versioned_id=_ARXIV_ID,
                    )
                self.assertEqual(
                    raised.exception.code,
                    "science_card.incomplete_generation",
                )


if __name__ == "__main__":
    unittest.main()
