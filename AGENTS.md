# AGENTS

Test workspace for the flight-sim interactive simulation stack. Runs the `ssp_airplane` airplane SSP through `ssp4sim`; the live visualization is ROS-free (`dis_viewer` + Rerun over the bridge's UDP telemetry). The native bridge FMU is still named `Ros2UdpBridge`; that is a legacy identifier kept for the UDP telemetry/control contract.

Key scripts:
- `scripts/check_environment.sh` — validate host prerequisites (`--source-build`, `--live-container`, `--container-build`)
- `scripts/build_airplane.py` — build the airplane SSP/FMUs and refresh the local `build/ssp` bundle
- `scripts/build_rerun_container.sh` — build the Podman Rerun viewer image (`Containerfile.rerun`)
- `scripts/run_rerun_stack.sh` — run the realtime sim plus the Rerun viewer; host venv by default, `RERUN_CONTAINER=1` for the Podman image
- `scripts/container_rerun_smoke.sh` — headless Rerun recording smoke test (no X11, no Podman)
- `scripts/send_pilot_command.py` — manual pilot input on UDP 5502
- `scripts/run_airplane_scenario.py` — run a batch/realtime scenario from the local bundle
- `scripts/prepare_instance_bundle.py` — prepare a per-instance SSP bundle and config
- `scripts/run_instances.py` — run the instance federation through `pysos_coordinate.Federation`
- `scripts/generate_instance_manifest.py` — generate/check `manifests/two_instances.manifest.json`
- `scripts/run_instance_process.py` — manifest command: prepare one bundle, then exec its simulation
- `scripts/render_showcase_movie.py` — render a showcase movie from a recorded capture (its RViz capture path has been retired)

The aircraft model, SysML architecture, and SSP/FMU build pipeline live in `3rd_party/airplane` (git submodule, handled separately).

Use the workspace venv for Python: `/home/eriro/pwa/2_work/flight_sim/venv/bin/python3`.
