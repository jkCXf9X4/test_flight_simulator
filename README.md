# test_flight_simulator

Top-level workspace for running the airplane SSP and evolving the interactive simulation stack around it.

## Layout

- `3rd_party/airplane` contains the aircraft model, SysML architecture, Modelica models, and SSP/FMU build pipeline.
- `docs` contains top-repo operational documentation for building and running the simulation stack.
- `scripts` contains top-repo helper scripts that wrap common airplane build and scenario commands.

## Entry points

- Build the aircraft package: `./scripts/build_airplane.sh`
- Build the ROS 2 Podman image: `./scripts/build_ros2_container.sh`
- Run a waypoint scenario: `./scripts/run_airplane_scenario.sh resources/scenarios/test_scenario.json`
- Launch the ROS 2 + RViz session: `./scripts/run_rviz_session.sh`
- Launch the simulator + ROS 2 + RViz entirely inside Podman: `./scripts/run_full_stack_container.sh`
- Read the simulation runbook: `docs/simulation_workflow.md`

## Interactive direction

The current recommended interactive direction keeps `ssp4sim` as the simulation master and uses a ROS 2 / RViz sidecar for visualization plus optional manual-control pass-through. The bridge FMU now publishes a ROS-oriented UDP packet to a Python ROS 2 companion runtime rather than speaking FlightGear directly. Repo-level operational notes live in `docs/simulation_workflow.md`.
