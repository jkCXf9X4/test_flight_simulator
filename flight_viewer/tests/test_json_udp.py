"""Tests for the bridge JSON-over-UDP source."""

from __future__ import annotations

import json
import math
import socket
import time

import pytest
from pysos_interop.rates import euler_rates_to_body_rates

from flight_viewer.config import EntityConfig, EntityType, Origin
from flight_viewer.model import EntityKey
from flight_viewer.sources.json_udp import JsonUdpMultiSource, JsonUdpSource


def _packet(
    *,
    x_km: float,
    y_km: float,
    z_km: float,
    roll_deg: float = 0.0,
    pitch_deg: float = 0.0,
    yaw_deg: float = 0.0,
    airspeed_mps: float = 61.0,
) -> dict:
    return {
        "transport": "UdpBridge",
        "reference_latitude_deg": 58.0,
        "reference_longitude_deg": 16.0,
        "reference_altitude_m": 12.0,
        "state": {"x_km": x_km, "y_km": y_km, "z_km": z_km},
        "orientation": {
            "roll_deg": roll_deg,
            "pitch_deg": pitch_deg,
            "yaw_deg": yaw_deg,
        },
        "flight_status": {
            "airspeed_mps": airspeed_mps,
            "energy_state_norm": 0.5,
            "angle_of_attack_deg": 3.0,
            "climb_rate": 1.25,
            "health_code": 0,
        },
        "mission_status": {
            "waypoint_index": 2,
            "total_waypoints": 7,
            "distance_to_waypoint_km": 0.4,
            "arrived": False,
            "complete": False,
        },
    }


def test_two_concatenated_packets_map_to_enu_with_finite_difference():
    entity = EntityConfig(
        key=EntityKey(site=1, application=2, entity=3),
        entity_type=EntityType(kind=1, domain=2, country=0, category=1),
        force_id=2,
        marking="TEST",
    )
    source = JsonUdpSource("127.0.0.1", 0, entity, Origin())
    sender = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        first = _packet(x_km=0.0, y_km=0.0, z_km=1.0)
        second = _packet(
            x_km=0.1,
            y_km=0.2,
            z_km=1.0,
            roll_deg=4.5,
            pitch_deg=-2.0,
            yaw_deg=90.0,
        )
        payload = json.dumps(first) + json.dumps(second)
        sender.sendto(payload.encode("utf-8"), ("127.0.0.1", source.port))
        states = source.receive(timeout=1.0)

        assert len(states) == 2
        assert states[0].position_enu_m == pytest.approx((0.0, 0.0, 1000.0))
        # x is north, y is east: y_km=0.2 -> 200 m east, x_km=0.1 -> 100 m north.
        assert states[1].position_enu_m == pytest.approx((200.0, 100.0, 1000.0))
        assert states[1].orientation_rps == pytest.approx(
            [math.radians(v) for v in (4.5, -2.0, 90.0)]
        )

        assert states[0].velocity_enu_mps == pytest.approx((0.0, 0.0, 0.0))
        dt = states[1].timestamp - states[0].timestamp
        assert dt > 0.0
        assert states[1].velocity_enu_mps == pytest.approx(
            (200.0 / dt, 100.0 / dt, 0.0)
        )
        assert states[0].angular_velocity_rps == pytest.approx((0.0, 0.0, 0.0))
        euler_rates = (
            math.radians(4.5) / dt,
            math.radians(-2.0) / dt,
            math.radians(90.0) / dt,
        )
        assert states[1].angular_velocity_rps == pytest.approx(
            euler_rates_to_body_rates(states[1].orientation_rps, euler_rates)
        )
        assert states[1].key == entity.key
        assert states[1].force_id == 2
        assert states[1].marking == "TEST"
        assert source.last_status["airspeed_mps"] == pytest.approx(61.0)
        assert source.last_status["climb_rate"] == pytest.approx(1.25)
        assert source.last_status["waypoint_index"] == 2
        assert source.last_status["complete"] is False
    finally:
        sender.close()
        source.close()


def test_yaw_rate_wraps_across_180_degrees():
    entity = EntityConfig(key=EntityKey(1, 1, 1))
    source = JsonUdpSource("127.0.0.1", 0, entity, Origin())
    sender = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        first = _packet(x_km=0.0, y_km=0.0, z_km=1.0, yaw_deg=179.0)
        second = _packet(x_km=0.0, y_km=0.0, z_km=1.0, yaw_deg=-179.0)
        payload = json.dumps(first) + json.dumps(second)
        sender.sendto(payload.encode("utf-8"), ("127.0.0.1", source.port))

        states = source.receive(timeout=1.0)

        assert len(states) == 2
        dt = states[1].timestamp - states[0].timestamp
        euler_rates = (0.0, 0.0, math.radians(2.0) / dt)
        assert states[1].angular_velocity_rps == pytest.approx(
            euler_rates_to_body_rates(states[1].orientation_rps, euler_rates)
        )
    finally:
        sender.close()
        source.close()


def test_whitespace_and_partial_payloads_do_not_crash():
    entity = EntityConfig(key=EntityKey(1, 1, 1))
    source = JsonUdpSource("127.0.0.1", 0, entity, Origin())
    sender = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        address = ("127.0.0.1", source.port)
        sender.sendto(b"   \n\t ", address)
        assert source.receive(timeout=0.5) == []

        sender.sendto(b'{"state": {"x_km": 1', address)
        assert source.receive(timeout=0.5) == []
    finally:
        sender.close()
        source.close()


def test_multi_source_returns_states_from_both_ports():
    first_entity = EntityConfig(key=EntityKey(site=1, application=1, entity=1))
    second_entity = EntityConfig(key=EntityKey(site=1, application=1, entity=2))
    multi = JsonUdpMultiSource(
        [
            ("127.0.0.1", 0, first_entity),
            ("127.0.0.1", 0, second_entity),
        ]
    )
    first_sender = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    second_sender = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        ports = [source.port for source in multi.sources]
        first_sender.sendto(
            json.dumps(_packet(x_km=0.1, y_km=0.0, z_km=1.0)).encode("utf-8"),
            ("127.0.0.1", ports[0]),
        )
        second_sender.sendto(
            json.dumps(_packet(x_km=0.0, y_km=0.2, z_km=2.0)).encode("utf-8"),
            ("127.0.0.1", ports[1]),
        )

        states = multi.receive(timeout=1.0)

        assert len(states) == 2
        by_key = {state.key: state for state in states}
        assert set(by_key) == {first_entity.key, second_entity.key}
        assert by_key[first_entity.key].position_enu_m == pytest.approx(
            (0.0, 100.0, 1000.0)
        )
        assert by_key[second_entity.key].position_enu_m == pytest.approx(
            (200.0, 0.0, 2000.0)
        )
        assert by_key[first_entity.key].marking == "AC-1"
        assert by_key[second_entity.key].marking == "AC-2"
    finally:
        first_sender.close()
        second_sender.close()
        multi.close()


def test_multi_source_without_traffic_returns_empty_list():
    multi = JsonUdpMultiSource(
        [
            ("127.0.0.1", 0, EntityConfig(key=EntityKey(1, 1, 1))),
            ("127.0.0.1", 0, EntityConfig(key=EntityKey(1, 1, 2))),
        ]
    )
    try:
        started = time.monotonic()
        states = multi.receive(timeout=0.05)
        elapsed = time.monotonic() - started
        assert states == []
        assert elapsed < 1.0
    finally:
        multi.close()
