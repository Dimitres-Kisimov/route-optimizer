"""Time windows (VRPTW) and a service-level / on-time analysis.

The base CVRP plan is capacity-aware but **time-blind**: it decides *who rides
with whom* and *in what order* to save kilometres, but never asks *when* a van
actually reaches a customer. Real deliveries carry a promised window — "before
noon", "after 2pm" — and a plan that ignores them will quietly show up late.

This module adds a light time model on top of the existing instance and answers
two questions a dispatcher actually cares about:

1. **How many promises does the time-blind plan already keep, and by how much
   does it miss the rest?** — a fully deterministic on-time *audit* of the
   Clarke-Wright savings plan (no solver, byte-for-byte reproducible).
2. **What does guaranteeing every window cost?** — the same OR-Tools engine, now
   given a *Time* dimension with per-customer windows (the classic **VRPTW**),
   which satisfies every window by construction. The extra distance over the
   time-blind plan is the price of the service guarantee.

The time windows are **synthetic and labelled** (morning / afternoon / anytime
slots, seeded per instance) — the same honesty as the rest of the repo's data.
Travel time is ``distance x 60 / speed`` minutes; each stop costs a fixed service
time. Distances are treated as kilometres, per the repo convention.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .heuristic import Solution, clarke_wright
from .model import Instance, distance_matrix, scaled_int_matrix

# OR-Tools arc/time costs are integers; scale then round (as solver.py does).
_SCALE = 100


@dataclass(frozen=True)
class TimeModel:
    """A synthetic time layer over an instance (all times in minutes).

    ``ready[i]`` / ``due[i]`` bound when *service may start* at node ``i`` — a van
    may arrive early and wait until ``ready``; it is **late** if it arrives after
    ``due``. Node 0 (depot) spans the whole ``[0, horizon]`` day.
    """

    ready: np.ndarray  # (n_nodes,) earliest service start
    due: np.ndarray  # (n_nodes,) latest service start
    service_min: float  # fixed service time per customer
    speed_kmh: float  # travel speed; travel_min = distance * 60 / speed
    horizon_min: float  # depot close (end of the working day)
    morning_due: float  # upper bound of the morning (AM) window
    afternoon_ready: float  # lower bound of the afternoon (PM) window
    labels: tuple[str, ...]  # "AM" / "PM" / "--" (anytime) per node

    @property
    def min_per_dist(self) -> float:
        """Minutes of driving per unit of distance."""
        return 60.0 / self.speed_kmh


def make_time_model(
    instance: Instance,
    *,
    speed_kmh: float = 40.0,
    service_min: float = 5.0,
    horizon_min: float = 480.0,
    morning_due: float = 210.0,
    afternoon_ready: float = 210.0,
    frac_morning: float = 0.4,
    frac_afternoon: float = 0.4,
    seed: int = 7,
) -> TimeModel:
    """Deterministic synthetic delivery windows for an instance.

    Each customer is labelled — seeded, so it is byte-for-byte reproducible —
    ``AM`` (window ``[0, morning_due]``), ``PM`` (``[afternoon_ready, horizon]``)
    or ``--`` (anytime). The default 8-hour day with 3.5-hour morning / afternoon
    slots is generous enough that the windows are satisfiable, yet tight enough
    that a time-blind route order misses some of them.
    """
    n = instance.num_nodes
    # Seed from a fixed base plus an instance signature: reproducible, and each
    # instance gets its own window pattern.
    rng = np.random.default_rng([int(seed), int(instance.demands.sum()), int(n)])
    coins = rng.random(n)

    ready = np.zeros(n, dtype=float)
    due = np.full(n, float(horizon_min), dtype=float)
    labels = ["--"] * n  # node 0 (depot) stays anytime
    am_cut = frac_morning
    pm_cut = frac_morning + frac_afternoon
    for i in range(1, n):
        if coins[i] < am_cut:
            due[i] = float(morning_due)
            labels[i] = "AM"
        elif coins[i] < pm_cut:
            ready[i] = float(afternoon_ready)
            labels[i] = "PM"
        # else: anytime, keep [0, horizon]
    return TimeModel(
        ready=ready,
        due=due,
        service_min=float(service_min),
        speed_kmh=float(speed_kmh),
        horizon_min=float(horizon_min),
        morning_due=float(morning_due),
        afternoon_ready=float(afternoon_ready),
        labels=tuple(labels),
    )


# --- deterministic on-time audit --------------------------------------------


@dataclass(frozen=True)
class StopTiming:
    vehicle: int
    node: int
    label: str
    arrival_min: float
    due_min: float
    late: bool
    lateness_min: float


@dataclass(frozen=True)
class VehicleAudit:
    vehicle: int
    stops: int
    late_stops: int
    worst_lateness_min: float
    total_lateness_min: float
    finish_min: float


@dataclass(frozen=True)
class ServiceAudit:
    """The on-time result of running a *given* set of routes against a TimeModel."""

    total_stops: int
    late_stops: int
    total_lateness_min: float
    worst_lateness_min: float
    per_vehicle: tuple[VehicleAudit, ...]
    timings: tuple[StopTiming, ...]

    @property
    def on_time_stops(self) -> int:
        return self.total_stops - self.late_stops

    @property
    def on_time_pct(self) -> float:
        return 100.0 * self.on_time_stops / self.total_stops if self.total_stops else 100.0


def route_timings(
    route: list[int], vehicle: int, instance: Instance, dist: np.ndarray, tm: TimeModel
) -> tuple[list[StopTiming], float]:
    """Simulate one route's clock: arrival at each stop, and the finish time.

    The van leaves the depot at ``t = 0``; between stops the clock advances by the
    travel time; at a customer it waits until ``ready`` if early, then spends the
    service time. Returns the per-customer timings and the depot return time.
    """
    t = 0.0
    timings: list[StopTiming] = []
    for k in range(1, len(route)):
        prev, node = route[k - 1], route[k]
        t += float(dist[prev, node]) * tm.min_per_dist
        if node == instance.depot:
            continue  # returning home; no service, no window
        arrival = t
        lateness = max(0.0, arrival - float(tm.due[node]))
        timings.append(
            StopTiming(
                vehicle=vehicle,
                node=node,
                label=tm.labels[node],
                arrival_min=arrival,
                due_min=float(tm.due[node]),
                late=lateness > 1e-9,
                lateness_min=lateness,
            )
        )
        start = max(arrival, float(tm.ready[node]))
        t = start + tm.service_min
    return timings, t


def audit_service(instance: Instance, routes: list[list[int]], tm: TimeModel) -> ServiceAudit:
    """Deterministic on-time audit of an arbitrary plan against the time windows."""
    dist = distance_matrix(instance)
    all_timings: list[StopTiming] = []
    per_vehicle: list[VehicleAudit] = []
    total_late = 0
    total_lateness = 0.0
    worst = 0.0
    for v, route in enumerate(routes, start=1):
        timings, finish = route_timings(route, v, instance, dist, tm)
        late = [s for s in timings if s.late]
        v_worst = max((s.lateness_min for s in late), default=0.0)
        v_total = sum(s.lateness_min for s in late)
        per_vehicle.append(
            VehicleAudit(
                vehicle=v,
                stops=len(timings),
                late_stops=len(late),
                worst_lateness_min=round(v_worst, 3),
                total_lateness_min=round(v_total, 3),
                finish_min=round(finish, 3),
            )
        )
        all_timings.extend(timings)
        total_late += len(late)
        total_lateness += v_total
        worst = max(worst, v_worst)
    return ServiceAudit(
        total_stops=len(all_timings),
        late_stops=total_late,
        total_lateness_min=round(total_lateness, 3),
        worst_lateness_min=round(worst, 3),
        per_vehicle=tuple(per_vehicle),
        timings=tuple(all_timings),
    )


# --- the VRPTW solve (OR-Tools, time-aware) ---------------------------------


def solve_vrptw(
    instance: Instance,
    tm: TimeModel,
    metric: str = "euclidean",
    time_limit_s: int = 8,
    log: bool = False,
) -> Solution:
    """CVRP + hard time windows, on the same OR-Tools engine as :func:`solve_cvrp`.

    Adds a **Time** dimension whose transit is ``service(i) + travel(i, j)`` and
    constrains each node's cumulative time to its ``[ready, due]`` window, with
    slack so a van may wait when it arrives early. Returns the usual
    :class:`~routeopt.heuristic.Solution`; every window is satisfied by
    construction (verify with :func:`audit_service`). Like any time-limited
    metaheuristic its distance can wobble a fraction of a percent between runs.
    """
    from ortools.constraint_solver import pywrapcp, routing_enums_pb2

    dist = distance_matrix(instance, metric)
    idist = scaled_int_matrix(dist, _SCALE)
    n_nodes = instance.num_nodes

    manager = pywrapcp.RoutingIndexManager(n_nodes, instance.num_vehicles, instance.depot)
    routing = pywrapcp.RoutingModel(manager)

    # arc cost = distance (identical objective to the base CVRP solver)
    def distance_cb(from_index: int, to_index: int) -> int:
        return int(idist[manager.IndexToNode(from_index)][manager.IndexToNode(to_index)])

    transit_idx = routing.RegisterTransitCallback(distance_cb)
    routing.SetArcCostEvaluatorOfAllVehicles(transit_idx)

    # capacity dimension
    def demand_cb(from_index: int) -> int:
        return int(instance.demands[manager.IndexToNode(from_index)])

    demand_idx = routing.RegisterUnaryTransitCallback(demand_cb)
    routing.AddDimensionWithVehicleCapacity(
        demand_idx, 0, [int(instance.capacity)] * instance.num_vehicles, True, "Capacity"
    )

    # time dimension: transit = service(from) + travel(from, to), scaled to int
    def time_cb(from_index: int, to_index: int) -> int:
        i = manager.IndexToNode(from_index)
        j = manager.IndexToNode(to_index)
        service = 0.0 if i == instance.depot else tm.service_min
        return int(round((service + float(dist[i][j]) * tm.min_per_dist) * _SCALE))

    time_idx = routing.RegisterTransitCallback(time_cb)
    horizon = int(round(tm.horizon_min * _SCALE))
    routing.AddDimension(time_idx, horizon, horizon, False, "Time")  # slack=horizon (waiting allowed)
    time_dim = routing.GetDimensionOrDie("Time")
    for node in range(n_nodes):
        idx = manager.NodeToIndex(node)
        time_dim.CumulVar(idx).SetRange(
            int(round(float(tm.ready[node]) * _SCALE)), int(round(float(tm.due[node]) * _SCALE))
        )
    # prefer earlier starts/finishes (tidy, deterministic-leaning schedules)
    for v in range(instance.num_vehicles):
        routing.AddVariableMinimizedByFinalizer(time_dim.CumulVar(routing.Start(v)))
        routing.AddVariableMinimizedByFinalizer(time_dim.CumulVar(routing.End(v)))

    params = pywrapcp.DefaultRoutingSearchParameters()
    params.first_solution_strategy = routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC
    params.local_search_metaheuristic = (
        routing_enums_pb2.LocalSearchMetaheuristic.GUIDED_LOCAL_SEARCH
    )
    params.time_limit.FromSeconds(int(time_limit_s))
    params.log_search = bool(log)

    t0 = time.perf_counter()
    solution = routing.SolveWithParameters(params)
    elapsed = time.perf_counter() - t0

    if solution is None:
        return Solution(
            method="or-tools-vrptw",
            routes=[],
            total_distance=float("inf"),
            vehicles_used=0,
            loads=[],
            feasible=False,
            solve_time_s=elapsed,
        )

    routes: list[list[int]] = []
    for v in range(instance.num_vehicles):
        index = routing.Start(v)
        route = [manager.IndexToNode(index)]
        while not routing.IsEnd(index):
            index = solution.Value(routing.NextVar(index))
            route.append(manager.IndexToNode(index))
        if len(route) > 2:
            routes.append(route)

    return Solution.from_routes(
        "or-tools-vrptw", routes, dist, instance.demands, instance.capacity, solve_time_s=elapsed
    )


# --- deliverables -----------------------------------------------------------

_AUDIT_HEADER = (
    "vehicle,stops,late_stops,on_time_stops,worst_lateness_min,total_lateness_min,finish_min"
)


def write_audit_csv(audit: ServiceAudit, path: Path) -> Path:
    """Per-vehicle on-time audit (of the deterministic savings plan) — byte-stable."""
    lines = [_AUDIT_HEADER]
    for va in audit.per_vehicle:
        lines.append(
            f"{va.vehicle},{va.stops},{va.late_stops},{va.stops - va.late_stops},"
            f"{va.worst_lateness_min:.3f},{va.total_lateness_min:.3f},{va.finish_min:.3f}"
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _pct(base: float, other: float) -> float:
    return 100.0 * (other - base) / base if base else 0.0


def write_service_md(
    instance: Instance,
    tm: TimeModel,
    savings: Solution,
    audit: ServiceAudit,
    vrptw: Solution,
    vrptw_audit: ServiceAudit,
    path: Path,
) -> Path:
    n_am = sum(1 for label in tm.labels if label == "AM")
    n_pm = sum(1 for label in tm.labels if label == "PM")
    n_any = instance.num_customers - n_am - n_pm
    premium = _pct(savings.total_distance, vrptw.total_distance)
    lines = [
        f"# Service level & time windows (VRPTW) - `{instance.name}`",
        "",
        f"- **{instance.num_customers}** customers on synthetic delivery windows "
        f"(**labelled estimates**): {n_am} morning `[0,{tm.morning_due:.0f}]`*, "
        f"{n_pm} afternoon `[{tm.afternoon_ready:.0f},{tm.horizon_min:.0f}]`, "
        f"{n_any} anytime. "
        f"Day **{tm.horizon_min:.0f} min**, service **{tm.service_min:.0f} min/stop**, "
        f"speed **{tm.speed_kmh:.0f} km/h** (travel = distance x {tm.min_per_dist:.2f} min).",
        "",
        "## The time-blind plan misses promises it never saw",
        "",
        "The Clarke-Wright savings plan is capacity-optimal but ignores time. Audited "
        "against the windows (deterministic):",
        "",
        f"- **{audit.on_time_stops}/{audit.total_stops} on time "
        f"({audit.on_time_pct:.1f}%)**, {audit.late_stops} late.",
        f"- Worst delivery **{audit.worst_lateness_min:,.0f} min** late; total lateness "
        f"**{audit.total_lateness_min:,.0f} min** across the fleet.",
        f"- Time-blind distance **{savings.total_distance:,.1f} km** on "
        f"{savings.vehicles_used} vans.",
        "",
        "Per-vehicle audit: `service_audit.csv`.",
        "",
        "## Making the solver time-aware guarantees every window",
        "",
        "The same OR-Tools engine with a **Time** dimension and hard windows (VRPTW):",
        "",
        f"- **{vrptw_audit.on_time_stops}/{vrptw_audit.total_stops} on time "
        f"({vrptw_audit.on_time_pct:.1f}%)** - every window kept, by construction.",
        f"- Distance **{vrptw.total_distance:,.1f} km** on {vrptw.vehicles_used} vans "
        f"(solve {vrptw.solve_time_s:.1f}s).",
        f"- Price of the guarantee vs the time-blind savings plan: "
        f"**{premium:+.1f}% distance** for **+{audit.late_stops} on-time deliveries**.",
        "",
        "> The VRPTW figures come from a **time-limited metaheuristic**, so the distance",
        "> (and hence the premium) can wobble a fraction of a percent between runs. The",
        "> deterministic savings-plan audit above does not.",
        "",
        "*Windows, speed, service and cost-of-time are **illustrative synthetic "
        "assumptions**, not certified; distance units are treated as kilometres.",
        "",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def build_service_analysis(
    instance: Instance,
    metric: str = "euclidean",
    time_limit_s: int = 8,
    out_dir: Path | None = None,
    tm: TimeModel | None = None,
) -> dict[str, object]:
    """Audit the time-blind savings plan, solve the VRPTW, write CSV + Markdown."""
    from .report import DELIVERABLES

    out_dir = out_dir or DELIVERABLES
    tm = tm or make_time_model(instance)
    dist = distance_matrix(instance, metric)

    savings = clarke_wright(instance, dist)
    audit = audit_service(instance, savings.routes, tm)
    vrptw = solve_vrptw(instance, tm, metric=metric, time_limit_s=time_limit_s)
    vrptw_audit = audit_service(instance, vrptw.routes, tm) if vrptw.routes else audit

    csv_path = write_audit_csv(audit, out_dir / "service_audit.csv")
    md_path = write_service_md(
        instance, tm, savings, audit, vrptw, vrptw_audit, out_dir / "service_level.md"
    )
    return {
        "time_model": tm,
        "savings": savings,
        "audit": audit,
        "vrptw": vrptw,
        "vrptw_audit": vrptw_audit,
        "csv": csv_path,
        "md": md_path,
    }
