"""Parameter sensitivity experiment for centralized and hybrid AGV planning.

Run from this directory with:
    python sensitivity.py

The default experiment evaluates 3 service times x 3 safety gaps x 3 lift
lengths x 3 seeds x 2 planner configurations, using 50 jobs and 10 AGVs.
Results are written to results_sensitivity/sensitivity.csv.
"""
from __future__ import annotations

import argparse
import csv
import os
import random
import time

import networkx as nx

from agv_core import AGV, Job, Log, Params, Layout, metrics, run_pipeline
from agv_hybrid import run_hybrid
from agv_layouts import LOBBY_LENGTH


ETA_VALUES = (8.0, 16.0, 32.0)
DELTA_VALUES = (5.0, 10.0, 20.0)
LIFT_LENGTH_VALUES = (20.0, 40.0, 80.0)
SEEDS = (1, 2, 3)
N_JOBS = 50
N_AGVS = 10
DEFAULT_OUTDIR = "results_sensitivity"

CSV_FIELDS = (
    "config", "seed", "jobs", "agvs", "eta", "delta", "lift_len",
    "makespan", "tardiness", "imbalance", "cpu_ms", "windows", "ok",
)


def build_five_floors(lift_length: float = 40.0, speed: float = 1.0) -> Layout:
    """Build five 3x3-derived floor graphs joined by eight lift links.

    Floor templates reuse the 3x3 grid, ring-with-hub, and comb patterns from
    agv_layouts.build_three_floors. Two lifts connect each adjacent pair of
    floors. A lobby node is inserted at each lift landing for hybrid waiting.
    """
    G = nx.Graph()
    G.graph["floor_names"] = {f: f"Floor {f}" for f in range(1, 6)}

    grid_edges = [
        ("A", "B"), ("B", "C"), ("D", "E"), ("E", "F"),
        ("G", "H"), ("H", "I"), ("A", "D"), ("D", "G"),
        ("B", "E"), ("E", "H"), ("C", "F"), ("F", "I"),
    ]
    ring_edges = [
        ("A", "B"), ("B", "C"), ("C", "D"), ("D", "E"),
        ("E", "F"), ("F", "G"), ("G", "H"), ("H", "A"),
        ("I", "A"), ("I", "C"), ("I", "E"), ("I", "G"),
    ]
    comb_edges = [
        ("A", "B"), ("B", "C"), ("C", "D"), ("D", "E"),
        ("B", "F"), ("D", "H"), ("F", "H"),
        ("C", "G"), ("E", "I"), ("G", "I"),
    ]

    def add_floor(floor: int, shape: str) -> None:
        if shape == "grid":
            coords = {letter: (x * 15.0, 30.0 - y * 15.0)
                      for y, row in enumerate(("ABC", "DEF", "GHI"))
                      for x, letter in enumerate(row)}
            edges = grid_edges
        elif shape == "ring":
            import math
            coords = {letter: (20.0 * math.cos(math.radians(45.0 * k)),
                               20.0 * math.sin(math.radians(45.0 * k)))
                      for k, letter in enumerate("ABCDEFGH")}
            coords["I"] = (0.0, 0.0)
            edges = ring_edges
        elif shape == "comb":
            coords = dict(zip("ABCDEFGHI", [
                (0, 0), (15, 0), (30, 0), (45, 0), (60, 0),
                (15, 15), (30, -15), (45, 15), (60, -15),
            ]))
            edges = comb_edges
        else:
            raise ValueError(f"unknown floor shape: {shape}")

        for letter, pos in coords.items():
            G.add_node(f"{floor}{letter}", pos=pos, floor=floor)
        for a, b in edges:
            u, v = f"{floor}{a}", f"{floor}{b}"
            length = ((G.nodes[u]["pos"][0] - G.nodes[v]["pos"][0]) ** 2 +
                      (G.nodes[u]["pos"][1] - G.nodes[v]["pos"][1]) ** 2) ** 0.5
            G.add_edge(u, v, length=round(length, 3), kind="floor")

    shapes = ("grid", "ring", "comb", "ring", "grid")
    for floor, shape in enumerate(shapes, start=1):
        add_floor(floor, shape)

    # Repeat the two-link pattern used to join adjacent floors in the
    # three-floor factory. Lift edges are landing-to-landing after lobby
    # insertion and carry the parameterized special length.
    for floor in range(1, 5):
        for source_letter, dest_letter in (("C", "E"), ("I", "G")):
            u, v = f"{floor}{source_letter}", f"{floor + 1}{dest_letter}"
            for landing in (u, v):
                lobby = f"{landing}~"
                if lobby not in G:
                    x, y = G.nodes[landing]["pos"]
                    G.add_node(lobby, pos=(x + 4.0, y + 4.0),
                               floor=G.nodes[landing]["floor"], lobby=True)
                    G.add_edge(landing, lobby, length=LOBBY_LENGTH, kind="floor")
            G.add_edge(f"{u}~", f"{v}~", length=float(lift_length), kind="lift")

    assert G.number_of_nodes() == 45 + 16
    assert G.number_of_edges() == 58 + 16 + 8
    assert nx.is_connected(G)
    L = Layout(G, "1A", speed=speed)
    L.exempt = {L.pi} | L.lobbies
    return L


