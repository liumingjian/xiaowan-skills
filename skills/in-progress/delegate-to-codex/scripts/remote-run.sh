#!/usr/bin/env bash
set -euo pipefail
umask 077

mode="${1:-}"
prompt_rel="${2:-}"
model="${3:-}"
resume_id="${4:-}"
effort="${5:-}"

case "$mode" in
  consult|implement) ;;
  *) printf 'invalid delegate mode\n' >&2; exit 64 ;;
esac
[[ -f "$prompt_rel" && -s "$prompt_rel" ]] || {
  printf 'handoff not found in the frozen workspace\n' >&2
  exit 65
}
[[ -n "${REXEC_ARTIFACTS:-}" && -d "$REXEC_ARTIFACTS" && ! -L "$REXEC_ARTIFACTS" ]] || {
  printf 'dedicated artifact directory unavailable\n' >&2
  exit 70
}
command -v python3 >/dev/null 2>&1 || { printf 'python3 unavailable\n' >&2; exit 66; }
codex_bin="$(command -v codex || true)"
[[ -n "$codex_bin" && -x "$codex_bin" ]] || {
  printf 'codex CLI unavailable on the paired Mac mini\n' >&2
  exit 66
}

private_out="$(mktemp -d "${TMPDIR:?}/delegate-private.XXXXXXXX")"
out="$REXEC_ARTIFACTS"
for artifact in response.md changes.patch status.json; do
  [[ ! -e "$out/$artifact" && ! -L "$out/$artifact" ]] || exit 70
done

if [[ "$mode" == "implement" ]]; then
  if [[ ! -e .git ]]; then
    git init -q
  fi
  git -c core.hooksPath=/dev/null -c commit.gpgsign=false \
    -c user.name='Codex Delegate' -c user.email='codex-delegate@localhost' add -A
  git -c core.hooksPath=/dev/null -c commit.gpgsign=false \
    -c user.name='Codex Delegate' -c user.email='codex-delegate@localhost' \
    commit -qm baseline --allow-empty
fi

prompt="$private_out/full-prompt.md"
case "$mode" in
  consult)
    cat >"$prompt" <<'PROMPT'
You are the second-opinion engineer, working in a synced copy of the project. Read only; the sandbox
blocks writes. Inspect every relevant file before deciding, ground the recommendation in repository
evidence, name the strongest alternative, and state where your confidence ends. Match depth to the
decision. The handoff follows.

--- HANDOFF ---
PROMPT
    sandbox="read-only"
    ;;
  implement)
    cat >"$prompt" <<'PROMPT'
You are the implementation engineer, working in a synced copy of the project. Edit files here and run
commands to check your own work; the sandbox has no network, so dependencies must already be available.
Implement the smallest complete solution, preserve unrelated behavior, and end with the exact checks
the caller should rerun plus remaining risks. Your test runs help you converge; the caller verifies the
accepted patch independently. The handoff follows.

--- HANDOFF ---
PROMPT
    sandbox="workspace-write"
    ;;
esac
cat "$prompt_rel" >>"$prompt"

codex_args=(exec)
[[ -z "$resume_id" ]] || codex_args+=(resume)
# Resume uses the process cwd; sandbox settings go through configuration for both modes.
codex_args+=(
  -c "sandbox_mode=$sandbox"
  --json
  --skip-git-repo-check
  -o "$out/response.md"
)
[[ -z "$model" ]] || codex_args+=(-m "$model")
[[ -z "$effort" ]] || codex_args+=(-c "model_reasoning_effort=$effort")
[[ -z "$resume_id" ]] || codex_args+=("$resume_id")
codex_args+=(-)

set +e
python3 - "$private_out" "$prompt" "$codex_bin" "${codex_args[@]}" <<'RUN'
import pathlib, subprocess, sys, threading
private = pathlib.Path(sys.argv[1])
limit = 4 * 1024 * 1024
marker = b"\n[delegate log truncated]\n"

def drain(pipe, path):
    remaining = limit - len(marker)
    truncated = False
    with path.open("xb") as destination:
        while block := pipe.read(65536):
            kept = min(len(block), remaining)
            destination.write(block[:kept])
            remaining -= kept
            if kept < len(block) and not truncated:
                destination.write(marker)
                truncated = True
    pipe.close()

with open(sys.argv[2], "rb") as prompt:
    process = subprocess.Popen(sys.argv[3:], stdin=prompt, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    readers = [threading.Thread(target=drain, args=(pipe, private / name))
               for pipe, name in ((process.stdout, "codex.jsonl"), (process.stderr, "codex.stderr"))]
    for reader in readers:
        reader.start()
    status = process.wait()
    for reader in readers:
        reader.join()
sys.exit(status if status >= 0 else 128 - status)
RUN
codex_status=$?
set -e

[[ -f "$out/response.md" ]] || : >"$out/response.md"
: >"$out/changes.patch"
if [[ "$mode" == "implement" ]]; then
  git -c core.hooksPath=/dev/null add -A
  git diff --cached --binary --no-ext-diff --no-textconv >"$out/changes.patch"
fi

python3 - "$private_out/codex.jsonl" "$out/status.json" "$codex_status" <<'PY'
import json, re, sys
thread = None
with open(sys.argv[1], encoding="utf-8", errors="replace") as events:
    for line in events:
        try:
            event = json.loads(line)
        except ValueError:
            continue
        candidate = event.get("thread_id") if isinstance(event, dict) else None
        if isinstance(candidate, str) and re.fullmatch(r"[A-Za-z0-9_-]{1,128}", candidate):
            thread = candidate
            break
with open(sys.argv[2], "x", encoding="utf-8") as destination:
    json.dump({"status": int(sys.argv[3]), "thread_id": thread}, destination)
    destination.write("\n")
PY
exit "$codex_status"
