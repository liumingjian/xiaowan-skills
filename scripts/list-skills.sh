#!/usr/bin/env bash
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd -P)"

cd "$REPO"
find skills -name SKILL.md -not -path '*/node_modules/*' | sort
