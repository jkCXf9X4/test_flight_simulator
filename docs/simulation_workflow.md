# Simulation workflow

This repository uses the airplane package in `3rd_party/airplane` as the simulation core. The top repo stores the operational entry points used to build, run, and evolve the simulation workflow.

## Supported workflows

The repository supports:

1. Build the aircraft FMUs/SSD/SSP.
2. Seed a local `build/ssp` simulation bundle.
3. Run that local bundle through `ssp4sim`.
4. Launch the live Rerun viewer on the host or through Podman.
5. Post-process and inspect the generated results.

Top-level wrappers:

- `./scripts/build_airplane.py`
- `./scripts/run_airplane_scenario.py`
- `./scripts/run_rerun_stack.sh`
- `./scripts/build_rerun_container.sh`
- `./scripts/container_rerun_smoke.sh`
- `./scripts/send_pilot_command.py`
- `./scripts/check_environment.sh` (`--live-container` checks Podman, the Rerun image, and X11; `--source-build` checks the airplane build dependencies)

Recommended live workflow:

```bash
./scripts/build_airplane.py
./scripts/run_rerun_stack.sh
```

What the build now does inside `3rd_party/airplane`:

- regenerates architecture-derived interfaces
- exports the Modelica subsystem FMUs with OpenModelica
- builds the native C++ bridge FMI 2.0 co-simulation FMU
- verifies the bridge FMU with a UDP socket regression test
- regenerates the SSD and packages `build/ssp/aircraft.ssp`
- copies the baseline SSP into the top-level `build/ssp`
- copies the selected scenario into the top-level `build/ssp/scenario.json`
- writes top-level `build/ssp/config.json` and `build/ssp/config.realtime.json`

## Rerun viewer

The supported live visualization is ROS-free. `ssp4sim` stays on the host, the native bridge FMU keeps emitting the existing newline-delimited JSON telemetry on UDP 5501, and `dis_viewer` renders it with Rerun.

```bash
# Host viewer, repo venv (default)
./scripts/build_airplane.py
./scripts/run_rerun_stack.sh

# View in the Podman image instead
./scripts/build_rerun_container.sh
RERUN_CONTAINER=1 ./scripts/run_rerun_stack.sh
```

- `run_rerun_stack.sh` starts `./scripts/run_airplane_scenario.py --realtime`, waits for `build/results/scenario_results_realtime.csv` to advance instead of sleeping, then runs `python -m dis_viewer --source json-udp --sink rerun --spawn --scenario 3rd_party/airplane/resources/scenarios/test_scenario.json --record build/results/dis_viewer.jsonl`.
- Host execution uses the repo venv. `RERUN_CONTAINER=1` runs the same command inside `Containerfile.rerun` with X11 mounts and `--network=host`, so UDP stays on loopback.
- Manual pilot input goes through the pilot shim: `./scripts/send_pilot_command.py --pitch 0.2 --roll -0.1 --throttle 0.7 --duration 5` sends JSON control packets to UDP 5502.
- Headless check, no X11 and no Podman: `./scripts/container_rerun_smoke.sh` writes `/tmp/smoke.rrd` and prints PASS/FAIL.
- Every live run also writes `build/results/dis_viewer.jsonl`; replay it with `python -m dis_viewer --source jsonl --path build/results/dis_viewer.jsonl --sink rerun --spawn`.

## Retired: ROS 2 / RViz viewer

The earlier ROS 2 / RViz runtime has been retired and replaced by the Rerun viewer. Use `./scripts/run_rerun_stack.sh` for live visualization. The native `Ros2UdpBridge` FMU keeps its historical name because the UDP JSON telemetry/control contract is unchanged.

## Current bridge implementation

The bridge is a native FMI 2.0 co-simulation FMU in C++ (`Ros2UdpBridge`) that acts as a UDP telemetry/control adapter, emitting newline-delimited JSON state packets. The name is a legacy identifier kept so the UDP contract and SSP members stay stable; it no longer implies a ROS 2 dependency.

Current behavior:

