"""Deterministic failure-mode analysis for terminal Player trajectories.

The analysis uses only observable benchmark records: ex-ante forecasts,
authoritative Oracle evidence, reported confidence changes, the committed
predictor, and the case evaluator result.  It locates an observable mismatch;
it does not infer a hidden psychological cause from model text.
"""

from __future__ import annotations

import itertools
import math
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from .expression import EXPRESSION_MODEL, ExpressionError, evaluate_expression_program


FAILURE_ANALYSIS_SCHEMA = "role_benchmark.failure_analysis"
_EPSILON = 1e-12


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _sequence(value: Any) -> Sequence[Any]:
    return value if isinstance(value, (list, tuple)) else ()


def _number(value: Any) -> Optional[float]:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        result = float(value)
    except (OverflowError, TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _event_payload(
    events: Sequence[Mapping[str, Any]], event_type: str
) -> Optional[Mapping[str, Any]]:
    for event in events:
        if event.get("event_type") == event_type:
            return {
                **_mapping(event.get("payload")),
                "_event_sequence": event.get("sequence"),
                "_event_type": event_type,
            }
    return None


def _indexed_payloads(
    events: Sequence[Mapping[str, Any]], event_type: str
) -> Mapping[int, Mapping[str, Any]]:
    result: Dict[int, Mapping[str, Any]] = {}
    for event in events:
        if event.get("event_type") != event_type:
            continue
        payload = _mapping(event.get("payload"))
        index = payload.get("action_index")
        if isinstance(index, int) and not isinstance(index, bool) and index > 0:
            result[index] = {**payload, "_event_sequence": event.get("sequence")}
    return result


def _confidence_map(action: Mapping[str, Any]) -> Mapping[str, float]:
    portfolio = _mapping(action.get("portfolio"))
    result: Dict[str, float] = {}
    for raw in _sequence(portfolio.get("hypotheses")):
        hypothesis = _mapping(raw)
        hypothesis_id = hypothesis.get("hypothesis_id")
        confidence = _number(hypothesis.get("confidence"))
        if isinstance(hypothesis_id, str) and confidence is not None:
            result[hypothesis_id] = confidence
    return result


def _statement_map(action: Mapping[str, Any]) -> Mapping[str, str]:
    portfolio = _mapping(action.get("portfolio"))
    result: Dict[str, str] = {}
    for raw in _sequence(portfolio.get("hypotheses")):
        hypothesis = _mapping(raw)
        hypothesis_id = hypothesis.get("hypothesis_id")
        statement = hypothesis.get("statement")
        if isinstance(hypothesis_id, str) and isinstance(statement, str):
            result[hypothesis_id] = statement
    return result


def _selected_hypothesis(action: Mapping[str, Any]) -> Mapping[str, Any]:
    final = _mapping(action.get("final"))
    selected_id = final.get("hypothesis_id")
    portfolio = _mapping(action.get("portfolio"))
    hypotheses = [_mapping(item) for item in _sequence(portfolio.get("hypotheses"))]
    if selected_id is None and hypotheses:
        selected_id = max(
            hypotheses,
            key=lambda item: _number(item.get("confidence")) or 0.0,
        ).get("hypothesis_id")
    for hypothesis in hypotheses:
        if hypothesis.get("hypothesis_id") == selected_id:
            return {
                "hypothesis_id": selected_id,
                "confidence": hypothesis.get("confidence"),
                "statement": hypothesis.get("statement"),
            }
    return {
        "hypothesis_id": selected_id,
        "confidence": None,
        "statement": None,
    }


def _readout_resolutions(case: Mapping[str, Any]) -> Mapping[str, float]:
    resources = _mapping(case.get("resources"))
    result: Dict[str, float] = {}
    for raw in _sequence(resources.get("readouts")):
        readout = _mapping(raw)
        name = readout.get("name")
        resolution = _number(readout.get("resolution"))
        if isinstance(name, str) and resolution is not None and resolution > 0.0:
            result[name] = resolution
    return result


def _mode(
    *,
    code: str,
    stage: str,
    message: str,
    action_index: Optional[int],
    evidence_turns: Iterable[int] = (),
    details: Optional[Mapping[str, Any]] = None,
    localization_basis: str,
    event_refs: Iterable[Mapping[str, Any]] = (),
) -> Mapping[str, Any]:
    return {
        "status": "fail",
        "code": code,
        "stage": stage,
        "message": message,
        "action_index": action_index,
        "evidence_turns": list(evidence_turns),
        "localization_basis": localization_basis,
        "event_refs": [dict(item) for item in event_refs],
        "details": dict(details or {}),
    }


def _event_ref(
    payload: Mapping[str, Any], event_type: str, json_path: str
) -> Mapping[str, Any]:
    return {
        "event_sequence": payload.get("_event_sequence"),
        "event_type": event_type,
        "json_path": json_path,
    }


def _terminal_payload(
    events: Sequence[Mapping[str, Any]],
) -> Optional[Mapping[str, Any]]:
    terminal = _event_payload(events, "episode.terminal")
    if terminal is not None:
        return terminal
    # Early development logs ended directly after a final-evaluation
    # transition.  The observable evaluation is sufficient for post-hoc
    # failure localization even though those logs predate episode.terminal.
    for event in reversed(events):
        if event.get("event_type") != "protocol.transition":
            continue
        payload = _mapping(event.get("payload"))
        if payload.get("outcome_kind") != "final_evaluation":
            continue
        evaluation = _mapping(_mapping(payload.get("outcome")).get("evaluation"))
        if not evaluation:
            continue
        return {
            "termination": {
                "kind": "submitted",
                "code": "submitted",
                "message": "Player committed a final submission.",
                "action_index": payload.get("action_index"),
            },
            "evaluation": evaluation,
            "trajectory_scores": _mapping(
                _mapping(payload.get("outcome")).get("trajectory_scores")
            ),
            "_event_sequence": event.get("sequence"),
            "_event_type": "protocol.transition",
        }
    return None


def _valid_evidence(transition: Mapping[str, Any]) -> Mapping[str, Any]:
    if transition.get("outcome_kind") != "experiment_evidence":
        return {}
    outcome = _mapping(transition.get("outcome"))
    response = _mapping(outcome.get("oracle_response"))
    if response.get("status") != "VALID":
        return {}
    return _mapping(response.get("evidence"))


def _forecast_errors_in_resolution_units(
    action: Mapping[str, Any],
    evidence: Mapping[str, Any],
    resolutions: Mapping[str, float],
) -> Mapping[str, float]:
    experiment = _mapping(action.get("experiment"))
    forecasts = _mapping(experiment.get("forecasts"))
    measurements = _mapping(evidence.get("measurements"))
    result: Dict[str, float] = {}
    for hypothesis_id, raw_predictions in forecasts.items():
        if not isinstance(hypothesis_id, str):
            continue
        predictions = _mapping(raw_predictions)
        errors = []
        for readout in _sequence(experiment.get("readouts")):
            if not isinstance(readout, str) or readout not in resolutions:
                continue
            predicted = _number(predictions.get(readout))
            observed = _number(measurements.get(readout))
            if predicted is None or observed is None:
                continue
            errors.append(abs(predicted - observed) / resolutions[readout])
        if errors:
            result[hypothesis_id] = sum(errors) / len(errors)
    return result


def _belief_update_modes(
    *,
    actions: Mapping[int, Mapping[str, Any]],
    transitions: Mapping[int, Mapping[str, Any]],
    resolutions: Mapping[str, float],
) -> Tuple[List[Mapping[str, Any]], int, int]:
    """Find confidence updates that do not follow the Player's own forecasts.

    Returned evidence is treated as discriminating a pair only when the
    hypotheses' mean realized forecast-error gap exceeds one public
    measurement-resolution unit.  This is distinct from whether the two
    ex-ante forecasts were themselves numerically separated.
    """

    modes: List[Mapping[str, Any]] = []
    scorable_turns = 0
    rewritten_pairs = 0
    ordered = sorted(actions)
    for position, action_index in enumerate(ordered[:-1]):
        action_payload = actions[action_index]
        action = _mapping(action_payload.get("action"))
        if action.get("kind") != "experiment":
            continue
        evidence = _valid_evidence(transitions.get(action_index, {}))
        if not evidence:
            continue
        errors = _forecast_errors_in_resolution_units(action, evidence, resolutions)
        if len(errors) < 2:
            continue
        next_index = ordered[position + 1]
        next_action = _mapping(actions[next_index].get("action"))
        before = _confidence_map(action)
        after = _confidence_map(next_action)
        before_statements = _statement_map(action)
        after_statements = _statement_map(next_action)
        candidates = []
        turn_is_scorable = False
        for left, right in itertools.combinations(sorted(errors), 2):
            if (
                left not in after
                or right not in after
                or before_statements.get(left) != after_statements.get(left)
                or before_statements.get(right) != after_statements.get(right)
            ):
                rewritten_pairs += 1
                continue
            error_gap = abs(errors[left] - errors[right])
            gap_before = before[left] - before[right]
            gap_after = after[left] - after[right]
            if error_gap <= 1.0:
                if not math.isclose(
                    gap_after, gap_before, rel_tol=0.0, abs_tol=_EPSILON
                ):
                    candidates.append(
                        (
                            2,
                            -abs(gap_after - gap_before),
                            "unsupported_confidence_shift",
                            left,
                            right,
                            gap_before,
                            gap_after,
                            error_gap,
                        )
                    )
                continue
            turn_is_scorable = True
            favored, disfavored = (
                (left, right) if errors[left] < errors[right] else (right, left)
            )
            if favored not in before or disfavored not in before:
                continue
            gap_before = before[favored] - before[disfavored]
            gap_after = after[favored] - after[disfavored]
            movement = gap_after - gap_before
            if movement < -_EPSILON:
                code = "belief_update_opposes_evidence"
            elif abs(movement) <= _EPSILON:
                code = "belief_update_omitted"
            else:
                continue
            candidates.append(
                (
                    0 if code == "belief_update_opposes_evidence" else 1,
                    -error_gap,
                    code,
                    favored,
                    disfavored,
                    gap_before,
                    gap_after,
                    error_gap,
                )
            )
        if turn_is_scorable:
            scorable_turns += 1
        if not candidates:
            continue
        (
            _priority,
            _negative_gap,
            code,
            favored,
            disfavored,
            gap_before,
            gap_after,
            error_gap,
        ) = sorted(candidates)[0]
        if code == "belief_update_opposes_evidence":
            message = (
                "After turn %d, confidence moved away from %s even though its "
                "forecast was closer to the observed readout than %s."
                % (action_index, favored, disfavored)
            )
        elif code == "belief_update_omitted":
            message = (
                "After turn %d, the confidence gap between evidence-favored %s "
                "and disfavored %s did not change."
                % (action_index, favored, disfavored)
            )
        else:
            message = (
                "After turn %d, confidence shifted between %s and %s even though "
                "the returned evidence did not discriminate between them under "
                "the configured realized-error-gap rule."
                % (action_index, favored, disfavored)
            )
        if code == "unsupported_confidence_shift":
            details = {
                "hypothesis_ids": [favored, disfavored],
                "forecast_error_resolution_units": {
                    favored: errors[favored],
                    disfavored: errors[disfavored],
                },
                "error_gap_resolution_units": error_gap,
                "classification_threshold_resolution_units": 1.0,
                "confidence_gap_before": gap_before,
                "confidence_gap_after": gap_after,
            }
        else:
            details = {
                "favored_hypothesis_id": favored,
                "disfavored_hypothesis_id": disfavored,
                "forecast_error_resolution_units": {
                    favored: errors[favored],
                    disfavored: errors[disfavored],
                },
                "error_gap_resolution_units": error_gap,
                "classification_threshold_resolution_units": 1.0,
                "confidence_gap_before": gap_before,
                "confidence_gap_after": gap_after,
            }
        modes.append(
            _mode(
                code=code,
                stage="belief_update",
                message=message,
                action_index=next_index,
                evidence_turns=(action_index,),
                details=details,
                localization_basis="deterministic_trajectory",
                event_refs=(
                    _event_ref(
                        transitions.get(action_index, {}),
                        "protocol.transition",
                        "$.payload.outcome.oracle_response.evidence",
                    ),
                    _event_ref(
                        actions[next_index],
                        "action.decoded",
                        "$.payload.action.portfolio",
                    ),
                ),
            )
        )
    return modes, scorable_turns, rewritten_pairs


def _candidate_prediction(
    case_id: str,
    final: Mapping[str, Any],
    controls: Mapping[str, Any],
) -> Mapping[str, float]:
    """Execute the built-in cases' public final-model contracts."""

    model = final.get("model")
    parameters = _mapping(final.get("parameters"))
    numeric_controls = {
        name: value
        for name, raw in controls.items()
        if (value := _number(raw)) is not None
    }
    if model == EXPRESSION_MODEL:
        try:
            return evaluate_expression_program(
                parameters,
                numeric_controls,
                allowed_variables=tuple(numeric_controls),
            )
        except (ExpressionError, ArithmeticError, ValueError):
            return {}

    try:
        if case_id.startswith("pendulum.") and model == "normalized_power_law":
            scale = float(parameters["reference_period_s"])
            length_exponent = float(parameters["length_exponent"])
            mass_exponent = float(parameters["mass_exponent"])
            return {
                "period_s": scale
                * (float(controls["length_m"]) / 1.0) ** length_exponent
                * (float(controls["bob_mass_kg"]) / 0.20) ** mass_exponent
            }
        if case_id.startswith("optical.interference.") and model == "double_slit_power_law":
            scale = float(parameters["reference_spacing_mm"])
            wavelength_exponent = float(parameters["wavelength_exponent"])
            distance_exponent = float(parameters["screen_distance_exponent"])
            separation_exponent = float(parameters["slit_separation_exponent"])
            return {
                "fringe_spacing_mm": scale
                * (float(controls["wavelength_nm"]) / 550.0) ** wavelength_exponent
                * (float(controls["screen_distance_m"]) / 1.0) ** distance_exponent
                    * (float(controls["slit_separation_mm"]) / 0.50)
                    ** separation_exponent
            }
        if case_id.startswith("sealed_gas.j_tube.") and model == "boyle_inverse_law":
            scale = float(parameters["reference_volume_ml"])
            ambient = float(parameters["ambient_pressure_kpa"])
            exponent = float(parameters["pressure_exponent"])
            absolute_pressure = ambient + float(controls["added_pressure_kpa"])
            return {
                "air_volume_ml": scale
                * (absolute_pressure / ambient) ** exponent,
                "absolute_pressure_kpa": absolute_pressure,
            }
        if (
            case_id.startswith("inclined_plane.descent.")
            and model == "inclined_plane_power_law"
        ):
            scale = float(parameters["reference_water_mass_g"])
            distance_exponent = float(parameters["distance_exponent"])
            sine_angle_exponent = float(parameters["sine_angle_exponent"])
            mass_exponent = float(parameters["mass_exponent"])
            sine_ratio = math.sin(
                math.radians(float(controls["incline_angle_deg"]))
            ) / math.sin(math.radians(5.0))
            return {
                "collected_water_g": scale
                * (float(controls["distance_m"]) / 1.0) ** distance_exponent
                * sine_ratio**sine_angle_exponent
                * (float(controls["ball_mass_kg"]) / 0.20) ** mass_exponent
            }
        if (
            case_id.startswith("phototube.response.")
            and model == "einstein_photoelectric_law"
        ):
            h_over_e = float(parameters["h_over_e_v_s"])
            work_function = float(parameters["work_function_equivalent_v"])
            current_scale = float(parameters["reference_saturation_current_ua"])
            excess = (
                h_over_e * float(controls["frequency_thz"]) * 1.0e12
                - work_function
            )
            return {
                "stopping_potential_v": max(0.0, excess),
                "saturation_current_ua": (
                    current_scale
                    * float(controls["absorbed_photon_flux_relative"])
                    if excess > 0.0
                    else 0.0
                ),
            }
        if (
            case_id.startswith("induction.coil.")
            and model == "faraday_flux_change_power_law"
        ):
            scale = float(parameters["reference_emf_mv"])
            return {
                "peak_emf_mv": scale
                * (float(controls["coil_turns"]) / 100.0)
                ** float(parameters["turn_exponent"])
                * (float(controls["loop_area_cm2"]) / 20.0)
                ** float(parameters["area_exponent"])
                * (float(controls["field_change_mt"]) / 10.0)
                ** float(parameters["field_change_exponent"])
                * (float(controls["change_time_ms"]) / 100.0)
                ** float(parameters["change_time_exponent"])
            }
        if (
            case_id.startswith("decaying_sample.counter.")
            and model == "single_exponential_decay"
        ):
            return {
                "count_rate_cpm": float(parameters["background_cpm"])
                + float(parameters["reference_activity_cpm"])
                * (float(controls["sample_mass_mg"]) / 1.0)
                ** float(parameters["mass_exponent"])
                * 2.0
                ** (
                    -float(controls["elapsed_time_min"])
                    / float(parameters["half_life_min"])
                )
            }
        if (
            case_id.startswith("foil_scattering.alpha.")
            and model == "rutherford_scattering_law"
        ):
            angular_ratio = math.sin(
                math.radians(float(controls["scattering_angle_deg"]) / 2.0)
            ) / math.sin(math.radians(30.0))
            return {
                "scattered_count_rate_cpm": float(
                    parameters["reference_count_rate_cpm"]
                )
                * (float(controls["foil_atomic_number"]) / 79.0)
                ** float(parameters["atomic_number_exponent"])
                * float(controls["target_areal_number_density_relative"])
                ** float(parameters["areal_number_density_exponent"])
                * float(controls["exposure_relative"])
                ** float(parameters["exposure_exponent"])
                * angular_ratio
                ** float(parameters["sine_half_angle_exponent"])
            }
    except (KeyError, OverflowError, TypeError, ValueError, ZeroDivisionError):
        return {}
    return {}


def _differing_control(
    left: Mapping[str, Any], right: Mapping[str, Any]
) -> Optional[str]:
    if set(left) != set(right):
        return None
    different = []
    for name in left:
        left_number = _number(left[name])
        right_number = _number(right[name])
        if left_number is not None and right_number is not None:
            same = math.isclose(
                left_number, right_number, rel_tol=0.0, abs_tol=_EPSILON
            )
        else:
            same = left[name] == right[name]
        if not same:
            different.append(name)
    return different[0] if len(different) == 1 else None


def _observed_fit_modes(
    *,
    case: Mapping[str, Any],
    actions: Mapping[int, Mapping[str, Any]],
    transitions: Mapping[int, Mapping[str, Any]],
    resolutions: Mapping[str, float],
) -> Tuple[List[Mapping[str, Any]], int]:
    """Check the committed predictor on evidence already shown to the Player."""

    final_indices = [
        index
        for index, payload in actions.items()
        if _mapping(payload.get("action")).get("kind") == "final"
    ]
    if not final_indices:
        return [], 0
    final_index = max(final_indices)
    final_action = _mapping(actions[final_index].get("action"))
    final = _mapping(final_action.get("final"))
    case_id = str(case.get("case_id", ""))
    if not final:
        return [], 0

    checked = 0
    worst: Optional[Mapping[str, Any]] = None
    for index, payload in sorted(actions.items()):
        action = _mapping(payload.get("action"))
        if action.get("kind") != "experiment":
            continue
        evidence = _valid_evidence(transitions.get(index, {}))
        measurements = _mapping(evidence.get("measurements"))
        controls = _mapping(_mapping(action.get("experiment")).get("controls"))
        prediction = _candidate_prediction(case_id, final, controls)
        for readout, raw_observed in measurements.items():
            if not isinstance(readout, str) or readout not in resolutions:
                continue
            observed = _number(raw_observed)
            predicted = _number(prediction.get(readout))
            if observed is None or predicted is None:
                continue
            checked += 1
            absolute_error = abs(predicted - observed)
            error_units = absolute_error / resolutions[readout]
            relative_error = absolute_error / max(abs(observed), resolutions[readout])
            candidate = {
                "turn_index": index,
                "readout": readout,
                "observed": observed,
                "predicted": predicted,
                "absolute_error": absolute_error,
                "relative_error": relative_error,
                "error_resolution_units": error_units,
                "controls": dict(controls),
            }
            if worst is None or error_units > float(
                worst.get("error_resolution_units", -1.0)
            ):
                worst = candidate

    if worst is None or float(worst["error_resolution_units"]) <= 1.0:
        return [], checked
    message = (
        "The committed predictor already misses observed turn %d: %s=%g was "
        "observed, but the predictor gives %g (%g public resolution units)."
        % (
            worst["turn_index"],
            worst["readout"],
            worst["observed"],
            worst["predicted"],
            worst["error_resolution_units"],
        )
    )
    return [
        _mode(
            code="final_model_misses_observed_evidence",
            stage="final_synthesis",
            message=message,
            action_index=final_index,
            evidence_turns=(int(worst["turn_index"]),),
            details={
                "worst_observed_fit": dict(worst),
                "selected_hypothesis": _selected_hypothesis(final_action),
            },
            localization_basis="deterministic_trajectory",
            event_refs=(
                _event_ref(
                    transitions.get(int(worst["turn_index"]), {}),
                    "protocol.transition",
                    "$.payload.outcome.oracle_response.evidence",
                ),
                _event_ref(
                    actions[final_index],
                    "action.decoded",
                    "$.payload.action.final",
                ),
            ),
        )
    ], checked


def _observed_contrast_modes(
    *,
    case: Mapping[str, Any],
    actions: Mapping[int, Mapping[str, Any]],
    transitions: Mapping[int, Mapping[str, Any]],
    resolutions: Mapping[str, float],
) -> Tuple[List[Mapping[str, Any]], int]:
    """Compare one-control evidence contrasts with the committed predictor."""

    final_indices = [
        index
        for index, payload in actions.items()
        if _mapping(payload.get("action")).get("kind") == "final"
    ]
    if not final_indices:
        return [], 0
    final_index = max(final_indices)
    final_action = _mapping(actions[final_index].get("action"))
    final = _mapping(final_action.get("final"))
    case_id = str(case.get("case_id", ""))
    if not final:
        return [], 0

    records = []
    for index, payload in sorted(actions.items()):
        action = _mapping(payload.get("action"))
        if action.get("kind") != "experiment":
            continue
        evidence = _valid_evidence(transitions.get(index, {}))
        measurements = _mapping(evidence.get("measurements"))
        experiment = _mapping(action.get("experiment"))
        controls = _mapping(experiment.get("controls"))
        if controls and measurements:
            records.append((index, controls, measurements))

    selected = _selected_hypothesis(final_action)
    strongest: Dict[Tuple[str, str, str], Mapping[str, Any]] = {}
    checked = 0
    for left, right in itertools.combinations(records, 2):
        left_index, left_controls, left_measurements = left
        right_index, right_controls, right_measurements = right
        control = _differing_control(left_controls, right_controls)
        if control is None:
            continue
        left_prediction = _candidate_prediction(case_id, final, left_controls)
        right_prediction = _candidate_prediction(case_id, final, right_controls)
        if not left_prediction or not right_prediction:
            continue
        for readout in sorted(set(left_measurements) & set(right_measurements)):
            resolution = resolutions.get(readout)
            left_observed = _number(left_measurements.get(readout))
            right_observed = _number(right_measurements.get(readout))
            left_predicted = _number(left_prediction.get(readout))
            right_predicted = _number(right_prediction.get(readout))
            if (
                resolution is None
                or left_observed is None
                or right_observed is None
                or left_predicted is None
                or right_predicted is None
            ):
                continue
            checked += 1
            observed_delta = right_observed - left_observed
            predicted_delta = right_predicted - left_predicted
            observed_units = abs(observed_delta) / resolution
            predicted_units = abs(predicted_delta) / resolution
            if observed_units > 1.0 and predicted_units <= 1.0:
                code = "final_model_omits_observed_effect"
                message = (
                    "Turns %d and %d changed only %s: %s changed from %g to %g, "
                    "but the committed predictor gives %g and %g."
                    % (
                        left_index,
                        right_index,
                        control,
                        readout,
                        left_observed,
                        right_observed,
                        left_predicted,
                        right_predicted,
                    )
                )
                strength = observed_units
            elif (
                observed_units > 1.0
                and predicted_units > 1.0
                and observed_delta * predicted_delta < 0.0
            ):
                code = "final_model_reverses_observed_effect"
                message = (
                    "Turns %d and %d isolate %s, but the committed predictor gives "
                    "the opposite %s direction."
                    % (left_index, right_index, control, readout)
                )
                strength = observed_units + predicted_units
            elif observed_units <= 1.0 and predicted_units > 1.0:
                code = "final_model_adds_unobserved_effect"
                message = (
                    "Turns %d and %d changed only %s without a resolved %s change, "
                    "but the committed predictor adds one."
                    % (left_index, right_index, control, readout)
                )
                strength = predicted_units
            else:
                continue
            key = (code, control, readout)
            details = {
                "control": control,
                "control_values": [left_controls[control], right_controls[control]],
                "readout": readout,
                "observed_values": [left_observed, right_observed],
                "predicted_values": [left_predicted, right_predicted],
                "observed_change_resolution_units": observed_units,
                "predicted_change_resolution_units": predicted_units,
                "selected_hypothesis": selected,
                "evidence_available_after_turn": max(left_index, right_index),
                "_strength": strength,
            }
            previous = strongest.get(key)
            if previous is None or strength > float(
                _mapping(previous.get("details")).get("_strength", -1.0)
            ):
                strongest[key] = _mode(
                    code=code,
                    stage="final_synthesis",
                    message=message,
                    action_index=final_index,
                    evidence_turns=(left_index, right_index),
                    details=details,
                    localization_basis="deterministic_trajectory",
                    event_refs=(
                        _event_ref(
                            transitions.get(left_index, {}),
                            "protocol.transition",
                            "$.payload.outcome.oracle_response.evidence",
                        ),
                        _event_ref(
                            transitions.get(right_index, {}),
                            "protocol.transition",
                            "$.payload.outcome.oracle_response.evidence",
                        ),
                        _event_ref(
                            actions[final_index],
                            "action.decoded",
                            "$.payload.action.final",
                        ),
                    ),
                )

    modes = []
    for mode in strongest.values():
        details = dict(_mapping(mode.get("details")))
        details.pop("_strength", None)
        modes.append({**mode, "details": details})
    return modes, checked


def _primary_mode(modes: Sequence[Mapping[str, Any]]) -> Optional[Mapping[str, Any]]:
    if not modes:
        return None
    stage_order = {
        "action_generation": 0,
        "protocol": 1,
        "stopping_and_commitment": 2,
        "experiment_design": 3,
        "belief_update": 4,
        "final_synthesis": 5,
        "final_model_specification": 6,
        "held_out_generalization": 7,
    }
    code_order = {
        "belief_update_opposes_evidence": 0,
        "belief_update_omitted": 1,
        "unsupported_confidence_shift": 2,
        "final_model_omits_observed_effect": 3,
        "final_model_reverses_observed_effect": 4,
        "final_model_adds_unobserved_effect": 5,
        "final_model_misses_observed_evidence": 6,
        "held_out_prediction_error": 7,
    }
    return min(
        modes,
        key=lambda mode: (
            mode.get("action_index")
            if isinstance(mode.get("action_index"), int)
            else 10**9,
            stage_order.get(str(mode.get("stage")), 99),
            code_order.get(str(mode.get("code")), 99),
            str(mode.get("code")),
        ),
    )


def _recovered_incidents(
    events: Sequence[Mapping[str, Any]],
    actions: Mapping[int, Mapping[str, Any]],
) -> List[Mapping[str, Any]]:
    incidents = []
    for event in events:
        if event.get("event_type") != "action.parse_failed":
            continue
        payload = _mapping(event.get("payload"))
        player_turn = payload.get("player_turn")
        if not isinstance(player_turn, int) or player_turn not in actions:
            continue
        error = _mapping(payload.get("wire_error"))
        incidents.append(
            {
                "status": "recovered",
                "stage": "action_generation",
                "code": error.get("code", "parse_failed"),
                "action_index": player_turn,
                "message": error.get("message", "A malformed action was repaired."),
                "event_refs": [
                    {
                        "event_sequence": event.get("sequence"),
                        "event_type": "action.parse_failed",
                        "json_path": "$.payload.wire_error",
                    },
                    _event_ref(
                        actions[player_turn],
                        "action.decoded",
                        "$.payload.action",
                    ),
                ],
            }
        )
    return incidents


def _terminal_player_stage(termination: Mapping[str, Any]) -> str:
    if termination.get("kind") == "player_output_invalid":
        return "action_generation"
    stopping_codes = {
        "experiment_budget_exhausted",
        "final_hypothesis_not_in_portfolio",
        "max_actions_reached",
        "stopping_condition_not_met",
    }
    return (
        "stopping_and_commitment"
        if termination.get("code") in stopping_codes
        or termination.get("kind") == "action_limit"
        else "protocol"
    )


def _evaluation_failure_stage(evaluation: Mapping[str, Any]) -> Tuple[str, str]:
    score_names = set(_mapping(evaluation.get("scores")))
    if any(name.startswith("hidden_") or "hidden_test" in name for name in score_names):
        return "held_out_generalization", "held_out_prediction_error"
    return "final_model_specification", "final_model_not_evaluable"


def analyze_failure_events(
    events: Sequence[Mapping[str, Any]],
    *, include_success: bool = False,
) -> Mapping[str, Any]:
    """Return one structured failure analysis for a completed run log.

    Every terminal failure receives at least its terminal or final-prediction
    failure.  Finer process modes are added whenever the decoded actions and
    logged evidence make them mechanically decidable, even if the Player never
    produced a strictly decoded final submission.
    """

    started = _event_payload(events, "run.started") or {}
    case = _mapping(started.get("case"))
    terminal = _terminal_payload(events)
    if terminal is None:
        return {
            "schema": FAILURE_ANALYSIS_SCHEMA,
            "status": "not_evaluated",
            "terminal_failure": None,
            "first_observed_misstep": None,
            "modes": [],
            "incidents": [],
            "coverage": {
                "forecast_update_turns": 0,
                "controlled_contrasts": 0,
                "observed_prediction_points": 0,
                "hypothesis_rewrite_pairs_excluded": 0,
                "natural_language_judge_used": False,
            },
        }

    evaluation = _mapping(terminal.get("evaluation"))
    termination = _mapping(terminal.get("termination"))
    termination_kind = termination.get("kind")
    protocol_violations = [
        _mapping(item) for item in _sequence(terminal.get("protocol_violations"))
    ]
    actions = _indexed_payloads(events, "action.decoded")
    incidents = _recovered_incidents(events, actions)
    passed = (
        termination_kind == "submitted"
        and evaluation.get("success") is True
        and not protocol_violations
    )
    if passed and not include_success:
        return {
            "schema": FAILURE_ANALYSIS_SCHEMA,
            "status": "passed_no_failure",
            "terminal_failure": None,
            "first_observed_misstep": None,
            "modes": [],
            "incidents": incidents,
            "coverage": {
                "forecast_update_turns": 0,
                "controlled_contrasts": 0,
                "observed_prediction_points": 0,
                "hypothesis_rewrite_pairs_excluded": 0,
                "natural_language_judge_used": False,
            },
        }

    transitions = _indexed_payloads(events, "protocol.transition")
    resolutions = _readout_resolutions(case)
    modes: List[Mapping[str, Any]] = []
    forecast_turns = 0
    controlled_contrasts = 0
    observed_prediction_points = 0
    rewritten_pairs = 0
    terminal_failure: Optional[Mapping[str, Any]] = None

    # Process diagnostics depend on observable actions and evidence, not on
    # whether the final action passed the hard protocol contract.  In
    # particular, a rejected decoded final can still be checked against all
    # evidence already returned to the Player.
    belief_modes, forecast_turns, rewritten_pairs = _belief_update_modes(
        actions=actions,
        transitions=transitions,
        resolutions=resolutions,
    )
    modes.extend(belief_modes)
    observed_fit_modes, observed_prediction_points = _observed_fit_modes(
        case=case,
        actions=actions,
        transitions=transitions,
        resolutions=resolutions,
    )
    modes.extend(observed_fit_modes)
    contrast_modes, controlled_contrasts = _observed_contrast_modes(
        case=case,
        actions=actions,
        transitions=transitions,
        resolutions=resolutions,
    )
    modes.extend(contrast_modes)

    if termination_kind != "submitted":
        terminal_failure = _mode(
            code=str(termination.get("code") or termination_kind or "failed"),
            stage=_terminal_player_stage(termination),
            message=str(termination.get("message") or "The episode failed."),
            action_index=(
                termination.get("action_index")
                if isinstance(termination.get("action_index"), int)
                else None
            ),
            details={"termination_kind": termination_kind},
            localization_basis="hard_contract",
            event_refs=(
                _event_ref(
                    terminal,
                    str(terminal.get("_event_type", "episode.terminal")),
                    (
                        "$.payload.termination"
                        if terminal.get("_event_type") == "episode.terminal"
                        else "$.payload.outcome.evaluation"
                    ),
                ),
            ),
        )
        modes.append(terminal_failure)
    elif protocol_violations:
        final_indices = [
            index
            for index, payload in actions.items()
            if _mapping(payload.get("action")).get("kind") == "final"
        ]
        action_index = max(final_indices) if final_indices else (
            termination.get("action_index")
            if isinstance(termination.get("action_index"), int)
            else None
        )
        terminal_failure = _mode(
            code=str(
                termination.get("code")
                or "submitted_with_protocol_violations"
            ),
            stage="stopping_and_commitment",
            message=str(
                termination.get("message")
                or "The final claim was evaluated with protocol violations."
            ),
            action_index=action_index,
            details={
                "termination_kind": termination_kind,
                "scientific_evaluation_success": evaluation.get("success") is True,
                "protocol_violations": [dict(item) for item in protocol_violations],
            },
            localization_basis="hard_contract",
            event_refs=(
                _event_ref(
                    terminal,
                    str(terminal.get("_event_type", "episode.terminal")),
                    "$.payload.protocol_violations",
                ),
            ),
        )
        modes.append(terminal_failure)
        for index, violation in enumerate(protocol_violations):
            modes.append(
                _mode(
                    code=str(violation.get("code") or "protocol_violation"),
                    stage="stopping_and_commitment",
                    message=str(
                        violation.get("message")
                        or "The final action violated the protocol contract."
                    ),
                    action_index=action_index,
                    details={"scientific_evaluation_success": evaluation.get("success") is True},
                    localization_basis="hard_contract",
                    event_refs=(
                        _event_ref(
                            terminal,
                            str(terminal.get("_event_type", "episode.terminal")),
                            "$.payload.protocol_violations[%d]" % index,
                        ),
                    ),
                )
            )
        if evaluation.get("success") is not True:
            scores = _mapping(evaluation.get("scores"))
            failure_stage, failure_code = _evaluation_failure_stage(evaluation)
            modes.append(
                _mode(
                    code=failure_code,
                    stage=failure_stage,
                    message=str(
                        evaluation.get("message")
                        or "The committed predictor failed the case evaluation."
                    ),
                    action_index=action_index,
                    details={"evaluation_scores": dict(scores)},
                    localization_basis="evaluator",
                    event_refs=(
                        _event_ref(
                            terminal,
                            str(terminal.get("_event_type", "episode.terminal")),
                            (
                                "$.payload.evaluation"
                                if terminal.get("_event_type") == "episode.terminal"
                                else "$.payload.outcome.evaluation"
                            ),
                        ),
                    ),
                )
            )
    elif not passed:
        final_indices = [
            index
            for index, payload in actions.items()
            if _mapping(payload.get("action")).get("kind") == "final"
        ]
        scores = _mapping(evaluation.get("scores"))
        failure_stage, failure_code = _evaluation_failure_stage(evaluation)
        terminal_failure = _mode(
            code=failure_code,
            stage=failure_stage,
            message=str(
                evaluation.get("message")
                or "The committed predictor failed the case evaluation."
            ),
            action_index=max(final_indices) if final_indices else None,
            details={"evaluation_scores": dict(scores)},
            localization_basis="evaluator",
            event_refs=(
                _event_ref(
                        terminal,
                        str(terminal.get("_event_type", "episode.terminal")),
                        (
                            "$.payload.evaluation"
                            if terminal.get("_event_type") == "episode.terminal"
                            else "$.payload.outcome.evaluation"
                        ),
                ),
            ),
        )
        modes.append(terminal_failure)

    modes = sorted(
        modes,
        key=lambda mode: (
            mode.get("action_index")
            if isinstance(mode.get("action_index"), int)
            else 10**9,
            str(mode.get("stage")),
            str(mode.get("code")),
        ),
    )
    return {
        "schema": FAILURE_ANALYSIS_SCHEMA,
        "status": "passed_analyzed" if passed else "failed_analyzed",
        "terminal_failure": terminal_failure,
        "first_observed_misstep": _primary_mode(modes),
        "modes": modes,
        "incidents": incidents,
        "coverage": {
            "forecast_update_turns": forecast_turns,
            "controlled_contrasts": controlled_contrasts,
            "observed_prediction_points": observed_prediction_points,
            "hypothesis_rewrite_pairs_excluded": rewritten_pairs,
            "natural_language_judge_used": False,
        },
    }


__all__ = ["FAILURE_ANALYSIS_SCHEMA", "analyze_failure_events"]
