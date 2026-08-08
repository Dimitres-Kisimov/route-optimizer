"""Robustness under demand uncertainty — the stress test a plan never gets on paper.

Every plan in this repo is optimal *for the forecast*: the demands the routes
were built on. On the day, the quantity at the door differs — a customer adds a
box, another cancels — and a van that was loaded to 96% of capacity suddenly
cannot serve its last two stops. The classic question from the stochastic-VRP
literature is therefore not "how short is the plan?" but **"how well does the
plan survive the day it was made for?"**

This module answers it the standard way — *a-priori* route evaluation with
**detour-to-depot recourse**:

1. **Scenarios.** K seeded demand scenarios are sampled around the forecast
   (multiplicative truncated-normal noise, rounded to whole units, clipped to
   ``[0, capacity]``). Same seed ⇒ byte-identical scenarios, every run.
2. **Recourse.** Each plan drives its routes *in the planned order* under each
   scenario. When the load needed at the next customer exceeds what is left in
   the van, the van makes a **restocking round trip** — back to the depot,
   reload, return to that customer, continue. That detour distance is the price
   of the forecast being wrong. (No re-optimization: a dispatcher who re-plans
   live would do better; this measures the *plan*, worst-case-honest.)
3. **The lever.** The same engines are then asked to plan with **capacity
   headroom** — routes built as if the vans were 5/10/15% smaller, evaluated
   against the real vans. Slack costs planned kilometres and buys resilience;
   the sweep shows the exchange rate.

Both engines are deterministic here: Clarke-Wright by construction, OR-Tools by
a fixed **solution limit** instead of a wall-clock limit (see
:mod:`routeopt.solver`), so every number in the deliverables is byte-for-byte
reproducible. The demand noise level is an **assumption, labelled** — the
fragility numbers are modelled, not measured.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path

import numpy as np

from .heuristic import Solution, clarke_wright
from .model import Instance, distance_matrix
from .sensitivity import _nice_ceiling
from .solver import solve_cvrp

# --- defaults (all overridable; all stated in the deliverables) --------------
N_SCENARIOS = 200  # Monte-Carlo sample size
DEMAND_CV = 0.15  # coefficient of variation of demand noise — an assumption
SEED = 11  # scenario RNG seed (mixed with an instance signature)
BUFFERS_PCT = (0, 5, 10, 15)  # capacity headroom levels planned for
SOLUTION_LIMIT = 200  # OR-Tools deterministic stopping rule


def sample_demand_scenarios(
    instance: Instance,
    n_scenarios: int = N_SCENARIOS,
    cv: float = DEMAND_CV,
    seed: int = SEED,
) -> np.ndarray:
    """K seeded realized-demand scenarios, shape ``(n_scenarios, n_nodes)``.

    Each customer's realized demand is ``round(forecast * (1 + cv * z))`` with
    ``z`` standard normal truncated to ±3, clipped to ``[0, capacity]`` (0 = the
    customer cancelled; the van still drives there — routes are fixed a priori).
    The depot row stays 0. Seeded from a fixed base plus an instance signature,
    so the same instance always gets the identical scenario set.
    """
    if cv < 0:
        raise ValueError("cv must be >= 0")
    rng = np.random.default_rng([int(seed), int(instance.demands.sum()), int(instance.num_nodes)])
    z = np.clip(rng.standard_normal((int(n_scenarios), instance.num_nodes)), -3.0, 3.0)
    realized = np.round(instance.demands[None, :] * (1.0 + cv * z))
    realized = np.clip(realized, 0, int(instance.capacity)).astype(np.int64)
    realized[:, instance.depot] = 0
    return realized


def simulate_recourse(
    route: list[int], realized: np.ndarray, capacity: int, dist: np.ndarray, depot: int = 0
) -> tuple[int, float]:
    """Drive one planned route under one realized-demand vector.

    The van leaves the depot full and serves stops in the planned order. When
    the next customer's realized demand exceeds what is left on board, the van
    drives back to the depot, reloads, returns to that customer and continues —
    the classic detour-to-depot recourse. Returns ``(restock_trips,
    extra_distance)``; both are 0 when the route survives as planned.
    """
    load = 0
    trips = 0
    extra = 0.0
    for node in route[1:-1]:
        q = int(realized[node])
        if load + q > capacity:
            extra += float(dist[node, depot]) + float(dist[depot, node])
            trips += 1
            load = 0
        load += q
    return trips, extra


@dataclass(frozen=True)
class PlanRobustness:
    """One plan's fragility profile across the whole scenario set."""

    engine: str  # "clarke-wright" | "or-tools"
    headroom_pct: int  # capacity buffer the plan was built with
    vehicles: int
    planned_distance: float  # forecast-world distance of the plan
    max_route_load_pct: float  # tightest planned route vs the REAL capacity
    fail_scenarios_pct: float  # share of scenarios with >= 1 restock trip
    mean_restocks: float  # expected restock trips per day
    mean_extra_km: float  # expected recourse distance per day
    p95_extra_km: float  # a bad-but-plausible day
    max_extra_km: float  # the worst sampled day
    expected_total_km: float  # planned + mean recourse


