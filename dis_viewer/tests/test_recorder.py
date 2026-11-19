"""Round-trip tests for the JSONL recorder and replay source."""

from __future__ import annotations

from dis_viewer.model import EntityKey, EntityState, EntityType
from dis_viewer.recorder import JsonlRecorder, JsonlSource


def _full_state(key: EntityKey, t_s: float) -> EntityState:
    return EntityState(
        key=key,
        t_s=t_s,
        position_enu_m=(123.5, -456.25, 789.125),
        orientation_deg=(1.5, -2.5, 359.75),
        velocity_enu_mps=(10.0, -20.0, 0.5),
        entity_type=EntityType(
            kind=1,
            domain=2,
            country=840,
            category=1,
            subcategory=3,
            specific=4,
            extra=5,
        ),
        force_id=3,
        marking="AC-007",
        stale=True,
    )


def test_round_trip_preserves_every_dataclass_field(tmp_path):
    state = _full_state(EntityKey(2, 4, 8), 12.5)
    path = tmp_path / "recording.jsonl"

    recorder = JsonlRecorder(path)
    recorder.write([state])
    recorder.close()

    replayed = JsonlSource(path).receive(timeout=0)
    assert len(replayed) == 1
    assert replayed[0] == state


def test_two_states_replay_in_file_order(tmp_path):
    first = _full_state(EntityKey(1, 1, 1), 1.0)
    second = _full_state(EntityKey(1, 1, 2), 1.1).copy_with(stale=False, marking="AC-2")
    path = tmp_path / "pair.jsonl"

    with JsonlRecorder(path) as recorder:
        recorder.write([first, second])

    replayed = JsonlSource(path).receive()
    assert [state.key for state in replayed] == [first.key, second.key]
    assert [state.t_s for state in replayed] == [first.t_s, second.t_s]
    assert replayed == [first, second]

    source = JsonlSource(path)
    assert source.receive() == replayed
    assert source.receive() == []
