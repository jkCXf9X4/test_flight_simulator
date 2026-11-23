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
- `./scripts/check_environment.sh` (`--live-container` checks Podman, the Rerun image, and X11; `--source-build` checks the airplane build dependencies)

Recommended live workflow:

```bash
./scripts/build_airplane.py
./scripts/run_rerun_stack.sh
```

What the build now does inside `3rd_party/airplane`:

- regenerates architecture-derived interfaces
- exports the Modelica subsystem FMUs with OpenModelica
- builds the RPR state-source and RPR entity FMI 2.0 co-simulation FMUs
- regenerates the SSD and packages `build/ssp/aircraft.ssp`
- copies the baseline SSP into the top-level `build/ssp`
- copies the selected scenario into the top-level `build/ssp/scenario.json`
- writes top-level `build/ssp/config.json` and `build/ssp/config.realtime.json`

## RPR broadcast and viewer replay

The supported live visualization is ROS-free and one-way. `ssp4sim` stays on the host, every aircraft broadcasts RPR entity-state packets to the recorder on UDP 5505, and `flight_viewer` replays the recorder's truth stream with Rerun. There is no live JSON telemetry/control socket and no pilot shim.

```bash
# Host viewer, repo venv (default)
./scripts/build_airplane.py
./scripts/run_rerun_stack.sh

# View in the Podman image instead
./scripts/build_rerun_container.sh
RERUN_CONTAINER=1 ./scripts/run_rerun_stack.sh

# Web viewer in Chrome (SwiftShader WebGL2, works without a GPU)
RERUN_WEB=1 ./scripts/run_rerun_stack.sh
```

- `run_rerun_stack.sh` starts the realtime federation, waits for the recorder artifacts to advance instead of sleeping, then runs `python -m flight_viewer --source jsonl --path build/runs/<run>/truth.jsonl --sink rerun --spawn --realtime` (`--connect-grpc` with `RERUN_WEB=1`) with the run's scenario.
- Host execution uses the repo venv. `RERUN_CONTAINER=1` runs the same command inside `Containerfile.rerun` with X11 mounts and `--network=host`, so UDP stays on loopback.
- Headless check, no X11 and no Podman: `./scripts/container_rerun_smoke.sh` writes `/tmp/smoke.rrd` and prints PASS/FAIL.
- A recorded federation run (`run_e2e_rpr.py --run-dir ...`) writes `truth.jsonl`; replay it in the Rerun web viewer with `./scripts/replay_web.sh build/runs/<run>/truth.jsonl` (adds `RATE=2` for a faster pass). Loading the coordinator's `.rrd` opens paused and re-renders slowly under software rasterization, so this streams the truth log live instead; `./scripts/render_replay_rrd.py` writes a lighter `.rrd` when a file is preferred.

## Retired: RViz viewer

The earlier RViz runtime has been retired and replaced by the Rerun viewer. Use `./scripts/run_rerun_stack.sh` for visualization.

## RPR broadcast path

The aircraft carries two native FMI 2.0 co-simulation FMUs: `rpr_state_source` projects the aircraft state onto the RPR entity-state vocabulary, and `rpr_entity` encodes and sends it. Deployment is initialization configuration:

- `rpr_entity.transport` is `udp`;
- `rpr_entity.bind_address` is the instance endpoint (5510, 5512, 5514, 5516);
- `rpr_entity.peer_address` is the recorder at `127.0.0.1:5505`.

Each instance publishes one-way at 10 Hz and never opens another instance's port. The recorder (`RprTruthRecorder` in `scripts/run_e2e_rpr.py`) binds 5505, decodes the RPR payloads, and writes `truth.jsonl`, `truth.meta.json`, `measurements.csv` and `recording.rrd`. There is no inbound control channel.

Containerized viewer behavior:

