"""Fleet-size / cost / service sensitivity — the what-if a fleet planner weighs.

The routing model minimises *total distance*. With no fixed per-vehicle cost it
naturally prefers **fewer, fuller vans** (fewer depot round-trips is less
distance), so "minimum vehicles" and "minimum distance" pull the same way. The
real tension is with **service**: fuller vans mean longer individual routes, so
the last customer on a round waits longer.

This module makes that trade-off explicit. It turns the fleet-sizing lever —
**vehicle capacity** (bigger vans ⇒ fewer vans) — across a grid and reads off,
for each resulting fleet size, the deterministic Clarke-Wright savings plan:

* ``vehicles`` — how many vans the savings heuristic then needs,
* ``total_distance`` — the cost axis (fewer/bigger vans ⇒ less total distance),
* ``longest_route`` — a service proxy (the worst single route ≈ time to the last
  customer); it grows as the fleet consolidates,
* ``est_cost_eur`` and ``est_co2_kg`` — *illustrative*, labelled, not certified.

Everything reuses the existing :func:`routeopt.heuristic.clarke_wright`, which is
deterministic, so the committed table/SVG are byte-for-byte reproducible. OR-Tools
would shave a few percent off every point (see the headline README comparison)
without changing the *shape* of the trade-off.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path

from . import plate
from .heuristic import clarke_wright
from .model import Instance, distance_matrix, route_distance

# --- illustrative conversion factors (labelled estimates, NOT certified) -----
# Same assumptions as docs/BUSINESS_CASE.md, kept in one place so they are easy
# to change. Distance units are treated as kilometres, per the repo convention.
CO2_G_PER_KM = 250.0  # a diesel light-commercial van — illustrative estimate
COST_EUR_PER_KM = 1.0  # fuel + driver time + wear, German LCV — illustrative


@dataclass(frozen=True)
class FleetPoint:
    """One plan on the fleet-size frontier."""

    vehicles: int
    capacity: int
    total_distance: float
    longest_route: float
    est_cost_eur: float
    est_co2_kg: float


def default_capacity_grid(instance: Instance) -> list[int]:
    """A sensible van-capacity sweep: roughly half-size to double-size vans.

    Bounded below by the largest single demand (a customer must fit in one van)
    and centred on the instance's own capacity, so the frontier straddles the
    instance's real operating point.
    """
    q0 = int(instance.capacity)
    max_demand = int(instance.demands.max())
    lo = max(max_demand, round(0.5 * q0))
    hi = max(lo + 1, round(2.0 * q0))
    return list(range(lo, hi + 1))


def _plan_at_capacity(instance: Instance, capacity: int, metric: str) -> FleetPoint | None:
    """Solve one capacity with Clarke-Wright; None if that capacity is infeasible."""
    if capacity < int(instance.demands.max()):
        return None  # a single customer would not fit in one van
    total_demand = int(instance.demands.sum())
    fleet = max(int(instance.num_vehicles), -(-total_demand // capacity) + 5)
    inst = replace(instance, capacity=int(capacity), num_vehicles=fleet)
    dist = distance_matrix(inst, metric)
    sol = clarke_wright(inst, dist)
    if not sol.feasible or not sol.routes:
        return None
    longest = max(route_distance(r, dist) for r in sol.routes)
    return FleetPoint(
        vehicles=sol.vehicles_used,
        capacity=int(capacity),
        total_distance=round(sol.total_distance, 3),
        longest_route=round(longest, 3),
        est_cost_eur=round(sol.total_distance * COST_EUR_PER_KM, 2),
        est_co2_kg=round(sol.total_distance * CO2_G_PER_KM / 1000.0, 2),
    )


def sweep_fleet(
    instance: Instance,
    capacities: list[int] | None = None,
    metric: str = "euclidean",
) -> list[FleetPoint]:
    """Efficient fleet-size frontier: for each fleet size, the min-distance plan.

    Sweeps van capacity, runs the deterministic savings heuristic at each, and
    keeps — per distinct number of vehicles used — the plan with the smallest
    total distance. Returned sorted by fleet size ascending.
    """
    caps = capacities if capacities is not None else default_capacity_grid(instance)
    best: dict[int, FleetPoint] = {}
    for cap in caps:
        pt = _plan_at_capacity(instance, cap, metric)
        if pt is None:
            continue
        cur = best.get(pt.vehicles)
        if cur is None or pt.total_distance < cur.total_distance:
            best[pt.vehicles] = pt
    return [best[v] for v in sorted(best)]


def operating_vehicles(instance: Instance, metric: str = "euclidean") -> int:
    """How many vans the savings heuristic uses at the instance's own capacity."""
    dist = distance_matrix(instance, metric)
    return clarke_wright(instance, dist).vehicles_used


