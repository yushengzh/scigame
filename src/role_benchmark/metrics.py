"""Primary held-out prediction metric for benchmark evaluation."""

from __future__ import annotations

import math
from typing import Iterable, Tuple


HELD_OUT_PREDICTION_SCORE = "held_out_prediction_score"
HELD_OUT_PREDICTION_SCORE_VERSION = "1.0"


def held_out_prediction_score(scaled_errors: Iterable[float]) -> float:
    """Return ``1 / (1 + mean(scaled error))`` on a fixed held-out set.

    A scaled error of zero gives 1.0; larger errors approach zero. Each
    condition-readout pair has equal weight. Invalid or missing submissions
    are assigned 0.0 by the caller because they have no finite error vector.
    """

    values: Tuple[float, ...] = tuple(float(value) for value in scaled_errors)
    if not values:
        raise ValueError("scaled_errors must contain at least one value")
    if any(not math.isfinite(value) or value < 0.0 for value in values):
        raise ValueError("scaled_errors must be finite and non-negative")
    mean_scaled_error = sum(values) / len(values)
    return 1.0 / (1.0 + mean_scaled_error)


__all__ = [
    "HELD_OUT_PREDICTION_SCORE",
    "HELD_OUT_PREDICTION_SCORE_VERSION",
    "held_out_prediction_score",
]
