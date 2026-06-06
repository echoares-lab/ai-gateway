#!/usr/bin/env bash
# Sync CLIProxy credential priorities from Postgres pool members (issue 38-13).
# Feature-flagged: set CLIPROXY_PRIORITY_SYNC_ENABLED=true to enable pushes.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"

if [[ -f "${ROOT}/.env" ]]; then
  # shellcheck disable=SC1091
  source "${ROOT}/.env"
fi

cd "${ROOT}/services/translator"
exec python3 "${ROOT}/scripts/pool_sync.py" "$@"