def _pct(base: float, other: float) -> float:
    return 100.0 * (other - base) / base if base else 0.0


def trade_off_read(frontier: list[FleetPoint], pivot_vehicles: int) -> list[str]:
    """The plain-language read: what one van costs, and what consolidation buys.

    Directions are reported exactly as the numbers fall. For this min-distance
    model, *fewer* vans means *less* distance and CO2 but a *longer* worst route
    (worse service) — the opposite of the naive "fewer vans, more driving".
    """
    if not frontier:
        return ["(frontier empty — no feasible plan in the swept range)"]
    by_v = {p.vehicles: p for p in frontier}
    sizes = sorted(by_v)
    if pivot_vehicles not in by_v:
        pivot_vehicles = min(sizes, key=lambda v: abs(v - pivot_vehicles))
    pivot = by_v[pivot_vehicles]
    lines = [
        f"Operating point - {pivot.vehicles} vans (capacity {pivot.capacity}): "
        f"{pivot.total_distance:,.1f} km, ~{pivot.est_co2_kg:,.1f} kg CO2 "
        f"(illustrative at {CO2_G_PER_KM:.0f} g/km), ~EUR {pivot.est_cost_eur:,.0f}.",
    ]
    fewer = [v for v in sizes if v < pivot_vehicles]
    if fewer:
        nxt = by_v[max(fewer)]
        lines.append(
            f"Consolidating {pivot.vehicles} -> {nxt.vehicles} vans (bigger vans): "
            f"total distance {_pct(pivot.total_distance, nxt.total_distance):+.1f}% "
            f"and CO2 {_pct(pivot.est_co2_kg, nxt.est_co2_kg):+.1f}%, "
            f"while the longest route moves "
            f"{_pct(pivot.longest_route, nxt.longest_route):+.1f}% (service)."
        )
        lean = by_v[min(sizes)]
        if lean.vehicles < pivot_vehicles:
            lines.append(
                f"Leanest modelled fleet - {lean.vehicles} vans: distance "
                f"{_pct(pivot.total_distance, lean.total_distance):+.1f}% and CO2 "
                f"{_pct(pivot.est_co2_kg, lean.est_co2_kg):+.1f}% vs the operating point, "
                f"but the longest route "
                f"{_pct(pivot.longest_route, lean.longest_route):+.1f}% (the service cost)."
            )
    more = [v for v in sizes if v > pivot_vehicles]
    if more:
        nxt = by_v[min(more)]
        lines.append(
            f"Adding a van {pivot.vehicles} -> {nxt.vehicles}: total distance "
            f"{_pct(pivot.total_distance, nxt.total_distance):+.1f}% and CO2 "
            f"{_pct(pivot.est_co2_kg, nxt.est_co2_kg):+.1f}%, longest route "
            f"{_pct(pivot.longest_route, nxt.longest_route):+.1f}% (service)."
        )
    return lines


# --- deliverables -----------------------------------------------------------

_CSV_HEADER = "vehicles,van_capacity,total_distance_km,longest_route_km,est_cost_eur,est_co2_kg"


