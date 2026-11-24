#!/usr/bin/env python3
"""System-of-systems model for the multi-entity flight simulation.

The model is split over two SysML v2 files because no single pyssporg lowering
accepts the whole federation today:

* the **entity plane** is ``sos/aircraft_federation.sysml``, lowered by
  ``pysos_sysml`` to the ``pysos_coordinate`` manifest (schema 1): process
  ``command``/``cwd``/``env``, per-instance UDP endpoints, entity identity and
  the shared ``PysosSoS::LaunchSpec`` contract. The variant parameter sets
  (scenario, identity, transport, experiment) and the application's
  ``waypointFrame`` stay on the entity model, not in the manifest. It imports
  the real ``Aircraft`` architecture, so every ``AircraftEntity`` composes
  ``AircraftModel`` instead of restating it;
* the **system plane** is ``sos/federation_system.sysml``: the shared frame, the
  federation timing contract, the aircraft participants, the host-side
  participants (orchestrator/recorder, viewer, builder), the RPR broadcast flows
  and the run artifacts. This module lowers it from the ``pycps_sysml`` IR,
  which already carries port definitions, port usages, connections and typed
  attribute values. The system plane imports the aircraft architecture (package
  ``Aircraft``), the entity plane (package ``AircraftFederation``) and
  pyfmi_rpr's bundled ``RprEntity`` definition instead of restating them; the
  import targets are named by the ``architecture`` and ``entity_model``
  attributes.

Authority is one-fact-one-place. The system plane never restates instance data:
each participant is a part typed by the entity plane's ``<X>Participant`` def,
in the order ``AircraftFederation::Federation`` declares. This module resolves
those parts against the entity plane and the lowered manifest and reports every
fact that is missing or contradictory, so "the model is complete" is a
checkable claim.

``pysos_sysml`` exposes the variant/application parameter sets on the entity
model while the manifest carries only the runnable command and lowered
endpoints. The checks below read each fact at its owner instead of requiring it
in ``command`` argv. The entity plane's typed facts (aircraft composition,
launch contract, identity, frame, timing and transport) are checked against the
manifest and the system plane here, not duplicated in the manifest.
"""

from __future__ import annotations

import argparse
import ast
import io
import json
import re
import shlex
import sys
import zipfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

import entity_manifest
import pycps_sysml
import pysos_sysml
import pyssp_sysml_definitions

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent

DEFAULT_MODEL = REPO_ROOT / "sos" / "federation_system.sysml"
DEFAULT_MANIFEST = REPO_ROOT / "manifests" / "aircraft_federation.manifest.json"

SCHEMA_VERSION = 1
SYSTEM_DEF = "SystemDescription"
RESERVED_PARTS = ("origin", "timing", "artifacts")
TIMING_POLICIES = frozenset({"wall_clock"})
TIMING_CLASSES = frozenset({"soft_realtime", "hard_realtime", "batch"})
FRAME_MODES = frozenset({"federation"})
WAYPOINT_FRAMES = frozenset({"federation", "local"})
PROTOCOLS = frozenset({"udp", "unix"})
ENCODINGS = frozenset({"json-udp", "dis", "rpr", "none"})
ROLES = frozenset({"supervisor", "recorder", "visualizer", "operator", "builder"})
LAUNCH_MODES = frozenset({"supervised", "operator", "manual"})
LAUNCH_READINESS = frozenset({"none", "port_bound", "socket_bound", "log_line"})
LAUNCH_ATTRIBUTES = {
    "mode": "String",
    "readiness": "String",
    "timeout_s": "Real",
    "order": "Integer",
    "after_process": "String",
}
REQUIRED_ARTIFACTS = ("truth", "measurements", "run")

#: SSP/FMI namespaces and members the artifact check reads by name.
NS_SSD = "http://ssp-standard.org/SSP1/SystemStructureDescription"
NS_SSV = "http://ssp-standard.org/SSP1/SystemStructureParameterValues"
SSD_MEMBER = "SystemStructure.ssd"
FMI_MODEL_DESCRIPTION = "modelDescription.xml"
#: RPR deployment parameters that must survive the build with their modelled defaults.
RPR_DEPLOYMENT_PARAMETERS = ("transport", "bind_address", "peer_address")
#: The aircraft is FMI 2.0 co-simulation only; the architecture declares the FMU
#: source but not the interface, so the checker pins it here.
FMI_VERSION = "2.0"
FMI_INTERFACE = "CoSimulation"

#: Artifact attribute names that differ from the contract key they fill.
ARTIFACT_ALIASES = {"run_json": "run", "instances_dir": "instances", "logs_dir": "logs"}


class ModelError(ValueError):
    """The system-plane model is not usable."""


# --------------------------------------------------------------------------- #
# System-plane model
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class Origin:
    latitude_deg: float
    longitude_deg: float
    altitude_m: float


@dataclass(frozen=True)
class Frame:
    mode: str
    axis_order: str
    origin: Origin
    reference: str
    waypoint_frame: str


@dataclass(frozen=True)
class Timing:
    mode: str
    policy: str
    realtime: bool
    step_size_s: float
    stop_time_s: float
    recording_interval_s: float
    sample_period_s: float
    fanin_watchdog_s: float
    epoch: str
    barrier: str
    overrun_policy: str


@dataclass(frozen=True)
class LaunchSpec:
    mode: str
    readiness: str
    timeout_s: float
    order: int
    after_process: str


@dataclass(frozen=True)
class Process:
    name: str
    roles: tuple[str, ...]
    launch: LaunchSpec
    command: tuple[str, ...]
    cwd: str
    ports: dict[str, int | str | None]
    artifact_keys: tuple[str, ...] = ()


@dataclass(frozen=True)
class Component:
    name: str
    fmu: str
    ports: tuple[str, ...]
    parameter_port: str | None
    parameters: dict[str, tuple[str, Any]]


@dataclass(frozen=True)
class Wire:
    name: str
    source: str
    source_port: str
    target: str
    target_port: str


@dataclass(frozen=True)
class Aircraft:
    system: str
    key: str
    components: tuple[Component, ...]
    wires: tuple[Wire, ...]


@dataclass(frozen=True)
class Flow:
    name: str
    source: str
    target: str
    protocol: str | None
    encoding: str | None
    rate_hz: float | None


@dataclass(frozen=True)
class Artifacts:
    run_dir: str
    files: dict[str, str]


@dataclass(frozen=True)
class Instance:
    """One entity-plane participant occurrence, in declared order."""

    name: str
    participant: str
    order: int


@dataclass(frozen=True)
class SystemModel:
    schema: int
    federation: str
    entity_model: str
    architecture: str
    manifest: str
    frame: Frame
    timing: Timing
    scenarios_dir: str
    source_ssp: str
    aircraft_ssp: str
    scenario_binding: str
    scenario_mapping: str
    instance_count: int
    aircraft: Aircraft
    processes: tuple[Process, ...]
    flows: tuple[Flow, ...]
    artifacts: Artifacts
    #: Entity-plane participants, in ``AircraftFederation::Federation`` order.
    instances: tuple[Instance, ...] = ()
    #: ``RprEntity::RprContract.version`` from the imported wire contract, if
    #: the architecture provides one. Marker flows derive their encoding here.
    rpr_contract: str | None = None

    def process(self, name: str) -> Process | None:
        for candidate in self.processes:
            if candidate.name == name:
                return candidate
        return None


# --------------------------------------------------------------------------- #
# SysML v2 lowering
# --------------------------------------------------------------------------- #


def _resolve_definition(mapping: Mapping[str, Any], name: str, kind: str) -> Any:
    """Resolve a bare or package-qualified definition name.

    Imported packages are keyed ``"Package::Name"`` while the architecture's
    own package keeps bare keys, so every lookup accepts either spelling and
    rejects an ambiguous suffix.
    """

    if name in mapping:
        return mapping[name]
    matches = [key for key in mapping if key.endswith(f"::{name}")]
    if len(matches) == 1:
        return mapping[matches[0]]
    if not matches:
        raise ModelError(f"unknown {kind} {name!r}; declared: {sorted(mapping)}")
    raise ModelError(f"ambiguous {kind} {name!r}; candidates: {sorted(matches)}")


def _part_definition(architecture: Any, name: str) -> Any:
    return _resolve_definition(architecture.part_definitions, name, "part definition")


def _port_definition(architecture: Any, name: str) -> Any:
    return _resolve_definition(architecture.port_definitions, name, "port definition")


def _attribute_definition(architecture: Any, name: str) -> Any:
    return _resolve_definition(architecture.attribute_definitions, name, "attribute definition")


def _optional_attribute_definition(architecture: Any, name: str) -> Any | None:
    """Resolve an attribute definition that a legacy model may not import."""

    matches = [
        key
        for key in architecture.attribute_definitions
        if key == name or key.endswith(f"::{name}")
    ]
    if not matches:
        return None
    if len(matches) > 1:
        raise ModelError(f"ambiguous attribute definition {name!r}; candidates: {sorted(matches)}")
    return architecture.attribute_definitions[matches[0]]


def _rpr_contract(architecture: Any) -> str | None:
    """The imported ``RprEntity::RprContract.version``, or ``None`` if absent."""

    definition = _optional_attribute_definition(architecture, "RprContract")
    if definition is None:
        return None
    return _typed(
        _attributes(definition), "version", "String", f"attribute def {definition.name}"
    )


def _attributes(definition: Any) -> dict[str, tuple[str, Any]]:
    """``{attribute: (declared type, value)}`` for one part definition."""

    return {
        name: (getattr(attribute, "type_name", None), getattr(attribute, "value", None))
        for name, attribute in (definition.attributes or {}).items()
    }


def _typed(
    attributes: Mapping[str, tuple[str, Any]],
    key: str,
    type_name: str,
    where: str,
) -> Any:
    if key not in attributes:
        raise ModelError(f"{where}: missing attribute '{key}'")
    declared, value = attributes[key]
    if declared != type_name:
        raise ModelError(f"{where}.{key}: expected type {type_name}, found {declared!r}")
    expected = {"String": str, "Real": float, "Integer": int, "Boolean": bool}[type_name]
    if expected is not str and not isinstance(value, expected):
        raise ModelError(f"{where}.{key}: expected a {type_name} literal, found {value!r}")
    return value


def _string_list(attributes: Mapping[str, tuple[str, Any]], key: str, where: str) -> tuple[str, ...]:
    raw = _typed(attributes, key, "String", where)
    items = tuple(item.strip() for item in raw.split(",") if item.strip())
    if not items:
        raise ModelError(f"{where}.{key}: expected a comma-separated list of names")
    return items


def _parse_origin(definition: Any) -> Origin:
    attributes = _attributes(definition)
    where = f"part def {definition.name}"
    return Origin(
        latitude_deg=float(_typed(attributes, "latitude_deg", "Real", where)),
        longitude_deg=float(_typed(attributes, "longitude_deg", "Real", where)),
        altitude_m=float(_typed(attributes, "altitude_m", "Real", where)),
    )


