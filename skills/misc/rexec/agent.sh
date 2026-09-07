#!/usr/bin/env bash
# rexec agent - runs on the mac, polls the server queue, executes in parallel, reports results back.
# Stop with Ctrl-C (terminates every running job, reports status, closes the multiplexed SSH connection).
#
# Environment variables (all have defaults):
#   REXEC_HOST      ssh target, default vps-2g
#   REXEC_MAC       this machine's identity on the server, derived from ComputerName + hardware UUID
#   REXEC_WS        local workspace, default ~/rexec-workspace
#   REXEC_POLL      poll interval in seconds, default 2
#   REXEC_CPU_MAX   CPU ceiling %; above it no new heavy job is claimed, default 80
#   REXEC_MEM_MIN   free memory floor %; below it no new heavy job is claimed, default 20
#   REXEC_CPU_RELAX below this CPU level the claim cooldown is ignored, default CPU_MAX/2 (i.e. 40)
#   REXEC_COOLDOWN  claim cooldown in seconds (only applies when CPU sits in RELAX..CPU_MAX), default 15
#   REXEC_LOG       write the terminal log to this file (opened in append mode internally; do not use a shell > redirect)
set -u
HOST="${REXEC_HOST:-vps-2g}"
WS="${REXEC_WS:-$HOME/rexec-workspace}"
POLL="${REXEC_POLL:-2}"
CPU_MAX="${REXEC_CPU_MAX:-80}"
MEM_MIN="${REXEC_MEM_MIN:-20}"
COOLDOWN="${REXEC_COOLDOWN:-15}"
CPU_RELAX="${REXEC_CPU_RELAX:-$(( ${REXEC_CPU_MAX:-80} / 2 ))}"

# Use REXEC_LOG for a log file rather than a shell `>` redirect:
#  - redirected to a file, bash's stdout is block-buffered, so log lines sit in the buffer instead of landing on disk;
#  - several children sharing one non-append fd each track their own offset, producing NUL holes and out-of-order lines.
# So in this mode say() appends line by line with `>>`: one open/write/close per line, immediately visible and atomic.
# stderr is unbuffered, so redirecting it directly is fine.
if [ -n "${REXEC_LOG:-}" ]; then exec 2>>"$REXEC_LOG"; fi

RD="$HOME/.rexec"
JOBS="$RD/jobs"
mkdir -p "$WS" "$RD" "$JOBS"

# Single instance: two agents fight over the queue, each claiming half the jobs and logging separately, which is brutal to diagnose.
# The install command is idempotent and users re-run it often, so this has to be blocked here.
PIDF="$RD/agent.pid"
if [ -f "$PIDF" ]; then
  OLD=$(cat "$PIDF" 2>/dev/null)
  case "$OLD" in ''|*[!0-9]*) OLD=0;; esac
  if [ "$OLD" -gt 0 ] && kill -0 "$OLD" 2>/dev/null; then
    echo "A rexec-agent is already running (pid $OLD); not starting another." >&2
    echo "To restart: press Ctrl-C in that terminal, or run  kill $OLD" >&2
    exit 1
  fi
fi
echo $$ > "$PIDF"

