"""Instance loading and the distance matrix.

An :class:`Instance` is the problem: a depot, customers with coordinates and
demands, a vehicle capacity and a fleet size. The distance matrix is built once
and reused by every solver / heuristic so they are all scored on identical
numbers.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np


@dataclass(frozen=True)
class Instance:
    name: str
    depot: int
    capacity: int
    num_vehicles: int
    coords: np.ndarray  # shape (n_nodes, 2), node 0 is the depot
    demands: np.ndarray  # shape (n_nodes,), demands[depot] == 0

    @property
    def num_nodes(self) -> int:
        return int(self.coords.shape[0])

    @property
    def num_customers(self) -> int:
        return self.num_nodes - 1

    @property
    def total_demand(self) -> int:
        return int(self.demands.sum())

    def __post_init__(self) -> None:
        if self.coords.shape[0] != self.demands.shape[0]:
            raise ValueError("coords and demands length mismatch")
        if self.demands[self.depot] != 0:
            raise ValueError("depot demand must be 0")
        if (self.demands > self.capacity).any():
            raise ValueError("a customer demand exceeds vehicle capacity — infeasible")


def load_instance(path: str | Path) -> Instance:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    return Instance(
        name=raw["name"],
        depot=int(raw["depot"]),
        capacity=int(raw["capacity"]),
        num_vehicles=int(raw["num_vehicles"]),
        coords=np.asarray(raw["coords"], dtype=float),
        demands=np.asarray(raw["demands"], dtype=int),
    )


def distance_matrix(instance: Instance, metric: str = "euclidean") -> np.ndarray:
    """Symmetric node-to-node distance matrix (float).

    ``euclidean`` — straight-line; ``manhattan`` — L1, a rough grid-street proxy.
    """
    c = instance.coords
    diff = c[:, None, :] - c[None, :, :]
    if metric == "euclidean":
        d = np.sqrt((diff**2).sum(axis=2))
    elif metric == "manhattan":
        d = np.abs(diff).sum(axis=2)
    else:
        raise ValueError(f"unknown metric: {metric!r}")
    np.fill_diagonal(d, 0.0)
    return d


def scaled_int_matrix(dist: np.ndarray, scale: int = 100) -> np.ndarray:
    """OR-Tools' arc costs must be integers; scale then round to keep precision."""
    return np.round(dist * scale).astype(np.int64)


def route_distance(route: list[int], dist: np.ndarray) -> float:
    """Total distance of one route (a list of nodes, depot at both ends)."""
    return float(sum(dist[route[i], route[i + 1]] for i in range(len(route) - 1)))


def route_load(route: list[int], demands: np.ndarray) -> int:
    return int(sum(demands[n] for n in route))
