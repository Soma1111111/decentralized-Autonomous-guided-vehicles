"""
agv_core.py  -  Prioritized planning for multiple-AGV scheduling
=================================================================
Implementation of the three algorithms of

    Guo, Yao, Li, Su, Ling - "Prioritized Planning for Large-Scale Multiple-AGV
    Scheduling Problem in Smart Manufacturing", ICARCV 2024,

written with the SAME NOTATION as the walkthrough deck.

NOTATION  (deck symbol  ->  name used in this code)
---------------------------------------------------
J, j                 jobs, Job.j
V, i                 AGVs, AGV.i
p_j, t_j             Job.p, Job.t              pickup station / desired pickup time
p'_j, t'_j           Job.p_prime, Job.t_prime  delivery station / desired delivery time
eta, eta'            Params.eta, Params.eta_p  loading / unloading time
G = {N, E}           Layout.G (undirected graph: every track is a bidirectional track)
pi                   Layout.pi                 THE parking station
delta                Params.delta              safety separation time
r_nn'                Layout.r_nn[(n, n2)]      Dijkstra shortest path (node list)
delta_nn'            Layout.delta_nn(n, n2)    non-stop travel time of that path
vt_i, s_i            AGV.vt, AGV.s             time / node at which AGV i becomes free
F_ji, ct_ji, et_ji, dt_ji, lambda
                     fitness(...)['F'|'ct'|'et'|'dt'], Params.lam
R_i                  AGV.R                     route (node sequence)
P_i = {[lt_m, rt_m]} Plan.P                    occupancy window of every node of R_i
W_n, W'_e            W[n], Wp[(u, v)]          fixed windows of higher-priority AGVs
st, mt = f(lt, rt, W) f(lt, rt, W, delta)
st*, mt*, k_max      st_star, mt_star, Params.k_max
V_1, V_2, ...        AGV.priority  (1 = V_1 = highest priority)

MODELLING CHOICES (where the paper is silent or where we are stricter)
----------------------------------------------------------------------
* eta / eta' are spent ONLY at the pickup / delivery node (pass-through nodes have lt = rt).
* The parking station pi is exempt from node conflicts (assumption 3 of the paper) and is the
  place where an AGV waits when Algorithm 3 pushes its plan to the right.
* A track (a pair of opposite edges) can hold one AGV at a time (assumption 4).  We check the
  new edge window against the windows of BOTH directions of the track (the paper's Table I
  names the reverse edge; checking both also forbids following on the same track).
* Algorithm 3 is started at node n_p.  For an *edge* conflict on e(n_{p-1}, n_p) the same sweep is
  used: it tests node n_p, then edge e(n_{p-1}, n_p), then node n_{p-1}, ... which only adds one
  extra (harmless) term to the paper's  edge -> node -> edge ... sequence.
"""
from __future__ import annotations

import math
import time
from collections import defaultdict
from dataclasses import dataclass, field

import networkx as nx

INF = math.inf
EPS = 1e-9


# ----------------------------------------------------------------------------------------------
# data structures
# ----------------------------------------------------------------------------------------------
@dataclass
class Params:
    eta: float = 16.0        # loading time
    eta_p: float = 16.0      # unloading time (eta')
    delta: float = 10.0      # safety separation time
    lam: float = 1.0         # weight lambda in the fitness function
    k_max: int = 100000      # maximum number of passes of Algorithm 3


@dataclass
class Job:
    j: str
    p: str            # pickup station p_j
    t: float          # desired pickup time t_j
    p_prime: str      # delivery station p'_j
    t_prime: float    # desired delivery time t'_j


@dataclass
class AGV:
    i: str
    priority: int                                   # 1 = V_1 = highest priority
    vt: float = 0.0                                 # vt_i
    s: str = ""                                     # s_i
    R: list = field(default_factory=list)           # R_i
    dwell: list = field(default_factory=list)       # L/U time spent at each node of R_i
    events: list = field(default_factory=list)      # (route index, 'pickup'|'delivery', job id)
    jobs: list = field(default_factory=list)


