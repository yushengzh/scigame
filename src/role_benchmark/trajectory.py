"""Deterministic post-hoc metrics for observable scientific trajectories."""

from __future__ import annotations

import itertools
import math
from typing import Dict, Mapping, Optional, Sequence

from .models import (
    CaseDefinition,
    ExperimentTurn,
    HypothesisPortfolio,
    OracleStatus,
)


_EPSILON = 1e-12


def _resolution_by_readout(definition: CaseDefinition) -> Mapping[str, float]:
    return {
        readout.name: (
            float(readout.resolution)
            if readout.resolution is not None and readout.resolution > 0.0
            else _EPSILON
        )
        for readout in definition.resources.readouts
    }


def _normalized_difference(left: float, right: float, resolution: float) -> float:
    return abs(left - right) / max(abs(left), abs(right), resolution, _EPSILON)


def _confidence_map(portfolio: HypothesisPortfolio) -> Mapping[str, float]:
    return {item.hypothesis_id: item.confidence for item in portfolio.hypotheses}


def _statement_map(portfolio: HypothesisPortfolio) -> Mapping[str, str]:
    return {item.hypothesis_id: item.statement for item in portfolio.hypotheses}


def score_trajectory(
    definition: CaseDefinition,
    turns: Sequence[ExperimentTurn],
    final_portfolio: Optional[HypothesisPortfolio],
) -> Mapping[str, float]:
    """Score forecast separation and evidence-aligned confidence movement.

    Experiment discriminativeness is the mean pairwise relative separation of
    ex-ante predictions.  Belief-update alignment is the fraction of persistent
    hypothesis pairs whose confidence gap moves toward the hypothesis with the
    smaller normalized forecast error (ties in confidence movement score 0.5).
    Only valid numerical evidence is scored.
    """

    resolutions = _resolution_by_readout(definition)
    discriminativeness_values = []
    update_values = []
    aligned_pair_count = 0
    inert_pair_count = 0
    opposed_pair_count = 0
    unsupported_shift_pair_count = 0
    rewritten_pair_count = 0
    seen_setups = []
    duplicate_setup_count = 0

    for index, turn in enumerate(turns):
        setup = (
            turn.proposal.apparatus,
            dict(turn.proposal.controls),
            tuple(turn.proposal.readouts),
            turn.proposal.replicates,
        )
        if any(setup == previous for previous in seen_setups):
            duplicate_setup_count += 1
        else:
            seen_setups.append(setup)
        if turn.response.status is not OracleStatus.VALID:
            continue
        evidence = turn.response.evidence
        if evidence is None:
            continue
        forecasts = turn.proposal.forecasts
        hypothesis_ids = [item.hypothesis_id for item in turn.portfolio.hypotheses]

        for readout in turn.proposal.readouts:
            predictions = [float(forecasts[item][readout]) for item in hypothesis_ids]
            resolution = resolutions.get(readout, _EPSILON)
            discriminativeness_values.extend(
                _normalized_difference(left, right, resolution)
                for left, right in itertools.combinations(predictions, 2)
            )

        next_portfolio = (
            turns[index + 1].portfolio
            if index + 1 < len(turns)
            else final_portfolio
        )
        if next_portfolio is None:
            # The final evidence has no observed ex-post belief report.  Its
            # forecast separation remains scorable, but an update does not.
            continue
        before = _confidence_map(turn.portfolio)
        after = _confidence_map(next_portfolio)
        before_statements = _statement_map(turn.portfolio)
        after_statements = _statement_map(next_portfolio)
        persistent = [item for item in hypothesis_ids if item in after]
        errors: Dict[str, float] = {}
        for hypothesis_id in persistent:
            readout_errors = []
            for readout in turn.proposal.readouts:
                observed = evidence.measurements.get(readout)
                if (
                    isinstance(observed, bool)
                    or not isinstance(observed, (int, float))
                    or not math.isfinite(float(observed))
                ):
                    continue
                predicted = float(forecasts[hypothesis_id][readout])
                resolution = resolutions.get(readout, _EPSILON)
                readout_errors.append(
                    _normalized_difference(predicted, float(observed), resolution)
                )
            if readout_errors:
                errors[hypothesis_id] = sum(readout_errors) / len(readout_errors)

        for left, right in itertools.combinations(errors, 2):
            if (
                before_statements[left] != after_statements[left]
                or before_statements[right] != after_statements[right]
            ):
                # Reusing an ID for a materially rewritten statement does not
                # expose a posterior update for the same hypothesis.
                rewritten_pair_count += 1
                continue
            error_delta = errors[left] - errors[right]
            if math.isclose(error_delta, 0.0, rel_tol=0.0, abs_tol=_EPSILON):
                gap_before = before[left] - before[right]
                gap_after = after[left] - after[right]
                if not math.isclose(
                    gap_after, gap_before, rel_tol=0.0, abs_tol=_EPSILON
                ):
                    unsupported_shift_pair_count += 1
                continue
            favored, disfavored = (left, right) if error_delta < 0.0 else (right, left)
            gap_before = before[favored] - before[disfavored]
            gap_after = after[favored] - after[disfavored]
            gap_change = gap_after - gap_before
            if gap_change > _EPSILON:
                update_values.append(1.0)
                aligned_pair_count += 1
            elif gap_change < -_EPSILON:
                update_values.append(0.0)
                opposed_pair_count += 1
            else:
                update_values.append(0.5)
                inert_pair_count += 1

    return {
        "experiment_discriminativeness_mean": (
            sum(discriminativeness_values) / len(discriminativeness_values)
            if discriminativeness_values
            else 0.0
        ),
        "evidence_aligned_belief_update_rate": (
            sum(update_values) / len(update_values) if update_values else 0.0
        ),
        "forecast_pair_count": float(len(discriminativeness_values)),
        "scorable_belief_pair_count": float(len(update_values)),
        "belief_update_aligned_pair_count": float(aligned_pair_count),
        "belief_update_inert_pair_count": float(inert_pair_count),
        "belief_update_opposed_pair_count": float(opposed_pair_count),
        "unsupported_confidence_shift_pair_count": float(
            unsupported_shift_pair_count
        ),
        "hypothesis_rewrite_excluded_pair_count": float(rewritten_pair_count),
        "duplicate_setup_count": float(duplicate_setup_count),
    }


__all__ = ["score_trajectory"]
