#!/usr/bin/env bash
# Workspace naming and cleanup tests: the real agent.sh (which writes gc.sh) against the real server scripts,
# with a fake `ssh` in between. Needs a mac, like agent-test.sh.
#
#   rexec 'bash skills/misc/rexec/tests/gc-test.sh'        # from the repository root
#
# Nothing touches the live setup: the agent gets its own HOME and workspace, the server its own REXEC_ROOT.
set -u
HERE=$(cd "$(dirname "$0")" && pwd -P)
AGENT=$HERE/../agent.sh
export SRV=$(cd "$HERE/../server" && pwd -P)
T=$(mktemp -d /tmp/rexec-gc-test.XXXXXX); T=$(cd "$T" && pwd -P)
export REXEC_ROOT="$T/root" FAKE="$T/fake" REXEC_LEGACY_ROOTS="$T/src"
mkdir -p "$REXEC_ROOT" "$FAKE/bin" "$T/home" "$T/src" "$T/ws"
MAC=testmac; M="$REXEC_ROOT/macs/$MAC"; WS="$T/ws"; WSM="$T/home/.rexec/ws"
PASS=0; FAIL=0
ok()  { PASS=$((PASS+1)); printf '  ok    %s\n' "$1"; }
bad() { FAIL=$((FAIL+1)); printf '  FAIL  %s\n     expected: %s\n     actual:   %s\n' "$1" "$2" "$3"; }
is()  { [ "$2" = "$3" ] && ok "$1" || bad "$1" "$2" "$3"; }
has() { [ -e "$1" ] && echo yes || echo no; }
wait_for() { _n=$(( $1 * 5 )); shift
  while [ "$_n" -gt 0 ]; do "$@" && return 0; sleep 0.2; _n=$((_n-1)); done; return 1; }
. "$SRV/rexec-lib.sh"

# The fake ssh: runs the remote command here, with the server scripts taken from this checkout. rsync's
# own `ssh host rsync --server ...` goes through it too, so syncs and dry runs work against local paths.
cat > "$FAKE/bin/ssh" <<'SSH'
#!/usr/bin/env bash
op=""; master=0
while [ $# -gt 0 ]; do
  case "$1" in -o) shift 2;; -O) op=$2; shift 2;; -M) master=1; shift;; -*) shift;; *) break;; esac
done
shift
[ "${1-}" = -n ] && shift
case "$op" in check) [ -f "$FAKE/master" ]; exit;; exit) rm -f "$FAKE/master"; exit 0;; esac
[ "$master" = 1 ] && { : > "$FAKE/master"; exit 0; }
exec bash -c "$(printf '%s' "$*" | sed "s#/var/lib/rexec/bin/#$SRV/#g")"
SSH
chmod +x "$FAKE/bin/ssh"

run_agent() { # GC_EVERY -> starts the agent in the background, sets APID
  HOME="$T/home" PATH="$FAKE/bin:$PATH" REXEC_HOST=fake REXEC_MAC=$MAC REXEC_WS="$WS" REXEC_POLL=1 \
    REXEC_GC_EVERY="$1" REXEC_LOG="$T/agent.log" bash "$AGENT" >/dev/null 2>&1 &
  APID=$!
}
stop_agent() { kill -TERM "$APID" 2>/dev/null; wait "$APID" 2>/dev/null; }
gc() { HOME="$T/home" PATH="$FAKE/bin:$PATH" bash "$T/home/.rexec/gc.sh" "$1" 2>&1; }
b64() { printf '%s' "$1" | openssl base64 -A; }
ws() { # NAME SRC DAYS_AGO -> a workspace with a record, as the agent leaves one
  mkdir -p "$WS/$1"; printf 'SRC64=%s\nUSED=%s\n' "$(b64 "$2")" $(( $(date +%s) - $3 * 86400 )) > "$WSM/$1"
}
src() { mkdir -p "$T/src/$1"; echo "$1" > "$T/src/$1/a.txt"; printf '%s' "$T/src/$1"; }

echo "rexec workspace tests  ($T)"
echo "  rsync: $(rsync --version 2>&1 | head -1)"

echo "- workspace names"
R="$T/src/myrepo"; mkdir -p "$R/web/app"
git -C "$R" init -q && git -C "$R" -c user.email=t@t -c user.name=t commit -q --allow-empty -m init
git -C "$R" worktree add -q "$T/src/wt-dir/feature-x" 2>/dev/null
ws_key "$R";                      is "a main checkout is named by its repository" "myrepo--$(path_hash6 "$R")" "$WS_NAME"
ws_key "$T/src/wt-dir/feature-x"; is "a worktree carries its repository's name" "myrepo--wt-feature-x--$(path_hash6 "$T/src/wt-dir/feature-x")" "$WS_NAME"
is "...and the ID prefix is the repository" myrepo "$WS_REPO"
ws_key "$R/web/app";              is "a synced subdirectory is named after it" "myrepo--web_app--$(path_hash6 "$R/web/app")" "$WS_NAME"
mkdir -p "$T/src/plain dir"
ws_key "$T/src/plain dir";        is "a directory outside git is named by itself" "plain_dir--$(path_hash6 "$T/src/plain dir")" "$WS_NAME"
rm -rf "$R" "$T/src/wt-dir" "$T/src/plain dir"

# gc.sh is written by the agent at startup; take it from an agent with the hourly run switched off.
run_agent 0
wait_for 20 test -f "$T/home/.rexec/gc.sh"; is "the agent writes gc.sh" 0 "$?"
stop_agent

