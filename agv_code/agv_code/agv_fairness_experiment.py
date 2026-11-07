"""Compare AGV waiting fairness and two priority-aging variants of hybrid C."""
from __future__ import annotations

import argparse
import csv
import math
import os
import statistics

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from scipy.stats import pearsonr, spearmanr

from agv_compare import run_one
from agv_core import AGV, Log, Params, metrics, plan_segments
from agv_hybrid import run_hybrid
from agv_layouts import build_three_floors
from agv_multifloor_demo import make_jobs


SEEDS = range(1, 11)
BASE_CONFIGS = ("A", "B", "B2", "C")
VARIANT_NAMES = ("C", "C-rotate", "C-wait-boost")
CAP_SECONDS = 600.0
FAIRNESS_KEYS = ("pearson", "spearman", "gini", "max_min_ratio")
OUTCOME_KEYS = ("makespan", "tardiness", "imbalance", "wait_total")


def _wait_by_agv(L, plans):
    return {aid: sum(seg[2] - seg[1] for seg in plan_segments(L, plan) if seg[0] == "wait")
            for aid, plan in plans.items()}


def _gini(values):
    values = sorted(max(0.0, float(x)) for x in values)
    total = sum(values)
    if not values or total == 0:
        return 0.0
    n = len(values)
    return (2 * sum((i + 1) * x for i, x in enumerate(values)) / (n * total)
            - (n + 1) / n)


def _fairness(ranks, waits):
    x = [ranks[aid] for aid in sorted(ranks, key=lambda aid: ranks[aid])]
    y = [waits[aid] for aid in sorted(ranks, key=lambda aid: ranks[aid])]
    p = float(pearsonr(x, y).statistic) if len(set(y)) > 1 else float("nan")
    s = float(spearmanr(x, y).statistic) if len(set(y)) > 1 else float("nan")
    minimum, maximum = min(y), max(y)
    ratio = maximum / minimum if minimum > 0 else float("inf")
    return dict(pearson=p, spearman=s, gini=_gini(y), max_min_ratio=ratio,
                wait_total=sum(y), wait_max=maximum, wait_min=minimum)


def _run_hybrid_variant(seed, n_jobs, prm, ranks, rotate=False):
    L = build_three_floors(lobbies=True)
    L.exempt = {L.pi} | L.lobbies
    jobs = make_jobs(L, prm, n_jobs, seed)
    # ranks is the current AGV-id -> priority mapping; preserve stable input order.
    agvs = [AGV(aid, ranks[aid]) for aid in sorted(ranks, key=lambda aid: int(aid[-2:]))]
    res = run_hybrid(L, jobs, agvs, prm, Log(), order="fcfs",
                     rotate_priority_rounds=rotate)
    if res["violations"]:
        raise RuntimeError(f"hybrid fairness variant failed verification: {res['violations'][0]}")
    outcome = metrics(L, res["plans"], agvs, jobs, res["estimate"], res["calls"], prm)
    waits = _wait_by_agv(L, res["plans"])
    row = dict(seed=seed, jobs=n_jobs, agvs=len(agvs),
               makespan=outcome["makespan_last_delivery"],
               tardiness=outcome["tardiness_final"],
               imbalance=outcome["load_imbalance"],
               wait_total=sum(waits.values()), wait_max=max(waits.values()),
               cpu_ms=1000 * sum(v["cpu"] for v in res["servers"].values()),
               ok=True, planning_rounds=1)
    return L, agvs, res, waits, row


