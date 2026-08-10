# Heterogeneous fleet mix (FSM) — `n60`

- **60** customers, total demand **448**. The **Fleet Size and Mix VRP** (Golden et al., 1984): which combination of van sizes serves the demand at the lowest total cost? The objective is **money** (fixed cost per deployed van + EUR/km per type), not kilometres.
- Engine: the same or-tools model as the base CVRP, with per-vehicle capacities, per-vehicle EUR/km arc costs, and per-vehicle fixed costs; pinned to a fixed **solution limit (200)** — deterministic, so this file regenerates byte-identically.
- All catalogue costs are **illustrative labelled estimates, not certified rates**; distance is straight-line synthetic-grid units treated as km.

## The catalogue

| Type | Capacity | Fixed (EUR/day) | Variable (EUR/km) | CO2 (g/km) |
|---|---:|---:|---:|---:|
| small | 25 | 40 | 0.70 | 180 |
| medium | 50 | 60 | 1.00 | 250 |
| large | 100 | 90 | 1.35 | 330 |

Per unit of capacity, both cost axes fall with size (economies of scale) — that is what makes the mix a genuine question rather than an arithmetic one.

## The options

| Option | Fleet | Vans | Distance (km) | Longest route (km) | Fixed (EUR) | Variable (EUR) | **Total (EUR/day)** | Est. CO2 (kg) |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| optimized mix | 5 large | 5 | 648.5 | 177.2 | 450 | 875 | **1,325** | 214.0 |
| all-small | 19 small | 19 | 1,798.0 | 139.6 | 760 | 1,259 | **2,019** | 323.6 |
| all-medium | 10 medium | 10 | 1,006.4 | 141.5 | 600 | 1,006 | **1,606** | 251.6 |
| all-large | 5 large | 5 | 648.5 | 177.2 | 450 | 875 | **1,325** | 214.0 |

## The read

- Status quo - all-medium (10 medium, today's van size): EUR 1,606/day (EUR 600 fixed + EUR 1,006 variable), 1,006.4 km, ~251.6 kg CO2.
- Cheapest modelled option - all-large (5 large): EUR 1,325/day, -17.5% cost vs the status quo; distance -35.6%, CO2 -14.9%, longest route +25.2% (service).
- The optimizer's mixed fleet (5 large) lands at EUR 1,325 and matches the best single-size fleet (all-large, EUR 1,325) by +0.0% - a heuristic under a fixed search budget, reported as it falls.

**Honest caveats.** Every plan is a good heuristic solution under a fixed search budget, **not a proven optimum** — and the mixed pool's larger search space means the mixed solve can occasionally trail a homogeneous one under the same budget; the table reports whatever the numbers say. A homogeneous option is dropped when its van cannot carry the largest single order. The catalogue prices are round illustrative figures; real quotes (lease, insurance, driver, fuel) would move the crossover points, which is exactly what this table is built to recompute. No route-duration cap is modelled — the longest-route column is the service price of consolidating into fewer, bigger vans.

