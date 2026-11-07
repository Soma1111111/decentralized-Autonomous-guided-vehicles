"""
Multi-floor demo: 3 floors x 9 nodes, ONE parking station, random jobs, 20 AGVs
================================================================================
* floor 1: 3x3 grid, floor 2: ring with hub, floor 3: comb with two loops (9 nodes each)
* floors are connected by 4 lifts whose "special" length (metres) is set in agv_layouts.LIFT_LENGTHS
* a job's pickup and delivery stations are drawn uniformly from all 26 non-parking nodes,
  so jobs can start/end on any floor and often cross floors
* AGV priorities are fixed and predefined: AGV-01 = V_1 (highest) ... AGV-20 = V_20

Run:
    python agv_multifloor_demo.py                       # seed 7, 100 jobs, 20 AGVs -> ./results
    python agv_multifloor_demo.py --seed 3 --jobs 100 --agvs 20 --gif --viewer
"""
import argparse
import csv
import json
import os
import random

from agv_core import AGV, Job, Log, Params, final_job_times, metrics, plan_segments, run_pipeline
from agv_layouts import build_three_floors


def make_jobs(L, prm, n_jobs, seed, horizon=600.0):
    rnd = random.Random(seed)
    stations = [n for n in L.G.nodes if n != L.pi and n not in L.lobbies]
    jobs = []
    for k in range(1, n_jobs + 1):
        p, q = rnd.sample(stations, 2)                                   # p_j != p'_j, any floor
        t = round(rnd.uniform(0, horizon), 1)                            # desired pickup time t_j
        slack = rnd.uniform(30, 200)
        t_prime = round(t + L.delta_nn(p, q) + prm.eta + prm.eta_p + slack, 1)   # desired delivery time t'_j
        jobs.append(Job(f"J{k:03d}", p, t, q, t_prime))
    return jobs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--jobs", type=int, default=100)
    ap.add_argument("--agvs", type=int, default=20)
    ap.add_argument("--lift-length", type=float, help="override the special inter-floor distance of ALL lifts (m)")
    ap.add_argument("--outdir", default=None, help="default: results_demo_<jobs>j_<agvs>a_s<seed>")
    ap.add_argument("--gif", action="store_true", help="also write a replay GIF (slower)")
    ap.add_argument("--viewer", action="store_true", help="open the interactive viewer")
    a = ap.parse_args()
    if a.outdir is None:  # folder name encodes the settings so runs cannot overwrite each other
        a.outdir = f"results_demo_{a.jobs}j_{a.agvs}a_s{a.seed}"

    import matplotlib
    if not a.viewer:
        matplotlib.use("Agg")
    import agv_viz as viz
    os.makedirs(a.outdir, exist_ok=True)
    out_p = lambda f: os.path.join(a.outdir, f)

    from agv_layouts import LIFT_LENGTHS
    lifts = {k: a.lift_length for k in LIFT_LENGTHS} if a.lift_length else None
    L = build_three_floors(lift_lengths=lifts)
    prm = Params(eta=16.0, eta_p=16.0, delta=10.0, lam=1.0)              # eta = eta' = 16 s, delta = 10 s
    jobs = make_jobs(L, prm, a.jobs, a.seed)
    agvs = [AGV(f"AGV-{k:02d}", k) for k in range(1, a.agvs + 1)]

    log = Log()
    res = run_pipeline(L, jobs, agvs, prm, log)
    plans, calls, est = res["plans"], res["calls"], res["estimate"]
    m = metrics(L, plans, agvs, jobs, est, calls, prm)
    fin = final_job_times(plans, agvs, prm)
    ok = not res["violations"]

    # ---------------- files -------------------------------------------------------------------
    with open(out_p("jobs.csv"), "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["j", "p_j", "floor_p", "t_j", "p'_j", "floor_p'", "t'_j"])
        for j in jobs:
            w.writerow([j.j, j.p, L.floor(j.p), j.t, j.p_prime, L.floor(j.p_prime), j.t_prime])
    with open(out_p("assignment.csv"), "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["j", "agv", "priority", "F_ji", "ct_ji(est)", "et_ji(est)", "dt_ji(est)",
                    "pickup_done(final)", "delivery_done(final)", "et(final)", "dt(final)", "delay_vs_estimate"])
        prio = {x.i: x.priority for x in agvs}
        for j in sorted(jobs, key=lambda x: (x.t, x.j)):
            e, f = est[j.j], fin[j.j]
            w.writerow([j.j, e["agv"], prio[e["agv"]], round(e["F"], 1), round(e["ct"], 1), round(e["et"], 1), round(e["dt"], 1),
                        round(f["pickup_done"], 1), round(f["delivery_done"], 1),
                        round(max(0, j.t - f["pickup_done"]), 1), round(max(0, f["delivery_done"] - j.t_prime), 1),
                        round(f["delivery_done"] - e["ct"], 1)])
    with open(out_p("plan_windows.csv"), "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["agv", "type", "index_m", "name", "floor", "start(lt or rt_{m-1})", "end(rt or lt_m)"])
        for x in sorted(agvs, key=lambda x: x.priority):
            pl = plans[x.i]
            for k, n in enumerate(pl.R):
                if k:
                    e0, e1 = pl.edge_window(k)
                    w.writerow([x.i, "edge", k, f"{pl.R[k - 1]}->{n}", "lift" if L.is_lift(pl.R[k - 1], n) else L.floor(n), round(e0, 2), round(e1, 2)])
                w.writerow([x.i, "node", k + 1, n, L.floor(n), round(pl.P[k][0], 2), round(pl.P[k][1], 2)])
    with open(out_p("activity.csv"), "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["agv", "activity", "start", "end", "info"])
        for x in sorted(agvs, key=lambda x: x.priority):
            for kind, t0, t1, info in plan_segments(L, plans[x.i]):
                w.writerow([x.i, kind, round(t0, 2), round(t1, 2), info])
    with open(out_p("routes.txt"), "w") as fh:
        for x in sorted(agvs, key=lambda x: x.priority):
            fh.write(f"{x.i} (V_{x.priority})  jobs={x.jobs}\n  R_i = {' -> '.join(x.R)}\n\n")
    with open(out_p("run_log.txt"), "w") as fh:
        for st, msg, kw in log.events:
            fh.write(f"[{st}] {msg}  " + "  ".join(f"{k}={v}" for k, v in kw.items()) + "\n")

    summary = dict(seed=a.seed, jobs=a.jobs, agvs=a.agvs, nodes=L.G.number_of_nodes(), edges=L.G.number_of_edges(),
                   parking=L.pi, lift_lengths_m=sorted({d["length"] for *_, d in L.G.edges(data=True) if d.get("kind") == "lift"}),
                   eta=prm.eta, eta_prime=prm.eta_p, delta=prm.delta, lam=prm.lam,
                   verification_ok=ok, violations=res["violations"][:5],
                   computation_time_s=dict(algorithm_1=round(res["t_alg1"], 3), algorithm_2_and_3=round(res["t_alg2"], 3)),
                   **{k: (round(v, 2) if isinstance(v, float) else v) for k, v in m.items() if k not in ("usage", "waiting_at_parking", "busy_time", "jobs_per_agv")},
                   per_agv={x.i: dict(priority=x.priority, jobs=len(x.jobs), usage_s=round(m["usage"][x.i], 1),
                                      busy_s=round(m["busy_time"][x.i], 1), waiting_at_parking_s=round(m["waiting_at_parking"][x.i], 1)) for x in agvs})
    with open(out_p("summary.json"), "w") as fh:
        json.dump(summary, fh, indent=2)

    cross = sum(L.floor(j.p) != L.floor(j.p_prime) for j in jobs)
    txt = [
        "MULTI-FLOOR DEMO - prioritized planning (Algorithms 1, 2, 3)",
        f"layout      : 3 floors x 9 nodes = {L.G.number_of_nodes()} nodes, {L.G.number_of_edges()} edges, 4 lifts of {summary['lift_lengths_m']} m, parking {L.pi}",
        f"fleet/jobs  : {a.agvs} AGVs (V_1..V_{a.agvs}), {a.jobs} random jobs (seed {a.seed}); {cross} of them cross floors",
        f"parameters  : eta = eta' = {prm.eta:g} s, delta = {prm.delta:g} s, lambda = {prm.lam:g}, speed = {L.speed:g} m/s",
        f"verified    : {'OK - no node/track conflict, no pause on an edge, every job served once' if ok else res['violations'][:5]}",
        f"compute time: Algorithm 1 {res['t_alg1']:.3f} s, Algorithms 2+3 {res['t_alg2']:.3f} s",
        f"makespan    : last delivery at {m['makespan_last_delivery']:.0f} s; fleet back at parking at {m['fleet_back_at_parking']:.0f} s",
        f"load imbalance (max - min usage time): {m['load_imbalance']:.0f} s",
        f"earliness/tardiness: final plan {m['earliness_final']:.0f} + {m['tardiness_final']:.0f} s   (Algorithm 1 estimate {m['earliness_estimate']:.0f} + {m['tardiness_estimate']:.0f} s)",
        f"Algorithm 3 : {m['alg3_calls']} calls, total shift {m['alg3_total_shift']:.0f} s, max single shift {m['alg3_max_shift']:.0f} s, fallbacks {m['alg3_fallbacks']}",
        f"lift crossings in all routes: {m['lift_crossings']}",
        "", "per AGV:   usage  busy  wait@pi  jobs",
    ] + [f"  {x.i} V{x.priority:<2} {m['usage'][x.i]:7.0f} {m['busy_time'][x.i]:6.0f} {m['waiting_at_parking'][x.i]:7.0f}  {len(x.jobs):3d}" for x in agvs]
    open(out_p("summary.txt"), "w").write("\n".join(txt) + "\n")
    print("\n".join(txt))

    # ---------------- figures -----------------------------------------------------------------
    viz.fig_floors(L, jobs, agvs, plans, out_p("fig1_floors_traffic.png"))
    viz.fig_gantt(L, agvs, plans, m, out_p("fig2_schedule_gantt.png"))
    viz.fig_load(L, agvs, m, out_p("fig3_load_per_agv.png"))
    viz.fig_alg3(calls, est, plans, jobs, agvs, out_p("fig4_algorithm3_and_estimate.png"))
    if a.gif:
        viz.save_gif(L, agvs, plans, out_p("replay.gif"), t_end=m["fleet_back_at_parking"] + 5)
    print(f"\nfiles written to {os.path.abspath(a.outdir)}")
    assert ok, "verification failed"

    if a.viewer:
        import matplotlib.pyplot as plt
        v = viz.Viewer(L, jobs, agvs, plans, log, calls, est, step_dt=5.0)
        plt.show()


if __name__ == "__main__":
    main()
