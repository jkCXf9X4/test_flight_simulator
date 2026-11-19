"""DIS sink: neutral ENU entity states out as Entity State PDUs."""

from __future__ import annotations

from typing import Iterable, Mapping, Optional

from ..config import EntityType, Origin
from ..model import EntityKey, EntityState
from ..pdu import encode_entity_state
from ..transport import Channel


class DisSink:
    """Encode and publish Entity State PDUs on a channel."""

    def __init__(
        self,
        channel: Channel,
        origin: Origin,
        exercise_id: int = 1,
        dr_algorithm: int = 4,
        entity_types: Optional[Mapping[EntityKey, EntityType]] = None,
    ) -> None:
        self.channel = channel
        self.origin = origin
        self.exercise_id = int(exercise_id)
        self.dr_algorithm = int(dr_algorithm)
        self.entity_types = dict(entity_types or {})

    def publish(self, states: Iterable[EntityState]) -> int:
        """Send one PDU per state and return the total bytes sent."""

        sent_bytes = 0
        for state in states:
            datagram = encode_entity_state(
                state,
                self.origin,
                self.exercise_id,
                dr_algorithm=self.dr_algorithm,
                entity_type=self.entity_types.get(state.key),
            )
            sent = self.channel.send(datagram)
            sent_bytes += len(datagram) if sent is None else int(sent)
        return sent_bytes
