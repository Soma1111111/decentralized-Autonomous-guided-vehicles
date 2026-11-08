"""
make_paper_gantts.py - paper Gantt figures for seed 7 (100 jobs, 20 AGVs)
=========================================================================
Regenerates the A and C plans for seed 7 deterministically, verifies every
plan with agv_core.verify() (and agv_compare's own violations list) before
plotting, cross-checks the schedule metrics against the saved
results_hybrid_100j_20a_s1-10_strict/comparison.csv row, and writes:

    paper/figures/gantt_A_C_seed7.pdf / .png     main figure: A and C stacked
    paper/figures/gantt_zoom_seed7_agv03.pdf / .png   one AGV, floor legs + lifts
    results_hybrid_100j_20a_s1-10_strict/gantt_annotations_seed7.csv
        (every number used in the figure titles / annotations / captions;
         make_paper_numbers.py turns this CSV into macros)

Run from agv_code/agv_code/:  python make_paper_gantts.py
"""
import csv
import os
from collections import defaultdict

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from agv_compare import run_one
from agv_core import Params, plan_segments, verify

HERE = os.path.dirname(os.path.abspath(__file__))
MAIN_DIR = os.path.join(HERE, "results_hybrid_100j_20a_s1-10_strict")
FIG_DIR = os.path.normpath(os.path.join(HERE, "..", "..", "paper", "figures"))
SEED, N_JOBS, N_AGVS = 7, 100, 20

# Okabe-Ito palette: colorblind-safe, distinct lightness for grayscale
COL = {"floor1": "#0072B2", "floor2": "#E69F00", "floor3": "#009E73",
       "lift": "#CC79A7", "pickup": "#D55E00", "delivery": "#56B4E9"}
WAIT_FACE, WAIT_EDGE, HATCH = "#E8EAED", "#7A828A", "////"
prm = Params(eta=16.0, eta_p=16.0, delta=10.0, lam=1.0, track_rule="strict")


def fmt(x, dec=1):
    return f"{x:,.{dec}f}"


def segments(L, pl):
    """plan_segments plus the floor of every segment (lift segments: None)."""
    out = []
    for kind, t0, t1, info in plan_segments(L, pl):
        fl = None
        if kind in ("travel", "pickup", "delivery", "wait"):
            node = info.split("->")[0].split("@")[-1].replace("wait at ", "")
            fl = L.floor(node)
        out.append((kind, t0, t1, info, fl))
    return out


def pre_move_wait(segs):
    """Total waiting before the AGV's first move or service."""
    t_first = min((t0 for k, t0, t1, i, f in segs if k != "wait"), default=None)
    if t_first is None:
        return 0.0
    return sum(t1 - t0 for k, t0, t1, i, f in segs
               if k == "wait" and t1 <= t_first + 1e-9)


def service_time(segs):
    return sum(t1 - t0 for k, t0, t1, i, f in segs if k in ("pickup", "delivery"))


# ---------------------------------------------------------------------------
# 1) regenerate seed 7, verify every plan, cross-check against the saved CSV
# ---------------------------------------------------------------------------
det = {}
for cfg in ("A", "C"):
    row, d = run_one(cfg, SEED, N_JOBS, N_AGVS, prm)
    assert not d["res"]["violations"], f"{cfg}: planner reported violations"
    bad = verify(d["L"], d["res"]["plans"], d["agvs"], d["jobs"], prm)
    assert not bad, f"{cfg}: agv_core.verify() rejected the plans: {bad[:3]}"
    with open(os.path.join(MAIN_DIR, "comparison.csv"), newline="", encoding="utf-8") as fh:
        saved = next(r for r in csv.DictReader(fh)
                     if r["config"] == cfg and r["seed"] == str(SEED))
    for key, val in (("makespan", d["m"]["makespan_last_delivery"]),
                     ("imbalance", d["m"]["load_imbalance"]),
                     ("wait_total", sum(d["m"]["waiting_at_parking"].values()))):
        assert abs(float(saved[key]) - val) < 1e-6, \
            f"{cfg} {key}: regenerated {val} != saved {saved[key]}"
    det[cfg] = d
    print(f"{cfg}: seed 7 regenerated, verified, and matches comparison.csv")

