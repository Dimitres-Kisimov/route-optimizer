# Driver shifts & working time — `n60`

- **60** customers, fleet **12** vans. A working day is modelled as **driving** (distance x 60 / 40 km/h), **service** (5 min per stop) and **breaks**, under a **600 min duty envelope**, a **540 min daily driving limit**, and a **45 min break** before **270 min** of continuous driving.
- These numbers are **informed by EU Regulation (EC) No 561/2006** (art. 6 daily driving, art. 7 breaks) — they are **not a compliance certification**. The split 15+30 break, the twice-weekly 10-hour driving extension, multi-manning, daily and weekly rest, and the Working Time Directive's own limits are **not modelled**, and a service stop is deliberately **not** counted as rest.
- Engine: the same or-tools CVRP model as the base solver plus a **Duty** dimension whose per-vehicle span is capped, pinned to a fixed **solution limit (200)** — deterministic, so this file regenerates byte-identically. The span handed to the solver (540 min of drive+service) is the duty cap with the breaks the rules will insert already paid for, so the plan is legal *after* scheduling — and the audit below re-checks it rather than assuming it.

## Today's plan, audited

The deterministic Clarke-Wright savings plan is shift-blind. Walking each route minute by minute and inserting the breaks the rules require:

- **10/10 vans** finish inside the 600-min envelope; worst duty **267 min**.
- **10/10 vans** are inside the 540-min driving limit.
- Worst continuous drive **227 min** against the 270-min break threshold; **0** break(s) inserted across the fleet.

| Van | Stops | Distance (km) | Drive (min) | Service (min) | Breaks | Break (min) | **Duty (min)** | Over cap (min) |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| V1 | 5 | 111.0 | 166 | 25 | 0 | 0 | **191** | 0 |
| V2 | 7 | 118.7 | 178 | 35 | 0 | 0 | **213** | 0 |
| V3 | 5 | 99.9 | 150 | 25 | 0 | 0 | **175** | 0 |
| V4 | 5 | 115.1 | 173 | 25 | 0 | 0 | **198** | 0 |
| V5 | 6 | 72.6 | 109 | 30 | 0 | 0 | **139** | 0 |
| V6 | 8 | 138.2 | 207 | 40 | 0 | 0 | **247** | 0 |
| V7 | 6 | 111.7 | 167 | 30 | 0 | 0 | **197** | 0 |
| V8 | 8 | 151.3 | 227 | 40 | 0 | 0 | **267** | 0 |
| V9 | 6 | 80.2 | 120 | 30 | 0 | 0 | **150** | 0 |
| V10 | 4 | 47.7 | 72 | 20 | 0 | 0 | **92** | 0 |

## What a shorter shift costs

The cap walked down, each point re-solved and re-audited under the identical deterministic budget. The uncapped solve is the reference: **1,001.6 km** on **10** vans.

| Shift cap (min) | Feasible | Vans | Distance (km) | Longest route (km) | Worst duty (min) | Worst continuous drive (min) | Breaks |
|---:|:--:|---:|---:|---:|---:|---:|---:|
| 480 | yes | 10 | 1,001.6 | 141.5 | 254 | 212 | 0 |
| 420 | yes | 10 | 1,001.6 | 141.5 | 254 | 212 | 0 |
| 360 | yes | 10 | 1,010.3 | 141.1 | 247 | 212 | 0 |
| 300 | yes | 10 | 1,014.3 | 141.1 | 254 | 212 | 0 |
| 240 | yes | 10 | 1,054.4 | 141.5 | 237 | 212 | 0 |
| 210 | yes | 11 | 1,177.1 | 132.6 | 209 | 199 | 0 |
| 180 | **no** | — | — | — | — | — | — |

## The read

- Today's shift-blind savings plan already finishes inside the modelled 10-hour envelope: worst duty 267 min on 10 vans, 333 min of headroom. The EU-informed limits are slack on this instance - the cap has to come down before it costs anything.
- Worst continuous drive in that plan: 227 min against the 270-min break threshold (43 min of slack), so the rules insert 0 break(s) - the break machinery is exercised by the tests, not by this data.
- Loosest modelled cap (480 min): 10 vans, 1,001.6 km - +0.0% against the uncapped solve (1,001.6 km on 10 vans) under the same search budget.
- Tightest cap that still has a plan (210 min): 11 vans, 1,177.1 km - +17.5% distance and +1 van(s) against the uncapped solve. That is the price of a 3.5-hour round, and it is the service consequence the fleet-mix layer could only point at.
- Every feasible cap here still fits inside the depot's 12 vans (widest need: 11).
- At 180 min there is no plan at *any* fleet size: one customer's out-and-back round trip already exceeds the cap. That is a proof, not a search-budget artifact.

**Honest caveats.** This is a *modelled* working day, not a compliance tool — see the rule list above for what is left out. Travel time is straight-line distance at a single flat speed with no congestion, no time windows and no depot loading time, so a real duty would be longer than every number here. Every capped plan is a good heuristic solution under a fixed search budget, **not a proven optimum**: the distance curve need not be monotone in the cap. An **infeasible** cap is the one exception: it is proved by construction (some customer's out-and-back round trip alone exceeds the cap), not inferred from a search that gave up. The break rule is exercised and hand-checked in the test suite; whether it fires on a given instance depends on that instance's driving times.

