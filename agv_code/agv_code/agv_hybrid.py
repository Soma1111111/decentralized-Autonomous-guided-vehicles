"""
agv_hybrid.py - HYBRID architecture: one central server + one edge server per floor
====================================================================================
The centralized planner (agv_core.run_pipeline) plans every node, track and lift of the factory on one
server.  Here the same work is split:

CENTRAL SERVER  (whole factory, coarse view)
  * runs Algorithm 1 (job assignment) exactly as before -> routes R_i
  * cuts every R_i into floor LEGS at the lift links
  * owns the lifts: books each lift trip so that two AGVs never use one lift track within delta
  * sends each leg to the server of its floor, receives the planned windows back
  * merges the legs into the final plans P_i and runs the independent verifier

FLOOR (EDGE) SERVER  (one floor, detailed view)
  * keeps W_n / W'_e of its own floor only
  * plans a leg with Algorithms 2 + 3 (agv_core.plan_route) starting at the leg's entry node
  * an AGV that must wait waits at the leg's entry: the parking station or the lift LOBBY of this floor
    (instead of waiting only at pi as in the paper) -> Algorithm 3 never slides a plan across floors

Order in which legs are planned
  order="fcfs"     : legs are planned in the order their AGV reaches the floor (earliest release first,
                     ties -> AGV priority).  Each floor serves AGVs first-come-first-served.
  order="priority" : all legs of V_1, then all legs of V_2, ...  This gives exactly the plans of the
                     centralized planner with the same lobbies (used as a correctness check).

Requires a layout built with lobbies=True and Layout.exempt = {pi} | lobbies.
"""
from __future__ import annotations

import heapq
import time
from collections import defaultdict

from agv_core import Log, Params, Plan, algorithm_1, f, freeze, plan_route, verify


class _OthersOnly:
    """W_n seen by one AGV: its own (earlier) legs are not obstacles for itself."""

    def __init__(self, W, agv_id):
        self.W, self.agv_id = W, agv_id

    def get(self, n, default=()):
        return [w for w in self.W.get(n, default) if w[2] != self.agv_id]


def split_legs(L, R):
    """Index ranges [s, e] of R that stay on one floor; consecutive legs are joined by one lift link."""
    legs, s = [], 0
    for m in range(1, len(R)):
        if L.is_lift(R[m - 1], R[m]):
            legs.append((s, m - 1))
            s = m
    legs.append((s, len(R) - 1))
    return legs


class FloorServer:
    def __init__(self, L, floor, prm: Params, log: Log):
        self.L, self.floor, self.prm, self.log = L, floor, prm, log
        self.W, self.Wp = defaultdict(list), defaultdict(list)     # W_n, W'_e of this floor only
        self.calls, self.cpu, self.legs = [], 0.0, 0
        self.t_free = 0.0                                           # end of the latest frozen window

    def plan_leg(self, agv_id, R, dwell, t0):
        tic = time.perf_counter()
        assert all(self.L.floor(n) == self.floor for n in R), "leg leaves the floor"
        assert R[0] in self.L.exempt, "a leg must start at pi or at a lobby"
        W = _OthersOnly(self.W, agv_id)
        Wtrack = lambda u, v: [w for w in self.Wp[(u, v)] + self.Wp[(v, u)] if w[2] != agv_id]
        P = plan_route(self.L, agv_id, R, dwell, t0, W, Wtrack, self.prm, self.log, self.calls, self.t_free)
        freeze(self.L, agv_id, R, P, self.W, self.Wp)
        self.t_free = max(self.t_free, P[-1][1])
        self.legs += 1
        self.cpu += time.perf_counter() - tic
        return P

    @property
    def windows_held(self):
        return sum(map(len, self.W.values())) + sum(map(len, self.Wp.values()))


