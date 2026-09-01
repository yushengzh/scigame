from __future__ import annotations

import copy
import json
import unittest
from dataclasses import replace
from pathlib import Path

from role_benchmark import (
    BenchmarkTrack,
    CaseOracle,
    Episode,
    ExperimentProposal,
    GenerationResponse,
    OracleStatus,
)
from role_benchmark.cases.matched import make_matched_case, truth_submission
from role_benchmark.temporal.author import (
    CaseDraftError,
    EXECUTABLE_ORACLE_STATISTIC,
    EXECUTABLE_ORACLE_UNCERTAINTY,
    RelationshipTarget,
    _canonical_relationship_shape,
    _direct_branch_parameter_contract,
    _direction,
    _relationship_witness,
    author_case_draft,
    bind_enumerated_condition_partitions,
    bind_reviewed_fixed_conditions,
    bind_reviewed_lineage,
    bind_reviewed_oracle,
    build_case_draft_request,
    case_draft_batch_json_schema,
    case_draft_batch_to_payload,
    condition_partition_bindings_to_payload,
    parse_case_draft_batch_payload,
    validate_case_draft_batch,
)
from role_benchmark.temporal.candidate import parse_candidate_payload
from role_benchmark.temporal.filter import filter_candidate
from role_benchmark.temporal.render import (
    build_identification_contract,
    build_matched_spec,
    render_candidate_module,
)
from role_benchmark.temporal.science_card import (
    parse_science_card_payload,
    science_card_to_payload,
)
from role_benchmark.temporal.warmup import (
    WarmupContractError,
    assess_family_source_closure,
    family_review_request_payload,
    parse_family_source_review_payload,
)
from role_benchmark.wire import canonical_json_dumps, episode_view_to_payload


def _anchor(line_start: int, line_end: int, support: str):
    return {
        "line_start": line_start,
        "line_end": line_end,
        "support": support,
    }


def _science_card_payload(*, ready: bool = True):
    return {
        "assessment": (
            "The paper reports two regimes of the same controlled response."
        ),
        "case_authoring_ready": ready,
        "source": {
            "citation": "A. Author et al., Example Journal (2026)",
            "journal_doi": "10.0000/example",
            "arxiv_versioned_id": "2607.01234v2",
        },
        "paper_scope": (
            "A fixed apparatus is operated in two reported regimes over the same "
            "input domain."
        ),
        "mechanisms": [
            {
                "mechanism_id": "reported_regime_response",
                "statement": (
                    "The selected reported regime determines whether the aggregate "
                    "response is linear or quadratic in the controlled input."
                ),
                "equations": [
                    "regime alpha: response = 2 * input_x",
                    "regime beta: response = 2 * input_x^2",
                ],
                "variable_names": ["input_x", "response"],
                "parameters": [
                    {
                        "name": "reported_scale",
                        "value": 2.0,
                        "uncertainty": "No coefficient uncertainty was reported.",
                        "unit": "dimensionless",
                        "role": "Common scale in both reported branches.",
                        "anchors": [
                            _anchor(12, 12, "Both equations report scale two.")
                        ],
                    },
                    {
                        "name": "alpha_exponent",
                        "value": 1.0,
                        "uncertainty": "No exponent uncertainty was reported.",
                        "unit": "dimensionless",
                        "role": "Exponent in reported regime alpha.",
                        "anchors": [
                            _anchor(13, 13, "Regime alpha is reported as linear.")
                        ],
                    },
                    {
                        "name": "beta_exponent",
                        "value": 2.0,
                        "uncertainty": "No exponent uncertainty was reported.",
                        "unit": "dimensionless",
                        "role": "Exponent in reported regime beta.",
                        "anchors": [
                            _anchor(14, 14, "Regime beta is reported as quadratic.")
                        ],
                    },
                ],
                "anchors": [
                    _anchor(10, 20, "The section defines both reported regimes.")
                ],
            }
        ],
        "fixed_conditions": [
            {
                "condition_id": "fixed_apparatus_state",
                "statement": "All apparatus settings other than input_x are fixed.",
                "anchors": [
                    _anchor(21, 22, "The apparatus state is held fixed.")
                ],
            }
        ],
        "controls": [
            {
                "name": "input_x",
                "definition": "The numeric input adjusted by the experimenter.",
                "unit": "a.u.",
                "minimum": 1.0,
                "maximum": 5.0,
                "anchors": [
                    _anchor(23, 24, "The reported input domain is one through five.")
                ],
            }
        ],
        "readouts": [
            {
                "name": "response",
                "definition": "The aggregate response reported by the apparatus.",
                "unit": "a.u.",
                "statistic": "Central aggregate response.",
                "uncertainty": "No observation-noise model was reported.",
                "resolution": {
                    "value": 0.01,
                    "kind": "reporting_increment",
                    "anchors": [
                        _anchor(25, 26, "The source reports response to hundredths.")
                    ],
                },
                "anchors": [
                    _anchor(25, 26, "The paper defines the aggregate response.")
                ],
            }
        ],
        "claims": [
            {
                "claim_id": "linear_regime_claim",
                "statement": "Regime alpha has a linear input-response relation.",
                "quantitative_form": "response = 2 * input_x",
                "oracle_outputs": {
                    "response": {
                        "op": "multiply",
                        "args": [
                            {"param": "reported_scale"},
                            {
                                "op": "power",
                                "args": [
                                    {"var": "input_x"},
                                    {"param": "alpha_exponent"},
                                ],
                            },
                        ],
                    }
                },
                "mechanism_ids": ["reported_regime_response"],
                "control_names": ["input_x"],
                "control_domains": [
                    {
                        "control_name": "input_x",
                        "minimum": 1.0,
                        "maximum": 5.0,
                        "anchors": [
                            _anchor(23, 24, "The branch uses the reported domain.")
                        ],
                    }
                ],
                "readout_names": ["response"],
                "fixed_condition_ids": ["fixed_apparatus_state"],
                "applicability": "Reported for input_x from one through five.",
                "statistical_basis": "Central aggregate response.",
                "uncertainty": "No observation-noise model was reported.",
                "depends_on": [],
                "anchors": [
                    _anchor(30, 32, "The first reported branch is linear.")
                ],
            },
            {
                "claim_id": "quadratic_regime_claim",
                "statement": "Regime beta has a quadratic input-response relation.",
                "quantitative_form": "response = 2 * input_x^2",
                "oracle_outputs": {
                    "response": {
                        "op": "multiply",
                        "args": [
                            {"param": "reported_scale"},
                            {
                                "op": "power",
                                "args": [
                                    {"var": "input_x"},
                                    {"param": "beta_exponent"},
                                ],
                            },
                        ],
                    }
                },
                "mechanism_ids": ["reported_regime_response"],
                "control_names": ["input_x"],
                "control_domains": [
                    {
                        "control_name": "input_x",
                        "minimum": 1.0,
                        "maximum": 5.0,
                        "anchors": [
                            _anchor(23, 24, "The branch uses the reported domain.")
                        ],
                    }
                ],
                "readout_names": ["response"],
                "fixed_condition_ids": ["fixed_apparatus_state"],
                "applicability": "Reported for input_x from one through five.",
                "statistical_basis": "Central aggregate response.",
                "uncertainty": "No observation-noise model was reported.",
                "depends_on": [],
                "anchors": [
                    _anchor(33, 35, "The second reported branch is quadratic.")
                ],
            },
        ],
        "source_ambiguities": [],
    }


def _candidate_payload():
    selector = {"param": "regime_selector"}
    return {
        "family": "reported_regime_response",
        "title": "the controlled aggregate response",
        "claim": (
            "The source reports linear and quadratic branches over one common "
            "control domain."
        ),
        "source": {
            "citation": "A. Author et al., Example Journal (2026)",
            "journal_doi": "10.0000/example",
            "arxiv_versioned_id": "2607.01234v2",
            "locator": "Lines 10-35",
            "role": "The two reported branch equations define both worlds.",
        },
        "apparatus": {
            "name": "aggregate_response_apparatus",
            "description": (
                "A fixed apparatus with one adjustable input and one aggregate "
                "readout."
            ),
        },
        "background": (
            "A fixed apparatus produces an aggregate response when its available "
            "input is adjusted. Determine the input-response relationship."
        ),
        "initial_observations": [
            "The apparatus returns a reproducible aggregate response."
        ],
        "common_fixed_conditions": [
            {
                "condition_id": "fixed_apparatus_state",
                "statement": "All apparatus settings other than input_x are fixed.",
            }
        ],
        "controls": [
            {
                "name": "input_x",
                "description": "The adjustable numeric input.",
                "unit": "a.u.",
                "minimum": 1.0,
                "maximum": 5.0,
            }
        ],
        "readouts": [
            {
                "name": "response",
                "description": "The central aggregate response.",
                "unit": "a.u.",
                "statistic": EXECUTABLE_ORACLE_STATISTIC,
                "uncertainty": EXECUTABLE_ORACLE_UNCERTAINTY,
                "resolution": 0.01,
                "resolution_kind": "reporting_increment",
            }
        ],
        "oracle": {
            "kind": "closed_form",
            "outputs": {
                "response": {
                    "op": "add",
                    "args": [
                        {
                            "op": "multiply",
                            "args": [
                                {
                                    "op": "subtract",
                                    "args": [1.0, selector],
                                },
                                {"param": "reported_scale"},
                                {
                                    "op": "power",
                                    "args": [
                                        {"var": "input_x"},
                                        {"param": "alpha_exponent"},
                                    ],
                                },
                            ],
                        },
                        {
                            "op": "multiply",
                            "args": [
                                selector,
                                {"param": "reported_scale"},
                                {
                                    "op": "power",
                                    "args": [
                                        {"var": "input_x"},
                                        {"param": "beta_exponent"},
                                    ],
                                },
                            ],
                        },
                    ],
                }
            },
            "paper_parameters": {
                "regime_selector": 0.0,
                "reported_scale": 2.0,
                "alpha_exponent": 1.0,
                "beta_exponent": 2.0,
            },
            "counterfactual_parameters": {
                "regime_selector": 1.0,
                "reported_scale": 2.0,
                "alpha_exponent": 1.0,
                "beta_exponent": 2.0,
            },
            "paper_applicability": [
                "Reported for input_x from one through five."
            ],
            "counterfactual_applicability": [
                "Reported for input_x from one through five."
            ],
            "paper_fixed_conditions": [],
            "counterfactual_fixed_conditions": [],
        },
        "diagnostic_conditions": [{"input_x": 1.0}, {"input_x": 5.0}],
        "hidden_conditions": [{"input_x": 2.0}, {"input_x": 4.0}],
        "budget": 4,
        "max_replicates": 1,
        "confidence_threshold": 0.9,
        "relative_tolerance": 0.05,
        "notes": ["All unlisted apparatus settings remain fixed."],
        "counterfactual_change": (
            "Only regime_selector changes to select the other branch reported "
            "by the same source."
        ),
    }


def _trace(items, claim_ids, line_ranges, *, fixed_condition_ids=()):
    return {
        "items": list(items),
        "claim_ids": list(claim_ids),
        "mechanism_ids": ["reported_regime_response"],
        "fixed_condition_ids": list(fixed_condition_ids),
        "line_ranges": [
            {"line_start": start, "line_end": end}
            for start, end in line_ranges
        ],
    }


def _public_trace(
    field,
    line_ranges,
    *,
    claim_ids=(),
    mechanism_ids=(),
    fixed_condition_ids=(),
):
    return {
        "field": field,
        "claim_ids": list(claim_ids),
        "mechanism_ids": list(mechanism_ids),
        "fixed_condition_ids": list(fixed_condition_ids),
        "line_ranges": [
            {"line_start": start, "line_end": end}
            for start, end in line_ranges
        ],
    }


def _authored_payload():
    return {
        "assessment": (
            "The two source-reported regimes support one matched family."
        ),
        "status": "authored",
        "drafts": [
            {
                "design_summary": (
                    "One selector chooses between the two source-reported branches."
                ),
                "information_boundary": {
                    "shared_player": [
                        _public_trace(
                            "title",
                            [(30, 32), (33, 35)],
                            claim_ids=(
                                "linear_regime_claim",
                                "quadratic_regime_claim",
                            ),
                        ),
                        _public_trace(
                            "background",
                            [(10, 20)],
                            mechanism_ids=("reported_regime_response",),
                        ),
                        _public_trace(
                            "apparatus",
                            [(10, 20)],
                            mechanism_ids=("reported_regime_response",),
                        ),
                        _public_trace(
                            "control.input_x",
                            [(23, 24)],
                            claim_ids=(
                                "linear_regime_claim",
                                "quadratic_regime_claim",
                            ),
                        ),
                        _public_trace(
                            "readout.response",
                            [(25, 26)],
                            claim_ids=(
                                "linear_regime_claim",
                                "quadratic_regime_claim",
                            ),
                        ),
                        _public_trace(
                            "initial_observation.0",
                            [(10, 20)],
                            mechanism_ids=("reported_regime_response",),
                        ),
                        _public_trace(
                            "fixed_condition.fixed_apparatus_state",
                            [(21, 22)],
                            fixed_condition_ids=("fixed_apparatus_state",),
                        ),
                        _public_trace(
                            "note.0",
                            [(21, 22)],
                            fixed_condition_ids=("fixed_apparatus_state",),
                        ),
                    ],
                    "identification_only": _trace(
                        [
                            "The shared source-defined power-law response scaffold "
                            "with world-neutral scalar parameter slots."
                        ],
                        ["linear_regime_claim", "quadratic_regime_claim"],
                        [(30, 32), (33, 35)],
                    ),
                    "oracle_only": _trace(
                        [
                            "The two exact reported equations and the private active "
                            "branch."
                        ],
                        ["linear_regime_claim", "quadratic_regime_claim"],
                        [(10, 20), (30, 32), (33, 35)],
                    ),
                },
                "counterfactual_derivation": {
                    "kind": "reported_regime_selection",
                    "description": (
                        "The selector switches between the two equations explicitly "
                        "reported by the source."
                    ),
                    "source_claim_ids": [
                        "linear_regime_claim",
                        "quadratic_regime_claim",
                    ],
                    "paper_claim_ids": ["linear_regime_claim"],
                    "counterfactual_claim_ids": ["quadratic_regime_claim"],
                    "source_mechanism_ids": ["reported_regime_response"],
                    "selector_parameter": "regime_selector",
                    "historical_value": 0.0,
                    "counterfactual_value": 1.0,
                    "paper_defined_equations_unchanged": True,
                },
                "relationship_targets": [
                    {
                        "control": "input_x",
                        "readout": "response",
                        "historical_direction": "increasing",
                        "counterfactual_direction": "increasing",
                        "historical_shape": "linear over the reported domain",
                        "counterfactual_shape": "quadratic over the reported domain",
                        "source_claim_ids": [
                            "linear_regime_claim",
                            "quadratic_regime_claim",
                        ],
                    }
                ],
                "candidate": _candidate_payload(),
            }
        ],
    }


def _scaffold_payload():
    payload = _authored_payload()
    boundary = payload["drafts"][0]["information_boundary"]
    for trace in boundary["shared_player"]:
        trace["line_ranges"] = []
    boundary["identification_only"]["line_ranges"] = []
    boundary["oracle_only"]["line_ranges"] = []
    oracle = payload["drafts"][0]["candidate"]["oracle"]
    oracle["outputs"] = {}
    oracle["paper_parameters"] = {}
    oracle["counterfactual_parameters"] = {}
    return payload


