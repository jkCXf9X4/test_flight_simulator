"""CLI-level tests for repeatable ``--telemetry`` multi-source specs."""

from __future__ import annotations

import pytest

from dis_viewer.cli import build_parser, resolve_telemetry


def test_telemetry_flags_build_one_spec_per_aircraft():
    args = build_parser().parse_args(
        [
            "--source",
            "json-udp",
            "--telemetry",
            "5501:1",
            "--telemetry",
            "5503:2",
        ]
    )

    specs = resolve_telemetry(args)

    assert [(host, port, entity.key.entity) for host, port, entity in specs] == [
        ("127.0.0.1", 5501, 1),
        ("127.0.0.1", 5503, 2),
    ]
    assert [entity.key.site for _, _, entity in specs] == [1, 1]
    assert [entity.key.application for _, _, entity in specs] == [1, 1]
    assert [entity.resolved_marking() for _, _, entity in specs] == ["AC-1", "AC-2"]


def test_malformed_telemetry_spec_exits_non_zero():
    args = build_parser().parse_args(["--telemetry", "not-a-spec"])

    with pytest.raises(SystemExit) as excinfo:
        resolve_telemetry(args)

    assert excinfo.value.code != 0


def test_duplicate_telemetry_entity_exits_non_zero():
    args = build_parser().parse_args(
        ["--telemetry", "5501:1", "--telemetry", "5503:1"]
    )

    with pytest.raises(SystemExit) as excinfo:
        resolve_telemetry(args)

    assert excinfo.value.code != 0
