#!/usr/bin/env python3
"""Rebuild the aircraft artifacts and refresh the local SSP bundle.

The aircraft build needs an interpreter that has the pyssp/pyfmi stack
installed. Resolution order: ``$PYTHON``, the workspace venv
(``../venv/bin/python3``), the airplane venv, then the interpreter running this
script. Candidates are probed by import so a bare system python3 never gets
picked silently.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
AIRPLANE_ROOT = REPO_ROOT / "3rd_party" / "airplane"
DEFAULT_SCENARIO = AIRPLANE_ROOT / "resources" / "scenarios" / "test_scenario.json"
WORKSPACE_VENV_PYTHON = REPO_ROOT.parent / "venv" / "bin" / "python3"
AIRPLANE_VENV_PYTHON = AIRPLANE_ROOT / "venv" / "bin" / "python3"

#: Imported by the airplane build CLIs; a candidate must satisfy all of them.
BUILD_IMPORTS = ("pyssp_sysml2", "pyssp_standard", "pyssp_workflow", "pycps_sysml2")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "scenario",
        nargs="?",
        default=str(DEFAULT_SCENARIO),
        help="Scenario JSON to copy into the local build/ssp bundle.",
    )
    return parser.parse_args(argv)


def _candidates() -> list[str]:
    candidates = []
    if os.environ.get("PYTHON"):
        candidates.append(os.environ["PYTHON"])
    candidates += [str(WORKSPACE_VENV_PYTHON), str(AIRPLANE_VENV_PYTHON)]
    if sys.executable:
        candidates.append(sys.executable)
    return candidates


def _supports_build(python: str) -> bool:
    if not Path(python).is_file():
        return False
    probe = subprocess.run(
        [python, "-c", f"import {', '.join(BUILD_IMPORTS)}"],
        capture_output=True,
        check=False,
    )
    if probe.returncode != 0:
        return False
    pyfmi = Path(python).with_name("pyfmi")
    return pyfmi.is_file() or shutil.which("pyfmi") is not None


def resolve_build_python() -> str:
    for candidate in _candidates():
        if _supports_build(candidate):
            return candidate
    tried = "\n  ".join(_candidates())
    raise SystemExit(
        "no interpreter with the airplane build dependencies was found. "
        f"Set PYTHON to one that imports {', '.join(BUILD_IMPORTS)} and has pyfmi. Tried:\n  {tried}"
    )


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

    python_bin = resolve_build_python()
    print(f"build interpreter: {python_bin}", flush=True)

    run_step([python_bin, "scripts/workflows/rebuild_from_source.py", "--run-simulation"], cwd=AIRPLANE_ROOT)
    run_step(
        [python_bin, "scripts/prepare_local_bundle.py", "--scenario", str(scenario_path)],
        cwd=REPO_ROOT,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
