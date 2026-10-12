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
# Replace the package as a whole: copying over it would keep modules a release removed.
rm -rf "$STATE/runtime/.next" "$STATE/runtime/.old"
cp -R "$BASE/runtime/rexec_runtime" "$STATE/runtime/.next"
rm -rf "$STATE/runtime/.next/__pycache__"
if [ -d "$STATE/runtime/rexec_runtime" ]; then mv "$STATE/runtime/rexec_runtime" "$STATE/runtime/.old"; fi
mv "$STATE/runtime/.next" "$STATE/runtime/rexec_runtime"
rm -rf "$STATE/runtime/.old"
# The Mac pulls this wrapper and the runtime beside it to install or update its worker.
install -m 600 "$BASE/agent.sh" "$STATE/agent.sh"
for NAME in rexec rexec-worker rexec-provision; do
  install -m 755 "$BASE/server/$NAME" "$STATE/bin/$NAME"
  ln -sfn "$STATE/bin/$NAME" "$BIN/$NAME"
done
if [ "$(id -u)" = 0 ]; then
  chown -R "$OWNER_UID:$OWNER_GID" "$STATE"
fi
# `rexec status` shows runtime_skew until the Mac runs this same runtime.
RUNTIME="$(cd / && PYTHONPATH="$STATE/runtime" python3 -B -c 'from rexec_runtime.common import runtime_version; print(runtime_version())')"
printf '{"installed":true,"runtime":"%s","services_started":false}\n' "$RUNTIME"
