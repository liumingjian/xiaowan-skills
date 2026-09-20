#!/usr/bin/env bash
# Scheduler and caller-heartbeat tests for the rexec server side.
#
# Run it straight from a checkout:  bash skills/misc/rexec/tests/queue-test.sh
#
# This is the one part of rexec worth asserting on, because a broken scheduler does not fail - it quietly
# stops moving, which is indistinguishable from "the mac is busy" until someone reads the queue by hand.
#
# Exception to the global "run everything on the mac" rule, deliberately: the subject under test *is* the
# server side, the whole suite is file operations against a REXEC_ROOT sandbox in /tmp, and it finishes in
# a couple of seconds with no compiler, no network and no mac involved.
set -u
SRV=$(cd "$(dirname "$(readlink -f "$0")")/../server" && pwd -P)
export REXEC_ROOT=$(mktemp -d /tmp/rexec-test.XXXXXX)
MAC=testmac
M="$REXEC_ROOT/macs/$MAC"
PASS=0; FAIL=0

ok()   { PASS=$((PASS+1)); printf '  ok    %s\n' "$1"; }
bad()  { FAIL=$((FAIL+1)); printf '  FAIL  %s\n     expected: %s\n     actual:   %s\n' "$1" "$2" "$3"; }
is()   { [ "$2" = "$3" ] && ok "$1" || bad "$1" "$2" "$3"; }

reset() { # start every case from an empty queue on one mac
  rm -rf "$REXEC_ROOT/macs"
  mkdir -p "$M/queue" "$M/running" "$M/results" "$M/cancel" "$M/alive"
}

submit() { # ID PROJECT [weight] [submit-epoch]
  _id=$1; _proj=$2; _w=${3:-normal}; _t=${4:-$(date +%s)}
  printf 'ID=%s\nCMD=%s\nSYNC=%s\nSUBCWD=\nTIMEOUT=900\nWEIGHT=%s\nWITHGIT=0\nPROJECT=%s\nSUBMIT=%s\nSEQ=%s\n' \
    "$_id" "$(printf 'true' | openssl base64 -A)" "$(printf '/tmp' | openssl base64 -A)" \
    "$_w" "$_proj" "$_t" "${_id##*-}" > "$M/queue/$_id.job"
  beat "$_id"
}

start()   { mv "$M/queue/$1.job" "$M/running/$1.job"; date +%s > "$M/running/$1.started"; }
beat()    { date +%s > "$M/alive/$1"; }                       # a caller that is still waiting
stale()   { printf '%s' $(( $(date +%s) - 600 )) > "$M/alive/$1"; }  # a caller killed 10 minutes ago
nobeat()  { rm -f "$M/alive/$1"; }                            # a client that predates heartbeats

# claim [WANT] [NRUN] [HEAVY_OK] [RIDS] [DIDS] -> the ID it picked, or NONE
# An omitted DIDS is how an agent that predates --detach calls in: it sends no detached list at all.
claim_raw() { "$SRV/rexec-claim" "$MAC" "${1:-1}" open "${2:-0}" 10% 80% "${3:-1}" "${4:--}" "${5-}" 2>/dev/null; }
claim()     { claim_raw "$@" | sed -n 's/^ID=//p' | head -1; }
picked()  { p=$(claim "$@"); [ -n "$p" ] || p=NONE; printf '%s' "$p"; }

echo "rexec scheduler tests  ($REXEC_ROOT)"

echo "- head-of-line blocking"
reset
submit proj_a-0001 proj_a; start proj_a-0001
submit proj_a-0002 proj_a
submit proj_b-0003 proj_b
is "another project runs past a blocked queue head" proj_b-0003 "$(picked 1 1 1 proj_a-0001)"

reset
submit proj_a-0001 proj_a; start proj_a-0001
submit proj_a-0002 proj_a
is "the blocked project itself still waits" NONE "$(picked 1 1 1 proj_a-0001)"

reset
submit proj_a-0002 proj_a 'normal' $(( $(date +%s) - 10 ))
submit proj_a-0003 proj_a
is "within one project the earlier job goes first" proj_a-0002 "$(picked)"

reset
submit proj_a-0001 proj_a
submit probe-0002 __nosync__ light
is "a light job runs past a gate-held heavy one" probe-0002 "$(picked 1 1 0)"

reset
submit proj_a-0001 proj_a
is "the gate never stalls an idle mac" proj_a-0001 "$(picked 1 0 0)"

echo "- callers that never come back"
reset
submit proj_a-0001 proj_a; stale proj_a-0001
submit proj_b-0002 proj_b
is "an abandoned queued job is not claimed" proj_b-0002 "$(picked)"
is "...and is dropped from the queue"        ""            "$(ls "$M/queue" | grep proj_a-0001 || true)"

