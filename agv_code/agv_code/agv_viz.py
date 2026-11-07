"""
agv_viz.py - figures, GIF replay and the interactive viewer (same buttons as the original demo)
"""
from __future__ import annotations

import math
from collections import Counter, defaultdict

import numpy as np
import matplotlib.pyplot as plt
from matplotlib.patches import ConnectionPatch
from matplotlib.widgets import Button

from agv_core import plan_segments

FLOOR_COLORS = {1: "#3D5A80", 2: "#1B998B", 3: "#EDAE49"}
KIND_COLORS = {"pickup": "#F28C28", "delivery": "#2E7D32", "lift": "#D1495B"}


# ---------------------------------------------------------------------------------------- helpers
def floors_of(L):
    return sorted({d["floor"] for _, d in L.G.nodes(data=True)})


def position_at(L, pl, t):
    """(floor, (x, y), mode, where) of an AGV at time t.  Never inside an edge window except while moving."""
    pos = lambda n: np.array(L.G.nodes[n]["pos"], dtype=float)
    R, P = pl.R, pl.P
    for m, n in enumerate(R):
        lt, rt = P[m]
        if lt <= t <= rt:
            mode = "WAIT" if n == L.pi else ("L/U" if pl.dwell[m] > 0 else "NODE")
            if m == len(R) - 1 and t >= lt and n == L.pi:
                mode = "DONE"                      # arrived at the final parking visit
            return L.floor(n), pos(n), mode, n
        if m + 1 < len(R):
            e0, e1 = pl.edge_window(m + 1)
            if e0 < t < e1:
                u, v = n, R[m + 1]
                r = (t - e0) / max(e1 - e0, 1e-9)
                if L.is_lift(u, v):
                    return (L.floor(u) if r < 0.5 else L.floor(v)), (pos(u) if r < 0.5 else pos(v)), "LIFT", f"{u}->{v}"
                return L.floor(u), pos(u) + r * (pos(v) - pos(u)), "EDGE", f"{u}->{v}"
    return L.floor(L.pi), pos(L.pi), "DONE", L.pi


def _agv_colors(agvs):
    cmap = plt.get_cmap("tab20")
    return {a.i: cmap(k % 20) for k, a in enumerate(sorted(agvs, key=lambda x: x.priority))}


def _floor_axes(fig, L, rect=None, gs=None):
    fl = floors_of(L)
    axes = {}
    for k, f in enumerate(fl):
        ax = fig.add_subplot(gs[k]) if gs is not None else fig.add_axes(rect[k])
        ax.set_aspect("equal")
        ax.axis("off")
        axes[f] = ax
    return axes


def draw_floor(ax, L, f, heat=None, endpoints=None, labels=True):
    G = L.G
    nodes = [n for n in G if G.nodes[n]["floor"] == f]
    for u, v, d in G.edges(data=True):
        if d.get("kind") == "lift":
            continue
        if G.nodes[u]["floor"] == f:
            (x1, y1), (x2, y2) = G.nodes[u]["pos"], G.nodes[v]["pos"]
            w = 1.5 + (3.0 * heat.get(frozenset((u, v)), 0) / max(heat.values())) if heat else 2.0
            ax.plot([x1, x2], [y1, y2], color="#9AA5B1", lw=w, solid_capstyle="round", zorder=1)
    xs = [G.nodes[n]["pos"][0] for n in nodes]
    ys = [G.nodes[n]["pos"][1] for n in nodes]
    size = [260 + (60 * endpoints.get(n, 0) if endpoints else 0) for n in nodes]
    ax.scatter(xs, ys, s=size, color=FLOOR_COLORS.get(f, "#3D5A80"), edgecolor="white", linewidth=1.5, zorder=3)
    if labels:
        for n, x, y in zip(nodes, xs, ys):
            ax.text(x, y, n, ha="center", va="center", fontsize=7, color="white", fontweight="bold", zorder=4)
    if L.pi in nodes:
        x, y = G.nodes[L.pi]["pos"]
        ax.scatter([x], [y], s=900, marker="s", facecolor="none", edgecolor="#F28C28", linewidth=2.5, zorder=5)
        ax.text(x, y + 6.5 if max(ys) > 5 else y + 0.45, "parking \u03c0", ha="center", fontsize=8, color="#F28C28", fontweight="bold")
    ax.set_title(G.graph.get("floor_names", {}).get(f, f"Floor {f}"), fontsize=10, fontweight="bold")
    pad = 8 if max(xs) > 10 else 0.8
    ax.set_xlim(min(xs) - pad, max(xs) + pad)
    ax.set_ylim(min(ys) - pad, max(ys) + pad)


