"""The system-of-systems model is complete enough to start and run the federation."""

from __future__ import annotations

import copy
import json
import zipfile
from dataclasses import replace
from functools import lru_cache
from pathlib import Path

import entity_manifest
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


@lru_cache(maxsize=1)
def _federation():
    return entity_manifest.load_entity_model(REPO_ROOT / _model().entity_model)


def _entity(federation, name: str):
    for instance in federation.instances:
        if instance.name == name:
            return instance
    raise KeyError(name)


def _with_entity(federation, name: str, **changes):
    return replace(
        federation,
        instances=[
            replace(instance, **changes) if instance.name == name else instance
            for instance in federation.instances
        ],
    )


def test_model_and_manifest_are_complete():
    model = _model()
    assert sos_model.check(_manifest(), model) == []
    FederationSpec.from_json(_manifest()).validate()

    entity = _federation()
    assert [instance.name for instance in model.instances] == [
        instance.name for instance in entity.instances
    ]
    assert [instance.order for instance in model.instances] == list(
        range(len(model.instances))
    )
    assert [instance.participant.split("::")[-1] for instance in model.instances] == [
        instance.part_def for instance in entity.instances
    ]
    assert model.instance_count == len(model.instances) == 4


def test_every_instance_is_paced_and_bounded():
    model = _model()
    timing = replace(model.timing, realtime=False, stop_time_s=30.0)

    problems = sos_model.check(_manifest(), replace(model, timing=timing))

    assert any("red_striker: --realtime is present but timing.realtime is False" in item for item in problems)
    assert any("red_striker: experiment.stopTime 120.0 != timing.stop_time_s 30.0" in item for item in problems)


def test_every_instance_declares_its_frame_and_placement():
    model = _model()
    blue = _entity(_federation(), "blue_cas")
    scenario = {
        key: value
        for key, value in blue.scenario_values.items()
        if key not in ("initX_km", "initY_km")
    }
    federation = _with_entity(_federation(), "blue_cas", waypoint_frame=None, scenario_values=scenario)

    problems = sos_model._check_frame(_manifest(), model, REPO_ROOT, federation)

    assert any("blue_cas: waypoint_frame None != 'federation'" in item for item in problems)
    assert any("blue_cas: placement is missing" in item for item in problems)


def test_duplicate_placement_is_reported():
    model = _model()
    blue = _entity(_federation(), "blue_baseline")
    scenario = {**blue.scenario_values, "initY_km": 5.0}
    federation = _with_entity(_federation(), "blue_baseline", scenario_values=scenario)

    problems = sos_model._check_frame(_manifest(), model, REPO_ROOT, federation)

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
        flow for flow in model.flows if flow.name != "rpr_broadcast_red_interceptor"
    )

    problems = sos_model.check(_manifest(), replace(model, flows=flows))

    assert any("red_interceptor: telemetry port 5510 feeds no modelled flow" in item for item in problems)


def test_control_is_not_modelled():
    model = _model()

    assert all("control" not in process.ports for process in model.processes)
    resolved, problems = sos_model._flow_contract(
        model, model.flows[0], _manifest(), _federation()
    )
    assert problems == []
    assert resolved.protocol == "udp"
    assert resolved.encoding == "rpr"
    assert resolved.rate_hz == pytest.approx(10.0)
    assert resolved.target == "orchestrator/rpr_in"


def test_marker_ports_are_accepted_without_an_external_flag():
    model = _model()

    assert model.flows[0].protocol is None
    assert model.flows[0].encoding is None
    assert model.flows[0].rate_hz is None
    assert model.process("orchestrator").ports["rpr_in"] == 5505
    assert sos_model.check(_manifest(), model) == []


def test_marker_listener_without_rprPort_is_rejected(tmp_path):
    source = tmp_path / "federation_system.sysml"
    source.write_text(
        MODEL_PATH.read_text(encoding="utf-8").replace(
            '    attribute rprPort : Integer = 5505;\n', ""
        ),
        encoding="utf-8",
    )

    with pytest.raises(sos_model.ModelError, match="rprPort"):
        sos_model.load_model(source)