def write_sensitivity_csv(frontier: list[FleetPoint], path: Path) -> Path:
    lines = [_CSV_HEADER]
    for p in frontier:
        lines.append(
            f"{p.vehicles},{p.capacity},{p.total_distance:.3f},"
            f"{p.longest_route:.3f},{p.est_cost_eur:.2f},{p.est_co2_kg:.2f}"
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _nice_ceiling(value: float) -> float:
    """Round an axis maximum up to a clean 1/2/5 * 10^k value (deterministic)."""
    if value <= 0:
        return 1.0
    import math

    exp = math.floor(math.log10(value))
    base = 10.0**exp
    for mult in (1.0, 2.0, 2.5, 5.0, 10.0):
        if mult * base >= value:
            return mult * base
    return 10.0 * base


def write_sensitivity_svg(
    frontier: list[FleetPoint], path: Path, title: str = "Fleet-size sensitivity"
) -> Path:
    """Plate 02 — the trade-off frontier as two stacked panels (one axis each).

    Panel A: total distance (km), the cost axis. Panel B: longest single route
    (km), the service proxy. Both share the fleet-size x axis — no dual-axis
    chart. Hand-drawn SVG on the shared plate system; every coordinate is
    rounded, so the file is byte-for-byte identical across re-runs.
    """
    w, h = plate.PLATE_W, 640
    px0, px1 = plate.MARGIN_L, w - plate.MARGIN_R

    vs = [p.vehicles for p in frontier]
    vmin, vmax = min(vs), max(vs)
    vspan = (vmax - vmin) or 1
    dmax = _nice_ceiling(max(p.total_distance for p in frontier))
    lmax = _nice_ceiling(max(p.longest_route for p in frontier))

    def sx(v: float) -> float:
        return round(px0 + (v - vmin) / vspan * (px1 - px0), 2)

    def sy(v: float, vcap: float, py0: float, py1: float) -> float:
        return round(py0 + (v / vcap) * (py1 - py0), 2)

    out = plate.open_svg(w, h)
    plate.plate_header(
        out, "02", title,
        f"Clarke-Wright savings; CO2 {CO2_G_PER_KM:.0f} g/km &amp; cost EUR "
        f"{COST_EUR_PER_KM:.2f}/km are illustrative estimates",
    )

    panels = (
        ("Total distance (km) — the cost axis, and the CO2/cost line with it",
         dmax, plate.BLUE, [(p.vehicles, p.total_distance) for p in frontier], 130, 306),
        ("Longest single route (km) — the service proxy: time to the last customer",
         lmax, plate.ORANGE, [(p.vehicles, p.longest_route) for p in frontier], 386, 562),
    )
    for ptitle, vcap, colour, series, py1, py0 in panels:
        plate.panel_title(out, px0, py1 - 18, ptitle)
        plate.h_grid(out, px0, px1, py0, py1, vcap)
        for v, _ in series:
            plate.x_tick(out, sx(v), py0, f"{v}")
        pts = [(sx(v), sy(val, vcap, py0, py1)) for v, val in series]
        plate.series_line(out, pts, colour)
        # selective direct labels: first and last point of each panel
        for (x, y), (_, val), anchor in (
            (pts[0], series[0], "start"),
            (pts[-1], series[-1], "end"),
        ):
            plate.direct_label(out, x, round(y - 9, 2), f"{val:,.0f}", anchor=anchor)

    plate.x_axis_label(out, px0, px1, 600, "vehicles used (fleet size)")
    plate.footer(
        out, w, h,
        "One measure per panel, shared fleet-size axis. Deterministic savings sweep — "
        "the file regenerates byte-identically. Table: fleet_sensitivity.csv / .md",
    )
    plate.close_svg(out)

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(out) + "\n", encoding="utf-8")
    return path


def write_sensitivity_md(
    instance: Instance,
    frontier: list[FleetPoint],
    read: list[str],
    path: Path,
) -> Path:
    lines = [
        f"# Fleet-size sensitivity — `{instance.name}`",
        "",
        f"- Customers **{instance.num_customers}**, total demand **{instance.total_demand}**. "
        f"Engine: **Clarke-Wright savings** (deterministic). Van capacity is swept; the "
        f"number of vehicles is what the heuristic then needs.",
        f"- CO2 at **{CO2_G_PER_KM:.0f} g/km** and cost at **EUR {COST_EUR_PER_KM:.2f}/km** "
        f"are **illustrative estimates**, not certified; distance units are treated as km.",
        "",
        "| Vehicles | Van capacity | Total distance (km) | Longest route (km) | Est. cost (EUR) | Est. CO2 (kg) |",
        "|---:|---:|---:|---:|---:|---:|",
    ]
    for p in frontier:
        lines.append(
            f"| {p.vehicles} | {p.capacity} | {p.total_distance:,.1f} | "
            f"{p.longest_route:,.1f} | {p.est_cost_eur:,.0f} | {p.est_co2_kg:,.1f} |"
        )
    lines += ["", "## The trade-off", ""]
    lines += [f"- {r}" for r in read]
    lines += [
        "",
        "Cost here is **variable only** (distance x EUR/km). A fleet also carries a "
        "fixed per-van cost (purchase, insurance, driver); adding it shifts the optimum "
        "further toward fewer vans. The frontier is intentionally left as variable cost "
        "so a planner can layer their own fixed cost on top.",
        "",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def build_fleet_sensitivity(
    instance: Instance,
    metric: str = "euclidean",
    out_dir: Path | None = None,
) -> dict[str, object]:
    """Sweep the fleet, write CSV + SVG + Markdown, and return everything."""
    from .report import DELIVERABLES

    out_dir = out_dir or DELIVERABLES
    frontier = sweep_fleet(instance, metric=metric)
    pivot = operating_vehicles(instance, metric=metric)
    read = trade_off_read(frontier, pivot)
    csv_path = write_sensitivity_csv(frontier, out_dir / "fleet_sensitivity.csv")
    svg_path = write_sensitivity_svg(
        frontier, out_dir / "fleet_sensitivity.svg",
        title=f"Fleet-size sensitivity - {instance.name}",
    )
    md_path = write_sensitivity_md(instance, frontier, read, out_dir / "fleet_sensitivity.md")
    return {
        "frontier": frontier,
        "operating_vehicles": pivot,
        "read": read,
        "csv": csv_path,
        "svg": svg_path,
        "md": md_path,
    }