def make_jobs(L: Layout, prm: Params, n_jobs: int, seed: int,
              horizon: float = 600.0) -> list[Job]:
    """Generate reproducible jobs on non-parking, non-lobby workstations."""
    rng = random.Random(seed)
    stations = [n for n in L.G if n != L.pi and n not in L.lobbies]
    jobs = []
    for k in range(1, n_jobs + 1):
        pickup, delivery = rng.sample(stations, 2)
        pickup_time = round(rng.uniform(0.0, horizon), 1)
        slack = rng.uniform(30.0, 200.0)
        delivery_time = round(
            pickup_time + L.delta_nn(pickup, delivery) + prm.eta + prm.eta_p + slack,
            1,
        )
        jobs.append(Job(f"J{k:03d}", pickup, pickup_time, delivery, delivery_time))
    return jobs


def count_central_windows(L: Layout, plans) -> int:
    """Count node and track reservation windows held by one central planner."""
    return sum(
        sum(1 for node in plan.R if node not in L.exempt) + len(plan.R) - 1
        for plan in plans.values()
    )


def run_case(config: str, seed: int, n_jobs: int, n_agvs: int,
             eta: float, delta: float, lift_len: float) -> dict:
    """Run one centralized (A) or hybrid (C) scenario and return its CSV row."""
    L = build_five_floors(lift_length=lift_len)
    prm = Params(eta=eta, eta_p=eta, delta=delta, lam=1.0)
    jobs = make_jobs(L, prm, n_jobs, seed)
    agvs = [AGV(f"AGV-{k:02d}", k) for k in range(1, n_agvs + 1)]
    log = Log()

    started = time.perf_counter()
    if config == "A":
        # A is the centralized paper-style planner: only pi is exempt.
        L.exempt = {L.pi}
        result = run_pipeline(L, jobs, agvs, prm, log)
        cpu_ms = 1000.0 * (result["t_alg1"] + result["t_alg2"])
        windows = count_central_windows(L, result["plans"])
    elif config == "C":
        # C uses lift lobbies and floor-local planning in FCFS order.
        result = run_hybrid(L, jobs, agvs, prm, log, order="fcfs")
        cpu_ms = 1000.0 * max(s["cpu"] for s in result["servers"].values())
        windows = max(s["windows"] for s in result["servers"].values())
    else:
        raise ValueError("config must be 'A' (centralized) or 'C' (hybrid)")
    _wall_seconds = time.perf_counter() - started

    m = metrics(L, result["plans"], agvs, jobs, result["estimate"],
                result["calls"], prm)
    return {
        "config": config,
        "seed": seed,
        "jobs": n_jobs,
        "agvs": n_agvs,
        "eta": eta,
        "delta": delta,
        "lift_len": lift_len,
        "makespan": round(m["makespan_last_delivery"], 3),
        "tardiness": round(m["tardiness_final"], 3),
        "imbalance": round(m["load_imbalance"], 3),
        "cpu_ms": round(cpu_ms, 3),
        "windows": windows,
        "ok": not result["violations"],
    }


def run_sweep(outdir: str = DEFAULT_OUTDIR) -> str:
    """Run the full fixed sensitivity grid and write the CSV output."""
    os.makedirs(outdir, exist_ok=True)
    out_path = os.path.join(outdir, "sensitivity.csv")
    rows = []
    for eta in ETA_VALUES:
        for delta in DELTA_VALUES:
            for lift_len in LIFT_LENGTH_VALUES:
                for seed in SEEDS:
                    for config in ("A", "C"):
                        row = run_case(config, seed, N_JOBS, N_AGVS,
                                       eta, delta, lift_len)
                        rows.append(row)
                        print(
                            f"{config} seed={seed} eta={eta:g} delta={delta:g} "
                            f"lift={lift_len:g}: ok={row['ok']} "
                            f"makespan={row['makespan']:.1f}"
                        )

    with open(out_path, "w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=CSV_FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    return out_path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--outdir", default=DEFAULT_OUTDIR)
    args = parser.parse_args()
    path = run_sweep(args.outdir)
    print(f"Wrote {path}")


if __name__ == "__main__":
    main()
