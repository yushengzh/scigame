import math
import unittest

from role_benchmark import Episode
from role_benchmark.cases import make_pendulum_case
from role_benchmark.expression import EXPRESSION_MODEL
from role_benchmark.models import (
    ExperimentProposal,
    FinalSubmission,
    Hypothesis,
    HypothesisPortfolio,
    PlayerAction,
)
from role_benchmark.protocols import CaseOracle
from role_benchmark.wire import (
    WireDecodeError,
    WireEncodeError,
    canonical_json_dumps,
    episode_view_from_json,
    episode_view_from_payload,
    episode_view_to_json,
    episode_view_to_payload,
    player_action_from_json,
    player_action_from_payload,
    player_action_to_json,
    player_action_to_payload,
    strict_json_loads,
)


def portfolio(confidence=0.8):
    return HypothesisPortfolio(
        (
            Hypothesis("H1", "A quantitative response law.", confidence),
            Hypothesis("H2", "A constant response law.", 1.0 - confidence),
        )
    )


def experiment_action():
    return PlayerAction.propose_experiment(
        portfolio(),
        ExperimentProposal(
            intent="Measure a controlled pendulum.",
            apparatus="simple_pendulum",
            controls={
                "length_m": 1.0,
                "bob_mass_kg": 0.2,
                "release_angle_deg": 5.0,
            },
            readouts=("period_s",),
            replicates=3,
            forecasts={
                "H1": {"period_s": 2.01},
                "H2": {"period_s": 1.00},
            },
        ),
    )


def final_action():
    confidence = 0.95
    return PlayerAction.submit_final(
        portfolio(confidence),
        FinalSubmission(
            explanation="A normalized power response predicts the observations.",
            hypothesis_id="H1",
            model=EXPRESSION_MODEL,
            parameters={
                "outputs": {
                    "period_s": {
                        "op": "multiply",
                        "args": [
                            2.0 * math.pi * math.sqrt(1.0 / 9.80665),
                            {
                                "op": "power",
                                "args": [{"var": "length_m"}, 0.5],
                            },
                        ],
                    }
                }
            },
            scope_conditions=("public control ranges",),
        ),
    )


