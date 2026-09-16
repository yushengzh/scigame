"""Public data model for the role benchmark.

The module intentionally contains only small, serializable value objects. A
case exposes :class:`CaseDefinition` to the Player while keeping its world model
and evaluator private.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Mapping, Optional, Tuple

from .expression import EXPRESSION_MODEL, ExpressionError, validate_expression_program


def _is_number(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
    )


@dataclass(frozen=True)
class Hypothesis:
    """One current explanatory hypothesis reported by the Player."""

    hypothesis_id: str
    statement: str
    confidence: float

    def __post_init__(self) -> None:
        if not self.hypothesis_id.strip():
            raise ValueError("hypothesis_id must be non-empty")
        if not self.statement.strip():
            raise ValueError("hypothesis statement must be non-empty")
        if not _is_number(self.confidence) or not 0.0 <= self.confidence <= 1.0:
            raise ValueError("hypothesis confidence must be in [0, 1]")


@dataclass(frozen=True)
class HypothesisPortfolio:
    """A typed container for the Player's current hypotheses.

    Hypotheses may be added, removed, or rewritten between turns. Experiment
    actions enforce multiple concrete alternatives, unique IDs, and normalized
    support. Final actions defer those process checks to the episode so a
    strictly decoded scientific model is not discarded with bad metadata.
    """

    hypotheses: Tuple[Hypothesis, ...]

    def __post_init__(self) -> None:
        if not self.hypotheses:
            raise ValueError("a portfolio must contain at least one hypothesis")

    @property
    def top(self) -> Hypothesis:
        return max(self.hypotheses, key=lambda item: item.confidence)

    def confidence_of(self, hypothesis_id: str) -> float:
        for item in self.hypotheses:
            if item.hypothesis_id == hypothesis_id:
                return item.confidence
        raise KeyError(hypothesis_id)


@dataclass(frozen=True)
class ControlSpec:
    name: str
    description: str
    unit: str = ""
    minimum: Optional[float] = None
    maximum: Optional[float] = None
    allowed_values: Tuple[Any, ...] = ()


@dataclass(frozen=True)
class ReadoutSpec:
    name: str
    description: str
    unit: str = ""
    resolution: Optional[float] = None
    statistic: str = ""
    uncertainty: str = ""
    resolution_kind: str = ""


@dataclass(frozen=True)
class InstrumentSpec:
    name: str
    description: str
    controls: Tuple[str, ...]
    readouts: Tuple[str, ...]


@dataclass(frozen=True)
class ResourceCatalog:
    instruments: Tuple[InstrumentSpec, ...]
    controls: Tuple[ControlSpec, ...]
    readouts: Tuple[ReadoutSpec, ...]
    max_replicates: int = 1
    notes: Tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.max_replicates < 1:
            raise ValueError("max_replicates must be positive")
        for label, values in (
            ("instrument", self.instruments),
            ("control", self.controls),
            ("readout", self.readouts),
        ):
            names = [value.name for value in values]
            if len(names) != len(set(names)):
                raise ValueError("%s names must be unique" % label)

    def instrument(self, name: str) -> Optional[InstrumentSpec]:
        return next((item for item in self.instruments if item.name == name), None)

    def control(self, name: str) -> Optional[ControlSpec]:
        return next((item for item in self.controls if item.name == name), None)

    def readout(self, name: str) -> Optional[ReadoutSpec]:
        return next((item for item in self.readouts if item.name == name), None)


class BenchmarkTrack(str, Enum):
    """The scientific construct a case is designed to measure.

    Identification exposes the model family and asks for its unknown
    parameters.  Discovery keeps the truth-specific family private and asks
    for a generalizable executable predictor under a track-wide representation
    contract.
    """

    IDENTIFICATION = "identification"
    DISCOVERY = "discovery"


@dataclass(frozen=True)
class CaseDefinition:
    """The complete public information supplied to the Player."""

    case_id: str
    title: str
    background: str
    initial_observations: Tuple[str, ...]
    resources: ResourceCatalog
    budget: Optional[int]
    confidence_threshold: float
    track: BenchmarkTrack
    max_hypotheses: int = 6
    count_all_experiment_attempts: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.track, BenchmarkTrack):
            raise ValueError("track must be a BenchmarkTrack")
        if not isinstance(self.count_all_experiment_attempts, bool):
            raise ValueError("count_all_experiment_attempts must be boolean")
        if not self.case_id.strip() or not self.title.strip() or not self.background.strip():
            raise ValueError("case_id, title, and background must be non-empty")
        if self.budget is not None and (
            isinstance(self.budget, bool) or not isinstance(self.budget, int)
            or self.budget < 1
        ):
            raise ValueError("experiment budget must be positive or None for unlimited")
        if not 0.0 < self.confidence_threshold <= 1.0:
            raise ValueError("confidence_threshold must be in (0, 1]")
        if self.budget is None and self.confidence_threshold == 1.0:
            raise ValueError("unlimited confidence stopping requires a threshold below 1")
        if self.max_hypotheses < 2:
            raise ValueError("max_hypotheses must allow at least two hypotheses")


@dataclass(frozen=True)
class ExperimentProposal:
    """A complete experimental setup proposed by the Player.

    ``forecasts`` records an ex-ante numerical prediction for every requested
    readout under every hypothesis in the accompanying portfolio.  The
    PlayerAction invariant checks the hypothesis/readout keys before evidence
    is generated, making experiment choice and subsequent belief revision
    mechanically auditable without exposing private reasoning.
    """

    intent: str
    apparatus: str
    controls: Mapping[str, Any]
    readouts: Tuple[str, ...]
    replicates: int = 1
    forecasts: Mapping[str, Mapping[str, float]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.forecasts, Mapping):
            raise ValueError("experiment forecasts must be a mapping")
        for hypothesis_id, predictions in self.forecasts.items():
            if not isinstance(hypothesis_id, str) or not hypothesis_id.strip():
                raise ValueError("forecast hypothesis_id must be non-empty text")
            if not isinstance(predictions, Mapping):
                raise ValueError("each hypothesis forecast must be a mapping")
            for readout, value in predictions.items():
                if not isinstance(readout, str) or not readout.strip():
                    raise ValueError("forecast readout names must be non-empty text")
                if not _is_number(value):
                    raise ValueError("forecast values must be finite numbers")


@dataclass(frozen=True)
class ExperimentEvidence:
    measurements: Mapping[str, Any]
    units: Mapping[str, str] = field(default_factory=dict)
    uncertainty: Mapping[str, str] = field(default_factory=dict)
    message: str = ""


class OracleStatus(str, Enum):
    VALID = "VALID"
    NEEDS_CLARIFICATION = "NEEDS_CLARIFICATION"
    UNAVAILABLE_INSTRUMENT = "UNAVAILABLE_INSTRUMENT"
    OUT_OF_RANGE = "OUT_OF_RANGE"
    INVALID_SETUP = "INVALID_SETUP"


@dataclass(frozen=True)
class OracleResponse:
    status: OracleStatus
    message: str
    evidence: Optional[ExperimentEvidence] = None

    def __post_init__(self) -> None:
        if self.status == OracleStatus.VALID and self.evidence is None:
            raise ValueError("a VALID response must contain evidence")
        if self.status != OracleStatus.VALID and self.evidence is not None:
            raise ValueError("a non-VALID response must not contain evidence")

    @property
    def consumes_budget(self) -> bool:
        return self.status != OracleStatus.NEEDS_CLARIFICATION


@dataclass(frozen=True)
class FinalSubmission:
    """The Player's committed rationale and optional executable model."""

    explanation: str
    model: str = ""
    parameters: Mapping[str, Any] = field(default_factory=dict)
    hypothesis_id: Optional[str] = None
    scope_conditions: Tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.explanation.strip():
            raise ValueError("final explanation must be non-empty")
        if self.model == EXPRESSION_MODEL:
            try:
                validate_expression_program(self.parameters)
            except ExpressionError as exc:
                raise ValueError("invalid expression program: %s" % exc) from exc


