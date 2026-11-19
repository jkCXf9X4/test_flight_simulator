#!/usr/bin/env bash

# Headless Rerun smoke test. No X11, no Podman, no viewer: generate a small
# JSONL recording, replay it through dis_viewer into an .rrd, and assert the
# recording is non-empty. Runs on the host with the repo venv.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RECORDING="${RECORDING:-/tmp/rerun_smoke.jsonl}"
RRD="${RRD:-/tmp/smoke.rrd}"

PYTHON="${PYTHON:-}"
if [[ -z "$PYTHON" ]]; then
  if [[ -x "$REPO_ROOT/../venv/bin/python" ]]; then
    PYTHON="$REPO_ROOT/../venv/bin/python"
  else
    PYTHON="$(command -v python3 || true)"
  fi
fi

if [[ -z "$PYTHON" ]] || ! "$PYTHON" -c "import rerun" >/dev/null 2>&1; then
  echo "FAIL: no Python interpreter with rerun-sdk; set PYTHON or install dis_viewer/requirements.txt" >&2
  exit 1
fi

rm -f "$RECORDING" "$RRD"

if ! PYTHONPATH="$REPO_ROOT${PYTHONPATH:+:$PYTHONPATH}" "$PYTHON" - "$RECORDING" <<'PY'
import sys
from pathlib import Path

from dis_viewer.model import EntityKey, EntityState, EntityType
from dis_viewer.recorder import JsonlRecorder

path = Path(sys.argv[1])
key = EntityKey(site=1, application=1, entity=1)
states = [
    EntityState(
        key=key,
        t_s=0.1 * i,
        position_enu_m=(10.0 * i, 20.0 * i, 1000.0 + i),
        orientation_deg=(0.0, 0.0, 45.0),
        velocity_enu_mps=(10.0, 20.0, 1.0),
        entity_type=EntityType(),
        force_id=1,
        marking="AC-1",
        stale=False,
    )
    for i in range(4)
]
with JsonlRecorder(path) as recorder:
    recorder.write(states)
PY
then
  echo "FAIL: could not write $RECORDING" >&2
  exit 1
fi

set +e
if command -v timeout >/dev/null 2>&1; then
  PYTHONPATH="$REPO_ROOT${PYTHONPATH:+:$PYTHONPATH}" timeout 20 \
    "$PYTHON" -m dis_viewer \
      --source jsonl \
      --path "$RECORDING" \
      --sink rerun \
      --rrd "$RRD" \
      --count 2
  status=$?
else
  PYTHONPATH="$REPO_ROOT${PYTHONPATH:+:$PYTHONPATH}" \
    "$PYTHON" -m dis_viewer \
      --source jsonl \
      --path "$RECORDING" \
      --sink rerun \
      --rrd "$RRD" \
      --count 2
  status=$?
fi
set -e

if [[ "$status" -ne 0 ]]; then
  echo "FAIL: dis_viewer exited with status $status" >&2
  exit "$status"
fi

if [[ ! -s "$RRD" ]]; then
  echo "FAIL: $RRD is missing or empty" >&2
  exit 1
fi

echo "PASS: $RRD ($(stat -c %s "$RRD") bytes)"
