"""
agv_compare.py - centralized vs hybrid (central + floor servers) on the same jobs
==================================================================================
Three configurations, all on the 3-floor layout WITH lift lobbies, all with the SAME Algorithm-1 job
assignment (so every difference comes from the routing architecture):

  A  centralized        : one server, the paper's rule - an AGV may wait only at the parking station pi
  B  centralized+lobby  : one server, AGVs may also wait in the lift lobbies (isolates the lobby effect)
  C  hybrid             : central server (Alg. 1, lift booking) + 3 floor servers (Alg. 2/3 on their floor),
                          legs planned first-come-first-served per floor

Check: the hybrid planned in priority order must give exactly the plans of B (decomposition is lossless).

Run:
    python agv_compare.py                          # 10 seeds, 100 jobs, 20 AGVs, AGV sweep 4..20 -> ./results_hybrid
    python agv_compare.py --seeds 1-30 --jobs 200
"""
import argparse
import csv
import os
import statistics as stats
import time

from agv_core import AGV, Log, Params, metrics, run_pipeline
from agv_hybrid import run_hybrid
from agv_layouts import build_three_floors
from agv_multifloor_demo import make_jobs

CONFIGS = [("A", "Centralized (paper)"), ("B", "Centralized + lobbies"), ("C", "Hybrid: central + floor servers")]
COLORS = {"A": "#2a78d6", "B": "#eb6834", "C": "#1baf7a"}      # categorical slots 1-3 (validated all-pairs)
INK, INK2, GRID = "#0b0b0b", "#52514e", "#e4e3df"
METRICS = [  # key, label, unit
    ("makespan", "Last delivery (makespan)", "s"),
    ("tardiness", "Total tardiness", "s"),
    ("imbalance", "Load imbalance (max - min usage)", "s"),
    ("wait_total", "Total waiting (parking + lobbies)", "s"),
    ("wait_max", "Longest wait of one AGV", "s"),
    ("cpu_ms", "Planning compute time, busiest server", "ms"),
]


def layout(cfg):
    L = build_three_floors(lobbies=True)
    if cfg in ("B", "C"):
        L.exempt = {L.pi} | L.lobbies
    return L


def count_windows(L, plans):
    """Windows a single central server holds at the end (all non-exempt nodes + all tracks)."""
    return sum(sum(1 for n in pl.R if n not in L.exempt) + len(pl.R) - 1 for pl in plans.values())


def run_one(cfg, seed, n_jobs, n_agvs, prm, order="fcfs"):
    L = layout(cfg)
    jobs = make_jobs(L, prm, n_jobs, seed)
    agvs = [AGV(f"AGV-{k:02d}", k) for k in range(1, n_agvs + 1)]
    log = Log()
    tic = time.perf_counter()
    res = run_hybrid(L, jobs, agvs, prm, log, order=order) if cfg == "C" else run_pipeline(L, jobs, agvs, prm, log)
    wall = time.perf_counter() - tic
    m = metrics(L, res["plans"], agvs, jobs, res["estimate"], res["calls"], prm)
    if cfg == "C":
        servers = res["servers"]
    else:
        servers = {"central": dict(cpu=res["t_alg1"] + res["t_alg2"], windows=count_windows(L, res["plans"]))}
    row = dict(config=cfg, seed=seed, jobs=n_jobs, agvs=n_agvs, ok=not res["violations"],
               makespan=m["makespan_last_delivery"], fleet_back=m["fleet_back_at_parking"],
               tardiness=m["tardiness_final"], earliness=m["earliness_final"], imbalance=m["load_imbalance"],
               wait_total=sum(m["waiting_at_parking"].values()), wait_max=max(m["waiting_at_parking"].values()),
               alg3_calls=m["alg3_calls"], cpu_total_ms=1000 * sum(s["cpu"] for s in servers.values()),
               cpu_ms=1000 * max(s["cpu"] for s in servers.values()), wall_ms=1000 * wall,
               max_windows_one_server=max(s["windows"] for s in servers.values()),
               messages=res.get("messages", 0), payload_windows=res.get("payload", 0))
    return row, dict(L=L, jobs=jobs, agvs=agvs, res=res, m=m, servers=servers)


