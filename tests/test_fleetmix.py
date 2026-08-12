from routeopt.fleetmix import (
    VehicleType,
    build_fleet_mix,
    compare_mixes,
    default_pool,
    default_vehicle_types,
    headline_read,
    solve_fleet_mix,
    status_quo_label,
)
from routeopt.model import distance_matrix, route_distance
from routeopt.solver import solve_cvrp


def test_default_catalogue_anchors_on_the_instance(n30):
    types = default_vehicle_types(n30)
    assert [t.name for t in types] == ["small", "medium", "large"]
    small, medium, large = types
    # medium IS the instance's own van; small carries half, large double
    assert medium.capacity == n30.capacity
    assert small.capacity == n30.capacity // 2
    assert large.capacity == 2 * n30.capacity
    # both cost axes rise with size...
    assert small.fixed_cost_eur < medium.fixed_cost_eur < large.fixed_cost_eur
    assert small.var_cost_eur_km < medium.var_cost_eur_km < large.var_cost_eur_km
    # ...but fall per unit of capacity (economies of scale — the point of the mix)
    for axis in ("fixed_cost_eur", "var_cost_eur_km"):
        per_unit = [getattr(t, axis) / t.capacity for t in types]
        assert per_unit[0] > per_unit[1] > per_unit[2]
    assert status_quo_label(n30, types) == "all-medium"


def test_default_pool_lets_any_type_serve_alone(n30):
    types = default_vehicle_types(n30)
    pool = default_pool(n30, types)
    for t in types:
        # enough vans of each type that the type could carry the whole demand,
        # plus slack so routing does not degenerate into tight bin packing
        assert (pool[t.name] - 2) * t.capacity >= n30.total_demand - t.capacity
        assert pool[t.name] * t.capacity >= n30.total_demand


def test_single_type_zero_fixed_collapses_to_base_cvrp(n30):
    # The base-case check: one type shaped exactly like the instance's van, no
    # fixed cost, EUR 1.00/km — the money objective becomes the distance
    # objective and the FSM model must reproduce the base CVRP solve, route for
    # route, under the same deterministic solution limit.
    van = VehicleType("van", n30.capacity, fixed_cost_eur=0.0, var_cost_eur_km=1.0, co2_g_km=250.0)
    mix = solve_fleet_mix(
        n30, (van,), solution_limit=60, pool={"van": n30.num_vehicles}, label="collapse"
    )
    base = solve_cvrp(n30, solution_limit=60)
    assert mix.feasible and base.feasible
    assert [list(r.route) for r in mix.routes] == base.routes
    assert mix.total_distance == round(base.total_distance, 3)
    assert mix.fixed_cost_eur == 0.0
    # at EUR 1.00/km, money and kilometres are the same number
    assert abs(mix.var_cost_eur - round(mix.total_distance, 2)) < 2e-2


def test_fixed_cost_steers_the_mix_hand_checked(tiny):
    # tiny: 5 customers, total demand 16, capacity-10 vans in the base instance.
    # A 20-capacity van can serve everything alone; a 10-capacity van cannot.
    small = VehicleType("small", 10, fixed_cost_eur=1000.0, var_cost_eur_km=1.0, co2_g_km=200.0)
    big = VehicleType("big", 20, fixed_cost_eur=1.0, var_cost_eur_km=1.0, co2_g_km=300.0)
    pool = {"small": 3, "big": 2}

    # Deploying a small van costs 1000, a big one 1 -> the only sane plan is a
    # single big van carrying all 16 units.
    plan = solve_fleet_mix(tiny, (small, big), solution_limit=50, pool=pool)
    assert plan.feasible
    assert dict(plan.counts) == {"small": 0, "big": 1}
    assert plan.vehicles == 1
    assert abs(plan.fixed_cost_eur - 1.0) < 1e-9
    # var cost at EUR 1/km is the distance itself; total = fixed + var
    assert abs(plan.var_cost_eur - round(plan.total_distance, 2)) < 2e-2
    assert abs(plan.total_cost_eur - (plan.fixed_cost_eur + plan.var_cost_eur)) <= 0.011

    # Flip the fixed costs: now the big van is the 1000-euro mistake. Demand 16
    # does not fit one 10-capacity van, so the answer is exactly two smalls.
    # (The first solution parks everything on one big van; escaping that local
    # optimum takes GLS a deeper — still deterministic — solution budget.)
    small2 = VehicleType("small", 10, fixed_cost_eur=1.0, var_cost_eur_km=1.0, co2_g_km=200.0)
    big2 = VehicleType("big", 20, fixed_cost_eur=1000.0, var_cost_eur_km=1.0, co2_g_km=300.0)
    plan2 = solve_fleet_mix(tiny, (small2, big2), solution_limit=1000, pool=pool)
    assert plan2.feasible
    assert dict(plan2.counts)["big"] == 0
    assert plan2.vehicles == 2


