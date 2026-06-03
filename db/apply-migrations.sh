#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
POSTGRES_CONTAINER="${1:-ai-postgres-1}"
POSTGRES_USER="${POSTGRES_USER:-postgres}"
POSTGRES_DB="${POSTGRES_DB:-litellm}"

if ! docker ps --format '{{.Names}}' | grep -qx "$POSTGRES_CONTAINER"; then
    echo "error: postgres container is not running: ${POSTGRES_CONTAINER}" >&2
    echo "usage: $0 [postgres-container]" >&2
    echo "examples:" >&2
    echo "  $0 ai-postgres-1" >&2
    echo "  $0 aidev1-postgres-1" >&2
    exit 1
fi

shopt -s nullglob
migrations=("$SCRIPT_DIR"/migrations/*.sql)
if (( ${#migrations[@]} == 0 )); then
    echo "no migrations found in ${SCRIPT_DIR}/migrations"
    exit 0
fi

for migration in "${migrations[@]}"; do
    echo "applying $(basename "$migration") to ${POSTGRES_CONTAINER}:${POSTGRES_DB}"
    docker exec -i "$POSTGRES_CONTAINER" \
        psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" < "$migration"
done

echo "migrations applied"
