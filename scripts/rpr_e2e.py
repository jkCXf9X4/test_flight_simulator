"""End-to-end RPR path over the two-instance airplane federation.

This is project glue, not library code. It composes the pieces the workspace
already owns:

* the P2 federation manifest runner (``instance_manifest`` + ``Federation``)
  launches two ``ssp4sim`` instances that emit telemetry JSON on UDP 5501/5503;
* one :class:`TelemetryRprPublisher` per instance converts that telemetry to the
  shared ``EntityState`` model and publishes RPR payloads on UDP 5505;
* :class:`RprTruthRecorder` subscribes that RPR stream, decodes with a shared
  explicit ``RprOrigin``, and writes the recorder artifacts;

The dedicated RPR port is ``5505``; it is deliberately outside the federation
port range 5501-5504. RPR has no timestamp field, so the recorder stamps each
decoded frame from its per-entity ordinal at the bridge's 10 Hz cadence
(``SAMPLE_PERIOD_S``); that gives both entities an aligned simulation-time base.

Artifacts written under the run directory:

``run.json``
    scenario, origin, ports, exit codes, sample counts and measured results
``truth.jsonl`` / ``truth.meta.json``
    ``pysos_interop.TruthRecorder`` truth stream and sidecar metadata
``measurements.csv``
    ``pysos_interop.export_measure_csv`` tabular form of the truth stream
``recording.rrd``
    ``pysos_interop.rerun_sink.recordings_to_rrd`` export
``comparison.csv``
    ``pyssp_vv.measure.compare`` result (entity 1 vs entity 2)
``instances/`` and ``logs/``
    per-instance bundles/results and federation stdout/stderr
"""

from __future__ import annotations

import dataclasses
import json
import math
import socket
import sys
import threading
import time
import traceback
from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import instance_manifest
import run_instances
from pysos_coordinate import Federation
from pysos_interop import (
    EntityKey,
    EntityState,
    TruthRecorder,
    euler_rates_to_body_rates,
    export_measure_csv,
)
from pysos_interop.rerun_sink import recordings_to_rrd
from pysos_interop.rpr import RprOrigin, decode_frame, encode_entity_state
from pysos_interop.transport import Channel, ChannelTimeoutError
from pysos_interop.truth import MEASURE_UNITS, entity_slug, iter_truth

from dis_viewer.geo import local_sim_to_enu
from dis_viewer.sources.json_udp import parse_state_packets

#: Dedicated RPR UDP port. Never overlaps the federation telemetry/control ports.
RPR_UDP_PORT = 5505

#: Fixed simulated duration used by the acceptance run.
DEFAULT_STOP_TIME_S = 6.0

#: Bridge telemetry cadence: one packet per 0.1 s communication step.
SAMPLE_PERIOD_S = 0.1

#: How long a reader keeps draining after the stop signal before it exits.
_DRAIN_S = 0.4


def load_origin(scenario_path: Path | str) -> RprOrigin:
    """Read the shared ENU origin from scenario ``points[0]``."""

    data = json.loads(Path(scenario_path).read_text(encoding="utf-8"))
    points = data.get("points") or []
    if not points:
        raise ValueError(f"{scenario_path}: scenario has no points")
    first = points[0]
    return RprOrigin(
        latitude_deg=float(first["latitude_deg"]),
        longitude_deg=float(first["longitude_deg"]),
        altitude_m=float(first.get("altitude_m", 0.0)),
    )


def _yaw_unwrapped(previous: float, current: float) -> float:
    return current + math.remainder(previous - current, 2.0 * math.pi)


def telemetry_to_state(
    packet: Mapping[str, Any],
    *,
    key: EntityKey,
    timestamp: float,
    period_s: float,
    previous: tuple[tuple[float, float, float], tuple[float, float, float]] | None,
) -> EntityState:
    """Convert one normalised telemetry packet to an ``EntityState``.

    Velocity and body angular velocity are finite differences over the
    simulated cadence, not the host clock: in a fast run the packets arrive
    almost simultaneously, so wall-clock differencing would be meaningless.
    """

    position = local_sim_to_enu(*packet["state_m"])
    orientation = tuple(math.radians(value) for value in packet["orientation_deg"])

    velocity = (0.0, 0.0, 0.0)
    angular = (0.0, 0.0, 0.0)
    if previous is not None and period_s > 0.0:
        previous_position, previous_orientation = previous
        velocity = tuple(
            (position[index] - previous_position[index]) / period_s for index in range(3)
        )
        euler_rate = (
            (orientation[0] - previous_orientation[0]) / period_s,
            (orientation[1] - previous_orientation[1]) / period_s,
            (_yaw_unwrapped(previous_orientation[2], orientation[2]) - previous_orientation[2])
            / period_s,
        )
        angular = euler_rates_to_body_rates(orientation, euler_rate)

    return EntityState(
        key=key,
        timestamp=float(timestamp),
        position_enu_m=position,
        velocity_enu_mps=velocity,
        orientation_rps=orientation,
        angular_velocity_rps=angular,
        marking=f"AC-{key.entity}"[:11],
    )


