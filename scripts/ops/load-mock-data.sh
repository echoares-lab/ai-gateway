#!/usr/bin/env bash
# Load pre-migrated LiteLLM schema into a dev/mock Postgres when the volume predates seeding.
# Fresh volumes get the same SQL via docker-entrypoint-initdb.d/02-seed-litellm-mock.sql.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
POSTGRES_CONTAINER="${1:-}"
SEED="${ROOT}/db/seed-litellm-mock.sql"

if [[ -z "$POSTGRES_CONTAINER" ]]; then
    echo "usage: $0 <postgres-container>" >&2
    exit 1
fi
if [[ ! -f "$SEED" ]]; then
    echo "error: seed file missing: ${SEED}" >&2
    exit 1
fi
if ! docker inspect "$POSTGRES_CONTAINER" >/dev/null 2>&1; then
    echo "error: container not found: ${POSTGRES_CONTAINER}" >&2
    exit 1
fi

has_prisma="$(docker exec "$POSTGRES_CONTAINER" psql -U postgres -d litellm -tAc \
    "SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema='public' AND table_name='_prisma_migrations')" \
    2>/dev/null | tr -d '[:space:]')"

if [[ "$has_prisma" == "t" ]]; then
    rows="$(docker exec "$POSTGRES_CONTAINER" psql -U postgres -d litellm -tAc \
        "SELECT COUNT(*) FROM _prisma_migrations" 2>/dev/null | tr -d '[:space:]')"
    if [[ "${rows:-0}" -gt 0 ]]; then
        echo "litellm schema already seeded (${rows} prisma migrations) — skipping"
        exit 0
    fi
fi

echo "loading pre-migrated LiteLLM schema into ${POSTGRES_CONTAINER} ..."
docker exec -i "$POSTGRES_CONTAINER" psql -v ON_ERROR_STOP=1 -U postgres -d postgres < "$SEED"
echo "mock LiteLLM schema loaded"
