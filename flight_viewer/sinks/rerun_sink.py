"""Rerun sink adapter over :mod:`pysos_interop.rerun_sink`.

The shared sink owns the documented path set ``world/entity/<slug>/`` with
``pose``, ``trail``, ``marker`` and the ``status/*`` scalars.  This adapter
keeps the viewer's constructor (``app_id``, ``rrd_path``, ``spawn``,
``origin``) and its ``log(states)`` call shape.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Iterable, Optional

from pysos_interop.rerun_sink import (
    ENTITY_LEAVES,
    STATUS_LEAVES,
    entity_path,
    entity_slug,
    rpy_rad_to_quaternion,
)
from pysos_interop.rerun_sink import (
    RerunSink as _SharedRerunSink,
)

from ..config import Origin
from ..model import EntityState

__all__ = [
    "ENTITY_LEAVES",
    "STATUS_LEAVES",
    "RerunSink",
    "entity_path",
    "entity_slug",
    "rpy_rad_to_quaternion",
]


class RerunSink(_SharedRerunSink):
    """Log entity states to Rerun, live (spawn) and/or to an ``.rrd`` file."""

    def __init__(
        self,
        app_id: str = "flight_viewer",
        rrd_path: Optional[Path] = None,
        spawn: bool = False,
        connect_grpc: Optional[str] = None,
        origin: Optional[Origin] = None,
    ) -> None:
        self._temporary: Optional[Path] = None
        if rrd_path is None:
            handle, temporary = tempfile.mkstemp(
                prefix="flight_viewer_", suffix=".rrd"
            )
            os.close(handle)
            self._temporary = Path(temporary)
            rrd_path = self._temporary
        self.spawn = bool(spawn)
        super().__init__(rrd_path, app_id=app_id, origin=origin)
        if connect_grpc is not None:
            # Stream into an already-running viewer/server (e.g. `rerun --serve-web`).
            self._rec.connect_grpc(connect_grpc or None)
        if self.spawn:
            try:
                self._rec.spawn()
            except Exception:
                self.close()
                raise

    def log(self, states: Iterable[EntityState], *, trail_points: int = 200) -> None:
        """Log a batch of entity states at their simulation time."""
        self.trail_points = max(1, int(trail_points))
        for state in states:
            self.observe(state)

    def close(self) -> None:
        super().close()
        if self._temporary is not None:
            Path(self._temporary).unlink(missing_ok=True)
