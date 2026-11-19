# AGENTS

Test workspace for the flight-sim interactive simulation stack. Runs the `ssp_airplane` airplane SSP through `ssp4sim`; the live visualization is ROS-free (`dis_viewer` + Rerun over the bridge's UDP telemetry). The ROS 2 / RViz stack is deprecated but its files remain.

Key scripts:
- `scripts/check_environment.sh` — validate host prerequisites (`--source-build`, legacy `--live-container`)
- `scripts/build_airplane.py` — build the airplane SSP/FMUs and refresh the local `build/ssp` bundle
- `scripts/build_rerun_container.sh` — build the Podman Rerun viewer image (`Containerfile.rerun`)
- `scripts/run_rerun_stack.sh` — run the realtime sim plus the Rerun viewer; host venv by default, `RERUN_CONTAINER=1` for the Podman image
- `scripts/container_rerun_smoke.sh` — headless Rerun recording smoke test (no X11, no Podman)
- `scripts/send_pilot_command.py` — manual pilot input on UDP 5502, replacing the ROS subscription
- `scripts/run_airplane_scenario.py` — run a batch/realtime scenario from the local bundle
- `scripts/build_ros2_container.sh` — deprecated ROS 2 image
- `scripts/run_full_stack_container.sh` — deprecated RViz stack
- `scripts/record_demo.sh` — deprecated RViz showcase movie capture
- `scripts/render_showcase_movie.py` — render the recorded capture into a movie

The aircraft model, SysML architecture, and SSP/FMU build pipeline live in `3rd_party/airplane` (git submodule, handled separately).

Use the workspace venv for Python: `/home/eriro/pwa/2_work/flight_sim/venv/bin/python3`.
