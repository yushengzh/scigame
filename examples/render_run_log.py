"""Render one current Role Benchmark JSONL run as a static review page.

The ordinary run log contains only public case information, observable Player
actions, authoritative Oracle evidence, and post-episode evaluation.  Private
ground truth is accepted only as a separate, optional reviewer input and is
rendered after the trajectory.
"""

from __future__ import annotations

import argparse
import html
import json
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Sequence, Tuple

from role_benchmark.failure_modes import analyze_failure_events
from role_benchmark.runlog import LoadedRunLog, load_run_log
from role_benchmark.wire import (
    DEFAULT_MAX_JSON_BYTES,
    PLAYER_ACTION_SCHEMA,
    strict_json_loads,
)


class RunLogRenderError(ValueError):
    """A current run log cannot be represented as a paired transcript."""


def _escape(value: Any) -> str:
    return html.escape(str(value), quote=True)


def _json_text(value: Any, *, indent: Optional[int] = None) -> str:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        indent=indent,
        sort_keys=True,
        separators=None if indent is not None else (",", ":"),
    )


def _code(value: Any) -> str:
    if isinstance(value, (dict, list, tuple)):
        rendered = _json_text(value)
    elif value is None:
        rendered = "null"
    elif isinstance(value, bool):
        rendered = "true" if value else "false"
    else:
        rendered = str(value)
    return "<code>%s</code>" % _escape(rendered)


def _mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise RunLogRenderError("%s must be an object" % label)
    return value


def _array(value: Any, label: str) -> Sequence[Any]:
    if not isinstance(value, (list, tuple)):
        raise RunLogRenderError("%s must be an array" % label)
    return value


def _action_index(payload: Mapping[str, Any], label: str) -> int:
    value = payload.get("action_index")
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise RunLogRenderError("%s action_index must be a positive integer" % label)
    return value


def _percentage(value: Any) -> str:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return str(value)
    return "%g%%" % (100.0 * float(value))


def _fact(label: str, value: Any) -> str:
    return "<div><dt>%s</dt><dd>%s</dd></div>" % (
        _escape(label),
        _code(value),
    )


def _replay_outcome(
    terminal: Optional[Mapping[str, Any]],
    ended: Mapping[str, Any],
) -> Tuple[str, str]:
    if terminal is None:
        return ("INCOMPLETE", "neutral")
    termination = _mapping(terminal.get("termination"), "episode.terminal.termination")
    evaluation = _mapping(terminal.get("evaluation"), "episode.terminal.evaluation")
    if termination.get("kind") == "submitted":
        if evaluation.get("success") is True:
            return ("PASS", "pass")
        if evaluation.get("success") is False:
            return ("SCIENTIFIC FAILURE", "fail")
    if ended.get("status") == "evaluated":
        return ("PROTOCOL FAILURE", "fail")
    return (str(ended.get("status", "INCOMPLETE")).upper(), "neutral")


def _render_replay_context(
    metadata: Mapping[str, Any],
    case: Mapping[str, Any],
    terminal: Optional[Mapping[str, Any]],
    ended: Mapping[str, Any],
    *,
    player_model: Any,
    oracle_model: Any,
) -> str:
    outcome, outcome_class = _replay_outcome(terminal, ended)
    facts = "".join(
        (
            _fact("Episode", metadata.get("episode_id", "unspecified")),
            _fact("Family", metadata.get("case_family", "unspecified")),
            _fact("World", metadata.get("world", "unspecified")),
            _fact("Track", metadata.get("track", case.get("track", "unspecified"))),
            _fact("Repeat", metadata.get("repeat", "unspecified")),
            _fact("Player", player_model),
            _fact("Oracle", oracle_model),
        )
    )
    return """
    <section class="replay-context" id="replay-context" aria-labelledby="replay-context-title">
      <div class="context-heading">
        <h2 id="replay-context-title">Replay context</h2>
        <span class="outcome %s">%s</span>
      </div>
      <p class="compact">These labels describe the benchmark replay. The world label and post-episode outcome were not shown to the Player.</p>
      <dl class="facts">%s</dl>
    </section>
    """ % (_escape(outcome_class), _escape(outcome), facts)


