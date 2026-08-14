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

## Fleet-size sensitivity

`routeopt/sensitivity.py` turns the single-instance solve into a planning curve.
The lever is **vehicle capacity** (bigger vans ⇒ fewer vans), swept roughly from
half-size to double-size around the instance's own capacity. At each capacity the
deterministic Clarke-Wright savings heuristic is re-run, and — per distinct number
of vehicles it then needs — the minimum-distance plan is kept, giving an efficient
frontier of *fleet size → (total distance, longest route, cost, CO2)*.

Two honest points about the direction:

- The routing objective is total distance with **no fixed per-vehicle cost**, so
  it prefers fewer, fuller vans (fewer depot round-trips). Minimum vehicles and
  minimum distance therefore pull the *same* way; the genuine tension is with
  **service** — the longest single route (≈ time to the last customer) grows as
  the fleet consolidates. The frontier reports that longest route as its service
  column.
- The `€1.00/km` and `250 g/km` figures are **illustrative estimates** (the same
  as `docs/BUSINESS_CASE.md`), not certified numbers; distance units are treated
  as kilometres. The cost column is variable only — a fixed per-van cost, if
  added, shifts the optimum further toward consolidation.

The engine is the deterministic savings heuristic (not the time-limited OR-Tools
metaheuristic), so `deliverables/fleet_sensitivity.{csv,svg,md}` are byte-for-byte
reproducible. OR-Tools would shave a few percent off every point without changing
the shape of the trade-off.

## Time windows (VRPTW) & the service-level audit

`routeopt/timewindows.py` adds the constraint the base CVRP ignores: *when* a van
reaches each customer. A light time model sits on top of the existing instance —
travel time is `distance x 60 / speed` minutes, each stop costs a fixed service
time, and every customer carries a delivery window `[ready, due]` (the time within
which service may *start*; a van that arrives early waits until `ready`, and is
**late** only if it arrives after `due`). The windows are **synthetic and
labelled** — seeded morning `[0, m]` / afternoon `[a, horizon]` / anytime slots —
in the same spirit as the rest of the repo's data.

Two things are then measured:

1. **A deterministic on-time audit.** The capacity-only Clarke-Wright plan is
   *time-blind*: it never consulted the clock. `audit_service` replays each route's
   schedule (depart depot at `t = 0`, add travel, wait to `ready`, add the service
   time) and counts, per vehicle, how many stops land after their `due` and by how
   many minutes. Because the savings plan and the arithmetic are both deterministic,
   `deliverables/service_audit.csv` is byte-for-byte reproducible.

2. **The VRPTW solve.** `solve_vrptw` reuses the same OR-Tools `RoutingModel` as the
   base solver — identical distance objective and capacity dimension — and adds a
   **Time** dimension whose transit is `service(from) + travel(from, to)`. Each
   node's cumulative-time variable is constrained to its `[ready, due]` window, with
   slack so a van may wait when early. Every window is therefore satisfied by
   construction; the extra distance over the time-blind plan is the price of that
   service guarantee. Like any time-limited metaheuristic its distance wobbles a
   fraction of a percent between runs, so — unlike the audit — the VRPTW number is
   reported, not pinned.

The honest comparison has two readings. Against the *time-blind savings plan* the
premium is small (the time-aware optimizer's better routing largely offsets the
constraint); against the *time-blind OR-Tools optimum* it is larger and is the
intrinsic cost of the windows, holding the optimizer fixed. Both are reported.

## Robustness under demand uncertainty (the stress test)

`routeopt/robustness.py` asks the question the stochastic-VRP literature asks of
any a-priori plan: **how does it survive the day it was planned for?** Three
pieces:

1. **Scenarios.** `sample_demand_scenarios` draws K realized-demand vectors
   around the forecast: `round(q_i * (1 + cv * z))` with `z` standard normal
   truncated at ±3σ, clipped to `[0, Q]` (0 = the customer cancelled; the van
   still drives there, because a-priori routes are fixed). The RNG is seeded from
   a fixed base plus an instance signature, so the scenario set is byte-for-byte
   reproducible.
2. **Recourse.** `simulate_recourse` drives each planned route in order under
   each scenario. When the next customer's realized demand exceeds what is left
   in the van, the van makes the classic **detour-to-depot** restocking round
   trip — extra distance `d(c, depot) + d(depot, c)` — and continues. No
   re-sequencing or reassignment is modelled: this measures the *plan*, and a
   dispatcher re-optimizing live would do better. Reported per plan: the share
   of scenarios with at least one failure, expected restocks, expected / p95 /
   worst recourse distance, and the expected total (planned + mean recourse).
3. **The headroom lever.** `plan_with_headroom` re-plans with the vans treated
   as 5/10/15% smaller (same fleet) and evaluates those plans against the *real*
   capacity. Slack costs planned kilometres and buys resilience; the sweep is
   the price-of-robustness curve in `deliverables/robustness.svg`.

Determinism is engineered, not hoped for: Clarke-Wright is deterministic by
construction, and the OR-Tools plans use a fixed **solution limit** rather than
a wall-clock limit — the routing search is single-threaded with no time-based
decisions, so the same instance and limit reproduce the identical routes on
every run (the test suite asserts this). One honest artifact: neither heuristic
is monotone in planning capacity, so a buffered plan can occasionally come out
*shorter* than the unbuffered one.

## Heterogeneous fleet mix — the Fleet Size and Mix VRP

`routeopt/fleetmix.py` drops the one assumption every other layer keeps: that
all vans are the same. The **Fleet Size and Mix VRP** (Golden, Assad, Levy &
Gheysens, 1984) asks which *combination* of vehicle types serves the demand at
the lowest total cost, where each type has its own capacity, fixed deployment
cost, and per-kilometre rate.

