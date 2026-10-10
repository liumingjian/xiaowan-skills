#!/usr/bin/env bash
set -euo pipefail
umask 077

usage() {
  cat <<'HELP'
Usage:
  delegate.sh --prompt-file PATH [options]

Runs Codex on the paired Mac mini through rexec.
Run it from the project root; rexec freezes the current directory.

Options:
  --mode consult|implement   Codex access mode (default: consult)
  --prompt-file PATH         Handoff Markdown, inside the current directory
  --with-git                 Include real Git history for history-based review
  --model MODEL              Codex model (default: gpt-6-astra)
  --effort EFFORT            Codex reasoning effort (default: xhigh)
  --timeout-seconds N        Execution deadline in seconds (default: 1800)
  --resume THREAD_ID         Continue an earlier Codex thread
  --output-dir DIR           Store text artifacts (default: .codex-out/<ts>)
  -h, --help                 Show this help
HELP
}

die() {
  printf 'delegate-to-codex: %s\n' "$*" >&2
  exit 1
}

require_value() {
  [[ $# -ge 2 && -n "$2" ]] || die "$1 requires a value"
}

shell_quote() {
  python3 -c 'import shlex, sys; print(shlex.quote(sys.argv[1]), end="")' "$1"
}

mode="consult"
prompt_file=""
with_git=0
model="gpt-6-astra"
effort="xhigh"
resume_id=""
output_dir=""
timeout_seconds=1800

while [[ $# -gt 0 ]]; do
  case "$1" in
    --mode) require_value "$@"; mode="$2"; shift 2 ;;
    --prompt-file) require_value "$@"; prompt_file="$2"; shift 2 ;;
    --with-git) with_git=1; shift ;;
    --model) require_value "$@"; model="$2"; shift 2 ;;
    --effort) require_value "$@"; effort="$2"; shift 2 ;;
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
[[ "$model" =~ ^[A-Za-z0-9._:-]+$ ]] || die "--model must be a plain model name"
[[ "$effort" =~ ^[a-z]+$ ]] || die "--effort must be a plain effort level"
[[ -z "$resume_id" || "$resume_id" =~ ^[A-Za-z0-9_-]+$ ]] || die "--resume must be an opaque thread identifier"
[[ "$timeout_seconds" =~ ^[1-9][0-9]{0,4}$ && "$timeout_seconds" -le 86400 ]] || die "--timeout-seconds must be between 1 and 86400"
[[ -n "$prompt_file" ]] || die "--prompt-file is required"
[[ -f "$prompt_file" && -s "$prompt_file" && ! -L "$prompt_file" ]] || die "handoff must be a non-empty regular file"
command -v rexec >/dev/null 2>&1 || die "rexec not found; use the rexec skill to prepare the channel"
command -v python3 >/dev/null 2>&1 || die "python3 is required to validate JSON receipts"