def _parse_frame(definition: Any) -> Frame:
    attributes = _attributes(definition)
    where = f"part def {definition.name}"
    frame = Frame(
        mode=_typed(attributes, "mode", "String", where),
        axis_order=_typed(attributes, "axis_order", "String", where),
        origin=_parse_origin(definition),
        reference=_typed(attributes, "reference", "String", where),
        waypoint_frame=_typed(attributes, "waypoint_frame", "String", where),
    )
    if frame.mode not in FRAME_MODES:
        raise ModelError(f"{where}.mode: expected one of {sorted(FRAME_MODES)}")
    if frame.waypoint_frame not in WAYPOINT_FRAMES:
        raise ModelError(f"{where}.waypoint_frame: expected one of {sorted(WAYPOINT_FRAMES)}")
    return frame


def _parse_timing(definition: Any) -> Timing:
    attributes = _attributes(definition)
    where = f"part def {definition.name}"
    timing = Timing(
        mode=_typed(attributes, "realtime_class", "String", where),
        policy=_typed(attributes, "policy", "String", where),
        realtime=_typed(attributes, "realtime", "Boolean", where),
        step_size_s=float(_typed(attributes, "step_size_s", "Real", where)),
        stop_time_s=float(_typed(attributes, "stop_time_s", "Real", where)),
        recording_interval_s=float(_typed(attributes, "recording_interval_s", "Real", where)),
        sample_period_s=float(_typed(attributes, "sample_period_s", "Real", where)),
        fanin_watchdog_s=float(_typed(attributes, "fanin_watchdog_s", "Real", where)),
        epoch=_typed(attributes, "epoch", "String", where),
        barrier=_typed(attributes, "barrier", "String", where),
        overrun_policy=_typed(attributes, "overrun_policy", "String", where),
    )
    if timing.mode not in TIMING_CLASSES:
        raise ModelError(f"{where}.realtime_class: expected one of {sorted(TIMING_CLASSES)}")
    if timing.policy not in TIMING_POLICIES:
        raise ModelError(f"{where}.policy: expected one of {sorted(TIMING_POLICIES)}")
    for name in ("step_size_s", "stop_time_s", "sample_period_s", "fanin_watchdog_s"):
        if getattr(timing, name) <= 0.0:
            raise ModelError(f"{where}.{name}: must be > 0")
    if timing.recording_interval_s < 0.0:
        raise ModelError(f"{where}.recording_interval_s: must be >= 0")
    return timing


def _port_number(architecture: Any, type_name: str, port_name: str, where: str) -> int | None:
    attributes = _attributes(_port_definition(architecture, type_name))
    if "udp_port" not in attributes:
        return None
    number = int(_typed(attributes, "udp_port", "Integer", f"{where}.{port_name}"))
    if not 1 <= number <= 65535:
        raise ModelError(f"{where}.{port_name}.udp_port: port {number} out of range")
    return number


def _port_contract(
    architecture: Any, type_name: str, where: str
) -> tuple[str | None, str | None, float | None]:
    """The authored contract on a port type, or ``None`` for a role marker.

    A marker port def carries no attributes at all. Its facts are owned by the
    entity transport set, ``RprEntity::RprContract``, ``Timing`` and the
    orchestrator; ``_check_flows`` derives them. Explicit attributes keep
    working for legacy models.
    """

    attributes = _attributes(_port_definition(architecture, type_name))
    where = f"port def {type_name}"
    if not attributes:
        return None, None, None
    protocol = _typed(attributes, "protocol", "String", where)
    encoding = _typed(attributes, "encoding", "String", where)
    rate_hz = float(_typed(attributes, "rate_hz", "Real", where))
    if protocol not in PROTOCOLS:
        raise ModelError(f"{where}.protocol: expected one of {sorted(PROTOCOLS)}")
    if encoding not in ENCODINGS:
        raise ModelError(f"{where}.encoding: expected one of {sorted(ENCODINGS)}")
    if rate_hz <= 0.0:
        raise ModelError(f"{where}.rate_hz: must be > 0")
    return protocol, encoding, rate_hz


def _string_literal(value: Any, where: str) -> str:
    if isinstance(value, str):
        try:
            parsed = ast.literal_eval(value)
        except (SyntaxError, ValueError):
            parsed = None
        if isinstance(parsed, str):
            return parsed
    raise ModelError(f"{where}: expected a quoted String literal, found {value!r}")


def _int_literal(value: Any, where: str) -> int:
    if isinstance(value, bool):
        raise ModelError(f"{where}: expected an Integer literal, found {value!r}")
    if isinstance(value, int):
        return value
    if isinstance(value, str) and re.fullmatch(r"[+-]?\d+", value.strip()):
        return int(value.strip())
    raise ModelError(f"{where}: expected an Integer literal, found {value!r}")


def _real_literal(value: Any, where: str) -> float:
    if isinstance(value, bool):
        raise ModelError(f"{where}: expected a Real literal, found {value!r}")
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError:
            pass
    raise ModelError(f"{where}: expected a Real literal, found {value!r}")


def _launch_spec(architecture: Any, definition: Any, where: str) -> LaunchSpec:
    """Lower the nested ``part launch : LaunchSpec`` contract.

    Nested usage-body values reach the IR as authored text, so they are
    normalised here. ``effective_members`` resolves a launch inherited from
    ``PysosSoS::Application`` when the concrete process does not redeclare it.
    """
    members = pycps_sysml.effective_members(architecture, definition)
    usage = members.parts.get("launch")
    if usage is None:
        raise ModelError(f"{where}: missing nested 'part launch : LaunchSpec'")
    launch_def = _part_definition(architecture, usage.type_name)
    if launch_def.name != "LaunchSpec":
        raise ModelError(
            f"{where}.launch: must be typed PysosSoS::LaunchSpec, got {launch_def.name!r}"
        )
    declared = {name: attribute.type_name for name, attribute in launch_def.attributes.items()}
    if declared != LAUNCH_ATTRIBUTES:
        raise ModelError(
            f"part def {launch_def.name}: expected attributes {sorted(LAUNCH_ATTRIBUTES)}, "
            f"found {sorted(declared)}"
        )
    body = usage.body
    if body is None:
        raise ModelError(f"{where}.launch: the launch spec has no attribute body")
    values = {
        name: (attribute.type_name, attribute.value)
        for name, attribute in body.attributes.items()
    }
    if set(values) != set(LAUNCH_ATTRIBUTES):
        raise ModelError(
            f"{where}.launch: expected attributes {sorted(LAUNCH_ATTRIBUTES)}, "
            f"found {sorted(values)}"
        )
    for name, expected in LAUNCH_ATTRIBUTES.items():
        actual, _value = values[name]
        if actual != expected:
            raise ModelError(
                f"{where}.launch.{name}: expected type {expected}, found {actual!r}"
            )
    mode = _string_literal(values["mode"][1], f"{where}.launch.mode")
    readiness = _string_literal(values["readiness"][1], f"{where}.launch.readiness")
    timeout = _real_literal(values["timeout_s"][1], f"{where}.launch.timeout_s")
    order = _int_literal(values["order"][1], f"{where}.launch.order")
    after_process = _string_literal(
        values["after_process"][1], f"{where}.launch.after_process"
    )
    if mode not in LAUNCH_MODES:
        raise ModelError(f"{where}.launch.mode: expected one of {sorted(LAUNCH_MODES)}")
    if readiness not in LAUNCH_READINESS:
        raise ModelError(
            f"{where}.launch.readiness: expected one of {sorted(LAUNCH_READINESS)}"
        )
    if timeout <= 0:
        raise ModelError(f"{where}.launch.timeout_s: must be greater than zero")
    if order < 0:
        raise ModelError(f"{where}.launch.order: must be non-negative")
    return LaunchSpec(
        mode=mode,
        readiness=readiness,
        timeout_s=timeout,
        order=order,
        after_process=after_process,
    )


def _parse_process(architecture: Any, name: str, usage: Any) -> Process:
    definition = _part_definition(architecture, usage.type_name)
    members = pycps_sysml.effective_members(architecture, definition)
    attributes = {
        attribute_name: (attribute.type_name, attribute.value)
        for attribute_name, attribute in members.attributes.items()
    }
    where = f"part {name}"
    roles = _string_list(attributes, "roles", where)
    unknown = sorted(set(roles) - ROLES)
    if unknown:
        raise ModelError(f"{where}.roles: unknown role(s) {unknown}")
    launch = _launch_spec(architecture, definition, where)
    command = tuple(shlex.split(_typed(attributes, "command", "String", where)))
    if not command:
        raise ModelError(f"{where}.command: empty command line")
    ports: dict[str, int | str | None] = {}
    for port_name, port in members.ports.items():
        port_definition = _port_definition(architecture, port.type_name)
        if _attributes(port_definition):
            ports[port_name] = _port_number(architecture, port.type_name, port_name, where)
        elif port_name == "rpr_in":
            # The marker owns no endpoint; the host application does. A UDP
            # listener is an integer port, a unix listener a bare socket path.
            if "rprPort" in attributes:
                number = int(_typed(attributes, "rprPort", "Integer", where))
                if not 1 <= number <= 65535:
                    raise ModelError(f"{where}.rprPort: port {number} out of range")
                ports[port_name] = number
            elif "rprPath" in attributes:
                path = str(_typed(attributes, "rprPath", "String", where))
                if _unix_path(path) is None:
                    raise ModelError(
                        f"{where}.rprPath: expected an absolute socket path or "
                        f"'@abstract-name', found {path!r}"
                    )
                ports[port_name] = path
            else:
                raise ModelError(
                    f"{where}.{port_name}: port def {port.type_name!r} is a marker; "
                    f"declare 'attribute rprPort : Integer' or "
                    f"'attribute rprPath : String' on the process"
                )
        else:
            ports[port_name] = None
    return Process(
        name=name,
        roles=tuple(roles),
        launch=launch,
        command=command,
        cwd=_typed(attributes, "cwd", "String", where),
        ports=ports,
    )


def _parse_artifacts(definition: Any) -> Artifacts:
    attributes = _attributes(definition)
    where = f"part def {definition.name}"
    files: dict[str, str] = {}
    for key in attributes:
        if key == "run_dir":
            continue
        files[ARTIFACT_ALIASES.get(key, key)] = _typed(attributes, key, "String", where)
    return Artifacts(run_dir=_typed(attributes, "run_dir", "String", where), files=files)


def _fmu_source(architecture: Any, definition: Any) -> str:
    """The ``<Name>.fmu`` basename from the component's ``fmu_meta`` attribute."""

    metadata = (definition.attributes or {}).get("fmu_meta")
    if metadata is None:
        raise ModelError(f"part def {definition.name}: missing 'fmu_meta'")
    attribute_def = _attribute_definition(architecture, metadata.type_name)
    source = _attributes(attribute_def).get("source")
    if source is None or not isinstance(source[1], str):
        raise ModelError(f"part def {definition.name}: fmu_meta has no 'source'")
    return Path(source[1]).name


def _is_parameter_interface(port_def: Any) -> bool:
    return any(
        str(base).split("::")[-1] == "ParameterInterface"
        for base in (getattr(port_def, "specializes", ()) or ())
    )


def _specializes(architecture: Any, definition: Any, target_key: str) -> bool:
    """Whether ``definition`` specializes ``target_key``, transitively."""

    pending = [definition]
    seen: set[str] = set()
    while pending:
        current = pending.pop(0)
        key = architecture.stored_key(current)
        if key == target_key:
            return True
        if key in seen:
            continue
        seen.add(key)
        for base in current.specializes or ():
            pending.append(_part_definition(architecture, base))
    return False


