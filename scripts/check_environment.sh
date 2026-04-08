#!/usr/bin/env bash

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
AIRPLANE_ROOT="$REPO_ROOT/3rd_party/airplane"
IMAGE_NAME="${IMAGE_NAME:-test-flight-simulator-ros2:kilted}"
MODE="${1:---live-container}"

fail() {
  echo "Environment check failed: $*" >&2
  exit 1
}

check_podman() {
  command -v podman >/dev/null 2>&1 || fail "podman is not installed or not on PATH"
}

check_image_present() {
  podman image exists "$IMAGE_NAME" || fail "Podman image $IMAGE_NAME is missing. Run ./scripts/build_ros2_container.sh"
}

check_x11() {
  command -v xhost >/dev/null 2>&1 || fail "xhost is not installed or not on PATH"
  [[ -n "${DISPLAY:-}" ]] || fail "DISPLAY is not set"

  local display_suffix="${DISPLAY#*:}"
  local display_number="${display_suffix%%.*}"
  local socket_path="/tmp/.X11-unix/X${display_number}"
  [[ "$display_number" =~ ^[0-9]+$ ]] || fail "DISPLAY=$DISPLAY does not contain a numeric X11 display number"
  [[ -S "$socket_path" ]] || fail "X11 socket for DISPLAY=$DISPLAY is not available at $socket_path"

  local xauth_path="${XAUTHORITY:-$HOME/.Xauthority}"
  [[ -f "$xauth_path" ]] || fail "Xauthority file not found at $xauth_path"
}

check_host_ros_python() {
  command -v python3 >/dev/null 2>&1 || fail "python3 is not on PATH"
  python3 -c "import rclpy" >/dev/null 2>&1 || fail "python3 cannot import rclpy on the host"
  python3 -c "import ros2_bridge.node" >/dev/null 2>&1 || fail "python3 cannot import ros2_bridge.node on the host"
}

check_airplane_venv() {
  [[ -x "$AIRPLANE_ROOT/venv/bin/python3" ]] || fail "airplane virtualenv is missing at $AIRPLANE_ROOT/venv"
  "$AIRPLANE_ROOT/venv/bin/python3" -c "import pycps_sysmlv2" >/dev/null 2>&1 || fail "airplane virtualenv is missing required build dependencies"
}

case "$MODE" in
  --live-container)
    check_podman
    check_image_present
    check_x11
    ;;
  --source-build)
    check_airplane_venv
    ;;
  --host-ros-python)
    check_host_ros_python
    ;;
  --container-build)
    check_podman
    ;;
  *)
    fail "unknown mode $MODE. Expected one of: --live-container, --source-build, --host-ros-python, --container-build"
    ;;
esac

echo "Environment check passed for $MODE"
