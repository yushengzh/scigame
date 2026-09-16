"""Read historical physical-assessment records; never used for new judging.

Current evaluation lives in ``discovery_evaluation``. These identifiers and the
pure decoder preserve the meaning of previously stored scientific results.
"""
from .discovery_evaluation import _claim_text, _observable_projection as physical_projection
from .wire import WireDecodeError, strict_json_loads

PHYSICAL_PROMPT_VERSION = "role_benchmark.evaluator_prompt.v3_physical"
PHYSICAL_AXES = ("physical_explanation", "evidence_revision", "predictor_explanation_consistency")
EXPLANATION_KINDS = ("no_explanation", "formula_restatement", "empirical_relation", "model_based", "mechanism_claim", "mixed")
CHANGE_KINDS = ("parameter", "functional_form", "scope_or_assumptions", "mechanism", "retention", "unclear")
UPDATE_TYPES = ("supported_revision", "unsupported_revision", "appropriate_retention",
                "unchanged_despite_evidence", "insufficient_evidence")


def _error(path, detail):
    raise WireDecodeError("invalid_physical_assessment", path, detail)


def _keys(value, expected, path):
    if not isinstance(value, dict) or set(value) != set(expected):
        _error(path, "unexpected object fields")


def _text(value, path, maximum=2048):
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        _error(path, "expected bounded nonempty text")


def decode_physical_evaluation(text, projection, *, max_bytes=262144):
    value = strict_json_loads(text, max_bytes=max_bytes)
    _keys(value, ("explanation_kind", "assessments", "updates", "summary"), "$")
    if value["explanation_kind"] not in EXPLANATION_KINDS:
        _error("$.explanation_kind", "unknown explanation kind")
    _text(value["summary"], "$.summary", 4096)
    _keys(value["assessments"], PHYSICAL_AXES, "$.assessments")
    events = {e["sequence"]: e for e in projection["observable_transcript"]}
    for axis, row in value["assessments"].items():
        path = "$.assessments." + axis
        _keys(row, ("score", "rationale", "event_sequences"), path)
        score = row["score"]
        if score is not None and (isinstance(score, bool) or score not in (0, 0.5, 1)):
            _error(path, "score must be 0, 0.5, 1, or null")
        _text(row["rationale"], path)
        refs = row["event_sequences"]
        if (not isinstance(refs, list) or any(type(n) is not int or n not in events for n in refs)
                or len(refs) != len(set(refs)) or (score is not None and not refs)):
            _error(path, "score requires valid unique evidence references")
        if score is not None and not any(events[n]["event_type"] == "action.decoded" for n in refs):
            _error(path, "a scored explanation must cite a Player action")
    if not isinstance(value["updates"], list) or len(value["updates"]) > 32:
        _error("$.updates", "expected at most 32 observable comparisons")
    for update in value["updates"]:
        _keys(update, ("before_sequence", "observation_sequence", "after_sequence", "before_claim",
                       "after_claim", "judgment", "change_kind", "rationale"), "$.updates")
        seq = [update[k] for k in ("before_sequence", "observation_sequence", "after_sequence")]
        if any(type(n) is not int or n not in events for n in seq) or not seq[0] < seq[1] < seq[2]:
            _error("$.updates", "comparison requires chronological before/evidence/after events")
        before, observation, after = [events[n] for n in seq]
        if [x["event_type"] for x in (before, observation, after)] != ["action.decoded", "protocol.transition", "action.decoded"]:
            _error("$.updates", "comparison event types differ")
        if before["payload"].get("action_index") != observation["payload"].get("action_index"):
            _error("$.updates", "observation must follow the cited experiment")
        oracle = observation["payload"].get("outcome", {}).get("oracle_response", {})
        if oracle.get("status") != "VALID" or not oracle.get("evidence"):
            _error("$.updates", "comparison requires an actual valid observation")
        for key, event in (("before_claim", before), ("after_claim", after)):
            _text(update[key], "$.updates." + key)
            if not any(update[key] in claim for claim in _claim_text(event["payload"]["action"])):
                _error("$.updates." + key, "claim is not quoted from the cited action")
        if update["judgment"] not in UPDATE_TYPES:
            _error("$.updates", "unknown update judgment")
        if update["change_kind"] not in CHANGE_KINDS:
            _error("$.updates", "unknown change kind")
        _text(update["rationale"], "$.updates.rationale")
    revision = value["assessments"]["evidence_revision"]
    if revision["score"] is not None:
        comparable = [u for u in value["updates"] if u["judgment"] != "insufficient_evidence"]
        if not comparable or not any(
            {u[k] for k in ("before_sequence", "observation_sequence", "after_sequence")}
            <= set(revision["event_sequences"]) for u in comparable
        ):
            _error("$.assessments.evidence_revision", "revision score must cite an assessable before/evidence/after comparison")
    if value["assessments"]["predictor_explanation_consistency"]["score"] is not None:
        refs = value["assessments"]["predictor_explanation_consistency"]["event_sequences"]
        if not any(events[n]["event_type"] == "action.decoded" and
                   (events[n]["payload"].get("action", {}).get("final") or {}).get("explanation", "").strip()
                   for n in refs):
            _error("$.assessments.predictor_explanation_consistency", "must cite the final submission")
    return value