class TelemetryRprPublisher(threading.Thread):
    """Subscribe one telemetry stream and republish it as RPR payloads."""

    def __init__(
        self,
        *,
        name: str,
        telemetry_host: str,
        telemetry_port: int,
        key: EntityKey,
        origin: RprOrigin,
        rpr_host: str,
        rpr_port: int,
        sample_period_s: float = SAMPLE_PERIOD_S,
    ) -> None:
        super().__init__(name=name, daemon=True)
        self.telemetry_host = telemetry_host
        self.telemetry_port = int(telemetry_port)
        self.key = key
        self.origin = origin
        self.rpr_host = rpr_host
        self.rpr_port = int(rpr_port)
        self.sample_period_s = float(sample_period_s)
        self.stop_event = threading.Event()
        self.ready = threading.Event()
        self.sent = 0
        self.error: BaseException | None = None
        self.error_traceback = ""

    def run(self) -> None:  # pragma: no cover - exercised end to end
        receiver: socket.socket | None = None
        sender: Channel | None = None
        try:
            receiver = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            receiver.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            receiver.bind((self.telemetry_host, self.telemetry_port))
            receiver.settimeout(0.05)
            sender = Channel(self.rpr_host, self.rpr_port).open()
            self.ready.set()

            ordinal = 0
            previous = None
            last_rx = time.monotonic()
            while True:
                try:
                    data, _ = receiver.recvfrom(65535)
                except TimeoutError:
                    if self.stop_event.is_set() and time.monotonic() - last_rx > _DRAIN_S:
                        break
                    continue
                last_rx = time.monotonic()
                for packet in parse_state_packets(data.decode("utf-8", "replace")):
                    state = telemetry_to_state(
                        packet,
                        key=self.key,
                        timestamp=ordinal * self.sample_period_s,
                        period_s=self.sample_period_s,
                        previous=previous,
                    )
                    previous = (state.position_enu_m, state.orientation_rps)
                    sender.send(encode_entity_state(state, origin=self.origin))
                    ordinal += 1
                    self.sent += 1
        except BaseException as exc:  # noqa: BLE001 - reported to the orchestrator
            self.error = exc
            self.error_traceback = traceback.format_exc()
            self.ready.set()
        finally:
            if sender is not None:
                sender.close()
            if receiver is not None:
                receiver.close()


class RprTruthRecorder(threading.Thread):
    """Subscribe the RPR stream, decode it, and write the recorder artifacts."""

    def __init__(
        self,
        *,
        host: str,
        port: int,
        origin: RprOrigin,
        expected_keys: Mapping[str, EntityKey],
        truth_path: Path,
        run_id: str,
        sample_period_s: float = SAMPLE_PERIOD_S,
    ) -> None:
        super().__init__(name="rpr-truth-recorder", daemon=True)
        self.host = host
        self.port = int(port)
        self.origin = origin
        self.expected_keys = dict(expected_keys)
        self.truth_path = Path(truth_path)
        self.run_id = run_id
        self.sample_period_s = float(sample_period_s)
        self.stop_event = threading.Event()
        self.ready = threading.Event()
        self.frames: dict[str, int] = defaultdict(int)
        self.samples = 0
        self.error: BaseException | None = None
        self.error_traceback = ""

    def run(self) -> None:  # pragma: no cover - exercised end to end
        channel: Channel | None = None
        recorder: TruthRecorder | None = None
        try:
            channel = Channel(self.host, self.port, bind=True).open()
            recorder = TruthRecorder(
                self.truth_path,
                run_id=self.run_id,
                origin=self.origin.geo,
                model_ids={slug: "airplane_ssp" for slug in self.expected_keys},
                sample_rate_hz=1.0 / self.sample_period_s,
            )
            expected = tuple(sorted(self.expected_keys))
            ordinals: dict[str, int] = defaultdict(int)
            pending: dict[float, dict[str, EntityState]] = defaultdict(dict)
            self.ready.set()

            last_rx = time.monotonic()
            while True:
                try:
                    data = channel.recv(timeout=0.05)
                except ChannelTimeoutError:
                    if self.stop_event.is_set() and time.monotonic() - last_rx > _DRAIN_S:
                        break
                    continue
                last_rx = time.monotonic()
                frame = decode_frame(data, origin=self.origin)
                slug = entity_slug(frame.state.key)
                timestamp = ordinals[slug] * self.sample_period_s
                ordinals[slug] += 1
                self.frames[slug] += 1
                pending[timestamp][slug] = dataclasses.replace(
                    frame.state, timestamp=timestamp
                )
                if all(slot in pending[timestamp] for slot in expected):
                    batch = pending.pop(timestamp)
                    recorder.write_sample(batch[slot] for slot in expected)
                    self.samples += 1

            for timestamp in sorted(pending):
                recorder.write_sample(
                    pending[timestamp][slot]
                    for slot in expected
                    if slot in pending[timestamp]
                )
                self.samples += 1
        except BaseException as exc:  # noqa: BLE001 - reported to the orchestrator
            self.error = exc
            self.error_traceback = traceback.format_exc()
            self.ready.set()
        finally:
            if recorder is not None:
                recorder.close()
            if channel is not None:
                channel.close()


