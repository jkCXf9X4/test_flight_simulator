# System-of-systems model

How the multi-entity flight simulation is modelled, which pyssporg pieces carry
which facts, and what "the model is complete" is verified to mean.

Run the gate with:

```bash
PY=/home/eriro/pwa/2_work/flight_sim/venv/bin/python3
$PY scripts/sos_model.py              # model + manifest, verifies artifacts when present
$PY scripts/sos_model.py --artifacts  # additionally requires the built SSPs to match
$PY -m pytest tests/test_sos_model.py -q
```

## 0. Building the full aircraft

```bash
./scripts/check_environment.sh --source-build   # resolves the venv, omc, cmake, c++
./scripts/build_airplane.py                     # 9 Modelica FMUs + RPR state source/entity + baseline SSP
                                                # then exports build/ssp/variants/<Variant>.ssp
$PY scripts/sos_model.py --artifacts            # proved against the fresh artifacts
```

`build_airplane.py` refreshes the local bundle and then calls
`scripts/export_aircraft_variants.py`, so the four variant archives are always
rebuilt with the FMUs; `--skip-variant-export` skips that step.

`build_airplane.py` resolves an interpreter that imports `pyssp_sysml2`,
`pyssp_standard`, `pyssp_workflow` and `pycps_sysml2` and has `pyfmi`
(`$PYTHON`, workspace venv, airplane venv, then the running interpreter), so it
never silently falls back to a bare system `python3`. `check_environment.sh
--source-build` applies the same resolution and also checks `omc`, `cmake` and a
C++ compiler.

One upstream fix was required to make that build work here and is part of the
setup, not a workaround: `pyssp_standard`'s XSD validators share one cached lxml
schema; validating it from the four parallel FMU-build threads corrupted the
heap ("double free"). Compile and validation are now serialised by a
process-wide lock (`common/xml_schema_validation.py`), with a threaded
regression test.

## 1. What must be modelled to start and run a federation

A run is complete only when all of the following are decided somewhere, once:

| fact | owner |
| --- | --- |
| process table: command, cwd, env, interpreter | entity plane `AircraftApplication` + the four app defs → manifest |
| launch contract: mode, readiness, timeout, order, dependency | entity plane `PysosSoS::LaunchSpec` → `startup_timeout` + `env.PYSOS_LAUNCH_MODE`/`PYSOS_READINESS`/`PYSOS_LAUNCH_ORDER`/`PYSOS_AFTER_PROCESS` |
| aircraft composition a variant builds on | entity plane `AircraftVariant :> AircraftModel`; the four variant roots inherit it |
| runnable variant selection | entity plane application `command` `--variant <Variant>` |
| per-instance RPR bind endpoint (one-way broadcast to the recorder) | entity plane variant `Transport` set (`bind_address`) → exported SSP |
| entity identity: site/application/entity and marking in the broadcast | entity plane variant `Identity` set → exported SSP |
| scenario/mission per entity | entity plane variant `Scenario` set → exported SSP; the application `scenario` names it in `PYSOS_SCENARIO` |
| run parameters per instance: placement, waypoint frame, reference origin (realtime on the command, stop time from `Timing`) | entity plane variant sets + application `waypointFrame` → exported SSP |
| shared frame: origin, axis order, waypoint frame | system plane (`sos/federation_system.sysml`) |
| timing contract: step, sample period, watchdog, epoch, barrier, overrun policy | system plane |
| host-side processes: supervisor/recorder, viewer, builder | system plane |
| data flows: which endpoint feeds which consumer, encoding, rate | system plane |
| aircraft composition: 11 FMUs, their ports, parameters and 23 wires | imported from `3rd_party/airplane/architecture/aircraft.sysml` |
| artifact binding: baseline SSP, scenario SSV/SSM | system plane |
| artifacts: run directory and the files the run is judged by | system plane |

The entity plane is lowered, not re-authored: `pysos_sysml` turns the SysML
federation into the `pysos_coordinate` manifest (schema 1). The system plane is
a project document. No fact is written down twice: per-variant values live once
in the variant `ParameterSet` sets and reach the run through the exported SSP;
the manifest carries the process facts. `scripts/sos_model.py` resolves the
system plane *against* the manifest and fails on any gap.

