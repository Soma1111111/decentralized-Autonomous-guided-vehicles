# Multi-floor multi-AGV scheduling

This repository contains a Python implementation of prioritized multi-AGV job
assignment and collision-free routing, based on Guo et al., ICARCV 2024, plus
multi-floor layouts and a hybrid planner. The hybrid uses a central server for
job assignment and lift reservations and one floor server per floor for local
route-leg planning. Lift lobbies provide waiting points at each landing. The
independent `verify()` checker checks generated plans.

## Repository map

- `agv_code/agv_code/` — Python source, pinned dependencies, tests, and generated
  experiment outputs.
- `agv_code/agv_code/agv_core.py` — Algorithms 1–3, plan verification, and
  metrics.
- `agv_code/agv_code/agv_hybrid.py` — central lift booking and floor-server
  routing.
- `agv_code/agv_code/agv_layouts.py` — single-floor and three-floor layouts.
- `agv_code/agv_code/agv_compare.py` — A/B/B2/C/WA comparisons and fleet sweeps.
- `agv_code/agv_code/agv_wait_adjust.py` — priority-ordered safe-interval wait adjustment
  with waits allowed at route nodes.
- `agv_code/agv_code/agv_statistical_experiments.py` runs paired light-load and 30-seed
  comparisons; `generate_latex_tables.py` regenerates bootstrap/Wilcoxon summaries and
  booktabs tables from its raw CSV.
- `agv_code/agv_code/sweep_job_scale.py` and
  `agv_code/agv_code/sensitivity.py` — job-scale and parameter-sensitivity
  experiments.
- `agv_code/agv_code/lobby_capacity_sweep.py` — finite lobby-capacity comparison
  on three- and five-floor layouts.
- `agv_code/agv_code/results/`, `agv_code/agv_code/results_hybrid/`,
  `agv_code/agv_code/results_same_direction/`,
  `agv_code/agv_code/results_scale/`,
  `agv_code/agv_code/results_sensitivity/`,
  `agv_code/agv_code/results_lobby_capacity/` — generated outputs for the demo,
  architecture comparison, track-rule comparison, job sweep, sensitivity sweep,
  and lobby-capacity sweep (`results_lobby_capacity/`).
- Root `*.tex`, PDF, presentation, and related-work files — paper and
  presentation materials.
- `REPRODUCIBILITY.md` — environment, exact commands, and full artifact runner.
- `run_all.sh` — one-command regeneration and verification script.

## Reproduce the results

Run the following commands from `agv_code/agv_code/` using Python 3.11 or 3.12.
The dependency versions are pinned in `requirements.txt`.

```bash
pip install -r requirements.txt
python agv_multifloor_demo.py --seed 7
python agv_compare.py --seeds 1-10 --jobs 100 --agvs 20
python agv_compare.py --seeds 1-10 --jobs 100 --agvs 20 --gantts-only --outdir results_hybrid
python agv_compare.py --seeds 1-10 --jobs 100 --agvs 20 --track-rule same-direction --outdir results_same_direction
python agv_hybrid_example.py --seed 7 --agv AGV-02
python sweep_job_scale.py
python sensitivity.py
python lobby_capacity_sweep.py
python agv_baselines.py
python agv_multifloor_demo.py --seed 7 --gif
python agv_stress_test.py
python -m unittest test_verify test_b2_c_equivalence test_sensitivity
```

To regenerate all saved experiment artifacts and run verification/tests from the
repository root, use `bash run_all.sh`. See `REPRODUCIBILITY.md` for the complete
command list and tested machine details.

## Archive note

`agv_code.zip` is retained as a historical snapshot. It is a stale subset and
omits `agv_hybrid.py`, `agv_compare.py`, `agv_hybrid_example.py`,
`agv_stress_test.py`, and `results_hybrid/`; use `agv_code/agv_code/` as the
current source of truth.
