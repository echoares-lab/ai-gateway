#!/usr/bin/env bash
# Free host ports used by Gate B mock-integration on self-hosted runners.
# Called before/after mock stack compose up/down. Intentionally omits `down -v` by
# default so aidevmock Postgres volume (dev_pgdata) persists across CI jobs.
# Set CI_MOCK_DOWN_VOLUMES=1 or CI_MOCK_FRESH_DB=1 to run `docker compose down -v` (full reset).
set -euo pipefail

ROOT="${1:-.}"
cd "$ROOT"

COMPOSE=(docker compose -f docker-compose.dev.yml -p aidevmock)
MOCK_PORTS=(18080 4010 4011 8327)

"${COMPOSE[@]}" down --remove-orphans || true
if [[ "${CI_MOCK_DOWN_VOLUMES:-}" == "1" || "${CI_MOCK_FRESH_DB:-}" == "1" ]]; then
  "${COMPOSE[@]}" down -v --remove-orphans || true
fi

# Orphaned aidevmock containers (compose down can miss crashed policy-engine publishers).
while read -r cid; do
  [[ -z "$cid" ]] && continue
  echo "Removing aidevmock container $cid"
  docker rm -f "$cid" || true
done < <(docker ps -aq --filter 'name=aidevmock-' 2>/dev/null || true)

# Containers publishing mock host ports (publish= filter misses 127.0.0.1:PORT bindings).
containers_publishing_port() {
  local port=$1
  local cid host_port
  while read -r cid; do
    [[ -z "$cid" ]] && continue
    while read -r host_port; do
      [[ -z "$host_port" ]] && continue
      if [[ "${host_port##*:}" == "$port" ]]; then
        echo "$cid"
        break
      fi
    done < <(docker port "$cid" 2>/dev/null | awk -F' -> ' 'NF==2 {print $2}')
  done < <(docker ps -q 2>/dev/null || true)
}

for port in "${MOCK_PORTS[@]}"; do
  while read -r cid; do
    [[ -z "$cid" ]] && continue
    echo "Removing container $cid still publishing host port $port"
    docker rm -f "$cid" || true
  done < <(containers_publishing_port "$port" | sort -u)
  # Legacy filter (0.0.0.0 bindings)
  while read -r cid; do
    [[ -z "$cid" ]] && continue
    echo "Removing container $cid (publish filter) on port $port"
    docker rm -f "$cid" || true
  done < <(docker ps -q --filter "publish=${port}" --filter "publish=127.0.0.1:${port}" 2>/dev/null || true)
done

port_in_use() {
  local port=$1
  ss -tln 2>/dev/null | grep -qE "[:.]${port}([[:space:]]|$)"
}

# Non-Docker listeners (rare); requires psmisc (fuser). Self-hosted CI installs it.
for port in "${MOCK_PORTS[@]}"; do
  if port_in_use "$port"; then
    echo "Port ${port} still in use after compose down; trying fuser -k"
    sudo fuser -k "${port}/tcp" 2>/dev/null || true
  fi
done

# Wait for Docker proxy to release bindings (policy-engine often holds 127.0.0.1:18080).
for _ in {1..12}; do
  blocked=()
  for port in "${MOCK_PORTS[@]}"; do
    if port_in_use "$port"; then
      blocked+=("$port")
      while read -r cid; do
        [[ -z "$cid" ]] && continue
        echo "Retry: removing container $cid on port $port"
        docker rm -f "$cid" || true
      done < <(containers_publishing_port "$port" | sort -u)
    fi
  done
  if [[ ${#blocked[@]} -eq 0 ]]; then
    break
  fi
  echo "Waiting for ports (${blocked[*]}) to free..."
  sleep 1
done

for port in "${MOCK_PORTS[@]}"; do
  if port_in_use "$port"; then
    echo "ERROR: host port ${port} still in use after cleanup"
    ss -tln 2>/dev/null | grep -E "[:.]${port}([[:space:]]|$)" || true
    docker ps -a --format 'table {{.Names}}\t{{.Ports}}\t{{.Status}}' 2>/dev/null | head -30 || true
    exit 1
  fi
done