def _parse_aircraft(architecture: Any, participants: Sequence[tuple[str, Any]]) -> Aircraft:
    """Lower the imported ``AircraftModel`` and prove every participant composes it."""

    model = _part_definition(architecture, "AircraftModel")
    members = pycps_sysml.effective_members(architecture, model)
    parts = dict(members.parts or {})

    components: list[Component] = []
    for name, part in parts.items():
        definition = _part_definition(architecture, part.type_name)
        parameter_port = None
        parameters: dict[str, tuple[str, Any]] = {}
        for port_name, port in (definition.ports or {}).items():
            port_def = _port_definition(architecture, port.type_name)
            if _is_parameter_interface(port_def):
                parameter_port = port_name
                parameters = _attributes(port_def)
                break
        components.append(
            Component(
                name=name,
                fmu=_fmu_source(architecture, definition),
                ports=tuple((definition.ports or {}).keys()),
                parameter_port=parameter_port,
                parameters=parameters,
            )
        )

    wires: list[Wire] = []
    for connection in (members.connections or {}).values():
        source, target = connection.source_part, connection.destination_part
        if source not in parts or target not in parts:
            continue
        wires.append(
            Wire(
                name=connection.name,
                source=source,
                source_port=connection.source_port,
                target=target,
                target_port=connection.destination_port,
            )
        )
    # Canonical qualified key: the entity plane and the system plane load the
    # aircraft as a different primary/include root, so `stored_key` would drop
    # the package on one side and keep it on the other.
    key = f"{model.package}::{model.name}" if model.package else model.name

    target_key = architecture.stored_key(model)
    for name, participant in participants:
        aircraft_usage = (
            pycps_sysml.effective_members(architecture, participant).parts or {}
        ).get("aircraft")
        if aircraft_usage is None:
            raise ModelError(f"participant {name}: expected a nested 'aircraft' part")
        variant = _part_definition(architecture, aircraft_usage.type_name)
        if not _specializes(architecture, variant, target_key):
            raise ModelError(
                f"participant {name}.aircraft: {architecture.stored_key(variant)!r} does "
                f"not specialize {target_key!r}"
            )

    return Aircraft(
        system=model.name,
        key=key,
        components=tuple(components),
        wires=tuple(wires),
    )


def _parse_flows(
    architecture: Any, system: Any, instance_names: Sequence[str]
) -> tuple[Flow, ...]:
    """Lower one outbound telemetry connection per entity-plane participant."""

    parts = dict(system.parts or {})
    instances = list(instance_names)
    instance_set = set(instances)
    pending = set(instances)
    flows: list[Flow] = []
    for connection in (system.connections or {}).values():
        source_part = connection.source_part
        target_part = connection.destination_part
        if source_part not in parts or target_part not in parts:
            raise ModelError(
                f"connection {connection.name!r}: both endpoints must be parts of {SYSTEM_DEF}"
            )
        if source_part not in instance_set:
            raise ModelError(
                f"connection {connection.name!r}: source {source_part!r} is not an "
                f"entity-plane participant"
            )
        if target_part in instance_set:
            raise ModelError(
                f"connection {connection.name!r}: target {target_part!r} is a participant; "
                f"the listener must be a host process"
            )
        if source_part not in pending:
            raise ModelError(
                f"connection {connection.name!r}: duplicate outbound telemetry for "
                f"participant {source_part!r}"
            )
        source_type = _part_definition(architecture, parts[source_part].type_name)
        source_ports = pycps_sysml.effective_members(architecture, source_type).ports or {}
        if connection.source_port not in source_ports:
            raise ModelError(
                f"connection {connection.name!r}: participant {source_part!r} declares no "
                f"port {connection.source_port!r}"
            )
        source_port = source_ports[connection.source_port]
        target_type = _part_definition(architecture, parts[target_part].type_name)
        target_ports = pycps_sysml.effective_members(architecture, target_type).ports or {}
        if connection.destination_port not in target_ports:
            raise ModelError(
                f"connection {connection.name!r}: {target_part!r} ({target_type.name}) "
                f"declares no port {connection.destination_port!r}"
            )
        protocol, encoding, rate_hz = _port_contract(
            architecture, source_port.type_name, f"connection {connection.name}"
        )
        flows.append(
            Flow(
                name=connection.name,
                source=f"instance/{source_part}/{connection.source_port}",
                target=f"{target_part}/{connection.destination_port}",
                protocol=protocol,
                encoding=encoding,
                rate_hz=rate_hz,
            )
        )
        pending.discard(source_part)
    if not flows:
        raise ModelError(f"{SYSTEM_DEF} declares no connections")
    if pending:
        raise ModelError(
            f"{SYSTEM_DEF}: participant(s) {sorted(pending)} have no outbound telemetry "
            f"connection"
        )
    return tuple(flows)


def parse_architecture(
    architecture: Any, source: Path, entity_federation: Any
) -> SystemModel:
    """Lower a ``pycps_sysml`` architecture to the system-plane model."""

    system = _part_definition(architecture, SYSTEM_DEF)
    attributes = _attributes(system)
    where = f"part def {SYSTEM_DEF}"
    parts = dict(system.parts or {})
    missing = [name for name in RESERVED_PARTS if name not in parts]
    if missing:
        raise ModelError(f"{where}: missing part(s) {missing}")
    fixed = {"origin": "FrameOrigin", "timing": "Timing", "artifacts": "Artifacts"}
    for name, expected in fixed.items():
        if parts[name].type_name != expected:
            raise ModelError(f"{where}.{name}: expected type {expected}, found {parts[name].type_name!r}")

    # The entity plane's Federation is authoritative for participant identity
    # and order. One system-plane part per participant, typed by the same def.
    entity_parts = list(
        (pycps_sysml.effective_members(architecture, entity_federation).parts or {}).items()
    )
    if not entity_parts:
        raise ModelError(f"part def {entity_federation.name}: declares no participants")
    entity_names = [name for name, _usage in entity_parts]
    entity_types: dict[str, str] = {}
    participants: list[tuple[str, Any]] = []
    for name, usage in entity_parts:
        definition = _part_definition(architecture, usage.type_name)
        entity_types[name] = architecture.stored_key(definition)
        participants.append((name, definition))

    for name in entity_names:
        if name not in parts:
            raise ModelError(
                f"{where}: missing participant part {name!r}; the entity plane's "
                f"{entity_federation.name} declares it"
            )

    participant_keys = set(entity_types.values())
    declared_instances: list[str] = []
    for name, usage in parts.items():
        if name in RESERVED_PARTS:
            continue
        if name not in entity_types:
            try:
                definition = _part_definition(architecture, usage.type_name)
            except ModelError:
                continue
            if architecture.stored_key(definition) not in participant_keys:
                continue
        declared_instances.append(name)
    if declared_instances != entity_names:
        raise ModelError(
            f"{where}: participant parts are declared as {declared_instances}; the entity "
            f"plane's {entity_federation.name} declares them as {entity_names} (order is "
            f"authoritative)"
        )

    instances: list[Instance] = []
    for order, (name, usage) in enumerate(entity_parts):
        actual = _part_definition(architecture, parts[name].type_name)
        if architecture.stored_key(actual) != entity_types[name]:
            raise ModelError(
                f"{where}.{name}: typed {architecture.stored_key(actual)!r} but the entity "
                f"plane's {entity_federation.name} declares {entity_types[name]!r}"
            )
        members = pycps_sysml.effective_members(architecture, actual)
        telemetry = (members.ports or {}).get("telemetry")
        if telemetry is None:
            raise ModelError(f"part def {actual.name}: missing port 'telemetry'")
        # Externality is structural: `telemetry` on the participant is the
        # process boundary. Resolve the type so an unknown port def is rejected.
        _port_definition(architecture, telemetry.type_name)
        instances.append(
            Instance(name=name, participant=entity_types[name], order=order)
        )

    processes = tuple(
        _parse_process(architecture, name, usage)
        for name, usage in parts.items()
        if name not in RESERVED_PARTS and name not in entity_types
    )
    flows = _parse_flows(architecture, system, entity_names)
    entity_model = _typed(attributes, "entity_model", "String", where)
    return SystemModel(
        schema=SCHEMA_VERSION,
        federation=_typed(attributes, "federation", "String", where),
        entity_model=entity_model,
        manifest=_typed(attributes, "manifest", "String", where),
        frame=_parse_frame(_part_definition(architecture, parts["origin"].type_name)),
        timing=_parse_timing(_part_definition(architecture, parts["timing"].type_name)),
        scenarios_dir=_typed(attributes, "scenarios_dir", "String", where),
        source_ssp=_typed(attributes, "source_ssp", "String", where),
        aircraft_ssp=_typed(attributes, "aircraft_ssp", "String", where),
        architecture=_typed(attributes, "architecture", "String", where),
        scenario_binding=_typed(attributes, "scenario_binding", "String", where),
        scenario_mapping=_typed(attributes, "scenario_mapping", "String", where),
        instance_count=len(instances),
        aircraft=_parse_aircraft(architecture, participants),
        processes=processes,
        flows=flows,
        artifacts=_parse_artifacts(_part_definition(architecture, parts["artifacts"].type_name)),
        instances=tuple(instances),
        rpr_contract=_rpr_contract(architecture),
    )


def _load_architecture(path: Path) -> Any:
    try:
        return pycps_sysml.load(path)
    except Exception as exc:  # sysmlpy raises its own syntax error type
        raise ModelError(f"{path}: cannot parse SysML v2 model: {exc}") from exc


def load_model(path: Path | str = DEFAULT_MODEL) -> SystemModel:
    """Parse the system plane and merge the architectures it imports."""

    source = Path(path)
    primary = _load_architecture(source)
    attributes = _attributes(_part_definition(primary, SYSTEM_DEF))
    where = f"part def {SYSTEM_DEF}"
    architecture = _typed(attributes, "architecture", "String", where)
    entity_model = _typed(attributes, "entity_model", "String", where)
    imported = REPO_ROOT / architecture
    if not imported.is_file():
        raise ModelError(
            f"architecture {architecture!r} does not exist; the system plane imports it"
        )
    entity_path = REPO_ROOT / entity_model
    if not entity_path.is_file():
        raise ModelError(
            f"entity model {entity_model!r} does not exist; the system plane imports it"
        )
    imported_architecture = _load_architecture(imported)
    entity_architecture = _load_architecture(entity_path)
    # The SoS vocabulary is an included root, not a copy: the system plane
    # imports PysosSoS::* and the checker supplies the shipped definitions. The
    # entity plane imports PysspCore, and the entity file itself is a root so
    # its participant defs and order can be referenced by type.
    includes: list[Path] = [
        imported,
        pysos_sysml.sos_definitions(),
        pyssp_sysml_definitions.core_definitions(),
    ]
    # The aircraft architecture imports the RPR entity dialect. pycps_sysml
    # resolves imports across the roots it is given, so supply the bundled
    # definition as well instead of restating it in the system plane.
    if (
        "RprEntity"
        in set(imported_architecture.imports) | set(primary.imports) | set(entity_architecture.imports)
    ):
        try:
            import pyfmi_rpr
        except ImportError as exc:  # pragma: no cover - depends on the install
            raise ModelError(f"RprEntity is imported but pyfmi_rpr is unavailable: {exc}") from exc
        includes.append(pyfmi_rpr.rpr_entity())
    includes.append(entity_path)
    merged = _load_architecture([*includes, source])
    package = imported_architecture.package_name
    # Check the system plane's own imports: `merged.imports` is architecture
    # wide, and the entity plane imports Aircraft too, so the union would hide
    # a missing import in the file that must name the dependency.
    if package not in primary.imports:
        raise ModelError(
            f"{source}: the architecture declares package {package!r}, but the system plane "
            f"does not import it; add 'private import {package}::*;'"
        )
    entity_package = entity_architecture.package_name
    if entity_package not in primary.imports:
        raise ModelError(
            f"{source}: the entity model declares package {entity_package!r}, but the system "
            f"plane does not import it; add 'private import {entity_package}::*;'"
        )
    entity_federation = _part_definition(merged, f"{entity_package}::Federation")
    return parse_architecture(merged, source, entity_federation)


