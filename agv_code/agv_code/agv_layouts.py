"""
agv_layouts.py - factory layouts G = {N, E}

build_single_floor()  : the 3x3 grid of the original demo (parking station A)
build_three_floors()  : 3 floors x 9 nodes = 27 nodes, ONE parking station pi for the whole factory

Every undirected edge is a bidirectional track.  Edge attribute  length  (metres) / AGV speed
gives the non-stop travel time delta_nn'.  Inter-floor links ("lifts") are ordinary edges with
kind = 'lift' and their own, longer "special" length (LIFT_LENGTHS below).
"""
from __future__ import annotations

import math

import networkx as nx

from agv_core import Layout

# ------------------------------------------------------------------------------------------
# EDIT HERE: special distance (metres) of every inter-floor lift link
# ------------------------------------------------------------------------------------------
LIFT_LENGTHS = {
    ("1C", "2E"): 40.0,   # floor 1 <-> floor 2, lift a
    ("1I", "2G"): 40.0,   # floor 1 <-> floor 2, lift b
    ("2A", "3A"): 40.0,   # floor 2 <-> floor 3, lift a
    ("2C", "3F"): 40.0,   # floor 2 <-> floor 3, lift b
}
PARKING_THREE_FLOORS = "1A"
# hybrid architecture only: every lift end gets a lobby node "<landing>~" (a side bay that can hold
# several waiting AGVs, like pi) joined to its landing by a short track of LOBBY_LENGTH metres
LOBBY_LENGTH = 2.0


def build_single_floor() -> Layout:
    """Original demo graph. Horizontal edges 2, vertical edges 1 (time units), parking A."""
    pos = dict(zip("ABCDEFGHI", [(0, 2), (2, 2), (4, 2), (0, 1), (2, 1), (4, 1), (0, 0), (2, 0), (4, 0)]))
    G = nx.Graph()
    G.graph["floor_names"] = {1: "Factory floor (3x3 grid)"}
    for n, p in pos.items():
        G.add_node(n, pos=p, floor=1)
    for u, v in [("A", "B"), ("B", "C"), ("D", "E"), ("E", "F"), ("G", "H"), ("H", "I"),
                 ("A", "D"), ("D", "G"), ("B", "E"), ("E", "H"), ("C", "F"), ("F", "I")]:
        G.add_edge(u, v, length=math.dist(pos[u], pos[v]), kind="floor")
    return Layout(G, "A", speed=1.0)


