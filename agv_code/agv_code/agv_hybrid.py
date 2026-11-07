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

Centralized FCFS ablation
  single_server=True : same lift booking, route-leg heap, and FCFS order as the hybrid planner, but
                       one global route planner holds node/track windows for every floor (B2).

Requires a layout built with lobbies=True and Layout.exempt = {pi} | lobbies.
"""
from __future__ import annotations

import heapq
import time
from collections import defaultdict

from agv_core import (LobbyEntryCapacityError, Log, Params, Plan, algorithm_1,
                      capacity_slide, f, freeze, plan_route, verify)


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
        # floor=None is the centralized B2 ablation: one planner holds the
        # reservation windows for route legs on every floor.
        self.L, self.floor, self.prm, self.log = L, floor, prm, log
        self.W, self.Wp = defaultdict(list), defaultdict(list)     # W_n, W'_e of this floor only
        self.Wcap = {n: [] for n in L.lobbies if floor is None or L.floor(n) == floor}
        self.calls, self.cpu, self.legs = [], 0.0, 0
        self.t_free = 0.0                                           # end of the latest frozen window

    def plan_leg(self, agv_id, R, dwell, t0, t_free=None, terminal_departure=None):
        tic = time.perf_counter()
        if self.floor is not None:
            assert all(self.L.floor(n) == self.floor for n in R), "leg leaves the floor"
        assert R[0] in self.L.exempt, "a leg must start at pi or at a lobby"
        W = _OthersOnly(self.W, agv_id)
        Wcap = {n: [w for w in ws if w[2] != agv_id] for n, ws in self.Wcap.items()}
        if self.prm.track_rule == "strict":
            Wtrack = lambda u, v: [w for w in self.Wp[(u, v)] + self.Wp[(v, u)] if w[2] != agv_id]
        else:
            Wtrack = lambda u, v: [w for w in self.Wp[(v, u)] if w[2] != agv_id]
        requested_t0 = t0
        for _ in range(self.prm.k_max):
            P = plan_route(self.L, agv_id, R, dwell, t0, W, Wtrack, self.prm, self.log, self.calls,
                           self.t_free if t_free is None else t_free, Wcap=Wcap)
            if terminal_departure is None or R[-1] not in Wcap or self.L.lobby_capacity is None:
                break
            dep = terminal_departure(P[-1][1])
            delay = capacity_slide(P[-1][0], dep, Wcap[R[-1]], self.L.lobby_capacity)
            if delay <= 1e-6:
                break
            if R[0] != self.L.pi:
                raise LobbyEntryCapacityError(delay)
            t0 += delay
        else:
            raise RuntimeError("lobby admission search exceeded its iteration limit")
        if R[0] == self.L.pi and t0 > requested_t0:
            P[0][0] = requested_t0
            P[0][1] += t0 - requested_t0
        freeze(self.L, agv_id, R, P, self.W, self.Wp, self.Wcap)
        self.t_free = max(self.t_free, P[-1][1])
        self.legs += 1
        self.cpu += time.perf_counter() - tic
        return P

    def extend_lobby(self, agv_id, lobby, start, end):
        """Update a terminal lobby reservation when its lift departure is booked later."""
        for idx in range(len(self.Wcap.get(lobby, ())) - 1, -1, -1):
            lt, _, aid = self.Wcap[lobby][idx]
            if aid == agv_id and abs(lt - start) < 1e-6:
                self.Wcap[lobby][idx] = (start, end, agv_id)
                return
        self.Wcap[lobby].append((start, end, agv_id))

    @property
    def windows_held(self):
        return sum(map(len, self.W.values())) + sum(map(len, self.Wp.values()))


class CentralServer:
    def __init__(self, L, prm: Params, log: Log):
        self.L, self.prm, self.log = L, prm, log
        self.lift = defaultdict(list)                  # lift track -> [(depart, arrive, agv)]
        self.bookings = {}
        self.cpu, self.messages, self.payload = 0.0, 0, 0

    def peek_lift(self, agv_id, u, v, ready):
        dur = self.L.delta_edge(u, v)
        key = frozenset((u, v))
        others = [w for w in self.lift[key] if w[2] != agv_id]
        st, _ = f(ready, ready + dur, others, self.prm.delta)
        return ready + st

    def book_lift(self, agv_id, u, v, ready, token=None):
        """Earliest departure >= ready at which lift track u-v is free (padded by delta)."""
        dur = self.L.delta_edge(u, v)
        key = frozenset((u, v))
        dep = self.peek_lift(agv_id, u, v, ready)
        st = dep - ready
        self.lift[key].append((dep, dep + dur, agv_id, token))
        if token is not None:
            self.bookings[token] = (agv_id, u, v, dep, dur)
        if st > 0:
            self.log.add("LIFT", f"{agv_id}: lift {u}->{v} busy, waits {st:.1f} s in lobby {u}", depart=round(dep, 1))
        return dep

    def delay_lift(self, token, delay):
        """Move a previously booked trip later after its destination lobby rejects admission."""
        agv_id, u, v, dep, _ = self.bookings[token]
        key = frozenset((u, v))
        self.lift[key] = [w for w in self.lift[key] if w[3] != token]
        del self.bookings[token]
        return self.book_lift(agv_id, u, v, dep + delay, token)

    @property
    def windows_held(self):
        return sum(map(len, self.lift.values()))


def _run_capacity_serial(L, jobs, agvs, prm, log, rotate_priority_rounds=False):
    """Safe capacity fallback: finish one AGV tour before admitting the next from pi."""
    central = CentralServer(L, prm, log)
    tic = time.perf_counter()
    estimate = algorithm_1(L, jobs, agvs, prm, log,
                           rotate_priority_rounds=rotate_priority_rounds)
    t_alg1 = time.perf_counter() - tic
    central.cpu += t_alg1
    floor_ids = sorted({L.floor(n) for n in L.G})
    floors = {fl: FloorServer(L, fl, prm, log) for fl in floor_ids}
    plans, calls = {}, []
    clock = 0.0
    for a in sorted(agvs, key=lambda x: (x.priority, x.i)):
        P_all = [None] * len(a.R)
        legs = split_legs(L, a.R)
        for k, (s, e) in enumerate(legs):
            tic = time.perf_counter()
            R_leg, dwell = a.R[s:e + 1], a.dwell[s:e + 1]
            floor = L.floor(R_leg[0])
            fs = floors[floor]
            tic2 = time.perf_counter()
            P_leg = fs.plan_leg(a.i, R_leg, dwell, clock if k == 0 else release,
                                terminal_departure=(lambda ready, u=a.R[e], v=a.R[e + 1]:
                                    central.peek_lift(a.i, u, v, ready))
                                if k + 1 < len(legs) else None)
            central.cpu += time.perf_counter() - tic2
            if k == 0 and clock > 0:
                P_leg[0][0] = 0.0
            P_all[s:e + 1] = P_leg
            if k + 1 < len(legs):
                u, v = a.R[e], a.R[e + 1]
                dep = central.book_lift(a.i, u, v, P_leg[-1][1])
                P_leg[-1][1] = dep
                fs.extend_lobby(a.i, u, P_leg[-1][0], dep)
                release = dep + L.delta_edge(u, v)
            else:
                clock = P_leg[-1][1]
        plans[a.i] = Plan(a.i, list(a.R), P_all, list(a.dwell), list(a.events))
        log.add("HY", f"{a.i} (priority {a.priority}) serialized for lobby capacity",
                end=round(plans[a.i].end_time, 1), legs=len(legs), jobs=len(a.jobs))
    calls = [c for fs in floors.values() for c in fs.calls]
    violations = verify(L, plans, agvs, jobs, prm)
    if violations:
        raise RuntimeError(f"capacity-safe serialized plan failed verification: {violations[0]}")
    servers = {"central": dict(cpu=central.cpu, windows=central.windows_held)}
    servers.update({f"floor{fl}": dict(cpu=fs.cpu, windows=fs.windows_held, legs=fs.legs)
                    for fl, fs in floors.items()})
    return dict(estimate=estimate, plans=plans, calls=calls, violations=violations,
                t_alg1=t_alg1, t_alg2=sum(s["cpu"] for s in servers.values()) - t_alg1,
                servers=servers, messages=central.messages, payload=central.payload,
                n_legs=sum(len(split_legs(L, a.R)) for a in agvs),
                capacity_fallback="serialized tours")


def run_hybrid(L, jobs, agvs, prm: Params, log: Log, order="fcfs", single_server=False,
               rotate_priority_rounds=False):
    """Run FCFS/priority legs using floor-local or single-global route reservations.

    single_server=True keeps the same leg heap and central lift reservations,
    but one planner holds all node/track windows (centralized B2 ablation).
    With a finite lobby capacity, tours are admitted one at a time in FCFS
    release/priority order; other AGVs wait at pi to prevent lobby deadlock.
    """
    assert L.lobbies and L.lobbies <= L.exempt, "build the layout with lobbies=True and make them exempt"
    if L.lobby_capacity is not None and not single_server:
        return _run_capacity_serial(L, jobs, agvs, prm, log, rotate_priority_rounds)
    central = CentralServer(L, prm, log)
    tic = time.perf_counter()
    estimate = algorithm_1(L, jobs, agvs, prm, log,
                           rotate_priority_rounds=rotate_priority_rounds)
    t_alg1 = time.perf_counter() - tic
    central.cpu += t_alg1
    floor_ids = sorted({L.floor(n) for n in L.G})
    if single_server:
        floors = {"global": FloorServer(L, None, prm, log)}
        floor_server = lambda _fl: floors["global"]
        floor_free = {fl: 0.0 for fl in floor_ids}
    else:
        floors = {fl: FloorServer(L, fl, prm, log) for fl in floor_ids}
        floor_server = lambda fl: floors[fl]
        floor_free = None

    tic = time.perf_counter()
    legs = {a.i: split_legs(L, a.R) for a in agvs}
    P_all = {a.i: [None] * len(a.R) for a in agvs}
    heap = []
    ticket_info = {}

    def push(a, k, release, ticket=None):
        key = (release, a.priority, k) if order == "fcfs" else (a.priority, k, release)
        heapq.heappush(heap, (key, a.i, k, release, ticket))

    by_id = {a.i: a for a in agvs}
    for a in agvs:
        push(a, 0, 0.0)
    central.cpu += time.perf_counter() - tic

    while heap:
        tic = time.perf_counter()
        _, aid, k, release, ticket = heapq.heappop(heap)
        a = by_id[aid]
        s, e = legs[aid][k]
        R_leg, dwell = a.R[s:e + 1], a.dwell[s:e + 1]
        route_floor = L.floor(R_leg[0])
        fs = floor_server(route_floor)
        central.messages += 1                                        # central -> floor: plan this leg
        central.payload += len(R_leg)
        central.cpu += time.perf_counter() - tic

        try:
            P_leg = fs.plan_leg(aid, R_leg, dwell, release,
                                t_free=floor_free[route_floor] if single_server else None,
                                terminal_departure=(lambda ready, u=a.R[e], v=a.R[e + 1]:
                                    central.peek_lift(aid, u, v, ready))
                                if k + 1 < len(legs[aid]) else None)
        except LobbyEntryCapacityError as exc:
            if ticket is None:
                push(a, k, release + exc.delay)
            else:
                new_dep = central.delay_lift(ticket, exc.delay)
                src_fs, src_lobby, src_start, src_idx = ticket_info[ticket]
                P_all[aid][src_idx][1] = new_dep
                cap_windows = [w for w in src_fs.Wcap[src_lobby] if w[2] != aid]
                if L.lobby_capacity is not None and capacity_slide(
                        src_start, new_dep, cap_windows, L.lobby_capacity) > 1e-6:
                    raise RuntimeError(f"lobby {src_lobby} would exceed capacity while {aid} waits for a lift")
                src_fs.extend_lobby(aid, src_lobby, src_start, new_dep)
                _, _, _, _, travel = central.bookings[ticket]
                push(a, k, new_dep + travel, ticket)
            continue
        if single_server:
            floor_free[route_floor] = max(floor_free[route_floor], P_leg[-1][1])

        tic = time.perf_counter()
        central.messages += 1                                        # floor -> central: windows of the leg
        central.payload += len(P_leg)
        P_all[aid][s:e + 1] = P_leg
        if k + 1 < len(legs[aid]):                                   # next leg starts after the lift
            u, v = a.R[e], a.R[e + 1]
            ticket = f"{aid}:{e}"
            dep = central.book_lift(aid, u, v, ready=P_leg[-1][1], token=ticket)
            P_all[aid][e][1] = dep                                   # wait in the departure lobby
            end_lobby = u
            lobby_start = P_leg[-1][0]
            other_windows = [w for w in fs.Wcap[end_lobby] if w[2] != aid]
            if L.lobby_capacity is not None and capacity_slide(
                    lobby_start, dep, other_windows, L.lobby_capacity) > 1e-6:
                raise RuntimeError(f"lobby {end_lobby} would exceed capacity before lift departure")
            fs.extend_lobby(aid, end_lobby, lobby_start, dep)
            ticket_info[ticket] = (fs, end_lobby, lobby_start, e)
            push(a, k + 1, dep + L.delta_edge(u, v), ticket)
        central.cpu += time.perf_counter() - tic

    plans = {a.i: Plan(a.i, list(a.R), P_all[a.i], list(a.dwell), list(a.events)) for a in agvs}
    for a in agvs:
        log.add("HY", f"{a.i} (priority {a.priority}) planned", end=round(plans[a.i].end_time, 1),
                legs=len(legs[a.i]), jobs=len(a.jobs))
    calls = [c for fs in floors.values() for c in fs.calls]
    violations = verify(L, plans, agvs, jobs, prm)
    if L.lobby_capacity is not None and violations:
        raise RuntimeError(f"capacity-constrained hybrid plan failed verification: {violations[0]}")
    servers = {"central": dict(cpu=central.cpu, windows=central.windows_held)}
    if single_server:
        fs = floors["global"]
        servers["global"] = dict(cpu=fs.cpu, windows=fs.windows_held, legs=fs.legs)
    else:
        servers.update({f"floor{fl}": dict(cpu=fs.cpu, windows=fs.windows_held, legs=fs.legs)
                        for fl, fs in floors.items()})
    return dict(estimate=estimate, plans=plans, calls=calls, violations=violations,
                t_alg1=t_alg1, t_alg2=sum(s["cpu"] for s in servers.values()) - t_alg1,
                servers=servers, messages=central.messages, payload=central.payload,
                n_legs=sum(len(v) for v in legs.values()))
