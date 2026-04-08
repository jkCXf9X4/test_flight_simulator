#!/usr/bin/env bash

SCENARIO_PATH="${1:-resources/scenarios/test_scenario.json}"
STOP_TIME="${STOP_TIME:-10}"
CONFIG_PATH="${CONFIG_PATH:-/workspace/build/results/config.realtime.json}"

if [[ -f "/workspace/$SCENARIO_PATH" ]]; then
  BRIDGE_SCENARIO_PATH="/workspace/$SCENARIO_PATH"
elif [[ -f "/workspace/3rd_party/airplane/$SCENARIO_PATH" ]]; then
  BRIDGE_SCENARIO_PATH="/workspace/3rd_party/airplane/$SCENARIO_PATH"
else
  echo "Scenario file not found: $SCENARIO_PATH" >&2
  exit 1
fi

source /opt/ros/kilted/setup.bash

set -u
set +e

./scripts/run_airplane_scenario.sh \
  "$SCENARIO_PATH" \
  --realtime \
  --bridge-input \
  --stop-time "$STOP_TIME" \
  --config-path "$CONFIG_PATH" \
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

timeout 12s rviz2 -d /workspace/ros2_bridge/mission_views.rviz >/tmp/rviz.out 2>/tmp/rviz.err
RVIZ_STATUS=$?

wait "$SIM_PID"
SIM_STATUS=$?

kill "$BRIDGE_PID" >/dev/null 2>&1 || true
wait "$BRIDGE_PID" >/dev/null 2>&1 || true

echo "RVIZ_STATUS=$RVIZ_STATUS"
echo "SIM_STATUS=$SIM_STATUS"
echo "--- sim.err ---"
cat /tmp/sim.err
echo "--- bridge.err ---"
cat /tmp/bridge.err
echo "--- rviz.err ---"
cat /tmp/rviz.err

if [[ "$SIM_STATUS" -ne 0 ]]; then
  exit "$SIM_STATUS"
fi

if [[ "$RVIZ_STATUS" -ne 0 && "$RVIZ_STATUS" -ne 124 ]]; then
  exit "$RVIZ_STATUS"
fi
