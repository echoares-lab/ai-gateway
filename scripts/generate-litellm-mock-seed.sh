#!/usr/bin/env bash
# Regenerate db/seed-litellm-mock.sql from a running LiteLLM Postgres with migrations applied.
# Requires: stable stack postgres (ai-postgres-1) or pass POSTGRES_CONTAINER.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
POSTGRES_CONTAINER="${POSTGRES_CONTAINER:-ai-postgres-1}"
OUT="${ROOT}/db/seed-litellm-mock.sql"
LITELLM_IMAGE="${LITELLM_IMAGE:-ghcr.io/berriai/litellm:v1.87.1}"

if ! docker inspect "$POSTGRES_CONTAINER" >/dev/null 2>&1; then
    echo "error: postgres container not found: ${POSTGRES_CONTAINER}" >&2
    exit 1
fi

count="$(docker exec "$POSTGRES_CONTAINER" psql -U postgres -d litellm -tAc \
    "SELECT COUNT(*) FROM _prisma_migrations" 2>/dev/null || echo 0)"
if [[ "${count// /}" -lt 1 ]]; then
    echo "error: ${POSTGRES_CONTAINER} litellm DB has no _prisma_migrations — run LiteLLM migrations first" >&2
    exit 1
fi

echo "generating ${OUT} from ${POSTGRES_CONTAINER} (${count} prisma migrations) ..."
{
    cat <<EOF
-- Pre-migrated LiteLLM schema for mock/CI/dev stacks.
-- Regenerate: scripts/generate-litellm-mock-seed.sh
-- LiteLLM image: ${LITELLM_IMAGE}
\\connect litellm
EOF
    docker exec "$POSTGRES_CONTAINER" pg_dump -U postgres -d litellm \
        --no-owner --no-privileges --schema-only
    echo ''
    echo '-- _prisma_migrations rows so LITELLM_MIGRATIONS=None skips proxy_extras'
    docker exec "$POSTGRES_CONTAINER" pg_dump -U postgres -d litellm \
        --no-owner --no-privileges --data-only --table='_prisma_migrations'
} > "$OUT"

bytes="$(wc -c < "$OUT")"
echo "wrote ${OUT} (${bytes} bytes)"