# --------------------------------------------------------------------------- #
# Manifest resolution
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class Resolved:
    label: str
    component: str
    scope: str
    port: int | str | None


def _as_int_port(value: Any) -> int | None:
    try:
        port = int(value)
    except (TypeError, ValueError):
        return None
    return port if 1 <= port <= 65535 else None


def _instance_ports(instance: Mapping[str, Any]) -> dict[str, int | str]:
    """Declared endpoint addresses: UDP ports as ints, unix paths as strings."""

    ports: dict[str, int | str] = {}
    for name in ("telemetry", "control"):
        endpoints = instance.get(name) or []
        if len(endpoints) != 1 or not isinstance(endpoints[0], Mapping):
            continue
        endpoint = endpoints[0]
        if endpoint.get("transport") == "unix":
            path = _unix_path(endpoint.get("path"))
            if path is not None:
                ports[name] = path
            continue
        port = _as_int_port(endpoint.get("port"))
        if port is not None:
            ports[name] = port
    return ports


def _unix_path(value: Any) -> str | None:
    """A bare unix endpoint: an absolute socket path or ``@abstract-name``."""

    if not isinstance(value, str):
        return None
    text = value.strip()
    if text.startswith("@"):
        return text if len(text) > 1 else None
    return text if text.startswith("/") else None


def _manifest_endpoint_address(endpoint: Any) -> str | None:
    """``host:port`` or a unix path, matching ``Endpoint.address``."""

    if not isinstance(endpoint, Mapping):
        return None
    if endpoint.get("transport") == "unix":
        return _unix_path(endpoint.get("path"))
    host = str(endpoint.get("host") or "")
    port = _as_int_port(endpoint.get("port"))
    if not host or port is None:
        return None
    return f"{host}:{port}"


def _entity_endpoint_address(endpoint: Any) -> str | None:
    """An entity-plane telemetry endpoint's address, UDP or unix."""

    if endpoint is None:
        return None
    if getattr(endpoint, "transport", "udp") == "unix" or getattr(
        endpoint, "path", None
    ) is not None:
        return _unix_path(getattr(endpoint, "path", None))
    host = getattr(endpoint, "host", None)
    port = getattr(endpoint, "port", None)
    if isinstance(port, int) and host:
        return f"{host}:{port}"
    return None


