"""WGS84 geodetic, ECEF and local ENU conversions.

Wire format is ECEF metres. Model and viewer use local ENU metres. The
simulation's own local frame is ``x=north, y=east, z=up`` in kilometres.
"""

from __future__ import annotations

import math
from typing import Tuple

from .config import Origin
from .model import Vec3

# WGS84 ellipsoid
WGS84_A = 6378137.0
WGS84_F = 1.0 / 298.257223563
WGS84_E2 = WGS84_F * (2.0 - WGS84_F)


def geodetic_to_ecef(latitude_deg: float, longitude_deg: float, altitude_m: float) -> Vec3:
    lat = math.radians(latitude_deg)
    lon = math.radians(longitude_deg)
    sin_lat = math.sin(lat)
    cos_lat = math.cos(lat)
    sin_lon = math.sin(lon)
    cos_lon = math.cos(lon)
    n = WGS84_A / math.sqrt(1.0 - WGS84_E2 * sin_lat * sin_lat)
    x = (n + altitude_m) * cos_lat * cos_lon
    y = (n + altitude_m) * cos_lat * sin_lon
    z = (n * (1.0 - WGS84_E2) + altitude_m) * sin_lat
    return (x, y, z)


def ecef_to_geodetic(ecef_m: Vec3) -> Tuple[float, float, float]:
    x, y, z = ecef_m
    lon = math.atan2(y, x)
    p = math.hypot(x, y)
    lat = math.atan2(z, p * (1.0 - WGS84_E2))
    altitude = 0.0
    for _ in range(5):
        sin_lat = math.sin(lat)
        n = WGS84_A / math.sqrt(1.0 - WGS84_E2 * sin_lat * sin_lat)
        altitude = p / math.cos(lat) - n
        lat = math.atan2(z, p * (1.0 - WGS84_E2 * n / (n + altitude)))
    return (math.degrees(lat), math.degrees(lon), altitude)


def _origin_ecef(origin: Origin) -> Vec3:
    return geodetic_to_ecef(origin.latitude_deg, origin.longitude_deg, origin.altitude_m)


def _enu_rotation(latitude_deg: float, longitude_deg: float) -> Tuple[Vec3, Vec3, Vec3]:
    """Return the east, north and up unit vectors of the local frame in ECEF."""

    lat = math.radians(latitude_deg)
    lon = math.radians(longitude_deg)
    sin_lat, cos_lat = math.sin(lat), math.cos(lat)
    sin_lon, cos_lon = math.sin(lon), math.cos(lon)
    east = (-sin_lon, cos_lon, 0.0)
    north = (-sin_lat * cos_lon, -sin_lat * sin_lon, cos_lat)
    up = (cos_lat * cos_lon, cos_lat * sin_lon, sin_lat)
    return (east, north, up)


def _dot(a: Vec3, b: Vec3) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def enu_to_ecef(enu_m: Vec3, origin: Origin) -> Vec3:
    east, north, up = _enu_rotation(origin.latitude_deg, origin.longitude_deg)
    ref = _origin_ecef(origin)
    return tuple(  # type: ignore[return-value]
        ref[i] + east[i] * enu_m[0] + north[i] * enu_m[1] + up[i] * enu_m[2]
        for i in range(3)
    )


def ecef_to_enu(ecef_m: Vec3, origin: Origin) -> Vec3:
    east, north, up = _enu_rotation(origin.latitude_deg, origin.longitude_deg)
    ref = _origin_ecef(origin)
    delta = (ecef_m[0] - ref[0], ecef_m[1] - ref[1], ecef_m[2] - ref[2])
    return (_dot(east, delta), _dot(north, delta), _dot(up, delta))


def enu_velocity_to_ecef(velocity_enu_mps: Vec3, origin: Origin) -> Vec3:
    east, north, up = _enu_rotation(origin.latitude_deg, origin.longitude_deg)
    e, n, u = velocity_enu_mps
    return tuple(  # type: ignore[return-value]
        east[i] * e + north[i] * n + up[i] * u for i in range(3)
    )


def ecef_velocity_to_enu(velocity_ecef_mps: Vec3, origin: Origin) -> Vec3:
    east, north, up = _enu_rotation(origin.latitude_deg, origin.longitude_deg)
    v = velocity_ecef_mps
    return (_dot(east, v), _dot(north, v), _dot(up, v))


