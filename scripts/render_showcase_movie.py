#!/usr/bin/env python3
"""Render the showcase movie from a recorded demo take.

Combines the raw RViz capture (scripts/record_demo.sh) with the realtime
telemetry CSV from the same run into one time-lapsed movie with title cards.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import subprocess
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[1]
DEMO_DIR = REPO_ROOT / "build" / "demo"

ALTITUDE_COLUMN = "environment.location.z_km"
AIRSPEED_COLUMN = "environment.flight_status.airspeed_mps"
WAYPOINT_COLUMN = "autopilot_module.missionStatus.waypoint_index"
TOTAL_WAYPOINTS_COLUMN = "autopilot_module.missionStatus.total_waypoints"
COMPLETE_COLUMN = "autopilot_module.missionStatus.complete"
DISTANCE_COLUMN = "autopilot_module.missionStatus.distance_to_waypoint_km"
FUEL_COLUMN = "fuel_system.fuelState.fuel_remaining_kg"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--demo-dir", type=Path, default=DEMO_DIR, help="Directory with raw_capture.mp4 and timeline stamps.")
    parser.add_argument("--csv", type=Path, default=REPO_ROOT / "build" / "results" / "scenario_results_realtime.csv")
    parser.add_argument("--scenario", type=Path, default=REPO_ROOT / "build" / "ssp" / "scenario.json")
    parser.add_argument("--out", type=Path, default=DEMO_DIR / "mission_showcase.mp4")
    parser.add_argument("--target-seconds", type=float, default=110.0, help="Duration of the time-lapsed mission section.")
    parser.add_argument("--fps", type=int, default=24, help="Output frame rate.")
    parser.add_argument("--panel-fps", type=int, default=12, help="Telemetry panel frame rate while rendering.")
    parser.add_argument("--rviz-delay", type=float, default=3.5, help="Seconds after RViz launch before the movie starts.")
    parser.add_argument("--hold-seconds", type=float, default=5.0, help="Hold on the completed mission before the end card.")
    parser.add_argument("--crop", default=None, help="Optional crop of the captured region as W:H:X:Y.")
    parser.add_argument("--title", default=None, help="Title card heading (defaults to the scenario name).")
    return parser.parse_args(argv)


def read_epoch(path: Path) -> float:
    return float(path.read_text().strip())


def ffprobe_duration(path: Path) -> float:
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", str(path)],
        capture_output=True, text=True, check=True,
    )
    return float(json.loads(result.stdout)["format"]["duration"])


def load_telemetry(csv_path: Path) -> dict[str, list[float]]:
    columns = {
        "time": "time",
        "altitude_m": ALTITUDE_COLUMN,
        "airspeed_mps": AIRSPEED_COLUMN,
        "waypoint_index": WAYPOINT_COLUMN,
        "total_waypoints": TOTAL_WAYPOINTS_COLUMN,
        "complete": COMPLETE_COLUMN,
        "distance_km": DISTANCE_COLUMN,
        "fuel_kg": FUEL_COLUMN,
    }
    data: dict[str, list[float]] = {key: [] for key in columns}
    with csv_path.open(newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            for key, column in columns.items():
                value = (row.get(column) or "").strip()
                try:
                    data[key].append(float(value) if value else math.nan)
                except ValueError:
                    data[key].append(math.nan)
    return data


def mmss(seconds: float) -> str:
    seconds = max(0.0, float(seconds))
    return f"{int(seconds // 60):02d}:{int(seconds % 60):02d}"


def build_panel_figure(data: dict[str, list[float]], stop_time: float):
    figure = plt.figure(figsize=(6.4, 10.0), dpi=100)
    figure.patch.set_facecolor("#101418")
    style = dict(color="#c8d3dd", fontsize=9)
    grid = figure.add_gridspec(4, 1, top=0.93, bottom=0.04, left=0.14, right=0.90, hspace=0.45)

    t_min = [t / 60.0 for t in data["time"]]
    stop_min = stop_time / 60.0

    figure.text(0.5, 0.965, "MISSION TELEMETRY", ha="center", va="center",
                color="#e8eef3", fontsize=15, fontweight="bold")
    clock = figure.text(0.5, 0.935, "T+ 00:00", ha="center", va="center", color="#7fd4a0", fontsize=13)

    def subplot(row: int, label: str, color: str, values: list[float], unit: str):
        axis = figure.add_subplot(grid[row, 0])
        axis.set_facecolor("#161c22")
        axis.tick_params(colors="#9fb0bd", labelsize=8)
        for spine in axis.spines.values():
            spine.set_color("#2c3742")
        line, = axis.plot([], [], color=color, linewidth=1.4)
        marker = axis.axvline(0.0, color="#e8eef3", linewidth=0.8, alpha=0.6)
        finite = [v for v in values if not math.isnan(v)]
        low, high = (min(finite), max(finite)) if finite else (0.0, 1.0)
        pad = (high - low) * 0.08 or 1.0
        axis.set_xlim(0.0, stop_min)
        axis.set_ylim(low - pad, high + pad)
        axis.set_ylabel(f"{label} [{unit}]", **style)
        axis.grid(True, color="#243038", linewidth=0.5)
        return axis, line, marker

    altitude_axis, altitude_line, altitude_marker = subplot(0, "Altitude", "#4fc3f7", data["altitude_m"], "m")
    airspeed_axis, airspeed_line, airspeed_marker = subplot(1, "Airspeed", "#ffb74d", data["airspeed_mps"], "m/s")

    waypoint_axis = figure.add_subplot(grid[2, 0])
    waypoint_axis.set_facecolor("#161c22")
    waypoint_axis.tick_params(colors="#9fb0bd", labelsize=8)
    for spine in waypoint_axis.spines.values():
        spine.set_color("#2c3742")
    waypoint_line, = waypoint_axis.step([], [], where="post", color="#81c784", linewidth=1.4)
    waypoint_axis.set_xlim(0.0, stop_min)
    waypoint_axis.set_ylim(0, max(data["waypoint_index"]) + 1)
    waypoint_axis.set_ylabel("Waypoint", **style)
    waypoint_axis.grid(True, color="#243038", linewidth=0.5)
    distance_axis = waypoint_axis.twinx()
    distance_axis.tick_params(colors="#9fb0bd", labelsize=8)
    for spine in distance_axis.spines.values():
        spine.set_color("#2c3742")
    distance_line, = distance_axis.plot([], [], color="#e57373", linewidth=1.2, alpha=0.9)
    finite_distance = [v for v in data["distance_km"] if not math.isnan(v)]
    distance_axis.set_ylim(0, (max(finite_distance) if finite_distance else 1.0) * 1.1)
    distance_axis.set_ylabel("Distance to WP [km]", **dict(style, color="#e57373"))
    waypoint_marker = waypoint_axis.axvline(0.0, color="#e8eef3", linewidth=0.8, alpha=0.6)

    fuel_axis, fuel_line, fuel_marker = subplot(3, "Fuel", "#ba68c8", data["fuel_kg"], "kg")
    for axis in (altitude_axis, airspeed_axis, waypoint_axis, fuel_axis):
        axis.set_xlabel("Mission time [min]", **style)

    lines = [
        (altitude_line, altitude_marker, data["altitude_m"]),
        (airspeed_line, airspeed_marker, data["airspeed_mps"]),
        (waypoint_line, waypoint_marker, data["waypoint_index"]),
        (fuel_line, fuel_marker, data["fuel_kg"]),
    ]

    def update(t_sim: float) -> None:
        count = sum(1 for t in data["time"] if t <= t_sim)
        t_now = min(t_sim, data["time"][-1]) / 60.0
        for line, marker, values in lines:
            line.set_data(t_min[:count], values[:count])
            marker.set_xdata([t_now])
        distance_line.set_data(t_min[:count], data["distance_km"][:count])
        clock.set_text(f"T+ {mmss(min(t_sim, data['time'][-1]))}")

    return figure, update


def render_telemetry_panel(data: dict[str, list[float]], stop_time: float, args: argparse.Namespace,
                            t_sim_start: float, speedup: float, out_path: Path) -> None:
    from matplotlib.animation import FFMpegWriter

    figure, update = build_panel_figure(data, stop_time)
    writer = FFMpegWriter(
        fps=args.panel_fps,
        codec="libx264",
        extra_args=["-pix_fmt", "yuv420p", "-crf", "20"],
    )
    frames = int(args.target_seconds * args.panel_fps)
    with writer.saving(figure, str(out_path), dpi=100):
        for frame in range(frames):
            t_out = frame / args.panel_fps
            update(t_sim_start + t_out * speedup)
            writer.grab_frame()
    plt.close(figure)


def render_card(out_path: Path, heading: str, lines: list[str]) -> None:
    figure = plt.figure(figsize=(22.4, 10.0), dpi=100)
    figure.patch.set_facecolor("#101418")
    figure.text(0.5, 0.72, heading, ha="center", va="center", color="#e8eef3", fontsize=44, fontweight="bold")
    for i, line in enumerate(reversed(lines)):
        figure.text(0.5, 0.42 + i * 0.07, line, ha="center", va="center", color="#9fb0bd", fontsize=20)
    figure.savefig(out_path, dpi=100, facecolor=figure.get_facecolor())
    plt.close(figure)


def run_ffmpeg(args: list[str]) -> None:
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *args], check=True)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    demo_dir = args.demo_dir
    raw_capture = demo_dir / "raw_capture.mp4"
    for required in (raw_capture, args.csv, args.scenario):
        if not required.exists():
            raise SystemExit(f"Required input not found: {required}")

    capture_start = read_epoch(demo_dir / "capture_start_epoch.txt")
    sim_start = read_epoch(demo_dir / "sim_start_epoch.txt")
    rviz_launch = read_epoch(demo_dir / "rviz_launch_epoch.txt")
    sim_end = read_epoch(demo_dir / "sim_end_epoch.txt")

    capture_duration = ffprobe_duration(raw_capture)
    trim_epoch = rviz_launch + args.rviz_delay
    trim = trim_epoch - capture_start
    if not 0.0 <= trim < capture_duration - 1.0:
        raise SystemExit(f"Trim point {trim:.1f}s outside capture duration {capture_duration:.1f}s")

    data = load_telemetry(args.csv)
    if len(data["time"]) < 2:
        raise SystemExit("Telemetry CSV has no data rows")

    t_sim_start = trim_epoch - sim_start

    # End the mission section shortly after mission completion, or at the end of
    # the recorded data for a partial take; the simulation itself keeps running
    # until its stop time, which would be dead air.
    complete_times = [t for t, c in zip(data["time"], data["complete"]) if c >= 0.5]
    t_sim_end = complete_times[0] if complete_times else data["time"][-1]
    capture_end = min(sim_start + t_sim_end + args.hold_seconds - capture_start, capture_duration)
    speedup = (capture_end - trim) / args.target_seconds

    print(f"capture {capture_duration:.1f}s, trim at {trim:.1f}s, mission ends at {capture_end:.1f}s, "
          f"movie starts at sim t={t_sim_start:.1f}s, speedup {speedup:.2f}x")

    mission_part = demo_dir / "mission_part.mp4"
    filters = [f"trim=start={trim:.3f}:end={capture_end:.3f}", "setpts=PTS-STARTPTS", f"setpts=PTS/{speedup:.6f}"]
    if args.crop:
        width, height, crop_x, crop_y = args.crop.split(":")
        filters.insert(0, f"crop={width}:{height}:{crop_x}:{crop_y}")
    run_ffmpeg([
        "-i", str(raw_capture),
        "-vf", ",".join(filters),
        "-r", str(args.fps), "-an",
        "-c:v", "libx264", "-preset", "medium", "-crf", "19", "-pix_fmt", "yuv420p",
        str(mission_part),
    ])

    telemetry_panel = demo_dir / "telemetry_panel.mp4"
    print("rendering telemetry panel ...")
    render_telemetry_panel(data, data["time"][-1], args, t_sim_start, speedup, telemetry_panel)

    composed = demo_dir / "composed.mp4"
    run_ffmpeg([
        "-i", str(mission_part), "-i", str(telemetry_panel),
        "-filter_complex", f"[1:v]fps={args.fps}[panel];[0:v][panel]hstack",
        "-c:v", "libx264", "-preset", "medium", "-crf", "19", "-pix_fmt", "yuv420p",
        "-shortest", str(composed),
    ])

    scenario_name = "Mission Showcase"
    try:
        scenario_name = json.loads(args.scenario.read_text()).get("name") or scenario_name
    except (json.JSONDecodeError, OSError):
        pass
    heading = args.title or f"SSP Aircraft — {scenario_name}"

    fuel_values = [v for v in data["fuel_kg"] if not math.isnan(v)]
    fuel_used = fuel_values[0] - fuel_values[-1] if fuel_values else 0.0
    waypoints = [v for v in data["waypoint_index"] if not math.isnan(v)]
    totals = [v for v in data["total_waypoints"] if not math.isnan(v)]
    flight_time = t_sim_end
    end_heading = "Mission complete" if complete_times else "End of showcase sequence"
    end_lines = [
        f"Flight time {mmss(flight_time)}",
        f"Waypoints reached {int(waypoints[-1]) if waypoints else 0} of {int(totals[-1]) if totals else 0}",
        f"Fuel used {fuel_used:.0f} kg",
    ]

    title_png = demo_dir / "title_card.png"
    end_png = demo_dir / "end_card.png"
    render_card(title_png, heading, ["FMI co-simulation · SSP · ROS 2 / RViz", f"recorded live · time-lapsed {speedup:.1f}×"])
    render_card(end_png, end_heading, end_lines)

    title_card = demo_dir / "title_card.mp4"
    end_card = demo_dir / "end_card.mp4"
    for png, card, duration in ((title_png, title_card, 4.0), (end_png, end_card, 6.0)):
        run_ffmpeg([
            "-loop", "1", "-t", str(duration), "-i", str(png),
            "-r", str(args.fps),
            "-c:v", "libx264", "-preset", "medium", "-crf", "19", "-pix_fmt", "yuv420p",
            str(card),
        ])

    concat_list = demo_dir / "concat.txt"
    concat_list.write_text(
        "".join(f"file '{path.name}'\n" for path in (title_card, composed, end_card))
    )
    run_ffmpeg([
        "-f", "concat", "-safe", "0", "-i", str(concat_list),
        "-c:v", "libx264", "-preset", "medium", "-crf", "19", "-pix_fmt", "yuv420p",
        "-movflags", "+faststart",
        str(args.out),
    ])

    final_duration = ffprobe_duration(args.out)
    print(f"showcase movie: {args.out} ({final_duration:.1f}s, {args.out.stat().st_size / 1e6:.1f} MB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
