"""UDP source for the bridge's newline-delimited JSON telemetry.

The parser is a local, pure-Python copy of the rules in
``ros2_bridge/common.py:parse_state_packet``; importing that module would pull
in the ROS 2 workspace and ``rclpy`` is forbidden in ``dis_viewer``.
"""

from __future__ import annotations

import json
import math
import select
import socket
import time
from typing import Any, Dict, List, Optional, Sequence, Tuple

from pysos_interop.rates import euler_rates_to_body_rates

from ..config import EntityConfig, Origin
from ..geo import local_sim_to_enu
from ..model import EntityState, Vec3

# The bridge publishes at 10 Hz. When several packets share one datagram the
# host clock gives them the same receive time, so successive packets are
# spaced by the nominal period instead of a zero-length interval.
_NOMINAL_DT_S = 0.1


def _orientation_rate_rps(
    previous_deg: Vec3, current_deg: Vec3, dt_s: float
) -> Vec3:
    """Finite-difference roll/pitch/yaw rates, unwrapping yaw across ±180°."""

    if dt_s <= 0.0:
        return (0.0, 0.0, 0.0)
    roll_delta = current_deg[0] - previous_deg[0]
    pitch_delta = current_deg[1] - previous_deg[1]
    yaw_delta = (current_deg[2] - previous_deg[2] + 180.0) % 360.0 - 180.0
    return (
        math.radians(roll_delta) / dt_s,
        math.radians(pitch_delta) / dt_s,
        math.radians(yaw_delta) / dt_s,
    )


def _decode_packets(payload: str) -> List[Dict[str, Any]]:
    """Decode every JSON value in ``payload``, tolerating a partial tail."""

    decoder = json.JSONDecoder()
    packets: List[Dict[str, Any]] = []
    idx = 0
    length = len(payload)
    while idx < length:
        while idx < length and payload[idx].isspace():
            idx += 1
        if idx >= length:
            break
        try:
            packet, end = decoder.raw_decode(payload, idx)
        except json.JSONDecodeError:
            break
        idx = end
        packets.append(packet)
    return packets


def _normalise_packet(packet: Dict[str, Any]) -> Dict[str, Any]:
    """Normalise one telemetry packet to the bridge's field contract."""

    state = packet["state"]
    orientation = packet["orientation"]
    flight_status = packet["flight_status"]
    mission_status = packet["mission_status"]
    return {
        "transport": packet.get("transport", "Ros2UdpBridge"),
        "reference_latitude_deg": float(packet["reference_latitude_deg"]),
        "reference_longitude_deg": float(packet["reference_longitude_deg"]),
        "reference_altitude_m": float(packet["reference_altitude_m"]),
        "state_m": (
            float(state["x_km"]) * 1000.0,
            float(state["y_km"]) * 1000.0,
            float(state["z_km"]) * 1000.0,
        ),
        "orientation_deg": (
            float(orientation["roll_deg"]),
            float(orientation["pitch_deg"]),
            float(orientation["yaw_deg"]),
        ),
        "flight_status": {
            "airspeed_mps": float(flight_status["airspeed_mps"]),
            "energy_state_norm": float(flight_status["energy_state_norm"]),
            "angle_of_attack_deg": float(flight_status["angle_of_attack_deg"]),
            "climb_rate": float(flight_status["climb_rate"]),
            "health_code": int(flight_status["health_code"]),
        },
        "mission_status": {
            "waypoint_index": int(mission_status["waypoint_index"]),
            "total_waypoints": int(mission_status["total_waypoints"]),
            "distance_to_waypoint_km": float(mission_status["distance_to_waypoint_km"]),
            "arrived": bool(mission_status["arrived"]),
            "complete": bool(mission_status["complete"]),
        },
    }


def parse_state_packet(payload: str) -> Dict[str, Any]:
    """Parse a single telemetry packet, mirroring ``common.parse_state_packet``."""

    packets = _decode_packets(payload)
    if not packets:
        raise ValueError("Empty state payload")
    return _normalise_packet(packets[-1])


def parse_state_packets(payload: str) -> List[Dict[str, Any]]:
    """Parse every packet in one datagram; a partial tail is ignored."""

    return [_normalise_packet(packet) for packet in _decode_packets(payload)]


