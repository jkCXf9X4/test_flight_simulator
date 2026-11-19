"""JSONL recording from :mod:`pysos_interop` plus realtime replay glue.

The shared recorder and reader own the row schema.  ``JsonlSource`` adds the
viewer's realtime pacing and ``receive``/``exhausted`` interface on top of
:func:`pysos_interop.jsonl.iter_jsonl`.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import List, Optional

from pysos_interop.jsonl import JsonlRecorder, iter_jsonl

from .model import EntityState

__all__ = ["JsonlRecorder", "JsonlSource", "iter_jsonl"]


class JsonlSource:
    """Replay a JSONL recording written by :class:`JsonlRecorder`."""

    def __init__(self, path: Path, realtime: bool = False) -> None:
        self.path = Path(path)
        self.realtime = realtime
        self._records: List[EntityState] = list(iter_jsonl(self.path))
        self._index = 0
        self._started_at: Optional[float] = None
        self._first_t: Optional[float] = None

    @property
    def exhausted(self) -> bool:
        return self._index >= len(self._records)

    def _next_until(self, timestamp: float) -> List[EntityState]:
        batch: List[EntityState] = []
        while (
            self._index < len(self._records)
            and self._records[self._index].timestamp <= timestamp
        ):
            batch.append(self._records[self._index])
            self._index += 1
        return batch

    def receive(self, timeout: float = 0) -> List[EntityState]:
        if self._index >= len(self._records):
            return []
        if not self.realtime:
            batch = self._records[self._index :]
            self._index = len(self._records)
            return list(batch)

        target = self._records[self._index]
        if self._started_at is None:
            self._started_at = time.monotonic()
            self._first_t = target.timestamp
        wait = (self._started_at + (target.timestamp - self._first_t)) - time.monotonic()
        if wait > 0.0:
            time.sleep(wait)
        return self._next_until(target.timestamp)

    def close(self) -> None:
        return None

    def __enter__(self) -> "JsonlSource":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()
