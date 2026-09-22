#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/.."
export PYTHONPATH=src:.
python3 -B -u -m experiments.resume_codex_long_output "$@"
