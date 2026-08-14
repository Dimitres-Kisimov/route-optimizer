from routeopt.heuristic import clarke_wright, nearest_neighbour
from routeopt.model import distance_matrix
from routeopt.report import (
    build_deliverables,
    plot_routes,
    replot_from_plan,
    solution_from_plan_csv,
    write_route_plan_csv,
)


def test_build_deliverables_writes_files(tiny, tmp_path):
    out = build_deliverables(tiny, time_limit_s=2, out_dir=tmp_path)
    for key in ("csv", "png", "summary"):
        assert out[key].exists(), f"{key} not written"
    assert (tmp_path / "route_plan.csv").read_text().startswith("vehicle,")
    assert "summary" in (tmp_path / "summary.md").read_text().lower()
    # all three methods present and feasible on the tiny instance
    assert out["or_tools"].feasible
    assert out["clarke_wright"].feasible
    assert out["nearest_neighbour"].feasible


def test_plot_routes_with_baseline_is_deterministic(tiny, tmp_path):
    # Plate 01 takes an optional gray baseline underlay; for fixed inputs the
    # PNG must render byte-identically (all placement is computed, no clock).
    dist = distance_matrix(tiny)
    sol = clarke_wright(tiny, dist)
    base = nearest_neighbour(tiny, dist)
    a = plot_routes(tiny, sol, tmp_path / "a.png", baseline=base)
    b = plot_routes(tiny, sol, tmp_path / "b.png", baseline=base)
    assert a.exists() and b.exists()
    assert a.read_bytes() == b.read_bytes(), "same plan must render the identical map"
    # and the no-baseline variant still works (single-solution map)
    assert plot_routes(tiny, sol, tmp_path / "solo.png").exists()


def test_plan_csv_round_trips_the_exact_routes(n30, tmp_path):
    # route_plan.csv is the committed record of the answer, so the plan must
    # come back out of it unchanged — this is what lets Plate 01 be re-inked
    # without a wall-clock re-solve moving the numbers underneath it.
    dist = distance_matrix(n30)
    sol = clarke_wright(n30, dist)
    write_route_plan_csv(n30, sol, tmp_path / "route_plan.csv")
    back = solution_from_plan_csv(n30, tmp_path / "route_plan.csv", method="clarke-wright")
    assert back.routes == sol.routes
    assert back.total_distance == sol.total_distance
    assert back.vehicles_used == sol.vehicles_used
    assert back.loads == sol.loads
    assert back.feasible


def test_replot_from_plan_redraws_the_map_byte_identically(n30, tmp_path):
    dist = distance_matrix(n30)
    write_route_plan_csv(n30, clarke_wright(n30, dist), tmp_path / "route_plan.csv")
    a = replot_from_plan(n30, out_dir=tmp_path).read_bytes()
    b = replot_from_plan(n30, out_dir=tmp_path).read_bytes()
    assert a == b, "re-inking the committed plan must be reproducible"
