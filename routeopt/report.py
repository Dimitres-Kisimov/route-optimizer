"""Deliverables: a route-plan CSV, a routes PNG, and a summary Markdown file.

Everything a dispatcher or a reviewer would actually want to look at, written to
``deliverables/``.

The routes PNG is **Plate 01** of the dispatch board (see :mod:`routeopt.plate`
for the shared design system): a dispatcher's wall map with a quiet basemap
grid, the depot as an anchor mark, per-vehicle routes in the validated
categorical palette (fixed slots, never cycled; dashed beyond slot 8), demand
as node area with a size key, direct ``V<n>`` route labels, and — when a
baseline solution is supplied — the heuristic plan as a recessive gray
underlay beneath the inked optimized routes.
"""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # headless / CI-safe
import matplotlib.patheffects as path_effects  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from . import plate  # noqa: E402
from .heuristic import Solution, clarke_wright, nearest_neighbour  # noqa: E402
from .model import Instance, distance_matrix, route_distance  # noqa: E402
from .solver import solve_cvrp  # noqa: E402

DELIVERABLES = Path(__file__).resolve().parent.parent / "deliverables"


def route_plan_frame(instance: Instance, solution: Solution, metric: str = "euclidean") -> pd.DataFrame:
    """One row per stop: vehicle, order, customer, demand, load-so-far, cumulative km."""
    dist = distance_matrix(instance, metric)
    rows = []
    for v, route in enumerate(solution.routes, start=1):
        load = 0
        cum = 0.0
        for order, node in enumerate(route):
            if order > 0:
                cum += float(dist[route[order - 1], node])
            demand = int(instance.demands[node])
            load += demand
            rows.append(
                {
                    "vehicle": v,
                    "stop_order": order,
                    "node": node,
                    "is_depot": node == instance.depot,
                    "demand": demand,
                    "load_after_stop": load,
                    "cumulative_distance": round(cum, 3),
                    "x": float(instance.coords[node][0]),
                    "y": float(instance.coords[node][1]),
                }
            )
    return pd.DataFrame(rows)


def write_route_plan_csv(instance: Instance, solution: Solution, path: Path, metric: str = "euclidean") -> Path:
    df = route_plan_frame(instance, solution, metric)
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False)
    return path


def _halo(linewidth: float = 2.6) -> list[path_effects.AbstractPathEffect]:
    """A surface-coloured halo so labels stay legible over lines and nodes."""
    return [path_effects.withStroke(linewidth=linewidth, foreground=plate.SURFACE)]


def _demand_area(demand: float, max_demand: float) -> float:
    """Marker area (pt^2) strictly proportional to demand — honest node sizing."""
    return 180.0 * float(demand) / float(max_demand)