def _draw_lifts(fig, L, axes):
    for u, v, d in L.G.edges(data=True):
        if d.get("kind") != "lift":
            continue
        fu, fv = L.floor(u), L.floor(v)
        cp = ConnectionPatch(L.G.nodes[u]["pos"], L.G.nodes[v]["pos"], "data", "data", axesA=axes[fu], axesB=axes[fv],
                             color="#D1495B", lw=1.6, linestyle=(0, (4, 3)), zorder=0)
        fig.add_artist(cp)


# ------------------------------------------------------------------------------------ static figures
def fig_floors(L, jobs, agvs, plans, path):
    traffic, ends = Counter(), Counter()
    for a in agvs:
        R = plans[a.i].R
        for m in range(1, len(R)):
            traffic[frozenset((R[m - 1], R[m]))] += 1
    for j in jobs:
        ends[j.p] += 1
        ends[j.p_prime] += 1
    fl = floors_of(L)
    fig = plt.figure(figsize=(6 * len(fl), 6.4))
    gs = fig.add_gridspec(1, len(fl))
    axes = _floor_axes(fig, L, gs=gs)
    floor_traffic = {k: v for k, v in traffic.items() if all(L.G.has_node(n) for n in k) and not L.is_lift(*tuple(k))}
    for f in fl:
        draw_floor(axes[f], L, f, heat=floor_traffic or None, endpoints=ends)
    fig.suptitle("Factory floors: node size = number of pickup/delivery stations placed there, "
                 "line width = number of AGV traversals, dashed red = lift links", fontsize=11)
    fig.canvas.draw()
    _draw_lifts(fig, L, axes)
    for u, v, d in L.G.edges(data=True):
        if d.get("kind") == "lift":
            n = traffic[frozenset((u, v))]
            xa, ya = axes[L.floor(u)].transData.transform(L.G.nodes[u]["pos"])
            xb, yb = axes[L.floor(v)].transData.transform(L.G.nodes[v]["pos"])
            xm, ym = fig.transFigure.inverted().transform(((xa + xb) / 2, (ya + yb) / 2))
            fig.text(xm, ym + 0.012, f"{d['length']:.0f} m  ({n}x)", ha="center", fontsize=7.5, color="#D1495B", fontweight="bold")
    fig.savefig(path, dpi=140, bbox_inches="tight")
    plt.close(fig)


def _draw_gantt(ax, L, agvs, plans, cursor=None, lw=0.7):
    order = sorted(agvs, key=lambda a: a.priority)
    for row, a in enumerate(order):
        by = defaultdict(list)
        for kind, t0, t1, info in plan_segments(L, plans[a.i]):
            if kind == "travel":
                fl = L.floor(info.split("->")[0])
                by[f"travel{fl}"].append((t0, t1 - t0))
            else:
                by[kind].append((t0, t1 - t0))
        for key, segs in by.items():
            if key.startswith("travel"):
                ax.broken_barh(segs, (row - lw / 2, lw), facecolors=FLOOR_COLORS[int(key[-1])], alpha=0.9, linewidth=0)
            elif key == "wait":
                ax.broken_barh(segs, (row - lw / 2, lw), facecolors="#E6E9ED", edgecolors="#9AA5B1", hatch="////", linewidth=0.4)
            else:
                ax.broken_barh(segs, (row - lw / 2, lw), facecolors=KIND_COLORS[key], linewidth=0)
    ax.set_yticks(range(len(order)))
    ax.set_yticklabels([f"{a.i}  (V{a.priority})" for a in order], fontsize=7)
    ax.invert_yaxis()
    ax.set_xlabel("time (s)")
    ax.grid(axis="x", alpha=0.25)
    ax.set_xlim(left=0)
    if cursor is not None:
        ax.axvline(cursor, color="k", ls="--", lw=1.2)


