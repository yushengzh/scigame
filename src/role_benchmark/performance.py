"""Three separate measures of Player performance, with explicit coverage."""
from copy import deepcopy
from dataclasses import asdict

from .formula_consistency import compare_formulas, FORMULA_METRIC_VERSION

PERFORMANCE_PROTOCOL = "scigame.player_performance"


def discovery_reference_context(case, spec, world):
    """Use the same scientific questions at both observable endpoints."""
    reference = reference_context(case, spec, world)
    controls = ", ".join(c.name for c in spec.controls)
    outputs = ", ".join(r.name for r in spec.readouts)
    reference.update({
        "task_setting": case.definition.track.value,
        "understanding_criteria": [
            {"id": "relation_meaning", "question":
             "Explain the active-world dependence of %s on %s, including any necessary interactions. "
             "For identification, assess the unknown parameters and their meaning, not rediscovery of the given form."
             % (outputs, controls)},
            {"id": "controlled_comparison", "question":
             "Explain a valid controlled comparison or scaling consequence of this case's active relation. "
             "Distinguish relationships the observations contradict from those that remain valid; "
             "do not require every relation to change."},
            {"id": "scope_and_evidence", "question":
             "Explain the scope and limits of the scientific conclusion using only the assumptions "
             "and evidence available at this endpoint. A conditional hypothesis is not a proven claim; "
             "absence of observations at the baseline is not itself an error."},
        ],
    })
    # A mutation describes the authored sibling, not every active world. Giving
    # it to an original-world judge can contradict the authoritative predictor.
    if world == "counterfactual":
        reference["counterfactual_change"] = spec.counterfactual_change
        original = spec.truths["historical"]
        reference["original_world_comparison"] = {
            "predictor": {"outputs": deepcopy(dict(original.discovery_outputs))},
            "purpose": "Inactive original-world comparison only. Grade the active predictor above; this comparison is not the active law.",
        }
    # The Historical RC task has two independently meaningful relationships.
    # Freeze both questions across endpoints; do not let a judge choose whichever
    # happened to improve in a particular run.
    if spec.family == "rc_discharge":
        reference["understanding_criteria"][0]["question"] = (
            "For this RC discharge world, can R and C affect voltage only through their product RC? "
            "Explain the consequence of changing R and C at fixed RC, time and initial voltage. "
            "Use the actual reference law, not the textbook answer.")
        reference["understanding_criteria"][1]["question"] = (
            "For this RC discharge world, what happens when C and time are scaled together "
            "with R and initial voltage fixed? Explain whether this relation is preserved "
            "and what the available comparison or derivation establishes.")
    return reference


def reference_context(case, spec, world):
    """Maintainer-only reference for a sealed episode's explanation judge.

    This value must never be attached to the Player view or Oracle requests.
    Counterfactual relations come from the active world, not textbook memory.
    """
    truth = spec.truths[world]
    return deepcopy({"case_id": case.definition.case_id,
        "active_world": {"runtime_key": world,
            "is_counterfactual": world == "counterfactual"},
        "predictor": {"outputs": dict(truth.discovery_outputs)},
        "applicability": list(truth.applicability),
        "fixed_conditions": list(truth.fixed_conditions),
        "controls": [asdict(c) for c in case.definition.resources.controls],
        "readouts": [asdict(r) for r in case.definition.resources.readouts],
        "interpretation": "The predictor here is the authoritative active-world relation. If is_counterfactual is false, the original historical or source-reported relation is active and no sibling mutation applies. An empirical formula alone does not establish a causal mechanism."})


def formula_metric(submission, spec, world):
    if submission is None:
        return {"version": FORMULA_METRIC_VERSION, "status": "unavailable", "reason": "no_submission"}
    if submission.model != "expression":
        return {"version": FORMULA_METRIC_VERSION, "status": "not_equivalent", "method": "invalid_predictor_contract"}
    return compare_formulas(submission.parameters,
        {"outputs": dict(spec.truths[world].discovery_outputs)}, spec.controls,
        probes=tuple(spec.hidden_conditions) + tuple(spec.diagnostic_conditions))
