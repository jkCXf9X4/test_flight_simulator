"""Dead reckoning between sparse DIS entity updates (phase 1).

:class:`~dis_viewer.model.EntityState` carries position, velocity, orientation
and angular velocity.  Algorithms 3, 4, 7 and 8 integrate orientation from
``angular_velocity_rps``; algorithm 2 remains position-only and algorithm 1 is
static.  Algorithm 8 honours an optional ``acceleration_enu_mps2`` attribute if
present and otherwise assumes zero linear acceleration.
"""

from __future__ import annotations

import math
from typing import Iterable, List

from .model import EntityState, Vec3

STATIC = 1
LINEAR = 2
ROTATING = frozenset({3, 4, 7, 8})
SUPPORTED_ALGORITHMS = frozenset({STATIC, LINEAR}) | ROTATING

_ZERO: Vec3 = (0.0, 0.0, 0.0)


def _vec3(value: object, default: Vec3 = _ZERO) -> Vec3:
    if value is None:
        return default
    return (float(value[0]), float(value[1]), float(value[2]))  # type: ignore[index]


def _optional(state: EntityState, name: str) -> Vec3:
    return _vec3(getattr(state, name, None))


def _advance(position: Vec3, velocity: Vec3, acceleration: Vec3, dt_s: float) -> Vec3:
    return (
        position[0] + velocity[0] * dt_s + 0.5 * acceleration[0] * dt_s * dt_s,
        position[1] + velocity[1] * dt_s + 0.5 * acceleration[1] * dt_s * dt_s,
        position[2] + velocity[2] * dt_s + 0.5 * acceleration[2] * dt_s * dt_s,
    )


def _integrate_orientation(orientation_deg: Vec3, rates_rps: Vec3, dt_s: float) -> Vec3:
    """Integrate roll/pitch/yaw rates (rad/s) over ``dt_s`` seconds."""

    return (
        orientation_deg[0] + math.degrees(rates_rps[0]) * dt_s,
        orientation_deg[1] + math.degrees(rates_rps[1]) * dt_s,
        orientation_deg[2] + math.degrees(rates_rps[2]) * dt_s,
    )


def extrapolate(state: EntityState, now_s: float, algorithm: int = 3) -> EntityState:
    """Propagate ``state`` to ``now_s`` using DIS dead-reckoning ``algorithm``.

    Algorithms 1 (static), 2 (linear, no rotation), 3/4/7 (linear position and
    velocity, optional rotation) and 8 (linear plus acceleration) are
    supported.  Any other algorithm number returns ``state`` unchanged.
    """

    now = float(now_s)
    if algorithm not in SUPPORTED_ALGORITHMS:
        return state

    dt_s = now - float(state.t_s)
    if algorithm == STATIC:
        return state.copy_with(t_s=now)

    velocity = _vec3(state.velocity_enu_mps)
    acceleration = _optional(state, "acceleration_enu_mps2") if algorithm == 8 else _ZERO
    position = _advance(_vec3(state.position_enu_m), velocity, acceleration, dt_s)

    changes = {"t_s": now, "position_enu_m": position}
    if algorithm in ROTATING:
        rates = _vec3(state.angular_velocity_rps)
        if any(rates):
            changes["orientation_deg"] = _integrate_orientation(
                _vec3(state.orientation_deg), rates, dt_s
            )
    return state.copy_with(**changes)


def predicted_position(state: EntityState, now_s: float, algorithm: int = 3) -> Vec3:
    """Return only the dead-reckoned ENU position at ``now_s``."""

    return extrapolate(state, now_s, algorithm).position_enu_m


def mark_stale(
    states: Iterable[EntityState], now_s: float, stale_after_s: float
) -> List[EntityState]:
    """Return copies of ``states`` flagged stale when older than the threshold.

    An entity exceeds the threshold strictly (``age > stale_after_s``); an
    already-stale entity stays stale.
    """

    now = float(now_s)
    limit = float(stale_after_s)
    result: List[EntityState] = []
    for state in states:
        stale = bool(state.stale) or (now - float(state.t_s)) > limit
        result.append(state.copy_with(stale=stale))
    return result