The aircraft and its participants are **imported, not restated**:
`sos/federation_system.sysml` says `private import Aircraft::*;` and
`private import AircraftFederation::*;`, and the checker loads
`3rd_party/airplane/architecture/aircraft.sysml` (package `Aircraft`, declared by
the `architecture` attribute), `sos/aircraft_federation.sysml` (package
`AircraftFederation`, declared by the `entity_model` attribute) and the bundled
RPR entity definition from `pyfmi_rpr`. Eleven FMI 2.0 co-simulation FMUs (nine
Modelica models plus `rpr_state_source` and `rpr_entity`), their ports,
parameter-set defaults, FMU sources and the 23 inter-component connections come
from `AircraftModel`. The system plane declares one part per
`AircraftFederation::Federation` participant, typed by the entity plane's
`<X>Participant` def and in the entity plane's order; each participant brings
its nested `aircraft : <Variant>`, `application` and the one RPR broadcast
boundary port (`telemetry`, which no SSP component declares). That port is the
structural process boundary, not a Boolean `external` flag. `sos_model.py` fails
if a participant part is missing, typed with another participant def, or declared
out of order, and it walks each variant's `specializes` chain to prove it
reaches `AircraftModel`.

Import resolution works with the shipped `pycps_sysml2`; the model names the
architecture and entity files, and the checker supplies the `PysosSoS`,
`PysspCore` and `RprEntity` include roots. The
SSP's `SystemStructure.ssd` stays authoritative for field-level wiring;
the checker proves the built SSP still matches the imported model instead of
duplicating 286 scalar connectors in SysML.

| aircraft parameter | value | where it comes from |
| --- | --- | --- |
| `rpr_entity.transport` | `udp` | variant `Transport` set → exported SSP |
| `rpr_entity.bind_address` | 5510, 5512, 5514, 5516 | variant `Transport.bind_address` → exported SSP |
| `rpr_entity.peer_address` | `127.0.0.1:5505` | variant `Transport.peer_address` → exported SSP |
| `rpr_state_source.entity_site` / `entity_application` / `entity_entity` | 1 / 1 / 1–4 | variant `Identity` set → exported SSP |
| `rpr_state_source.marking_characters` | RED-1, RED-2, BLUE-1, BLUE-2 | variant `Identity` set → exported SSP |
| `rpr_state_source.reference_latitude_deg` / `reference_longitude_deg` / `reference_altitude_m` | −2.957519 / 39.232955 / 0 | variant `Identity` set (equals `FrameOrigin`) → exported SSP |
| `environment.initX_km` / `initY_km` | placement offsets 0/0, 0/5, 0/10, 0/15 km | variant `Scenario` set → exported SSP |
| `autopilot_module.waypoint*_km`, `targetAirspeed_mps` | scenario | variant `Scenario` set → exported SSP |
| `simulation.stop_time` / `timestep` | 120 s / 0.1 s | `Timing` → exported SSP `DefaultExperiment` / ssp4sim config |

## 2. Which pyssporg pieces are reasonable here

`pysp_dev/repos/*` refers to the workspace superproject; verdicts are for a
system-of-systems layer, not for the aircraft model.

