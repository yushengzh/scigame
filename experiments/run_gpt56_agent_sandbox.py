#!/usr/bin/env python3
"""Run one non-API-equivalent three-agent plumbing smoke.

The script intentionally bypasses ``run_case_matrix`` so its artifacts cannot
be mistaken for registered provider results.  Each LLM role uses a distinct
role-bound :class:`AgentFileExchangeBackend`; missing replies are captured as
request files and cause a clean pause.  Re-running after the matching response
files are supplied deterministically replays earlier replies and continues.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Optional, Sequence

from role_benchmark.agent_sandbox import (
    AGENT_SANDBOX_PROVIDER,
    AgentFileExchangeBackend,
    pending_agent_sandbox_requests,
)
from role_benchmark.cases import make_case
from role_benchmark.llm import (
    GenerationConfig,
    generation_response_to_payload,
)
from role_benchmark.llm_evaluator import (
    PostHocLLMEvaluator,
    llm_evaluation_to_payload,
)
from role_benchmark.models import BenchmarkTrack
from role_benchmark.runlog import load_run_log, replay_run_log, run_llm_episode
from role_benchmark.wire import canonical_json_dumps, evaluation_result_to_payload


SANDBOX_EXPERIMENT_ID = "EXP-METHOD-PILOT-GPT56-SANDBOX-001"
SANDBOX_MODEL = "gpt-5.6-sol"
ROLE_AGENT_IDS = {
    "player": "player_sandbox_agent",
    "oracle": "oracle_sandbox_agent",
    "evaluator": "evaluator_sandbox_agent",
}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run one pendulum plumbing smoke through three independently "
            "captured gpt-5.6 agent roles. This is not an API provider run."
        )
    )
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--exchange-dir")
    return parser


def _write_json(path: Path, payload: object) -> None:
    path.write_text(canonical_json_dumps(payload) + "\n", encoding="utf-8")


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _official_pilot_root() -> Path:
    return (Path(__file__).resolve().parents[1] / "runs" / "EXP-METHOD-PILOT-001").resolve()


def _reject_official_output(path: Path) -> None:
    official = _official_pilot_root()
    if path == official or official in path.parents:
        raise ValueError(
            "agent sandbox output must not be written under EXP-METHOD-PILOT-001"
        )


def _complete_log(output_dir: Path) -> Optional[Path]:
    for path in sorted((output_dir / "attempts").glob("episode-attempt-*.jsonl")):
        try:
            loaded = load_run_log(str(path))
            if (
                loaded.complete
                and loaded.events[-1]["event_type"] == "run.ended"
                and loaded.events[-1]["payload"].get("status") == "evaluated"
            ):
                return path
        except Exception:
            continue
    return None


def _next_attempt_path(output_dir: Path) -> Path:
    attempts = output_dir / "attempts"
    attempts.mkdir(parents=True, exist_ok=True)
    index = 1
    while True:
        path = attempts / ("episode-attempt-%02d.jsonl" % index)
        if not path.exists():
            return path
        index += 1


def _print_pending(exchange_dir: Path) -> None:
    pending = pending_agent_sandbox_requests(str(exchange_dir))
    if not pending:
        print("Sandbox paused without an identifiable pending response.")
        return
    print("Sandbox paused; supply the role-bound response for:")
    for path in pending:
        print(path)


def run(output_dir: Path, exchange_dir: Path) -> int:
    output_dir = output_dir.resolve()
    exchange_dir = exchange_dir.resolve()
    _reject_official_output(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    exchange_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = output_dir / "manifest.json"
    manifest = {
        "schema": "role_benchmark.agent_sandbox_manifest.v1",
        "experiment_id": SANDBOX_EXPERIMENT_ID,
        "classification": "sandbox_non_api_equivalent_not_for_scientific_inference",
        "formal_experiment_id": None,
        "provider": AGENT_SANDBOX_PROVIDER,
        "model": SANDBOX_MODEL,
        "roles": ROLE_AGENT_IDS,
        "case": {
            "family": "pendulum",
            "condition": "historical",
            "task_setting": "identification",
            "evaluation_method": "unregistered_plumbing_smoke",
        },
        "rules": {
            "three_distinct_backends": True,
            "oracle_evidence_source": "deterministic_world_model",
            "oracle_llm_policy": "exact_authoritative_message_copy",
            "evaluator_changes_scientific_score": False,
            "standard_api_pipeline_modified": False,
        },
    }
    if manifest_path.exists():
        if json.loads(manifest_path.read_text(encoding="utf-8")) != manifest:
            raise ValueError("sandbox output contains a different manifest")
    else:
        _write_json(manifest_path, manifest)

    backends = {
        role: AgentFileExchangeBackend(
            str(exchange_dir),
            role=role,
            agent_id=agent_id,
            model=SANDBOX_MODEL,
        )
        for role, agent_id in ROLE_AGENT_IDS.items()
    }
    if len({id(backend) for backend in backends.values()}) != 3:
        raise AssertionError("sandbox roles must use distinct backend instances")

    case = make_case(
        "pendulum",
        world="historical",
        track=BenchmarkTrack.IDENTIFICATION,
    )
    log_path = _complete_log(output_dir)
    if log_path is None:
        log_path = _next_attempt_path(output_dir)
        try:
            run_llm_episode(
                backends["player"],
                case,
                str(log_path),
                config=GenerationConfig(
                    max_output_tokens=8192,
                    temperature=0.0,
                    top_p=1.0,
                    seed=None,
                ),
                oracle_backend=backends["oracle"],
                oracle_config=GenerationConfig(
                    max_output_tokens=256,
                    temperature=0.0,
                    top_p=1.0,
                    seed=None,
                ),
                max_repair_attempts=0,
                max_actions=6,
                run_id="gpt56-agent-sandbox-pendulum",
                run_metadata={
                    "experiment_id": SANDBOX_EXPERIMENT_ID,
                    "classification": manifest["classification"],
                    "provider": AGENT_SANDBOX_PROVIDER,
                    "model": SANDBOX_MODEL,
                    "role_agent_ids": ROLE_AGENT_IDS,
                },
            )
        except Exception:
            _print_pending(exchange_dir)
            return 2

    replay = replay_run_log(str(log_path), case)
    if replay.outcome.termination.kind.value != "submitted":
        raise RuntimeError("sandbox Player must finish with a submitted final")
    if replay.outcome.attempts_used < 1:
        raise RuntimeError(
            "sandbox Player must execute at least one experiment so the Oracle agent participates"
        )
    evaluator_result_path = output_dir / "evaluator.json"
    if not evaluator_result_path.exists():
        try:
            evaluator_run = PostHocLLMEvaluator(
                backends["evaluator"],
                config=GenerationConfig(
                    max_output_tokens=2048,
                    temperature=0.0,
                    top_p=1.0,
                    seed=None,
                ),
            ).evaluate(load_run_log(str(log_path)))
        except Exception:
            _print_pending(exchange_dir)
            return 2
        _write_json(
            evaluator_result_path,
            {
                "schema": "role_benchmark.agent_sandbox_evaluator_result.v1",
                "experiment_id": SANDBOX_EXPERIMENT_ID,
                "classification": manifest["classification"],
                "response": generation_response_to_payload(evaluator_run.response),
                "evaluation": llm_evaluation_to_payload(evaluator_run.evaluation),
            },
        )

    for role in ROLE_AGENT_IDS:
        role_directory = exchange_dir / role
        requests = tuple(role_directory.glob("*.request.json"))
        responses = tuple(role_directory.glob("*.response.json"))
        if not requests or len(responses) != len(requests):
            raise RuntimeError(
                "sandbox role %s did not complete every captured exchange" % role
            )

    outcome = replay.outcome
    summary = {
        "schema": "role_benchmark.agent_sandbox_summary.v1",
        "experiment_id": SANDBOX_EXPERIMENT_ID,
        "classification": manifest["classification"],
        "provider": AGENT_SANDBOX_PROVIDER,
        "model": SANDBOX_MODEL,
        "roles": ROLE_AGENT_IDS,
        "log_path": str(log_path.relative_to(output_dir)),
        "log_sha256": _sha256_file(log_path),
        "termination_kind": outcome.termination.kind.value,
        "termination_code": outcome.termination.code,
        "attempts_used": outcome.attempts_used,
        "scientific_evaluation": (
            evaluation_result_to_payload(outcome.evaluation)
            if outcome.evaluation is not None
            else None
        ),
        "replay": {
            "event_count": replay.event_count,
            "action_count": replay.action_count,
            "parser_actions_checked": replay.parser_actions_checked,
            "prompt_requests_checked": replay.prompt_requests_checked,
        },
        "evaluator_result": str(evaluator_result_path.relative_to(output_dir)),
    }
    _write_json(output_dir / "summary.json", summary)
    print("Sandbox smoke completed: %s" % (output_dir / "summary.json"))
    return 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = _parser().parse_args(argv)
    output_dir = Path(args.output_dir)
    exchange_dir = (
        Path(args.exchange_dir) if args.exchange_dir else output_dir / "exchange"
    )
    return run(output_dir, exchange_dir)


if __name__ == "__main__":
    raise SystemExit(main())