def same_plans(p1, p2, tol=1e-6):
    return all(p1[k].R == p2[k].R and all(abs(x - y) <= tol for w1, w2 in zip(p1[k].P, p2[k].P)
                                           for x, y in zip(w1, w2)) for k in p1)


def parse_seeds(s):
    if "-" in s:
        a, b = map(int, s.split("-"))
        return list(range(a, b + 1))
    return [int(x) for x in s.split(",")]


# ----------------------------------------------------------------------------------------------- figures
def _style(ax):
    for sp in ("top", "right"):
        ax.spines[sp].set_visible(False)
    for sp in ("left", "bottom"):
        ax.spines[sp].set_color(GRID)
    ax.tick_params(colors=INK2, labelsize=8)
    ax.grid(axis="y", color=GRID, lw=0.8)
    ax.set_axisbelow(True)


def fig_bars(rows, path):
    import matplotlib.pyplot as plt
    from matplotlib.patches import Patch
    fig, axes = plt.subplots(2, 3, figsize=(14, 7.6))
    for ax, (key, label, unit) in zip(axes.flat, METRICS):
        means, lo, hi = [], [], []
        for c, _ in CONFIGS:
            v = [r[key] for r in rows if r["config"] == c]
            means.append(stats.mean(v)); lo.append(min(v)); hi.append(max(v))
        x = range(len(CONFIGS))
        ax.bar(x, means, width=0.62, color=[COLORS[c] for c, _ in CONFIGS], edgecolor="white", linewidth=2)
        ax.errorbar(x, means, yerr=[[m - l for m, l in zip(means, lo)], [h - m for m, h in zip(means, hi)]],
                    fmt="none", ecolor=INK2, elinewidth=1, capsize=4)
        for xi, mv, h in zip(x, means, hi):
            ax.text(xi, h * 1.02 + 1e-9, f"{mv:,.0f}" if mv >= 10 else f"{mv:.1f}", ha="center", va="bottom", fontsize=9, color=INK)
        ax.set_xticks(list(x)); ax.set_xticklabels(["A", "B", "C"], color=INK2)
        ax.set_title(f"{label} ({unit})", fontsize=10, color=INK, loc="left")
        ax.set_ylim(0, max(hi) * 1.18 + 1e-9)
        _style(ax)
    n = len({r["seed"] for r in rows})
    fig.legend(handles=[Patch(color=COLORS[c], label=f"{c}  {name}") for c, name in CONFIGS],
               loc="lower center", ncol=3, frameon=False, fontsize=9)
    fig.suptitle(f"Centralized vs hybrid: mean over {n} random job sets (bar), min-max (whisker); lower is better",
                 fontsize=12, color=INK)
    fig.tight_layout(rect=(0, 0.05, 1, 0.96))
    fig.savefig(path, dpi=140)
    plt.close(fig)


def fig_gantts(details, path, title=None):
    import matplotlib.pyplot as plt
    import agv_viz as viz
    fig, axes = plt.subplots(3, 1, figsize=(15, 17), sharex=True)
    if title:
        fig.suptitle(title, fontsize=13, color=INK)
    for ax, (c, name) in zip(axes, CONFIGS):
        d = details[c]
        viz._draw_gantt(ax, d["L"], d["agvs"], d["res"]["plans"], lw=0.7)
        m = d["m"]
        ax.set_title(f"{c}  {name}:  last delivery {m['makespan_last_delivery']:.0f} s,  "
                     f"load imbalance {m['load_imbalance']:.0f} s,  total waiting {sum(m['waiting_at_parking'].values()):.0f} s",
                     fontsize=11, loc="left", color=INK)
        ax.set_xlabel("")
    axes[-1].set_xlabel("time (s)")
    viz._gantt_legend(axes[-1], viz.floors_of(details["A"]["L"]), wait_label="waiting at parking or lift lobby", y=-0.12)
    fig.tight_layout(rect=(0, 0, 1, 0.975) if title else None)
    fig.savefig(path, dpi=120)
    plt.close(fig)


