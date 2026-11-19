#!/usr/bin/env bash

# Host-side launcher for the ROS-free stack.
#
# The simulation always runs on the host. The dis_viewer/Rerun frontend runs
# either on the host with the repo venv (default) or inside the Rerun Podman
# image when RERUN_CONTAINER=1. The container uses host networking so it can
# receive the bridge's UDP telemetry on 127.0.0.1:5501.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
IMAGE_NAME="${IMAGE_NAME:-test-flight-simulator-rerun:latest}"
CONTAINER_NAME="${CONTAINER_NAME:-test-flight-simulator-rerun}"
RERUN_CONTAINER="${RERUN_CONTAINER:-0}"
SCENARIO_PATH="${SCENARIO_PATH:-3rd_party/airplane/resources/scenarios/test_scenario.json}"
RECORD_PATH="${RECORD_PATH:-build/results/dis_viewer.jsonl}"
TELEMETRY_CSV="${TELEMETRY_CSV:-$REPO_ROOT/build/results/scenario_results_realtime.csv}"
SIM_READY_TIMEOUT="${SIM_READY_TIMEOUT:-30}"
XAUTHORITY_PATH="${XAUTHORITY:-$HOME/.Xauthority}"

if [[ $# -gt 0 ]]; then
  echo "run_rerun_stack.sh does not accept arguments; use environment variables instead." >&2
  exit 1
fi

fail() {
  echo "$*" >&2
  exit 1
}

if [[ ! -f "$REPO_ROOT/build/ssp/config.realtime.json" ]]; then
  fail "Local realtime config not found: build/ssp/config.realtime.json. Run ./scripts/build_airplane.py first."
fi

if [[ ! -f "$REPO_ROOT/$SCENARIO_PATH" ]]; then
  fail "Scenario file not found: $SCENARIO_PATH"
fi

if ! command -v setsid >/dev/null 2>&1; then
  fail "setsid is required to start and stop the simulation as its own process group."
fi

SIM_PID=""
VIEWER_PID=""
XHOST_ADDED=0

cleanup() {
  if [[ -n "$VIEWER_PID" ]]; then
    kill "$VIEWER_PID" >/dev/null 2>&1 || true
    wait "$VIEWER_PID" >/dev/null 2>&1 || true
  fi
  if [[ -n "$SIM_PID" ]]; then
    # The sim was started with setsid, so kill the whole process group.
    kill -- "-$SIM_PID" >/dev/null 2>&1 || kill "$SIM_PID" >/dev/null 2>&1 || true
    wait "$SIM_PID" >/dev/null 2>&1 || true
  fi
  if [[ "$RERUN_CONTAINER" == "1" ]]; then
    podman rm -f "$CONTAINER_NAME" >/dev/null 2>&1 || true
  fi
  if [[ "$XHOST_ADDED" == "1" ]]; then
    xhost -SI:localuser:"$(id -un)" >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT INT TERM

# Wait for this run's telemetry instead of a blind sleep. The realtime config
# truncates and rewrites the CSV, so a fresh mtime plus non-zero size means the
# master loop is advancing (and the bridge is emitting on UDP 5501).
wait_for_telemetry() {
  local start_epoch deadline mtime
  start_epoch="$(date +%s)"
  deadline=$((start_epoch + SIM_READY_TIMEOUT))
  while (( $(date +%s) <= deadline )); do
    if ! kill -0 "$SIM_PID" >/dev/null 2>&1; then
      echo "Simulation exited before telemetry was ready." >&2
      return 1
    fi
    if [[ -s "$TELEMETRY_CSV" ]]; then
      mtime="$(stat -c %Y "$TELEMETRY_CSV" 2>/dev/null || echo 0)"
      if (( mtime >= start_epoch )); then
        return 0
      fi
    fi
    sleep 0.25
  done
  echo "Timed out after ${SIM_READY_TIMEOUT}s waiting for $TELEMETRY_CSV." >&2
  return 1
}

mkdir -p "$REPO_ROOT/build/results"

echo "Starting simulation (realtime) ..."
(
  cd "$REPO_ROOT"
  exec setsid ./scripts/run_airplane_scenario.py --realtime
) &
SIM_PID=$!

echo "Waiting for telemetry ..."
wait_for_telemetry

VIEWER_ARGS=(
  --source json-udp
  --sink rerun
  --spawn
  --scenario "$SCENARIO_PATH"
  --record "$RECORD_PATH"
)

echo "Starting Rerun viewer ..."
if [[ "$RERUN_CONTAINER" == "1" ]]; then
  command -v podman >/dev/null 2>&1 || fail "RERUN_CONTAINER=1 requires podman on PATH."
  [[ -n "${DISPLAY:-}" ]] || fail "RERUN_CONTAINER=1 requires DISPLAY to be set."
  podman image exists "$IMAGE_NAME" >/dev/null 2>&1 \
    || fail "Podman image $IMAGE_NAME is missing. Run ./scripts/build_rerun_container.sh."

  xhost +SI:localuser:"$(id -un)" >/dev/null
  XHOST_ADDED=1

  PODMAN_ARGS=(
    run --rm --replace
    --name "$CONTAINER_NAME"
    --userns=keep-id
    --security-opt label=disable
    --network=host
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

  podman "${PODMAN_ARGS[@]}" "$IMAGE_NAME" "${VIEWER_ARGS[@]}" &
  VIEWER_PID=$!
  wait "$VIEWER_PID"
else
  PYTHON="${PYTHON:-}"
  if [[ -z "$PYTHON" ]]; then
    if [[ -x "$REPO_ROOT/../venv/bin/python" ]]; then
      PYTHON="$REPO_ROOT/../venv/bin/python"
    elif command -v python3 >/dev/null 2>&1; then
      PYTHON="$(command -v python3)"
    else
      fail "No Python interpreter found. Set PYTHON or activate the repo venv."
    fi
  fi
  if ! "$PYTHON" -c "import rerun" >/dev/null 2>&1; then
    fail "$PYTHON cannot import rerun. Install dis_viewer/requirements.txt or set PYTHON."
  fi

  (
    cd "$REPO_ROOT"
    exec "$PYTHON" -m dis_viewer "${VIEWER_ARGS[@]}"
  ) &
  VIEWER_PID=$!
  wait "$VIEWER_PID"
fi
