"""DIS source: UDP bytes in, neutral ENU entity states out."""

from __future__ import annotations

from typing import List

from ..config import Origin
from ..model import EntityState
from ..pdu import ENTITY_STATE_PDU_TYPE, decode_datagram, pdu_spans
from ..transport import Channel


class DisSource:
    """Receive Entity State PDUs and drop other exercises."""

    def __init__(self, channel: Channel, origin: Origin, exercise_id: int = 1) -> None:
        self.channel = channel
        self.origin = origin
        self.exercise_id = int(exercise_id) & 0xFF

    def receive(self, timeout: float | None) -> List[EntityState]:
        data = self.channel.receive(timeout)
        if not data:
            return []

        kept = bytearray()
        for start, end in pdu_spans(data):
            if data[start + 2] != ENTITY_STATE_PDU_TYPE:
                continue
            if data[start + 1] != self.exercise_id:
                continue
            kept.extend(data[start:end])

        if not kept:
            return []
        return decode_datagram(bytes(kept), self.origin)