def fig_sweep(sweep_rows, path):
    import matplotlib.pyplot as plt
    keys = [("makespan", "Last delivery (s)"), ("tardiness", "Total tardiness (s)"), ("imbalance", "Load imbalance (s)")]
    sizes = sorted({r["agvs"] for r in sweep_rows})
    fig, axes = plt.subplots(1, 3, figsize=(15, 4.6))
    for ax, (key, label) in zip(axes, keys):
        for c, name in CONFIGS:
            ys = [stats.mean(r[key] for r in sweep_rows if r["config"] == c and r["agvs"] == n) for n in sizes]
            ax.plot(sizes, ys, color=COLORS[c], lw=2, marker="o", ms=6, mec="white", mew=2, label=f"{c}  {name}")
            ax.annotate(c, (sizes[-1], ys[-1]), xytext=(6, 0), textcoords="offset points", va="center", fontsize=9, color=INK2)
        ax.set_xticks(sizes)
        ax.set_xlabel("number of AGVs", color=INK2, fontsize=9)
        ax.set_title(label, fontsize=10, loc="left", color=INK)
        ax.set_ylim(bottom=0)
        _style(ax)
    axes[0].legend(fontsize=8, frameon=False)
    fig.suptitle("Effect of fleet size (mean over seeds)", fontsize=12, color=INK)
    fig.tight_layout()
    fig.savefig(path, dpi=140)
    plt.close(fig)


def fig_servers(details, path):
    import matplotlib.pyplot as plt
    fig, axes = plt.subplots(1, 2, figsize=(13, 4.4))
    bars = [("A: central", details["A"]["servers"]["central"], COLORS["A"])]
    bars += [(f"C: {k}", v, COLORS["C"]) for k, v in details["C"]["servers"].items()]
    names = [b[0] for b in bars]
    for ax, key, label, scale in ((axes[0], "cpu", "Planning compute time per server (ms)", 1000),
                                  (axes[1], "windows", "Time windows stored per server", 1)):
        vals = [b[1][key] * scale for b in bars]
        ax.bar(names, vals, color=[b[2] for b in bars], edgecolor="white", linewidth=2, width=0.62)
        for x, v in enumerate(vals):
            ax.text(x, v * 1.02, f"{v:,.1f}" if scale > 1 else f"{v:,.0f}", ha="center", va="bottom", fontsize=9, color=INK)
        ax.set_title(label, fontsize=10, loc="left", color=INK)
        ax.set_ylim(0, max(vals) * 1.18)
        _style(ax)
    fig.suptitle("Work and state per server (one job set): one central server vs central + 3 floor servers",
                 fontsize=12, color=INK)
    fig.tight_layout()
    fig.savefig(path, dpi=140)
    plt.close(fig)


