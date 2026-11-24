#!/usr/bin/env python3
"""Run the aircraft scenario as a federation supervised by pysos_coordinate.

The project owns scenario settings, not process supervision: this script
translates its CLI into the federation manifest (see ``instance_manifest.py``)
and hands it to ``pysos_coordinate.Federation``. Each instance command runs
``run_instance_process.py``, which prepares the per-instance bundle with
``prepare_instance_bundle.py`` and then execs the simulation.

The old single-scenario flags (``--instances``, ``--source-ssp``, ``--out-dir``,
``--stop-time``, ``--realtime``, ``--python``) keep their meaning; the generated
spec defaults to schema-2 unix (``--transport udp`` is the escape hatch);
``--manifest`` runs a checked-in manifest as-is with the project interpreter
substituted and ``--stop-time`` overriding each instance's duration if given,
and ``--dry-run`` validates without launching anything.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
AIRPLANE_ROOT = REPO_ROOT / "3rd_party" / "airplane"
WORKSPACE_VENV_PYTHON = REPO_ROOT.parent / "venv" / "bin" / "python"

if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from instance_manifest import (
    DEFAULT_MANIFEST,
    DEFAULT_OUT_DIR,
    DEFAULT_SOURCE_SSP,
    SCENARIO_PATH,
    build_spec,
    load_spec,
)
from pysos_coordinate import Federation, SpecError, SupervisorError


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--instances", type=int, default=2, help="Number of concurrent instances.")
    parser.add_argument("--source-ssp", type=Path, default=DEFAULT_SOURCE_SSP, help="Prepared source SSP archive.")
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR, help="Directory for instance bundles.")
    parser.add_argument("--stop-time", type=float, default=None, help="Stop time in seconds for every instance.")
    parser.add_argument("--realtime", action="store_true", help="Pace instances against the wall clock.")
    parser.add_argument("--python", type=Path, default=None, help="Interpreter used for the simulations.")
    parser.add_argument("--scenario", type=Path, default=SCENARIO_PATH, help="Scenario JSON that names the federation.")
    parser.add_argument(
        "--transport",
        choices=("udp", "unix"),
        default="unix",
        help="Generated-spec transport: unix datagram sockets (default) or UDP.",
    )
    parser.add_argument(
        "--unix-prefix",
        default="pysos",
        help="Abstract-socket prefix for the generated unix spec (default: pysos).",
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=None,
        help=f"Run this manifest as-is instead of translating the flags (checked in: {DEFAULT_MANIFEST.relative_to(REPO_ROOT)}).",
    )
    parser.add_argument("--log-dir", type=Path, default=None, help="Capture instance stdout/stderr here.")
    parser.add_argument("--dry-run", action="store_true", help="Build and validate the manifest, then exit without launching.")
    return parser.parse_args(argv)


def resolve_python(override: Path | None) -> str:
    if override is not None:
        return str(override)
    if WORKSPACE_VENV_PYTHON.exists():
        return str(WORKSPACE_VENV_PYTHON)
    airplane_python = AIRPLANE_ROOT / "venv" / "bin" / "python3"
    if airplane_python.exists():
        return str(airplane_python)
    return sys.executable or "python3"


def apply_python(spec, python: str):
    """Record the resolved interpreter as every instance's argv[0]."""

    for instance in spec.instances:
        instance.command[0] = python
    return spec


def apply_stop_time(spec, stop_time: float):
    """Override every instance's ``--stop-time``, keeping the flag meaningful for manifests."""

    value = str(float(stop_time))
    for instance in spec.instances:
        command = instance.command
        for index in range(len(command) - 1, -1, -1):
            if command[index] == "--stop-time":
                del command[index : index + 2]
        instance.command += ["--stop-time", value]
    return spec


def describe(spec) -> None:
    print(f"federation: {spec.name} ({len(spec.instances)} instance(s), schema {spec.schema}, timing {spec.timing.value})")
    for instance in spec.instances:
        entity = instance.entities[0] if instance.entities else None
        telemetry = instance.telemetry[0] if instance.telemetry else None
        control = instance.control[0] if instance.control else None
        print(
            f"  {instance.name:<12} telemetry={telemetry} control={control} "
            f"entity={entity if entity is not None else '-'}"
        )


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        if args.manifest is not None:
            spec = load_spec(args.manifest)
            if args.stop_time is not None:
                spec = apply_stop_time(spec, args.stop_time)
        else:
            spec = build_spec(
                instances=args.instances,
                python=resolve_python(args.python),
                source_ssp=args.source_ssp,
                out_dir=args.out_dir,
                stop_time=args.stop_time,
                realtime=args.realtime,
                scenario_path=args.scenario,
                transport=args.transport,
                unix_prefix=args.unix_prefix,
            )
        spec = apply_python(spec, resolve_python(args.python))
        spec.validate()
    except (SpecError, ValueError, OSError) as exc:
        print(f"invalid: {exc}", file=sys.stderr)
        return 1

    describe(spec)
    if args.dry_run:
        print("ok: manifest is valid; nothing launched")
        return 0

    federation = Federation(spec, log_dir=args.log_dir)
    try:
        result = federation.run()
    except SupervisorError as exc:
        print(f"launch failed: {exc}", file=sys.stderr)
        return 1
    for status in result.statuses:
        state = "running" if status.running else f"exit {status.exit_code}"
        print(f"  {status.name:<12} pid={status.pid} {state}")
    print(f"duration: {result.duration_s:.3f}s  timed_out: {result.timed_out}")
    if result.log_dir is not None:
        print(f"logs: {result.log_dir}")
    return 0 if result.ok and not result.timed_out else 1


if __name__ == "__main__":
    raise SystemExit(main())
