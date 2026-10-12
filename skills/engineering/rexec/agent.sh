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
  STATE="${REXEC_STATE_DIR:-$HOME/.local/share/rexec}"
  run() { PYTHONPATH="$HOME_DIR/runtime" "$PYTHON" -m rexec_runtime agent "$@"; }
  # Each step reports on stderr; stdout carries only the final result line.
  start_worker() {
    if [ ! -f "$STATE/worker.token" ]; then run setup >&2 || return 1; fi
    run service install >&2 && run service start >&2
  }
  # Stop whichever worker is loaded before the swap; running supervisors keep their deadlines.
  PYTHONPATH="$FETCHED/runtime" "$PYTHON" -m rexec_runtime agent service stop >&2
  rm -rf "$HOME_DIR/runtime.old" "$HOME_DIR/runtime.failed"
  if [ -d "$HOME_DIR/runtime" ]; then mv "$HOME_DIR/runtime" "$HOME_DIR/runtime.old"; fi
  mv "$FETCHED/runtime" "$HOME_DIR/runtime"
  SINCE="$(date +%s)"
  RESULT=""
  # Success means the new worker heartbeated to the VPS, not merely that launchd accepted it.
  if start_worker && RESULT="$(run verify "$SINCE")"; then
    mv "$FETCHED/agent.sh" "$HOME_DIR/agent.sh"
    rm -rf "$HOME_DIR/runtime.old"
    printf '{"updated":true,%s\n' "${RESULT#\{}"
    exit 0
  fi
  # The verify error (or null when an earlier step failed; its output is on stderr) names the cause.
  CAUSE="${RESULT:-null}"
  # Put the previous runtime back so the Mac keeps serving; runtime.failed stays for inspection.
  if [ -d "$HOME_DIR/runtime.old" ]; then
    PYTHONPATH="$HOME_DIR/runtime" "$PYTHON" -m rexec_runtime agent service stop >&2 || true
    mv "$HOME_DIR/runtime" "$HOME_DIR/runtime.failed"
    mv "$HOME_DIR/runtime.old" "$HOME_DIR/runtime"
    if start_worker; then
      printf '{"updated":false,"cause":%s,"rolled_back":true,"running":true}\n' "$CAUSE"
    else
      printf '{"updated":false,"cause":%s,"rolled_back":true,"running":false}\n' "$CAUSE"
    fi
  else
    printf '{"updated":false,"cause":%s,"rolled_back":false,"running":false}\n' "$CAUSE"
  fi
  exit 1
fi
BASE="$(cd "$(dirname "${BASH_SOURCE[0]}")/runtime" && pwd)"
export PYTHONPATH="$BASE"
# Resolve the runtime now; launchd receives this absolute executable path.
PYTHON="$(uv python find)"
exec "$PYTHON" -m rexec_runtime agent "$@"
