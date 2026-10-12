#!/usr/bin/env bash
# Run the live stack for a showcase recording; exits shortly after the mission ends.
# Meant to run inside the ROS 2 container (see scripts/record_demo.sh on the host).

SCENARIO_PATH="${1:-build/ssp/scenario.json}"
GRACE_AFTER_SIM="${GRACE_AFTER_SIM:-10}"
DEMO_DIR="${DEMO_DIR:-build/demo}"
RVIZ_CONFIG="${RVIZ_CONFIG:-/workspace/ros2_bridge/mission_views.rviz}"

if [[ -f "/workspace/$SCENARIO_PATH" ]]; then
  BRIDGE_SCENARIO_PATH="/workspace/$SCENARIO_PATH"
else
  echo "Scenario file not found: $SCENARIO_PATH" >&2
  exit 1
fi

source /opt/ros/kilted/setup.bash

set -u
set +e

mkdir -p "$DEMO_DIR"

STOP_TIME_ARGS=()
if [[ -n "${STOP_TIME:-}" ]]; then
  STOP_TIME_ARGS=(--stop-time "$STOP_TIME")
fi

date +%s.%N >"$DEMO_DIR/sim_start_epoch.txt"
./scripts/run_airplane_scenario.py --realtime "${STOP_TIME_ARGS[@]}" \
  >/tmp/sim.out 2>/tmp/sim.err &
SIM_PID=$!

sleep 2

python3 -m ros2_bridge.node \
  --scenario "$BRIDGE_SCENARIO_PATH" \
  --host 127.0.0.1 \
  --state-port 5501 \
  --command-port 5502 \
  >/tmp/bridge.out 2>/tmp/bridge.err &
BRIDGE_PID=$!

date +%s.%N >"$DEMO_DIR/rviz_launch_epoch.txt"
rviz2 -d "$RVIZ_CONFIG" >/tmp/rviz.out 2>/tmp/rviz.err &
RVIZ_PID=$!

SIM_STATUS=0
wait "$SIM_PID" || SIM_STATUS=$?
date +%s.%N >"$DEMO_DIR/sim_end_epoch.txt"

sleep "$GRACE_AFTER_SIM"

kill "$RVIZ_PID" "$BRIDGE_PID" >/dev/null 2>&1 || true
wait "$RVIZ_PID" >/dev/null 2>&1 || true
wait "$BRIDGE_PID" >/dev/null 2>&1 || true

echo "SIM_STATUS=$SIM_STATUS"
exit "$SIM_STATUS"
