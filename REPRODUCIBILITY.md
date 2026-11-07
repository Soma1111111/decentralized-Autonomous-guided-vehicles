# Reproducibility

## Supported environment

Use Python 3.11 or 3.12 and run commands from `agv_code/agv_code/`. The full
`run_all.sh` run recorded here used Python 3.12.3 with:

- NetworkX 3.7
- NumPy 2.5.4
- Matplotlib 3.11.2
- Pillow 13.0.0

The versions above are pinned in `agv_code/agv_code/requirements.txt`.

Recorded machine: Windows 11 host (build 26300, AMD64) running WSL2, Linux
kernel `6.18.54.1-microsoft-standard-WSL2`, 8 logical CPUs, Intel CPU signature
`Family 6 Model 142 Stepping 12`. Runtime measurements can vary with the machine
and system load; seeded schedule inputs are fixed by the commands below.

## Install and regenerate experiment outputs

From `agv_code/agv_code/`, install the pinned packages:

```bash
pip install -r requirements.txt
```

Regenerate the single-seed demo in `results/`:

```bash
python agv_multifloor_demo.py --seed 7
```

Regenerate the strict-track comparison and fleet sweep. Output folders encode
their settings, so runs with different settings never overwrite each other
(the main experiment lands in `results_hybrid_100j_20a_s1-10_strict/`):

```bash
python agv_compare.py --seeds 1-10 --jobs 100 --agvs 20
```

Regenerate the per-seed Gantt figures (the canonical 100-job per-seed Gantts
live in `results_hybrid/gantts/` from an earlier verified run):

```bash
python agv_compare.py --seeds 1-10 --jobs 100 --agvs 20 --gantts-only
```

Every result folder is documented in `results_manifest.json`: the command,
git commit hash, seeds, jobs, AGVs, track rule, date, Python and package
versions, and CPU model. `test_results_manifest.py` fails if a folder's
contents disagree with its manifest entry or with its own folder name.

Regenerate the paper-style same-direction-following comparison in
`results_same_direction/`:

```bash
python agv_compare.py --seeds 1-10 --jobs 100 --agvs 20 --track-rule same-direction --outdir results_same_direction
```

Regenerate the hybrid leg example, job-scale sweep, and sensitivity sweep:

```bash
python agv_hybrid_example.py --seed 7 --agv AGV-02
python sweep_job_scale.py
python sensitivity.py
python lobby_capacity_sweep.py
```

The lobby-capacity sweep runs B and C for K = 1, 2, 4, and unlimited on both
three- and five-floor layouts, with seeds 1–10, 100 jobs, and 20 AGVs. It writes
`results_lobby_capacity/capacity_sweep.csv` and `summary.txt`.

Print the three-seed assignment-baseline comparison:

```bash
python agv_baselines.py
```

The demo's optional replay GIF is generated with:

```bash
python agv_multifloor_demo.py --seed 7 --gif
```

## Verification

The randomized stress test runs 300 scenarios and checks each plan with
`agv_core.verify()`:

```bash
python agv_stress_test.py
```

Run the focused verifier and experiment tests with:

```bash
python -m unittest test_verify test_b2_c_equivalence test_sensitivity test_lobby_capacity
```

## One-command reproduction

After installing the pinned packages above, run this from the repository root
to regenerate the outputs (including the optional GIF) and run baselines, the
300-scenario stress test, and unit tests:

```bash
bash run_all.sh
```

`agv_code.zip` remains as a historical snapshot, but it is incomplete: it omits
the hybrid planner and related outputs. Use the working tree under
`agv_code/agv_code/` as the source of truth.

## Statistical comparison and light-load experiments

Run from `agv_code/agv_code/` after installing the pinned requirements. This
executes 30 paired seeds for A/B/B2/C at 100 jobs, at 10/20/30 jobs, and at
10 jobs at 1800- and 3600-second horizons, and 100 jobs with an 1800-second
horizon. It writes all
per-seed metrics and verification flags to `results_statistics/experiment_raw.csv`,
then regenerates bootstrap confidence intervals, paired Wilcoxon tests, and
booktabs LaTeX tables.

```bash
python agv_statistical_experiments.py --outdir results_statistics_20a_s1-30_7regimes
```

To regenerate just the analysis and LaTeX tables from saved raw data:

```bash
python generate_latex_tables.py --raw results_statistics_20a_s1-30_7regimes/experiment_raw.csv --outdir results_statistics_20a_s1-30_7regimes
```

## CPU-timing repeats

Planning CPU is wall-clock dependent, so the busiest-server reduction was
checked with five repeated runs of the main experiment:

```bash
python agv_compare.py --sweep '' --outdir results_cpu_repeat_r1   # ... r2..r5
```

Per-repeat C-vs-A busiest-server reductions: −93%, −91%, −92%, −91%, −93%
(medians 139.4 ms for A, 10.5 ms for C). Machine details for these runs are
recorded in `results_manifest.json`.

## Original demo corrections

The corrected implementation addresses the original demo bugs listed in
`agv_code/agv_code/README.md` under “What was wrong in the original”: Algorithm 3
could stop before conflicts were resolved; the parking node was incorrectly
included in node-conflict checks; service time was applied at pass-through
nodes; the sliding-window `f(lt, rt, W)` and `st*`/`mt*` behavior and parking
window extension were missing; and speed scaling, service-time parameters, and
other configuration values were hard-coded or incorrect.
