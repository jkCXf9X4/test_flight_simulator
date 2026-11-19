#!/usr/bin/env python3
"""Prepare one instance bundle, then replace this process with its simulation.

This is the manifest ``command`` entry point. It keeps
``prepare_instance_bundle.py`` as the artifact preparer (SSP copy, ports, offset,
ssp4sim config), then ``exec``s the simulator so the process supervised by
``pysos_coordinate.Federation`` is the simulation itself — one process per
instance, no intermediate supervisor.
"""

from __future__ import annotations

import argparse
import json
import os
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
    prepare_instance,
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--instance", type=int, required=True, help="1-based instance index.")
    parser.add_argument("--source-ssp", type=Path, default=DEFAULT_SOURCE_SSP, help="Prepared source SSP archive.")
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR, help="Directory for instance bundles.")
    parser.add_argument("--offset-north-km", type=float, default=None, help="Shift initX_km by this many kilometres.")
    parser.add_argument("--offset-east-km", type=float, default=None, help="Shift initY_km by this many kilometres.")
    parser.add_argument("--stop-time", type=float, default=None, help="Stop time in seconds.")
    parser.add_argument("--realtime", action="store_true", help="Pace the instance against the wall clock.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    summary = prepare_instance(
        args.instance,
        args.source_ssp,
        args.out_dir,
        offset_north_km=args.offset_north_km,
        offset_east_km=args.offset_east_km,
        stop_time=args.stop_time,
        realtime=args.realtime,
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
