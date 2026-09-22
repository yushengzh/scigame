"""Paired semantic-context ablation over an unchanged private discovery case.

Both arms use the same neutral interface. Only the familiar arm's background
contains a semantic sidecard. The manifest is private audit data: never put it
in a Player request. Import this module alongside the chosen frozen benchmark
runtime; it does not load, alter, or select a different source snapshot.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, dataclass, replace
import hashlib
import json
import re
from typing import Any, Mapping, Optional

from role_benchmark.evaluation_methods import (
    FixedExperiment, FixedObservation, PreparedEvaluationCase, _method_note,
    fixed_observation_to_payload,
)
from role_benchmark.expression import (
    EXPRESSION_LANGUAGE_VERSION, EXPRESSION_MAX_DEPTH, EXPRESSION_MAX_NODES,
    EXPRESSION_MODEL, EXPRESSION_OPERATOR_ARITIES,
)
from role_benchmark.models import (
    BenchmarkTrack, EvaluationResult, ExperimentEvidence, ExperimentProposal,
    FinalSubmission, InstrumentSpec, OracleResponse, OracleStatus,
)
from role_benchmark.protocols import BenchmarkCase, CaseOracle, WorldModelContractError
from role_benchmark.wire import canonical_json_dumps

SCHEMA = "scigame.semantic_ablation.v1"
ARMS = ("anonymous", "familiar")
_BACKGROUND = "Infer the fixed deterministic response of the supplied numerical interface from permitted observations."
_INITIAL = ("Every legal setup has a deterministic response. The active response remains fixed throughout the episode.",)


def opaque_case_id(identifier: str) -> str:
    """Use a family-level identifier, shared across worlds, arms and repeats."""
    return "case_" + hashlib.sha256(identifier.encode("utf-8")).hexdigest()[:16]


def _unknown(kind, value):
    # Unknown submitted names must not accidentally become valid original names.
    return "__ablation_invalid_" + kind + "_" + hashlib.sha256(str(value).encode()).hexdigest()[:16]


def _raise_neutral(exc, context):
    # Preserve ordinary exception categories while omitting private free text.
    try:
        neutral = type(exc)(context)
    except Exception:
        neutral = RuntimeError(context)
    raise neutral from None


def _common_notes(resources):
    arities = "; ".join("%s: %d..%s" % (name, lo, "unbounded" if hi is None else hi)
                        for name, (lo, hi) in EXPRESSION_OPERATOR_ARITIES.items())
    return (
        "Only listed controls, apparatus, and readouts are available. Keep all numeric values in their declared coordinate units; no rescaling is performed.",
        "A valid experiment changes only listed controls. Replicates and numeric bounds follow the resource catalog. Observation accounting and stopping follow the evaluation-method instructions.",
        "Portfolio confidences must sum to 1. A final portfolio may contain one hypothesis. The selected hypothesis's portfolio confidence determines stopping under the public confidence threshold.",
        "Submit model='%s' with parameters={'outputs': {READOUT: EXPR, ...}} and exactly outputs %s. "
        "An expression is a finite JSON number, {'var': CONTROL}, or {'op': OPERATOR, 'args': [CHILDREN]}. "
        "Language %s; at most %d nodes across outputs; root depth zero; maximum depth %d. "
        "Operator arities: %s. Trigonometric angles use radians; atan2 arguments are (y,x); cbrt is the real cube root. "
        "round uses ties to even; step(x)=1 for x>0 and 0 otherwise; sign(0)=0. "
        "Undefined or non-finite predictions are invalid and are never clipped or repaired."
        % (EXPRESSION_MODEL, ", ".join(r.name for r in resources.readouts),
           EXPRESSION_LANGUAGE_VERSION, EXPRESSION_MAX_NODES, EXPRESSION_MAX_DEPTH, arities),
    )


@dataclass(frozen=True)
class InterfaceMap:
    controls: Mapping[str, str]  # original -> neutral
    readouts: Mapping[str, str]
    instruments: Mapping[str, str]
    categories: Mapping[str, Mapping[str, str]]  # original control -> original string -> neutral string

    def names(self, kind, *, to_original):
        mapping = getattr(self, kind)
        return {value: key for key, value in mapping.items()} if to_original else mapping

    def name(self, kind, value, *, to_original):
        if isinstance(value, str) and not value.strip():
            return value
        return self.names(kind, to_original=to_original).get(value, _unknown(kind, value))

    def control_value(self, control, value, *, to_original):
        original = self.names("controls", to_original=True).get(control) if to_original else control
        categories = self.categories.get(original, {})
        if not isinstance(value, str):
            return deepcopy(value)
        mapping = {v: k for k, v in categories.items()} if to_original else categories
        return mapping.get(value, _unknown("category", value))

    def expression(self, tree, *, to_original):
        if isinstance(tree, dict):
            if set(tree) == {"var"}:
                return {"var": self.name("controls", tree["var"], to_original=to_original)}
            return {key: self.expression(value, to_original=to_original) for key, value in tree.items()}
        if isinstance(tree, list):
            return [self.expression(value, to_original=to_original) for value in tree]
        return deepcopy(tree)

    def submission(self, submission, *, to_original):
        parameters = deepcopy(submission.parameters)
        if submission.model == EXPRESSION_MODEL and isinstance(parameters.get("outputs"), Mapping):
            parameters["outputs"] = {
                self.name("readouts", key, to_original=to_original): self.expression(tree, to_original=to_original)
                for key, tree in parameters["outputs"].items()
            }
        return replace(submission, parameters=parameters)

    def proposal(self, proposal, *, to_original):
        return replace(proposal,
            intent=proposal.intent if to_original else ("Query the declared interface." if proposal.intent.strip() else ""),
            apparatus=self.name("instruments", proposal.apparatus, to_original=to_original),
            controls={self.name("controls", key, to_original=to_original):
                      self.control_value(key, value, to_original=to_original)
                      for key, value in proposal.controls.items()},
            readouts=tuple(self.name("readouts", key, to_original=to_original) for key in proposal.readouts),
            forecasts={hypothesis: {self.name("readouts", key, to_original=to_original): value
                                   for key, value in values.items()}
                       for hypothesis, values in proposal.forecasts.items()})

    def scores(self, scores, *, to_original):
        names = self.names("readouts", to_original=to_original)
        mapping = {old + "_max_scaled_error": new + "_max_scaled_error" for old, new in names.items()}
        return {mapping.get(key, key): value for key, value in scores.items()}


class _MappedWorld:
    def __init__(self, original, mapping, definition):
        self.original = original
        self.mapping = mapping
        self.definition = definition

    def run(self, proposal):
        try:
            reply = CaseOracle(self.original.definition, self.original.world_model).respond(
                self.mapping.proposal(proposal, to_original=True))
        except Exception as exc:
            _raise_neutral(exc, "The private numerical interface could not produce a valid response.")
        if reply.status is not OracleStatus.VALID or reply.evidence is None:
            raise WorldModelContractError("The mapped private interface rejected a publicly valid setup.")
        return neutral_evidence(reply.evidence, self.mapping, self.definition)


class _MappedEvaluator:
    def __init__(self, original, mapping):
        self.original = original
        self.mapping = mapping

    def evaluate(self, submission):
        try:
            result = self.original.evaluate(self.mapping.submission(submission, to_original=True))
        except Exception as exc:
            _raise_neutral(exc, "The private numerical evaluator could not evaluate the submitted predictor.")
        return EvaluationResult(result.success, self.mapping.scores(result.scores, to_original=False),
            "The predictor passed the held-out numerical tests." if result.success else
            "The predictor failed the held-out numerical tests or expression contract.")


def neutral_evidence(evidence, mapping, definition):
    measurements = {mapping.name("readouts", key, to_original=False): deepcopy(value)
                    for key, value in evidence.measurements.items()}
    units = {mapping.name("readouts", key, to_original=False):
             definition.resources.readout(mapping.name("readouts", key, to_original=False)).unit
             for key in evidence.units}
    uncertainty = {mapping.name("readouts", key, to_original=False):
                   definition.resources.readout(mapping.name("readouts", key, to_original=False)).uncertainty
                   for key in evidence.uncertainty}
    return ExperimentEvidence(measurements, units, uncertainty, "The numerical response is reported in the declared coordinate units.")


@dataclass(frozen=True)
class AdaptedCase:
    case: BenchmarkCase
    manifest: Mapping[str, Any]
    interface: InterfaceMap
    prepared: Optional[PreparedEvaluationCase] = None

    def to_original_proposal(self, proposal):
        return self.interface.proposal(proposal, to_original=True)

    def to_neutral_proposal(self, proposal):
        return self.interface.proposal(proposal, to_original=False)

    def to_original_submission(self, submission):
        return self.interface.submission(submission, to_original=True)

    def to_neutral_submission(self, submission):
        return self.interface.submission(submission, to_original=False)

    def to_original_scores(self, scores):
        return self.interface.scores(scores, to_original=True)

    def to_neutral_observation(self, observation):
        evidence = (neutral_evidence(observation.response.evidence, self.interface, self.case.definition)
                    if observation.response.evidence is not None else None)
        response = OracleResponse(observation.response.status,
            "The numerical response is reported in the declared coordinate units." if evidence else
            "The setup does not satisfy the declared interface contract.", evidence)
        return FixedObservation(observation.index, self.to_neutral_proposal(observation.proposal), response)


def adapt_case(case: BenchmarkCase, *, arm: str, opaque_id: str) -> AdaptedCase:
    """Adapt a raw DISCOVERY case; use adapt_prepared_case for method-prepared cases.

    All original free-text initial observations/notes are omitted in both arms.
    Use the prepared entry point to retain supplied fixed numerical observations.
    Numeric coordinates and private world/evaluator objects are never replaced.
    """
    if arm not in ARMS:
        raise ValueError("arm must be anonymous or familiar")
    if not re.fullmatch(r"case_[0-9a-f]{4,64}", opaque_id):
        raise ValueError("opaque_id must be case_ followed by 4..64 hexadecimal characters")
    if case.definition.track is not BenchmarkTrack.DISCOVERY:
        raise ValueError("Semantic ablation currently supports DISCOVERY only")
    resources = case.definition.resources
    if any(name.startswith("__ablation_invalid_") for collection in
           (resources.controls, resources.readouts, resources.instruments) for name in (item.name for item in collection)):
        raise ValueError("Resource names collide with reserved invalid-name namespace")
    mapping = InterfaceMap(
        {item.name: "x%d" % index for index, item in enumerate(resources.controls, 1)},
        {item.name: "y%d" % index for index, item in enumerate(resources.readouts, 1)},
        {item.name: "instrument_%d" % index for index, item in enumerate(resources.instruments, 1)},
        {item.name: {value: "category_%d_%d" % (index, j)
                     for j, value in enumerate(item.allowed_values, 1) if isinstance(value, str)}
         for index, item in enumerate(resources.controls, 1)})
    controls = tuple(replace(item, name=mapping.controls[item.name], description="Input coordinate %d." % i,
        unit="unit_" + mapping.controls[item.name], allowed_values=tuple(
            mapping.control_value(item.name, value, to_original=False) for value in item.allowed_values))
        for i, item in enumerate(resources.controls, 1))
    readouts = tuple(replace(item, name=mapping.readouts[item.name], description="Output coordinate %d." % i,
        unit="unit_" + mapping.readouts[item.name], statistic="deterministic numerical output",
        uncertainty=("Rounding interval +/- %s %s." % (repr(item.resolution / 2), "unit_" + mapping.readouts[item.name])
                     if item.resolution is not None and not item.uncertainty else
                     "Deterministic numerical output; original free-text uncertainty is not supplied."),
        resolution_kind="" if not item.resolution_kind else "declared numerical resolution")
        for i, item in enumerate(resources.readouts, 1))
    instruments = tuple(InstrumentSpec(mapping.instruments[item.name], "Numerical query interface %d." % i,
        tuple(mapping.controls[name] for name in item.controls),
        tuple(mapping.readouts[name] for name in item.readouts)) for i, item in enumerate(resources.instruments, 1))
    neutral_resources = replace(resources, controls=controls, readouts=readouts, instruments=instruments, notes=())
    neutral_resources = replace(neutral_resources, notes=_common_notes(neutral_resources))
    sidecard = {"title": case.definition.title, "background": case.definition.background,
        "controls": {mapping.controls[item.name]: {"original_name": item.name,
            "description": item.description, "unit": item.unit,
            "categorical_values": {value: key for key, value in mapping.categories[item.name].items()}}
            for item in resources.controls},
        "readouts": {mapping.readouts[item.name]: {"original_name": item.name,
            "description": item.description, "unit": item.unit} for item in resources.readouts},
        "instruments": {mapping.instruments[item.name]: {"original_name": item.name,
            "description": item.description} for item in resources.instruments}}
    background = _BACKGROUND
    if arm == "familiar":
        background += "\nSemantic context for the unchanged coordinate interface:\n" + json.dumps(sidecard, ensure_ascii=False, sort_keys=True)
    definition = replace(case.definition, case_id=opaque_id, title="Numerical response inference",
        background=background, initial_observations=_INITIAL, resources=neutral_resources)
    result = BenchmarkCase(definition, _MappedWorld(case, mapping, definition), _MappedEvaluator(case.evaluator, mapping))
    manifest = {"schema": SCHEMA, "arm": arm, "opaque_case_id": opaque_id,
        "mapping": asdict(mapping), "original_public_definition": asdict(case.definition),
        "semantic_sidecard": sidecard, "original_free_text_removed_in_both_arms": True,
        "semantic_treatment": "original title/background and resource names/descriptions/units; not notes, credits, truth parameters, or applicability",
        "numeric_fingerprints_retained": True, "coordinate_rescaling": False,
        "private_world_and_evaluator": "delegate unchanged original objects",
        "uncertainty_policy": "numeric resolution preserved; original free-text statistic/uncertainty/message omitted in both arms"}
    return AdaptedCase(result, manifest, mapping)


def adapt_prepared_case(prepared: PreparedEvaluationCase, *, arm: str, opaque_id: str) -> AdaptedCase:
    """Retain all fixed observations and method state, with neutral public names."""
    adapted = adapt_case(prepared.case, arm=arm, opaque_id=opaque_id)
    observations = tuple(adapted.to_neutral_observation(item) for item in prepared.fixed_observations)
    fixed = []
    for index, experiment in enumerate(prepared.plan.fixed_experiments, 1):
        proposal = adapted.to_neutral_proposal(experiment.proposal(index, prepared.plan.observation_budget))
        fixed.append(FixedExperiment(proposal.apparatus, tuple(proposal.controls.items()), proposal.readouts, proposal.replicates))
    plan = replace(prepared.plan, family=opaque_id, fixed_experiments=tuple(fixed))
    method_note = _method_note(plan)
    if prepared.case.definition.count_all_experiment_attempts:
        method_note = method_note.replace("All non-clarification experiment attempts are recorded.",
            "Every experiment request sent to the Oracle counts as one attempt, including rejected requests and requests needing clarification.")
    definition = replace(adapted.case.definition,
        resources=replace(adapted.case.definition.resources, notes=adapted.case.definition.resources.notes + (method_note,)),
        initial_observations=_INITIAL + tuple("Fixed experimental design observation %d/%d: %s" %
            (item.index, plan.observation_budget, canonical_json_dumps(fixed_observation_to_payload(item))) for item in observations))
    case = replace(adapted.case, definition=definition)
    neutral_prepared = replace(prepared, case=case, plan=plan, fixed_observations=observations)
    manifest = {**adapted.manifest, "evaluation_method": plan.method,
        "observation_budget": plan.observation_budget, "initial_attempts_used": prepared.initial_attempts_used,
        "fixed_observation_count": len(observations)}
    return replace(adapted, case=case, prepared=neutral_prepared, manifest=manifest)


__all__ = ["adapt_case", "adapt_prepared_case", "opaque_case_id", "AdaptedCase", "InterfaceMap", "SCHEMA", "ARMS"]