def build_three_floors(speed: float = 1.0, lift_lengths=None, lobbies: bool = False,
                       lobby_capacity=None) -> Layout:
    """lobbies=True inserts a lobby node at both ends of every lift: landing - lobby ~~lift~~ lobby - landing.
    The lobbies are ordinary nodes until they are added to Layout.exempt (see agv_compare.py)."""
    lift_lengths = lift_lengths or LIFT_LENGTHS
    G = nx.Graph()
    G.graph["floor_names"] = {1: "Floor 1 - 3x3 grid", 2: "Floor 2 - ring with hub", 3: "Floor 3 - comb with two loops"}

    def add(floor, names, coords, edges):
        for n, p in zip(names, coords):
            G.add_node(f"{floor}{n}", pos=p, floor=floor)
        for u, v in edges:
            a, b = f"{floor}{u}", f"{floor}{v}"
            G.add_edge(a, b, length=round(math.dist(G.nodes[a]["pos"], G.nodes[b]["pos"]), 3), kind="floor")

    # floor 1: 3x3 grid, spacing 15 m
    add(1, "ABCDEFGHI", [(x * 15, 30 - y * 15) for y in range(3) for x in range(3)],
        [("A", "B"), ("B", "C"), ("D", "E"), ("E", "F"), ("G", "H"), ("H", "I"),
         ("A", "D"), ("D", "G"), ("B", "E"), ("E", "H"), ("C", "F"), ("F", "I")])
    # floor 2: ring of 8 nodes (radius 20 m) + hub I, four spokes
    ring = [(20 * math.cos(math.radians(45 * k)), 20 * math.sin(math.radians(45 * k))) for k in range(8)]
    add(2, "ABCDEFGHI", ring + [(0, 0)],
        [("A", "B"), ("B", "C"), ("C", "D"), ("D", "E"), ("E", "F"), ("F", "G"), ("G", "H"), ("H", "A"),
         ("I", "A"), ("I", "C"), ("I", "E"), ("I", "G")])
    # floor 3: spine A-E with four branches F,H (above) G,I (below) and two connectors F-H, G-I
    add(3, "ABCDEFGHI", [(0, 0), (15, 0), (30, 0), (45, 0), (60, 0), (15, 15), (30, -15), (45, 15), (60, -15)],
        [("A", "B"), ("B", "C"), ("C", "D"), ("D", "E"), ("B", "F"), ("D", "H"), ("F", "H"),
         ("C", "G"), ("E", "I"), ("G", "I")])
    # lifts = special inter-floor distances
    for (u, v), length in lift_lengths.items():
        if lobbies:
            for n in (u, v):
                b = f"{n}~"
                if b not in G:
                    x, y = G.nodes[n]["pos"]
                    G.add_node(b, pos=(x + 4, y + 4), floor=G.nodes[n]["floor"], lobby=True)
                    G.add_edge(n, b, length=LOBBY_LENGTH, kind="floor")
            u, v = f"{u}~", f"{v}~"
        G.add_edge(u, v, length=float(length), kind="lift")
    n_lobby = sum(1 for _, d in G.nodes(data=True) if d.get("lobby"))
    assert G.number_of_nodes() == 27 + n_lobby and nx.is_connected(G)
    return Layout(G, PARKING_THREE_FLOORS, speed=speed, lobby_capacity=lobby_capacity)


def _insert_lobbies(G):
    """Replace each lift edge by landing-lobby, lift, lobby-landing edges."""
    for u, v, data in list(G.edges(data=True)):
        if data.get("kind") != "lift":
            continue
        length = data["length"]
        G.remove_edge(u, v)
        lu, lv = f"{u}~", f"{v}~"
        for node, lobby in ((u, lu), (v, lv)):
            x, y = G.nodes[node]["pos"]
            G.add_node(lobby, pos=(x + 4, y + 4), floor=G.nodes[node]["floor"], lobby=True)
            G.add_edge(node, lobby, length=LOBBY_LENGTH, kind="floor")
        G.add_edge(lu, lv, length=length, kind="lift")


def build_five_floors(speed: float = 1.0, lift_length: float = 40.0,
                      lobbies: bool = False, lobby_capacity=None) -> Layout:
    """Five 3x3-style floors with two lifts between each adjacent pair of floors."""
    base = build_three_floors(speed=speed)
    G = base.G.copy()
    template_edges = [(u[1:], v[1:], dict(d)) for u, v, d in G.edges(data=True)
                      if u.startswith("3") and v.startswith("3") and d.get("kind") == "floor"]
    template_nodes = [(n[1:], d) for n, d in G.nodes(data=True) if n.startswith("3")]
    for floor in (4, 5):
        G.graph.setdefault("floor_names", {})[floor] = f"Floor {floor} - comb with two loops"
        for suffix, data in template_nodes:
            x, y = data["pos"]
            G.add_node(f"{floor}{suffix}", pos=(x, y - 100 * (floor - 3)), floor=floor)
        for u, v, data in template_edges:
            G.add_edge(f"{floor}{u}", f"{floor}{v}", **data)
    lifts = [("3A", "4A"), ("3F", "4G"), ("4A", "5A"), ("4F", "5G")]
    for u, v in lifts:
        G.add_edge(u, v, length=float(lift_length), kind="lift")
    if lobbies:
        _insert_lobbies(G)
    return Layout(G, PARKING_THREE_FLOORS, speed=speed, lobby_capacity=lobby_capacity)
