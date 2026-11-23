"""The checked-in manifest is generated, schema-valid, and matches the flags."""

from __future__ import annotations

import json

import generate_instance_manifest
import instance_manifest
import pytest
from pysos_coordinate import FederationSpec, SpecError

MANIFEST = instance_manifest.DEFAULT_MANIFEST


def _manifest_json() -> dict:
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


def test_checked_in_manifest_validates():
    spec = instance_manifest.load_spec(MANIFEST)
    assert spec.validate() is spec
    assert spec.schema == 1
    assert spec.name == "high_altitude_intercept"
    assert spec.timing.value == "wall_clock"
    assert [instance.name for instance in spec.instances] == ["instance-1", "instance-2"]


def test_top_level_keys_and_instance_shape():
    data = _manifest_json()
    assert list(data) == ["schema", "name", "timing", "instances"]
    for instance in data["instances"]:
        assert list(instance) == [
            "name",
            "command",
            "cwd",
            "env",
            "entities",
            "telemetry",
            "control",
            "startup_timeout",
        ]
        assert instance["cwd"] == "."
        assert instance["control"] == []
        assert isinstance(instance["command"], list)
        assert all(isinstance(arg, str) for arg in instance["command"])


def test_ports_entities_and_separation_match_scenario():
    data = _manifest_json()
    first, second = data["instances"]
    assert first["telemetry"] == [{"host": "127.0.0.1", "port": 5510}]
    assert first["control"] == []
    assert second["telemetry"] == [{"host": "127.0.0.1", "port": 5512}]
    assert second["control"] == []
    assert first["env"] == {
        "PYSOS_SCENARIO": "test_scenario",
        "PYSOS_TELEMETRY_PORT": "5510",
    }
    assert second["env"] == {
        "PYSOS_SCENARIO": "test_scenario",
        "PYSOS_TELEMETRY_PORT": "5512",
    }

    assert first["entities"] == [{"site": "1", "application": "1", "entity": "1", "marking": ""}]
    assert second["entities"] == [{"site": "1", "application": "1", "entity": "2", "marking": ""}]

    first_command = first["command"]
    second_command = second["command"]
    assert first_command[first_command.index("--offset-east-km") + 1] == "0.0"
    assert second_command[second_command.index("--offset-east-km") + 1] == "5.0"
    assert second_command[second_command.index("--offset-north-km") + 1] == "0.0"


def test_identity_and_reference_args_match_the_manifest():
    data = _manifest_json()
    for index, instance in enumerate(data["instances"], start=1):
        command = instance["command"]
        entity = instance["entities"][0]
        assert command[command.index("--entity-site") + 1] == entity["site"]
        assert command[command.index("--entity-application") + 1] == entity["application"]
        assert command[command.index("--entity") + 1] == str(index)
        assert command[command.index("--marking") + 1] == entity["marking"]
        assert command[command.index("--waypoint-frame") + 1] == "federation"
        assert command[command.index("--reference-latitude-deg") + 1] == "-2.957519"
        assert command[command.index("--reference-longitude-deg") + 1] == "39.232955"
        assert command[command.index("--reference-altitude-m") + 1] == "0.0"


def test_manifest_is_generated_not_hand_edited():
    generated = instance_manifest.build_spec().to_json()
    assert generated == _manifest_json()
    assert generate_instance_manifest.main(["--check"]) == 0


def test_generator_reports_stale_manifest(tmp_path):
    stale = tmp_path / "stale.manifest.json"
    stale.write_text("{}\n", encoding="utf-8")
    assert generate_instance_manifest.main(["--check", "--out", str(stale)]) == 1


def test_translated_flags_match_manifest_exactly():
    translated = instance_manifest.build_spec(
        instances=2,
        python=instance_manifest.DEFAULT_PYTHON,
        source_ssp=instance_manifest.DEFAULT_SOURCE_SSP,
        out_dir=instance_manifest.DEFAULT_OUT_DIR,
        stop_time=None,
        realtime=False,
        scenario_path=instance_manifest.SCENARIO_PATH,
    )
    assert translated.to_json() == _manifest_json()


def test_python_override_changes_only_argv_zero():
    baseline = instance_manifest.build_spec().to_json()
    overridden = instance_manifest.build_spec(python="/opt/python3").to_json()
    for before, after in zip(baseline["instances"], overridden["instances"], strict=True):
        assert before["command"][1:] == after["command"][1:]
        assert after["command"][0] == "/opt/python3"


def test_single_instance_uses_first_port_and_no_offset():
    spec = instance_manifest.build_spec(instances=1)
    instance = spec.instances[0]
    assert [(endpoint.port) for endpoint in instance.telemetry] == [5510]
    assert instance.control == []
    command = instance.command
    assert command[command.index("--offset-east-km") + 1] == "0.0"


def test_flags_are_translated_into_stop_time_and_realtime():
    spec = instance_manifest.build_spec(stop_time=10.0, realtime=True)
    for instance in spec.instances:
        assert instance.command[-3:] == ["--stop-time", "10.0", "--realtime"]


@pytest.mark.parametrize(
    "mutate",
    [
        lambda data: data.update(schema=2),
        lambda data: data.update(timing="lock_step"),
        lambda data: data["instances"][1]["telemetry"][0].update(port=5510),
    ],
)
def test_invalid_manifests_are_rejected(mutate):
    data = _manifest_json()
    mutate(data)
    with pytest.raises(SpecError):
        FederationSpec.from_json(data)
