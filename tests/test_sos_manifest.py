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
SCENARIO_DIR = REPO_ROOT / "3rd_party" / "airplane" / "resources" / "scenarios"
RPR_PORT = 5505

EXPECTED = {
    "red_interceptor": (1, 5510, "high_altitude_intercept", "RED-1"),
    "red_striker": (2, 5512, "deep_strike_penetration", "RED-2"),
    "blue_cas": (3, 5514, "cas_multi_store_support", "BLUE-1"),
    "blue_baseline": (4, 5516, "test_scenario", "BLUE-2"),
}


def _manifest_cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "pysos_sysml", "manifest", *args],
        capture_output=True,
        text=True,
        check=False,
    )


def _manifest_json() -> dict:
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


def test_checked_in_manifest_matches_fresh_lowering():
    fresh = _manifest_cli(str(SYSML))
    assert fresh.returncode == 0, fresh.stderr
    assert MANIFEST.read_text(encoding="utf-8") == fresh.stdout
    check = _manifest_cli(str(SYSML), "-o", str(MANIFEST), "--check")
    assert check.returncode == 0, check.stderr


def test_generator_reports_stale_manifest(tmp_path):
    stale = tmp_path / "stale.manifest.json"
    stale.write_text("{}\n", encoding="utf-8")
    assert _manifest_cli(str(SYSML), "-o", str(stale), "--check").returncode == 1


def test_manifest_is_accepted_by_coordinate_and_constructs():
    spec = FederationSpec.from_json(_manifest_json())
    assert spec.validate() is spec
    assert spec.schema == 1
    federation = Federation(spec)
    assert len(federation.spec.instances) == 4


def test_four_distinct_entities_and_unique_endpoints():
    spec = FederationSpec.from_json(_manifest_json())
    assert len(spec.instances) == 4
    entities = [instance.entities[0].entity for instance in spec.instances]
    assert entities == ["1", "2", "3", "4"]
    assert len(set(entities)) == 4
    ports = [endpoint.port for instance in spec.instances for endpoint in instance.telemetry + instance.control]
    assert len(ports) == len(set(ports))
    assert RPR_PORT not in ports


def test_env_carries_scenario_and_telemetry_port():
    data = _manifest_json()
    for instance in data["instances"]:
        _entity, telemetry, scenario, _marking = EXPECTED[instance["name"]]
        assert instance["env"]["PYSOS_SCENARIO"] == scenario
        assert instance["env"]["PYSOS_TELEMETRY_PORT"] == str(telemetry)


def test_identity_args_carry_the_lowered_entity():
    data = _manifest_json()
    for instance in data["instances"]:
        entity = instance["entities"][0]
        command = instance["command"]
        assert command[command.index("--entity-site") + 1] == entity["site"]
        assert command[command.index("--entity-application") + 1] == entity["application"]
        assert command[command.index("--entity") + 1] == entity["entity"]
        assert command[command.index("--marking") + 1] == entity["marking"]


def test_scenarios_are_distinct_and_exist():
    data = _manifest_json()
    scenarios = [instance["env"]["PYSOS_SCENARIO"] for instance in data["instances"]]
    assert len(set(scenarios)) == 4
    for scenario in scenarios:
        assert (SCENARIO_DIR / f"{scenario}.json").is_file()
