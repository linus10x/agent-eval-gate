#!/usr/bin/env bash
set -euo pipefail
# Self-checking acceptance demo. Exit code IS the demo's verdict: 0 only if the
# race DENYs and the safe case is permitted. No make, no install, no network.
cd "$(dirname "$0")"
export PYTHONPATH="$(pwd)/src:$(pwd)/vendor${PYTHONPATH:+:$PYTHONPATH}"
exec python3 -m agent_eval_gate.demo "$@"