@dataclass
class Plan:
    i: str
    R: list
    P: list                       # P_i : list of [lt_m, rt_m]  (mutable)
    dwell: list
    events: list

    def edge_window(self, m):     # window of e(n_{m-1}, n_m) is [rt_{m-1}, lt_m]
        return self.P[m - 1][1], self.P[m][0]

    @property
    def end_time(self):               # time at which the AGV is finished (back at pi)
        return self.P[-1][1]


class Layout:
    """Graph G = {N, E}, one parking station pi, Dijkstra tables r_nn' and delta_nn'."""

    def __init__(self, G: nx.Graph, parking: str, speed: float = 1.0):
        self.G, self.pi, self.speed = G, parking, speed
        # nodes exempt from node conflicts, where an AGV may wait (paper: only pi).  The hybrid
        # architecture (agv_hybrid.py) adds the lift lobbies here.
        self.exempt = {parking}
        self.lobbies = {n for n, d in G.nodes(data=True) if d.get("lobby")}
        self.r_nn, self._dist = {}, {}
        for n, (dist, path) in nx.all_pairs_dijkstra(G, weight="length"):
            for n2, pth in path.items():
                self.r_nn[(n, n2)] = pth
                self._dist[(n, n2)] = dist[n2]

    def delta_nn(self, n, n2):                       # delta_nn' = path length / speed
        return self._dist[(n, n2)] / self.speed

    def delta_edge(self, u, v):                      # non-stop travel time of one edge
        return self.G[u][v]["length"] / self.speed

    def floor(self, n):
        return self.G.nodes[n].get("floor", 1)

    def is_lift(self, u, v):
        return self.G[u][v].get("kind") == "lift"


class Log:
    def __init__(self, echo=False):
        self.events, self.echo = [], echo

    def add(self, stage, msg, **kw):
        self.events.append((stage, msg, kw))
        if self.echo:
            extra = "  ".join(f"{k}={v}" for k, v in kw.items())
            print(f"[{stage}] {msg}  {extra}")


# ----------------------------------------------------------------------------------------------
# ALGORITHM 1 - prioritized job assignment
# ----------------------------------------------------------------------------------------------
def fitness(L: Layout, a: AGV, job: Job, prm: Params):
    """F_ji(vt_i, s_i) = ct_ji + lambda (et_ji + dt_ji)   [deck eq. (1), (2)]."""
    d_sp = L.delta_nn(a.s, job.p)
    d_pp = L.delta_nn(job.p, job.p_prime)
    ct = a.vt + d_sp + prm.eta + d_pp + prm.eta_p
    et = max(0.0, job.t - (a.vt + d_sp + prm.eta))
    dt = max(0.0, ct - job.t_prime)
    return dict(F=ct + prm.lam * (et + dt), ct=ct, et=et, dt=dt)


def _append_path(a: AGV, path, lu_time):
    assert path[0] == a.R[-1], "route must be contiguous"
    for n in path[1:]:
        a.R.append(n)
        a.dwell.append(0.0)
    a.dwell[-1] += lu_time          # loading / unloading happens at the last node of the path
    return len(a.R) - 1


