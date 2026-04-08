#!/usr/bin/env python3
"""Rebuild the aircraft artifacts and refresh the local SSP bundle."""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
AIRPLANE_ROOT = REPO_ROOT / "3rd_party" / "airplane"
DEFAULT_SCENARIO = AIRPLANE_ROOT / "resources" / "scenarios" / "test_scenario.json"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "scenario",
        nargs="?",
        default=str(DEFAULT_SCENARIO),
        help="Scenario JSON to copy into the local build/ssp bundle.",
    )
    return parser.parse_args(argv)


def resolve_airplane_python() -> str:
    venv_python = AIRPLANE_ROOT / "venv" / "bin" / "python3"
    if venv_python.exists():
        return str(venv_python)

    python = shutil.which("python3")
    if python is None:
        raise SystemExit("python3 is not available on PATH.")
    return python


def run_step(cmd: list[str], cwd: Path) -> None:
    subprocess.run(cmd, cwd=cwd, check=True)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    scenario_path = Path(args.scenario)
    if not scenario_path.is_absolute():
        scenario_path = (REPO_ROOT / scenario_path).resolve()
    else:
        scenario_path = scenario_path.resolve()

    if not scenario_path.exists():
        raise SystemExit(f"Scenario JSON not found: {scenario_path}")

    python_bin = resolve_airplane_python()

    run_step([python_bin, "scripts/workflows/rebuild_from_source.py"], cwd=AIRPLANE_ROOT)
    run_step(
        [python_bin, "scripts/prepare_local_bundle.py", "--scenario", str(scenario_path)],
        cwd=REPO_ROOT,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
