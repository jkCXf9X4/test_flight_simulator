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

What the build now does inside `3rd_party/airplane`:

- regenerates architecture-derived interfaces
- exports the Modelica subsystem FMUs with OpenModelica
- builds the native C++ `FlightGearBridge` FMI 2.0 co-simulation FMU
- verifies the bridge FMU with a UDP socket regression test
- regenerates the SSD and packages `build/ssp/aircraft.ssp`

## Interactive target architecture

The intended interactive runtime is:

`FlightGear <-> FlightGearBridge <-> ssp4sim SSP`

Where:

- `ssp4sim` remains the simulation engine and co-simulation master.
- `FlightGear` provides the visual frontend and pilot I/O.
- `FlightGearBridge` is the adapter layer that translates between simulation signals and FlightGear generic socket messages.

The first implementation target is FlightGear `generic` communication rather than native protocol packing, because it keeps the exchanged signals explicit during integration.

## Current FlightGearBridge implementation

`FlightGearBridge` is now implemented as a native FMI 2.0 co-simulation FMU in C++ rather than relying on the placeholder Modelica implementation.

Current behavior:

- outbound telemetry is emitted as a UDP generic packet from the FMU once per communication step
- inbound control packets are read non-blocking by the FMU once per communication step
- the control packet currently accepts a minimal four-field format:
  `stick_pitch_norm,stick_roll_norm,rudder_norm,throttle_norm`
- if additional fields are supplied, the FMU also accepts:
  `throttle_aux_norm,button_mask,hat_x,hat_y,mode_switch,reserved`

FlightGear protocol definitions for this packet format are stored under:

- `flightgear/Protocol/ssp_aircraft_state.xml`
- `flightgear/Protocol/ssp_aircraft_controls.xml`

Implementation/build notes:

- the FMU is built from `3rd_party/airplane/native/flightgear_bridge/`
- the generated FMU is written to `3rd_party/airplane/build/fmus/Aircraft_FlightGearBridge.fmu`
- the shared library exports the standard FMI 2 `fmi2*` entry points so `pyssp4sim` can import it directly
- `3rd_party/airplane/tests/test_flightgear_bridge_fmu.py` is the regression test that checks UDP send/receive on the native bridge

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

The aircraft package now includes the native bridge in the packaged SSP workflow:

- the dedicated `FlightGearBridge` component is part of the aircraft architecture and SSD
- the bridge is packaged as a native C++ FMU alongside the Modelica-exported subsystem FMUs
- bridge-produced pilot commands enter through `ControlInterface`
- top-level scripts build the SSP and can run a scenario while the bridge emits live UDP telemetry

## Expected next implementation steps

1. Add a top-level FlightGear launch/run script for realtime interactive sessions.
2. Document the expected reference origin and runtime port configuration for non-default environments.
3. Add a more complete FlightGear property/protocol mapping and operator runbook.