class CentralServer:
    def __init__(self, L, prm: Params, log: Log):
        self.L, self.prm, self.log = L, prm, log
        self.lift = defaultdict(list)                  # lift track -> [(depart, arrive, agv)]
        self.cpu, self.messages, self.payload = 0.0, 0, 0

    def book_lift(self, agv_id, u, v, ready):
        """Earliest departure >= ready at which lift track u-v is free (padded by delta)."""
        dur = self.L.delta_edge(u, v)
        key = frozenset((u, v))
        others = [w for w in self.lift[key] if w[2] != agv_id]
        st, _ = f(ready, ready + dur, others, self.prm.delta)
        dep = ready + st
        self.lift[key].append((dep, dep + dur, agv_id))
        if st > 0:
            self.log.add("LIFT", f"{agv_id}: lift {u}->{v} busy, waits {st:.1f} s in lobby {u}", depart=round(dep, 1))
        return dep

    @property
    def windows_held(self):
        return sum(map(len, self.lift.values()))


def run_hybrid(L, jobs, agvs, prm: Params, log: Log, order="fcfs"):
    """Same inputs / outputs as agv_core.run_pipeline, plus per-server statistics."""
    assert L.lobbies and L.lobbies <= L.exempt, "build the layout with lobbies=True and make them exempt"
    central = CentralServer(L, prm, log)
    tic = time.perf_counter()
    estimate = algorithm_1(L, jobs, agvs, prm, log)
    t_alg1 = time.perf_counter() - tic
    central.cpu += t_alg1
    floors = {fl: FloorServer(L, fl, prm, log) for fl in sorted({L.floor(n) for n in L.G})}

    tic = time.perf_counter()
    legs = {a.i: split_legs(L, a.R) for a in agvs}
    P_all = {a.i: [None] * len(a.R) for a in agvs}
    heap = []

    def push(a, k, release):
        key = (release, a.priority, k) if order == "fcfs" else (a.priority, k, release)
        heapq.heappush(heap, (key, a.i, k, release))

    by_id = {a.i: a for a in agvs}
    for a in agvs:
        push(a, 0, 0.0)
    central.cpu += time.perf_counter() - tic

    while heap:
        tic = time.perf_counter()
        _, aid, k, release = heapq.heappop(heap)
        a = by_id[aid]
        s, e = legs[aid][k]
        R_leg, dwell = a.R[s:e + 1], a.dwell[s:e + 1]
        fs = floors[L.floor(R_leg[0])]
        central.messages += 1                                        # central -> floor: plan this leg
        central.payload += len(R_leg)
        central.cpu += time.perf_counter() - tic

        P_leg = fs.plan_leg(aid, R_leg, dwell, release)

        tic = time.perf_counter()
        central.messages += 1                                        # floor -> central: windows of the leg
        central.payload += len(P_leg)
        P_all[aid][s:e + 1] = P_leg
        if k + 1 < len(legs[aid]):                                   # next leg starts after the lift
            u, v = a.R[e], a.R[e + 1]
            dep = central.book_lift(aid, u, v, ready=P_leg[-1][1])
            P_all[aid][e][1] = dep                                   # wait in the departure lobby
            push(a, k + 1, dep + L.delta_edge(u, v))
        central.cpu += time.perf_counter() - tic

    plans = {a.i: Plan(a.i, list(a.R), P_all[a.i], list(a.dwell), list(a.events)) for a in agvs}
    for a in agvs:
        log.add("HY", f"{a.i} (priority {a.priority}) planned", end=round(plans[a.i].end_time, 1),
                legs=len(legs[a.i]), jobs=len(a.jobs))
    calls = [c for fs in floors.values() for c in fs.calls]
    violations = verify(L, plans, agvs, jobs, prm)
    servers = {"central": dict(cpu=central.cpu, windows=central.windows_held)}
    servers.update({f"floor{fl}": dict(cpu=fs.cpu, windows=fs.windows_held, legs=fs.legs) for fl, fs in floors.items()})
    return dict(estimate=estimate, plans=plans, calls=calls, violations=violations,
                t_alg1=t_alg1, t_alg2=sum(s["cpu"] for s in servers.values()) - t_alg1,
                servers=servers, messages=central.messages, payload=central.payload,
                n_legs=sum(len(v) for v in legs.values()))
