"""Entity State PDU adapter tests: byte identity, frames and round trips."""

from __future__ import annotations

import math
import struct
from pathlib import Path

import pytest
from opendis.PduFactory import createPdu
from pysos_interop.dis import BODY_FRAME_ALGORITHMS
from pysos_interop.rates import euler_rates_to_body_rates

from flight_viewer.config import EntityType, Origin
from flight_viewer.geo import enu_velocity_to_ecef
from flight_viewer.model import EntityKey, EntityState
from flight_viewer.pdu import (
    ENTITY_STATE_PDU_TYPE,
    decode_datagram,
    dis_timestamp,
    encode_entity_state,
    pdu_spans,
)
from flight_viewer.sources.dis_rx import DisSource

ORIGIN = Origin(latitude_deg=57.7, longitude_deg=12.0, altitude_m=100.0)
FIXTURES = Path(__file__).parent / "fixtures"
ENTITY_TYPE = EntityType(1, 2, 225, 1, 2, 3, 4)
ORIENTATION_DEG = (10.0, -5.0, 123.0)
ORIENTATION = tuple(math.radians(value) for value in ORIENTATION_DEG)
EULER_RATES = (0.1, -0.2, 0.3)
BODY_RATES = euler_rates_to_body_rates(ORIENTATION, EULER_RATES)


def make_state(**changes) -> EntityState:
    values = dict(
        key=EntityKey(1, 2, 3),
        timestamp=12.5,
        position_enu_m=(1000.0, -500.0, 250.0),
        velocity_enu_mps=(12.0, 3.0, -0.5),
        orientation_rps=ORIENTATION,
        angular_velocity_rps=BODY_RATES,
        marking="AC-3",
        force_id=3,
    )
    values.update(changes)
    return EntityState(**values)


def close_vec(actual, expected, tolerance):
    return all(abs(a - b) <= tolerance for a, b in zip(actual, expected))


def test_dis_timestamp_relative_ticks_and_hour_wrap():
    assert dis_timestamp(0.0) == 0
    assert dis_timestamp(3600.0) == 0
    assert dis_timestamp(1800.0) == 1 << 30
    assert dis_timestamp(1.0) == int((1 << 31) / 3600.0)
    absolute = dis_timestamp(1800.0, relative=False)
    assert absolute == (1 << 30) | 0x80000000


@pytest.mark.parametrize("fixture", ["rvw", "pw"])
def test_encoded_bytes_match_pre_migration_golden(fixture):
    # The fixtures were produced by the project-local encoder before dedup.
    algorithm = 4 if fixture == "rvw" else 2
    golden = bytes.fromhex(
        (FIXTURES / f"entity_state_{fixture}_v7.hex").read_text(encoding="ascii").strip()
    )
    encoded = encode_entity_state(
        make_state(),
        ORIGIN,
        7,
        dr_algorithm=algorithm,
        timestamp=0x01020304,
        entity_type=ENTITY_TYPE,
    )
    assert encoded == golden


def test_encode_decode_pose_identity_and_reenecode():
    state = make_state()
    encoded = encode_entity_state(
        state,
        ORIGIN,
        7,
        dr_algorithm=4,
        timestamp=0x01020304,
        entity_type=ENTITY_TYPE,
    )
    assert len(encoded) == 144
    assert encoded[0] == 7
    assert encoded[1] == 7
    assert encoded[2] == ENTITY_STATE_PDU_TYPE
    assert struct.unpack_from(">H", encoded, 8)[0] == 144

    decoded = decode_datagram(encoded, ORIGIN)[0]
    assert decoded.key == state.key
    assert decoded.force_id == state.force_id
    assert decoded.marking == state.marking
    assert decoded.exercise_id == 7
    assert close_vec(decoded.position_enu_m, state.position_enu_m, 1e-3)
    assert close_vec(decoded.orientation_rps, state.orientation_rps, 1e-6)
    assert close_vec(decoded.velocity_enu_mps, state.velocity_enu_mps, 1e-3)
    assert close_vec(decoded.angular_velocity_rps, state.angular_velocity_rps, 1e-6)

    reencoded = encode_entity_state(
        decoded,
        ORIGIN,
        7,
        dr_algorithm=4,
        timestamp=0x01020304,
        entity_type=ENTITY_TYPE,
    )
    assert reencoded == encoded


def test_entity_type_is_carried_on_the_wire():
    encoded = encode_entity_state(
        make_state(),
        ORIGIN,
        7,
        dr_algorithm=4,
        timestamp=1,
        entity_type=ENTITY_TYPE,
    )
    pdu = createPdu(encoded)
    wire = pdu.entityType
    assert (
        wire.entityKind,
        wire.domain,
        wire.country,
        wire.category,
        wire.subcategory,
        wire.specific,
        wire.extra,
    ) == ENTITY_TYPE.as_tuple()


def test_world_frame_velocity_is_ecef():
    state = make_state()
    encoded = encode_entity_state(state, ORIGIN, 1, dr_algorithm=2, timestamp=1)
    decoded = decode_datagram(encoded, ORIGIN)[0]
    assert close_vec(decoded.velocity_enu_mps, state.velocity_enu_mps, 1e-3)

    pdu = createPdu(encoded)
    raw = (
        pdu.entityLinearVelocity.x,
        pdu.entityLinearVelocity.y,
        pdu.entityLinearVelocity.z,
    )
    assert pdu.deadReckoningParameters.deadReckoningAlgorithm == 2
    assert close_vec(raw, enu_velocity_to_ecef(state.velocity_enu_mps, ORIGIN), 1e-2)


