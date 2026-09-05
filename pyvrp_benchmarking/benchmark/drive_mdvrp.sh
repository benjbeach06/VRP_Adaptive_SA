#!/bin/bash
# Sequential MDVRP sweep: both solvers, same budget, one at a time.
#
# Sequential on purpose. Two solvers competing for cores would make a
# wall-clock-budgeted comparison meaningless, which is the whole measurement.
#
#   ./drive_mdvrp.sh 60                      # seconds per run
#   PY=/path/to/python ./drive_mdvrp.sh 60   # pick the interpreter
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SECS=${1:-60}
SEEDS=${SEEDS:-3}

# One interpreter that runs both sides is fine. Fall back to the venvs, then to
# whatever python is on PATH.
if [ -z "${PY:-}" ]; then
  for c in "$HERE/venv-sa/bin/python" "$HERE/venv-sa/Scripts/python.exe" python3 python; do
    if command -v "$c" >/dev/null 2>&1 || [ -x "$c" ]; then PY="$c"; break; fi
  done
fi
PY_SA=${PY_SA:-$PY}
PY_PV=${PY_PV:-$PY}

# Default lands beside the harness, which dirties it. Point OUT at an experiment
# folder instead:  OUT=experiment_logs/benchmarks/<slug>/results_mdvrp.jsonl ./drive_mdvrp.sh 60
OUT="${OUT:-$HERE/results_mdvrp.jsonl}"
: > "$OUT"
echo "solver interpreter : $PY_SA" >&2
echo "pyvrp  interpreter : $PY_PV" >&2

for f in "$HERE"/instances/MDVRP/*.json; do
  name=$(basename "$f" .json)
  for seed in $(seq 0 $((SEEDS - 1))); do
    "$PY_SA" "$HERE/run_sa_mdvrp.py" "$f" --seconds "$SECS" --seed "$seed" \
      2>/dev/null | grep '^{' | tail -1 >> "$OUT" || echo "  !! sa $name seed $seed produced no result" >&2
    echo "done sa $name seed $seed" >&2
  done
  "$PY_PV" "$HERE/run_pyvrp_mdvrp.py" "$f" --seconds "$SECS" --seed 0 \
    2>/dev/null | grep '^{' | tail -1 >> "$OUT" || echo "  !! pyvrp $name produced no result" >&2
  echo "done pyvrp $name" >&2
done
echo ALLDONE >&2