def test_flow_protocol_is_derived_from_each_source_transport():
    model = _model()
    blue = _entity(_federation(), "blue_cas")
    transport = {**blue.transport_values, "transport": "loopback"}
    federation = _with_entity(_federation(), "blue_cas", transport_values=transport)

    problems = sos_model._check_flows(_manifest(), model, federation)

    assert any(
        "flows.rpr_broadcast_blue_cas.protocol: blue_cas transport 'loopback'" in item
        for item in problems
    )
    assert any("flows: marker sources disagree on protocol" in item for item in problems)


def test_flow_encoding_is_derived_from_the_imported_rpr_contract():
    model = _model()
    flow = model.flows[0]

    drifted = replace(model, rpr_contract="json.v1")
    resolved, problems = sos_model._flow_contract(drifted, flow, _manifest(), _federation())
    assert resolved.encoding is None
    assert any("RprEntity::RprContract.version 'json.v1'" in item for item in problems)

    missing = replace(model, rpr_contract=None)
    _resolved, problems = sos_model._flow_contract(missing, flow, _manifest(), _federation())
    assert any("RprEntity::RprContract.version is missing" in item for item in problems)

    newer = replace(model, rpr_contract="rpr.v3")
    resolved, problems = sos_model._flow_contract(newer, flow, _manifest(), _federation())
    assert problems == []
    assert resolved.encoding == "rpr"


def test_flow_rate_is_derived_from_timing():
    model = _model()
    flow = model.flows[0]

    faster = replace(model, timing=replace(model.timing, step_size_s=0.05))
    resolved, problems = sos_model._flow_contract(faster, flow, _manifest(), _federation())
    assert problems == []
    assert resolved.rate_hz == pytest.approx(20.0)

    stalled = replace(model, timing=replace(model.timing, step_size_s=0.0))
    _resolved, problems = sos_model._flow_contract(stalled, flow, _manifest(), _federation())
    assert any(
        "flows.rpr_broadcast_red_interceptor.rate_hz: Timing.step_size_s 0.0 must be > 0" in item
        for item in problems
    )


def test_four_fan_in_sources_share_one_listener_without_a_collision():
    model = _model()
    manifest = _manifest()
    processes = {process.name: process for process in model.processes}
    instances = sos_model._instances(manifest)
    expected = [instance.name for instance in model.instances]

    assert len(model.flows) == model.instance_count == 4
    covered: list[str] = []
    for flow in model.flows:
        sources, source_problem = sos_model._resolve_reference(
            flow.source, instances, processes
        )
        targets, target_problem = sos_model._resolve_reference(
            flow.target, instances, processes
        )

        assert source_problem is None
        assert target_problem is None
        assert len(sources) == 1
        assert sources[0].scope == "instance"
        covered.append(sources[0].component)
        assert [target.label for target in targets] == ["orchestrator/rpr_in"]

    assert covered == expected
    assert len(set(covered)) == 4
    assert sos_model._check_ports(manifest, model) == []
    assert sos_model._check_flows(manifest, model, _federation()) == []


def test_viewer_replays_the_recorder_truth_stream():
    model = _model()
    viewer = model.process("viewer")
    assert viewer is not None
    command = list(viewer.command)
    command[command.index("--path") + 1] = "build/runs/other/truth.jsonl"

    problems = sos_model.check(
        _manifest(),
        replace(model, processes=tuple(replace(viewer, command=tuple(command)) if item.name == "viewer" else item for item in model.processes)),
    )

    assert any("processes.viewer: --path" in item for item in problems)


def test_identity_set_must_match_the_manifest():
    manifest = _manifest()
    _instance(manifest, "blue_cas")["entities"][0]["marking"] = "RED-9"

    problems = sos_model.check(manifest, _model())

    assert any("blue_cas: entity marking 'BLUE-1' != manifest marking 'RED-9'" in item for item in problems)


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


def test_frame_origin_drift_reaches_the_entity_identity_set():
    model = _model()
    origin = replace(model.frame.origin, latitude_deg=-3.5)

    problems = sos_model.check(
        _manifest(), replace(model, frame=replace(model.frame, origin=origin))
    )

    assert any(
        "blue_cas: identity.reference_latitude_deg -2.957519 != frame.origin.latitude_deg -3.5"
        in item
        for item in problems
    )


