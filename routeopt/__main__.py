"""Command-line entry point.

    python -m routeopt --instance data/instances/n60.json
    python -m routeopt --instance data/instances/n60.json --compare
    python -m routeopt --instance data/instances/n60.json --time-limit 10 --metric manhattan
    python -m routeopt --instance data/instances/n60.json --stress
    python -m routeopt --instance data/instances/n60.json --mix
"""

from __future__ import annotations

import argparse
from pathlib import Path

from .fleetmix import build_fleet_mix
from .heuristic import Solution, clarke_wright, nearest_neighbour
from .model import distance_matrix, load_instance
from .report import build_deliverables
from .robustness import build_robustness
from .sensitivity import build_fleet_sensitivity
from .solver import solve_cvrp
from .timewindows import build_service_analysis


def _fmt(sol: Solution) -> str:
    return (
        f"{sol.method:22s} dist={sol.total_distance:10.1f}  "
        f"vehicles={sol.vehicles_used:2d}  feasible={sol.feasible}  "
        f"t={sol.solve_time_s:5.2f}s"
    )


def _pct(base: float, imp: float) -> float:
    return 100.0 * (base - imp) / base if base > 0 else 0.0


def _run_fleet_sweep(instance, metric: str) -> int:
    out = build_fleet_sensitivity(instance, metric=metric)
    frontier = out["frontier"]
    print(
        "\nfleet-size sensitivity (Clarke-Wright savings; capacity swept, "
        "vehicles is the consequence):\n"
    )
    print(f"{'vehicles':>8} {'capacity':>8} {'distance':>10} {'longest':>9} "
          f"{'cost_EUR':>9} {'CO2_kg':>8}")
    for p in frontier:
        print(
            f"{p.vehicles:8d} {p.capacity:8d} {p.total_distance:10.1f} "
            f"{p.longest_route:9.1f} {p.est_cost_eur:9.0f} {p.est_co2_kg:8.1f}"
        )
    print("\ntrade-off read:")
    for line in out["read"]:
        print(f"  {line}")
    print(f"\nwrote {out['csv']}")
    print(f"wrote {out['svg']}")
    print(f"wrote {out['md']}")
    return 0


def _run_service(instance, metric: str, time_limit_s: int) -> int:
    out = build_service_analysis(instance, metric=metric, time_limit_s=time_limit_s)
    audit = out["audit"]
    vrptw = out["vrptw"]
    vrptw_audit = out["vrptw_audit"]
    savings = out["savings"]
    print("\nservice-level / time-window analysis (synthetic labelled windows):\n")
    print(
        f"  time-blind savings plan: {audit.on_time_stops}/{audit.total_stops} on time "
        f"({audit.on_time_pct:.1f}%), {audit.late_stops} late, worst "
        f"{audit.worst_lateness_min:.0f} min, dist {savings.total_distance:,.1f}"
    )
    print(
        f"  time-aware VRPTW solve:  {vrptw_audit.on_time_stops}/{vrptw_audit.total_stops} "
        f"on time ({vrptw_audit.on_time_pct:.1f}%), dist {vrptw.total_distance:,.1f} "
        f"(+{100.0 * (vrptw.total_distance - savings.total_distance) / savings.total_distance:.1f}% "
        f"vs time-blind), t={vrptw.solve_time_s:.1f}s"
    )
    print(f"\nwrote {out['csv']}")
    print(f"wrote {out['md']}")
    return 0


def _run_stress(instance, metric: str, n_scenarios: int, cv: float, solution_limit: int) -> int:
    out = build_robustness(
        instance, metric=metric, n_scenarios=n_scenarios, cv=cv, solution_limit=solution_limit
    )
    print(
        f"\nrobustness stress test ({n_scenarios} seeded demand scenarios, cv {cv:.2f}; "
        f"deterministic engines):\n"
    )
    print(
        f"{'engine':>14} {'headroom':>8} {'vans':>4} {'planned':>9} {'maxload':>7} "
        f"{'fail%':>6} {'restocks':>8} {'extra_km':>8} {'E[total]':>9}"
    )
    for r in out["results"]:
        print(
            f"{r.engine:>14} {r.headroom_pct:7d}% {r.vehicles:4d} {r.planned_distance:9.1f} "
            f"{r.max_route_load_pct:6.0f}% {r.fail_scenarios_pct:6.1f} {r.mean_restocks:8.2f} "
            f"{r.mean_extra_km:8.1f} {r.expected_total_km:9.1f}"
        )
    print("\nthe read:")
    for line in out["read"]:
        print(f"  {line}")
    print(f"\nwrote {out['csv']}")
    print(f"wrote {out['svg']}")
    print(f"wrote {out['md']}")
    return 0