class WireEncodingTest(unittest.TestCase):
    def test_episode_view_is_canonical_public_data(self):
        episode = Episode(make_pendulum_case("historical"))
        first = episode_view_to_json(episode.view())
        second = episode_view_to_json(episode.view())
        payload = episode_view_to_payload(episode.view())

        self.assertEqual(first, second)
        self.assertEqual(payload["case"]["track"], "identification")
        self.assertNotIn("oracle", first)
        self.assertNotIn("world_model", first)
        self.assertNotIn("evaluator", first)
        self.assertNotIn("_truth", first)
        self.assertEqual(
            episode_view_to_payload(episode_view_from_json(first)), payload
        )

    def test_episode_view_decoder_is_strict_and_checks_public_invariants(self):
        payload = episode_view_to_payload(Episode(make_pendulum_case()).view())
        decoded = episode_view_from_payload(payload)
        self.assertEqual(episode_view_to_payload(decoded), payload)

        payload["unknown"] = True
        with self.assertRaises(WireDecodeError) as context:
            episode_view_from_payload(payload)
        self.assertEqual(context.exception.code, "unknown_field")

        del payload["unknown"]
        payload["attempts_used"] = payload["case"]["budget"]
        payload["attempts_remaining"] = 1
        with self.assertRaises(WireDecodeError) as context:
            episode_view_from_payload(payload)
        self.assertEqual(context.exception.code, "model_invariant")

    def test_actions_round_trip_with_one_canonical_shape(self):
        for action in (experiment_action(), final_action()):
            with self.subTest(kind=action.kind):
                text = player_action_to_json(action)
                decoded = player_action_from_json(text)
                self.assertEqual(player_action_to_payload(decoded), player_action_to_payload(action))
                payload = player_action_to_payload(decoded)
                self.assertIn("experiment", payload)
                self.assertIn("final", payload)
                if action.kind == "experiment":
                    self.assertEqual(
                        payload["experiment"]["forecasts"]["H1"]["period_s"],
                        2.01,
                    )
                else:
                    self.assertNotIn("confidence", payload["final"])

    def test_final_allows_one_hypothesis_and_defers_portfolio_semantics(self):
        payload = player_action_to_payload(final_action())
        payload["portfolio"]["hypotheses"] = [
            {
                "hypothesis_id": "H1",
                "statement": "The selected quantitative relationship.",
                "confidence": 1.0,
            }
        ]
        decoded = player_action_from_payload(payload)
        self.assertEqual(len(decoded.portfolio.hypotheses), 1)

        payload["portfolio"]["hypotheses"].append(
            {
                "hypothesis_id": "H1",
                "statement": "A contradictory duplicate entry.",
                "confidence": 0.2,
            }
        )
        decoded = player_action_from_payload(payload)
        self.assertEqual(len(decoded.portfolio.hypotheses), 2)

        payload["kind"] = "experiment"
        payload["experiment"] = player_action_to_payload(
            experiment_action()
        )["experiment"]
        payload["final"] = None
        with self.assertRaises(WireDecodeError) as context:
            player_action_from_payload(payload)
        self.assertEqual(context.exception.code, "model_invariant")

    def test_final_rejects_removed_duplicate_confidence_field(self):
        payload = player_action_to_payload(final_action())
        payload["final"]["confidence"] = 0.95
        with self.assertRaises(WireDecodeError) as context:
            player_action_from_payload(payload)
        self.assertEqual(context.exception.code, "unknown_field")

    def test_encoder_rejects_non_json_numeric_values(self):
        with self.assertRaises(WireEncodeError):
            canonical_json_dumps({"value": float("nan")})
        with self.assertRaises(WireEncodeError):
            canonical_json_dumps({1: "non-string key"})

    def test_encoder_rejects_cycles_depth_surrogates_and_unsafe_integral_float(self):
        cyclic = []
        cyclic.append(cyclic)
        with self.assertRaises(WireEncodeError) as context:
            canonical_json_dumps(cyclic)
        self.assertEqual(context.exception.code, "cyclic_value")

        nested = []
        cursor = nested
        for _ in range(70):
            child = []
            cursor.append(child)
            cursor = child
        with self.assertRaises(WireEncodeError) as context:
            canonical_json_dumps(nested)
        self.assertEqual(context.exception.code, "too_deep")

        with self.assertRaises(WireEncodeError) as context:
            canonical_json_dumps({"\ud800": 1})
        self.assertEqual(context.exception.code, "invalid_unicode")
        with self.assertRaises(WireEncodeError) as context:
            canonical_json_dumps({"value": float(2**53)})
        self.assertEqual(context.exception.code, "number_out_of_range")

    def test_action_encoder_and_decoder_share_the_same_byte_limit(self):
        large = PlayerAction.submit_final(
            portfolio(0.95),
            FinalSubmission(
                explanation="x" * 70_000,
                hypothesis_id="H1",
                model="normalized_power_law",
                parameters={},
            ),
        )
        with self.assertRaises(WireEncodeError):
            player_action_to_json(large)
        text = player_action_to_json(large, max_bytes=100_000)
        decoded = player_action_from_json(text, max_bytes=100_000)
        self.assertEqual(decoded.final.explanation, large.final.explanation)

        with self.assertRaises(ValueError):
            episode_view_to_json(Episode(make_pendulum_case()).view(), max_bytes=True)


