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

Check the manifest with `pysos-sysml manifest sos/aircraft_federation.sysml -o manifests/aircraft_federation.manifest.json --check`; omit `--check` (or drop `-o`) to regenerate it.