- `./scripts/check_environment.sh --source-build` resolves the build interpreter (`$PYTHON`, workspace venv, airplane venv, PATH) and checks `omc`, `cmake` and a C++ compiler
- `./scripts/check_environment.sh --live-container` validates Podman, the built Rerun image (`test-flight-simulator-rerun`), and the X11 requirements before launch
- `./scripts/build_airplane.py [scenario-json]` refreshes the local SSP bundle used by both batch and live runs
- `./scripts/build_rerun_container.sh` builds the reusable Podman Rerun image from `Containerfile.rerun`
- `./scripts/run_rerun_stack.sh` runs the realtime federation on the host and replays the recorder truth stream either on the host (default), with `RERUN_CONTAINER=1` in the container with X11 mounts and host networking, or with `RERUN_WEB=1` as the web viewer (`RERUN_WEB_PORT`, default 9090) in a dedicated Chrome instance that enables SwiftShader WebGL2 (`CHROME_BIN` overrides the browser)
- `./scripts/container_rerun_smoke.sh` runs the headless Rerun recording check without X11 or Podman
- `./scripts/run_airplane_scenario.py` only runs `pyssp4sim` against the prepared local config and does not repackage scenario artifacts
- use `./scripts/run_airplane_scenario.py --realtime` when you want the local realtime config without a viewer

Implementation/build notes:

- the RPR entity definition is dialect data from `pyfmi_rpr`; `sos/federation_system.sysml` supplies it as an included root so `scripts/sos_model.py` can resolve `RprEntity` without restating it
- `scripts/prepare_instance_bundle.py` writes the per-instance RPR bind/peer addresses and entity identity into the SSP's SSV/SSM
- the generated FMUs are packaged into `build/ssp/aircraft.ssp` alongside the Modelica subsystem FMUs

## Timing approach

The first realtime implementation should use the existing `ssp4sim` realtime execution option to pace the simulation.

For now, do not add new synchronization methods to the `pyssp4sim` API and do not introduce a separate external package sync layer just to establish timing.

Planned follow-up work, but explicitly not part of the initial implementation:

1. Add a `doStep(t)` style method to the Python API so the caller can drive step timing explicitly.
2. Add support for synchronizing against an external package or external clock source when the transport/runtime requirements justify it.

## Where design ownership lives

- Repo-level operational workflow: this document
- Aircraft-side architecture notes: `3rd_party/airplane/architecture/aircraft.sysml`

## Current aircraft adaptation status

The aircraft package now broadcasts RPR in the packaged SSP workflow:

- `rpr_state_source` and `rpr_entity` are part of the aircraft architecture and SSD
- both are packaged as native FMI 2.0 co-simulation FMUs alongside the Modelica-exported subsystem FMUs
- per-instance bind/peer addresses and entity identity are written into the SSP parameters
- top-level scripts build the SSP and run a scenario while the aircraft broadcasts RPR entity state

## Expected next implementation steps

The RViz runtime removal is complete. Remaining follow-up work is tracked in `TODO.md`.

## Multi-instance runs

Two checked-in federation manifests describe independent aircraft instances in
the schema owned by `pysos_coordinate`:

- `manifests/two_instances.manifest.json` — the generated two-instance default,
  produced by `scripts/generate_instance_manifest.py`.
- `manifests/aircraft_federation.manifest.json` — the four-aircraft SoS
  manifest, lowered from `sos/aircraft_federation.sysml` by `pysos-sysml`
  (RED-1/RED-2/BLUE-1/BLUE-2, four distinct scenarios).

They are generated, not hand-edited:

```bash
PY=/home/eriro/pwa/2_work/flight_sim/venv/bin/python3
$PY scripts/generate_instance_manifest.py           # rewrite the two-instance manifest
$PY scripts/generate_instance_manifest.py --check   # fail if it is stale
$PY -m pysos_sysml manifest sos/aircraft_federation.sysml -o manifests/aircraft_federation.manifest.json --check  # fail if it is stale
```

The system-of-systems model has two planes: the entity plane
(`sos/aircraft_federation.sysml`, lowered to the manifest) and the system plane
(`sos/federation_system.sysml`, lowered by `scripts/sos_model.py`). The system
plane owns the shared frame and origin, the timing contract, the host-side
participants (orchestrator/recorder on RPR 5505, viewer replaying the truth
stream, builder), the RPR broadcast flow and the run artifacts. `scripts/sos_model.py` must print `ok:` before a federation
run, and `scripts/sos_model.py --artifacts` after a build to prove the fresh
SSPs still match the modelled aircraft; see `docs/sos_model.md`.