reset
submit proj_a-0001 proj_a; nobeat proj_a-0001
is "a job from a pre-heartbeat client is left alone" proj_a-0001 "$(picked)"

reset
submit proj_a-0001 proj_a; start proj_a-0001; stale proj_a-0001
claim_raw 0 1 1 proj_a-0001 >/dev/null
is "an abandoned running job is cancelled" "" "$(ls "$M/cancel" | grep -v proj_a-0001 || true)"
is "...and the cancel reaches the agent" "CANCEL=proj_a-0001" "$(claim_raw 0 1 1 proj_a-0001 | head -1)"

reset
submit proj_a-0001 proj_a; start proj_a-0001; beat proj_a-0001
claim_raw 0 1 1 proj_a-0001 >/dev/null
is "a long job with a live caller is left running" "CANCEL=" "$(claim_raw 0 1 1 proj_a-0001 | head -1)"

echo "- restarting the agent unsticks the queue"
# The reported symptom: a job whose caller died, plus a stale running entry, survived every restart.
reset
submit proj_a-0001 proj_a; start proj_a-0001; stale proj_a-0001   # left running by a dead agent
submit proj_a-0002 proj_a; stale proj_a-0002                      # queued, caller long gone
submit proj_a-0003 proj_a                                         # queued, caller still waiting
"$SRV/rexec-announce" "$MAC" "$(printf 'Test Mac' | openssl base64 -A)" git,reap >/dev/null 2>&1
is "restart reaps the stale running entry" "" "$(ls "$M/running" | grep proj_a-0001 || true)"
is "the live caller's job then runs"       proj_a-0003 "$(picked)"

echo "- detached jobs"
detach() { # ID PROJECT [pgid] - submit it, claim it, and hand it off to detached/
  submit "$1" "$2"; start "$1"
  "$SRV/rexec-detached" start "$MAC" "$1" "${3:-99999}" boot1 "$(printf '/log' | openssl base64 -A)" >/dev/null
  rm -f "$M/running/$1.job" "$M/running/$1.started" "$M/alive/$1"   # what reporting the launch does
}

reset
detach proj_a-0001 proj_a
submit proj_a-0002 proj_a
submit proj_b-0003 proj_b
is "a detached job still holds its project's workspace" proj_b-0003 "$(picked 1 1 1 - )"
is "...so its own project keeps waiting"                 ""          "$(ls "$M/running" | grep proj_a-0002 || true)"

reset
detach proj_a-0001 proj_a
printf 'EXIT=0\nRAN=5\nEND=%s\n' "$(date +%s)" > "$M/detached/proj_a-0001.done"
submit proj_a-0002 proj_a
is "a finished detached job releases the slot" proj_a-0002 "$(picked)"

reset
detach proj_a-0001 proj_a
claim_raw 0 1 1 - proj_a-0001 >/dev/null
is "a detached job the agent still sees is left alone" "" "$(ls "$M/detached" | grep '\.done' || true)"

reset
detach proj_a-0001 proj_a
claim_raw 0 0 1 - - >/dev/null
is "a detached job the agent cannot see any more is reaped" 129 \
   "$(sed -n 's/^EXIT=//p' "$M/detached/proj_a-0001.done" 2>/dev/null)"

reset
detach proj_a-0001 proj_a
claim_raw 0 0 1 - >/dev/null
is "an agent that predates --detach reaps nothing" "" \
   "$(sed -n 's/^EXIT=//p' "$M/detached/proj_a-0001.done" 2>/dev/null)"

reset
detach proj_a-0001 proj_a
"$SRV/rexec-cancel" proj_a-0001 >/dev/null 2>&1
is "a detached job can still be cancelled explicitly" proj_a-0001 "$(ls "$M/cancel")"

reset
detach proj_a-0001 proj_a
printf 'built ok' | openssl base64 -A | "$SRV/rexec-detached" done "$MAC" proj_a-0001 0 42 >/dev/null
is "the job reports its own result" 0        "$(sed -n 's/^EXIT=//p' "$M/detached/proj_a-0001.done")"
is "...with its log"                'built ok' "$(cat "$M/detached/proj_a-0001.out")"
printf 'later' | openssl base64 -A | "$SRV/rexec-detached" done "$MAC" proj_a-0001 9 99 >/dev/null
is "...and a second report is ignored" 0     "$(sed -n 's/^EXIT=//p' "$M/detached/proj_a-0001.done")"
is "a finished job leaves the active list"  "" "$("$SRV/rexec-detached" list "$MAC")"

printf '\n%s passed, %s failed\n' "$PASS" "$FAIL"
rm -rf "$REXEC_ROOT"
[ "$FAIL" = 0 ]
