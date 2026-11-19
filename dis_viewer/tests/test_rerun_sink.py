"""Headless tests for the Rerun sink: no viewer is ever spawned."""

from __future__ import annotations

from dis_viewer.model import EntityKey, EntityState, EntityType
from dis_viewer.sinks.rerun_sink import RerunSink, entity_path, entity_slug


def _state(key: EntityKey, t_s: float, offset: float = 0.0) -> EntityState:
    return EntityState(
        key=key,
        t_s=t_s,
        position_enu_m=(offset, offset * 2.0, 1000.0 + offset),
        orientation_deg=(5.0, -2.0, 45.0),
        velocity_enu_mps=(10.0, 20.0, 1.0),
        entity_type=EntityType(),
        force_id=1,
        marking="AC-1",
        stale=False,
    )


def test_entity_path_uses_documented_slug_form():
    key = EntityKey(site=1, application=2, entity=3)
    assert entity_slug(key) == "1_2_3"
    assert key.slug == "1_2_3"
    assert entity_path(key, "pose") == "world/entity/1_2_3/pose"


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
