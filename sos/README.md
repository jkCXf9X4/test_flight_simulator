# Aircraft federation

Four aircraft variants authored in `aircraft_federation.sysml` (package
`AircraftFederation`) and lowered to `manifests/aircraft_federation.manifest.json`.
The entity plane has four layers: the `RprBroadcast`/`RprListener` markers (no
attributes); `AircraftVariant :> AircraftModel`, the export root that inherits
the real architecture (`private import Aircraft::*;`) so the aircraft is not
restated; twelve `ParameterSet` defs (Scenario/Identity/Transport per variant)
bound on each variant root; and `AircraftApplication` plus four app defs and
participant defs, joined by `part def Federation`. Every application declares a
shared `part launch : LaunchSpec` (`supervised`, `socket_bound`, 30 s, order 2,
after the `supervisor` role) from the `PysosSoS` vocabulary shipped by
`pysos_sysml`.

| Variant | Callsign | Scenario | RPR bind socket |
| --- | --- | --- | --- |
| `RedInterceptor` | `RED-1` | `high_altitude_intercept` | `@pysos-red-interceptor` |
| `RedStriker` | `RED-2` | `deep_strike_penetration` | `@pysos-red-striker` |
| `BlueCas` | `BLUE-1` | `cas_multi_store_support` | `@pysos-blue-cas` |
| `BlueBaseline` | `BLUE-2` | `test_scenario` | `@pysos-blue-baseline` |

All four run site 1 / application 1, entities 1–4, from the repository root
with `python scripts/run_instance_process.py --realtime --variant <Variant>`.
Scenario, identity and transport values live in that variant's exported SSP;
the application `scenario` only supplies the descriptive `PYSOS_SCENARIO` name.
`build/ssp/variants/<Variant>.ssp` carries the inherited aircraft, the bound
parameter sets, the `DefaultExperiment` and the FMU sources, and the instance
bundle copies it byte-for-byte.

Every entity broadcasts its own RPR entity state one-way to the recorder on
`@pysos-recorder` and never addresses another entity; there are no
entity-to-entity links in the setup. The aircraft's `rpr_entity` binds its
variant telemetry socket (`@pysos-red-interceptor` etc.) and peers at
`@pysos-recorder`. An explicit UDP model keeps the `127.0.0.1:5505` form.

## System plane

`federation_system.sysml` (package `FederationSystem`) models everything that is
not an aircraft participant: the shared frame and origin, the timing contract,
the host-side participants (`orchestrator` = supervisor + recorder listening on
`@pysos-recorder`, `viewer` replaying the recorder truth stream, `builder`), the flows
between them and the run artifacts. It imports both planes instead of repeating
them: `private import Aircraft::*;` brings the real aircraft composition
(`3rd_party/airplane/architecture/aircraft.sysml`), and
`private import AircraftFederation::*;` brings the entity plane's participant
defs and the order of `AircraftFederation::Federation`. The system plane
declares one part per participant (`part red_interceptor :
RedInterceptorParticipant;`, then `red_striker`, `blue_cas`, `blue_baseline`)
in that order, plus one `rpr_broadcast_<part>` connection each. It is SysML v2
lowered through `pycps_sysml` by `scripts/sos_model.py`, which fails if the
participants, their types or their order drift from the entity plane or the
manifest.

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
