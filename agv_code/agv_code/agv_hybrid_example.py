"""
agv_hybrid_example.py - worked examples of the hybrid planner, leg by leg
==========================================================================
    python agv_hybrid_example.py                      # deck slide 49: AGV-02, seed 7, 100 jobs, 20 AGVs (config C)
    python agv_hybrid_example.py --agv AGV-20 --seed 3
    python agv_hybrid_example.py --toy                # 2 AGVs, 2 jobs on floor 3: hybrid (C) vs centralized (A)

For every leg (= part of a route on one floor) the table shows
    arrives          time the AGV is at the leg's entry (pi or the arrival lift lobby)
    waits at entry   Algorithm-3 slide of the floor server (conflict on THIS floor), spent in that lobby / at pi
    reaches lobby    time the AGV reaches the departure lift lobby (or pi at the end)
    waits for lift   lift booked by another AGV (central server, book_lift), spent in the departure lobby
    leaves floor     departure time of the lift
The table of all AGVs is also written to results_hybrid/legs_seed<seed>.csv.
"""
import argparse
import csv
import os

from agv_compare import run_one
from agv_core import AGV, Job, Log, Params, plan_segments, run_pipeline
from agv_hybrid import run_hybrid, split_legs
from agv_layouts import build_three_floors

PRM = Params(eta=16.0, eta_p=16.0, delta=10.0, lam=1.0)


def leg_rows(L, a, pl):
    rows = []
    for k, (s, e) in enumerate(split_legs(L, a.R)):
        last = e == len(a.R) - 1
        rows.append(dict(agv=a.i, leg=k + 1, floor=L.floor(a.R[s]), path=" -> ".join(a.R[s:e + 1]),
                         arrives=pl.P[s][0], waits_at_entry=pl.P[s][1] - pl.P[s][0] - a.dwell[s],
                         reaches_lobby=pl.P[e][0], waits_for_lift=0.0 if last else pl.P[e][1] - pl.P[e][0] - a.dwell[e],
                         leaves_floor=pl.P[e][1]))
    return rows


def print_rows(rows):
    print(f"{'leg':>3} {'floor':>5}  {'arrives':>8} {'wait@entry':>10} {'reaches':>8} {'wait@lift':>9} {'leaves':>8}  path")
    for r in rows:
        print(f"{r['leg']:>3} {r['floor']:>5}  {r['arrives']:>8.1f} {r['waits_at_entry']:>10.1f} {r['reaches_lobby']:>8.1f} "
              f"{r['waits_for_lift']:>9.1f} {r['leaves_floor']:>8.1f}  {r['path']}")


def seed_example(seed, agv_id, outdir="results_hybrid"):
    _, d = run_one("C", seed, 100, 20, PRM)
    L, res = d["L"], d["res"]
    assert not res["violations"]
    all_rows = [r for a in d["agvs"] for r in leg_rows(L, a, res["plans"][a.i])]
    a = next(x for x in d["agvs"] if x.i == agv_id)
    print(f"Hybrid (C), seed {seed}: {a.i} (V_{a.priority}), jobs {a.jobs}")
    print_rows([r for r in all_rows if r["agv"] == agv_id])
    os.makedirs(outdir, exist_ok=True)
    path = os.path.join(outdir, f"legs_seed{seed}.csv")
    with open(path, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(all_rows[0]))
        w.writeheader()
        w.writerows({k: round(v, 1) if isinstance(v, float) else v for k, v in r.items()} for r in all_rows)
    print(f"all AGVs -> {path}")


def toy_example():
    spec = [("J1", "3D", 0, "3B", 400), ("J2", "3C", 5, "3A", 400)]
    for cfg in ("A", "C"):
        L = build_three_floors(lobbies=True)
        if cfg == "C":
            L.exempt = {L.pi} | L.lobbies
        jobs, agvs = [Job(*j) for j in spec], [AGV(f"AGV-{k}", k) for k in (1, 2)]
        res = (run_hybrid if cfg == "C" else run_pipeline)(L, jobs, agvs, PRM, Log())
        assert not res["violations"]
        print(f"\n=== config {cfg} ({'hybrid' if cfg == 'C' else 'centralized, wait only at pi'})")
        for a in agvs:
            pl = res["plans"][a.i]
            print(f"{a.i} jobs {a.jobs}, home at {pl.end_time:.1f}")
            for s in plan_segments(L, pl):
                if s[0] == "wait":
                    print(f"   waits {s[2] - s[1]:6.1f} s  ({s[1]:.1f} -> {s[2]:.1f})  {s[3]}")
            if cfg == "C":
                print_rows(leg_rows(L, a, pl))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--agv", default="AGV-02")
    ap.add_argument("--toy", action="store_true")
    a = ap.parse_args()
    toy_example() if a.toy else seed_example(a.seed, a.agv)
