#!/bin/bash
# Offline dry-run by default only when requested; real execution requires root snapshot.
set -euo pipefail
cd "$(dirname "$0")/.."
export PYTHONPATH=src:.
python3 -B -u -m experiments.recover_codex_failed "$@"
