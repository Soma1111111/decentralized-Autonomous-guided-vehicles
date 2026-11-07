"""Focused tests for sensitivity.py (run with python -m unittest test_sensitivity)."""
import csv
import os
import tempfile
import unittest
from unittest.mock import patch

import sensitivity
from agv_core import Params


class FiveFloorLayoutTests(unittest.TestCase):
    def test_layout_is_connected_and_has_expected_resources(self):
        layout = sensitivity.build_five_floors(lift_length=40.0)
        self.assertEqual(layout.G.number_of_nodes(), 61)
        self.assertEqual(layout.G.number_of_edges(), 82)
        self.assertTrue(__import__("networkx").is_connected(layout.G))
        self.assertEqual(layout.pi, "1A")
        self.assertEqual(len(layout.lobbies), 16)
        self.assertEqual(sum(layout.is_lift(u, v) for u, v in layout.G.edges), 8)
        self.assertEqual(layout.exempt, {layout.pi} | layout.lobbies)
        self.assertEqual({layout.floor(n) for n in layout.G}, {1, 2, 3, 4, 5})

    def test_lift_length_parameter_is_applied(self):
        layout = sensitivity.build_five_floors(lift_length=80.0)
        lengths = {d["length"] for _, _, d in layout.G.edges(data=True)
                   if d.get("kind") == "lift"}
        self.assertEqual(lengths, {80.0})


class SensitivityExperimentTests(unittest.TestCase):
    def test_job_generation_is_seeded_and_uses_valid_stations(self):
        layout = sensitivity.build_five_floors()
        prm = Params(eta=16.0, eta_p=16.0, delta=10.0)
        first = sensitivity.make_jobs(layout, prm, 5, seed=11)
        again = sensitivity.make_jobs(layout, prm, 5, seed=11)
        self.assertEqual(first, again)
        stations = set(layout.G) - {layout.pi} - layout.lobbies
        for job in first:
            self.assertIn(job.p, stations)
            self.assertIn(job.p_prime, stations)
            self.assertNotEqual(job.p, job.p_prime)
            self.assertGreaterEqual(job.t, 0.0)
            self.assertLessEqual(job.t, 600.0)
            slack = job.t_prime - job.t - layout.delta_nn(job.p, job.p_prime) - 32.0
            self.assertGreaterEqual(slack, 29.9)
            self.assertLessEqual(slack, 200.1)

    def test_both_planners_return_verified_csv_rows(self):
        expected = set(sensitivity.CSV_FIELDS)
        for config in ("A", "B", "B2", "C"):
            row = sensitivity.run_case(config, seed=3, n_jobs=4, n_agvs=2,
                                       eta=8.0, delta=5.0, lift_len=20.0)
            self.assertEqual(set(row), expected)
            self.assertTrue(row["ok"], msg=f"{config}: {row}")
            self.assertEqual(row["jobs"], 4)
            self.assertEqual(row["agvs"], 2)
            self.assertGreaterEqual(row["makespan"], 0.0)
            self.assertGreaterEqual(row["tardiness"], 0.0)
            self.assertGreaterEqual(row["windows"], 0)
            self.assertGreaterEqual(row["cpu_ms"], 0.0)

    def test_sweep_writer_emits_requested_schema(self):
        row = {field: ("A" if field == "config" else 1) for field in sensitivity.CSV_FIELDS}
        row["ok"] = True
        with tempfile.TemporaryDirectory() as outdir:
            with patch.object(sensitivity, "ETA_VALUES", (8.0,)), \
                 patch.object(sensitivity, "DELTA_VALUES", (5.0,)), \
                 patch.object(sensitivity, "LIFT_LENGTH_VALUES", (20.0,)), \
                 patch.object(sensitivity, "SEEDS", (1,)), \
                 patch.object(sensitivity, "run_case", return_value=row):
                path = sensitivity.run_sweep(outdir)
            self.assertTrue(os.path.isfile(path))
            with open(path, newline="", encoding="utf-8") as stream:
                reader = csv.DictReader(stream)
                self.assertEqual(tuple(reader.fieldnames), sensitivity.CSV_FIELDS)
                self.assertEqual(len(list(reader)), 4)


if __name__ == "__main__":
    unittest.main()
