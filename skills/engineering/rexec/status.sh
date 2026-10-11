#!/usr/bin/env bash
set -eu
BASE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec "$BASE/server/rexec" status "$@"