# ------------------------------------------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", default="1-10")
    ap.add_argument("--jobs", type=int, default=100)
    ap.add_argument("--agvs", type=int, default=20)
    ap.add_argument("--sweep", default="4,8,12,16,20", help="fleet sizes for the AGV sweep ('' to skip)")
    ap.add_argument("--gantt-seed", type=int, default=7)
    ap.add_argument("--outdir", default="results_hybrid")
    ap.add_argument("--gantts-only", action="store_true",
                    help="only write an A/B/C Gantt figure for every seed to <outdir>/gantts/")
    a = ap.parse_args()

    import matplotlib
    matplotlib.use("Agg")
    os.makedirs(a.outdir, exist_ok=True)
    out = lambda f: os.path.join(a.outdir, f)
    prm = Params(eta=16.0, eta_p=16.0, delta=10.0, lam=1.0)
    seeds = parse_seeds(a.seeds)

    if a.gantts_only:                    # one A/B/C Gantt figure per seed, nothing else is (re)written
        os.makedirs(out("gantts"), exist_ok=True)
        for s in seeds:
            details = {c: run_one(c, s, a.jobs, a.agvs, prm)[1] for c, _ in CONFIGS}
            assert all(not d["res"]["violations"] for d in details.values())
            path = out(os.path.join("gantts", f"gantt_A_B_C_seed{s:02d}.png"))
            fig_gantts(details, path, title=f"Job set (seed) {s}: {a.jobs} jobs, {a.agvs} AGVs")
            print("wrote", path)
        return

    # 1) correctness: hybrid in priority order == centralized with lobbies
    for s in seeds:
        _, dB = run_one("B", s, a.jobs, a.agvs, prm)
        _, dC = run_one("C", s, a.jobs, a.agvs, prm, order="priority")
        assert same_plans(dB["res"]["plans"], dC["res"]["plans"]), f"decomposition check failed (seed {s})"
    print(f"check: hybrid (priority order) == centralized + lobbies on {len(seeds)} seeds  OK")

    # 2) main comparison
    rows, details = [], {}
    for s in seeds:
        for c, _ in CONFIGS:
            r, d = run_one(c, s, a.jobs, a.agvs, prm)
            assert r["ok"], f"verification failed: config {c}, seed {s}: {d['res']['violations'][:3]}"
            rows.append(r)
            if s == a.gantt_seed:
                details[c] = d
    with open(out("comparison.csv"), "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)

    # 3) fleet-size sweep
    sweep_rows = []
    sizes = [int(x) for x in a.sweep.split(",")] if a.sweep else []
    for n in sizes:
        for s in seeds:
            for c, _ in CONFIGS:
                r, _ = run_one(c, s, a.jobs, n, prm)
                assert r["ok"]
                sweep_rows.append(r)
    if sweep_rows:
        with open(out("sweep_agvs.csv"), "w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=list(sweep_rows[0]))
            w.writeheader()
            w.writerows(sweep_rows)

    # 4) text summary
    keys = METRICS + [("cpu_total_ms", "Planning compute time, all servers", "ms"),
                      ("max_windows_one_server", "Time windows held by one server", ""),
                      ("messages", "Central <-> floor messages", ""), ("alg3_calls", "Algorithm 3 calls", "")]
    txt = [f"CENTRALIZED vs HYBRID  -  {a.jobs} jobs, {a.agvs} AGVs, seeds {seeds[0]}..{seeds[-1]} ({len(seeds)} job sets)",
           "all plans verified conflict-free by agv_core.verify(); hybrid in priority order == B on every seed", "",
           *[f"  {c}  {name}" for c, name in CONFIGS], "",
           f"{'metric (mean over seeds)':<44}" + "".join(f"{c:>14}" for c, _ in CONFIGS) + f"{'C vs A':>10}"]
    for key, label, unit in keys:
        mv = [stats.mean(r[key] for r in rows if r["config"] == c) for c, _ in CONFIGS]
        rel = f"{100 * (mv[2] - mv[0]) / mv[0]:+.0f}%" if mv[0] else "-"
        txt.append(f"{label + (f' ({unit})' if unit else ''):<44}" + "".join(f"{v:14,.1f}" for v in mv) + f"{rel:>10}")
    if sweep_rows:
        txt += ["", "fleet-size sweep (mean over seeds): load imbalance (s) / total tardiness (s)",
                f"{'AGVs':<8}" + "".join(f"{c:>24}" for c, _ in CONFIGS)]
        for n in sizes:
            cells = []
            for c, _ in CONFIGS:
                sel = [r for r in sweep_rows if r["config"] == c and r["agvs"] == n]
                cells.append(f"{stats.mean(r['imbalance'] for r in sel):,.0f} / {stats.mean(r['tardiness'] for r in sel):,.0f}")
            txt.append(f"{n:<8}" + "".join(f"{x:>24}" for x in cells))
    if details:
        txt += ["", f"per server, seed {a.gantt_seed}:   compute (ms)   windows held"]
        for c in ("A", "C"):
            for k, v in details[c]["servers"].items():
                txt.append(f"  {c}  {k:<10} {1000 * v['cpu']:12.1f} {v['windows']:14,d}")
    open(out("summary.txt"), "w").write("\n".join(txt) + "\n")
    print("\n".join(txt))

    # 5) figures
    fig_bars(rows, out("fig1_compare_metrics.png"))
    if details:
        fig_gantts(details, out("fig2_gantt_A_B_C.png"))
        fig_servers(details, out("fig4_per_server.png"))
    if sweep_rows:
        fig_sweep(sweep_rows, out("fig3_fleet_size_sweep.png"))
    print(f"\nfiles written to {os.path.abspath(a.outdir)}")


if __name__ == "__main__":
    main()
