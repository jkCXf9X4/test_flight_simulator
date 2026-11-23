# test_flight_simulator

Top-level workspace for running the airplane SSP and evolving the interactive simulation stack around it.

## Layout

- `3rd_party/airplane` contains the aircraft model, SysML architecture, Modelica models, and SSP/FMU build pipeline.
- `docs` contains top-repo operational documentation for building and running the simulation stack.
- `scripts` contains top-repo helper scripts that wrap common airplane build and scenario commands.

## Just Works

The supported live workflow is ROS-free: `ssp4sim` runs on the host, the aircraft SSP broadcasts RPR entity state to the recorder on UDP 5505, and the Rerun viewer replays the recorder's truth stream.

```bash
./scripts/build_airplane.py
./scripts/run_rerun_stack.sh
```

`run_rerun_stack.sh` starts the realtime run, waits for the run artifacts to advance, then replays `build/runs/<run>/truth.jsonl` with
`python -m flight_viewer --source jsonl --sink rerun --spawn`.

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
- Read the workflow notes: `docs/simulation_workflow.md`

## Interactive Direction

The supported live setup keeps `ssp4sim` as the simulation master on the host. Every aircraft broadcasts its own RPR entity-state packets to the recorder on UDP 5505; the recorder writes `truth.jsonl`, `measurements.csv` and `recording.rrd`, and `flight_viewer` replays the truth stream with Rerun.

There is no live JSON telemetry/control bridge and no pilot shim. The RViz runtime has been retired; the live stack is the Rerun viewer replaying the recorder output.
