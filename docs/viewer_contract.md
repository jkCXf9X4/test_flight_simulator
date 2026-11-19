# Viewer contract (phase 1)

Normative. Code in `flight_viewer/` must follow this document. Change the document
first, then the code.

The default path is newline-delimited JSON telemetry over UDP. DIS is an optional
codec imported from `pysos_interop`; sections that name DIS apply only to
`--source dis` / `--sink dis`.

## 1. Identity

- Entity id is the triple `(site, application, entity)`, each a 16-bit unsigned
  integer. Defaults: `site=1`, `application=1`, `entity=1..N`.
- Exactly one entity id per simulated aircraft. Uniqueness is asserted by a test
  over the exercise configuration; DIS itself does not enforce it.
- Exercise id: default `1`, 8-bit. Receivers drop datagrams with a different
  exercise id.
- Force id: default `1` (friendly), configurable per entity.
- Marking: ASCII, at most 11 characters, default `AC-<entity>`.

## 2. Entity type

Seven fields, all configurable:

| field | default |
| --- | --- |
| kind | 1 (Platform) |
| domain | 2 (Air) |
| country | 0 (Other) |
| category | 1 |
| subcategory | 0 |
| specific | 0 |
| extra | 0 |

## 3. Coordinates

- Wire: geocentric WGS84 ECEF metres for position and velocity, orientation as
  DIS `(psi, theta, phi)` radians.
- Viewer and model: local ENU metres `(east, north, up)`.
- The simulation's local frame is `x=north`, `y=east`, `z=up`, in kilometres
  (`scripts/lib/common/geo/geometry.py:65-66`). Mapping to ENU is
  `(east, north, up) = (y_km*1000, x_km*1000, z_km*1000)`.
- Origin: geodetic point of scenario `points[0]`. The bridge FMU's
  `reference_latitude_deg` defaults to `0` and is **not** used. If no scenario is
  given, the origin defaults to `(0, 0, 0)` and a warning is printed; encoding
  DIS requires an explicit origin.
- Never mix two origins in one recording.

## 4. Time

- JSON telemetry states use host monotonic receive time; DIS-decoded states use
  the PDU header timestamp.
- The DIS header timestamp is hour-relative, 2^-31 h ticks, bit 31 selecting
  absolute versus relative. Use relative in phase 1.
- Dead reckoning advances from the state timestamp it is given.
- M3 adds `sim_time_s` to the telemetry JSON. Playback may use it; ordering must
  not.

## 5. Message rates

- One Entity State PDU per aircraft per telemetry packet, 10 Hz.
- No separate heartbeat PDU. An entity with no update for 5 s is stale
  (`pysos_interop.is_stale`) and keeps its last pose.
- Dead-reckoning algorithms 1 (static), 2 (linear) and 4 (RVW) are the shared
  contract; 4 is the default. RVW needs velocity, not linear acceleration.
- Angular velocity is carried through the pipeline: the shared model stores
  body-frame angular velocity in radians per second, telemetry sources derive
  Z-Y-X Euler rates by finite difference and convert them once with
  `pysos_interop.euler_rates_to_body_rates`.

## 6. Module API

Python 3.11, package `flight_viewer`, no imports of `rclpy` anywhere.

`model.py`
- Re-exports `EntityKey`, `EntityState` and `Vec3` from `pysos_interop`.
- `EntityState(key, timestamp, position_enu_m, velocity_enu_mps,
  orientation_rps, angular_velocity_rps, marking, force_id=1, exercise_id=1)`;
  frozen; `orientation_rps` is `(roll, pitch, yaw)` radians and
  `angular_velocity_rps` is body-frame radians per second.

`config.py`
- `Origin(latitude_deg, longitude_deg, altitude_m)`, frozen; `is_set()`;
  `Origin.from_scenario(path)` reads `points[0]`.
- `EntityType(kind, domain, country, category, subcategory, specific, extra)`,
  frozen; `as_tuple()` returns the seven fields in that order. It is scenario
  identity metadata and is not part of `EntityState`.
- `EntityConfig(key, entity_type, force_id=1, marking="")`, frozen.
- `TransportConfig(mode="unicast", host="127.0.0.1", port=3000, ttl=1,
  interface=None)`, frozen; `mode` is `"unicast"` or `"multicast"`.
- `ExerciseConfig(exercise_id=1, origin=Origin(), entities=(), transport=TransportConfig(),
  publish_hz=10.0, heartbeat_s=5.0, stale_after_s=5.0, dr_algorithm=4)`.
- `load_exercise(path)` reads the JSON form of the above; `save_exercise(path, cfg)`.

