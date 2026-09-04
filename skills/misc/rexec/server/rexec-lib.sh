#!/usr/bin/env bash
# rexec shared library: multi-mac namespacing and identity resolution.
# Shared by rexec / queue / cancel / claim / report.
#
# Directory layout (one independent queue per mac, fully isolated):
#   /var/lib/rexec/macs/<MACID>/{queue,running,results,cancel}
#   /var/lib/rexec/macs/<MACID>/{agent.alive,gate.status,origin,name}
#   /var/lib/rexec/{seq,seq.lock,history.jsonl}          shared globally
#
# The state lives outside /root because two different unix users touch it: the `agent` user runs the
# client (rexec), while the mac's agent reaches the server side over ssh as root. The tree is
# group-owned by `agent` and setgid; umask 002 keeps everything root creates group-writable, so the
# client can still consume and clean up its own results.
ROOT=/var/lib/rexec
MACS="$ROOT/macs"
umask 002

mac_dirs() { # create the full directory set for one mac
  mkdir -p "$MACS/$1/queue" "$MACS/$1/running" "$MACS/$1/results" "$MACS/$1/cancel"
}
all_macs()  { for d in "$MACS"/*; do [ -d "$d" ] && basename "$d"; done; }
mac_hb()    { l=$(cat "$MACS/$1/agent.alive" 2>/dev/null); case "$l" in ''|*[!0-9]*) l=0;; esac; printf '%s' "$l"; }
mac_online(){ h=$(mac_hb "$1"); [ "$h" -gt 0 ] && [ $(( $(date +%s) - h )) -le 60 ]; }
online_macs(){ for m in $(all_macs); do mac_online "$m" && echo "$m"; done; }
mac_label() { n=$(cat "$MACS/$1/name" 2>/dev/null); [ -n "$n" ] && printf '%s' "$n" || printf '%s' "$1"; }

# Read one process's environment. Running as `agent`, the ancestors up the chain are root-owned and
# /proc/<pid>/environ is unreadable, which used to silently lose the session's source IP; fall back to
# passwordless sudo when it is available, and stay quiet when it is not.
read_environ() {
  { cat "/proc/$1/environ" 2>/dev/null || sudo -n cat "/proc/$1/environ" 2>/dev/null; } \
    | tr '\0' '\n' 2>/dev/null
}

# Which IP this invocation came into the VPS from.
# Claude Code and interactive shells are both descendants of sshd, so they carry SSH_CONNECTION;
# but rexec may be called from a deeper child, so walk up the parent chain to find it.
origin_ip() {
  if [ -n "${SSH_CONNECTION:-}" ]; then printf '%s' "${SSH_CONNECTION%% *}"; return 0; fi
  p=$$; i=0
  while [ "$p" -gt 1 ] && [ "$i" -lt 40 ]; do
    v=$(read_environ "$p" | sed -n 's/^SSH_CONNECTION=//p' | head -1)
    [ -n "$v" ] && { printf '%s' "${v%% *}"; return 0; }
    p=$(awk '{print $4}' "/proc/$p/stat" 2>/dev/null); case "$p" in ''|*[!0-9]*) p=1;; esac
    i=$((i+1))
  done
  return 0
}

mac_list_hint() {
  echo "  macs currently known:" >&2
  found=0
  for m in $(all_macs); do
    found=1
    if mac_online "$m"; then s=ONLINE; else s=OFFLINE; fi
    printf '    %-18s %-8s %-16s %s\n' "$m" "$s" \
      "$(cat "$MACS/$m/origin" 2>/dev/null || echo -)" "$(mac_label "$m")" >&2
  done
  [ "$found" = 0 ] && echo "    (none - no agent has been started on any mac yet)" >&2
}

# Every mac that announced from this IP, online or not.
macs_at_ip() {
  for m in $(all_macs); do
    [ "$(cat "$MACS/$m/origin" 2>/dev/null)" = "$1" ] && echo "$m"
  done
}

# resolve_mac [wanted name]
# 1) explicit --mac / REXEC_MAC (a unique prefix is enough)
# 2) the mac this session ssh'd in from, matched on source IP - online or not, so an offline one
#    reports "start the agent" instead of silently handing the job to a different machine
# 3) source IP unknown (not an ssh session) and exactly one mac online - use it
# 4) otherwise fail: make the caller be explicit rather than guess a machine
resolve_mac() {
  want="${1:-}"
  if [ -n "$want" ]; then
    [ -d "$MACS/$want" ] && { printf '%s' "$want"; return 0; }
    hit=""; n=0
    for m in $(all_macs); do
      case "$m" in "$want"*) hit="$m"; n=$((n+1));; esac
    done
    [ "$n" = 1 ] && { printf '%s' "$hit"; return 0; }
    if [ "$n" = 0 ]; then echo "rexec: no mac named '$want'." >&2
    else                  echo "rexec: prefix '$want' is not unique - it matches $n macs." >&2; fi
    mac_list_hint; return 3
  fi

  IP=$(origin_ip)
  if [ -n "$IP" ]; then
    hit=""; n=0
    for m in $(macs_at_ip "$IP"); do hit="$m"; n=$((n+1)); done
    [ "$n" = 1 ] && { printf '%s' "$hit"; return 0; }
    if [ "$n" = 0 ]; then
      # No agent has ever announced from this IP. Another mac may well be online, but it is not the
      # machine this session is sitting on, so the job must not go there.
      echo "__none__"; return 0
    fi
    echo "rexec: $n macs share this session's source IP ($IP), so it does not identify which to use." >&2
    echo "  Be explicit:  rexec --mac <name> '<command>'" >&2
    mac_list_hint; return 3
  fi

  ONLINE=$(online_macs)
  [ -n "$ONLINE" ] || { echo "__none__"; return 0; }
  n=0; last=""
  for m in $ONLINE; do n=$((n+1)); last="$m"; done
  [ "$n" = 1 ] && { printf '%s' "$last"; return 0; }

  echo "rexec: $n macs online, and this session has no ssh source IP to identify which to use." >&2
  echo "  Be explicit:  rexec --mac <name> '<command>'" >&2
  mac_list_hint; return 3
}