def algorithm_1(L: Layout, jobs, agvs, prm: Params, log: Log):
    """Jobs are taken in order of desired pickup time t_j; each goes to the AGV with minimum F_ji."""
    for a in agvs:
        a.vt, a.s, a.R, a.dwell, a.events, a.jobs = 0.0, L.pi, [L.pi], [0.0], [], []
    estimate = {}
    for job in sorted(jobs, key=lambda x: (x.t, x.j)):                 # earliest pickup first
        cand = []
        for a in agvs:
            c = fitness(L, a, job, prm)
            cand.append((c["F"], a.priority, a, c))
        cand.sort(key=lambda x: (x[0], x[1]))                          # tie -> higher priority AGV
        F, _, a, c = cand[0]
        i1 = _append_path(a, L.r_nn[(a.s, job.p)], prm.eta)            # R_i <- R_i U r_{s_i p_j}
        a.events.append((i1, "pickup", job.j))
        i2 = _append_path(a, L.r_nn[(job.p, job.p_prime)], prm.eta_p)  #          U r_{p_j p'_j}
        a.events.append((i2, "delivery", job.j))
        a.vt, a.s = c["ct"], job.p_prime                               # vt_i* <- ct_ji*, s_i* <- p'_j
        a.jobs.append(job.j)
        estimate[job.j] = dict(agv=a.i, **c)
        log.add("A1", f"{job.j} -> {a.i}", F=round(F, 1), ct=round(c["ct"], 1),
                et=round(c["et"], 1), dt=round(c["dt"], 1),
                runner_up=f"{cand[1][2].i}:{cand[1][0]:.1f}" if len(cand) > 1 else "-")
    for a in agvs:                                                     # R_i <- R_i U r_{s_i pi}
        _append_path(a, L.r_nn[(a.s, L.pi)], 0.0)
    return estimate


# ----------------------------------------------------------------------------------------------
# ALGORITHM 3 - conflict elimination by sliding windows to the right
# ----------------------------------------------------------------------------------------------
def f(lt, rt, W, delta):
    """(st, mt) = f(lt, rt, W).
    st : smallest slide to the right that clears every fixed window of W (padded by delta),
    mt : largest slide (measured from the given position) before the next fixed window is hit
         (infinity if there is none).  With no conflict st = 0."""
    width, cur, moved = rt - lt, lt, True
    while moved:
        moved = False
        for w in W:
            a, b = w[0], w[1]
            if cur < b + delta - EPS and cur + width > a - delta + EPS:
                cur, moved = b + delta, True
    st = cur - lt
    nxt = INF
    for w in W:
        if w[0] - delta >= cur + width - EPS:
            nxt = min(nxt, w[0])
    return st, (INF if nxt == INF else nxt - delta - rt)


def algorithm_3(R, P, p, W, Wtrack, delta, pi, k_max, t_free=None, trace=None):
    """Make the windows of n_p (and everything before it, back to the previous parking station)
    conflict-free by sliding them right.  P is modified in place.  Returns (st_star, passes, fallback).
    pi may be one node or a set of exempt nodes (parking station + lift lobbies in the hybrid case)."""
    buf = {pi} if isinstance(pi, str) else pi
    q = max(m for m in range(p) if R[m] in buf)        # nearest previous parking station / lobby
    st_star, fallback, passes = 0.0, False, 0
    for k in range(1, k_max + 1):
        passes, mt_star, broke, m = k, INF, False, p
        while m > q:
            n = R[m]
            if n not in buf:                                         # node window of n_m
                st, mt = f(P[m][0] + st_star, P[m][1] + st_star, W.get(n, ()), delta)
                mt_star = min(st_star + mt, mt_star)
                if trace is not None:
                    trace.append((k, f"node n{m + 1}={n}", st, mt, st_star + st, mt_star))
                st_star += st
                if st_star > mt_star + EPS:
                    broke = True
                    break
            st, mt = f(P[m - 1][1] + st_star, P[m][0] + st_star, Wtrack(R[m - 1], R[m]), delta)
            mt_star = min(st_star + mt, mt_star)                     # edge window e(n_{m-1}, n_m)
            if trace is not None:
                trace.append((k, f"edge e(n{m},n{m + 1})", st, mt, st_star + st, mt_star))
            st_star += st
            if st_star > mt_star + EPS:
                broke = True
                break
            m -= 1
        if not broke:
            break
    else:                                                  # k_max exhausted -> worst case of the paper:
        fallback = True                                    # wait at pi until every higher-priority AGV is done
        st_star = max(st_star, (t_free if t_free is not None else 0.0) + delta - P[q][1])
    for m in range(q + 1, p + 1):                          # slide windows n_{q+1} ... n_p by st*
        P[m][0] += st_star
        P[m][1] += st_star
    P[q][1] += st_star                                     # extend the parking-station window by st*
    return st_star, passes, fallback


