#!/usr/bin/env python3
"""Prepare one independent aircraft instance from the prepared local SSP bundle.

The source SSP already binds ``resources/MissionScenario.ssv`` and
``resources/HighAltitudeIntercept.ssm`` in its ``SystemStructure.ssd``. This
script rewrites those two archive members in a per-instance copy of the SSP:

* ``ros2_udp_bridge.telemetry_port`` / ``ros2_udp_bridge.control_port``
* shifted ``initX_km`` (north) / ``initY_km`` (east) when an offset applies
* the ``MissionScenario.ssv`` waypoint array, ``waypointCount``,
  ``waypointProximity_km`` and ``targetAirspeed_mps`` selected by ``scenario``

and writes a per-instance ssp4sim config with its own working directory, CSV,
and log file. The rewrite is deterministic and idempotent, and refuses to write
an archive when a required mapping could not be injected. The scenario JSON is
converted through the airplane scenario library, so this script does not own a
second waypoint generator.
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

REPO_ROOT = Path(__file__).resolve().parents[1]
AIRPLANE_ROOT = REPO_ROOT / "3rd_party" / "airplane"
DEFAULT_SOURCE_SSP = REPO_ROOT / "build" / "ssp" / "scenario.ssp"
DEFAULT_OUT_DIR = REPO_ROOT / "build" / "ssp" / "instances"
SCENARIO_DIR = AIRPLANE_ROOT / "resources" / "scenarios"
DEFAULT_SCENARIO = "test_scenario"

if str(AIRPLANE_ROOT) not in sys.path:
    sys.path.insert(0, str(AIRPLANE_ROOT))

from scripts.lib.paths import GENERATED_SCENARIO_SSV
from scripts.lib.scenarios import preparation
from scripts.lib.scenarios.runtime import (
    create_simulation_config,
    write_simulation_config,
)

SSV_MEMBER = "resources/MissionScenario.ssv"
SSM_MEMBER = "resources/HighAltitudeIntercept.ssm"
SSD_MEMBER = "SystemStructure.ssd"

NS_SSV = "http://ssp-standard.org/SSP1/SystemStructureParameterValues"
NS_SSM = "http://ssp-standard.org/SSP1/SystemStructureParameterMapping"
NS_SSD = "http://ssp-standard.org/SSP1/SystemStructureDescription"

TELEMETRY_PARAM = "ros2_udp_bridge.telemetry_port"
CONTROL_PARAM = "ros2_udp_bridge.control_port"
INIT_X_PARAM = "initX_km"
INIT_Y_PARAM = "initY_km"
WAYPOINT_COUNT_PARAM = "waypointCount"
WAYPOINT_PROXIMITY_PARAM = "waypointProximity_km"
TARGET_AIRSPEED_PARAM = "targetAirspeed_mps"
WAYPOINT_ARRAY_SIZE = preparation.WAYPOINT_ARRAY_SIZE

ET.register_namespace("ssv", NS_SSV)
ET.register_namespace("ssm", NS_SSM)
ET.register_namespace("ssd", NS_SSD)


def instance_defaults(index: int) -> dict[str, float | int]:
    """Default ports and offset for a 1-based instance index."""

    if index < 1:
        raise SystemExit(f"--instance must be 1-based, got {index}")
    telemetry_port = 5510 + 2 * (index - 1)
    control_port = telemetry_port + 1
    if control_port > 65535:
        raise SystemExit(f"Instance {index} port {control_port} exceeds 65535")
    return {
        "telemetry_port": telemetry_port,
        "control_port": control_port,
        "offset_north_km": 0.0,
        "offset_east_km": (index - 1) * 5.0,
    }


def _scenario_parameter_set(scenario: str) -> dict[str, tuple[str, str]]:
    """Convert a scenario JSON through the airplane library into SSV values."""

    path = SCENARIO_DIR / f"{scenario}.json"
    if not path.is_file():
        available = sorted(item.stem for item in SCENARIO_DIR.glob("*.json"))
        raise SystemExit(f"Scenario not found: {path}; available: {available}")
    scenario_data = json.loads(path.read_text(encoding="utf-8"))
    points = scenario_data.get("points") or []
    if not points:
        raise SystemExit(f"{path}: scenario has no points")
    preparation.validate_scenario_points(points)
    local_points = preparation.project_waypoints_to_local_km(points)
    overrides = scenario_data.get("simulation_overrides") or {}
    proximity = overrides.get("waypoint_proximity_km", preparation.WAYPOINT_PROXIMITY_KM)
    airspeed = overrides.get("target_airspeed_mps", overrides.get("cruise_speed_mps"))

    requested = {
        TARGET_AIRSPEED_PARAM,
        WAYPOINT_PROXIMITY_PARAM,
        WAYPOINT_COUNT_PARAM,
    }
    for index in range(1, WAYPOINT_ARRAY_SIZE + 1):
        requested.update((f"waypointX_km[{index}]", f"waypointY_km[{index}]", f"waypointZ_km[{index}]"))

    with tempfile.TemporaryDirectory(prefix="flight-sim-scenario-") as directory:
        generated = preparation.emit_waypoint_parameter_set(
            local_points,
            Path(directory) / f"{scenario}.ssv",
            baseline_path=GENERATED_SCENARIO_SSV,
            enable_bridge_input=False,
            waypoint_proximity_km=float(proximity),
            target_airspeed_mps=None if airspeed is None else float(airspeed),
        )
        params = ET.parse(generated).getroot().find(f"{{{NS_SSV}}}Parameters")
        if params is None:
            raise SystemExit(f"{generated}: no <ssv:Parameters> element")
        values: dict[str, tuple[str, str]] = {}
        for parameter in params.findall(f"{{{NS_SSV}}}Parameter"):
            name = parameter.get("name")
            if name not in requested:
                continue
            for child in parameter:
                values[name] = (_namespace(child.tag)[1], child.get("value", "0"))
                break

    values[WAYPOINT_COUNT_PARAM] = ("Integer", str(WAYPOINT_ARRAY_SIZE))
    missing = sorted(requested - set(values))
    if missing:
        raise SystemExit(f"{path}: conversion did not produce {missing}")
    return values


def _namespace(tag: str) -> tuple[str, str]:
    return tag[1:].split("}", 1)


def _ssv_parameter_value(params: ET.Element, name: str) -> float | None:
    for parameter in params.findall(f"{{{NS_SSV}}}Parameter"):
        if parameter.get("name") != name:
            continue
        for child in parameter:
            if _namespace(child.tag)[1] == "Real":
                return float(child.get("value", "0"))
        return None
    return None


def _set_ssv_parameter(params: ET.Element, name: str, tag: str, value: str) -> None:
    for parameter in params.findall(f"{{{NS_SSV}}}Parameter"):
        if parameter.get("name") != name:
            continue
        for child in list(parameter):
            parameter.remove(child)
        ET.SubElement(parameter, f"{{{NS_SSV}}}{tag}").set("value", value)
        return
    parameter = ET.SubElement(params, f"{{{NS_SSV}}}Parameter")
    parameter.set("name", name)
    ET.SubElement(parameter, f"{{{NS_SSV}}}{tag}").set("value", value)


def _rewrite_ssv(payload: bytes, updates: dict[str, tuple[str, str]]) -> bytes:
    root = ET.fromstring(payload)
    params = root.find(f"{{{NS_SSV}}}Parameters")
    if params is None:
        raise SystemExit(f"{SSV_MEMBER}: no <ssv:Parameters> element")
    for name, (tag, value) in updates.items():
        _set_ssv_parameter(params, name, tag, value)
    ET.indent(root, space="  ")
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def _rewrite_ssm(payload: bytes, mapping: dict[str, str]) -> bytes:
    root = ET.fromstring(payload)
    entries = root.findall(f"{{{NS_SSM}}}MappingEntry")
    if not entries:
        raise SystemExit(f"{SSM_MEMBER}: no <ssm:MappingEntry> elements")
    by_source = {entry.get("source"): entry for entry in entries}
    for source, target in mapping.items():
        entry = by_source.get(source)
        if entry is None:
            entry = ET.SubElement(root, f"{{{NS_SSM}}}MappingEntry")
            entry.set("source", source)
            by_source[source] = entry
        entry.set("target", target)
    ET.indent(root, space="  ")
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def _ssd_has_connector(ssd_root: ET.Element, component: str, connector: str) -> bool:
    for element in ssd_root.findall(f".//{{{NS_SSD}}}Component"):
        if element.get("name") != component:
            continue
        for candidate in element.findall(f"{{{NS_SSD}}}Connectors/{{{NS_SSD}}}Connector"):
            if candidate.get("name") == connector:
                return True
    return False


def _validate_ssd(payload: bytes, mapping: dict[str, str]) -> None:
    root = ET.fromstring(payload)
    for target in mapping.values():
        component, _, connector = target.partition(".")
        if not _ssd_has_connector(root, component, connector):
            raise SystemExit(
                f"{SSD_MEMBER}: no connector {target!r} for parameter target; "
                f"available members: {SSD_MEMBER}, {SSV_MEMBER}, {SSM_MEMBER}"
            )


def _read_bundle(source_ssp: Path) -> list[tuple[zipfile.ZipInfo, bytes]]:
    with zipfile.ZipFile(source_ssp) as archive:
        names = set(archive.namelist())
        missing = [m for m in (SSV_MEMBER, SSM_MEMBER, SSD_MEMBER) if m not in names]
        if missing:
            raise SystemExit(
                f"{source_ssp}: missing archive members {missing}; "
                f"inspected {sorted(names)}"
            )
        return [(info, archive.read(info.filename)) for info in archive.infolist()]


def _write_bundle(dest_ssp: Path, entries: list[tuple[zipfile.ZipInfo, bytes]]) -> None:
    tmp_path = dest_ssp.with_name(dest_ssp.name + ".tmp")
    with zipfile.ZipFile(tmp_path, "w") as archive:
        for info, data in entries:
            out = zipfile.ZipInfo(info.filename, date_time=(1980, 1, 1, 0, 0, 0))
            out.compress_type = zipfile.ZIP_DEFLATED
            out.create_system = 3
            out.external_attr = info.external_attr
            archive.writestr(out, data)
    tmp_path.replace(dest_ssp)


def _verify_archive(
    dest_ssp: Path,
    updates: dict[str, tuple[str, str]],
    mapping: dict[str, str],
) -> None:
    with zipfile.ZipFile(dest_ssp) as archive:
        ssv = ET.fromstring(archive.read(SSV_MEMBER))
        params = ssv.find(f"{{{NS_SSV}}}Parameters")
        assert params is not None
        for name, (tag, value) in updates.items():
            for parameter in params.findall(f"{{{NS_SSV}}}Parameter"):
                if parameter.get("name") != name:
                    continue
                child = parameter.find(f"{{{NS_SSV}}}{tag}")
                if child is None or child.get("value") != value:
                    raise SystemExit(f"{dest_ssp}: verification failed for {name}")
                break
            else:
                raise SystemExit(f"{dest_ssp}: verification failed, {name} missing")

        ssm = ET.fromstring(archive.read(SSM_MEMBER))
        targets = {
            entry.get("source"): entry.get("target")
            for entry in ssm.findall(f"{{{NS_SSM}}}MappingEntry")
        }
        for source, target in mapping.items():
            if targets.get(source) != target:
                raise SystemExit(f"{dest_ssp}: verification failed for mapping {source}")


def _resolve_stop_time(source_ssp: Path) -> float:
    config_path = source_ssp.parent / "config.json"
    if config_path.is_file():
        config = json.loads(config_path.read_text(encoding="utf-8"))
        stop_time = config.get("simulation", {}).get("stop_time")
        if stop_time is not None:
            return float(stop_time)

    with zipfile.ZipFile(source_ssp) as archive:
        ssd = ET.fromstring(archive.read(SSD_MEMBER))
    experiment = ssd.find(f".//{{{NS_SSD}}}DefaultExperiment")
    if experiment is not None and experiment.get("stopTime") is not None:
        return float(experiment.get("stopTime"))
    raise SystemExit(f"{source_ssp}: cannot resolve a default stop time; pass --stop-time")


def prepare_instance(
    index: int,
    source_ssp: Path,
    out_dir: Path,
    *,
    telemetry_port: int | None = None,
    control_port: int | None = None,
    offset_north_km: float | None = None,
    offset_east_km: float | None = None,
    working_dir: Path | None = None,
    csv_path: Path | None = None,
    log_path: Path | None = None,
    stop_time: float | None = None,
    scenario: str | None = None,
    realtime: bool = False,
) -> dict[str, str]:
    """Write the per-instance SSP and config; return their paths and settings."""

    defaults = instance_defaults(index)
    telemetry = int(telemetry_port if telemetry_port is not None else defaults["telemetry_port"])
    control = int(control_port if control_port is not None else defaults["control_port"])
    north = float(offset_north_km if offset_north_km is not None else defaults["offset_north_km"])
    east = float(offset_east_km if offset_east_km is not None else defaults["offset_east_km"])
    scenario_name = scenario or DEFAULT_SCENARIO
    for label, port in (("--telemetry-port", telemetry), ("--control-port", control)):
        if not 1 <= port <= 65535:
            raise SystemExit(f"{label} out of range: {port}")

    source_ssp = source_ssp.resolve()
    if not source_ssp.is_file():
        raise SystemExit(f"Source SSP not found: {source_ssp}")

    instance_dir = out_dir.resolve() / f"instance-{index}"
    instance_dir.mkdir(parents=True, exist_ok=True)
    dest_ssp = instance_dir / source_ssp.name
    config_path = instance_dir / "config.json"
    work_dir = (working_dir or instance_dir / "work").resolve()
    csv_file = (csv_path or instance_dir / "results" / "scenario_results.csv").resolve()
    log_file = (log_path or instance_dir / "results" / "sim.log").resolve()
    for directory in (work_dir, csv_file.parent, log_file.parent):
        directory.mkdir(parents=True, exist_ok=True)

    resolved_stop_time = float(stop_time) if stop_time is not None else _resolve_stop_time(source_ssp)

    entries = _read_bundle(source_ssp)
    contents = {info.filename: data for info, data in entries}

    ssv_root = ET.fromstring(contents[SSV_MEMBER])
    ssv_params = ssv_root.find(f"{{{NS_SSV}}}Parameters")
    if ssv_params is None:
        raise SystemExit(f"{source_ssp}: {SSV_MEMBER} has no <ssv:Parameters> element")
    base_north = _ssv_parameter_value(ssv_params, INIT_X_PARAM)
    base_east = _ssv_parameter_value(ssv_params, INIT_Y_PARAM)
    if base_north is None or base_east is None:
        raise SystemExit(
            f"{source_ssp}: {SSV_MEMBER} lacks {INIT_X_PARAM}/{INIT_Y_PARAM}; "
            f"cannot apply an initial-position offset"
        )

    updates = {
        TELEMETRY_PARAM: ("Integer", str(telemetry)),
        CONTROL_PARAM: ("Integer", str(control)),
        INIT_X_PARAM: ("Real", f"{base_north + north:.6f}"),
        INIT_Y_PARAM: ("Real", f"{base_east + east:.6f}"),
    }
    updates.update(_scenario_parameter_set(scenario_name))
    mapping = {
        TELEMETRY_PARAM: TELEMETRY_PARAM,
        CONTROL_PARAM: CONTROL_PARAM,
        INIT_X_PARAM: f"environment.{INIT_X_PARAM}",
        INIT_Y_PARAM: f"environment.{INIT_Y_PARAM}",
        WAYPOINT_COUNT_PARAM: f"autopilot_module.{WAYPOINT_COUNT_PARAM}",
    }

    _validate_ssd(contents[SSD_MEMBER], mapping)
    rewritten = {
        SSV_MEMBER: _rewrite_ssv(contents[SSV_MEMBER], updates),
        SSM_MEMBER: _rewrite_ssm(contents[SSM_MEMBER], mapping),
    }
    new_entries = [
        (info, rewritten.get(info.filename, data)) for info, data in entries
    ]
    _write_bundle(dest_ssp, new_entries)
    _verify_archive(dest_ssp, updates, mapping)

    config = create_simulation_config(
        ssp_path=dest_ssp,
        result_file=csv_file,
        stop_time=resolved_stop_time,
        realtime=realtime,
        recording_interval=0.25,
    )
    config["simulation"]["working_dir"] = str(work_dir)
    config["simulation"]["recording"]["csv"]["file"] = str(csv_file)
    config["simulation"]["log"]["file"] = str(log_file)
    write_simulation_config(config=config, result_file=csv_file, config_path=config_path)

    return {
        "instance": str(index),
        "ssp": str(dest_ssp),
        "config": str(config_path),
        "working_dir": str(work_dir),
        "csv": str(csv_file),
        "log": str(log_file),
        "telemetry_port": str(telemetry),
        "control_port": str(control),
        "init_x_km": updates[INIT_X_PARAM][1],
        "init_y_km": updates[INIT_Y_PARAM][1],
        "stop_time": f"{resolved_stop_time}",
        "scenario": scenario_name,
        "realtime": str(realtime).lower(),
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--instance", type=int, required=True, help="1-based instance index.")
    parser.add_argument("--source-ssp", type=Path, default=DEFAULT_SOURCE_SSP, help="Prepared source SSP archive.")
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR, help="Directory for instance bundles.")
    parser.add_argument("--telemetry-port", type=int, default=None, help="Telemetry UDP port.")
    parser.add_argument("--control-port", type=int, default=None, help="Control UDP port.")
    parser.add_argument("--offset-north-km", type=float, default=None, help="Shift initX_km by this many kilometres.")
    parser.add_argument("--offset-east-km", type=float, default=None, help="Shift initY_km by this many kilometres.")
    parser.add_argument("--working-dir", type=Path, default=None, help="Simulation working directory.")
    parser.add_argument("--csv", type=Path, default=None, help="Per-instance result CSV path.")
    parser.add_argument("--log", type=Path, default=None, help="Per-instance simulation log path.")
    parser.add_argument("--stop-time", type=float, default=None, help="Stop time in seconds.")
    parser.add_argument("--scenario", default=None, help="Scenario JSON stem (default: test_scenario).")
    parser.add_argument("--realtime", action="store_true", help="Pace the instance against the wall clock.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    summary = prepare_instance(
        args.instance,
        args.source_ssp,
        args.out_dir,
        telemetry_port=args.telemetry_port,
        control_port=args.control_port,
        offset_north_km=args.offset_north_km,
        offset_east_km=args.offset_east_km,
        working_dir=args.working_dir,
        csv_path=args.csv,
        log_path=args.log,
        stop_time=args.stop_time,
        scenario=args.scenario,
        realtime=args.realtime,
    )
    print(f"Wrote SSP {summary['ssp']}")
    print(f"Wrote config {summary['config']}")
    print(
        f"Instance {summary['instance']}: telemetry {summary['telemetry_port']}, "
        f"control {summary['control_port']}, scenario {summary['scenario']}, init "
        f"(north {summary['init_x_km']} km, east {summary['init_y_km']} km)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
