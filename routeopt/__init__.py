"""route-optimizer — a Capacitated Vehicle Routing Problem (CVRP) solver.

OR-Tools' guided local search against the classic Clarke-Wright savings and
nearest-neighbour baselines, on synthetic last-mile delivery instances.
"""

from .heuristic import Solution, clarke_wright, nearest_neighbour
from .model import Instance, distance_matrix, load_instance
from .sensitivity import FleetPoint, build_fleet_sensitivity, sweep_fleet, trade_off_read
from .solver import solve_cvrp

__all__ = [
    "FleetPoint",
    "Instance",
    "Solution",
    "build_fleet_sensitivity",
    "clarke_wright",
    "distance_matrix",
    "load_instance",
    "nearest_neighbour",
    "solve_cvrp",
    "sweep_fleet",
    "trade_off_read",
]

__version__ = "0.1.0"