# ----------------------------------------------------------------------------------------------
# ALGORITHM 2 - prioritized conflict-free routing
# ----------------------------------------------------------------------------------------------
def _overlap(lt, rt, windows, delta):
    for w in windows:
        if lt < w[1] + delta - EPS and rt > w[0] - delta + EPS:
            return w
    return None


def plan_route(L: Layout, agv_id, R, dwell, t0, W, Wtrack, prm: Params, log: Log, calls,
               t_free=0.0, keep_trace=True):
    """Lines 5-23 of Algorithm 2 for ONE route R starting at time t0: build P_i node by node and call
    Algorithm 3 whenever a window conflicts with W / W'.  R[0] must be an exempt node (pi or a lobby)."""
    P = []
    for m, n in enumerate(R):
        lt = t0 if m == 0 else P[m - 1][1] + L.delta_edge(R[m - 1], n)
        P.append([lt, lt + dwell[m]])                          # rt_m = lt_m (+ eta or eta' at L/U nodes)
        for attempt in range(3):
            e_hit = _overlap(P[m - 1][1], P[m][0], Wtrack(R[m - 1], n), prm.delta) if m > 0 else None
            n_hit = _overlap(P[m][0], P[m][1], W.get(n, ()), prm.delta) if n not in L.exempt else None
            if e_hit is None and n_hit is None:
                break
            tr = [] if keep_trace else None
            st_star, passes, fb = algorithm_3(R, P, m, W, Wtrack, prm.delta, L.exempt,
                                              prm.k_max, t_free, tr)
            rec = dict(agv=agv_id, m=m + 1, node=n, kind="edge" if e_hit is not None else "node",
                       blocker=(e_hit or n_hit)[2], st_star=st_star, passes=passes,
                       fallback=fb, trace=tr)
            calls.append(rec)
            log.add("A3", f"{agv_id}: conflict at {'edge into' if e_hit else 'node'} n{m + 1}={n} "
                    f"(blocked by {(e_hit or n_hit)[2]})", passes=passes,
                    st_star=round(st_star, 2), fallback=fb)
        else:
            raise RuntimeError("Algorithm 3 did not remove the conflict (should be impossible)")
    return P


def freeze(L: Layout, agv_id, R, P, W, Wp):
    """Line 24 of Algorithm 2: add the windows of a planned route to W and W'."""
    for m, n in enumerate(R):
        if n not in L.exempt:
            W[n].append((P[m][0], P[m][1], agv_id))
        if m > 0:
            Wp[(R[m - 1], n)].append((P[m - 1][1], P[m][0], agv_id))


def algorithm_2(L: Layout, agvs, prm: Params, log: Log, keep_trace=True):
    W = defaultdict(list)       # W_n   : node -> [(lt, rt, agv)]
    Wp = defaultdict(list)      # W'_e  : directed edge (u, v) -> [(rt_{m-1}, lt_m, agv)]
    Wtrack = lambda u, v: Wp[(u, v)] + Wp[(v, u)]
    plans, calls = {}, []
    t_free = 0.0
    for a in sorted(agvs, key=lambda x: x.priority):           # V_1 first
        R = a.R
        P = plan_route(L, a.i, R, a.dwell, 0.0, W, Wtrack, prm, log, calls, t_free, keep_trace)
        plans[a.i] = Plan(a.i, list(R), P, list(a.dwell), list(a.events))
        freeze(L, a.i, R, P, W, Wp)
        t_free = max(t_free, P[-1][1])
        log.add("A2", f"{a.i} (priority {a.priority}) planned", end=round(P[-1][1], 1),
                nodes=len(R), jobs=len(a.jobs))
    return plans, calls