class WireDecodingTest(unittest.TestCase):
    def test_parser_rejects_non_json_wrappers_duplicates_and_unknown_fields(self):
        valid = player_action_to_json(experiment_action())
        malformed = (
            "```json\n" + valid + "\n```",
            '{"wire_schema":"role_benchmark.player_action",'
            '"wire_schema":"role_benchmark.player_action"}',
        )
        for text in malformed:
            with self.subTest(text=text[:20]):
                with self.assertRaises(WireDecodeError):
                    player_action_from_json(text)

        payload = player_action_to_payload(experiment_action())
        payload["unknown"] = True
        with self.assertRaises(WireDecodeError) as context:
            player_action_from_payload(payload)
        self.assertEqual(context.exception.code, "unknown_field")

    def test_parser_rejects_bool_nonfinite_and_unsafe_numbers(self):
        payload = player_action_to_payload(experiment_action())
        payload["experiment"]["replicates"] = True
        with self.assertRaises(WireDecodeError):
            player_action_from_payload(payload)

        for number in ("NaN", "Infinity", "1e9999", str(2**53)):
            text = player_action_to_json(experiment_action()).replace(
                '"replicates":3', '"replicates":%s' % number
            )
            with self.subTest(number=number):
                with self.assertRaises(WireDecodeError):
                    player_action_from_json(text)

        cases = {
            "9007199254740993.0": "number_out_of_range",
            "9.007199254740993e15": "number_out_of_range",
            "1e-9999": "number_underflow",
            "1.234567890123456789": "number_precision_loss",
        }
        for number, code in cases.items():
            with self.subTest(number=number):
                with self.assertRaises(WireDecodeError) as context:
                    strict_json_loads(number)
                self.assertEqual(context.exception.code, code)

    def test_decoder_rejects_surrogate_keys_and_detaches_nested_input(self):
        with self.assertRaises(WireDecodeError) as context:
            strict_json_loads('{"\\ud800":1}')
        self.assertEqual(context.exception.code, "invalid_unicode")

        payload = player_action_to_payload(final_action())
        nested = {
            "outputs": {
                "period_s": {
                    "op": "multiply",
                    "args": [1.0, {"var": "length_m"}],
                }
            }
        }
        payload["final"]["parameters"] = nested
        decoded = player_action_from_payload(payload)
        nested["outputs"]["period_s"]["args"][0] = 99.0
        nested["outputs"]["period_s"]["args"].append(2.0)
        self.assertEqual(
            decoded.final.parameters["outputs"]["period_s"]["args"],
            [1.0, {"var": "length_m"}],
        )

    def test_parser_rejects_portfolio_invariants_without_leaking_raw_exceptions(self):
        payload = player_action_to_payload(experiment_action())
        payload["portfolio"]["hypotheses"][1]["hypothesis_id"] = "H1"
        with self.assertRaises(WireDecodeError) as context:
            player_action_from_payload(payload)
        self.assertEqual(context.exception.code, "model_invariant")

        payload = player_action_to_payload(experiment_action())
        payload["portfolio"]["hypotheses"][1]["hypothesis_id"] = "OTHER"
        with self.assertRaises(WireDecodeError) as context:
            player_action_from_payload(payload)
        self.assertEqual(context.exception.code, "model_invariant")

        payload = player_action_to_payload(experiment_action())
        payload["portfolio"]["hypotheses"][0]["statement"] = ""
        with self.assertRaises(WireDecodeError):
            player_action_from_payload(payload)

    def test_parser_rejects_missing_or_misaligned_ex_ante_forecasts(self):
        payload = player_action_to_payload(experiment_action())
        del payload["experiment"]["forecasts"]["H2"]
        with self.assertRaises(WireDecodeError) as context:
            player_action_from_payload(payload)
        self.assertEqual(context.exception.code, "model_invariant")

        payload = player_action_to_payload(experiment_action())
        payload["experiment"]["forecasts"]["H2"] = {"wrong_readout": 1.0}
        with self.assertRaises(WireDecodeError) as context:
            player_action_from_payload(payload)
        self.assertEqual(context.exception.code, "model_invariant")

    def test_parser_rejects_malformed_predictor_expression(self):
        payload = player_action_to_payload(final_action())
        payload["final"]["model"] = EXPRESSION_MODEL
        payload["final"]["parameters"] = {
            "outputs": {"period_s": {"op": "python", "args": [1.0]}}
        }
        with self.assertRaises(WireDecodeError) as context:
            player_action_from_payload(payload)
        self.assertEqual(context.exception.code, "model_invariant")

    def test_resource_invalid_action_decodes_then_oracle_applies_budget_semantics(self):
        payload = player_action_to_payload(experiment_action())
        payload["experiment"]["apparatus"] = ""
        payload["experiment"]["readouts"] = []
        payload["experiment"]["replicates"] = 0
        payload["experiment"]["forecasts"] = {"H1": {}, "H2": {}}
        action = player_action_from_payload(payload)
        response = CaseOracle(
            make_pendulum_case().definition,
            make_pendulum_case().world_model,
        ).respond(action.experiment)
        self.assertEqual(response.status.value, "NEEDS_CLARIFICATION")


if __name__ == "__main__":
    unittest.main()
