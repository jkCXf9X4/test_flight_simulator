# test_flight_simulator

Top-level workspace for running the airplane SSP and evolving the interactive simulation stack around it.

## Layout

- `3rd_party/airplane` contains the aircraft model, SysML architecture, Modelica models, and SSP/FMU build pipeline.
- `docs` contains top-repo operational documentation for building and running the simulation stack.
- `scripts` contains top-repo helper scripts that wrap common airplane build and scenario commands.

## Just Works

The supported live workflow is containerized.

```bash
./scripts/check_environment.sh --live-container
./scripts/build_airplane.py
./scripts/build_ros2_container.sh
./scripts/run_full_stack_container.sh
```

Seed the local bundle with a different scenario during build:

```bash
./scripts/build_airplane.py 3rd_party/airplane/resources/scenarios/test_scenario.json
```

Other useful entry points:

- Rebuild SSP/FMU artifacts and refresh the local `build/ssp` bundle: `./scripts/build_airplane.py`
- Run a batch simulation from the local bundle: `./scripts/run_airplane_scenario.py`
- Run a realtime batch simulation from the local bundle: `./scripts/run_airplane_scenario.py --realtime`
- Read the workflow notes: `docs/simulation_workflow.md`

## Interactive Direction

The supported live setup keeps `ssp4sim` as the simulation master and runs RViz plus the ROS 2 bridge runtime inside a Podman container. The bridge FMU publishes a ROS-oriented UDP packet to the Python ROS 2 companion runtime. Repo-level operational notes live in `docs/simulation_workflow.md`.
