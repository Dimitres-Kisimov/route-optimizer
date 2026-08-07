import numpy as np

from routeopt.heuristic import clarke_wright
from routeopt.model import distance_matrix
from routeopt.timewindows import (
    TimeModel,
    audit_service,
    build_service_analysis,
    make_time_model,
    route_timings,
    solve_vrptw,
)


def _open_model(instance, speed_kmh=60.0, service_min=5.0, horizon_min=1000.0):
    """An all-anytime TimeModel: every window is [0, horizon] (no waiting, no lateness)."""
    n = instance.num_nodes
    return TimeModel(
        ready=np.zeros(n),
        due=np.full(n, horizon_min),
        service_min=service_min,
        speed_kmh=speed_kmh,
        horizon_min=horizon_min,
        morning_due=horizon_min,
        afternoon_ready=0.0,
        labels=tuple(["--"] * n),
    )


def test_time_model_is_deterministic_and_labelled(n30):
    a = make_time_model(n30)
    b = make_time_model(n30)
    assert np.array_equal(a.ready, b.ready), "same instance must give identical windows"
    assert np.array_equal(a.due, b.due)
    assert a.labels == b.labels
    # depot is anytime; every customer carries a slot label
    assert a.labels[n30.depot] == "--"
    assert set(a.labels[1:]) <= {"AM", "PM", "--"}
    # windows are well-formed: ready <= due, inside the day
    assert (a.ready <= a.due).all()
    assert (a.due <= a.horizon_min + 1e-9).all()
    # the depot always spans the whole day
    assert a.ready[n30.depot] == 0.0
    assert a.due[n30.depot] == a.horizon_min


def test_am_and_pm_windows_match_their_labels(n30):
    tm = make_time_model(n30)
    for i in range(1, n30.num_nodes):
        if tm.labels[i] == "AM":
            assert tm.ready[i] == 0.0 and tm.due[i] == tm.morning_due
        elif tm.labels[i] == "PM":
            assert tm.ready[i] == tm.afternoon_ready and tm.due[i] == tm.horizon_min


def test_route_timings_hand_checkable(tiny):
    # tiny: depot(0)-east(1,+20x)-depot. speed 60 km/h -> 1 min per unit distance,
    # so arrival at node 1 is exactly 20 min. All-anytime windows: no waiting.
    tm = _open_model(tiny, speed_kmh=60.0, service_min=5.0)
    dist = distance_matrix(tiny)
    timings, finish = route_timings([0, 1, 0], 1, tiny, dist, tm)
    assert len(timings) == 1
    assert abs(timings[0].arrival_min - 20.0) < 1e-9
    assert not timings[0].late
    # depot return: 20 (out) + 5 (service) + 20 (back) = 45
    assert abs(finish - 45.0) < 1e-9


def test_audit_counts_lateness_consistently(n30):
    tm = make_time_model(n30)
    dist = distance_matrix(n30)
    cw = clarke_wright(n30, dist)
    audit = audit_service(n30, cw.routes, tm)
    # every customer is audited exactly once
    assert audit.total_stops == n30.num_customers
    assert audit.on_time_stops + audit.late_stops == audit.total_stops
    assert 0.0 <= audit.on_time_pct <= 100.0
    # per-vehicle late counts sum to the fleet total; worst is the max over vehicles
    assert sum(va.late_stops for va in audit.per_vehicle) == audit.late_stops
    assert audit.worst_lateness_min == max(va.worst_lateness_min for va in audit.per_vehicle)


def test_audit_is_deterministic(n30):
    tm = make_time_model(n30)
    dist = distance_matrix(n30)
    routes = clarke_wright(n30, dist).routes
    a = audit_service(n30, routes, tm)
    b = audit_service(n30, routes, tm)
    assert a.late_stops == b.late_stops
    assert a.total_lateness_min == b.total_lateness_min
    assert a.per_vehicle == b.per_vehicle


def test_vrptw_satisfies_every_window(n30):
    tm = make_time_model(n30)
    sol = solve_vrptw(n30, tm, time_limit_s=4)
    assert sol.feasible, "VRPTW solution must be capacity-feasible and complete"
    # every customer served exactly once, routes closed at the depot
    served = sorted(node for r in sol.routes for node in r if node != n30.depot)
    assert served == list(range(1, n30.num_nodes))
    for r in sol.routes:
        assert r[0] == n30.depot and r[-1] == n30.depot
    # the whole point: with hard windows, nobody is late
    audit = audit_service(n30, sol.routes, tm)
    assert audit.late_stops == 0, "time-aware solve must keep every window"


def test_time_windows_actually_bind_on_the_blind_plan(n30):
    # If the windows never bit, the comparison would be vacuous. The time-blind
    # savings plan should miss at least one promised window on this instance.
    tm = make_time_model(n30)
    dist = distance_matrix(n30)
    cw = clarke_wright(n30, dist)
    assert audit_service(n30, cw.routes, tm).late_stops > 0


def test_build_service_writes_csv_and_md(n30, tmp_path):
    out = build_service_analysis(n30, time_limit_s=4, out_dir=tmp_path)
    for key in ("csv", "md"):
        assert out[key].exists(), f"{key} not written"
    csv_text = (tmp_path / "service_audit.csv").read_text()
    assert csv_text.startswith("vehicle,stops,late_stops,on_time_stops,")
    md_text = (tmp_path / "service_level.md").read_text()
    assert "time window" in md_text.lower()
    # the audited (deterministic) CSV is byte-identical across builds
    build_service_analysis(n30, time_limit_s=4, out_dir=tmp_path / "again")
    assert (tmp_path / "again" / "service_audit.csv").read_text() == csv_text
