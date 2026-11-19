# DIS viewer adapter — implementation plan

Goal: a multi-entity view of the simulation without ROS. Sibling entities broadcast
DIS entity-state PDUs; one adapter parses them into a neutral entity state; Rerun
renders the live and recorded view.

Scope of phase 1 stops at M5. HLA, time management, FOM, ownership, terrain and
detailed meshes are explicitly out of scope.

## Architecture

- DIS lives in a sidecar Python process (`dis_viewer/`), not inside the 0.1 s
  Jacobi step loop of the FMI/SSP master.
- The sim keeps its existing UDP JSON telemetry contract (port 5501) and control
  contract (port 5502). The adapter is the only new consumer.
- Local runs default to unicast loopback (`127.0.0.1:3000`). Multicast
  (`239.255.0.1:3000`, TTL 1) is for LAN and containers. Both carry identical
  PDU bytes and are selected with `--transport`.
- The end state moves the DIS codec into a shared package reused by
  `pyfmi_distributed`'s `DisTransport`. That is not phase 1.

## Contracts

Normative details live in `docs/dis_contract.md`. Freeze before code:

- entity identity `(site, application, entity)`, unique per exercise;
- exercise id and force id, both configurable;
- entity type tuple, configurable;
- ECEF on the wire, local ENU in the viewer, origin pinned to scenario `points[0]`;
- receive-time ordering in phase 1, `sim_time_s` added to telemetry in M3;
- one ESPDU per telemetry packet at 10 Hz, entity stale after 5 s;
- dead-reckoning algorithm 3 with rotation;
- Rerun path scheme `world/entity/<site>_<app>_<entity>/...`.

## Milestones

M0 — contracts, 1 day. Exit: `docs/dis_contract.md` frozen, one golden ESPDU
fixture captured.

M1 — UDP JSON to Rerun, 2 days. Exit: one live aircraft rendered from port 5501,
and a replayable `.rrd` written with no live viewer. No DIS code yet.

M2 — DIS receive path, 2 days. Exit: a synthetic sender renders through the same
viewer; exercise and entity filters proven.

M3 — DIS send path, 2 days. Exit: the adapter emits ESPDUs derived from port 5501;
an independent receiver decodes a matching pose and orientation.

M4 — multi-entity, 3 days. Exit: 2–3 entities in one `.rrd` with distinct ids and
per-entity trails. ROS is retired here.

M5 — hardening, 3 days. Exit: recorder and replay, headless CI smoke test,
container image, runbook.

## Test plan

- Unit: PDU encode/decode/encode equality; ECEF/ENU round trip within 1e-3 m;
  roll/pitch/yaw and psi/theta/phi round trip; dead reckoning against closed-form
  linear motion.
- Contract: golden PDUs from a recorded capture decode byte-for-byte; wrong
  exercise id or unknown entity is dropped.
- Integration: unicast loopback sender to receiver; multicast behind
  `@pytest.mark.network` bound to `lo`.
- System: two entities produce one `.rrd`; loading it with the SDK shows the
  expected entity count and a monotonic timeline.
- CI is headless: `rr.save()` only, no spawned viewer, no X11, no GPU.

## ROS removal

ROS currently provides RViz rendering, `pilot_command_json` input, tf and mission
markers. No external consumer of the ROS topics exists. The aircraft flies
scenarios on autopilot with `useBridgeInput=false`, so the sim needs no pilot
input at all.

Replacement: DIS plus Rerun for rendering; a small shim that writes the existing
control JSON to port 5502 for manual flying. Keep the native `Ros2UdpBridge` FMU
and its UDP contract; retire the rclpy node, the RViz config, the ROS image and
the ROS launchers at M4. The name `Ros2UdpBridge` remains as naming debt until
renamed.

## Risks

- Software GL (`llvmpipe`): 10 Hz logging, capped trails, recorded `.rrd` in CI.
- DIS timestamp is hour-relative, not wall time: order by receive time.
- Entity id collisions are silent: single allocator, CI uniqueness assertion.
- Body versus world frame in dead-reckoning parameters.
- Multicast does not cross Docker bridge networks by default: host networking or
  an explicit interface.
- Late join has no snapshot: rely on the 10 Hz update rate and mark stale entities.
- Rerun API churn: pin the version and keep one adapter module.
