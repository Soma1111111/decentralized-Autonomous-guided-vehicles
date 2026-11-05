"""
Stress test of the corrected implementation: many random scenarios, every plan re-checked by verify().

    python agv_stress_test.py                 # 300 scenarios: 150 on the single 3x3 floor, 150 on the 3-floor factory
    python agv_stress_test.py --n 600 --seed 1

Each scenario draws a random fleet size and a random number of jobs (stations, t_j and t'_j as in
agv_multifloor_demo.make_jobs), runs Algorithm 1 -> 2 -> 3 and counts the violations found by verify().
"""
import argparse
import random

from agv_core import AGV, Log, Params, run_pipeline
from agv_layouts import build_single_floor, build_three_floors
from agv_multifloor_demo import make_jobs

LAYOUTS = {
    # name: (builder, Params, (min AGVs, max AGVs), (min jobs, max jobs), t_j horizon)
    "single 3x3 floor": (build_single_floor, Params(eta=1.0, eta_p=1.0, delta=2.0, lam=1.0), (2, 6), (5, 30), 60.0),
    "3-floor factory": (build_three_floors, Params(eta=16.0, eta_p=16.0, delta=10.0, lam=1.0), (3, 20), (10, 100), 600.0),
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=300, help="total number of scenarios (split evenly over the layouts)")
    ap.add_argument("--seed", type=int, default=0)
    a = ap.parse_args()

    rnd = random.Random(a.seed)
    total_bad = 0
    for name, (build, prm, agv_rng, job_rng, horizon) in LAYOUTS.items():
        L = build()
        n = a.n // len(LAYOUTS)
        bad_runs = fallbacks = calls = 0
        for _ in range(n):
            n_agvs, n_jobs = rnd.randint(*agv_rng), rnd.randint(*job_rng)
            jobs = make_jobs(L, prm, n_jobs, rnd.randrange(10**9), horizon)
            agvs = [AGV(f"AGV-{k:02d}", k) for k in range(1, n_agvs + 1)]
            out = run_pipeline(L, jobs, agvs, prm, Log(echo=False))
            v = out["violations"]
            if v:
                bad_runs += 1
                total_bad += len(v)
                print(f"  {name}: {n_agvs} AGVs, {n_jobs} jobs -> {len(v)} violations, e.g. {v[0]}")
            calls += len(out["calls"])
            fallbacks += sum(c["fallback"] for c in out["calls"])
        print(f"{name:<18}: {n} scenarios, {bad_runs} with violations, "
              f"{calls} Algorithm-3 calls, {fallbacks} fallbacks")
    print(f"TOTAL violations: {total_bad}")


if __name__ == "__main__":
    main()
