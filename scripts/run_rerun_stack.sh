#!/usr/bin/env bash

# Host-side launcher for the ROS-free stack.
#
# The federation runs on the host and records an RPR truth stream through
# scripts/run_e2e_rpr.py. There is no JSON telemetry port: each aircraft's
# rpr_entity FMU broadcasts directly to the recorder over Unix datagram sockets
# by default, and the viewer replays the recorder's truth.jsonl. Set
# TRANSPORT=udp for the legacy RPR broadcast on 127.0.0.1:5505, and UNIX_DIR to
# use pathname sockets instead of abstract names. The flight_viewer/Rerun
# frontend runs either on the host with the repo venv (default) or inside the
# Rerun Podman image when RERUN_CONTAINER=1.
#
# RERUN_WEB=1 swaps the native viewer window for the Rerun web viewer, fed
# over gRPC and opened in a dedicated Chrome instance that enables the
# SwiftShader WebGL2 fallback (plain Chrome refuses WebGL2 on GPU-less hosts).
#
# MANIFEST=<path> runs that federation manifest instead of the default
# two-instance federation built from the flags (e.g.
# manifests/aircraft_federation.manifest.json for the four aircraft).

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
IMAGE_NAME="${IMAGE_NAME:-test-flight-simulator-rerun:latest}"
CONTAINER_NAME="${CONTAINER_NAME:-test-flight-simulator-rerun}"
RERUN_CONTAINER="${RERUN_CONTAINER:-0}"
SCENARIO_PATH="${SCENARIO_PATH:-3rd_party/airplane/resources/scenarios/test_scenario.json}"
MANIFEST="${MANIFEST:-}"
RUN_DIR="${RUN_DIR:-build/results/e2e}"
TRUTH_PATH="${TRUTH_PATH:-$RUN_DIR/truth.jsonl}"
STOP_TIME="${STOP_TIME:-30.0}"
TRANSPORT="${TRANSPORT:-unix}"
UNIX_DIR="${UNIX_DIR:-}"
XAUTHORITY_PATH="${XAUTHORITY:-$HOME/.Xauthority}"
RERUN_WEB="${RERUN_WEB:-0}"
RERUN_WEB_PORT="${RERUN_WEB_PORT:-9090}"
RERUN_GRPC_PORT="${RERUN_GRPC_PORT:-9876}"
CHROME_BIN="${CHROME_BIN:-}"
WEB_READY_TIMEOUT="${WEB_READY_TIMEOUT:-20}"
WEB_URL="http://127.0.0.1:${RERUN_WEB_PORT}/?url=rerun%2Bhttp%3A%2F%2Flocalhost%3A${RERUN_GRPC_PORT}%2Fproxy"

