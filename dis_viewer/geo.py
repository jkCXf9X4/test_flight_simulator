"""WGS84 / ENU conversions re-exported from :mod:`pysos_interop`.

The shared geodetic layer owns the WGS84 and ECEF/ENU maths.  This module
keeps only the project-specific frame helpers: the simulation's local
``x=north, y=east`` frame and compass heading.
"""

from __future__ import annotations

import math

from pysos_interop.geo import (
    WGS84_A,
    WGS84_E2,
    WGS84_F,
    ecef_to_enu,
    ecef_to_geodetic,
    ecef_velocity_to_enu,
    enu_to_ecef,
    enu_velocity_to_ecef,
    geodetic_to_ecef,
)
from pysos_interop.rates import (
    body_rates_to_euler_rates,
    euler_rates_to_body_rates,
)

from .model import Vec3

__all__ = [
    "WGS84_A",
    "WGS84_E2",
    "WGS84_F",
    "body_rates_to_euler_rates",
    "ecef_to_enu",
    "ecef_to_geodetic",
    "ecef_velocity_to_enu",
    "enu_to_ecef",
    "enu_to_local_sim",
    "enu_velocity_to_ecef",
    "euler_rates_to_body_rates",
    "geodetic_to_ecef",
    "heading_deg_from_velocity",
    "local_sim_to_enu",
]


def local_sim_to_enu(x_m: float, y_m: float, z_m: float) -> Vec3:
    """Simulation local frame (x north, y east, z up) to ENU (east, north, up)."""

    return (y_m, x_m, z_m)


def enu_to_local_sim(enu_m: Vec3) -> Vec3:
    east, north, up = enu_m
    return (north, east, up)


def heading_deg_from_velocity(velocity_enu_mps: Vec3) -> float:
    """Compass heading in degrees for a velocity given in ENU."""

    east, north = velocity_enu_mps[0], velocity_enu_mps[1]
    if east == 0.0 and north == 0.0:
        return 0.0
    return math.degrees(math.atan2(east, north)) % 360.0
