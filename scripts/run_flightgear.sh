#!/usr/bin/env bash

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PROTOCOL_SRC_DIR="$REPO_ROOT/flightgear/Protocol"
SYSTEM_FG_ROOT="${SYSTEM_FG_ROOT:-/usr/share/games/flightgear}"

if command -v fgfs >/dev/null 2>&1; then
  FG_COMMAND="$(command -v fgfs)"
elif command -v flightgear >/dev/null 2>&1; then
  FG_COMMAND="$(command -v flightgear)"
else
  echo "Could not find FlightGear on PATH. Expected 'fgfs' or 'flightgear'." >&2
  exit 1
fi

FGFS_HOME_ROOT="${FGFS_HOME_ROOT:-/tmp/test-flight-simulator-fgfs}"
FG_ROOT_OVERLAY="${FG_ROOT_OVERLAY:-/tmp/test-flight-simulator-fgroot}"
mkdir -p "$FGFS_HOME_ROOT/.fgfs/Protocol"
cp "$PROTOCOL_SRC_DIR"/*.xml "$FGFS_HOME_ROOT/.fgfs/Protocol/"

mkdir -p "$FG_ROOT_OVERLAY"
for entry in "$SYSTEM_FG_ROOT"/*; do
  name="$(basename "$entry")"
  if [[ "$name" == "Protocol" ]]; then
    continue
  fi
  if [[ ! -e "$FG_ROOT_OVERLAY/$name" ]]; then
    ln -s "$entry" "$FG_ROOT_OVERLAY/$name"
  fi
done
mkdir -p "$FG_ROOT_OVERLAY/Protocol"
cp "$PROTOCOL_SRC_DIR"/*.xml "$FG_ROOT_OVERLAY/Protocol/"

exec env HOME="$FGFS_HOME_ROOT" \
  "$FG_COMMAND" \
  --fg-root="$FG_ROOT_OVERLAY" \
  --aircraft=ufo \
  --fdm=null \
  --disable-terrasync \
  --timeofday=noon \
  --generic=socket,in,10,127.0.0.1,5501,udp,ssp_aircraft_state \
  --generic=socket,out,10,127.0.0.1,5502,udp,ssp_aircraft_controls \
  "$@"
