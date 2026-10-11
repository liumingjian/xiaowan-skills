#!/usr/bin/env bash
set -eu -o pipefail
# With no arguments: install or update the Mac worker from the VPS in one step.
#   mkdir -p ~/.rexec && ssh vps-cc 'cat /var/lib/rexec/agent.sh' > ~/.rexec/agent.sh && bash ~/.rexec/agent.sh
if [ "$#" -eq 0 ]; then
  HOME_DIR="${REXEC_HOME:-$HOME/.rexec}"
  REMOTE="${REXEC_REMOTE_ROOT:-/var/lib/rexec}"
  umask 077
  mkdir -p "$HOME_DIR"
  FETCHED="$(mktemp -d "$HOME_DIR/.runtime-XXXXXX")"
  trap 'rm -rf "$FETCHED"' EXIT
  ssh vps-cc "tar -C '$REMOTE' --exclude=__pycache__ -cf - agent.sh runtime/rexec_runtime" | tar -x -C "$FETCHED"
  [ -f "$FETCHED/runtime/rexec_runtime/__main__.py" ] || { printf '{"error":"UPDATE_FAILED"}\n'; exit 2; }
  PYTHON="$(uv python find)"
  run() { PYTHONPATH="$HOME_DIR/runtime" "$PYTHON" -m rexec_runtime agent "$@"; }
  # Stop whichever worker is loaded before the swap; running supervisors keep their deadlines.
  PYTHONPATH="$FETCHED/runtime" "$PYTHON" -m rexec_runtime agent service stop >/dev/null
  rm -rf "$HOME_DIR/runtime.old"
  if [ -d "$HOME_DIR/runtime" ]; then mv "$HOME_DIR/runtime" "$HOME_DIR/runtime.old"; fi
  mv "$FETCHED/runtime" "$HOME_DIR/runtime"
  mv "$FETCHED/agent.sh" "$HOME_DIR/agent.sh"
  rm -rf "$HOME_DIR/runtime.old"
  STATE="${REXEC_STATE_DIR:-$HOME/.local/share/rexec}"
  if [ ! -f "$STATE/worker.token" ]; then run setup >/dev/null; fi
  run service install >/dev/null
  run service start >/dev/null
  printf '{"updated":true,"running":true}\n'
  exit 0
fi
BASE="$(cd "$(dirname "${BASH_SOURCE[0]}")/runtime" && pwd)"
export PYTHONPATH="$BASE"
# Resolve the runtime now; launchd receives this absolute executable path.
PYTHON="$(uv python find)"
exec "$PYTHON" -m rexec_runtime agent "$@"
