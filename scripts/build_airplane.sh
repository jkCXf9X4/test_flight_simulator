#!/usr/bin/env bash

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
AIRPLANE_ROOT="$REPO_ROOT/3rd_party/airplane"

cd "$AIRPLANE_ROOT"
if [[ -x venv/bin/python3 ]]; then
  exec venv/bin/python3 scripts/workflows/rebuild_from_source.py
fi

exec python3 scripts/workflows/rebuild_from_source.py
