# Robustness under demand uncertainty — `n60`

- **60** customers, forecast demand **448**, capacity **50**, fleet **12**. Each plan is driven, in planned order, through **200** seeded demand scenarios (multiplicative noise, cv **0.15**, truncated at ±3σ, seed 11) — a **modelled assumption, not measured data**.
- When a van cannot serve the next customer it makes a **restocking round trip** to the depot (classic detour-to-depot recourse) and continues; no live re-optimization is modelled. Distance units are treated as km.
- Both engines are deterministic here — Clarke-Wright by construction, or-tools by a fixed solution limit (200) instead of a wall clock — so this file regenerates byte-identically.

| Engine | Headroom | Vans | Planned km | Max route load | Fail scen. | Mean restocks | Mean extra km | p95 extra km | Expected total km |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| clarke-wright | 0% | 10 | 1,046.2 | 100% | 96% | 2.65 | 178.3 | 333.7 | 1,224.5 |
| clarke-wright | 5% | 10 | 1,039.1 | 94% | 54% | 0.70 | 40.7 | 131.2 | 1,079.8 |
| clarke-wright | 10% | 11 | 1,072.1 | 90% | 21% | 0.23 | 12.8 | 74.9 | 1,084.9 |
| clarke-wright | 15% | 12 | 1,145.7 | 84% | 1% | 0.01 | 0.6 | 0.0 | 1,146.2 |
| or-tools | 0% | 10 | 1,001.6 | 100% | 96% | 2.17 | 117.4 | 214.4 | 1,119.0 |
| or-tools | 5% | 10 | 1,032.0 | 94% | 44% | 0.52 | 35.4 | 108.7 | 1,067.4 |
| or-tools | 10% | 11 | 1,093.3 | 90% | 17% | 0.19 | 8.1 | 57.6 | 1,101.4 |
| or-tools | 15% | 11 | 1,136.0 | 84% | 1% | 0.01 | 0.9 | 0.0 | 1,136.8 |

## The read

- On the forecast, or-tools plans -4.3% distance vs clarke-wright; under demand noise it fails in 96% of scenarios (cw: 96%), expected recourse 117.4 km/day (cw: 178.3).
- Counting expected recourse, the plans land at 1,119.0 km (or-tools) vs 1,224.5 km (clarke-wright) per day.
- Planning with 5% capacity headroom costs +3.0% planned km but cuts failing scenarios 96% -> 44% and the expected day -4.6% - the cheapest expected day in the sweep.
- The deepest modelled buffer (15%) trades +13.4% planned km for a 1% failure rate and 0.01 expected restocks/day (0% buffer: 2.17).

**Honest caveats.** The noise level is an assumption (no order history exists for synthetic customers); failure rates scale with it. Recourse is the textbook policy — a real dispatcher would re-sequence or reassign live and do better. The or-tools plans are good heuristic solutions under a fixed search budget, not proven optima, and neither heuristic is monotone in planning capacity — a tighter capacity can occasionally yield a *shorter* plan. 'Max route load' is the plan's tightest van under the *forecast* — the plans differ in how much slack they carry, which is exactly what the table prices out.