def test_body_frame_velocity_round_trips_and_is_not_ecef():
    # Zero attitude: body x=north, y=east, z=down, so an eastward ENU
    # velocity of 10 m/s becomes body (0, 10, 0) rather than ECEF.
    state = make_state(
        orientation_rps=(0.0, 0.0, 0.0), velocity_enu_mps=(10.0, 0.0, 0.0)
    )
    encoded = encode_entity_state(state, ORIGIN, 1, dr_algorithm=4, timestamp=1)
    pdu = createPdu(encoded)
    raw = (
        pdu.entityLinearVelocity.x,
        pdu.entityLinearVelocity.y,
        pdu.entityLinearVelocity.z,
    )
    assert pdu.deadReckoningParameters.deadReckoningAlgorithm in BODY_FRAME_ALGORITHMS
    assert close_vec(raw, (0.0, 10.0, 0.0), 1e-3)

    decoded = decode_datagram(encoded, ORIGIN)[0]
    assert close_vec(decoded.velocity_enu_mps, state.velocity_enu_mps, 1e-3)


def test_angular_velocity_round_trips_for_algorithm_four():
    state = make_state(angular_velocity_rps=BODY_RATES)

    encoded = encode_entity_state(state, ORIGIN, 1, dr_algorithm=4, timestamp=1)
    pdu = createPdu(encoded)
    wire = pdu.deadReckoningParameters.entityAngularVelocity
    assert close_vec((wire.x, wire.y, wire.z), BODY_RATES, 1e-6)
    acceleration = pdu.deadReckoningParameters.entityLinearAcceleration
    assert close_vec(
        (acceleration.x, acceleration.y, acceleration.z), (0.0, 0.0, 0.0), 0.0
    )

    decoded = decode_datagram(encoded, ORIGIN)[0]
    assert close_vec(decoded.angular_velocity_rps, BODY_RATES, 1e-6)


def test_non_rotating_algorithm_carries_zero_angular_velocity():
    encoded = encode_entity_state(
        make_state(), ORIGIN, 1, dr_algorithm=2, timestamp=1
    )
    pdu = createPdu(encoded)
    wire = pdu.deadReckoningParameters.entityAngularVelocity
    assert close_vec((wire.x, wire.y, wire.z), (0.0, 0.0, 0.0), 0.0)


def test_concatenated_pdus_decode_in_order():
    first = make_state(key=EntityKey(1, 2, 3), marking="ONE")
    second = make_state(key=EntityKey(1, 2, 4), marking="TWO")
    data = encode_entity_state(first, ORIGIN, 1, timestamp=1) + encode_entity_state(
        second, ORIGIN, 1, timestamp=2
    )
    assert pdu_spans(data) == [(0, 144), (144, 288)]
    states = decode_datagram(data, ORIGIN)
    assert [state.key.entity for state in states] == [3, 4]
    assert [state.marking for state in states] == ["ONE", "TWO"]


def test_non_entity_state_pdu_is_skipped():
    # Minimal 12-byte non-ES PDU: version, exercise, type 22, family 0,
    # timestamp, length, pduStatus, padding.
    comment = struct.pack(">BBBBLH", 7, 1, 22, 0, 0, 12) + b"\x00\x00"
    entity = encode_entity_state(make_state(), ORIGIN, 1, timestamp=1)
    states = decode_datagram(comment + entity + comment, ORIGIN)
    assert len(states) == 1
    assert states[0].key == EntityKey(1, 2, 3)


class FakeChannel:
    def __init__(self, data: bytes) -> None:
        self.data = data

    def send(self, data: bytes) -> int:
        return len(data)

    def receive(self, timeout: float | None) -> bytes | None:
        return self.data

    def close(self) -> None:
        self.data = b""


def test_dis_source_drops_wrong_exercise():
    wrong = encode_entity_state(make_state(), ORIGIN, 2, timestamp=1)
    right = encode_entity_state(
        make_state(key=EntityKey(1, 2, 9), marking="KEEP"), ORIGIN, 1, timestamp=1
    )

    assert DisSource(FakeChannel(wrong), ORIGIN, exercise_id=1).receive(0.0) == []
    states = DisSource(FakeChannel(wrong + right), ORIGIN, exercise_id=1).receive(0.0)
    assert len(states) == 1
    assert states[0].key == EntityKey(1, 2, 9)
    assert states[0].marking == "KEEP"


def test_golden_entity_state_v7_fixture():
    data = bytes.fromhex((FIXTURES / "entity_state_v7.hex").read_text(encoding="ascii").strip())
    assert len(data) == 144
    assert data[0] == 7
    assert data[1] == 3  # exercise id
    assert data[2] == ENTITY_STATE_PDU_TYPE
    assert struct.unpack_from(">I", data, 4)[0] == 0x01020304
    assert struct.unpack_from(">H", data, 8)[0] == 144
    assert data[18] == 2  # force id
    assert data[88] == 3  # DR algorithm RPW

    states = decode_datagram(data, ORIGIN)
    assert len(states) == 1
    state = states[0]
    assert state.key == EntityKey(1, 1, 7)
    assert state.marking == "GOLD-7"
    assert state.force_id == 2
    assert close_vec(state.position_enu_m, (1000.0, -500.0, 250.0), 1e-3)
    assert close_vec(
        state.orientation_rps,
        [math.radians(v) for v in (10.0, -5.0, 123.0)],
        1e-6,
    )
    assert close_vec(state.velocity_enu_mps, (12.0, 3.0, -0.5), 1e-3)
