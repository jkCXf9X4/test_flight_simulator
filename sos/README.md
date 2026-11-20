# Aircraft federation

Four aircraft authored in `aircraft_federation.sysml` (package
`AircraftFederation`) and lowered to `manifests/aircraft_federation.manifest.json`.
Each part is a scalar usage of the empty part def `AircraftEntity`.

| Usage | Callsign | Scenario | Telemetry | Control |
| --- | --- | --- | --- | --- |
| `red_interceptor` | `RED-1` | `high_altitude_intercept` | 5510 | 5511 |
| `red_striker` | `RED-2` | `deep_strike_penetration` | 5512 | 5513 |
| `blue_cas` | `BLUE-1` | `cas_multi_store_support` | 5514 | 5515 |
| `blue_baseline` | `BLUE-2` | `test_scenario` | 5516 | 5517 |

All four run site 1 / application 1, entities 1–4, from the repository root
with `python scripts/run_instance_process.py`.

Every entity publishes telemetry one-way and never addresses another entity;
there are no entity-to-entity links in the setup.

Each instance command also carries the run parameters the narrow `pysos_sysml`
subset cannot type: `--realtime`, `--stop-time 120`, its placement offsets, and
`--waypoint-frame federation`.

## System plane

`federation_system.sysml` (package `FederationSystem`) models everything that is
not an aircraft instance: the shared frame and origin, the timing contract, the
aircraft (`private import Aircraft::*;` — the real composition, parameters and
FMU sources come from `3rd_party/airplane/architecture/aircraft.sysml`; the
system plane adds only the two `external` boundary ports), the
host-side participants (`orchestrator` = supervisor + recorder on RPR 5505,
`viewer`, `pilot`, `builder`), the flows between them and the run artifacts. It is SysML v2
lowered through `pycps_sysml2` by `scripts/sos_model.py`, and it references the
entity plane instead of repeating it (`part instances : AircraftInstance [4]`, typed by the imported `AircraftModel`).

```bash
PY=/home/eriro/pwa/2_work/flight_sim/venv/bin/python3
$PY -m pysos_sysml manifest sos/aircraft_federation.sysml -o manifests/aircraft_federation.manifest.json --check
$PY scripts/sos_model.py              # entity plane + system plane + frame + timing + flows
$PY scripts/sos_model.py --artifacts  # also require the built SSPs to match
./scripts/build_airplane.py           # build the full aircraft (after --source-build checks)
```

Omit `--check` from the first command (or drop `-o`) to regenerate the manifest.
`docs/sos_model.md` explains the two-plane split, which pyssporg piece owns
which fact, and the frame/timing contracts.