def _render_public_case(case: Mapping[str, Any]) -> str:
    resources = _mapping(case.get("resources"), "run.started.payload.case.resources")
    instruments = _array(resources.get("instruments", []), "case.resources.instruments")
    controls = _array(resources.get("controls", []), "case.resources.controls")
    readouts = _array(resources.get("readouts", []), "case.resources.readouts")
    observations = _array(case.get("initial_observations", []), "case.initial_observations")
    notes = _array(resources.get("notes", []), "case.resources.notes")

    facts = "".join(
        (
            _fact("Case ID", case.get("case_id", "")),
            _fact("Track", case.get("track", "")),
            _fact("Experiment budget", case.get("budget", "")),
            _fact("Commit threshold", case.get("confidence_threshold", "")),
            _fact("Max hypotheses", case.get("max_hypotheses", "")),
            _fact("Max replicates", resources.get("max_replicates", "")),
        )
    )

    observation_items = "".join(
        "<li>%s</li>" % _escape(item) for item in observations
    ) or "<li>None recorded.</li>"

    instrument_items = []
    for index, item in enumerate(instruments):
        instrument = _mapping(item, "case.resources.instruments[%d]" % index)
        instrument_items.append(
            "<li><strong>%s</strong> — %s"
            "<div class=\"compact\">controls %s · readouts %s</div></li>"
            % (
                _escape(instrument.get("name", "")),
                _escape(instrument.get("description", "")),
                _code(instrument.get("controls", [])),
                _code(instrument.get("readouts", [])),
            )
        )
    instruments_html = "".join(instrument_items) or "<li>None recorded.</li>"

    control_rows = []
    for index, item in enumerate(controls):
        control = _mapping(item, "case.resources.controls[%d]" % index)
        if control.get("allowed_values"):
            domain = _code(control["allowed_values"])
        else:
            domain = "%s to %s" % (
                _code(control.get("minimum")),
                _code(control.get("maximum")),
            )
        control_rows.append(
            "<tr><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>"
            % (
                _code(control.get("name", "")),
                _escape(control.get("description", "")),
                domain,
                _escape(control.get("unit") or "—"),
            )
        )
    controls_html = "".join(control_rows) or (
        "<tr><td colspan=\"4\">None recorded.</td></tr>"
    )

    readout_rows = []
    for index, item in enumerate(readouts):
        readout = _mapping(item, "case.resources.readouts[%d]" % index)
        readout_rows.append(
            "<tr><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>"
            % (
                _code(readout.get("name", "")),
                _escape(readout.get("description", "")),
                _escape(readout.get("unit") or "—"),
                _code(readout.get("resolution")),
            )
        )
    readouts_html = "".join(readout_rows) or (
        "<tr><td colspan=\"4\">None recorded.</td></tr>"
    )
    notes_html = "".join("<li>%s</li>" % _escape(note) for note in notes)
    if not notes_html:
        notes_html = "<li>None recorded.</li>"

    return """
    <section class="public-case" id="public-case" aria-labelledby="public-case-title">
      <h2 id="public-case-title">Public case information supplied to Player</h2>
      <dl class="facts">%s</dl>
      <h3>%s</h3>
      <p>%s</p>
      <div class="public-grid">
        <div>
          <h3>Initial observations</h3><ul>%s</ul>
          <h3>Available apparatus</h3><ul>%s</ul>
        </div>
        <div>
          <h3>Controls</h3>
          <div class="table-wrap"><table><thead><tr><th>Name</th><th>Description</th><th>Domain</th><th>Unit</th></tr></thead><tbody>%s</tbody></table></div>
          <h3>Readouts</h3>
          <div class="table-wrap"><table><thead><tr><th>Name</th><th>Description</th><th>Unit</th><th>Resolution</th></tr></thead><tbody>%s</tbody></table></div>
        </div>
      </div>
      <h3>Resource and submission notes</h3><ol>%s</ol>
      <details><summary>Complete public case JSON</summary><pre>%s</pre></details>
    </section>
    """ % (
        facts,
        _escape(case.get("title", "")),
        _escape(case.get("background", "")),
        observation_items,
        instruments_html,
        controls_html,
        readouts_html,
        notes_html,
        _escape(_json_text(case, indent=2)),
    )


def _render_hypotheses(portfolio: Mapping[str, Any]) -> str:
    hypotheses = _array(portfolio.get("hypotheses", []), "action.portfolio.hypotheses")
    rows = []
    for index, item in enumerate(hypotheses):
        hypothesis = _mapping(item, "action.portfolio.hypotheses[%d]" % index)
        rows.append(
            "<div class=\"hypothesis\"><strong>%s</strong>"
            "<span class=\"confidence\">%s</span><span>%s</span></div>"
            % (
                _escape(hypothesis.get("hypothesis_id", "")),
                _escape(_percentage(hypothesis.get("confidence", ""))),
                _escape(hypothesis.get("statement", "")),
            )
        )
    return "".join(rows) or "<p>No decoded hypotheses.</p>"