def local_sim_to_enu(x_m: float, y_m: float, z_m: float) -> Vec3:
    """Simulation local frame (x north, y east, z up) to ENU (east, north, up)."""

    return (y_m, x_m, z_m)


def enu_to_local_sim(enu_m: Vec3) -> Vec3:
    east, north, up = enu_m
    return (north, east, up)


def rpy_deg_to_dis(roll_deg: float, pitch_deg: float, yaw_deg: float) -> Tuple[float, float, float]:
    """Convert roll/pitch/yaw degrees to DIS psi/theta/phi radians."""

    return (math.radians(yaw_deg), math.radians(pitch_deg), math.radians(roll_deg))


def dis_to_rpy_deg(psi_rad: float, theta_rad: float, phi_rad: float) -> Tuple[float, float, float]:
    return (math.degrees(phi_rad), math.degrees(theta_rad), math.degrees(psi_rad))


def euler_rates_to_body_rates(rates_rps: Vec3, orientation_deg: Vec3) -> Vec3:
    """Convert Z-Y-X Euler-angle rates to body-frame angular rates.

    ``rates_rps`` is ``(roll_dot, pitch_dot, yaw_dot)`` in radians per second
    for the model's ``(roll, pitch, yaw)`` orientation in degrees.  The
    orientation uses the Z-Y-X convention: yaw about the local vertical, then
    pitch, then roll.

    The result is ``(p, q, r)``: angular velocity about the body axes
    ``x`` forward, ``y`` right, ``z`` down, in radians per second.  These are
    the axes of the DIS ``EntityAngularVelocity`` field, so the result can be
    written to the wire unchanged.  The relation is::

        p = roll_dot - yaw_dot * sin(pitch)
        q = pitch_dot * cos(roll) + yaw_dot * sin(roll) * cos(pitch)
        r = -pitch_dot * sin(roll) + yaw_dot * cos(roll) * cos(pitch)
    """

    roll, pitch = math.radians(orientation_deg[0]), math.radians(orientation_deg[1])
    roll_dot, pitch_dot, yaw_dot = rates_rps
    sin_roll, cos_roll = math.sin(roll), math.cos(roll)
    sin_pitch, cos_pitch = math.sin(pitch), math.cos(pitch)

    p = roll_dot - yaw_dot * sin_pitch
    q = pitch_dot * cos_roll + yaw_dot * sin_roll * cos_pitch
    r = -pitch_dot * sin_roll + yaw_dot * cos_roll * cos_pitch
    return (p, q, r)


def body_rates_to_euler_rates(body_rates_rps: Vec3, orientation_deg: Vec3) -> Vec3:
    """Inverse of :func:`euler_rates_to_body_rates`.

    Converts body-frame angular rates ``(p, q, r)`` in radians per second to
    Z-Y-X Euler-angle rates ``(roll_dot, pitch_dot, yaw_dot)`` for the given
    ``(roll, pitch, yaw)`` orientation in degrees.  Raises ``ValueError`` when
    ``pitch`` is within 1e-9 rad of +/-90 degrees: there the Euler yaw and roll
    rates are not recoverable from body rates (gimbal lock).
    """

    roll, pitch = math.radians(orientation_deg[0]), math.radians(orientation_deg[1])
    p, q, r = body_rates_rps
    sin_roll, cos_roll = math.sin(roll), math.cos(roll)
    cos_pitch = math.cos(pitch)
    if abs(cos_pitch) < 1e-9:
        raise ValueError("Euler rates are undefined at pitch = +/-90 degrees (gimbal lock)")

    roll_dot = p + (q * sin_roll + r * cos_roll) * math.tan(pitch)
    pitch_dot = q * cos_roll - r * sin_roll
    yaw_dot = (q * sin_roll + r * cos_roll) / cos_pitch
    return (roll_dot, pitch_dot, yaw_dot)


def heading_deg_from_velocity(velocity_enu_mps: Vec3) -> float:
    """Compass heading in degrees for a velocity given in ENU."""

    east, north = velocity_enu_mps[0], velocity_enu_mps[1]
    if east == 0.0 and north == 0.0:
        return 0.0
    return math.degrees(math.atan2(east, north)) % 360.0