@dataclass
class E2EResult:
    """Paths and measurements produced by one end-to-end run."""

    run_dir: Path
    truth_jsonl: Path
    metadata_json: Path
    measure_csv: Path
    rrd_path: Path
    comparison_csv: Path
    run_json: Path
    stop_time_s: float
    exit_codes: dict[str, int | None] = field(default_factory=dict)
    timed_out: bool = False
    frames: dict[str, int] = field(default_factory=dict)
    samples: int = 0
    instance_sim_durations: dict[str, float] = field(default_factory=dict)
    separation_m: dict[str, Any] = field(default_factory=dict)
    comparison: dict[str, Any] = field(default_factory=dict)


def _retarget(spec, *, out_dir: Path, stop_time: float, realtime: bool):
    """Point a loaded manifest at the run directory and the fixed duration."""

    for instance in spec.instances:
        command = list(instance.command)
        if "--out-dir" in command:
            command[command.index("--out-dir") + 1] = str(out_dir)
        if stop_time is not None:
            command += ["--stop-time", str(float(stop_time))]
        if realtime and "--realtime" not in command:
            command.append("--realtime")
        instance.command = command
    return spec.validate()


def _load_trajectories(csv_path: Path) -> dict[str, Any]:
    """Load the measurement CSV into one ``pyssp_vv`` Trajectory per entity."""

    import csv

    import numpy as np
    from pyssp_vv.measure import Trajectory

    with Path(csv_path).open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    if not rows:
        raise ValueError(f"{csv_path}: no data rows")
    times = np.array([float(row["time"]) for row in rows], dtype=np.float64)

    slugs = sorted({column.split(".", 1)[0] for column in rows[0] if column != "time"})
    trajectories: dict[str, Any] = {}
    for slug in slugs:
        channels = {}
        units = {}
        prefix = f"{slug}."
        for column in rows[0]:
            if not column.startswith(prefix):
                continue
            name = column[len(prefix):]
            channels[name] = np.array(
                [float(row[column]) for row in rows], dtype=np.float64
            )
            if name in MEASURE_UNITS:
                units[name] = MEASURE_UNITS[name]
        trajectories[slug] = Trajectory(
            time=times, channels=channels, label=slug, units=units
        )
    return trajectories


def separation_summary(csv_path: Path) -> dict[str, Any]:
    """Range statistics between the two entities in the measurement CSV.

    The bridge emits one all-zero state at ``t = 0`` before the model applies
    the per-instance initial offset, so that startup frame is reported
    separately and excluded from the steady-state range.
    """

    import numpy as np

    trajectories = _load_trajectories(csv_path)
    slugs = sorted(trajectories)
    if len(slugs) < 2:
        raise ValueError(f"{csv_path}: expected at least two entities, got {slugs}")
    first, second = trajectories[slugs[0]], trajectories[slugs[1]]
    axes = ("position_east_m", "position_north_m", "position_up_m")
    finite = np.ones(first.time.shape, dtype=bool)
    for axis in axes:
        finite &= np.isfinite(first[axis]) & np.isfinite(second[axis])
    distance = np.sqrt(
        sum((second[axis] - first[axis]) ** 2 for axis in axes)
    )
    steady = finite & (first.time > 0.0)
    startup = finite & (first.time == 0.0)
    if not steady.any():
        raise ValueError(f"{csv_path}: no comparable steady-state entity samples")
    distances = distance[steady]
    return {
        "min_m": float(distances.min()),
        "mean_m": float(distances.mean()),
        "max_m": float(distances.max()),
        "samples": int(distances.size),
        "excluded_startup_samples": int(startup.sum()),
        "startup_m": float(distance[startup].max()) if startup.any() else None,
        "entities": slugs[:2],
    }