def _render_forecasts(forecasts: Any) -> str:
    values = _mapping(forecasts, "action.experiment.forecasts")
    if not values:
        return "<p>No forecasts recorded.</p>"
    rows = []
    for hypothesis_id, prediction in values.items():
        rows.append(
            "<tr><td>%s</td><td>%s</td></tr>"
            % (_escape(hypothesis_id), _code(prediction))
        )
    return (
        "<div class=\"table-wrap\"><table><thead><tr><th>Hypothesis</th>"
        "<th>Ex-ante readout forecast</th></tr></thead><tbody>%s</tbody></table></div>"
        % "".join(rows)
    )


def _selected_portfolio_confidence(
    portfolio: Mapping[str, Any], final: Mapping[str, Any]
) -> Any:
    hypotheses = [
        _mapping(item, "action.portfolio.hypothesis")
        for item in _array(
            portfolio.get("hypotheses", []),
            "action.portfolio.hypotheses",
        )
    ]
    selected_id = final.get("hypothesis_id")
    if selected_id is None and hypotheses:
        selected_id = max(
            hypotheses,
            key=lambda item: (
                item.get("confidence")
                if isinstance(item.get("confidence"), (int, float))
                and not isinstance(item.get("confidence"), bool)
                else float("-inf")
            ),
        ).get("hypothesis_id")
    matches = [
        item.get("confidence")
        for item in hypotheses
        if item.get("hypothesis_id") == selected_id
    ]
    return matches[0] if len(matches) == 1 else "unavailable"


def _render_player(action: Mapping[str, Any]) -> str:
    portfolio = _mapping(action.get("portfolio"), "action.portfolio")
    kind = action.get("kind")
    sections = [
        "<h3>Player · %s</h3>" % _escape(kind or "action"),
        "<div class=\"hypotheses\">%s</div>" % _render_hypotheses(portfolio),
    ]
    if kind == "experiment":
        proposal = _mapping(action.get("experiment"), "action.experiment")
        sections.extend(
            (
                "<h4>Proposed experiment</h4>",
                "<dl class=\"pair-grid\">"
                "<dt>Intent</dt><dd>%s</dd>"
                "<dt>Apparatus</dt><dd>%s</dd>"
                "<dt>Controls</dt><dd>%s</dd>"
                "<dt>Readouts</dt><dd>%s</dd>"
                "<dt>Replicates</dt><dd>%s</dd></dl>"
                % (
                    _escape(proposal.get("intent", "")),
                    _code(proposal.get("apparatus", "")),
                    _code(proposal.get("controls", {})),
                    _code(proposal.get("readouts", [])),
                    _code(proposal.get("replicates", "")),
                ),
                "<h4>Forecasts made before evidence</h4>",
                _render_forecasts(proposal.get("forecasts", {})),
            )
        )
    elif kind == "final":
        final = _mapping(action.get("final"), "action.final")
        sections.extend(
            (
                "<h4>Committed answer</h4>",
                "<dl class=\"pair-grid\">"
                "<dt>Selected hypothesis</dt><dd>%s</dd>"
                "<dt>Selected portfolio confidence</dt><dd>%s</dd>"
                "<dt>Model</dt><dd>%s</dd>"
                "<dt>Parameters</dt><dd>%s</dd>"
                "<dt>Explanation</dt><dd>%s</dd>"
                "<dt>Scope</dt><dd>%s</dd></dl>"
                % (
                    _code(final.get("hypothesis_id")),
                    _escape(
                        _percentage(
                            _selected_portfolio_confidence(portfolio, final)
                        )
                    ),
                    _code(final.get("model", "")),
                    _code(final.get("parameters", {})),
                    _escape(final.get("explanation", "")),
                    _code(final.get("scope_conditions", [])),
                ),
            )
        )
    else:
        raise RunLogRenderError("decoded action has an unsupported kind %r" % kind)
    return "".join(sections)