| piece | what it actually owns | verdict at SoS level |
| --- | --- | --- |
| `experimental_pyssp_standard` (SSP/SSD/SSV/SSM) | describes and packs FMU composition: components, connectors, connections, parameter sets/mappings, `DefaultExperiment`; no executor | **rejected as the SoS model, adopted inside an instance.** Components are FMUs and connections are FMI connectors, so an entity's internals belong here (`build/ssp/scenario.ssp`), but a process federation is not an SSP. `pyssp_standard` has no process, timing policy, entity identity or frame. |
| `pysos_sysml` | lowers one SysML package of `part` usages to the coordinator manifest | **adopted for the entity plane.** It now uses the `pycps_sysml2` base for imports/include roots, entity composition (`part aircraft : AircraftModel`) and the shared `PysosSoS::LaunchSpec`. It still rejects ports, connections and timing, so run parameters ride in the exported variant SSPs and the application names its variant on the command line. The entity plane and the system plane therefore compose the same imported `AircraftModel` instead of restating it. |
| `pycps_sysml2` (the SysML v2 IR) | parses packages, part/port definitions, part usages, port usages, connections and typed attribute values (`Real`, `Integer`, `Boolean`, `String`) | **adopted as the system-plane lowering.** It already carries what `pysos_sysml` rejects, so the system plane is authored as SysML v2 and lowered here. Gap: part-usage multiplicity is dropped; the model no longer relies on it — participant count and order come from `AircraftFederation::Federation` through `effective_members`. It also carries cross-package imports (`Architecture.imports`), which is how the aircraft architecture and the entity plane are pulled in. |
| `pysos_coordinate` | process supervision: spawn, log, SIGTERM/SIGKILL by process group, exit codes | **adopted.** It owns no clock: `timing` accepts only `wall_clock` and is never read by the supervisor; `startup_timeout` is validated but unenforced; there is no readiness gate, heartbeat or restart. The timing contract below records this instead of pretending otherwise. |
| `ssp4sim` + `pyssp4sim` | per-instance fixed-step FMI 2.0 CS execution, absolute-deadline wall-clock pacing | **adopted, one process per instance.** `realtime: true` is a blocking `sleep_until` from a `CLOCK_MONOTONIC` reference captured at executor construction; no drift estimate and no overrun policy (an overrun free-runs until it catches up). There is no external `doStep`, pause or command channel. |
| `pyssp_simulate` | config construction, backend dispatch, result CSV reading | **adopted** as the thin wrapper that runs the ssp4sim child process. |
| `pysos_interop` | neutral `EntityState`, JSONL/DIS codecs, UDP `Channel`, dead reckoning, `SampleFanIn` barrier, truth/measure export | **adopted as the data-plane contract.** It defines identity, frames, rates and staleness, and it is where sample alignment lives (ordinal sample index, watchdog flush). |
| `pysos_rpr` | protobuf RPR-derived vocabulary and projection helpers | **adopted at the edge only** (the recorder's RPR loopback). It carries no time and no transport, so it cannot model the run. |
| `pyssp_vv` | trajectory loading and comparison metrics | **adopted** for post-run judgement; not part of the start/run model. |
| `pyspp_sysml2` | SysML v2 → SSP/SSD/SSV/SSM generation | **rejected here**: it targets FMU composition, not a process federation. |
| `pyfmi_interop` | non-FMI software generated as FMI 2.0 CS FMUs, realtime scheduler with overrun policies, UDP/TCP transport, rate groups | **future, and the obvious route to a hardened timing contract.** Unused today because the harness deliberately keeps `ssp4sim` pacing and adds no second sync layer (`docs/simulation_workflow.md`, "Timing approach"). |
| `pyfmu_csv` | builds FMI CS FMUs from CSV-described signals | not applicable until a non-FMI participant must be wrapped. |

The two tempting shortcuts are wrong for the same reason: an SSP/SSD at the SoS
level would model FMU connectors that no engine steps, and a
`pysos_coordinate` manifest alone models processes but not the frame, timing or
flows they share.

## 3. Model layout

```
sos/aircraft_federation.sysml     entity plane, SysML v2, lowered by pysos_sysml
  ├─ private imports              Aircraft::* / PysosSoS::* / PysspCore::*
  ├─ marker ports                 RprBroadcast / RprListener (no attributes)
  ├─ AircraftVariant :> AircraftModel   the export root, inherited by four variants
  ├─ 12 ParameterSet defs         4 variants × Scenario / Identity / Transport
  ├─ four variant roots           19 binds each (18 original + waypointCount)
  ├─ AircraftApplication + 4 apps participant, roles, scenario, command, cwd,
  │                               waypointFrame, LaunchSpec
  ├─ four participants            part aircraft / part application / port telemetry
  └─ part def Federation          four scalar participant usages
     └─ manifests/aircraft_federation.manifest.json   schema 1 (pysos_coordinate)
sos/federation_system.sysml       system plane, SysML v2, lowered by pycps_sysml2
  ├─ private import Aircraft::*   the same composition, parameters, FMU sources
  ├─ private import AircraftFederation::*  participants, their types and order
  ├─ private import PysosSoS::*   the same launch vocabulary for host processes
  └─ scripts/sos_model.py         lowered model + manifest resolution + checks
scripts/entity_manifest.py        lowers the entity plane with its include roots
scripts/export_aircraft_variants.py  exports build/ssp/variants/<Variant>.ssp
tests/test_sos_model.py           the completeness gate
```

Two SysML files, one per plane, because `pysos_sysml` still rejects the
constructs the system plane needs (ports, connections, timing) and no single
lowering accepts both. The system plane imports the entity plane for its
participant defs and their order, and the two planes share the same imported
`AircraftModel` and the same `LaunchSpec` vocabulary; `scripts/sos_model.py`
proves the entity plane, the manifest and the system plane agree. Each file is
the only authority for its plane; the system plane references the entity plane,
never restates it.

Entity-plane instance command (one line per application in the SysML):

```
../venv/bin/python scripts/run_instance_process.py --realtime --variant RedStriker
```

`run_instance_process.py` derives its 1-based index (ports, defaults) from
`PYSOS_TELEMETRY_PORT`, copies the pre-exported
`build/ssp/variants/<Variant>.ssp` byte-for-byte, writes only the ssp4sim
config, then `exec`s ssp4sim, so the supervised process is the simulation
itself. In variant mode it does not rewrite scenario/identity/transport
SSV/SSM; that legacy rewrite path remains for the baseline bundle.

System-plane SysML (package `FederationSystem`, entry `part def
SystemDescription`):

- `port def RprBroadcast` / `RprListener` — imported from the entity plane
  (`AircraftFederation::*`); role markers with no attributes.
  The flow contract is derived from its owners: protocol from each source's
  variant `Transport` set (`udp`), encoding from the imported
  `RprEntity::RprContract.version` (`rpr.v2` → `rpr`), rate from
  `Timing.step_size_s` (0.1 s → 10 Hz), and the listener port from
  `Orchestrator.rprPort` (5505), so nothing is copied;
- `part def FrameOrigin` — federation origin (geodetic), axis order, waypoint
  frame, and the scenario point the origin must equal;
- `part def Timing` — `soft_realtime`, 0.1 s step, 10 Hz sample period, 2.0 s
  fan-in watchdog, 0.25 s recording interval, 120 s stop time,
  `per_process_monotonic` epoch, `barrier: none`, `overrun_policy: lag`;
- imported entity participants — `part red_interceptor : RedInterceptorParticipant`
  (then `red_striker`, `blue_cas`, `blue_baseline`) mirror
  `AircraftFederation::Federation` by type and order; each participant brings
  its nested variant `aircraft`, `application` and the structural
  `telemetry : RprBroadcast` port. Identity, endpoints, scenario values and the
  application stay in the entity plane;
- `part def Orchestrator` / `Viewer` / `Builder :> Application` — the host-side
  processes specialize the shared `PysosSoS::Application` (roles, command, cwd)
  and declare their own nested `part launch : LaunchSpec` (`mode`, `readiness`,
  `timeout_s`, `order`, `after_process`). `sos_model.py` resolves inherited
  members through `effective_members` and validates the launch graph: builder
  order 0, orchestrator after the builder, viewer after the recorder, no cycles.
  The orchestrator binds RPR 5505; the viewer reads the recorder truth file and
  owns no socket;
- `connection rpr_broadcast_<part> connect <part>.telemetry to
  orchestrator.rpr_in` — one RPR broadcast flow per participant; each lowers to
  an `instance/<part>/telemetry` source, and its protocol, encoding and rate
  come from the source owners, not the marker port;
- `part def Artifacts` — `build/runs/sos4` and the files the run is judged by.

## 4. Frame contract

The simulation frame is a flat local tangent plane at the federation origin:
`x` north, `y` east, `z` up, kilometres
(`3rd_party/airplane/scripts/lib/common/geo/geometry.py:50-66`). The viewer and
recorder use ENU metres, `(east, north, up) = (y, x, z)`
(`flight_viewer/geo.py:48-51`). The geodetic origin is needed to encode
RPR/DIS ECEF; relative geometry never uses it.

Each aircraft scenario is authored around its own `points[0]`, and the four
checked-in scenarios disagree by thousands of kilometres. Left alone, four
entities would publish four different local frames while the recorder converts
them all with a single origin. `waypointFrame = "federation"` on every
`AircraftApplication` closes that hole: the variant's placement offset is
applied to the scenario waypoints as well as to the initial position, and the
export carries the policy into the SSP, so every entity is expressed in the
federation frame. The model declares which frame policy is in force, and the
check fails if a variant's `waypointFrame` is not `federation`.

## 5. Timing contract, stated honestly

What the model declares:

| fact | value | why |
| --- | --- | --- |
| class | `soft_realtime` | ssp4sim pacing is best-effort; no hard-RT claim |
| step | 0.1 s | `architecture/aircraft.sysml` baseline, ssp4sim macro step |
| sample period / rate | 0.1 s / 10 Hz | RPR publish cadence and fan-in grid |
| fan-in watchdog | 2.0 s | partial-sample flush in `SampleFanIn` |
| stop time | 120 s | federation run window; per variant via the exported SSP `DefaultExperiment` |
| epoch | `per_process_monotonic` | clock reference is per ssp4sim process |
| barrier | `none` | no shared epoch, no step barrier |
| overrun policy | `lag` | overrunning steps free-run, no abort/skip |

Consequences that the model makes explicit:

- simultaneous execution means "all instances started, each paced from its own
  monotonic reference"; the skew is the sum of preparation, spawn and FMU
  initialisation, is not measured, and is not compensated;
- sample alignment exists only in the recorder (ordinal index × 0.1 s, 2 s
  watchdog), not between simulators; sub-sample interaction is not meaningful;
- every entity publishes one-way; the recorder never feeds a command back, so
  there is no control channel to lock-step.

## 6. What the check proves

`scripts/sos_model.py` fails the model when any of these is untrue:

1. the manifest parses and validates through `pysos_coordinate`, and its
   `name`, `schema` (1) and `timing` match the model;
2. every instance has exactly one entity and one telemetry endpoint, a
   non-empty command, and no control endpoint;
3. every application command names its runnable variant with `--variant`, and
   `--realtime` never contradicts `timing.realtime`;
4. stop time and sample period are integer multiples of the step, and the
   watchdog is longer than the sample period;
5. the frame origin is in range and equals `points[n]` of the scenario the model
   cites; every variant's `waypointFrame` is `federation`, its identity
   reference origin equals the frame origin, its placement offsets match the
   expected values, and no two entities share a placement;
6. entity slugs and markings are unique, the variant identity sets equal the
   manifest entities, `env.PYSOS_TELEMETRY_PORT` equals the manifest telemetry
   port, `PYSOS_SCENARIO` equals the application `scenario`, and no host
   process is named like an instance;
7. no UDP port is declared twice across instances and host ports;
8. every instance telemetry port feeds the modelled RPR broadcast flow, and the
   flow contract resolves from its owners (transport, `RprContract.version`,
   `Timing.step_size_s`, `Orchestrator.rprPort`);
9. a supervisor process names the same manifest, viewer/recorder `--scenario`
   matches the frame reference, `--run-dir` matches `artifacts.run_dir`, and the
   viewer replays the recorder truth file (`--source jsonl`, `--path`
   `artifacts.run_dir/truth.jsonl`) with no `--telemetry` socket;
10. the artifact set contains `truth`, `measurements` and `run`, with unique
    paths and a repository-relative run directory;
11. the entity plane loads with its `Aircraft`/`PysosSoS`/`PysspCore` include
    roots, the package name matches the federation, every variant composes the
    same `AircraftModel` the system plane imported, its bind/peer addresses
    match the manifest and the system listener, and its identity and
    `LaunchSpec` agree with the manifest (mode, readiness, order, after-process,
    `startup_timeout`);
12. the built baseline `scenario.ssp` matches the imported aircraft: the same
    eleven components with the same FMU files, every modelled port present as an
    SSD connector, every modelled parameter present as an SSD parameter
    connector (arrays as `name[i]`), every modelled wire present as SSD
    connections, FMI 2.0 CoSimulation, the RPR deployment defaults, and the
    `MissionScenario.ssv`/`HighAltitudeIntercept.ssm` binding. The baseline
    `aircraft.ssp` must stay unbound; the four `build/ssp/variants/*.ssp`
    archives are checked by `export_aircraft_variants.py` at export time, not
    re-parsed here.

## 7. Known gaps (next iterations, in order of value)

1. **Readiness and epoch.** The model now declares a `PysosSoS::LaunchSpec`
   (`mode`, `readiness`, `timeout_s`, `order`, `after_process`) for every entity
   and host process, and the entity plane lowers it to `startup_timeout` plus
   `env.PYSOS_LAUNCH_MODE`/`PYSOS_READINESS`/`PYSOS_LAUNCH_ORDER`/
   `PYSOS_AFTER_PROCESS`. `sos_model.py` validates the host launch graph.
   `pysos_coordinate` still spawns
   sequentially with no readiness gate and does not enforce `startup_timeout`.
   A handshake (port bound or log line) plus a shared start instant would turn
   "started" into "started together". Until then, `epoch:
   per_process_monotonic` is the truth and the launch contract is declared, not
   enforced.
2. **External stepping.** `doStep(t)`/pause/resume is explicitly not implemented
   in ssp4sim (`IMP-037`) and the workflow doc forbids adding a second sync
   layer for now. That is the prerequisite for any barrier-based federation.
3. **One SysML file.** The federation is still two SysML files. `pysos_sysml`
   now accepts imports/include roots, entity composition and `LaunchSpec`, so
   both planes compose the same aircraft and share the launch vocabulary.
   Collapsing the planes also needs ports, connections and timing in the entity
   lowerer, and a way to express the per-variant run parameters without a
   separate export step. Until then the split and the exported variant SSPs are
   deliberate.
4. **Viewer launch.** The viewer is not started by the coordinator; it is a
   manual replay of the recorder truth file, so the file path is duplicated and
   only guarded by the check. Launching it as another supervised instance would
   remove the duplication.
5. **Entity type/force.** `rpr_state_source` carries site/application/entity,
   marking and force; the instance preparer still publishes neutral entity
   type and force defaults because the manifest has no fields for them.
6. **Heterogeneous participants.** Any non-FMI software joining the federation
   would need `pyfmi_interop` (FMU wrapper, overrun policies, its own transport),
   which would then supersede `overrun_policy: lag`.