- outbound telemetry is emitted as a UDP JSON packet from the FMU once per communication step
- inbound control packets are read non-blocking by the FMU once per communication step
- control packets are JSON objects carrying the `PilotCommand` fields
- when no fresh control packets arrive, the bridge marks itself inactive so `ControlInterface` falls back to the scripted/manual default path

Containerized viewer behavior:

- `./scripts/check_environment.sh --live-container` validates Podman, the built Rerun image (`test-flight-simulator-rerun`), and the X11 requirements before launch
- `./scripts/build_airplane.py [scenario-json]` refreshes the local SSP bundle used by both batch and live runs
- `./scripts/build_rerun_container.sh` builds the reusable Podman Rerun image from `Containerfile.rerun`
- `./scripts/run_rerun_stack.sh` runs the realtime simulation on the host and starts the viewer either on the host (default) or, with `RERUN_CONTAINER=1`, in the container with X11 mounts and host networking
- `./scripts/container_rerun_smoke.sh` runs the headless Rerun recording check without X11 or Podman
- `./scripts/run_airplane_scenario.py` only runs `pyssp4sim` against the prepared local config and does not repackage scenario artifacts
- use `./scripts/run_airplane_scenario.py --realtime` when you want the local realtime config without a viewer

Implementation/build notes:

- the FMU is built from `3rd_party/airplane/models/ros2_udp_bridge/native/`
- the generated FMU is written to `3rd_party/airplane/build/fmus/Ros2UdpBridge.fmu`
- the shared library exports the standard FMI 2 `fmi2*` entry points so `pyssp4sim` can import it directly
- `3rd_party/airplane/tests/test_ros2_udp_bridge_fmu.py` now verifies the JSON bridge packet and control pass-through path

## Timing approach

The first realtime implementation should use the existing `ssp4sim` realtime execution option to pace the simulation.

For now, do not add new synchronization methods to the `pyssp4sim` API and do not introduce a separate external package sync layer just to establish timing.

Planned follow-up work, but explicitly not part of the initial implementation:

1. Add a `doStep(t)` style method to the Python API so the caller can drive step timing explicitly.
2. Add support for synchronizing against an external package or external clock source when the bridge/runtime requirements justify it.

## Where design ownership lives

- Repo-level operational workflow: this document
- Aircraft-side architecture notes: `3rd_party/airplane/architecture/aircraft.sysml`

## Current aircraft adaptation status

The aircraft package now includes the native bridge in the packaged SSP workflow:

- the dedicated `Ros2UdpBridge` component is part of the aircraft architecture and SSD
- the bridge is packaged as a native C++ FMU alongside the Modelica-exported subsystem FMUs
- bridge-produced pilot commands enter through `ControlInterface`
- top-level scripts build the SSP and can run a scenario while the bridge emits live UDP telemetry

## Expected next implementation steps

The ROS 2 / RViz runtime removal is complete. Remaining follow-up work is tracked in `TODO.md`.

## Multi-instance runs

Two checked-in federation manifests describe independent aircraft instances in
the schema owned by `pysos_coordinate`:

- `manifests/two_instances.manifest.json` — the generated two-instance default,
  produced by `scripts/generate_instance_manifest.py`.
- `manifests/aircraft_federation.manifest.json` — the four-aircraft SoS
  manifest, lowered from `sos/aircraft_federation.sysml` by
  `scripts/generate_sos_manifest.py` (RED-1/RED-2/BLUE-1/BLUE-2, four distinct
  scenarios).

They are generated, not hand-edited:

```bash
PY=/home/eriro/pwa/2_work/flight_sim/venv/bin/python3
$PY scripts/generate_instance_manifest.py           # rewrite the two-instance manifest
$PY scripts/generate_instance_manifest.py --check   # fail if it is stale
$PY scripts/generate_sos_manifest.py                # rewrite the SoS manifest
$PY scripts/generate_sos_manifest.py --check        # fail if it is stale
```

