"""The system-of-systems model is complete enough to start and run the federation."""

from __future__ import annotations

import copy
import json
import zipfile
from dataclasses import replace
from pathlib import Path

import prepare_instance_bundle
import pytest
import sos_model
from pysos_coordinate import FederationSpec

REPO_ROOT = Path(__file__).resolve().parents[1]
MODEL_PATH = REPO_ROOT / "sos" / "federation_system.sysml"
MANIFEST_PATH = REPO_ROOT / "manifests" / "aircraft_federation.manifest.json"


def _model() -> sos_model.SystemModel:
    return sos_model.load_model(MODEL_PATH)


def _manifest() -> dict:
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


def _instance(manifest: dict, name: str) -> dict:
    for instance in manifest["instances"]:
        if instance["name"] == name:
            return instance
    raise KeyError(name)


def _command_flags(argv: list[str], flag: str) -> list[str]:
    return [argv[index + 1] for index, token in enumerate(argv[:-1]) if token == flag]


def test_model_and_manifest_are_complete():
    assert sos_model.check(_manifest(), _model()) == []
    FederationSpec.from_json(_manifest()).validate()


def test_every_instance_is_paced_and_bounded():
    manifest = _manifest()
    argv = _instance(manifest, "red_striker")["command"]
    argv.remove("--realtime")
    argv[argv.index("--stop-time") + 1] = "30"

    problems = sos_model.check(manifest, _model())

    assert any("red_striker: --realtime is False" in item for item in problems)
    assert any("red_striker: --stop-time 30.0 != timing.stop_time_s 120.0" in item for item in problems)


def test_every_instance_declares_its_frame_and_placement():
    manifest = _manifest()
    argv = _instance(manifest, "blue_cas")["command"]
    argv.remove("--waypoint-frame")
    argv.remove("federation")
    argv.remove("--offset-east-km")
    argv.remove("10")

    problems = sos_model.check(manifest, _model())

    assert any("blue_cas: --waypoint-frame is missing" in item for item in problems)
    assert any("blue_cas: placement offsets are missing" in item for item in problems)


def test_duplicate_placement_is_reported():
    manifest = _manifest()
    argv = _instance(manifest, "blue_baseline")["command"]
    argv[argv.index("--offset-east-km") + 1] = "5"

    problems = sos_model.check(manifest, _model())

    assert any("placement (0.0, 5.0) collides with red_striker" in item for item in problems)


def test_host_port_collision_is_reported():
    model = _model()
    orchestrator = model.process("orchestrator")
    assert orchestrator is not None
    collided = replace(orchestrator, ports={"rpr_in": 5510})

    problems = sos_model.check(
        _manifest(),
        replace(model, processes=tuple(collided if item.name == "orchestrator" else item for item in model.processes)),
    )

    assert any("port 5510 declared by both red_interceptor.telemetry" in item for item in problems)


def test_every_telemetry_port_feeds_a_modelled_flow():
    model = _model()
    flows = tuple(
        flow
        for flow in model.flows
        if flow.name not in {"telemetry_to_orchestrator", "telemetry_to_viewer"}
    )

    problems = sos_model.check(_manifest(), replace(model, flows=flows))

    assert any("red_interceptor: telemetry port 5510 feeds no modelled flow" in item for item in problems)


def test_every_control_port_has_a_producer():
    model = _model()
    flows = tuple(flow for flow in model.flows if flow.name != "pilot_control")

    problems = sos_model.check(_manifest(), replace(model, flows=flows))

    assert any("blue_baseline: control port 5517 has no modelled producer" in item for item in problems)


def test_viewer_telemetry_must_match_the_manifest():
    model = _model()
    viewer = model.process("viewer")
    assert viewer is not None
    command = list(viewer.command)
    command[command.index("5512:2")] = "5512:9"

    problems = sos_model.check(
        _manifest(),
        replace(model, processes=tuple(replace(viewer, command=tuple(command)) if item.name == "viewer" else item for item in model.processes)),
    )

    assert any("processes.viewer: --telemetry" in item for item in problems)


def test_federation_and_timing_must_match_the_manifest():
    manifest = _manifest()
    manifest["name"] = "OtherFederation"
    manifest["timing"] = "event"

    problems = sos_model.check(manifest, _model())

    assert any("manifest.name 'OtherFederation'" in item for item in problems)
    assert any("manifest.timing 'event'" in item for item in problems)


def test_frame_origin_must_match_the_reference_scenario():
    model = _model()
    origin = replace(model.frame.origin, latitude_deg=-3.5)

    problems = sos_model.check(
        _manifest(), replace(model, frame=replace(model.frame, origin=origin))
    )

    assert any("frame.origin.latitude_deg -3.5" in item for item in problems)


def test_system_plane_is_authored_in_sysml_v2():
    assert MODEL_PATH.suffix == ".sysml"
    model = _model()
    assert (REPO_ROOT / model.entity_model).is_file()
    assert model.instance_count == len(_manifest()["instances"])


def test_instance_count_must_match_the_manifest():
    model = _model()

    problems = sos_model.check(_manifest(), replace(model, instance_count=2))

    assert any("manifest.instances has 4 entr(ies) but the model declares part instances : 2" in item for item in problems)