def _real_temporal_artifact(relative_paper_directory: str):
    paper_directory = (
        Path(__file__).resolve().parents[1]
        / "runs"
        / "temporal_window_2026-04-01_2026-06-30"
        / "generated_families"
        / relative_paper_directory
    )
    card = parse_science_card_payload(
        json.loads(
            (paper_directory / "reviewed_science_card.json").read_text(
                encoding="utf-8"
            )
        )
    )
    batch = parse_case_draft_batch_payload(
        json.loads((paper_directory / "draft.json").read_text(encoding="utf-8"))
    )
    source_review = json.loads(
        (paper_directory / "source_review.json").read_text(encoding="utf-8")
    )
    selected = source_review["selected_cluster"]
    branch_claim_ids = (
        tuple(selected["branch_a_claim_ids"]),
        tuple(selected["branch_b_claim_ids"]),
    )
    return card, batch, branch_claim_ids


def _direct_branch_parameter_card(shape: str):
    """Return a card whose branch laws differ at one anchored leaf only."""

    payload = copy.deepcopy(_science_card_payload())

    def parameter(name, value, role, line):
        return {
            "name": name,
            "value": value,
            "uncertainty": "No parameter uncertainty was reported.",
            "unit": "dimensionless",
            "role": role,
            "anchors": [_anchor(line, line, role)],
        }

    if shape == "aah":
        payload["mechanisms"] = [
            {
                "mechanism_id": "common_lyapunov_program",
                "statement": "Both regimes use the same Lyapunov expression.",
                "equations": ["L=max(0,x-2*pi*eta)"],
                "variable_names": ["input_x", "response"],
                "parameters": [
                    parameter("zero", 0.0, "The lower bound in max.", 11),
                    parameter("two_pi", 6.283185307179586, "The eta scale.", 12),
                ],
                "anchors": [_anchor(10, 12, "The common expression is reported.")],
            },
            {
                "mechanism_id": "eta_zero_regime",
                "statement": "The first reported regime sets eta to zero.",
                "equations": ["eta=0"],
                "variable_names": ["eta"],
                "parameters": [
                    parameter("eta_zero", 0.0, "Eta in the first regime.", 13)
                ],
                "anchors": [_anchor(13, 13, "The zero-eta regime is reported.")],
            },
            {
                "mechanism_id": "eta_point_one_regime",
                "statement": "The second reported regime sets eta to one tenth.",
                "equations": ["eta=0.1"],
                "variable_names": ["eta"],
                "parameters": [
                    parameter(
                        "eta_point_one",
                        0.1,
                        "Eta in the second regime.",
                        14,
                    )
                ],
                "anchors": [_anchor(14, 14, "The nonzero-eta regime is reported.")],
            },
        ]

        def expression(eta_name):
            return {
                "op": "maximum",
                "args": [
                    {"param": "zero"},
                    {
                        "op": "subtract",
                        "args": [
                            {"var": "input_x"},
                            {
                                "op": "multiply",
                                "args": [
                                    {"param": "two_pi"},
                                    {"param": eta_name},
                                ],
                            },
                        ],
                    },
                ],
            }

        payload["claims"][0]["mechanism_ids"] = [
            "common_lyapunov_program",
            "eta_zero_regime",
        ]
        payload["claims"][0]["oracle_outputs"]["response"] = expression(
            "eta_zero"
        )
        payload["claims"][1]["mechanism_ids"] = [
            "common_lyapunov_program",
            "eta_point_one_regime",
        ]
        payload["claims"][1]["oracle_outputs"]["response"] = expression(
            "eta_point_one"
        )
    elif shape == "anderson":
        payload["mechanisms"] = [
            {
                "mechanism_id": "first_order_scaling",
                "statement": "The first regime has inverse-square scaling.",
                "equations": ["Y=q^-2"],
                "variable_names": ["input_x", "response"],
                "parameters": [
                    parameter(
                        "first_order_exponent",
                        -2.0,
                        "The first source-reported scaling exponent.",
                        13,
                    )
                ],
                "anchors": [_anchor(13, 13, "Inverse-square scaling is reported.")],
            },
            {
                "mechanism_id": "second_order_scaling",
                "statement": "The second regime has inverse-fourth scaling.",
                "equations": ["Y=q^-4"],
                "variable_names": ["input_x", "response"],
                "parameters": [
                    parameter(
                        "second_order_exponent",
                        -4.0,
                        "The second source-reported scaling exponent.",
                        14,
                    )
                ],
                "anchors": [_anchor(14, 14, "Inverse-fourth scaling is reported.")],
            },
        ]

        def expression(exponent_name):
            return {
                "op": "power",
                "args": [
                    {"var": "input_x"},
                    {"param": exponent_name},
                ],
            }

        payload["claims"][0]["mechanism_ids"] = ["first_order_scaling"]
        payload["claims"][0]["oracle_outputs"]["response"] = expression(
            "first_order_exponent"
        )
        payload["claims"][1]["mechanism_ids"] = ["second_order_scaling"]
        payload["claims"][1]["oracle_outputs"]["response"] = expression(
            "second_order_exponent"
        )
    else:
        raise ValueError("unknown direct-branch fixture")
    return parse_science_card_payload(payload)


def _mixed_case_interface_card():
    payload = copy.deepcopy(_science_card_payload())
    payload["controls"][0]["name"] = "M"
    payload["readouts"][0]["name"] = "L_over_L0"
    payload["mechanisms"][0]["variable_names"] = ["M", "L_over_L0"]
    for claim in payload["claims"]:
        claim["control_names"] = ["M"]
        claim["control_domains"][0]["control_name"] = "M"
        claim["readout_names"] = ["L_over_L0"]
        expression = claim["oracle_outputs"].pop("response")

        def rename_variables(node):
            if isinstance(node, dict) and set(node) == {"var"}:
                node["var"] = "M"
            elif isinstance(node, dict) and "args" in node:
                for argument in node["args"]:
                    rename_variables(argument)

        rename_variables(expression)
        claim["oracle_outputs"]["L_over_L0"] = expression
    return parse_science_card_payload(payload)


def _mapped_interface_scaffold_payload():
    payload = _scaffold_payload()
    draft = payload["drafts"][0]
    candidate = draft["candidate"]
    candidate["controls"][0]["name"] = "m"
    candidate["readouts"][0]["name"] = "l_over_l0"
    for conditions in (
        candidate["diagnostic_conditions"],
        candidate["hidden_conditions"],
    ):
        for condition in conditions:
            condition["m"] = condition.pop("input_x")
    target = draft["relationship_targets"][0]
    target["control"] = "m"
    target["readout"] = "l_over_l0"
    for trace in draft["information_boundary"]["shared_player"]:
        if trace["field"] == "control.input_x":
            trace["field"] = "control.m"
        elif trace["field"] == "readout.response":
            trace["field"] = "readout.l_over_l0"
    return payload


def _fixed_condition_binding_fixture():
    card_payload = _science_card_payload()
    card_payload["fixed_conditions"] = [
        {
            "condition_id": "COMMON_Second",
            "statement": "The secondary boundary setting remains fixed.",
            "anchors": [
                _anchor(20, 20, "The source states the second shared condition.")
            ],
        },
        {
            "condition_id": "COMMON_Setting",
            "statement": "The fixed geometry satisfies L_z = 2*pi and N = 1024.",
            "anchors": [
                _anchor(21, 21, "The source states the shared fixed geometry.")
            ],
        },
        {
            "condition_id": "ALPHA_Mode",
            "statement": "The alpha configuration is active.",
            "anchors": [
                _anchor(22, 22, "The source states the alpha configuration.")
            ],
        },
        {
            "condition_id": "BETA_Mode",
            "statement": "The beta configuration is active.",
            "anchors": [
                _anchor(27, 27, "The source states the beta configuration.")
            ],
        },
    ]
    card_payload["claims"][0]["fixed_condition_ids"] = [
        "COMMON_Setting",
        "ALPHA_Mode",
        "COMMON_Second",
    ]
    card_payload["claims"][1]["fixed_condition_ids"] = [
        "COMMON_Second",
        "COMMON_Setting",
        "BETA_Mode",
    ]
    card = parse_science_card_payload(card_payload)

    payload = _scaffold_payload()
    candidate = payload["drafts"][0]["candidate"]
    candidate["common_fixed_conditions"] = []
    candidate["oracle"]["paper_fixed_conditions"] = []
    candidate["oracle"]["counterfactual_fixed_conditions"] = []
    traces = payload["drafts"][0]["information_boundary"]["shared_player"]
    second_common_trace = None
    for trace in traces:
        if trace["field"] == "fixed_condition.fixed_apparatus_state":
            trace["field"] = "fixed_condition.common_setting"
            trace["fixed_condition_ids"] = ["COMMON_Setting"]
            second_common_trace = copy.deepcopy(trace)
            second_common_trace["field"] = "fixed_condition.common_second"
            second_common_trace["fixed_condition_ids"] = ["COMMON_Second"]
        elif trace["field"] == "note.0":
            trace["fixed_condition_ids"] = [
                "COMMON_Second",
                "COMMON_Setting",
            ]
    assert second_common_trace is not None
    traces.append(second_common_trace)
    payload["drafts"][0]["information_boundary"]["oracle_only"][
        "fixed_condition_ids"
    ] = ["ALPHA_Mode", "BETA_Mode"]
    return card, payload


class _FakeBackend:
    def __init__(self, payload):
        self.payload = payload
        self.requests = []

    def generate(self, request):
        self.requests.append(request)
        return GenerationResponse(
            text=json.dumps(self.payload),
            provider="fake",
            model="fake-case-author",
        )


class _QueuedBackend:
    def __init__(self, payloads):
        self.payloads = list(payloads)
        self.requests = []

    def generate(self, request):
        self.requests.append(request)
        if not self.payloads:
            raise AssertionError("case-draft authoring exceeded queued calls")
        payload = self.payloads.pop(0)
        text = payload if isinstance(payload, str) else json.dumps(payload)
        return GenerationResponse(
            text=text,
            provider="fake",
            model="fake-case-author",
            finish_reason="stop",
        )


