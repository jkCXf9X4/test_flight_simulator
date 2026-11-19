"""Command line entry point for the DIS viewer adapter."""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path
from typing import Iterable, List, Optional, Tuple

from .config import EntityConfig, ExerciseConfig, Origin, TransportConfig, load_exercise
from .model import EntityKey, EntityState
from .recorder import JsonlRecorder, JsonlSource
from .sinks.dis_tx import DisSink
from .sinks.rerun_sink import RerunSink
from .sources.dis_rx import DisSource
from .sources.json_udp import JsonUdpMultiSource, JsonUdpSource
from .transport import Channel, open_channel

DEFAULT_TELEMETRY_PORT = 5501
DEFAULT_DIS_PORT = 3000
DEFAULT_MULTICAST_GROUP = "239.255.0.1"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="flight_viewer",
        description="Bridge simulation telemetry, DIS PDUs and Rerun recordings.",
    )
    parser.add_argument("--source", choices=("json-udp", "dis", "jsonl"), default="json-udp")
    parser.add_argument("--sink", choices=("rerun", "dis", "jsonl"), default="rerun")
    parser.add_argument("--host", default=None, help="telemetry bind host or DIS host")
    parser.add_argument("--port", type=int, default=None)
    parser.add_argument(
        "--telemetry",
        action="append",
        default=None,
        metavar="SPEC",
        help="PORT:ENTITY or HOST:PORT:ENTITY; repeat per aircraft",
    )
    parser.add_argument("--transport", choices=("unicast", "multicast"), default="unicast")
    parser.add_argument("--group", default=DEFAULT_MULTICAST_GROUP)
    parser.add_argument("--interface", default=None)
    parser.add_argument("--ttl", type=int, default=1)
    parser.add_argument("--config", type=Path, default=None, help="exercise JSON")
    parser.add_argument("--scenario", type=Path, default=None, help="scenario JSON for the origin")
    parser.add_argument("--origin-lat", type=float, default=None)
    parser.add_argument("--origin-lon", type=float, default=None)
    parser.add_argument("--origin-alt", type=float, default=0.0)
    parser.add_argument("--entity-site", type=int, default=1)
    parser.add_argument("--entity-application", type=int, default=1)
    parser.add_argument("--entity-id", type=int, default=1)
    parser.add_argument("--exercise-id", type=int, default=1)
    parser.add_argument(
        "--dr-algorithm",
        type=int,
        default=None,
        help="DIS dead-reckoning algorithm (default 4, RVW; use 3 for RPW)",
    )
    parser.add_argument("--rrd", type=Path, default=None, help="write a .rrd recording")
    parser.add_argument("--spawn", action="store_true", help="spawn the live Rerun viewer")
    parser.add_argument("--record", type=Path, default=None, help="also write a JSONL recording")
    parser.add_argument("--path", type=Path, default=None, help="JSONL file for source/sink jsonl")
    parser.add_argument("--duration", type=float, default=0.0, help="seconds, 0 = forever")
    parser.add_argument("--count", type=int, default=0, help="iterations, 0 = until duration")
    parser.add_argument("--realtime", action="store_true", help="pace JSONL replay by t_s")
    parser.add_argument("--app-id", default="flight_viewer")
    return parser


def _entity_from_args(args: argparse.Namespace) -> EntityConfig:
    key = EntityKey(
        site=args.entity_site,
        application=args.entity_application,
        entity=args.entity_id,
    )
    return EntityConfig(key=key)