Per-instance run parameters live in the manifest `command` argv because the
`pysos_sysml` subset cannot type them: `--realtime`, `--stop-time`, the
placement offsets, `--waypoint-frame federation`, the federation
`--reference-latitude-deg/--reference-longitude-deg/--reference-altitude-m`,
and the entity identity `--entity-site/--entity-application/--entity/--marking`.
The frame flag rebases each scenario's waypoints into the federation frame, so
four scenarios authored around four different geodetic origins still publish one
consistent frame; the reference flags put that same origin in every RPR state
packet and the identity flags name the entity on the wire. The aircraft composition itself is imported from
`3rd_party/airplane/architecture/aircraft.sysml`, not restated.

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
| instance RPR bind | `5510 + 2*(index-1)` | 5510, 5512, 5514, 5516 for four instances |
| RPR fan-in | **5505** | dedicated recorder port, never an instance port |

The old `5501` plan is retired; it collided with RPR `5505` at instance 3.
`PYSOS_CONTROL_PORT` and the per-instance control port remain only in the
SysML-lowered manifest, because the current `pysos_sysml` loader requires
`controlPort`; no aircraft consumes them.

| instance | RPR bind | init offset (north, east) |
| --- | --- | --- |
| 1 | 5510 | 0, 0 km |
| 2 | 5512 | 0, +5 km |
| 3 | 5514 | 0, +10 km |
| 4 | 5516 | 0, +15 km |

The default manifest runs `test_scenario` for both instances. The SoS manifest
runs `high_altitude_intercept`, `deep_strike_penetration`,
`cas_multi_store_support`, and `test_scenario` on instances 1-4 respectively.

Each instance writes to `build/ssp/instances/instance-<N>/` when launched from
the generated manifest (the e2e runner retargets this to its own run
directory): its own SSP, `config.json`, `work/`, result CSV, and log. The
federation origin is scenario `points[0]`; it is written into
`rpr_state_source.reference_*` so every broadcast names the frame it uses.

### Per-instance scenario flow

The scenario is selected per instance, never shared:

1. The SysML federation author writes `scenario = "<stem>"` on an instance in
   `sos/aircraft_federation.sysml`.
2. `pysos-sysml manifest` lowers that to the manifest `env.PYSOS_SCENARIO`
   key (alongside `PYSOS_TELEMETRY_PORT`; `PYSOS_CONTROL_PORT` is the vestigial
   key the current loader still emits).
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

Aircraft are peerless: every instance only broadcasts its own RPR state from
its own bind port. No instance opens another instance's port or ingests another
instance's state; only the single recorder on UDP 5505 fans the streams in.

## End-to-end RPR acceptance run

`scripts/run_e2e_rpr.py` composes the whole stack for a fixed simulated
duration. It launches every instance in the selected manifest through
`pysos_coordinate.Federation` and binds the recorder to the dedicated RPR port
**5505**. The aircraft broadcast RPR themselves; the recorder decodes the
payloads with the scenario's explicit `RprOrigin` (`points[0]`) and writes the
recorder artifacts. It adds no library code to `pyssp_dev`.

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

RPR has no timestamp field, so each entity's RPR stream carries a per-entity
ordinal at the 10 Hz cadence and the recorder stamps sample `n` at
`n * sample_period_s`. A per-sample barrier writes a row only when every
expected slug has arrived; a watchdog flushes the oldest partial sample after
2.0 s, so a missing publisher cannot hang the recorder. Entities absent from a
partial sample have no values and appear as `nan` in `measurements.csv` and
`separation.csv`.

Batch mode runs 20 s of 10 Hz telemetry as a burst several times faster than
realtime, so the per-instance RPR bind sockets and the shared recorder socket
are finite kernel UDP buffers. `run.json` now carries a `transport` block with
per-slug RPR datagrams received, recorder datagrams decoded, and the kernel UDP
counter delta (`RcvbufErrors`); a non-zero
`RcvbufErrors` that matches a frame deficit means the kernel dropped datagrams,
not that the recorder logic lost them. Publisher/recorder thread exceptions are
recorded there too (`error`, `error_traceback`), so a dead thread leaves
evidence even when the run is started from a script.

The RPR path drops the leading all-zero pre-initialisation record, so the
recorded artifacts start at the first real packet with zero velocity on its
first sample and no startup separation frame. The two-instance default measures
**5000.0 m** between entity 1 and entity 2 (origin `points[0]` =
`(-2.957519, 39.232955)`, 5 km east offset). The four-aircraft SoS run keeps all
four aircraft at a few kilometres separation while their path lengths differ
with their scenarios.
