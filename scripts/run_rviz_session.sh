#!/usr/bin/env bash

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SCENARIO_PATH="resources/scenarios/test_scenario.json"
SIM_READY_DELAY="${SIM_READY_DELAY:-2}"
LOCAL_REALTIME_CONFIG="${LOCAL_REALTIME_CONFIG:-$REPO_ROOT/build/results/config.realtime.json}"
BRIDGE_HOST="${BRIDGE_HOST:-127.0.0.1}"
BRIDGE_STATE_PORT="${BRIDGE_STATE_PORT:-5501}"
BRIDGE_COMMAND_PORT="${BRIDGE_COMMAND_PORT:-5502}"
RVIZ_CONFIG="${RVIZ_CONFIG:-$REPO_ROOT/ros2_bridge/mission_views.rviz}"

if [[ $# -gt 0 && "${1:-}" != "--" ]]; then
  SCENARIO_PATH="$1"
  shift
fi

if [[ "${1:-}" == "--" ]]; then
  shift
fi

if ! command -v rviz2 >/dev/null 2>&1; then
  echo "Could not find rviz2 on PATH." >&2
  exit 1
fi

SIM_PID=""
BRIDGE_PID=""
RVIZ_PID=""

cleanup() {
  for pid in "$RVIZ_PID" "$BRIDGE_PID" "$SIM_PID"; do
    if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
      kill "$pid" 2>/dev/null || true
      wait "$pid" 2>/dev/null || true
    fi
  done
}

trap cleanup EXIT INT TERM

"$REPO_ROOT/scripts/run_airplane_scenario.sh" \
  "$SCENARIO_PATH" \
  --realtime \
  --bridge-input \
  --config-path "$LOCAL_REALTIME_CONFIG" \
  "$@" &
SIM_PID=$!

sleep "$SIM_READY_DELAY"

python3 -m ros2_bridge.node \
  --scenario "$SCENARIO_PATH" \
  --host "$BRIDGE_HOST" \
  --state-port "$BRIDGE_STATE_PORT" \
  --command-port "$BRIDGE_COMMAND_PORT" &
BRIDGE_PID=$!

rviz2 -d "$RVIZ_CONFIG" &
RVIZ_PID=$!

wait "$SIM_PID"