project_root="$(pwd -P)"
prompt_abs="$(cd "$(dirname "$prompt_file")" && pwd -P)/$(basename "$prompt_file")"
case "$prompt_abs" in
  "$project_root"/*) prompt_rel="${prompt_abs#"$project_root"/}" ;;
  *) die "the handoff must live under the current directory; rexec freezes only that source" ;;
esac


if [[ -z "$output_dir" ]]; then
  output_dir=".codex-out/$(date +%Y%m%d-%H%M%S)"
fi
mkdir -p "$output_dir"
for artifact in response.md changes.patch status.json acceptance.json wait.json; do
  [[ ! -e "$output_dir/$artifact" && ! -L "$output_dir/$artifact" ]] || die "output artifact already exists: $artifact"
done
output_dir="$(cd "$output_dir" && pwd -P)"

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
remote_runner="$script_dir/remote-run.sh"
[[ -f "$remote_runner" ]] || die "remote runner not found"
runner_b64="$(base64 <"$remote_runner" | tr -d '\r\n')"
remote_script='rs=$(mktemp "${TMPDIR:?}/delegate-run.XXXXXXXX") || exit 70; printf %s '
remote_script+="$(shell_quote "$runner_b64")"
remote_script+=' | base64 -d > "$rs" || exit 70; bash "$rs" '
for value in "$mode" "$prompt_rel" "$model" "$resume_id" "$effort"; do
  remote_script+="$(shell_quote "$value") "
done
remote_script+='; rc=$?; rm -f -- "$rs"; exit "$rc"'

rexec_args=(--background --timeout "$timeout_seconds")
[[ "$with_git" -eq 1 ]] && rexec_args+=(--with-git)
if rexec "${rexec_args[@]}" "$remote_script" >"$output_dir/acceptance.json"; then
  :
else
  submit_status=$?
  printf 'delegate-to-codex: submission did not return acceptance; inspect rexec status before resubmitting\n' >&2
  exit "$submit_status"
fi

job_id="$(python3 - "$output_dir/acceptance.json" <<'PY'
import json, re, sys
try:
    with open(sys.argv[1], encoding="utf-8") as source:
        receipt = json.load(source)
    job = receipt["job_id"]
    if not isinstance(job, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", job):
        raise ValueError()
except (OSError, ValueError, KeyError, TypeError):
    sys.exit("delegate-to-codex: invalid acceptance JSON; inspect rexec status before resubmitting")
print(job)
PY
)" || exit 1
printf 'JOB_ID=%s\n' "$job_id"

trap 'printf "delegate-to-codex: wait interrupted; job %s remains durable; use rexec wait and artifacts to collect it\n" "$job_id" >&2; exit 130' INT
trap 'printf "delegate-to-codex: wait interrupted; job %s remains durable; use rexec wait and artifacts to collect it\n" "$job_id" >&2; exit 143' TERM
set +e
rexec wait "$job_id" >"$output_dir/wait.json"
wait_status=$?
set -e
trap - INT TERM

wait_outcome="$(python3 - "$output_dir/wait.json" "$job_id" "$wait_status" <<'PY'
import json, sys
try:
    with open(sys.argv[1], encoding="utf-8") as source:
        receipt = json.load(source)
    if receipt["job_id"] != sys.argv[2]:
        raise ValueError()
    outcome = receipt.get("outcome")
    if outcome in ("completed", "cancelled", "timeout", "unknown", "failed"):
        code = receipt["exit_code"]
        if type(code) is not int or not 0 <= code <= 255 or code != int(sys.argv[3]):
            raise ValueError()
        print(outcome)
    elif receipt.get("state") == "pending" and receipt.get("reason") == "WAIT_TIMEOUT" and int(sys.argv[3]) == 75:
        print("pending")
    else:
        raise ValueError()
except (OSError, ValueError, KeyError, TypeError):
    sys.exit("delegate-to-codex: no validated terminal receipt; job remains durable; inspect rexec status before resubmitting")
PY
)" || { [[ "$wait_status" -eq 0 ]] || exit "$wait_status"; exit 1; }
case "$wait_outcome" in
  pending)
    printf 'delegate-to-codex: wait ended before collection; job %s remains durable; use rexec wait and artifacts to collect it\n' "$job_id" >&2
    exit 75
    ;;
  unknown)
    printf 'delegate-to-codex: execution outcome unknown for job %s; inspect safe status/trace before resubmitting\n' "$job_id" >&2
    [[ "$wait_status" -eq 0 ]] && exit 1
    exit "$wait_status"
    ;;
  timeout) printf 'delegate-to-codex: execution deadline reached for job %s\n' "$job_id" >&2 ;;
  cancelled) printf 'delegate-to-codex: job %s was cancelled\n' "$job_id" >&2 ;;
esac

if rexec artifacts "$job_id" --into "$output_dir"; then
  :
else
  artifact_status=$?
  printf 'delegate-to-codex: artifact collection failed for job %s; inspect its safe status/trace; raw logs are not a fallback\n' "$job_id" >&2
  [[ "$wait_status" -eq 0 ]] || exit "$wait_status"
  exit "$artifact_status"
fi

result="$(python3 - "$output_dir" "$mode" <<'PY'
import json, pathlib, re, sys
try:
    directory = pathlib.Path(sys.argv[1])
    for name in ("response.md", "changes.patch", "status.json"):
        path = directory / name
        if path.is_symlink() or not path.is_file():
            raise ValueError()
        path.read_text(encoding="utf-8")
    state = json.loads((directory / "status.json").read_text(encoding="utf-8"))
    status, thread = state["status"], state["thread_id"]
    if type(status) is not int or not 0 <= status <= 255:
        raise ValueError()
    if thread is not None and (not isinstance(thread, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", thread)):
        raise ValueError()
    if sys.argv[2] == "consult" and (directory / "changes.patch").stat().st_size:
        raise ValueError()
except (OSError, ValueError, KeyError, TypeError):
    sys.exit("delegate-to-codex: invalid or incomplete text artifacts")
print(status)
print(thread or "unknown")
PY
)" || { [[ "$wait_status" -eq 0 ]] || exit "$wait_status"; exit 1; }
codex_status="${result%%$'\n'*}"
thread_id="${result#*$'\n'}"
if [[ -s "$output_dir/changes.patch" ]]; then
  git apply --numstat -- "$output_dir/changes.patch" >/dev/null 2>&1 || die "returned patch is malformed; inspect the safe artifacts"
fi

printf 'OUTPUT_DIR=%s\n' "$output_dir"
printf 'MODE=%s\n' "$mode"
printf 'MODEL=%s\n' "$model"
printf 'EFFORT=%s\n' "$effort"
printf 'RESPONSE=%s/response.md\n' "$output_dir"
printf 'PATCH=%s/changes.patch\n' "$output_dir"
printf 'PATCH_BYTES=%s\n' "$(wc -c <"$output_dir/changes.patch" | tr -d ' ')"
printf 'THREAD_ID=%s\n' "$thread_id"
printf 'STATUS=%s\n' "$codex_status"

[[ "$wait_status" -eq 0 ]] || exit "$wait_status"
exit "$codex_status"
