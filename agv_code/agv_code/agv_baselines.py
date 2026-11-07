"""Alternative job-assignment baselines using the common routing algorithms.

Run from this directory:
    python agv_baselines.py

The script compares agv_compare.py configurations A/B/C with FCFS and random
job assignment on identical seeded job sets. The two new assignment policies
are followed by agv_core.algorithm_2 (which invokes Algorithm 3).
"""
from __future__ import annotations

import random
import statistics
import time

from agv_core import (
    AGV,
    Job,
    Log,
    Params,
    algorithm_2,
    fitness,
    metrics,
    verify,
)


def _append_path(agv: AGV, path, service_time: float) -> int:
    """Append a contiguous shortest path and dwell at its terminal node."""
    if not agv.R:
        agv.R, agv.dwell = [path[0]], [0.0]
    if path[0] != agv.R[-1]:
        raise ValueError("route path is not contiguous with the AGV route")
    for node in path[1:]:
        agv.R.append(node)
        agv.dwell.append(0.0)
    agv.dwell[-1] += service_time
    return len(agv.R) - 1


def _assign_jobs(L, jobs, agvs, prm: Params, policy: str, seed: int, log: Log):
    """Construct ordered routes with FCFS-earliest-completion or random assignment.

    FCFS processes jobs by (desired pickup time, ID) and assigns each to the
    AGV with the earliest predicted delivery completion time. Random assignment
    uses a seeded uniform draw from the fleet for each job, while preserving
    the same job processing order. Neither policy minimizes the fitness score.
    """
    if policy not in {"fcfs", "random"}:
        raise ValueError("policy must be 'fcfs' or 'random'")

    rng = random.Random(seed)
    for agv in agvs:
        agv.vt, agv.s = 0.0, L.pi
        agv.R, agv.dwell = [L.pi], [0.0]
        agv.events, agv.jobs = [], []

    estimate = {}
    for job in sorted(jobs, key=lambda j: (j.t, j.j)):
        if policy == "fcfs":
            # Completion is used only as an availability measure, not the
            # earliness/tardiness-weighted fitness used by Algorithm 1.
            candidates = []
            for agv in agvs:
                completion = (
                    agv.vt
                    + L.delta_nn(agv.s, job.p)
                    + prm.eta
                    + L.delta_nn(job.p, job.p_prime)
                    + prm.eta_p
                )
                candidates.append((completion, agv.priority, agv))
            agv = min(candidates, key=lambda item: (item[0], item[1]))[2]
        else:
            agv = rng.choice(agvs)

        # Use the shared estimator for reported estimates only. Its fitness
        # does not affect the FCFS or random assignment decision.
        estimate_fields = fitness(L, agv, job, prm)
        pickup_idx = _append_path(agv, L.r_nn[(agv.s, job.p)], prm.eta)
        agv.events.append((pickup_idx, "pickup", job.j))
        delivery_idx = _append_path(agv, L.r_nn[(job.p, job.p_prime)], prm.eta_p)
        agv.events.append((delivery_idx, "delivery", job.j))
        agv.vt = estimate_fields["ct"]
        agv.s = job.p_prime
        agv.jobs.append(job.j)
        estimate[job.j] = dict(agv=agv.i, **estimate_fields)
        log.add("ASSIGN", f"{job.j} -> {agv.i}", policy=policy,
                completion=round(estimate_fields["ct"], 1))

    for agv in agvs:
        path = L.r_nn[(agv.s, L.pi)]
        _append_path(agv, path, 0.0)
    return estimate


def run_baseline(L, jobs, agvs, prm: Params, log: Log,
                 policy: str, seed: int = 0, keep_trace: bool = True):
    """Run an assignment baseline followed by the shared Algorithms 2 and 3.

    Returns the same core planning fields as ``run_pipeline``: ``plans``,
    ``calls``, ``estimate``, and ``violations``. Timing fields are included
    for compatibility with callers that inspect pipeline results.
    """
    start = time.perf_counter()
    estimate = _assign_jobs(L, jobs, agvs, prm, policy, seed, log)
    assigned = time.perf_counter()
    plans, calls = algorithm_2(L, agvs, prm, log, keep_trace=keep_trace)
    routed = time.perf_counter()
    violations = verify(L, plans, agvs, jobs, prm)
    return {
        "estimate": estimate,
        "plans": plans,
        "calls": calls,
        "violations": violations,
        "t_alg1": assigned - start,
        "t_alg2": routed - assigned,
    }


def run_fcfs(L, jobs, agvs, prm: Params, log: Log, seed: int = 0,
             keep_trace: bool = True):
    """Earliest-pickup-first jobs assigned to the earliest-finishing AGV."""
    return run_baseline(L, jobs, agvs, prm, log, "fcfs", seed, keep_trace)


def run_random(L, jobs, agvs, prm: Params, log: Log, seed: int = 0,
               keep_trace: bool = True):
    """Uniform random job-to-AGV assignment, reproducible for a fixed seed."""
    return run_baseline(L, jobs, agvs, prm, log, "random", seed, keep_trace)


def main():
    # Imports are local to keep the baseline functions usable without loading
    # the plotting stack used by agv_compare.py.
    from agv_compare import layout, run_one
    from agv_multifloor_demo import make_jobs

    prm = Params(eta=16.0, eta_p=16.0, delta=10.0, lam=1.0)
    seeds = (1, 2, 3)
    n_jobs, n_agvs = 100, 20
    names = {"A": "Centralized", "B": "Centralized+lobbies",
             "C": "Hybrid", "FCFS": "FCFS assignment", "Random": "Random assignment"}
    values = {name: [] for name in names}

    for seed in seeds:
        # Use run_one for A/B/C so these exactly match agv_compare's layouts,
        # generated jobs, and hybrid FCFS leg scheduling.
        for cfg in ("A", "B", "C"):
            _, detail = run_one(cfg, seed, n_jobs, n_agvs, prm)
            m = detail["m"]
            values[cfg].append((m["makespan_last_delivery"],
                                m["tardiness_final"], m["load_imbalance"]))

        L = layout("A")
        jobs = make_jobs(L, prm, n_jobs, seed)
        for label, runner in (("FCFS", run_fcfs), ("Random", run_random)):
            agvs = [AGV(f"AGV-{k:02d}", k) for k in range(1, n_agvs + 1)]
            result = runner(L, jobs, agvs, prm, Log(), seed=seed, keep_trace=False)
            if result["violations"]:
                raise RuntimeError(f"{label}, seed {seed} failed verification: "
                                   f"{result['violations'][:3]}")
            m = metrics(L, result["plans"], agvs, jobs, result["estimate"],
                        result["calls"], prm)
            values[label].append((m["makespan_last_delivery"],
                                  m["tardiness_final"], m["load_imbalance"]))

        print(f"seed {seed}: all five configurations verified")

    print(f"\nMean over seeds {seeds[0]}-{seeds[-1]} "
          f"({n_jobs} jobs, {n_agvs} AGVs)")
    print(f"{'Config':<22}{'Makespan (s)':>16}{'Tardiness (s)':>17}{'Imbalance (s)':>17}")
    for key, label in names.items():
        means = [statistics.mean(row[idx] for row in values[key]) for idx in range(3)]
        print(f"{label:<22}{means[0]:16.1f}{means[1]:17.1f}{means[2]:17.1f}")


if __name__ == "__main__":
    main()
