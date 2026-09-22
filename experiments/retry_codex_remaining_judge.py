"""One final Judge-only retry, preserving the user-adjudicated active failure."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from experiments import run_case_matrix as matrix
from experiments.recover_codex_failed import original_args

RUN = Path("runs/EXP-CODEX-GPT55-BOTH-R1-20260917")
TARGET = "young_double_slit__canonical__counterfactual__identification__fixed-experimental-design__r01"

def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()

def now():
    return datetime.now(timezone.utc).isoformat()

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    cli = parser.parse_args()
    root = RUN.resolve()
    args = original_args(root)
    plan = matrix.build_plan(case_pack="both", repeats=1, schedule_seed=20260825)
    spec = next(s for s in plan if s.episode_id == TARGET)
    result_path = root / "results" / (TARGET + ".result.json")
    previous_path = root / "evaluations" / (TARGET + ".evaluation.json")
    active = json.loads(result_path.read_text())
    previous = json.loads(previous_path.read_text())
    assert active["status"] == "evaluated" and previous["status"] == "infrastructure_failed"
    adjudications = json.loads((root / "adjudications.json").read_text())
    assert TARGET not in {a["episode_id"] for a in adjudications["adjudications"]}
    calls_before = {p.parent.name for p in (root / "codex_calls").glob("*/request.json")}
    assert all((root / "codex_calls" / c / "response.json").exists() or
               (root / "codex_calls" / c / "failure.json").exists() for c in calls_before)
    config = json.loads((root / "config.json").read_text())
    expected = matrix._config_payload(args, plan)
    assert {k:v for k,v in config.items() if k != "created_at"} == {k:v for k,v in expected.items() if k != "created_at"}
    print("Validated one Judge-only retry; no Player backend is loaded; adjudicated case excluded.", flush=True)
    if cli.dry_run:
        return 0
    history = root / "recovery_history"
    backup = history / "judge_only_resume_before.evaluation.json"
    with backup.open("xb") as f:
        f.write(previous_path.read_bytes())
    protected = {str(p.relative_to(root)):sha(p) for p in (root / "results").glob("*.result.json")}
    repo = Path(__file__).resolve().parents[1]
    record = {"schema":"codex_final_judge_only_resume.v1", "started_at":now(),
        "judge_retry_ids":[TARGET], "evaluator_timeout_s":900, "player_calls_allowed":False,
        "excluded_adjudicated_ids":[a["episode_id"] for a in adjudications["adjudications"]],
        "command":["bash","scripts/retry_codex_remaining_judge.sh"],
        "config_sha256":sha(root / "config.json"), "adjudications_sha256":sha(root / "adjudications.json"),
        "before_evaluation_path":str(backup.relative_to(root)), "before_evaluation_sha256":sha(backup),
        "active_results_sha256":protected, "calls_before":sorted(calls_before),
        "source_sha256":{p:sha(repo / p) for p in ("experiments/run_case_matrix.py",
            "experiments/codex_structured_backend.py", "experiments/retry_codex_remaining_judge.py",
            "scripts/retry_codex_remaining_judge.sh")}, "status":"running"}
    path = history / "judge_only_resume_provenance.json"
    with path.open("x") as f:
        json.dump(record,f,indent=2)
    evaluator = matrix.load_role_backend(args,"evaluator")
    evaluation = matrix._run_evaluator(args,evaluator_backend=evaluator,output_dir=root,spec=spec,episode_result=active)
    matrix._persist_evaluator_result(root,spec,evaluation)
    assert all(sha(root / p)==h for p,h in protected.items())
    record.update(completed_at=now(),status=evaluation["status"],exit_code=int(evaluation["status"]!="evaluated"),
        new_call_ids=sorted({p.parent.name for p in (root / "codex_calls").glob("*/request.json")}-calls_before),
        active_results_preserved=True)
    temporary=path.with_suffix(".tmp");temporary.write_text(json.dumps(record,indent=2)+"\n");temporary.replace(path)
    matrix.write_summaries(root)
    print("Judge result: " + evaluation["status"],flush=True)
    return record["exit_code"]

if __name__ == "__main__":
    raise SystemExit(main())
