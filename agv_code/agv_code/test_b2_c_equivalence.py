"""B2 centralized-FCFS and C hybrid-FCFS schedule equivalence check."""
import unittest

from agv_compare import run_one, same_plans
from agv_core import Params


class B2CHybridEquivalenceTests(unittest.TestCase):
    def test_identical_schedules_for_seeds_1_through_10(self):
        prm = Params(eta=16.0, eta_p=16.0, delta=10.0, lam=1.0)
        for seed in range(1, 11):
            row_b2, b2 = run_one("B2", seed, 100, 20, prm)
            row_c, c = run_one("C", seed, 100, 20, prm)
            self.assertTrue(row_b2["ok"], msg=f"B2 invalid for seed {seed}")
            self.assertTrue(row_c["ok"], msg=f"C invalid for seed {seed}")
            self.assertTrue(
                same_plans(b2["res"]["plans"], c["res"]["plans"]),
                msg=self._difference(seed, b2["res"]["plans"], c["res"]["plans"]),
            )

    @staticmethod
    def _difference(seed, b2, c):
        for agv_id in b2:
            if b2[agv_id].R != c[agv_id].R:
                return (f"seed {seed}, {agv_id}: route mismatch; "
                        f"B2={b2[agv_id].R[:12]}, C={c[agv_id].R[:12]}")
            for idx, (w_b2, w_c) in enumerate(zip(b2[agv_id].P, c[agv_id].P)):
                if any(abs(x - y) > 1e-6 for x, y in zip(w_b2, w_c)):
                    return (f"seed {seed}, {agv_id}, visit {idx + 1}: "
                            f"B2 window={w_b2}, C window={w_c}")
        return f"seed {seed}: B2 and C schedules differ"


if __name__ == "__main__":
    unittest.main()