def _gantt_legend(ax, floors, wait_label="waiting at parking (Alg. 3 slide)", y=-0.07):
    from matplotlib.patches import Patch
    h = [Patch(color=FLOOR_COLORS[f], label=f"moving on floor {f}") for f in floors]
    h += [Patch(color=KIND_COLORS["lift"], label="lift"), Patch(color=KIND_COLORS["pickup"], label="loading (\u03b7)"),
          Patch(color=KIND_COLORS["delivery"], label="unloading (\u03b7')"),
          Patch(facecolor="#E6E9ED", edgecolor="#9AA5B1", hatch="////", label=wait_label)]
    ax.legend(handles=h, loc="upper center", bbox_to_anchor=(0.5, y), ncol=len(h), fontsize=8, frameon=False)


def fig_gantt(L, agvs, plans, m, path):
    fig, ax = plt.subplots(figsize=(15, 8.2))
    _draw_gantt(ax, L, agvs, plans)
    _gantt_legend(ax, floors_of(L))
    ax.set_title("Conflict-free schedule of all AGVs (rows in priority order: V1 on top)\n"
                 f"last delivery at {m['makespan_last_delivery']:.0f} s,  fleet back at parking at {m['fleet_back_at_parking']:.0f} s,  "
                 f"load imbalance {m['load_imbalance']:.0f} s", fontsize=11)
    fig.tight_layout()
    fig.savefig(path, dpi=140)
    plt.close(fig)


def fig_load(L, agvs, m, path):
    order = sorted(agvs, key=lambda a: a.priority)
    names = [a.i.replace("AGV-", "") for a in order]
    busy = [m["busy_time"][a.i] for a in order]
    wait = [m["waiting_at_parking"][a.i] for a in order]
    fig, ax = plt.subplots(1, 2, figsize=(15, 4.8), gridspec_kw={"width_ratios": [1.6, 1]})
    ax[0].bar(names, busy, color="#3D5A80", label="busy (moving + loading/unloading)")
    ax[0].bar(names, wait, bottom=busy, color="#E6E9ED", edgecolor="#9AA5B1", hatch="////", label="waiting at parking (Alg. 3)")
    for x, a in enumerate(order):
        ax[0].text(x, busy[x] + wait[x] + 8, str(m["jobs_per_agv"][a.i]), ha="center", fontsize=8)
    ax[0].set_xlabel("AGV number (= priority rank, 1 = highest)")
    ax[0].set_ylabel("usage time (s)")
    ax[0].set_title("Usage time per AGV (number on top = jobs served)")
    ax[0].legend(fontsize=8)
    ax[1].scatter([a.priority for a in order], wait, color="#D1495B")
    ax[1].set_xlabel("AGV priority rank")
    ax[1].set_ylabel("total waiting at parking (s)")
    ax[1].set_title("Lower priority = longer waiting")
    ax[1].grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(path, dpi=140)
    plt.close(fig)


def fig_alg3(calls, estimate, plans, jobs, agvs, path):
    from agv_core import final_job_times, Params
    fig, ax = plt.subplots(1, 3, figsize=(16, 4.6))
    sh = [c["st_star"] for c in calls]
    ax[0].hist(sh, bins=25, color="#3D5A80")
    ax[0].set_xlabel("st*  (shift applied by one call of Algorithm 3, s)")
    ax[0].set_ylabel("number of calls")
    ax[0].set_title(f"{len(calls)} calls of Algorithm 3")
    ps = Counter(c["passes"] for c in calls)
    ax[1].bar([str(k) for k in sorted(ps)], [ps[k] for k in sorted(ps)], color="#1B998B")
    ax[1].set_xlabel("passes k needed")
    ax[1].set_ylabel("calls")
    ax[1].set_title("passes of the outer loop (k)")
    fin = final_job_times(plans, agvs, Params())
    xs = [estimate[j.j]["ct"] for j in jobs]
    ys = [fin[j.j]["delivery_done"] for j in jobs]
    ax[2].scatter(xs, ys, s=14, color="#D1495B")
    lim = max(max(xs), max(ys))
    ax[2].plot([0, lim], [0, lim], "k--", lw=1)
    ax[2].set_xlabel("completion time estimated in Algorithm 1 (ct_ji, conflicts ignored)")
    ax[2].set_ylabel("completion time in the final conflict-free plan")
    ax[2].set_title("Cost of removing conflicts")
    fig.tight_layout()
    fig.savefig(path, dpi=140)
    plt.close(fig)


