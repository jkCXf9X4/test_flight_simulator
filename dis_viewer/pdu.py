"""IEEE 1278.1 Entity State PDU encode/decode.

The model stores pose in local ENU metres; the wire carries geocentric WGS84
ECEF metres.  Orientation is ``(roll, pitch, yaw)`` degrees in the model and
DIS ``(psi, theta, phi)`` radians on the wire.

Linear velocity follows the selected dead-reckoning algorithm:

* world frame (ECEF) for algorithms 2, 3, 5, 6, 9
* entity/body frame for algorithms 4, 7, 8

The body frame is the usual aerospace frame (x forward, y right, z down),
with yaw measured clockwise from north.  Only the velocity field changes
frame; position is always ECEF.

Angular velocity is carried for rotating algorithms 3, 4, 7 and 8.  DIS carries
body-frame angular velocity, while the model stores Z-Y-X Euler-angle rates;
the two are converted with :func:`~dis_viewer.geo.euler_rates_to_body_rates`
at the PDU boundary.  Linear acceleration is always zero.
"""

from __future__ import annotations

import io
import math
import struct
import time
from typing import List, Tuple

from opendis.PduFactory import createPdu
from opendis.dis7 import (
    DeadReckoningParameters,
    EntityMarking,
    EntityStatePdu,
    EntityType as DisEntityType,
)
from opendis.record.common import (
    EntityIdentifier,
    EulerAngles,
    SimulationAddress,
    Vector3Float,
    WorldCoordinates,
)
from opendis.stream import DataOutputStream

from .config import Origin
from .geo import (
    body_rates_to_euler_rates,
    dis_to_rpy_deg,
    ecef_to_enu,
    ecef_velocity_to_enu,
    enu_to_ecef,
    enu_velocity_to_ecef,
    euler_rates_to_body_rates,
    rpy_deg_to_dis,
)
from .model import EntityKey, EntityState, EntityType, Vec3

ENTITY_STATE_PDU_TYPE = 1
PROTOCOL_VERSION = 7
PDU_HEADER_LEN = 12
TICKS_PER_HOUR = 1 << 31
RELATIVE_TIMESTAMP_MASK = 0x7FFFFFFF

# Names map to the IEEE 1278.1 dead-reckoning algorithm enumeration.  The
# canonical OpenDIS names are kept alongside short aliases.
DR_ALGORITHMS = {
    "other": 0,
    "static": 1,
    "pw": 2,
    "rpw": 3,
    "rvw": 4,
    "rpw_accel": 5,
    "rpw_accel_2": 6,
    "rvw_accel": 7,
    "rvw_accel_2": 8,
    "rpw_accel_3": 9,
    "OTHER": 0,
    "STATIC": 1,
    "RPW": 3,
    "RVW": 4,
    "DRM_F_P_W": 2,
    "DRM_F_R_P_W": 3,
    "DRM_F_R_P_B": 4,
    "DRM_F_R_P_W_A": 5,
    "DRM_F_R_P_W_A_2": 6,
    "DRM_F_R_P_B_A": 7,
    "DRM_F_R_P_B_A_2": 8,
    "DRM_F_R_P_W_A_3": 9,
}

# Wire velocity frame by algorithm, as required by the phase-1 contract.
WORLD_FRAME_DR_ALGORITHMS = frozenset({2, 3, 5, 6, 9})
BODY_FRAME_DR_ALGORITHMS = frozenset({4, 7, 8})
ROTATING_DR_ALGORITHMS = frozenset({3, 4, 7, 8})
KNOWN_DR_ALGORITHMS = frozenset(range(10))

Vec3Matrix = Tuple[Vec3, Vec3, Vec3]


def dis_timestamp(t_s: float, *, relative: bool = True) -> int:
    """Return a DIS header timestamp from seconds.

    The low 31 bits are hour-relative ticks of ``2**-31`` hour.  The hour
    wraps; ``relative=False`` sets the absolute-time bit (bit 31).
    """

    seconds = float(t_s) % 3600.0
    ticks = int(seconds * TICKS_PER_HOUR / 3600.0)
    ticks &= RELATIVE_TIMESTAMP_MASK
    if relative:
        return ticks
    return ticks | 0x80000000