def test_missing_system_description_is_rejected(tmp_path):
    source = tmp_path / "empty.sysml"
    source.write_text("package Empty {\n  part def Something {\n  }\n}\n", encoding="utf-8")

    with pytest.raises(sos_model.ModelError, match="unknown part definition"):
        sos_model.load_model(source)


def test_check_does_not_mutate_its_inputs():
    manifest = _manifest()
    snapshot = copy.deepcopy(manifest)
    sos_model.check(manifest, _model())
    assert manifest == snapshot


SCENARIO_SSP = REPO_ROOT / "build" / "ssp" / "scenario.ssp"
requires_built_aircraft = pytest.mark.skipif(
    not SCENARIO_SSP.is_file(), reason="build/ssp/scenario.ssp is not built"
)


@requires_built_aircraft
def test_built_aircraft_matches_the_model():
    assert sos_model.check(_manifest(), _model(), artifacts=True) == []


@requires_built_aircraft
def test_aircraft_component_drift_is_reported():
    model = _model()
    components = tuple(
        replace(component, fmu="Renamed.fmu") if component.name == "udp_bridge" else component
        for component in model.aircraft.components
    )

    problems = sos_model.check(
        _manifest(),
        replace(model, aircraft=replace(model.aircraft, components=components)),
        artifacts=True,
    )

    assert any("udp_bridge" in item and "Renamed.fmu" in item for item in problems)
    assert any("resources/Renamed.fmu is missing" in item for item in problems)


@requires_built_aircraft
def test_aircraft_connection_drift_is_reported():
    model = _model()
    wires = tuple(
        replace(wire, target_port="nowhere") if wire.source == "udp_bridge" else wire
        for wire in model.aircraft.wires
    )

    problems = sos_model.check(
        _manifest(),
        replace(model, aircraft=replace(model.aircraft, wires=wires)),
        artifacts=True,
    )

    assert any("udp_bridge.pilotCommand -> control_interface.nowhere" in item for item in problems)


@requires_built_aircraft
def test_bridge_input_flag_must_match_the_built_scenario():
    problems = sos_model.check(_manifest(), replace(_model(), bridge_input=True), artifacts=True)

    assert any("useBridgeInput" in item and "true" in item for item in problems)


def test_missing_artifacts_fail_only_when_required():
    model = replace(_model(), source_ssp="build/runs/not-built/aircraft.ssp")

    assert not any(
        "does not exist" in item
        for item in sos_model.check(_manifest(), model)
    )
    assert any(
        "does not exist" in item
        for item in sos_model.check(_manifest(), model, artifacts=True)
    )


def test_system_plane_imports_the_airplane_architecture():
    model = _model()
    architecture = REPO_ROOT / model.architecture

    assert architecture.is_file()
    assert "package Aircraft" in architecture.read_text(encoding="utf-8")
    assert len(model.aircraft.components) == 10
    assert len(model.aircraft.wires) == 24
    assert "part def UdpBridge" not in MODEL_PATH.read_text(encoding="utf-8")


def test_missing_reference_origin_is_reported():
    manifest = _manifest()
    argv = _instance(manifest, "blue_cas")["command"]
    index = argv.index("--reference-longitude-deg")
    del argv[index:index + 2]

    problems = sos_model.check(manifest, _model())

    assert any("blue_cas: --reference-longitude-deg is missing" in item for item in problems)


@requires_built_aircraft
def test_reference_origin_and_bridge_input_land_in_the_instance_bundle(tmp_path):
    summary = prepare_instance_bundle.prepare_instance(
        2,
        SCENARIO_SSP,
        tmp_path,
        reference_latitude_deg=-2.957519,
        reference_longitude_deg=39.232955,
        reference_altitude_m=0.0,
        waypoint_frame="federation",
        stop_time=120.0,
    )

    with zipfile.ZipFile(summary["ssp"]) as archive:
        ssv = archive.read("resources/MissionScenario.ssv").decode("utf-8")
        ssm = archive.read("resources/HighAltitudeIntercept.ssm").decode("utf-8")

    assert 'name="udp_bridge.reference_latitude_deg"' in ssv
    assert "-2.957519000" in ssv
    assert 'name="udp_bridge.reference_longitude_deg"' in ssv
    assert "39.232955000" in ssv
    assert 'name="useBridgeInput"' in ssv
    assert 'target="control_interface.useBridgeInput"' in ssm
    assert 'target="udp_bridge.reference_altitude_m"' in ssm
    assert summary["waypoint_frame"] == "federation"
    assert summary["bridge_input"] == "false"


def test_system_plane_must_import_the_architecture(tmp_path):
    source = tmp_path / "federation_system.sysml"
    source.write_text(
        MODEL_PATH.read_text(encoding="utf-8").replace("private import Aircraft::*;", ""),
        encoding="utf-8",
    )

    with pytest.raises(sos_model.ModelError, match="does not import"):
        sos_model.load_model(source)


def test_declared_architecture_must_exist(tmp_path):
    source = tmp_path / "federation_system.sysml"
    source.write_text(
        MODEL_PATH.read_text(encoding="utf-8").replace(
            'attribute architecture : String = "3rd_party/airplane/architecture/aircraft.sysml";',
            'attribute architecture : String = "no/such/aircraft.sysml";',
        ),
        encoding="utf-8",
    )

    with pytest.raises(sos_model.ModelError, match="does not exist"):
        sos_model.load_model(source)
