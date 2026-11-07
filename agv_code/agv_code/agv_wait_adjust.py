"""Prioritized wait-adjustment routing with safe-interval checks.

Each AGV keeps the route and job assignment produced by Algorithm 1. AGVs are
then scheduled by priority. A route search inserts waits at route nodes whenever
the node or the next track is reserved by a higher-priority AGV.
"""
from __future__ import annotations

import time
from collections import defaultdict

from agv_core import Plan, algorithm_1, verify


def _overlaps(start, end, windows, delta):
    for a, b, aid in windows:
        if start < b + delta - 1e-9 and end > a - delta + 1e-9:
            return a, b, aid
    return None


def _schedule_route(L, route, dwell, prm, node_windows, edge_windows):
    """Depth-first safe-interval search over departure times on a fixed route."""
    n = len(route)
    starts, ends = [0.0] * n, [0.0] * n
    expansions = 0

    def search(m, arrival):
        nonlocal expansions
        expansions += 1
        if expansions > 200000:
            return False
        starts[m] = arrival
        minimum = arrival + dwell[m]
        if m == n - 1:
            ends[m] = minimum
            return True

        u, v = route[m], route[m + 1]
        travel = L.delta_edge(u, v)
        track = edge_windows[frozenset((u, v))]
        # Candidate departure boundaries are the ends of blocked safe intervals.
        candidates = {minimum}
        for a, b, _ in track:
            candidates.add(max(minimum, b + prm.delta))
        if v not in L.exempt:
            for a, b, _ in node_windows[v]:
                candidates.add(max(minimum, b + prm.delta - travel))
        candidates = sorted(candidates)
        # New reservations can create a chain of later safe intervals. Expand
        # boundaries lazily until a feasible continuation is found.
        seen = set()
        while candidates:
            depart = candidates.pop(0)
            key = round(depart, 9)
            if key in seen:
                continue
            seen.add(key)
            if u not in L.exempt:
                block = _overlaps(arrival, depart, node_windows[u], prm.delta)
                if block is not None:
                    continue
            if _overlaps(depart, depart + travel, track, prm.delta) is not None:
                continue
            starts[m + 1] = depart + travel
            if v not in L.exempt and _overlaps(starts[m + 1], starts[m + 1] + dwell[m + 1],
                                                node_windows[v], prm.delta) is not None:
                # This interval is not safe at v; departure at the end of that
                # reservation may be a later candidate for the current node.
                blockers = [b + prm.delta - travel for a, b, _ in node_windows[v]
                            if a - prm.delta < starts[m + 1] + dwell[m + 1]
                            and b + prm.delta > starts[m + 1]]
                for t in blockers:
                    if t > depart + 1e-9 and round(t, 9) not in seen:
                        candidates.append(t)
                candidates.sort()
                continue
            ends[m] = depart
            if search(m + 1, depart + travel):
                return True
            ends[m] = 0.0
        return False

    if not search(0, 0.0):
        raise RuntimeError(f"wait-adjustment safe-interval search failed for route {route}")
    return [[starts[m], ends[m]] for m in range(n)]


def run_wait_adjustment(L, jobs, agvs, prm, log):
    """Run Algorithm 1 assignment followed by priority-ordered safe-interval routing."""
    cpu_start = time.perf_counter()
    estimate = algorithm_1(L, jobs, agvs, prm, log)
    t_assign = time.perf_counter()
    node_windows = defaultdict(list)
    edge_windows = defaultdict(list)
    plans, calls = {}, []

    for agv in sorted(agvs, key=lambda a: a.priority):
        route = list(agv.R)
        windows = _schedule_route(L, route, agv.dwell, prm, node_windows, edge_windows)
        plan = Plan(agv.i, route, windows, list(agv.dwell), list(agv.events))
        plans[agv.i] = plan
        for m, node in enumerate(route):
            if node not in L.exempt:
                node_windows[node].append((windows[m][0], windows[m][1], agv.i))
            if m:
                edge_windows[frozenset((route[m - 1], node))].append(
                    (windows[m - 1][1], windows[m][0], agv.i))
        log.add("WA", f"{agv.i} scheduled with safe intervals", end=round(plan.end_time, 1),
                nodes=len(route))

    violations = verify(L, plans, agvs, jobs, prm)
    if violations:
        raise RuntimeError(f"wait-adjustment plan failed verification: {violations[0]}")
    t_done = time.perf_counter()
    return dict(estimate=estimate, plans=plans, calls=calls, violations=violations,
                t_alg1=t_assign - cpu_start, t_alg2=t_done - t_assign,
                servers={"central": dict(cpu=t_done - cpu_start,
                                          windows=sum(len(p.R) * 2 - 1 for p in plans.values()))})
