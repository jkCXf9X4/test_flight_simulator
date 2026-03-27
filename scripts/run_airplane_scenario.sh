#!/usr/bin/env bash

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
AIRPLANE_ROOT="$REPO_ROOT/3rd_party/airplane"

SCENARIO_PATH="${1:-resources/scenarios/test_scenario.json}"
shift || true

cd "$AIRPLANE_ROOT"
source venv/bin/activate
exec python3 -m scripts.workflows.simulate_scenario --scenario "$SCENARIO_PATH" "$@"
