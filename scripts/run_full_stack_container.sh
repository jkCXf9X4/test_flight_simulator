#!/usr/bin/env bash

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SCENARIO_PATH="resources/scenarios/test_scenario.json"
SIM_READY_DELAY="${SIM_READY_DELAY:-2}"
LOCAL_REALTIME_CONFIG="${LOCAL_REALTIME_CONFIG:-/workspace/build/results/config.realtime.json}"
BRIDGE_HOST="${BRIDGE_HOST:-127.0.0.1}"
BRIDGE_STATE_PORT="${BRIDGE_STATE_PORT:-5501}"
BRIDGE_COMMAND_PORT="${BRIDGE_COMMAND_PORT:-5502}"
IMAGE_NAME="${IMAGE_NAME:-test-flight-simulator-ros2:kilted}"
CONTAINER_NAME="${CONTAINER_NAME:-test-flight-simulator-full-stack}"
RVIZ_CONFIG="${RVIZ_CONFIG:-/workspace/ros2_bridge/mission_views.rviz}"

if [[ $# -gt 0 && "${1:-}" != "--" ]]; then
  SCENARIO_PATH="$1"
  shift
fi

if [[ "${1:-}" == "--" ]]; then
  shift
fi

"$REPO_ROOT/scripts/check_environment.sh" --live-container

if [[ -f "$REPO_ROOT/$SCENARIO_PATH" ]]; then
  SCENARIO_ABS="$REPO_ROOT/$SCENARIO_PATH"
  BRIDGE_SCENARIO_PATH="/workspace/$SCENARIO_PATH"
elif [[ -f "$REPO_ROOT/3rd_party/airplane/$SCENARIO_PATH" ]]; then
  SCENARIO_ABS="$REPO_ROOT/3rd_party/airplane/$SCENARIO_PATH"
  BRIDGE_SCENARIO_PATH="/workspace/3rd_party/airplane/$SCENARIO_PATH"
else
  echo "Scenario file not found: $SCENARIO_PATH" >&2
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

SIM_ARGS=("$@")
SIM_ARGS_STR=""
for arg in "${SIM_ARGS[@]}"; do
  SIM_ARGS_STR+=" $(printf '%q' "$arg")"
done

exec podman "${PODMAN_ARGS[@]}" \
  "$IMAGE_NAME" \
  "set -eo pipefail; \
   source /opt/ros/kilted/setup.bash; \
   set -u; \
   ./scripts/run_airplane_scenario.sh $(printf '%q' "$SCENARIO_PATH") --realtime --bridge-input --config-path $(printf '%q' "$LOCAL_REALTIME_CONFIG")${SIM_ARGS_STR} & \
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
