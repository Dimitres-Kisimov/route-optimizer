# Route optimization summary — `n60`

- Customers: **60**, total demand **448**, vehicle capacity **50**, fleet **12**.

| Method | Total distance | Vehicles used | Feasible | Solve time (s) |
|---|---:|---:|:--:|---:|
| Nearest-neighbour | 1,445.8 | 10 | True | 0.00 |
| Clarke-Wright savings | 1,046.2 | 10 | True | 0.00 |
| **OR-Tools (GLS)** | **1,001.6** | **10** | **True** | **8.00** |

**OR-Tools cut total distance 4.3% vs Clarke-Wright savings** and 30.7% vs nearest-neighbour.

## OR-Tools routes

| Vehicle | Load | Stops | Distance |
|---:|---:|---:|---:|
| 1 | 50/50 | 9 | 139.4 |
| 2 | 31/50 | 4 | 93.5 |
| 3 | 48/50 | 6 | 94.5 |
| 4 | 49/50 | 6 | 141.5 |
| 5 | 49/50 | 8 | 114.5 |
| 6 | 43/50 | 5 | 107.5 |
| 7 | 50/50 | 6 | 76.5 |
| 8 | 39/50 | 4 | 58.6 |
| 9 | 50/50 | 7 | 109.4 |
| 10 | 39/50 | 5 | 66.2 |