The model is the base CVRP `RoutingModel` with three heterogeneous extensions:

- **A typed pool.** For each catalogue type, `ceil(total_demand / capacity) + 2`
  candidate vans are created — enough that any single type could serve the whole
  demand alone, with slack so routing does not degenerate into tight bin
  packing. The capacity dimension takes one capacity *per pool van*.
- **Money as the objective.** Each van pays its type's EUR/km through a
  per-vehicle arc-cost evaluator (`SetArcCostEvaluatorOfVehicle`; integer cents,
  since OR-Tools objectives are integral), plus its type's fixed cost
  (`SetFixedCostOfVehicle`), charged only if the van actually leaves the depot.
  Minimising that objective *is* choosing the mix: a pool van that does not earn
  its fixed cost stays parked.
- **A like-for-like comparison.** The mixed-pool solve is scored against each
  homogeneous option ("all-small", "all-medium", "all-large") under the
  identical cost model. A homogeneous option whose van cannot carry the largest
  single order is infeasible by construction and dropped.

The default catalogue anchors on the instance's own van: `medium` *is* that van
(with the repo's illustrative EUR 1.00/km and 250 g/km), `small` carries half at
EUR 0.70/km and EUR 40/day fixed, `large` carries double at EUR 1.35/km and
EUR 90/day fixed. Both cost axes rise with size but *fall per unit of capacity*
— the economies of scale that make the mix a genuine optimisation question
rather than an arithmetic one. All figures are labelled estimates, not
certified rates.

Every reported number (distance, fixed / variable / total EUR, CO2, longest
route) is recomputed in floats from the extracted routes and the catalogue — the
integer objective only *guides* the search — so the deliverables are exact
functions of the routes and the test suite recomputes them by hand. The layer
always runs under a fixed **solution limit**, never a wall clock, so
`deliverables/fleet_mix.{csv,svg,md}` regenerate byte-identically. Two honest
notes: the plans are heuristic solutions under a fixed budget, not proven
optima — and because the mixed pool has a much larger search space, the mixed
solve can trail a homogeneous one under the same budget (the deliverable
reports whatever falls). The route-duration cap the longest-route column asks
for is the next section.

## Driver shifts and working time

The longest-route column above is a *proxy* for service: the layer that turns it
into a constraint models the working day explicitly. A route's day is exactly
three kinds of minute — **drive** (`distance x 60 / speed`, the time-window
layer's convention), **service** (a fixed number of minutes at each customer)
and **break** — under a duty envelope `S`, a daily driving limit, and a break of
`B` minutes required before continuous driving passes `D`.

The defaults (`S = 600`, driving `<= 540`, `D = 270`, `B = 45`, at 40 km/h and
5 min/stop) are **informed by EU Regulation (EC) No 561/2006** — art. 6 daily
driving, art. 7 breaks — and are **not an implementation of it**. Not modelled:
the 15+30 split break, the twice-weekly 10-hour driving extension, multi-manning,
daily and weekly rest between shifts, and the Working Time Directive's own
limits. A service stop is deliberately *not* counted as rest, which is the
conservative reading.

**The break scheduler** walks a route leg by leg, splitting a leg across as many
breaks as it needs: it drives until continuous driving would exceed `D`, rests
`B`, and resets. `duty = drive + service + break` holds by construction, and the
walk never rests after the last kilometre — so a route whose drive+service span
is `t` needs at most `ceil(t / D) - 1` breaks.

**The solver bound.** OR-Tools gets one added **Duty** dimension whose transit is
`service(from) + travel(from, to)`; with the start cumulative fixed at zero, a
capacity on that dimension is exactly a per-route span limit. But the dimension
knows nothing about breaks, so the bound handed to it must already have paid for
them. From the count above, spans in the window `(k*D, (k+1)*D]` cost at most `k`
breaks, so the largest span affordable with `k` breaks is
`min((k+1)*D, S - k*B)`; the bound is the best of those, capped by the daily
driving limit (driving is bounded by the span). On the defaults that is **540
min** of drive+service: one break, `540 + 45 = 585 <= 600`. The bound is
conservative — service minutes are counted against the driving threshold — so a
returned plan is legal *after* scheduling, and the audit re-checks it rather
than asserting it.

**Sizing the pool.** A routing model with too few vans for the cap has no
solution for a solution limit to stop at, so the search would never end. A
duty-aware greedy construction (nearest-neighbour with an extra admission test:
reach it, serve it, and still get home inside the bound) settles that in one
pass: its van count plus two slack vans sizes the pool, and its failure is a
*proof* of infeasibility at any fleet size — one customer's out-and-back trip
alone exceeds the cap. The reported answer is therefore how many vans a shift
*needs*, compared against the fleet the depot owns.

Everything here runs under a fixed **solution limit**, so
`deliverables/driver_shifts.{csv,svg,md}` regenerate byte-identically. Honest
limits: one flat speed, no congestion, no time windows and no depot loading
time, so a real duty is longer than any number reported; and the capped plans
are heuristic solutions under a fixed budget, so the distance curve need not be
monotone in the cap.

## Reproducibility

Instances are generated with fixed NumPy seeds (`data/generate_instances.py`), so
the committed JSON is byte-for-byte reproducible. OR-Tools' GLS is time-limited,
so its final distance can wobble by a fraction of a percent between runs and
machines; the baselines are deterministic. The sensitivity, robustness, fleet-mix
and driver-shift layers avoid the wobble entirely (savings heuristic; fixed
solution limits), so their committed deliverables regenerate byte-identically.
The route map is the one drawn deliverable whose numbers come from a wall-clock
solve, so it is re-inked rather than re-solved: `--replot` reads the routes back
out of the committed `route_plan.csv` and redraws Plate 01, which keeps the
design current without moving the figures underneath it.
