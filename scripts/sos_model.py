#!/usr/bin/env python3
"""System-of-systems model for the multi-entity flight simulation.

The model is split over two SysML v2 files because no single pyssporg lowering
accepts the whole federation today:

* the **entity plane** is ``sos/aircraft_federation.sysml``, lowered by
  ``pysos_sysml`` to the ``pysos_coordinate`` manifest (schema 1): process
  ``command``/``cwd``/``env``, per-instance UDP endpoints, entity identity and
  the scenario name;
* the **system plane** is ``sos/federation_system.sysml``: the shared frame, the
  federation timing contract, the host-side participants
  (orchestrator/recorder, viewer, pilot), the flows and the run artifacts. This
  module lowers it from the ``pycps_sysml2`` IR, which already carries port
  definitions, port usages, connections and typed attribute values. The system
  plane imports the aircraft architecture (package ``Aircraft``) instead of
  restating it; the import target is named by the ``architecture`` attribute.

Authority is one-fact-one-place. The system plane never restates instance data:
``part instances : AircraftInstance [4]`` is one pattern, and connections to it are
lowered to the ``instance/*`` wildcard. This module resolves that pattern
against the lowered manifest and reports every fact that is missing or
contradictory, so "the model is complete" is a checkable claim.

``pysos_sysml`` lowers only a fixed attribute set, so per-instance run
parameters ride in the manifest ``command`` argv; the checks below keep them
present and consistent.
"""

from __future__ import annotations

import argparse
import io
import json
import re
import shlex
import sys
import zipfile
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

import pycps_sysml2

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent

DEFAULT_MODEL = REPO_ROOT / "sos" / "federation_system.sysml"
DEFAULT_MANIFEST = REPO_ROOT / "manifests" / "aircraft_federation.manifest.json"

SCHEMA_VERSION = 1
SYSTEM_DEF = "SystemDescription"
RESERVED_PARTS = ("origin", "timing", "overrides", "instances", "artifacts")
TIMING_POLICIES = frozenset({"wall_clock"})
TIMING_CLASSES = frozenset({"soft_realtime", "hard_realtime", "batch"})
FRAME_MODES = frozenset({"federation"})
WAYPOINT_FRAMES = frozenset({"federation", "local"})
PROTOCOLS = frozenset({"udp"})
ENCODINGS = frozenset({"json-udp", "dis", "rpr", "none"})
ROLES = frozenset({"supervisor", "recorder", "visualizer", "operator", "builder"})
LAUNCHES = frozenset({"operator", "manual", "human"})
REQUIRED_ARTIFACTS = ("truth", "measurements", "run")

#: SSP/FMI namespaces and members the artifact check reads by name.
NS_SSD = "http://ssp-standard.org/SSP1/SystemStructureDescription"
NS_SSV = "http://ssp-standard.org/SSP1/SystemStructureParameterValues"
SSD_MEMBER = "SystemStructure.ssd"
FMI_MODEL_DESCRIPTION = "modelDescription.xml"
#: Bridge parameters that must survive the build with their modelled defaults.
BRIDGE_PARAMETERS = ("transport", "remote_host", "telemetry_port", "control_port")
#: The aircraft is FMI 2.0 co-simulation only; the architecture declares the FMU
#: source but not the interface, so the checker pins it here.
FMI_VERSION = "2.0"
FMI_INTERFACE = "CoSimulation"

#: Artifact attribute names that differ from the contract key they fill.
ARTIFACT_ALIASES = {"run_json": "run", "instances_dir": "instances", "logs_dir": "logs"}

#: A part-usage occurrence count, written ``part name : Type [N]``. The parser
#: (pycps_sysml2 0.3.0) drops usage multiplicity, so this lexical adjunct reads
#: the annotation it loses. It is not a general SysML reader.
_MULTIPLICITY = re.compile(
    r"^\s*part\s+(?P<name>[A-Za-z_][A-Za-z0-9_]*)"
    r"\s*:\s*(?P<type>[A-Za-z_][A-Za-z0-9_:]*)"
    r"\s*\[\s*(?P<count>[^\]]*?)\s*\]"
)


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
class Process:
    name: str
    roles: tuple[str, ...]
    launch: str
    command: tuple[str, ...]
    cwd: str
    ports: dict[str, int | None]
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
    components: tuple[Component, ...]
    wires: tuple[Wire, ...]


@dataclass(frozen=True)
class Flow:
    name: str
    source: str
    target: str
    protocol: str
    encoding: str
    rate_hz: float


