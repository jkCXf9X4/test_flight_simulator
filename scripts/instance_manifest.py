"""Build, load, and write the federation manifest for the aircraft scenario.

The manifest schema is owned by ``pysos_coordinate``
(``docs/breakdown/02-architecture/manifest.md`` there). This module only
translates project settings — instance count, interpreter, SSP bundle paths,
ports, and the 5 km east offset — into that schema. It has no supervisor of its
own: ``run_instances.py`` hands the resulting ``FederationSpec`` to
``pysos_coordinate.Federation``.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
AIRPLANE_ROOT = REPO_ROOT / "3rd_party" / "airplane"

if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from prepare_instance_bundle import (
    DEFAULT_OUT_DIR,
    DEFAULT_SOURCE_SSP,
    instance_defaults,
)
from pysos_coordinate import Endpoint, EntityRef, FederationSpec, InstanceSpec

SCENARIO_PATH = AIRPLANE_ROOT / "resources" / "scenarios" / "test_scenario.json"
DEFAULT_MANIFEST = REPO_ROOT / "manifests" / "two_instances.manifest.json"
DEFAULT_PYTHON = "python3"
LAUNCH_SCRIPT = "scripts/run_instance_process.py"
ENTITY_SITE = "1"
ENTITY_APPLICATION = "1"


def _display_path(path: Path | str) -> str:
    """Repository-relative spelling when possible, so the manifest is portable."""

    candidate = Path(path)
    if not candidate.is_absolute():
        return str(candidate)
    try:
        return str(candidate.relative_to(REPO_ROOT))
    except ValueError:
        return str(candidate)


def _scenario_name(scenario_path: Path | str) -> str:
    data = json.loads(Path(scenario_path).read_text(encoding="utf-8"))
    name = data.get("name")
    if not isinstance(name, str) or not name.strip():
        raise ValueError(f"{scenario_path}: scenario has no non-empty 'name'")
    return name


def build_spec(
    *,
    instances: int = 2,
    python: str = DEFAULT_PYTHON,
    source_ssp: Path | str = DEFAULT_SOURCE_SSP,
    out_dir: Path | str = DEFAULT_OUT_DIR,
    stop_time: float | None = None,
    realtime: bool = False,
    scenario_path: Path | str = SCENARIO_PATH,
    name: str | None = None,
) -> FederationSpec:
    """Translate project settings into a validated ``FederationSpec``."""

    if instances < 1:
        raise ValueError(f"instances must be >= 1, got {instances}")
    federation_name = name or _scenario_name(scenario_path)
    specs: list[InstanceSpec] = []
    for index in range(1, instances + 1):
        defaults = instance_defaults(index)
        command = [
            str(python),
            LAUNCH_SCRIPT,
            "--instance",
            str(index),
            "--source-ssp",
            _display_path(source_ssp),
            "--out-dir",
            _display_path(out_dir),
            "--offset-north-km",
            str(float(defaults["offset_north_km"])),
            "--offset-east-km",
            str(float(defaults["offset_east_km"])),
        ]
        if stop_time is not None:
            command += ["--stop-time", str(float(stop_time))]
        if realtime:
            command.append("--realtime")
        specs.append(
            InstanceSpec(
                name=f"instance-{index}",
                command=command,
                cwd=Path("."),
                entities=[
                    EntityRef(
                        site=ENTITY_SITE,
                        application=ENTITY_APPLICATION,
                        entity=str(index),
                    )
                ],
                telemetry=[Endpoint.udp(int(defaults["telemetry_port"]))],
                control=[Endpoint.udp(int(defaults["control_port"]))],
            )
        )
    return FederationSpec(name=federation_name, instances=specs).validate()


def load_spec(path: Path | str = DEFAULT_MANIFEST) -> FederationSpec:
    """Read a manifest and validate it with ``pysos_coordinate``."""

    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return FederationSpec.from_json(data)


def write_manifest(spec: FederationSpec, path: Path | str = DEFAULT_MANIFEST) -> Path:
    """Write the canonical JSON form of ``spec``."""

    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(spec.to_json(), indent=2) + "\n", encoding="utf-8")
    return destination