def _status_fields(normalised: Dict[str, Any]) -> Dict[str, Any]:
    flight = normalised["flight_status"]
    mission = normalised["mission_status"]
    return {
        "airspeed_mps": flight["airspeed_mps"],
        "climb_rate": flight["climb_rate"],
        "angle_of_attack_deg": flight["angle_of_attack_deg"],
        "waypoint_index": mission["waypoint_index"],
        "complete": mission["complete"],
        "flight_status": dict(flight),
        "mission_status": dict(mission),
        "reference_latitude_deg": normalised["reference_latitude_deg"],
        "reference_longitude_deg": normalised["reference_longitude_deg"],
        "reference_altitude_m": normalised["reference_altitude_m"],
    }


class JsonUdpSource:
    """Receive bridge telemetry over UDP and emit :class:`EntityState` values.

    ``last_status`` holds the flat flight/mission fields of the most recent
    packet (airspeed, climb rate, angle of attack, waypoint index, completion).
    The shared entity state is frozen and carries no status mapping; consumers
    that need the raw telemetry fields read ``last_status``.
    """

    def __init__(self, host: str, port: int, entity: EntityConfig, origin: Origin) -> None:
        self.entity = entity
        self.origin = origin
        self.last_status: Dict[str, Any] = {}
        self._last: Optional[Tuple[float, Vec3, Vec3]] = None
        self._socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._socket.bind((host, port))
        self.host = self._socket.getsockname()[0]
        self.port = self._socket.getsockname()[1]

    def receive(self, timeout: Optional[float] = None) -> List[EntityState]:
        self._socket.settimeout(timeout)
        try:
            data, _ = self._socket.recvfrom(65535)
        except (socket.timeout, OSError):
            return []
        return self._datagram_to_states(data)

    def _datagram_to_states(self, data: bytes) -> List[EntityState]:
        text = data.decode("utf-8", "replace")
        try:
            packets = parse_state_packets(text)
        except (KeyError, TypeError, ValueError):
            return []

        base = time.monotonic()
        states: List[EntityState] = []
        for index, packet in enumerate(packets):
            t_s = base + index * _NOMINAL_DT_S
            position = local_sim_to_enu(*packet["state_m"])
            orientation_deg = packet["orientation_deg"]
            orientation_rps = tuple(
                math.radians(value) for value in orientation_deg
            )
            velocity: Vec3 = (0.0, 0.0, 0.0)
            angular_velocity: Vec3 = (0.0, 0.0, 0.0)
            if self._last is not None:
                dt = t_s - self._last[0]
                if dt > 0.0:
                    velocity = (
                        (position[0] - self._last[1][0]) / dt,
                        (position[1] - self._last[1][1]) / dt,
                        (position[2] - self._last[1][2]) / dt,
                    )
                    angular_velocity = euler_rates_to_body_rates(
                        orientation_rps,
                        _orientation_rate_rps(self._last[2], orientation_deg, dt),
                    )
            self._last = (t_s, position, orientation_deg)

            status = _status_fields(packet)
            self.last_status = status
            states.append(
                EntityState(
                    key=self.entity.key,
                    timestamp=t_s,
                    position_enu_m=position,
                    velocity_enu_mps=velocity,
                    orientation_rps=orientation_rps,
                    angular_velocity_rps=angular_velocity,
                    force_id=self.entity.force_id,
                    marking=self.entity.resolved_marking(),
                )
            )
        return states

    def close(self) -> None:
        self._socket.close()

    def __enter__(self) -> "JsonUdpSource":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()


class JsonUdpMultiSource:
    """Receive telemetry from several UDP sockets, one per simulation instance.

    ``specs`` is a sequence of ``(host, port, entity)`` triples. All sockets are
    polled together with :func:`select.select`, so one call waits at most
    ``timeout`` seconds for the whole set instead of spinning over them.
    """

    def __init__(self, specs: Sequence[Tuple[str, int, EntityConfig]]) -> None:
        self.sources = tuple(
            JsonUdpSource(host, port, entity, Origin()) for host, port, entity in specs
        )
        self._by_socket = {}
        for source in self.sources:
            source._socket.setblocking(False)
            self._by_socket[source._socket] = source

    def receive(self, timeout: Optional[float] = None) -> List[EntityState]:
        if not self._by_socket:
            return []
        try:
            ready, _, _ = select.select(list(self._by_socket), [], [], timeout)
        except (OSError, ValueError):
            return []

        states: List[EntityState] = []
        for sock in ready:
            source = self._by_socket[sock]
            while True:
                try:
                    data, _ = sock.recvfrom(65535)
                except (BlockingIOError, OSError):
                    break
                states.extend(source._datagram_to_states(data))
        return states

    def close(self) -> None:
        for source in self.sources:
            source.close()

    def __enter__(self) -> "JsonUdpMultiSource":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()
