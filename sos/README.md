# Aircraft federation

Four aircraft authored in `aircraft_federation.sysml` (package
`AircraftFederation`) and lowered to `manifests/aircraft_federation.manifest.json`.
Each part is a scalar usage of the empty part def `AircraftEntity`.

| Usage | Callsign | Scenario | RPR bind port |
| --- | --- | --- | --- |
| `red_interceptor` | `RED-1` | `high_altitude_intercept` | 5510 |
| `red_striker` | `RED-2` | `deep_strike_penetration` | 5512 |
| `blue_cas` | `BLUE-1` | `cas_multi_store_support` | 5514 |
| `blue_baseline` | `BLUE-2` | `test_scenario` | 5516 |

All four run site 1 / application 1, entities 1–4, from the repository root
with `python scripts/run_instance_process.py`. Each command carries its entity
identity (`--entity-site`, `--entity-application`, `--entity`, `--marking`) and
the federation reference origin so the per-instance bundle can write them into
`rpr_state_source`; the other run parameters ride in `command` because the
narrow `pysos_sysml` subset cannot type them. `controlPort` remains in the
entity plane only because the current `pysos_sysml` loader requires it; the
control endpoint and `PYSOS_CONTROL_PORT` are vestigial and the aircraft no
longer consumes them.

Every entity broadcasts its own RPR entity state one-way to the recorder on
`127.0.0.1:5505` and never addresses another entity; there are no
entity-to-entity links in the setup. The aircraft's `rpr_entity` binds the
instance telemetry endpoint (5510/5512/5514/5516) and peers at 5505.

## System plane

`federation_system.sysml` (package `FederationSystem`) models everything that is
not an aircraft instance: the shared frame and origin, the timing contract, the
aircraft (`private import Aircraft::*;` — the real composition, parameters and
FMU sources come from `3rd_party/airplane/architecture/aircraft.sysml`; the
system plane adds only the external RPR broadcast boundary port), the host-side
participants (`orchestrator` = supervisor + recorder listening on RPR 5505,
`viewer` replaying the recorder truth stream, `builder`), the flow between them
and the run artifacts. It is SysML v2 lowered through `pycps_sysml2` by
`scripts/sos_model.py`, and it references the entity plane instead of repeating
it (`part instances : AircraftInstance [4]`, typed by the imported
`AircraftModel`).

```bash
PY=/home/eriro/pwa/2_work/flight_sim/venv/bin/python3
$PY -m pysos_sysml manifest sos/aircraft_federation.sysml -o manifests/aircraft_federation.manifest.json --check
$PY scripts/sos_model.py              # entity plane + system plane + frame + timing + flow
$PY scripts/sos_model.py --artifacts  # also require the built SSPs to match
./scripts/build_airplane.py           # build the full aircraft (after --source-build checks)
```

Omit `--check` from the first command (or drop `-o`) to regenerate the manifest.
`docs/sos_model.md` explains the two-plane split, which pyssporg piece owns
which fact, and the frame/timing contracts.
