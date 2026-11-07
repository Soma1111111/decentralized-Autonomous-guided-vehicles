"""Run paired light-load, long-horizon, and 30-seed A/B/B2/C experiments."""
from __future__ import annotations

import argparse
import csv
import os

from agv_compare import run_one
from agv_core import Params


CONFIGS = ("A", "B", "B2", "C")
SEEDS = tuple(range(1, 31))
REGIMES = (
    ("main_100_h600", 100, 600.0),
    ("light_10_h600", 10, 600.0),
    ("light_20_h600", 20, 600.0),
    ("light_30_h600", 30, 600.0),
    ("light_10_h1800", 10, 1800.0),
    ("light_10_h3600", 10, 3600.0),
    ("main_100_h1800", 100, 1800.0),
)
METRICS = (
    "makespan", "fleet_back", "tardiness", "earliness", "imbalance",
    "wait_total", "wait_max", "alg3_calls", "cpu_total_ms", "cpu_ms",
    "wall_ms", "max_windows_one_server", "messages", "payload_windows",
)


def default_outdir():
    return f"results_statistics_20a_s{SEEDS[0]}-{SEEDS[-1]}_{len(REGIMES)}regimes"


def run(outdir=None):
    if outdir is None:  # folder name encodes the settings so runs cannot overwrite each other
        outdir = default_outdir()
    os.makedirs(outdir, exist_ok=True)
    raw_path = os.path.join(outdir, "experiment_raw.csv")
    prm = Params(eta=16.0, eta_p=16.0, delta=10.0, lam=1.0)
    rows = []
    for regime, jobs, horizon in REGIMES:
        for seed in SEEDS:
            for config in CONFIGS:
                result, details = run_one(config, seed, jobs, 20, prm, horizon=horizon)
                violations = details["res"]["violations"]
                if not result["ok"] or violations:
                    raise RuntimeError(f"verification failed: {regime}, seed={seed}, {config}: {violations[:3]}")
                rows.append(dict(regime=regime, jobs=jobs, agvs=20, horizon=horizon,
                                 track_rule=prm.track_rule, config=config, seed=seed,
                                 **{metric: result[metric] for metric in METRICS}, ok=True))
            print(f"completed {regime}, seed {seed}")
    fields = ("regime", "jobs", "agvs", "horizon", "track_rule", "config", "seed",
              *METRICS, "ok")
    with open(raw_path, "w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    print(f"verified {len(rows)} schedules; wrote {raw_path}")
    return raw_path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--outdir", default=None, help="default: settings-encoded, see agv_statistical_experiments.default_outdir")
    args = parser.parse_args()
    raw_path = run(args.outdir)
    from generate_latex_tables import generate
    generate(raw_path, args.outdir)


if __name__ == "__main__":
    main()
