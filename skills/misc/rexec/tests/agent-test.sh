#!/usr/bin/env bash
# Agent tests: run the real agent.sh against the real server scripts, with a fake `ssh` in between that can
# drop the link on demand. Needs a mac (the agent samples load with top, memory_pressure and sysctl).
#
#   rexec 'bash skills/misc/rexec/tests/agent-test.sh'        # from the repository root
#   bash tests/agent-test.sh path/to/agent.sh                 # against another agent version
#
# Nothing touches the live setup: the agent gets its own HOME (so its own pid file and job records), the
# server side its own REXEC_ROOT, and no real ssh connection is ever made.
set -u
HERE=$(cd "$(dirname "$0")" && pwd -P)
AGENT=${1:-$HERE/../agent.sh}
export SRV=$(cd "$HERE/../server" && pwd -P)
T=$(mktemp -d /tmp/rexec-agent-test.XXXXXX)
export REXEC_ROOT="$T/root" FAKE="$T/fake"
export REXEC_STRAND_GRACE=2          # the server gives up on an unlisted job after 2s instead of 120s
mkdir -p "$REXEC_ROOT" "$FAKE/bin" "$T/home"
MAC=testmac; M="$REXEC_ROOT/macs/$MAC"
PASS=0; FAIL=0
ok()  { PASS=$((PASS+1)); printf '  ok    %s\n' "$1"; }
bad() { FAIL=$((FAIL+1)); printf '  FAIL  %s\n     expected: %s\n     actual:   %s\n' "$1" "$2" "$3"; }
is()  { [ "$2" = "$3" ] && ok "$1" || bad "$1" "$2" "$3"; }
wait_for() { # SECONDS TEST... -> true once the test passes
  _n=$(( $1 * 5 )); shift
  while [ "$_n" -gt 0 ]; do "$@" && return 0; sleep 0.2; _n=$((_n-1)); done; return 1
}

# The fake ssh. `noreport` makes result reports fail the way a dropped link does (exit 255) while polls
# still get through - the mix a flaky link produces, and the one where a lost report used to strand a job.
# The `master` file stands for a live ControlMaster, and every `-M` that brings one up is logged to `masters`.
cat > "$FAKE/bin/ssh" <<'SSH'
#!/usr/bin/env bash
op=""; master=0
while [ $# -gt 0 ]; do
  case "$1" in
    -o) shift 2;; -O) op=$2; shift 2;; -M) master=1; shift;; -*) shift;; *) break;;
  esac
done
shift                                                 # the host
[ "${1-}" = -n ] && shift                             # ssh takes options after the host too
case "$op" in
  check) [ -f "$FAKE/master" ]; exit;;
  exit)  rm -f "$FAKE/master"; exit 0;;
esac
[ "$master" = 1 ] && { : > "$FAKE/master"; echo x >> "$FAKE/masters"; exit 0; }
[ -f "$FAKE/noreport" ] && case "$*" in *rexec-report*) exit 255;; esac
exec bash -c "$(printf '%s' "$*" | sed "s#/var/lib/rexec/bin/#$SRV/#g")"
SSH
chmod +x "$FAKE/bin/ssh"

submit() { # ID COMMAND - a --no-sync job, as the rexec client queues it
  mkdir -p "$M/queue"
  printf 'ID=%s\nCMD=%s\nSYNC=%s\nSUBCWD=\nTIMEOUT=900\nWEIGHT=light\nWITHGIT=0\nPROJECT=__nosync__\nSUBMIT=%s\nSEQ=1\n' \
    "$1" "$(printf '%s' "$2" | openssl base64 -A)" "$(printf '-' | openssl base64 -A)" "$(date +%s)" \
    > "$M/queue/$1.job"
}
exit_of()  { sed -n 's/^EXIT=//p' "$M/results/$1.done" 2>/dev/null; }
reported() { [ -f "$M/results/$1.done" ]; }
warned()   { grep -q "WARN.*$1" "$T/agent.log" 2>/dev/null; }
two_masters() { [ "$(wc -l < "$FAKE/masters" 2>/dev/null)" -ge 2 ]; }

echo "rexec agent tests  ($T, agent: $AGENT)"
mkdir -p "$M"
: > "$FAKE/noreport"
submit nosync-0001 'echo built'
HOME="$T/home" PATH="$FAKE/bin:$PATH" REXEC_HOST=fake REXEC_MAC=$MAC REXEC_WS="$T/ws" REXEC_POLL=1 \
  REXEC_LOG="$T/agent.log" bash "$AGENT" >/dev/null 2>&1 &
APID=$!

echo "- a report that does not reach the server"
wait_for 20 warned nosync-0001; is "the agent says the report is being retried" 0 "$?"
sleep 4                                  # several polls, each well past the server's strand grace
is "a finished job is not reaped as stranded while its report is pending" "" "$(exit_of nosync-0001)"
rm -f "$FAKE/noreport"
wait_for 20 reported nosync-0001
is "...and its real exit code arrives once the link is back" 0 "$(exit_of nosync-0001)"
is "...with its output"   built "$(cat "$M/results/nosync-0001.out" 2>/dev/null)"

echo "- the ControlMaster"
rm -f "$FAKE/master"                     # sshd timed it out
wait_for 10 two_masters; is "a master that died is brought back up" 0 "$?"

kill -TERM "$APID" 2>/dev/null; wait "$APID" 2>/dev/null
printf '\n%s passed, %s failed\n' "$PASS" "$FAIL"
[ "$FAIL" = 0 ] || { echo "--- agent log"; cat "$T/agent.log"; }
rm -rf "$T"
[ "$FAIL" = 0 ]