def _body_to_enu_rotation(orientation_deg: Vec3) -> Vec3Matrix:
    """Rotation matrix mapping body (x fwd, y right, z down) to ENU."""

    roll, pitch, yaw = (math.radians(value) for value in orientation_deg)
    cr, sr = math.cos(roll), math.sin(roll)
    cp, sp = math.cos(pitch), math.sin(pitch)
    cy, sy = math.cos(yaw), math.sin(yaw)

    # R_ned_body = Rz(yaw) * Ry(pitch) * Rx(roll)
    north = (
        cy * cp,
        cy * sp * sr - sy * cr,
        cy * sp * cr + sy * sr,
    )
    east = (
        sy * cp,
        sy * sp * sr + cy * cr,
        sy * sp * cr - cy * sr,
    )
    down = (-sp, cp * sr, cp * cr)

    # ENU = (NED east, NED north, -NED down)
    return (east, north, tuple(-value for value in down))


def _apply(matrix: Vec3Matrix, vector: Vec3) -> Vec3:
    return tuple(  # type: ignore[return-value]
        row[0] * vector[0] + row[1] * vector[1] + row[2] * vector[2]
        for row in matrix
    )


def _apply_transpose(matrix: Vec3Matrix, vector: Vec3) -> Vec3:
    return tuple(  # type: ignore[return-value]
        sum(matrix[row][column] * vector[row] for row in range(3))
        for column in range(3)
    )


def _enu_to_body_velocity(velocity_enu: Vec3, orientation_deg: Vec3) -> Vec3:
    return _apply_transpose(_body_to_enu_rotation(orientation_deg), velocity_enu)


def _body_to_enu_velocity(velocity_body: Vec3, orientation_deg: Vec3) -> Vec3:
    return _apply(_body_to_enu_rotation(orientation_deg), velocity_body)


def _velocity_from_wire(
    velocity_wire: Vec3, orientation_deg: Vec3, origin: Origin, dr_algorithm: int
) -> Vec3:
    if dr_algorithm in BODY_FRAME_DR_ALGORITHMS:
        return _body_to_enu_velocity(velocity_wire, orientation_deg)
    return ecef_velocity_to_enu(velocity_wire, origin)


def _wire_velocity(
    velocity_enu: Vec3, orientation_deg: Vec3, origin: Origin, dr_algorithm: int
) -> Vec3:
    if dr_algorithm in BODY_FRAME_DR_ALGORITHMS:
        return _enu_to_body_velocity(velocity_enu, orientation_deg)
    return enu_velocity_to_ecef(velocity_enu, origin)


def _wire_angular_velocity(state: EntityState, dr_algorithm: int) -> Vec3:
    """Return the DIS body-frame angular velocity for a rotating algorithm.

    The model's ``angular_velocity_rps`` holds Euler-angle rates; DIS carries
    angular velocity about the body axes, so the rates are converted using the
    current orientation.  Non-rotating algorithms carry zero angular velocity.
    """

    if dr_algorithm in ROTATING_DR_ALGORITHMS:
        return euler_rates_to_body_rates(
            _vec3_any(state.angular_velocity_rps), state.orientation_deg
        )
    return (0.0, 0.0, 0.0)


def _vec3_any(value: object) -> Vec3:
    return (float(value[0]), float(value[1]), float(value[2]))  # type: ignore[index]


def _clean_marking(marking: str) -> str:
    return str(marking).encode("ascii", "ignore").decode("ascii")[:11]


def _marking_record(marking: str) -> EntityMarking:
    record = EntityMarking(characterSet=1)
    record.setString(_clean_marking(marking))
    return record


