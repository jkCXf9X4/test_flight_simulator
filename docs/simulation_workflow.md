# Simulation workflow

This repository uses the airplane package in `3rd_party/airplane` as the simulation core. The top repo stores the operational entry points used to build, run, and evolve the simulation workflow.

## Supported workflows

The repository supports:

1. Build the aircraft FMUs/SSD/SSP.
2. Seed a local `build/ssp` simulation bundle.
3. Run that local bundle through `ssp4sim`.
4. Launch the live RViz workflow through Podman.
5. Post-process and inspect the generated results.

Top-level wrappers:

- `./scripts/check_environment.sh --live-container`
- `./scripts/run_full_stack_container.sh`
- `./scripts/build_airplane.py`
- `./scripts/build_ros2_container.sh`
- `./scripts/run_airplane_scenario.py`

Recommended live workflow:

```bash
./scripts/check_environment.sh --live-container
./scripts/build_airplane.py
./scripts/build_ros2_container.sh
./scripts/run_full_stack_container.sh
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

## Interactive target architecture

The current interactive runtime is:

`RViz / ROS 2 nodes <-> ROS2 UDP companion runtime <-> bridge FMU <-> ssp4sim SSP`

Where:

- `ssp4sim` remains the simulation engine and co-simulation master.
- the native bridge FMU exports simulator state and accepts manual pilot commands.
- a Python ROS 2 runtime publishes RViz topics and forwards manual control messages back to the bridge.
- `rviz2` is the primary live visualization frontend.

## Current bridge implementation

The bridge remains a native FMI 2.0 co-simulation FMU in C++, but it now emits newline-delimited JSON state packets for a ROS 2 companion runtime rather than FlightGear generic CSV.

Current behavior:

- outbound telemetry is emitted as a UDP JSON packet from the FMU once per communication step
- inbound control packets are read non-blocking by the FMU once per communication step
- control packets are JSON objects carrying the `PilotCommand` fields
- when no fresh control packets arrive, the bridge marks itself inactive so `ControlInterface` falls back to the scripted/manual default path

Containerized launcher behavior:

- `./scripts/check_environment.sh --live-container` validates Podman, the built image, and the X11 requirements before launch
- `./scripts/build_airplane.py [scenario-json]` refreshes the local SSP bundle used by both batch and live runs
- `./scripts/build_ros2_container.sh` builds the reusable Podman image
- `./scripts/run_full_stack_container.sh` runs the local `build/ssp` scenario, ROS 2 bridge runtime, and RViz entirely inside the container with no extra arguments
- the container reuses the checked-out workspace via a bind mount and forwards X11 for RViz
- `./scripts/run_airplane_scenario.py` only runs `pyssp4sim` against the prepared local config and does not repackage scenario artifacts
- use `./scripts/run_airplane_scenario.py --realtime` when you want the local realtime config without RViz
- host-side live RViz launching has been removed from the repository

Implementation/build notes:

- the FMU is built from `3rd_party/airplane/models/flightgear_bridge/native/`
- the generated FMU is written to `3rd_party/airplane/build/fmus/Aircraft_FlightGearBridge.fmu`
- the shared library exports the standard FMI 2 `fmi2*` entry points so `pyssp4sim` can import it directly
- `3rd_party/airplane/tests/test_flightgear_bridge_fmu.py` now verifies the JSON bridge packet and control pass-through path

## Timing approach

The first realtime implementation should use the existing `ssp4sim` realtime execution option to pace the simulation.

For now, do not add new synchronization methods to the `pyssp4sim` API and do not introduce a separate external package sync layer just to establish timing.

Planned follow-up work, but explicitly not part of the initial implementation:

1. Add a `doStep(t)` style method to the Python API so the caller can drive step timing explicitly.
2. Add support for synchronizing against an external package or external clock source when the bridge/runtime requirements justify it.

## Where design ownership lives

- Repo-level operational workflow: this document
- Aircraft-side architecture notes: `3rd_party/airplane/architecture/simulation.sysml`

## Current aircraft adaptation status

The aircraft package now includes the native bridge in the packaged SSP workflow:

- the dedicated `FlightGearBridge` component is part of the aircraft architecture and SSD
- the bridge is packaged as a native C++ FMU alongside the Modelica-exported subsystem FMUs
- bridge-produced pilot commands enter through `ControlInterface`
- top-level scripts build the SSP and can run a scenario while the bridge emits live UDP telemetry

## Expected next implementation steps

1. Simplify the bridge/FMUs naming away from the historical FlightGear identifier.
2. Add a ROS-native operator runbook for manual command publishers and RViz usage.
