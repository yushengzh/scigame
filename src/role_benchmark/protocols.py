"""Player/Oracle interfaces and the truth-grounded case Oracle."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from .models import (
    CaseDefinition,
    EpisodeView,
    EvaluationResult,
    ExperimentEvidence,
    ExperimentProposal,
    FinalSubmission,
    OracleResponse,
    OracleStatus,
    PlayerAction,
)


@runtime_checkable
class WorldModel(Protocol):
    """Private case implementation that computes valid experimental evidence."""

    def run(self, proposal: ExperimentProposal) -> ExperimentEvidence:
        ...


@runtime_checkable
class FinalEvaluator(Protocol):
    """Private scorer for a committed final submission."""

    def evaluate(self, submission: FinalSubmission) -> EvaluationResult:
        ...


@runtime_checkable
class Oracle(Protocol):
    """The only environment role visible to the Player."""

    def respond(self, proposal: ExperimentProposal) -> OracleResponse:
        ...


@runtime_checkable
class PlayerBackend(Protocol):
    """A tested agent; an LLM adapter should implement this interface."""

    def next_action(self, view: EpisodeView) -> PlayerAction:
        ...


@dataclass(frozen=True)
class BenchmarkCase:
    """A public definition bound to a private world model and evaluator."""

    definition: CaseDefinition
    world_model: WorldModel
    evaluator: FinalEvaluator


class WorldModelContractError(RuntimeError):
    """The private world model violated the declared readout contract."""


def _finite_number(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
    )


class CaseOracle:
    """Validate a setup, execute the world model, and return one neutral reply.

    This is the benchmark's visible Oracle role. Valid evidence comes only from
    the case-defined world model.
    """

    def __init__(self, definition: CaseDefinition, world_model: WorldModel) -> None:
        self._definition = definition
        self._world_model = world_model

    def respond(self, proposal: ExperimentProposal) -> OracleResponse:
        problem = self._validate(proposal)
        if problem is not None:
            return problem
        evidence = self._world_model.run(proposal)
        expected = set(proposal.readouts)
        if set(evidence.measurements) != expected:
            raise WorldModelContractError(
                "world-model measurements must exactly match requested readouts"
            )
        if set(evidence.units) != expected:
            raise WorldModelContractError(
                "world-model units must exactly match requested readouts"
            )
        for readout, unit in evidence.units.items():
            declared = self._definition.resources.readout(readout)
            if declared is None or unit != declared.unit:
                raise WorldModelContractError(
                    "world-model unit for %s does not match the public contract"
                    % readout
                )
        if not set(evidence.uncertainty).issubset(expected):
            raise WorldModelContractError(
                "world model returned uncertainty for an unknown readout"
            )
        return OracleResponse(
            status=OracleStatus.VALID,
            message=evidence.message or "The experiment was executed as specified.",
            evidence=evidence,
        )

    def _validate(self, proposal: ExperimentProposal) -> Any:
        if not proposal.intent.strip():
            return OracleResponse(
                OracleStatus.NEEDS_CLARIFICATION,
                "State the purpose of the experiment.",
            )
        if not proposal.apparatus.strip():
            return OracleResponse(
                OracleStatus.NEEDS_CLARIFICATION,
                "Specify one available apparatus.",
            )

        resources = self._definition.resources
        instrument = resources.instrument(proposal.apparatus)
        if instrument is None:
            return OracleResponse(
                OracleStatus.UNAVAILABLE_INSTRUMENT,
                "The requested apparatus is not available in this case.",
            )

        if not proposal.readouts:
            return OracleResponse(
                OracleStatus.NEEDS_CLARIFICATION,
                "Specify at least one readout.",
            )
        unexpected_readouts = set(proposal.readouts) - set(instrument.readouts)
        if unexpected_readouts:
            return OracleResponse(
                OracleStatus.INVALID_SETUP,
                "Unsupported readout(s): %s."
                % ", ".join(sorted(unexpected_readouts)),
            )
        if len(proposal.readouts) != len(set(proposal.readouts)):
            return OracleResponse(
                OracleStatus.INVALID_SETUP,
                "Readouts must not be duplicated.",
            )

        supplied_controls = set(proposal.controls)
        required_controls = set(instrument.controls)
        missing = required_controls - supplied_controls
        if missing:
            return OracleResponse(
                OracleStatus.NEEDS_CLARIFICATION,
                "Specify control(s): %s." % ", ".join(sorted(missing)),
            )
        unexpected = supplied_controls - required_controls
        if unexpected:
            return OracleResponse(
                OracleStatus.INVALID_SETUP,
                "Unsupported control(s): %s." % ", ".join(sorted(unexpected)),
            )

        for name, value in proposal.controls.items():
            spec = resources.control(name)
            if spec is None:
                return OracleResponse(
                    OracleStatus.INVALID_SETUP,
                    "The control %s has no resource specification." % name,
                )
            if spec.allowed_values:
                if value not in spec.allowed_values:
                    return OracleResponse(
                        OracleStatus.OUT_OF_RANGE,
                        "%s must be one of the allowed values." % name,
                    )
            elif spec.minimum is not None or spec.maximum is not None:
                if not _finite_number(value):
                    return OracleResponse(
                        OracleStatus.INVALID_SETUP,
                        "%s must be a finite number." % name,
                    )
                numeric = float(value)
                if spec.minimum is not None and numeric < spec.minimum:
                    return OracleResponse(
                        OracleStatus.OUT_OF_RANGE,
                        "%s is below the available range." % name,
                    )
                if spec.maximum is not None and numeric > spec.maximum:
                    return OracleResponse(
                        OracleStatus.OUT_OF_RANGE,
                        "%s is above the available range." % name,
                    )

        if isinstance(proposal.replicates, bool) or not isinstance(
            proposal.replicates, int
        ):
            return OracleResponse(
                OracleStatus.INVALID_SETUP,
                "replicates must be an integer.",
            )
        if proposal.replicates < 1 or proposal.replicates > resources.max_replicates:
            return OracleResponse(
                OracleStatus.OUT_OF_RANGE,
                "replicates must be between 1 and %d." % resources.max_replicates,
            )
        return None


__all__ = [
    "BenchmarkCase",
    "CaseOracle",
    "FinalEvaluator",
    "Oracle",
    "PlayerBackend",
    "WorldModel",
    "WorldModelContractError",
]
