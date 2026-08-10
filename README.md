# route-optimizer

[![CI](https://github.com/Dimitres-Kisimov/route-optimizer/actions/workflows/ci.yml/badge.svg)](https://github.com/Dimitres-Kisimov/route-optimizer/actions/workflows/ci.yml)

This solves the last-mile routing problem a distributor actually faces every
morning: a depot, a list of customers with locations and order sizes, and a
fleet of capacity-limited vans — which van visits whom, in what order, so that
the total distance driven is as small as possible. Fewer kilometres is directly
fewer euros and less CO2, so the gap between a decent plan and a good one is
money. It is the **Capacitated Vehicle Routing Problem (CVRP)**, and it is
NP-hard, so the interesting question is not "can we solve it" but "how much does
a real optimizer beat the heuristic a dispatcher would reach for by hand?"

So I built both and measured. The baseline is the classic **Clarke-Wright savings**
algorithm (1964), written from scratch. The optimizer is **Google OR-Tools**'
CVRP solver with guided local search. The whole thing runs on CPU in seconds, on
synthetic-but-structured instances, with no API keys and nothing to download at
run time.

![OR-Tools routes on the 60-customer instance](deliverables/routes.png)

## The result

On the seeded 60-customer instance (448 units of demand, capacity-50 vans):

```
Nearest-neighbour        1,445.8   10 vehicles   (naive greedy sweep)
Clarke-Wright savings    1,046.2   10 vehicles   (the classic 1964 heuristic)
OR-Tools (GLS, 8s)         998.3   10 vehicles
```

**OR-Tools cut total distance 4.6% below Clarke-Wright savings, and 31% below a
naive nearest-neighbour sweep, in 8 seconds.** Both the savings baseline and the
solver parked 2 of the 12 available vans. That ~5% over an *already good* baseline
is the honest headline: savings is strong, and squeezing the last few percent out
of it is exactly what the metaheuristic is for. On the 100-customer instance the
gap is smaller (~1%) — the savings heuristic happens to find near-optimal
structure there, which is a fair thing to show rather than hide.

## Fleet-size sensitivity (what-if)

Cutting one instance is a point answer; a fleet planner works a curve. So there
is a second layer that asks *how big should the fleet be at all?* It sweeps the
sizing lever — **van capacity** (bigger vans ⇒ fewer vans) — with the
deterministic Clarke-Wright savings heuristic and reads off, for each resulting
fleet size, the total distance, the longest single route (a **service** proxy —
time to the last customer), and a labelled cost/CO2 line.

![Fleet-size sensitivity frontier for the 60-customer instance](deliverables/fleet_sensitivity.svg)

The honest finding is the direction. Because the model minimises distance with no
fixed per-van cost, **fewer, fuller vans win on both distance and CO2** — the
thing you trade away is service. On `n60` (`deliverables/fleet_sensitivity.csv`):

```
Operating point — 10 vans (capacity 51): 1,017.2 km, ~254.3 kg CO2, ~€1,017/round.
Consolidating 10 → 9 vans:  distance −5.6%, CO2 −5.6%, longest route +0.1% (service).
Leanest modelled 5 vans:    distance −33.7%, CO2 −33.7%, longest route +4.4% (service).
Adding a van 10 → 11:       distance +5.4%, CO2 +5.4%, longest route −0.3% (service).
```

So the "more vans = more driving" intuition is backwards here: **more vans buys
shorter routes (better service) at the cost of more total distance/CO2, not less.**
Cost is variable only (distance × €/km); a real fixed per-van cost would push the
optimum further toward consolidation — the fleet-mix layer below now prices
exactly that. The **€1.00/km and 250 g/km factors are
illustrative estimates, not certified** — distance is straight-line synthetic-grid
units treated as km. Full table and the drawn frontier:
`deliverables/fleet_sensitivity.md` / `.csv` / `.svg`.

## Time windows & service level (VRPTW)

Capacity is not the only promise a distributor makes. Deliveries come with a
*window* — "before noon", "after 2pm" — and the base plan never looks at the
clock. So there is a third layer that adds **time windows** and asks the service
question: *how many promises does the time-blind plan already keep, and what does
guaranteeing the rest cost?*

On `n60` with synthetic morning / afternoon / anytime windows (labelled estimates:
an 8-hour day, 40 km/h, 5 min/stop):

- The **time-blind Clarke-Wright** plan keeps **41 of 60** windows (68%) — 19
  deliveries land late, the worst **107 minutes** past due. That audit is
  deterministic (`deliverables/service_audit.csv`).
- Giving the **same OR-Tools engine a time dimension** (the classic **VRPTW**)
  keeps **all 60** windows by construction, for **+1.2% distance** over the
  time-blind plan — 19 late deliveries fixed for barely more driving, because the
  better routing largely pays for the added constraint. (Held against the
  time-blind OR-Tools *optimum* rather than the savings plan, the intrinsic price
  of the window constraint is closer to ~5%.)

Full write-up: `deliverables/service_level.md`. The windows are **synthetic and
labelled**; the VRPTW distance comes from a time-limited metaheuristic, so it
wobbles a fraction of a percent between runs, while the on-time audit of the
deterministic savings plan does not.

## Robustness under demand uncertainty (stress test)

Every number above is optimal *for the forecast*. On the day, the quantity at
the door differs — and a van planned to 100% of capacity has no slack to absorb
it. So there is a fourth layer that stress-tests the plans the standard
stochastic-VRP way: drive each plan, in planned order, through **200 seeded
demand scenarios** (±15% multiplicative noise — a labelled assumption), and when
a van can't serve the next customer it makes the classic **detour-to-depot
restocking trip**. Both engines are pinned deterministic for this (Clarke-Wright
by construction, OR-Tools by a fixed solution limit instead of a wall clock), so
every number regenerates byte-identically.

![Robustness vs capacity headroom for the 60-customer instance](deliverables/robustness.svg)

The honest findings on `n60` (`deliverables/robustness.csv`):

- **Both zero-buffer plans are fragile**: packed to 100% max route load, they hit
  at least one capacity failure in **~96% of scenarios**. The optimized plan is
  *not* more fragile than the baseline here — it fails as often but recovers
  cheaper (**117 vs 178 km** expected recourse/day), so it stays ahead under
  noise: **1,119 vs 1,225 km** expected total.
- **A small buffer pays for itself.** Re-planning with just **5% capacity
  headroom** costs **+3.0% planned km** but cuts failing scenarios **96% → 44%**
  and the *expected* day by **4.6%** (1,067 km) — the recourse saved outweighs
  the planned km added, the classic flaw-of-averages result.
- **Deep buffers buy near-certainty, not economy**: at 15% headroom the failure
  rate is ~1%, for +13.4% planned km. Where on that curve to sit is a business
  choice; the table prices it.

Full table and write-up: `deliverables/robustness.md`. The noise level is
**modelled, not measured** — synthetic customers have no order history — and the
recourse is the textbook policy; a dispatcher re-planning live would do better.

## Heterogeneous fleet mix (FSM)

Every layer above assumes the fleet is a row of identical vans. A real
distributor shops a *catalogue* — small vans that are cheap to own and cheap per
kilometre but carry little, large ones that carry double and cost more on both
axes — and asks the question Golden, Assad, Levy and Gheysens posed in 1984 as
the **Fleet Size and Mix VRP**: *which combination of van sizes serves today's
demand at the lowest total cost?* It is also the layer that finally prices the
caveat the fleet-size sweep had to leave open — its cost was variable-only, with
fixed per-van cost named as the missing force toward consolidation. Now it is in
the objective, with numbers.

The same OR-Tools engine gets a **pool** of candidate vans of every type
(per-vehicle capacities), each paying its type's EUR/km (per-vehicle arc costs)
plus a **fixed cost per deployed van** — so the objective is money, not
kilometres, and parking a van the demand does not justify is how the solver
saves it. The optimizer's mix is then scored against every homogeneous fleet
under the identical cost model, deterministically (fixed solution limit —
byte-identical reruns).

![Fleet mix cost comparison for the 60-customer instance](deliverables/fleet_mix.svg)

The honest findings (`deliverables/fleet_mix.csv`; illustrative catalogue:
capacity 25/50/100 at EUR 40/60/90 fixed + EUR 0.70/1.00/1.35 per km):

- On `n60` **consolidation wins outright**: 5 large vans (EUR 1,325/day)
  undercut the status-quo 10 mediums (EUR 1,606) by **17.5%** — distance
  −35.6%, CO2 −14.9% — and the mixed pool *agrees with* the all-large answer.
  The price is service: the longest route grows **+25.2%**.
- On `n30` the mix is genuine: **1 medium + 2 large** (EUR 628/day) beats the
  best single-size fleet (all-large, EUR 686) by **8.5%** and the status quo by
  14.7%. The tail of demand does not justify a third big van, so the optimizer
  tops up with a cheaper medium — 197 units on 200 units of fleet.

Full table and write-up: `deliverables/fleet_mix.md`. The catalogue costs are
**illustrative labelled estimates, not certified rates**, and every plan is a
heuristic under a fixed search budget, not a proven optimum — on a fixed budget
the mixed pool's larger search space can even trail a homogeneous solve, and
the deliverable reports whatever the numbers say.

## Run it

```bash
pip install ortools numpy matplotlib pandas
python data/generate_instances.py                              # seeded instances -> data/instances/
python -m routeopt --instance data/instances/n60.json --compare   # print all three methods + the gap
python -m routeopt --instance data/instances/n60.json --sweep-fleet  # fleet-size sensitivity (CSV+SVG+MD)
python -m routeopt --instance data/instances/n60.json --service   # time-window (VRPTW) service-level analysis
python -m routeopt --instance data/instances/n60.json --stress    # demand-uncertainty stress test (CSV+SVG+MD)
python -m routeopt --instance data/instances/n60.json --mix       # heterogeneous fleet-mix (FSM) comparison (CSV+SVG+MD)
python web/build_data.py --instance data/instances/n60.json    # web/data.js -> open web/index.html offline
pytest -q                                                      # 46 tests, ~40s
```

`python -m routeopt --instance ...` also writes the deliverables:
`deliverables/route_plan.csv` (vehicle, stop order, load, cumulative distance),
`deliverables/routes.png`, and `deliverables/summary.md`. Knobs: `--metric
manhattan`, `--time-limit 20`, `--compare`, `--no-deliverables`.

Open `web/index.html` (no server needed) for the interactive map: depot,
customers and colored routes on a canvas, a metrics panel, a toggle to overlay
the savings-heuristic routes for visual comparison, and light/dark.

## How it works

The maths — the CVRP formulation, the savings algorithm, and the exact OR-Tools
setup (capacity + distance dimensions, `PATH_CHEAPEST_ARC` first solution,
guided local search) — is written out in [`docs/METHOD.md`](docs/METHOD.md).

- `data/generate_instances.py` — deterministic clustered instances (N ≈ 30/60/100
  plus a hand-checkable tiny one) with a depot, integer demands, capacity and fleet.
- `routeopt/model.py` — instance loading + the distance matrix.
- `routeopt/heuristic.py` — Clarke-Wright savings and nearest-neighbour, from scratch.
- `routeopt/solver.py` — the OR-Tools CVRP solver.
- `routeopt/report.py` — the CSV / PNG / summary deliverables.
- `routeopt/sensitivity.py` — the fleet-size / cost / service / CO2 what-if sweep.
- `routeopt/timewindows.py` — time windows (VRPTW) on the OR-Tools engine plus the
  deterministic on-time / service-level audit of the time-blind plan.
- `routeopt/robustness.py` — the demand-uncertainty stress test: seeded scenarios,
  detour-to-depot recourse simulation, and the capacity-headroom sweep.
- `routeopt/fleetmix.py` — the heterogeneous fleet mix (Fleet Size and Mix VRP):
  a typed vehicle pool with per-vehicle capacities, EUR/km and fixed deployment
  costs, and the mixed-vs-homogeneous comparison.

## Limitations

I would rather state these than oversell:

- **Synthetic instances.** Coordinates and demands are generated, not real orders.
  The generator clusters customers to look like service neighbourhoods, but it is
  still made-up data.
- **Euclidean distances, not roads.** Distance is straight-line (a Manhattan L1
  option exists as a crude grid proxy). A production system would use a road-network
  distance/time matrix from an OSRM/Valhalla-style engine, and the routes would shift.
- **Single depot.** Everything starts from one depot. Time windows *are* now
  modelled (the VRPTW / service-level layer above), but on **synthetic** windows
  and a fixed per-stop service time; the fleet *can* now be heterogeneous (the
  fleet-mix layer), but its catalogue costs are illustrative estimates, not
  quotes. Multi-depot, driver shifts and variable service times are the next
  constraints, and OR-Tools supports all of them.
- **GLS is time-limited, so its final number wobbles** a fraction of a percent between
  runs. The baselines are deterministic; the headline gap is stable to within noise.
  (The robustness layer avoids this by pinning OR-Tools to a fixed *solution limit*
  instead — deterministic, at a small cost in solution quality.)
- **The stress test measures the plan, not the dispatcher.** Scenarios are drawn from
  an assumed ±15% demand noise (synthetic customers have no order history), and the
  recourse is the textbook detour-to-depot policy with no live re-optimization. The
  failure rates and recourse kilometres are modelled, not measured, and scale with
  the assumed noise.

## License

© 2026 Dimitres Kisimov — all rights reserved; published for portfolio review. See LICENSE. Data is synthetic; OR-Tools is Apache-2.0. See
[CREDITS.md](CREDITS.md).
