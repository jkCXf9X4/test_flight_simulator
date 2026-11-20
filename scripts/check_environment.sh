#!/usr/bin/env bash

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
AIRPLANE_ROOT="$REPO_ROOT/3rd_party/airplane"
WORKSPACE_VENV_PYTHON="$REPO_ROOT/../venv/bin/python3"
AIRPLANE_VENV_PYTHON="$AIRPLANE_ROOT/venv/bin/python3"
IMAGE_NAME="${IMAGE_NAME:-test-flight-simulator-rerun:latest}"
MODE="${1:---live-container}"

#: Imported by the airplane build CLIs.
BUILD_IMPORTS="pyssp_sysml2, pyssp_standard, pyssp_workflow, pycps_sysml2"

fail() {
  echo "Environment check failed: $*" >&2
  exit 1
}

check_podman() {
  command -v podman >/dev/null 2>&1 || fail "podman is not installed or not on PATH"
}

check_image_present() {
  podman image exists "$IMAGE_NAME" || fail "Podman image $IMAGE_NAME is missing. Run ./scripts/build_rerun_container.sh"
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

# Mirrors scripts/build_airplane.py: $PYTHON, workspace venv, airplane venv, PATH.
resolve_build_python() {
  local candidates=()
  [[ -n "${PYTHON:-}" ]] && candidates+=("$PYTHON")
  candidates+=("$WORKSPACE_VENV_PYTHON" "$AIRPLANE_VENV_PYTHON")
  if command -v python3 >/dev/null 2>&1; then
    candidates+=("$(command -v python3)")
  fi

  local py
  for py in "${candidates[@]}"; do
    [[ -f "$py" ]] || continue
    "$py" -c "import ${BUILD_IMPORTS}" >/dev/null 2>&1 || continue
    if [[ -x "$(dirname "$py")/pyfmi" ]] || command -v pyfmi >/dev/null 2>&1; then
      printf '%s\n' "$py"
      return 0
    fi
  done
  return 1
}

check_source_build() {
  local py
  py="$(resolve_build_python)" || fail "no interpreter imports ${BUILD_IMPORTS} and has pyfmi. Set PYTHON to one that does (workspace venv: $WORKSPACE_VENV_PYTHON)."
  echo "build python: $py"

  if [[ -n "${OMC:-}" ]]; then
    [[ -x "$OMC" ]] || fail "OMC=$OMC is not executable"
  else
    command -v omc >/dev/null 2>&1 || fail "omc is not installed or not on PATH (OpenModelica 1.26.x); set OMC to its full path"
  fi
  echo "omc: $(command -v "${OMC:-omc}")"

  command -v cmake >/dev/null 2>&1 || fail "cmake is not installed or not on PATH (>= 3.16)"
  echo "cmake: $(command -v cmake)"

  if ! command -v c++ >/dev/null 2>&1 && ! command -v g++ >/dev/null 2>&1; then
    fail "no C++ compiler (c++ or g++) on PATH; the UdpBridge FMU is built natively"
  fi
  echo "c++: $(command -v c++ || command -v g++)"
}

case "$MODE" in
  --live-container)
    check_podman
    check_image_present
    check_x11
    ;;
  --source-build)
    check_source_build
    ;;
  --container-build)
    check_podman
    ;;
  *)
    fail "unknown mode $MODE. Expected one of: --live-container, --source-build, --container-build"
    ;;
esac

echo "Environment check passed for $MODE"
