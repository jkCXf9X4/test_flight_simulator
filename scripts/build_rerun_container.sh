#!/usr/bin/env bash

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
IMAGE_NAME="${IMAGE_NAME:-test-flight-simulator-rerun:latest}"

if ! command -v podman >/dev/null 2>&1; then
  echo "podman is not installed or not on PATH; install Podman to build $IMAGE_NAME." >&2
  exit 1
fi

exec podman build \
  -f "$REPO_ROOT/Containerfile.rerun" \
  -t "$IMAGE_NAME" \
  "$REPO_ROOT"
