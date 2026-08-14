"""Driver shifts: a working-time cap on the route, and the breaks inside it.

Every layer so far treats a van as a machine that can drive all day. A van
cannot: a *driver* can. The fleet-mix layer priced consolidation into fewer,
bigger vans and had to close with the caveat that "no route-duration cap is
modelled — the longest-route column is the service price"; the README lists
driver shifts as the next constraint. This module is that constraint.

It models a working day as three kinds of minute and nothing else:

* **drive** — ``distance x 60 / speed``, the same convention as the time-window
  layer,
* **service** — a fixed number of minutes at each customer,
* **break** — a mandated rest that the driver must take *before* continuous
  driving exceeds a threshold.

and enforces two limits on top: a cap on **total duty** (depot out to depot
back, breaks included) and a cap on **continuous driving** between breaks.

**Informed by EU driving-time rules, not a compliance certification.** The
default numbers are shaped by Regulation (EC) No 561/2006 — a 9-hour daily
driving limit (art. 6), a 45-minute break before 4.5 hours of continuous
driving (art. 7) — inside a 10-hour duty envelope. What is deliberately *not*
modelled: the 15+30 minute split break, the twice-weekly 10-hour driving
extension, multi-manning, daily/weekly rest between shifts, the working-time
directive's own separate limits, and the fact that a 5-minute delivery stop is
not a break. Nothing here should be used to decide whether a real roster is
legal.

Three things happen, in the order a dispatcher would want them:

1. **Audit** the plan you have. The deterministic Clarke-Wright savings plan
   is shift-blind; :func:`schedule_duty` walks each route minute by minute,
   inserts the breaks the rules require, and reports the duty each driver
   actually works. No solver, byte-for-byte reproducible.
2. **Solve** under a cap. :func:`solve_shift_capped` is the same OR-Tools CVRP
   model as :func:`routeopt.solver.solve_cvrp` with one added **Duty**
   dimension whose per-vehicle span is bounded — always under a fixed
   *solution limit*, never a wall clock, so the deliverables regenerate
   byte-identically. The bound handed to the solver is deliberately
   conservative: it is the largest drive+service span for which the breaks the
   rules will later insert *still* fit inside the duty cap
   (:func:`solver_span_cap`), so the plan the solver returns is legal after
   scheduling rather than legal-by-assertion. The audit re-checks it anyway.
3. **Price** the cap. :func:`sweep_shift_caps` walks the cap down and reads off
   what a shorter shift costs — more vans, more kilometres, and eventually a
   cap so short that one customer's out-and-back trip alone will not fit it,
   which no fleet size can rescue.

The honest result on the repo's synthetic instances is reported in
``deliverables/driver_shifts.md``: at the repo's own labelled assumptions the
statutory limits are **slack** — nobody is close to a 9-hour drive — so the
layer's value here is pricing a *shorter* shift (a half-day round, an agency
driver, a depot that has to close early), not certifying a legal one.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from ortools.constraint_solver import pywrapcp, routing_enums_pb2

from . import plate
from .heuristic import Solution, clarke_wright
from .model import Instance, distance_matrix, route_distance, scaled_int_matrix
from .solver import solve_cvrp

_SCALE = 100  # OR-Tools transits are integers; same convention as solver.py
SOLUTION_LIMIT = 200  # deterministic stopping rule (solutions, not seconds)

# The cap sweep: a full shift down to a short round. Chosen to straddle the
# point where the cap starts to bind on the repo's instances.
SHIFT_CAPS_MIN: tuple[int, ...] = (480, 420, 360, 300, 240, 210, 180)

DRIVE = "drive"
SERVICE = "service"
BREAK = "break"


@dataclass(frozen=True)
class ShiftRules:
    """A working day, in minutes. All values are **modelled assumptions**.

    ``max_shift_min`` bounds total duty — depot departure to depot return,
    breaks included. ``max_drive_min`` bounds the driving inside it.
    ``max_continuous_drive_min`` is how long a driver may drive before taking a
    break of ``break_min``. ``service_min`` and ``speed_kmh`` follow the
    time-window layer's conventions so the two layers agree on what a minute is.
    """

    max_shift_min: float = 600.0  # 10 h duty envelope
    max_drive_min: float = 540.0  # 9 h daily driving limit (EU 561/2006 art. 6)
    max_continuous_drive_min: float = 270.0  # 4.5 h (art. 7)
    break_min: float = 45.0  # the break that art. 7 requires
    service_min: float = 5.0  # fixed minutes at each customer
    speed_kmh: float = 40.0  # travel_min = distance * 60 / speed

    def __post_init__(self) -> None:
        for field_name in (
            "max_shift_min",
            "max_drive_min",
            "max_continuous_drive_min",
            "break_min",
            "speed_kmh",
        ):
            if float(getattr(self, field_name)) <= 0:
                raise ValueError(f"{field_name} must be positive")
        if float(self.service_min) < 0:
            raise ValueError("service_min must not be negative")
        if float(self.max_drive_min) > float(self.max_shift_min):
            raise ValueError("max_drive_min cannot exceed max_shift_min")

    @property
    def min_per_dist(self) -> float:
        """Minutes of driving per unit of distance."""
        return 60.0 / self.speed_kmh


@dataclass(frozen=True)
class DutyBlock:
    """One stretch of the working day: driving, serving a stop, or resting."""

    kind: str  # DRIVE | SERVICE | BREAK
    minutes: float
    node: int = -1  # the customer being served, for SERVICE blocks


@dataclass(frozen=True)
class DutySchedule:
    """What one driver actually works, once the mandated breaks are inserted."""

    vehicle: int
    blocks: tuple[DutyBlock, ...]
    stops: int
    distance: float
    drive_min: float
    service_min: float
    break_min: float
    duty_min: float
    breaks: int
    worst_continuous_drive_min: float
    over_shift_min: float  # minutes past the duty cap (0.0 when legal)
    over_drive_min: float  # minutes past the daily driving limit (0.0 when legal)

    @property
    def legal(self) -> bool:
        """Inside both modelled limits. **Modelled**, not a compliance verdict."""
        return self.over_shift_min <= 0.0 and self.over_drive_min <= 0.0


def schedule_duty(
    route: list[int], vehicle: int, depot: int, dist: np.ndarray, rules: ShiftRules
) -> DutySchedule:
    """Walk one route's working day and insert the breaks the rules require.

    The driver leaves the depot, drives, serves, and must stop for
    ``break_min`` before continuous driving would pass
    ``max_continuous_drive_min``; a long leg is split across as many breaks as
    it needs. A service stop is **not** treated as a break — five minutes at a
    door is not rest — which is the conservative reading and the one that makes
    the count reproducible.

    Pure arithmetic: no solver, no randomness. ``duty_min`` is exactly
    ``drive_min + service_min + break_min`` by construction.
    """
    limit = float(rules.max_continuous_drive_min)
    blocks: list[DutyBlock] = []
    drive = service = rest = 0.0
    continuous = 0.0
    worst_continuous = 0.0
    breaks = 0
    stops = 0

    for k in range(1, len(route)):
        prev, node = route[k - 1], route[k]
        remaining = float(dist[prev, node]) * rules.min_per_dist
        while continuous + remaining > limit:
            # Drive up to the threshold, then rest. The break resets the clock.
            leg = limit - continuous
            if leg > 0:
                blocks.append(DutyBlock(DRIVE, leg))
                drive += leg
                continuous += leg
                remaining -= leg
            worst_continuous = max(worst_continuous, continuous)
            blocks.append(DutyBlock(BREAK, float(rules.break_min)))
            rest += float(rules.break_min)
            breaks += 1
            continuous = 0.0
        if remaining > 0:
            blocks.append(DutyBlock(DRIVE, remaining))
            drive += remaining
            continuous += remaining
            worst_continuous = max(worst_continuous, continuous)
        if node != depot:
            blocks.append(DutyBlock(SERVICE, float(rules.service_min), node))
            service += float(rules.service_min)
            stops += 1

    duty = drive + service + rest
    return DutySchedule(
        vehicle=vehicle,
        blocks=tuple(blocks),
        stops=stops,
        distance=round(route_distance(route, dist), 3),
        drive_min=round(drive, 3),
        service_min=round(service, 3),
        break_min=round(rest, 3),
        duty_min=round(duty, 3),
        breaks=breaks,
        worst_continuous_drive_min=round(worst_continuous, 3),
        over_shift_min=round(max(0.0, duty - float(rules.max_shift_min)), 3),
        over_drive_min=round(max(0.0, drive - float(rules.max_drive_min)), 3),
    )


@dataclass(frozen=True)
class ShiftAudit:
    """The shift result of running a *given* set of routes under given rules."""

    schedules: tuple[DutySchedule, ...]
    vans: int
    vans_over_shift: int
    vans_over_drive: int
    worst_duty_min: float
    worst_over_shift_min: float
    worst_continuous_drive_min: float
    breaks: int
    total_distance: float

    @property
    def all_legal(self) -> bool:
        return self.vans_over_shift == 0 and self.vans_over_drive == 0


def audit_shifts(
    instance: Instance,
    routes: list[list[int]],
    rules: ShiftRules,
    metric: str = "euclidean",
    dist: np.ndarray | None = None,
) -> ShiftAudit:
    """Deterministic working-time audit of an arbitrary plan (no solver)."""
    dist = distance_matrix(instance, metric) if dist is None else dist
    schedules = tuple(
        schedule_duty(route, v, instance.depot, dist, rules)
        for v, route in enumerate(routes, start=1)
    )
    return ShiftAudit(
        schedules=schedules,
        vans=len(schedules),
        vans_over_shift=sum(1 for s in schedules if s.over_shift_min > 0),
        vans_over_drive=sum(1 for s in schedules if s.over_drive_min > 0),
        worst_duty_min=round(max((s.duty_min for s in schedules), default=0.0), 3),
        worst_over_shift_min=round(max((s.over_shift_min for s in schedules), default=0.0), 3),
        worst_continuous_drive_min=round(
            max((s.worst_continuous_drive_min for s in schedules), default=0.0), 3
        ),
        breaks=sum(s.breaks for s in schedules),
        total_distance=round(sum(s.distance for s in schedules), 3),
    )


def solver_span_cap(rules: ShiftRules) -> float:
    """The largest drive+service span that still fits the duty cap with breaks.

    The solver's Duty dimension counts driving and service — it does not know
    about breaks, which :func:`schedule_duty` inserts afterwards. So the bound
    handed to the solver must already have the breaks paid for.

    A route whose drive+service span is ``t`` cannot need more than
    ``ceil(t / max_continuous_drive) - 1`` breaks: every break is preceded by a
    full continuous-driving threshold, driving is never more than the whole
    span, and the walk never rests after the last kilometre. Spans in the
    window ``(k*D, (k+1)*D]`` therefore cost at most ``k`` breaks, so the
    largest span affordable with ``k`` breaks is
    ``min((k+1)*D, max_shift - k*break)``; the cap is the best of those, and
    never more than the daily driving limit (driving is bounded by the span).

    Conservative by construction — service minutes are counted against the
    driving threshold — so a plan inside this cap is legal *after* scheduling,
    which the audit then re-checks rather than assumes.
    """
    threshold = float(rules.max_continuous_drive_min)
    rest = float(rules.break_min)
    best = 0.0
    k = 0
    while True:
        budget = float(rules.max_shift_min) - k * rest
        window_lo = k * threshold
        if budget <= window_lo:
            break
        best = max(best, min((k + 1) * threshold, budget))
        k += 1
    return round(min(best, float(rules.max_drive_min)), 6)


def duty_greedy_plan(
    instance: Instance, dist: np.ndarray, rules: ShiftRules
) -> Solution | None:
    """A duty-aware greedy plan — feasibility proof and pool size in one pass.

    The same nearest-neighbour sweep as
    :func:`routeopt.heuristic.nearest_neighbour`, with one extra admission
    test: a customer may join the current round only if the driver can still
    reach it, serve it, *and* get home inside :func:`solver_span_cap`. Opening
    a fresh van is always allowed, so the only way this fails is when a single
    out-and-back trip to some customer already blows the cap — which is
    infeasible at **any** fleet size, and is the honest answer rather than a
    search that never terminates.

    Its van count is what sizes the vehicle pool for the capped solve below:
    the metaheuristic is then guaranteed a feasible region to search instead of
    exhausting an infeasible tree.
    """
    span_cap = solver_span_cap(rules)
    depot = instance.depot
    demands = instance.demands
    mpd = rules.min_per_dist
    service = float(rules.service_min)
    unvisited = set(range(instance.num_nodes)) - {depot}

    routes: list[list[int]] = []
    while unvisited:
        route = [depot]
        load = 0
        span = 0.0
        current = depot
        while True:
            candidates = [
                n
                for n in unvisited
                if load + demands[n] <= instance.capacity
                and span
                + (float(dist[current, n]) + float(dist[n, depot])) * mpd
                + service
                <= span_cap
            ]
            if not candidates:
                break
            nxt = min(candidates, key=lambda n: dist[current, n])
            span += float(dist[current, nxt]) * mpd + service
            route.append(nxt)
            load += int(demands[nxt])
            unvisited.remove(nxt)
            current = nxt
        if len(route) == 1:
            return None  # even one round trip does not fit — no fleet size helps
        route.append(depot)
        routes.append(route)

    return Solution.from_routes(
        "duty-greedy", routes, dist, demands, instance.capacity
    )


def solve_shift_capped(
    instance: Instance,
    rules: ShiftRules,
    metric: str = "euclidean",
    solution_limit: int = SOLUTION_LIMIT,
    fleet: int | None = None,
    log: bool = False,
) -> Solution:
    """CVRP + a per-vehicle working-time cap, on the base OR-Tools engine.

    Identical to :func:`routeopt.solver.solve_cvrp` — same arc costs, same
    capacity dimension, same first-solution strategy and guided local search —
    plus a **Duty** dimension whose transit is ``service(from) + travel(from,
    to)`` and whose cumulative value is bounded by :func:`solver_span_cap`.
    With the start cumulative fixed at zero the bound is exactly a per-route
    span limit, which is the shift cap with the mandated breaks already
    subtracted.

    ``fleet`` is how many vans the model may use; it defaults to the
    instance's own fleet. Callers that need a guaranteed-feasible region (the
    cap sweep) size it from :func:`duty_greedy_plan` instead, because a routing
    model with too few vans for the cap has no solution to stop at and a
    solution limit cannot end that search.

    Always deterministic: a fixed solution limit, never a wall clock. Returns
    the usual :class:`~routeopt.heuristic.Solution`; if the search finds
    nothing it comes back ``feasible=False`` with no routes.
    """
    dist = distance_matrix(instance, metric)
    idist = scaled_int_matrix(dist, _SCALE)
    n_nodes = instance.num_nodes
    n_vehicles = int(fleet if fleet is not None else instance.num_vehicles)

    manager = pywrapcp.RoutingIndexManager(n_nodes, n_vehicles, instance.depot)
    routing = pywrapcp.RoutingModel(manager)

    def distance_cb(from_index: int, to_index: int) -> int:
        return int(idist[manager.IndexToNode(from_index)][manager.IndexToNode(to_index)])

    transit_idx = routing.RegisterTransitCallback(distance_cb)
    routing.SetArcCostEvaluatorOfAllVehicles(transit_idx)

    def demand_cb(from_index: int) -> int:
        return int(instance.demands[manager.IndexToNode(from_index)])

    demand_idx = routing.RegisterUnaryTransitCallback(demand_cb)
    routing.AddDimensionWithVehicleCapacity(
        demand_idx, 0, [int(instance.capacity)] * n_vehicles, True, "Capacity"
    )

    # --- the working-time dimension: drive + service, span-capped -----------
    def duty_cb(from_index: int, to_index: int) -> int:
        i = manager.IndexToNode(from_index)
        j = manager.IndexToNode(to_index)
        at_stop = 0.0 if i == instance.depot else rules.service_min
        return int(round((at_stop + float(dist[i][j]) * rules.min_per_dist) * _SCALE))

    duty_idx = routing.RegisterTransitCallback(duty_cb)
    span_cap = int(round(solver_span_cap(rules) * _SCALE))
    routing.AddDimension(duty_idx, 0, span_cap, True, "Duty")

    routing.AddDimension(transit_idx, 0, int(idist.sum()), True, "Distance")

    params = pywrapcp.DefaultRoutingSearchParameters()
    params.first_solution_strategy = routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC
    params.local_search_metaheuristic = (
        routing_enums_pb2.LocalSearchMetaheuristic.GUIDED_LOCAL_SEARCH
    )
    params.solution_limit = int(solution_limit)  # deterministic — see solver.py
    params.log_search = bool(log)

    t0 = time.perf_counter()
    solution = routing.SolveWithParameters(params)
    elapsed = time.perf_counter() - t0

    if solution is None:
        return Solution(
            method="or-tools-shift",
            routes=[],
            total_distance=float("inf"),
            vehicles_used=0,
            loads=[],
            feasible=False,
            solve_time_s=elapsed,
        )

    routes: list[list[int]] = []
    for v in range(n_vehicles):
        index = routing.Start(v)
        route = [manager.IndexToNode(index)]
        while not routing.IsEnd(index):
            index = solution.Value(routing.NextVar(index))
            route.append(manager.IndexToNode(index))
        if len(route) > 2:
            routes.append(route)

    return Solution.from_routes(
        "or-tools-shift", routes, dist, instance.demands, instance.capacity, solve_time_s=elapsed
    )


# --- the cap sweep -----------------------------------------------------------


POOL_SLACK = 2  # spare vans in the search pool (same convention as fleetmix)


@dataclass(frozen=True)
class ShiftPoint:
    """One shift cap, priced: what the fleet has to do to finish inside it."""

    cap_min: int
    feasible: bool
    vans: int
    fleet: int  # vans the depot actually owns
    total_distance: float
    longest_route: float
    worst_duty_min: float
    worst_drive_min: float
    worst_continuous_drive_min: float
    breaks: int
    total_drive_min: float
    total_service_min: float
    total_break_min: float

    @property
    def over_fleet(self) -> int:
        """Vans this cap needs beyond the ones the depot owns (0 when it fits)."""
        return max(0, self.vans - self.fleet)


def _infeasible_point(cap_min: int, fleet: int) -> ShiftPoint:
    return ShiftPoint(
        cap_min=int(cap_min),
        feasible=False,
        vans=0,
        fleet=int(fleet),
        total_distance=0.0,
        longest_route=0.0,
        worst_duty_min=0.0,
        worst_drive_min=0.0,
        worst_continuous_drive_min=0.0,
        breaks=0,
        total_drive_min=0.0,
        total_service_min=0.0,
        total_break_min=0.0,
    )


def capped_rules(rules: ShiftRules, cap_min: float) -> ShiftRules:
    """``rules`` with the duty envelope moved to ``cap_min``.

    The driving limit follows the envelope down, so a 3-hour shift is never
    handed a 9-hour driving allowance.
    """
    return ShiftRules(
        max_shift_min=float(cap_min),
        max_drive_min=min(float(rules.max_drive_min), float(cap_min)),
        max_continuous_drive_min=rules.max_continuous_drive_min,
        break_min=rules.break_min,
        service_min=rules.service_min,
        speed_kmh=rules.speed_kmh,
    )


def price_shift_cap(
    instance: Instance,
    cap_min: int,
    rules: ShiftRules,
    metric: str = "euclidean",
    solution_limit: int = SOLUTION_LIMIT,
) -> ShiftPoint:
    """Solve under one shift cap and audit the answer against the same rules.

    The vehicle pool is sized from :func:`duty_greedy_plan` (plus
    :data:`POOL_SLACK`) rather than from the depot's own fleet: a routing model
    with too few vans for the cap has no solution for the solution limit to
    stop at, so the search would never end. Sizing the pool to a known-feasible
    plan keeps the run deterministic *and* bounded, and lets the answer be the
    more useful one — **how many vans this shift needs**, which
    :attr:`ShiftPoint.over_fleet` compares against what the depot owns.

    A cap that no fleet size can meet — one customer's out-and-back trip alone
    exceeds it — comes back ``feasible=False``. That is a proof, not a timeout.
    """
    capped = capped_rules(rules, cap_min)
    dist = distance_matrix(instance, metric)

    greedy = duty_greedy_plan(instance, dist, capped)
    if greedy is None:
        return _infeasible_point(cap_min, instance.num_vehicles)

    sol = solve_shift_capped(
        instance,
        capped,
        metric=metric,
        solution_limit=solution_limit,
        fleet=max(instance.num_vehicles, greedy.vehicles_used + POOL_SLACK),
    )
    if not sol.feasible or not sol.routes:
        sol = greedy  # the constructive plan is legal by construction

    audit = audit_shifts(instance, sol.routes, capped, dist=dist)
    return ShiftPoint(
        cap_min=int(cap_min),
        feasible=True,
        vans=sol.vehicles_used,
        fleet=int(instance.num_vehicles),
        total_distance=round(sol.total_distance, 3),
        longest_route=round(max(route_distance(r, dist) for r in sol.routes), 3),
        worst_duty_min=audit.worst_duty_min,
        worst_drive_min=round(max(s.drive_min for s in audit.schedules), 3),
        worst_continuous_drive_min=audit.worst_continuous_drive_min,
        breaks=audit.breaks,
        total_drive_min=round(sum(s.drive_min for s in audit.schedules), 3),
        total_service_min=round(sum(s.service_min for s in audit.schedules), 3),
        total_break_min=round(sum(s.break_min for s in audit.schedules), 3),
    )


def sweep_shift_caps(
    instance: Instance,
    rules: ShiftRules | None = None,
    caps_min: tuple[int, ...] = SHIFT_CAPS_MIN,
    metric: str = "euclidean",
    solution_limit: int = SOLUTION_LIMIT,
) -> list[ShiftPoint]:
    """Price every shift cap in ``caps_min``, longest first."""
    rules = rules or ShiftRules()
    return [
        price_shift_cap(
            instance, cap, rules, metric=metric, solution_limit=solution_limit
        )
        for cap in sorted(caps_min, reverse=True)
    ]


def _pct(base: float, other: float) -> float:
    return 100.0 * (other - base) / base if base else 0.0


def headline_read(
    instance: Instance,
    audit: ShiftAudit,
    points: list[ShiftPoint],
    uncapped: Solution,
    rules: ShiftRules,
) -> list[str]:
    """The plain-language read, reported exactly as the numbers fall."""
    lines: list[str] = []

    hours = rules.max_shift_min / 60.0
    if audit.vans_over_shift == 0:
        lines.append(
            f"Today's shift-blind savings plan already finishes inside the modelled "
            f"{hours:.0f}-hour envelope: worst duty {audit.worst_duty_min:,.0f} min on "
            f"{audit.vans} vans, {rules.max_shift_min - audit.worst_duty_min:,.0f} min of "
            f"headroom. The EU-informed limits are slack on this instance - the cap has "
            f"to come down before it costs anything."
        )
    else:
        lines.append(
            f"Today's shift-blind savings plan breaks the modelled {hours:.0f}-hour "
            f"envelope on {audit.vans_over_shift} of {audit.vans} vans, the worst by "
            f"{audit.worst_over_shift_min:,.0f} min (worst duty "
            f"{audit.worst_duty_min:,.0f} min)."
        )
    lines.append(
        f"Worst continuous drive in that plan: {audit.worst_continuous_drive_min:,.0f} min "
        f"against the {rules.max_continuous_drive_min:,.0f}-min break threshold "
        f"({rules.max_continuous_drive_min - audit.worst_continuous_drive_min:,.0f} min of "
        f"slack), so the rules insert {audit.breaks} break(s) - the break machinery is "
        f"exercised by the tests, not by this data."
    )

    feasible = [p for p in points if p.feasible]
    if feasible and uncapped.feasible:
        loosest = feasible[0]
        tightest = feasible[-1]
        lines.append(
            f"Loosest modelled cap ({loosest.cap_min} min): {loosest.vans} vans, "
            f"{loosest.total_distance:,.1f} km - "
            f"{_pct(uncapped.total_distance, loosest.total_distance):+.1f}% against the "
            f"uncapped solve ({uncapped.total_distance:,.1f} km on "
            f"{uncapped.vehicles_used} vans) under the same search budget."
        )
        lines.append(
            f"Tightest cap that still has a plan ({tightest.cap_min} min): "
            f"{tightest.vans} vans, {tightest.total_distance:,.1f} km - "
            f"{_pct(uncapped.total_distance, tightest.total_distance):+.1f}% distance and "
            f"{tightest.vans - uncapped.vehicles_used:+d} van(s) against the uncapped "
            f"solve. That is the price of a {tightest.cap_min / 60.0:.1f}-hour round, and "
            f"it is the service consequence the fleet-mix layer could only point at."
        )
        over = [p for p in feasible if p.over_fleet > 0]
        lines.append(
            f"Every feasible cap here still fits inside the depot's {instance.num_vehicles} "
            f"vans (widest need: {max(p.vans for p in feasible)})."
            if not over
            else f"Caps at or below {max(p.cap_min for p in over)} min need more vans than "
            f"the depot owns ({instance.num_vehicles}): up to "
            f"{max(p.vans for p in over)}."
        )
    infeasible = [p for p in points if not p.feasible]
    if infeasible:
        lines.append(
            f"At {', '.join(str(p.cap_min) for p in infeasible)} min there is no plan at "
            f"*any* fleet size: one customer's out-and-back round trip already exceeds the "
            f"cap. That is a proof, not a search-budget artifact."
        )
    return lines


# --- deliverables -----------------------------------------------------------

_CSV_HEADER = (
    "shift_cap_min,feasible,vans,total_distance_km,longest_route_km,worst_duty_min,"
    "worst_drive_min,worst_continuous_drive_min,breaks,total_drive_min,"
    "total_service_min,total_break_min"
)


def write_shifts_csv(points: list[ShiftPoint], path: Path) -> Path:
    lines = [_CSV_HEADER]
    for p in points:
        lines.append(
            f"{p.cap_min},{str(p.feasible).lower()},{p.vans},{p.total_distance:.3f},"
            f"{p.longest_route:.3f},{p.worst_duty_min:.3f},{p.worst_drive_min:.3f},"
            f"{p.worst_continuous_drive_min:.3f},{p.breaks},{p.total_drive_min:.3f},"
            f"{p.total_service_min:.3f},{p.total_break_min:.3f}"
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


_TICK_MIN = 120  # the minute axis ticks every two hours


def _axis_minutes(vmax: float) -> float:
    """Round a minute axis up to a clean two-hour tick (deterministic)."""
    return float(max(_TICK_MIN, int(math.ceil(vmax / _TICK_MIN)) * _TICK_MIN))


def write_shifts_svg(
    audit: ShiftAudit,
    points: list[ShiftPoint],
    uncapped: Solution,
    rules: ShiftRules,
    path: Path,
    title: str = "Driver shifts — the working day, capped",
    solution_limit: int = SOLUTION_LIMIT,
) -> Path:
    """Plate 05 — the shift board over the cap curve, on one shared minute axis.

    Panel A is the board a dispatcher would pin up: one horizontal bar per van
    of today's shift-blind savings plan, split into driving (courier blue),
    time at the kerb (haulage orange) and mandated breaks (road-marking
    amber), with the modelled duty envelope drawn as a signal-red rule and any
    over-cap tail painted the same signal red beside a label naming the
    breach. Panel B walks the cap down the *same* minute axis and reads off
    what each shorter shift costs in kilometres, direct-labelled with the van
    count; caps with no plan at any fleet size are marked in signal red
    rather than quietly dropped. One axis, shared by both panels — no dual scales.

    Every coordinate is rounded, so the file regenerates byte-identically.
    """
    w, h = plate.PLATE_W, 640
    px0, px1 = plate.MARGIN_L, w - plate.MARGIN_R

    caps = [p.cap_min for p in points]
    xmax = _axis_minutes(
        max([audit.worst_duty_min, float(rules.max_shift_min), float(max(caps))]) * 1.06
    )
    xticks = int(xmax // _TICK_MIN) + 1

    def sx(minutes: float) -> float:
        return round(px0 + (minutes / xmax) * (px1 - px0), 2)

    out = plate.open_svg(w, h)
    plate.plate_header(
        out, "05", title,
        f"or-tools, deterministic solution limit {solution_limit}; informed by EU "
        f"driving-time rules, not a compliance certification",
    )

    # --- panel A: the shift board --------------------------------------------
    a_py1, a_py0 = 116, 330
    plate.panel_title(
        out, px0, a_py1 - 18,
        "Duty per van — today's shift-blind savings plan (minutes worked)",
    )
    plate.x_grid(out, px0, px1, a_py0, a_py1, xmax, ticks=xticks)

    rows = list(audit.schedules)
    row_h = (a_py0 - a_py1) / max(len(rows), 1)
    bar_h = round(min(13.0, row_h * 0.62), 2)
    for i, s in enumerate(rows):
        y = round(a_py1 + i * row_h + (row_h - bar_h) / 2, 2)
        legal_min = min(s.duty_min, float(rules.max_shift_min))
        share = legal_min / s.duty_min if s.duty_min else 0.0
        segs = [
            (round(sx(s.drive_min * share) - px0, 2), plate.BLUE),
            (round(sx(s.service_min * share) - px0, 2), plate.ORANGE),
            (round(sx(s.break_min * share) - px0, 2), plate.MARKING_AMBER),
        ]
        if s.over_shift_min > 0:
            segs.append((round(sx(s.over_shift_min) - px0, 2), plate.SIGNAL_RED))
        end = plate.h_bar_segments(out, px0, y, bar_h, segs)
        out.append(
            f'<text x="{px0 - 8}" y="{round(y + bar_h - 2.5, 2)}" font-size="9.5" '
            f'text-anchor="end" fill="{plate.SECONDARY}">V{s.vehicle}</text>'
        )
        note = (
            f"{s.duty_min:,.0f} min &#183; +{s.over_shift_min:,.0f} over cap"
            if s.over_shift_min > 0
            else f"{s.duty_min:,.0f} min"
        )
        tone = plate.SIGNAL_RED if s.over_shift_min > 0 else plate.SECONDARY
        out.append(
            f'<text x="{round(end + 6, 2)}" y="{round(y + bar_h - 2.5, 2)}" font-size="9.5" '
            f'fill="{tone}">{note}</text>'
        )
    cap_x = sx(float(rules.max_shift_min))
    plate.rule_v(
        out, cap_x, a_py1 - 8, a_py0, plate.SIGNAL_RED,
        f"{rules.max_shift_min / 60.0:.0f} h duty cap",
        anchor="end" if cap_x > (px0 + px1) / 2 else "start",
        label_y=a_py1 - 12,
    )
    # The legend is the plate's fixed vocabulary; a term with nothing to point
    # at on this instance says so rather than quietly disappearing.
    none_break = "" if audit.breaks else " (none here)"
    none_over = "" if audit.vans_over_shift else " (none here)"
    plate.legend_swatch(out, px0 + 6, a_py0 + 36, plate.BLUE, "driving")
    plate.legend_swatch(out, px0 + 92, a_py0 + 36, plate.ORANGE, "at the kerb (service)")
    plate.legend_swatch(
        out, px0 + 254, a_py0 + 36, plate.MARKING_AMBER, f"mandated break{none_break}"
    )
    plate.legend_swatch(
        out, px0 + 424, a_py0 + 36, plate.SIGNAL_RED, f"over the cap{none_over}"
    )

    # --- panel B: what a shorter shift costs ---------------------------------
    b_py1, b_py0 = 428, 566
    plate.panel_title(
        out, px0, b_py1 - 18, "Planned distance (km) at each shift cap — vans labelled"
    )
    feasible = [p for p in points if p.feasible]
    kmax = max(
        [p.total_distance for p in feasible]
        + [uncapped.total_distance if uncapped.feasible else 0.0]
    )
    kmax = float(math.ceil(kmax / 250.0) * 250.0)
    plate.h_grid(out, px0, px1, b_py0, b_py1, kmax, ticks=6)
    plate.x_grid(out, px0, px1, b_py0, b_py1, xmax, ticks=xticks)

    def sy(v: float) -> float:
        return round(b_py0 + (v / kmax) * (b_py1 - b_py0), 2)

    # The caps that had no plan: a full-height rule through the column, so the
    # gap in the curve is visibly a wall rather than a missing measurement.
    for p in points:
        if p.feasible:
            continue
        x = sx(p.cap_min)
        out.append(
            f'<line x1="{x}" y1="{b_py0}" x2="{x}" y2="{b_py1}" '
            f'stroke="{plate.SIGNAL_RED}" stroke-width="1.5" '
            f'stroke-dasharray="{plate.DASH}"/>'
        )
        ym = round((b_py0 + b_py1) / 2, 2)
        for y_from, y_to in (((ym - 4), (ym + 4)), ((ym + 4), (ym - 4))):
            out.append(
                f'<line x1="{round(x - 4, 2)}" y1="{round(y_from, 2)}" '
                f'x2="{round(x + 4, 2)}" y2="{round(y_to, 2)}" '
                f'stroke="{plate.SIGNAL_RED}" stroke-width="2"/>'
            )
        out.append(
            f'<text x="{round(x + 9, 2)}" y="{round(ym + 3.5, 2)}" font-size="9.5" '
            f'font-weight="600" fill="{plate.SIGNAL_RED}">no plan at any fleet size</text>'
        )

    if uncapped.feasible:
        yref = sy(uncapped.total_distance)
        out.append(
            f'<line x1="{px0}" y1="{yref}" x2="{px1}" y2="{yref}" '
            f'stroke="{plate.REF_GRAY}" stroke-width="2" stroke-dasharray="{plate.DASH}"/>'
        )
        plate.direct_label(
            out, round(px1 - 2, 2), round(yref + 15, 2),
            f"uncapped solve {uncapped.total_distance:,.0f} km on "
            f"{uncapped.vehicles_used} vans", anchor="end",
        )
    pts = [(sx(p.cap_min), sy(p.total_distance)) for p in reversed(feasible)]
    if pts:
        plate.series_line(out, pts, plate.BLUE)
    for p in feasible:
        plate.direct_label(
            out, sx(p.cap_min), round(sy(p.total_distance) - 9, 2),
            f"{p.vans} vans", anchor="middle",
        )

    plate.x_axis_label(
        out, px0, px1, 604,
        "minutes of the working day — duty worked (top), shift cap offered (bottom)",
    )
    plate.footer(
        out, w, h,
        "One shared minute axis, no dual scales. Fixed solution limit — regenerates "
        "byte-identically. Table: driver_shifts.csv / .md",
    )
    plate.close_svg(out)

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(out) + "\n", encoding="utf-8")
    return path


def write_shifts_md(
    instance: Instance,
    rules: ShiftRules,
    audit: ShiftAudit,
    points: list[ShiftPoint],
    uncapped: Solution,
    read: list[str],
    path: Path,
    solution_limit: int = SOLUTION_LIMIT,
) -> Path:
    lines = [
        f"# Driver shifts & working time — `{instance.name}`",
        "",
        f"- **{instance.num_customers}** customers, fleet **{instance.num_vehicles}** vans. "
        f"A working day is modelled as **driving** (distance x 60 / "
        f"{rules.speed_kmh:.0f} km/h), **service** ({rules.service_min:.0f} min per stop) "
        f"and **breaks**, under a **{rules.max_shift_min:.0f} min duty envelope**, a "
        f"**{rules.max_drive_min:.0f} min daily driving limit**, and a "
        f"**{rules.break_min:.0f} min break** before "
        f"**{rules.max_continuous_drive_min:.0f} min** of continuous driving.",
        "- These numbers are **informed by EU Regulation (EC) No 561/2006** (art. 6 daily "
        "driving, art. 7 breaks) — they are **not a compliance certification**. The split "
        "15+30 break, the twice-weekly 10-hour driving extension, multi-manning, daily and "
        "weekly rest, and the Working Time Directive's own limits are **not modelled**, and "
        "a service stop is deliberately **not** counted as rest.",
        f"- Engine: the same or-tools CVRP model as the base solver plus a **Duty** "
        f"dimension whose per-vehicle span is capped, pinned to a fixed **solution limit "
        f"({solution_limit})** — deterministic, so this file regenerates byte-identically. "
        f"The span handed to the solver ({solver_span_cap(rules):,.0f} min of drive+service) "
        f"is the duty cap with the breaks the rules will insert already paid for, so the "
        f"plan is legal *after* scheduling — and the audit below re-checks it rather than "
        f"assuming it.",
        "",
        "## Today's plan, audited",
        "",
        "The deterministic Clarke-Wright savings plan is shift-blind. Walking each route "
        "minute by minute and inserting the breaks the rules require:",
        "",
        f"- **{audit.vans - audit.vans_over_shift}/{audit.vans} vans** finish inside the "
        f"{rules.max_shift_min:.0f}-min envelope; worst duty **{audit.worst_duty_min:,.0f} "
        f"min**.",
        f"- **{audit.vans - audit.vans_over_drive}/{audit.vans} vans** are inside the "
        f"{rules.max_drive_min:.0f}-min driving limit.",
        f"- Worst continuous drive **{audit.worst_continuous_drive_min:,.0f} min** against "
        f"the {rules.max_continuous_drive_min:.0f}-min break threshold; "
        f"**{audit.breaks}** break(s) inserted across the fleet.",
        "",
        "| Van | Stops | Distance (km) | Drive (min) | Service (min) | Breaks | Break (min) | **Duty (min)** | Over cap (min) |",
        "|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for s in audit.schedules:
        lines.append(
            f"| V{s.vehicle} | {s.stops} | {s.distance:,.1f} | {s.drive_min:,.0f} | "
            f"{s.service_min:,.0f} | {s.breaks} | {s.break_min:,.0f} | "
            f"**{s.duty_min:,.0f}** | {s.over_shift_min:,.0f} |"
        )
    lines += [
        "",
        "## What a shorter shift costs",
        "",
        "The cap walked down, each point re-solved and re-audited under the identical "
        "deterministic budget. The uncapped solve is the reference: "
        + (
            f"**{uncapped.total_distance:,.1f} km** on **{uncapped.vehicles_used}** vans."
            if uncapped.feasible
            else "no feasible uncapped plan."
        ),
        "",
        "| Shift cap (min) | Feasible | Vans | Distance (km) | Longest route (km) | Worst duty (min) | Worst continuous drive (min) | Breaks |",
        "|---:|:--:|---:|---:|---:|---:|---:|---:|",
    ]
    for p in points:
        if not p.feasible:
            lines.append(
                f"| {p.cap_min} | **no** | — | — | — | — | — | — |"
            )
            continue
        lines.append(
            f"| {p.cap_min} | yes | {p.vans} | {p.total_distance:,.1f} | "
            f"{p.longest_route:,.1f} | {p.worst_duty_min:,.0f} | "
            f"{p.worst_continuous_drive_min:,.0f} | {p.breaks} |"
        )
    lines += ["", "## The read", ""]
    lines += [f"- {r}" for r in read]
    lines += [
        "",
        "**Honest caveats.** This is a *modelled* working day, not a compliance tool — see "
        "the rule list above for what is left out. Travel time is straight-line distance at "
        "a single flat speed with no congestion, no time windows and no depot loading time, "
        "so a real duty would be longer than every number here. Every capped plan is a good "
        "heuristic solution under a fixed search budget, **not a proven optimum**: the "
        "distance curve need not be monotone in the cap. An **infeasible** cap is the one "
        "exception: it is proved by construction (some customer's out-and-back round trip "
        "alone exceeds the cap), not inferred from a search that gave up. The break rule "
        "is exercised and hand-checked in the test suite; whether it fires on a given "
        "instance depends on that instance's driving times.",
        "",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def build_driver_shifts(
    instance: Instance,
    metric: str = "euclidean",
    out_dir: Path | None = None,
    rules: ShiftRules | None = None,
    caps_min: tuple[int, ...] = SHIFT_CAPS_MIN,
    solution_limit: int = SOLUTION_LIMIT,
) -> dict[str, object]:
    """Audit today's plan, price every shift cap, write CSV + SVG + Markdown."""
    from .report import DELIVERABLES

    out_dir = out_dir or DELIVERABLES
    rules = rules or ShiftRules()
    dist = distance_matrix(instance, metric)

    savings = clarke_wright(instance, dist)
    audit = audit_shifts(instance, savings.routes, rules, dist=dist)
    uncapped = solve_cvrp(instance, metric=metric, solution_limit=solution_limit)
    points = sweep_shift_caps(
        instance, rules=rules, caps_min=caps_min, metric=metric, solution_limit=solution_limit
    )
    read = headline_read(instance, audit, points, uncapped, rules)

    csv_path = write_shifts_csv(points, out_dir / "driver_shifts.csv")
    svg_path = write_shifts_svg(
        audit, points, uncapped, rules, out_dir / "driver_shifts.svg",
        title=f"Driver shifts - the working day, capped - {instance.name}",
        solution_limit=solution_limit,
    )
    md_path = write_shifts_md(
        instance, rules, audit, points, uncapped, read,
        out_dir / "driver_shifts.md", solution_limit=solution_limit,
    )
    return {
        "rules": rules,
        "savings": savings,
        "audit": audit,
        "uncapped": uncapped,
        "points": points,
        "read": read,
        "csv": csv_path,
        "svg": svg_path,
        "md": md_path,
    }
