# AGV prioritized planning - corrected code + 3-floor demo

Files
- `agv_core.py`            Algorithms 1, 2, 3 + independent verifier + metrics (notation = the deck)
- `agv_layouts.py`         single 3x3 floor (original demo) and the 3-floor factory (edit `LIFT_LENGTHS` here)
- `agv_viz.py`             figures, GIF replay, interactive viewer (Play/Pause/Step/Reset/A1/A2/A3/All)
- `agv_prioritized_demo.py` the ORIGINAL scenario, corrected  (`--selftest` reproduces the deck's Algorithm-3 example)
- `agv_multifloor_demo.py`  3 floors x 9 nodes, 100 random jobs, 20 AGVs  ->  `results/`

Run: `pip install -r requirements.txt` then
`python agv_core.py`, `python agv_prioritized_demo.py`, `python agv_multifloor_demo.py --gif [--viewer] [--seed N]`

## What was wrong in the original `agv_prioritized_demo.py`
1. Algorithm 3 stopped after 10 iterations (`if iteration >= 10: break`) even when conflicts remained.
   Stress test (5 AGVs, 30 random jobs): the original returned plans with 79 conflicts; the fixed code returns 0.
2. The parking station was treated as an ordinary node (paper, assumption 3: exempt), so all AGVs that start at A at
   t = 0 conflicted artificially (AGV-2 started at 23 instead of 21, AGV-3 at 31 instead of 29).
3. A service time was added at EVERY node instead of only at the pickup (eta) / delivery (eta') node, so plans disagreed
   with the completion times of Algorithm 1 and pass-through windows were not lt = rt.
4. "Algorithm 3" was not the paper's: no f(lt, rt, W), no st* / mt* check, mt was computed (wrongly) but never used,
   and the whole plan was shifted without extending the parking-station window.
5. Smaller issues: distances not divided by speed (delta_nn' = length / speed), lambda / parking "A" / 3 AGVs hard-coded,
   eta and eta' not separate, viewer hard-wired to 3 AGVs.
Algorithm 1 itself (fitness, earliest-pickup-first, return to parking) was essentially right.

## Verification
- `agv_core.py` reproduces the deck's numerical example exactly (P_i = {[0,24],[28,32]}, st* = 18, every st/mt/st*/mt*).
- `verify()` re-checks every plan WITHOUT using f or Algorithm 3: node conflicts (parking exempt), track conflicts,
  no pause on an edge, start/end at pi, every job served once.  300 random scenarios: 0 violations.
- For 19 of 20 AGVs the wait at parking equals the minimal start delay that makes the whole route conflict-free,
  i.e. Algorithm 3 is optimal inside the paper's rule "wait only at the parking station".

## Modelling choices (the paper is silent or we are stricter)
- Inter-floor links ("lifts") are normal edges with a special length (default 40 m, speed 1 m/s -> 40 s).
- One parking station for the whole factory: node `1A`.
- A track holds one AGV at a time: both directions of a track are checked (stricter than the reverse-edge check of Table I).
- AGV priorities are fixed: AGV-01 = V_1 (highest) ... AGV-20.  The paper does not say how to choose them.
- Jobs: stations uniform over the 26 non-parking nodes, t_j ~ U[0,600] s, t'_j = t_j + travel + eta + eta' + U[30,200] s.
- usage time of an AGV = time it is back at the parking station; load imbalance = max - min usage time;
  makespan = last delivery completed.

## Hybrid architecture (central server + one server per floor)
- `agv_hybrid.py`  the hybrid planner. **Central server** runs Algorithm 1, cuts every route into floor legs at the
  lifts, books lift trips (no two AGVs on one lift track within delta) and merges the result. **Floor servers** keep
  W / W' of their own floor only and plan each leg with Algorithms 2 + 3. Legs are planned first-come-first-served.
- `agv_compare.py` runs the same jobs through A = centralized (paper), B = centralized + lift lobbies,
  C = hybrid  ->  `results_hybrid/` (comparison.csv, sweep_agvs.csv, summary.txt, 4 figures).
  Run: `python agv_compare.py [--seeds 1-10] [--jobs 100] [--agvs 20]`
  `python agv_compare.py --gantts-only` writes only one A/B/C Gantt figure per seed to `results_hybrid/gantts/`.
- `agv_hybrid_example.py` prints one AGV's plan leg by leg (deck slide 49: AGV-02, seed 7) and writes
  `results_hybrid/legs_seed7.csv` for all AGVs; `--toy` runs a 2-AGV example in config A and C.
- New assumption (hybrid only): each lift end has a **lobby** node `<landing>~` (2 m side bay) that, like pi, can
  hold several waiting AGVs. So an AGV can wait on the floor where the conflict is, not only at pi.
  `build_three_floors(lobbies=True)`; the lobbies become waiting points when added to `Layout.exempt`.
- Checks: every plan passes `verify()`; the hybrid planned in priority order gives exactly the plans of B
  (the split into servers loses nothing); the original demo still reproduces `results/summary.txt`.
