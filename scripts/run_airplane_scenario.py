#!/usr/bin/env python3
"""Run the prepared local SSP bundle through pyssp4sim."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
AIRPLANE_ROOT = REPO_ROOT / "3rd_party" / "airplane"
LOCAL_BUNDLE_DIR = REPO_ROOT / "build" / "ssp"
DEFAULT_CONFIG_PATH = LOCAL_BUNDLE_DIR / "config.json"
DEFAULT_REALTIME_CONFIG_PATH = LOCAL_BUNDLE_DIR / "config.realtime.json"
RUNTIME_CONFIG_PATH = LOCAL_BUNDLE_DIR / "config.runtime.json"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--realtime", action="store_true", help="Run the prepared realtime config.")
    parser.add_argument("--stop-time", type=float, default=None, help="Override stop time for this run only.")
    return parser.parse_args(argv)


def resolve_airplane_python() -> str:
    venv_python = AIRPLANE_ROOT / "venv" / "bin" / "python3"
    if venv_python.exists():
        return str(venv_python)

    python = shutil.which("python3")
    if python is None:
        raise SystemExit("python3 is not available on PATH.")
    return python


def load_local_config(realtime: bool) -> Path:
    config_path = DEFAULT_REALTIME_CONFIG_PATH if realtime else DEFAULT_CONFIG_PATH
    if not config_path.exists():
        raise SystemExit(
            f"Local simulation config not found: {config_path}\n"
            "Run ./scripts/build_airplane.py first to prepare ./build/ssp."
        )
    return config_path


def write_runtime_override(base_config_path: Path, stop_time: float) -> Path:
    config = json.loads(base_config_path.read_text(encoding="utf-8"))
    config["simulation"]["stop_time"] = float(stop_time)
    RUNTIME_CONFIG_PATH.write_text(json.dumps(config, indent=2), encoding="utf-8")
    return RUNTIME_CONFIG_PATH


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    config_path = load_local_config(args.realtime)
    if args.stop_time is not None:
        config_path = write_runtime_override(config_path, args.stop_time)

    python_bin = resolve_airplane_python()
    env = os.environ.copy()
    pythonpath = env.get("PYTHONPATH")
    env["PYTHONPATH"] = str(AIRPLANE_ROOT) if not pythonpath else f"{AIRPLANE_ROOT}:{pythonpath}"

    subprocess.run(
        [python_bin, "-m", "scripts.cli.scenarios_run_ssp4sim", "--config-path", str(config_path)],
        cwd=REPO_ROOT,
        check=True,
        env=env,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
