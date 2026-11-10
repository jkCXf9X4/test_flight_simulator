# AGENTS

Test workspace for the flight-sim interactive simulation stack. Runs the `ssp_airplane` airplane SSP through `ssp4sim`, with a Podman/ROS2 container stack for the live RViz workflow.

Key scripts:
- `scripts/check_environment.sh` — validate host prerequisites (`--live-container`)
- `scripts/build_airplane.py` — build the airplane SSP/FMUs and refresh the local `build/ssp` bundle
- `scripts/build_ros2_container.sh` — build the Podman ROS2 image
- `scripts/run_full_stack_container.sh` — run the live containerized stack
- `scripts/run_airplane_scenario.py` — run a batch/realtime scenario from the local bundle
- `scripts/record_demo.sh` — record an RViz showcase movie capture
- `scripts/render_showcase_movie.py` — render the recorded capture into a movie

The aircraft model, SysML architecture, and SSP/FMU build pipeline live in `3rd_party/airplane` (git submodule, handled separately).

Use the workspace venv for Python: `/home/eriro/pwa/2_work/flight_sim/venv/bin/python3`.