L = det["C"]["L"]

# ---------------------------------------------------------------------------
# 2) annotation numbers (all from the verified plans)
# ---------------------------------------------------------------------------
ann = {}
for cfg in ("A", "C"):
    d = det[cfg]
    pm = {a.i: pre_move_wait(segments(d["L"], d["res"]["plans"][a.i])) for a in d["agvs"]}
    agv = max(pm, key=lambda k: pm[k])
    segs = segments(d["L"], d["res"]["plans"][agv])
    ann[cfg] = dict(
        agv=agv, wait=pm[agv], service=service_time(segs),
        makespan=d["m"]["makespan_last_delivery"], imbalance=d["m"]["load_imbalance"],
        wait_total=sum(d["m"]["waiting_at_parking"].values()),
        first_service=min((t0 for k, t0, t1, i, f in segs if k in ("pickup", "delivery")),
                          default=None))
assert abs(ann["A"]["service"] - ann["C"]["service"]) < 1e-9, \
    "the annotated AGV must have the same service time in A and C"
assert ann["A"]["service"] > 0, "annotated AGV serves no jobs"
print(f"annotation AGV {ann['A']['agv']}: wait A={ann['A']['wait']:.1f} s, "
      f"C={ann['C']['wait']:.1f} s, service={ann['A']['service']:.1f} s")

# zoom AGV: most lift trips in C (ties by lowest priority rank)
zoom = min(det["C"]["agvs"], key=lambda a: (-sum(1 for k, *_ in segments(L, det["C"]["res"]["plans"][a.i])
                                                 if k == "lift"), a.priority))
zsegs = segments(L, det["C"]["res"]["plans"][zoom.i])
zlifts = [(t0, t1, info) for k, t0, t1, info, f in zsegs if k == "lift"]
zlobby = [(t0, t1, info.split("at ")[1]) for k, t0, t1, info, f in zsegs
          if k == "wait" and info.split("at ")[1] in L.lobbies]
zfloors = {f for k, t0, t1, i, f in zsegs if f}
assert len(zlifts) >= 2 and len(zfloors) >= 2, "zoom AGV is not illustrative"
print(f"zoom AGV {zoom.i}: {len(zlifts)} lift trips, {len(zlobby)} lobby waits, "
      f"floors {sorted(zfloors)}")

# ---------------------------------------------------------------------------
# 3) main figure: A and C stacked, shared time axis
# ---------------------------------------------------------------------------
x_max = max(max(pl.end_time for pl in det[c]["res"]["plans"].values())
            for c in ("A", "C")) * 1.01

