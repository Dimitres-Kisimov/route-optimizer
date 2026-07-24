import numpy as np

from routeopt.model import distance_matrix, route_distance, scaled_int_matrix


def test_distance_matrix_symmetric_zero_diagonal(n30):
    d = distance_matrix(n30)
    assert d.shape == (n30.num_nodes, n30.num_nodes)
    assert np.allclose(np.diag(d), 0.0)
    assert np.allclose(d, d.T)
    assert (d >= 0).all()


def test_manhattan_ge_euclidean(n30):
    eu = distance_matrix(n30, "euclidean")
    ma = distance_matrix(n30, "manhattan")
    # L1 >= L2 for every pair.
    assert (ma + 1e-9 >= eu).all()


def test_scaled_int_matrix_roundtrip(tiny):
    d = distance_matrix(tiny)
    s = scaled_int_matrix(d, 100)
    assert s.dtype == np.int64
    assert np.allclose(s / 100.0, d, atol=0.01)


def test_route_distance_known(tiny):
    d = distance_matrix(tiny)
    # depot(0) -> east(1,+20x) -> depot: out and back = 40.
    assert route_distance([0, 1, 0], d) == 40.0
