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
./scripts/build_airplane.py                     # 9 Modelica FMUs + native UdpBridge + SSPs
$PY scripts/sos_model.py --artifacts            # proved against the fresh artifacts
```

`build_airplane.py` resolves an interpreter that imports `pyssp_sysml2`,
`pyssp_standard`, `pyssp_workflow` and `pycps_sysml2` and has `pyfmi`
(`$PYTHON`, workspace venv, airplane venv, then the running interpreter), so it
never silently falls back to a bare system `python3`. `check_environment.sh
--source-build` applies the same resolution and also checks `omc`, `cmake` and a
C++ compiler.

Two upstream fixes were required to make that build work here and are part of
the setup, not workarounds:

- `pyssp_standard`'s XSD validators share one cached lxml schema; validating it
  from the four parallel FMU-build threads corrupted the heap ("double free").
  Compile and validation are now serialised by a process-wide lock
  (`common/xml_schema_validation.py`), with a threaded regression test.
- The native bridge test stepped once, but `BridgeRuntime::do_step` deliberately
  skips the first communication step (connected inputs still carry zeros). The
  test now steps twice.

## 1. What must be modelled to start and run a federation

A run is complete only when all of the following are decided somewhere, once:

| fact | owner |
| --- | --- |
| process table: command, cwd, env, interpreter | entity plane (`sos/aircraft_federation.sysml` → manifest) |
| entity identity: site/application/entity, marking | entity plane |
| per-instance UDP endpoints: telemetry out, control in | entity plane |
| scenario/mission per entity | entity plane (`scenario` attribute → `PYSOS_SCENARIO`) |
| run parameters per instance: realtime, stop time, placement, waypoint frame | entity plane (`command` argv) |
| shared frame: origin, axis order, waypoint frame | system plane (`sos/federation_system.sysml`) |
| timing contract: step, sample period, watchdog, epoch, barrier, overrun policy | system plane |
| host-side processes: supervisor/recorder, viewer, operator | system plane |
| data flows: which endpoint feeds which consumer, encoding, rate | system plane |
| aircraft composition: 10 FMUs, their ports, parameters and 24 wires | imported from `3rd_party/airplane/architecture/aircraft.sysml` |
| artifact binding: baseline SSP, scenario SSV/SSM, `useBridgeInput` | system plane |
| artifacts: run directory and the files the run is judged by | system plane |

The entity plane is lowered, not re-authored: `pysos_sysml` turns the SysML
federation into the `pysos_coordinate` manifest (schema 1). The system plane is
a project document. No fact is written down twice; `scripts/sos_model.py`
resolves the system plane *against* the manifest and fails on any gap.

The aircraft is **imported, not restated**: `sos/federation_system.sysml` says
`private import Aircraft::*;` and the checker loads
`3rd_party/airplane/architecture/aircraft.sysml` (package `Aircraft`, declared by
the `architecture` attribute) alongside it. Ten FMI 2.0 co-simulation FMUs, their
ports, parameter-set defaults, FMU sources and the 24 inter-component
connections come from `AircraftModel`; the system plane adds only
`part def AircraftInstance` with the two `external` UDP boundary ports
(`telemetry`/`control`, which no SSP component declares).

Import resolution works with the shipped `pycps_sysml2`; the model only has to
name the architecture file, because a package name cannot be mapped back to a
path. The SSP's `SystemStructure.ssd` stays authoritative for field-level wiring;
the checker proves the built SSP still matches the imported model instead of
duplicating 286 scalar connectors in SysML.

| aircraft parameter | value | where it comes from |
| --- | --- | --- |
| `udp_bridge.telemetry_port` / `control_port` | 5510/5511, 5512/5513, 5514/5515, 5516/5517 | manifest instance endpoints → SSV/SSM |
| `udp_bridge.reference_latitude_deg` / `longitude_deg` / `altitude_m` | −2.957519 / 39.232955 / 0 | `FrameOrigin` → instance argv → SSV/SSM |
| `environment.initX_km` / `initY_km` | placement offsets 0/0, 0/5, 0/10, 0/15 km | instance argv → SSV/SSM |
| `autopilot_module.waypoint*_km`, `targetAirspeed_mps` | scenario | scenario JSON → SSV/SSM |
| `control_interface.useBridgeInput` | `false` | `FederationOverrides.bridge_input` → SSV/SSM |
| `simulation.stop_time` / `timestep` | 120 s / 0.1 s | `Timing` → instance argv / config |

## 2. Which pyssporg pieces are reasonable here

`pysp_dev/repos/*` refers to the workspace superproject; verdicts are for a
system-of-systems layer, not for the aircraft model.

| piece | what it actually owns | verdict at SoS level |
| --- | --- | --- |
| `experimental_pyssp_standard` (SSP/SSD/SSV/SSM) | describes and packs FMU composition: components, connectors, connections, parameter sets/mappings, `DefaultExperiment`; no executor | **rejected as the SoS model, adopted inside an instance.** Components are FMUs and connections are FMI connectors, so an entity's internals belong here (`build/ssp/scenario.ssp`), but a process federation is not an SSP. `pyssp_standard` has no process, timing policy, entity identity or frame. |
| `pysos_sysml` | lowers one SysML package of `part` usages to the coordinator manifest | **adopted for the entity plane only.** Its subset is deliberately narrow: exactly eight attributes per instance, no ports, no connections, no timing (ports/connections are parsed by `pycps_sysml2` but rejected by this loader). Consequence: run parameters must ride in `command` argv, and that is what §1 lists. |
| `pycps_sysml2` (the SysML v2 IR) | parses packages, part/port definitions, part usages, port usages, connections and typed attribute values (`Real`, `Integer`, `Boolean`, `String`) | **adopted as the system-plane lowering.** It already carries what `pysos_sysml` rejects, so the system plane is authored as SysML v2 and lowered here. Gap: part-usage multiplicity is dropped, so `part instances : AircraftInstance [4]` is recovered by a one-line lexical adjunct (the same workaround `pysos_sysml` uses). It also carries cross-package imports (`Architecture.imports`), which is how the aircraft architecture is pulled in. |
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
  └─ manifests/aircraft_federation.manifest.json   schema 1 (pysos_coordinate)
sos/federation_system.sysml       system plane, SysML v2, lowered by pycps_sysml2
  ├─ private import Aircraft::*   aircraft composition, parameters, FMU sources
  │    └─ 3rd_party/airplane/architecture/aircraft.sysml   (not duplicated)
  └─ scripts/sos_model.py         lowered model + manifest resolution + checks
tests/test_sos_model.py           the completeness gate
```

Two SysML files, one per plane, because `pysos_sysml` rejects the constructs the
system plane needs (ports, connections, attributes beyond the eight instance
ones) and no single lowering accepts both. Each file is the only authority for
its plane; the system plane references the entity plane, never restates it.

Entity-plane instance command (one line per entity in the SysML):

```
python scripts/run_instance_process.py --realtime --stop-time 120 \
  --offset-north-km 0 --offset-east-km 5 --waypoint-frame federation
```

`run_instance_process.py` derives its 1-based index (ports, defaults) from
`PYSOS_TELEMETRY_PORT`, prepares the per-instance SSP, then `exec`s ssp4sim, so
the supervised process is the simulation itself.

System-plane SysML (package `FederationSystem`, entry `part def
SystemDescription`):

- `port def` interfaces carry the flow contract — protocol, encoding, rate, and
  optionally `udp_port`. `RprListener` owns the only host-side port number
  (5505); every other number comes from the manifest, so nothing is copied;
- `part def FrameOrigin` — federation origin (geodetic), axis order, waypoint
  frame, and the scenario point the origin must equal;
- `part def Timing` — `soft_realtime`, 0.1 s step, 10 Hz sample period, 2.0 s
  fan-in watchdog, 0.25 s recording interval, 120 s stop time,
  `per_process_monotonic` epoch, `barrier: none`, `overrun_policy: lag`;
- `part def AircraftInstance` — the imported `AircraftModel` plus the two UDP
  boundary ports; `part instances : AircraftInstance [4]` is one occurrence per
  manifest entry, and identity, endpoints, scenario and run flags stay in the
  entity plane;
- `part def Orchestrator` / `Viewer` / `Pilot` — the host-side processes with
  `roles`, `launch`, `cwd`, `command` and typed ports;
- `connection <name> connect a.p to b.q` — the four flows; a connection to the
  multiplicity part lowers to the `instance/*` wildcard, and its protocol,
  encoding and rate come from the source port type;
- `part def Artifacts` — `build/runs/sos4` and the files the run is judged by.

## 4. Frame contract

The simulation frame is a flat local tangent plane at the federation origin:
`x` north, `y` east, `z` up, kilometres
(`3rd_party/airplane/scripts/lib/common/geo/geometry.py:50-66`). The viewer and
recorder use ENU metres, `(east, north, up) = (y, x, z)`
(`flight_viewer/geo.py:48-51`). The geodetic origin is only needed to encode
DIS/ECEF; relative geometry never uses it.

Each aircraft scenario is authored around its own `points[0]`, and the four
checked-in scenarios disagree by thousands of kilometres. Left alone, four
entities would publish four different local frames while the recorder converts
them all with a single origin. `--waypoint-frame federation` closes that hole:
the instance's placement offset is applied to the scenario waypoints as well as
to the initial position, so every entity is expressed in the federation frame.
The model declares which frame policy is in force, and the check fails if an
instance does not carry the flag.

## 5. Timing contract, stated honestly

What the model declares:

| fact | value | why |
| --- | --- | --- |
| class | `soft_realtime` | ssp4sim pacing is best-effort; no hard-RT claim |
| step | 0.1 s | `architecture/aircraft.sysml` baseline, ssp4sim macro step |
| sample period / rate | 0.1 s / 10 Hz | bridge cadence and fan-in grid |
| fan-in watchdog | 2.0 s | partial-sample flush in `SampleFanIn` |
| stop time | 120 s | federation run window; per instance via `--stop-time` |
| epoch | `per_process_monotonic` | clock reference is per ssp4sim process |
| barrier | `none` | no shared epoch, no step barrier |
| overrun policy | `lag` | overrunning steps free-run, no abort/skip |

Consequences that the model makes explicit:

- simultaneous execution means "all instances started, each paced from its own
  monotonic reference"; the skew is the sum of preparation, spawn and FMU
  initialisation, is not measured, and is not compensated;
- sample alignment exists only in the recorder (ordinal index × 0.1 s, 2 s
  watchdog), not between simulators; sub-sample interaction is not meaningful;
- control input is consumed by the bridge asynchronously (non-blocking read,
  1 s inactivity fallback), so pilot commands are not lock-stepped either.

## 6. What the check proves

`scripts/sos_model.py` fails the model when any of these is untrue:

1. the manifest parses and validates through `pysos_coordinate`, and its
   `name`, `schema` and `timing` match the model;
2. every instance has exactly one entity, one telemetry and one control
   endpoint, a non-empty command and a resolvable scenario file;
3. `timing.realtime` is reflected by `--realtime` in every instance command, and
   `timing.stop_time_s` by an equal `--stop-time`;
4. stop time and sample period are integer multiples of the step, and the
   watchdog is longer than the sample period;
5. the frame origin is in range and equals `points[n]` of the scenario the model
   cites; every instance carries the declared `--waypoint-frame` and explicit
   placement offsets, and no two entities share a placement;
6. entity slugs and markings are unique, and no host process is named like an
   instance;
7. no UDP port is declared twice across instances and host ports;
8. every instance telemetry port feeds at least one modelled flow, every control
   port has at least one modelled producer, and every flow endpoint resolves;
9. a supervisor process names the same manifest, viewer/recorder `--scenario`
   matches the frame reference, `--run-dir` matches `artifacts.run_dir`, and the
   viewer's `--telemetry` set equals the manifest telemetry endpoints;
10. the artifact set contains `truth`, `measurements` and `run`, with unique
    paths and a repository-relative run directory;
11. the built `scenario.ssp` matches the imported aircraft: the same ten
    components with the same FMU files, every modelled port present as an SSD
    connector, every modelled parameter present as an SSD parameter connector
    (arrays as `name[i]`), every modelled wire present as SSD connections, FMI
    2.0 CoSimulation, the bridge's parameter defaults, the
    `MissionScenario.ssv`/`HighAltitudeIntercept.ssm` binding, and a
    `useBridgeInput` value equal to `FederationOverrides.bridge_input`.

## 7. Known gaps (next iterations, in order of value)

1. **Readiness and epoch.** `pysos_coordinate` spawns sequentially with no
   readiness gate, and `startup_timeout` is unenforced. A handshake (port bound
   or log line) plus a shared start instant would turn "started" into
   "started together". Until then, `epoch: per_process_monotonic` is the truth.
2. **External stepping.** `doStep(t)`/pause/resume is explicitly not implemented
   in ssp4sim (`IMP-037`) and the workflow doc forbids adding a second sync
   layer for now. That is the prerequisite for any barrier-based federation.
3. **One SysML file.** The federation is two SysML files because `pysos_sysml`
   rejects ports/connections/timing while `pycps_sysml2` accepts them. Teaching
   `pysos_sysml` to lower ports, connections and extra attributes would collapse
   both planes into one package and let per-instance run parameters leave the
   `command` string. Until then the split and the argv encoding are deliberate.
4. **Viewer launch.** The viewer is not started by the coordinator, so its
   telemetry list is duplicated and only guarded by the check. Launching it as
   another supervised instance would remove the duplication.
5. **Per-entity origin on the wire.** The bridge's `reference_*` fields exist but
   stay at their defaults. Emitting the true origin per entity would let a
   recorder accept non-rebased instances.
6. **Entity type/force.** `EntityRef` carries site/application/entity and
   marking only; DIS/RPR entity type and force still come from viewer config.
7. **Heterogeneous participants.** Any non-FMI software joining the federation
   would need `pyfmi_interop` (FMU wrapper, overrun policies, its own transport),
   which would then supersede `overrun_policy: lag`.
