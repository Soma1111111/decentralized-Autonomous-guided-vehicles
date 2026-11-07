"""Compare centralized A and hybrid C as job volume grows.

Run from this directory:
    python sweep_job_scale.py

Writes results_scale/sweep_jobs.csv and results_scale/summary.txt for 20 AGVs,
job counts 50/100/200/400, and seeds 1--5.
"""
from __future__ import annotations

import argparse
import csv
import os
import statistics

from agv_compare import run_one
from agv_core import Params


JOB_COUNTS = (50, 100, 200, 400)
SEEDS = (1, 2, 3, 4, 5)
N_AGVS = 20
CONFIGS = ("A", "C")
FIELDS = (
    "config", "seed", "jobs", "agvs", "makespan", "tardiness", "imbalance",
    "alg3_calls", "cpu_ms", "windows_per_server", "ok",
)


def run_sweep(outdir="results_scale"):
    os.makedirs(outdir, exist_ok=True)
    csv_path = os.path.join(outdir, "sweep_jobs.csv")
    prm = Params(eta=16.0, eta_p=16.0, delta=10.0, lam=1.0)
    rows = []

    for n_jobs in JOB_COUNTS:
        for seed in SEEDS:
            for config in CONFIGS:
                result, _ = run_one(config, seed, n_jobs, N_AGVS, prm)
                row = {
                    "config": config,
                    "seed": seed,
                    "jobs": n_jobs,
                    "agvs": N_AGVS,
                    "makespan": round(result["makespan"], 3),
                    "tardiness": round(result["tardiness"], 3),
                    "imbalance": round(result["imbalance"], 3),
                    "alg3_calls": result["alg3_calls"],
                    "cpu_ms": round(result["cpu_ms"], 3),
                    "windows_per_server": result["max_windows_one_server"],
                    "ok": result["ok"],
                }
                rows.append(row)
                print(f"{config} jobs={n_jobs} seed={seed}: ok={row['ok']} "
                      f"makespan={row['makespan']:.1f} tardiness={row['tardiness']:.1f}")

    with open(csv_path, "w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)

    summary_path = os.path.join(outdir, "summary.txt")
    summary = make_summary(rows, csv_path)
    with open(summary_path, "w", encoding="utf-8") as stream:
        stream.write(summary)
    print(f"Wrote {csv_path}")
    print(f"Wrote {summary_path}")
    print(summary)
    return csv_path, summary_path, rows


def make_summary(rows, csv_path="results_scale/sweep_jobs.csv"):
    def mean(config, jobs, field):
        selected = [float(r[field]) for r in rows
                    if r["config"] == config and int(r["jobs"]) == jobs]
        return statistics.mean(selected)

    lines = [
        "JOB-SCALE SWEEP: centralized A vs hybrid C",
        f"20 AGVs; {len(SEEDS)} seeds (1-5); jobs {', '.join(map(str, JOB_COUNTS))};",
        "eta=eta'=16 s, delta=10 s, lambda=1, lift length=40 m.",
        f"All plans verified: {all(r['ok'] for r in rows)}; CSV: {csv_path}",
        "",
        "Means over seeds:",
        f"{'jobs':>6} {'config':>7} {'makespan':>13} {'tardiness':>15} "
        f"{'imbalance':>13} {'Alg3 calls':>12} {'CPU ms':>10} {'windows/server':>16}",
    ]
    for jobs in JOB_COUNTS:
        for config in CONFIGS:
            lines.append(
                f"{jobs:6d} {config:>7} {mean(config, jobs, 'makespan'):13,.1f} "
                f"{mean(config, jobs, 'tardiness'):15,.1f} "
                f"{mean(config, jobs, 'imbalance'):13,.1f} "
                f"{mean(config, jobs, 'alg3_calls'):12,.1f} "
                f"{mean(config, jobs, 'cpu_ms'):10,.1f} "
                f"{mean(config, jobs, 'windows_per_server'):16,.1f}"
            )

    metrics = ("makespan", "tardiness", "imbalance")
    improvements = {
        metric: {
            jobs: 100.0 * (mean("A", jobs, metric) - mean("C", jobs, metric))
            / mean("A", jobs, metric)
            for jobs in JOB_COUNTS
        }
        for metric in metrics
    }
    lines += ["", "Hybrid reduction relative to A (%; positive favors C):"]
    lines.append(
        f"{'jobs':>6} " + " ".join(f"{metric:>12}" for metric in metrics)
    )
    for jobs in JOB_COUNTS:
        lines.append(
            f"{jobs:6d} " + " ".join(
                f"{improvements[metric][jobs]:11.1f}%" for metric in metrics
            )
        )

    first, last = JOB_COUNTS[0], JOB_COUNTS[-1]
    changes = {metric: improvements[metric][last] - improvements[metric][first]
               for metric in metrics}
    if all(value > 0 for value in changes.values()):
        interpretation = "The hybrid advantage grows across all three outcome metrics"
    elif all(value < 0 for value in changes.values()):
        interpretation = "The hybrid advantage shrinks across all three outcome metrics"
    else:
        interpretation = "The hybrid advantage changes with job volume and differs by metric"
    lines += ["", "Interpretation:",
              f"{interpretation} from {first} to {last} jobs. The C-vs-A reduction "
              f"changes by {changes['makespan']:+.1f} percentage points for makespan, "
              f"{changes['tardiness']:+.1f} points for tardiness, and "
              f"{changes['imbalance']:+.1f} points for imbalance. These are five-seed "
              "means at a fixed fleet size of 20 AGVs; the job-to-AGV ratio rises "
              "from 2.5 to 20, so the trend reflects increasing workload and route "
              "contention in this modeled layout, not a general scaling guarantee."]
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--outdir", default="results_scale")
    args = parser.parse_args()
    run_sweep(args.outdir)


if __name__ == "__main__":
    main()
