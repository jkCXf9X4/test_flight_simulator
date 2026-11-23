"""Pure-Python helpers shared by the telemetry tooling and tests."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _airplane_root() -> Path:
    return repo_root() / "3rd_party" / "airplane"


def resolve_scenario_path(path: Path) -> Path:
    candidates = []
    if path.is_absolute():
        candidates.append(path)
    else:
        candidates.append(repo_root() / path)
        candidates.append(_airplane_root() / path)
        candidates.append(path)
    for candidate in candidates:
        if candidate.exists():
            return candidate.resolve()
    raise FileNotFoundError(f"Scenario file not found: {path}")


def load_local_waypoints(scenario_path: Path) -> list[dict[str, float]]:
    import sys

    airplane_root = _airplane_root()
    if str(airplane_root) not in sys.path:
        sys.path.insert(0, str(airplane_root))

    from scripts.lib.common.geo import project_waypoints_to_local_km  # type: ignore

    scenario = json.loads(resolve_scenario_path(scenario_path).read_text(encoding="utf-8"))
    points = scenario.get("points") or []
    return project_waypoints_to_local_km(points)


def parse_state_packet(payload: str) -> dict[str, Any]:
    decoder = json.JSONDecoder()
    idx = 0
    packet = None
    length = len(payload)
    while idx < length:
        while idx < length and payload[idx].isspace():
            idx += 1
        if idx >= length:
            break
        packet, end = decoder.raw_decode(payload, idx)
        idx = end
    if packet is None:
        raise ValueError("Empty state payload")
    state = packet["state"]
    orientation = packet["orientation"]
    flight_status = packet["flight_status"]
    mission_status = packet["mission_status"]
    return {
        "transport": packet.get("transport", "UdpBridge"),
        "reference_latitude_deg": float(packet["reference_latitude_deg"]),
        "reference_longitude_deg": float(packet["reference_longitude_deg"]),
        "reference_altitude_m": float(packet["reference_altitude_m"]),
        "state_m": {
            "x": float(state["x_km"]) * 1000.0,
            "y": float(state["y_km"]) * 1000.0,
            "z": float(state["z_km"]) * 1000.0,
        },
        "orientation_deg": {
            "roll": float(orientation["roll_deg"]),
            "pitch": float(orientation["pitch_deg"]),
            "yaw": float(orientation["yaw_deg"]),
        },
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
