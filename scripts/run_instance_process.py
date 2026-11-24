#!/usr/bin/env python3
"""Prepare one instance bundle, then replace this process with its simulation.

This is the manifest ``command`` entry point. It keeps
``prepare_instance_bundle.py`` as the artifact preparer (SSP copy, RPR bind
port, offset, ssp4sim config), then ``exec``s the simulator so the process
supervised by ``pysos_coordinate.Federation`` is the simulation itself — one
process per instance, no intermediate supervisor.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
AIRPLANE_ROOT = REPO_ROOT / "3rd_party" / "airplane"

if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from prepare_instance_bundle import (
    DEFAULT_OUT_DIR,
    DEFAULT_SCENARIO,
    DEFAULT_SOURCE_SSP,
    DEFAULT_UNIX_RECORDER_ADDRESS,
    TRANSPORT_CHOICES,
    default_unix_bind_address,
    instance_defaults,
    prepare_instance,
    resolve_env_transport,
)


def _env_int(name: str) -> int | None:
    value = os.environ.get(name)
    if value is None or not value.strip():
        return None
    try:
        return int(value)
    except ValueError as exc:
        raise SystemExit(f"{name} must be an integer, got {value!r}") from exc


def _env_scenario() -> str | None:
    value = os.environ.get("PYSOS_SCENARIO")
    return value.strip() if value and value.strip() else None


def _instance_name_from_bind_address(address: str) -> str:
    """Derive a stable bundle name from a unix bind address (no port needed)."""

    raw = address[1:] if address.startswith("@") else Path(address).name
    raw = raw.removesuffix(".sock")
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "-", raw).strip("-._")
    if not cleaned:
        raise SystemExit(
            f"--bind-address {address!r} yields no instance name; pass --instance"
        )
    return cleaned if cleaned.startswith("instance-") else f"instance-{cleaned}"


def _instance_from_bind_port(port: int) -> int:
    """Recover the 1-based index from the manifest's per-instance bind port plan."""

    offset = port - int(instance_defaults(1)["telemetry_port"])
    if offset < 0 or offset % 2:
        raise SystemExit(f"PYSOS_TELEMETRY_PORT={port} is outside the instance bind port plan")
    index = offset // 2 + 1
    if int(instance_defaults(index)["telemetry_port"]) != port:
        raise SystemExit(f"PYSOS_TELEMETRY_PORT={port} is outside the instance bind port plan")
    return index


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--instance",
        type=int,
        default=None,
        help="1-based instance index (required for unix; otherwise derived from PYSOS_TELEMETRY_PORT).",
    )
    parser.add_argument("--source-ssp", type=Path, default=DEFAULT_SOURCE_SSP, help="Prepared source SSP archive.")
    parser.add_argument("--variant", default=None, help="Per-variant SSP stem under the variant directory.")
    parser.add_argument(
        "--variant-dir",
        type=Path,
        default=None,
        help="Directory holding variant SSPs (default: build/ssp/variants).",
    )
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR, help="Directory for instance bundles.")
    parser.add_argument("--telemetry-port", type=int, default=None, help="Per-instance RPR bind UDP port (overrides PYSOS_TELEMETRY_PORT).")
    parser.add_argument(
        "--transport",
        choices=TRANSPORT_CHOICES,
        default=None,
        help="RPR transport: Unix datagram sockets (default) or UDP (escape hatch); defaults to PYSOS_TRANSPORT.",
    )
    parser.add_argument(
        "--bind-address",
        default=None,
        help="RPR bind address; in unix mode '/abs/path.sock' or '@abstract-name'.",
    )
    parser.add_argument(
        "--peer-address",
        default=None,
        help="RPR peer address; in unix mode '/abs/path.sock' or '@abstract-name'.",
    )
    parser.add_argument("--offset-north-km", type=float, default=None, help="Shift initX_km by this many kilometres.")
    parser.add_argument("--offset-east-km", type=float, default=None, help="Shift initY_km by this many kilometres.")
    parser.add_argument("--stop-time", type=float, default=None, help="Stop time in seconds.")
    parser.add_argument("--scenario", default=None, help="Scenario JSON stem (overrides PYSOS_SCENARIO).")
    parser.add_argument("--realtime", action="store_true", help="Pace the instance against the wall clock.")
    parser.add_argument(
        "--waypoint-frame",
        choices=("local", "federation"),
        default="local",
        help="Keep scenario waypoints in their own local frame, or translate them into the federation frame.",
    )
    parser.add_argument("--reference-latitude-deg", type=float, default=None, help="Wire origin latitude.")
    parser.add_argument("--reference-longitude-deg", type=float, default=None, help="Wire origin longitude.")
    parser.add_argument("--reference-altitude-m", type=float, default=None, help="Wire origin altitude.")
    parser.add_argument("--entity-site", default=None, help="Entity site in the RPR payload.")
    parser.add_argument("--entity-application", default=None, help="Entity application in the RPR payload.")
    parser.add_argument("--entity", default=None, help="Entity number in the RPR payload.")
    parser.add_argument("--marking", default=None, help="Entity marking in the RPR payload.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    env_transport, env_bind, env_peer = resolve_env_transport()
    transport = args.transport if args.transport is not None else env_transport
    unix = transport == "unix"
    bind_address = args.bind_address
    if bind_address is None and unix:
        bind_address = env_bind
    peer_address = args.peer_address
    if peer_address is None and unix:
        peer_address = env_peer
    telemetry_env = None if unix else _env_int("PYSOS_TELEMETRY_PORT")
    index = args.instance
    instance_name = None
    if index is None:
        if unix:
            if args.variant is None:
                raise SystemExit(
                    "--transport unix without --instance requires --variant: "
                    "no port derives the index, and the variant owns identity"
                )
            bind_address = bind_address or default_unix_bind_address(args.variant, 1)
            peer_address = peer_address or DEFAULT_UNIX_RECORDER_ADDRESS
            instance_name = _instance_name_from_bind_address(bind_address)
            index = 1
        else:
            if telemetry_env is None:
                raise SystemExit("--instance is required when PYSOS_TELEMETRY_PORT is unset")
            index = _instance_from_bind_port(telemetry_env)
    if args.variant is None:
        scenario = args.scenario or _env_scenario() or DEFAULT_SCENARIO
    else:
        # A variant archive owns its scenario parameter set, so a missing
        # PYSOS_SCENARIO must not fall back to the baseline scenario.
        scenario = args.scenario or _env_scenario()
    summary = prepare_instance(
        index,
        args.source_ssp,
        args.out_dir,
        telemetry_port=None
        if unix
        else (args.telemetry_port if args.telemetry_port is not None else telemetry_env),
        transport=transport,
        bind_address=bind_address,
        peer_address=peer_address,
        instance_name=instance_name,
        offset_north_km=args.offset_north_km,
        offset_east_km=args.offset_east_km,
        stop_time=args.stop_time,
        scenario=scenario,
        realtime=args.realtime,
        waypoint_frame=args.waypoint_frame,
        reference_latitude_deg=args.reference_latitude_deg,
        reference_longitude_deg=args.reference_longitude_deg,
        reference_altitude_m=args.reference_altitude_m,
        entity_site=args.entity_site if args.entity_site is not None else "1",
        entity_application=args.entity_application if args.entity_application is not None else "1",
        entity=args.entity,
        marking=args.marking if args.marking is not None else "",
        variant=args.variant,
        variant_dir=args.variant_dir,
    )
    print(json.dumps(summary, sort_keys=True), flush=True)

    python = sys.executable or "python3"
    env = os.environ.copy()
    pythonpath = env.get("PYTHONPATH")
    env["PYTHONPATH"] = str(AIRPLANE_ROOT) if not pythonpath else f"{AIRPLANE_ROOT}:{pythonpath}"
    command = [python, "-m", "scripts.cli.scenarios_run_ssp4sim", "--config-path", summary["config"]]
    os.execvpe(python, command, env)
    return 0  # pragma: no cover - exec never returns


if __name__ == "__main__":
    raise SystemExit(main())
