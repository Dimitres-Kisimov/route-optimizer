import numpy as np

from routeopt.model import distance_matrix
from routeopt.robustness import (
    build_robustness,
    evaluate_plan,
    plan_with_headroom,
    sample_demand_scenarios,
    simulate_recourse,
    stress_test,
)
from routeopt.solver import solve_cvrp


def test_scenarios_are_seeded_and_bounded(n30):
    a = sample_demand_scenarios(n30, n_scenarios=50)
    b = sample_demand_scenarios(n30, n_scenarios=50)
    assert np.array_equal(a, b), "same instance + seed must give identical scenarios"
    assert a.shape == (50, n30.num_nodes)
    # the depot never has demand; realized demands stay within [0, capacity]
    assert (a[:, n30.depot] == 0).all()
    assert a.min() >= 0
    assert a.max() <= n30.capacity
    # a different seed gives a different scenario set (noise actually flows)
    c = sample_demand_scenarios(n30, n_scenarios=50, seed=99)
    assert not np.array_equal(a, c)


def test_zero_noise_scenarios_equal_forecast(n30):
    s = sample_demand_scenarios(n30, n_scenarios=10, cv=0.0)
    for row in s:
        assert np.array_equal(row, n30.demands), "cv=0 must reproduce the forecast exactly"


def test_recourse_hand_checked_on_tiny(tiny):
    # tiny geometry: depot (50,50); customers 1..4 at 20 units N/S/E/W; capacity 10.
    dist = distance_matrix(tiny)
    realized = np.zeros(tiny.num_nodes, dtype=np.int64)

    # Both fit: 7 + 3 = 10 == capacity -> no restock, no extra distance.
    realized[1], realized[2] = 7, 3
    assert simulate_recourse([0, 1, 2, 0], realized, tiny.capacity, dist) == (0, 0.0)

    # Second stop busts the van: 7 + 7 > 10. One restock round trip at customer 2,
    # extra = d(2,0) + d(0,2) = 20 + 20 = 40 exactly.
    realized[1], realized[2] = 7, 7
    trips, extra = simulate_recourse([0, 1, 2, 0], realized, tiny.capacity, dist)
    assert trips == 1
    assert abs(extra - 40.0) < 1e-9


def test_recourse_full_reload_serves_everyone(tiny):
    # Every customer realizes a full van-load: restock before every stop after the
    # first. Route depot-1-2-3-depot, all demands = capacity -> 2 trips, 40 km each.
    dist = distance_matrix(tiny)
    realized = np.full(tiny.num_nodes, tiny.capacity, dtype=np.int64)
    realized[tiny.depot] = 0
    trips, extra = simulate_recourse([0, 1, 2, 3, 0], realized, tiny.capacity, dist)
    assert trips == 2
    assert abs(extra - 80.0) < 1e-9


def test_zero_noise_collapses_to_planned(n30):
    # The base-case check: with no demand noise every plan survives as planned —
    # zero failures, zero recourse, expected total == planned distance.
    results = stress_test(
        n30, buffers_pct=(0,), n_scenarios=10, cv=0.0, solution_limit=30
    )
    assert len(results) == 2  # clarke-wright and or-tools, headroom 0
    for r in results:
        assert r.fail_scenarios_pct == 0.0
        assert r.mean_restocks == 0.0
        assert r.mean_extra_km == 0.0
        assert r.max_extra_km == 0.0
        assert r.expected_total_km == r.planned_distance


def test_headroom_reduces_failures_deterministically(n30):
    # Seeded scenarios + deterministic plans: the buffered plan must not fail more
    # often than the tightly packed one, and must carry more slack by construction.
    dist = distance_matrix(n30)
    scenarios = sample_demand_scenarios(n30, n_scenarios=200)
    tight = plan_with_headroom(n30, 0, "clarke-wright")
    slack = plan_with_headroom(n30, 15, "clarke-wright")
    assert tight is not None and slack is not None
    r_tight = evaluate_plan("clarke-wright", 0, tight, n30, dist, scenarios)
    r_slack = evaluate_plan("clarke-wright", 15, slack, n30, dist, scenarios)
    assert r_slack.max_route_load_pct < r_tight.max_route_load_pct
    assert r_slack.fail_scenarios_pct <= r_tight.fail_scenarios_pct
    assert r_slack.mean_extra_km <= r_tight.mean_extra_km
    # the noise must actually bite the tight plan, or the comparison is vacuous
    assert r_tight.fail_scenarios_pct > 0.0


def test_solution_limit_solver_is_deterministic(n30):
    a = solve_cvrp(n30, solution_limit=60)
    b = solve_cvrp(n30, solution_limit=60)
    assert a.feasible and b.feasible
    assert a.routes == b.routes, "fixed solution limit must give identical routes"
    assert a.total_distance == b.total_distance


def test_stress_results_deterministic(n30):
    a = stress_test(n30, buffers_pct=(0, 10), n_scenarios=60, solution_limit=40)
    b = stress_test(n30, buffers_pct=(0, 10), n_scenarios=60, solution_limit=40)
    assert a == b, "the whole stress test must be reproducible end to end"


def test_evaluate_plan_row_semantics(n30):
    dist = distance_matrix(n30)
    scenarios = sample_demand_scenarios(n30, n_scenarios=80)
    plan = plan_with_headroom(n30, 0, "clarke-wright")
    r = evaluate_plan("clarke-wright", 0, plan, n30, dist, scenarios)
    assert 0.0 <= r.fail_scenarios_pct <= 100.0
    assert r.mean_extra_km <= r.max_extra_km
    assert r.p95_extra_km <= r.max_extra_km
    # expected total is planned + mean recourse (up to the stored rounding)
    assert abs(r.expected_total_km - (r.planned_distance + r.mean_extra_km)) < 2e-3
    assert r.vehicles == plan.vehicles_used


def test_build_writes_files_and_regenerates_byte_identically(n30, tmp_path):
    kwargs = dict(n_scenarios=40, buffers_pct=(0, 10), solution_limit=40)
    out = build_robustness(n30, out_dir=tmp_path / "a", **kwargs)
    for key in ("csv", "svg", "md"):
        assert out[key].exists(), f"{key} not written"
    csv_text = (tmp_path / "a" / "robustness.csv").read_text()
    assert csv_text.startswith("engine,headroom_pct,vehicles,planned_km,")
    md_text = (tmp_path / "a" / "robustness.md").read_text()
    assert "not measured" in md_text
    svg_text = (tmp_path / "a" / "robustness.svg").read_text()
    assert "PLATE 03" in svg_text  # numbered plate on the dispatch board
    assert "not measured" in svg_text  # the honesty line stays on the plate
    build_robustness(n30, out_dir=tmp_path / "b", **kwargs)
    for name in ("robustness.csv", "robustness.svg", "robustness.md"):
        assert (tmp_path / "a" / name).read_bytes() == (tmp_path / "b" / name).read_bytes(), (
            f"{name} must regenerate byte-identically"
        )