def evaluate_plan(
    engine: str,
    headroom_pct: int,
    plan: Solution,
    instance: Instance,
    dist: np.ndarray,
    scenarios: np.ndarray,
) -> PlanRobustness:
    """Score one plan against every scenario (deterministic arithmetic only)."""
    capacity = int(instance.capacity)
    trips_per_scenario = np.zeros(scenarios.shape[0], dtype=np.int64)
    extra_per_scenario = np.zeros(scenarios.shape[0], dtype=float)
    for s in range(scenarios.shape[0]):
        row = scenarios[s]
        trips = 0
        extra = 0.0
        for route in plan.routes:
            t, e = simulate_recourse(route, row, capacity, dist, depot=instance.depot)
            trips += t
            extra += e
        trips_per_scenario[s] = trips
        extra_per_scenario[s] = extra
    mean_extra = float(extra_per_scenario.mean())
    return PlanRobustness(
        engine=engine,
        headroom_pct=int(headroom_pct),
        vehicles=plan.vehicles_used,
        planned_distance=round(plan.total_distance, 3),
        max_route_load_pct=round(100.0 * max(plan.loads) / capacity, 1),
        fail_scenarios_pct=round(100.0 * float((trips_per_scenario > 0).mean()), 1),
        mean_restocks=round(float(trips_per_scenario.mean()), 3),
        mean_extra_km=round(mean_extra, 3),
        p95_extra_km=round(float(np.percentile(extra_per_scenario, 95)), 3),
        max_extra_km=round(float(extra_per_scenario.max()), 3),
        expected_total_km=round(plan.total_distance + mean_extra, 3),
    )


def plan_with_headroom(
    instance: Instance,
    headroom_pct: int,
    engine: str,
    metric: str = "euclidean",
    solution_limit: int = SOLUTION_LIMIT,
) -> Solution | None:
    """Build a plan as if the vans were ``headroom_pct`` percent smaller.

    The instance's fleet is unchanged — only the planning capacity shrinks, so
    the routes carry slack against demand surprises. Returns ``None`` when the
    buffered capacity is infeasible (a customer no longer fits, or the engine
    cannot place everyone on the available fleet).
    """
    eff_capacity = int(instance.capacity * (100 - headroom_pct) / 100.0)
    if eff_capacity < int(instance.demands.max()):
        return None
    inst = replace(instance, capacity=eff_capacity)
    dist = distance_matrix(inst, metric)
    if engine == "clarke-wright":
        sol = clarke_wright(inst, dist)
        if sol.vehicles_used > inst.num_vehicles:
            return None  # savings ignores the fleet cap; honour it here
    elif engine == "or-tools":
        sol = solve_cvrp(inst, metric=metric, solution_limit=solution_limit)
    else:
        raise ValueError(f"unknown engine: {engine!r}")
    return sol if sol.feasible and sol.routes else None


