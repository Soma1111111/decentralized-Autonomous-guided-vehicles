# Reproducibility

Run the commands below from `agv_code/agv_code/` with Python 3.11 or 3.12.
Install the dependencies:

```bash
pip install -r requirements.txt
```

The requirements are `networkx`, `matplotlib`, `numpy`, and `pillow`.

## Reproduce `results/`

```bash
python agv_multifloor_demo.py --seed 7
```

This writes the multi-floor demo outputs to `results/` (100 jobs and 20 AGVs
by default).

## Reproduce `results_hybrid/`

```bash
python agv_compare.py --seeds 1-10 --jobs 100 --agvs 20
```

This writes the centralized-versus-hybrid comparison outputs to
`results_hybrid/`.

## Verify plans

Run the randomized scenarios and independent `verify()` checker with:

```bash
python agv_stress_test.py
```

The documented run covers 300 scenarios and reports `TOTAL violations: 0`
when every plan passes verification.

## Commit scope and archive note

This commit fixes the original demo bugs listed in
`agv_code/agv_code/README.md` under `What was wrong in the original`:

- Algorithm 3 stopped after 10 iterations even if conflicts remained.
- The parking station was incorrectly subject to node-conflict checks.
- Service time was added at every node instead of only at pickup and delivery.
- Algorithm 3 did not implement the paper's `f(lt, rt, W)` and `st*`/`mt*`
  rules or extend the parking-station window.
- Travel-time scaling, separate pickup/delivery service parameters, and other
  configuration values were hard-coded or incorrect.

The root `agv_code.zip` is a stale subset of the working tree: it omits the
hybrid files (`agv_hybrid.py`, `agv_compare.py`, `agv_hybrid_example.py`, and
`agv_stress_test.py`) and `results_hybrid/`. Use `agv_code/agv_code/` as the
source of truth.
