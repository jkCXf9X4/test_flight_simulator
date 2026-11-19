#!/usr/bin/env python3
"""Prepare and run several aircraft instances concurrently from the local bundle.

Each instance gets its own SSP copy, telemetry/control ports, initial offset,
working directory, CSV, and log (see ``prepare_instance_bundle.py``). All
instances are launched together and awaited; their exit codes are reported.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
AIRPLANE_ROOT = REPO_ROOT / "3rd_party" / "airplane"
WORKSPACE_VENV_PYTHON = REPO_ROOT.parent / "venv" / "bin" / "python"

if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from prepare_instance_bundle import DEFAULT_OUT_DIR, DEFAULT_SOURCE_SSP, prepare_instance  # noqa: E402


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--instances", type=int, default=2, help="Number of concurrent instances.")
    parser.add_argument("--source-ssp", type=Path, default=DEFAULT_SOURCE_SSP, help="Prepared source SSP archive.")
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR, help="Directory for instance bundles.")
    parser.add_argument("--stop-time", type=float, default=None, help="Stop time in seconds for every instance.")
    parser.add_argument("--realtime", action="store_true", help="Pace instances against the wall clock.")
    parser.add_argument("--python", type=Path, default=None, help="Interpreter used for the simulations.")
    return parser.parse_args(argv)


def resolve_python(override: Path | None) -> str:
    if override is not None:
        return str(override)
    if WORKSPACE_VENV_PYTHON.exists():
        return str(WORKSPACE_VENV_PYTHON)
    airplane_python = AIRPLANE_ROOT / "venv" / "bin" / "python3"
    if airplane_python.exists():
        return str(airplane_python)
    return sys.executable


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.instances < 1:
        raise SystemExit(f"--instances must be >= 1, got {args.instances}")

    prepared = [
        prepare_instance(
            index,
            args.source_ssp,
            args.out_dir,
            stop_time=args.stop_time,
            realtime=args.realtime,
        )
        for index in range(1, args.instances + 1)
    ]

    python_bin = resolve_python(args.python)
    env = os.environ.copy()
    pythonpath = env.get("PYTHONPATH")
    env["PYTHONPATH"] = str(AIRPLANE_ROOT) if not pythonpath else f"{AIRPLANE_ROOT}:{pythonpath}"

    processes: list[tuple[dict[str, str], subprocess.Popen[bytes]]] = []
    for summary in prepared:
        command = [python_bin, "-m", "scripts.cli.scenarios_run_ssp4sim", "--config-path", summary["config"]]
        print(
            f"Launching instance {summary['instance']}: "
            f"telemetry {summary['telemetry_port']}, control {summary['control_port']}, "
            f"config {summary['config']}",
            flush=True,
        )
        process = subprocess.Popen(command, cwd=REPO_ROOT, env=env)
        processes.append((summary, process))

    exit_code = 0
    for summary, process in processes:
        code = process.wait()
        print(f"Instance {summary['instance']} exited with {code}", flush=True)
        if code != 0:
            exit_code = 1
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