def stress_test(
    instance: Instance,
    metric: str = "euclidean",
    buffers_pct: tuple[int, ...] = BUFFERS_PCT,
    n_scenarios: int = N_SCENARIOS,
    cv: float = DEMAND_CV,
    seed: int = SEED,
    solution_limit: int = SOLUTION_LIMIT,
) -> list[PlanRobustness]:
    """Every (engine, headroom) plan scored against the one shared scenario set."""
    dist = distance_matrix(instance, metric)
    scenarios = sample_demand_scenarios(instance, n_scenarios=n_scenarios, cv=cv, seed=seed)
    results: list[PlanRobustness] = []
    for engine in ("clarke-wright", "or-tools"):
        for b in buffers_pct:
            plan = plan_with_headroom(
                instance, b, engine, metric=metric, solution_limit=solution_limit
            )
            if plan is None:
                continue
            results.append(evaluate_plan(engine, b, plan, instance, dist, scenarios))
    return results


def _pct(base: float, other: float) -> float:
    return 100.0 * (other - base) / base if base else 0.0


def headline_read(results: list[PlanRobustness]) -> list[str]:
    """The plain-language read, reported exactly as the numbers fall."""
    if not results:
        return ["(no feasible plan in the swept range)"]
    by_key = {(r.engine, r.headroom_pct): r for r in results}
    lines: list[str] = []

    cw0 = by_key.get(("clarke-wright", 0))
    ot0 = by_key.get(("or-tools", 0))
    if cw0 and ot0:
        lines.append(
            f"On the forecast, or-tools plans {_pct(cw0.planned_distance, ot0.planned_distance):+.1f}% "
            f"distance vs clarke-wright; under demand noise it fails in "
            f"{ot0.fail_scenarios_pct:.0f}% of scenarios (cw: {cw0.fail_scenarios_pct:.0f}%), "
            f"expected recourse {ot0.mean_extra_km:,.1f} km/day (cw: {cw0.mean_extra_km:,.1f})."
        )
        lines.append(
            f"Counting expected recourse, the plans land at {ot0.expected_total_km:,.1f} km "
            f"(or-tools) vs {cw0.expected_total_km:,.1f} km (clarke-wright) per day."
        )

    ot_rows = sorted(
        (r for r in results if r.engine == "or-tools"), key=lambda r: r.headroom_pct
    )
    if ot0 and len(ot_rows) > 1:
        best = min(ot_rows, key=lambda r: r.expected_total_km)
        if best.headroom_pct != 0:
            lines.append(
                f"Planning with {best.headroom_pct}% capacity headroom costs "
                f"{_pct(ot0.planned_distance, best.planned_distance):+.1f}% planned km but cuts "
                f"failing scenarios {ot0.fail_scenarios_pct:.0f}% -> {best.fail_scenarios_pct:.0f}% "
                f"and the expected day {_pct(ot0.expected_total_km, best.expected_total_km):+.1f}% "
                f"- the cheapest expected day in the sweep."
            )
        else:
            lines.append(
                "In this sweep no headroom level beats the 0%-buffer plan on expected "
                "total distance — the recourse saved is smaller than the planned km added."
            )
        worst = max(ot_rows, key=lambda r: r.headroom_pct)
        lines.append(
            f"The deepest modelled buffer ({worst.headroom_pct}%) trades "
            f"{_pct(ot0.planned_distance, worst.planned_distance):+.1f}% planned km for a "
            f"{worst.fail_scenarios_pct:.0f}% failure rate and "
            f"{worst.mean_restocks:.2f} expected restocks/day "
            f"(0% buffer: {ot0.mean_restocks:.2f})."
        )
    return lines


