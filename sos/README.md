# Aircraft federation

Four aircraft variants authored in `aircraft_federation.sysml` (package
`AircraftFederation`) and lowered to `manifests/aircraft_federation.manifest.json`.
The entity plane has four layers: the `RprBroadcast`/`RprListener` markers (no
attributes); `AircraftVariant :> AircraftModel`, the export root that inherits
the real architecture (`private import Aircraft::*;`) so the aircraft is not
restated; twelve `ParameterSet` defs (Scenario/Identity/Transport per variant)
bound on each variant root; and `AircraftApplication` plus four app defs and
participant defs, joined by `part def Federation`. Every application declares a
shared `part launch : LaunchSpec` (`supervised`, `port_bound`, 30 s, order 2,
after the `supervisor` role) from the `PysosSoS` vocabulary shipped by
`pysos_sysml`.

| Variant | Callsign | Scenario | RPR bind port |
| --- | --- | --- | --- |
| `RedInterceptor` | `RED-1` | `high_altitude_intercept` | 5510 |
| `RedStriker` | `RED-2` | `deep_strike_penetration` | 5512 |
| `BlueCas` | `BLUE-1` | `cas_multi_store_support` | 5514 |
| `BlueBaseline` | `BLUE-2` | `test_scenario` | 5516 |

All four run site 1 / application 1, entities 1–4, from the repository root
with `python scripts/run_instance_process.py --realtime --variant <Variant>`.
Scenario, identity and transport values live in that variant's exported SSP;
the application `scenario` only supplies the descriptive `PYSOS_SCENARIO` name.
`build/ssp/variants/<Variant>.ssp` carries the inherited aircraft, the bound
parameter sets, the `DefaultExperiment` and the FMU sources, and the instance
bundle copies it byte-for-byte.

Every entity broadcasts its own RPR entity state one-way to the recorder on
`127.0.0.1:5505` and never addresses another entity; there are no
entity-to-entity links in the setup. The aircraft's `rpr_entity` binds the
variant telemetry endpoint (5510/5512/5514/5516) and peers at 5505.

## System plane

`federation_system.sysml` (package `FederationSystem`) models everything that is
not an aircraft instance: the shared frame and origin, the timing contract, the
aircraft (`private import Aircraft::*;` — the real composition, parameters and
FMU sources come from `3rd_party/airplane/architecture/aircraft.sysml`; the
system plane adds only the structural RPR broadcast boundary port), the host-side
participants (`orchestrator` = supervisor + recorder listening on RPR 5505,
`viewer` replaying the recorder truth stream, `builder`), the flow between them
and the run artifacts. It is SysML v2 lowered through `pycps_sysml2` by
`scripts/sos_model.py`, and it references the entity plane instead of repeating
it (`part instances : AircraftInstance [4]`, typed by the imported
`AircraftModel`).

```bash
PY=/home/eriro/pwa/2_work/flight_sim/venv/bin/python3
$PY scripts/entity_manifest.py --check   # lower the entity plane with its include roots
$PY scripts/export_aircraft_variants.py  # build build/ssp/variants/<Variant>.ssp (4 archives)
$PY scripts/sos_model.py                 # entity plane + system plane + frame + timing + flow
$PY scripts/sos_model.py --artifacts     # also require the built SSPs to match
./scripts/build_airplane.py              # build the full aircraft, then export the variants
```

Omit `--check` from the first command (or drop `-o`) to regenerate the manifest.
`docs/sos_model.md` explains the two-plane split, which pyssporg piece owns
which fact, and the frame/timing contracts.
