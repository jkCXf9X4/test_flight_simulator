#!/usr/bin/env python3
"""Rebuild a lightweight Rerun recording from an RPR truth log.

The coordinator's own ``recording.rrd`` carries a 200-point trail per entity
and per-sample status scalars, which is fine with a GPU but stalls the software
rasterizer (llvmpipe/SwiftShader). This writes a small stand-in: one point plus
a short trail per entity, which replays smoothly without hardware rendering.

    ./scripts/render_replay_rrd.py build/runs/sos4-120/truth.jsonl \
        build/runs/sos4-120/replay-lite.rrd --tail 40
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("truth", type=Path, help="RPR truth JSONL from run_e2e_rpr.py")
    parser.add_argument("out", type=Path, help="Output .rrd path")
    parser.add_argument("--tail", type=int, default=40, help="trail points per entity (0 = no trail)")
    parser.add_argument("--radius", type=float, default=4.0, help="entity point radius in metres")
    return parser.parse_args(argv)


def color_for(marking: str) -> list[int]:
    palette = {
        "RED": [229, 72, 77],
        "BLUE": [76, 141, 255],
        "GREEN": [70, 167, 88],
        "YELLOW": [245, 217, 10],
    }
    return palette.get(marking.split("-")[0].upper(), [200, 200, 200])


def load_tracks(path: Path) -> dict[str, list[tuple[float, list[float]]]]:
    tracks: dict[str, list[tuple[float, list[float]]]] = defaultdict(list)
    with path.open() as handle:
        for line in handle:
            record = json.loads(line)
            tracks[record["marking"]].append((record["timestamp"], record["position_enu_m"]))
    return tracks


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    import rerun as rr

    tracks = load_tracks(args.truth)
    if not tracks:
        raise SystemExit(f"no truth records in {args.truth}")

    rr.init("flight_sim_replay", spawn=False)
    rr.save(str(args.out))
    for name in sorted(tracks):
        colour = color_for(name)
        points: list[list[float]] = []
        for t_s, position in tracks[name]:
            rr.set_time("sim_time", duration=t_s)
            points.append(position)
            rr.log(f"world/{name}/pose", rr.Points3D([position], colors=[colour], radii=[args.radius]))
            if args.tail > 0 and len(points) > 1:
                rr.log(f"world/{name}/trail", rr.LineStrips3D([points[-args.tail :]], colors=[colour]))

    frames = sum(len(rows) for rows in tracks.values())
    print(f"wrote {args.out}: {len(tracks)} entities, {frames} samples, tail {args.tail}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
