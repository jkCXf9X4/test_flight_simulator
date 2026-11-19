"""Round-trip tests for the shared JSONL recorder and the replay source."""

from __future__ import annotations

import json

from flight_viewer.model import EntityKey, EntityState
from flight_viewer.recorder import JsonlRecorder, JsonlSource


def _full_state(key: EntityKey, timestamp: float) -> EntityState:
    return EntityState(
        key=key,
        timestamp=timestamp,
        position_enu_m=(123.5, -456.25, 789.125),
        velocity_enu_mps=(10.0, -20.0, 0.5),
        orientation_rps=(0.0262, -0.0436, 6.2788),
        angular_velocity_rps=(0.01, -0.02, 0.03),
        marking="AC-007",
        force_id=3,
        exercise_id=2,
    )


def test_round_trip_preserves_every_dataclass_field(tmp_path):
    state = _full_state(EntityKey(2, 4, 8), 12.5)
    path = tmp_path / "recording.jsonl"

    recorder = JsonlRecorder(path)
    recorder.write(state)
    recorder.close()

    replayed = JsonlSource(path).receive(timeout=0)
    assert len(replayed) == 1
    assert replayed[0] == state


def test_two_states_replay_in_file_order(tmp_path):
    first = _full_state(EntityKey(1, 1, 1), 1.0)
    second = EntityState(
        key=EntityKey(1, 1, 2),
        timestamp=1.1,
        position_enu_m=first.position_enu_m,
        velocity_enu_mps=first.velocity_enu_mps,
        orientation_rps=first.orientation_rps,
        angular_velocity_rps=first.angular_velocity_rps,
        marking="AC-2",
        force_id=3,
        exercise_id=2,
    )
    path = tmp_path / "pair.jsonl"

    with JsonlRecorder(path) as recorder:
        recorder.write(first)
        recorder.write(second)

    replayed = JsonlSource(path).receive()
    assert [state.key for state in replayed] == [first.key, second.key]
    assert [state.timestamp for state in replayed] == [first.timestamp, second.timestamp]
    assert replayed == [first, second]

    source = JsonlSource(path)
    assert source.receive() == replayed
    assert source.receive() == []


def test_old_record_without_angular_velocity_loads_zeros(tmp_path):
    state = _full_state(EntityKey(1, 1, 1), 2.0)
    path = tmp_path / "legacy.jsonl"
    with JsonlRecorder(path) as recorder:
        recorder.write(state)

    legacy = json.loads(path.read_text(encoding="utf-8"))
    legacy.pop("angular_velocity_rps")
    path.write_text(json.dumps(legacy) + "\n", encoding="utf-8")

    replayed = JsonlSource(path).receive()
    assert replayed[0].angular_velocity_rps == (0.0, 0.0, 0.0)