@dataclass(frozen=True)
class Artifacts:
    run_dir: str
    files: dict[str, str]


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
    bridge_input: bool
    instance_count: int
    aircraft: Aircraft
    processes: tuple[Process, ...]
    flows: tuple[Flow, ...]
    artifacts: Artifacts

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


def _multiplicities(path: Path) -> dict[str, tuple[str, int]]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise ModelError(f"cannot read model: {exc}") from exc
    found: dict[str, tuple[str, int]] = {}
    for line in lines:
        match = _MULTIPLICITY.match(line)
        if match is None:
            continue
        raw = match.group("count")
        if not raw.isdigit() or int(raw) < 1:
            raise ModelError(
                f"{path}:{match.group('name')}: multiplicity must be a positive integer, e.g. [3]"
            )
        found[match.group("name")] = (match.group("type"), int(raw))
    return found


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


def _port_contract(architecture: Any, type_name: str, where: str) -> tuple[str, str, float]:
    attributes = _attributes(_port_definition(architecture, type_name))
    where = f"port def {type_name}"
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


def _parse_process(architecture: Any, name: str, usage: Any) -> Process:
    definition = _part_definition(architecture, usage.type_name)
    attributes = _attributes(definition)
    where = f"part {name}"
    roles = _string_list(attributes, "roles", where)
    unknown = sorted(set(roles) - ROLES)
    if unknown:
        raise ModelError(f"{where}.roles: unknown role(s) {unknown}")
    launch = _typed(attributes, "launch", "String", where)
    if launch not in LAUNCHES:
        raise ModelError(f"{where}.launch: expected one of {sorted(LAUNCHES)}")
    command = tuple(shlex.split(_typed(attributes, "command", "String", where)))
    if not command:
        raise ModelError(f"{where}.command: empty command line")
    ports = {
        port_name: _port_number(architecture, port.type_name, port_name, where)
        for port_name, port in (definition.ports or {}).items()
    }
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


def _parse_aircraft(architecture: Any, usage: Any) -> Aircraft:
    """Lower the imported aircraft model referenced by ``part instances``."""

    wrapper = _part_definition(architecture, usage.type_name)
    aircraft_usage = (wrapper.parts or {}).get("aircraft")
    if aircraft_usage is None:
        raise ModelError(f"part def {wrapper.name}: expected a nested 'aircraft' part")
    model = _part_definition(architecture, aircraft_usage.type_name)
    parts = dict(model.parts or {})

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
    for connection in (model.connections or {}).values():
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
    return Aircraft(system=model.name, components=tuple(components), wires=tuple(wires))


def _parse_flows(architecture: Any, system: Any, multiplicity_parts: Iterable[str]) -> tuple[Flow, ...]:
    wildcards = set(multiplicity_parts)
    flows: list[Flow] = []
    parts = dict(system.parts or {})
    for connection in (system.connections or {}).values():
        if connection.source_part not in parts or connection.destination_part not in parts:
            raise ModelError(
                f"connection {connection.name!r}: both endpoints must be parts of {SYSTEM_DEF}"
            )
        source_type = _part_definition(architecture, parts[connection.source_part].type_name)
        source_port = source_type.ports[connection.source_port]
        protocol, encoding, rate_hz = _port_contract(
            architecture, source_port.type_name, f"connection {connection.name}"
        )
        flows.append(
            Flow(
                name=connection.name,
                source=_reference(connection.source_part, connection.source_port, wildcards),
                target=_reference(connection.destination_part, connection.destination_port, wildcards),
                protocol=protocol,
                encoding=encoding,
                rate_hz=rate_hz,
            )
        )
    if not flows:
        raise ModelError(f"{SYSTEM_DEF} declares no connections")
    return tuple(flows)


def _reference(part_name: str, port_name: str, wildcards: set[str]) -> str:
    if part_name in wildcards:
        return f"instance/*/{port_name}"
    return f"{part_name}/{port_name}" if port_name else part_name


