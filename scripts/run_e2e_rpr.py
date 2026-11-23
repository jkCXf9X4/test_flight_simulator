#!/usr/bin/env python3
"""Run the two-instance airplane scenario through the end-to-end RPR path.

Launches the P2 federation manifest, lets each instance's ``rpr_entity`` FMU
broadcast ``rpr.v2.PhysicalEntity`` frames to the recorder on UDP 5505, records
the decoded stream, and writes the truth JSONL, metadata sidecar, measurement
CSV and ``.rrd`` under one run directory. See ``scripts/rpr_e2e.py`` for the
component wiring and the artifact layout.
"""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import instance_manifest
import rpr_e2e


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--run-dir",
        type=Path,
        default=None,
        help="Artifact directory (default: build/runs/e2e-<UTC timestamp>).",
    )
    parser.add_argument(
        "--stop-time",
        type=float,
        default=rpr_e2e.DEFAULT_STOP_TIME_S,
        help="Fixed simulated duration in seconds.",
    )
    parser.add_argument(
        "--scenario",
        type=Path,
        default=instance_manifest.SCENARIO_PATH,
        help="Scenario JSON that supplies the shared RprOrigin (points[0]).",
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=None,
        help="Run this P2 manifest instead of building it from the flags.",
    )
    parser.add_argument(
        "--instances",
        type=int,
        default=2,
        help="Number of instances when no --manifest is given.",
    )
    parser.add_argument("--python", type=Path, default=None, help="Interpreter for the instances.")
    parser.add_argument(
        "--rpr-port", type=int, default=rpr_e2e.RPR_UDP_PORT, help="Dedicated RPR UDP port."
    )
    parser.add_argument("--realtime", action="store_true", help="Pace instances against the wall clock.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    run_dir = args.run_dir
    if run_dir is None:
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        run_dir = REPO_ROOT / "build" / "runs" / f"e2e-{stamp}"

    result = rpr_e2e.run_e2e(
        run_dir=run_dir,
        stop_time=args.stop_time,
        scenario_path=args.scenario,
        manifest_path=args.manifest,
        instances=args.instances,
        python=args.python,
        rpr_port=args.rpr_port,
        realtime=args.realtime,
    )

    print(f"run: {result.run_dir}")
    for name, path in (
        ("truth", result.truth_jsonl),
        ("metadata", result.metadata_json),
        ("measure_csv", result.measure_csv),
        ("rrd", result.rrd_path),
        ("comparison", result.comparison_csv),
        ("separation", result.separation_csv),
        ("run_json", result.run_json),
    ):
        size = path.stat().st_size if path.exists() else 0
        print(f"  {name:<12} {size:>8} B  {path.name}")
    print(f"  samples      {result.samples:>8}    frames {result.frames}  partial {result.partial_samples}")
    print(
        "  separation   "
        f"min {result.separation_m['min_m']:.1f} m  "
        f"mean {result.separation_m['mean_m']:.1f} m  "
        f"max {result.separation_m['max_m']:.1f} m"
    )
    print("  paths        " + ", ".join(f"{slug}={item['path_length_m']:.1f} m" for slug, item in result.entities.items()))
    print(f"  exit codes   {result.exit_codes}  timed_out={result.timed_out}")
    ok = (
        bool(result.exit_codes)
        and all(code == 0 for code in result.exit_codes.values())
        and not result.timed_out
        and result.samples > 0
    )
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