def test_transport_bind_must_match_the_telemetry_endpoint():
    manifest = _manifest()
    _instance(manifest, "blue_cas")["telemetry"][0]["port"] = 5599

    problems = sos_model.check(manifest, _model())

    assert any(
        "blue_cas: transport.bind_address 127.0.0.1:5514 != manifest telemetry 127.0.0.1:5599"
        in item
        for item in problems
    )


def test_identity_set_marking_drift_is_reported():
    model = _model()
    blue = _entity(_federation(), "blue_cas")
    identity = {**blue.identity_values, "marking_characters": "WRONG"}
    federation = _with_entity(_federation(), "blue_cas", identity_values=identity)

    problems = sos_model._check_identity(_manifest(), model, REPO_ROOT, federation)

    assert any("blue_cas: entity marking 'WRONG' != manifest marking 'BLUE-1'" in item for item in problems)


def test_variant_must_be_named_in_the_application_command():
    model = _model()
    blue = _entity(_federation(), "blue_cas")
    application = {
        **blue.application_values,
        "command": blue.application_values["command"].replace(" --variant BlueCas", ""),
    }
    federation = _with_entity(_federation(), "blue_cas", application_values=application)

    problems = sos_model._check_identity(_manifest(), model, REPO_ROOT, federation)

    assert any("blue_cas: application command is missing --variant" in item for item in problems)


def test_scenario_name_must_match_the_application():
    manifest = _manifest()
    _instance(manifest, "blue_cas")["env"]["PYSOS_SCENARIO"] = "wrong_scenario"

    problems = sos_model._check_identity(manifest, _model(), REPO_ROOT, _federation())

    assert any(
        "blue_cas: env.PYSOS_SCENARIO 'wrong_scenario' != "
        "application scenario 'cas_multi_store_support'" in item
        for item in problems
    )


def test_missing_scenario_name_is_reported():
    manifest = _manifest()
    del _instance(manifest, "blue_cas")["env"]["PYSOS_SCENARIO"]

    problems = sos_model._check_identity(manifest, _model(), REPO_ROOT, _federation())

    assert any("blue_cas: env.PYSOS_SCENARIO is missing" in item for item in problems)


def test_application_scenario_metadata_is_required():
    model = _model()
    blue = _entity(_federation(), "blue_cas")
    application = {
        key: value for key, value in blue.application_values.items() if key != "scenario"
    }
    federation = _with_entity(_federation(), "blue_cas", application_values=application)

    problems = sos_model._check_identity(_manifest(), model, REPO_ROOT, federation)

    assert any("blue_cas: application scenario is missing" in item for item in problems)


def test_system_plane_is_authored_in_sysml_v2():
    assert MODEL_PATH.suffix == ".sysml"
    text = MODEL_PATH.read_text(encoding="utf-8")
    assert "private import AircraftFederation::*;" in text
    assert "port def RprBroadcast;" not in text
    assert "port def RprListener;" not in text
    assert 'attribute rprPort : Integer = 5505;' in text

    model = _model()
    assert (REPO_ROOT / model.entity_model).is_file()
    assert model.instance_count == len(_manifest()["instances"])
    assert model.process("orchestrator").ports["rpr_in"] == 5505

    resolved, problems = sos_model._flow_contract(
        model, model.flows[0], _manifest(), _federation()
    )
    assert problems == []
    assert resolved.protocol == "udp"
    assert resolved.encoding == "rpr"
    assert resolved.rate_hz == pytest.approx(10.0)
    assert resolved.target == "orchestrator/rpr_in"


def test_entity_plane_composes_the_imported_aircraft():
    model = _model()
    federation = entity_manifest.load_entity_model(REPO_ROOT / model.entity_model)

    assert federation.name == model.federation
    assert model.aircraft.key == "Aircraft::AircraftModel"
    for instance in federation.instances:
        assert instance.aircraft == model.aircraft.key
        assert instance.launch is not None
        assert instance.launch.mode == "supervised"


