# Simulation workflow

This repository uses the airplane package in `3rd_party/airplane` as the simulation core. The top repo stores the operational entry points used to build, run, and evolve the simulation workflow.

## Current supported workflow

The currently working path is the batch SSP workflow:

1. Build the aircraft FMUs/SSD/SSP.
2. Run a scenario through `ssp4sim`.
3. Post-process and inspect the generated results.

Top-level wrappers:

- `./scripts/build_airplane.sh`
- `./scripts/run_airplane_scenario.sh <scenario-json>`

Example:

```bash
./scripts/build_airplane.sh
./scripts/run_airplane_scenario.sh resources/scenarios/test_scenario.json
```

## Interactive target architecture

The intended interactive runtime is:

`FlightGear <-> FlightGearBridge <-> ssp4sim SSP`

Where:

- `ssp4sim` remains the simulation engine and co-simulation master.
- `FlightGear` provides the visual frontend and pilot I/O.
- `FlightGearBridge` is the adapter layer that translates between simulation signals and FlightGear generic socket messages.

The first implementation target is FlightGear `generic` communication rather than native protocol packing, because it keeps the exchanged signals explicit during integration.

## Timing approach

The first realtime implementation should use the existing `ssp4sim` realtime execution option to pace the simulation.

For now, do not add new synchronization methods to the `pyssp4sim` API and do not introduce a separate external package sync layer just to establish timing.

Planned follow-up work, but explicitly not part of the initial implementation:

1. Add a `doStep(t)` style method to the Python API so the caller can drive step timing explicitly.
2. Add support for synchronizing against an external package or external clock source when the bridge/runtime requirements justify it.

## Where design ownership lives

- Repo-level operational workflow: this document
- Aircraft-side integration design: `3rd_party/airplane/docs/flightgear_bridge.md`
- Aircraft-side architecture notes: `3rd_party/airplane/architecture/simulation.sysml`

## Current aircraft adaptation status

The aircraft package has started adapting toward the interactive design:

- a dedicated `FlightGearBridge` component is being introduced into the aircraft architecture
- the manual control path is being refactored so bridge-provided commands can enter through `ControlInterface`

The bridge runtime itself is not fully implemented yet. Current top-level scripts are focused on building and running the existing airplane simulation consistently from the parent repo.

## Expected next implementation steps

1. Add a runnable bridge process at the top repo level for using `ssp4sim` realtime execution and exchanging FlightGear generic messages.
2. Extend the aircraft package so the bridge-facing component can be exported and packaged cleanly with the rest of the system.
3. Add a FlightGear launch script and a documented property/protocol mapping.
