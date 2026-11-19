"""Rerun sink. This module is the only place that imports ``rerun``.

Rerun's world frame is ENU: x=east, y=north, z=up. Orientation ``(roll, pitch,
yaw)`` degrees is composed as an intrinsic Z-Y-X rotation and passed to Rerun
as a quaternion in ``(x, y, z, w)`` order.
"""

from __future__ import annotations

import math
from collections import deque
from typing import Deque, Dict, Iterable, Optional, Tuple
from pathlib import Path

import rerun as rr

from ..config import Origin
from ..model import EntityKey, EntityState, Vec3


def entity_slug(key: EntityKey) -> str:
    """Documented slug form: ``<site>_<application>_<entity>``."""

    return key.slug


def entity_path(key: EntityKey, leaf: str) -> str:
    """Rerun entity path for one leaf of an entity."""

    return f"world/entity/{entity_slug(key)}/{leaf}"


def rpy_deg_to_quaternion(
    roll_deg: float, pitch_deg: float, yaw_deg: float
) -> Tuple[float, float, float, float]:
    """Compose roll/pitch/yaw degrees into ``(x, y, z, w)``."""

    half_roll = math.radians(roll_deg) * 0.5
    half_pitch = math.radians(pitch_deg) * 0.5
    half_yaw = math.radians(yaw_deg) * 0.5
    cr, sr = math.cos(half_roll), math.sin(half_roll)
    cp, sp = math.cos(half_pitch), math.sin(half_pitch)
    cy, sy = math.cos(half_yaw), math.sin(half_yaw)
    return (
        sr * cp * cy - cr * sp * sy,
        cr * sp * cy + sr * cp * sy,
        cr * cp * sy - sr * sp * cy,
        cr * cp * cy + sr * sp * sy,
    )


def _origin_text(origin: Origin) -> str:
    return (
        "ENU origin (WGS84): "
        f"latitude={origin.latitude_deg:.9f} deg, "
        f"longitude={origin.longitude_deg:.9f} deg, "
        f"altitude={origin.altitude_m:.3f} m"
    )


class RerunSink:
    """Log entity states to Rerun, either live (spawn) or to an ``.rrd`` file."""

    _MARKER_SIZE_M: Vec3 = (15.0, 12.0, 4.0)

    def __init__(
        self,
        app_id: str = "dis_viewer",
        rrd_path: Optional[Path] = None,
        spawn: bool = False,
        origin: Optional[Origin] = None,
    ) -> None:
        self.app_id = app_id
        self.rrd_path = Path(rrd_path) if rrd_path is not None else None
        self.spawn = spawn
        self.origin = origin or Origin()
        self._histories: Dict[str, Deque[Vec3]] = {}
        self._closed = False

        rr.init(app_id, spawn=spawn)
        if self.rrd_path is not None:
            rr.save(str(self.rrd_path))
        rr.log("world/origin", rr.TextDocument(_origin_text(self.origin)), static=True)

    def log(self, states: Iterable[EntityState], *, trail_points: int = 200) -> None:
        depth = max(1, int(trail_points))
        for state in states:
            slug = entity_slug(state.key)
            rr.set_time("sim_time", duration=float(state.t_s))

            quaternion = rpy_deg_to_quaternion(*state.orientation_deg)
            rr.log(
                entity_path(state.key, "pose"),
                rr.Transform3D(translation=state.position_enu_m, quaternion=quaternion),
            )

            history = self._histories.get(slug)
            if history is None or history.maxlen != depth:
                previous = list(history) if history is not None else []
                history = deque(previous, maxlen=depth)
                self._histories[slug] = history
            history.append(state.position_enu_m)
            if len(history) >= 2:
                rr.log(
                    entity_path(state.key, "trail"),
                    rr.LineStrips3D([list(history)]),
                )

            rr.log(
                entity_path(state.key, "marker"),
                rr.Boxes3D(
                    sizes=[self._MARKER_SIZE_M],
                    centers=[state.position_enu_m],
                    quaternions=[quaternion],
                ),
            )

            status = getattr(state, "status", {}) or {}
            rr.log(
                entity_path(state.key, "status/airspeed_mps"),
                rr.Scalars(
                    float(status.get("airspeed_mps", math.sqrt(sum(v * v for v in state.velocity_enu_mps))))
                ),
            )
            rr.log(
                entity_path(state.key, "status/altitude_m"),
                rr.Scalars(float(state.position_enu_m[2])),
            )
            climb_rate = status.get("climb_rate", status.get("climb_rate_mps"))
            if climb_rate is not None:
                rr.log(
                    entity_path(state.key, "status/climb_rate_mps"),
                    rr.Scalars(float(climb_rate)),
                )

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        rr.disconnect()

    def __enter__(self) -> "RerunSink":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()
