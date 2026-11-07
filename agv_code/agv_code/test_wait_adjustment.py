import unittest

from agv_compare import run_one
from agv_core import Params


class WaitAdjustmentTests(unittest.TestCase):
    def test_seeded_schedule_passes_independent_verifier(self):
        row, details = run_one("WA", 1, 100, 20, Params())
        self.assertTrue(row["ok"])
        self.assertEqual([], details["res"]["violations"])

    def test_wait_can_be_inserted_at_route_node(self):
        row, details = run_one("WA", 1, 100, 20, Params())
        L, plans = details["L"], details["res"]["plans"]
        self.assertTrue(any(
            node not in L.exempt and window[1] - window[0] > plan.dwell[m] + 1e-6
            for plan in plans.values()
            for m, (node, window) in enumerate(zip(plan.R, plan.P))
        ))


if __name__ == "__main__":
    unittest.main()