def parse_architecture(architecture: Any, source: Path) -> SystemModel:
    """Lower a ``pycps_sysml2`` architecture to the system-plane model."""

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

    multiplicities = _multiplicities(source)
    if "instances" not in multiplicities:
        raise ModelError(
            f"{source}: part 'instances' needs an occurrence count, e.g. 'part instances : AircraftInstance [4]'"
        )
    declared_type, instance_count = multiplicities["instances"]
    if declared_type != parts["instances"].type_name:
        raise ModelError(
            f"{source}: 'instances' is typed {parts['instances'].type_name!r} but the multiplicity "
            f"line names {declared_type!r}"
        )

    instance_type = _part_definition(architecture, parts["instances"].type_name)
    for port_name in ("telemetry", "control"):
        if port_name not in (instance_type.ports or {}):
            raise ModelError(f"part def {instance_type.name}: missing port '{port_name}'")
    for port_name, port in (instance_type.ports or {}).items():
        external = _attributes(_port_definition(architecture, port.type_name)).get("external")
        if external is None or external[1] is not True:
            raise ModelError(
                f"part def {instance_type.name}: port {port_name!r} must be declared external"
            )
    overrides_def = _part_definition(architecture, parts["overrides"].type_name)

    processes = tuple(
        _parse_process(architecture, name, process_usage)
        for name, process_usage in parts.items()
        if name not in RESERVED_PARTS
    )
    flows = _parse_flows(architecture, system, multiplicities)
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
        bridge_input=_typed(
            _attributes(overrides_def), "bridge_input", "Boolean", f"part def {overrides_def.name}"
        ),
        instance_count=instance_count,
        aircraft=_parse_aircraft(architecture, parts["instances"]),
        processes=processes,
        flows=flows,
        artifacts=_parse_artifacts(_part_definition(architecture, parts["artifacts"].type_name)),
    )


def _load_architecture(path: Path) -> Any:
    try:
        return pycps_sysml2.load(path)
    except Exception as exc:  # sysmlpy raises its own syntax error type
        raise ModelError(f"{path}: cannot parse SysML v2 model: {exc}") from exc


def load_model(path: Path | str = DEFAULT_MODEL) -> SystemModel:
    """Parse the system plane and merge the architecture it imports."""

    source = Path(path)
    primary = _load_architecture(source)
    system = _part_definition(primary, SYSTEM_DEF)
    architecture = _typed(
        _attributes(system), "architecture", "String", f"part def {SYSTEM_DEF}"
    )
    imported = REPO_ROOT / architecture
    if not imported.is_file():
        raise ModelError(
            f"architecture {architecture!r} does not exist; the system plane imports it"
        )
    merged = _load_architecture([imported, source])
    package = _load_architecture(imported).package_name
    if package not in merged.imports:
        raise ModelError(
            f"{source}: the architecture declares package {package!r}, but the system plane "
            f"does not import it; add 'private import {package}::*;'"
        )
    return parse_architecture(merged, source)


# --------------------------------------------------------------------------- #
# Manifest resolution
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class Resolved:
    label: str
    component: str
    scope: str
    port: int | None


def _as_int_port(value: Any) -> int | None:
    try:
        port = int(value)
    except (TypeError, ValueError):
        return None
    return port if 1 <= port <= 65535 else None


