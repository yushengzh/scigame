"""Tests for the frozen continuous held-out prediction score."""

from __future__ import annotations

import math
import unittest

from role_benchmark import (
    BenchmarkTrack,
    Episode,
    EpisodeTermination,
    HELD_OUT_PREDICTION_SCORE,
    HELD_OUT_PREDICTION_SCORE_VERSION,
    TerminationKind,
    held_out_prediction_score,
)
from role_benchmark.cases import CASE_SPECS, make_case
from role_benchmark.cases.matched import truth_submission


class HeldOutPredictionScoreTest(unittest.TestCase):
    def test_definition_direction_and_range(self):
        self.assertEqual(HELD_OUT_PREDICTION_SCORE_VERSION, "1.0")
        self.assertEqual(held_out_prediction_score([0.0, 0.0]), 1.0)
        self.assertAlmostEqual(held_out_prediction_score([1.0, 3.0]), 1.0 / 3.0)
        self.assertGreater(
            held_out_prediction_score([0.5]),
            held_out_prediction_score([2.0]),
        )

    def test_invalid_vectors_are_rejected(self):
        for values in ((), (-1.0,), (math.inf,), (math.nan,)):
            with self.subTest(values=values), self.assertRaises(ValueError):
                held_out_prediction_score(values)

    def test_truth_and_false_twin_use_the_frozen_score(self):
        spec = CASE_SPECS["pendulum"]
        for track in BenchmarkTrack:
            with self.subTest(track=track.value):
                evaluator = make_case("pendulum", "historical", track).evaluator
                truth = evaluator.evaluate(
                    truth_submission(spec, "historical", track)
                )
                false_twin = evaluator.evaluate(
                    truth_submission(spec, "counterfactual", track)
                )
                self.assertEqual(truth.scores[HELD_OUT_PREDICTION_SCORE], 1.0)
                self.assertGreaterEqual(
                    false_twin.scores[HELD_OUT_PREDICTION_SCORE], 0.0
                )
                self.assertLess(
                    false_twin.scores[HELD_OUT_PREDICTION_SCORE], 1.0
                )
                expected = 1.0 / (
                    1.0 + false_twin.scores["hidden_test_mean_scaled_error"]
                )
                self.assertAlmostEqual(
                    false_twin.scores[HELD_OUT_PREDICTION_SCORE], expected
                )

    def test_missing_submission_receives_zero(self):
        episode = Episode(make_case("pendulum"))
        outcome = episode.terminate_player_failure(
            EpisodeTermination(
                kind=TerminationKind.ACTION_LIMIT,
                code="max_actions_reached",
                message="No final submission was produced.",
            )
        )
        self.assertEqual(outcome.evaluation.scores[HELD_OUT_PREDICTION_SCORE], 0.0)


if __name__ == "__main__":
    unittest.main()
