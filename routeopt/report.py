"""Deliverables: a route-plan CSV, a routes PNG, and a summary Markdown file.

Everything a dispatcher or a reviewer would actually want to look at, written to
``deliverables/``.
"""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # headless / CI-safe
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402

from .heuristic import Solution, clarke_wright, nearest_neighbour  # noqa: E402
from .model import Instance, distance_matrix  # noqa: E402
from .solver import solve_cvrp  # noqa: E402

DELIVERABLES = Path(__file__).resolve().parent.parent / "deliverables"

# A colour-blind-friendly qualitative palette (Okabe-Ito), cycled per route.
_PALETTE = [
    "#0072B2", "#D55E00", "#009E73", "#CC79A7", "#E69F00",
    "#56B4E9", "#F0E442", "#000000", "#8C564B", "#7F7F7F",
    "#1B9E77", "#666666", "#A6761D", "#E7298A", "#66A61E",
]


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


def plot_routes(instance: Instance, solution: Solution, path: Path, title: str | None = None) -> Path:
    coords = instance.coords
    depot = instance.depot

    fig, ax = plt.subplots(figsize=(8, 8), dpi=120)
    # customers
    cust = [n for n in range(instance.num_nodes) if n != depot]
    ax.scatter(
        coords[cust, 0], coords[cust, 1], s=28, c="#888888", zorder=3,
        edgecolors="white", linewidths=0.5, label="customers",
    )
    # routes
    for v, route in enumerate(solution.routes):
        colour = _PALETTE[v % len(_PALETTE)]
        xs = [coords[n][0] for n in route]
        ys = [coords[n][1] for n in route]
        ax.plot(xs, ys, "-", color=colour, linewidth=1.6, alpha=0.9, zorder=2)
    # depot on top
    ax.scatter(
        [coords[depot][0]], [coords[depot][1]], s=220, marker="*",
        c="#D55E00", edgecolors="black", linewidths=0.8, zorder=5, label="depot",
    )

    ttl = title or (
        f"{instance.name}: {solution.method} — "
        f"{solution.total_distance:.0f} distance, {solution.vehicles_used} vehicles"
    )
    ax.set_title(ttl, fontsize=12)
    ax.set_xlabel("x")
    ax.set_ylabel("y")
    ax.set_aspect("equal", adjustable="box")
    ax.grid(True, linewidth=0.3, alpha=0.4)
    ax.legend(loc="upper right", fontsize=9, framealpha=0.9)
    fig.tight_layout()
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path)
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
    png_path = plot_routes(instance, ort, out_dir / "routes.png")
    md_path = write_summary_md(instance, ort, cw, nn, out_dir / "summary.md")

    return {
        "or_tools": ort,
        "clarke_wright": cw,
        "nearest_neighbour": nn,
        "csv": csv_path,
        "png": png_path,
        "summary": md_path,
    }
