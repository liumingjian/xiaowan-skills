#!/usr/bin/env bash
set -euo pipefail

remote_root="${1:-}"
mode="${2:-}"

[[ "$remote_root" =~ ^/tmp/delegate-to-cc\.[A-Za-z0-9]+$ ]] || {
  printf 'Invalid remote workspace: %s\n' "$remote_root" >&2
  exit 1
}
case "$mode" in
  consult|implement) ;;
  *)
    printf 'Invalid mode: %s\n' "$mode" >&2
    exit 1
    ;;
esac

workspace="$remote_root/workspace"
mkdir -p "$workspace"
tar -xzf "$remote_root/repo.tar.gz" -C "$workspace"

cd "$workspace"
# This Git metadata is disposable and exists only to produce a portable patch.
git init -q
git config user.name "Claude Code Delegate"
git config user.email "claude-delegate@localhost"
git add -Af
git commit -qm snapshot

export PATH="$HOME/.local/bin:$PATH"
claude_bin="$(command -v claude || true)"
if [[ -z "$claude_bin" ]]; then
  claude_bin="$(bash -ilc 'command -v claude' 2>/dev/null | tail -n 1)"
fi
[[ -n "$claude_bin" && -x "$claude_bin" ]] || {
  printf 'Claude Code CLI not found in the remote login environment.\n' >&2
  exit 1
}
command -v timeout >/dev/null 2>&1 || {
  printf 'GNU timeout is required on the remote host.\n' >&2
  exit 1
}
timeout_seconds="$(tr -d '[:space:]' <"$remote_root/timeout-seconds")"
[[ "$timeout_seconds" =~ ^[1-9][0-9]*$ && "$timeout_seconds" -le 86400 ]] || {
  printf 'Invalid timeout: %s\n' "$timeout_seconds" >&2
  exit 1
}

full_prompt="$remote_root/full-prompt.md"
case "$mode" in
  consult)
    cat >"$full_prompt" <<'EOF'
You are the second-opinion engineer. Work only from this disposable project snapshot and the handoff below.

Inspect every relevant file before deciding. Do not modify files. Give a clear recommendation grounded in repository evidence, identify the strongest alternative, and state any uncertainty or missing evidence. Match the depth to the decision.

--- HANDOFF ---
EOF
    tools="Read,Glob,Grep"
    permission_mode="dontAsk"
    ;;
  implement)
    cat >"$full_prompt" <<'EOF'
You are the implementation engineer in a disposable project snapshot. Work only inside this snapshot and follow the handoff below.

Inspect every relevant file, then implement the smallest complete solution by editing files. Preserve unrelated behavior and existing user work. Shell access is intentionally unavailable, so do not claim tests ran; end with the exact local checks Codex should run, plus remaining risks.

--- HANDOFF ---
EOF
    tools="Read,Glob,Grep,Edit,Write"
    permission_mode="acceptEdits"
    ;;
esac
cat "$remote_root/prompt.md" >>"$full_prompt"

claude_args=(
  -p
  --safe-mode
  --no-session-persistence
  --output-format text
  --tools "$tools"
  --permission-mode "$permission_mode"
)
model="$(tr -d '\r\n' <"$remote_root/model")"
if [[ -n "$model" ]]; then
  claude_args+=(--model "$model")
fi

set +e
timeout "$timeout_seconds" "$claude_bin" "${claude_args[@]}" <"$full_prompt" >"$remote_root/response.md" 2>"$remote_root/claude.stderr"
claude_status=$?
set -e

git add -Af
git diff --cached --binary --no-ext-diff >"$remote_root/changes.patch"
printf '%s\n' "$claude_status" >"$remote_root/status"

tar -czf "$remote_root/results.tar.gz" \
  -C "$remote_root" \
  response.md changes.patch claude.stderr status
