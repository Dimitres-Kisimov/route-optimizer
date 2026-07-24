from routeopt.heuristic import clarke_wright, nearest_neighbour
from routeopt.model import distance_matrix


def _assert_feasible(instance, sol):
    # every customer visited exactly once
    served = sorted(n for r in sol.routes for n in r if n != instance.depot)
    assert served == list(range(1, instance.num_nodes))
    # routes start and end at the depot
    for r in sol.routes:
        assert r[0] == instance.depot and r[-1] == instance.depot
    # capacity respected
    for load in sol.loads:
        assert load <= instance.capacity
    assert sol.feasible
    assert sol.vehicles_used <= instance.num_vehicles


def test_nearest_neighbour_feasible(n30):
    d = distance_matrix(n30)
    _assert_feasible(n30, nearest_neighbour(n30, d))


def test_clarke_wright_feasible(n30):
    d = distance_matrix(n30)
    _assert_feasible(n30, clarke_wright(n30, d))


def test_savings_beats_nearest_neighbour(n30):
    d = distance_matrix(n30)
    nn = nearest_neighbour(n30, d)
    cw = clarke_wright(n30, d)
    # the savings construction should not be worse than a naive greedy sweep
    assert cw.total_distance <= nn.total_distance
