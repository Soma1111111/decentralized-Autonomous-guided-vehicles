"""Negative tests for the independent schedule verifier."""
from __future__ import annotations

import unittest
from copy import deepcopy

from agv_core import AGV, Job, Log, Params, Plan, run_pipeline, verify
from agv_hybrid import run_hybrid
from agv_layouts import build_single_floor, build_three_floors


class VerifyNegativeTests(unittest.TestCase):
    def single_floor_plan(self):
        layout = build_single_floor()
        prm = Params(eta=2.0, eta_p=3.0, delta=1.0)
        jobs = [Job("J1", "B", 0.0, "I", 100.0)]
        agvs = [AGV("AGV-01", 1), AGV("AGV-02", 2)]
        result = run_pipeline(layout, jobs, agvs, prm, Log())
        self.assertEqual(result["violations"], [])
        return layout, prm, jobs, agvs, result["plans"]

    def test_wrong_pickup_station_is_reported(self):
        layout, prm, jobs, agvs, plans = self.single_floor_plan()
        pl = plans["AGV-01"]
        idx = next(i for i, kind, jid in pl.events if kind == "pickup" and jid == "J1")
        pl.R[idx] = "A"
        self.assertTrue(any("pickup is not at its station" in x for x in verify(layout, plans, agvs, jobs, prm)))

    def test_wrong_delivery_station_is_reported(self):
        layout, prm, jobs, agvs, plans = self.single_floor_plan()
        pl = plans["AGV-01"]
        idx = next(i for i, kind, jid in pl.events if kind == "delivery" and jid == "J1")
        pl.R[idx] = "A"
        self.assertTrue(any("delivery is not at its station" in x for x in verify(layout, plans, agvs, jobs, prm)))

    def test_pickup_after_delivery_is_reported(self):
        layout, prm, jobs, agvs, plans = self.single_floor_plan()
        pl = plans["AGV-01"]
        events = list(pl.events)
        p = next(k for k, e in enumerate(events) if e[1:] == ("pickup", "J1"))
        d = next(k for k, e in enumerate(events) if e[1:] == ("delivery", "J1"))
        ip, _, jid = events[p]
        idel, _, _ = events[d]
        pl.events[p] = (idel, "pickup", jid)
        pl.events[d] = (ip, "delivery", jid)
        self.assertTrue(any("pickup must precede delivery" in x for x in verify(layout, plans, agvs, jobs, prm)))

    def test_service_dwell_shortfall_is_reported(self):
        layout, prm, jobs, agvs, plans = self.single_floor_plan()
        pl = plans["AGV-01"]
        idx = next(i for i, kind, jid in pl.events if kind == "pickup" and jid == "J1")
        pl.dwell[idx] = 0.0
        self.assertTrue(any("dwell at" in x and "shorter than job service" in x
                            for x in verify(layout, plans, agvs, jobs, prm)))

    def test_event_on_unassigned_agv_is_reported(self):
        layout, prm, jobs, agvs, plans = self.single_floor_plan()
        agvs[0].jobs.clear()
        agvs[1].jobs.append("J1")
        self.assertTrue(any("event is not on the assigned AGV" in x
                            for x in verify(layout, plans, agvs, jobs, prm)))

    def test_overlapping_lift_bookings_are_reported(self):
        layout = build_three_floors(lobbies=True)
        layout.exempt = {layout.pi} | layout.lobbies
        prm = Params(eta=1.0, eta_p=1.0, delta=1.0)
        jobs = [Job("J1", "1C", 0.0, "2E", 1000.0)]
        a1 = AGV("AGV-01", 1)
        result = run_hybrid(layout, jobs, [a1], prm, Log(), order="fcfs")
        self.assertEqual(result["violations"], [])
        p2 = deepcopy(result["plans"][a1.i])
        a2 = AGV("AGV-02", 2, R=list(p2.R))
        p2.i = a2.i
        plans = dict(result["plans"], **{a2.i: p2})
        self.assertTrue(any("lift capacity conflict" in x for x in verify(layout, plans, [a1, a2], jobs, prm)))

    def test_broken_floor_leg_joint_is_reported(self):
        layout = build_three_floors(lobbies=True)
        layout.exempt = {layout.pi} | layout.lobbies
        prm = Params(eta=1.0, eta_p=1.0, delta=1.0)
        jobs = [Job("J1", "1C", 0.0, "2E", 1000.0)]
        agv = AGV("AGV-01", 1)
        result = run_hybrid(layout, jobs, [agv], prm, Log(), order="fcfs")
        pl = result["plans"][agv.i]
        m = next(i for i in range(1, len(pl.R)) if layout.is_lift(pl.R[i - 1], pl.R[i]))
        replacement = next(n for n in layout.G if n not in (pl.R[m - 1], pl.R[m])
                           and not layout.G.has_edge(pl.R[m - 1], n))
        pl.R[m] = replacement
        agv.R = list(pl.R)
        self.assertTrue(any("route discontinuity" in x and "floor-leg joint" in x
                            for x in verify(layout, result["plans"], [agv], jobs, prm)))


if __name__ == "__main__":
    unittest.main()