@dataclass(frozen=True)
class EvaluationResult:
    """A case-specific result whose score names state measured constructs."""

    success: bool
    scores: Mapping[str, float] = field(default_factory=dict)
    message: str = ""


class TerminationKind(str, Enum):
    """Why an episode reached a terminal state.

    ``SUBMITTED`` means that a strictly decoded final scientific claim was
    evaluated.  Its portfolio or stopping metadata may still carry separately
    recorded protocol violations.  The other values have no decodable final
    claim to evaluate.
    """

    SUBMITTED = "submitted"
    PLAYER_OUTPUT_INVALID = "player_output_invalid"
    ACTION_REJECTED = "action_rejected"
    ACTION_LIMIT = "action_limit"


@dataclass(frozen=True)
class EpisodeTermination:
    """Stable, provider-neutral description of why an episode stopped."""

    kind: TerminationKind
    code: str
    message: str
    action_index: Optional[int] = None
    generation_attempts: Optional[int] = None

    def __post_init__(self) -> None:
        if not isinstance(self.kind, TerminationKind):
            raise ValueError("termination kind must be a TerminationKind")
        if not isinstance(self.code, str) or not self.code.strip():
            raise ValueError("termination code must be non-empty text")
        if not isinstance(self.message, str) or not self.message.strip():
            raise ValueError("termination message must be non-empty text")
        if self.action_index is not None and (
            isinstance(self.action_index, bool)
            or not isinstance(self.action_index, int)
            or self.action_index < 1
        ):
            raise ValueError("termination action_index must be a positive integer")
        if self.generation_attempts is not None and (
            isinstance(self.generation_attempts, bool)
            or not isinstance(self.generation_attempts, int)
            or self.generation_attempts < 1
        ):
            raise ValueError(
                "termination generation_attempts must be a positive integer"
            )


