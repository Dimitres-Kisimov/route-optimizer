"""Generate deterministic synthetic CVRP instances.

Each instance is a depot plus N customers scattered across a service area in a
few clusters (like neighbourhoods a distributor actually serves), with integer
demands and a homogeneous fleet of capacity-limited vehicles. Everything is
seeded, so the JSON files committed to the repo are reproducible byte-for-byte.

Run:  python data/generate_instances.py
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

OUT_DIR = Path(__file__).resolve().parent / "instances"

# Service area is a 100 x 100 grid; the depot sits near the middle.
AREA = 100.0
DEPOT = (50.0, 50.0)


def _clustered_points(rng: np.random.Generator, n: int, n_clusters: int) -> np.ndarray:
    """N customer points drawn around a handful of cluster centres."""
    centres = rng.uniform(15.0, AREA - 15.0, size=(n_clusters, 2))
    pts = np.empty((n, 2), dtype=float)
    for i in range(n):
        c = centres[i % n_clusters]
        p = rng.normal(loc=c, scale=9.0)
        pts[i] = np.clip(p, 2.0, AREA - 2.0)
    return np.round(pts, 2)


def make_instance(
    name: str,
    n_customers: int,
    n_clusters: int,
    capacity: int,
    n_vehicles: int,
    seed: int,
    demand_lo: int = 1,
    demand_hi: int = 12,
) -> dict:
    rng = np.random.default_rng(seed)
    pts = _clustered_points(rng, n_customers, n_clusters)
    demands = rng.integers(demand_lo, demand_hi + 1, size=n_customers).tolist()

    # Node 0 is the depot (demand 0), nodes 1..N are customers.
    coords = [list(DEPOT)] + pts.tolist()
    all_demands = [0] + list(demands)

    total_demand = int(sum(demands))
    min_vehicles = -(-total_demand // capacity)  # ceil
    if n_vehicles < min_vehicles:
        raise ValueError(
            f"{name}: fleet of {n_vehicles} x {capacity} = {n_vehicles * capacity} "
            f"cannot carry total demand {total_demand} (need >= {min_vehicles} vehicles)"
        )

    return {
        "name": name,
        "seed": seed,
        "depot": 0,
        "capacity": capacity,
        "num_vehicles": n_vehicles,
        "coords": coords,
        "demands": all_demands,
        "meta": {
            "num_customers": n_customers,
            "num_clusters": n_clusters,
            "total_demand": total_demand,
            "min_vehicles_by_capacity": min_vehicles,
            "distance": "euclidean",
        },
    }


def tiny_instance() -> dict:
    """A hand-checkable 5-customer instance placed on a symmetric cross.

    The depot is at (50,50); customers sit on the axes at distance 20. With a
    capacity that forces two vehicles, the geometry has an obvious sensible
    answer, which the tests pin down.
    """
    coords = [
        [50.0, 50.0],  # 0 depot
        [70.0, 50.0],  # 1 east
        [50.0, 70.0],  # 2 north
        [30.0, 50.0],  # 3 west
        [50.0, 30.0],  # 4 south
        [70.0, 70.0],  # 5 north-east
    ]
    demands = [0, 3, 3, 3, 3, 4]
    return {
        "name": "tiny",
        "seed": 0,
        "depot": 0,
        "capacity": 10,
        "num_vehicles": 2,
        "coords": coords,
        "demands": demands,
        "meta": {
            "num_customers": 5,
            "num_clusters": 1,
            "total_demand": sum(demands),
            "min_vehicles_by_capacity": 2,
            "distance": "euclidean",
            "note": "hand-checkable; used by the test suite",
        },
    }


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    instances = [
        tiny_instance(),
        make_instance("n30", n_customers=30, n_clusters=3, capacity=40, n_vehicles=7, seed=30),
        make_instance("n60", n_customers=60, n_clusters=5, capacity=50, n_vehicles=12, seed=60),
        make_instance("n100", n_customers=100, n_clusters=6, capacity=60, n_vehicles=15, seed=100),
    ]
    for inst in instances:
        path = OUT_DIR / f"{inst['name']}.json"
        path.write_text(json.dumps(inst, indent=2) + "\n", encoding="utf-8")
        m = inst["meta"]
        print(
            f"wrote {path.name:12s}  customers={m['num_customers']:3d}  "
            f"demand={m['total_demand']:4d}  cap={inst['capacity']}  "
            f"fleet={inst['num_vehicles']}  (>= {m['min_vehicles_by_capacity']} needed)"
        )


if __name__ == "__main__":
    main()
