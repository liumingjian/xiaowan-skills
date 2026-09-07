#!/usr/bin/env bash
set -euo pipefail

# Runs on the Mac, inside the rexec workspace (cwd). Emits one base64 tarball on stdout.

mode="${1:-}"
prompt_rel="${2:-}"
model="${3:-}"
resume_id="${4:-}"

case "$mode" in
  consult|implement) ;;
  *) printf 'invalid mode: %s\n' "$mode" >&2; exit 64 ;;
esac
[[ -f "$prompt_rel" && -s "$prompt_rel" ]] || {
  printf 'handoff not found in the synced workspace: %s\n' "$prompt_rel" >&2
  exit 65
}

export PATH="$HOME/.local/bin:$PATH"
codex_bin="$(command -v codex || true)"
if [[ -z "$codex_bin" ]]; then
  codex_bin="$(bash -ilc 'command -v codex' 2>/dev/null | tail -n 1)"
fi
[[ -n "$codex_bin" && -x "$codex_bin" ]] || {
  printf 'codex CLI not found on this Mac.\n' >&2
  exit 66
}

out="$(mktemp -d "${TMPDIR:-/tmp}/delegate-to-codex.XXXXXXXX")"
trap 'rm -rf -- "$out"' EXIT

# A baseline to diff Codex's edits against. Only implement mode needs one, and skipping it in consult
# mode leaves real history (synced by `rexec --with-git`) pristine for Codex to review against a base branch.
if [[ "$mode" == "implement" ]]; then
  if [[ ! -d .git ]]; then
    git init -q
  fi
  git config user.name "Codex Delegate"
  git config user.email "codex-delegate@localhost"
  git add -Af
  git commit -qm baseline --allow-empty
fi

prompt="$out/full-prompt.md"
case "$mode" in
  consult)
    cat >"$prompt" <<'EOF'
You are the second-opinion engineer, working in a synced copy of the project. Read only; the sandbox
blocks writes. Inspect every relevant file before deciding, ground the recommendation in repository
evidence, name the strongest alternative, and state where your confidence ends. Match depth to the
decision. The handoff follows.

--- HANDOFF ---
EOF
    sandbox="read-only"
    ;;
  implement)
    cat >"$prompt" <<'EOF'
You are the implementation engineer, working in a synced copy of the project. Edit files here and run
commands to check your own work; the sandbox has no network, so installing dependencies fails and is
not your job. Implement the smallest complete solution, preserve unrelated behaviour, and end with the
exact checks the caller should re-run plus the remaining risks. Your test runs help you converge; they
are not the caller's evidence. The handoff follows.

--- HANDOFF ---
EOF
    sandbox="workspace-write"
    ;;
esac
cat "$prompt_rel" >>"$prompt"

codex_args=(exec)
if [[ -n "$resume_id" ]]; then
  codex_args+=(resume)
fi
# `codex exec resume` takes neither -s nor -C, so the sandbox goes through -c and the
# working directory is simply this process's cwd (the rexec workspace).
codex_args+=(
  -c "sandbox_mode=$sandbox"
  --json
  --skip-git-repo-check
  -o "$out/response.md"
)
if [[ -n "$model" ]]; then
  codex_args+=(-m "$model")
fi
# The session id is positional and must follow the options.
if [[ -n "$resume_id" ]]; then
  codex_args+=("$resume_id")
fi
codex_args+=(-)

set +e
"$codex_bin" "${codex_args[@]}" <"$prompt" >"$out/codex.jsonl" 2>"$out/codex.stderr"
codex_status=$?
set -e

[[ -f "$out/response.md" ]] || : >"$out/response.md"
: >"$out/changes.patch"
if [[ "$mode" == "implement" ]]; then
  git add -Af
  git diff --cached --binary --no-ext-diff >"$out/changes.patch"
fi

sed -n 's/.*"thread_id":"\([^"]*\)".*/\1/p' "$out/codex.jsonl" | head -n 1 >"$out/thread-id"
printf '%s\n' "$codex_status" >"$out/status"

tar_opts=()
for opt in --no-xattrs --no-mac-metadata; do
  if tar "$opt" -cf /dev/null -T /dev/null >/dev/null 2>&1; then
    tar_opts+=("$opt")
  fi
done
COPYFILE_DISABLE=1 tar ${tar_opts[@]+"${tar_opts[@]}"} -czf "$out/results.tar.gz" -C "$out" \
  response.md changes.patch codex.jsonl codex.stderr thread-id status

printf '===DELEGATE_TO_CODEX_RESULTS_B64===\n'
base64 <"$out/results.tar.gz"
printf '===DELEGATE_TO_CODEX_END===\n'
