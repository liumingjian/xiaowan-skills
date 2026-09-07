#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage:
  delegate.sh --prompt-file PATH [options]

Runs Codex on the Mac this session ssh'd in from, through the rexec channel.
Run it from the project root; rexec syncs the current directory.

Options:
  --mode consult|implement   Codex access mode (default: consult)
  --prompt-file PATH         Handoff Markdown, inside the current directory
  --mac NAME_OR_PREFIX       Target a specific Mac (see: rexec --macs)
  --with-git                 Sync real Git history, so Codex can review against a base branch
  --model MODEL              Codex model
  --timeout-seconds N        Stop Codex after N seconds of run time (default: 1800)
  --resume THREAD_ID         Continue an earlier Codex thread
  --output-dir DIR           Store returned artifacts in DIR (default: .codex-out/<ts>)
  -h, --help                 Show this help
EOF
}

die() {
  printf 'delegate-to-codex: %s\n' "$*" >&2
  exit 1
}

require_value() {
  [[ $# -ge 2 && -n "$2" ]] || die "$1 requires a value"
}

mode="consult"
prompt_file=""
mac=""
with_git=0
model=""
resume_id=""
output_dir=""
timeout_seconds=1800

while [[ $# -gt 0 ]]; do
  case "$1" in
    --mode) require_value "$@"; mode="$2"; shift 2 ;;
    --prompt-file) require_value "$@"; prompt_file="$2"; shift 2 ;;
    --mac) require_value "$@"; mac="$2"; shift 2 ;;
    --with-git) with_git=1; shift ;;
    --model) require_value "$@"; model="$2"; shift 2 ;;
    --resume) require_value "$@"; resume_id="$2"; shift 2 ;;
    --timeout-seconds) require_value "$@"; timeout_seconds="$2"; shift 2 ;;
    --output-dir) require_value "$@"; output_dir="$2"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) die "unknown argument: $1" ;;
  esac
done

case "$mode" in
  consult|implement) ;;
  *) die "--mode must be consult or implement" ;;
esac
[[ "$timeout_seconds" =~ ^[1-9][0-9]*$ && "$timeout_seconds" -le 86400 ]] || die "--timeout-seconds must be between 1 and 86400"
[[ -n "$prompt_file" ]] || die "--prompt-file is required"
[[ -f "$prompt_file" && -s "$prompt_file" ]] || die "handoff must exist and be non-empty: $prompt_file"
command -v rexec >/dev/null 2>&1 || die "rexec not found; the /rexec skill provides the only channel to the Mac"

project_root="$PWD"
prompt_abs="$(cd "$(dirname "$prompt_file")" && pwd -P)/$(basename "$prompt_file")"
case "$prompt_abs" in
  "$project_root"/*) prompt_rel="${prompt_abs#"$project_root"/}" ;;
  *) die "the handoff must live under the current directory ($project_root); rexec syncs only that" ;;
esac

# rexec syncs with --filter=':- .gitignore', so an ignored handoff never reaches the Mac.
if git rev-parse --show-toplevel >/dev/null 2>&1; then
  if git check-ignore -q "$prompt_abs" 2>/dev/null; then
    die "the handoff is gitignored, so rexec will not sync it: $prompt_rel"
  fi
fi

timestamp="$(date +%Y%m%d-%H%M%S)"
if [[ -z "$output_dir" ]]; then
  output_dir=".codex-out/$timestamp"
fi
mkdir -p "$output_dir"
for artifact in response.md changes.patch codex.jsonl codex.stderr status; do
  [[ ! -e "$output_dir/$artifact" ]] || die "output artifact already exists: $output_dir/$artifact"
done
output_dir="$(cd "$output_dir" && pwd -P)"

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
remote_runner="$script_dir/remote-run.sh"
[[ -f "$remote_runner" ]] || die "remote runner not found: $remote_runner"
runner_b64="$(base64 -w0 <"$remote_runner")"

remote_script='rs="${TMPDIR:-/tmp}/delegate-to-codex-run.sh"; printf %s '"'$runner_b64'"' | base64 -d > "$rs"; bash "$rs" '"'$mode' '$prompt_rel' '$model' '$resume_id'"

rexec_args=(--timeout "$timeout_seconds")
[[ -n "$mac" ]] && rexec_args+=(--mac "$mac")
[[ "$with_git" -eq 1 ]] && rexec_args+=(--with-git)

raw="$output_dir/rexec.out"
bill="$output_dir/rexec.err"

set +e
rexec "${rexec_args[@]}" "$remote_script" >"$raw" 2>"$bill"
rexec_status=$?
set -e

case "$rexec_status" in
  0) ;;
  2) die "rexec rejected the job; see $bill (with --with-git this usually means the Mac's agent needs a restart)" ;;
  3) die "several Macs share this session's source IP; re-run with --mac (see: rexec --macs)" ;;
  69) die "the rexec agent is not running on this session's Mac; start it there, then re-run" ;;
  65) die "the handoff did not reach the Mac; confirm $prompt_rel is not gitignored, then re-run" ;;
  66) die "codex is not installed on the target Mac; re-run with --mac to use the other one" ;;
  124) die "Codex exceeded --timeout-seconds ($timeout_seconds) of run time" ;;
  125) die "the job was cancelled" ;;
  *) die "the Mac run failed (rexec exit $rexec_status); see $bill and the tail of $raw" ;;
esac

sed -n '/^===DELEGATE_TO_CODEX_RESULTS_B64===$/,/^===DELEGATE_TO_CODEX_END===$/p' "$raw" \
  | sed '1d;$d' | base64 -d | tar -xzf - -C "$output_dir" \
  || die "could not decode the results returned from the Mac; see $raw"

codex_status="$(tr -d '[:space:]' <"$output_dir/status")"
[[ "$codex_status" =~ ^[0-9]+$ ]] || die "invalid Codex exit status: $codex_status"
thread_id="$(tr -d '[:space:]' <"$output_dir/thread-id")"
target_mac="$(sed -n 's/.*--- \[\([^]]*\)\] exit=.*/\1/p' "$bill" | tail -n 1)"

printf 'OUTPUT_DIR=%s\n' "$output_dir"
printf 'MODE=%s\n' "$mode"
printf 'MAC=%s\n' "${target_mac:-unknown}"
printf 'RESPONSE=%s/response.md\n' "$output_dir"
printf 'PATCH=%s/changes.patch\n' "$output_dir"
printf 'PATCH_BYTES=%s\n' "$(wc -c <"$output_dir/changes.patch" | tr -d ' ')"
printf 'LOG=%s/codex.jsonl\n' "$output_dir"
printf 'THREAD_ID=%s\n' "${thread_id:-unknown}"
printf 'STATUS=%s\n' "$codex_status"

if git rev-parse --show-toplevel >/dev/null 2>&1 && ! git check-ignore -q .codex-out 2>/dev/null; then
  printf 'GITIGNORE_HINT=add .codex-out/ to .gitignore\n'
fi

[[ "$codex_status" -eq 0 ]] || exit 1
