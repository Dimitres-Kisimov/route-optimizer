# Business case — route-optimizer

*An enterprise-framed read of the same solver this repo builds. The distributor
is an illustrative scenario; every distance number is measured by `routeopt` on
the seeded synthetic instances, and every euro/CO2 figure is an **estimate** with
its assumptions stated, not a measured result.*

## Situation

**Meridian Industrieteile GmbH** (fictional, drawn to type) runs its own last-mile
delivery: one depot, a fleet of capacity-limited vans, and every morning the same
job — a fresh list of customers with locations and order sizes that has to be cut
into routes before the vans roll. Today a dispatcher builds those routes by hand
on a map, the way most distributors this size do: group by postcode, sequence by
feel. It works, but "works" and "tight" are different numbers, and the difference
is diesel, driver-hours and CO2 that recur every single delivery day.

## Problem (quantified)

This is the **Capacitated Vehicle Routing Problem (CVRP)** — NP-hard, so the honest
question isn't "can it be solved" but "how much does a real optimizer beat what a
dispatcher would reach for by hand?" On the seeded 60-customer instance (448 units
of demand, capacity-50 vans), measured by this repo:

```
Nearest-neighbour        1,445.8 km   10 vehicles   (a naive greedy sweep)
Clarke-Wright savings    1,046.2 km   10 vehicles   (the classic 1964 heuristic)
OR-Tools (GLS, 8s)         998.3 km   10 vehicles   (the optimizer)
```

- The optimizer drives **4.6% fewer km than the strong Clarke-Wright baseline**,
  and **31% fewer than a naive nearest-neighbour sweep**, in 8 seconds of CPU.
- Both good methods parked 2 of the 12 available vans — fewer routes, same service.

## Impact (estimated — assumptions stated)

Turning kilometres into money needs assumptions, so here they are, all labelled as
estimates and easy to change:

- **Operating cost:** ~€1.00 per van-km (fuel + driver time + wear, German light
  commercial, *estimate*).
- **Delivery days:** ~250 per year.
- **Per-day distances** as measured above, held representative of a typical round.

| Comparison | km saved / day | km saved / year | Est. € / year | Est. CO2 saved / year |
|---|---|---|---|---|
| Optimizer vs naive hand/greedy planning | 447.5 | ~111,900 | **~€111,900** | ~28 t |
| Optimizer vs an already-good savings heuristic | 47.9 | ~12,000 | **~€12,000** | ~3 t |

*(CO2 at ~250 g/km for a diesel van — estimate.)*

The honest headline is the split: the **big** win (~€112k/yr) is moving off hand/
naive planning onto *any* real optimizer; the **incremental** win of the
metaheuristic over the classic 1964 heuristic is a genuine but smaller ~€12k/yr.
On the 100-customer instance that incremental gap narrows to ~1% — the savings
heuristic finds near-optimal structure there, which the repo shows rather than
hides.

## Stakeholders & use case

- **Dispatch / transport planning** — gets a printable route plan each morning
  instead of a hand-drawn map; the plan says which van visits whom, in what order.
- **Finance / sustainability** — a defensible, reproducible cost and CO2 line, with
  the assumptions visible.
- **Operations lead** — a lever to run the same service on fewer vans.

## Deliverable

A route plan and a before/after comparison chart (`deliverables/routes.png`) that a
dispatcher can act on directly, produced by a solver that runs on CPU in seconds
with no API keys and nothing to download at run time.

## Honesty note

All instances are synthetic-but-structured (seeded). The distance results are
measured; the euro and CO2 figures are estimates built on the stated per-km and
per-day assumptions — change those and the totals scale linearly. The point is the
method and the measured routing gap, both of which carry over to real data
unchanged.
