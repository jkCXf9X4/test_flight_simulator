"""The checked-in aircraft federation manifest is generated and valid."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from pysos_coordinate import Federation, FederationSpec

REPO_ROOT = Path(__file__).resolve().parents[1]
SYSML = REPO_ROOT / "sos" / "aircraft_federation.sysml"
MANIFEST = REPO_ROOT / "manifests" / "aircraft_federation.manifest.json"
RECORDER = "@pysos-recorder"
BIND_SOCKETS = (
    "@pysos-red-interceptor",
    "@pysos-red-striker",
    "@pysos-blue-cas",
    "@pysos-blue-baseline",
)

EXPECTED = {
    "red_interceptor": ("1", "@pysos-red-interceptor", "RED-1", "RedInterceptor"),
    "red_striker": ("2", "@pysos-red-striker", "RED-2", "RedStriker"),
    "blue_cas": ("3", "@pysos-blue-cas", "BLUE-1", "BlueCas"),
    "blue_baseline": ("4", "@pysos-blue-baseline", "BLUE-2", "BlueBaseline"),
}

SCENARIOS = {
    "red_interceptor": "high_altitude_intercept",
    "red_striker": "deep_strike_penetration",
    "blue_cas": "cas_multi_store_support",
    "blue_baseline": "test_scenario",
}


def _manifest_cli(*args: str) -> subprocess.CompletedProcess[str]:
    # The entity plane imports Aircraft + PysosSoS, so lowering goes through
    # the wrapper that resolves those include roots.
    return subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "entity_manifest.py"), *args],
        capture_output=True,
        text=True,
        check=False,
    )


def _manifest_json() -> dict:
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


def test_checked_in_manifest_matches_fresh_lowering():
    fresh = _manifest_cli()
    assert fresh.returncode == 0, fresh.stderr
    assert MANIFEST.read_text(encoding="utf-8") == fresh.stdout
    check = _manifest_cli("-o", str(MANIFEST), "--check")
    assert check.returncode == 0, check.stderr


def test_generator_reports_stale_manifest(tmp_path):
    stale = tmp_path / "stale.manifest.json"
    stale.write_text("{}\n", encoding="utf-8")
    assert _manifest_cli("-o", str(stale), "--check").returncode == 1


def test_every_entity_launch_spec_is_lowered():
    for instance in _manifest_json()["instances"]:
        assert instance["startup_timeout"] == 30.0
        assert instance["env"]["PYSOS_LAUNCH_MODE"] == "supervised"
        assert instance["env"]["PYSOS_READINESS"] == "socket_bound"
        assert instance["env"]["PYSOS_LAUNCH_ORDER"] == "2"
        assert instance["env"]["PYSOS_AFTER_PROCESS"] == "supervisor"


def test_manifest_is_accepted_by_coordinate_and_constructs():
    spec = FederationSpec.from_json(_manifest_json())
    assert spec.validate() is spec
    assert spec.schema == 2
    federation = Federation(spec)
    assert len(federation.spec.instances) == 4


def test_four_distinct_entities_and_unique_endpoints():
    spec = FederationSpec.from_json(_manifest_json())
    assert len(spec.instances) == 4
    entities = [instance.entities[0].entity for instance in spec.instances]
    assert entities == ["1", "2", "3", "4"]
    assert len(set(entities)) == 4
    sockets = [
        endpoint.path for instance in spec.instances for endpoint in instance.telemetry
    ]
    assert sockets == list(BIND_SOCKETS)
    assert len(sockets) == len(set(sockets))
    assert all(endpoint.transport == "unix" for instance in spec.instances for endpoint in instance.telemetry)
    assert all(not instance.control for instance in spec.instances)
    assert RECORDER not in sockets


def test_env_carries_the_telemetry_path_and_the_scenario_name():
    data = _manifest_json()
    for instance in data["instances"]:
        _entity, telemetry, _marking, _variant = EXPECTED[instance["name"]]
        assert instance["env"]["PYSOS_TRANSPORT"] == "unix"
        assert instance["env"]["PYSOS_TELEMETRY_PATH"] == telemetry
        assert instance["env"]["PYSOS_SCENARIO"] == SCENARIOS[instance["name"]]
        assert "PYSOS_TELEMETRY_PORT" not in instance["env"]
        assert "PYSOS_CONTROL_PATH" not in instance["env"]
        assert "PYSOS_CONTROL_PORT" not in instance["env"]


def test_entities_carry_the_lowered_identity_sets():
    data = _manifest_json()
    for instance in data["instances"]:
        entity = instance["entities"][0]
        expected_entity, _telemetry, marking, variant = EXPECTED[instance["name"]]
        assert entity["site"] == "1"
        assert entity["application"] == "1"
        assert entity["entity"] == expected_entity
        assert entity["marking"] == marking
        command = instance["command"]
        assert command[command.index("--variant") + 1] == variant


def test_four_distinct_variants_are_commanded():
    data = _manifest_json()
    variants = [
        instance["command"][instance["command"].index("--variant") + 1]
        for instance in data["instances"]
    ]
    assert variants == ["RedInterceptor", "RedStriker", "BlueCas", "BlueBaseline"]
    assert len(set(variants)) == 4
