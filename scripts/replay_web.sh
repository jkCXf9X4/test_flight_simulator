#!/usr/bin/env bash

# Replay an RPR truth log in the Rerun web viewer.
#
# The native viewer renders poorly on GPU-less hosts and a loaded .rrd opens
# paused (and cannot be driven from the browser), so this launches a Rerun web
# server, opens it in a dedicated Chrome instance with the SwiftShader WebGL2
# fallback, and streams the truth log into the viewer at realtime pace.
#
#   ./scripts/replay_web.sh build/runs/sos4-120/truth.jsonl
#   RATE=2 ./scripts/replay_web.sh build/runs/sos4-120/truth.jsonl
#
# Environment:
#   RATE            playback speed (default 1.0)
#   TAIL            trail points per entity (default 40)
#   RERUN_WEB_PORT  web viewer port (default 9090)
#   RERUN_GRPC_PORT gRPC port (default 9876)
#   CHROME_BIN      browser to use (default: google-chrome, chromium, ...)
#   PYTHON          interpreter with rerun installed (default: workspace venv)

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TRUTH="${1:-$REPO_ROOT/build/runs/sos4-120/truth.jsonl}"
RATE="${RATE:-1.0}"
TAIL="${TAIL:-40}"
RERUN_WEB_PORT="${RERUN_WEB_PORT:-9090}"
RERUN_GRPC_PORT="${RERUN_GRPC_PORT:-9876}"
CHROME_BIN="${CHROME_BIN:-}"
WEB_WINDOW="${WEB_WINDOW:-1100,700}"
WEB_READY_TIMEOUT="${WEB_READY_TIMEOUT:-20}"
PROFILE_DIR="${PROFILE_DIR:-$REPO_ROOT/build/chrome-rerun}"
CHROME_DEBUG_PORT="${CHROME_DEBUG_PORT:-}"
WEB_URL="http://127.0.0.1:${RERUN_WEB_PORT}/?url=rerun%2Bhttp%3A%2F%2Flocalhost%3A${RERUN_GRPC_PORT}%2Fproxy"

fail() {
  echo "$*" >&2
  exit 1
}

[[ -f "$TRUTH" ]] || fail "Truth log not found: $TRUTH"

PYTHON="${PYTHON:-}"
if [[ -z "$PYTHON" ]]; then
  if [[ -x "$REPO_ROOT/../venv/bin/python" ]]; then
    PYTHON="$REPO_ROOT/../venv/bin/python"
  else
    PYTHON="$(command -v python3 || true)"
  fi
fi
[[ -n "$PYTHON" ]] || fail "No Python interpreter found; set PYTHON."

RERUN_BIN="$(dirname "$PYTHON")/rerun"
[[ -x "$RERUN_BIN" ]] || RERUN_BIN="$(command -v rerun || true)"
[[ -n "$RERUN_BIN" ]] || fail "rerun CLI not found next to $PYTHON; set PYTHON to the venv."

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

CHROME="$(find_chrome)" || fail "Chrome/Chromium not found; set CHROME_BIN."
[[ -n "${DISPLAY:-}" ]] || fail "DISPLAY is not set."

WEB_PID=""
CHROME_PID=""

cleanup() {
  if [[ -n "$CHROME_PID" ]]; then
    kill "$CHROME_PID" >/dev/null 2>&1 || true
    wait "$CHROME_PID" >/dev/null 2>&1 || true
  fi
  if [[ -n "$WEB_PID" ]]; then
    kill -- "-$WEB_PID" >/dev/null 2>&1 || kill "$WEB_PID" >/dev/null 2>&1 || true
    wait "$WEB_PID" >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT INT TERM

wait_for_web() {
  local deadline
  deadline=$(( $(date +%s) + WEB_READY_TIMEOUT ))
  while (( $(date +%s) <= deadline )); do
    if ! kill -0 "$WEB_PID" >/dev/null 2>&1; then
      fail "Rerun web server exited early (see the launch log)."
    fi
    if (exec 3<>"/dev/tcp/127.0.0.1/$RERUN_WEB_PORT") 2>/dev/null; then
      exec 3>&- 3<&-
      return 0
    fi
    sleep 0.25
  done
  fail "Timed out waiting for http://127.0.0.1:$RERUN_WEB_PORT."
}

mkdir -p "$REPO_ROOT/build/results"

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

# SwiftShader supplies WebGL2 where no usable GPU exists; without these flags
# the web viewer never gets a canvas context. The occlusion flags keep Chrome
# painting while the window is covered.
echo "Opening the web viewer in Chrome ..."
CHROME_ARGS=(
  --user-data-dir="$PROFILE_DIR"
  --no-first-run --no-default-browser-check
  --disable-backgrounding-occluded-windows
  --disable-renderer-backgrounding
  --disable-features=CalculateNativeWinOcclusion
  --ignore-gpu-blocklist --enable-unsafe-swiftshader
  --use-gl=angle --use-angle=swiftshader
  --window-size="$WEB_WINDOW" --window-position=120,80
)
if [[ -n "$CHROME_DEBUG_PORT" ]]; then
  CHROME_ARGS+=(--remote-debugging-port="$CHROME_DEBUG_PORT")
fi
"$CHROME" "${CHROME_ARGS[@]}" --app="$WEB_URL" >/dev/null 2>&1 &
CHROME_PID=$!

sleep 5
echo "Streaming $TRUTH at ${RATE}x ..."
"$PYTHON" "$REPO_ROOT/scripts/stream_truth_rerun.py" "$TRUTH" \
  --connect "rerun+http://127.0.0.1:${RERUN_GRPC_PORT}/proxy" \
  --tail "$TAIL" --rate "$RATE"

echo "Replay finished; viewer stays open until you close it (Ctrl-C here stops both)."
wait "$CHROME_PID"