rm -f "$JOBS"/* 2>/dev/null

CP="$RD/cm-%C"
BASE="-T -o ControlPath=$CP -o ConnectTimeout=10 -o ServerAliveInterval=15 -o ServerAliveCountMax=3"
SSH_OPTS="$BASE -o ControlMaster=no"
SSH="ssh $SSH_OPTS $HOST"
RSH="ssh $SSH_OPTS"

b64()  { openssl base64 -A; }
b64d() { openssl base64 -d -A; }

# ---------- machine identity ----------
# Several macs share one VPS, and the server gives each its own queue keyed by MACID.
# The name comes from ComputerName (recognisable), the suffix from a hash of the hardware UUID (so two identically named machines never collide).
if [ -n "${REXEC_MAC:-}" ]; then
  MACID=$(printf '%s' "$REXEC_MAC" | tr 'A-Z' 'a-z' | tr -c 'a-z0-9_.-' '-')
else
  MACNAME=$(scutil --get ComputerName 2>/dev/null || hostname -s 2>/dev/null || echo mac)
  MACUUID=$(ioreg -rd1 -c IOPlatformExpertDevice 2>/dev/null | awk -F'"' '/IOPlatformUUID/{print $4}')
  [ -n "$MACUUID" ] || MACUUID=$(hostname 2>/dev/null || echo unknown)
  SHORT=$(printf '%s' "$MACNAME" | tr 'A-Z' 'a-z' | tr -c 'a-z0-9_.-' '-' \
          | sed 's/-\{1,\}/-/g; s/^-//; s/-$//' | cut -c1-12)
  [ -n "$SHORT" ] || SHORT=mac
  MACID="$SHORT-$(printf '%s' "$MACUUID" | openssl md5 | sed 's/.*[= ]//' | cut -c1-4)"
fi
LABEL="${MACNAME:-$MACID}"
# What this agent version can do. The server refuses a job whose flag is missing here, rather than
# running it with the flag silently dropped.
CAPS="git"


# ---------- log format: TIME(8) EVENT(6) ID(15) sigil DETAIL ----------
# $ introduces a command (free text, always last on the line); | separates fixed-width data. A pipe inside a command therefore never clashes with the separator.
# Colour only on a real terminal: ANSI adds no character width and does not break alignment, and the log file stays clean plain text.
if [ -t 1 ] && [ -z "${REXEC_LOG:-}" ]; then
  C_G=$'\033[32m'; C_R=$'\033[31m'; C_Y=$'\033[33m'; C_D=$'\033[90m'; C_0=$'\033[0m'
else
  C_G=''; C_R=''; C_Y=''; C_D=''; C_0=''
fi
out() { # one log line; in REXEC_LOG mode appends line by line, bypassing bash's block buffering
  if [ -n "${REXEC_LOG:-}" ]; then printf '%s\n' "$1" >> "$REXEC_LOG"; else printf '%s\n' "$1"; fi
}
say() { # EVENT ID SEP DETAIL
  case "$1" in
    OK)        c="$C_G";;
    FAIL)      c="$C_R";;
    CANCEL)    c="$C_Y";;
    GATE|SYNC) c="$C_D";;
    *)         c='';;
  esac
  out "$(printf '%s  %s%s%s  %s %s %s' \
    "$(date +%H:%M:%S)" "$c" "$(printf '%-6s' "$1")" "$C_0" \
    "$(printf '%-15s' "$2")" "$3" "$4")"
}
fmt_dur() {
  s=${1:-0}; case "$s" in ''|*[!0-9]*) s=0;; esac
  if [ "$s" -lt 60 ]; then printf '%ds' "$s"; else printf '%dm%02ds' $((s/60)) $((s%60)); fi
}

# ---------- job body (a separate file to avoid nested quoting; exec'd after perl setpgrp) ----------
cat > "$RD/runner.sh" <<'RUNNER_EOF'
#!/bin/bash
# Reached via exec after perl setpgrp(0,0), so $$ is this job's process group ID.
# The whole tree (rsync included) sits in that group, so a cancel kills it cleanly and can never reach the agent itself.
set -u
echo $$ > "$J_JOBS/$J_ID.pgid"
if [ "$J_SYNC" != "-" ]; then
  : > "$J_JOBS/$J_ID.syncing"
  mkdir -p "$J_RUNDIR" || exit 91
  echo "[sync] $J_HOST:$J_SYNC/ -> $J_RUNDIR/"
  # .git is excluded by default (history is dead weight for a build) and pulled only on --with-git.
  # rsync leaves excluded paths on the receiver alone, so a workspace's own disposable .git survives the
  # default mode and is overwritten by the server's history the moment --with-git is used.
  GITEX="--exclude=.git/"; [ "${J_GIT:-0}" = 1 ] && GITEX=""
  rsync -az --delete -e "$J_RSH" \
    $GITEX --exclude 'node_modules/' --exclude '.venv/' --exclude 'venv/' \
    --exclude '__pycache__/' --exclude '.mypy_cache/' --exclude '.pytest_cache/' \
    --exclude 'target/' --exclude 'dist/' --exclude 'build/' --exclude '.next/' \
    --filter=':- .gitignore' \
    "$J_HOST:$J_SYNC/" "$J_RUNDIR/"
  rc=$?
  rm -f "$J_JOBS/$J_ID.syncing"
  [ $rc -ne 0 ] && { echo "[sync] rsync failed rc=$rc"; exit 90; }
else
  mkdir -p "$J_RUNDIR" || exit 91
fi
DIR="$J_RUNDIR"
[ -n "$J_SUB" ] && DIR="$J_RUNDIR/$J_SUB"
cd "$DIR" 2>/dev/null || { echo "directory does not exist: $DIR"; exit 91; }
exec /bin/bash -lc "$J_CMD"
RUNNER_EOF
chmod +x "$RD/runner.sh"

# ---------- load sampling: a background sampler writes a cache every 5s; the main loop only reads it, so polling never blocks ----------
NCPU=$(sysctl -n hw.ncpu 2>/dev/null || echo 4)
printf '50' > "$RD/cpu"; printf '50' > "$RD/mem"
AGENT_PID=$$
(
  trap '' INT TERM
  while kill -0 "$AGENT_PID" 2>/dev/null; do
    # only the second sample of top -l 2 is a true instantaneous value; it is the one accurate CPU reading, hence the background sampler
    c=$(top -l 2 -n 0 -s 1 2>/dev/null | awk '/CPU usage/{idle=$(NF-1)} END{gsub("%","",idle); if(idle=="") print 50; else printf "%.0f", 100-idle}')
    [ -n "$c" ] && { printf '%s' "$c" > "$RD/cpu.tmp" && mv "$RD/cpu.tmp" "$RD/cpu"; }
    # macOS fills memory with cache by design, so "used memory" is always 90%+; only memory_pressure reflects real pressure
    m=$(memory_pressure 2>/dev/null | awk '/free percentage/{gsub("%","",$NF); print $NF}' | tail -1)
    [ -z "$m" ] && m=50
    printf '%s' "$m" > "$RD/mem.tmp" && mv "$RD/mem.tmp" "$RD/mem"
    sleep 5
  done
) </dev/null >/dev/null 2>&1 &
SAMPLER_PID=$!

# ---------- shutdown ----------
STOPPING=0
running_ids() { for m in "$JOBS"/*.meta; do [ -e "$m" ] || break; basename "$m" .meta; done; }
pgid_of()     { cat "$JOBS/$1.pgid" 2>/dev/null; }
kill_job() {
  p=$(pgid_of "$1")
  [ -n "$p" ] && { kill -TERM -"$p" 2>/dev/null; sleep 1; kill -KILL -"$p" 2>/dev/null; }
}
stop_agent() {
  if [ "$STOPPING" = 1 ]; then echo; echo "forced exit"; exit 130; fi
  STOPPING=1; echo
  kill "$SAMPLER_PID" 2>/dev/null
  for id in $(running_ids); do
    kill_job "$id"
    st=$(sed -n 's/^START=//p' "$JOBS/$id.meta" 2>/dev/null || echo 0)
    case "$st" in ''|*[!0-9]*) st=$(date +%s);; esac
    # each one must be reported, or those sessions wait until they time out
    tail -c 400000 "$RD/$id.log" 2>/dev/null | b64 \
      | ssh $SSH_OPTS "$HOST" /var/lib/rexec/bin/rexec-report "$MACID" "$id" 130 $(( $(date +%s) - st )) >/dev/null 2>&1
    say CANCEL "$id" '|' "agent stopped"
  done
  ssh $BASE -O exit "$HOST" >/dev/null 2>&1
  rm -f "$PIDF"
  out "rexec-agent stopped"
  exit 130
}
trap stop_agent INT TERM

# ---------- connection ----------
out "rexec-agent  $MACID  ->  $HOST  $WS"
ssh $BASE -M -f -N "$HOST" </dev/null >/dev/null 2>&1
if ! ssh $SSH_OPTS -o BatchMode=yes "$HOST" true 2>/tmp/rexec-sshtest.$$; then
  echo "Cannot connect to '$HOST' with key-based auth:" >&2
  sed 's/^/    /' /tmp/rexec-sshtest.$$ >&2
  cat >&2 <<'MSG'
  Troubleshooting:
    1) verify by hand:  ssh -o BatchMode=yes vps-2g true && echo OK
    2) key has a passphrase:  ssh-add --apple-use-keychain ~/.ssh/my-vps_ed25519
    3) different alias or key:  REXEC_HOST=your-alias bash ~/rexec-agent.sh
MSG
  rm -f /tmp/rexec-sshtest.$$; kill "$SAMPLER_PID" 2>/dev/null; exit 1
fi
rm -f /tmp/rexec-sshtest.$$

# Register the identity: the server builds a dedicated queue from it and records this machine's source IP for automatic routing
if ! $SSH -n "/var/lib/rexec/bin/rexec-announce $MACID $(printf '%s' "$LABEL" | b64) $CAPS" >/dev/null 2>&1; then
  echo "Registration failed: the server-side rexec may be an old version. Re-run the install on the VPS:" >&2
  echo "  bash /home/agent/.claude/skills/rexec/install.sh" >&2
  kill "$SAMPLER_PID" 2>/dev/null; rm -f "$PIDF"; exit 1
fi

out "polling every ${POLL}s, ctrl-c to stop"
out ""

LAST_CLAIM=0
GATE_STATE=init

while true; do
  NOW=$(date +%s)
  CPU=$(cat "$RD/cpu" 2>/dev/null || echo 50); case "$CPU" in ''|*[!0-9]*) CPU=50;; esac
  MEM=$(cat "$RD/mem" 2>/dev/null || echo 50); case "$MEM" in ''|*[!0-9]*) MEM=50;; esac

  # ---- 1. reap finished jobs ----
  for m in "$JOBS"/*.meta; do
    [ -e "$m" ] || break
    id=$(basename "$m" .meta)
    st=$(sed -n 's/^START=//p'   "$m"); case "$st" in ''|*[!0-9]*) st=$NOW;; esac
    tmo=$(sed -n 's/^TIMEOUT=//p' "$m"); case "$tmo" in ''|*[!0-9]*) tmo=900;; esac
    el=$(( NOW - st ))

    if [ -f "$JOBS/$id.exit" ]; then
      ex=$(cat "$JOBS/$id.exit"); case "$ex" in ''|*[!0-9]*) ex=1;; esac
      # 143/137 from a kill carry no information; map them to the semantic codes the caller expects
      [ -f "$JOBS/$id.timedout"  ] && ex=124
      [ -f "$JOBS/$id.cancelled" ] && ex=125
      tail -c 400000 "$RD/$id.log" 2>/dev/null | b64 \
        | $SSH /var/lib/rexec/bin/rexec-report "$MACID" "$id" "$ex" "$el" >/dev/null 2>&1
      qd=$(sed -n 's/^QUEUED=//p' "$m"); case "$qd" in ''|*[!0-9]*) qd=0;; esac
      det="$(printf '%-8s' "exit $ex") | $(printf '%-13s' "queued $(fmt_dur "$qd")") | ran $(fmt_dur "$el")"
      case "$ex" in
        0)   say OK     "$id" '|' "$det";;
        125) say CANCEL "$id" '|' "$det";;
        *)   say FAIL   "$id" '|' "$det";;
      esac
      rm -f "$JOBS/$id".*
      continue
    fi

    # only speak up once a sync passes 5s, otherwise the first sync of a big project looks like a hang
    if [ -f "$JOBS/$id.syncing" ] && [ ! -f "$JOBS/$id.syncnoted" ] && [ "$el" -ge 5 ]; then
      : > "$JOBS/$id.syncnoted"; say SYNC "$id" '|' "${el}s elapsed"
    fi
    if [ "$el" -ge "$tmo" ] && [ ! -f "$JOBS/$id.cancelled" ] && [ ! -f "$JOBS/$id.timedout" ]; then
      : > "$JOBS/$id.timedout"
      echo "[rexec-agent] timed out after ${tmo}s, terminating" >> "$RD/$id.log"
      kill_job "$id"
    fi
  done

  NRUN=0; for m in "$JOBS"/*.meta; do [ -e "$m" ] && NRUN=$((NRUN+1)); done

  # ---- 2. gate: CPU and memory both guard; either one over the limit stops heavy claims ----
  if [ "$CPU" -le "$CPU_MAX" ] && [ "$MEM" -ge "$MEM_MIN" ]; then GATE=open; else GATE=closed; fi
  if [ "$GATE" != "$GATE_STATE" ] && [ "$GATE_STATE" != init ]; then
    if [ "$GATE" = open ]; then say GATE open   '|' "cpu ${CPU}% | mem ${MEM}%"
    else                        say GATE closed '|' "cpu ${CPU}% | mem ${MEM}%"; fi
  fi
  GATE_STATE="$GATE"

  # Whether another heavy job can be taken. CPU is a lagging indicator: claiming again before the last claim shows up in the reading overshoots;
  # but on a clearly idle machine that worry does not hold - one new job cannot push 12 cores from 15% past 80%.
  # Hence three bands, and only the middle one pays the cooldown:
  #   CPU < RELAX        let it through - the normal path for cross-project parallelism, which must not idle through a cooldown
  #   RELAX..CPU_MAX     wait out the cooldown before claiming again
  #   CPU > CPU_MAX      gate closed, every heavy job waits
  HEAVY_OK=0
  if [ "$GATE" = open ]; then
    if   [ "$CPU" -lt "$CPU_RELAX" ];                    then HEAVY_OK=1
    elif [ $(( NOW - LAST_CLAIM )) -ge "$COOLDOWN" ];    then HEAVY_OK=1
    fi
  fi
  WANT=1

  # ---- 3. one ssh round trip: refresh heartbeat + fetch cancel list + optionally claim ----
  PAYLOAD=$($SSH -n "/var/lib/rexec/bin/rexec-claim $MACID $WANT $GATE $NRUN ${CPU}% ${MEM}% $HEAVY_OK" 2>/dev/null)
  if [ -z "$PAYLOAD" ]; then
    say WARN "-" '|' "connection lost, retrying in 5s"; sleep 5; continue
  fi
  CANCELS=$(printf '%s\n' "$PAYLOAD" | sed -n '1s/^CANCEL=//p')
  BODY=$(printf '%s\n'   "$PAYLOAD" | sed '1d')

  # ---- 4. handle cancels: kill only that job's process group; neighbours and the agent are untouched ----
  for cid in $CANCELS; do
    if [ -f "$JOBS/$cid.meta" ] && [ ! -f "$JOBS/$cid.cancelled" ]; then
      : > "$JOBS/$cid.cancelled"
      echo "[rexec-agent] cancel requested" >> "$RD/$cid.log"
      kill_job "$cid"
    fi
  done

  # ---- 5. start a new job ----
  if [ -n "$BODY" ] && [ "$BODY" != NONE ]; then
    ID=$(printf     '%s\n' "$BODY" | sed -n 's/^ID=//p')
    CMD=$(printf    '%s\n' "$BODY" | sed -n 's/^CMD=//p'     | b64d)
    SYNC=$(printf   '%s\n' "$BODY" | sed -n 's/^SYNC=//p'    | b64d)
    SUB=$(printf    '%s\n' "$BODY" | sed -n 's/^SUBCWD=//p'  | b64d)
    TMO=$(printf    '%s\n' "$BODY" | sed -n 's/^TIMEOUT=//p')
    PROJ=$(printf   '%s\n' "$BODY" | sed -n 's/^PROJECT=//p')
    SUBMIT=$(printf '%s\n' "$BODY" | sed -n 's/^SUBMIT=//p')
    WEIGHT=$(printf '%s\n' "$BODY" | sed -n 's/^WEIGHT=//p')
    WGIT=$(printf   '%s\n' "$BODY" | sed -n 's/^WITHGIT=//p')
    case "$WGIT" in 1) ;; *) WGIT=0;; esac
    case "$TMO"    in ''|*[!0-9]*) TMO=900;; esac
    case "$SUBMIT" in ''|*[!0-9]*) SUBMIT=$NOW;; esac

    if [ "$PROJ" = "__nosync__" ]; then
      RUNDIR="$WS/_nosync"
    else
      RUNDIR="$WS/$PROJ"
      # Migrate the old layout (it named directories by basename, so same-named different projects rsync --delete each other's files).
      # OLD must be a real subdirectory of the workspace: basename "/" yields "/", which degrades OLD into $WS itself,
      # turning this into "move the whole workspace into its own subdirectory". That is exactly how the old version synced the VPS root in.
      OLDBASE=$(basename "$SYNC")
      case "$OLDBASE" in
        ''|'/'|'.'|'..') ;;
        *) OLD="$WS/$OLDBASE"
           [ -d "$OLD" ] && [ ! -d "$RUNDIR" ] && mv "$OLD" "$RUNDIR" 2>/dev/null;;
      esac
    fi

    : > "$RD/$ID.log"
    (
      J_ID="$ID" J_CMD="$CMD" J_SYNC="$SYNC" J_SUB="$SUB" J_GIT="$WGIT" \
      J_RUNDIR="$RUNDIR" J_HOST="$HOST" J_RSH="$RSH" J_JOBS="$JOBS" \
      perl -e 'setpgrp(0,0); exec @ARGV or die "exec failed: $!"' -- \
           /bin/bash "$RD/runner.sh" >> "$RD/$ID.log" 2>&1
      # This wrapper deliberately stays in the agent's process group: kill -PGID cannot reach it, so the exit code survives
      echo $? > "$JOBS/$ID.exit.tmp" && mv "$JOBS/$ID.exit.tmp" "$JOBS/$ID.exit"
    ) </dev/null >/dev/null 2>&1 &

    printf 'START=%s\nTIMEOUT=%s\nPROJECT=%s\nQUEUED=%s\n' \
      "$NOW" "$TMO" "$PROJ" "$(( NOW - SUBMIT ))" > "$JOBS/$ID.meta"
    # only heavy jobs trigger the cooldown: a zero-cost probe should not stall the next heavy job for 25s
    [ "$WEIGHT" != light ] && LAST_CLAIM="$NOW"
    say RUN "$ID" '$' "$CMD"
  fi

  sleep "$POLL"
done
