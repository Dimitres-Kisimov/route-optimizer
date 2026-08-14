"""Driver shifts: the break scheduler, the solver bound, and the cap sweep.

The break rule and the span bound are the two pieces the whole layer rests on,
so both are tested against hand-computed arithmetic rather than against the
solver's output. Everything else checks that a capped plan really is legal
after scheduling — verified, never assumed.
"""

import numpy as np
import pytest

from routeopt.heuristic import clarke_wright
from routeopt.model import distance_matrix
from routeopt.shifts import (
    BREAK,
    DRIVE,
    SERVICE,
    ShiftRules,
    audit_shifts,
    build_driver_shifts,
    capped_rules,
    duty_greedy_plan,
    headline_read,
    price_shift_cap,
    schedule_duty,
    solve_shift_capped,
    solver_span_cap,
    sweep_shift_caps,
)
from routeopt.solver import solve_cvrp


def _tour_dist(legs: list[float]) -> np.ndarray:
    """A symmetric matrix whose closed tour 0->1->...->0 has exactly `legs`.

    Only the arcs the tour uses are pinned, which is all the duty scheduler
    ever reads — so a leg length can be stated directly instead of inferred
    from coordinates.
    """
    n = len(legs)
    d = np.zeros((n, n))
    order = [*range(n), 0]
    for k, leg in enumerate(legs):
        i, j = order[k], order[k + 1]
        d[i, j] = d[j, i] = leg
    return d


# --- the break scheduler -----------------------------------------------------


def test_no_break_when_continuous_driving_stays_under_the_threshold():
    # 60 km at 60 km/h = 60 min of driving, one stop: nowhere near 4.5 hours.
    rules = ShiftRules(speed_kmh=60.0, service_min=10.0)
    dist = _tour_dist([30.0, 30.0])  # depot -> c1 -> back
    s = schedule_duty([0, 1, 0], 1, 0, dist, rules)
    assert s.breaks == 0 and s.break_min == 0.0
    assert s.drive_min == pytest.approx(60.0)
    assert s.service_min == pytest.approx(10.0)
    assert s.duty_min == pytest.approx(70.0)
    assert s.worst_continuous_drive_min == pytest.approx(60.0)
    assert [b.kind for b in s.blocks] == [DRIVE, SERVICE, DRIVE]
    assert s.legal


def test_break_is_inserted_mid_leg_and_hand_checked():
    # 60 km/h, a 200-min break threshold, a 30-min break. Legs: 100 km out
    # (100 min), 150 km on (150 min), 50 km home (50 min) — 300 min of driving,
    # plus 20 min of service at two stops.
    rules = ShiftRules(
        max_shift_min=1000.0,
        max_drive_min=1000.0,
        max_continuous_drive_min=200.0,
        break_min=30.0,
        service_min=10.0,
        speed_kmh=60.0,
    )
    dist = _tour_dist([100.0, 150.0, 50.0])
    s = schedule_duty([0, 1, 2, 0], 1, 0, dist, rules)

    # continuous driving reaches 200 min 100 min into the second leg -> one
    # break there; the remaining 50 min + the 50-min run home is 100 min, under
    # the threshold, so no second break.
    assert s.breaks == 1
    assert s.drive_min == pytest.approx(300.0)
    assert s.service_min == pytest.approx(20.0)
    assert s.break_min == pytest.approx(30.0)
    assert s.duty_min == pytest.approx(350.0)
    assert s.worst_continuous_drive_min == pytest.approx(200.0)
    kinds = [b.kind for b in s.blocks]
    assert kinds == [DRIVE, SERVICE, DRIVE, BREAK, DRIVE, SERVICE, DRIVE]
    # the split legs still add up to the original leg length
    assert s.blocks[2].minutes + s.blocks[4].minutes == pytest.approx(150.0)


def test_one_long_leg_takes_as_many_breaks_as_it_needs():
    # 500 min of driving in a single leg against a 200-min threshold needs two
    # breaks (200 | 200 | 100) — never three, because the walk does not rest
    # after the last kilometre.
    rules = ShiftRules(
        max_shift_min=2000.0, max_drive_min=2000.0,
        max_continuous_drive_min=200.0, break_min=45.0,
        service_min=0.0, speed_kmh=60.0,
    )
    dist = _tour_dist([500.0, 0.0, 0.0])
    s = schedule_duty([0, 1, 2, 0], 1, 0, dist, rules)
    assert s.breaks == 2
    assert s.drive_min == pytest.approx(500.0)
    assert s.duty_min == pytest.approx(500.0 + 2 * 45.0)
    # an exact multiple of the threshold does NOT trigger a trailing break
    exact = schedule_duty([0, 1, 2, 0], 1, 0, _tour_dist([400.0, 0.0, 0.0]), rules)
    assert exact.breaks == 1