def _instances(manifest: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    return {
        str(instance.get("name")): instance
        for instance in manifest.get("instances") or []
        if isinstance(instance, Mapping)
    }


def _resolve_reference(
    reference: str,
    instances: Mapping[str, Mapping[str, Any]],
    processes: Mapping[str, Process],
) -> tuple[list[Resolved], str | None]:
    """Resolve ``instance/<name>|<*>```/<port>``, ``<process>/<port>``, ``<component>``."""

    parts = reference.split("/")
    if len(parts) == 1:
        name = parts[0]
        process = processes.get(name)
        if process is not None:
            if process.ports:
                return (
                    [
                        Resolved(f"{name}/{port_name}", name, "host", port)
                        for port_name, port in process.ports.items()
                    ],
                    None,
                )
            return [Resolved(name, name, "host", None)], None
        instance = instances.get(name)
        if instance is not None:
            return [
                Resolved(f"instance/{name}/{port_name}", name, "instance", port)
                for port_name, port in _instance_ports(instance).items()
            ], None
        return [], f"{reference!r} names no instance or host process"
    if len(parts) == 2:
        component, port_name = parts
        instance = instances.get(component)
        if instance is not None:
            ports = _instance_ports(instance)
            if port_name in ports:
                return [Resolved(reference, component, "instance", ports[port_name])], None
            return (
                [],
                f"{reference!r}: instance {component!r} declares no {port_name!r} endpoint",
            )
        process = processes.get(component)
        if process is None:
            return [], f"{reference!r} names no host process {component!r}"
        if port_name not in process.ports:
            return [], f"{reference!r}: process {component!r} declares no port {port_name!r}"
        return [Resolved(reference, component, "host", process.ports[port_name])], None
    if len(parts) == 3:
        scope, selector, port_name = parts
        if scope != "instance":
            return [], f"{reference!r}: the instance scope is spelled 'instance/<name>|<*>/<port>'"
        names = list(instances) if selector == "*" else [selector]
        resolved: list[Resolved] = []
        for name in names:
            instance = instances.get(name)
            if instance is None:
                return [], f"{reference!r} names no instance {name!r}"
            ports = _instance_ports(instance)
            if port_name not in ports:
                return [], f"{reference!r}: instance {name!r} declares no {port_name!r} endpoint"
            resolved.append(Resolved(f"instance/{name}/{port_name}", name, "instance", ports[port_name]))
        return resolved, None
    return [], f"{reference!r}: malformed reference"


def _argv(instance: Mapping[str, Any]) -> list[str]:
    command = instance.get("command") or []
    return [str(token) for token in command]


def _flag(argv: Sequence[str], flag: str) -> str | None:
    try:
        index = argv.index(flag)
    except ValueError:
        return None
    if index + 1 >= len(argv):
        return ""
    return argv[index + 1]


def _entity_slug(entity: Mapping[str, Any]) -> str:
    return f"{entity.get('site')}_{entity.get('application')}_{entity.get('entity')}"


def _close(left: float, right: float, tolerance: float = 1e-9) -> bool:
    return abs(left - right) <= tolerance * max(1.0, abs(left), abs(right))


def _integer_ratio(numerator: float, denominator: float) -> int | None:
    if denominator <= 0.0:
        return None
    ratio = numerator / denominator
    rounded = round(ratio)
    return int(rounded) if _close(ratio, float(rounded), 1e-6) else None


# --------------------------------------------------------------------------- #
# Checks
# --------------------------------------------------------------------------- #


def _check_manifest(manifest: Mapping[str, Any], model: SystemModel) -> list[str]:
    problems: list[str] = []
    if not isinstance(manifest, Mapping):
        return ["manifest: expected a JSON object"]
    if manifest.get("name") != model.federation:
        problems.append(
            f"manifest.name {manifest.get('name')!r} != model.federation {model.federation!r}"
        )
    if manifest.get("timing") != model.timing.policy:
        problems.append(
            f"manifest.timing {manifest.get('timing')!r} != model.timing.policy {model.timing.policy!r}"
        )
    listener = _system_listener_address(model)
    if listener is not None:
        # The system plane is the authority for the transport: a unix listener
        # is schema 2, an integer listener is the explicit UDP schema 1.
        expected_schema = 2 if isinstance(listener, str) else 1
        if manifest.get("schema") != expected_schema:
            problems.append(
                f"manifest.schema {manifest.get('schema')!r} != {expected_schema} for "
                f"system listener {listener!r}"
            )
    elif manifest.get("schema") not in (1, 2):
        problems.append(f"manifest.schema {manifest.get('schema')!r} != {SCHEMA_VERSION}")
    instances = manifest.get("instances") or []
    expected_order = [instance.name for instance in model.instances]
    if not instances:
        problems.append("manifest.instances: the federation has no instances")
    else:
        if len(instances) != model.instance_count:
            problems.append(
                f"manifest.instances has {len(instances)} entr(ies) but the model declares "
                f"{model.instance_count} participant part(s)"
            )
        declared_order = [
            str(instance.get("name"))
            for instance in instances
            if isinstance(instance, Mapping)
        ]
        if declared_order != expected_order:
            problems.append(
                f"manifest.instances order {declared_order} != model participant order "
                f"{expected_order}"
            )
    for instance in instances:
        if not isinstance(instance, Mapping):
            problems.append("manifest.instances: expected objects")
            continue
        name = instance.get("name")
        if not instance.get("command"):
            problems.append(f"manifest.instances[{name}]: empty command")
        entities = instance.get("entities") or []
        if len(entities) != 1:
            problems.append(f"{name}: expected exactly one entity, found {len(entities)}")
        telemetry = instance.get("telemetry") or []
        if len(telemetry) != 1:
            problems.append(
                f"{name}: expected exactly one telemetry endpoint, found {len(telemetry)}"
            )
        # Control is retired: the participant plane owns telemetry only and the
        # lowerer emits no control endpoint.
        control = instance.get("control") or []
        if control:
            problems.append(f"{name}: expected no control endpoints, found {len(control)}")
    return problems


def _entity_occurrences(federation: Any | None) -> dict[str, tuple[Any, int, Any]]:
    """Map manifest names to ``(instance, occurrence index, entity)`` pairs."""

    occurrences: dict[str, tuple[Any, int, Any]] = {}
    if federation is None:
        return occurrences
    for instance in federation.instances:
        for index in range(instance.count):
            name = instance.name if instance.count == 1 else f"{instance.name}_{index + 1}"
            occurrences[name] = (instance, index, instance.entities[index])
    return occurrences


def _load_entity_federation(
    model: SystemModel, repo_root: Path
) -> tuple[Any | None, list[str]]:
    path = repo_root / model.entity_model
    if not path.is_file():
        return None, [f"entity model {model.entity_model!r} does not exist"]
    try:
        return entity_manifest.load_entity_model(path), []
    except (OSError, ValueError) as exc:  # SysMLError is a ValueError
        return None, [f"entity model {model.entity_model!r}: {exc}"]


def _host_port(value: Any) -> tuple[str, int] | None:
    host, separator, port_text = str(value).rpartition(":")
    if not separator or not host:
        return None
    try:
        port = int(port_text)
    except ValueError:
        return None
    return (host, port) if 1 <= port <= 65535 else None


def _check_timing(
    manifest: Mapping[str, Any], model: SystemModel, federation: Any | None = None
) -> list[str]:
    problems: list[str] = []
    timing = model.timing
    if _integer_ratio(timing.stop_time_s, timing.step_size_s) is None:
        problems.append(
            f"timing.stop_time_s {timing.stop_time_s} is not a multiple of step_size_s {timing.step_size_s}"
        )
    ratio = _integer_ratio(timing.sample_period_s, timing.step_size_s)
    if ratio is None or ratio < 1:
        problems.append(
            f"timing.sample_period_s {timing.sample_period_s} is not a positive multiple of "
            f"step_size_s {timing.step_size_s}"
        )
    if timing.fanin_watchdog_s <= timing.sample_period_s:
        problems.append("timing.fanin_watchdog_s must exceed timing.sample_period_s")
    occurrences = _entity_occurrences(federation)
    for instance in _instances(manifest).values():
        name = instance.get("name")
        argv = _argv(instance)
        if "--realtime" in argv and not timing.realtime:
            problems.append(
                f"{name}: --realtime is present but timing.realtime is {timing.realtime}"
            )
        occurrence = occurrences.get(str(name))
        if occurrence is None:
            continue
        values = occurrence[0].experiment_values
        for key, declared in (
            ("stopTime", timing.stop_time_s),
            ("stepSize", timing.step_size_s),
        ):
            if key not in values:
                continue
            try:
                value = float(values[key])
            except (TypeError, ValueError):
                problems.append(
                    f"{name}: experiment.{key} {values[key]!r} is not a number"
                )
                continue
            if not _close(value, declared):
                problems.append(
                    f"{name}: experiment.{key} {value} != timing."
                    f"{'stop_time_s' if key == 'stopTime' else 'step_size_s'} {declared}"
                )
    return problems


def _frame_reference(model: SystemModel, repo_root: Path) -> tuple[Path | None, int]:
    reference = model.frame.reference
    path_text, _, selector = reference.partition("#")
    index_text = selector.removeprefix("points[") if selector.startswith("points[") else ""
    index = int(index_text.rstrip("]")) if index_text.rstrip("]").isdigit() else 0
    path = repo_root / path_text
    return (path if path.is_file() else None), index


def _check_frame(
    manifest: Mapping[str, Any],
    model: SystemModel,
    repo_root: Path,
    federation: Any | None = None,
) -> list[str]:
    problems: list[str] = []
    origin = model.frame.origin
    if not -90.0 <= origin.latitude_deg <= 90.0:
        problems.append(f"frame.origin.latitude_deg {origin.latitude_deg} is out of range")
    if not -180.0 <= origin.longitude_deg <= 180.0:
        problems.append(f"frame.origin.longitude_deg {origin.longitude_deg} is out of range")
    if not -500.0 <= origin.altitude_m <= 25000.0:
        problems.append(f"frame.origin.altitude_m {origin.altitude_m} is implausible")

    scenario_path, point_index = _frame_reference(model, repo_root)
    if scenario_path is None:
        problems.append(f"frame.reference {model.frame.reference!r}: file does not exist")
    else:
        data = json.loads(scenario_path.read_text(encoding="utf-8"))
        points = data.get("points") or []
        if point_index >= len(points):
            problems.append(
                f"frame.reference {model.frame.reference!r}: scenario has {len(points)} point(s)"
            )
        else:
            point = points[point_index]
            for key, declared in (
                ("latitude_deg", origin.latitude_deg),
                ("longitude_deg", origin.longitude_deg),
                ("altitude_m", origin.altitude_m),
            ):
                if not _close(float(point.get(key, 0.0)), declared, 1e-6):
                    problems.append(
                        f"frame.origin.{key} {declared} != {scenario_path.name} points[{point_index}].{key}"
                    )

    expected_placements = {
        "red_interceptor": (0.0, 0.0),
        "red_striker": (0.0, 5.0),
        "blue_cas": (0.0, 10.0),
        "blue_baseline": (0.0, 15.0),
    }
    placements: dict[tuple[float, float], str] = {}
    for name, (instance, _index, _entity) in _entity_occurrences(federation).items():
        if instance.waypoint_frame != "federation":
            problems.append(
                f"{name}: waypoint_frame {instance.waypoint_frame!r} != 'federation'"
            )
        elif instance.waypoint_frame != model.frame.waypoint_frame:
            problems.append(
                f"{name}: waypoint_frame {instance.waypoint_frame!r} != "
                f"{model.frame.waypoint_frame!r}"
            )
        for key, identity_key in (
            ("latitude_deg", "reference_latitude_deg"),
            ("longitude_deg", "reference_longitude_deg"),
            ("altitude_m", "reference_altitude_m"),
        ):
            declared = getattr(origin, key)
            if identity_key not in instance.identity_values:
                problems.append(
                    f"{name}: identity.{identity_key} is missing; the wire origin does not "
                    f"match the federation frame"
                )
                continue
            try:
                value = float(instance.identity_values[identity_key])
            except (TypeError, ValueError):
                problems.append(
                    f"{name}: identity.{identity_key} {instance.identity_values[identity_key]!r} "
                    f"is not a number"
                )
                continue
            if not _close(value, declared, 1e-9):
                problems.append(
                    f"{name}: identity.{identity_key} {value} != frame.origin.{key} {declared}"
                )
        scenario = instance.scenario_values
        if "initX_km" not in scenario or "initY_km" not in scenario:
            problems.append(f"{name}: placement is missing; scenario initX_km/initY_km are absent")
            continue
        try:
            placement = (round(float(scenario["initX_km"]), 6), round(float(scenario["initY_km"]), 6))
        except (TypeError, ValueError):
            problems.append(f"{name}: placement is not numeric")
            continue
        expected = expected_placements.get(name)
        if expected is not None and placement != expected:
            problems.append(f"{name}: placement {placement} != expected {expected}")
        if placement in placements:
            problems.append(
                f"{name}: placement {placement} collides with {placements[placement]}"
            )
        placements[placement] = name
    return problems


def _check_identity(
    manifest: Mapping[str, Any],
    model: SystemModel,
    repo_root: Path,
    federation: Any | None = None,
) -> list[str]:
    problems: list[str] = []
    occurrences = _entity_occurrences(federation)
    slugs: dict[str, str] = {}
    markings: dict[str, str] = {}
    for name, instance in _instances(manifest).items():
        declared = (instance.get("entities") or [{}])[0]
        slug = _entity_slug(declared)
        if slug in slugs:
            problems.append(f"{name}: entity {slug} already used by {slugs[slug]}")
        slugs[slug] = name
        marking = str(declared.get("marking") or "")
        if marking:
            if marking in markings:
                problems.append(f"{name}: marking {marking!r} already used by {markings[marking]}")
            markings[marking] = name
        else:
            problems.append(f"{name}: entity has no marking")
        occurrence = occurrences.get(name)
        if occurrence is not None:
            identity = occurrence[0].identity_values
            for key, identity_key in (
                ("site", "entity_site"),
                ("application", "entity_application"),
                ("entity", "entity_entity"),
                ("marking", "marking_characters"),
            ):
                if identity_key not in identity:
                    problems.append(
                        f"{name}: identity.{identity_key} is missing; the RPR identity is not wired"
                    )
                    continue
                actual = str(identity[identity_key])
                expected = str(declared.get(key) or "")
                if actual != expected:
                    problems.append(
                        f"{name}: entity {key} {actual!r} != manifest {key} {expected!r}"
                    )
            tokens: list[str] = []
            try:
                tokens = shlex.split(
                    str(occurrence[0].application_values.get("command") or "")
                )
            except ValueError:
                problems.append(
                    f"{name}: application command is not a valid command line"
                )
            variant = tokens[tokens.index("--variant") + 1] if "--variant" in tokens[:-1] else ""
            if "--variant" not in tokens:
                problems.append(
                    f"{name}: application command is missing --variant; the runnable variant "
                    f"is not named"
                )
            elif not variant:
                problems.append(f"{name}: application --variant is empty")
        env = instance.get("env") or {}
        telemetry = instance.get("telemetry") or []
        unix_endpoint = (
            len(telemetry) == 1
            and isinstance(telemetry[0], Mapping)
            and telemetry[0].get("transport") == "unix"
        )
        if unix_endpoint:
            if env.get("PYSOS_TRANSPORT") != "unix":
                problems.append(
                    f"{name}: env.PYSOS_TRANSPORT {env.get('PYSOS_TRANSPORT')!r} != "
                    f"'unix' for a unix telemetry endpoint"
                )
            expected_path = str(telemetry[0].get("path") or "")
            if "PYSOS_TELEMETRY_PATH" not in env:
                problems.append(f"{name}: env.PYSOS_TELEMETRY_PATH is missing")
            elif str(env.get("PYSOS_TELEMETRY_PATH")) != expected_path:
                problems.append(
                    f"{name}: env.PYSOS_TELEMETRY_PATH "
                    f"{env.get('PYSOS_TELEMETRY_PATH')!r} != manifest telemetry path "
                    f"{expected_path!r}"
                )
            control = instance.get("control") or []
            control_unix = (
                len(control) == 1
                and isinstance(control[0], Mapping)
                and control[0].get("transport") == "unix"
            )
            if control_unix:
                expected_control = str(control[0].get("path") or "")
                if "PYSOS_CONTROL_PATH" not in env:
                    problems.append(f"{name}: env.PYSOS_CONTROL_PATH is missing")
                elif str(env.get("PYSOS_CONTROL_PATH")) != expected_control:
                    problems.append(
                        f"{name}: env.PYSOS_CONTROL_PATH "
                        f"{env.get('PYSOS_CONTROL_PATH')!r} != manifest control path "
                        f"{expected_control!r}"
                    )
            elif "PYSOS_CONTROL_PATH" in env:
                problems.append(
                    f"{name}: env.PYSOS_CONTROL_PATH is set but the manifest has no "
                    f"unix control endpoint"
                )
        else:
            if "PYSOS_TELEMETRY_PORT" not in env:
                problems.append(f"{name}: env.PYSOS_TELEMETRY_PORT is missing")
            if (
                telemetry
                and isinstance(telemetry[0], Mapping)
                and str(env.get("PYSOS_TELEMETRY_PORT")) != str(telemetry[0].get("port"))
            ):
                problems.append(
                    f"{name}: env.PYSOS_TELEMETRY_PORT {env.get('PYSOS_TELEMETRY_PORT')!r} != "
                    f"manifest telemetry port {telemetry[0].get('port')!r}"
                )
        if "PYSOS_SCENARIO" not in env:
            problems.append(
                f"{name}: env.PYSOS_SCENARIO is missing; the scenario name is "
                f"application metadata"
            )
        elif occurrence is not None:
            declared_scenario = occurrence[0].application_values.get("scenario")
            if declared_scenario is None:
                problems.append(
                    f"{name}: application scenario is missing; the descriptive "
                    f"scenario name is not authored"
                )
            elif str(env["PYSOS_SCENARIO"]) != str(declared_scenario):
                problems.append(
                    f"{name}: env.PYSOS_SCENARIO {env['PYSOS_SCENARIO']!r} != "
                    f"application scenario {declared_scenario!r}"
                )
    return problems


def _system_listener_address(model: SystemModel) -> int | str | None:
    for process in model.processes:
        if "rpr_in" in process.ports:
            return process.ports["rpr_in"]
    return None


def _check_entity_model(
    manifest: Mapping[str, Any], model: SystemModel, federation: Any | None
) -> list[str]:
    """Prove the entity plane composes the same aircraft and agrees with the manifest."""
    problems: list[str] = []
    if federation is None:
        return problems
    if federation.name != model.federation:
        problems.append(
            f"entity model {model.entity_model!r}: package {federation.name!r} "
            f"!= federation {model.federation!r}"
        )

    for instance in federation.instances:
        if instance.aircraft != model.aircraft.key:
            problems.append(
                f"entity {instance.name}: aircraft {instance.aircraft!r} != "
                f"system-plane {model.aircraft.key!r}; the entity plane must compose the imported model"
            )
        if instance.launch is None:
            problems.append(f"entity {instance.name}: missing LaunchSpec")

    occurrences = _entity_occurrences(federation)
    instances = _instances(manifest)
    entity_order = list(occurrences)
    system_order = [instance.name for instance in model.instances]
    if entity_order != system_order:
        problems.append(
            f"entity model {model.entity_model!r}: participant order {entity_order} != "
            f"system-plane participant order {system_order}"
        )
    manifest_order = list(instances)
    if entity_order != manifest_order:
        problems.append(
            f"entity model {model.entity_model!r}: participant order {entity_order} != "
            f"manifest instance order {manifest_order}"
        )
    for name in sorted(set(occurrences) - set(instances)):
        problems.append(f"entity {name}: declared but absent from the manifest")
    listener = _system_listener_address(model)
    for name, instance in instances.items():
        if name not in occurrences:
            problems.append(f"{name}: manifest instance has no entity-plane declaration")
            continue
        entity_instance, index, _entity = occurrences[name]
        declared = (instance.get("entities") or [{}])[0]
        identity = entity_instance.identity_values
        for key, identity_key in (
            ("site", "entity_site"),
            ("application", "entity_application"),
            ("entity", "entity_entity"),
            ("marking", "marking_characters"),
        ):
            if identity_key not in identity:
                problems.append(
                    f"{name}: identity.{identity_key} is missing; the RPR identity is not wired"
                )
                continue
            actual = str(identity[identity_key])
            expected = str(declared.get(key) or "")
            if actual != expected:
                problems.append(
                    f"{name}: entity {key} {actual!r} != manifest {key} {expected!r}"
                )

        entity_endpoint = (
            entity_instance.telemetry_ports[index]
            if index < len(entity_instance.telemetry_ports)
            else None
        )
        if len(entity_instance.telemetry_ports) != entity_instance.count:
            problems.append(
                f"{name}: entity plane declares {len(entity_instance.telemetry_ports)} "
                f"telemetry endpoint(s) for {entity_instance.count} occurrence(s); expected one each"
            )
        if entity_endpoint is None:
            problems.append(f"{name}: entity plane declares no telemetry endpoint")
        transport = entity_instance.transport_values
        transport_name = transport.get("transport")
        unix = transport_name == "unix"
        if transport_name not in ("udp", "unix"):
            problems.append(
                f"{name}: transport {transport_name!r} is not 'udp' or 'unix'"
            )
        if entity_instance.control_ports and not unix:
            problems.append(
                f"{name}: entity plane declares {len(entity_instance.control_ports)} "
                f"control endpoint(s); expected none"
            )
        entity_address = _entity_endpoint_address(entity_endpoint)
        telemetry = instance.get("telemetry") or []
        manifest_address = (
            _manifest_endpoint_address(telemetry[0])
            if len(telemetry) == 1
            else None
        )
        if "bind_address" not in transport:
            problems.append(f"{name}: transport.bind_address is missing; the RPR bind is not wired")
        elif unix:
            bind_path = _unix_path(transport["bind_address"])
            if bind_path is None:
                problems.append(
                    f"{name}: transport.bind_address {transport['bind_address']!r} is not "
                    f"an absolute socket path or '@abstract-name'"
                )
            else:
                if entity_address is not None and entity_address != bind_path:
                    problems.append(
                        f"{name}: transport.bind_address {bind_path} != "
                        f"entity telemetry {entity_address}"
                    )
                if manifest_address is not None and manifest_address != bind_path:
                    problems.append(
                        f"{name}: transport.bind_address {bind_path} != "
                        f"manifest telemetry {manifest_address}"
                    )
        else:
            bind = _host_port(transport["bind_address"])
            if bind is None:
                problems.append(
                    f"{name}: transport.bind_address {transport['bind_address']!r} is not "
                    f"'host:port'"
                )
            else:
                if entity_endpoint is not None and bind != (
                    entity_endpoint.host,
                    entity_endpoint.port,
                ):
                    problems.append(
                        f"{name}: transport.bind_address {bind[0]}:{bind[1]} != "
                        f"entity telemetry {entity_endpoint.host}:{entity_endpoint.port}"
                    )
                if len(telemetry) == 1 and isinstance(telemetry[0], Mapping):
                    endpoint_host = str(telemetry[0].get("host") or "")
                    endpoint_port = _as_int_port(telemetry[0].get("port"))
                    if (endpoint_host, endpoint_port) != bind:
                        problems.append(
                            f"{name}: transport.bind_address {bind[0]}:{bind[1]} != "
                            f"manifest telemetry {endpoint_host}:{endpoint_port}"
                        )
        if "peer_address" not in transport:
            problems.append(
                f"{name}: transport.peer_address is missing; the listener is not wired"
            )
        elif unix:
            peer_path = _unix_path(transport["peer_address"])
            if peer_path is None:
                problems.append(
                    f"{name}: transport.peer_address {transport['peer_address']!r} is not "
                    f"an absolute socket path or '@abstract-name'"
                )
            else:
                if listener is None:
                    problems.append(
                        f"{name}: transport.peer_address {peer_path} names no system "
                        f"listener address (rpr_in)"
                    )
                elif str(listener) != peer_path:
                    problems.append(
                        f"{name}: transport.peer_address {peer_path} != system listener "
                        f"address {listener}"
                    )
                if entity_instance.control_ports and index < len(entity_instance.control_ports):
                    control_address = _entity_endpoint_address(
                        entity_instance.control_ports[index]
                    )
                    if control_address is not None and control_address != peer_path:
                        problems.append(
                            f"{name}: transport.peer_address {peer_path} != "
                            f"entity control {control_address}"
                        )
                control = instance.get("control") or []
                if len(control) == 1:
                    control_address = _manifest_endpoint_address(control[0])
                    if control_address is not None and control_address != peer_path:
                        problems.append(
                            f"{name}: transport.peer_address {peer_path} != "
                            f"manifest control {control_address}"
                        )
        else:
            peer = _host_port(transport["peer_address"])
            if peer is None:
                problems.append(
                    f"{name}: transport.peer_address {transport['peer_address']!r} is not "
                    f"'host:port'"
                )
            elif listener is None:
                problems.append(
                    f"{name}: transport.peer_address {peer[0]}:{peer[1]} names no system "
                    f"listener port (rpr_in)"
                )
            elif peer[1] != listener:
                problems.append(
                    f"{name}: transport.peer_address port {peer[1]} != system listener port "
                    f"{listener}"
                )

        env = instance.get("env") or {}
        launch = entity_instance.launch
        if launch is None:
            continue
        if launch.mode != "supervised":
            problems.append(
                f"{name}: launch mode {launch.mode!r}; the coordinator starts entity processes"
            )
        if env.get("PYSOS_LAUNCH_MODE") != launch.mode:
            problems.append(
                f"{name}: manifest env.PYSOS_LAUNCH_MODE does not match the entity LaunchSpec"
            )
        if env.get("PYSOS_READINESS") != launch.readiness:
            problems.append(
                f"{name}: manifest env.PYSOS_READINESS does not match the entity LaunchSpec"
            )
        if env.get("PYSOS_LAUNCH_ORDER") != str(launch.order):
            problems.append(
                f"{name}: manifest env.PYSOS_LAUNCH_ORDER does not match the entity LaunchSpec"
            )
        if env.get("PYSOS_AFTER_PROCESS") != launch.after_process:
            problems.append(
                f"{name}: manifest env.PYSOS_AFTER_PROCESS does not match the entity LaunchSpec"
            )
        if instance.get("startup_timeout") != launch.timeout_s:
            problems.append(
                f"{name}: manifest startup_timeout {instance.get('startup_timeout')!r} "
                f"!= entity LaunchSpec {launch.timeout_s!r}"
            )
        if launch.after_process:
            target = _launch_target(model, launch.after_process)
            if target is None:
                problems.append(
                    f"{name}: entity launch.after_process {launch.after_process!r} names "
                    f"no host process or a non-unique role"
                )
            elif "supervisor" not in target.roles:
                problems.append(
                    f"{name}: entity launch.after_process resolves to {target.name!r}, "
                    f"which is not the supervisor"
                )
            elif launch.order < target.launch.order:
                problems.append(
                    f"{name}: entity launch.order {launch.order} < supervisor order "
                    f"{target.launch.order}"
                )
        else:
            problems.append(
                f"{name}: entity LaunchSpec must name the supervisor in after_process"
            )
    return problems


def _check_ports(manifest: Mapping[str, Any], model: SystemModel) -> list[str]:
    problems: list[str] = []
    owners: dict[int | str, str] = {}

    def claim(address: int | str, label: str) -> None:
        if address in owners:
            kind = "address" if isinstance(address, str) else "port"
            rendered = repr(address) if isinstance(address, str) else address
            problems.append(f"{kind} {rendered} declared by both {owners[address]} and {label}")
        owners[address] = label

    for name, instance in _instances(manifest).items():
        for endpoint_name, address in _instance_ports(instance).items():
            claim(address, f"{name}.{endpoint_name}")
    for process in model.processes:
        for port_name, address in process.ports.items():
            if address is None:
                continue
            claim(address, f"{process.name}.{port_name}")
    return problems


def _flow_contract(
    model: SystemModel,
    flow: Flow,
    manifest: Mapping[str, Any],
    federation: Any | None,
) -> tuple[Flow, list[str]]:
    """Fill a marker flow's contract from its real owners.

    A flow whose source port def is a marker carries no authored contract.
    Transport comes from each source instance's entity-plane transport set,
    the wire version from the imported ``RprEntity::RprContract``, cadence from
    ``Timing``, and the listener from the orchestrator. Problems are reported
    here; a legacy flow with explicit attributes is returned untouched.
    """

    if flow.protocol is not None or flow.encoding is not None or flow.rate_hz is not None:
        return flow, []

    problems: list[str] = []
    instances = _instances(manifest)
    processes = {process.name: process for process in model.processes}
    occurrences = _entity_occurrences(federation)
    sources, _source_problem = _resolve_reference(flow.source, instances, processes)

    protocols: dict[str, str] = {}
    for source in sources:
        if source.scope != "instance":
            problems.append(
                f"flows.{flow.name}.protocol: source {source.label!r} is not an instance"
            )
            continue
        occurrence = occurrences.get(source.component)
        if occurrence is None:
            problems.append(
                f"flows.{flow.name}.protocol: instance {source.component!r} has no "
                f"entity-plane transport"
            )
            continue
        transport = occurrence[0].transport_values
        if "transport" not in transport:
            problems.append(
                f"flows.{flow.name}.protocol: {source.component}.transport is missing"
            )
        else:
            protocols[source.component] = str(transport["transport"])

        bind = transport.get("bind_address")
        source_unix = transport.get("transport") == "unix"
        if bind is None:
            problems.append(
                f"flows.{flow.name}.{source.component}: transport.bind_address is missing"
            )
        else:
            telemetry = instances.get(source.component, {}).get("telemetry") or []
            manifest_address = (
                _manifest_endpoint_address(telemetry[0])
                if len(telemetry) == 1
                else None
            )
            if source_unix:
                endpoint = _unix_path(bind)
                if endpoint is None:
                    problems.append(
                        f"flows.{flow.name}.{source.component}: transport.bind_address "
                        f"{bind!r} is not an absolute socket path or '@abstract-name'"
                    )
                elif endpoint != manifest_address:
                    problems.append(
                        f"flows.{flow.name}.{source.component}: transport.bind_address "
                        f"{endpoint} != manifest telemetry {manifest_address}"
                    )
            else:
                endpoint = _host_port(bind)
                manifest_endpoint = None
                if len(telemetry) == 1 and isinstance(telemetry[0], Mapping):
                    manifest_endpoint = (
                        str(telemetry[0].get("host") or ""),
                        _as_int_port(telemetry[0].get("port")),
                    )
                if endpoint is None:
                    problems.append(
                        f"flows.{flow.name}.{source.component}: transport.bind_address "
                        f"{bind!r} is not 'host:port'"
                    )
                elif endpoint != manifest_endpoint:
                    problems.append(
                        f"flows.{flow.name}.{source.component}: transport.bind_address "
                        f"{endpoint[0]}:{endpoint[1]} != manifest telemetry "
                        f"{manifest_endpoint[0] if manifest_endpoint else None}:"
                        f"{manifest_endpoint[1] if manifest_endpoint else None}"
                    )

    for name, protocol in sorted(protocols.items()):
        if protocol not in PROTOCOLS:
            problems.append(
                f"flows.{flow.name}.protocol: {name} transport {protocol!r} is not one of "
                f"{sorted(PROTOCOLS)}"
            )
    values = set(protocols.values())
    if len(values) > 1:
        problems.append(f"flows.{flow.name}.protocol: sources disagree: {sorted(values)}")
    protocol = next(iter(values)) if len(values) == 1 else None

    step = model.timing.step_size_s
    if step <= 0.0:
        problems.append(
            f"flows.{flow.name}.rate_hz: Timing.step_size_s {step} must be > 0"
        )
        rate_hz = None
    else:
        rate_hz = 1.0 / step

    version = model.rpr_contract
    if not version:
        problems.append(
            f"flows.{flow.name}.encoding: RprEntity::RprContract.version is missing; "
            f"the wire version is not imported"
        )
        encoding = None
    elif not re.fullmatch(r"rpr\..+", version):
        problems.append(
            f"flows.{flow.name}.encoding: RprEntity::RprContract.version {version!r} "
            f"is not an 'rpr.*' version"
        )
        encoding = None
    else:
        encoding = "rpr"

    targets, _target_problem = _resolve_reference(flow.target, instances, processes)
    orchestrator = processes.get("orchestrator")
    declared = orchestrator.ports.get("rpr_in") if orchestrator is not None else None
    if len(targets) == 1:
        target = targets[0]
        if target.label != "orchestrator/rpr_in":
            problems.append(
                f"flows.{flow.name}.to: marker flow must target orchestrator/rpr_in, "
                f"found {target.label!r}"
            )
        elif target.port is None or declared is None or target.port != declared:
            problems.append(
                f"flows.{flow.name}.to: target address {target.port} != "
                f"Orchestrator.rpr_in {declared}"
            )
    elif targets:
        problems.append(
            f"flows.{flow.name}.to: marker flow must target one listener, found "
            f"{[item.label for item in targets]}"
        )

    return replace(flow, protocol=protocol, encoding=encoding, rate_hz=rate_hz), problems


def _check_flows(
    manifest: Mapping[str, Any], model: SystemModel, federation: Any | None = None
) -> list[str]:
    problems: list[str] = []
    instances = _instances(manifest)
    processes = {process.name: process for process in model.processes}
    names = [flow.name for flow in model.flows]
    duplicates = sorted({name for name in names if names.count(name) > 1})
    if duplicates:
        problems.append(f"flows: duplicate name(s) {duplicates}")

    covered_sources: set[str] = set()
    covered_targets: set[str] = set()
    marker_protocols: dict[str, str] = {}
    for flow in model.flows:
        resolved, contract_problems = _flow_contract(model, flow, manifest, federation)
        problems += contract_problems
        if resolved.protocol is not None and resolved.protocol not in PROTOCOLS:
            problems.append(f"flows.{flow.name}.protocol: expected one of {sorted(PROTOCOLS)}")
        if resolved.encoding is not None and resolved.encoding not in ENCODINGS:
            problems.append(f"flows.{flow.name}.encoding: expected one of {sorted(ENCODINGS)}")
        if resolved.rate_hz is not None and resolved.rate_hz <= 0.0:
            problems.append(f"flows.{flow.name}.rate_hz: must be > 0")
        if (
            flow.protocol is None
            and flow.encoding is None
            and flow.rate_hz is None
            and resolved.protocol is not None
        ):
            marker_protocols[flow.name] = resolved.protocol
        sources, source_problem = _resolve_reference(flow.source, instances, processes)
        if source_problem:
            problems.append(f"flows.{flow.name}.from: {source_problem}")
        targets, target_problem = _resolve_reference(flow.target, instances, processes)
        if target_problem:
            problems.append(f"flows.{flow.name}.to: {target_problem}")
        covered_sources.update(item.label for item in sources)
        covered_targets.update(item.label for item in targets)

    # Each marker flow now has one source, so protocol agreement is checked
    # across the whole fan-in, not inside a single flow's source list.
    marker_values = set(marker_protocols.values())
    if len(marker_values) > 1:
        problems.append(f"flows: marker sources disagree on protocol: {sorted(marker_values)}")

    for name, instance in instances.items():
        for endpoint_name, port in _instance_ports(instance).items():
            if endpoint_name != "telemetry":
                continue
            label = f"instance/{name}/{endpoint_name}"
            if label not in covered_sources:
                problems.append(f"{name}: telemetry port {port} feeds no modelled flow")
    return problems


def _check_processes(manifest: Mapping[str, Any], model: SystemModel) -> list[str]:
    problems: list[str] = []
    instances = _instances(manifest)
    for process in model.processes:
        for name in instances:
            if process.name == name:
                problems.append(f"processes.{process.name}: name collides with an instance")
        argv = list(process.command)
        manifest_flags = [argv[i + 1] for i, token in enumerate(argv[:-1]) if token == "--manifest"]
        for value in manifest_flags:
            if value != model.manifest:
                problems.append(
                    f"processes.{process.name}: --manifest {value!r} != model.manifest {model.manifest!r}"
                )
        if "supervisor" in process.roles and "--manifest" not in argv:
            problems.append(
                f"processes.{process.name}: a supervisor must name the manifest it launches"
            )
        run_dir = _flag(argv, "--run-dir")
        if run_dir is not None and run_dir != model.artifacts.run_dir:
            problems.append(
                f"processes.{process.name}: --run-dir {run_dir!r} != artifacts.run_dir "
                f"{model.artifacts.run_dir!r}"
            )
        scenario = _flag(argv, "--scenario")
        if scenario is not None:
            declared = model.frame.reference.partition("#")[0]
            if scenario != declared:
                problems.append(
                    f"processes.{process.name}: --scenario {scenario!r} != frame.reference "
                    f"{declared!r}; the viewer/recorder origin would not match the federation frame"
                )
        if "visualizer" in process.roles:
            if "--telemetry" in argv:
                problems.append(
                    f"processes.{process.name}: --telemetry is retired; the viewer replays the "
                    f"recorder truth stream"
                )
            source = _flag(argv, "--source")
            if source != "jsonl":
                problems.append(
                    f"processes.{process.name}: --source {source!r} != 'jsonl'; the viewer replays "
                    f"the recorder truth stream"
                )
            expected = str(
                Path(model.artifacts.run_dir) / model.artifacts.files.get("truth", "truth.jsonl")
            )
            path = _flag(argv, "--path")
            if path != expected:
                problems.append(
                    f"processes.{process.name}: --path {path!r} != recorder truth {expected!r}"
                )
    return problems


def _launch_target(model: SystemModel, token: str) -> Process | None:
    """Resolve an ``after_process`` token to one host process by name or role."""
    for process in model.processes:
        if process.name == token:
            return process
    owners = [process for process in model.processes if token in process.roles]
    return owners[0] if len(owners) == 1 else None


def _check_launch_graph(model: SystemModel) -> list[str]:
    """Validate the launch order/dependency contract over host processes."""
    problems: list[str] = []
    by_name = {process.name: process for process in model.processes}
    for process in model.processes:
        token = process.launch.after_process
        if not token:
            continue
        target = _launch_target(model, token)
        if target is None:
            problems.append(
                f"processes.{process.name}: launch.after_process {token!r} names no "
                f"process or a non-unique role"
            )
            continue
        if process.launch.order < target.launch.order:
            problems.append(
                f"processes.{process.name}: launch.order {process.launch.order} < "
                f"{target.name} order {target.launch.order}"
            )
    for process in model.processes:
        if "builder" not in process.roles:
            continue
        if process.launch.after_process:
            problems.append(
                f"processes.{process.name}: a builder starts first and must not declare "
                f"after_process {process.launch.after_process!r}"
            )
        if process.launch.order != 0:
            problems.append(
                f"processes.{process.name}: builder launch.order must be 0, "
                f"found {process.launch.order}"
            )
    reported: set[frozenset[str]] = set()
    for start in by_name:
        chain: list[str] = []
        cursor: str | None = start
        while cursor is not None:
            if cursor in chain:
                cycle = frozenset(chain[chain.index(cursor) :])
                if cycle not in reported:
                    reported.add(cycle)
                    problems.append(
                        "processes.launch: dependency cycle " + " -> ".join([*chain, cursor])
                    )
                break
            chain.append(cursor)
            process = by_name[cursor]
            target = (
                _launch_target(model, process.launch.after_process)
                if process.launch.after_process
                else None
            )
            cursor = target.name if target is not None else None
    return problems


def _check_source_ssp(manifest: Mapping[str, Any], model: SystemModel) -> list[str]:
    problems: list[str] = []
    for name, instance in _instances(manifest).items():
        declared = _flag(_argv(instance), "--source-ssp")
        if declared is not None and declared != model.source_ssp:
            problems.append(
                f"{name}: --source-ssp {declared!r} != model.source_ssp {model.source_ssp!r}"
            )
    return problems


def _ssd_root(archive: zipfile.ZipFile) -> ElementTree.Element:
    return ElementTree.fromstring(archive.read(SSD_MEMBER))


def _ssd_components(root: ElementTree.Element) -> dict[str, str]:
    return {
        component.get("name", ""): component.get("source", "")
        for component in root.findall(f".//{{{NS_SSD}}}Component")
    }


def _ssd_connectors(root: ElementTree.Element) -> dict[str, dict[str, str]]:
    found: dict[str, dict[str, str]] = {}
    for component in root.findall(f".//{{{NS_SSD}}}Component"):
        connectors = component.findall(f"{{{NS_SSD}}}Connectors/{{{NS_SSD}}}Connector")
        found[component.get("name", "")] = {
            item.get("name", ""): item.get("kind", "") for item in connectors
        }
    return found


def _ssd_connections(root: ElementTree.Element) -> list[tuple[str, str, str, str]]:
    return [
        (
            item.get("startElement", ""),
            item.get("startConnector", ""),
            item.get("endElement", ""),
            item.get("endConnector", ""),
        )
        for item in root.findall(f".//{{{NS_SSD}}}Connections/{{{NS_SSD}}}Connection")
    ]


def _ssd_binding(root: ElementTree.Element) -> tuple[str, str] | None:
    binding = root.find(f".//{{{NS_SSD}}}ParameterBinding")
    if binding is None:
        return None
    mapping = binding.find(f"{{{NS_SSD}}}ParameterMapping")
    return binding.get("source", ""), (mapping.get("source", "") if mapping is not None else "")


def _ssv_parameters(payload: bytes) -> dict[str, str]:
    root = ElementTree.fromstring(payload)
    parameters = root.find(f"{{{NS_SSV}}}Parameters")
    if parameters is None:
        return {}
    values: dict[str, str] = {}
    for parameter in parameters.findall(f"{{{NS_SSV}}}Parameter"):
        child = next(iter(parameter), None)
        if child is not None:
            values[parameter.get("name", "")] = child.get("value", "")
    return values


def _fmu_contract(archive: zipfile.ZipFile, resource: str) -> tuple[str, bool, dict[str, str]]:
    with zipfile.ZipFile(io.BytesIO(archive.read(resource))) as fmu:
        description = ElementTree.fromstring(fmu.read(FMI_MODEL_DESCRIPTION))
    parameters: dict[str, str] = {}
    for variable in description.findall(".//ScalarVariable"):
        if variable.get("causality") != "parameter":
            continue
        for child in variable:
            if child.tag in {"Real", "Integer", "Boolean", "String"}:
                parameters[variable.get("name", "")] = child.get("start", "")
    return description.get("fmiVersion", ""), description.find("CoSimulation") is not None, parameters


def _check_aircraft(model: SystemModel, repo_root: Path, *, require: bool) -> list[str]:
    """Prove the built SSP is still the aircraft this model describes."""

    problems: list[str] = []
    scenario_ssp = repo_root / model.source_ssp
    if not scenario_ssp.is_file():
        if not require:
            return []
        return [
            f"source_ssp {model.source_ssp!r} does not exist; run scripts/build_airplane.py"
        ]

    modelled = {component.name: component for component in model.aircraft.components}
    with zipfile.ZipFile(scenario_ssp) as archive:
        names = set(archive.namelist())
        if SSD_MEMBER not in names:
            return [f"{model.source_ssp}: no {SSD_MEMBER}"]
        root = _ssd_root(archive)
        built = _ssd_components(root)
        connectors = _ssd_connectors(root)
        connections = _ssd_connections(root)

        for name in sorted(set(modelled) - set(built)):
            problems.append(f"{model.source_ssp}: component {name!r} is modelled but not built")
        for name in sorted(set(built) - set(modelled)):
            problems.append(f"{model.source_ssp}: component {name!r} is built but not modelled")
        for name, source in built.items():
            component = modelled.get(name)
            if component is None:
                continue
            if Path(source).name != component.fmu:
                problems.append(
                    f"{name}: built from {Path(source).name!r} but modelled as {component.fmu!r}"
                )
            component_connectors = connectors.get(name, {})
            for port_name in component.ports:
                if port_name == component.parameter_port:
                    continue
                if not any(
                    item == port_name or item.startswith(f"{port_name}.")
                    for item in component_connectors
                ):
                    problems.append(f"{name}: modelled port {port_name!r} has no SSD connector")
            for parameter_name in component.parameters:
                matched = [
                    kind
                    for connector_name, kind in component_connectors.items()
                    if connector_name == parameter_name
                    or connector_name.startswith(f"{parameter_name}[")
                ]
                if not matched or any(kind != "parameter" for kind in matched):
                    problems.append(
                        f"{name}: modelled parameter {parameter_name!r} is not an SSD "
                        f"parameter connector"
                    )

        for wire in model.aircraft.wires:
            matched = [
                item
                for item in connections
                if item[0] == wire.source
                and (item[1] == wire.source_port or item[1].startswith(f"{wire.source_port}."))
                and item[2] == wire.target
                and (item[3] == wire.target_port or item[3].startswith(f"{wire.target_port}."))
            ]
            if not matched:
                problems.append(
                    f"aircraft wire {wire.source}.{wire.source_port} -> "
                    f"{wire.target}.{wire.target_port} is modelled but not built"
                )

        binding = _ssd_binding(root)
        if binding is None:
            problems.append(f"{model.source_ssp}: no ParameterBinding; the scenario is not applied")
        else:
            if Path(binding[0]).name != model.scenario_binding:
                problems.append(
                    f"binding source {Path(binding[0]).name!r} != modelled {model.scenario_binding!r}"
                )
            if Path(binding[1]).name != model.scenario_mapping:
                problems.append(
                    f"binding mapping {Path(binding[1]).name!r} != modelled {model.scenario_mapping!r}"
                )
            ssv = binding[0]
            if ssv in names:
                parameters = _ssv_parameters(archive.read(ssv))
                # The JSON bridge and its useBridgeInput switch are gone; the
                # baseline must not resurrect a bridge-only parameter.
                if "useBridgeInput" in parameters:
                    problems.append(
                        "useBridgeInput is still bound but the JSON bridge is retired"
                    )

        resources = {Path(name).name for name in names if name.startswith("resources/") and name.endswith(".fmu")}
        for component in model.aircraft.components:
            if component.fmu not in resources:
                problems.append(f"{model.source_ssp}: resources/{component.fmu} is missing")
                continue
            version, co_simulation, parameters = _fmu_contract(archive, f"resources/{component.fmu}")
            if version != FMI_VERSION:
                problems.append(f"{component.fmu}: FMI version {version!r} != {FMI_VERSION!r}")
            if not co_simulation:
                problems.append(f"{component.fmu}: expected a {FMI_INTERFACE} FMU")
            if component.name == "rpr_entity":
                for key in RPR_DEPLOYMENT_PARAMETERS:
                    declared = component.parameters.get(key)
                    if declared is None:
                        continue
                    expected = str(declared[1]).lower() if isinstance(declared[1], bool) else str(declared[1])
                    if parameters.get(key) != expected:
                        problems.append(
                            f"rpr_entity.{key}: FMU default {parameters.get(key)!r} != modelled "
                            f"{expected!r}"
                        )

    baseline = repo_root / model.aircraft_ssp
    if baseline.is_file():
        with zipfile.ZipFile(baseline) as archive:
            if SSD_MEMBER not in archive.namelist():
                problems.append(f"{model.aircraft_ssp}: no {SSD_MEMBER}")
            else:
                built = _ssd_components(_ssd_root(archive))
                for name in sorted(set(modelled) - set(built)):
                    problems.append(f"{model.aircraft_ssp}: component {name!r} is modelled but not built")
                for name in sorted(set(built) - set(modelled)):
                    problems.append(f"{model.aircraft_ssp}: component {name!r} is built but not modelled")
                if _ssd_binding(_ssd_root(archive)) is not None:
                    problems.append(
                        f"{model.aircraft_ssp}: baseline carries a ParameterBinding; expected an unbound aircraft"
                    )
    elif require:
        problems.append(f"aircraft_ssp {model.aircraft_ssp!r} does not exist; run scripts/build_airplane.py")
    return problems


def _check_artifacts(model: SystemModel) -> list[str]:
    problems: list[str] = []
    artifacts = model.artifacts
    if Path(artifacts.run_dir).is_absolute():
        problems.append("artifacts.run_dir: expected a repository-relative path")
    for required in REQUIRED_ARTIFACTS:
        if required not in artifacts.files:
            problems.append(f"artifacts.files: missing required artifact {required!r}")
    values = list(artifacts.files.values())
    duplicates = sorted({value for value in values if values.count(value) > 1})
    if duplicates:
        problems.append(f"artifacts.files: duplicate path(s) {duplicates}")
    return problems


def check(
    manifest: Mapping[str, Any],
    model: SystemModel,
    *,
    repo_root: Path = REPO_ROOT,
    artifacts: bool = False,
) -> list[str]:
    """Return every fact that is missing or contradictory; empty means complete.

    ``artifacts=True`` also requires the built SSPs to exist and match the
    modelled aircraft; otherwise they are verified only when present.
    """

    problems: list[str] = []
    federation, entity_problems = _load_entity_federation(model, repo_root)
    problems += _check_manifest(manifest, model)
    problems += entity_problems
    problems += _check_entity_model(manifest, model, federation)
    problems += _check_timing(manifest, model, federation)
    problems += _check_frame(manifest, model, repo_root, federation)
    problems += _check_identity(manifest, model, repo_root, federation)
    problems += _check_ports(manifest, model)
    problems += _check_flows(manifest, model, federation)
    problems += _check_processes(manifest, model)
    problems += _check_launch_graph(model)
    problems += _check_source_ssp(manifest, model)
    problems += _check_artifacts(model)
    problems += _check_aircraft(model, repo_root, require=artifacts)
    return problems


def summary(model: SystemModel, manifest: Mapping[str, Any]) -> str:
    instances = _instances(manifest)
    addresses = sorted(
        (
            address
            for instance in instances.values()
            for name, address in _instance_ports(instance).items()
            if name == "telemetry"
        ),
        key=str,
    )
    return (
        f"{model.federation}: {len(instances)} entities, {len(model.processes)} host processes, "
        f"{len(model.flows)} flows, aircraft "
        f"{len(model.aircraft.components)} components/{len(model.aircraft.wires)} wires, "
        f"addresses {addresses}, "
        f"frame {model.frame.origin.latitude_deg:.6f},{model.frame.origin.longitude_deg:.6f} "
        f"({model.frame.waypoint_frame}), {model.timing.mode} "
        f"step {model.timing.step_size_s}s stop {model.timing.stop_time_s}s"
    )


def _load_manifest(path: Path) -> Mapping[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, Mapping):
        raise ModelError(f"{path}: expected a JSON object")
    return data


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--model", type=Path, default=DEFAULT_MODEL, help="System-plane SysML model.")
    parser.add_argument(
        "--manifest",
        type=Path,
        default=None,
        help="Lowered pysos_coordinate manifest (default: the model's manifest).",
    )
    parser.add_argument(
        "--artifacts",
        action="store_true",
        help="Require the built aircraft SSPs and verify them against the model.",
    )
    parser.add_argument("--json", action="store_true", help="Emit the result as JSON.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        model = load_model(args.model)
    except (OSError, ModelError) as exc:
        print(f"invalid: {exc}", file=sys.stderr)
        return 2
    manifest_path = args.manifest or (REPO_ROOT / model.manifest)
    try:
        manifest = _load_manifest(manifest_path)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"invalid: {exc}", file=sys.stderr)
        return 2

    problems = check(manifest, model, repo_root=REPO_ROOT, artifacts=args.artifacts)
    if args.json:
        print(
            json.dumps(
                {
                    "ok": not problems,
                    "summary": summary(model, manifest),
                    "problems": problems,
                },
                indent=2,
            )
        )
        return 0 if not problems else 1
    if problems:
        print(f"invalid: {summary(model, manifest)}", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        return 1
    print(f"ok: {summary(model, manifest)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
