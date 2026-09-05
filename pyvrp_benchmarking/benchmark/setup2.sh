#!/usr/bin/env bash
# Set up the CVRPLIB benchmark: two virtualenvs and the instance set.
#
# Two envs because the solver and PyVRP have different Python floors -- the
# solver needs 3.12+ (3.14 unpatched), PyVRP ships wheels for released CPython.
# They never need to talk to each other; each writes JSON lines to the same file.
#
#   ./benchmark/setup.sh                     # autodetect interpreters
#   SA_PYTHON=python3.14 PYVRP_PYTHON=python3.12 ./benchmark/setup.sh
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(dirname "$HERE")"

pick() {   # first interpreter on the list that exists
  for c in "$@"; do command -v "$c" >/dev/null 2>&1 && { echo "$c"; return; }; done
}

SA_PYTHON="${SA_PYTHON:-$(pick python3.14 python3.13 python3.12 python3)}"
PYVRP_PYTHON="${PYVRP_PYTHON:-$(pick python3.12 python3.11 python3.13 python3)}"

[ -n "$SA_PYTHON" ]    || { echo "no Python found for the solver" >&2; exit 1; }

# The solver uses PEP 695 generics (class Move[Ops: tuple], ...), which are syntax, not
# annotations -- no __future__ import can back-port them. 3.12 is a hard floor.
if ! "$SA_PYTHON" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 12) else 1)'; then
  echo "solver needs Python >= 3.12 (PEP 695 generics); found $($SA_PYTHON -V)." >&2
  echo "Install 3.12+ and re-run with SA_PYTHON=python3.12 ./benchmark/setup.sh" >&2
  exit 1
fi
[ -n "$PYVRP_PYTHON" ] || { echo "no Python found for PyVRP" >&2; exit 1; }

echo "solver interpreter : $SA_PYTHON ($($SA_PYTHON -V))"
echo "pyvrp  interpreter : $PYVRP_PYTHON ($($PYVRP_PYTHON -V))"
echo

# ---------------------------------------------------------------- solver env
echo "[1/3] solver venv"
"$SA_PYTHON" -m venv "$HERE/venv-sa"
"$HERE/venv-sa/bin/pip" -q install --upgrade pip
"$HERE/venv-sa/bin/pip" -q install numpy

if ! (cd "$ROOT" && "$HERE/venv-sa/bin/python" -c "import SimAnn_VRP_Solver" 2>/dev/null); then
  echo "      import failed on this interpreter; applying the __future__ annotations patch"
  "$HERE/venv-sa/bin/python" "$HERE/compat_patch.py" --apply
  (cd "$ROOT" && "$HERE/venv-sa/bin/python" -c "import SimAnn_VRP_Solver") \
    || { echo "      still failing -- try SA_PYTHON=python3.14" >&2; exit 1; }
fi
echo "      solver imports OK"

# ----------------------------------------------------------------- pyvrp env
echo "[2/3] pyvrp venv"
"$PYVRP_PYTHON" -m venv "$HERE/venv-pyvrp"
"$HERE/venv-pyvrp/bin/pip" -q install --upgrade pip
"$HERE/venv-pyvrp/bin/pip" -q install pyvrp
"$HERE/venv-pyvrp/bin/python" -c "import pyvrp, importlib.metadata as m; print('      pyvrp', m.version('pyvrp'))"

# ----------------------------------------------------------------- instances
echo "[3/3] instances"
if [ -d "$HERE/instances/CVRP" ]; then
  echo "      already present ($(ls "$HERE"/instances/CVRP/*.vrp 2>/dev/null | wc -l) files)"
else
  # Uchoa et al. X-series with best-known solutions, mirrored by the PyVRP project.
  git clone --depth 1 -q https://github.com/PyVRP/Instances.git "$HERE/instances"
  echo "      $(ls "$HERE"/instances/CVRP/*.vrp | wc -l) CVRP instances"
fi

cat <<EOF

Ready.

  python benchmark/bench.py --seconds 60 --seeds 3     # about 30 min
  python benchmark/report.py

Quick check first:

  benchmark/venv-sa/bin/python    benchmark/run_sa.py    benchmark/instances/CVRP/X-n101-k25.vrp --seconds 10
  benchmark/venv-pyvrp/bin/python benchmark/run_pyvrp.py benchmark/instances/CVRP/X-n101-k25.vrp --seconds 10
EOF
