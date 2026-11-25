"""Headless tests for the shared Rerun sink adapter: no viewer is spawned."""

from __future__ import annotations

import math

from flight_viewer.model import EntityKey, EntityState
from flight_viewer.sinks.rerun_sink import (
    ENTITY_LEAVES,
    RerunSink,
    entity_path,
    entity_slug,
)


def _state(key: EntityKey, timestamp: float, offset: float = 0.0) -> EntityState:
    return EntityState(
        key=key,
        timestamp=timestamp,
        position_enu_m=(offset, offset * 2.0, 1000.0 + offset),
        velocity_enu_mps=(10.0, 20.0, 1.0),
        orientation_rps=tuple(math.radians(value) for value in (5.0, -2.0, 45.0)),
        angular_velocity_rps=(0.0, 0.0, 0.0),
        marking="AC-1",
    )


def test_entity_path_uses_documented_slug_form():
    key = EntityKey(site=1, application=2, entity=3)
    assert entity_slug(key) == "1_2_3"
    assert entity_path(key, "pose") == "world/entity/1_2_3/pose"
    assert ENTITY_LEAVES == (
        "pose",
        "trail",
        "marker",
        "status/airspeed_mps",
        "status/altitude_m",
        "status/climb_rate_mps",
        "status/climb_angle_deg",
    )


def test_headless_recording_writes_non_empty_rrd(tmp_path):
    rrd_path = tmp_path / "run.rrd"
    sink = RerunSink(rrd_path=rrd_path, spawn=False)
    try:
        sink.log(
            [
                _state(EntityKey(1, 1, 1), 1.0, offset=0.0),
                _state(EntityKey(1, 1, 2), 1.0, offset=10.0),
            ]
        )
    finally:
        sink.close()

    assert rrd_path.exists()
    assert rrd_path.stat().st_size > 0
