#!/usr/bin/env bash
# Deploy the rexec channel on the server (idempotent).
# The client runs as the `agent` user, while the mac's agent reaches the server side over ssh as root,
# so the state tree lives in /var/lib/rexec (group `agent`, setgid, group-writable) rather than under
# /root, which is 0700. /root/.rexec stays as a symlink to it for the root-side callers.
set -eu
S="$(cd "$(dirname "$0")" && pwd -P)"   # deploy from wherever this checkout lives
R=/var/lib/rexec
mkdir -p "$R/macs" "$R/bin" "$R/logs"
install -m 775 "$S/server/rexec"        "$S/server/rexec-claim"  "$S/server/rexec-report" \
               "$S/server/rexec-queue"  "$S/server/rexec-cancel" "$S/server/rexec-macs"   \
               "$S/server/rexec-announce" "$R/bin/"
install -m 664 "$S/server/rexec-lib.sh" "$R/bin/"
install -m 775 "$S/agent.sh" "$R/agent.sh"
# Shared between root and agent: group-owned by agent, setgid so new files inherit the group.
chgrp -R agent "$R" 2>/dev/null || sudo chgrp -R agent "$R"
chmod -R g+rwX "$R"; find "$R" -type d -exec chmod g+s {} +
sudo ln -sfn "$R" /root/.rexec
sudo ln -sfn "$R/bin/rexec" /usr/local/bin/rexec
# Clear the flat single-mac-era layout: drop empty dirs and the global heartbeat file so they are not
# confused with the same-named things under macs/<id>/.
for d in queue running results cancel; do rmdir "$R/$d" 2>/dev/null || true; done
rm -f "$R/agent.alive" "$R/gate.status"
echo "Server side deployed: $R/ (rexec linked into /usr/local/bin/, /root/.rexec -> $R)"
