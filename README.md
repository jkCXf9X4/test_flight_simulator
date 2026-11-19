# test_flight_simulator

Top-level workspace for running the airplane SSP and evolving the interactive simulation stack around it.

## Layout

- `3rd_party/airplane` contains the aircraft model, SysML architecture, Modelica models, and SSP/FMU build pipeline.
- `docs` contains top-repo operational documentation for building and running the simulation stack.
- `scripts` contains top-repo helper scripts that wrap common airplane build and scenario commands.

## Just Works

The supported live workflow is ROS-free: `ssp4sim` runs on the host and the Rerun viewer renders the bridge's UDP telemetry.

```bash
./scripts/build_airplane.py
./scripts/run_rerun_stack.sh
```

`run_rerun_stack.sh` starts `./scripts/run_airplane_scenario.py --realtime`, waits for the realtime telemetry file to advance, then runs `python -m flight_viewer --source json-udp --sink rerun --spawn` with the repo venv.

To run the viewer inside Podman instead of on the host, build the image and opt in:

```bash
./scripts/build_rerun_container.sh
RERUN_CONTAINER=1 ./scripts/run_rerun_stack.sh
```

Seed the local bundle with a different scenario during build:

```bash
./scripts/build_airplane.py 3rd_party/airplane/resources/scenarios/test_scenario.json
```

Other useful entry points:

- Rebuild SSP/FMU artifacts and refresh the local `build/ssp` bundle: `./scripts/build_airplane.py`
- Run a batch simulation from the local bundle: `./scripts/run_airplane_scenario.py`
- Run a realtime batch simulation from the local bundle: `./scripts/run_airplane_scenario.py --realtime`
- Run the two-instance federation through `pysos_coordinate` (validate first with `--dry-run`): `./scripts/run_instances.py --instances 2`
- Regenerate the checked-in federation manifest from the scenario settings: `./scripts/generate_instance_manifest.py`
- Headless Rerun smoke test (no X11, no Podman): `./scripts/container_rerun_smoke.sh`
- Manual pilot input on UDP 5502: `./scripts/send_pilot_command.py --pitch 0.2 --duration 5`
- Read the workflow notes: `docs/simulation_workflow.md`

## Interactive Direction

The supported live setup keeps `ssp4sim` as the simulation master on the host. The native bridge FMU still emits newline-delimited JSON telemetry on UDP 5501; `flight_viewer` consumes it and renders with Rerun. Manual pilot commands go to UDP 5502 through `scripts/send_pilot_command.py`.

The RViz runtime has been retired. The live stack is the Rerun viewer described above; the native `UdpBridge` FMU keeps its unchanged UDP telemetry/control contract. The viewer's default path is JSON telemetry over UDP; DIS is an optional codec from `pysos_interop`.
