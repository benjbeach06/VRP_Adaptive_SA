#!/bin/bash
# Both sweeps at 600 s per run, 3 SA seeds, 1 PyVRP seed. Sequential on purpose:
# every number here is a wall-clock budget, so concurrent runs would corrupt it.
# MDVRP runs first because it is shorter -- a broken pipeline shows up in 4 h, not 5 h 20 m.
set -uo pipefail
cd /c/Users/Bben6/PycharmProjects/PythonProject
D=experiment_logs/benchmarks/2026-09-05_pyvrp_600s
PYW="C:/Users/Bben6/PycharmProjects/PythonProject/.venv1/Scripts/python.exe"
LOG="$D/run.log"

echo "=== solver commit $(git rev-parse --short HEAD), tree $(git status --porcelain | wc -l) dirty files ===" >> "$LOG"
echo "=== MDVRP sweep started $(date) ===" >> "$LOG"
OUT="$D/results_mdvrp.jsonl" PY="$PYW" bash pyvrp_benchmarking/benchmark/drive_mdvrp.sh 600 >> "$LOG" 2>&1
echo "=== MDVRP done $(date) ===" >> "$LOG"

echo "=== CVRP sweep started $(date) ===" >> "$LOG"
"$PYW" pyvrp_benchmarking/benchmark/bench.py --seconds 600 --seeds 3 \
  --python "$PYW" --out "$D/results_cvrp.jsonl" >> "$LOG" 2>&1
echo "=== CVRP done $(date) ===" >> "$LOG"
echo "=== ALL SWEEPS COMPLETE $(date) ===" >> "$LOG"