fig = plt.figure(figsize=(7.0, 4.3))
gs = fig.add_gridspec(2, 1, hspace=0.28, left=0.085, right=0.985, top=0.87, bottom=0.22)
axes = {}
for k, cfg in enumerate(("A", "C")):
    ax = fig.add_subplot(gs[k])
    axes[cfg] = ax
    d = det[cfg]
    order = sorted(d["agvs"], key=lambda a: a.priority)
    for row, a in enumerate(order):
        by = defaultdict(list)
        for kind, t0, t1, info, fl in segments(d["L"], d["res"]["plans"][a.i]):
            key = f"floor{fl}" if kind == "travel" else kind
            by[key].append((t0, t1 - t0))
        for key, segs in by.items():
            if key == "wait":
                ax.broken_barh(segs, (row - 0.38, 0.76), facecolors=WAIT_FACE,
                               edgecolors=WAIT_EDGE, hatch=HATCH, linewidth=0.3)
            else:
                ax.broken_barh(segs, (row - 0.38, 0.76), facecolors=COL[key],
                                   linewidth=0.15, edgecolors="#404040")
    ax.set_yticks(range(len(order)))
    ax.set_yticklabels([f"V{a.priority:02d}" for a in order], fontsize=5.5)
    ax.invert_yaxis()
    ax.set_xlim(0, x_max)
    ax.set_ylim(len(order) - 0.5, -0.5)
    ax.grid(axis="x", alpha=0.25, linewidth=0.4)
    ax.tick_params(axis="x", labelsize=7)
    a = ann[cfg]
    ax.axvline(a["makespan"], color="#333333", ls="--", lw=0.9)
    ax.set_title(f"{cfg} — {'centralized (paper)' if cfg == 'A' else 'hybrid (central + floor servers)'}:  "
                 f"last delivery {fmt(a['makespan'])} s, load imbalance {fmt(a['imbalance'])} s, "
                 f"total waiting {fmt(a['wait_total'])} s", fontsize=8, loc="left")
    # annotations for the SAME AGV in both panels
    row = next(r for r, ag in enumerate(order) if ag.i == a["agv"])
    y_row = row  # data y (inverted axis; V20 is the bottom row)
    if cfg == "A":
        # Panel A: one short annotation at AGV-20's first-move point (bottom row).
        ax.annotate(f"{a['agv']}: waits {fmt(a['wait'], 0)} s before first move",
                    xy=(a["wait"], y_row), xycoords="data",
                    xytext=(a["wait"] - 1500, y_row - 1.7), textcoords="data",
                    ha="center", fontsize=6.5,
                    arrowprops=dict(arrowstyle="->", lw=0.6, color="#333333"),
                    bbox=dict(fc="white", ec="#999999", lw=0.4, pad=1.5))
    else:
        # Panel C: annotations in the empty right side.
        ax.annotate(f"{a['agv']}: waits {fmt(a['wait'], 0)} s before first move",
                    xy=(a["wait"], y_row), xycoords="data",
                    xytext=(x_max * 0.62, 1.05), textcoords="axes fraction",
                    ha="left", fontsize=6.5,
                    arrowprops=dict(arrowstyle="->", lw=0.6, color="#333333"),
                    bbox=dict(fc="white", ec="#999999", lw=0.4, pad=1.5))
        ax.annotate(f"service (load+unload): {fmt(a['service'], 0)} s in total",
                    xy=(a["first_service"], y_row - 0.5), xycoords="data",
                    xytext=(x_max * 0.62, 0.92), textcoords="axes fraction",
                    ha="left", fontsize=6.5,
                    arrowprops=dict(arrowstyle="->", lw=0.6, color="#333333"),
                    bbox=dict(fc="white", ec="#999999", lw=0.4, pad=1.5))
axes["C"].set_xlabel("time (s)", fontsize=8)
handles = [plt.Rectangle((0, 0), 1, 1, fc=COL[f"floor{f}"], ec="#404040", lw=0.3,
                         label=f"moving on floor {f}")
           for f in (1, 2, 3)]
handles += [plt.Rectangle((0, 0), 1, 1, fc=COL["lift"], ec="#404040", lw=0.3, label="lift trip"),
            plt.Rectangle((0, 0), 1, 1, fc=COL["pickup"], ec="#404040", lw=0.3, label="loading ($\\eta$)"),
            plt.Rectangle((0, 0), 1, 1, fc=COL["delivery"], ec="#404040", lw=0.3, label="unloading ($\\eta'$)"),
            plt.Rectangle((0, 0), 1, 1, fc=WAIT_FACE, ec=WAIT_EDGE, hatch=HATCH, label="waiting")]
fig.legend(handles=handles, loc="lower center", ncol=4, fontsize=6, frameon=False,
           bbox_to_anchor=(0.5, 0.018))
for ext in ("pdf", "png"):
    fig.savefig(os.path.join(FIG_DIR, f"gantt_A_C_seed7.{ext}"), dpi=300)
plt.close(fig)
print("wrote gantt_A_C_seed7.pdf/.png")