`geo.py`
- Re-exports the WGS84/ECEF/ENU conversions and the Z-Y-X rate helpers from
  `pysos_interop`.
- `local_sim_to_enu(x_m, y_m, z_m) -> Vec3`, `enu_to_local_sim(enu_m)`,
  `heading_deg_from_velocity(velocity_enu_mps)`.

`dead_reckoning.py`
- Re-exports `dead_reckon(state, dt, algorithm=4)`, `is_stale(state, now,
  threshold)` and the algorithm constants from `pysos_interop`.

`pdu.py`
- `encode_entity_state(state, origin, exercise_id, *, dr_algorithm=4,
  timestamp=None, entity_type=None) -> bytes`; delegates to
  `pysos_interop.dis` and patches the scenario entity type.
- `decode_datagram(data, origin) -> list[EntityState]` (handles concatenated PDUs)
- `dis_timestamp(t_s, *, relative=True) -> int`
- `ENTITY_STATE_PDU_TYPE = 1`.

`transport.py`
- `open_channel(cfg: TransportConfig, *, receive: bool) -> Channel`, an adapter
  over `pysos_interop.transport.Channel` where `receive` returns `None` on
  timeout.

`sources/json_udp.py`
- `JsonUdpSource(host, port, entity: EntityConfig, origin: Origin)`;
  `receive(timeout) -> list[EntityState]`; parses the newline-delimited JSON
  telemetry and maps it to `EntityState` with `force_id` and `marking` from the
  entity config; `last_status` keeps the flat flight/mission fields.

`sources/dis_rx.py`
- `DisSource(channel, origin, exercise_id=1)`; `receive(timeout) -> list[EntityState]`.

`sinks/dis_tx.py`
- `DisSink(channel, origin, exercise_id=1, dr_algorithm=4, entity_types=None)`;
  `publish(states) -> int` (bytes sent). `entity_types` maps `EntityKey` to the
  scenario `EntityType` patched onto the wire.

`sinks/rerun_sink.py`
- `RerunSink(app_id="flight_viewer", rrd_path=None, spawn=False)`;
  `log(states, *, trail_points=200)`; `close()`. Per entity it logs
  `world/entity/<slug>/pose` (`Transform3D`), `/trail` (`LineStrips3D`),
  `/marker` (`Boxes3D`, no external mesh), `/status/*` scalars. Positions are
  ENU metres. `spawn=False` and `rrd_path` set must produce a non-empty file.

`recorder.py`
- `JsonlRecorder(path)` from `pysos_interop.jsonl`; `write(state)`, `close()`.
- `JsonlSource(path)`; `receive(timeout=0) -> list[EntityState]`; replays at
  original `timestamp` pacing when `realtime=True`.

`cli.py`
- `python -m flight_viewer --source {json-udp,dis,jsonl} --sink {rerun,dis,jsonl}`
  with `--host`, `--port`, `--telemetry`, `--transport {unicast,multicast}`,
  `--group`, `--interface`, `--ttl`, `--scenario`, `--config`, `--origin-lat`,
  `--origin-lon`, `--origin-alt`, `--entity-site`, `--entity-application`,
  `--entity-id`, `--exercise-id`, `--dr-algorithm`, `--rrd`, `--record`,
  `--spawn`, `--path`, `--realtime`, `--duration`, `--count`, `--app-id`.
- `--source json-udp` defaults to `127.0.0.1:5501`; `--sink dis` defaults to
  unicast `127.0.0.1:3000`.
- `--telemetry SPEC` is repeatable and selects one UDP telemetry stream per
  aircraft: `PORT:ENTITY`, or `HOST:PORT:ENTITY` when the host differs from
  `--host`/`127.0.0.1`. It applies only to `--source json-udp` and takes
  precedence over `--port`/`--entity-id`; every entity inherits the default
  entity type and `--entity-site`/`--entity-application`, with marking
  `AC-<entity>`. Malformed specs and duplicate `(site, application, entity)`
  triples are rejected.
- `--record PATH` writes a JSONL copy alongside any sink, so every run is
  replayable.

## 7. Rerun paths

- `world/entity/<site>_<app>_<entity>/pose`
- `world/entity/<site>_<app>_<entity>/trail`
- `world/entity/<site>_<app>_<entity>/marker`
- `world/entity/<site>_<app>_<entity>/status/airspeed_mps` and siblings
- `world/origin` static text with the geodetic origin

## 8. Pinned dependencies

`rerun-sdk==0.43.2`, `opendis==1.1.0`. Python 3.11 from the repo `venv/`.
