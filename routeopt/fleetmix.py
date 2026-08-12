"""Heterogeneous fleet mix — the Fleet Size and Mix VRP (Golden et al., 1984).

Every layer so far assumes the fleet is a row of identical vans. A real
distributor shops a *catalogue*: small vans that are cheap to own and cheap per
kilometre but carry little, large ones that carry double but cost more on both
axes. The classic planning question — posed by Golden, Assad, Levy and Gheysens
in 1984 as the **Fleet Size and Mix VRP** — is: *which combination of vehicle
sizes serves today's demand at the lowest total cost?*

This module answers it with the same OR-Tools engine as the base solver, extended
along the axes the homogeneous model cannot express:

* a **pool** of candidate vans of every catalogue type (enough of each that any
  single type could serve the whole demand alone),
* **per-vehicle capacities** (the capacity dimension takes a vector),
* **per-vehicle arc costs** — each type pays its own EUR/km, so the objective is
  money, not kilometres,
* a **fixed deployment cost** per van that is only charged when the van is
  actually used — this is what finally prices the "fewer, fuller vans" direction
  the fleet-size sensitivity layer could only point at, and what makes the
  solver *park* pool vans that do not earn their keep.

The optimizer's mixed answer is scored against every homogeneous option
("all-small", "all-medium", "all-large") under the identical cost model, so the
deliverable is a like-for-like table: composition, distance, fixed / variable /
total cost, CO2, and the longest route (service).

Determinism: this layer always runs OR-Tools with a fixed **solution limit**
(never a wall clock — see :mod:`routeopt.solver`), so the committed deliverables
regenerate byte-identically. Honesty: the catalogue costs are **illustrative
labelled estimates**, not certified rates; the solver is a heuristic under a
fixed search budget, not a proven optimum — and because the mixed pool has a
much larger search space, the mixed solve can occasionally *trail* a homogeneous
one under the same budget, which is reported exactly as it falls.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from ortools.constraint_solver import pywrapcp, routing_enums_pb2

from . import plate
from .model import Instance, distance_matrix, route_load, scaled_int_matrix
from .sensitivity import CO2_G_PER_KM, COST_EUR_PER_KM, _nice_ceiling

# Distance arc costs are scaled with the same factor as the base solver; money
# is handled inside the search as integer cents (OR-Tools objectives are ints).
_SCALE = 100
COST_SCALE = 100  # 1 EUR = 100 integer cost units (cents)
SOLUTION_LIMIT = 200  # deterministic stopping rule (solutions, not seconds)


@dataclass(frozen=True)
class VehicleType:
    """One van size in the catalogue. All costs are illustrative, labelled."""

    name: str
    capacity: int
    fixed_cost_eur: float  # per *deployed* van per day (ownership, insurance)
    var_cost_eur_km: float  # per km driven (fuel, wear, driver time)
    co2_g_km: float


def default_vehicle_types(instance: Instance) -> tuple[VehicleType, ...]:
    """A three-size catalogue anchored on the instance's own van.

    ``medium`` *is* the instance's van (same capacity, and the same illustrative
    EUR 1.00/km and 250 g/km as the sensitivity layer and the business case).
    ``small`` carries half at a cheaper rate, ``large`` carries double at a
    dearer rate. Per unit of capacity both cost axes *fall* with size — the
    economies of scale that make fleet mix a real question. All figures are
    **illustrative estimates, not certified**.
    """
    q = int(instance.capacity)
    return (
        VehicleType("small", max(1, q // 2), fixed_cost_eur=40.0, var_cost_eur_km=0.70, co2_g_km=180.0),
        VehicleType("medium", q, fixed_cost_eur=60.0, var_cost_eur_km=COST_EUR_PER_KM, co2_g_km=CO2_G_PER_KM),
        VehicleType("large", 2 * q, fixed_cost_eur=90.0, var_cost_eur_km=1.35, co2_g_km=330.0),
    )


def default_pool(instance: Instance, types: tuple[VehicleType, ...]) -> dict[str, int]:
    """Candidate vans per type: enough that the type could serve everything alone.

    ``ceil(total_demand / capacity) + 2`` — the +2 mirrors the base instances'
    fleet slack (a perfectly tight pool turns routing into bin packing). Fixed
    costs make the solver park whatever it does not need, so a generous pool
    costs search effort, not money.
    """
    total = instance.total_demand
    return {t.name: math.ceil(total / t.capacity) + 2 for t in types}


@dataclass(frozen=True)
class MixRoute:
    """One deployed van: its type, its route, and what the route costs."""

    vehicle_type: str
    route: tuple[int, ...]  # depot at both ends
    load: int
    distance: float


@dataclass(frozen=True)
class MixPlan:
    """One fleet option (the optimizer's mix, or a homogeneous fleet) fully priced."""

    label: str
    routes: tuple[MixRoute, ...]
    counts: tuple[tuple[str, int], ...]  # (type name, vans deployed), catalogue order
    vehicles: int
    total_distance: float
    longest_route: float  # service proxy — time to the last customer
    fixed_cost_eur: float
    var_cost_eur: float
    total_cost_eur: float
    est_co2_kg: float
    feasible: bool
    solve_time_s: float = field(compare=False, default=0.0)

    @property
    def fleet_str(self) -> str:
        used = [f"{n} {name}" for name, n in self.counts if n > 0]
        return " + ".join(used) if used else "(none)"


def make_plan(
    label: str,
    types: tuple[VehicleType, ...],
    typed_routes: list[tuple[VehicleType, list[int]]],
    instance: Instance,
    dist: np.ndarray,
    solve_time_s: float = 0.0,
) -> MixPlan:
    """Price a set of typed routes and check feasibility (pure arithmetic).

    Every reported number is recomputed in floats from the routes and the
    catalogue — the solver's integer objective only *guides* the search, so the
    deliverables are exact functions of the routes and the test suite can
    recompute them by hand.
    """
    routes: list[MixRoute] = []
    fixed = var = co2 = total_d = 0.0
    for t, r in typed_routes:
        if len(r) <= 2:
            continue
        d = float(sum(dist[r[i], r[i + 1]] for i in range(len(r) - 1)))
        routes.append(
            MixRoute(vehicle_type=t.name, route=tuple(r), load=route_load(r, instance.demands), distance=round(d, 3))
        )
        fixed += t.fixed_cost_eur
        var += d * t.var_cost_eur_km
        co2 += d * t.co2_g_km / 1000.0
        total_d += d
    by_name = {t.name: t for t in types}
    served = sorted(n for mr in routes for n in mr.route if n != instance.depot)
    feasible = served == list(range(1, instance.num_nodes)) and all(
        mr.load <= by_name[mr.vehicle_type].capacity for mr in routes
    )
    counts_map: dict[str, int] = {t.name: 0 for t in types}
    for mr in routes:
        counts_map[mr.vehicle_type] += 1
    longest = max((mr.distance for mr in routes), default=0.0)
    return MixPlan(
        label=label,
        routes=tuple(routes),
        counts=tuple((t.name, counts_map[t.name]) for t in types),
        vehicles=len(routes),
        total_distance=round(total_d, 3),
        longest_route=round(longest, 3),
        fixed_cost_eur=round(fixed, 2),
        var_cost_eur=round(var, 2),
        total_cost_eur=round(fixed + var, 2),
        est_co2_kg=round(co2, 2),
        feasible=feasible,
        solve_time_s=solve_time_s,
    )


def _infeasible(label: str, types: tuple[VehicleType, ...]) -> MixPlan:
    return MixPlan(
        label=label,
        routes=(),
        counts=tuple((t.name, 0) for t in types),
        vehicles=0,
        total_distance=0.0,
        longest_route=0.0,
        fixed_cost_eur=0.0,
        var_cost_eur=0.0,
        total_cost_eur=0.0,
        est_co2_kg=0.0,
        feasible=False,
    )


def solve_fleet_mix(
    instance: Instance,
    types: tuple[VehicleType, ...],
    metric: str = "euclidean",
    solution_limit: int = SOLUTION_LIMIT,
    pool: dict[str, int] | None = None,
    label: str = "optimized mix",
) -> MixPlan:
    """Solve one FSM instance: a pool of typed vans, money as the objective.

    The same OR-Tools ``RoutingModel`` as :func:`routeopt.solver.solve_cvrp`,
    with three heterogeneous extensions: the capacity dimension takes one
    capacity *per pool van*, each van pays its type's EUR/km through a
    per-vehicle arc-cost evaluator (integer cents), and each van carries its
    type's fixed cost, charged only if the van leaves the depot. Always runs
    under a fixed solution limit — deterministic, never wall-clock.
    """
    dist = distance_matrix(instance, metric)
    idist = scaled_int_matrix(dist, _SCALE)
    pool = pool if pool is not None else default_pool(instance, types)

    veh_types: list[VehicleType] = []
    for t in types:
        veh_types.extend([t] * int(pool.get(t.name, 0)))
    max_cap = max((t.capacity for t in veh_types), default=0)
    if not veh_types or max_cap < int(instance.demands.max()):
        return _infeasible(label, types)  # a customer's order fits in no pool van

    manager = pywrapcp.RoutingIndexManager(instance.num_nodes, len(veh_types), instance.depot)
    routing = pywrapcp.RoutingModel(manager)

    # --- distance callback (drives the Distance dimension, not the objective)
    def distance_cb(from_index: int, to_index: int) -> int:
        return int(idist[manager.IndexToNode(from_index)][manager.IndexToNode(to_index)])

    transit_idx = routing.RegisterTransitCallback(distance_cb)

    # --- money: one integer-cents cost matrix per type, one evaluator per van
    def _register_cost(cmat: np.ndarray) -> int:
        def cb(from_index: int, to_index: int) -> int:
            return int(cmat[manager.IndexToNode(from_index)][manager.IndexToNode(to_index)])

        return routing.RegisterTransitCallback(cb)

    cost_idx = {
        t.name: _register_cost(np.round(dist * t.var_cost_eur_km * COST_SCALE).astype(np.int64))
        for t in types
    }
    for v, t in enumerate(veh_types):
        routing.SetArcCostEvaluatorOfVehicle(cost_idx[t.name], v)
        routing.SetFixedCostOfVehicle(int(round(t.fixed_cost_eur * COST_SCALE)), v)

    # --- capacity dimension, one capacity per pool van --------------------
    def demand_cb(from_index: int) -> int:
        return int(instance.demands[manager.IndexToNode(from_index)])

    demand_idx = routing.RegisterUnaryTransitCallback(demand_cb)
    routing.AddDimensionWithVehicleCapacity(
        demand_idx, 0, [int(t.capacity) for t in veh_types], True, "Capacity"
    )

    # --- distance dimension (same convention as the base solver) ----------
    routing.AddDimension(transit_idx, 0, int(idist.sum()), True, "Distance")

    params = pywrapcp.DefaultRoutingSearchParameters()
    params.first_solution_strategy = routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC
    params.local_search_metaheuristic = (
        routing_enums_pb2.LocalSearchMetaheuristic.GUIDED_LOCAL_SEARCH
    )
    params.solution_limit = int(solution_limit)  # deterministic — see module docstring

    t0 = time.perf_counter()
    solution = routing.SolveWithParameters(params)
    elapsed = time.perf_counter() - t0
    if solution is None:
        return _infeasible(label, types)

    typed_routes: list[tuple[VehicleType, list[int]]] = []
    for v, t in enumerate(veh_types):
        index = routing.Start(v)
        route = [manager.IndexToNode(index)]
        while not routing.IsEnd(index):
            index = solution.Value(routing.NextVar(index))
            route.append(manager.IndexToNode(index))
        if len(route) > 2:
            typed_routes.append((t, route))
    return make_plan(label, types, typed_routes, instance, dist, solve_time_s=elapsed)


def compare_mixes(
    instance: Instance,
    types: tuple[VehicleType, ...] | None = None,
    metric: str = "euclidean",
    solution_limit: int = SOLUTION_LIMIT,
) -> list[MixPlan]:
    """The optimizer's mix plus every homogeneous option, identically priced.

    Homogeneous options whose van cannot carry the largest single order are
    infeasible by construction and dropped (the markdown deliverable notes the
    rule). Feasible plans only, in catalogue order after the mixed headline.
    """
    types = types if types is not None else default_vehicle_types(instance)
    plans = [solve_fleet_mix(instance, types, metric=metric, solution_limit=solution_limit)]
    for t in types:
        plans.append(
            solve_fleet_mix(
                instance,
                types,
                metric=metric,
                solution_limit=solution_limit,
                pool={t.name: default_pool(instance, (t,))[t.name]},
                label=f"all-{t.name}",
            )
        )
    return [p for p in plans if p.feasible]


def status_quo_label(instance: Instance, types: tuple[VehicleType, ...]) -> str:
    """The homogeneous option matching the instance's own van (closest capacity)."""
    t = min(types, key=lambda t: abs(t.capacity - int(instance.capacity)))
    return f"all-{t.name}"


def _pct(base: float, other: float) -> float:
    return 100.0 * (other - base) / base if base else 0.0


def headline_read(plans: list[MixPlan], status_label: str) -> list[str]:
    """The plain-language read, reported exactly as the numbers fall."""
    if not plans:
        return ["(no feasible fleet option - no catalogue van fits the largest order)"]
    by_label = {p.label: p for p in plans}
    lines: list[str] = []

    sq = by_label.get(status_label)
    if sq is not None:
        lines.append(
            f"Status quo - {sq.label} ({sq.fleet_str}, today's van size): "
            f"EUR {sq.total_cost_eur:,.0f}/day (EUR {sq.fixed_cost_eur:,.0f} fixed + "
            f"EUR {sq.var_cost_eur:,.0f} variable), {sq.total_distance:,.1f} km, "
            f"~{sq.est_co2_kg:,.1f} kg CO2."
        )

    cheapest = min(plans, key=lambda p: (p.total_cost_eur, p.label))
    if sq is not None and cheapest.label != sq.label:
        lines.append(
            f"Cheapest modelled option - {cheapest.label} ({cheapest.fleet_str}): "
            f"EUR {cheapest.total_cost_eur:,.0f}/day, "
            f"{_pct(sq.total_cost_eur, cheapest.total_cost_eur):+.1f}% cost vs the status quo; "
            f"distance {_pct(sq.total_distance, cheapest.total_distance):+.1f}%, "
            f"CO2 {_pct(sq.est_co2_kg, cheapest.est_co2_kg):+.1f}%, "
            f"longest route {_pct(sq.longest_route, cheapest.longest_route):+.1f}% (service)."
        )
    elif sq is not None:
        lines.append(
            "No modelled option undercuts the status-quo fleet — today's van size "
            "is already the cheapest of the catalogue under these illustrative costs."
        )

    mixed = next((p for p in plans if not p.label.startswith("all-")), None)
    homogeneous = [p for p in plans if p.label.startswith("all-")]
    if mixed is not None and homogeneous:
        best_h = min(homogeneous, key=lambda p: (p.total_cost_eur, p.label))
        verdict = (
            "beats" if mixed.total_cost_eur < best_h.total_cost_eur
            else ("matches" if mixed.total_cost_eur == best_h.total_cost_eur else "trails")
        )
        lines.append(
            f"The optimizer's mixed fleet ({mixed.fleet_str}) lands at "
            f"EUR {mixed.total_cost_eur:,.0f} and {verdict} the best single-size fleet "
            f"({best_h.label}, EUR {best_h.total_cost_eur:,.0f}) by "
            f"{_pct(best_h.total_cost_eur, mixed.total_cost_eur):+.1f}% - a heuristic under "
            f"a fixed search budget, reported as it falls."
        )
    return lines


# --- deliverables -----------------------------------------------------------

_CSV_HEADER = (
    "option,fleet,vehicles,total_distance_km,longest_route_km,"
    "fixed_cost_eur,var_cost_eur,total_cost_eur,est_co2_kg"
)


def write_mix_csv(plans: list[MixPlan], path: Path) -> Path:
    lines = [_CSV_HEADER]
    for p in plans:
        lines.append(
            f"{p.label},{p.fleet_str},{p.vehicles},{p.total_distance:.3f},"
            f"{p.longest_route:.3f},{p.fixed_cost_eur:.2f},{p.var_cost_eur:.2f},"
            f"{p.total_cost_eur:.2f},{p.est_co2_kg:.2f}"
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def write_mix_svg(
    plans: list[MixPlan],
    path: Path,
    title: str = "Fleet mix — cost of each option",
    solution_limit: int = SOLUTION_LIMIT,
) -> Path:
    """Plate 04 — the fleet options as two stacked panels (one axis each).

    Panel A (EUR/day): a stacked money bar per option — fixed cost as the
    light step of the blue ramp under variable cost in full blue, a 2px
    surface gap between segments, total labelled on top. Panel B (kg/day):
    estimated CO2 per option, direct-labelled. Both share the option axis —
    no dual-axis chart. Every coordinate is rounded, so the file is
    byte-for-byte identical across runs.
    """
    w, h = plate.PLATE_W, 640
    px0, px1 = plate.MARGIN_L, w - plate.MARGIN_R

    emax = _nice_ceiling(max(p.total_cost_eur for p in plans))
    cmax = _nice_ceiling(max(p.est_co2_kg for p in plans))
    n = len(plans)
    slot = (px1 - px0) / n

    def sx(i: int) -> float:
        return round(px0 + (i + 0.5) * slot, 2)

    def sy(v: float, vcap: float, py0: float, py1: float) -> float:
        return round(py0 + (v / vcap) * (py1 - py0), 2)

    out = plate.open_svg(w, h)
    plate.plate_header(
        out, "04", title,
        f"or-tools, deterministic solution limit {solution_limit}; catalogue costs are "
        f"illustrative estimates, not certified",
    )

    # --- panel A: the money stack --------------------------------------------
    a_py1, a_py0 = 130, 330
    plate.panel_title(out, px0, a_py1 - 18, "Cost (EUR/day) — fixed + variable, total labelled")
    plate.h_grid(out, px0, px1, a_py0, a_py1, emax, ticks=6)
    bar_w = round(min(56.0, slot * 0.4), 2)
    for i, p in enumerate(plans):
        x = sx(i)
        plate.stacked_bar(
            out, x, bar_w, a_py0,
            sy(p.fixed_cost_eur, emax, a_py0, a_py1),
            sy(p.total_cost_eur, emax, a_py0, a_py1),
        )
        out.append(
            f'<text x="{x}" y="{round(sy(p.total_cost_eur, emax, a_py0, a_py1) - 7, 2)}" '
            f'font-size="11" font-weight="600" text-anchor="middle" '
            f'fill="{plate.INK}">{p.total_cost_eur:,.0f}</text>'
        )
        out.append(
            f'<text x="{x}" y="{a_py0 + 16}" font-size="10.5" text-anchor="middle" '
            f'fill="{plate.INK}">{p.label}</text>'
        )
        out.append(
            f'<text x="{x}" y="{a_py0 + 29}" font-size="9.5" text-anchor="middle" '
            f'fill="{plate.MUTED}">{p.fleet_str}</text>'
        )
    plate.legend_swatch(out, px0 + 6, a_py1 + 10, plate.BLUE_LIGHT, "fixed cost (deployed vans)")
    plate.legend_swatch(out, px0 + 196, a_py1 + 10, plate.BLUE, "variable cost (km driven)")

    # --- panel B: emissions ---------------------------------------------------
    b_py1, b_py0 = 410, 560
    plate.panel_title(out, px0, b_py1 - 18, "Est. CO2 (kg/day) — illustrative factors per van type")
    plate.h_grid(out, px0, px1, b_py0, b_py1, cmax, ticks=6)
    co2_w = round(min(30.0, slot * 0.22), 2)
    for i, p in enumerate(plans):
        x = sx(i)
        y_top = sy(p.est_co2_kg, cmax, b_py0, b_py1)
        plate.bar(out, x, co2_w, b_py0, y_top, plate.AQUA)
        plate.direct_label(out, x, round(y_top - 7, 2), f"{p.est_co2_kg:,.0f}", anchor="middle")
        out.append(
            f'<text x="{x}" y="{b_py0 + 16}" font-size="9.5" text-anchor="middle" '
            f'fill="{plate.MUTED}">{p.label}</text>'
        )

    plate.x_axis_label(out, px0, px1, 600, "fleet option (same options in both panels)")
    plate.footer(
        out, w, h,
        "Money and emissions on separate axes, shared option order. Fixed solution limit — "
        "regenerates byte-identically. Table: fleet_mix.csv / .md",
    )
    plate.close_svg(out)

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(out) + "\n", encoding="utf-8")
    return path


def write_mix_md(
    instance: Instance,
    types: tuple[VehicleType, ...],
    plans: list[MixPlan],
    read: list[str],
    path: Path,
    solution_limit: int = SOLUTION_LIMIT,
) -> Path:
    lines = [
        f"# Heterogeneous fleet mix (FSM) — `{instance.name}`",
        "",
        f"- **{instance.num_customers}** customers, total demand **{instance.total_demand}**. "
        f"The **Fleet Size and Mix VRP** (Golden et al., 1984): which combination of van "
        f"sizes serves the demand at the lowest total cost? The objective is **money** "
        f"(fixed cost per deployed van + EUR/km per type), not kilometres.",
        f"- Engine: the same or-tools model as the base CVRP, with per-vehicle capacities, "
        f"per-vehicle EUR/km arc costs, and per-vehicle fixed costs; pinned to a fixed "
        f"**solution limit ({solution_limit})** — deterministic, so this file regenerates "
        f"byte-identically.",
        "- All catalogue costs are **illustrative labelled estimates, not certified rates**; "
        "distance is straight-line synthetic-grid units treated as km.",
        "",
        "## The catalogue",
        "",
        "| Type | Capacity | Fixed (EUR/day) | Variable (EUR/km) | CO2 (g/km) |",
        "|---|---:|---:|---:|---:|",
    ]
    for t in types:
        lines.append(
            f"| {t.name} | {t.capacity} | {t.fixed_cost_eur:,.0f} | "
            f"{t.var_cost_eur_km:.2f} | {t.co2_g_km:.0f} |"
        )
    lines += [
        "",
        "Per unit of capacity, both cost axes fall with size (economies of scale) — that "
        "is what makes the mix a genuine question rather than an arithmetic one.",
        "",
        "## The options",
        "",
        "| Option | Fleet | Vans | Distance (km) | Longest route (km) | Fixed (EUR) | Variable (EUR) | **Total (EUR/day)** | Est. CO2 (kg) |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for p in plans:
        lines.append(
            f"| {p.label} | {p.fleet_str} | {p.vehicles} | {p.total_distance:,.1f} | "
            f"{p.longest_route:,.1f} | {p.fixed_cost_eur:,.0f} | {p.var_cost_eur:,.0f} | "
            f"**{p.total_cost_eur:,.0f}** | {p.est_co2_kg:,.1f} |"
        )
    lines += ["", "## The read", ""]
    lines += [f"- {r}" for r in read]
    lines += [
        "",
        "**Honest caveats.** Every plan is a good heuristic solution under a fixed search "
        "budget, **not a proven optimum** — and the mixed pool's larger search space means "
        "the mixed solve can occasionally trail a homogeneous one under the same budget; "
        "the table reports whatever the numbers say. A homogeneous option is dropped when "
        "its van cannot carry the largest single order. The catalogue prices are round "
        "illustrative figures; real quotes (lease, insurance, driver, fuel) would move the "
        "crossover points, which is exactly what this table is built to recompute. No "
        "route-duration cap is modelled — the longest-route column is the service price "
        "of consolidating into fewer, bigger vans.",
        "",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def build_fleet_mix(
    instance: Instance,
    metric: str = "euclidean",
    out_dir: Path | None = None,
    solution_limit: int = SOLUTION_LIMIT,
    types: tuple[VehicleType, ...] | None = None,
) -> dict[str, object]:
    """Run the FSM comparison and write CSV + SVG + Markdown; return everything."""
    from .report import DELIVERABLES

    out_dir = out_dir or DELIVERABLES
    types = types if types is not None else default_vehicle_types(instance)
    plans = compare_mixes(instance, types=types, metric=metric, solution_limit=solution_limit)
    read = headline_read(plans, status_quo_label(instance, types))
    csv_path = write_mix_csv(plans, out_dir / "fleet_mix.csv")
    svg_path = write_mix_svg(
        plans,
        out_dir / "fleet_mix.svg",
        title=f"Fleet mix - cost of each option - {instance.name}",
        solution_limit=solution_limit,
    )
    md_path = write_mix_md(
        instance, types, plans, read, out_dir / "fleet_mix.md", solution_limit=solution_limit
    )
    return {
        "types": types,
        "plans": plans,
        "read": read,
        "csv": csv_path,
        "svg": svg_path,
        "md": md_path,
    }