def _wait_boost(seed, n_jobs, prm, base_ranks, cap=CAP_SECONDS, max_rounds=5):
    current = dict(base_ranks)
    seen = set()
    result = None
    rounds = 0
    for round_index in range(1, max_rounds + 1):
        result = _run_hybrid_variant(seed, n_jobs, prm, current)
        _, _, _, waits, row = result
        # Each cap interval above the threshold moves an AGV forward one rank.
        promoted = {}
        for aid, base_rank in base_ranks.items():
            wait = waits[aid]
            steps = max(0, math.ceil(wait / cap) - 1) if wait > cap else 0
            promoted[aid] = max(1, base_rank - steps)
        order = sorted(promoted, key=lambda aid: (promoted[aid], -waits[aid], base_ranks[aid]))
        updated = {aid: rank for rank, aid in enumerate(order, 1)}
        signature = tuple(updated[aid] for aid in sorted(updated))
        row["planning_rounds"] = round_index
        if updated == current or signature in seen:
            break
        seen.add(signature)
        current = updated
    row["wait_threshold_s"] = cap
    row["threshold_exceeded_agvs"] = sum(w > cap for w in result[3].values())
    row["threshold_is_hard_cap"] = False
    return (*result[:4], row)


def _write_csv(path, rows):
    if not rows:
        return
    fields = list(dict.fromkeys(key for row in rows for key in row))
    with open(path, "w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def _summarize_fairness(seed_rows):
    summary = []
    for config in sorted({r["config"] for r in seed_rows}):
        group = [r for r in seed_rows if r["config"] == config]
        for metric in FAIRNESS_KEYS:
            vals = [float(r[metric]) for r in group if math.isfinite(float(r[metric]))]
            inf_count = sum(not math.isfinite(float(r[metric])) for r in group)
            summary.append(dict(config=config, metric=metric, n=len(group),
                                finite_n=len(vals),
                                mean=statistics.mean(vals) if vals else "",
                                sd=statistics.stdev(vals) if len(vals) > 1 else 0.0,
                                infinite_count=inf_count))
    return summary


def _summarize_variants(rows):
    result = []
    for config in VARIANT_NAMES:
        group = [r for r in rows if r["config"] == config]
        for metric in (*OUTCOME_KEYS, "wait_max", "cpu_ms"):
            vals = [float(r[metric]) for r in group]
            mean = statistics.mean(vals)
            baseline = [float(r[metric]) for r in rows if r["config"] == "C"]
            base_mean = statistics.mean(baseline)
            result.append(dict(config=config, metric=metric, n=len(vals),
                               mean=mean, sd=statistics.stdev(vals),
                               change_vs_C=mean - base_mean,
                               percent_vs_C=(100 * (mean - base_mean) / base_mean
                                             if base_mean else 0.0)))
    return result


def _plot(wait_rows, path):
    colors = {"A": "#2a78d6", "B": "#eb6834", "B2": "#8b65ad", "C": "#1baf7a"}
    fig, ax = plt.subplots(figsize=(9, 5.2))
    ranks = sorted({int(r["priority_rank"]) for r in wait_rows})
    for config in BASE_CONFIGS:
        ys = []
        for rank in ranks:
            vals = [float(r["wait_s"]) for r in wait_rows
                    if r["config"] == config and int(r["priority_rank"]) == rank]
            ys.append(statistics.mean(vals))
        ax.plot(ranks, ys, marker="o", markersize=3.5, linewidth=2,
                color=colors[config], label=config)
    ax.set_xlabel("AGV priority rank (1 = highest)")
    ax.set_ylabel("Mean waiting at parking and lobbies (s)")
    ax.set_title("Waiting time by AGV priority, mean over seeds 1–10")
    ax.set_xticks(ranks)
    ax.grid(axis="y", alpha=0.25)
    ax.legend(frameon=False, ncol=4)
    fig.tight_layout()
    fig.savefig(path, dpi=160)
    plt.close(fig)


def run(outdir=None, n_jobs=100, cap=CAP_SECONDS):
    if outdir is None:  # folder name encodes the settings so runs cannot overwrite each other
        outdir = f"results_fairness_{n_jobs}j_cap{cap:g}"
    os.makedirs(outdir, exist_ok=True)
    prm = Params(eta=16.0, eta_p=16.0, delta=10.0, lam=1.0)
    wait_rows, seed_fairness, variant_rows = [], [], []
    for seed in SEEDS:
        original_ranks = {f"AGV-{rank:02d}": rank for rank in range(1, 21)}
        base_c_details = None
        for config in BASE_CONFIGS:
            _, details = run_one(config, seed, n_jobs, 20, prm)
            if details["res"]["violations"]:
                raise RuntimeError(f"{config} seed {seed} failed verify: {details['res']['violations'][0]}")
            waits = _wait_by_agv(details["L"], details["res"]["plans"])
            fair = _fairness(original_ranks, waits)
            seed_fairness.append(dict(config=config, seed=seed, **fair))
            if config == "C":
                base_c_details = details
            for aid, wait in waits.items():
                wait_rows.append(dict(config=config, seed=seed, agv=aid,
                                      priority_rank=original_ranks[aid], wait_s=wait, ok=True))
        # Rotation is applied to each block of fleet-size jobs during assignment.
        L, agvs, res, waits, row = _run_hybrid_variant(seed, n_jobs, prm,
                                                       original_ranks, rotate=True)
        row.update(config="C-rotate")
        variant_rows.append(row)
        seed_fairness.append(dict(config="C-rotate", seed=seed,
                                  **_fairness(original_ranks, waits)))
        for aid, wait in waits.items():
            wait_rows.append(dict(config="C-rotate", seed=seed, agv=aid,
                                  priority_rank=original_ranks[aid], wait_s=wait, ok=True))
        # Threshold aging replans from scratch, promoting AGVs whose current plan
        # wait exceeds the cap. verify() is checked on every iteration.
        L, agvs, res, waits, row = _wait_boost(seed, n_jobs, prm, original_ranks, cap=cap)
        row.update(config="C-wait-boost")
        variant_rows.append(row)
        seed_fairness.append(dict(config="C-wait-boost", seed=seed,
                                  **_fairness(original_ranks, waits)))
        for aid, wait in waits.items():
            wait_rows.append(dict(config="C-wait-boost", seed=seed, agv=aid,
                                  priority_rank=original_ranks[aid], wait_s=wait, ok=True))
        # Include baseline C outcomes in the same paired table as variants.
        outcome = base_c_details["m"]
        base_waits = _wait_by_agv(base_c_details["L"], base_c_details["res"]["plans"])
        variant_rows.append(dict(config="C", seed=seed, jobs=n_jobs, agvs=20,
                                 makespan=outcome["makespan_last_delivery"],
                                 tardiness=outcome["tardiness_final"],
                                 imbalance=outcome["load_imbalance"],
                                 wait_total=sum(base_waits.values()),
                                 wait_max=max(base_waits.values()),
                                 cpu_ms=1000 * sum(v["cpu"] for v in base_c_details["servers"].values()),
                                 planning_rounds=1, ok=True))
        print(f"completed seed {seed}")

    _write_csv(os.path.join(outdir, "per_agv_wait.csv"), wait_rows)
    _write_csv(os.path.join(outdir, "fairness_by_seed.csv"), seed_fairness)
    _write_csv(os.path.join(outdir, "fairness_summary.csv"), _summarize_fairness(seed_fairness))
    _write_csv(os.path.join(outdir, "variant_metrics.csv"), variant_rows)
    _write_csv(os.path.join(outdir, "variant_summary.csv"), _summarize_variants(variant_rows))
    _plot(wait_rows, os.path.join(outdir, "mean_wait_by_priority.png"))
    print(f"wrote fairness outputs to {os.path.abspath(outdir)}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--outdir", default=None, help="default: results_fairness_<jobs>j_cap<wait cap>")
    parser.add_argument("--jobs", type=int, default=100)
    parser.add_argument("--wait-cap", type=float, default=CAP_SECONDS)
    args = parser.parse_args()
    if args.outdir is None:  # folder name encodes the settings so runs cannot overwrite each other
        args.outdir = f"results_fairness_{args.jobs}j_cap{args.wait_cap:g}"
    run(args.outdir, args.jobs, args.wait_cap)


if __name__ == "__main__":
    main()
