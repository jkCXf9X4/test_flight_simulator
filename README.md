# test_flight_simulator

Top-level workspace for running the airplane SSP and evolving the interactive simulation stack around it.

## Layout

- `3rd_party/airplane` contains the aircraft model, SysML architecture, Modelica models, and SSP/FMU build pipeline.
- `docs` contains top-repo operational documentation for building and running the simulation stack.
- `scripts` contains top-repo helper scripts that wrap common airplane build and scenario commands.

## Entry points

- Build the aircraft package: `./scripts/build_airplane.sh`
- Run a waypoint scenario: `./scripts/run_airplane_scenario.sh resources/scenarios/test_scenario.json`
- Read the simulation runbook: `docs/simulation_workflow.md`

## Interactive direction

The current recommended interactive direction keeps `ssp4sim` as the simulation master and uses `FlightGear` as the visual and pilot-I/O frontend via a dedicated bridge component. The first timing approach should use `ssp4sim` realtime execution as-is rather than adding new synchronization methods to the Python API. Repo-level operational notes live in `docs/simulation_workflow.md`; aircraft-level design notes live in `3rd_party/airplane/docs/flightgear_bridge.md`.
