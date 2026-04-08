#!/usr/bin/env bash

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
AIRPLANE_ROOT="$REPO_ROOT/3rd_party/airplane"

SCENARIO_PATH="${1:-resources/scenarios/test_scenario.json}"
shift || true

cd "$AIRPLANE_ROOT"
if [[ -f venv/bin/activate ]]; then
  source venv/bin/activate
fi
exec python3 -m scripts.cli.scenarios_simulate --scenario "$SCENARIO_PATH" "$@"
