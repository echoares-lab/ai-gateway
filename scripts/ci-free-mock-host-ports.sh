#!/usr/bin/env bash
# Free host ports used by Gate B mock-integration on self-hosted runners.
# Called before/after mock stack compose up/down. Intentionally omits `down -v` by
# default so aidevmock Postgres volume (dev_pgdata) persists across CI jobs.
# Set CI_MOCK_DOWN_VOLUMES=1 to run `docker compose down -v` (full reset).
set -euo pipefail

ROOT="${1:-.}"
cd "$ROOT"

COMPOSE=(docker compose -f docker-compose.dev.yml -f docker-compose.mock.yml -p aidevmock)
MOCK_PORTS=(18080 4010 4011)

"${COMPOSE[@]}" down --remove-orphans || true
if [[ "${CI_MOCK_DOWN_VOLUMES:-}" == "1" ]]; then
  "${COMPOSE[@]}" down -v --remove-orphans || true
fi

# Crashed jobs can leave containers publishing these ports outside compose state.
for port in "${MOCK_PORTS[@]}"; do
  while read -r cid; do
    [[ -z "$cid" ]] && continue
    echo "Removing container $cid still publishing host port $port"
    docker rm -f "$cid" || true
  done < <(docker ps -q --filter "publish=${port}" 2>/dev/null || true)
done

# Non-Docker listeners (rare); requires psmisc (fuser). Self-hosted CI installs it.
for port in "${MOCK_PORTS[@]}"; do
  if ss -tln 2>/dev/null | grep -q ":${port} "; then
    echo "Port ${port} still in use after compose down; trying fuser -k"
    sudo fuser -k "${port}/tcp" 2>/dev/null || true
  fi
done
