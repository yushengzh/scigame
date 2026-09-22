"""Episode state machine for sequential experiment and belief revision."""

from __future__ import annotations

import copy
from typing import List, Optional

from .models import (
    EpisodeOutcome,
    EpisodeResult,
    EpisodeTermination,
    EpisodeView,
    EvaluationResult,
    ExperimentTurn,
    FinalSubmission,
    HypothesisPortfolio,
    OracleResponse,
    PlayerAction,
    ProtocolViolation,
    TerminationKind,
)
from .metrics import HELD_OUT_PREDICTION_SCORE
from .protocols import BenchmarkCase, CaseOracle, Oracle
from .semantic_oracle import LLMSemanticOracle, prepare_semantic_oracle_case
from .trajectory import score_trajectory


class EpisodeProtocolError(ValueError):
    """Raised when the Player violates the episode protocol.

    ``code`` is stable and machine-readable; the human-readable exception
    message remains the first positional argument for backwards compatibility.
    """

    def __init__(
        self,
        message: str,
        *,
        code: str = "episode_protocol_error",
    ) -> None:
        if not isinstance(code, str) or not code.strip():
            raise ValueError("protocol error code must be non-empty text")
        super().__init__(message)
        self.code = code
        self.message = message


class Episode:
    """A single immutable-truth Player--Oracle interaction."""

    def __init__(
        self,
        case: BenchmarkCase,
        oracle: Optional[Oracle] = None,
        *,
        observation_budget: Optional[int] = None,
        initial_attempts_used: int = 0,
        require_budget_exhaustion: bool = False,
    ) -> None:
        # The semantic Oracle's public contract and charging rule must also
        # hold when callers use Episode directly, without the logged runner.
        if isinstance(oracle, LLMSemanticOracle):
            case = prepare_semantic_oracle_case(case)
            if oracle.definition != case.definition:
                raise ValueError("semantic Oracle definition must match the prepared case")
        # The public definition contains nested mappings/tuples.  Snapshot it so
        # external aliases cannot change resource or budget semantics mid-run.
        definition = copy.deepcopy(case.definition)
        self.case = BenchmarkCase(definition, case.world_model, case.evaluator)
        self.oracle = oracle or CaseOracle(definition, case.world_model)
        if observation_budget is None:
            observation_budget = definition.budget
        elif definition.budget is None:
            raise ValueError("an unlimited adaptive case cannot use a finite observation budget")
        if observation_budget is not None and (
            isinstance(observation_budget, bool)
            or not isinstance(observation_budget, int)
            or observation_budget < 0
            or (definition.budget is not None and observation_budget > definition.budget)
        ):
            raise ValueError(
                "observation_budget must be an integer between zero and case budget"
            )
        if (
            isinstance(initial_attempts_used, bool)
            or not isinstance(initial_attempts_used, int)
            or initial_attempts_used < 0
            or (observation_budget is not None and initial_attempts_used > observation_budget)
        ):
            raise ValueError(
                "initial_attempts_used must be between zero and observation_budget"
            )
        if not isinstance(require_budget_exhaustion, bool):
            raise ValueError("require_budget_exhaustion must be boolean")
        if observation_budget is None and require_budget_exhaustion:
            raise ValueError("an unlimited experiment budget cannot require exhaustion")
        self._observation_budget = observation_budget
        self._require_budget_exhaustion = require_budget_exhaustion
        self._initial_attempts_used = initial_attempts_used
        self._attempts_used = initial_attempts_used
        self._turns: List[ExperimentTurn] = []
        self._protocol_violations: List[ProtocolViolation] = []
        self._result: Optional[EpisodeResult] = None
        self._outcome: Optional[EpisodeOutcome] = None

    @property
    def finished(self) -> bool:
        return self._outcome is not None

    @property
    def result(self) -> EpisodeResult:
        if self._result is None:
            if self._outcome is None:
                raise EpisodeProtocolError(
                    "episode has not finished",
                    code="episode_not_finished",
                )
            raise EpisodeProtocolError(
                "episode terminated without a committed final submission",
                code="no_committed_final_submission",
            )
        return copy.deepcopy(self._result)

    @property
    def outcome(self) -> EpisodeOutcome:
        """Return either the committed result or a Player-side failure."""

        if self._outcome is None:
            raise EpisodeProtocolError(
                "episode has not finished",
                code="episode_not_finished",
            )
        return copy.deepcopy(self._outcome)

    def view(self) -> EpisodeView:
        return EpisodeView(
            case=copy.deepcopy(self.case.definition),
            attempts_used=self._attempts_used,
            attempts_remaining=(None if self._observation_budget is None
                                else self._observation_budget - self._attempts_used),
            turns=tuple(copy.deepcopy(self._turns)),
        )

    def apply(self, action: PlayerAction) -> Optional[OracleResponse]:
        if self.finished:
            raise EpisodeProtocolError(
                (
                    "the final submission is already committed"
                    if self._result is not None
                    else "episode is already terminated"
                ),
                code="episode_already_terminated",
            )
        if not isinstance(action, PlayerAction):
            raise EpisodeProtocolError(
                "action must be PlayerAction",
                code="invalid_action_type",
            )
        action = copy.deepcopy(action)
        if action.kind == "experiment":
            self._validate_experiment_portfolio(action.portfolio)
            return self._run_experiment(action)
        self._commit(action.portfolio, action.final)
        return None

    def terminate_player_failure(
        self,
        termination: EpisodeTermination,
        *,
        candidate_action: Optional[PlayerAction] = None,
    ) -> EpisodeOutcome:
        """End the episode after a Player-side failure.

        This path deliberately does not call the case evaluator: without a
        strictly decoded final submission there is no scientific claim to score.
        A decoded rejected action may be retained as evidence of what the
        Player supplied, but it is never repaired or committed.
        """

        if self.finished:
            raise EpisodeProtocolError(
                "episode is already terminated",
                code="episode_already_terminated",
            )
        if not isinstance(termination, EpisodeTermination):
            raise ValueError("termination must be an EpisodeTermination")
        if termination.kind == TerminationKind.SUBMITTED:
            raise ValueError(
                "terminate_player_failure requires a Player failure kind"
            )
        if candidate_action is not None and not isinstance(
            candidate_action, PlayerAction
        ):
            raise ValueError("candidate_action must be PlayerAction or None")

        evaluation = EvaluationResult(
            success=False,
            scores={
                "active_pass": 0.0,
                "protocol_completion": 0.0,
                "submission_available": 0.0,
                HELD_OUT_PREDICTION_SCORE: 0.0,
            },
            message=(
                "No strictly decoded final submission was available: "
                + termination.code
            ),
        )
        trajectory_scores = score_trajectory(
            self.case.definition,
            self._turns,
            final_portfolio=(
                candidate_action.portfolio
                if candidate_action is not None
                else None
            ),
        )
        self._outcome = EpisodeOutcome(
            case_id=self.case.definition.case_id,
            track=self.case.definition.track,
            attempts_used=self._attempts_used,
            turns=tuple(copy.deepcopy(self._turns)),
            termination=copy.deepcopy(termination),
            evaluation=evaluation,
            trajectory_scores=trajectory_scores,
            candidate_action=copy.deepcopy(candidate_action),
        )
        return copy.deepcopy(self._outcome)

    def _validate_experiment_portfolio(
        self, portfolio: HypothesisPortfolio
    ) -> None:
        if len(portfolio.hypotheses) > self.case.definition.max_hypotheses:
            raise EpisodeProtocolError(
                "portfolio exceeds the case's max_hypotheses",
                code="portfolio_limit_exceeded",
            )
        # The action's portfolio is the belief state before its experiment.
        # Unlimited adaptive episodes must stop as soon as that state crosses
        # the public threshold, before any Oracle call or attempt is recorded.
        threshold = getattr(self.case.definition, "confidence_threshold", None)
        if (
            self._observation_budget is None
            and threshold is not None
            and portfolio.top.confidence >= threshold
        ):
            violation = ProtocolViolation(
                code="confidence_stop_required",
                message=(
                    "Current portfolio confidence reaches or exceeds the public "
                    "threshold; submit a final predictor instead of an experiment."
                ),
            )
            # The logged runner records the rejected action and terminates. A
            # direct caller that catches this error must not erase the violation
            # by subsequently committing a scientifically correct final.
            if violation not in self._protocol_violations:
                self._protocol_violations.append(violation)
            raise EpisodeProtocolError(violation.message, code=violation.code)

    def _run_experiment(self, action: PlayerAction) -> OracleResponse:
        if self._observation_budget is not None and self._attempts_used >= self._observation_budget:
            raise EpisodeProtocolError(
                "experiment budget is exhausted; commit a final submission",
                code="experiment_budget_exhausted",
            )
        if action.experiment is None:
            raise EpisodeProtocolError(
                "experiment action has no proposal",
                code="missing_experiment",
            )
        proposal = copy.deepcopy(action.experiment)
        response = copy.deepcopy(self.oracle.respond(copy.deepcopy(proposal)))
        attempt_index = None
        if self.case.definition.count_all_experiment_attempts or response.consumes_budget:
            self._attempts_used += 1
            attempt_index = self._attempts_used
        self._turns.append(
            ExperimentTurn(
                turn_index=len(self._turns) + 1,
                portfolio=copy.deepcopy(action.portfolio),
                proposal=proposal,
                response=copy.deepcopy(response),
                attempt_index=attempt_index,
            )
        )
        return copy.deepcopy(response)

    def _commit(
        self,
        portfolio: HypothesisPortfolio,
        submission: Optional[FinalSubmission],
    ) -> None:
        if submission is None:
            raise EpisodeProtocolError(
                "final action has no submission",
                code="missing_final_submission",
            )
        if (
            self._require_budget_exhaustion
            and self._attempts_used < self._observation_budget
        ):
            raise EpisodeProtocolError(
                "the evaluation method requires exactly %d experiment attempts before final submission"
                % self._observation_budget,
                code="observation_budget_not_exhausted",
            )
        # Invalid and out-of-range experiments already consume attempts.
        # Once the attempt budget is exhausted, final submission must remain
        # possible even if fewer valid observations were obtained.
        violations = list(self._protocol_violations)
        if len(portfolio.hypotheses) > self.case.definition.max_hypotheses:
            violations.append(
                ProtocolViolation(
                    code="portfolio_limit_exceeded",
                    message="Final portfolio exceeds the case's max_hypotheses.",
                )
            )

        hypothesis_ids = [
            item.hypothesis_id for item in portfolio.hypotheses
        ]
        if any(
            hypothesis_id.strip().upper() == "OTHER"
            for hypothesis_id in hypothesis_ids
        ):
            violations.append(
                ProtocolViolation(
                    code="reserved_hypothesis_id",
                    message="OTHER is not a concrete hypothesis_id.",
                )
            )
        if len(hypothesis_ids) != len(set(hypothesis_ids)):
            violations.append(
                ProtocolViolation(
                    code="duplicate_hypothesis_id",
                    message="Final portfolio hypothesis_id values are not unique.",
                )
            )
        selected_id = submission.hypothesis_id or portfolio.top.hypothesis_id
        selected = [
            item for item in portfolio.hypotheses
            if item.hypothesis_id == selected_id
        ]
        if not selected:
            selected_confidence = None
            violations.append(
                ProtocolViolation(
                    code="final_hypothesis_not_in_portfolio",
                    message=(
                        "Final hypothesis_id is not in the final portfolio; "
                        "its confidence is therefore unavailable."
                    ),
                )
            )
        elif len(selected) > 1:
            selected_confidence = None
            violations.append(
                ProtocolViolation(
                    code="final_hypothesis_not_unique",
                    message=(
                        "Final hypothesis_id occurs more than once, so no "
                        "unique selected portfolio confidence is available."
                    ),
                )
            )
        else:
            selected_confidence = selected[0].confidence
        budget_exhausted = (
            self._observation_budget is not None
            and self._attempts_used >= self._observation_budget
        )
        threshold_reached = (
            selected_confidence is not None
            and selected_confidence >= self.case.definition.confidence_threshold
        )
        if (
            selected_confidence is not None
            and not budget_exhausted
            and not threshold_reached
        ):
            violations.append(
                ProtocolViolation(
                    code="stopping_condition_not_met",
                    message=(
                        "Selected portfolio confidence must reach or exceed the "
                        "public threshold for an unlimited adaptive episode."
                        if self._observation_budget is None else
                        "Selected portfolio confidence is below the public "
                        "threshold and the experiment budget is not exhausted."
                    ),
                )
            )
        scientific_evaluation = copy.deepcopy(
            self.case.evaluator.evaluate(copy.deepcopy(submission))
        )
        protocol_completed = not violations
        scores = dict(scientific_evaluation.scores)
        scores.update(
            {
                "active_pass": float(
                    scientific_evaluation.success and protocol_completed
                ),
                "protocol_completion": float(protocol_completed),
                "submission_available": 1.0,
            }
        )
        if selected_confidence is not None:
            scores.update(
                {
                    "selected_portfolio_confidence": selected_confidence,
                    "confidence_threshold_reached": float(threshold_reached),
                }
            )
        evaluation = EvaluationResult(
            success=scientific_evaluation.success,
            scores=scores,
            message=scientific_evaluation.message,
        )
        trajectory_scores = score_trajectory(
            self.case.definition,
            self._turns,
            portfolio,
        )
        self._result = EpisodeResult(
            case_id=self.case.definition.case_id,
            track=self.case.definition.track,
            attempts_used=self._attempts_used,
            turns=tuple(copy.deepcopy(self._turns)),
            final_portfolio=copy.deepcopy(portfolio),
            final_submission=copy.deepcopy(submission),
            evaluation=evaluation,
            trajectory_scores=trajectory_scores,
            protocol_violations=tuple(violations),
        )
        termination_code = (
            "submitted"
            if protocol_completed
            else "submitted_with_protocol_violations"
        )
        termination_message = (
            "Player committed a protocol-valid final submission."
            if protocol_completed
            else (
                "Player's strictly decoded final was scientifically evaluated "
                "with protocol violations."
            )
        )
        self._outcome = EpisodeOutcome(
            case_id=self._result.case_id,
            track=self._result.track,
            attempts_used=self._result.attempts_used,
            turns=tuple(copy.deepcopy(self._result.turns)),
            termination=EpisodeTermination(
                kind=TerminationKind.SUBMITTED,
                code=termination_code,
                message=termination_message,
                action_index=len(self._turns) + 1,
            ),
            evaluation=copy.deepcopy(self._result.evaluation),
            trajectory_scores=copy.deepcopy(self._result.trajectory_scores),
            final_portfolio=copy.deepcopy(self._result.final_portfolio),
            final_submission=copy.deepcopy(self._result.final_submission),
            protocol_violations=copy.deepcopy(
                self._result.protocol_violations
            ),
        )


__all__ = ["Episode", "EpisodeProtocolError"]
