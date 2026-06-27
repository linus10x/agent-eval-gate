#!/usr/bin/env bash
set -euo pipefail
# One-command MCP server. The process exit code IS the server's return value.
# No make, no install, no network: PYTHONPATH points at the in-tree src + vendor
# so the package and the vendored gate resolve from this repo alone.
cd "$(dirname "$0")"
export PYTHONPATH="$(pwd)/src:$(pwd)/vendor${PYTHONPATH:+:$PYTHONPATH}"
exec python3 -m agent_eval_gate.server "$@"