def parse_telemetry_spec(
    spec: str, default_host: str = "127.0.0.1"
) -> Tuple[str, int, int]:
    """Parse ``PORT:ENTITY`` or ``HOST:PORT:ENTITY`` into ``(host, port, entity)``."""

    parts = spec.split(":")
    if len(parts) == 2:
        host = default_host
        port_text, entity_text = parts
    elif len(parts) == 3:
        host, port_text, entity_text = parts
    else:
        raise ValueError(
            f"Invalid --telemetry spec {spec!r}; expected PORT:ENTITY or HOST:PORT:ENTITY"
        )
    if not host:
        raise ValueError(f"Invalid --telemetry spec {spec!r}: empty host")
    try:
        port = int(port_text)
        entity = int(entity_text)
    except ValueError:
        raise ValueError(
            f"Invalid --telemetry spec {spec!r}: port and entity must be integers"
        ) from None
    if not 0 <= port <= 65535:
        raise ValueError(f"Invalid --telemetry spec {spec!r}: port out of range")
    if not 0 <= entity <= 65535:
        raise ValueError(f"Invalid --telemetry spec {spec!r}: entity out of range")
    return host, port, entity


def resolve_telemetry(args: argparse.Namespace) -> List[Tuple[str, int, EntityConfig]]:
    """Build ``(host, port, entity)`` specs from repeatable ``--telemetry`` flags."""

    specs: List[Tuple[str, int, EntityConfig]] = []
    seen: dict[Tuple[int, int, int], str] = {}
    default_host = getattr(args, "host", None) or "127.0.0.1"
    for spec in getattr(args, "telemetry", None) or ():
        try:
            host, port, entity_id = parse_telemetry_spec(spec, default_host=default_host)
        except ValueError as exc:
            raise SystemExit(f"error: {exc}") from None
        key = EntityKey(
            site=args.entity_site,
            application=args.entity_application,
            entity=entity_id,
        )
        triple = (key.site, key.application, key.entity)
        if triple in seen:
            raise SystemExit(
                f"error: duplicate --telemetry entity (site, application, entity) "
                f"= {triple} in {seen[triple]!r} and {spec!r}"
            )
        seen[triple] = spec
        specs.append((host, port, EntityConfig(key=key)))
    return specs


def resolve_origin(args: argparse.Namespace) -> Origin:
    if args.origin_lat is not None or args.origin_lon is not None:
        return Origin(
            latitude_deg=args.origin_lat or 0.0,
            longitude_deg=args.origin_lon or 0.0,
            altitude_m=args.origin_alt or 0.0,
        )
    if args.config is not None:
        return load_exercise(args.config).origin
    if args.scenario is not None:
        return Origin.from_scenario(args.scenario)
    print(
        "warning: no origin configured; using (0, 0, 0). "
        "Pass --scenario, --config or --origin-* before encoding DIS.",
        file=sys.stderr,
    )
    return Origin()


def resolve_exercise(args: argparse.Namespace) -> ExerciseConfig:
    if args.config is not None:
        config = load_exercise(args.config)
        return ExerciseConfig(
            exercise_id=args.exercise_id or config.exercise_id,
            origin=resolve_origin(args),
            entities=config.entities,
            transport=config.transport,
            publish_hz=config.publish_hz,
            heartbeat_s=config.heartbeat_s,
            stale_after_s=config.stale_after_s,
            dr_algorithm=(
                config.dr_algorithm
                if args.dr_algorithm is None
                else args.dr_algorithm
            ),
        )
    return ExerciseConfig(
        exercise_id=args.exercise_id,
        origin=resolve_origin(args),
        entities=(_entity_from_args(args),),
        dr_algorithm=4 if args.dr_algorithm is None else args.dr_algorithm,
    )


def _transport_config(args: argparse.Namespace) -> TransportConfig:
    if args.transport == "multicast":
        return TransportConfig(
            mode="multicast",
            host=args.group,
            port=args.port or DEFAULT_DIS_PORT,
            ttl=args.ttl,
            interface=args.interface,
        )
    return TransportConfig(
        mode="unicast",
        host=args.host or "127.0.0.1",
        port=args.port or DEFAULT_DIS_PORT,
    )