def _instance_ports(instance: Mapping[str, Any]) -> dict[str, int]:
    ports: dict[str, int] = {}
    for name in ("telemetry", "control"):
        endpoints = instance.get(name) or []
        if len(endpoints) != 1 or not isinstance(endpoints[0], Mapping):
            continue
        port = _as_int_port(endpoints[0].get("port"))
        if port is not None:
            ports[name] = port
    return ports


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
    if manifest.get("schema") != SCHEMA_VERSION:
        problems.append(f"manifest.schema {manifest.get('schema')!r} != {SCHEMA_VERSION}")
    instances = manifest.get("instances") or []
    if not instances:
        problems.append("manifest.instances: the federation has no instances")
    elif len(instances) != model.instance_count:
        problems.append(
            f"manifest.instances has {len(instances)} entr(ies) but the model declares "
            f"part instances : {model.instance_count}"
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
        for endpoint_name in ("telemetry", "control"):
            endpoints = instance.get(endpoint_name) or []
            if len(endpoints) != 1:
                problems.append(
                    f"{name}: expected exactly one {endpoint_name} endpoint, found {len(endpoints)}"
                )
    return problems


def _check_timing(manifest: Mapping[str, Any], model: SystemModel) -> list[str]:
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
    for instance in _instances(manifest).values():
        name = instance.get("name")
        argv = _argv(instance)
        realtime = "--realtime" in argv
        if realtime != timing.realtime:
            problems.append(
                f"{name}: --realtime is {realtime} but timing.realtime is {timing.realtime}"
            )
        stop = _flag(argv, "--stop-time")
        if stop is None:
            problems.append(f"{name}: --stop-time is missing; the run duration is not modelled")
        else:
            try:
                value = float(stop)
            except ValueError:
                problems.append(f"{name}: --stop-time {stop!r} is not a number")
            else:
                if not _close(value, timing.stop_time_s):
                    problems.append(
                        f"{name}: --stop-time {value} != timing.stop_time_s {timing.stop_time_s}"
                    )
        for unsupported in ("--step-size", "--timestep"):
            if unsupported in argv:
                problems.append(
                    f"{name}: {unsupported} is not consumed downstream; declare it under timing"
                )
    return problems


def _frame_reference(model: SystemModel, repo_root: Path) -> tuple[Path | None, int]:
    reference = model.frame.reference
    path_text, _, selector = reference.partition("#")
    index_text = selector.removeprefix("points[") if selector.startswith("points[") else ""
    index = int(index_text.rstrip("]")) if index_text.rstrip("]").isdigit() else 0
    path = repo_root / path_text
    return (path if path.is_file() else None), index


def _check_frame(manifest: Mapping[str, Any], model: SystemModel, repo_root: Path) -> list[str]:
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

    placements: dict[tuple[float, float], str] = {}
    for instance in _instances(manifest).values():
        name = instance.get("name")
        argv = _argv(instance)
        waypoint_frame = _flag(argv, "--waypoint-frame")
        if waypoint_frame is None:
            problems.append(
                f"{name}: --waypoint-frame is missing; the frame policy {model.frame.waypoint_frame!r} "
                f"is not enforced"
            )
        elif waypoint_frame != model.frame.waypoint_frame:
            problems.append(
                f"{name}: --waypoint-frame {waypoint_frame!r} != {model.frame.waypoint_frame!r}"
            )
        for key, flag in (
            ("latitude_deg", "--reference-latitude-deg"),
            ("longitude_deg", "--reference-longitude-deg"),
            ("altitude_m", "--reference-altitude-m"),
        ):
            declared = getattr(origin, key)
            text = _flag(argv, flag)
            if text is None:
                problems.append(
                    f"{name}: {flag} is missing; the wire origin does not match the federation frame"
                )
                continue
            try:
                value = float(text)
            except ValueError:
                problems.append(f"{name}: {flag} {text!r} is not a number")
                continue
            if not _close(value, declared, 1e-9):
                problems.append(
                    f"{name}: {flag} {value} != frame.origin.{key} {declared}"
                )
        north_text = _flag(argv, "--offset-north-km")
        east_text = _flag(argv, "--offset-east-km")
        if north_text is None or east_text is None:
            problems.append(f"{name}: placement offsets are missing; the entity position is implicit")
            continue
        try:
            placement = (round(float(north_text), 6), round(float(east_text), 6))
        except ValueError:
            problems.append(f"{name}: placement offsets are not numbers")
            continue
        if placement in placements:
            problems.append(
                f"{name}: placement {placement} collides with {placements[placement]}"
            )
        placements[placement] = str(name)
    return problems


def _check_identity(manifest: Mapping[str, Any], model: SystemModel, repo_root: Path) -> list[str]:
    problems: list[str] = []
    slugs: dict[str, str] = {}
    markings: dict[str, str] = {}
    scenarios_dir = repo_root / model.scenarios_dir
    for instance in _instances(manifest).values():
        name = str(instance.get("name"))
        entity = (instance.get("entities") or [{}])[0]
        slug = _entity_slug(entity)
        if slug in slugs:
            problems.append(f"{name}: entity {slug} already used by {slugs[slug]}")
        slugs[slug] = name
        marking = str(entity.get("marking") or "")
        if marking:
            if marking in markings:
                problems.append(f"{name}: marking {marking!r} already used by {markings[marking]}")
            markings[marking] = name
        else:
            problems.append(f"{name}: entity has no marking")
        scenario = (instance.get("env") or {}).get("PYSOS_SCENARIO")
        if not scenario:
            problems.append(f"{name}: env.PYSOS_SCENARIO is missing")
        elif not (scenarios_dir / f"{scenario}.json").is_file():
            problems.append(f"{name}: scenario {scenario!r} not found under {model.scenarios_dir}")
    return problems


def _check_entity_model(model: SystemModel, repo_root: Path) -> list[str]:
    path = repo_root / model.entity_model
    if not path.is_file():
        return [f"entity model {model.entity_model!r} does not exist"]
    text = path.read_text(encoding="utf-8")
    if "part def Federation" not in text:
        return [f"entity model {model.entity_model!r} declares no 'part def Federation'"]
    return []


def _check_ports(manifest: Mapping[str, Any], model: SystemModel) -> list[str]:
    problems: list[str] = []
    owners: dict[int, str] = {}
    for name, instance in _instances(manifest).items():
        for endpoint_name, port in _instance_ports(instance).items():
            label = f"{name}.{endpoint_name}"
            if port in owners:
                problems.append(f"port {port} declared by both {owners[port]} and {label}")
            owners[port] = label
    for process in model.processes:
        for port_name, port in process.ports.items():
            if port is None:
                continue
            label = f"{process.name}.{port_name}"
            if port in owners:
                problems.append(f"port {port} declared by both {owners[port]} and {label}")
            owners[port] = label
    return problems


def _check_flows(manifest: Mapping[str, Any], model: SystemModel) -> list[str]:
    problems: list[str] = []
    instances = _instances(manifest)
    processes = {process.name: process for process in model.processes}
    names = [flow.name for flow in model.flows]
    duplicates = sorted({name for name in names if names.count(name) > 1})
    if duplicates:
        problems.append(f"flows: duplicate name(s) {duplicates}")

    covered_sources: set[str] = set()
    covered_targets: set[str] = set()
    for flow in model.flows:
        if flow.protocol not in PROTOCOLS:
            problems.append(f"flows.{flow.name}.protocol: expected one of {sorted(PROTOCOLS)}")
        if flow.encoding not in ENCODINGS:
            problems.append(f"flows.{flow.name}.encoding: expected one of {sorted(ENCODINGS)}")
        if flow.rate_hz <= 0.0:
            problems.append(f"flows.{flow.name}.rate_hz: must be > 0")
        sources, source_problem = _resolve_reference(flow.source, instances, processes)
        if source_problem:
            problems.append(f"flows.{flow.name}.from: {source_problem}")
        targets, target_problem = _resolve_reference(flow.target, instances, processes)
        if target_problem:
            problems.append(f"flows.{flow.name}.to: {target_problem}")
        covered_sources.update(item.label for item in sources)
        covered_targets.update(item.label for item in targets)

    for name, instance in instances.items():
        for endpoint_name, port in _instance_ports(instance).items():
            label = f"instance/{name}/{endpoint_name}"
            if endpoint_name == "telemetry" and label not in covered_sources:
                problems.append(f"{name}: telemetry port {port} feeds no modelled flow")
            if endpoint_name == "control" and label not in covered_targets:
                problems.append(f"{name}: control port {port} has no modelled producer")
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
        telemetry_specs = [
            argv[index + 1] for index, token in enumerate(argv[:-1]) if token == "--telemetry"
        ]
        if telemetry_specs:
            expected = {
                f"{port}:{entity.get('entity')}"
                for instance in instances.values()
                for port in [_instance_ports(instance).get("telemetry")]
                if port is not None
                for entity in (instance.get("entities") or [{}])[0:1]
            }
            if set(telemetry_specs) != expected:
                problems.append(
                    f"processes.{process.name}: --telemetry {sorted(telemetry_specs)} != manifest "
                    f"telemetry {sorted(expected)}"
                )
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
                declared = "true" if model.bridge_input else "false"
                if parameters.get("useBridgeInput") != declared:
                    problems.append(
                        f"useBridgeInput is {parameters.get('useBridgeInput')!r} but the model "
                        f"declares {declared!r}"
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
            if component.name == "udp_bridge":
                for key in BRIDGE_PARAMETERS:
                    declared = component.parameters.get(key)
                    if declared is None:
                        continue
                    expected = str(declared[1]).lower() if isinstance(declared[1], bool) else str(declared[1])
                    if parameters.get(key) != expected:
                        problems.append(
                            f"udp_bridge.{key}: FMU default {parameters.get(key)!r} != modelled "
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
    problems += _check_manifest(manifest, model)
    problems += _check_entity_model(model, repo_root)
    problems += _check_timing(manifest, model)
    problems += _check_frame(manifest, model, repo_root)
    problems += _check_identity(manifest, model, repo_root)
    problems += _check_ports(manifest, model)
    problems += _check_flows(manifest, model)
    problems += _check_processes(manifest, model)
    problems += _check_source_ssp(manifest, model)
    problems += _check_artifacts(model)
    problems += _check_aircraft(model, repo_root, require=artifacts)
    return problems


def summary(model: SystemModel, manifest: Mapping[str, Any]) -> str:
    instances = _instances(manifest)
    ports = sorted(
        port for instance in instances.values() for port in _instance_ports(instance).values()
    )
    return (
        f"{model.federation}: {len(instances)} entities, {len(model.processes)} host processes, "
        f"{len(model.flows)} flows, aircraft "
        f"{len(model.aircraft.components)} components/{len(model.aircraft.wires)} wires, ports {ports}, "
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