@dataclass(frozen=True)
class ProtocolViolation:
    """A process-contract violation attached to an evaluated final claim."""

    code: str
    message: str

    def __post_init__(self) -> None:
        if not isinstance(self.code, str) or not self.code.strip():
            raise ValueError("protocol violation code must be non-empty text")
        if not isinstance(self.message, str) or not self.message.strip():
            raise ValueError("protocol violation message must be non-empty text")


@dataclass(frozen=True)
class PlayerAction:
    """One Player turn: report beliefs, then experiment or commit."""

    kind: str
    portfolio: HypothesisPortfolio
    experiment: Optional[ExperimentProposal] = None
    final: Optional[FinalSubmission] = None

    def __post_init__(self) -> None:
        if self.kind not in ("experiment", "final"):
            raise ValueError("action kind must be 'experiment' or 'final'")
        if self.kind == "experiment":
            if self.experiment is None or self.final is not None:
                raise ValueError("experiment action requires only experiment")
            if len(self.portfolio.hypotheses) < 2:
                raise ValueError(
                    "experiment action requires at least two hypotheses"
                )
            hypothesis_ids_in_order = [
                item.hypothesis_id for item in self.portfolio.hypotheses
            ]
            if any(
                hypothesis_id.strip().upper() == "OTHER"
                for hypothesis_id in hypothesis_ids_in_order
            ):
                raise ValueError("OTHER is not a concrete hypothesis_id")
            if len(hypothesis_ids_in_order) != len(set(hypothesis_ids_in_order)):
                raise ValueError("hypothesis_id values must be unique")
            total = sum(
                item.confidence for item in self.portfolio.hypotheses
            )
            if not math.isclose(total, 1.0, rel_tol=0.0, abs_tol=1e-6):
                raise ValueError("hypothesis confidences must sum to 1")
            hypothesis_ids = set(hypothesis_ids_in_order)
            forecast_ids = set(self.experiment.forecasts)
            if forecast_ids != hypothesis_ids:
                raise ValueError(
                    "experiment forecasts must contain exactly every current hypothesis_id"
                )
            requested_readouts = set(self.experiment.readouts)
            for hypothesis_id, predictions in self.experiment.forecasts.items():
                if set(predictions) != requested_readouts:
                    raise ValueError(
                        "forecast %s must contain exactly every requested readout"
                        % hypothesis_id
                    )
        elif self.final is None or self.experiment is not None:
            raise ValueError("final action requires only final submission")

    @classmethod
    def propose_experiment(
        cls, portfolio: HypothesisPortfolio, experiment: ExperimentProposal
    ) -> "PlayerAction":
        return cls(kind="experiment", portfolio=portfolio, experiment=experiment)

    @classmethod
    def submit_final(
        cls, portfolio: HypothesisPortfolio, final: FinalSubmission
    ) -> "PlayerAction":
        return cls(kind="final", portfolio=portfolio, final=final)


@dataclass(frozen=True)
class ExperimentTurn:
    turn_index: int
    portfolio: HypothesisPortfolio
    proposal: ExperimentProposal
    response: OracleResponse
    attempt_index: Optional[int]