# ----------------------------------------------------------------------------------------------
# independent verification (does NOT reuse f / Algorithm 3)
# ----------------------------------------------------------------------------------------------
def verify(L: Layout, plans, agvs, jobs, prm: Params):
#     Every AGV starts at π at time 0 and ends at π.
# No node conflict: two different AGVs on the same node within δ. Parking and lobbies are exempt.
# No track conflict: two AGVs on one bidirectional track within δ, in either direction.
# No pause on an edge: each edge window is exactly the travel time. This is assumption 5.
# Each node window is exactly the dwell time (η or η′ at pickup/delivery, 0 elsewhere). Only π may be longer.
# Every job is served exactly once.
    """Return a list of violations (empty list = every assumption of the paper holds)."""
    bad, d = [], prm.delta
    node_w, track_w = defaultdict(list), defaultdict(list)
    for a in agvs:
        pl = plans[a.i]
        if pl.R[0] != L.pi or pl.R[-1] != L.pi or abs(pl.P[0][0]) > 1e-6:
            bad.append(f"{a.i}: must start at time 0 at pi and end at pi")
        for m, n in enumerate(pl.R):
            lt, rt = pl.P[m]
            if n not in L.exempt and abs((rt - lt) - pl.dwell[m]) > 1e-6:
                bad.append(f"{a.i}: node window n{m + 1}={n} length {rt - lt:.3f} != dwell {pl.dwell[m]}")
            if n in L.exempt and rt - lt < pl.dwell[m] - 1e-6:
                bad.append(f"{a.i}: parking/lobby window too short")
            if n not in L.exempt:
                node_w[n].append((lt, rt, a.i))
            if m > 0:
                e0, e1 = pl.edge_window(m)
                if abs((e1 - e0) - L.delta_edge(pl.R[m - 1], n)) > 1e-6:
                    bad.append(f"{a.i}: AGV pauses on edge e(n{m},n{m + 1})")
                track_w[frozenset((pl.R[m - 1], n))].append((e0, e1, a.i))
    for kind, table in (("node", node_w), ("track", track_w)):
        for key, ws in table.items():
            ws.sort()
            for x in range(len(ws)):
                for y in range(x + 1, len(ws)):
                    if ws[y][0] >= ws[x][1] + d - EPS:
                        break
                    if ws[x][2] != ws[y][2] and ws[y][0] < ws[x][1] + d - EPS and ws[y][1] > ws[x][0] - d + EPS:
                        bad.append(f"{kind} conflict {sorted(key) if kind == 'track' else key}: "
                                   f"{ws[x][2]} {ws[x][:2]} vs {ws[y][2]} {ws[y][:2]}")
    served = sorted(j for a in agvs for j in a.jobs)
    if served != sorted(j.j for j in jobs):
        bad.append("some job is not served exactly once")
    return bad


# ----------------------------------------------------------------------------------------------
# results: activity segments, final job times, metrics
# ----------------------------------------------------------------------------------------------
def plan_segments(L: Layout, pl: Plan):
    """Decompose a plan into activities: ('wait'|'travel'|'lift'|'pickup'|'delivery', t0, t1, info)."""
    segs, ev_at = [], defaultdict(list)
    for (idx, kind, jid) in pl.events:
        ev_at[idx].append((kind, jid))
    for m, n in enumerate(pl.R):
        lt, rt = pl.P[m]
        if m > 0:
            e0, e1 = pl.edge_window(m)
            segs.append(("lift" if L.is_lift(pl.R[m - 1], n) else "travel", e0, e1, f"{pl.R[m - 1]}->{n}"))
        t = lt
        for kind, jid in ev_at.get(m, []):
            dur = pl.dwell[m] / max(1, len(ev_at[m]))
            segs.append((kind, t, t + dur, f"{jid}@{n}"))
            t += dur
        if n in L.exempt and rt - t > 1e-9 and m < len(pl.R) - 1:  # slide of Algorithm 3 = waiting at pi / lobby
            segs.append(("wait", t, rt, f"wait at {n}"))
    return segs


