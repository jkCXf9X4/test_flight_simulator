# Simulation workflow

This repository uses the airplane package in `3rd_party/airplane` as the simulation core. The top repo stores the operational entry points used to build, run, and evolve the simulation workflow.

## Supported workflows

The repository supports:

1. Build the aircraft FMUs/SSD/SSP.
2. Seed a local `build/ssp` simulation bundle.
3. Run that local bundle through `ssp4sim`.
4. Launch the live Rerun viewer on the host or through Podman.
5. Post-process and inspect the generated results.

Top-level wrappers:

- `./scripts/build_airplane.py`
- `./scripts/run_airplane_scenario.py`
- `./scripts/run_rerun_stack.sh`
- `./scripts/build_rerun_container.sh`
- `./scripts/container_rerun_smoke.sh`
- `./scripts/send_pilot_command.py`
- `./scripts/check_environment.sh` (`--live-container` checks Podman, the Rerun image, and X11; `--source-build` checks the airplane build dependencies)

Recommended live workflow:

```bash
./scripts/build_airplane.py
./scripts/run_rerun_stack.sh
```

What the build now does inside `3rd_party/airplane`:

- regenerates architecture-derived interfaces
- exports the Modelica subsystem FMUs with OpenModelica
- builds the native C++ bridge FMI 2.0 co-simulation FMU
- verifies the bridge FMU with a UDP socket regression test
- regenerates the SSD and packages `build/ssp/aircraft.ssp`
- copies the baseline SSP into the top-level `build/ssp`
- copies the selected scenario into the top-level `build/ssp/scenario.json`
- writes top-level `build/ssp/config.json` and `build/ssp/config.realtime.json`

## Rerun viewer

The supported live visualization is ROS-free. `ssp4sim` stays on the host, the native bridge FMU keeps emitting the existing newline-delimited JSON telemetry on UDP 5501, and `dis_viewer` renders it with Rerun.

```bash
# Host viewer, repo venv (default)
./scripts/build_airplane.py
./scripts/run_rerun_stack.sh

# View in the Podman image instead
./scripts/build_rerun_container.sh
RERUN_CONTAINER=1 ./scripts/run_rerun_stack.sh
```

- `run_rerun_stack.sh` starts `./scripts/run_airplane_scenario.py --realtime`, waits for `build/results/scenario_results_realtime.csv` to advance instead of sleeping, then runs `python -m dis_viewer --source json-udp --sink rerun --spawn --scenario 3rd_party/airplane/resources/scenarios/test_scenario.json --record build/results/dis_viewer.jsonl`.
- Host execution uses the repo venv. `RERUN_CONTAINER=1` runs the same command inside `Containerfile.rerun` with X11 mounts and `--network=host`, so UDP stays on loopback.
- Manual pilot input goes through the pilot shim: `./scripts/send_pilot_command.py --pitch 0.2 --roll -0.1 --throttle 0.7 --duration 5` sends JSON control packets to UDP 5502.
- Headless check, no X11 and no Podman: `./scripts/container_rerun_smoke.sh` writes `/tmp/smoke.rrd` and prints PASS/FAIL.
- Every live run also writes `build/results/dis_viewer.jsonl`; replay it with `python -m dis_viewer --source jsonl --path build/results/dis_viewer.jsonl --sink rerun --spawn`.

## Retired: ROS 2 / RViz viewer

The earlier ROS 2 / RViz runtime has been retired and replaced by the Rerun viewer. Use `./scripts/run_rerun_stack.sh` for live visualization. The native `Ros2UdpBridge` FMU keeps its historical name because the UDP JSON telemetry/control contract is unchanged.

## Current bridge implementation

The bridge is a native FMI 2.0 co-simulation FMU in C++ (`Ros2UdpBridge`) that acts as a UDP telemetry/control adapter, emitting newline-delimited JSON state packets. The name is a legacy identifier kept so the UDP contract and SSP members stay stable; it no longer implies a ROS 2 dependency.

Current behavior:

- outbound telemetry is emitted as a UDP JSON packet from the FMU once per communication step
- inbound control packets are read non-blocking by the FMU once per communication step
- control packets are JSON objects carrying the `PilotCommand` fields
- when no fresh control packets arrive, the bridge marks itself inactive so `ControlInterface` falls back to the scripted/manual default path

