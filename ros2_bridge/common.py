"""Pure-Python helpers shared by the ROS 2 bridge node and tests."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List


def _airplane_root() -> Path:
    return Path(__file__).resolve().parents[1] / "3rd_party" / "airplane"


def load_local_waypoints(scenario_path: Path) -> List[Dict[str, float]]:
    import sys

    airplane_root = _airplane_root()
    if str(airplane_root) not in sys.path:
        sys.path.insert(0, str(airplane_root))

    from scripts.lib.common.geo import project_waypoints_to_local_km  # type: ignore

    scenario = json.loads(scenario_path.read_text(encoding="utf-8"))
    points = scenario.get("points") or []
    return project_waypoints_to_local_km(points)


def parse_state_packet(payload: str) -> Dict[str, Any]:
    packet = json.loads(payload)
    state = packet["state"]
    orientation = packet["orientation"]
    flight_status = packet["flight_status"]
    mission_status = packet["mission_status"]
    return {
        "transport": packet.get("transport", "Ros2UdpBridge"),
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


def encode_control_packet(command: Dict[str, Any]) -> bytes:
    packet = {
        "stick_pitch_norm": float(command.get("stick_pitch_norm", 0.0)),
        "stick_roll_norm": float(command.get("stick_roll_norm", 0.0)),
        "rudder_norm": float(command.get("rudder_norm", 0.0)),
        "throttle_norm": float(command.get("throttle_norm", 0.6)),
        "throttle_aux_norm": float(command.get("throttle_aux_norm", command.get("throttle_norm", 0.6))),
        "button_mask": int(command.get("button_mask", 0)),
        "hat_x": int(command.get("hat_x", 0)),
        "hat_y": int(command.get("hat_y", 0)),
        "mode_switch": int(command.get("mode_switch", 0)),
        "reserved": int(command.get("reserved", 0)),
    }
    return (json.dumps(packet, separators=(",", ":")) + "\n").encode("utf-8")