# --- deliverables -----------------------------------------------------------

_CSV_HEADER = (
    "engine,headroom_pct,vehicles,planned_km,max_route_load_pct,fail_scenarios_pct,"
    "mean_restocks,mean_extra_km,p95_extra_km,max_extra_km,expected_total_km"
)


def write_robustness_csv(results: list[PlanRobustness], path: Path) -> Path:
    lines = [_CSV_HEADER]
    for r in results:
        lines.append(
            f"{r.engine},{r.headroom_pct},{r.vehicles},{r.planned_distance:.3f},"
            f"{r.max_route_load_pct:.1f},{r.fail_scenarios_pct:.1f},{r.mean_restocks:.3f},"
            f"{r.mean_extra_km:.3f},{r.p95_extra_km:.3f},{r.max_extra_km:.3f},"
            f"{r.expected_total_km:.3f}"
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def write_robustness_svg(
    results: list[PlanRobustness],
    path: Path,
    title: str = "Robustness vs capacity headroom",
    cv: float = DEMAND_CV,
    n_scenarios: int = N_SCENARIOS,
) -> Path:
    """Hand-drawn SVG (no plotting library): the price-of-robustness curve.

    X: capacity headroom the or-tools plan was built with. Left axis: planned
    distance (blue) and expected total incl. recourse (green). Right axis:
    share of scenarios with at least one restock (orange, dashed). Every
    coordinate is rounded, so the file is byte-for-byte identical across runs.
    """
    rows = sorted((r for r in results if r.engine == "or-tools"), key=lambda r: r.headroom_pct)
    if not rows:
        rows = sorted(
            (r for r in results if r.engine == "clarke-wright"), key=lambda r: r.headroom_pct
        )
    w, h = 760, 460
    ml, mr, mt, mb = 64, 66, 56, 64
    px0, px1 = ml, w - mr
    py0, py1 = h - mb, mt

    xs_v = [r.headroom_pct for r in rows]
    kms = [r.planned_distance for r in rows] + [r.expected_total_km for r in rows]
    kmax = _nice_ceiling(max(kms))
    xmin, xmax = min(xs_v), max(xs_v)
    xspan = (xmax - xmin) or 1

    def sx(v: float) -> float:
        return round(px0 + (v - xmin) / xspan * (px1 - px0), 2)

    def sy_km(v: float) -> float:
        return round(py0 + (v / kmax) * (py1 - py0), 2)

    def sy_pc(v: float) -> float:
        return round(py0 + (v / 100.0) * (py1 - py0), 2)

    blue, green, orange, ink, grid = "#0072B2", "#009E73", "#D55E00", "#222222", "#DDDDDD"
    out: list[str] = []
    out.append(
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" '
        f'viewBox="0 0 {w} {h}" font-family="system-ui,Segoe UI,Arial,sans-serif">'
    )
    out.append(f'<rect width="{w}" height="{h}" fill="#FFFFFF"/>')
    out.append(
        f'<text x="{ml}" y="30" font-size="17" font-weight="600" fill="{ink}">{title}</text>'
    )
    out.append(
        f'<text x="{ml}" y="47" font-size="11" fill="#666666">'
        f"or-tools (deterministic solution limit); {n_scenarios} seeded demand scenarios, "
        f"cv {cv:.2f} — modelled noise, not measured</text>"
    )

    for i in range(5):
        gy = round(py0 + i / 4 * (py1 - py0), 2)
        out.append(f'<line x1="{px0}" y1="{gy}" x2="{px1}" y2="{gy}" stroke="{grid}" stroke-width="1"/>')
        out.append(
            f'<text x="{px0 - 8}" y="{gy + 4}" font-size="11" text-anchor="end" '
            f'fill="{blue}">{kmax * i / 4:.0f}</text>'
        )
        out.append(
            f'<text x="{px1 + 8}" y="{gy + 4}" font-size="11" text-anchor="start" '
            f'fill="{orange}">{100 * i // 4}</text>'
        )

    for r in rows:
        x = sx(r.headroom_pct)
        out.append(f'<line x1="{x}" y1="{py0}" x2="{x}" y2="{py0 + 5}" stroke="{ink}" stroke-width="1"/>')
        out.append(
            f'<text x="{x}" y="{py0 + 19}" font-size="11" text-anchor="middle" fill="{ink}">'
            f"{r.headroom_pct}%</text>"
        )

    out.append(
        f'<text x="{(px0 + px1) / 2}" y="{h - 16}" font-size="12" text-anchor="middle" '
        f'fill="{ink}">capacity headroom the plan was built with</text>'
    )
    out.append(
        f'<text x="16" y="{(py0 + py1) / 2}" font-size="12" text-anchor="middle" fill="{blue}" '
        f'transform="rotate(-90 16 {(py0 + py1) / 2})">distance (km)</text>'
    )
    out.append(
        f'<text x="{w - 14}" y="{(py0 + py1) / 2}" font-size="12" text-anchor="middle" '
        f'fill="{orange}" transform="rotate(90 {w - 14} {(py0 + py1) / 2})">'
        f"scenarios with a failure (%)</text>"
    )

    pts_f = " ".join(f"{sx(r.headroom_pct)},{sy_pc(r.fail_scenarios_pct)}" for r in rows)
    out.append(f'<polyline points="{pts_f}" fill="none" stroke="{orange}" stroke-width="2" stroke-dasharray="5 4"/>')
    for r in rows:
        out.append(f'<circle cx="{sx(r.headroom_pct)}" cy="{sy_pc(r.fail_scenarios_pct)}" r="3" fill="{orange}"/>')

    pts_e = " ".join(f"{sx(r.headroom_pct)},{sy_km(r.expected_total_km)}" for r in rows)
    out.append(f'<polyline points="{pts_e}" fill="none" stroke="{green}" stroke-width="2.5"/>')
    for r in rows:
        out.append(f'<circle cx="{sx(r.headroom_pct)}" cy="{sy_km(r.expected_total_km)}" r="3.5" fill="{green}"/>')

    pts_p = " ".join(f"{sx(r.headroom_pct)},{sy_km(r.planned_distance)}" for r in rows)
    out.append(f'<polyline points="{pts_p}" fill="none" stroke="{blue}" stroke-width="2.5"/>')
    for r in rows:
        out.append(f'<circle cx="{sx(r.headroom_pct)}" cy="{sy_km(r.planned_distance)}" r="3.5" fill="{blue}"/>')

    lx, ly = px0 + 12, py1 + 14
    out.append(f'<line x1="{lx}" y1="{ly}" x2="{lx + 26}" y2="{ly}" stroke="{blue}" stroke-width="2.5"/>')
    out.append(f'<text x="{lx + 32}" y="{ly + 4}" font-size="11" fill="{ink}">planned distance (forecast world)</text>')
    out.append(f'<line x1="{lx}" y1="{ly + 18}" x2="{lx + 26}" y2="{ly + 18}" stroke="{green}" stroke-width="2.5"/>')
    out.append(f'<text x="{lx + 32}" y="{ly + 22}" font-size="11" fill="{ink}">expected total incl. recourse</text>')
    out.append(
        f'<line x1="{lx}" y1="{ly + 36}" x2="{lx + 26}" y2="{ly + 36}" stroke="{orange}" '
        f'stroke-width="2" stroke-dasharray="5 4"/>'
    )
    out.append(f'<text x="{lx + 32}" y="{ly + 40}" font-size="11" fill="{ink}">scenarios with a failure</text>')
    out.append("</svg>")

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(out) + "\n", encoding="utf-8")
    return path