Containerized viewer behavior:

- `./scripts/check_environment.sh --live-container` validates Podman, the built Rerun image (`test-flight-simulator-rerun`), and the X11 requirements before launch
- `./scripts/build_airplane.py [scenario-json]` refreshes the local SSP bundle used by both batch and live runs
- `./scripts/build_rerun_container.sh` builds the reusable Podman Rerun image from `Containerfile.rerun`
- `./scripts/run_rerun_stack.sh` runs the realtime simulation on the host and starts the viewer either on the host (default) or, with `RERUN_CONTAINER=1`, in the container with X11 mounts and host networking
- `./scripts/container_rerun_smoke.sh` runs the headless Rerun recording check without X11 or Podman
- `./scripts/run_airplane_scenario.py` only runs `pyssp4sim` against the prepared local config and does not repackage scenario artifacts
- use `./scripts/run_airplane_scenario.py --realtime` when you want the local realtime config without a viewer

Implementation/build notes:

- the FMU is built from `3rd_party/airplane/models/ros2_udp_bridge/native/`
- the generated FMU is written to `3rd_party/airplane/build/fmus/Ros2UdpBridge.fmu`
- the shared library exports the standard FMI 2 `fmi2*` entry points so `pyssp4sim` can import it directly
- `3rd_party/airplane/tests/test_ros2_udp_bridge_fmu.py` now verifies the JSON bridge packet and control pass-through path

## Timing approach

The first realtime implementation should use the existing `ssp4sim` realtime execution option to pace the simulation.

For now, do not add new synchronization methods to the `pyssp4sim` API and do not introduce a separate external package sync layer just to establish timing.

Planned follow-up work, but explicitly not part of the initial implementation:

1. Add a `doStep(t)` style method to the Python API so the caller can drive step timing explicitly.
2. Add support for synchronizing against an external package or external clock source when the bridge/runtime requirements justify it.

## Where design ownership lives

- Repo-level operational workflow: this document
- Aircraft-side architecture notes: `3rd_party/airplane/architecture/aircraft.sysml`

## Current aircraft adaptation status

The aircraft package now includes the native bridge in the packaged SSP workflow:

- the dedicated `Ros2UdpBridge` component is part of the aircraft architecture and SSD
- the bridge is packaged as a native C++ FMU alongside the Modelica-exported subsystem FMUs
- bridge-produced pilot commands enter through `ControlInterface`
- top-level scripts build the SSP and can run a scenario while the bridge emits live UDP telemetry

## Expected next implementation steps

The ROS 2 / RViz runtime removal is complete. Remaining follow-up work is tracked in `TODO.md`.

## Multi-instance runs

`scripts/prepare_instance_bundle.py` copies the prepared SSP, rewrites the bound
`MissionScenario.ssv`/`HighAltitudeIntercept.ssm` members with per-instance
`ros2_udp_bridge.telemetry_port`, `ros2_udp_bridge.control_port` and shifted
`initX_km`/`initY_km`, then writes a per-instance ssp4sim config. The source SSP
and `config.json` are the only inputs, so this works from a clean `build/ssp`.

```bash
PY=/home/eriro/pwa/2_work/flight_sim/venv/bin/python3
$PY scripts/prepare_instance_bundle.py --instance 1 --stop-time 60
$PY scripts/prepare_instance_bundle.py --instance 2 --stop-time 60
$PY scripts/run_instances.py --instances 2 --stop-time 60
```

`run_instances.py` prepares and launches all instances concurrently with
`PYTHONPATH=3rd_party/airplane`, waits for them, and reports exit codes. Add
`--realtime` to pace against the wall clock instead of running as fast as
possible.

Port map (defaults: telemetry `5501 + 2*(index-1)`, control = telemetry + 1,
east offset `(index-1)*5 km`, north offset 0):

| instance | telemetry | control | init offset (north, east) |
| --- | --- | --- | --- |
| 1 | 5501 | 5502 | 0, 0 km |
| 2 | 5503 | 5504 | 0, +5 km |

Each instance writes to `build/ssp/instances/instance-<N>/` (its own SSP,
`config.json`, `work/`, result CSV, and log). The local origin is still scenario
`points[0]` and is shared by every instance; the bridge's `reference_*` fields
stay at their defaults and are not used for framing. Only the initial offset and
the ports differ between instances.
