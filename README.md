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

## Run it

```bash
pip install ortools numpy matplotlib pandas
python data/generate_instances.py                              # seeded instances -> data/instances/
python -m routeopt --instance data/instances/n60.json --compare   # print all three methods + the gap
python web/build_data.py --instance data/instances/n60.json    # web/data.js -> open web/index.html offline
pytest -q                                                      # 11 tests, ~12s
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

## Limitations

I would rather state these than oversell:

- **Synthetic instances.** Coordinates and demands are generated, not real orders.
  The generator clusters customers to look like service neighbourhoods, but it is
  still made-up data.
- **Euclidean distances, not roads.** Distance is straight-line (a Manhattan L1
  option exists as a crude grid proxy). A production system would use a road-network
  distance/time matrix from an OSRM/Valhalla-style engine, and the routes would shift.
- **Single depot, homogeneous fleet, no time windows.** All vans are identical and
  start from one depot; there are no delivery time windows, service times, or driver
  shifts. Those are the obvious next constraints and OR-Tools supports all of them.
- **GLS is time-limited, so its final number wobbles** a fraction of a percent between
  runs. The baselines are deterministic; the headline gap is stable to within noise.

## License

© 2026 Dimitres Kisimov — all rights reserved; published for portfolio review. See LICENSE. Data is synthetic; OR-Tools is Apache-2.0. See
[CREDITS.md](CREDITS.md).