@dataclass(frozen=True)
class EpisodeView:
    case: CaseDefinition
    attempts_used: int
    attempts_remaining: Optional[int]
    turns: Tuple[ExperimentTurn, ...]


@dataclass(frozen=True)
class EpisodeResult:
    """Completed public result tagged with its measured benchmark construct."""

    case_id: str
    track: BenchmarkTrack
    attempts_used: int
    turns: Tuple[ExperimentTurn, ...]
    final_portfolio: HypothesisPortfolio
    final_submission: FinalSubmission
    evaluation: EvaluationResult
    trajectory_scores: Mapping[str, float] = field(default_factory=dict)
    protocol_violations: Tuple[ProtocolViolation, ...] = ()


@dataclass(frozen=True)
class EpisodeOutcome:
    """Terminal outcome for either a submission or a Player-side failure.

    A rejected action is retained only when it was already decoded as a strict
    :class:`PlayerAction`.  An undecodable output therefore has no
    ``candidate_action``.  This preserves what the Player actually supplied
    without repairing it or inventing a final answer.
    """

    case_id: str
    track: BenchmarkTrack
    attempts_used: int
    turns: Tuple[ExperimentTurn, ...]
    termination: EpisodeTermination
    evaluation: EvaluationResult
    trajectory_scores: Mapping[str, float] = field(default_factory=dict)
    final_portfolio: Optional[HypothesisPortfolio] = None
    final_submission: Optional[FinalSubmission] = None
    candidate_action: Optional[PlayerAction] = None
    protocol_violations: Tuple[ProtocolViolation, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.case_id, str) or not self.case_id.strip():
            raise ValueError("outcome case_id must be non-empty text")
        if not isinstance(self.track, BenchmarkTrack):
            raise ValueError("outcome track must be a BenchmarkTrack")
        if (
            isinstance(self.attempts_used, bool)
            or not isinstance(self.attempts_used, int)
            or self.attempts_used < 0
        ):
            raise ValueError("outcome attempts_used must be a non-negative integer")
        if not isinstance(self.termination, EpisodeTermination):
            raise ValueError("outcome termination must be an EpisodeTermination")
        if not isinstance(self.evaluation, EvaluationResult):
            raise ValueError("outcome evaluation must be an EvaluationResult")
        if self.candidate_action is not None and not isinstance(
            self.candidate_action, PlayerAction
        ):
            raise ValueError("outcome candidate_action must be PlayerAction or None")
        if any(
            not isinstance(item, ProtocolViolation)
            for item in self.protocol_violations
        ):
            raise ValueError(
                "outcome protocol_violations must contain ProtocolViolation values"
            )

        submitted = self.termination.kind == TerminationKind.SUBMITTED
        has_final = (
            self.final_portfolio is not None and self.final_submission is not None
        )
        has_partial_final = (
            self.final_portfolio is None
        ) != (
            self.final_submission is None
        )
        if has_partial_final:
            raise ValueError(
                "final_portfolio and final_submission must be present together"
            )
        if submitted and not has_final:
            raise ValueError("a submitted outcome requires a committed final")
        if not submitted and has_final:
            raise ValueError("a Player failure cannot contain a committed final")
        if not submitted and self.protocol_violations:
            raise ValueError(
                "only an evaluated final may contain protocol violations"
            )
        if submitted and self.candidate_action is not None:
            raise ValueError("a submitted outcome cannot contain a rejected action")

    @property
    def protocol_completed(self) -> bool:
        return (
            self.termination.kind == TerminationKind.SUBMITTED
            and not self.protocol_violations
        )

    @property
    def scientifically_evaluable(self) -> bool:
        return self.final_submission is not None

    @property
    def active_pass(self) -> bool:
        return self.protocol_completed and self.evaluation.success


__all__ = [
    "BenchmarkTrack",
    "CaseDefinition",
    "ControlSpec",
    "EpisodeOutcome",
    "EpisodeResult",
    "EpisodeTermination",
    "EpisodeView",
    "EvaluationResult",
    "ExperimentEvidence",
    "ExperimentProposal",
    "ExperimentTurn",
    "FinalSubmission",
    "Hypothesis",
    "HypothesisPortfolio",
    "InstrumentSpec",
    "OracleResponse",
    "OracleStatus",
    "PlayerAction",
    "ProtocolViolation",
    "ReadoutSpec",
    "ResourceCatalog",
    "TerminationKind",
]