def test_var_cost_steers_the_mix(tiny):
    # No fixed costs at all; the small van pays 10x per km. Any kilometre in a
    # small van is a mistake, so only big vans may drive.
    small = VehicleType("small", 10, fixed_cost_eur=0.0, var_cost_eur_km=10.0, co2_g_km=200.0)
    big = VehicleType("big", 20, fixed_cost_eur=0.0, var_cost_eur_km=1.0, co2_g_km=300.0)
    plan = solve_fleet_mix(tiny, (small, big), solution_limit=50, pool={"small": 3, "big": 2})
    assert plan.feasible
    assert dict(plan.counts)["small"] == 0
    assert abs(plan.var_cost_eur - round(plan.total_distance, 2)) < 2e-2


def test_costs_recompute_from_routes(n30):
    # Every reported euro/kg must be a pure function of the routes and the
    # catalogue — recompute them by hand and compare.
    types = default_vehicle_types(n30)
    by_name = {t.name: t for t in types}
    dist = distance_matrix(n30)
    plans = compare_mixes(n30, solution_limit=40)
    assert len(plans) == 4  # optimized mix + all-small / all-medium / all-large
    for p in plans:
        assert p.feasible
        served = sorted(n for mr in p.routes for n in mr.route if n != n30.depot)
        assert served == list(range(1, n30.num_nodes)), p.label
        fixed = var = co2 = 0.0
        longest = 0.0
        for mr in p.routes:
            t = by_name[mr.vehicle_type]
            assert mr.load <= t.capacity, f"{p.label}: overloaded {t.name}"
            d = route_distance(list(mr.route), dist)
            assert abs(mr.distance - d) < 1e-3
            fixed += t.fixed_cost_eur
            var += d * t.var_cost_eur_km
            co2 += d * t.co2_g_km / 1000.0
            longest = max(longest, d)
        assert abs(p.fixed_cost_eur - fixed) < 1e-6
        assert abs(p.var_cost_eur - var) < 6e-3
        assert abs(p.est_co2_kg - co2) < 6e-3
        assert abs(p.total_cost_eur - (fixed + var)) < 6e-3
        assert abs(p.longest_route - longest) < 1e-3
        assert p.vehicles == len(p.routes) == sum(n for _, n in p.counts)


def test_undersized_type_is_dropped(n30):
    # A van smaller than the largest single order can never serve that customer:
    # its homogeneous option must vanish, while the mixed pool stays feasible
    # (the big vans take the big orders).
    max_demand = int(n30.demands.max())
    micro = VehicleType("micro", max_demand - 1, fixed_cost_eur=1.0, var_cost_eur_km=0.5, co2_g_km=100.0)
    medium = VehicleType("medium", n30.capacity, fixed_cost_eur=60.0, var_cost_eur_km=1.0, co2_g_km=250.0)
    solo = solve_fleet_mix(n30, (micro,), solution_limit=40, pool={"micro": 40})
    assert not solo.feasible
    plans = compare_mixes(n30, types=(micro, medium), solution_limit=40)
    labels = [p.label for p in plans]
    assert "all-micro" not in labels
    assert "optimized mix" in labels
    assert "all-medium" in labels


def test_compare_is_deterministic(n30):
    a = compare_mixes(n30, solution_limit=40)
    b = compare_mixes(n30, solution_limit=40)
    assert a == b, "fixed solution limit must reproduce the identical plans end to end"


def test_headline_read_reports_the_options(n30):
    types = default_vehicle_types(n30)
    plans = compare_mixes(n30, solution_limit=40)
    read = headline_read(plans, status_quo_label(n30, types))
    assert read, "read must not be empty"
    assert read[0].startswith("Status quo - all-medium")
    assert any("single-size fleet" in line for line in read)
    # degenerate input stays graceful
    assert headline_read([], "all-medium") == [
        "(no feasible fleet option - no catalogue van fits the largest order)"
    ]


def test_build_writes_files_and_regenerates_byte_identically(n30, tmp_path):
    kwargs = dict(solution_limit=40)
    out = build_fleet_mix(n30, out_dir=tmp_path / "a", **kwargs)
    for key in ("csv", "svg", "md"):
        assert out[key].exists(), f"{key} not written"
    csv_text = (tmp_path / "a" / "fleet_mix.csv").read_text()
    assert csv_text.startswith("option,fleet,vehicles,total_distance_km,")
    md_text = (tmp_path / "a" / "fleet_mix.md").read_text(encoding="utf-8")
    assert "not certified" in md_text
    assert "Golden" in md_text  # the FSM lineage is named
    svg_text = (tmp_path / "a" / "fleet_mix.svg").read_text()
    assert "PLATE 04" in svg_text  # numbered plate on the dispatch board
    assert "not certified" in svg_text  # the honesty line stays on the plate
    build_fleet_mix(n30, out_dir=tmp_path / "b", **kwargs)
    for name in ("fleet_mix.csv", "fleet_mix.svg", "fleet_mix.md"):
        assert (tmp_path / "a" / name).read_bytes() == (tmp_path / "b" / name).read_bytes(), (
            f"{name} must regenerate byte-identically"
        )
