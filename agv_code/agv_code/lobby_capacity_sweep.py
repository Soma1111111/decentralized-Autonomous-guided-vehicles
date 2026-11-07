"""Capacity sweep for centralized+lobby (B) and hybrid (C) planners.

Run from this directory: python lobby_capacity_sweep.py
Writes results_lobby_capacity/capacity_sweep.csv and summary.txt.
"""
from __future__ import annotations

import argparse
import csv
import os
import statistics

from agv_core import AGV, Log, Params, metrics, run_pipeline
from agv_hybrid import run_hybrid
from agv_layouts import build_five_floors, build_three_floors
from agv_multifloor_demo import make_jobs


CAPACITIES = ((1, "1"), (2, "2"), (4, "4"), (None, "unlimited"))
BUILDERS = (("3-floor", build_three_floors), ("5-floor", build_five_floors))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--outdir", default="results_lobby_capacity")
    args = parser.parse_args()
    os.makedirs(args.outdir, exist_ok=True)
    prm = Params(eta=16.0, eta_p=16.0, delta=10.0, lam=1.0)
    rows = []

    for layout_name, builder in BUILDERS:
        base = builder(lobbies=True, lobby_capacity=None)
        jobs_by_seed = {seed: make_jobs(base, prm, 100, seed) for seed in range(1, 11)}
        for capacity, capacity_label in CAPACITIES:
            for seed in range(1, 11):
                for config in ("B", "C"):
                    L = builder(lobbies=True, lobby_capacity=capacity)
                    L.exempt = {L.pi} | L.lobbies
                    jobs = jobs_by_seed[seed]
                    agvs = [AGV(f"AGV-{k:02d}", k) for k in range(1, 21)]
                    try:
                        if config == "B":
                            result = run_pipeline(L, jobs, agvs, prm, Log())
                        else:
                            result = run_hybrid(L, jobs, agvs, prm, Log(), order="fcfs")
                        violations = result["violations"]
                        if violations:
                            raise RuntimeError(violations[0])
                        values = metrics(L, result["plans"], agvs, jobs,
                                         result["estimate"], result["calls"], prm)
                        row = dict(layout=layout_name, config=config, seed=seed, jobs=100,
                                   agvs=20, lobby_capacity=capacity_label, ok=True,
                                   makespan=values["makespan_last_delivery"],
                                   tardiness=values["tardiness_final"],
                                   imbalance=values["load_imbalance"], reason="")
                    except (RuntimeError, AssertionError) as exc:
                        row = dict(layout=layout_name, config=config, seed=seed, jobs=100,
                                   agvs=20, lobby_capacity=capacity_label, ok=False,
                                   makespan="", tardiness="", imbalance="", reason=str(exc))
                    rows.append(row)
                    print(f"{layout_name} K={capacity_label} {config} seed={seed}: "
                          f"ok={row['ok']}" +
                          (f" makespan={row['makespan']:.1f} tardiness={row['tardiness']:.1f}"
                           if row["ok"] else f" reason={row['reason']}"))

    csv_path = os.path.join(args.outdir, "capacity_sweep.csv")
    with open(csv_path, "w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    lines = ["LOBBY CAPACITY SWEEP (10 seeds, 100 jobs, 20 AGVs)",
             "Means include only verified plans. Failed means the planner did not produce a verified plan;",
             "it does not prove that the underlying scheduling instance is physically infeasible.",
             "Finite-capacity C uses FCFS tour admission with one AGV active at a time;",
             "other AGVs wait at pi, eliminating lobby wait-for cycles.", ""]
    for layout_name, _ in BUILDERS:
        lines.append(layout_name)
        lines.append(f"{'K':<12}{'Config':<8}{'Verified':>10}{'Failed':>12}"
                     f"{'Makespan':>14}{'Tardiness':>16}{'Imbalance':>14}")
        for _, capacity_label in CAPACITIES:
            for config in ("B", "C"):
                cell = [r for r in rows if r["layout"] == layout_name
                        and r["lobby_capacity"] == capacity_label and r["config"] == config]
                feasible = [r for r in cell if r["ok"]]
                def mean(key):
                    return statistics.mean(float(r[key]) for r in feasible) if feasible else None
                vals = [mean(k) for k in ("makespan", "tardiness", "imbalance")]
                fmt = [f"{v:,.1f}" if v is not None else "n/a" for v in vals]
                lines.append(f"{capacity_label:<12}{config:<8}{len(feasible):>10}"
                             f"{len(cell) - len(feasible):>12}{fmt[0]:>14}{fmt[1]:>16}{fmt[2]:>14}")
        lines.append("")

    lines.append("C vs B (percentage reduction; only seeds feasible in both configurations):")
    for layout_name, _ in BUILDERS:
        for _, capacity_label in CAPACITIES:
            paired = {(r["seed"], r["config"]): r for r in rows
                      if r["layout"] == layout_name and r["lobby_capacity"] == capacity_label and r["ok"]}
            pairs = [(paired[(s, "B")], paired[(s, "C")]) for s in range(1, 11)
                     if (s, "B") in paired and (s, "C") in paired]
            if not pairs:
                lines.append(f"  {layout_name} K={capacity_label}: no paired feasible seeds")
                continue
            changes = []
            for key in ("makespan", "tardiness", "imbalance"):
                b = statistics.mean(float(x[key]) for x, _ in pairs)
                c = statistics.mean(float(y[key]) for _, y in pairs)
                changes.append(f"{key} {100 * (b - c) / b:+.1f}%" if b else f"{key} n/a")
            lines.append(f"  {layout_name} K={capacity_label} ({len(pairs)} paired seeds): "
                         + ", ".join(changes))

    summary = "\n".join(lines) + "\n"
    with open(os.path.join(args.outdir, "summary.txt"), "w", encoding="utf-8") as stream:
        stream.write(summary)
    print("\n" + summary)
    print(f"Wrote {csv_path}")


if __name__ == "__main__":
    main()
