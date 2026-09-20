#!/usr/bin/env bash
# rexec shared library: multi-mac namespacing and identity resolution.
# Shared by rexec / queue / cancel / claim / report.
#
# Directory layout (one independent queue per mac, fully isolated):
#   /var/lib/rexec/macs/<MACID>/{queue,running,results,cancel,alive}
#   /var/lib/rexec/macs/<MACID>/{agent.alive,gate.status,origin,name}
#   /var/lib/rexec/{seq,seq.lock,history.jsonl,default}   shared globally
#
# The state lives outside /root because two different unix users touch it: the `agent` user runs the
# client (rexec), while the mac's agent reaches the server side over ssh as root. The tree is
# group-owned by `agent` and setgid; umask 002 keeps everything root creates group-writable, so the
# client can still consume and clean up its own results.
ROOT=${REXEC_ROOT:-/var/lib/rexec}
MACS="$ROOT/macs"
umask 002

mac_dirs() { # create the full directory set for one mac
  mkdir -p "$MACS/$1/queue" "$MACS/$1/running" "$MACS/$1/results" "$MACS/$1/cancel" "$MACS/$1/alive"
}
all_macs()  { for d in "$MACS"/*; do [ -d "$d" ] && basename "$d"; done; }
mac_hb()    { l=$(cat "$MACS/$1/agent.alive" 2>/dev/null); case "$l" in ''|*[!0-9]*) l=0;; esac; printf '%s' "$l"; }
mac_online(){ h=$(mac_hb "$1"); [ "$h" -gt 0 ] && [ $(( $(date +%s) - h )) -le 60 ]; }
online_macs(){ for m in $(all_macs); do mac_online "$m" && echo "$m"; done; }
mac_label() { n=$(cat "$MACS/$1/name" 2>/dev/null); [ -n "$n" ] && printf '%s' "$n" || printf '%s' "$1"; }

# Read one process's environment. Running as `agent`, the ancestors up the chain are root-owned and
# /proc/<pid>/environ is unreadable, which used to silently lose the session's login; fall back to
# passwordless sudo when it is available, and stay quiet when it is not.
read_environ() {
  { cat "/proc/$1/environ" 2>/dev/null || sudo -n cat "/proc/$1/environ" 2>/dev/null; } \
    | tr '\0' '\n' 2>/dev/null
}

# ::ffff:1.2.3.4 and 1.2.3.4 are the same host reached over a dual stack; store and compare one form.
norm_ip() { printf '%s' "${1#::ffff:}"; }

# Record the IP a mac last called from. Display only: routing never reads it, because home IPs rotate
# and a proxy can give one mac several at once.
note_origin() { # MACID IP
  _ip=$(norm_ip "$2"); [ -n "$_ip" ] || return 0
  printf '%s' "$_ip" > "$MACS/$1/.orig.$$" && mv "$MACS/$1/.orig.$$" "$MACS/$1/origin"
}

# ---- caller heartbeat ----
# `rexec` writes the current time into alive/<ID> before it submits, and again on every poll of its wait
# loop. A caller that is killed outright - ESC is trapped, but a compacted session, an OOM kill or a
# dropped ssh link is not - stops touching it, and that silence is the only reliable way to tell "nobody
# is waiting for this any more" from "this is simply taking a while". Without it an abandoned job keeps
# its place in the queue forever, survives every agent restart, and blocks its project-mates behind it.
#
# A job with no heartbeat file at all was submitted by a client that predates this, so it is left alone:
# grandfathering costs one stale job that finishes on its own, while the opposite default would reap
# every in-flight job the moment the server is upgraded.
CALLER_GRACE=${REXEC_CALLER_GRACE:-90}

caller_gone() { # MACID ID -> true when the caller has stopped heartbeating
  _a="$MACS/$1/alive/$2"
  [ -f "$_a" ] || return 1
  _t=$(cat "$_a" 2>/dev/null); case "$_t" in ''|*[!0-9]*) return 1;; esac
  [ $(( $(date +%s) - _t )) -gt "$CALLER_GRACE" ]
}

# Finish a job the mac is not running any more, handing its caller a result instead of leaving a
# `running/` entry nobody will ever report. Such an entry is indistinguishable from a live job to
# rexec-claim, so it holds its project's slot forever - and every path that can strand a job (agent
# restart, agent losing its local job records) ends here rather than dropping the files quietly.
reap_job() { # MACID ID EXIT REASON
  _m="$MACS/$1"; _id="$2"; _ex="$3"; _why="$4"
  _job="$_m/running/$_id.job"
  _sub=$(sed -n 's/^SUBMIT=//p'  "$_job" 2>/dev/null); case "$_sub" in ''|*[!0-9]*) _sub=0;; esac
  _cmd=$(sed -n 's/^CMD=//p'     "$_job" 2>/dev/null)
  _prj=$(sed -n 's/^PROJECT=//p' "$_job" 2>/dev/null)
  _st=$(cat "$_m/running/$_id.started" 2>/dev/null); case "$_st" in ''|*[!0-9]*) _st=0;; esac
  _now=$(date +%s)
  _q=0; [ "$_sub" -gt 0 ] && [ "$_st" -ge "$_sub" ] && _q=$(( _st - _sub ))
  _ran=0; [ "$_st" -gt 0 ] && _ran=$(( _now - _st ))
  printf '[rexec] %s\n' "$_why" > "$_m/results/.$_id.out.tmp"
  mv "$_m/results/.$_id.out.tmp" "$_m/results/$_id.out"
  printf 'EXIT=%s\nRAN=%s\nQUEUED=%s\n' "$_ex" "$_ran" "$_q" > "$_m/results/.$_id.done.tmp"
  mv "$_m/results/.$_id.done.tmp" "$_m/results/$_id.done"
  printf '{"id":"%s","mac":"%s","project":"%s","exit":%s,"queued":%s,"ran":%s,"end":%s,"cmd_b64":"%s"}\n' \
    "$_id" "$1" "$_prj" "$_ex" "$_q" "$_ran" "$_now" "$_cmd" >> "$ROOT/history.jsonl"
  rm -f "$_job" "$_m/running/$_id.started" "$_m/cancel/$_id" "$_m/alive/$_id"
}

# ---- identity: every mac logs in with its own ssh key ----
# Each mac's public key sits in authorized_keys with the comment `rexec-mac=<MACID>`. sshd runs with
# `ExposeAuthInfo yes`, so every login gets $SSH_USER_AUTH: a file naming the key it authenticated
# with, which sshd deletes when the login ends.
KEYS=${REXEC_KEYS:-$HOME/.ssh/authorized_keys}

# The MACID tagged on the key recorded in auth-info file $1. Empty when the file is gone (the login
# ended) or the key carries no tag (a key shared by several macs).
mac_of_auth() {
  [ -n "${1:-}" ] && [ -r "$1" ] || return 0
  _blob=$(awk '$1=="publickey"{print $3; exit}' "$1")
  [ -n "$_blob" ] || return 0
  awk -v b="$_blob" '{
      for (i = 1; i <= NF; i++) if ($i == b) {
        for (j = i + 1; j <= NF; j++) if ($j ~ /^rexec-mac=/) { sub(/^rexec-mac=/, "", $j); print $j; exit }
      }
    }' "$KEYS" 2>/dev/null
}

# The auth-info file of the ssh login this invocation descends from. rexec may be called from a deep
# child, so walk up the parent chain and stop at the first process carrying SSH_USER_AUTH. A process
# that outlived its login (a Claude daemon spawning background jobs) still carries the variable, but
# sshd has deleted the file, so it resolves to nothing rather than to whichever mac logged in when the
# daemon started.
session_auth_file() {
  if [ -n "${SSH_USER_AUTH:-}" ]; then printf '%s' "$SSH_USER_AUTH"; return 0; fi
  p=$$; i=0
  while [ "$p" -gt 1 ] && [ "$i" -lt 40 ]; do
    v=$(read_environ "$p" | sed -n 's/^SSH_USER_AUTH=//p' | head -1)
    [ -n "$v" ] && { printf '%s' "$v"; return 0; }
    p=$(awk '{print $4}' "/proc/$p/stat" 2>/dev/null); case "$p" in ''|*[!0-9]*) p=1;; esac
    i=$((i+1))
  done
  return 0
}
session_mac() { mac_of_auth "$(session_auth_file)"; }

# The mac set with `rexec --use`, which picks one when several are online and no live login names one.
default_mac() {
  _d=$(cat "$ROOT/default" 2>/dev/null)
  if [ -n "$_d" ] && [ -d "$MACS/$_d" ]; then printf '%s' "$_d"; fi
}

# Called by the agent's own logins (announce, claim): refuse a MACID other than the one the login key
# is tagged with. A login without auth info, or with an untagged key, is let through, so a mac still on
# a shared key keeps working until it gets its own.
login_matches() { # MACID
  _k=$(mac_of_auth "${SSH_USER_AUTH:-}")
  [ -z "$_k" ] || [ "$_k" = "$1" ]
}

mac_list_hint() {
  echo "  macs currently known:" >&2
  found=0; _d=$(default_mac)
  for m in $(all_macs); do
    found=1
    if mac_online "$m"; then s=ONLINE; else s=OFFLINE; fi
    _u=''; [ "$m" = "$_d" ] && _u=' (rexec --use default)'
    printf '    %-18s %-8s %s%s\n' "$m" "$s" "$(mac_label "$m")" "$_u" >&2
  done
  [ "$found" = 0 ] && echo "    (none - no agent has been started on any mac yet)" >&2
}

# resolve_mac [wanted name]
# 1) explicit --mac / REXEC_MAC (a unique prefix is enough)
# 2) the mac whose key this session's live ssh login used - online or not, so an offline one reports
#    "start the agent" instead of the job silently going to a different machine
# 3) exactly one mac online - use it: an agent only runs where the user started it
# 4) several online - the `rexec --use` default, if it is one of them
# 5) otherwise fail: make the caller be explicit rather than guess a machine
# Prints __none__ when no mac is online and nothing names one.
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

  k=$(session_mac)
  [ -n "$k" ] && { printf '%s' "$k"; return 0; }

  ONLINE=$(online_macs)
  [ -n "$ONLINE" ] || { echo "__none__"; return 0; }
  n=0; last=""
  for m in $ONLINE; do n=$((n+1)); last="$m"; done
  [ "$n" = 1 ] && { printf '%s' "$last"; return 0; }

  d=$(default_mac)
  for m in $ONLINE; do [ "$m" = "$d" ] && { printf '%s' "$d"; return 0; }; done

  echo "rexec: $n macs online, and neither a live ssh login nor a default picks one." >&2
  echo "  Set a default:  rexec --use <name>     or per call:  rexec --mac <name> '<command>'" >&2
  mac_list_hint; return 3
}
