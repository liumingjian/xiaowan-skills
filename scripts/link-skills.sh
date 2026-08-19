#!/usr/bin/env bash
set -euo pipefail

# Maintainer helper: link every skill into local Agent Skills directories.
# The repository remains the single source of truth; a later pull updates links.

REPO="$(cd "$(dirname "$0")/.." && pwd -P)"
DESTS=(
  "$HOME/.claude/skills"
  "$HOME/.agents/skills"
  "$HOME/.codex/skills"
)

names=()
srcs=()
while IFS= read -r -d '' skill_md; do
  src="$(dirname "$skill_md")"
  names+=("$(basename "$src")")
  srcs+=("$src")
done < <(find "$REPO/skills" -name SKILL.md -not -path '*/node_modules/*' -not -path '*/deprecated/*' -print0)

for dest in "${DESTS[@]}"; do
  if [[ -L "$dest" ]]; then
    resolved="$(readlink -f "$dest")"
    case "$resolved" in
      "$REPO"|"$REPO"/*)
        printf 'error: %s is a symlink into this repo (%s)\n' "$dest" "$resolved" >&2
        exit 1
        ;;
    esac
  fi

  mkdir -p "$dest"

  for i in "${!names[@]}"; do
    name="${names[$i]}"
    src="${srcs[$i]}"
    target="$dest/$name"

    if [[ -e "$target" && ! -L "$target" ]]; then
      rm -rf -- "$target"
    fi

    ln -sfn "$src" "$target"
    printf 'linked %s -> %s (%s)\n' "$name" "$src" "$dest"
  done
done
