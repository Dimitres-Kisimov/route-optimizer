# Method

## The problem — CVRP

The Capacitated Vehicle Routing Problem is: one depot, a set of customers each
with a known demand, and a fleet of identical vehicles each with capacity `Q`.
Every customer must be visited exactly once by exactly one vehicle; each vehicle
leaves the depot, serves a subset of customers whose demands sum to at most `Q`,
and returns to the depot. Minimise the total distance travelled by all vehicles.

Formally, with nodes `0` (depot) and `1..n` (customers), demand `q_i`, distance
`d_ij`, and binary `x_ijk = 1` if vehicle `k` drives arc `i→j`:

```
minimise    sum_k sum_i sum_j  d_ij * x_ijk
subject to  each customer entered and left exactly once (across all vehicles)
            flow conservation per vehicle at every node
            sum of served demand on vehicle k  <=  Q
            sub-tour elimination (routes connect back to the depot)
            x_ijk in {0,1}
```

CVRP is NP-hard — it contains the Travelling Salesman Problem as the single-vehicle,
uncapacitated special case — so for anything past a handful of customers we do not
solve the integer program to proven optimality. We construct a good feasible
solution and then improve it with local search.

Distances here are **Euclidean** (straight-line) by default, with a Manhattan
(L1) option as a crude grid-street proxy. Neither is a real road network; see the
limitations in the README.

## Baseline 1 — Clarke-Wright savings (1964)

The classic construction heuristic, implemented from scratch in
`routeopt/heuristic.py`.

1. Start with the trivial solution: one dedicated out-and-back route
   `depot → i → depot` for every customer `i`.
2. For every pair `(i, j)` compute the **saving** from serving them on one route
   instead of two:

   ```
   s(i, j) = d(depot, i) + d(depot, j) − d(i, j)
   ```

   A large saving means `i` and `j` are close to each other relative to their
   distance from the depot — exactly the pairs worth combining.
3. Sort pairs by saving, descending. Walk the list and **merge** the routes
   containing `i` and `j` whenever: they are on different routes, `i` and `j`
   each sit at an *end* of their route (so the merge is a clean concatenation),
   and the combined demand still fits in `Q`.

This is the *parallel* savings variant (all routes grow together). It is fast,
deterministic, and typically lands within ~10–15% of good solutions — a genuinely
strong baseline, which is the point: beating it takes real optimization.

## Baseline 2 — nearest-neighbour

A greedy sweep, for a naive lower bar: from the depot, repeatedly hop to the
closest unvisited customer that still fits in the current vehicle; when nothing
fits, close the route and start a new vehicle. Cheap, and usually 20–35% worse
than savings — it shows how much the savings *structure* already buys you.

## The optimizer — OR-Tools CVRP

`routeopt/solver.py` builds a Google OR-Tools `RoutingModel`:

- **Arc cost** = the distance callback. OR-Tools works in integers, so distances
  are scaled by 100 and rounded; the reported totals are scaled back to real
  units so every method is compared on identical numbers.
- **Capacity dimension** — a unary demand callback with per-vehicle capacity `Q`
  and no slack, so overloaded routes are infeasible by construction.
- **Distance dimension** — bounds any single route and lets the search reason
  about route length.
- **First solution**: `PATH_CHEAPEST_ARC` — a quick greedy construction to get a
  feasible starting point.
- **Metaheuristic**: `GUIDED_LOCAL_SEARCH` under a wall-clock **time limit**
  (default 5s). GLS escapes local optima by penalising features (long arcs) that
  keep reappearing, then re-runs local search (2-opt, or-opt, relocation…).

The solver returns the same structure as the baselines — routes, total distance,
vehicles used, per-route load, feasibility, solve time — so `routeopt/report.py`
can score all three head to head.

## Why the fleet has slack

Each instance is given a few more vehicles than the tight lower bound
`ceil(total_demand / Q)`. A perfectly-sized fleet turns routing into a hard
bin-packing feasibility puzzle before any distance is optimised; real distributors
also run with spare capacity. The solver still *uses* as few vehicles as it can —
on `n60` it parks 2 of the 12.

## Reproducibility

Instances are generated with fixed NumPy seeds (`data/generate_instances.py`), so
the committed JSON is byte-for-byte reproducible. OR-Tools' GLS is time-limited,
so its final distance can wobble by a fraction of a percent between runs and
machines; the baselines are deterministic.
