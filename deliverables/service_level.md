# Service level & time windows (VRPTW) - `n60`

- **60** customers on synthetic delivery windows (**labelled estimates**): 26 morning `[0,210]`*, 27 afternoon `[210,480]`, 7 anytime. Day **480 min**, service **5 min/stop**, speed **40 km/h** (travel = distance x 1.50 min).

## The time-blind plan misses promises it never saw

The Clarke-Wright savings plan is capacity-optimal but ignores time. Audited against the windows (deterministic):

- **41/60 on time (68.3%)**, 19 late.
- Worst delivery **107 min** late; total lateness **968 min** across the fleet.
- Time-blind distance **1,046.2 km** on 10 vans.

Per-vehicle audit: `service_audit.csv`.

## Making the solver time-aware guarantees every window

The same OR-Tools engine with a **Time** dimension and hard windows (VRPTW):

- **60/60 on time (100.0%)** - every window kept, by construction.
- Distance **1,059.2 km** on 10 vans (solve 8.0s).
- Price of the guarantee vs the time-blind savings plan: **+1.2% distance** for **+19 on-time deliveries**.

> The VRPTW figures come from a **time-limited metaheuristic**, so the distance
> (and hence the premium) can wobble a fraction of a percent between runs. The
> deterministic savings-plan audit above does not.

*Windows, speed, service and cost-of-time are **illustrative synthetic assumptions**, not certified; distance units are treated as kilometres.