if [[ $# -gt 0 ]]; then
  echo "run_rerun_stack.sh does not accept arguments; use environment variables instead." >&2
  exit 1
fi

fail() {
  echo "$*" >&2
  exit 1
}

if [[ ! -f "$REPO_ROOT/build/ssp/scenario.ssp" ]]; then
  fail "Prepared airplane SSP not found: build/ssp/scenario.ssp. Run ./scripts/build_airplane.py first."
fi

if [[ ! -f "$REPO_ROOT/$SCENARIO_PATH" ]]; then
  fail "Scenario file not found: $SCENARIO_PATH"
fi

if ! command -v setsid >/dev/null 2>&1; then
  fail "setsid is required to start and stop the simulation as its own process group."
fi

SIM_PID=""
VIEWER_PID=""
WEB_PID=""
CHROME_PID=""
XHOST_ADDED=0

cleanup() {
  if [[ -n "$CHROME_PID" ]]; then
    kill "$CHROME_PID" >/dev/null 2>&1 || true
    wait "$CHROME_PID" >/dev/null 2>&1 || true
  fi
  if [[ -n "$WEB_PID" ]]; then
    kill -- "-$WEB_PID" >/dev/null 2>&1 || kill "$WEB_PID" >/dev/null 2>&1 || true
    wait "$WEB_PID" >/dev/null 2>&1 || true
  fi
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

# The federation is synchronous: run_e2e_rpr writes truth.jsonl and run.json
# when the recorder closes. Wait for it, then replay the recorder's truth stream.

# RERUN_WEB support: find a browser that can run the web viewer.

find_chrome() {
  local candidate
  if [[ -n "$CHROME_BIN" ]]; then
    printf '%s\n' "$CHROME_BIN"
    return 0
  fi
  for candidate in google-chrome google-chrome-stable chromium chromium-browser; do
    if command -v "$candidate" >/dev/null 2>&1; then
      command -v "$candidate"
      return 0
    fi
  done
  if [[ -x /opt/google/chrome/chrome ]]; then
    printf '%s\n' /opt/google/chrome/chrome
    return 0
  fi
  return 1
}

wait_for_web() {
  local start_epoch deadline
  start_epoch="$(date +%s)"
  deadline=$((start_epoch + WEB_READY_TIMEOUT))
  while (( $(date +%s) <= deadline )); do
    if ! kill -0 "$WEB_PID" >/dev/null 2>&1; then
      echo "Rerun web server exited early (see build/results/rerun_web.log)." >&2
      return 1
    fi
    if (exec 3<>"/dev/tcp/127.0.0.1/$RERUN_WEB_PORT") 2>/dev/null; then
      exec 3>&- 3<&-
      return 0
    fi
    sleep 0.25
  done
  echo "Timed out after ${WEB_READY_TIMEOUT}s waiting for http://127.0.0.1:$RERUN_WEB_PORT." >&2
  return 1
}

mkdir -p "$REPO_ROOT/build/results"

# Resolve the interpreter once: the scenario runner re-execs itself with
# sys.executable, and the system python lacks the simulation dependencies.
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

echo "Starting federation (realtime) ..."
SIM_ARGS=(
  --realtime
  --stop-time "$STOP_TIME"
  --run-dir "$RUN_DIR"
  --scenario "$SCENARIO_PATH"
  --transport "$TRANSPORT"
)
if [[ -n "$UNIX_DIR" ]]; then
  SIM_ARGS+=(--unix-dir "$UNIX_DIR")
fi
if [[ -n "$MANIFEST" ]]; then
  SIM_ARGS+=(--manifest "$MANIFEST")
fi
(
  cd "$REPO_ROOT"
  exec setsid "$PYTHON" ./scripts/run_e2e_rpr.py "${SIM_ARGS[@]}"
) &
SIM_PID=$!

echo "Waiting for the federation to write its RPR recording ..."
if ! wait "$SIM_PID"; then
  SIM_PID=""
  fail "Federation run failed; see $RUN_DIR/run.json and $RUN_DIR/logs."
fi
SIM_PID=""
[[ -s "$REPO_ROOT/$TRUTH_PATH" ]] || fail "Recorder wrote no truth stream at $TRUTH_PATH."
[[ -f "$REPO_ROOT/$RUN_DIR/run.json" ]] || fail "Federation wrote no $RUN_DIR/run.json."

VIEWER_ARGS=(
  --source jsonl
  --path "$TRUTH_PATH"
  --sink rerun
  --scenario "$SCENARIO_PATH"
  --realtime
)

if [[ "$RERUN_WEB" == "1" ]]; then
  [[ "$RERUN_CONTAINER" == "1" ]] && fail "RERUN_WEB=1 cannot be combined with RERUN_CONTAINER=1."
  VIEWER_ARGS+=(--connect-grpc)
else
  VIEWER_ARGS+=(--spawn)
fi

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
  if ! "$PYTHON" -c "import rerun" >/dev/null 2>&1; then
    fail "$PYTHON cannot import rerun. Install flight_viewer/requirements.txt or set PYTHON."
  fi

  if [[ "$RERUN_WEB" == "1" ]]; then
    RERUN_BIN="$(dirname "$PYTHON")/rerun"
    if [[ ! -x "$RERUN_BIN" ]]; then
      RERUN_BIN="$(command -v rerun || true)"
    fi
    [[ -n "$RERUN_BIN" ]] || fail "RERUN_WEB=1 requires the rerun CLI (venv/bin/rerun)."
    CHROME="$(find_chrome)" || fail "RERUN_WEB=1 requires Chrome or Chromium; set CHROME_BIN."
    [[ -n "${DISPLAY:-}" ]] || fail "RERUN_WEB=1 requires DISPLAY to be set."

    echo "Starting Rerun web server on :$RERUN_WEB_PORT (gRPC :$RERUN_GRPC_PORT) ..."
    (
      cd "$REPO_ROOT"
      exec setsid "$RERUN_BIN" --serve-web \
        --web-viewer-port "$RERUN_WEB_PORT" \
        --port "$RERUN_GRPC_PORT" \
        >"$REPO_ROOT/build/results/rerun_web.log" 2>&1
    ) &
    WEB_PID=$!
    wait_for_web

    # SwiftShader gives WebGL2 on hosts without a usable GPU; without these
    # flags the web viewer's canvas fails to get a context and stays blank.
    echo "Opening web viewer in Chrome ..."
    "$CHROME" \
      --user-data-dir="$REPO_ROOT/build/chrome-rerun" \
      --no-first-run --no-default-browser-check \
      --ignore-gpu-blocklist --enable-unsafe-swiftshader \
      --use-gl=angle --use-angle=swiftshader \
      --window-size=1700,950 --window-position=120,80 \
      --app="$WEB_URL" >/dev/null 2>&1 &
    CHROME_PID=$!
  fi

  (
    cd "$REPO_ROOT"
    exec "$PYTHON" -m flight_viewer "${VIEWER_ARGS[@]}"
  ) &
  VIEWER_PID=$!
  wait "$VIEWER_PID"
fi