class _Source:
    def __init__(self, args: argparse.Namespace, config: ExerciseConfig) -> None:
        self.kind = args.source
        self._dis_channel: Optional[Channel] = None
        if args.source == "json-udp":
            specs = resolve_telemetry(args)
            if specs:
                self._impl = JsonUdpMultiSource(specs)
            else:
                self._impl = JsonUdpSource(
                    args.host or "127.0.0.1",
                    args.port or DEFAULT_TELEMETRY_PORT,
                    config.entities[0],
                    config.origin,
                )
        elif args.source == "dis":
            self._dis_channel = open_channel(_transport_config(args), receive=True)
            self._impl = DisSource(self._dis_channel, config.origin, config.exercise_id)
        else:
            if args.path is None:
                raise SystemExit("--source jsonl requires --path")
            self._impl = JsonlSource(args.path, realtime=args.realtime)

    def receive(self, timeout: float) -> List[EntityState]:
        return self._impl.receive(timeout)

    @property
    def exhausted(self) -> bool:
        return bool(getattr(self._impl, "exhausted", False))

    def close(self) -> None:
        close_impl = getattr(self._impl, "close", None)
        if close_impl is not None:
            close_impl()
        if self._dis_channel is not None:
            self._dis_channel.close()


class _Sink:
    def __init__(self, args: argparse.Namespace, config: ExerciseConfig) -> None:
        self.kind = args.sink
        self._dis_channel: Optional[Channel] = None
        if args.sink == "rerun":
            self._impl = RerunSink(
                app_id=args.app_id,
                rrd_path=args.rrd,
                spawn=args.spawn,
                origin=config.origin,
            )
        elif args.sink == "dis":
            if not config.origin.is_set():
                raise SystemExit("--sink dis requires an origin (--scenario, --config or --origin-*)")
            self._dis_channel = open_channel(_transport_config(args), receive=False)
            self._impl = DisSink(
                self._dis_channel,
                config.origin,
                config.exercise_id,
                config.dr_algorithm,
                entity_types={
                    entity.key: entity.entity_type for entity in config.entities
                },
            )
        else:
            if args.path is None:
                raise SystemExit("--sink jsonl requires --path")
            self._impl = JsonlRecorder(args.path)

    def publish(self, states: List[EntityState]) -> None:
        if self.kind == "rerun":
            self._impl.log(states)
        elif self.kind == "dis":
            self._impl.publish(states)
        else:
            for state in states:
                self._impl.write(state)

    def close(self) -> None:
        close_impl = getattr(self._impl, "close", None)
        if close_impl is not None:
            close_impl()
        if self._dis_channel is not None:
            self._dis_channel.close()


def _loop(
    source: _Source,
    sink: _Sink,
    recorder: Optional[JsonlRecorder],
    config: ExerciseConfig,
    duration: float,
    count: int,
) -> int:
    started = time.monotonic()
    deadline = started + duration if duration > 0 else None
    iterations = 0
    try:
        while True:
            if count and iterations >= count:
                break
            if deadline is not None and time.monotonic() >= deadline:
                break
            timeout = 0.1
            if deadline is not None:
                timeout = max(0.0, min(timeout, deadline - time.monotonic()))
            states = source.receive(timeout)
            if states:
                sink.publish(states)
                if recorder is not None:
                    for state in states:
                        recorder.write(state)
            elif source.exhausted:
                break
            iterations += 1
    except KeyboardInterrupt:
        pass
    return iterations


def main(argv: Optional[Iterable[str]] = None) -> int:
    args = build_parser().parse_args(list(argv) if argv is not None else None)
    config = resolve_exercise(args)
    config.assert_unique_entities()

    source = _Source(args, config)
    sink = _Sink(args, config)
    recorder = JsonlRecorder(args.record) if args.record is not None else None
    try:
        iterations = _loop(source, sink, recorder, config, args.duration, args.count)
    finally:
        source.close()
        sink.close()
        if recorder is not None:
            recorder.close()

    print(f"processed {iterations} updates", file=sys.stderr)
    if args.rrd is not None:
        size = args.rrd.stat().st_size if args.rrd.exists() else 0
        print(f"recording: {args.rrd} ({size} bytes)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