def test_service_time_is_not_treated_as_rest():
    # Two 100-min legs with a 60-min stop between them: the stop does not reset
    # the continuous-driving clock, so the 200-min threshold still bites.
    rules = ShiftRules(
        max_shift_min=2000.0, max_drive_min=2000.0,
        max_continuous_drive_min=150.0, break_min=45.0,
        service_min=60.0, speed_kmh=60.0,
    )
    s = schedule_duty([0, 1, 0], 1, 0, _tour_dist([100.0, 100.0]), rules)
    assert s.breaks == 1, "a delivery stop is not a break"


def test_duty_is_always_drive_plus_service_plus_breaks(n30):
    rules = ShiftRules(max_continuous_drive_min=30.0, break_min=20.0)
    dist = distance_matrix(n30)
    for v, route in enumerate(clarke_wright(n30, dist).routes, start=1):
        s = schedule_duty(route, v, n30.depot, dist, rules)
        assert s.duty_min == pytest.approx(s.drive_min + s.service_min + s.break_min)
        assert s.break_min == pytest.approx(s.breaks * rules.break_min)
        assert s.stops == len(route) - 2
        assert s.worst_continuous_drive_min <= rules.max_continuous_drive_min + 1e-6


def test_rules_reject_impossible_days():
    with pytest.raises(ValueError):
        ShiftRules(max_shift_min=0.0)
    with pytest.raises(ValueError):
        ShiftRules(break_min=-5.0)
    with pytest.raises(ValueError):
        ShiftRules(service_min=-1.0)
    with pytest.raises(ValueError):
        ShiftRules(max_shift_min=300.0, max_drive_min=540.0)


# --- the solver's span bound -------------------------------------------------


def test_solver_span_cap_hand_checked_on_the_defaults():
    # 600-min envelope, 4.5 h threshold, 45-min break: a route may plan 540 min
    # of drive+service, which costs one break (585 <= 600). A second break
    # would need 540 min of driving *plus* 90 min of rest, which does not fit.
    assert solver_span_cap(ShiftRules()) == pytest.approx(540.0)
    # a short shift is its own bound (no break can be required inside it)
    assert solver_span_cap(capped_rules(ShiftRules(), 240)) == pytest.approx(240.0)
    # ... and the daily driving limit caps the span even in a long envelope
    long_day = ShiftRules(max_shift_min=1200.0, max_drive_min=480.0)
    assert solver_span_cap(long_day) == pytest.approx(480.0)


def test_solver_span_cap_is_conservative_by_construction(n30):
    # The contract: ANY route whose drive+service span fits the bound must
    # still be legal once the scheduler inserts the breaks. Check it against
    # real routes over a grid of rule sets.
    dist = distance_matrix(n30)
    routes = clarke_wright(n30, dist).routes
    for shift, threshold, brk in [
        (600.0, 270.0, 45.0), (300.0, 120.0, 30.0),
        (180.0, 45.0, 15.0), (480.0, 60.0, 40.0),
    ]:
        rules = ShiftRules(
            max_shift_min=shift, max_drive_min=shift,
            max_continuous_drive_min=threshold, break_min=brk,
        )
        bound = solver_span_cap(rules)
        assert 0 < bound <= shift
        for v, route in enumerate(routes, start=1):
            s = schedule_duty(route, v, n30.depot, dist, rules)
            span = s.drive_min + s.service_min
            if span <= bound + 1e-9:
                assert s.duty_min <= shift + 1e-6, (
                    f"span {span} inside bound {bound} but duty {s.duty_min} > {shift}"
                )


# --- the duty-aware construction ---------------------------------------------


def test_duty_greedy_plan_is_feasible_and_inside_the_bound(n30):
    dist = distance_matrix(n30)
    rules = capped_rules(ShiftRules(), 240)
    plan = duty_greedy_plan(n30, dist, rules)
    assert plan is not None and plan.feasible
    audit = audit_shifts(n30, plan.routes, rules, dist=dist)
    assert audit.all_legal
    assert audit.worst_duty_min <= rules.max_shift_min


def test_impossible_cap_is_proved_not_timed_out(n30):
    # A cap shorter than the nearest customer's round trip: no fleet size can
    # help, and the construction says so immediately.
    dist = distance_matrix(n30)
    assert duty_greedy_plan(n30, dist, capped_rules(ShiftRules(), 5)) is None
    point = price_shift_cap(n30, 5, ShiftRules(), solution_limit=20)
    assert point.feasible is False
    assert point.vans == 0 and point.fleet == n30.num_vehicles


# --- the capped solve --------------------------------------------------------