# ---------------------------------------------------------------------------------------- GIF replay
def save_gif(L, agvs, plans, path, t_end, n_frames=150, fps=12, dpi=90):
    from matplotlib.animation import FuncAnimation, PillowWriter
    fl = floors_of(L)
    fig = plt.figure(figsize=(4.6 * len(fl), 5.6))
    gs = fig.add_gridspec(1, len(fl))
    axes = _floor_axes(fig, L, gs=gs)
    for f in fl:
        draw_floor(axes[f], L, f, labels=False)
    _draw_lifts(fig, L, axes)
    cols = _agv_colors(agvs)
    order = sorted(agvs, key=lambda a: a.priority)
    sc = {f: axes[f].scatter([], [], s=210, zorder=10, edgecolor="k", linewidth=0.8) for f in fl}
    txt = {a.i: [axes[f].text(0, 0, "", fontsize=5.5, ha="center", va="center", zorder=11, fontweight="bold") for f in fl] for a in order}
    title = fig.suptitle("", fontsize=12, fontweight="bold")
    times = np.linspace(0, t_end, n_frames)

    def update(k):
        t = times[k]
        pts = {f: ([], []) for f in fl}
        modes = Counter()
        for a in order:
            f, p, mode, _ = position_at(L, plans[a.i], t)
            modes[mode] += 1
            pts[f][0].append(p)
            pts[f][1].append(cols[a.i])
            for ff in fl:
                txt[a.i][fl.index(ff)].set_text("")
            tx = txt[a.i][fl.index(f)]
            tx.set_position(p)
            tx.set_text(a.i.replace("AGV-", ""))
        for f in fl:
            if pts[f][0]:
                sc[f].set_offsets(np.array(pts[f][0]))
                sc[f].set_facecolor(pts[f][1])
            else:
                sc[f].set_offsets(np.empty((0, 2)))
        title.set_text(f"t = {t:6.0f} s   moving {modes['EDGE']}   in lifts {modes['LIFT']}   loading/unloading {modes['L/U']}   "
                       f"waiting at parking {modes['WAIT']}   parked/done {modes['DONE']}")
        return []

    FuncAnimation(fig, update, frames=n_frames, blit=False).save(path, writer=PillowWriter(fps=fps), dpi=dpi)
    plt.close(fig)