`scripts/run_instances.py` translates its CLI into a manifest and hands the
validated spec to `pysos_coordinate.Federation`; the project keeps no process
supervisor of its own. Per-instance preparation stays in
`scripts/prepare_instance_bundle.py`, wired as the manifest `command` through
`scripts/run_instance_process.py`: that wrapper prepares the bundle and then
`exec`s the ssp4sim run, so the supervised process is the simulation itself.

```bash
$PY scripts/run_instances.py --dry-run           # validate, launch nothing
$PY scripts/run_instances.py --instances 2 --stop-time 60
$PY scripts/run_instances.py --manifest manifests/two_instances.manifest.json
$PY scripts/run_instances.py --manifest manifests/aircraft_federation.manifest.json
```

The old flags (`--instances`, `--source-ssp`, `--out-dir`, `--stop-time`,
`--realtime`, `--python`) keep their meaning and are translated into the same
manifest. `--realtime` paces against the wall clock, `--log-dir` captures
per-instance stdout/stderr, and `--manifest` runs a checked-in manifest with
the project interpreter substituted for the portable `python3` in `command`.

### Ports

| purpose | ports | notes |
| --- | --- | --- |
| instance telemetry | `5510 + 2*(index-1)` | 5510, 5512, 5514, 5516 for four instances |
| instance control | telemetry + 1 | 5511, 5513, 5515, 5517 |
| RPR fan-in | **5505** | dedicated recorder port, never an instance port |

The old `5501` plan is retired; it collided with RPR `5505` at instance 3.

| instance | telemetry | control | init offset (north, east) |
| --- | --- | --- | --- |
| 1 | 5510 | 5511 | 0, 0 km |
| 2 | 5512 | 5513 | 0, +5 km |
| 3 | 5514 | 5515 | 0, +10 km |
| 4 | 5516 | 5517 | 0, +15 km |

The default manifest runs `test_scenario` for both instances. The SoS manifest
runs `high_altitude_intercept`, `deep_strike_penetration`,
`cas_multi_store_support`, and `test_scenario` on instances 1-4 respectively.

Each instance writes to `build/ssp/instances/instance-<N>/` when launched from
the generated manifest (the e2e runner retargets this to its own run
directory): its own SSP, `config.json`, `work/`, result CSV, and log. The local
origin is scenario `points[0]`; the bridge's `reference_*` fields stay at their
defaults and are not used for framing.

### Per-instance scenario flow

The scenario is selected per instance, never shared:

1. The SysML federation author writes `scenario = "<stem>"` on an instance in
   `sos/aircraft_federation.sysml`.
2. `scripts/generate_sos_manifest.py` lowers that to the manifest
   `env.PYSOS_SCENARIO` key (alongside `PYSOS_TELEMETRY_PORT` and
   `PYSOS_CONTROL_PORT`).
3. `scripts/run_instance_process.py` reads those variables (explicit CLI flags
   still win, and the scenario defaults to `test_scenario` when the key is
   absent). When `--instance` is omitted, it derives the 1-based index from
   `PYSOS_TELEMETRY_PORT`.
4. `scripts/prepare_instance_bundle.py` loads
   `3rd_party/airplane/resources/scenarios/<scenario>.json`, converts it through
   the airplane scenario library (`scripts/lib/scenarios/preparation.py`), and
   rewrites the per-instance SSP's `resources/MissionScenario.ssv` members:
   `waypointX_km[1..10]`, `waypointY_km[1..10]`, `waypointZ_km[1..10]`,
   `waypointCount`, `targetAirspeed_mps`, and `waypointProximity_km`. The
   existing `initX_km`/`initY_km` offsets and port rewrite stay unchanged.

Aircraft are peerless: every instance only publishes its own telemetry on its
own port, and the e2e runner starts one one-way RPR publisher per instance. No
instance opens another instance's port or ingests another instance's telemetry;
only the single recorder on UDP 5505 fans the streams in.

## End-to-end RPR acceptance run

`scripts/run_e2e_rpr.py` composes the whole stack for a fixed simulated
duration. It launches every instance in the selected manifest through
`pysos_coordinate.Federation`, converts each instance's telemetry JSON to the
shared `EntityState`, and republishes it as RPR payloads on the dedicated RPR
port **5505**, then subscribes that stream, decodes it with the scenario's
explicit `RprOrigin` (`points[0]`), and writes the recorder artifacts. It uses
`pysos_interop.rpr.encode_entity_state` / `decode_frame` and adds no library
code to `pyssp_dev`.

