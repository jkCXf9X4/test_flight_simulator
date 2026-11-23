# AGENTS

Test workspace for the flight-sim interactive simulation stack. Runs the `ssp_airplane` airplane SSP through `ssp4sim`; the live visualization is ROS-free (`flight_viewer` + Rerun). The aircraft broadcasts RPR entity state to the recorder on UDP 5505; the recorder writes truth/measure/rrd and the viewer replays the truth stream. The JSON telemetry/control bridge and pilot shim are retired.

Key scripts:
- `scripts/check_environment.sh` — validate host prerequisites (`--source-build`, `--live-container`, `--container-build`)
- `scripts/build_airplane.py` — build the airplane SSP/FMUs and refresh the local `build/ssp` bundle (resolves `$PYTHON` / workspace venv / airplane venv; run `check_environment.sh --source-build` first)
- `scripts/build_rerun_container.sh` — build the Podman Rerun viewer image (`Containerfile.rerun`)
- `scripts/run_rerun_stack.sh` — run the realtime sim plus the Rerun viewer replaying the recorder output; host venv by default, `RERUN_CONTAINER=1` for the Podman image, `RERUN_WEB=1` for the web viewer in Chrome with SwiftShader WebGL2
- `scripts/container_rerun_smoke.sh` — headless Rerun recording smoke test (no X11, no Podman)
- `scripts/run_airplane_scenario.py` — run a batch/realtime scenario from the local bundle
- `scripts/prepare_instance_bundle.py` — prepare a per-instance SSP bundle and config
- `scripts/run_instances.py` — run the instance federation through `pysos_coordinate.Federation`
- `scripts/entity_manifest.py` — lower/check `manifests/aircraft_federation.manifest.json`, resolving the entity plane's `Aircraft`/`PysosSoS`/`RprEntity` include roots
- `scripts/generate_instance_manifest.py` — generate/check `manifests/two_instances.manifest.json`
- `scripts/run_instance_process.py` — manifest command: prepare one bundle (scenario and ports from its environment), then exec its simulation
- `scripts/run_e2e_rpr.py` — run the federation, receive the aircraft RPR broadcasts on 5505, record truth/CSV/Rerun, summarize separation
- `scripts/replay_web.sh` — replay a truth log in the Rerun web viewer (Chrome with SwiftShader WebGL2, streamed live so it animates)
- `scripts/stream_truth_rerun.py` — stream a truth log into a running Rerun viewer at realtime pace
- `scripts/render_replay_rrd.py` — build a lightweight `.rrd` from a truth log (short trails) for software rendering
- `sos/aircraft_federation.sysml` — entity plane and source of truth for the four aircraft; it imports the real `Aircraft` model and the shared `PysosSoS::LaunchSpec`, and is lowered by `scripts/entity_manifest.py` (check with `scripts/entity_manifest.py --check`)
- `sos/federation_system.sysml` — system plane: frame, timing, host processes (recorder, viewer, builder), the RPR broadcast flow and artifacts (SysML v2, lowered by `pycps_sysml2`)
- `scripts/sos_model.py` — lower the system plane and check it against the manifest; must print `ok:` before a federation run (`--artifacts` also verifies the built aircraft SSPs)
- `scripts/render_showcase_movie.py` — render a showcase movie from a recorded capture (its RViz capture path has been retired)

The aircraft model, SysML architecture, and SSP/FMU build pipeline live in `3rd_party/airplane` (git submodule, handled separately).

Use the workspace venv for Python: `/home/eriro/pwa/2_work/flight_sim/venv/bin/python3`.
