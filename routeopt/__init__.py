"""route-optimizer — a Capacitated Vehicle Routing Problem (CVRP) solver.

OR-Tools' guided local search against the classic Clarke-Wright savings and
nearest-neighbour baselines, on synthetic last-mile delivery instances.
"""

from .heuristic import Solution, clarke_wright, nearest_neighbour
from .model import Instance, distance_matrix, load_instance
from .sensitivity import FleetPoint, build_fleet_sensitivity, sweep_fleet, trade_off_read
from .shifts import (
    DutySchedule,
    ShiftAudit,
    ShiftPoint,
    ShiftRules,
    audit_shifts,
    build_driver_shifts,
    schedule_duty,
    solve_shift_capped,
    solver_span_cap,
    sweep_shift_caps,
)
from .solver import solve_cvrp
from .timewindows import (
    ServiceAudit,
    TimeModel,
    audit_service,
    build_service_analysis,
    make_time_model,
    solve_vrptw,
)

__all__ = [
    "DutySchedule",
    "FleetPoint",
    "Instance",
    "ServiceAudit",
    "ShiftAudit",
    "ShiftPoint",
    "ShiftRules",
    "Solution",
    "TimeModel",
    "audit_service",
    "audit_shifts",
    "build_driver_shifts",
    "build_fleet_sensitivity",
    "build_service_analysis",
    "clarke_wright",
    "distance_matrix",
    "load_instance",
    "make_time_model",
    "nearest_neighbour",
    "schedule_duty",
    "solve_cvrp",
    "solve_shift_capped",
    "solve_vrptw",
    "solver_span_cap",
    "sweep_fleet",
    "sweep_shift_caps",
    "trade_off_read",
]

__version__ = "0.2.0"
