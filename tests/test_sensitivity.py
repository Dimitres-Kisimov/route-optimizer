from routeopt.sensitivity import (
    CO2_G_PER_KM,
    COST_EUR_PER_KM,
    build_fleet_sensitivity,
    default_capacity_grid,
    operating_vehicles,
    sweep_fleet,
    trade_off_read,
)


def test_default_grid_respects_max_demand(n30):
    grid = default_capacity_grid(n30)
    assert min(grid) >= int(n30.demands.max()), "no van smaller than the biggest order"
    assert max(grid) > min(grid)


def test_frontier_nonempty_and_sorted(n30):
    frontier = sweep_fleet(n30)
    assert frontier, "frontier should contain at least one feasible plan"
    vehicles = [p.vehicles for p in frontier]
    assert vehicles == sorted(vehicles), "frontier sorted by fleet size ascending"
    assert len(set(vehicles)) == len(vehicles), "one row per distinct fleet size"


def test_fewer_vans_means_less_distance(n30):
    # The core honest finding: min-distance CVRP prefers fewer, fuller vans, so
    # total distance is non-decreasing as the fleet grows.
    frontier = sweep_fleet(n30)
    for earlier, later in zip(frontier, frontier[1:], strict=False):
        assert later.vehicles > earlier.vehicles
        assert later.total_distance >= earlier.total_distance - 1e-6


def test_co2_and_cost_are_the_labelled_factors(n30):
    frontier = sweep_fleet(n30)
    for p in frontier:
        assert p.est_co2_kg == round(p.est_co2_kg, 2)
        assert abs(p.est_co2_kg - p.total_distance * CO2_G_PER_KM / 1000.0) < 0.02
        assert abs(p.est_cost_eur - p.total_distance * COST_EUR_PER_KM) < 0.02


def test_frontier_is_deterministic(n30):
    a = sweep_fleet(n30)
    b = sweep_fleet(n30)
    assert a == b, "same instance must give a byte-identical frontier"


def test_trade_off_read_anchored_at_operating_point(n30):
    frontier = sweep_fleet(n30)
    pivot = operating_vehicles(n30)
    read = trade_off_read(frontier, pivot)
    assert read and read[0].startswith("Operating point")
    assert any("CO2" in line for line in read)


def test_build_writes_csv_svg_md(n30, tmp_path):
    out = build_fleet_sensitivity(n30, out_dir=tmp_path)
    for key in ("csv", "svg", "md"):
        assert out[key].exists(), f"{key} not written"
    csv_text = (tmp_path / "fleet_sensitivity.csv").read_text()
    assert csv_text.startswith("vehicles,van_capacity,total_distance_km,")
    svg_text = (tmp_path / "fleet_sensitivity.svg").read_text()
    assert svg_text.lstrip().startswith("<svg")
    assert "trade-off" in (tmp_path / "fleet_sensitivity.md").read_text().lower()