def plot_routes(
    instance: Instance,
    solution: Solution,
    path: Path,
    title: str | None = None,
    baseline: Solution | None = None,
    metric: str = "euclidean",
) -> Path:
    """Plate 01 — the dispatch-board route map.

    Quiet basemap grid; depot as a concentric anchor mark; per-vehicle routes
    in the validated fixed-slot palette (dashed beyond slot 8 — colour+dash,
    never a cycled hue) with direct ``V<n>`` labels; customer nodes sized by
    demand (area-proportional) with a size key; optional ``baseline`` plan as
    a recessive gray underlay — emphasis (ink vs gray), not two rainbows.
    """
    coords = instance.coords
    depot = instance.depot
    dist = distance_matrix(instance, metric)
    cust = [n for n in range(instance.num_nodes) if n != depot]
    max_demand = max(float(instance.demands.max()), 1.0)

    fig = plt.figure(figsize=(10.0, 8.6), dpi=120)
    fig.patch.set_facecolor(plate.SURFACE)
    ax = fig.add_axes([0.055, 0.06, 0.615, 0.795])
    ax_leg = fig.add_axes([0.71, 0.06, 0.265, 0.795])
    ax_leg.set_xlim(0, 1)
    ax_leg.set_ylim(0, 1)
    ax_leg.axis("off")

    # --- header: numbered plate, honest title and framing --------------------
    ttl = title or (
        f"{instance.name}: {solution.method} — "
        f"{solution.total_distance:.0f} distance, {solution.vehicles_used} vehicles"
    )
    fig.text(
        0.055, 0.962, "PLATE 01 · DISPATCH BOARD — ROUTE MAP",
        fontsize=9, fontweight="bold", color=plate.MUTED,
    )
    fig.text(0.055, 0.922, ttl, fontsize=15, fontweight=600, color=plate.INK)
    sub_y = 0.893
    if baseline is not None:
        fig.text(
            0.055, sub_y,
            f"gray underlay — {baseline.method} baseline: "
            f"{baseline.total_distance:.0f} distance, {baseline.vehicles_used} vehicles",
            fontsize=9.5, color=plate.SECONDARY,
        )
        sub_y = 0.869
    fig.text(
        0.055, sub_y,
        f"synthetic instance · {metric} straight-line distances treated as km · "
        f"node area ∝ demand",
        fontsize=9.5, color=plate.SECONDARY,
    )

    # --- quiet basemap -------------------------------------------------------
    ax.set_facecolor(plate.SURFACE)
    ax.set_axisbelow(True)
    ax.grid(True, color=plate.GRID, linewidth=0.7)
    for spine in ax.spines.values():
        spine.set_color(plate.AXIS)
        spine.set_linewidth(0.8)
    ax.tick_params(colors=plate.AXIS, labelcolor=plate.MUTED, labelsize=7.5, length=3, width=0.8)
    ax.set_xlabel("x", fontsize=9, color=plate.SECONDARY)
    ax.set_ylabel("y", fontsize=9, color=plate.SECONDARY)
    xmin, xmax = float(coords[:, 0].min()), float(coords[:, 0].max())
    ymin, ymax = float(coords[:, 1].min()), float(coords[:, 1].max())
    span = max(xmax - xmin, ymax - ymin) or 1.0
    pad = 0.07 * span
    ax.set_xlim(xmin - pad, xmax + pad)
    ax.set_ylim(ymin - pad, ymax + pad)
    ax.set_aspect("equal", adjustable="box")
    ax.set_anchor("NW")

    # --- baseline underlay: the quiet gray reference -------------------------
    if baseline is not None:
        for route in baseline.routes:
            ax.plot(
                [coords[n][0] for n in route], [coords[n][1] for n in route],
                "-", color=plate.BASELINE_GRAY, linewidth=1.15, zorder=1.6,
                solid_capstyle="round",
            )

    # --- the inked answer: fixed-slot routes with direct labels --------------
    for v, route in enumerate(solution.routes, start=1):
        colour, dashed = plate.vehicle_style(v)
        ax.plot(
            [coords[n][0] for n in route], [coords[n][1] for n in route],
            color=colour, linewidth=1.9, zorder=2.2, solid_capstyle="round",
            linestyle=(0, (5, 2.2)) if dashed else "-",
        )
        stops = [n for n in route if n != depot]
        if stops:  # label at the route's far point, pushed outward from the depot
            far = max(stops, key=lambda n: float(np.hypot(*(coords[n] - coords[depot]))))
            direction = coords[far] - coords[depot]
            norm = float(np.hypot(*direction)) or 1.0
            lx, ly = coords[far] + direction / norm * (0.055 * span)
            ax.text(
                lx, ly, f"V{v}", fontsize=9, fontweight="bold", color=colour,
                ha="center", va="center", zorder=8, path_effects=_halo(3.0),
            )

    # --- customers: demand as node area, ringed in white ---------------------
    ax.scatter(
        coords[cust, 0], coords[cust, 1],
        s=[_demand_area(instance.demands[n], max_demand) for n in cust],
        facecolor="#ffffff", edgecolor=plate.SECONDARY, linewidths=0.8, zorder=3,
    )

    # --- depot: the anchor mark ----------------------------------------------
    dx, dy = float(coords[depot][0]), float(coords[depot][1])
    ax.scatter([dx], [dy], s=430, facecolor="#ffffff", edgecolor=plate.INK, linewidths=1.5, zorder=5)
    ax.scatter([dx], [dy], s=140, facecolor="none", edgecolor=plate.INK, linewidths=1.1, zorder=6)
    ax.scatter([dx], [dy], s=26, facecolor=plate.INK, zorder=7)
    ax.annotate(
        "DEPOT", (dx, dy), xytext=(0, -15), textcoords="offset points",
        ha="center", va="top", fontsize=7, fontweight="bold", color=plate.INK,
        path_effects=_halo(2.4), zorder=8,
    )

    # --- side panel: vehicles, baseline, size key, depot key ------------------
    def _row(y: float, colour: str, dashed: bool, text: str, lw: float = 2.2) -> None:
        ax_leg.plot(
            [0.02, 0.15], [y, y], color=colour, linewidth=lw,
            linestyle=(0, (5, 2.2)) if dashed else "-", solid_capstyle="round",
        )
        ax_leg.text(0.20, y, text, fontsize=8.2, color=plate.SECONDARY, va="center")

    def _section(y: float, text: str) -> None:
        ax_leg.text(0.02, y, text, fontsize=8, fontweight="bold", color=plate.MUTED)

    yy = 0.985
    _section(yy, "VEHICLES")
    yy -= 0.045
    dy_row = min(0.042, 0.55 / max(len(solution.routes), 1))
    for v, route in enumerate(solution.routes, start=1):
        colour, dashed = plate.vehicle_style(v)
        _row(yy, colour, dashed, f"V{v} · {route_distance(route, dist):.1f} km")
        yy -= dy_row
    if baseline is not None:
        yy -= 0.03
        _section(yy, "BASELINE (GRAY)")
        yy -= 0.045
        _row(yy, plate.BASELINE_GRAY, False, f"{baseline.method} · {baseline.total_distance:.0f} km", lw=1.5)
        yy -= dy_row
    yy -= 0.03
    _section(yy, "DEMAND · NODE AREA")
    yy -= 0.055
    lo, hi = int(min(instance.demands[n] for n in cust)), int(max_demand)
    for val in sorted({lo, int(round((lo + hi) / 2)), hi}):
        ax_leg.scatter(
            [0.085], [yy], s=_demand_area(val, max_demand),
            facecolor="#ffffff", edgecolor=plate.SECONDARY, linewidths=0.8,
        )
        unit = "unit" if val == 1 else "units"
        ax_leg.text(0.20, yy, f"{val} {unit}", fontsize=8.2, color=plate.SECONDARY, va="center")
        yy -= 0.052
    yy -= 0.02
    _section(yy, "DEPOT")
    yy -= 0.055
    ax_leg.scatter([0.085], [yy], s=200, facecolor="#ffffff", edgecolor=plate.INK, linewidths=1.2)
    ax_leg.scatter([0.085], [yy], s=64, facecolor="none", edgecolor=plate.INK, linewidths=0.9)
    ax_leg.scatter([0.085], [yy], s=13, facecolor=plate.INK)
    ax_leg.text(0.20, yy, "routes start & end here",
                fontsize=8.2, color=plate.SECONDARY, va="center")

    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, facecolor=plate.SURFACE)
    plt.close(fig)
    return path


