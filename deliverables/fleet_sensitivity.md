# Fleet-size sensitivity — `n60`

- Customers **60**, total demand **448**. Engine: **Clarke-Wright savings** (deterministic). Van capacity is swept; the number of vehicles is what the heuristic then needs.
- CO2 at **250 g/km** and cost at **EUR 1.00/km** are **illustrative estimates**, not certified; distance units are treated as km.

| Vehicles | Van capacity | Total distance (km) | Longest route (km) | Est. cost (EUR) | Est. CO2 (kg) |
|---:|---:|---:|---:|---:|---:|
| 5 | 100 | 674.9 | 156.3 | 675 | 168.7 |
| 6 | 90 | 741.8 | 167.6 | 742 | 185.4 |
| 7 | 75 | 803.7 | 155.9 | 804 | 200.9 |
| 8 | 64 | 894.4 | 150.5 | 894 | 223.6 |
| 9 | 56 | 960.7 | 149.9 | 961 | 240.2 |
| 10 | 51 | 1,017.2 | 149.7 | 1,017 | 254.3 |
| 11 | 45 | 1,072.1 | 149.3 | 1,072 | 268.0 |
| 12 | 42 | 1,145.7 | 141.0 | 1,146 | 286.4 |
| 13 | 38 | 1,233.3 | 141.0 | 1,233 | 308.3 |
| 14 | 37 | 1,291.5 | 141.1 | 1,292 | 322.9 |
| 15 | 33 | 1,372.9 | 140.8 | 1,373 | 343.2 |
| 16 | 32 | 1,436.7 | 140.0 | 1,437 | 359.2 |
| 17 | 30 | 1,471.4 | 135.0 | 1,471 | 367.8 |
| 18 | 29 | 1,540.9 | 135.0 | 1,541 | 385.2 |
| 20 | 26 | 1,707.1 | 135.0 | 1,707 | 426.8 |

## The trade-off

- Operating point - 10 vans (capacity 51): 1,017.2 km, ~254.3 kg CO2 (illustrative at 250 g/km), ~EUR 1,017.
- Consolidating 10 -> 9 vans (bigger vans): total distance -5.6% and CO2 -5.6%, while the longest route moves +0.1% (service).
- Leanest modelled fleet - 5 vans: distance -33.7% and CO2 -33.7% vs the operating point, but the longest route +4.4% (the service cost).
- Adding a van 10 -> 11: total distance +5.4% and CO2 +5.4%, longest route -0.3% (service).

Cost here is **variable only** (distance x EUR/km). A fleet also carries a fixed per-van cost (purchase, insurance, driver); adding it shifts the optimum further toward fewer vans. The frontier is intentionally left as variable cost so a planner can layer their own fixed cost on top.

