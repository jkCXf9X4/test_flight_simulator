#!/usr/bin/env python3
"""Create a stable local SSP/config bundle for repeated simulation runs."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
AIRPLANE_ROOT = REPO_ROOT / "3rd_party" / "airplane"

if str(AIRPLANE_ROOT) not in sys.path:
    sys.path.insert(0, str(AIRPLANE_ROOT))

from scripts.lib.scenarios.packaging import package_ssp_with_parameters
from scripts.lib.scenarios.preparation import estimate_duration, prepare_scenario_for_simulation
from scripts.lib.scenarios.runtime import create_simulation_config, write_simulation_config


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--scenario",
        type=Path,
        default=AIRPLANE_ROOT / "resources" / "scenarios" / "test_scenario.json",
        help="Scenario JSON used to seed the local bundle.",
    )
    parser.add_argument(
        "--source-ssp",
        type=Path,
        default=AIRPLANE_ROOT / "build" / "ssp" / "aircraft.ssp",
        help="Baseline SSP archive produced by the aircraft build chain.",
    )
    parser.add_argument(
        "--bundle-dir",
        type=Path,
        default=REPO_ROOT / "build" / "ssp",
        help="Directory where the local SSP/scenario/config bundle is written.",
    )
    parser.add_argument(
        "--results-dir",
        type=Path,
        default=REPO_ROOT / "build" / "results",
        help="Directory referenced by the generated simulator configs for result CSV output.",
    )
    parser.add_argument(
        "--bridge-input",
        action="store_true",
        help="Enable bridge/manual input in the packaged local SSP.",
    )
    return parser.parse_args(argv)


def resolve_stop_time_s(scenario: dict, total_distance_km: float, cruise_speed_mps: float) -> float:
    overrides = scenario.get("simulation_overrides", {})
    override_value = overrides.get("stop_time_s", overrides.get("stop_time"))
    if override_value is not None:
        return float(override_value)
    return float(estimate_duration(total_distance_km, cruise_speed_mps))


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    source_ssp = args.source_ssp.resolve()
    source_scenario = args.scenario.resolve()
    bundle_dir = args.bundle_dir.resolve()
    results_dir = args.results_dir.resolve()

    if not source_ssp.exists():
        raise SystemExit(f"Baseline SSP not found: {source_ssp}")
    if not source_scenario.exists():
        raise SystemExit(f"Scenario JSON not found: {source_scenario}")

    bundle_dir.mkdir(parents=True, exist_ok=True)
    results_dir.mkdir(parents=True, exist_ok=True)

    local_ssp_path = bundle_dir / "aircraft.ssp"
    local_scenario_path = bundle_dir / "scenario.json"
    local_prepared_ssp_path = bundle_dir / "scenario.ssp"
    local_config_path = bundle_dir / "config.json"
    local_realtime_config_path = bundle_dir / "config.realtime.json"
    result_file = results_dir / "scenario_results.csv"
    realtime_result_file = results_dir / "scenario_results_realtime.csv"
    config_ssp_path = Path("build/ssp/scenario.ssp")
    config_result_path = Path("build/results/scenario_results.csv")
    config_realtime_result_path = Path("build/results/scenario_results_realtime.csv")

    shutil.copy2(source_ssp, local_ssp_path)
    shutil.copy2(source_scenario, local_scenario_path)

    prepared = prepare_scenario_for_simulation(
        scenario_path=local_scenario_path,
        results_dir=bundle_dir,
        bridge_input=args.bridge_input,
    )

    generated_prepared_ssp = package_ssp_with_parameters(
        ssp_path=local_ssp_path,
        parameter_set_path=prepared.parameter_set_path,
        scenario_stem="scenario",
        results_dir=bundle_dir,
    )
    shutil.copy2(generated_prepared_ssp, local_prepared_ssp_path)

    run_dir = bundle_dir / "scenario_run"
    if run_dir.exists():
        shutil.rmtree(run_dir)

    stop_time_s = resolve_stop_time_s(prepared.scenario, prepared.total_distance_km, prepared.cruise_speed_mps)

    config = create_simulation_config(
        ssp_path=config_ssp_path,
        result_file=config_result_path,
        stop_time=stop_time_s,
        realtime=False,
    )
    write_simulation_config(config=config, result_file=config_result_path, config_path=local_config_path)

    realtime_config = create_simulation_config(
        ssp_path=config_ssp_path,
        result_file=config_realtime_result_path,
        stop_time=stop_time_s,
        realtime=True,
    )
    write_simulation_config(
        config=realtime_config,
        result_file=config_realtime_result_path,
        config_path=local_realtime_config_path,
    )

    summary = {
        "scenario_source": str(source_scenario),
        "bundle_dir": str(bundle_dir),
        "results_dir": str(results_dir),
        "local_ssp": str(local_ssp_path),
        "prepared_ssp": str(local_prepared_ssp_path),
        "scenario": str(local_scenario_path),
        "config": str(local_config_path),
        "config_realtime": str(local_realtime_config_path),
        "parameter_set": str(prepared.parameter_set_path),
        "waypoints": str(prepared.waypoints_file),
        "stop_time_s": stop_time_s,
    }
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
