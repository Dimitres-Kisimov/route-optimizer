"""Baseline CVRP heuristics, implemented from scratch.

These exist so OR-Tools' metaheuristic has something honest to beat:

* **Clarke-Wright savings** (1964) — the classic parallel-savings construction.
  Start with one out-and-back route per customer, then greedily merge the two
  route endpoints with the largest *saving* s(i,j) = d(0,i) + d(0,j) - d(i,j),
  as long as the merge respects vehicle capacity and keeps i and j on the
  outside of their routes.
* **Nearest-neighbour** — a greedy sweep: from the depot, repeatedly hop to the
  closest unvisited customer that still fits, opening a new route when nothing
  fits.

Both return the same shape as the OR-Tools solver so :mod:`routeopt.report` can
score them side by side.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .model import Instance, route_distance, route_load


@dataclass
class Solution:
    method: str
    routes: list[list[int]]  # each route starts and ends at the depot
    total_distance: float
    vehicles_used: int
    loads: list[int]
    feasible: bool
    solve_time_s: float = 0.0

    @classmethod
    def from_routes(
        cls, method: str, routes: list[list[int]], dist: np.ndarray, demands: np.ndarray, capacity: int, solve_time_s: float = 0.0
    ) -> Solution:
        routes = [r for r in routes if len(r) > 2]  # drop empty depot->depot routes
        loads = [route_load(r, demands) for r in routes]
        total = sum(route_distance(r, dist) for r in routes)
        served = sorted(n for r in routes for n in r if n != 0)
        expected = list(range(1, len(demands)))
        feasible = served == expected and all(load <= capacity for load in loads)
        return cls(
            method=method,
            routes=routes,
            total_distance=float(total),
            vehicles_used=len(routes),
            loads=loads,
            feasible=feasible,
            solve_time_s=solve_time_s,
        )


def nearest_neighbour(instance: Instance, dist: np.ndarray) -> Solution:
    depot = instance.depot
    demands = instance.demands
    capacity = instance.capacity
    unvisited = set(range(instance.num_nodes)) - {depot}

    routes: list[list[int]] = []
    while unvisited:
        route = [depot]
        load = 0
        current = depot
        while True:
            candidates = [n for n in unvisited if load + demands[n] <= capacity]
            if not candidates:
                break
            nxt = min(candidates, key=lambda n: dist[current, n])
            route.append(nxt)
            load += int(demands[nxt])
            unvisited.remove(nxt)
            current = nxt
        route.append(depot)
        routes.append(route)

    return Solution.from_routes("nearest-neighbour", routes, dist, demands, capacity)


def clarke_wright(instance: Instance, dist: np.ndarray) -> Solution:
    depot = instance.depot
    demands = instance.demands
    capacity = instance.capacity
    customers = [n for n in range(instance.num_nodes) if n != depot]

    # Every route gets a stable integer key. Start with one out-and-back route
    # per customer (each holding a customer sequence with no depot).
    seq: dict[int, list[int]] = {}  # route key -> ordered customer list
    load: dict[int, int] = {}       # route key -> total demand
    route_of: dict[int, int] = {}   # customer -> its route key
    for key, c in enumerate(customers):
        seq[key] = [c]
        load[key] = int(demands[c])
        route_of[c] = key

    # Savings for every customer pair, largest first.
    savings = []
    for a_idx in range(len(customers)):
        i = customers[a_idx]
        for b_idx in range(a_idx + 1, len(customers)):
            j = customers[b_idx]
            s = float(dist[depot, i] + dist[depot, j] - dist[i, j])
            savings.append((s, i, j))
    savings.sort(reverse=True)

    for s, i, j in savings:
        if s <= 0:
            break
        ki = route_of[i]
        kj = route_of[j]
        if ki == kj:
            continue  # already on the same route
        ri, rj = seq[ki], seq[kj]
        # i and j must each sit at an *end* of their route to merge cleanly.
        if not ((ri[0] == i or ri[-1] == i) and (rj[0] == j or rj[-1] == j)):
            continue
        if load[ki] + load[kj] > capacity:
            continue

        # Orient both routes so i is at the tail of ri and j at the head of rj,
        # then concatenate: [...->i] + [j->...] into ki; retire kj.
        if ri[0] == i:
            ri.reverse()
        if rj[-1] == j:
            rj.reverse()
        seq[ki] = ri + rj
        load[ki] = load[ki] + load[kj]
        for c in rj:
            route_of[c] = ki
        del seq[kj]
        del load[kj]

    # Wrap each surviving route with the depot at both ends.
    final = [[depot, *r, depot] for r in seq.values()]
    return Solution.from_routes("clarke-wright", final, dist, demands, capacity)
