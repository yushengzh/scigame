"""Append scientific post-evaluation to existing case-matrix episodes.

The source run is read-only. Formula measurements and summaries need no model
call; --judge additionally evaluates missing scientific explanations without
running the Player or Oracle again.
"""

import argparse
from copy import deepcopy
from dataclasses import fields
import json
from pathlib import Path

from experiments import run_case_matrix as matrix
from role_benchmark.discovery_evaluation import DISCOVERY_PROMPT_VERSION
from role_benchmark.performance import PERFORMANCE_PROTOCOL
from role_benchmark.runlog import load_run_log


MODE = "scientific_postevaluation_only"
EVALUATOR_OPTIONS = (
    "provider", "model", "api_key_env", "endpoint", "max_output_tokens",
    "timeout_s", "reasoning_effort", "thinking", "ifm_api_mode",
)


def _parser():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", required=True, help="Existing standard case-matrix run")
    parser.add_argument("--output-dir", required=True, help="Separate post-evaluation directory; may be resumed")
    parser.add_argument("--judge", action="store_true", help="Call only the Evaluator for missing scientific assessments")
    parser.add_argument("--evaluator-provider", choices=("deepseek", "openai", "gemini", "ifm"))
    parser.add_argument("--evaluator-model")
    parser.add_argument("--evaluator-api-key-env", help="Read the credential only from this environment variable")
    parser.add_argument("--evaluator-endpoint", help="Complete provider HTTP endpoint")
    parser.add_argument("--evaluator-max-output-tokens", type=int, default=8192)
    parser.add_argument("--evaluator-timeout-s", type=float)
    parser.add_argument("--evaluator-reasoning-effort", choices=("none", "minimal", "low", "medium", "high", "xhigh", "max"))
    parser.add_argument("--evaluator-thinking", choices=("enabled", "disabled"))
    parser.add_argument("--evaluator-ifm-api-mode", choices=("ifm_platform", "core42"))
    return parser


def _episode_spec(row):
    if row.get("schema") != matrix.EPISODE_RESULT_SCHEMA:
        raise ValueError("Expected standard case-matrix episode results; specialized historical/revision formats require their own explicit adapter.")
    names = [field.name for field in fields(matrix.EpisodeSpec)]
    missing = [name for name in names if name not in row]
    if missing:
        raise ValueError("Case-matrix episode is missing fields: " + ", ".join(missing))
    spec = matrix.EpisodeSpec(**{name: row[name] for name in names})
    if (spec.dataset_kind == matrix.DatasetKind.HISTORICAL_COUNTERFACTUAL.value
            and (spec.case_pack not in {matrix.HISTORICAL_CASE_PACK, matrix.BOTH_CASE_PACK}
                 or spec.variant_id != "canonical")):
        raise ValueError(
            "Archived Historical results require their original dataset reference and Git revision; "
            "they cannot be relabelled or scored as the current historical dataset.")
    try:
        pack = matrix.CASE_PACKS[spec.case_pack]
        family = pack.specifications[spec.case_family][spec.variant_id]
        world = pack.runtime_condition_ids.get(spec.case_family, {}).get(spec.condition_id, spec.condition_id)
        family.truths[world]
    except KeyError as exc:
        raise ValueError("Episode does not identify a registered case family, variant and world") from exc
    return spec


def _source_row(row, source_dir):
    copied = deepcopy(row)
    raw_path = row.get("log_path")
    if row.get("status") == "evaluated":
        if not isinstance(raw_path, str) or not raw_path:
            raise ValueError("Completed episode is missing its recorded log path")
        path = Path(raw_path)
        path = path if path.is_absolute() else source_dir / path
        path = path.resolve()
        log = load_run_log(str(path))
        if not log.complete or log.run_id != row.get("run_id"):
            raise ValueError("Episode result must refer to its own completed run log, including the recorded resume attempt")
        started = next(event["payload"] for event in log.events if event["event_type"] == "run.started")
        if started.get("case", {}).get("case_id") != row.get("case_id"):
            raise ValueError("Episode result and observable transcript identify different cases")
        copied["log_path"] = str(path)
    elif isinstance(raw_path, str) and raw_path:
        path = Path(raw_path)
        copied["log_path"] = str((path if path.is_absolute() else source_dir / path).resolve())
    copied["source_metrics_protocol"] = row.get("source_metrics_protocol", row.get("metrics_protocol", "legacy"))
    copied["metrics_protocol"] = PERFORMANCE_PROTOCOL
    for key in ("llm_evaluation", "llm_evaluation_status", "evaluator_llm_stats", "evaluator_result_path",
                "metrics_complete", "science_postevaluation"):
        copied.pop(key, None)
    return copied