# ---------------------------------------------------------------------------
# 4) zoom figure: one AGV, floor legs + lift trips + lobby waits
# ---------------------------------------------------------------------------
z0 = min(t0 for _, t0, t1, i, f in zsegs)
z1 = max(t1 for _, t0, t1, i, f in zsegs)
lanes = {1: 0, 2: 1, 3: 2, "lift": 3}
fig = plt.figure(figsize=(3.5, 3.15))
ax = fig.add_subplot(111)
ax.set_xlim(z0, z1 + (z1 - z0) * 0.02)
ax.set_ylim(5.75, -0.7)                       # extra band below the lift lane for labels
for k, t0, t1, info, fl in zsegs:
    y = lanes["lift"] if k == "lift" else lanes[fl]
    if k == "wait":
        ax.broken_barh([(t0, t1 - t0)], (y - 0.34, 0.68), facecolors=WAIT_FACE,
                       edgecolors=WAIT_EDGE, hatch=HATCH, linewidth=0.3)
        if info.split("at ")[1] in L.lobbies:
            ax.text((t0 + t1) / 2, y + 0.55, f"{t1 - t0:.0f} s", rotation=90,
                    ha="center", va="bottom", fontsize=4.2, color="#555555")
    else:
        key = "lift" if k == "lift" else (f"floor{fl}" if k == "travel" else k)
        ax.broken_barh([(t0, t1 - t0)], (y - 0.34, 0.68), facecolors=COL[key],
                       linewidth=0.2, edgecolors="#404040")
for n, (t0, t1, info) in enumerate(zlifts):  # staggered so adjacent trips do not collide
    ax.text((t0 + t1) / 2, 3.52 + (0.0 if n % 2 == 0 else 0.62),
            info.replace("~", "").replace("->", "\u2192"),
            rotation=90, ha="center", va="top", fontsize=4.6, color="#7A3E5C")
ax.set_yticks([0, 1, 2, 3])
ax.set_yticklabels(["Floor 1", "Floor 2", "Floor 3", "Lift"], fontsize=6.5)
ax.set_xlabel("time (s)", fontsize=7)
ax.tick_params(axis="x", labelsize=6.5)
ax.grid(axis="x", alpha=0.25, linewidth=0.4)
ax.set_ylim(4.5, -0.7)
ax.set_title(f"{zoom.i} in C (seed {SEED}): {len(zlifts)} lift trips, "
             f"{len(zlobby)} lobby waits", fontsize=7.5, loc="left")
fig.tight_layout()
for ext in ("pdf", "png"):
    fig.savefig(os.path.join(FIG_DIR, f"gantt_zoom_seed7_{zoom.i.lower()}.{ext}"), dpi=300)
plt.close(fig)
zoom_name = f"gantt_zoom_seed7_{zoom.i.lower()}"
print(f"wrote {zoom_name}.pdf/.png")

# ---------------------------------------------------------------------------
# 5) annotations CSV: every figure number, traceable (read by make_paper_numbers.py)
# ---------------------------------------------------------------------------
path = os.path.join(MAIN_DIR, "gantt_annotations_seed7.csv")
with open(path, "w", newline="", encoding="utf-8") as fh:
    w = csv.writer(fh)
    w.writerow(["figure", "panel", "agv", "priority", "pre_move_wait_s", "service_s",
                "last_delivery_s", "imbalance_s", "wait_total_s",
                "lift_trips", "lobby_waits", "lobby_wait_total_s"])
    for cfg in ("A", "C"):
        a = ann[cfg]
        w.writerow([f"gantt_A_C_seed7", cfg, a["agv"],
                    next(ag.priority for ag in det[cfg]["agvs"] if ag.i == a["agv"]),
                    f"{a['wait']:.3f}", f"{a['service']:.3f}", f"{a['makespan']:.3f}",
                    f"{a['imbalance']:.3f}", f"{a['wait_total']:.3f}",
                    len(zlifts) if cfg == "C" else "", "", ""])
    w.writerow([zoom_name, "C", zoom.i, zoom.priority, "", "", "", "", "",
                len(zlifts), len(zlobby), f"{sum(t1 - t0 for t0, t1, i in zlobby):.3f}"])
print(f"wrote {os.path.relpath(path, HERE)}")