echo "- what goes and what stays"
ws gone "$T/src/deleted" 0
ws idle "$(src idle)" 8;           echo idle > "$WS/idle/a.txt"; mkdir -p "$WS/idle/node_modules/x"
ws dropped "$(src dropped)" 8;     echo dropped > "$WS/dropped/a.txt"; echo SECRET=1 > "$WS/dropped/.env"
ws built "$(src built)" 8;         echo built > "$WS/built/a.txt"; mkdir -p "$WS/built/coverage"; echo x > "$WS/built/coverage/r.txt"
ws fresh "$(src fresh)" 1
ws running "$T/src/deleted" 0;     mkdir -p "$T/home/.rexec/jobs"; printf 'PROJECT=running\n' > "$T/home/.rexec/jobs/x-0001.meta"
ws queued "$T/src/deleted" 0;      mkdir -p "$M/queue"; printf 'ID=q-0002\nPROJECT=queued\n' > "$M/queue/q-0002.job"
OLDSRC=$(src legacyproj); OLD=$(ws_legacy_key "$OLDSRC"); mkdir -p "$WS/$OLD"; ws_key "$OLDSRC"; NEW=$WS_NAME
mkdir -p "$WS/zzzz-abcdef" "$WS/.echo-cargo-target" "$WS/_nosync"

OUT=$(gc --dry-run)
is "a dry run lists a deleted source"      1 "$(printf '%s\n' "$OUT" | grep -c 'would delete.*gone .*source gone')"
is "...and the legacy rename"              1 "$(printf '%s\n' "$OUT" | grep -c "would rename  $OLD -> $NEW")"
is "...and what rexec did not create"      1 "$(printf '%s\n' "$OUT" | grep -c '\.echo-cargo-target')"
is "...and deletes nothing"                "yes yes yes" "$(has "$WS/gone") $(has "$WS/zzzz-abcdef") $(has "$WS/$OLD")"

OUT=$(gc --auto)
is "a workspace whose source is gone is deleted"            no  "$(has "$WS/gone")"
is "...and says so, with the reason"                        1   "$(printf '%s\n' "$OUT" | grep -c '^deleted .* gone .*source gone')"
is "an idle workspace is deleted"                           no  "$(has "$WS/idle")"
is "an idle one holding a hand-placed file is kept"         yes "$(has "$WS/dropped/.env")"
is "...and reported, naming the file"                       1   "$(printf '%s\n' "$OUT" | grep -c '^kept dropped .*\.env')"
is "build output the server lacks is no reason to keep one" no  "$(has "$WS/built")"
is "a recently used workspace stays"                        yes "$(has "$WS/fresh")"
is "a workspace a job is running in stays"                  yes "$(has "$WS/running")"
is "a workspace with a queued job stays"                    yes "$(has "$WS/queued")"
is "a legacy workspace is renamed"                          "no yes" "$(has "$WS/$OLD") $(has "$WS/$NEW")"
is "...and gets a record"                                   "$OLDSRC" "$(sed -n 's/^SRC64=//p' "$WSM/$NEW" | openssl base64 -d -A)"
is "an unplaceable legacy name waits for --apply"           yes "$(has "$WS/zzzz-abcdef")"
is "the record of a deleted workspace goes with it"         no  "$(has "$WSM/gone")"
is "a kept workspace is reported once, not every hour"      0   "$(gc --auto | grep -c '^kept')"

gc --apply >/dev/null
is "--apply deletes the unplaceable legacy name"            no  "$(has "$WS/zzzz-abcdef")"
is "...but never what rexec did not create"                 "yes yes" "$(has "$WS/.echo-cargo-target") $(has "$WS/_nosync")"
is "nothing is left in the trash"                           no  "$(has "$WS/.rexec-trash")"

echo "- the agent"
rm -rf "$WS"/* "$WSM"/* "$T/home/.rexec/jobs"/* "$M/queue"/*
ws gone2 "$T/src/deleted" 0
# Outside REXEC_LEGACY_ROOTS, so the startup cleanup cannot place it: only the claim can do the renaming.
PSRC="$T/elsewhere/synced"; mkdir -p "$PSRC"; echo synced > "$PSRC/a.txt"; POLD=$(ws_legacy_key "$PSRC"); mkdir -p "$WS/$POLD/node_modules"; ws_key "$PSRC"; PNEW=$WS_NAME
mkdir -p "$M/queue"
printf 'ID=synced-0003\nCMD=%s\nSYNC=%s\nSUBCWD=\nTIMEOUT=900\nWEIGHT=light\nWITHGIT=0\nPROJECT=%s\nSUBMIT=%s\nSEQ=3\n' \
  "$(b64 'cat a.txt')" "$(b64 "$PSRC")" "$PNEW" "$(date +%s)" > "$M/queue/synced-0003.job"
run_agent 3600
logged() { grep -q 'CLEAN.*deleted .*gone2' "$T/agent.log" 2>/dev/null; }
wait_for 20 logged; is "the cleanup at startup logs a CLEAN line" 0 "$?"
done3() { [ -f "$M/results/synced-0003.done" ]; }
wait_for 30 done3
is "a job runs in its workspace"                         synced "$(tail -1 "$M/results/synced-0003.out" 2>/dev/null)"
is "...moved over from the legacy name, deps and all"    "no yes" "$(has "$WS/$POLD") $(has "$WS/$PNEW/node_modules")"
is "...and stamps its record"                            "$PSRC" "$(sed -n 's/^SRC64=//p' "$WSM/$PNEW" | openssl base64 -d -A)"
stop_agent

printf '\n%s passed, %s failed\n' "$PASS" "$FAIL"
[ "$FAIL" = 0 ] || { echo "--- agent log"; tail -30 "$T/agent.log"; }
rm -rf "$T"
[ "$FAIL" = 0 ]