def _run_mix(instance, metric: str, solution_limit: int) -> int:
    out = build_fleet_mix(instance, metric=metric, solution_limit=solution_limit)
    print(
        f"\nheterogeneous fleet mix (FSM; money objective, deterministic "
        f"solution limit {solution_limit}):\n"
    )
    print("catalogue (illustrative costs, not certified):")
    for t in out["types"]:
        print(
            f"  {t.name:>7}: capacity {t.capacity:3d}, EUR {t.fixed_cost_eur:5.0f}/day fixed, "
            f"EUR {t.var_cost_eur_km:.2f}/km, {t.co2_g_km:.0f} g/km"
        )
    print(
        f"\n{'option':>14} {'fleet':>24} {'vans':>4} {'distance':>9} {'longest':>8} "
        f"{'fixed':>7} {'var':>7} {'total_EUR':>9} {'CO2_kg':>7}"
    )
    for p in out["plans"]:
        print(
            f"{p.label:>14} {p.fleet_str:>24} {p.vehicles:4d} {p.total_distance:9.1f} "
            f"{p.longest_route:8.1f} {p.fixed_cost_eur:7.0f} {p.var_cost_eur:7.0f} "
            f"{p.total_cost_eur:9.0f} {p.est_co2_kg:7.1f}"
        )
    print("\nthe read:")
    for line in out["read"]:
        print(f"  {line}")
    print(f"\nwrote {out['csv']}")
    print(f"wrote {out['svg']}")
    print(f"wrote {out['md']}")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="routeopt", description="CVRP route optimizer (OR-Tools vs savings).")
    ap.add_argument("--instance", required=True, type=Path, help="path to an instance JSON")
    ap.add_argument("--metric", default="euclidean", choices=["euclidean", "manhattan"])
    ap.add_argument("--time-limit", type=int, default=5, help="OR-Tools wall-clock seconds")
    ap.add_argument("--compare", action="store_true", help="run all three methods and print the gap")
    ap.add_argument(
        "--sweep-fleet",
        action="store_true",
        help="fleet-size/cost/service sensitivity (deterministic); writes CSV+SVG+MD, skips OR-Tools",
    )
    ap.add_argument(
        "--service",
        action="store_true",
        help="time-window (VRPTW) service-level analysis; audits the time-blind plan and "
        "solves the time-aware one, writes service_audit.csv + service_level.md",
    )
    ap.add_argument(
        "--stress",
        action="store_true",
        help="robustness stress test under demand uncertainty (deterministic); drives each "
        "plan through seeded demand scenarios with detour-to-depot recourse and sweeps "
        "capacity headroom, writes robustness.csv + robustness.svg + robustness.md",
    )
    ap.add_argument(
        "--mix",
        action="store_true",
        help="heterogeneous fleet mix (FSM, deterministic): prices the optimizer's mixed "
        "fleet against every homogeneous option (fixed + per-km costs per van type), "
        "writes fleet_mix.csv + fleet_mix.svg + fleet_mix.md",
    )
    ap.add_argument("--scenarios", type=int, default=200, help="stress test: number of seeded demand scenarios")
    ap.add_argument("--demand-cv", type=float, default=0.15, help="stress test: demand noise level (coefficient of variation)")
    ap.add_argument(
        "--solution-limit",
        type=int,
        default=200,
        help="stress test / fleet mix: OR-Tools deterministic stopping rule (solutions, not seconds)",
    )
    ap.add_argument("--no-deliverables", action="store_true", help="skip writing CSV/PNG/summary")
    args = ap.parse_args(argv)

    instance = load_instance(args.instance)
    dist = distance_matrix(instance, args.metric)

    print(
        f"instance {instance.name}: {instance.num_customers} customers, "
        f"demand {instance.total_demand}, capacity {instance.capacity}, "
        f"fleet {instance.num_vehicles}, metric {args.metric}"
    )

    if args.sweep_fleet:
        return _run_fleet_sweep(instance, args.metric)

    if args.service:
        return _run_service(instance, args.metric, args.time_limit)

    if args.stress:
        return _run_stress(instance, args.metric, args.scenarios, args.demand_cv, args.solution_limit)

    if args.mix:
        return _run_mix(instance, args.metric, args.solution_limit)

    ort = solve_cvrp(instance, metric=args.metric, time_limit_s=args.time_limit)

    if args.compare:
        nn = nearest_neighbour(instance, dist)
        cw = clarke_wright(instance, dist)
        print("\n" + _fmt(nn))
        print(_fmt(cw))
        print(_fmt(ort))
        print(
            f"\nOR-Tools vs Clarke-Wright: {_pct(cw.total_distance, ort.total_distance):+.1f}%  "
            f"| vs nearest-neighbour: {_pct(nn.total_distance, ort.total_distance):+.1f}%"
        )
    else:
        print("\n" + _fmt(ort))

    if not args.no_deliverables:
        out = build_deliverables(instance, metric=args.metric, time_limit_s=args.time_limit)
        print(f"\nwrote {out['csv']}")
        print(f"wrote {out['png']}")
        print(f"wrote {out['summary']}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
