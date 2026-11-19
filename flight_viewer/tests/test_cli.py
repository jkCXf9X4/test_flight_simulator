"""Integration smoke test for the command line entry point (headless)."""

from __future__ import annotations

import time
from pathlib import Path

from flight_viewer.cli import build_parser, main, resolve_exercise
from flight_viewer.model import EntityKey, EntityState
from flight_viewer.recorder import JsonlRecorder


def _states() -> list[EntityState]:
    key = EntityKey(1, 1, 1)
    return [
        EntityState(
            key=key,
            timestamp=0.0,
            position_enu_m=(0.0, 0.0, 1000.0),
            velocity_enu_mps=(0.0, 0.0, 0.0),
            orientation_rps=(0.0, 0.0, 0.0),
            angular_velocity_rps=(0.0, 0.0, 0.0),
            marking="AC-1",
        ),
        EntityState(
            key=key,
            timestamp=0.1,
            position_enu_m=(15.0, 30.0, 1001.0),
            velocity_enu_mps=(0.0, 0.0, 0.0),
            orientation_rps=(0.0, 0.0, 0.0),
            angular_velocity_rps=(0.0, 0.0, 0.0),
            marking="AC-1",
        ),
    ]


def test_parser_defaults() -> None:
    args = build_parser().parse_args([])
    assert args.source == "json-udp"
    assert args.sink == "rerun"
    assert args.duration == 0.0


def test_default_dr_algorithm_is_rvw() -> None:
    args = build_parser().parse_args(["--origin-lat", "0", "--origin-lon", "0"])
    assert resolve_exercise(args).dr_algorithm == 4


def test_dr_algorithm_flag_can_select_world_frame_velocity() -> None:
    args = build_parser().parse_args(
        ["--dr-algorithm", "2", "--origin-lat", "0", "--origin-lon", "0"]
    )
    assert resolve_exercise(args).dr_algorithm == 2


def test_jsonl_to_rerun_recording(tmp_path: Path) -> None:
    source_path = tmp_path / "run.jsonl"
    with JsonlRecorder(source_path) as recorder:
        for state in _states():
            recorder.write(state)
    rrd_path = tmp_path / "out.rrd"

    rc = main(
        [
            "--source",
            "jsonl",
            "--path",
            str(source_path),
            "--sink",
            "rerun",
            "--rrd",
            str(rrd_path),
            "--count",
            "2",
        ]
    )

    assert rc == 0
    assert rrd_path.exists()
    assert rrd_path.stat().st_size > 0


def test_jsonl_replay_stops_when_exhausted(tmp_path: Path) -> None:
    source_path = tmp_path / "run.jsonl"
    with JsonlRecorder(source_path) as recorder:
        for state in _states():
            recorder.write(state)
    rrd_path = tmp_path / "replay.rrd"

    started = time.monotonic()
    rc = main(
        [
            "--source",
            "jsonl",
            "--path",
            str(source_path),
            "--sink",
            "rerun",
            "--rrd",
            str(rrd_path),
            "--realtime",
            "--duration",
            "30",
        ]
    )
    elapsed = time.monotonic() - started

    assert rc == 0
    assert elapsed < 5.0
    assert rrd_path.stat().st_size > 0