def test_shift_capped_plan_respects_the_cap_after_scheduling(n30):
    rules = capped_rules(ShiftRules(), 200)
    dist = distance_matrix(n30)
    greedy = duty_greedy_plan(n30, dist, rules)
    assert greedy is not None
    sol = solve_shift_capped(
        n30, rules, solution_limit=40, fleet=max(n30.num_vehicles, greedy.vehicles_used + 2)
    )
    assert sol.feasible and sol.routes
    audit = audit_shifts(n30, sol.routes, rules, dist=dist)
    assert audit.all_legal, "the capped solve must be legal once breaks are inserted"
    assert audit.worst_duty_min <= rules.max_shift_min + 1e-6
    # every customer is still served exactly once
    served = sorted(n for r in sol.routes for n in r if n != n30.depot)
    assert served == list(range(1, n30.num_nodes))


def test_a_loose_cap_reproduces_the_uncapped_solve(n30):
    # With an envelope no route can reach, the Duty dimension is slack and the
    # model collapses to the base CVRP, route for route, under the same budget.
    loose = ShiftRules(max_shift_min=100_000.0, max_drive_min=100_000.0)
    capped = solve_shift_capped(n30, loose, solution_limit=60)
    base = solve_cvrp(n30, solution_limit=60)
    assert capped.feasible and base.feasible
    assert capped.routes == base.routes
    assert capped.total_distance == pytest.approx(base.total_distance)


def test_a_tighter_cap_never_leaves_a_van_over_the_line(n30):
    # The point of the layer: the shift-blind plan can blow a cap that the
    # capped solve then respects.
    dist = distance_matrix(n30)
    rules = capped_rules(ShiftRules(), 180)
    blind = audit_shifts(n30, clarke_wright(n30, dist).routes, rules, dist=dist)
    assert blind.vans_over_shift > 0, "the savings plan should breach a 3-hour shift"
    assert blind.worst_over_shift_min > 0
    point = price_shift_cap(n30, 180, ShiftRules(), solution_limit=40)
    assert point.feasible
    assert point.worst_duty_min <= 180 + 1e-6
    assert point.vans >= blind.vans, "a tighter shift never needs fewer vans here"


# --- the sweep and the deliverables ------------------------------------------


def test_sweep_is_deterministic_and_ordered(n30):
    caps = (300, 240, 180)
    a = sweep_shift_caps(n30, caps_min=caps, solution_limit=30)
    b = sweep_shift_caps(n30, caps_min=caps, solution_limit=30)
    assert a == b, "a fixed solution limit must reproduce the identical sweep"
    assert [p.cap_min for p in a] == [300, 240, 180]
    for p in a:
        assert p.fleet == n30.num_vehicles
        if p.feasible:
            assert p.worst_duty_min <= p.cap_min + 1e-6
            assert p.total_break_min == pytest.approx(p.breaks * ShiftRules().break_min)
            assert p.over_fleet == max(0, p.vans - p.fleet)


def test_headline_read_reports_the_numbers_as_they_fall(n30):
    dist = distance_matrix(n30)
    rules = ShiftRules()
    audit = audit_shifts(n30, clarke_wright(n30, dist).routes, rules, dist=dist)
    points = sweep_shift_caps(n30, caps_min=(300, 240), solution_limit=30)
    uncapped = solve_cvrp(n30, solution_limit=30)
    read = headline_read(n30, audit, points, uncapped, rules)
    assert read, "read must not be empty"
    assert "slack" in read[0] or "breaks the modelled" in read[0]
    assert any("continuous drive" in line for line in read)
    # the layer never claims compliance, only a modelled envelope
    assert not any("compliant" in line.lower() for line in read)


def test_build_writes_files_and_regenerates_byte_identically(n30, tmp_path):
    kwargs = dict(caps_min=(300, 240), solution_limit=30)
    out = build_driver_shifts(n30, out_dir=tmp_path / "a", **kwargs)
    for key in ("csv", "svg", "md"):
        assert out[key].exists(), f"{key} not written"

    csv_text = (tmp_path / "a" / "driver_shifts.csv").read_text()
    assert csv_text.startswith("shift_cap_min,feasible,vans,total_distance_km,")
    md_text = (tmp_path / "a" / "driver_shifts.md").read_text(encoding="utf-8")
    assert "not a compliance certification" in md_text
    assert "561/2006" in md_text  # the rules' lineage is named
    assert "not modelled" in md_text  # ...and so is what was left out
    svg_text = (tmp_path / "a" / "driver_shifts.svg").read_text()
    assert "PLATE 05" in svg_text  # numbered plate on the dispatch board
    assert "not a compliance certification" in svg_text  # honesty stays on the plate

    build_driver_shifts(n30, out_dir=tmp_path / "b", **kwargs)
    for name in ("driver_shifts.csv", "driver_shifts.svg", "driver_shifts.md"):
        assert (tmp_path / "a" / name).read_bytes() == (tmp_path / "b" / name).read_bytes(), (
            f"{name} must regenerate byte-identically"
        )