```bash
PY=/home/eriro/pwa/2_work/flight_sim/venv/bin/python3

# Fixed 6 s two-instance run; origin from the scenario, artifacts under build/runs/
$PY scripts/run_e2e_rpr.py --stop-time 6 --run-dir build/runs/e2e

# Same path against the generated manifest (retargeted to the run directory)
$PY scripts/run_e2e_rpr.py --manifest manifests/two_instances.manifest.json \
    --stop-time 6 --run-dir build/runs/e2e-manifest

# Four aircraft, four scenarios (N comes from the SoS manifest)
$PY scripts/run_e2e_rpr.py --manifest manifests/aircraft_federation.manifest.json \
    --stop-time 3 --run-dir build/runs/sos4

# Without a manifest, --instances N builds the default scenario N times
$PY scripts/run_e2e_rpr.py --instances 2

# Rerun load check (viewer-side exit code)
$PY -m rerun rrd verify build/runs/e2e/recording.rrd

# Live acceptance test (skips only if the bundle or ports are unavailable)
$PY -m pytest tests/test_e2e_rpr.py -q
```

Run directory layout (`build/runs/e2e/`):

| path | content |
| --- | --- |
| `run.json` | scenario, origin, ports, exit codes, sample counts, per-entity path lengths, per-pair separation, and `pyssp_vv` comparison |
| `truth.jsonl` | `pysos_interop.TruthRecorder` truth stream, one row per entity per sample |
| `truth.meta.json` | metadata sidecar: run id, origin, entity catalogue, 10 Hz rate, units |
| `measurements.csv` | `pysos_interop.export_measure_csv` table, `<site>_<app>_<entity>.<channel>` columns |
| `recording.rrd` | `pysos_interop.rerun_sink.recordings_to_rrd` export (ENU, `world/entity/<slug>/...`) with per-entity labels and deterministic distinct colours |
| `comparison.csv` | `pyssp_vv.measure.compare` rows: one self-compare per entity plus every entity pair |
| `separation.csv` | `time, min_separation_m, nearest_a, nearest_b` over all entity pairs |
| `instances/instance-<N>/` | per-instance SSP, `config.json`, `work/`, result CSV and log |
| `logs/<instance>.{stdout,stderr}.log` | federation process logs |

RPR has no timestamp field, so each publisher owns a per-entity ordinal at the
bridge's 10 Hz cadence and the recorder stamps sample `n` at
`n * sample_period_s`. A per-sample barrier writes a row only when every
expected slug has arrived; a watchdog flushes the oldest partial sample after
2.0 s, so a missing publisher cannot hang the recorder. Entities absent from a
partial sample have no values and appear as `nan` in `measurements.csv` and
`separation.csv`.

Batch mode runs 20 s of 10 Hz telemetry as a burst several times faster than
realtime, so the per-instance telemetry sockets and the shared RPR socket are
finite kernel UDP buffers. `run.json` now carries a `transport` block with
per-slug telemetry datagrams/packets received, RPR payloads sent, recorder
datagrams decoded, and the kernel UDP counter delta (`RcvbufErrors`); a non-zero
`RcvbufErrors` that matches a frame deficit means the kernel dropped datagrams,
not that the recorder logic lost them. Publisher/recorder thread exceptions are
recorded there too (`error`, `error_traceback`), so a dead thread leaves
evidence even when the run is started from a script.

The publisher drops the bridge's leading all-zero pre-initialisation record, so
the recorded artifacts start at the first real packet with zero velocity on its
first sample and no startup separation frame. The two-instance default measures
**5000.0 m** between entity 1 and entity 2 (origin `points[0]` =
`(-2.957519, 39.232955)`, 5 km east offset). The four-aircraft SoS run keeps all
four aircraft at a few kilometres separation while their path lengths differ
with their scenarios.
