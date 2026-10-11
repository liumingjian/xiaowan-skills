#!/usr/bin/env bash
set -eu
BASE="$(cd "$(dirname "${BASH_SOURCE[0]}")/runtime" && pwd)"
export PYTHONPATH="$BASE"
# Resolve the runtime now; launchd receives this absolute executable path.
PYTHON="$(uv python find)"
exec "$PYTHON" -m rexec_runtime agent "$@"
