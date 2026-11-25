#!/usr/bin/env python3
"""Stream an RPR truth log into a running Rerun viewer at realtime pace.

Loading a recorded ``.rrd`` in the viewer leaves it paused, and the viewer's
time cursor cannot be driven from the browser. Streaming the same truth data
over gRPC instead makes the viewer follow live data, so it animates on its own.

    ./scripts/stream_truth_rerun.py build/runs/sos4-120/truth.jsonl \
        --connect rerun+http://127.0.0.1:9876/proxy --tail 40
"""

from __future__ import annotations

import argparse
import json
import math
import time
from collections import defaultdict
from pathlib import Path

COLORS = {
    "RED": [229, 72, 77],
    "BLUE": [76, 141, 255],
    "GREEN": [70, 167, 88],
    "YELLOW": [245, 217, 10],
}


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("truth", type=Path, help="RPR truth JSONL (run_e2e_rpr.py output)")
    parser.add_argument("--connect", default="rerun+http://127.0.0.1:9876/proxy")
    parser.add_argument("--app-id", default="flight_sim_live")
    parser.add_argument("--tail", type=int, default=40, help="trail points per entity")
    parser.add_argument("--radius", type=float, default=4.0, help="point radius in metres")
    parser.add_argument("--rate", type=float, default=1.0, help="playback speed (1.0 = realtime)")
    return parser.parse_args(argv)


def climb_angle_deg(
    previous: tuple[float, list[float]], current: tuple[float, list[float]]
) -> float:
    """Climb angle above the horizon from consecutive ENU fixes (z up).

    Derived from position deltas rather than ``velocity_enu_mps``: the truth
    stream's vertical velocity component is near-zero even while altitude
    changes, so it cannot carry the climb angle.
    """
    (t0, before), (t1, after) = previous, current
    dt = t1 - t0
    if dt <= 0.0:
        return 0.0
    return math.degrees(
        math.atan2(
            (after[2] - before[2]) / dt,
            math.hypot(after[0] - before[0], after[1] - before[1]) / dt,
        )
    )


def load(path: Path) -> dict[str, list[tuple[float, list[float]]]]:
    tracks: dict[str, list[tuple[float, list[float]]]] = defaultdict(list)
    with path.open() as handle:
        for line in handle:
            record = json.loads(line)
            tracks[record["marking"]].append((record["timestamp"], record["position_enu_m"]))
    for rows in tracks.values():
        rows.sort(key=lambda row: row[0])
    return tracks


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    import rerun as rr

    tracks = load(args.truth)
    if not tracks:
        raise SystemExit(f"no truth records in {args.truth}")

    recording = rr.RecordingStream(args.app_id)
    recording.connect_grpc(args.connect)

    tail: dict[str, list[list[float]]] = defaultdict(list)
    last_fix: dict[str, tuple[float, list[float]]] = {}
    frames = sorted({t for rows in tracks.values() for t, _ in rows})
    started = time.monotonic()
    for t_s in frames:
        target = started + t_s / max(args.rate, 1e-9)
        delay = target - time.monotonic()
        if delay > 0:
            time.sleep(delay)
        recording.set_time("sim_time", duration=t_s)
        for name, rows in tracks.items():
            past = [row for row in rows if row[0] <= t_s]
            if not past:
                continue
            colour = COLORS.get(name.split("-")[0].upper(), [200, 200, 200])
            fix = past[-1]
            position = fix[1]
            tail[name].append(position)
            angle = climb_angle_deg(last_fix[name], fix) if name in last_fix else 0.0
            last_fix[name] = fix
            recording.log(
                f"world/{name}/pose",
                rr.Points3D(
                    [position],
                    colors=[colour],
                    radii=[args.radius],
                    labels=[f"{name}  climb {angle:+.1f} deg"],
                    show_labels=True,
                ),
            )
            recording.log(
                f"world/{name}/status/climb_angle_deg",
                rr.Scalars(angle),
            )
            if args.tail > 0:
                recording.log(
                    f"world/{name}/trail",
                    rr.LineStrips3D([tail[name][-args.tail :]], colors=[colour]),
                )
    print(f"streamed {len(frames)} frames, {len(tracks)} entities, tail {args.tail}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