def test_host_processes_declare_the_shared_launch_vocabulary():
    processes = {process.name: process for process in _model().processes}

    assert processes["orchestrator"].launch.mode == "operator"
    assert processes["orchestrator"].launch.readiness == "port_bound"
    assert processes["orchestrator"].launch.order == 1
    assert processes["orchestrator"].launch.after_process == "builder"
    assert processes["viewer"].launch.mode == "manual"
    assert processes["viewer"].launch.after_process == "recorder"
    assert processes["builder"].launch.readiness == "none"
    assert processes["builder"].launch.order == 0
    assert processes["builder"].launch.after_process == ""

    launch = _model().process("orchestrator").launch
    assert launch.timeout_s == 30.0


def test_entity_launch_drift_is_reported():
    manifest = _manifest()
    instance = _instance(manifest, "red_striker")
    instance["env"]["PYSOS_READINESS"] = "log_line"
    instance["startup_timeout"] = 5.0

    problems = sos_model.check(manifest, _model())

    assert any("red_striker: manifest env.PYSOS_READINESS" in item for item in problems)
    assert any("red_striker: manifest startup_timeout 5.0" in item for item in problems)


def test_launch_dependency_cycle_is_reported():
    model = _model()
    processes = tuple(
        replace(process, launch=replace(process.launch, after_process="viewer"))
        if process.name == "orchestrator"
        else process
        for process in model.processes
    )

    problems = sos_model.check(_manifest(), replace(model, processes=processes))

    assert any("processes.launch: dependency cycle" in item for item in problems)


def test_entity_identity_drift_is_reported():
    manifest = _manifest()
    _instance(manifest, "blue_cas")["entities"][0]["marking"] = "WRONG"

    problems = sos_model.check(manifest, _model())

    assert any("blue_cas: entity marking 'BLUE-1' != manifest marking 'WRONG'" in item for item in problems)


def test_instance_count_must_match_the_manifest():
    model = _model()

    problems = sos_model.check(_manifest(), replace(model, instance_count=2))

    assert any(
        "manifest.instances has 4 entr(ies) but the model declares 2 participant part(s)"
        in item
        for item in problems
    )


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
        replace(component, fmu="Renamed.fmu") if component.name == "rpr_entity" else component
        for component in model.aircraft.components
    )

    problems = sos_model.check(
        _manifest(),
        replace(model, aircraft=replace(model.aircraft, components=components)),
        artifacts=True,
    )

    assert any("rpr_entity" in item and "Renamed.fmu" in item for item in problems)
    assert any("resources/Renamed.fmu is missing" in item for item in problems)


@requires_built_aircraft
def test_aircraft_connection_drift_is_reported():
    model = _model()
    wires = tuple(
        replace(wire, target_port="nowhere") if wire.source == "rpr_state_source" else wire
        for wire in model.aircraft.wires
    )

    problems = sos_model.check(
        _manifest(),
        replace(model, aircraft=replace(model.aircraft, wires=wires)),
        artifacts=True,
    )

    assert any(
        "rpr_state_source.entityState -> rpr_entity.nowhere" in item for item in problems
    )


@requires_built_aircraft
def test_rpr_deployment_defaults_must_match_the_built_scenario():
    model = _model()
    components = tuple(
        replace(
            component,
            parameters={**component.parameters, "transport": ("String", "udp")},
        )
        if component.name == "rpr_entity"
        else component
        for component in model.aircraft.components
    )

    problems = sos_model.check(
        _manifest(),
        replace(model, aircraft=replace(model.aircraft, components=components)),
        artifacts=True,
    )

    assert any("rpr_entity.transport" in item and "loopback" in item for item in problems)


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
    assert len(model.aircraft.components) == 11
    assert len(model.aircraft.wires) == 23
    model_text = MODEL_PATH.read_text(encoding="utf-8")
    assert "part def UdpBridge" not in model_text
    assert "part def Pilot" not in model_text
    assert "ControlInterface" not in model_text
    assert "private import RprEntity::*;" in model_text
    assert "private import AircraftFederation::*;" in model_text
    assert "port def RprBroadcast;" not in model_text
    assert "part def AircraftInstance" not in model_text
    assert "part instances :" not in model_text


