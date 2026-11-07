#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$REPO_ROOT/agv_code/agv_code"

PYTHON=${PYTHON:-python}
if ! command -v "$PYTHON" >/dev/null 2>&1; then
    PYTHON=python3
fi
if ! command -v "$PYTHON" >/dev/null 2>&1; then
    echo "Python 3.11 or 3.12 is required (set PYTHON to its executable)." >&2
    exit 1
fi
PYTHON_VERSION=$("$PYTHON" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
case "$PYTHON_VERSION" in
    3.11|3.12) ;;
    *) echo "Python 3.11 or 3.12 is required; found $PYTHON_VERSION." >&2; exit 1 ;;
esac

"$PYTHON" agv_multifloor_demo.py --seed 7 --gif
"$PYTHON" agv_compare.py --seeds 1-10 --jobs 100 --agvs 20
"$PYTHON" agv_compare.py --seeds 1-10 --jobs 100 --agvs 20 \
    --gantts-only --outdir results_hybrid
"$PYTHON" agv_compare.py --seeds 1-10 --jobs 100 --agvs 20 \
    --track-rule same-direction --outdir results_same_direction
"$PYTHON" agv_hybrid_example.py --seed 7 --agv AGV-02
"$PYTHON" sweep_job_scale.py
"$PYTHON" sensitivity.py
"$PYTHON" lobby_capacity_sweep.py
"$PYTHON" agv_baselines.py
"$PYTHON" agv_stress_test.py
"$PYTHON" -m unittest test_verify test_b2_c_equivalence test_sensitivity test_lobby_capacity
