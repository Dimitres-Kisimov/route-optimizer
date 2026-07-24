"""route-optimizer — a Capacitated Vehicle Routing Problem (CVRP) solver.

OR-Tools' guided local search against the classic Clarke-Wright savings and
nearest-neighbour baselines, on synthetic last-mile delivery instances.
"""

from .heuristic import Solution, clarke_wright, nearest_neighbour
from .model import Instance, distance_matrix, load_instance
from .solver import solve_cvrp

__all__ = [
    "Instance",
    "Solution",
    "clarke_wright",
    "distance_matrix",
    "load_instance",
    "nearest_neighbour",
    "solve_cvrp",
]

__version__ = "0.1.0"
