"""JSON Lines recorder and replay source for :class:`EntityState` values.

Each line is one entity state. Keys mirror the dataclass field order so the
file is stable/diffable. ``JsonlSource(..., realtime=False)`` drains the whole
file on the first ``receive`` call; with ``realtime=True`` it returns records
in original ``t_s`` batches, sleeping until each batch is due.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .model import EntityKey, EntityState, EntityType


def _state_to_dict(state: EntityState) -> Dict[str, Any]:
    key = state.key
    entity_type = state.entity_type
    return {
        "key": {
            "site": int(key.site),
            "application": int(key.application),
            "entity": int(key.entity),
        },
        "t_s": float(state.t_s),
        "position_enu_m": [float(value) for value in state.position_enu_m],
        "orientation_deg": [float(value) for value in state.orientation_deg],
        "velocity_enu_mps": [float(value) for value in state.velocity_enu_mps],
        "entity_type": {
            "kind": int(entity_type.kind),
            "domain": int(entity_type.domain),
            "country": int(entity_type.country),
            "category": int(entity_type.category),
            "subcategory": int(entity_type.subcategory),
            "specific": int(entity_type.specific),
            "extra": int(entity_type.extra),
        },
        "force_id": int(state.force_id),
        "marking": str(state.marking),
        "stale": bool(state.stale),
    }


def _state_from_dict(data: Dict[str, Any]) -> EntityState:
    return EntityState(
        key=EntityKey(
            site=int(data["key"]["site"]),
            application=int(data["key"]["application"]),
            entity=int(data["key"]["entity"]),
        ),
        t_s=float(data["t_s"]),
        position_enu_m=tuple(float(value) for value in data["position_enu_m"]),  # type: ignore[arg-type]
        orientation_deg=tuple(float(value) for value in data["orientation_deg"]),  # type: ignore[arg-type]
        velocity_enu_mps=tuple(float(value) for value in data["velocity_enu_mps"]),  # type: ignore[arg-type]
        entity_type=EntityType(
            kind=int(data["entity_type"]["kind"]),
            domain=int(data["entity_type"]["domain"]),
            country=int(data["entity_type"]["country"]),
            category=int(data["entity_type"]["category"]),
            subcategory=int(data["entity_type"]["subcategory"]),
            specific=int(data["entity_type"]["specific"]),
            extra=int(data["entity_type"]["extra"]),
        ),
        force_id=int(data["force_id"]),
        marking=str(data["marking"]),
        stale=bool(data["stale"]),
    )


class JsonlRecorder:
    """Append entity states as one JSON object per line."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self._file = self.path.open("w", encoding="utf-8")

    def write(self, states: List[EntityState]) -> None:
        for state in states:
            self._file.write(json.dumps(_state_to_dict(state), separators=(",", ":")) + "\n")
        self._file.flush()

    def close(self) -> None:
        if not self._file.closed:
            self._file.close()

    def __enter__(self) -> "JsonlRecorder":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()


class JsonlSource:
    """Replay a :class:`JsonlRecorder` file."""

    def __init__(self, path: Path, realtime: bool = False) -> None:
        self.path = Path(path)
        self.realtime = realtime
        self._records: List[EntityState] = []
        with self.path.open("r", encoding="utf-8") as handle:
            for line in handle:
                stripped = line.strip()
                if stripped:
                    self._records.append(_state_from_dict(json.loads(stripped)))
        self._index = 0
        self._started_at: Optional[float] = None
        self._first_t: Optional[float] = None

    def _next_until(self, t_s: float) -> List[EntityState]:
        batch: List[EntityState] = []
        while self._index < len(self._records) and self._records[self._index].t_s <= t_s:
            batch.append(self._records[self._index].copy_with())
            self._index += 1
        return batch

    def receive(self, timeout: float = 0) -> List[EntityState]:
        if self._index >= len(self._records):
            return []
        if not self.realtime:
            batch = [state.copy_with() for state in self._records[self._index :]]
            self._index = len(self._records)
            return batch

        target = self._records[self._index]
        if self._started_at is None:
            self._started_at = time.monotonic()
            self._first_t = target.t_s
        wait = (self._started_at + (target.t_s - self._first_t)) - time.monotonic()
        if wait > 0.0:
            time.sleep(wait)
        return self._next_until(target.t_s)

    def close(self) -> None:
        return None

    def __enter__(self) -> "JsonlSource":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()


__all__ = ["JsonlRecorder", "JsonlSource"]