def test_missing_reference_origin_is_reported():
    model = _model()
    blue = _entity(_federation(), "blue_cas")
    identity = {
        key: value
        for key, value in blue.identity_values.items()
        if key != "reference_longitude_deg"
    }
    federation = _with_entity(_federation(), "blue_cas", identity_values=identity)

    problems = sos_model._check_frame(_manifest(), model, REPO_ROOT, federation)

    assert any("blue_cas: identity.reference_longitude_deg is missing" in item for item in problems)


@requires_built_aircraft
def test_rpr_identity_and_reference_origin_land_in_the_instance_bundle(tmp_path):
    summary = prepare_instance_bundle.prepare_instance(
        2,
        SCENARIO_SSP,
        tmp_path,
        reference_latitude_deg=-2.957519,
        reference_longitude_deg=39.232955,
        reference_altitude_m=0.0,
        waypoint_frame="federation",
        stop_time=120.0,
        entity_site="1",
        entity_application="1",
        entity="2",
        marking="RED-2",
    )

    with zipfile.ZipFile(summary["ssp"]) as archive:
        ssv = archive.read("resources/MissionScenario.ssv").decode("utf-8")
        ssm = archive.read("resources/HighAltitudeIntercept.ssm").decode("utf-8")

    assert 'name="rpr_entity.bind_address"' in ssv
    assert "127.0.0.1:5512" in ssv
    assert 'name="rpr_entity.peer_address"' in ssv
    assert "127.0.0.1:5505" in ssv
    assert 'name="rpr_state_source.reference_latitude_deg"' in ssv
    assert "-2.957519000" in ssv
    assert 'name="rpr_state_source.reference_longitude_deg"' in ssv
    assert "39.232955000" in ssv
    assert 'name="rpr_state_source.entity_entity"' in ssv
    assert 'name="rpr_state_source.marking_characters"' in ssv
    assert "RED-2" in ssv
    assert 'target="rpr_entity.bind_address"' in ssm
    assert 'target="rpr_state_source.reference_altitude_m"' in ssm
    assert "useBridgeInput" not in ssv
    assert summary["waypoint_frame"] == "federation"
    assert summary["rpr_bind_address"] == "127.0.0.1:5512"
    assert summary["entity"] == "1/1/2"
    assert summary["marking"] == "RED-2"


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


def test_system_plane_must_import_the_entity_plane(tmp_path):
    source = tmp_path / "federation_system.sysml"
    source.write_text(
        MODEL_PATH.read_text(encoding="utf-8").replace(
            "  private import AircraftFederation::*;\n", ""
        ),
        encoding="utf-8",
    )

    with pytest.raises(sos_model.ModelError, match="AircraftFederation::\\*"):
        sos_model.load_model(source)


def test_participant_order_must_match_the_entity_plane(tmp_path):
    text = MODEL_PATH.read_text(encoding="utf-8")
    swapped = text.replace(
        "    part red_interceptor : RedInterceptorParticipant;\n"
        "    part red_striker : RedStrikerParticipant;\n",
        "    part red_striker : RedStrikerParticipant;\n"
        "    part red_interceptor : RedInterceptorParticipant;\n",
    )
    assert swapped != text
    source = tmp_path / "federation_system.sysml"
    source.write_text(swapped, encoding="utf-8")

    with pytest.raises(sos_model.ModelError, match="order is authoritative"):
        sos_model.load_model(source)


def test_participant_must_be_typed_by_its_entity_definition(tmp_path):
    text = MODEL_PATH.read_text(encoding="utf-8")
    mistyped = text.replace(
        "    part blue_cas : BlueCasParticipant;",
        "    part blue_cas : RedInterceptorParticipant;",
    )
    assert mistyped != text
    source = tmp_path / "federation_system.sysml"
    source.write_text(mistyped, encoding="utf-8")

    with pytest.raises(sos_model.ModelError, match="BlueCasParticipant"):
        sos_model.load_model(source)


def test_missing_participant_part_is_rejected(tmp_path):
    text = MODEL_PATH.read_text(encoding="utf-8")
    missing = text.replace("    part blue_baseline : BlueBaselineParticipant;\n", "")
    assert missing != text
    source = tmp_path / "federation_system.sysml"
    source.write_text(missing, encoding="utf-8")

    with pytest.raises(sos_model.ModelError, match="blue_baseline"):
        sos_model.load_model(source)
