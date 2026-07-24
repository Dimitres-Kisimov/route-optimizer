import math

from routeopt.heuristic import clarke_wright
from routeopt.model import distance_matrix
from routeopt.solver import solve_cvrp


def _assert_feasible(instance, sol):
    served = sorted(n for r in sol.routes for n in r if n != instance.depot)
    assert served == list(range(1, instance.num_nodes)), "every customer served exactly once"
    for r in sol.routes:
        assert r[0] == instance.depot and r[-1] == instance.depot, "routes start/end at depot"
    for load in sol.loads:
        assert load <= instance.capacity, "route load within capacity"
    assert sol.vehicles_used <= instance.num_vehicles
    assert sol.feasible


def test_ortools_feasible(n30):
    sol = solve_cvrp(n30, time_limit_s=3)
    _assert_feasible(n30, sol)


def test_ortools_not_worse_than_savings(n30):
    d = distance_matrix(n30)
    cw = clarke_wright(n30, d)
    ort = solve_cvrp(n30, time_limit_s=3)
    # optimization must actually help (or at least tie) — small tolerance for
    # the integer arc-cost scaling used inside OR-Tools.
    assert ort.total_distance <= cw.total_distance + 1e-6


def test_tiny_known_optimum(tiny):
    sol = solve_cvrp(tiny, time_limit_s=3)
    _assert_feasible(tiny, sol)
    # Hand-worked optimum: split {1,2,5} + {3,4}. Route depot-3-4-depot costs
    # 20 + 20*sqrt(2) + 20; depot-1-5-2-depot costs 80. Total = 120 + 20*sqrt(2).
    expected = 120.0 + 20.0 * math.sqrt(2)
    assert sol.total_distance == round(expected, 6) or abs(sol.total_distance - expected) < 1e-6
