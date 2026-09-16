#!/usr/bin/env python3
"""Run the Phase 1 schedule with temporary gpt-5.6-sol role agents."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Optional, Sequence

from experiments.run_case_matrix import _parser as matrix_parser
from experiments.run_case_matrix import run_matrix
from role_benchmark.agent_queue import SequentialAgentBackend, pending_agent_requests


MODEL = "gpt-5.6-sol"
RUN_ID = "EXP-METHOD-PILOT-GPT56-AGENT-001"
AGENTS = {
    "player": "player_sandbox_agent",
    "oracle": "oracle_sandbox_agent",
    "evaluator": "evaluator_sandbox_agent",
}
CURATED_FAMILIES = (
    "pendulum",
    "young_double_slit",
    "radioactive_decay",
    "ohm_circuit",
    "michaelis_menten",
    "poiseuille_flow",
)
TEMPORAL_FAMILIES = (
    "kz_incompressible_energy_temperature_regimes",
    "viscous_inertial_rheology",
    "self_similar_spreading_radius_ratio",
)


def _arguments(
    subrun: str,
    output_dir: Path,
    *,
    schedule_start_index: int = 1,
    schedule_stop_index: Optional[int] = None,
    schedule_shard_count: int = 1,
    schedule_shard_index: int = 0,
) -> argparse.Namespace:
    values = [
        "--experiment-id", RUN_ID,
        "--output-dir", str(output_dir / subrun),
        "--case-pack", subrun,
        "--repeats", "2",
        "--schedule-seed", "20260825",
        "--oracle-mode", "llm_presentation",
        "--player-provider", "openai",
        "--player-model", MODEL,
        "--player-snapshot-id", "unknown",
        "--player-reasoning-effort", "high",
        "--player-max-output-tokens", "8192",
        "--oracle-provider", "openai",
        "--oracle-model", MODEL,
        "--oracle-snapshot-id", "unknown",
        "--oracle-reasoning-effort", "high",
        "--oracle-max-output-tokens", "256",
        "--evaluator-provider", "openai",
        "--evaluator-model", MODEL,
        "--evaluator-snapshot-id", "unknown",
        "--evaluator-reasoning-effort", "high",
        "--evaluator-max-output-tokens", "2048",
        "--max-repair-attempts", "1",
        "--max-actions", "16",
        "--workers", "1",
    ]
    families = CURATED_FAMILIES if subrun == "curated" else TEMPORAL_FAMILIES
    for family in families:
        values.extend(("--family", family))
    if subrun == "curated":
        values.extend(("--variant", "easy", "--variant", "hard"))
    args = matrix_parser().parse_args(values)
    args.schedule_start_index = schedule_start_index
    args.schedule_stop_index = schedule_stop_index
    args.schedule_shard_count = schedule_shard_count
    args.schedule_shard_index = schedule_shard_index
    return args


def _has_episode_retry(output_dir: Path, subrun: str) -> bool:
    for path in (output_dir / subrun / "results").glob("*.result.json"):
        value = json.loads(path.read_text(encoding="utf-8"))
        if value.get("status") == "infrastructure_failed":
            return True
    return False


def _has_evaluator_retry(output_dir: Path, subrun: str) -> bool:
    for path in (output_dir / subrun / "evaluations").glob("*.evaluation.json"):
        value = json.loads(path.read_text(encoding="utf-8"))
        if value.get("status") != "evaluated":
            return True
    return False


def _loader(exchange_dir: Path, role: str, *, resume_existing: bool):
    return lambda: SequentialAgentBackend(
        str(exchange_dir),
        role=role,
        agent_id=AGENTS[role],
        model=MODEL,
        resume_existing=resume_existing,
    )


def run(
    subrun: str,
    output_dir: Path,
    *,
    force_new_player: bool = False,
    schedule_start_index: int = 1,
    schedule_stop_index: Optional[int] = None,
    schedule_shard_count: int = 1,
    schedule_shard_index: int = 0,
) -> int:
    output_dir = output_dir.resolve()
    exchange_dir = output_dir / "exchange"
    args = _arguments(
        subrun,
        output_dir,
        schedule_start_index=schedule_start_index,
        schedule_stop_index=schedule_stop_index,
        schedule_shard_count=schedule_shard_count,
        schedule_shard_index=schedule_shard_index,
    )
    episode_retry = _has_episode_retry(output_dir, subrun) and not force_new_player
    evaluator_retry = _has_evaluator_retry(output_dir, subrun)
    try:
        run_matrix(
            args,
            player_backend_loader=_loader(
                exchange_dir, "player", resume_existing=episode_retry
            ),
            oracle_backend_loader=_loader(
                exchange_dir, "oracle", resume_existing=episode_retry
            ),
            evaluator_backend_loader=_loader(
                exchange_dir, "evaluator", resume_existing=evaluator_retry
            ),
        )
    except RuntimeError as exc:
        pending = pending_agent_requests(str(exchange_dir))
        if not pending:
            raise
        print(str(exc))
        print("Waiting for agent response:")
        for path in pending:
            print(path)
        return 2
    return 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--subrun", choices=("curated", "temporal"), default="curated")
    parser.add_argument(
        "--output-dir",
        default="runs/EXP-METHOD-PILOT-GPT56-AGENT-001",
    )
    parser.add_argument("--force-new-player", action="store_true")
    parser.add_argument("--schedule-start-index", type=int, default=1)
    parser.add_argument("--schedule-stop-index", type=int)
    parser.add_argument("--schedule-shard-count", type=int, default=1)
    parser.add_argument("--schedule-shard-index", type=int, default=0)
    args = parser.parse_args(argv)
    return run(
        args.subrun,
        Path(args.output_dir),
        force_new_player=args.force_new_player,
        schedule_start_index=args.schedule_start_index,
        schedule_stop_index=args.schedule_stop_index,
        schedule_shard_count=args.schedule_shard_count,
        schedule_shard_index=args.schedule_shard_index,
    )


if __name__ == "__main__":
    raise SystemExit(main())
