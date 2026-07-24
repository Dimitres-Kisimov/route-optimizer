"""Command-line entry point.

    python -m routeopt --instance data/instances/n60.json
    python -m routeopt --instance data/instances/n60.json --compare
    python -m routeopt --instance data/instances/n60.json --time-limit 10 --metric manhattan
"""

from __future__ import annotations

import argparse
from pathlib import Path

from .heuristic import Solution, clarke_wright, nearest_neighbour
from .model import distance_matrix, load_instance
from .report import build_deliverables
from .solver import solve_cvrp


def _fmt(sol: Solution) -> str:
    return (
        f"{sol.method:22s} dist={sol.total_distance:10.1f}  "
        f"vehicles={sol.vehicles_used:2d}  feasible={sol.feasible}  "
        f"t={sol.solve_time_s:5.2f}s"
    )


def _pct(base: float, imp: float) -> float:
    return 100.0 * (base - imp) / base if base > 0 else 0.0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="routeopt", description="CVRP route optimizer (OR-Tools vs savings).")
    ap.add_argument("--instance", required=True, type=Path, help="path to an instance JSON")
    ap.add_argument("--metric", default="euclidean", choices=["euclidean", "manhattan"])
    ap.add_argument("--time-limit", type=int, default=5, help="OR-Tools wall-clock seconds")
    ap.add_argument("--compare", action="store_true", help="run all three methods and print the gap")
    ap.add_argument("--no-deliverables", action="store_true", help="skip writing CSV/PNG/summary")
    args = ap.parse_args(argv)

    instance = load_instance(args.instance)
    dist = distance_matrix(instance, args.metric)

    print(
        f"instance {instance.name}: {instance.num_customers} customers, "
        f"demand {instance.total_demand}, capacity {instance.capacity}, "
        f"fleet {instance.num_vehicles}, metric {args.metric}"
    )

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