def encode_entity_state(
    state: EntityState,
    origin: Origin,
    exercise_id: int,
    *,
    dr_algorithm: int = 3,
    timestamp: int | None = None,
) -> bytes:
    """Serialise one Entity State PDU.

    ``timestamp`` defaults to :func:`dis_timestamp` of ``state.t_s`` (relative).
    """

    dr_algorithm = int(dr_algorithm)
    if dr_algorithm not in KNOWN_DR_ALGORITHMS:
        raise ValueError(f"Unknown dead-reckoning algorithm: {dr_algorithm}")

    key = state.key
    position_ecef = enu_to_ecef(state.position_enu_m, origin)
    velocity_wire = _wire_velocity(
        state.velocity_enu_mps, state.orientation_deg, origin, dr_algorithm
    )
    psi, theta, phi = rpy_deg_to_dis(*state.orientation_deg)
    angular_wire = _wire_angular_velocity(state, dr_algorithm)
    kind, domain, country, category, subcategory, specific, extra = (
        state.entity_type.as_tuple()
    )

    pdu = EntityStatePdu(
        entityID=EntityIdentifier(
            SimulationAddress(int(key.site), int(key.application)),
            int(key.entity),
        ),
        forceId=int(state.force_id) & 0xFF,
        entityType=DisEntityType(
            kind, domain, country, category, subcategory, specific, extra
        ),
        entityLinearVelocity=Vector3Float(*velocity_wire),
        entityLocation=WorldCoordinates(*position_ecef),
        entityOrientation=EulerAngles(psi, theta, phi),
        deadReckoningParameters=DeadReckoningParameters(
            deadReckoningAlgorithm=dr_algorithm,
            entityLinearAcceleration=Vector3Float(),
            entityAngularVelocity=Vector3Float(*angular_wire),
        ),
        marking=_marking_record(state.marking),
    )
    pdu.protocolVersion = PROTOCOL_VERSION
    pdu.exerciseID = int(exercise_id) & 0xFF
    pdu.timestamp = (
        dis_timestamp(state.t_s) if timestamp is None else int(timestamp) & 0xFFFFFFFF
    )

    buffer = io.BytesIO()
    pdu.serialize(DataOutputStream(buffer))
    data = bytearray(buffer.getvalue())
    if len(data) < PDU_HEADER_LEN:
        raise ValueError("opendis produced a truncated Entity State PDU")
    struct.pack_into(">H", data, 8, len(data))
    return bytes(data)


def pdu_spans(data: bytes) -> List[Tuple[int, int]]:
    """Return ``(start, end)`` spans for the PDUs in one datagram."""

    spans: List[Tuple[int, int]] = []
    offset = 0
    total = len(data)
    while offset + PDU_HEADER_LEN <= total:
        length = struct.unpack_from(">H", data, offset + 8)[0]
        if length < PDU_HEADER_LEN or offset + length > total:
            break
        spans.append((offset, offset + length))
        offset += length
    return spans


def _entity_id(pdu: EntityStatePdu) -> EntityKey:
    identifier = pdu.entityID
    return EntityKey(
        int(identifier.simulationAddress.site),
        int(identifier.simulationAddress.application),
        int(identifier.entityNumber),
    )


def _entity_type(pdu: EntityStatePdu) -> EntityType:
    wire = pdu.entityType
    return EntityType(
        int(wire.entityKind),
        int(wire.domain),
        int(wire.country),
        int(wire.category),
        int(wire.subcategory),
        int(wire.specific),
        int(wire.extra),
    )


def _decode_pdu(pdu: EntityStatePdu, origin: Origin, now_s: float) -> EntityState:
    location = pdu.entityLocation
    position_enu = ecef_to_enu((location.x, location.y, location.z), origin)

    orientation_deg = dis_to_rpy_deg(
        pdu.entityOrientation.psi,
        pdu.entityOrientation.theta,
        pdu.entityOrientation.phi,
    )
    velocity = pdu.entityLinearVelocity
    velocity_wire = (velocity.x, velocity.y, velocity.z)
    dr_algorithm = int(pdu.deadReckoningParameters.deadReckoningAlgorithm)
    velocity_enu = _velocity_from_wire(
        velocity_wire, orientation_deg, origin, dr_algorithm
    )
    angular = pdu.deadReckoningParameters.entityAngularVelocity
    angular_wire = (float(angular.x), float(angular.y), float(angular.z))
    if dr_algorithm in ROTATING_DR_ALGORITHMS:
        angular_velocity_rps = body_rates_to_euler_rates(
            angular_wire, orientation_deg
        )
    else:
        angular_velocity_rps = angular_wire

    return EntityState(
        key=_entity_id(pdu),
        t_s=now_s,
        position_enu_m=position_enu,
        orientation_deg=orientation_deg,
        velocity_enu_mps=velocity_enu,
        angular_velocity_rps=angular_velocity_rps,
        entity_type=_entity_type(pdu),
        force_id=int(pdu.forceId),
        marking=pdu.marking.charactersString(),
    )


def decode_datagram(data: bytes, origin: Origin) -> List[EntityState]:
    """Decode every Entity State PDU in ``data`` into ENU states.

    Non-Entity-State PDUs are skipped.  ``t_s`` is the host monotonic receive
    time, not the PDU timestamp.
    """

    now_s = time.monotonic()
    states: List[EntityState] = []
    for start, end in pdu_spans(data):
        if data[start + 2] != ENTITY_STATE_PDU_TYPE:
            continue
        pdu = createPdu(bytes(data[start:end]))
        if pdu is None or getattr(pdu, "pduType", None) != ENTITY_STATE_PDU_TYPE:
            continue
        states.append(_decode_pdu(pdu, origin, now_s))
    return states
