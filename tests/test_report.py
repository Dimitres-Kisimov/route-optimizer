from routeopt.heuristic import clarke_wright, nearest_neighbour
from routeopt.model import distance_matrix
from routeopt.report import build_deliverables, plot_routes


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
