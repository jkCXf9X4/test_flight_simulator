#!/usr/bin/env python3
"""Generate (or check) the checked-in federation manifest.

The manifest is a build artifact of the project scenario settings, not a
hand-maintained file. Regenerate it after changing the scenario, the instance
layout, or the launch command::

    venv/bin/python scripts/generate_instance_manifest.py

``--check`` exits non-zero when the checked-in file no longer matches what the
generator would write, which is how the test suite keeps it honest.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from instance_manifest import (
    DEFAULT_MANIFEST,
    DEFAULT_OUT_DIR,
    DEFAULT_PYTHON,
    DEFAULT_SOURCE_SSP,
    SCENARIO_PATH,
    build_spec,
    write_manifest,
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--scenario", type=Path, default=SCENARIO_PATH, help="Scenario JSON that names the federation.")
    parser.add_argument("--instances", type=int, default=2, help="Number of instances in the federation.")
    parser.add_argument("--python", default=DEFAULT_PYTHON, help="Interpreter recorded as command[0] (portable default: python3).")
    parser.add_argument("--source-ssp", type=Path, default=DEFAULT_SOURCE_SSP, help="Prepared source SSP archive.")
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR, help="Directory for per-instance bundles.")
    parser.add_argument("--stop-time", type=float, default=None, help="Stop time recorded in every launch command.")
    parser.add_argument("--realtime", action="store_true", help="Record realtime pacing in every launch command.")
    parser.add_argument("--out", type=Path, default=DEFAULT_MANIFEST, help="Manifest path to write or check.")
    parser.add_argument(
        "--transport",
        choices=("udp", "unix"),
        default="unix",
        help="Manifest transport (default: unix, schema 2; '--transport udp' is the schema-1 escape hatch).",
    )
    parser.add_argument("--unix-prefix", default="pysos", help="Abstract-socket prefix for a schema-2 unix manifest.")
    parser.add_argument("--check", action="store_true", help="Fail when --out differs from the generated manifest.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    spec = build_spec(
        instances=args.instances,
        python=args.python,
        source_ssp=args.source_ssp,
        out_dir=args.out_dir,
        stop_time=args.stop_time,
        realtime=args.realtime,
        scenario_path=args.scenario,
        transport=args.transport,
        unix_prefix=args.unix_prefix,
    )
    expected = json.dumps(spec.to_json(), indent=2) + "\n"
    if args.check:
        try:
            actual = args.out.read_text(encoding="utf-8")
        except OSError:
            actual = None
        if actual != expected:
            print(f"stale: {args.out} (regenerate with scripts/generate_instance_manifest.py)", file=sys.stderr)
            return 1
        print(f"ok: {args.out} is up to date")
        return 0
    write_manifest(spec, args.out)
    print(f"wrote {args.out} ({spec.name}, {len(spec.instances)} instance(s), schema {spec.schema})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
