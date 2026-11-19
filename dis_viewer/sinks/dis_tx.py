"""DIS sink: neutral ENU entity states out as Entity State PDUs."""

from __future__ import annotations

from typing import Iterable

from ..config import Origin
from ..model import EntityState
from ..pdu import encode_entity_state
from ..transport import Channel


class DisSink:
    """Encode and publish Entity State PDUs on a channel."""

    def __init__(
        self,
        channel: Channel,
        origin: Origin,
        exercise_id: int = 1,
        dr_algorithm: int = 3,
    ) -> None:
        self.channel = channel
        self.origin = origin
        self.exercise_id = int(exercise_id)
        self.dr_algorithm = int(dr_algorithm)

    def publish(self, states: Iterable[EntityState]) -> int:
        """Send one PDU per state and return the total bytes sent."""

        sent_bytes = 0
        for state in states:
            datagram = encode_entity_state(
                state,
                self.origin,
                self.exercise_id,
                dr_algorithm=self.dr_algorithm,
            )
            sent = self.channel.send(datagram)
            sent_bytes += len(datagram) if sent is None else int(sent)
        return sent_bytes
