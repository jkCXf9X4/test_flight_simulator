"""Tests for the WGS84 / ENU geodetic layer."""

import math

import pytest

from dis_viewer.config import Origin
from dis_viewer.geo import (
    WGS84_A,
    WGS84_E2,
    dis_to_rpy_deg,
    ecef_to_enu,
    ecef_to_geodetic,
    enu_to_ecef,
    enu_to_local_sim,
    geodetic_to_ecef,
    heading_deg_from_velocity,
    local_sim_to_enu,
    rpy_deg_to_dis,
)

SITES = [
    pytest.param(0.0, 0.0, 0.0, id="equator"),
    pytest.param(45.0, 10.0, 1200.0, id="mid-latitude"),
    pytest.param(70.0, 20.0, 300.0, id="high-latitude"),
]

ORIGIN = Origin(latitude_deg=45.0, longitude_deg=10.0, altitude_m=100.0)


def _distance(a, b):
    return math.dist(a, b)


@pytest.mark.parametrize("lat_deg,lon_deg,alt_m", SITES)
def test_geodetic_ecef_round_trip(lat_deg, lon_deg, alt_m):
    ecef = geodetic_to_ecef(lat_deg, lon_deg, alt_m)
    lat2, lon2, alt2 = ecef_to_geodetic(ecef)
    ecef2 = geodetic_to_ecef(lat2, lon2, alt2)
    assert _distance(ecef, ecef2) < 1e-3
    assert lat2 == pytest.approx(lat_deg, abs=1e-9)
    assert lon2 == pytest.approx(lon_deg, abs=1e-9)


@pytest.mark.parametrize("lat_deg,lon_deg,alt_m", SITES)
def test_altitude_preserved(lat_deg, lon_deg, alt_m):
    _, _, recovered_alt = ecef_to_geodetic(geodetic_to_ecef(lat_deg, lon_deg, alt_m))
    assert recovered_alt == pytest.approx(alt_m, abs=1e-3)


@pytest.mark.parametrize(
    "enu_m",
    [
        pytest.param((0.0, 0.0, 0.0), id="origin"),
        pytest.param((1234.5, -678.9, 42.0), id="arbitrary"),
        pytest.param((-5000.0, 3000.0, 100.0), id="negative-east"),
    ],
)
def test_enu_ecef_enu_round_trip(enu_m):
    back = ecef_to_enu(enu_to_ecef(enu_m, ORIGIN), ORIGIN)
    assert _distance(enu_m, back) < 1e-3


def _geodetic_offset(lat_deg, lon_deg, north_m=0.0, east_m=0.0):
    """Independent first-order offset using WGS84 meridional/normal radii."""

    lat = math.radians(lat_deg)
    sin_lat = math.sin(lat)
    w = math.sqrt(1.0 - WGS84_E2 * sin_lat * sin_lat)
    meridional = WGS84_A * (1.0 - WGS84_E2) / (w**3)
    normal = WGS84_A / w
    lat2 = lat_deg + math.degrees(north_m / meridional)
    lon2 = lon_deg + math.degrees(east_m / (normal * math.cos(lat)))
    return lat2, lon2


@pytest.mark.parametrize("offset_m", [50.0])
def test_enu_axis_directions_from_independent_reference(offset_m):
    lat2, lon2 = _geodetic_offset(45.0, 10.0, north_m=offset_m)
    north_point = geodetic_to_ecef(lat2, lon2, ORIGIN.altitude_m)
    east_point_geodetic = _geodetic_offset(45.0, 10.0, east_m=offset_m)
    east_point = geodetic_to_ecef(*east_point_geodetic, ORIGIN.altitude_m)

    enu_north = ecef_to_enu(north_point, ORIGIN)
    enu_east = ecef_to_enu(east_point, ORIGIN)

    assert enu_north[0] == pytest.approx(0.0, abs=1e-3)
    assert enu_north[1] == pytest.approx(offset_m, abs=1e-3)
    assert enu_north[2] == pytest.approx(0.0, abs=1e-3)

    assert enu_east[0] == pytest.approx(offset_m, abs=1e-3)
    assert enu_east[1] == pytest.approx(0.0, abs=1e-3)
    assert enu_east[2] == pytest.approx(0.0, abs=1e-3)


def test_local_sim_to_enu_axis_mapping():
    assert local_sim_to_enu(1000.0, 2000.0, 3000.0) == (2000.0, 1000.0, 3000.0)
    assert enu_to_local_sim((2000.0, 1000.0, 3000.0)) == (1000.0, 2000.0, 3000.0)
    assert enu_to_local_sim(local_sim_to_enu(-1.0, 2.0, -3.0)) == (-1.0, 2.0, -3.0)


@pytest.mark.parametrize(
    "rpy_deg",
    [
        pytest.param((0.0, 0.0, 0.0), id="zero"),
        pytest.param((10.0, -20.0, 30.0), id="typical"),
        pytest.param((-90.0, 45.0, 179.9), id="extremes"),
    ],
)
def test_rpy_dis_round_trip(rpy_deg):
    psi, theta, phi = rpy_deg_to_dis(*rpy_deg)
    assert dis_to_rpy_deg(psi, theta, phi) == pytest.approx(rpy_deg, abs=1e-12)


@pytest.mark.parametrize(
    "velocity,heading",
    [
        pytest.param((0.0, 10.0, 0.0), 0.0, id="north"),
        pytest.param((10.0, 0.0, 0.0), 90.0, id="east"),
        pytest.param((0.0, -10.0, 0.0), 180.0, id="south"),
        pytest.param((-10.0, 0.0, 0.0), 270.0, id="west"),
        pytest.param((7.0, 7.0, 0.0), 45.0, id="north-east"),
        pytest.param((0.0, 0.0, 0.0), 0.0, id="stationary"),
    ],
)
def test_heading_deg_from_velocity_cardinals(velocity, heading):
    assert heading_deg_from_velocity(velocity) == pytest.approx(heading, abs=1e-12)
