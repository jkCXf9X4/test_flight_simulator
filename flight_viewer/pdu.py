"""IEEE 1278.1 Entity State PDU adapter over :mod:`pysos_interop.dis`.

The shared codec owns PDU assembly, ECEF/ENU conversion, body-frame velocity
and angular velocity.  This module keeps only the project boundary:

* scenario ``EntityType`` is patched into the PDU because the shared entity
  state deliberately does not carry entity type;
* a datagram may hold several PDUs, while the shared decoder reads one;
* the viewer writes model radians straight to the wire.
"""

from __future__ import annotations

import struct
from dataclasses import replace
from typing import List, Optional, Tuple

from pysos_interop.dis import (
    ENTITY_STATE_PDU_TYPE,
    PDU_HEADER_LEN,
    PROTOCOL_VERSION,
    RELATIVE_TIMESTAMP_MASK,
    TICKS_PER_HOUR,
    decode_entity_state,
    dis_timestamp,
)
from pysos_interop.dis import encode_entity_state as _encode_entity_state

from .config import EntityType, Origin
from .model import EntityState

__all__ = [
    "ENTITY_STATE_PDU_TYPE",
    "PDU_HEADER_LEN",
    "PROTOCOL_VERSION",
    "RELATIVE_TIMESTAMP_MASK",
    "TICKS_PER_HOUR",
    "decode_datagram",
    "dis_timestamp",
    "encode_entity_state",
    "pdu_spans",
]

# PDU header (12) + entity id (6) + force id (1) + variable-parameter count (1).
ENTITY_TYPE_OFFSET = PDU_HEADER_LEN + 8
ENTITY_TYPE_STRUCT = ">BBHBBBB"


def encode_entity_state(
    state: EntityState,
    origin: Origin,
    exercise_id: int,
    *,
    dr_algorithm: int = 4,
    timestamp: Optional[int] = None,
    entity_type: Optional[EntityType] = None,
) -> bytes:
    """Serialise one Entity State PDU.

    ``timestamp`` defaults to the DIS header timestamp derived from
    ``state.timestamp`` (relative).  ``entity_type`` is scenario identity
    metadata, patched into the shared PDU after encoding.
    """

    stub = replace(state, exercise_id=int(exercise_id) & 0xFF)
    data = bytearray(
        _encode_entity_state(
            stub,
            origin=origin,
            dr_algorithm=dr_algorithm,
            timestamp=timestamp,
        )
    )
    kind, domain, country, category, subcategory, specific, extra = (
        (EntityType() if entity_type is None else entity_type).as_tuple()
    )
    struct.pack_into(
        ENTITY_TYPE_STRUCT,
        data,
        ENTITY_TYPE_OFFSET,
        kind,
        domain,
        country,
        category,
        subcategory,
        specific,
        extra,
    )
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


def decode_datagram(data: bytes, origin: Origin) -> List[EntityState]:
    """Decode every Entity State PDU in ``data`` into ENU states.

    Non-Entity-State PDUs are skipped.  The timestamp is the PDU header time,
    not the host receive time.
    """

    states: List[EntityState] = []
    for start, end in pdu_spans(data):
        if data[start + 2] != ENTITY_STATE_PDU_TYPE:
            continue
        try:
            states.append(decode_entity_state(bytes(data[start:end]), origin=origin))
        except ValueError:
            continue
    return states
