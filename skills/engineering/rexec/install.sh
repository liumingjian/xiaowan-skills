#!/usr/bin/env bash
set -eu
BASE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
STATE="${REXEC_STATE_DIR:-/var/lib/rexec}"
BIN="${REXEC_INSTALL_BIN_DIR:-/usr/local/bin}"
OWNER_UID="${SUDO_UID:-$(id -u)}"
OWNER_GID="${SUDO_GID:-$(id -g)}"
case "$OWNER_UID:$OWNER_GID" in *[!0-9:]*|0:*) printf '{"error":"INSTALL_OWNER_REQUIRED"}\n'; exit 2;; esac
if [ "$STATE" = / ] || [ -L "$STATE" ] || [ -L "$BIN" ] || [ -L "$STATE/bin" ] || [ -L "$STATE/runtime" ]; then
  printf '{"error":"PRIVATE_STORAGE_REQUIRED"}\n'; exit 2
fi
if [ -e "$STATE/macs" ]; then
  printf '{"error":"LEGACY_STATE_REQUIRES_REVIEW"}\n'; exit 2
fi
umask 077
mkdir -p "$STATE/bin" "$STATE/runtime" "$BIN"
chmod 700 "$STATE" "$STATE/bin" "$STATE/runtime"
cp -R "$BASE/runtime/rexec_runtime" "$STATE/runtime/"
# The Mac pulls this wrapper and the runtime beside it to install or update its worker.
install -m 600 "$BASE/agent.sh" "$STATE/agent.sh"
for NAME in rexec rexec-worker rexec-provision; do
  install -m 755 "$BASE/server/$NAME" "$STATE/bin/$NAME"
  ln -sfn "$STATE/bin/$NAME" "$BIN/$NAME"
done
if [ "$(id -u)" = 0 ]; then
  chown -R "$OWNER_UID:$OWNER_GID" "$STATE"
fi
printf '{"installed":true,"services_started":false}\n'
