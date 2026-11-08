#!/usr/bin/env bash
# run_all.sh - regenerate every result, the paper numbers, all figures, and both
# PDFs; then run the number checker and all unit tests. Exits non-zero on any
# failure. Run from the repository root:
#
#     bash run_all.sh
#
# Requires Python 3.11 or 3.12 (set PYTHON to its executable if needed) and,
# for PDF compilation, tectonic (found on PATH or at /tmp/opencode/tectonic).
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

# tectonic is used to compile both papers; allow a local copy for this environment
if ! command -v tectonic >/dev/null 2>&1 && [ -x /tmp/opencode/tectonic ]; then
    PATH="/tmp/opencode:$PATH"
fi

echo "[run_all] 1/7 regenerating experiment results (settings-encoding output folders)"
"$PYTHON" agv_multifloor_demo.py --seed 7 --gif
"$PYTHON" agv_compare.py --seeds 1-10 --jobs 100 --agvs 20
"$PYTHON" agv_compare.py --seeds 1-10 --jobs 100 --agvs 20 --gantts-only
"$PYTHON" agv_compare.py --seeds 1-10 --jobs 100 --agvs 20 \
    --track-rule same-direction --outdir results_same_direction
"$PYTHON" agv_compare.py --seeds 1-10 --jobs 100 --agvs 20 \
    --outdir results_wait_adjustment
"$PYTHON" agv_hybrid_example.py --seed 7 --agv AGV-02
"$PYTHON" sweep_job_scale.py
"$PYTHON" sensitivity.py
"$PYTHON" lobby_capacity_sweep.py
"$PYTHON" agv_baselines.py
"$PYTHON" agv_statistical_experiments.py --outdir results_statistics
"$PYTHON" agv_stress_test.py
"$PYTHON" agv_fairness_experiment.py --outdir results_fairness
for r in 1 2 3 4 5; do
    "$PYTHON" agv_compare.py --seeds 1-10 --jobs 100 --agvs 20 --sweep '' \
        --outdir results_cpu_repeat_r$r
done

echo "[run_all] 2/7 refreshing results_manifest.json"
"$PYTHON" make_manifest.py

echo "[run_all] 3/7 generating figures"
"$PYTHON" make_paper_gantts.py
"$PYTHON" make_architecture_figure.py

echo "[run_all] 4/7 generating paper numbers and LaTeX table bodies"
"$PYTHON" make_paper_numbers.py

echo "[run_all] 5/7 checking that no paper number is hard-coded"
"$PYTHON" check_paper_numbers.py

echo "[run_all] 6/7 running unit tests"
"$PYTHON" -m pytest test_results_manifest.py -q
"$PYTHON" -m unittest test_verify test_b2_c_equivalence test_sensitivity test_lobby_capacity test_wait_adjustment

echo "[run_all] 7/7 compiling both papers and writing final PDFs"
(cd ../../paper/short && tectonic main.tex >/dev/null 2>&1 && tectonic main.tex)
cp ../../paper/short/main.pdf ../../paper/paper_short.pdf
(cd ../../paper/full && tectonic main.tex >/dev/null 2>&1 && tectonic main.tex)
cp ../../paper/full/main.pdf ../../paper/paper_full.pdf
rm -f ../../paper/short/main.pdf ../../paper/short/main.log \
      ../../paper/full/main.pdf ../../paper/full/main.log
echo "[run_all] done: paper/paper_short.pdf and paper/paper_full.pdf written"
