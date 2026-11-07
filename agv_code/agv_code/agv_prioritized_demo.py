"""
AGV Prioritized-Planning Demo (single floor)  -  corrected version
===================================================================
Same scenario as the original demo (3x3 grid, parking A, 3 AGVs, 3 jobs) but running on the corrected
implementation in agv_core.py, with the notation of the walkthrough deck.

Run:
    python agv_prioritized_demo.py              # logs + interactive window (Play/Pause/Step/Reset/A1/A2/A3/All)
    python agv_prioritized_demo.py --no-gui     # logs only
    python agv_prioritized_demo.py --png out.png
    python agv_prioritized_demo.py --selftest   # reproduces the deck's numerical example of Algorithm 3
"""
import argparse

from agv_core import AGV, Job, Log, Params, metrics, paper_example, run_pipeline
from agv_layouts import build_single_floor


def build_demo():
    L = build_single_floor()
    prm = Params(eta=1.0, eta_p=1.0, delta=2.0, lam=1.0)       # eta = eta' = 1, safety time delta = 2
    jobs = [Job("J1", p="C", t=0, p_prime="G", t_prime=30),
            Job("J2", p="G", t=1, p_prime="C", t_prime=35),
            Job("J3", p="I", t=2, p_prime="A", t_prime=40)]
    agvs = [AGV("AGV-1", 1), AGV("AGV-2", 2), AGV("AGV-3", 3)]  # V_1 > V_2 > V_3
    return L, prm, jobs, agvs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-gui", action="store_true")
    ap.add_argument("--png")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()

    if a.selftest:
        P, st_star, passes, trace = paper_example()
        print("Deck example (delta = 2): P_i =", P, "st* =", st_star, "passes =", passes)
        for row in trace:
            print("  pass %d  %-14s st=%-3g mt=%-3g st*=%-3g mt*=%g" % row)
        assert P == [[0, 24], [28, 32]]
        print("OK")
        return

    L, prm, jobs, agvs = build_demo()
    log = Log(echo=False)
    out = run_pipeline(L, jobs, agvs, prm, log)
    plans = out["plans"]

    print("=" * 78 + "\nALGORITHM 1 - prioritized job assignment (earliest pickup time first)\n" + "=" * 78)
    for st, msg, kw in log.events:
        if st == "A1":
            print(f"  {msg:<12} F_ji={kw['F']:<6} ct_ji={kw['ct']:<6} et_ji={kw['et']:<5} dt_ji={kw['dt']:<5} (runner-up {kw['runner_up']})")
    print("\nRoutes R_i:")
    for ag in agvs:
        print(f"  {ag.i} (V_{ag.priority}) jobs={ag.jobs}\n      R_i = {' -> '.join(ag.R)}")

    print("\n" + "=" * 78 + "\nALGORITHM 2 / 3 - prioritized conflict-free routing\n" + "=" * 78)
    for c in out["calls"]:
        print(f"  Algorithm 3 for {c['agv']}: conflict at {c['kind']} n{c['m']}={c['node']} (blocked by {c['blocker']}) "
              f"-> {c['passes']} pass(es), st* = {c['st_star']:.1f}")
        for row in c["trace"][:8]:
            print("        pass %d  %-16s st=%-5.1f mt=%-6s st*=%-5.1f mt*=%s" % (row[0], row[1], row[2],
                  "inf" if row[3] == float("inf") else f"{row[3]:.1f}", row[4], "inf" if row[5] == float("inf") else f"{row[5]:.1f}"))
    print("\nPlans P_i = {[lt_m, rt_m]}:")
    for ag in sorted(agvs, key=lambda x: x.priority):
        pl = plans[ag.i]
        print(f"  {ag.i}: " + "  ".join(f"{n}[{w[0]:g},{w[1]:g}]" for n, w in zip(pl.R, pl.P)))

    m = metrics(L, plans, agvs, jobs, out["estimate"], out["calls"], prm)
    print("\n" + "=" * 78 + "\nVERIFICATION (independent checker): " +
          ("OK - no node/edge conflict, no pause on an edge, all jobs served" if not out["violations"] else out["violations"]))
    print(f"last delivery at {m['makespan_last_delivery']:.1f}, fleet back at parking at {m['fleet_back_at_parking']:.1f}, "
          f"Algorithm-3 calls: {m['alg3_calls']}")
    assert not out["violations"]

    if a.png or not a.no_gui:
        import matplotlib
        if a.png and a.no_gui:
            matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from agv_viz import Viewer
        v = Viewer(L, jobs, agvs, plans, log, out["calls"], out["estimate"], step_dt=1.0)
        if a.png:
            v.t = 14.0
            v.draw()
            v.fig.savefig(a.png, dpi=110)
            print("saved", a.png)
        if not a.no_gui:
            plt.show()


if __name__ == "__main__":
    main()
