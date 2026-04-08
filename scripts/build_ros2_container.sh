#!/usr/bin/env bash

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
IMAGE_NAME="${IMAGE_NAME:-test-flight-simulator-ros2:kilted}"

exec podman build \
  -f "$REPO_ROOT/Containerfile.ros2" \
  -t "$IMAGE_NAME" \
  "$REPO_ROOT"