def final_job_times(plans, agvs, prm: Params):
    """Actual pickup-completion / delivery-completion times in the conflict-free plans."""
    out = {}
    for a in agvs:
        pl = plans[a.i]
        at = defaultdict(list)
        for idx, kind, jid in pl.events:
            at[idx].append((kind, jid))
        for idx, evs in at.items():
            t = pl.P[idx][0]
            for kind, jid in evs:
                t += pl.dwell[idx] / len(evs)
                out.setdefault(jid, {"agv": a.i})["pickup_done" if kind == "pickup" else "delivery_done"] = t
    return out


def metrics(L: Layout, plans, agvs, jobs, estimate, calls, prm: Params):
    jd = {j.j: j for j in jobs}
    fin = final_job_times(plans, agvs, prm)
    et_f = dt_f = et_e = dt_e = 0.0
    for jid, v in fin.items():
        et_f += max(0.0, jd[jid].t - v["pickup_done"])
        dt_f += max(0.0, v["delivery_done"] - jd[jid].t_prime)
        et_e += estimate[jid]["et"]
        dt_e += estimate[jid]["dt"]
    usage = {a.i: (plans[a.i].end_time if a.jobs else 0.0) for a in agvs}
    wait = {a.i: sum(s[2] - s[1] for s in plan_segments(L, plans[a.i]) if s[0] == "wait") for a in agvs}
    busy = {a.i: sum(s[2] - s[1] for s in plan_segments(L, plans[a.i]) if s[0] != "wait") for a in agvs}
    shifts = [c["st_star"] for c in calls]
    return dict(
        makespan_last_delivery=max(v["delivery_done"] for v in fin.values()),
        fleet_back_at_parking=max(usage.values()),
        load_imbalance=max(usage.values()) - min(usage.values()),
        earliness_final=et_f, tardiness_final=dt_f, earliness_estimate=et_e, tardiness_estimate=dt_e,
        alg3_calls=len(calls), alg3_total_shift=sum(shifts), alg3_max_shift=max(shifts, default=0.0),
        alg3_fallbacks=sum(c["fallback"] for c in calls),
        usage=usage, waiting_at_parking=wait, busy_time=busy,
        jobs_per_agv={a.i: len(a.jobs) for a in agvs},
        lift_crossings=sum(1 for a in agvs for m in range(1, len(plans[a.i].R))
                           if L.is_lift(plans[a.i].R[m - 1], plans[a.i].R[m])),
    )


def run_pipeline(L: Layout, jobs, agvs, prm: Params, log: Log):
    """Algorithm 1 -> Algorithm 2 (calls Algorithm 3) -> independent verification."""
    t0 = time.perf_counter()
    estimate = algorithm_1(L, jobs, agvs, prm, log)
    t1 = time.perf_counter()
    plans, calls = algorithm_2(L, agvs, prm, log)
    t2 = time.perf_counter()
    violations = verify(L, plans, agvs, jobs, prm)
    return dict(estimate=estimate, plans=plans, calls=calls, violations=violations,
                t_alg1=t1 - t0, t_alg2=t2 - t1)


# ----------------------------------------------------------------------------------------------
# self-test: the numerical example of the deck / paper (Section III-B)
# ----------------------------------------------------------------------------------------------
def paper_example():
    R, P = ["n1", "n2"], [[0.0, 6.0], [10.0, 14.0]]       # n1 = parking station, delta = 2
    W = {"n2": [(8, 12), (22, 26), (50, 54)]}
    Wtrack = lambda u, v: [(10, 14), (30, 34)]            # W'_{e(n2,n1)}
    tr = []
    st_star, passes, _ = algorithm_3(R, P, 1, W, Wtrack, 2.0, "n1", 100, None, tr)
    return P, st_star, passes, tr


if __name__ == "__main__":
    P, st_star, passes, tr = paper_example()
    print("paper example  ->  P_i =", P, " st* =", st_star, " passes =", passes)
    for row in tr:
        print("   pass %d  %-14s st=%-4g mt=%-4g st*=%-4g mt*=%g" % row)
    assert P == [[0.0, 24.0], [28.0, 32.0]] and st_star == 18.0 and passes == 2
    print("OK: matches the deck (P_i = {[0,24],[28,32]}, st* = 18)")
