# Credits

- **Data** — every instance under `data/instances/` is synthetic, produced by
  `data/generate_instances.py` with fixed seeds. No customer or company data is
  used, and none is implied.
- **[Google OR-Tools](https://developers.google.com/optimization)** — the CVRP
  solver (`ortools.constraint_solver`). Licensed under Apache-2.0. OR-Tools is a
  dependency, invoked as a library; its source is not vendored here.
- **Clarke-Wright savings** and **nearest-neighbour** baselines in
  `routeopt/heuristic.py` are implemented from scratch for comparison.
- numpy, matplotlib and pandas for the distance matrix, plots and the route table.

The Clarke & Wright savings algorithm is from G. Clarke and J. W. Wright,
"Scheduling of Vehicles from a Central Depot to a Number of Delivery Points,"
*Operations Research* 12(4), 1964.