# ---------------------------------------------------------------------------------- interactive viewer
class Viewer:
    """Play / Pause / Step / Reset / A1 / A2 / A3 / All - as in the original demo, for any number of AGVs/floors."""

    def __init__(self, L, jobs, agvs, plans, log, calls, estimate, step_dt=1.0, interval=400):
        self.L, self.jobs, self.agvs, self.plans, self.log = L, jobs, agvs, plans, log
        self.calls, self.estimate, self.step_dt = calls, estimate, step_dt
        self.t, self.running, self.mode = 0.0, False, "all"
        self.t_end = max(p.end_time for p in plans.values()) + 2 * step_dt
        self.cols = _agv_colors(agvs)
        self.order = sorted(agvs, key=lambda a: a.priority)
        fl = floors_of(L)
        self.fl = fl
        self.fig = plt.figure(figsize=(16.5, 10))
        gs = self.fig.add_gridspec(2, len(fl) + 1, height_ratios=[1.0, 0.9], width_ratios=[1] * len(fl) + [0.9])
        self.axes = {f: self.fig.add_subplot(gs[0, k]) for k, f in enumerate(fl)}
        for ax in self.axes.values():
            ax.set_aspect("equal")
            ax.axis("off")
        self.ax_gantt = self.fig.add_subplot(gs[1, :len(fl)])
        self.ax_dbg = self.fig.add_subplot(gs[:, len(fl)])
        self.fig.suptitle("Prioritized multi-AGV scheduling - Algorithms 1, 2 and 3", fontsize=15, fontweight="bold")
        self.buttons = {}
        for k, (lab, cb) in enumerate([("Play", self.play), ("Pause", self.pause), ("Step", self.step), ("Reset", self.reset),
                                       ("A1", lambda e: self.set_mode("a1")), ("A2", lambda e: self.set_mode("a2")),
                                       ("A3", lambda e: self.set_mode("a3")), ("All", lambda e: self.set_mode("all"))]):
            b = Button(self.fig.add_axes([0.04 + k * 0.07, 0.005, 0.06, 0.03]), lab)
            b.on_clicked(cb)
            self.buttons[lab] = b
        from matplotlib.animation import FuncAnimation
        self.anim = FuncAnimation(self.fig, self._tick, interval=interval, blit=False, cache_frame_data=False)
        self.draw()

    def play(self, e=None): self.running = True
    def pause(self, e=None): self.running = False
    def step(self, e=None): self._advance(); self.draw()
    def reset(self, e=None): self.t, self.running = 0.0, False; self.draw()
    def set_mode(self, m): self.mode = m; self.draw()

    def _advance(self):
        self.t = min(self.t + self.step_dt, self.t_end)
        if self.t >= self.t_end:
            self.running = False

    def _tick(self, _):
        if self.running:
            self._advance()
            self.draw()

    def draw(self):
        L = self.L
        modes = Counter()
        for f in self.fl:
            ax = self.axes[f]
            ax.clear(); ax.set_aspect("equal"); ax.axis("off")
            draw_floor(ax, L, f)
        for a in self.order:
            f, p, mode, where = position_at(L, self.plans[a.i], self.t)
            modes[mode] += 1
            ax = self.axes[f]
            ax.scatter([p[0]], [p[1]], s=330, color=self.cols[a.i], edgecolor="k", linewidth=1, zorder=10)
            ax.text(p[0], p[1], a.i.replace("AGV-", ""), ha="center", va="center", fontsize=7, fontweight="bold", zorder=11)
        self.axes[self.fl[0]].set_title(f"{self.axes[self.fl[0]].get_title()}\nt = {self.t:.1f}", fontsize=10, fontweight="bold")
        self.ax_gantt.clear()
        _draw_gantt(self.ax_gantt, L, self.agvs, self.plans, cursor=self.t)
        self.ax_dbg.clear(); self.ax_dbg.axis("off")
        self.ax_dbg.text(0, 1, self._debug(modes), va="top", ha="left", family="monospace", fontsize=7.5, transform=self.ax_dbg.transAxes)
        self.fig.canvas.draw_idle()

    def _debug(self, modes):
        L, out = self.L, []
        if self.mode == "a1":
            out.append("ALGORITHM 1 - job -> AGV (earliest pickup first)\n")
            for st, msg, kw in [e for e in self.log.events if e[0] == "A1"][:45]:
                out.append(f"{msg:<16} F={kw['F']:<7} ct={kw['ct']:<7} et={kw['et']:<5} dt={kw['dt']}")
        elif self.mode == "a2":
            out.append("ALGORITHM 2 - plans P_i (priority order)\n")
            for a in self.order[:30]:
                pl = self.plans[a.i]
                out.append(f"{a.i} V{a.priority:<2} jobs={len(a.jobs):<2} nodes={len(pl.R):<3} end={pl.end_time:8.1f}")
        elif self.mode == "a3":
            out.append(f"ALGORITHM 3 - {len(self.calls)} calls\n")
            big = sorted(self.calls, key=lambda c: -c["st_star"])[:12]
            for c in big:
                out.append(f"{c['agv']} n{c['m']}={c['node']:<4} {c['kind']:<4} k={c['passes']} st*={c['st_star']:.1f} <- {c['blocker']}")
            if big and big[0]["trace"]:
                out.append("\ntrace of the largest call:  (k, term, st, mt, st*, mt*)")
                for row in big[0]["trace"][:14]:
                    out.append("  %d %-16s %s %s %s %s" % (row[0], row[1], *(f"{x:.0f}" if x != math.inf else "inf" for x in row[2:])))
        else:
            out.append(f"LIVE STATE  t = {self.t:.1f}\n")
            out.append("  ".join(f"{k}:{v}" for k, v in sorted(modes.items())) + "\n")
            for a in self.order:
                f, p, mode, where = position_at(L, self.plans[a.i], self.t)
                out.append(f"{a.i:<7}{mode:<6}{where:<9}F{f}")
        return "\n".join(out[:60])
