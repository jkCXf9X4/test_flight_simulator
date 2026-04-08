#!/usr/bin/env bash

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
echo "$REPO_ROOT"

SCENARIO_PATH="resources/scenarios/test_scenario.json"
SIM_READY_DELAY="${SIM_READY_DELAY:-2}"
LOCAL_REALTIME_CONFIG="${LOCAL_REALTIME_CONFIG:-$REPO_ROOT/build/results/config.realtime.json}"

if [[ $# -gt 0 && "${1:-}" != "--" ]]; then
  SCENARIO_PATH="$1"
  shift
fi

if [[ "${1:-}" == "--" ]]; then
  shift
fi

FG_PID=""
SIM_PID=""

cleanup() {
  if [[ -n "$SIM_PID" ]] && kill -0 "$SIM_PID" 2>/dev/null; then
    kill "$SIM_PID" 2>/dev/null || true
    wait "$SIM_PID" 2>/dev/null || true
  fi
  if [[ -n "$FG_PID" ]] && kill -0 "$FG_PID" 2>/dev/null; then
    kill "$FG_PID" 2>/dev/null || true
    wait "$FG_PID" 2>/dev/null || true
  fi
}

trap cleanup EXIT INT TERM

"$REPO_ROOT/scripts/run_airplane_scenario.sh" \
  "$SCENARIO_PATH" \
  --realtime \
  --config-path "$LOCAL_REALTIME_CONFIG" \
  "$@" &
SIM_PID=$!

sleep "$SIM_READY_DELAY"

"$REPO_ROOT/scripts/run_flightgear.sh" &
FG_PID=$!

wait "$SIM_PID"