def write_robustness_md(
    instance: Instance,
    results: list[PlanRobustness],
    read: list[str],
    path: Path,
    n_scenarios: int = N_SCENARIOS,
    cv: float = DEMAND_CV,
    seed: int = SEED,
    solution_limit: int = SOLUTION_LIMIT,
) -> Path:
    lines = [
        f"# Robustness under demand uncertainty — `{instance.name}`",
        "",
        f"- **{instance.num_customers}** customers, forecast demand "
        f"**{instance.total_demand}**, capacity **{instance.capacity}**, fleet "
        f"**{instance.num_vehicles}**. Each plan is driven, in planned order, through "
        f"**{n_scenarios}** seeded demand scenarios (multiplicative noise, cv **{cv:.2f}**, "
        f"truncated at ±3σ, seed {seed}) — a **modelled assumption, not measured data**.",
        "- When a van cannot serve the next customer it makes a **restocking round trip** "
        "to the depot (classic detour-to-depot recourse) and continues; no live "
        "re-optimization is modelled. Distance units are treated as km.",
        f"- Both engines are deterministic here — Clarke-Wright by construction, or-tools "
        f"by a fixed solution limit ({solution_limit}) instead of a wall clock — so this "
        f"file regenerates byte-identically.",
        "",
        "| Engine | Headroom | Vans | Planned km | Max route load | Fail scen. | Mean restocks | Mean extra km | p95 extra km | Expected total km |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for r in results:
        lines.append(
            f"| {r.engine} | {r.headroom_pct}% | {r.vehicles} | {r.planned_distance:,.1f} | "
            f"{r.max_route_load_pct:.0f}% | {r.fail_scenarios_pct:.0f}% | {r.mean_restocks:.2f} | "
            f"{r.mean_extra_km:,.1f} | {r.p95_extra_km:,.1f} | {r.expected_total_km:,.1f} |"
        )
    lines += ["", "## The read", ""]
    lines += [f"- {r}" for r in read]
    lines += [
        "",
        "**Honest caveats.** The noise level is an assumption (no order history exists for "
        "synthetic customers); failure rates scale with it. Recourse is the textbook policy — "
        "a real dispatcher would re-sequence or reassign live and do better. The or-tools "
        "plans are good heuristic solutions under a fixed search budget, not proven optima, "
        "and neither heuristic is monotone in planning capacity — a tighter capacity can "
        "occasionally yield a *shorter* plan. 'Max route load' is the plan's tightest van "
        "under the *forecast* — the plans differ in how much slack they carry, which is "
        "exactly what the table prices out.",
        "",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def build_robustness(
    instance: Instance,
    metric: str = "euclidean",
    out_dir: Path | None = None,
    n_scenarios: int = N_SCENARIOS,
    cv: float = DEMAND_CV,
    seed: int = SEED,
    buffers_pct: tuple[int, ...] = BUFFERS_PCT,
    solution_limit: int = SOLUTION_LIMIT,
) -> dict[str, object]:
    """Run the stress test and write CSV + SVG + Markdown; return everything."""
    from .report import DELIVERABLES

    out_dir = out_dir or DELIVERABLES
    results = stress_test(
        instance,
        metric=metric,
        buffers_pct=buffers_pct,
        n_scenarios=n_scenarios,
        cv=cv,
        seed=seed,
        solution_limit=solution_limit,
    )
    read = headline_read(results)
    csv_path = write_robustness_csv(results, out_dir / "robustness.csv")
    svg_path = write_robustness_svg(
        results,
        out_dir / "robustness.svg",
        title=f"Robustness vs capacity headroom - {instance.name}",
        cv=cv,
        n_scenarios=n_scenarios,
    )
    md_path = write_robustness_md(
        instance,
        results,
        read,
        out_dir / "robustness.md",
        n_scenarios=n_scenarios,
        cv=cv,
        seed=seed,
        solution_limit=solution_limit,
    )
    return {
        "results": results,
        "read": read,
        "csv": csv_path,
        "svg": svg_path,
        "md": md_path,
    }
