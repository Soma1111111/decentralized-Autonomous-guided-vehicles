"""Lobby occupancy verification tests."""
import unittest

import networkx as nx

from agv_core import AGV, Job, Layout, Log, Params, Plan, verify
from agv_hybrid import run_hybrid
from agv_layouts import build_three_floors


class LobbyCapacityTests(unittest.TestCase):
    def test_verifier_rejects_overfull_lobby(self):
        graph = nx.Graph()
        graph.add_node("P", floor=1)
        graph.add_node("L", floor=1, lobby=True)
        graph.add_edge("P", "L", length=1.0, kind="floor")
        layout = Layout(graph, "P", lobby_capacity=1)
        prm = Params(delta=0.0)
        agvs = [AGV("A1", 1), AGV("A2", 2)]
        windows = (
            [[0.0, 0.0], [1.0, 5.0], [6.0, 6.0]],
            [[0.0, 1.0], [2.0, 5.0], [6.0, 6.0]],
        )
        plans = {}
        for agv, P in zip(agvs, windows):
            agv.R = ["P", "L", "P"]
            plans[agv.i] = Plan(agv.i, list(agv.R), P, [0.0, 0.0, 0.0], [])
        violations = verify(layout, plans, agvs, [], prm)
        self.assertTrue(any("lobby capacity exceeded at L" in item for item in violations), violations)

    def test_capacity_limited_hybrid_plan_passes_verifier(self):
        layout = build_three_floors(lobbies=True, lobby_capacity=1)
        layout.exempt = {layout.pi} | layout.lobbies
        prm = Params(eta=1.0, eta_p=1.0, delta=1.0)
        jobs = [Job("J1", "1C", 0.0, "2E", 1000.0)]
        agvs = [AGV("AGV-01", 1), AGV("AGV-02", 2)]
        result = run_hybrid(layout, jobs, agvs, prm, Log())
        self.assertEqual(result["violations"], [])
        self.assertEqual(verify(layout, result["plans"], agvs, jobs, prm), [])


if __name__ == "__main__":
    unittest.main()
