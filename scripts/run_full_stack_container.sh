#!/usr/bin/env bash

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SIM_READY_DELAY="${SIM_READY_DELAY:-2}"
BRIDGE_HOST="${BRIDGE_HOST:-127.0.0.1}"
BRIDGE_STATE_PORT="${BRIDGE_STATE_PORT:-5501}"
BRIDGE_COMMAND_PORT="${BRIDGE_COMMAND_PORT:-5502}"
IMAGE_NAME="${IMAGE_NAME:-test-flight-simulator-ros2:kilted}"
CONTAINER_NAME="${CONTAINER_NAME:-test-flight-simulator-full-stack}"
RVIZ_CONFIG="${RVIZ_CONFIG:-/workspace/build/ssp/mission_views.rviz}"

if [[ $# -gt 0 ]]; then
  echo "run_full_stack_container.sh does not accept arguments. Scenario selection now happens during build." >&2
  echo "Use ./scripts/build_airplane.py [scenario-json] first, then rerun ./scripts/run_full_stack_container.sh." >&2
  exit 1
fi

"$REPO_ROOT/scripts/check_environment.sh" --live-container

if [[ -f "$REPO_ROOT/build/ssp/scenario.json" ]]; then
  BRIDGE_SCENARIO_PATH="/workspace/build/ssp/scenario.json"
else
  echo "Local scenario file not found: build/ssp/scenario.json" >&2
  echo "Run ./scripts/build_airplane.py first to prepare ./build/ssp." >&2
  exit 1
fi

if [[ ! -f "$REPO_ROOT/build/ssp/mission_views.rviz" ]]; then
  echo "Local RViz config not found: build/ssp/mission_views.rviz" >&2
  echo "Run ./scripts/build_airplane.py first to prepare ./build/ssp." >&2
  exit 1
fi

XAUTHORITY_PATH="${XAUTHORITY:-$HOME/.Xauthority}"

cleanup() {
  podman rm -f "$CONTAINER_NAME" >/dev/null 2>&1 || true
  xhost -SI:localuser:"$(id -un)" >/dev/null 2>&1 || true
}

trap cleanup EXIT INT TERM

xhost +SI:localuser:"$(id -un)" >/dev/null

PODMAN_ARGS=(
  run --rm --replace
  --name "$CONTAINER_NAME"
  --userns=keep-id
  --security-opt label=disable
  -e DISPLAY="${DISPLAY:-:0}"
  -e XAUTHORITY=/tmp/.Xauthority
  -v /tmp/.X11-unix:/tmp/.X11-unix:rw
  -v "$XAUTHORITY_PATH":/tmp/.Xauthority:ro
  -v "$REPO_ROOT":/workspace:rw
  -w /workspace
)

if [[ -e /dev/dri ]]; then
  PODMAN_ARGS+=(--device /dev/dri)
fi

exec podman "${PODMAN_ARGS[@]}" \
  "$IMAGE_NAME" \
  "set -eo pipefail; \
   source /opt/ros/kilted/setup.bash; \
   set -u; \
   ./scripts/run_airplane_scenario.py --realtime & \
   SIM_PID=\$!; \
   sleep $(printf '%q' "$SIM_READY_DELAY"); \
   python3 -m ros2_bridge.node --scenario $(printf '%q' "$BRIDGE_SCENARIO_PATH") --host $(printf '%q' "$BRIDGE_HOST") --state-port $(printf '%q' "$BRIDGE_STATE_PORT") --command-port $(printf '%q' "$BRIDGE_COMMAND_PORT") & \
   BRIDGE_PID=\$!; \
   cleanup_inner() { \
     kill \$BRIDGE_PID \$SIM_PID >/dev/null 2>&1 || true; \
     wait \$BRIDGE_PID >/dev/null 2>&1 || true; \
     wait \$SIM_PID >/dev/null 2>&1 || true; \
   }; \
   trap cleanup_inner EXIT; \
   rviz2 -d $(printf '%q' "$RVIZ_CONFIG")"
