"""The OR-Tools CVRP solver.

Builds a `RoutingModel` with two dimensions — travelled distance and vehicle
load — solves with PATH_CHEAPEST_ARC for the first solution and guided local
search as the metaheuristic, under a wall-clock time limit, and returns the
routes in the same :class:`~routeopt.heuristic.Solution` shape as the baselines.

Two stopping modes:

* ``time_limit_s`` (default) — wall-clock. Best quality per second, but the
  final distance wobbles a fraction of a percent between runs and machines.
* ``solution_limit`` — stop after a fixed number of solutions instead. The
  search is single-threaded and contains no time-based decisions, so the same
  instance + limit gives the **identical routes on every run** — this is the
  mode the robustness stress test pins its deliverables on.
"""

from __future__ import annotations

import time

from ortools.constraint_solver import pywrapcp, routing_enums_pb2

from .heuristic import Solution
from .model import Instance, distance_matrix, scaled_int_matrix

# Arc costs are scaled to integers with this factor; total_distance is divided
# back out at the end so every method reports in the same real units.
_SCALE = 100


def solve_cvrp(
    instance: Instance,
    metric: str = "euclidean",
    time_limit_s: int = 5,
    log: bool = False,
    solution_limit: int | None = None,
) -> Solution:
    dist = distance_matrix(instance, metric)
    idist = scaled_int_matrix(dist, _SCALE)
    n_nodes = instance.num_nodes

    manager = pywrapcp.RoutingIndexManager(n_nodes, instance.num_vehicles, instance.depot)
    routing = pywrapcp.RoutingModel(manager)

    # --- distance callback + arc cost ------------------------------------
    def distance_cb(from_index: int, to_index: int) -> int:
        i = manager.IndexToNode(from_index)
        j = manager.IndexToNode(to_index)
        return int(idist[i][j])

    transit_idx = routing.RegisterTransitCallback(distance_cb)
    routing.SetArcCostEvaluatorOfAllVehicles(transit_idx)

    # --- capacity dimension ----------------------------------------------
    def demand_cb(from_index: int) -> int:
        return int(instance.demands[manager.IndexToNode(from_index)])

    demand_idx = routing.RegisterUnaryTransitCallback(demand_cb)
    routing.AddDimensionWithVehicleCapacity(
        demand_idx,
        0,  # no slack
        [int(instance.capacity)] * instance.num_vehicles,
        True,  # start cumul at zero
        "Capacity",
    )

    # --- distance dimension (lets the solver balance / bound route length)
    horizon = int(idist.sum())  # a loose upper bound on any single route
    routing.AddDimension(transit_idx, 0, horizon, True, "Distance")

    # --- search parameters ------------------------------------------------
    params = pywrapcp.DefaultRoutingSearchParameters()
    params.first_solution_strategy = routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC
    params.local_search_metaheuristic = (
        routing_enums_pb2.LocalSearchMetaheuristic.GUIDED_LOCAL_SEARCH
    )
    if solution_limit is not None:
        # Deterministic mode: a fixed solution count, no wall-clock anywhere in
        # the search, so the result is identical run-to-run (see module docstring).
        params.solution_limit = int(solution_limit)
    else:
        params.time_limit.FromSeconds(int(time_limit_s))
    params.log_search = bool(log)

    t0 = time.perf_counter()
    solution = routing.SolveWithParameters(params)
    elapsed = time.perf_counter() - t0

    if solution is None:
        return Solution(
            method="or-tools",
            routes=[],
            total_distance=float("inf"),
            vehicles_used=0,
            loads=[],
            feasible=False,
            solve_time_s=elapsed,
        )

    routes: list[list[int]] = []
    for v in range(instance.num_vehicles):
        index = routing.Start(v)
        route = [manager.IndexToNode(index)]
        while not routing.IsEnd(index):
            index = solution.Value(routing.NextVar(index))
            route.append(manager.IndexToNode(index))
        if len(route) > 2:  # vehicle actually used
            routes.append(route)

    sol = Solution.from_routes(
        "or-tools", routes, dist, instance.demands, instance.capacity, solve_time_s=elapsed
    )
    return sol