def compare_entities(csv_path: Path, out_csv: Path) -> dict[str, Any]:
    """Run ``pyssp_vv.measure.compare`` on the CSV-loaded trajectories."""

    from pyssp_vv.measure import compare

    trajectories = _load_trajectories(csv_path)
    slugs = sorted(trajectories)
    if len(slugs) < 2:
        raise ValueError(f"{csv_path}: expected at least two entities, got {slugs}")
    reference, candidate = trajectories[slugs[0]], trajectories[slugs[1]]

    self_comparison = compare(reference, reference)
    cross = compare(reference, candidate)
    cross.write_csv(out_csv)

    def _metrics(comparison) -> dict[str, dict[str, float]]:
        return {
            item.signal: {
                "coverage": item.coverage,
                "max_abs_error": item.max_abs_error,
                "mean_abs_error": item.mean_abs_error,
                "rmse": item.rmse,
            }
            for item in comparison.signals
        }

    return {
        "self": {
            "reference": self_comparison.reference_label,
            "candidate": self_comparison.candidate_label,
            "signals": _metrics(self_comparison),
        },
        "cross": {
            "reference": cross.reference_label,
            "candidate": cross.candidate_label,
            "signals": _metrics(cross),
        },
    }


def _instance_durations(run_dir: Path) -> dict[str, float]:
    durations: dict[str, float] = {}
    for csv_path in sorted((run_dir / "instances").glob("instance-*/results/*.csv")):
        try:
            with csv_path.open(newline="", encoding="utf-8") as handle:
                import csv

                rows = list(csv.DictReader(handle))
            durations[csv_path.parents[1].name] = max(
                (float(row["time"]) for row in rows), default=0.0
            )
        except (OSError, KeyError, ValueError):
            continue
    return durations


