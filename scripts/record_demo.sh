#!/usr/bin/env bash
# Record the live RViz stack into a raw capture for the showcase movie.
# Captures the RViz window region of the X display while the full stack runs
# the mission in realtime, then leaves timeline stamps in build/demo for the
# post-processing step (scripts/render_showcase_movie.py).

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
IMAGE_NAME="${IMAGE_NAME:-test-flight-simulator-ros2:kilted}"
CONTAINER_NAME="${CONTAINER_NAME:-test-flight-simulator-demo}"
DEMO_DIR="${DEMO_DIR:-build/demo}"
CAPTURE_FRAMERATE="${CAPTURE_FRAMERATE:-30}"
GRACE_AFTER_SIM="${GRACE_AFTER_SIM:-10}"
# RViz window geometry as saved in ros2_bridge/mission_views.rviz.
RVIZ_X="${RVIZ_X:-60}"
RVIZ_Y="${RVIZ_Y:-40}"
RVIZ_WIDTH="${RVIZ_WIDTH:-1600}"
RVIZ_HEIGHT="${RVIZ_HEIGHT:-1000}"
XAUTHORITY_PATH="${XAUTHORITY:-$HOME/.Xauthority}"

"$REPO_ROOT/scripts/check_environment.sh" --live-container

if [[ ! -f "$REPO_ROOT/build/ssp/scenario.json" ]]; then
  echo "Local scenario file not found: build/ssp/scenario.json" >&2
  echo "Run ./scripts/build_airplane.py first." >&2
  exit 1
fi

mkdir -p "$REPO_ROOT/$DEMO_DIR"

xhost +SI:localuser:"$(id -un)" >/dev/null

CAPTURE="$DEMO_DIR/raw_capture.mp4"
FFMPEG_LOG="$DEMO_DIR/ffmpeg.log"

# Start the screen capture before the stack so the RViz window is never missed.
ffmpeg -y \
  -f x11grab -framerate "$CAPTURE_FRAMERATE" \
  -video_size "${RVIZ_WIDTH}x${RVIZ_HEIGHT}" \
  -i "${DISPLAY}+${RVIZ_X},${RVIZ_Y}" \
  -c:v libx264 -preset veryfast -crf 20 -pix_fmt yuv420p \
  "$CAPTURE" >"$FFMPEG_LOG" 2>&1 &
FFMPEG_PID=$!
trap 'kill -INT "$FFMPEG_PID" 2>/dev/null || true' EXIT INT TERM

sleep 1
date +%s.%N >"$DEMO_DIR/capture_start_epoch.txt"

PODMAN_ARGS=(
  run --rm --replace
  --name "$CONTAINER_NAME"
  --userns=keep-id
  --security-opt label=disable
  -e DISPLAY="${DISPLAY:-:0}"
  -e XAUTHORITY=/tmp/.Xauthority
  -e STOP_TIME="${STOP_TIME:-}"
  -e GRACE_AFTER_SIM="$GRACE_AFTER_SIM"
  -e DEMO_DIR="$DEMO_DIR"
  -v /tmp/.X11-unix:/tmp/.X11-unix:rw
  -v "$XAUTHORITY_PATH":/tmp/.Xauthority:ro
  -v "$REPO_ROOT":/workspace:rw
  -w /workspace
)
if [[ -e /dev/dri ]]; then
  PODMAN_ARGS+=(--device /dev/dri)
fi

podman "${PODMAN_ARGS[@]}" \
  "$IMAGE_NAME" \
  ./scripts/container_full_stack_demo.sh build/ssp/scenario.json &
STACK_PID=$!

STACK_STATUS=0
wait "$STACK_PID" || STACK_STATUS=$?

# Finalize the capture cleanly (SIGINT makes ffmpeg close the mp4 properly).
kill -INT "$FFMPEG_PID"
wait "$FFMPEG_PID" || true

echo "STACK_STATUS=$STACK_STATUS"
echo "Raw capture: $CAPTURE"
echo "Next: ./3rd_party/airplane/venv/bin/python3 scripts/render_showcase_movie.py"
exit "$STACK_STATUS"