def _pct_saved(baseline: float, improved: float) -> float:
    if baseline <= 0:
        return 0.0
    return 100.0 * (baseline - improved) / baseline


def write_summary_md(
    instance: Instance,
    ortools: Solution,
    savings: Solution,
    nn: Solution,
    path: Path,
) -> Path:
    saved_vs_cw = _pct_saved(savings.total_distance, ortools.total_distance)
    saved_vs_nn = _pct_saved(nn.total_distance, ortools.total_distance)
    lines = [
        f"# Route optimization summary — `{instance.name}`",
        "",
        f"- Customers: **{instance.num_customers}**, total demand **{instance.total_demand}**, "
        f"vehicle capacity **{instance.capacity}**, fleet **{instance.num_vehicles}**.",
        "",
        "| Method | Total distance | Vehicles used | Feasible | Solve time (s) |",
        "|---|---:|---:|:--:|---:|",
        f"| Nearest-neighbour | {nn.total_distance:,.1f} | {nn.vehicles_used} | {nn.feasible} | {nn.solve_time_s:.2f} |",
        f"| Clarke-Wright savings | {savings.total_distance:,.1f} | {savings.vehicles_used} | {savings.feasible} | {savings.solve_time_s:.2f} |",
        f"| **OR-Tools (GLS)** | **{ortools.total_distance:,.1f}** | **{ortools.vehicles_used}** | **{ortools.feasible}** | **{ortools.solve_time_s:.2f}** |",
        "",
        f"**OR-Tools cut total distance {saved_vs_cw:.1f}% vs Clarke-Wright savings** "
        f"and {saved_vs_nn:.1f}% vs nearest-neighbour.",
        "",
        "## OR-Tools routes",
        "",
        "| Vehicle | Load | Stops | Distance |",
        "|---:|---:|---:|---:|",
    ]
    from .model import route_distance

    dist = distance_matrix(instance)
    for v, route in enumerate(ortools.routes, start=1):
        stops = len(route) - 2
        lines.append(
            f"| {v} | {ortools.loads[v - 1]}/{instance.capacity} | {stops} | {route_distance(route, dist):,.1f} |"
        )
    lines.append("")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def build_deliverables(
    instance: Instance,
    metric: str = "euclidean",
    time_limit_s: int = 5,
    out_dir: Path | None = None,
) -> dict[str, object]:
    """Solve with all three methods and write the CSV / PNG / summary."""
    out_dir = out_dir or DELIVERABLES
    out_dir.mkdir(parents=True, exist_ok=True)

    dist = distance_matrix(instance, metric)
    nn = nearest_neighbour(instance, dist)
    cw = clarke_wright(instance, dist)
    ort = solve_cvrp(instance, metric=metric, time_limit_s=time_limit_s)

    csv_path = write_route_plan_csv(instance, ort, out_dir / "route_plan.csv", metric)
    png_path = plot_routes(instance, ort, out_dir / "routes.png", baseline=cw, metric=metric)
    md_path = write_summary_md(instance, ort, cw, nn, out_dir / "summary.md")

    return {
        "or_tools": ort,
        "clarke_wright": cw,
        "nearest_neighbour": nn,
        "csv": csv_path,
        "png": png_path,
        "summary": md_path,
    }