def run_e2e(
    *,
    run_dir: Path | str,
    stop_time: float = DEFAULT_STOP_TIME_S,
    scenario_path: Path | str = instance_manifest.SCENARIO_PATH,
    manifest_path: Path | str | None = None,
    python: Path | str | None = None,
    rpr_port: int = RPR_UDP_PORT,
    realtime: bool = False,
    log: Any = print,
) -> E2EResult:
    """Run the two-instance federation through the RPR publisher/recorder path."""

    run_dir = Path(run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    instances_dir = run_dir / "instances"
    logs_dir = run_dir / "logs"
    origin = load_origin(scenario_path)
    interpreter = run_instances.resolve_python(None if python is None else Path(python))

    if manifest_path is not None:
        spec = instance_manifest.load_spec(manifest_path)
        spec = _retarget(spec, out_dir=instances_dir, stop_time=stop_time, realtime=realtime)
    else:
        spec = instance_manifest.build_spec(
            instances=2,
            python=interpreter,
            out_dir=instances_dir,
            stop_time=stop_time,
            realtime=realtime,
            scenario_path=scenario_path,
        )
    spec = run_instances.apply_python(spec, interpreter)

    expected: dict[str, EntityKey] = {}
    publishers: list[TelemetryRprPublisher] = []
    for instance in spec.instances:
        if len(instance.entities) != 1 or len(instance.telemetry) != 1:
            raise ValueError(
                f"{instance.name}: e2e expects one entity and one telemetry endpoint"
            )
        ref = instance.entities[0]
        key = EntityKey(int(ref.site), int(ref.application), int(ref.entity))
        expected[entity_slug(key)] = key
        endpoint = instance.telemetry[0]
        publishers.append(
            TelemetryRprPublisher(
                name=f"rpr-publisher-{instance.name}",
                telemetry_host=endpoint.host,
                telemetry_port=endpoint.port,
                key=key,
                origin=origin,
                rpr_host="127.0.0.1",
                rpr_port=rpr_port,
            )
        )

    run_id = f"{spec.name}-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}"
    truth_path = run_dir / "truth.jsonl"
    measure_csv = run_dir / "measurements.csv"
    rrd_path = run_dir / "recording.rrd"
    comparison_csv = run_dir / "comparison.csv"

    recorder = RprTruthRecorder(
        host="127.0.0.1",
        port=rpr_port,
        origin=origin,
        expected_keys=expected,
        truth_path=truth_path,
        run_id=run_id,
    )
    recorder.start()
    if not recorder.ready.wait(timeout=5.0):
        raise RuntimeError("RPR recorder did not bind the RPR port")
    if recorder.error is not None:
        raise RuntimeError(f"RPR recorder failed to start: {recorder.error}")

    for publisher in publishers:
        publisher.start()
    for publisher in publishers:
        if not publisher.ready.wait(timeout=5.0):
            raise RuntimeError(f"{publisher.name} did not bind its telemetry port")
        if publisher.error is not None:
            raise RuntimeError(f"{publisher.name} failed to start: {publisher.error}")

    log(f"federation {spec.name}: {len(spec.instances)} instances, stop {stop_time}s, origin {origin}")
    federation = Federation(spec, log_dir=logs_dir)
    try:
        result = federation.run()
    finally:
        for publisher in publishers:
            publisher.stop_event.set()
        for publisher in publishers:
            publisher.join(timeout=10.0)
        recorder.stop_event.set()
        recorder.join(timeout=20.0)

    if recorder.error is not None:
        raise RuntimeError(
            f"RPR recorder failed: {recorder.error!r}\n{recorder.error_traceback}"
        )
    for publisher in publishers:
        if publisher.error is not None:
            raise RuntimeError(
                f"{publisher.name} failed: {publisher.error!r}\n{publisher.error_traceback}"
            )

    export_measure_csv(truth_path, measure_csv)
    recordings_to_rrd(
        truth_path,
        rrd_path,
        app_id="flight_sim_e2e",
        origin=origin.geo,
    )
    separation = separation_summary(measure_csv)
    comparison = compare_entities(measure_csv, comparison_csv)
    durations = _instance_durations(run_dir)

    e2e = E2EResult(
        run_dir=run_dir,
        truth_jsonl=truth_path,
        metadata_json=truth_path.with_suffix(".meta.json"),
        measure_csv=measure_csv,
        rrd_path=rrd_path,
        comparison_csv=comparison_csv,
        run_json=run_dir / "run.json",
        stop_time_s=float(stop_time),
        exit_codes=dict(result.exit_codes),
        timed_out=bool(result.timed_out),
        frames=dict(recorder.frames),
        samples=recorder.samples,
        instance_sim_durations=durations,
        separation_m=separation,
        comparison=comparison,
    )

    summary = {
        "schema": 1,
        "run_id": run_id,
        "federation": spec.name,
        "stop_time_s": float(stop_time),
        "realtime": bool(realtime),
        "origin": {
            "latitude_deg": origin.latitude_deg,
            "longitude_deg": origin.longitude_deg,
            "altitude_m": origin.altitude_m,
        },
        "ports": {
            "telemetry": {
                instance.name: instance.telemetry[0].port
                for instance in spec.instances
            },
            "rpr": rpr_port,
        },
        "exit_codes": e2e.exit_codes,
        "timed_out": e2e.timed_out,
        "frames": e2e.frames,
        "samples": e2e.samples,
        "instance_sim_durations_s": e2e.instance_sim_durations,
        "separation_m": e2e.separation_m,
        "artifacts": {
            "truth_jsonl": truth_path.name,
            "metadata": e2e.metadata_json.name,
            "measure_csv": measure_csv.name,
            "rrd": rrd_path.name,
            "comparison_csv": comparison_csv.name,
        },
        "pyssp_vv_comparison": comparison,
    }
    e2e.run_json.write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    log(f"artifacts: {run_dir}")
    log(f"samples: {e2e.samples}, frames: {e2e.frames}")
    log(f"separation: {separation['min_m']:.1f}..{separation['max_m']:.1f} m (mean {separation['mean_m']:.1f})")
    return e2e


def truth_time_span(truth_path: Path | str) -> tuple[float, float]:
    """First and last timestamp of a truth stream, in simulation seconds."""

    timestamps = [state.timestamp for state in iter_truth(truth_path)]
    if not timestamps:
        raise ValueError(f"{truth_path}: empty truth stream")
    return min(timestamps), max(timestamps)
