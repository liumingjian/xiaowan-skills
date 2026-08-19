#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage:
  delegate.sh --prompt-file PATH [options]

Options:
  --mode consult|implement   Claude access mode (default: consult)
  --host SSH_ALIAS           SSH host alias (default: vps-2g)
  --model MODEL              Claude model alias or full model ID
  --timeout-seconds N        Stop Claude after N seconds (default: 900)
  --include-untracked        Include Git untracked, non-ignored files
  --output-dir DIR           Store returned artifacts in DIR
  -h, --help                 Show this help
EOF
}

die() {
  printf 'delegate-to-cc: %s\n' "$*" >&2
  exit 1
}

require_value() {
  [[ $# -ge 2 && -n "$2" ]] || die "$1 requires a value"
}

mode="consult"
host="vps-2g"
model=""
prompt_file=""
output_dir=""
include_untracked=0
timeout_seconds=900

while [[ $# -gt 0 ]]; do
  case "$1" in
    --mode)
      require_value "$@"
      mode="$2"
      shift 2
      ;;
    --host)
      require_value "$@"
      host="$2"
      shift 2
      ;;
    --model)
      require_value "$@"
      model="$2"
      shift 2
      ;;
    --prompt-file)
      require_value "$@"
      prompt_file="$2"
      shift 2
      ;;
    --timeout-seconds)
      require_value "$@"
      timeout_seconds="$2"
      shift 2
      ;;
    --output-dir)
      require_value "$@"
      output_dir="$2"
      shift 2
      ;;
    --include-untracked)
      include_untracked=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      die "unknown argument: $1"
      ;;
  esac
done

case "$mode" in
  consult|implement) ;;
  *) die "--mode must be consult or implement" ;;
esac
[[ "$timeout_seconds" =~ ^[1-9][0-9]*$ && "$timeout_seconds" -le 86400 ]] || die "--timeout-seconds must be between 1 and 86400"
[[ "$host" != -* ]] || die "--host cannot start with a hyphen"

[[ -n "$prompt_file" ]] || die "--prompt-file is required"
[[ -f "$prompt_file" && -s "$prompt_file" ]] || die "prompt file must exist and be non-empty: $prompt_file"

for command_name in git ssh scp tar; do
  command -v "$command_name" >/dev/null 2>&1 || die "required command not found: $command_name"
done
tar_metadata_options=()
for tar_option in --no-xattrs --no-mac-metadata; do
  if tar "$tar_option" -cf /dev/null -T /dev/null >/dev/null 2>&1; then
    tar_metadata_options+=("$tar_option")
  fi
done

repo_root="$(git rev-parse --show-toplevel 2>/dev/null)" || die "run from inside a Git repository"
script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
remote_runner="$script_dir/remote-run.sh"
[[ -f "$remote_runner" ]] || die "remote runner not found: $remote_runner"

if [[ -z "$output_dir" ]]; then
  output_dir="$(mktemp -d "${TMPDIR:-/tmp}/claude-delegation.XXXXXXXX")"
else
  mkdir -p "$output_dir"
  for artifact in response.md changes.patch claude.stderr status; do
    [[ ! -e "$output_dir/$artifact" ]] || die "output artifact already exists: $output_dir/$artifact"
  done
fi
output_dir="$(cd "$output_dir" && pwd -P)"

local_tmp="$(mktemp -d "${TMPDIR:-/tmp}/delegate-to-cc.XXXXXXXX")"
remote_dir=""
ssh_options=(
  -o BatchMode=yes
  -o ConnectTimeout=10
  -o ServerAliveInterval=15
  -o ServerAliveCountMax=3
)

cleanup() {
  if [[ "$remote_dir" =~ ^/tmp/delegate-to-cc\.[A-Za-z0-9]+$ ]]; then
    ssh "${ssh_options[@]}" "$host" "rm -rf -- '$remote_dir'" >/dev/null 2>&1 || true
  fi
  if [[ "$local_tmp" =~ /delegate-to-cc\.[A-Za-z0-9]+$ && -d "$local_tmp" ]]; then
    rm -rf -- "$local_tmp"
  fi
}
trap cleanup EXIT

manifest="$local_tmp/manifest"
archive="$local_tmp/repo.tar.gz"
snapshot_args=(--cached)
if [[ $include_untracked -eq 1 ]]; then
  snapshot_args+=(--others --exclude-standard)
fi

while IFS= read -r -d '' path; do
  if [[ -e "$repo_root/$path" || -L "$repo_root/$path" ]]; then
    printf './%s\0' "$path"
  fi
done < <(git -C "$repo_root" ls-files -z "${snapshot_args[@]}") >"$manifest"

file_count="$(tr -cd '\0' <"$manifest" | wc -c | tr -d ' ')"
[[ "$file_count" -gt 0 ]] || die "snapshot contains no files"

if [[ $include_untracked -eq 0 ]]; then
  untracked_count="$(git -C "$repo_root" ls-files -z --others --exclude-standard | tr -cd '\0' | wc -c | tr -d ' ')"
  if [[ "$untracked_count" -gt 0 ]]; then
    printf 'Note: omitted %s untracked file(s); inspect them before using --include-untracked.\n' "$untracked_count" >&2
  fi
fi

COPYFILE_DISABLE=1 tar "${tar_metadata_options[@]}" --null -czf "$archive" -C "$repo_root" -T "$manifest"
cp "$prompt_file" "$local_tmp/prompt.md"
cp "$remote_runner" "$local_tmp/remote-run.sh"
printf '%s\n' "$model" >"$local_tmp/model"
printf '%s\n' "$timeout_seconds" >"$local_tmp/timeout-seconds"

remote_dir="$(ssh "${ssh_options[@]}" "$host" 'mktemp -d /tmp/delegate-to-cc.XXXXXXXX')" || die "could not create remote workspace on $host"
[[ "$remote_dir" =~ ^/tmp/delegate-to-cc\.[A-Za-z0-9]+$ ]] || die "unexpected remote workspace path: $remote_dir"

scp -q "${ssh_options[@]}" \
  "$archive" \
  "$local_tmp/prompt.md" \
  "$local_tmp/model" \
  "$local_tmp/timeout-seconds" \
  "$local_tmp/remote-run.sh" \
  "$host:$remote_dir/"

ssh "${ssh_options[@]}" "$host" "bash '$remote_dir/remote-run.sh' '$remote_dir' '$mode'"
scp -q "${ssh_options[@]}" "$host:$remote_dir/results.tar.gz" "$local_tmp/results.tar.gz"
tar -xzf "$local_tmp/results.tar.gz" -C "$output_dir"

claude_status="$(tr -d '[:space:]' <"$output_dir/status")"
[[ "$claude_status" =~ ^[0-9]+$ ]] || die "invalid Claude exit status: $claude_status"

printf 'OUTPUT_DIR=%s\n' "$output_dir"
printf 'RESPONSE=%s/response.md\n' "$output_dir"
printf 'PATCH=%s/changes.patch\n' "$output_dir"
printf 'STDERR=%s/claude.stderr\n' "$output_dir"
printf 'STATUS=%s\n' "$claude_status"

if [[ "$claude_status" -ne 0 ]]; then
  exit 1
fi