def _usable_judge(result, row, options):
    if not result:
        return False
    if result.get("episode_id") != row["episode_id"] or result.get("run_id") != row.get("run_id"):
        return False
    for name in ("provider", "model"):
        requested = getattr(options, "evaluator_" + name)
        if requested is not None and result.get("evaluator_" + name) != requested:
            return False
    details = (result.get("evaluation") or {}).get("details") or {}
    return (result.get("status") == "evaluated"
            and result.get("evaluator_prompt_version") == DISCOVERY_PROMPT_VERSION
            and isinstance(details.get("understanding"), dict))


def _judge_args(options, case_pack):
    arguments = ["--output-dir", options.output_dir, "--case-pack", case_pack]
    for name in EVALUATOR_OPTIONS:
        value = getattr(options, "evaluator_" + name)
        if value is not None:
            arguments.extend(["--evaluator-" + name.replace("_", "-"), str(value)])
    return matrix._parser().parse_args(arguments)


def run_postevaluation(options, *, evaluator_backend_loader=None):
    """Write a separate result view and optionally fill missing judge outputs."""
    source = Path(options.run_dir).resolve()
    output = Path(options.output_dir).resolve()
    if source == output or source in output.parents:
        raise ValueError("Post-evaluation output must be separate from, and outside, the source run directory")
    rows = matrix.load_episode_results(source)
    if not rows:
        raise ValueError("No standard results/*.result.json found; specialized historical/revision formats are not automatically converted")
    specifications = [_episode_spec(row) for row in rows]
    experiment_ids = {row.get("experiment_id") for row in rows}
    if len(experiment_ids) != 1 or not next(iter(experiment_ids)):
        raise ValueError("Source episode results must belong to one identified experiment")
    config = {"source_run_dir": str(source), "mode": MODE, "experiment_id": next(iter(experiment_ids))}
    prepared = [_source_row(row, source) for row in rows]
    if (output / "config.json").exists():
        if json.loads((output / "config.json").read_text(encoding="utf-8")) != config:
            raise ValueError("Output directory belongs to a different source run")
    elif output.exists() and any(output.iterdir()):
        raise ValueError("Output must be new, empty, or an existing post-evaluation of this source")
    output.mkdir(parents=True, exist_ok=True)
    (output / "results").mkdir(exist_ok=True)
    (output / "evaluations").mkdir(exist_ok=True)
    if not (output / "config.json").exists():
        matrix._write_json(output / "config.json", config, exclusive=True)

    pending = []
    for spec, row in zip(specifications, prepared):
        target = matrix._result_path(output, spec)
        if target.exists():
            previous = json.loads(target.read_text(encoding="utf-8"))
            if previous.get("run_id") != row.get("run_id") or previous.get("log_path") != row.get("log_path"):
                raise ValueError("Source episode now points to a different attempt; use a new post-evaluation directory")
        if row.get("status") == "evaluated":
            row["formula_consistency"] = matrix._formula_result(spec, row)
        matrix._write_json(target, row)
        if row.get("status") != "evaluated":
            continue
        existing = matrix._load_evaluator_result(output, spec.episode_id)
        if _usable_judge(existing, row, options):
            continue
        reusable = matrix._load_evaluator_result(source, spec.episode_id)
        if _usable_judge(reusable, row, options):
            matrix._persist_evaluator_result(output, spec, reusable)
        else:
            pending.append((spec, row))

    # Save measurements and pending coverage even when no model is requested.
    results = matrix.write_summaries(output)
    if options.judge and pending:
        args = _judge_args(options, specifications[0].case_pack)
        credential = None if evaluator_backend_loader is not None else matrix._resolve_api_key(args, "evaluator")
        backend = matrix.load_role_backend(args, "evaluator", api_key=credential, loader=evaluator_backend_loader)
        for spec, row in pending:
            judged = matrix._run_evaluator(args, evaluator_backend=backend, output_dir=output,
                                           spec=spec, episode_result=row)
            matrix._persist_evaluator_result(output, spec, judged)
            results = matrix.write_summaries(output)
    return results


def main(argv=None):
    parser = _parser()
    options = parser.parse_args(argv)
    try:
        rows = run_postevaluation(options)
    except (ValueError, OSError) as exc:
        parser.error(str(exc))
    complete = sum(row.get("metrics_complete") is True for row in rows)
    print("Scientific post-evaluation: %d/%d episodes have complete metrics; source episodes preserved." % (complete, len(rows)))
    return int(options.judge and any(row.get("status") == "evaluated" and not row.get("metrics_complete") for row in rows))


if __name__ == "__main__":
    raise SystemExit(main())