class TemporalCaseAuthoringTests(unittest.TestCase):
    def setUp(self):
        self.card = parse_science_card_payload(_science_card_payload())

    def test_request_contains_only_the_science_card_not_latex(self):
        request = build_case_draft_request(self.card)
        self.assertEqual(request.metadata["purpose"], "temporal_case_authoring")
        self.assertEqual(request.metadata["source_mode"], "science_card_only")
        self.assertEqual(
            request.messages[1].content,
            "Private science card; this is the only scientific authority:\n"
            + canonical_json_dumps(science_card_to_payload(self.card))
            + "\nImmutable CaseDraft machine interface; use mapped values in every "
            "generated machine-interface position while leaving the ScienceCard "
            "above unchanged:\n"
            + canonical_json_dumps(
                {
                    "machine_interface_mapping": {
                        "immutable": True,
                        "controls": {"input_x": "input_x"},
                        "readouts": {"response": "response"},
                        "fixed_conditions": {
                            "fixed_apparatus_state": "fixed_apparatus_state",
                        },
                    }
                }
            ),
        )
        self.assertNotIn("\\documentclass", request.messages[1].content)
        self.assertNotIn("LaTeX source follows", request.messages[1].content)
        oracle_schema = request.response_schema["$defs"][
            "temporal_case_candidate"
        ]["properties"]["oracle"]["properties"]
        for field in (
            "outputs",
            "paper_parameters",
            "counterfactual_parameters",
        ):
            self.assertEqual(oracle_schema[field]["maxProperties"], 0)
        readout_schema = request.response_schema["$defs"][
            "temporal_case_candidate"
        ]["properties"]["readouts"]["items"]["properties"]
        self.assertEqual(
            readout_schema["statistic"]["enum"],
            [EXECUTABLE_ORACLE_STATISTIC],
        )
        self.assertEqual(
            readout_schema["uncertainty"]["enum"],
            [EXECUTABLE_ORACLE_UNCERTAINTY],
        )
        self.assertIn(
            "remain private provenance",
            request.messages[0].content,
        )
        self.assertIn("immutable machine_interface_mapping", request.messages[0].content)

        backend = _FakeBackend(_scaffold_payload())
        result = author_case_draft(backend, self.card)
        self.assertEqual(result.batch.status, "authored")
        self.assertEqual(
            result.batch.drafts[0].candidate.oracle.outputs,
            parse_candidate_payload(_candidate_payload()).oracle.outputs,
        )
        self.assertEqual(len(backend.requests), 1)
        self.assertEqual(
            backend.requests[0].messages[1].content,
            request.messages[1].content,
        )

    def test_reviewed_lineage_is_bound_from_ids_after_one_model_call(self):
        request = build_case_draft_request(self.card)
        boundary_schema = request.response_schema["properties"]["drafts"][
            "items"
        ]["properties"]["information_boundary"]["properties"]
        self.assertEqual(
            boundary_schema["shared_player"]["items"]["properties"][
                "line_ranges"
            ]["maxItems"],
            0,
        )
        self.assertEqual(
            boundary_schema["identification_only"]["properties"][
                "line_ranges"
            ]["maxItems"],
            0,
        )
        self.assertIn("Emit line_ranges as exactly []", request.messages[0].content)

        raw = _scaffold_payload()
        raw_boundary = raw["drafts"][0]["information_boundary"]
        self.assertTrue(
            all(not trace["line_ranges"] for trace in raw_boundary["shared_player"])
        )
        backend = _FakeBackend(raw)
        result = author_case_draft(backend, self.card)

        self.assertEqual(result.attempt_count, 1)
        self.assertEqual(len(backend.requests), 1)
        boundary = result.batch.drafts[0].information_boundary
        traces = {trace.field: trace for trace in boundary.shared_player}

        def pairs(trace):
            return tuple(
                (line_range.line_start, line_range.line_end)
                for line_range in trace.line_ranges
            )

        self.assertEqual(pairs(traces["title"]), ((30, 32), (33, 35)))
        self.assertEqual(pairs(traces["background"]), ((10, 20),))
        self.assertEqual(
            pairs(traces["control.input_x"]),
            ((23, 24), (30, 32), (33, 35)),
        )
        self.assertEqual(
            pairs(traces["readout.response"]),
            ((25, 26), (30, 32), (33, 35)),
        )
        self.assertEqual(
            pairs(boundary.identification_only),
            ((10, 20), (30, 32), (33, 35)),
        )
        self.assertEqual(
            traces["control.input_x"].claim_ids,
            ("linear_regime_claim", "quadratic_regime_claim"),
        )
        self.assertEqual(
            result.batch.drafts[0].design_summary,
            raw["drafts"][0]["design_summary"],
        )
        persisted = parse_case_draft_batch_payload(
            case_draft_batch_to_payload(result.batch)
        )
        validate_case_draft_batch(persisted, self.card)
        review_material = family_review_request_payload(
            result.batch.drafts[0], paper_id="paper_example"
        )["review_material"]
        review_traces = {
            trace["field"]: trace
            for trace in review_material["information_boundary"]["shared_player"]
        }
        self.assertEqual(
            review_traces["control.input_x"]["line_ranges"],
            [
                {"line_start": 23, "line_end": 24},
                {"line_start": 30, "line_end": 32},
                {"line_start": 33, "line_end": 35},
            ],
        )

    def test_reviewed_fixed_conditions_are_scaffolded_and_bound_exactly(self):
        card, payload = _fixed_condition_binding_fixture()
        partition = (
            ("linear_regime_claim",),
            ("quadratic_regime_claim",),
        )
        request = build_case_draft_request(
            card,
            reviewed_branch_claim_ids=partition,
        )
        candidate_schema = request.response_schema["$defs"][
            "temporal_case_candidate"
        ]
        self.assertEqual(
            candidate_schema["properties"]["common_fixed_conditions"][
                "maxItems"
            ],
            0,
        )
        oracle_schema = candidate_schema["properties"]["oracle"]["properties"]
        self.assertEqual(oracle_schema["paper_fixed_conditions"]["maxItems"], 0)
        self.assertEqual(
            oracle_schema["counterfactual_fixed_conditions"]["maxItems"], 0
        )
        self.assertIn(
            "Emit candidate.common_fixed_conditions",
            request.messages[0].content,
        )

        raw_candidate = payload["drafts"][0]["candidate"]
        raw_candidate["common_fixed_conditions"] = [
            {"condition_id": "invented", "statement": "Model-authored text."}
        ]
        raw_candidate["oracle"]["paper_fixed_conditions"] = [
            {"condition_id": "invented", "statement": "Wrong paper branch."}
        ]
        raw_candidate["oracle"]["counterfactual_fixed_conditions"] = [
            {"condition_id": "invented", "statement": "Wrong alternate branch."}
        ]
        result = author_case_draft(
            _FakeBackend(payload),
            card,
            reviewed_branch_claim_ids=partition,
        )
        candidate = result.batch.drafts[0].candidate
        self.assertEqual(
            tuple(
                (item.condition_id, item.statement)
                for item in candidate.common_fixed_conditions
            ),
            (
                ("common_second", "The secondary boundary setting remains fixed."),
                (
                    "common_setting",
                    "The fixed geometry satisfies L_z = 2*pi and N = 1024.",
                ),
            ),
        )
        self.assertEqual(
            tuple(
                (item.condition_id, item.statement)
                for item in candidate.oracle.paper_fixed_conditions
            ),
            (("alpha_mode", "The alpha configuration is active."),),
        )
        self.assertEqual(
            tuple(
                (item.condition_id, item.statement)
                for item in candidate.oracle.counterfactual_fixed_conditions
            ),
            (("beta_mode", "The beta configuration is active."),),
        )
        fixed_trace = next(
            trace
            for trace in result.batch.drafts[0].information_boundary.shared_player
            if trace.field == "fixed_condition.common_setting"
        )
        self.assertEqual(fixed_trace.fixed_condition_ids, ("COMMON_Setting",))

    def test_fixed_condition_binding_follows_whole_branch_swap(self):
        card, payload = _fixed_condition_binding_fixture()
        derivation = payload["drafts"][0]["counterfactual_derivation"]
        derivation["paper_claim_ids"] = ["quadratic_regime_claim"]
        derivation["counterfactual_claim_ids"] = ["linear_regime_claim"]
        partition = (
            ("linear_regime_claim",),
            ("quadratic_regime_claim",),
        )
        batch = bind_reviewed_fixed_conditions(
            parse_case_draft_batch_payload(payload),
            card,
            reviewed_branch_claim_ids=partition,
        )
        oracle = batch.drafts[0].candidate.oracle
        self.assertEqual(
            tuple(item.condition_id for item in oracle.paper_fixed_conditions),
            ("beta_mode",),
        )
        self.assertEqual(
            tuple(
                item.condition_id
                for item in oracle.counterfactual_fixed_conditions
            ),
            ("alpha_mode",),
        )

    def test_fixed_condition_binding_does_not_repair_bad_public_traces(self):
        card, payload = _fixed_condition_binding_fixture()
        partition = (
            ("linear_regime_claim",),
            ("quadratic_regime_claim",),
        )
        fixed_trace = next(
            trace
            for trace in payload["drafts"][0]["information_boundary"][
                "shared_player"
            ]
            if trace["field"] == "fixed_condition.common_setting"
        )
        fixed_trace["fixed_condition_ids"] = ["common_setting"]
        with self.assertRaises(CaseDraftError) as wrong_source_id:
            author_case_draft(
                _FakeBackend(payload),
                card,
                reviewed_branch_claim_ids=partition,
            )
        self.assertIn(
            wrong_source_id.exception.code,
            {"case_draft.schema", "case_draft.public_lineage"},
        )
        self.assertIn("exact condition", wrong_source_id.exception.detail)

        card, payload = _fixed_condition_binding_fixture()
        payload["drafts"][0]["information_boundary"]["shared_player"] = [
            trace
            for trace in payload["drafts"][0]["information_boundary"][
                "shared_player"
            ]
            if trace["field"] != "fixed_condition.common_setting"
        ]
        with self.assertRaises(CaseDraftError) as missing_trace:
            author_case_draft(
                _FakeBackend(payload),
                card,
                reviewed_branch_claim_ids=partition,
            )
        self.assertEqual(
            missing_trace.exception.code,
            "case_draft.public_lineage",
        )
        self.assertIn("fixed_condition.common_setting", missing_trace.exception.detail)

    def test_formula_condition_is_allowed_and_formula_note_is_neutralized(self):
        card, payload = _fixed_condition_binding_fixture()
        partition = (
            ("linear_regime_claim",),
            ("quadratic_regime_claim",),
        )
        author_case_draft(
            _FakeBackend(payload),
            card,
            reviewed_branch_claim_ids=partition,
        )

        payload["drafts"][0]["candidate"]["notes"] = [
            "The target response = 2 * input_x."
        ]
        result = author_case_draft(
            _FakeBackend(payload),
            card,
            reviewed_branch_claim_ids=partition,
        )
        self.assertEqual(
            result.batch.drafts[0].candidate.notes,
            ("Use only the stated controls, readouts, and fixed conditions.",),
        )
        self.assertEqual(
            result.prose_normalizations[0].path,
            "$.drafts[0].candidate.notes[0]",
        )
        self.assertEqual(
            json.loads(result.response.text)["drafts"][0]["candidate"][
                "notes"
            ][0],
            "The target response = 2 * input_x.",
        )

    def test_lineage_binding_does_not_repair_wrong_or_missing_ids(self):
        unknown = _scaffold_payload()
        unknown["drafts"][0]["information_boundary"]["shared_player"][0][
            "claim_ids"
        ] = ["unknown_claim"]
        with self.assertRaises(CaseDraftError) as unknown_error:
            author_case_draft(_FakeBackend(unknown), self.card)
        self.assertEqual(unknown_error.exception.code, "case_draft.schema")
        self.assertIn("unknown_claim", unknown_error.exception.detail)

        missing_branch = _scaffold_payload()
        control_trace = missing_branch["drafts"][0]["information_boundary"][
            "shared_player"
        ][3]
        control_trace["claim_ids"] = ["linear_regime_claim"]
        with self.assertRaises(CaseDraftError) as missing_error:
            author_case_draft(_FakeBackend(missing_branch), self.card)
        self.assertEqual(
            missing_error.exception.code,
            "case_draft.public_lineage",
        )
        self.assertIn("alternate branch domain claim", missing_error.exception.detail)

    def test_model_authored_locator_is_rejected_instead_of_canonicalized(self):
        payload = _scaffold_payload()
        payload["drafts"][0]["information_boundary"]["shared_player"][0][
            "line_ranges"
        ] = [{"line_start": 30, "line_end": 32}]

        with self.assertRaises(CaseDraftError) as raised:
            author_case_draft(_FakeBackend(payload), self.card)

        self.assertEqual(raised.exception.code, "case_draft.schema")
        self.assertIn("must be empty", raised.exception.detail)

    def test_request_maps_card_symbols_to_case_draft_machine_ids(self):
        card = _mixed_case_interface_card()
        request = build_case_draft_request(card)
        mapping = {
            "machine_interface_mapping": {
                "immutable": True,
                "controls": {"M": "m"},
                "readouts": {"L_over_L0": "l_over_l0"},
                "fixed_conditions": {
                    "fixed_apparatus_state": "fixed_apparatus_state",
                },
            }
        }
        self.assertIn(canonical_json_dumps(mapping), request.messages[1].content)
        self.assertIn(
            canonical_json_dumps(science_card_to_payload(card)),
            request.messages[1].content,
        )

        backend = _FakeBackend(_mapped_interface_scaffold_payload())
        result = author_case_draft(backend, card)

        draft = result.batch.drafts[0]
        self.assertEqual([item.name for item in draft.candidate.controls], ["m"])
        self.assertEqual(
            [item.name for item in draft.candidate.readouts], ["l_over_l0"]
        )
        self.assertEqual(
            (draft.relationship_targets[0].control, draft.relationship_targets[0].readout),
            ("m", "l_over_l0"),
        )
        self.assertEqual(set(draft.candidate.oracle.outputs), {"l_over_l0"})
        self.assertIn(
            '{"var": "m"}',
            json.dumps(draft.candidate.oracle.outputs, sort_keys=True),
        )

    def test_explicit_retry_request_carries_only_frozen_artifact_diagnostic(self):
        card = _mixed_case_interface_card()
        retry_error = CaseDraftError(
            "case_draft.public_lineage",
            "$.drafts[0].information_boundary.shared_player",
            "missing=['control.m']; extra=['control.M']",
        )

        request = build_case_draft_request(
            card,
            retry_artifact_error=retry_error,
        )

        retry_payload = {
            "case_draft_retry": {
                "frozen_original_failure": {
                    "code": retry_error.code,
                    "detail": retry_error.detail,
                    "path": retry_error.path,
                },
                "machine_interface_mapping": {
                    "immutable": True,
                    "controls": {"M": "m"},
                    "readouts": {"L_over_L0": "l_over_l0"},
                    "fixed_conditions": {
                        "fixed_apparatus_state": "fixed_apparatus_state",
                    },
                },
            }
        }
        self.assertIn(
            canonical_json_dumps(retry_payload),
            request.messages[1].content,
        )
        self.assertIn(
            "Correct only this structural/interface/field-lineage/public-prose error",
            request.messages[1].content,
        )
        self.assertIn(
            "All private scientific truth, quantities, source IDs",
            request.messages[1].content,
        )
        self.assertIn(
            "Emit line_ranges as [] in every trace",
            request.messages[1].content,
        )
        self.assertEqual(
            request.metadata["retry_reason"],
            "case_draft.public_lineage",
        )

    def test_explicit_retry_rejects_scientific_failure_codes(self):
        with self.assertRaises(ValueError):
            build_case_draft_request(
                self.card,
                retry_artifact_error=CaseDraftError(
                    "case_draft.source_fidelity", "$", "scientific"
                ),
            )

        leakage_request = build_case_draft_request(
            self.card,
            retry_artifact_error=CaseDraftError(
                "case_draft.public_leakage",
                "$.drafts[0].candidate.background",
                "Player-visible prose contains an answer direction",
            ),
        )
        self.assertEqual(
            leakage_request.metadata["retry_reason"],
            "case_draft.public_leakage",
        )

    def test_original_mixed_case_interface_id_still_fails_schema(self):
        card = _mixed_case_interface_card()
        payload = _mapped_interface_scaffold_payload()
        payload["drafts"][0]["relationship_targets"][0]["control"] = "M"
        backend = _FakeBackend(payload)

        with self.assertRaises(CaseDraftError) as raised:
            author_case_draft(backend, card)

        self.assertEqual(raised.exception.code, "case_draft.schema")
        self.assertEqual(
            raised.exception.path,
            "$.drafts[0].relationship_targets[0].control",
        )
        self.assertEqual(raised.exception.detail, "must be lower_snake_case")

    def test_selector_values_are_schema_enums_and_parse_before_science_validation(self):
        derivation_schema = case_draft_batch_json_schema(scaffold_oracle=True)[
            "properties"
        ]["drafts"]["items"]["properties"]["counterfactual_derivation"]
        self.assertEqual(
            derivation_schema["properties"]["historical_value"],
            {"type": "number", "enum": [0.0, 1.0]},
        )
        self.assertEqual(
            derivation_schema["properties"]["counterfactual_value"],
            {"type": "number", "enum": [0.0, 1.0]},
        )

        for field, value in (
            ("historical_value", 0.15),
            ("counterfactual_value", 0.8),
        ):
            with self.subTest(field=field):
                payload = _scaffold_payload()
                payload["drafts"][0]["counterfactual_derivation"][field] = value
                with self.assertRaises(CaseDraftError) as raised:
                    parse_case_draft_batch_payload(payload)
                self.assertEqual(raised.exception.code, "case_draft.schema")
                self.assertEqual(
                    raised.exception.path,
                    "$.drafts[0].counterfactual_derivation." + field,
                )
                self.assertIn("0.0 or 1.0", raised.exception.detail)

    def test_selector_schema_failure_can_use_the_single_shape_repair(self):
        invalid = _scaffold_payload()
        derivation = invalid["drafts"][0]["counterfactual_derivation"]
        derivation["historical_value"] = 0.15
        derivation["counterfactual_value"] = 0.8
        backend = _QueuedBackend((invalid, _scaffold_payload()))

        result = author_case_draft(
            backend,
            self.card,
            max_total_attempts=2,
        )

        self.assertEqual(result.attempt_count, 2)
        self.assertEqual(len(backend.requests), 2)
        repair = json.loads(backend.requests[1].messages[2].content)["repair"]
        self.assertEqual(
            repair["validation_error"],
            {
                "code": "case_draft.schema",
                "detail": (
                    "must be one of the benchmark-only selector values 0.0 or 1.0"
                ),
                "path": (
                    "$.drafts[0].counterfactual_derivation.historical_value"
                ),
            },
        )

    def test_schema_shape_failure_gets_one_explicit_repair(self):
        invalid = _scaffold_payload()
        invalid["drafts"][0]["relationship_targets"][0]["control"] = "input_X"
        invalid_text = json.dumps(invalid)
        corrected = _scaffold_payload()
        backend = _QueuedBackend((invalid_text, corrected))

        result = author_case_draft(
            backend,
            self.card,
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
            "case_draft.schema",
        )
        repair_payload = json.loads(repair.messages[2].content)["repair"]
        self.assertEqual(repair_payload["previous_output"], invalid_text)
        self.assertEqual(repair_payload["schema"], primary.response_schema)
        self.assertEqual(
            repair_payload["validation_error"],
            {
                "code": "case_draft.schema",
                "detail": "must be lower_snake_case",
                "path": "$.drafts[0].relationship_targets[0].control",
            },
        )
        self.assertEqual(
            repair_payload["machine_interface_mapping"],
            {
                "immutable": True,
                "controls": {"input_x": "input_x"},
                "readouts": {"response": "response"},
                "fixed_conditions": {
                    "fixed_apparatus_state": "fixed_apparatus_state",
                },
            },
        )
        self.assertIn("change only the field or fields needed", repair_payload["instruction"])
        self.assertIn("Do not add, remove, reinterpret", repair_payload["instruction"])
        self.assertEqual(
            result.batch.drafts[0].counterfactual_derivation.source_claim_ids,
            ("linear_regime_claim", "quadratic_regime_claim"),
        )
        self.assertEqual(
            result.batch.drafts[0].candidate.oracle.outputs,
            parse_candidate_payload(_candidate_payload()).oracle.outputs,
        )

    def test_schema_repair_second_failure_is_terminal_after_two_calls(self):
        invalid = _scaffold_payload()
        invalid["drafts"][0]["relationship_targets"][0]["readout"] = "Response"
        backend = _QueuedBackend((invalid, invalid, _scaffold_payload()))

        with self.assertRaises(CaseDraftError) as raised:
            author_case_draft(
                backend,
                self.card,
                max_total_attempts=2,
            )

        self.assertEqual(raised.exception.code, "case_draft.schema")
        self.assertEqual(len(backend.requests), 2)
        self.assertEqual(len(backend.payloads), 1)

    def test_schema_repair_does_not_bypass_scientific_validation(self):
        invalid = _scaffold_payload()
        invalid["drafts"][0]["relationship_targets"][0]["control"] = "input_X"
        corrected_but_unfaithful = _scaffold_payload()
        corrected_but_unfaithful["drafts"][0]["counterfactual_derivation"][
            "paper_defined_equations_unchanged"
        ] = False
        backend = _QueuedBackend((invalid, corrected_but_unfaithful))

        with self.assertRaises(CaseDraftError) as raised:
            author_case_draft(
                backend,
                self.card,
                max_total_attempts=2,
            )

        self.assertEqual(raised.exception.code, "case_draft.source_fidelity")
        self.assertEqual(len(backend.requests), 2)

    def test_four_call_loop_repairs_serial_mechanical_errors(self):
        uppercase = _scaffold_payload()
        uppercase["drafts"][0]["relationship_targets"][0]["control"] = "input_X"

        bad_lineage = _scaffold_payload()
        shared = bad_lineage["drafts"][0]["information_boundary"]["shared_player"]
        bad_lineage["drafts"][0]["information_boundary"]["shared_player"] = [
            trace for trace in shared if trace["field"] != "note.0"
        ]

        bad_selector = _scaffold_payload()
        derivation = bad_selector["drafts"][0]["counterfactual_derivation"]
        derivation["historical_value"] = 0.15
        derivation["counterfactual_value"] = 0.8

        corrected = _scaffold_payload()
        outputs = (uppercase, bad_lineage, bad_selector, corrected)
        backend = _QueuedBackend(outputs)

        result = author_case_draft(
            backend,
            self.card,
            max_total_attempts=4,
        )

        self.assertEqual(result.attempt_count, 4)
        self.assertEqual(len(backend.requests), 4)
        expected_errors = (
            (
                "case_draft.schema",
                "$.drafts[0].relationship_targets[0].control",
            ),
            (
                "case_draft.public_lineage",
                "$.drafts[0].information_boundary.shared_player",
            ),
            (
                "case_draft.schema",
                "$.drafts[0].counterfactual_derivation.historical_value",
            ),
        )
        mapping = {
            "immutable": True,
            "controls": {"input_x": "input_x"},
            "readouts": {"response": "response"},
            "fixed_conditions": {
                "fixed_apparatus_state": "fixed_apparatus_state",
            },
        }
        for attempt_number, (request, previous, expected_error) in enumerate(
            zip(backend.requests[1:], outputs, expected_errors),
            start=2,
        ):
            repair = json.loads(request.messages[2].content)["repair"]
            self.assertEqual(request.metadata["generation_attempt"], attempt_number)
            self.assertEqual(request.metadata["repair_reason"], expected_error[0])
            self.assertEqual(repair["previous_output"], json.dumps(previous))
            self.assertEqual(repair["machine_interface_mapping"], mapping)
            self.assertEqual(repair["validation_error"]["code"], expected_error[0])
            self.assertEqual(repair["validation_error"]["path"], expected_error[1])
        self.assertEqual(backend.payloads, [])

    def test_fourth_mechanical_failure_is_terminal(self):
        invalid = _scaffold_payload()
        invalid["drafts"][0]["relationship_targets"][0]["control"] = "input_X"
        backend = _QueuedBackend((invalid, invalid, invalid, invalid, _scaffold_payload()))

        with self.assertRaises(CaseDraftError) as raised:
            author_case_draft(
                backend,
                self.card,
                max_total_attempts=4,
            )

        self.assertEqual(raised.exception.code, "case_draft.schema")
        self.assertEqual(len(backend.requests), 4)
        self.assertEqual(len(backend.payloads), 1)

    def test_scientific_failure_never_enters_repair_loop(self):
        source_drift = _scaffold_payload()
        source_drift["drafts"][0]["counterfactual_derivation"][
            "paper_defined_equations_unchanged"
        ] = False

        backend = _QueuedBackend((source_drift, _scaffold_payload()))
        with self.assertRaises(CaseDraftError) as raised:
            author_case_draft(
                backend,
                self.card,
                max_total_attempts=4,
            )
        self.assertEqual(raised.exception.code, "case_draft.source_fidelity")
        self.assertEqual(len(backend.requests), 1)
        self.assertEqual(len(backend.payloads), 1)

    def test_public_leakage_enters_bounded_repair_loop(self):
        public_leakage = _scaffold_payload()
        public_leakage["drafts"][0]["candidate"]["controls"][0][
            "description"
        ] = "The response equals 2.0."

        backend = _QueuedBackend((public_leakage, _scaffold_payload()))
        result = author_case_draft(
            backend,
            self.card,
            max_total_attempts=4,
        )
        self.assertEqual(result.attempt_count, 2)
        self.assertEqual(len(backend.requests), 2)
        self.assertEqual(backend.payloads, [])
        repair = json.loads(backend.requests[1].messages[2].content)["repair"]
        self.assertEqual(
            repair["validation_error"]["code"],
            "case_draft.public_leakage",
        )
        self.assertIn("do not move it", repair["instruction"])

    def test_initial_observation_leakage_is_compiled_without_an_llm_retry(self):
        repeated = _scaffold_payload()
        leaking_sentence = "The response decreases as input_x increases."
        repeated["drafts"][0]["candidate"]["initial_observations"].append(
            leaking_sentence
        )
        repeated["drafts"][0]["information_boundary"]["shared_player"].append(
            _public_trace(
                "initial_observation.1",
                [],
                mechanism_ids=("reported_regime_response",),
            )
        )
        backend = _QueuedBackend((repeated, repeated, repeated, repeated))

        result = author_case_draft(
            backend,
            self.card,
            max_total_attempts=4,
        )

        self.assertEqual(result.attempt_count, 1)
        self.assertEqual(len(backend.requests), 1)
        self.assertEqual(len(backend.payloads), 3)
        self.assertEqual(
            result.batch.drafts[0].candidate.initial_observations[1],
            "A measurable response is present under the stated conditions.",
        )
        normalization = result.prose_normalizations[0]
        self.assertEqual(
            normalization.path,
            "$.drafts[0].candidate.initial_observations[1]",
        )
        self.assertEqual(normalization.original, leaking_sentence)
        self.assertEqual(
            json.loads(result.response.text)["drafts"][0]["candidate"][
                "initial_observations"
            ][1],
            leaking_sentence,
        )

    def test_note_leakage_is_compiled_without_an_llm_retry(self):
        repeated = _scaffold_payload()
        leaking_sentence = "The response is independent of input_x."
        repeated["drafts"][0]["candidate"]["notes"][0] = leaking_sentence
        backend = _QueuedBackend((repeated, repeated, repeated, repeated))

        result = author_case_draft(
            backend,
            self.card,
            max_total_attempts=4,
        )

        self.assertEqual(result.attempt_count, 1)
        self.assertEqual(len(backend.requests), 1)
        self.assertEqual(len(backend.payloads), 3)
        self.assertEqual(len(result.batch.drafts[0].candidate.notes), 1)
        self.assertEqual(
            result.batch.drafts[0].candidate.notes[0],
            "Use only the stated controls, readouts, and fixed conditions.",
        )
        normalization = result.prose_normalizations[0]
        self.assertEqual(
            normalization.path,
            "$.drafts[0].candidate.notes[0]",
        )
        self.assertEqual(normalization.original, leaking_sentence)
        self.assertEqual(
            json.loads(result.response.text)["drafts"][0]["candidate"][
                "notes"
            ][0],
            leaking_sentence,
        )

    def test_initial_observation_compiler_does_not_hide_private_leakage(self):
        invalid = _scaffold_payload()
        invalid["drafts"][0]["candidate"]["initial_observations"].append(
            "The response decreases as input_x increases."
        )
        invalid["drafts"][0]["information_boundary"]["shared_player"].append(
            _public_trace(
                "initial_observation.1",
                [],
                mechanism_ids=("reported_regime_response",),
            )
        )
        invalid["drafts"][0]["candidate"]["controls"][0]["description"] = (
            "The historical selector activates the paper branch."
        )
        backend = _QueuedBackend((invalid,))

        with self.assertRaises(CaseDraftError) as raised:
            author_case_draft(backend, self.card, max_total_attempts=1)

        self.assertEqual(raised.exception.code, "case_draft.public_leakage")
        self.assertIn("controls[0].description", raised.exception.path)
        self.assertEqual(len(backend.requests), 1)

    def test_decorative_background_leakage_is_compiled_without_an_llm_retry(self):
        repeated = _scaffold_payload()
        leaking_sentence = "The response increases with input_x."
        repeated["drafts"][0]["candidate"]["background"] = leaking_sentence
        backend = _QueuedBackend((repeated, repeated, repeated, repeated))

        result = author_case_draft(
            backend,
            self.card,
            max_total_attempts=4,
        )

        self.assertEqual(result.attempt_count, 1)
        self.assertEqual(len(backend.requests), 1)
        self.assertEqual(len(backend.payloads), 3)
        self.assertEqual(
            result.batch.drafts[0].candidate.background,
            "Use controlled measurements to characterize the observed phenomenon.",
        )
        self.assertEqual(len(result.prose_normalizations), 1)
        normalization = result.prose_normalizations[0]
        self.assertEqual(
            normalization.path, "$.drafts[0].candidate.background"
        )
        self.assertEqual(normalization.original, leaking_sentence)
        # The provider artifact remains the unmodified response; only the
        # validated compiled batch contains neutral presentation prose.
        self.assertEqual(
            json.loads(result.response.text)["drafts"][0]["candidate"][
                "background"
            ],
            leaking_sentence,
        )

    def test_decorative_compiler_does_not_bypass_source_fidelity(self):
        invalid = _scaffold_payload()
        invalid["drafts"][0]["candidate"]["initial_observations"].append(
            "The response increases with input_x."
        )
        invalid["drafts"][0]["information_boundary"]["shared_player"].append(
            _public_trace(
                "initial_observation.1",
                [],
                mechanism_ids=("reported_regime_response",),
            )
        )
        invalid["drafts"][0]["candidate"]["controls"][0]["maximum"] = 6.0
        backend = _QueuedBackend((invalid, _scaffold_payload()))

        with self.assertRaises(CaseDraftError) as raised:
            author_case_draft(
                backend,
                self.card,
                max_total_attempts=4,
            )

        self.assertEqual(raised.exception.code, "case_draft.source_fidelity")
        self.assertEqual(len(backend.requests), 1)
        self.assertEqual(len(backend.payloads), 1)

    def test_invalid_json_and_incomplete_generation_are_not_repaired(self):
        for text, finish_reason, expected_code in (
            ("not json", "stop", "case_draft.invalid_json"),
            (json.dumps(_scaffold_payload()), "length", "case_draft.incomplete_generation"),
        ):
            with self.subTest(expected_code=expected_code):
                backend = _QueuedBackend((text, _scaffold_payload()))
                if finish_reason != "stop":
                    original_generate = backend.generate

                    def generate(request, *, _original=original_generate):
                        response = _original(request)
                        return GenerationResponse(
                            text=response.text,
                            provider=response.provider,
                            model=response.model,
                            finish_reason=finish_reason,
                        )

                    backend.generate = generate
                with self.assertRaises(CaseDraftError) as raised:
                    author_case_draft(
                        backend,
                        self.card,
                        max_total_attempts=2,
                    )
                self.assertEqual(raised.exception.code, expected_code)
                self.assertEqual(len(backend.requests), 1)

    def test_authored_and_not_authorable_status_contracts(self):
        authored = parse_case_draft_batch_payload(_authored_payload())
        validate_case_draft_batch(authored, self.card)
        self.assertEqual(authored.status, "authored")
        self.assertEqual(len(authored.drafts), 1)

        not_authorable = parse_case_draft_batch_payload(
            {
                "assessment": "No source-reported alternate regime is available.",
                "status": "not_authorable",
                "drafts": [],
            }
        )
        validate_case_draft_batch(not_authorable, self.card)
        self.assertEqual(not_authorable.drafts, ())

        for status, drafts in (
            ("authored", []),
            ("not_authorable", _authored_payload()["drafts"]),
        ):
            with self.subTest(status=status):
                with self.assertRaises(CaseDraftError):
                    parse_case_draft_batch_payload(
                        {
                            "assessment": "Invalid status cardinality.",
                            "status": status,
                            "drafts": drafts,
                        }
                    )

    def test_unknown_claim_and_anchor_are_rejected(self):
        payload = _authored_payload()
        payload["drafts"][0]["information_boundary"]["shared_player"][0][
            "claim_ids"
        ] = ["unknown_claim"]
        batch = parse_case_draft_batch_payload(payload)
        with self.assertRaises(CaseDraftError) as unknown_claim:
            validate_case_draft_batch(batch, self.card)
        self.assertIn("claim_ids", unknown_claim.exception.path)
        self.assertIn("unknown_claim", unknown_claim.exception.detail)

        payload = _authored_payload()
        payload["drafts"][0]["information_boundary"]["shared_player"][0][
            "line_ranges"
        ][0] = {"line_start": 98, "line_end": 99}
        batch = parse_case_draft_batch_payload(payload)
        with self.assertRaises(CaseDraftError) as unknown_anchor:
            validate_case_draft_batch(batch, self.card)
        self.assertIn("line_ranges", unknown_anchor.exception.path)
        self.assertIn("not an anchor", unknown_anchor.exception.detail)

    def test_derivation_mechanisms_must_equal_selected_claim_links(self):
        card_payload = _science_card_payload()
        unrelated = copy.deepcopy(card_payload["mechanisms"][0])
        unrelated["mechanism_id"] = "unrelated_mechanism"
        for parameter in unrelated["parameters"]:
            parameter["name"] = "unrelated_" + parameter["name"]
        card_payload["mechanisms"].append(unrelated)
        card = parse_science_card_payload(card_payload)

        payload = _authored_payload()
        payload["drafts"][0]["counterfactual_derivation"][
            "source_mechanism_ids"
        ] = ["unrelated_mechanism"]
        batch = parse_case_draft_batch_payload(payload)
        with self.assertRaises(CaseDraftError) as mismatch:
            validate_case_draft_batch(batch, card)
        self.assertEqual(mismatch.exception.code, "case_draft.source_fidelity")
        self.assertIn("mechanism union", mismatch.exception.detail)

    def test_nested_science_card_truth_is_revalidated_before_provider_call(self):
        card_payload = _science_card_payload()
        unrelated = copy.deepcopy(card_payload["mechanisms"][0])
        unrelated["mechanism_id"] = "unrelated_mechanism"
        for parameter in unrelated["parameters"]:
            parameter["name"] = "unrelated_" + parameter["name"]
        card_payload["mechanisms"].append(unrelated)
        card = parse_science_card_payload(card_payload)

        card.claims[0].oracle_outputs["response"]["args"][0]["param"] = (
            "unrelated_reported_scale"
        )
        with self.assertRaises(CaseDraftError) as mutated:
            build_case_draft_request(card)
        self.assertEqual(mutated.exception.code, "case_draft.source_fidelity")
        self.assertIn("changed after validation", mutated.exception.detail)

    def test_numeric_initial_observation_is_rejected(self):
        payload = _authored_payload()
        payload["drafts"][0]["candidate"]["initial_observations"] = [
            "At one setting the response is 4.0."
        ]
        batch = parse_case_draft_batch_payload(payload)
        with self.assertRaises(CaseDraftError) as leakage:
            validate_case_draft_batch(batch, self.card)
        self.assertEqual(leakage.exception.code, "case_draft.public_leakage")
        self.assertIn("initial_observations", leakage.exception.path)

    def test_digits_inside_machine_symbols_are_not_numeric_answer_leakage(self):
        payload = _authored_payload()
        payload["drafts"][0]["candidate"]["apparatus"]["description"] = (
            "The apparatus exposes public controls lambda_1 and lambda_2."
        )
        batch = parse_case_draft_batch_payload(payload)
        validate_case_draft_batch(batch, self.card)

    def test_operational_inverse_length_term_is_not_answer_direction(self):
        payload = _authored_payload()
        payload["drafts"][0]["candidate"]["background"] = (
            "The readout is an inverse localization length of the system."
        )
        validate_case_draft_batch(
            parse_case_draft_batch_payload(payload), self.card
        )

        payload["drafts"][0]["candidate"]["background"] = (
            "The response is inversely related to the input."
        )
        with self.assertRaises(CaseDraftError) as leakage:
            validate_case_draft_batch(
                parse_case_draft_batch_payload(payload), self.card
            )
        self.assertEqual(leakage.exception.code, "case_draft.public_leakage")

    def test_public_formula_direction_and_source_fragment_are_rejected(self):
        mutations = (
            ("background", "The response = input_x."),
            ("background", "The response increases with the input."),
            ("title", "et al example journal response"),
        )
        for field, value in mutations:
            with self.subTest(field=field, value=value):
                payload = _authored_payload()
                payload["drafts"][0]["candidate"][field] = value
                batch = parse_case_draft_batch_payload(payload)
                with self.assertRaises(CaseDraftError) as leakage:
                    validate_case_draft_batch(batch, self.card)
                self.assertEqual(
                    leakage.exception.code, "case_draft.public_leakage"
                )
                self.assertIn(
                    ".candidate.%s" % field,
                    leakage.exception.path,
                )

    def test_power_relation_phrase_is_neutralized_without_matching_optical_power(self):
        payload = _scaffold_payload()
        leaking_background = "The radius grows as a power of time."
        payload["drafts"][0]["candidate"]["background"] = leaking_background

        result = author_case_draft(
            _QueuedBackend((payload,)), self.card, max_total_attempts=1
        )

        self.assertEqual(
            result.batch.drafts[0].candidate.background,
            "Use controlled measurements to characterize the observed phenomenon.",
        )
        self.assertEqual(len(result.prose_normalizations), 1)
        self.assertEqual(
            result.prose_normalizations[0].original, leaking_background
        )

        safe = _authored_payload()
        safe["drafts"][0]["candidate"]["background"] = (
            "The optical power of the source is adjusted using the listed control."
        )
        validate_case_draft_batch(
            parse_case_draft_batch_payload(safe), self.card
        )

    def test_decorative_source_fragment_is_compiled_with_exact_field_path(self):
        repeated = _scaffold_payload()
        leaking_title = "et al example journal response"
        repeated["drafts"][0]["candidate"]["title"] = leaking_title
        backend = _QueuedBackend((repeated, repeated, repeated, repeated))

        result = author_case_draft(
            backend,
            self.card,
            max_total_attempts=4,
        )

        self.assertEqual(result.attempt_count, 1)
        self.assertEqual(len(backend.requests), 1)
        self.assertEqual(
            result.batch.drafts[0].candidate.title,
            "Interactive measurement study",
        )
        self.assertEqual(len(result.prose_normalizations), 1)
        self.assertEqual(
            result.prose_normalizations[0].path,
            "$.drafts[0].candidate.title",
        )

        card_payload = _science_card_payload()
        card_payload["readouts"][0]["statistic"] = "Ensemble mean."
        card = parse_science_card_payload(card_payload)
        payload = _authored_payload()
        payload["drafts"][0]["candidate"]["readouts"][0]["statistic"] = (
            "The response increases with the input."
        )
        batch = parse_case_draft_batch_payload(payload)
        with self.assertRaises(CaseDraftError) as semantic_leak:
            validate_case_draft_batch(batch, card)
        self.assertEqual(
            semantic_leak.exception.code, "case_draft.public_leakage"
        )
        self.assertIn("statistic", semantic_leak.exception.path)

    def test_every_public_field_needs_its_own_bound_source_trace(self):
        payload = _authored_payload()
        del payload["drafts"][0]["information_boundary"]["shared_player"][0]
        batch = parse_case_draft_batch_payload(payload)
        with self.assertRaises(CaseDraftError) as missing:
            validate_case_draft_batch(batch, self.card)
        self.assertEqual(missing.exception.code, "case_draft.public_lineage")
        self.assertIn("missing=['title']", missing.exception.detail)

        payload = _authored_payload()
        control_trace = payload["drafts"][0]["information_boundary"][
            "shared_player"
        ][3]
        control_trace["claim_ids"] = ["linear_regime_claim"]
        control_trace["line_ranges"] = [
            {"line_start": 30, "line_end": 32}
        ]
        batch = parse_case_draft_batch_payload(payload)
        with self.assertRaises(CaseDraftError) as wrong_resource:
            validate_case_draft_batch(batch, self.card)
        self.assertEqual(wrong_resource.exception.code, "case_draft.schema")
        self.assertIn("direct science-card resource anchor", wrong_resource.exception.detail)

    def test_public_control_and_readout_traces_include_nested_source_anchors(self):
        card_payload = _science_card_payload()
        card_payload["claims"][0]["control_domains"][0]["anchors"] = [
            _anchor(40, 40, "The paper branch domain is reported here.")
        ]
        card_payload["claims"][1]["control_domains"][0]["anchors"] = [
            _anchor(41, 41, "The alternate branch domain is reported here.")
        ]
        card = parse_science_card_payload(card_payload)
        batch = parse_case_draft_batch_payload(_authored_payload())
        with self.assertRaises(CaseDraftError) as missing_domain_anchors:
            validate_case_draft_batch(batch, card)
        self.assertEqual(
            missing_domain_anchors.exception.code, "case_draft.public_lineage"
        )
        self.assertIn("branch domain anchor", missing_domain_anchors.exception.detail)

        card_payload = _science_card_payload()
        card_payload["readouts"][0]["resolution"]["anchors"] = [
            _anchor(42, 42, "The reporting increment is stated here.")
        ]
        card = parse_science_card_payload(card_payload)
        batch = parse_case_draft_batch_payload(_authored_payload())
        with self.assertRaises(CaseDraftError) as missing_resolution_anchor:
            validate_case_draft_batch(batch, card)
        self.assertEqual(
            missing_resolution_anchor.exception.code, "case_draft.public_lineage"
        )
        self.assertIn("resolution anchor", missing_resolution_anchor.exception.detail)

    def test_unselected_paper_resources_are_not_forced_into_the_case(self):
        for resource in ("controls", "readouts"):
            with self.subTest(resource=resource):
                card_payload = _science_card_payload()
                extra = copy.deepcopy(card_payload[resource][0])
                extra["name"] = "second_" + extra["name"]
                card_payload[resource].append(extra)
                card = parse_science_card_payload(card_payload)
                batch = parse_case_draft_batch_payload(_authored_payload())
                validate_case_draft_batch(batch, card)

    def test_candidate_cannot_drop_a_selected_claim_resource(self):
        for resource in ("controls", "readouts"):
            with self.subTest(resource=resource):
                card_payload = _science_card_payload()
                extra = copy.deepcopy(card_payload[resource][0])
                extra["name"] = "second_" + extra["name"]
                card_payload[resource].append(extra)
                for claim in card_payload["claims"]:
                    if resource == "controls":
                        claim["control_names"].append(extra["name"])
                        domain = copy.deepcopy(claim["control_domains"][0])
                        domain["control_name"] = extra["name"]
                        claim["control_domains"].append(domain)
                    else:
                        claim["readout_names"].append(extra["name"])
                        claim["oracle_outputs"][extra["name"]] = copy.deepcopy(
                            claim["oracle_outputs"]["response"]
                        )
                card = parse_science_card_payload(card_payload)
                batch = parse_case_draft_batch_payload(_authored_payload())
                with self.assertRaises(CaseDraftError) as omitted:
                    validate_case_draft_batch(batch, card)
                self.assertEqual(
                    omitted.exception.code, "case_draft.source_fidelity"
                )
                self.assertIn(resource, omitted.exception.path)

    def test_both_source_branches_must_support_the_public_domain(self):
        card_payload = _science_card_payload()
        card_payload["claims"][1]["control_names"] = []
        card_payload["claims"][1]["control_domains"] = []
        card_payload["claims"][1]["oracle_outputs"]["response"] = {
            "param": "reported_scale"
        }
        card = parse_science_card_payload(card_payload)
        batch = parse_case_draft_batch_payload(_authored_payload())
        with self.assertRaises(CaseDraftError) as missing_domain:
            validate_case_draft_batch(batch, card)
        self.assertEqual(
            missing_domain.exception.code, "case_draft.source_fidelity"
        )
        self.assertIn("both branches", missing_domain.exception.detail)

    def test_source_semantics_cannot_be_relabelled_or_rounded_arbitrarily(self):
        mutations = (
            (
                ("candidate", "readouts", 0, "statistic"),
                "A different aggregate.",
            ),
            (
                ("candidate", "readouts", 0, "uncertainty"),
                "A guessed standard error.",
            ),
            (("candidate", "readouts", 0, "resolution"), 0.1),
            (
                ("candidate", "oracle", "paper_applicability"),
                ["An invented domain."],
            ),
            (
                ("candidate", "common_fixed_conditions", 0, "statement"),
                "A different apparatus condition.",
            ),
        )
        for keys, value in mutations:
            with self.subTest(keys=keys):
                payload = _authored_payload()
                target = payload["drafts"][0]
                for key in keys[:-1]:
                    target = target[key]
                target[keys[-1]] = value
                batch = parse_case_draft_batch_payload(payload)
                with self.assertRaises(CaseDraftError) as changed:
                    validate_case_draft_batch(batch, self.card)
                self.assertEqual(
                    changed.exception.code, "case_draft.source_fidelity"
                )

    def test_prose_shape_labels_cannot_hide_a_constant_offset(self):
        payload = _authored_payload()
        payload["drafts"][0]["candidate"]["oracle"]["outputs"]["response"] = {
            "op": "add",
            "args": [
                {
                    "op": "multiply",
                    "args": [
                        {"param": "reported_scale"},
                        {"var": "input_x"},
                    ],
                },
                {"param": "regime_selector"},
            ],
        }
        batch = parse_case_draft_batch_payload(payload)
        with self.assertRaises(CaseDraftError) as invariant_offset:
            validate_case_draft_batch(batch, self.card)
        self.assertEqual(
            invariant_offset.exception.code, "case_draft.source_fidelity"
        )
        self.assertIn("reviewed ScienceClaim", invariant_offset.exception.detail)

    def test_structured_truth_rejects_formula_drift_and_binder_overwrites_it(self):
        payload = _authored_payload()
        payload["drafts"][0]["candidate"]["oracle"]["outputs"]["response"] = {
            "op": "add",
            "args": [{"var": "input_x"}, {"param": "regime_selector"}],
        }
        batch = parse_case_draft_batch_payload(payload)
        with self.assertRaises(CaseDraftError) as drift:
            validate_case_draft_batch(batch, self.card)
        self.assertEqual(drift.exception.code, "case_draft.source_fidelity")
        self.assertIn("reviewed ScienceClaim", drift.exception.detail)

        rebound = bind_reviewed_oracle(batch, self.card)
        validate_case_draft_batch(rebound, self.card)
        self.assertEqual(
            rebound.drafts[0].candidate.oracle.outputs,
            parse_candidate_payload(_candidate_payload()).oracle.outputs,
        )

    def test_aah_shaped_branches_compile_one_source_parameter_program(self):
        card = _direct_branch_parameter_card("aah")
        batch = bind_reviewed_oracle(
            parse_case_draft_batch_payload(_scaffold_payload()),
            card,
            reviewed_branch_claim_ids=(
                ("linear_regime_claim",),
                ("quadratic_regime_claim",),
            ),
        )
        oracle = batch.drafts[0].candidate.oracle

        self.assertEqual(
            oracle.outputs["response"],
            {
                "op": "maximum",
                "args": [
                    {"param": "zero"},
                    {
                        "op": "subtract",
                        "args": [
                            {"var": "input_x"},
                            {
                                "op": "multiply",
                                "args": [
                                    {"param": "two_pi"},
                                    {"param": "eta_zero"},
                                ],
                            },
                        ],
                    },
                ],
            },
        )
        self.assertEqual(
            oracle.paper_parameters,
            {"zero": 0.0, "two_pi": 6.283185307179586, "eta_zero": 0.0},
        )
        self.assertEqual(
            oracle.counterfactual_parameters,
            {"zero": 0.0, "two_pi": 6.283185307179586, "eta_zero": 0.1},
        )
        self.assertNotIn("regime_selector", oracle.paper_parameters)
        self.assertNotIn("eta_point_one", oracle.counterfactual_parameters)
        self.assertNotEqual(oracle.outputs["response"].get("op"), "add")
        self.assertTrue(filter_candidate(batch.drafts[0].candidate).eligible)
        spec = build_matched_spec(batch.drafts[0].candidate)
        self.assertEqual(
            spec.truths["counterfactual"].parameters["eta_zero"], 0.1
        )

    def test_anderson_shaped_branches_compile_one_source_parameter_program(self):
        card = _direct_branch_parameter_card("anderson")
        batch = bind_reviewed_oracle(
            parse_case_draft_batch_payload(_scaffold_payload()),
            card,
            reviewed_branch_claim_ids=(
                ("linear_regime_claim",),
                ("quadratic_regime_claim",),
            ),
        )
        oracle = batch.drafts[0].candidate.oracle

        self.assertEqual(
            oracle.outputs,
            {
                "response": {
                    "op": "power",
                    "args": [
                        {"var": "input_x"},
                        {"param": "first_order_exponent"},
                    ],
                }
            },
        )
        self.assertEqual(
            oracle.paper_parameters, {"first_order_exponent": -2.0}
        )
        self.assertEqual(
            oracle.counterfactual_parameters,
            {"first_order_exponent": -4.0},
        )
        self.assertNotIn("regime_selector", oracle.paper_parameters)
        self.assertNotIn("second_order_exponent", oracle.counterfactual_parameters)
        self.assertTrue(filter_candidate(batch.drafts[0].candidate).eligible)
        spec = build_matched_spec(batch.drafts[0].candidate)
        self.assertEqual(
            spec.truths["historical"].parameters["first_order_exponent"],
            -2.0,
        )
        self.assertEqual(
            spec.truths["counterfactual"].parameters["first_order_exponent"],
            -4.0,
        )

    def test_real_powerlaw_artifact_binds_one_reviewed_exponent_leaf(self):
        card, batch, branch_claim_ids = _real_temporal_artifact(
            "powerlaw_suspension_final_accepted/papers/"
            "01_paper_2502_06256v3"
        )
        rebound = bind_reviewed_oracle(
            batch,
            card,
            reviewed_branch_claim_ids=branch_claim_ids,
        )
        oracle = rebound.drafts[0].candidate.oracle

        self.assertEqual(
            oracle.outputs,
            {
                "y": {
                    "op": "power",
                    "args": [
                        {"var": "q"},
                        {"param": "beta_k3"},
                    ],
                }
            },
        )
        self.assertEqual(oracle.paper_parameters, {"beta_k3": 0.2})
        self.assertEqual(
            oracle.counterfactual_parameters,
            {"beta_k3": 0.3333333333333333},
        )
        self.assertNotIn("regime_selector", oracle.paper_parameters)
        validate_case_draft_batch(
            rebound,
            card,
            reviewed_branch_claim_ids=branch_claim_ids,
        )

    def test_real_fractal_artifact_binds_one_reviewed_coefficient_leaf(self):
        card, batch, branch_claim_ids = _real_temporal_artifact(
            "fractal_detuning_final_accepted/papers/"
            "01_paper_2506_20617v2"
        )
        rebound = bind_reviewed_oracle(
            batch,
            card,
            reviewed_branch_claim_ids=branch_claim_ids,
        )
        oracle = rebound.drafts[0].candidate.oracle
        output_text = canonical_json_dumps(oracle.outputs)
        changed = {
            name
            for name, value in oracle.paper_parameters.items()
            if oracle.counterfactual_parameters[name] != value
        }

        self.assertEqual(changed, {"c_interface"})
        self.assertEqual(oracle.paper_parameters["c_interface"], 1.0)
        self.assertEqual(oracle.counterfactual_parameters["c_interface"], 0.0)
        self.assertIn('"param":"c_interface"', output_text)
        self.assertNotIn("c_homogeneous", output_text)
        self.assertNotIn("regime_selector", output_text)
        validate_case_draft_batch(
            rebound,
            card,
            reviewed_branch_claim_ids=branch_claim_ids,
        )

    def test_direct_binding_rejects_a_leaf_reused_by_the_other_branch(self):
        contract = _direct_branch_parameter_contract(
            {
                "response": {
                    "op": "multiply",
                    "args": [
                        {"param": "paper_leaf"},
                        {"param": "common_leaf"},
                    ],
                }
            },
            {
                "response": {
                    "op": "multiply",
                    "args": [
                        {"param": "alternate_leaf"},
                        {"param": "paper_leaf"},
                    ],
                }
            },
            source_parameters={
                "paper_leaf": 1.0,
                "alternate_leaf": 2.0,
                "common_leaf": 1.0,
            },
        )

        self.assertIsNone(contract)

    def test_distinct_reviewed_programs_keep_selector_compilation(self):
        card_payload = _science_card_payload()
        card_payload["claims"][1]["oracle_outputs"]["response"] = {
            "op": "multiply",
            "args": [
                {"param": "reported_scale"},
                {
                    "op": "exp",
                    "args": [
                        {
                            "op": "multiply",
                            "args": [
                                {"param": "beta_exponent"},
                                {"var": "input_x"},
                            ],
                        }
                    ],
                },
            ],
        }
        card = parse_science_card_payload(card_payload)
        batch = bind_reviewed_oracle(
            parse_case_draft_batch_payload(_scaffold_payload()), card
        )
        oracle = batch.drafts[0].candidate.oracle

        self.assertEqual(
            oracle.paper_parameters["regime_selector"], 0.0
        )
        self.assertEqual(
            oracle.counterfactual_parameters["regime_selector"], 1.0
        )
        self.assertEqual(oracle.outputs["response"]["op"], "add")

    def test_structured_truth_supports_reversed_selector_values(self):
        payload = _scaffold_payload()
        derivation = payload["drafts"][0]["counterfactual_derivation"]
        derivation["historical_value"] = 1.0
        derivation["counterfactual_value"] = 0.0
        batch = bind_reviewed_lineage(
            bind_reviewed_oracle(
                parse_case_draft_batch_payload(payload), self.card
            ),
            self.card,
        )
        oracle = batch.drafts[0].candidate.oracle
        self.assertEqual(oracle.paper_parameters["regime_selector"], 1.0)
        self.assertEqual(oracle.counterfactual_parameters["regime_selector"], 0.0)
        first_weight = oracle.outputs["response"]["args"][0]["args"][0]
        second_weight = oracle.outputs["response"]["args"][1]["args"][0]
        self.assertEqual(first_weight, {"param": "regime_selector"})
        self.assertEqual(
            second_weight,
            {
                "op": "subtract",
                "args": [1.0, {"param": "regime_selector"}],
            },
        )
        validate_case_draft_batch(batch, self.card)

    def test_maximum_source_depth_still_compiles_inside_runtime_limit(self):
        card_payload = _science_card_payload()
        expression = {"param": "reported_scale"}
        for _ in range(22):
            expression = {"op": "negate", "args": [expression]}
        card_payload["claims"][0]["oracle_outputs"]["response"] = expression
        card = parse_science_card_payload(card_payload)

        payload = _scaffold_payload()
        payload["drafts"][0]["relationship_targets"][0][
            "historical_direction"
        ] = "source_defined"
        batch = bind_reviewed_lineage(
            bind_reviewed_oracle(
                parse_case_draft_batch_payload(payload), card
            ),
            card,
        )
        validate_case_draft_batch(batch, card)

    def test_mixed_legacy_and_structured_claim_truth_is_rejected(self):
        card_payload = _science_card_payload()
        del card_payload["claims"][1]["oracle_outputs"]
        card = parse_science_card_payload(card_payload)
        batch = parse_case_draft_batch_payload(_authored_payload())
        with self.assertRaises(CaseDraftError) as mixed:
            bind_reviewed_oracle(batch, card)
        self.assertEqual(mixed.exception.code, "case_draft.source_fidelity")
        self.assertIn("cannot mix legacy opaque claims", mixed.exception.detail)
        with self.assertRaises(CaseDraftError) as request_error:
            build_case_draft_request(card)
        self.assertEqual(
            request_error.exception.code, "case_draft.mixed_truth_contract"
        )

    def test_reviewer_branch_partition_is_prompted_and_cannot_be_regrouped(self):
        partition = (
            ("linear_regime_claim",),
            ("quadratic_regime_claim",),
        )
        request = build_case_draft_request(
            self.card,
            reviewed_branch_claim_ids=partition,
        )
        self.assertIn("Reviewer-selected branch partition", request.messages[1].content)
        self.assertIn('"branch_a_claim_ids":["linear_regime_claim"]', request.messages[1].content)

        batch = bind_reviewed_lineage(
            bind_reviewed_oracle(
                parse_case_draft_batch_payload(_scaffold_payload()),
                self.card,
                reviewed_branch_claim_ids=partition,
            ),
            self.card,
        )
        validate_case_draft_batch(
            batch,
            self.card,
            reviewed_branch_claim_ids=partition,
        )

        swapped_payload = _scaffold_payload()
        swapped_derivation = swapped_payload["drafts"][0][
            "counterfactual_derivation"
        ]
        swapped_derivation["paper_claim_ids"] = ["quadratic_regime_claim"]
        swapped_derivation["counterfactual_claim_ids"] = [
            "linear_regime_claim"
        ]
        swapped = bind_reviewed_lineage(
            bind_reviewed_oracle(
                parse_case_draft_batch_payload(swapped_payload),
                self.card,
                reviewed_branch_claim_ids=partition,
            ),
            self.card,
        )
        validate_case_draft_batch(
            swapped,
            self.card,
            reviewed_branch_claim_ids=partition,
        )

        regrouped_payload = _scaffold_payload()
        derivation = regrouped_payload["drafts"][0][
            "counterfactual_derivation"
        ]
        derivation["paper_claim_ids"] = [
            "linear_regime_claim",
            "quadratic_regime_claim",
        ]
        derivation["counterfactual_claim_ids"] = ["quadratic_regime_claim"]
        with self.assertRaises(CaseDraftError) as regrouped:
            bind_reviewed_oracle(
                parse_case_draft_batch_payload(regrouped_payload),
                self.card,
                reviewed_branch_claim_ids=partition,
            )
        self.assertEqual(regrouped.exception.code, "case_draft.source_fidelity")
        self.assertIn("regrouping is not", regrouped.exception.detail)

    def test_declared_direction_must_match_the_executable_relation(self):
        payload = _authored_payload()
        payload["drafts"][0]["relationship_targets"][0][
            "historical_direction"
        ] = "decreasing"
        batch = parse_case_draft_batch_payload(payload)
        with self.assertRaises(CaseDraftError) as mismatch:
            validate_case_draft_batch(batch, self.card)
        self.assertEqual(mismatch.exception.code, "case_draft.source_fidelity")
        self.assertIn("disagrees with the executable Oracle", mismatch.exception.detail)

    def test_direction_labels_distinguish_plateaus_and_turning_points(self):
        cases = (
            ((0.0, 1.0, 2.0), "increasing"),
            ((2.0, 1.0, 0.0), "decreasing"),
            ((1.0, 1.0, 1.0), "approximately_invariant"),
            ((0.0, 1.0, 0.0), "non_monotonic"),
            ((0.0, 0.0, 1.0), "non_decreasing"),
            ((1.0, 1.0, 0.0), "non_increasing"),
        )
        for values, expected in cases:
            with self.subTest(values=values):
                self.assertEqual(_direction(values, 1.0e-12), expected)

        canonical_shapes = {
            "increasing": "Strictly increasing over the declared control domain.",
            "decreasing": "Strictly decreasing over the declared control domain.",
            "non_increasing": (
                "Non-increasing over the declared control domain, with possible plateaus."
            ),
            "non_decreasing": (
                "Non-decreasing over the declared control domain, with possible plateaus."
            ),
            "approximately_invariant": (
                "Approximately invariant over the declared control domain."
            ),
            "non_monotonic": "Non-monotonic over the declared control domain.",
            "source_defined": "Source-defined relation over the declared control domain.",
        }
        for direction, expected in canonical_shapes.items():
            with self.subTest(direction=direction):
                self.assertEqual(
                    _canonical_relationship_shape(direction), expected
                )

    def test_relationship_witness_spans_other_controls_for_aah_like_plateau(self):
        payload = _candidate_payload()
        payload["controls"] = [
            {
                "name": "lambda_1",
                "description": "First coupling control.",
                "unit": "dimensionless",
                "minimum": 0.0,
                "maximum": 1.0,
            },
            {
                "name": "lambda_2",
                "description": "Second coupling control.",
                "unit": "dimensionless",
                "minimum": 0.0,
                "maximum": 1.0,
            },
        ]
        payload["oracle"]["outputs"] = {
            "response": {
                "op": "maximum",
                "args": [
                    {"param": "zero"},
                    {
                        "op": "subtract",
                        "args": [
                            {
                                "op": "subtract",
                                "args": [
                                    {"var": "lambda_2"},
                                    {"var": "lambda_1"},
                                ],
                            },
                            {"param": "offset"},
                        ],
                    },
                ],
            }
        }
        payload["oracle"]["paper_parameters"] = {"zero": 0.0, "offset": 0.0}
        payload["oracle"]["counterfactual_parameters"] = {
            "zero": 0.0,
            "offset": 0.25,
        }
        payload["diagnostic_conditions"] = [
            {"lambda_1": 0.25, "lambda_2": 0.75}
        ]
        payload["hidden_conditions"] = [
            {"lambda_1": 0.75, "lambda_2": 0.25}
        ]
        candidate = parse_candidate_payload(payload)

        lambda_1 = RelationshipTarget(
            control="lambda_1",
            readout="response",
            historical_direction="source_defined",
            counterfactual_direction="source_defined",
            historical_shape="clipped difference",
            counterfactual_shape="shifted clipped difference",
            source_claim_ids=("historical", "alternate"),
        )
        lambda_2 = replace(lambda_1, control="lambda_2")

        historical, counterfactual, differs = _relationship_witness(
            candidate, lambda_1
        )
        self.assertEqual(historical, "non_increasing")
        self.assertEqual(counterfactual, "non_increasing")
        self.assertTrue(differs)
        historical, counterfactual, differs = _relationship_witness(
            candidate, lambda_2
        )
        self.assertEqual(historical, "non_decreasing")
        self.assertEqual(counterfactual, "non_decreasing")
        self.assertTrue(differs)

    def test_dense_target_axis_detects_xas_multi_lorentzian_extrema(self):
        def binary(operator, left, right):
            return {"op": operator, "args": [left, right]}

        def parameter(name):
            return {"param": name}

        def add_all(items):
            result = items[0]
            for item in items[1:]:
                result = binary("add", result, item)
            return result

        omega = {"var": "omega"}

        def lorentzian(index):
            numerator = binary(
                "multiply",
                binary("divide", parameter("a%d" % index), parameter("pi")),
                parameter("sigma%d" % index),
            )
            displacement = binary(
                "subtract", omega, parameter("omega0%d" % index)
            )
            denominator = binary(
                "add",
                binary("power", displacement, parameter("two")),
                binary(
                    "power",
                    parameter("sigma%d" % index),
                    parameter("two"),
                ),
            )
            return binary("divide", numerator, denominator)

        xas_expression = add_all(
            [lorentzian(index) for index in (1, 2, 3)]
            + [
                binary(
                    "add",
                    binary("multiply", parameter("slope"), omega),
                    parameter("intercept"),
                )
            ]
        )
        payload = _candidate_payload()
        payload["controls"] = [
            {
                "name": "omega",
                "description": "Photon energy.",
                "unit": "eV",
                "minimum": 527.89,
                "maximum": 529.7,
            }
        ]
        payload["oracle"]["outputs"] = {"response": xas_expression}
        payload["oracle"]["paper_parameters"] = {
            "a1": 0.7,
            "a2": 0.5,
            "a3": 1.5,
            "intercept": -20.0,
            "omega01": 527.89,
            "omega02": 528.45,
            "omega03": 529.68,
            "pi": 3.141592653589793,
            "sigma1": 0.28,
            "sigma2": 0.34,
            "sigma3": 0.55,
            "slope": 0.038,
            "two": 2.0,
        }
        payload["oracle"]["counterfactual_parameters"] = {
            "a1": 0.8,
            "a2": 0.6,
            "a3": 1.5,
            "intercept": -18.0,
            "omega01": 527.9,
            "omega02": 528.46,
            "omega03": 529.7,
            "pi": 3.141592653589793,
            "sigma1": 0.31,
            "sigma2": 0.37,
            "sigma3": 1.18,
            "slope": 0.035,
            "two": 2.0,
        }
        payload["diagnostic_conditions"] = [{"omega": 528.2}]
        payload["hidden_conditions"] = [{"omega": 529.2}]
        candidate = parse_candidate_payload(payload)
        target = RelationshipTarget(
            control="omega",
            readout="response",
            historical_direction="source_defined",
            counterfactual_direction="source_defined",
            historical_shape="three Lorentzians plus a linear background",
            counterfactual_shape="three Lorentzians plus a linear background",
            source_claim_ids=("equilibrium", "transient"),
        )

        historical, counterfactual, differs = _relationship_witness(
            candidate, target
        )

        self.assertEqual(historical, "non_monotonic")
        self.assertEqual(counterfactual, "non_monotonic")
        self.assertTrue(differs)

    def test_author_binds_direction_and_replaces_contradictory_shape_prose(self):
        card_payload = _science_card_payload()
        for claim in card_payload["claims"]:
            original = claim["oracle_outputs"]["response"]
            claim["oracle_outputs"]["response"] = {
                "op": "negate",
                "args": [original],
            }
        card = parse_science_card_payload(card_payload)
        payload = _scaffold_payload()
        payload["drafts"][0]["relationship_targets"][0][
            "historical_shape"
        ] = "r increases with St."
        payload["drafts"][0]["relationship_targets"][0][
            "counterfactual_shape"
        ] = "r increases with St."
        raw_target = copy.deepcopy(payload["drafts"][0]["relationship_targets"][0])
        backend = _QueuedBackend((payload,))

        result = author_case_draft(backend, card, max_total_attempts=1)

        target = result.batch.drafts[0].relationship_targets[0]
        self.assertEqual(target.historical_direction, "decreasing")
        self.assertEqual(target.counterfactual_direction, "decreasing")
        self.assertEqual(
            target.historical_shape,
            "Strictly decreasing over the declared control domain.",
        )
        self.assertEqual(
            target.counterfactual_shape,
            "Strictly decreasing over the declared control domain.",
        )
        self.assertEqual(target.control, raw_target["control"])
        self.assertEqual(target.readout, raw_target["readout"])
        self.assertEqual(target.source_claim_ids, tuple(raw_target["source_claim_ids"]))
        self.assertEqual(len(result.relationship_direction_bindings), 1)
        binding = result.relationship_direction_bindings[0]
        self.assertEqual(binding.original_historical_direction, "increasing")
        self.assertEqual(binding.bound_historical_direction, "decreasing")
        self.assertEqual(
            binding.original_historical_shape, "r increases with St."
        )
        self.assertEqual(
            binding.bound_historical_shape,
            "Strictly decreasing over the declared control domain.",
        )
        self.assertEqual(
            json.loads(result.response.text)["drafts"][0][
                "relationship_targets"
            ][0]["historical_direction"],
            "increasing",
        )
        self.assertEqual(
            json.loads(result.response.text)["drafts"][0][
                "relationship_targets"
            ][0]["historical_shape"],
            raw_target["historical_shape"],
        )

    def test_direction_binder_leaves_invalid_interface_for_strict_validator(self):
        payload = _scaffold_payload()
        payload["drafts"][0]["relationship_targets"][0]["control"] = "input_X"
        backend = _QueuedBackend((payload,))

        with self.assertRaises(CaseDraftError) as raised:
            author_case_draft(backend, self.card, max_total_attempts=1)

        self.assertEqual(raised.exception.code, "case_draft.schema")
        self.assertIn(".control", raised.exception.path)

    def test_direction_binding_does_not_admit_worlds_without_relation_difference(self):
        card_payload = _science_card_payload()
        card_payload["claims"][1]["oracle_outputs"]["response"] = copy.deepcopy(
            card_payload["claims"][0]["oracle_outputs"]["response"]
        )
        card = parse_science_card_payload(card_payload)
        backend = _QueuedBackend((_scaffold_payload(),))

        with self.assertRaises(CaseDraftError) as raised:
            author_case_draft(backend, card, max_total_attempts=1)

        self.assertEqual(raised.exception.code, "case_draft.source_fidelity")
        self.assertIn("invariant offset or not at all", raised.exception.detail)
        self.assertEqual(len(backend.requests), 1)

    def test_player_notes_cannot_reveal_the_private_regime_selector(self):
        payload = _authored_payload()
        payload["drafts"][0]["candidate"]["notes"] = [
            "The counterfactual world sets the selector to the other regime."
        ]
        batch = parse_case_draft_batch_payload(payload)
        with self.assertRaises(CaseDraftError) as leakage:
            validate_case_draft_batch(batch, self.card)
        self.assertEqual(leakage.exception.code, "case_draft.public_leakage")
        self.assertIn("notes", leakage.exception.path)

    def test_non_source_only_counterfactual_requires_explicit_opt_out(self):
        payload = _authored_payload()
        payload["drafts"][0]["counterfactual_derivation"]["kind"] = (
            "benchmark_authored_parameter_substitution"
        )
        batch = parse_case_draft_batch_payload(payload)
        with self.assertRaises(CaseDraftError) as source_fidelity:
            validate_case_draft_batch(batch, self.card)
        self.assertEqual(
            source_fidelity.exception.code, "case_draft.source_fidelity"
        )

        validate_case_draft_batch(batch, self.card, strict_source_only=False)

    def test_selector_must_match_the_oracle_parameter_and_values(self):
        payload = _authored_payload()
        payload["drafts"][0]["counterfactual_derivation"][
            "selector_parameter"
        ] = "missing_selector"
        batch = parse_case_draft_batch_payload(payload)
        with self.assertRaises(CaseDraftError) as missing_selector:
            validate_case_draft_batch(batch, self.card)
        self.assertIn("selector_parameter", missing_selector.exception.path)
        self.assertIn("must be an Oracle parameter", missing_selector.exception.detail)

        payload = _authored_payload()
        payload["drafts"][0]["counterfactual_derivation"][
            "historical_value"
        ] = 1.0
        batch = parse_case_draft_batch_payload(payload)
        with self.assertRaises(CaseDraftError) as wrong_value:
            validate_case_draft_batch(batch, self.card)
        self.assertIn("historical_value", wrong_value.exception.path)
        self.assertIn("does not match Oracle", wrong_value.exception.detail)

    def test_invented_oracle_coefficient_is_rejected(self):
        payload = _authored_payload()
        for parameter_map in (
            "paper_parameters",
            "counterfactual_parameters",
        ):
            payload["drafts"][0]["candidate"]["oracle"][parameter_map][
                "reported_scale"
            ] = 3.0
        batch = parse_case_draft_batch_payload(payload)
        with self.assertRaises(CaseDraftError) as invented:
            validate_case_draft_batch(batch, self.card)
        self.assertEqual(invented.exception.code, "case_draft.source_fidelity")
        self.assertIn("reported_scale", invented.exception.path)
        self.assertIn("science-card parameter", invented.exception.detail)

    def test_valid_source_contained_draft_filters_and_renders(self):
        batch = parse_case_draft_batch_payload(_authored_payload())
        validate_case_draft_batch(batch, self.card)
        candidate = batch.drafts[0].candidate
        result = filter_candidate(candidate)
        self.assertTrue(result.eligible, result.issues)

        source = render_candidate_module(candidate)
        compile(source, "reported_regime_response.py", "exec")
        namespace = {}
        exec(source, namespace)
        self.assertIn("REPORTED_REGIME_RESPONSE_SPEC", source)

        self.assertEqual(
            parse_case_draft_batch_payload(case_draft_batch_to_payload(batch)),
            batch,
        )

    def test_temporal_identification_is_world_neutral_and_selector_free(self):
        candidate = parse_candidate_payload(_candidate_payload())
        spec = build_matched_spec(candidate)
        self.assertEqual(
            spec.identification_parameters,
            ("response_exponent",),
        )
        private_tokens = (
            "reported_regime_response",
            "regime_selector",
            "reported_scale",
            "alpha_exponent",
            "beta_exponent",
        )
        self.assertEqual(spec.identification_model, "case_specific_closed_form")

        payloads = {}
        for world in ("historical", "counterfactual"):
            case = make_matched_case(
                spec, world, BenchmarkTrack.IDENTIFICATION
            )
            payload = episode_view_to_payload(Episode(case).view())
            public_text = canonical_json_dumps(payload)
            for token in private_tokens:
                self.assertNotIn(token, public_text)
            payload["case"]["case_id"] = "opaque_instance"
            payloads[world] = payload
        self.assertEqual(payloads["historical"], payloads["counterfactual"])

        for world in ("historical", "counterfactual"):
            case = make_matched_case(
                spec, world, BenchmarkTrack.IDENTIFICATION
            )
            valid = truth_submission(spec, world, BenchmarkTrack.IDENTIFICATION)
            self.assertTrue(case.evaluator.evaluate(valid).success)
            invalid = replace(
                valid,
                parameters={**valid.parameters, "regime_selector": 0.0},
            )
            rejected = case.evaluator.evaluate(invalid)
            self.assertFalse(rejected.success)
            self.assertIn("public contract exactly", rejected.message)

    def test_identification_rejects_more_free_parameters_than_episode_observations(self):
        payload = _candidate_payload()
        branches = payload["oracle"]["outputs"]["response"]["args"]
        for branch, prefix in zip(branches, ("alpha", "beta")):
            selector = branch["args"][0]
            power = branch["args"][2]
            branch["args"] = [
                selector,
                {
                    "op": "add",
                    "args": [
                        {
                            "op": "multiply",
                            "args": [{"param": prefix + "_scale"}, power],
                        },
                        {"param": prefix + "_offset"},
                    ],
                },
            ]
        for parameters in (
            payload["oracle"]["paper_parameters"],
            payload["oracle"]["counterfactual_parameters"],
        ):
            del parameters["reported_scale"]
            parameters.update(
                {
                    "alpha_scale": 2.0,
                    "alpha_offset": 0.5,
                    "beta_scale": 3.0,
                    "beta_offset": 1.5,
                }
            )
        payload["budget"] = 2

        result = filter_candidate(parse_candidate_payload(payload))
        self.assertIn(
            "identification.insufficient_observation_capacity",
            {issue.code for issue in result.issues},
        )

    def test_finite_control_domain_cannot_be_enumerated_within_budget(self):
        payload = _candidate_payload()
        payload["controls"][0] = {
            "name": "input_x",
            "description": "The adjustable numeric input.",
            "unit": "a.u.",
            "minimum": None,
            "maximum": None,
            "allowed_values": [1.0, 2.0, 4.0, 5.0],
        }

        result = filter_candidate(parse_candidate_payload(payload))
        self.assertIn(
            "discovery.enumerable_control_domain",
            {issue.code for issue in result.issues},
        )

    def test_projected_identification_matches_private_oracle_and_discovery(self):
        candidate = parse_candidate_payload(_candidate_payload())
        spec = build_matched_spec(candidate)
        conditions = spec.diagnostic_conditions + spec.hidden_conditions
        for world in ("historical", "counterfactual"):
            truth = spec.truths[world]
            for condition in conditions:
                private = spec.predict(truth.parameters, condition)
                identified = spec.identification_predict(
                    truth.identification_values, condition
                )
                self.assertEqual(private, identified)

            proposal = ExperimentProposal(
                intent="Compare the two public tracks at one allowed setting.",
                apparatus=spec.apparatus_name,
                controls=dict(conditions[0]),
                readouts=("response",),
                replicates=1,
            )
            evidence = []
            for track in (
                BenchmarkTrack.IDENTIFICATION,
                BenchmarkTrack.DISCOVERY,
            ):
                case = make_matched_case(spec, world, track)
                response = CaseOracle(
                    case.definition, case.world_model
                ).respond(proposal)
                self.assertIs(response.status, OracleStatus.VALID)
                evidence.append(response.evidence.measurements)
            self.assertEqual(evidence[0], evidence[1])

    def test_reported_branches_may_project_multiple_public_scalar_slots(self):
        payload = _candidate_payload()
        second_branch = payload["oracle"]["outputs"]["response"]["args"][1]
        second_branch["args"][1] = {"param": "beta_scale"}
        for parameters in (
            payload["oracle"]["paper_parameters"],
            payload["oracle"]["counterfactual_parameters"],
        ):
            parameters["beta_scale"] = 3.0
        spec = build_matched_spec(parse_candidate_payload(payload))
        self.assertEqual(
            spec.truths["historical"].identification_values,
            {"response_scale": 2.0, "response_exponent": 1.0},
        )
        self.assertEqual(
            spec.truths["counterfactual"].identification_values,
            {"response_scale": 3.0, "response_exponent": 2.0},
        )
        changed_private = [
            name
            for name in spec.truths["historical"].parameters
            if spec.truths["historical"].parameters[name]
            != spec.truths["counterfactual"].parameters[name]
        ]
        self.assertEqual(changed_private, ["regime_selector"])

    def test_heterogeneous_or_identity_mismatched_branches_fail_closed(self):
        heterogeneous = _candidate_payload()
        second_branch = heterogeneous["oracle"]["outputs"]["response"][
            "args"
        ][1]
        second_branch["args"][2] = {
            "op": "exp",
            "args": [{"var": "input_x"}],
        }
        for parameters in (
            heterogeneous["oracle"]["paper_parameters"],
            heterogeneous["oracle"]["counterfactual_parameters"],
        ):
            del parameters["beta_exponent"]
        result = filter_candidate(parse_candidate_payload(heterogeneous))
        self.assertIn(
            "identification.no_common_skeleton",
            {issue.code for issue in result.issues},
        )

        identity_mismatch = _candidate_payload()
        first_branch = identity_mismatch["oracle"]["outputs"]["response"][
            "args"
        ][0]
        first_branch["args"][1] = {"param": "alpha_exponent"}
        result = filter_candidate(parse_candidate_payload(identity_mismatch))
        self.assertIn(
            "identification.no_common_skeleton",
            {issue.code for issue in result.issues},
        )

    def test_identification_projection_is_independent_of_output_key_order(self):
        left = _candidate_payload()
        second_readout = copy.deepcopy(left["readouts"][0])
        second_readout["name"] = "aux_response"
        second_readout["description"] = "A second aggregate response."
        left["readouts"].append(second_readout)
        original = left["oracle"]["outputs"]["response"]
        left["oracle"]["outputs"] = {
            "response": original,
            "aux_response": copy.deepcopy(original),
        }
        right = copy.deepcopy(left)
        right["oracle"]["outputs"] = {
            "aux_response": right["oracle"]["outputs"]["aux_response"],
            "response": right["oracle"]["outputs"]["response"],
        }
        self.assertEqual(
            build_identification_contract(parse_candidate_payload(left)),
            build_identification_contract(parse_candidate_payload(right)),
        )

    def test_identification_boundary_cannot_promise_a_private_selector(self):
        payload = _authored_payload()
        payload["drafts"][0]["information_boundary"]["identification_only"][
            "items"
        ] = ["Expose the private selector without its value."]
        batch = parse_case_draft_batch_payload(payload)
        with self.assertRaises(CaseDraftError) as raised:
            validate_case_draft_batch(batch, self.card)
        self.assertEqual(raised.exception.code, "case_draft.public_leakage")

    def test_source_semantics_reach_resources_truth_and_oracle_evidence(self):
        batch = parse_case_draft_batch_payload(_authored_payload())
        validate_case_draft_batch(batch, self.card)
        spec = build_matched_spec(batch.drafts[0].candidate)
        self.assertEqual(
            spec.truths["historical"].applicability,
            ("Reported for input_x from one through five.",),
        )
        self.assertEqual(
            spec.truths["historical"].fixed_conditions,
            ("All apparatus settings other than input_x are fixed.",),
        )
        case = make_matched_case(
            spec, "historical", BenchmarkTrack.IDENTIFICATION
        )
        public_readout = case.definition.resources.readouts[0]
        self.assertEqual(public_readout.statistic, EXECUTABLE_ORACLE_STATISTIC)
        self.assertEqual(
            public_readout.uncertainty,
            EXECUTABLE_ORACLE_UNCERTAINTY,
        )
        self.assertEqual(public_readout.resolution_kind, "reporting_increment")
        response = CaseOracle(case.definition, case.world_model).respond(
            ExperimentProposal(
                intent="Measure the source-defined aggregate.",
                apparatus=spec.apparatus_name,
                controls={"input_x": 3.0},
                readouts=("response",),
                replicates=1,
            )
        )
        self.assertIs(response.status, OracleStatus.VALID)
        self.assertEqual(
            response.evidence.uncertainty["response"],
            EXECUTABLE_ORACLE_UNCERTAINTY,
        )
        self.assertIn(EXECUTABLE_ORACLE_STATISTIC, response.evidence.message)

    def test_source_error_bars_remain_provenance_not_query_uncertainty(self):
        card_payload = _science_card_payload()
        card_payload["readouts"][0]["statistic"] = (
            "Ensemble mean over stochastic realizations."
        )
        card_payload["readouts"][0]["uncertainty"] = (
            "Data-point error bars denote one standard deviation."
        )
        for claim in card_payload["claims"]:
            claim["statistical_basis"] = (
                "Weighted fit to ensemble-mean data."
            )
            claim["uncertainty"] = (
                "Data-point error bars denote one standard deviation."
            )
        card = parse_science_card_payload(card_payload)

        raw_payload = _scaffold_payload()
        raw_readout = raw_payload["drafts"][0]["candidate"]["readouts"][0]
        raw_readout["statistic"] = card.readouts[0].statistic
        raw_readout["uncertainty"] = card.readouts[0].uncertainty
        raw_batch = bind_reviewed_lineage(
            parse_case_draft_batch_payload(raw_payload), card
        )
        with self.assertRaises(CaseDraftError) as mislabeled:
            validate_case_draft_batch(raw_batch, card)
        self.assertEqual(mislabeled.exception.code, "case_draft.source_fidelity")
        self.assertIn("statistic", mislabeled.exception.path)

        bound = bind_reviewed_oracle(raw_batch, card)
        validate_case_draft_batch(bound, card)
        candidate = bound.drafts[0].candidate
        self.assertEqual(candidate.readouts[0].statistic, EXECUTABLE_ORACLE_STATISTIC)
        self.assertEqual(
            candidate.readouts[0].uncertainty,
            EXECUTABLE_ORACLE_UNCERTAINTY,
        )
        self.assertEqual(
            card.claims[0].statistical_basis,
            "Weighted fit to ensemble-mean data.",
        )
        self.assertEqual(
            card.readouts[0].uncertainty,
            "Data-point error bars denote one standard deviation.",
        )

        spec = build_matched_spec(candidate)
        case = make_matched_case(
            spec, "historical", BenchmarkTrack.IDENTIFICATION
        )
        response = CaseOracle(case.definition, case.world_model).respond(
            ExperimentProposal(
                intent="Query the central fitted relation.",
                apparatus=spec.apparatus_name,
                controls={"input_x": 3.0},
                readouts=("response",),
                replicates=1,
            )
        )
        self.assertIs(response.status, OracleStatus.VALID)
        self.assertNotIn("standard deviation", response.evidence.message.lower())
        self.assertNotIn("ensemble mean", response.evidence.message.lower())
        self.assertEqual(
            response.evidence.uncertainty["response"],
            EXECUTABLE_ORACLE_UNCERTAINTY,
        )

    def test_unquantized_source_readout_stays_deterministic_and_unrounded(self):
        card_payload = _science_card_payload()
        card_payload["readouts"][0]["resolution"] = None
        card = parse_science_card_payload(card_payload)
        payload = _authored_payload()
        payload["drafts"][0]["candidate"]["readouts"][0]["resolution"] = None
        payload["drafts"][0]["candidate"]["readouts"][0][
            "resolution_kind"
        ] = None
        batch = parse_case_draft_batch_payload(payload)
        validate_case_draft_batch(batch, card)
        candidate = batch.drafts[0].candidate
        self.assertTrue(filter_candidate(candidate).eligible)

        spec = build_matched_spec(candidate)
        public_readout = spec.readouts[0]
        self.assertIsNone(public_readout.resolution)
        self.assertEqual(public_readout.resolution_kind, "")
        case = make_matched_case(
            spec, "historical", BenchmarkTrack.IDENTIFICATION
        )
        response = CaseOracle(case.definition, case.world_model).respond(
            ExperimentProposal(
                intent="Read the deterministic source-defined statistic.",
                apparatus=spec.apparatus_name,
                controls={"input_x": 1.23456789},
                readouts=("response",),
                replicates=1,
            )
        )
        self.assertIs(response.status, OracleStatus.VALID)
        self.assertEqual(response.evidence.measurements["response"], 2.46913578)
        self.assertEqual(
            response.evidence.uncertainty["response"],
            EXECUTABLE_ORACLE_UNCERTAINTY,
        )
        namespace = {}
        exec(render_candidate_module(candidate), namespace)
        self.assertIn("REPORTED_REGIME_RESPONSE_SPEC", namespace)

        invented = copy.deepcopy(payload)
        invented_readout = invented["drafts"][0]["candidate"]["readouts"][0]
        invented_readout["resolution"] = 0.01
        invented_readout["resolution_kind"] = "reporting_increment"
        with self.assertRaises(CaseDraftError) as raised:
            validate_case_draft_batch(
                parse_case_draft_batch_payload(invented), card
            )
        self.assertEqual(raised.exception.code, "case_draft.source_fidelity")

    def test_common_source_domain_is_enforced_before_oracle_execution(self):
        card_payload = _science_card_payload()
        card_payload["claims"][1]["control_domains"][0]["minimum"] = 2.0
        card_payload["claims"][1]["control_domains"][0]["maximum"] = 4.0
        card = parse_science_card_payload(card_payload)
        payload = _authored_payload()
        candidate = payload["drafts"][0]["candidate"]
        candidate["controls"][0]["minimum"] = 2.0
        candidate["controls"][0]["maximum"] = 4.0
        candidate["diagnostic_conditions"] = [
            {"input_x": 2.0},
            {"input_x": 4.0},
        ]
        candidate["hidden_conditions"] = [
            {"input_x": 2.5},
            {"input_x": 3.5},
        ]
        batch = parse_case_draft_batch_payload(payload)
        validate_case_draft_batch(batch, card)
        spec = build_matched_spec(batch.drafts[0].candidate)
        case = make_matched_case(
            spec, "counterfactual", BenchmarkTrack.DISCOVERY
        )
        response = CaseOracle(case.definition, case.world_model).respond(
            ExperimentProposal(
                intent="Do not extrapolate beyond the common source domain.",
                apparatus=spec.apparatus_name,
                controls={"input_x": 1.5},
                readouts=("response",),
                replicates=1,
            )
        )
        self.assertIs(response.status, OracleStatus.OUT_OF_RANGE)
        self.assertIsNone(response.evidence)

    def test_benchmark_interval_may_be_a_strict_subset_of_source_support(self):
        card_payload = _science_card_payload()
        card = parse_science_card_payload(card_payload)
        payload = _authored_payload()
        candidate = payload["drafts"][0]["candidate"]
        candidate["controls"][0]["minimum"] = 2.0
        candidate["controls"][0]["maximum"] = 4.0
        candidate["diagnostic_conditions"] = [
            {"input_x": 2.0},
            {"input_x": 4.0},
        ]
        candidate["hidden_conditions"] = [
            {"input_x": 2.5},
            {"input_x": 3.5},
        ]
        batch = parse_case_draft_batch_payload(payload)
        validate_case_draft_batch(batch, card)
        self.assertTrue(filter_candidate(batch.drafts[0].candidate).eligible)

    def test_reported_numeric_settings_compile_as_an_enumerated_query_set(self):
        card_payload = _science_card_payload()
        source_values = [1.0, 2.0, 3.0, 4.0, 5.0]
        for domain in (
            card_payload["controls"][0],
            card_payload["claims"][0]["control_domains"][0],
            card_payload["claims"][1]["control_domains"][0],
        ):
            domain.update(
                {
                    "domain_kind": "numeric_values",
                    "minimum": None,
                    "maximum": None,
                    "allowed_values": source_values,
                    "domain_statement": "The source reports five manipulated settings.",
                }
            )
        card = parse_science_card_payload(card_payload)
        payload = _authored_payload()
        payload["drafts"][0]["candidate"]["controls"][0].update(
            {
                "minimum": None,
                "maximum": None,
                "allowed_values": source_values,
            }
        )
        batch = parse_case_draft_batch_payload(payload)
        validate_case_draft_batch(batch, card)
        candidate = batch.drafts[0].candidate
        self.assertTrue(filter_candidate(candidate).eligible)
        self.assertEqual(build_matched_spec(candidate).controls[0].allowed_values, tuple(source_values))

    def test_author_splits_one_complete_duplicated_enumeration(self):
        card_payload = _science_card_payload()
        source_values = [1.0, 2.0, 3.0, 4.0, 5.0]
        for domain in (
            card_payload["controls"][0],
            card_payload["claims"][0]["control_domains"][0],
            card_payload["claims"][1]["control_domains"][0],
        ):
            domain.update(
                {
                    "domain_kind": "numeric_values",
                    "minimum": None,
                    "maximum": None,
                    "allowed_values": source_values,
                    "domain_statement": "The source reports five manipulated settings.",
                }
            )
        card = parse_science_card_payload(card_payload)
        payload = _scaffold_payload()
        candidate = payload["drafts"][0]["candidate"]
        candidate["controls"][0].update(
            {
                "minimum": None,
                "maximum": None,
                "allowed_values": source_values,
            }
        )
        complete = [{"input_x": value} for value in source_values]
        candidate["diagnostic_conditions"] = copy.deepcopy(complete)
        candidate["hidden_conditions"] = copy.deepcopy(complete)

        result = author_case_draft(
            _QueuedBackend((payload,)), card, max_total_attempts=1
        )

        bound = result.batch.drafts[0].candidate
        self.assertEqual(
            bound.diagnostic_conditions,
            ({"input_x": 1.0}, {"input_x": 5.0}),
        )
        self.assertEqual(
            bound.hidden_conditions,
            ({"input_x": 2.0}, {"input_x": 3.0}, {"input_x": 4.0}),
        )
        self.assertTrue(filter_candidate(bound).eligible)
        self.assertEqual(len(result.condition_partition_bindings), 1)
        replay = condition_partition_bindings_to_payload(
            result.condition_partition_bindings
        )["bindings"][0]
        self.assertEqual(replay["allowed_values"], source_values)
        self.assertEqual(replay["original_diagnostic_conditions"], complete)
        self.assertEqual(replay["original_hidden_conditions"], complete)
        self.assertEqual(
            replay["bound_diagnostic_conditions"],
            [{"input_x": 1.0}, {"input_x": 5.0}],
        )
        self.assertEqual(
            replay["bound_hidden_conditions"],
            [{"input_x": 2.0}, {"input_x": 3.0}, {"input_x": 4.0}],
        )
        raw_candidate = json.loads(result.response.text)["drafts"][0]["candidate"]
        self.assertEqual(raw_candidate["diagnostic_conditions"], complete)
        self.assertEqual(raw_candidate["hidden_conditions"], complete)

    def test_condition_partition_binder_is_narrow_and_truth_preserving(self):
        base = _authored_payload()

        continuous = copy.deepcopy(base)
        continuous_candidate = continuous["drafts"][0]["candidate"]
        complete = [{"input_x": value} for value in (1.0, 3.0, 5.0)]
        continuous_candidate["diagnostic_conditions"] = copy.deepcopy(complete)
        continuous_candidate["hidden_conditions"] = copy.deepcopy(complete)
        continuous_batch = parse_case_draft_batch_payload(continuous)
        unchanged, bindings = bind_enumerated_condition_partitions(
            continuous_batch
        )
        self.assertEqual(unchanged, continuous_batch)
        self.assertEqual(bindings, ())

        already_valid = copy.deepcopy(base)
        valid_candidate = already_valid["drafts"][0]["candidate"]
        valid_candidate["controls"][0].update(
            {
                "minimum": None,
                "maximum": None,
                "allowed_values": [1.0, 2.0, 3.0],
            }
        )
        valid_candidate["diagnostic_conditions"] = [
            {"input_x": 1.0},
            {"input_x": 3.0},
        ]
        valid_candidate["hidden_conditions"] = [{"input_x": 2.0}]
        valid_batch = parse_case_draft_batch_payload(already_valid)
        unchanged, bindings = bind_enumerated_condition_partitions(valid_batch)
        self.assertEqual(unchanged, valid_batch)
        self.assertEqual(bindings, ())

        multiple = copy.deepcopy(base)
        multi_candidate = multiple["drafts"][0]["candidate"]
        multi_candidate["controls"][0].update(
            {
                "minimum": None,
                "maximum": None,
                "allowed_values": [1.0, 2.0, 3.0],
            }
        )
        multi_candidate["controls"].append(
            {
                "name": "input_y",
                "description": "A second enumerated input.",
                "unit": "a.u.",
                "minimum": None,
                "maximum": None,
                "allowed_values": [10.0, 20.0, 30.0],
            }
        )
        multi_complete = [
            {"input_x": x, "input_y": y}
            for x, y in ((1.0, 10.0), (2.0, 20.0), (3.0, 30.0))
        ]
        multi_candidate["diagnostic_conditions"] = copy.deepcopy(multi_complete)
        multi_candidate["hidden_conditions"] = copy.deepcopy(multi_complete)
        multi_batch = parse_case_draft_batch_payload(multiple)
        unchanged, bindings = bind_enumerated_condition_partitions(multi_batch)
        self.assertEqual(unchanged, multi_batch)
        self.assertEqual(bindings, ())

        exact = copy.deepcopy(already_valid)
        exact_candidate = exact["drafts"][0]["candidate"]
        exact_candidate["diagnostic_conditions"] = [
            {"input_x": 3.0},
            {"input_x": 1.0},
            {"input_x": 2.0},
        ]
        exact_candidate["hidden_conditions"] = copy.deepcopy(
            exact_candidate["diagnostic_conditions"]
        )
        exact_batch = parse_case_draft_batch_payload(exact)
        original_oracle = exact_batch.drafts[0].candidate.oracle
        bound, bindings = bind_enumerated_condition_partitions(exact_batch)
        self.assertEqual(len(bindings), 1)
        self.assertEqual(bound.drafts[0].candidate.oracle, original_oracle)

    def test_temporal_specs_enable_held_out_interior_validation_only_explicitly(self):
        candidate = parse_candidate_payload(_candidate_payload())
        spec = build_matched_spec(candidate)
        self.assertTrue(spec.require_held_out_interior)
        endpoint = ({"input_x": spec.controls[0].maximum},)
        interior_diagnostics = ({"input_x": 2.0}, {"input_x": 3.0})
        with self.assertRaisesRegex(ValueError, "control interior"):
            replace(
                spec,
                diagnostic_conditions=interior_diagnostics,
                hidden_conditions=endpoint,
            )
        relaxed = replace(
            spec,
            diagnostic_conditions=interior_diagnostics,
            hidden_conditions=endpoint,
            require_held_out_interior=False,
        )
        self.assertFalse(relaxed.require_held_out_interior)

    def test_family_review_request_contains_plain_draft_boundary_and_predictions(self):
        batch = parse_case_draft_batch_payload(_authored_payload())
        validate_case_draft_batch(batch, self.card)
        draft = batch.drafts[0]
        request = family_review_request_payload(
            draft,
            paper_id="paper_1",
        )
        self.assertEqual(request["decision"], "source_closure_rejected")
        material = request["review_material"]
        self.assertEqual(
            material["candidate"]["family"], "reported_regime_response"
        )
        self.assertEqual(
            {item["field"] for item in material["information_boundary"]["shared_player"]},
            {
                "title",
                "background",
                "apparatus",
                "control.input_x",
                "readout.response",
                "initial_observation.0",
                "fixed_condition.fixed_apparatus_state",
                "note.0",
            },
        )
        self.assertEqual(
            {item["group"] for item in material["predictions"]},
            {"diagnostic", "hidden"},
        )
        self.assertTrue(
            any(
                item["paper"] != item["alternate"]
                for item in material["predictions"]
            )
        )

    def test_family_review_binds_the_complete_draft_and_exact_json_types(self):
        batch = parse_case_draft_batch_payload(_authored_payload())
        validate_case_draft_batch(batch, self.card)
        draft = batch.drafts[0]
        request = family_review_request_payload(draft, paper_id="paper_1")
        request.update(
            {
                "reviewer": "independent family source reviewer",
                "decision": "source_closed",
                "assessment": "The complete draft and predictions are source closed.",
                "issues": [],
            }
        )
        review = parse_family_source_review_payload(request)
        self.assertTrue(
            assess_family_source_closure(draft, review, paper_id="paper_1")
        )

        changed_relationship = copy.deepcopy(request)
        changed_relationship["review_material"]["relationship_targets"][0][
            "historical_shape"
        ] = "changed after review"
        with self.assertRaises(WarmupContractError) as relationship_error:
            assess_family_source_closure(
                draft,
                parse_family_source_review_payload(changed_relationship),
                paper_id="paper_1",
            )
        self.assertEqual(
            relationship_error.exception.code, "warmup.family_review_material"
        )

        changed_type = copy.deepcopy(request)
        changed_type["review_material"]["candidate"]["budget"] = True
        with self.assertRaises(WarmupContractError) as type_error:
            assess_family_source_closure(
                draft,
                parse_family_source_review_payload(changed_type),
                paper_id="paper_1",
            )
        self.assertEqual(type_error.exception.code, "warmup.family_review_material")


if __name__ == "__main__":
    unittest.main()