def _positive_event_index(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise RunLogRenderError("%s must be a positive integer" % label)
    return value


def _render_rejected_player_attempt(
    completion: Mapping[str, Any],
    parse_failure: Optional[Mapping[str, Any]],
) -> str:
    call_index = _positive_event_index(
        completion.get("call_index"), "model.completed call_index"
    )
    player_turn = _positive_event_index(
        completion.get("player_turn"), "model.completed player_turn"
    )
    purpose = completion.get("purpose")
    if purpose not in ("next_action", "repair_action"):
        raise RunLogRenderError("rejected model completion has an invalid purpose")
    attempt_label = "primary" if purpose == "next_action" else "repair"
    status = completion.get("status")

    if status == "ok":
        if parse_failure is None:
            raise RunLogRenderError("rejected completion has no parse failure")
        if (
            parse_failure.get("call_index") != call_index
            or parse_failure.get("player_turn") != player_turn
        ):
            raise RunLogRenderError("parse failure does not match its completion")
        response = _mapping(
            completion.get("response"), "model.completed.payload.response"
        )
        raw_text = response.get("text")
        if not isinstance(raw_text, str):
            raise RunLogRenderError("rejected model response text must be a string")
        wire_error = _mapping(
            parse_failure.get("wire_error"), "action.parse_failed.payload.wire_error"
        )
        raw_html = (
            "<details><summary>Rejected raw completion</summary><pre>%s</pre></details>"
            % _escape(raw_text)
        )
    elif status == "output_rejected":
        if parse_failure is not None:
            raise RunLogRenderError(
                "output-rejected completion must not have a parse failure"
            )
        wire_error = _mapping(
            completion.get("wire_error"), "model.completed.payload.wire_error"
        )
        summary = _mapping(
            completion.get("response_summary"),
            "model.completed.payload.response_summary",
        )
        raw_html = (
            "<p>The provider output exceeded a logged safety bound, so its raw "
            "text was intentionally omitted.</p>"
            "<details><summary>Recorded response summary</summary><pre>%s</pre></details>"
            % _escape(_json_text(summary, indent=2))
        )
    else:
        raise RunLogRenderError("rejected model completion has an invalid status")

    return """
    <section class="turn rejected-attempt" aria-labelledby="rejected-%d-title">
      <div class="turn-label" id="rejected-%d-title">Player turn %d · rejected %s attempt · call %d</div>
      <div class="exchange">
        <article class="lane player rejected">
          <h3>Player · rejected output</h3>
          <p>This completion did not decode into an accepted protocol action.</p>
          <dl class="pair-grid">
            <dt>Error code</dt><dd>%s</dd>
            <dt>JSON path</dt><dd>%s</dd>
            <dt>Message</dt><dd>%s</dd>
          </dl>
          %s
        </article>
        <article class="lane oracle">
          <h3>Oracle · no call</h3>
          <p>The rejected Player completion never reached the experiment protocol, so no Oracle evidence was requested.</p>
        </article>
      </div>
    </section>
    """ % (
        call_index,
        call_index,
        player_turn,
        _escape(attempt_label),
        call_index,
        _code(wire_error.get("code", "")),
        _code(wire_error.get("path", "")),
        _escape(wire_error.get("message", "")),
        raw_html,
    )


def _rejected_attempt_sections(
    events: Sequence[Mapping[str, Any]],
) -> Sequence[Tuple[int, str]]:
    parse_failures: Dict[int, Mapping[str, Any]] = {}
    for event in events:
        if event.get("event_type") != "action.parse_failed":
            continue
        payload = _mapping(event.get("payload"), "action.parse_failed.payload")
        call_index = _positive_event_index(
            payload.get("call_index"), "action.parse_failed call_index"
        )
        if call_index in parse_failures:
            raise RunLogRenderError(
                "duplicate action.parse_failed for call_index %d" % call_index
            )
        parse_failures[call_index] = payload

    sections = []
    matched_failures = set()
    for event in events:
        if event.get("event_type") != "model.completed":
            continue
        payload = _mapping(event.get("payload"), "model.completed.payload")
        call_index = _positive_event_index(
            payload.get("call_index"), "model.completed call_index"
        )
        parse_failure = parse_failures.get(call_index)
        if payload.get("status") == "ok" and parse_failure is None:
            # Successful raw JSON is already represented by the decoded action.
            continue
        if payload.get("status") not in ("ok", "output_rejected"):
            continue
        sequence = _positive_event_index(
            event.get("sequence"), "model.completed sequence"
        )
        sections.append(
            (sequence, _render_rejected_player_attempt(payload, parse_failure))
        )
        if parse_failure is not None:
            matched_failures.add(call_index)

    unmatched = sorted(set(parse_failures) - matched_failures)
    if unmatched:
        raise RunLogRenderError(
            "parse failure has no matching model completion: call_index %d"
            % unmatched[0]
        )
    return tuple(sections)


def _render_evidence(evidence: Mapping[str, Any]) -> str:
    measurements = _mapping(evidence.get("measurements", {}), "evidence.measurements")
    units = _mapping(evidence.get("units", {}), "evidence.units")
    uncertainty = _mapping(evidence.get("uncertainty", {}), "evidence.uncertainty")
    rows = []
    for readout, value in measurements.items():
        rows.append(
            "<tr><td>%s</td><td><strong>%s</strong></td><td>%s</td><td>%s</td></tr>"
            % (
                _escape(readout),
                _escape(value),
                _escape(units.get(readout, "")),
                _escape(uncertainty.get(readout, "")),
            )
        )
    return (
        "<div class=\"table-wrap\"><table><thead><tr><th>Readout</th>"
        "<th>Measurement</th><th>Unit</th><th>Uncertainty</th></tr></thead>"
        "<tbody>%s</tbody></table></div>" % "".join(rows)
    )


def _render_oracle(
    action: Mapping[str, Any],
    transition: Mapping[str, Any],
    budget: Any,
) -> str:
    outcome_kind = transition.get("outcome_kind")
    if action.get("kind") == "final":
        extra = ""
        if outcome_kind != "final_evaluation":
            extra = "<p class=\"error\">%s</p>" % _escape(
                transition.get("error", transition.get("outcome", ""))
            )
        return (
            "<h3>Oracle · no call</h3>"
            "<p>The final submission ends the Player–Oracle dialogue and is sent "
            "to the separate evaluator.</p>%s" % extra
        )

    if outcome_kind != "experiment_evidence":
        return (
            "<h3>Oracle / protocol · %s</h3><p class=\"error\">%s</p>"
            % (
                _escape(outcome_kind or "no evidence"),
                _escape(transition.get("error", transition.get("outcome", ""))),
            )
        )
    outcome = _mapping(transition.get("outcome"), "protocol.transition.outcome")
    response = _mapping(
        outcome.get("oracle_response"),
        "protocol.transition.outcome.oracle_response",
    )
    evidence_value = response.get("evidence")
    evidence_html = ""
    if evidence_value is not None:
        evidence_html = _render_evidence(_mapping(evidence_value, "oracle_response.evidence"))
    used = transition.get("attempts_used_after", "")
    return (
        "<h3>Oracle · %s</h3><p>%s</p>%s"
        "<p class=\"compact\">Budget: %s / %s used</p>"
        % (
            _escape(response.get("status", "")),
            _escape(response.get("message", "")),
            evidence_html,
            _escape(used),
            _escape(budget),
        )
    )


def _render_terminal(terminal: Optional[Mapping[str, Any]], ended: Mapping[str, Any]) -> str:
    if terminal is None:
        return (
            "<section class=\"evaluation\" id=\"evaluation\"><h2>Run outcome</h2>"
            "<p>No evaluated episode. Run status: %s; stop reason: %s.</p></section>"
            % (_escape(ended.get("status", "")), _escape(ended.get("stop_reason", "")))
        )
    termination = _mapping(terminal.get("termination"), "episode.terminal.termination")
    evaluation = _mapping(terminal.get("evaluation"), "episode.terminal.evaluation")
    scores = _mapping(evaluation.get("scores", {}), "episode.terminal.evaluation.scores")
    trajectory = _mapping(
        terminal.get("trajectory_scores", {}),
        "episode.terminal.trajectory_scores",
    )
    score_rows = "".join(
        "<tr><td>%s</td><td>%s</td></tr>" % (_escape(name), _code(value))
        for name, value in scores.items()
    ) or "<tr><td colspan=\"2\">None recorded.</td></tr>"
    trajectory_rows = "".join(
        "<tr><td>%s</td><td>%s</td></tr>" % (_escape(name), _code(value))
        for name, value in trajectory.items()
    ) or "<tr><td colspan=\"2\">None recorded.</td></tr>"
    return """
    <section class="evaluation" id="evaluation" aria-labelledby="evaluation-title">
      <h2 id="evaluation-title">Post-episode evaluation</h2>
      <dl class="facts">
        %s%s%s%s
      </dl>
      <p>%s</p>
      <div class="evaluation-grid">
        <div><h3>Outcome scores</h3><table><tbody>%s</tbody></table></div>
        <div><h3>Trajectory scores</h3><table><tbody>%s</tbody></table></div>
      </div>
    </section>
    """ % (
        _fact("Termination", termination.get("kind", "")),
        _fact("Code", termination.get("code", "")),
        _fact("Scientific success", evaluation.get("success", "")),
        _fact("Run status", ended.get("status", "")),
        _escape(evaluation.get("message", "")),
        score_rows,
        trajectory_rows,
    )


def _render_failure_analysis(analysis: Mapping[str, Any]) -> str:
    if analysis.get("status") != "failed_analyzed":
        return ""
    primary = _mapping(
        analysis.get("first_observed_misstep"),
        "failure_analysis.first_observed_misstep",
    )
    modes = _array(analysis.get("modes", []), "failure_analysis.modes")
    coverage = _mapping(
        analysis.get("coverage", {}), "failure_analysis.coverage"
    )
    rows = []
    for index, raw in enumerate(modes):
        mode = _mapping(raw, "failure_analysis.modes[%d]" % index)
        evidence_turns = mode.get("evidence_turns", [])
        locus = "action %s" % mode.get("action_index")
        if evidence_turns:
            locus += " · evidence turns %s" % ", ".join(
                str(item) for item in evidence_turns
            )
        rows.append(
            "<article class=\"failure-mode\"><h3>%s · %s</h3>"
            "<p class=\"compact\">%s</p><p>%s</p><details>"
            "<summary>Structured evidence</summary><pre>%s</pre></details></article>"
            % (
                _escape(mode.get("stage", "")),
                _escape(mode.get("code", "")),
                _escape(locus),
                _escape(mode.get("message", "")),
                _escape(_json_text(mode.get("details", {}), indent=2)),
            )
        )
    return """
    <section class="failure-analysis" id="failure-analysis" aria-labelledby="failure-analysis-title">
      <h2 id="failure-analysis-title">Failure-mode analysis</h2>
      <p><strong>First observed misstep:</strong> %s at %s — %s</p>
      <p class="compact">This diagnostic locates recorded evidence/action inconsistencies; it does not infer a hidden psychological cause.</p>
      <dl class="facts">%s%s%s%s</dl>
      <div class="failure-list">%s</div>
    </section>
    """ % (
        _escape(primary.get("code", "")),
        _escape(primary.get("stage", "")),
        _escape(primary.get("message", "")),
        _fact("Forecast-update turns", coverage.get("forecast_update_turns", 0)),
        _fact("Observed prediction points", coverage.get("observed_prediction_points", 0)),
        _fact("Controlled contrasts", coverage.get("controlled_contrasts", 0)),
        _fact("Natural-language judge used", coverage.get("natural_language_judge_used", False)),
        "".join(rows),
    )


def _render_ground_truth(ground_truth: Optional[Mapping[str, Any]]) -> str:
    if ground_truth is None:
        return ""
    return """
    <section class="ground-truth" id="ground-truth" aria-labelledby="ground-truth-title">
      <h2 id="ground-truth-title">Private ground truth — revealed post-run</h2>
      <p>This reviewer-only input was not part of the Player public case or dialogue.</p>
      <pre>%s</pre>
    </section>
    """ % _escape(_json_text(ground_truth, indent=2))


_STYLE = """
  :root { color-scheme: light dark; font-family: ui-sans-serif, system-ui, sans-serif; }
  body { margin: 0; background: Canvas; color: CanvasText; }
  main { width: min(1200px, calc(100% - 32px)); margin: 0 auto; padding: 24px 0 48px; }
  header, section { padding: 16px 0; border-bottom: 1px solid color-mix(in srgb, CanvasText 18%, transparent); }
  h1, h2, h3, h4 { line-height: 1.25; }
  h1 { margin: 0 0 8px; }
  h2 { margin: 0 0 14px; }
  h3 { margin: 14px 0 8px; }
  h4 { margin: 16px 0 8px; }
  p { line-height: 1.55; }
  .context-heading { display: flex; align-items: center; justify-content: space-between; gap: 16px; }
  .context-heading h2 { margin: 0; }
  .outcome { display: inline-flex; align-items: center; border-radius: 999px; padding: 5px 10px; font-size: 0.78rem; font-weight: 800; letter-spacing: 0.04em; }
  .outcome.pass { color: #166534; background: color-mix(in srgb, #22c55e 18%, transparent); }
  .outcome.fail { color: #991b1b; background: color-mix(in srgb, #ef4444 18%, transparent); }
  .outcome.neutral { background: color-mix(in srgb, CanvasText 10%, transparent); }
  code, pre { font-family: ui-monospace, SFMono-Regular, Consolas, monospace; overflow-wrap: anywhere; }
  pre { white-space: pre-wrap; padding: 12px; background: color-mix(in srgb, CanvasText 6%, transparent); }
  .role-key, .facts { display: flex; flex-wrap: wrap; gap: 10px 22px; }
  .facts { margin: 0 0 14px; }
  .facts div { min-width: 130px; }
  dt, .compact { color: color-mix(in srgb, CanvasText 65%, transparent); }
  dd { margin: 2px 0 0; }
  .public-grid, .evaluation-grid, .dialogue-head, .exchange { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); gap: 20px; }
  .dialogue-head { padding: 8px 0; font-weight: 700; }
  .turn { padding: 16px 0; border-top: 1px solid color-mix(in srgb, CanvasText 14%, transparent); }
  .turn-label { margin-bottom: 8px; color: color-mix(in srgb, CanvasText 65%, transparent); }
  .lane { min-width: 0; padding: 0 14px; border-left: 4px solid #2563eb; }
  .lane.oracle { border-left-color: #c2410c; }
  .rejected-attempt .lane.player { border-left-color: #b91c1c; }
  .oracle-rejected { margin: 0 0 16px; padding: 10px 12px; border-left: 4px solid #b91c1c; background: color-mix(in srgb, #b91c1c 7%, transparent); }
  .oracle-rejected h4 { margin-top: 0; }
  .hypothesis { display: grid; grid-template-columns: 42px 58px minmax(0, 1fr); gap: 8px; padding: 5px 0; border-bottom: 1px solid color-mix(in srgb, CanvasText 12%, transparent); }
  .confidence { font-variant-numeric: tabular-nums; }
  .pair-grid { display: grid; grid-template-columns: max-content minmax(0, 1fr); gap: 6px 10px; }
  .table-wrap { overflow-x: auto; }
  table { width: 100%; border-collapse: collapse; }
  th, td { padding: 7px 8px; text-align: left; vertical-align: top; border-bottom: 1px solid color-mix(in srgb, CanvasText 14%, transparent); }
  .error { color: #b91c1c; }
  .failure-analysis { border-left: 5px solid #b91c1c; padding-left: 16px; }
  .failure-mode { padding: 10px 0; border-top: 1px solid color-mix(in srgb, CanvasText 14%, transparent); }
  .failure-mode h3 { font-family: ui-monospace, SFMono-Regular, Consolas, monospace; }
  .ground-truth { margin-top: 20px; border: 2px solid #7c3aed; padding: 16px; }
  @media (max-width: 720px) {
    .public-grid, .evaluation-grid, .dialogue-head, .exchange { grid-template-columns: 1fr; }
    .dialogue-head { display: none; }
    .lane.oracle { margin-top: 16px; }
  }
"""


def render_loaded_run(
    loaded: LoadedRunLog,
    *,
    ground_truth: Optional[Mapping[str, Any]] = None,
) -> str:
    """Render an already validated current run log to escaped static HTML."""

    if not loaded.complete:
        raise RunLogRenderError("run log is incomplete")
    if not loaded.events:
        raise RunLogRenderError("run log contains no events")
    started = _mapping(loaded.events[0].get("payload"), "run.started.payload")
    if started.get("action_schema") != PLAYER_ACTION_SCHEMA:
        raise RunLogRenderError("run log does not use the current action schema")
    case = _mapping(started.get("case"), "run.started.payload.case")

    actions: Dict[int, Tuple[int, Mapping[str, Any]]] = {}
    transitions: Dict[int, Tuple[int, Mapping[str, Any]]] = {}
    terminals = []
    ended: Optional[Mapping[str, Any]] = None
    for event in loaded.events:
        event_type = event.get("event_type")
        payload = _mapping(event.get("payload"), "%s.payload" % event_type)
        if event_type == "action.decoded":
            index = _action_index(payload, "action.decoded")
            if index in actions:
                raise RunLogRenderError("duplicate action.decoded for action_index %d" % index)
            action = _mapping(payload.get("action"), "action.decoded.payload.action")
            if action.get("wire_schema") != PLAYER_ACTION_SCHEMA:
                raise RunLogRenderError("decoded action does not use the current action schema")
            actions[index] = (event["sequence"], action)
        elif event_type == "protocol.transition":
            index = _action_index(payload, "protocol.transition")
            if index in transitions:
                raise RunLogRenderError(
                    "duplicate protocol.transition for action_index %d" % index
                )
            transitions[index] = (event["sequence"], payload)
        elif event_type == "episode.terminal":
            terminals.append(payload)
        elif event_type == "run.ended":
            ended = payload

    if set(actions) != set(transitions):
        raise RunLogRenderError(
            "action.decoded and protocol.transition action_index sets differ"
        )
    if len(terminals) > 1:
        raise RunLogRenderError("run log contains multiple episode.terminal events")
    if ended is None:
        raise RunLogRenderError("run log contains no run.ended event")

    dialogue_sections = list(_rejected_attempt_sections(loaded.events))
    for index in sorted(actions):
        action_sequence, action = actions[index]
        transition_sequence, transition = transitions[index]
        if action_sequence >= transition_sequence:
            raise RunLogRenderError(
                "protocol.transition precedes action.decoded for action_index %d" % index
            )
        dialogue_sections.append(
            (
                action_sequence,
                """
            <section class="turn" aria-labelledby="turn-%d-title">
              <div class="turn-label" id="turn-%d-title">Turn %d · %s</div>
              <div class="exchange">
                <article class="lane player">%s</article>
                <article class="lane oracle">%s</article>
              </div>
            </section>
            """
                % (
                    index,
                    index,
                    index,
                    _escape(action.get("kind", "action")),
                    _render_player(action),
                    _render_oracle(action, transition, case.get("budget", "")),
                ),
            )
        )

    metadata = _mapping(started.get("run_metadata", {}), "run.started.run_metadata")
    player_model = metadata.get("player_model", metadata.get("requested_model", "unspecified"))
    if started.get("oracle_mode") == "llm_case":
        oracle_model = metadata.get("oracle_model", "LLM Oracle")
    else:
        oracle_model = metadata.get("oracle_model", "CaseOracle")
    terminal = terminals[0] if terminals else None
    failure_analysis = analyze_failure_events(loaded.events)
    return """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>%s · Role Benchmark run</title>
  <style>%s</style>
</head>
<body>
<main>
  <header>
    <h1>%s · bench log</h1>
    <div class="role-key"><span><strong>Player</strong> %s</span><span><strong>Oracle</strong> %s</span></div>
  </header>
  %s
  %s
  <section class="dialogue" id="dialogue" aria-labelledby="dialogue-title">
    <h2 id="dialogue-title">Player ↔ Oracle</h2>
    <div class="dialogue-head" aria-hidden="true"><div>Player output</div><div>Oracle response</div></div>
    %s
  </section>
  %s
  %s
  %s
</main>
</body>
</html>
""" % (
        _escape(case.get("title", "Role Benchmark")),
        _STYLE,
        _escape(case.get("title", "Role Benchmark")),
        _code(player_model),
        _code(oracle_model),
        _render_replay_context(
            metadata,
            case,
            terminal,
            ended,
            player_model=player_model,
            oracle_model=oracle_model,
        ),
        _render_public_case(case),
        "".join(section for _sequence, section in sorted(dialogue_sections)),
        _render_terminal(terminal, ended),
        _render_failure_analysis(failure_analysis),
        _render_ground_truth(ground_truth),
    )


def load_ground_truth(path: str) -> Mapping[str, Any]:
    raw = Path(path).read_text(encoding="utf-8")
    value = strict_json_loads(raw, max_bytes=DEFAULT_MAX_JSON_BYTES)
    if not isinstance(value, Mapping):
        raise RunLogRenderError("ground-truth JSON must be an object")
    return value


def render_run_log(
    log_path: str,
    *,
    ground_truth: Optional[Mapping[str, Any]] = None,
) -> str:
    return render_loaded_run(load_run_log(log_path), ground_truth=ground_truth)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Render one current Role Benchmark JSONL log as static HTML."
    )
    parser.add_argument("run_log", help="Current JSONL run log")
    parser.add_argument(
        "--output-dir",
        required=True,
        help="Directory in which to create <run-log-stem>.html",
    )
    parser.add_argument(
        "--ground-truth-json",
        help="Optional reviewer-only JSON object rendered after the evaluation",
    )
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    try:
        ground_truth = (
            load_ground_truth(args.ground_truth_json)
            if args.ground_truth_json
            else None
        )
        rendered = render_run_log(args.run_log, ground_truth=ground_truth)
        output_dir = Path(args.output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / (Path(args.run_log).stem + ".html")
        with output_path.open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(rendered)
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    print(output_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
