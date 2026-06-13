#!/usr/bin/env bash
# dev-env.sh — manage isolated dev gateway stacks for parallel feature development
#
# Usage:
#   ./dev-env.sh start   [slot]          build & start dev stack (default slot=1)
#   ./dev-env.sh stop    [slot]          stop & remove dev stack and its auth volume
#   ./dev-env.sh rebuild [slot]          rebuild gateway-engine only (fast after gateway-engine.py edit)
#   ./dev-env.sh rebuild-cliproxy [slot] rebuild cliproxy from fork source
#   ./dev-env.sh logs    [slot]          tail all dev logs
#   ./dev-env.sh test    [slot]          run integration tests against dev slot
#   ./dev-env.sh list                    show all running aidev* containers
#
# Port layout (slot N):
#   gateway-engine  4000+N*10   (e.g. slot 1 → 4010)
#   litellm UI  4001+N*10   (e.g. slot 1 → 4011)
#   cliproxy    8317+N*10   (e.g. slot 1 → 8327)
#
# Slot 0 is reserved for the stable stack.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
COMPOSE_FILE="${SCRIPT_DIR}/docker-compose.dev.yml"
MOCK_OVERLAY="${SCRIPT_DIR}/docker-compose.mock.yml"
ENV_FILE="${SCRIPT_DIR}/.env"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

die() { echo "error: $*" >&2; exit 1; }

require_slot() {
    local slot="${1:-1}"
    [[ "$slot" =~ ^[0-9]+$ ]] || die "slot must be a non-negative integer"
    (( slot != 0 )) || die "slot 0 is reserved for the stable stack"
    echo "$slot"
}

slot_ports() {
    local slot="$1"
    GATEWAY_ENGINE_PORT=$(( 4000 + slot * 10 ))
    LITELLM_PORT=$(( 4001 + slot * 10 ))
    CLIPROXY_PORT=$(( 8317 + slot * 10 ))
}

compose_env() {
    local slot="$1"
    slot_ports "$slot"
    local dev_cfg="${CLIPROXY_DEV_CONFIG:-}"
    local cfg_var=""
    [[ -n "$dev_cfg" ]] && cfg_var="CLIPROXY_DEV_CONFIG=${dev_cfg}"
    echo "COMPOSE_PROJECT_NAME=aidev${slot}" \
         "DEV_GATEWAY_ENGINE_PORT=${GATEWAY_ENGINE_PORT}" \
         "DEV_LITELLM_PORT=${LITELLM_PORT}" \
         "DEV_CLIPROXY_PORT=${CLIPROXY_PORT}" \
         $cfg_var
}

run_compose() {
    local slot="$1"; shift
    local env_vars
    env_vars="$(compose_env "$slot")"

    local op_run_prefix=""
    if [ -f "$HOME/.op-token" ]; then
        export OP_SERVICE_ACCOUNT_TOKEN
        OP_SERVICE_ACCOUNT_TOKEN=$(cat "$HOME/.op-token")
        op_run_prefix="op run --"
    elif grep -q 'op://' "$ENV_FILE" 2>/dev/null; then
        die "Secrets in $ENV_FILE are 1Password references, but ~/.op-token is missing."
    fi

    # Load .env for LITELLM_MASTER_KEY and CLIPROXY_API_KEY
    if [[ -f "$ENV_FILE" ]]; then
        set -o allexport
        # shellcheck disable=SC1090
        source "$ENV_FILE"
        set +o allexport
    fi
    # shellcheck disable=SC2086
    env $env_vars $op_run_prefix docker compose -f "$COMPOSE_FILE" "$@"
}

seed_auth_volume() {
    local slot="$1"
    local vol="aidev${slot}_dev_auth"
    local src="${HOME}/.cli-proxy-api"
    [[ -d "$src" ]] || die "auth source not found: $src — run cliproxy-setup.sh install first"
    echo "seeding auth volume ${vol} from ${src} ..."
    docker volume create "$vol" 2>/dev/null || true
    docker run --rm \
        -v "${src}:/src:ro" \
        -v "${vol}:/dst" \
        alpine sh -c "cp -r /src/. /dst/ && echo 'seeded $(ls /dst | wc -l) entries'"
}

# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

cmd_start() {
    local slot
    slot="$(require_slot "${1:-1}")"
    slot_ports "$slot"
    local wait_timeout="${DEV_ENV_WAIT_TIMEOUT:-300}"
    echo "starting dev slot ${slot}: gateway-engine=:${GATEWAY_ENGINE_PORT}  litellm=:${LITELLM_PORT}  cliproxy=:${CLIPROXY_PORT}"
    seed_auth_volume "$slot"
    if ! run_compose "$slot" up -d --build --wait --wait-timeout "$wait_timeout"; then
        echo "initial compose wait failed; retrying once for slow LiteLLM migration recovery ..." >&2
        run_compose "$slot" up -d --wait --wait-timeout "$wait_timeout"
    fi
    echo ""
    echo "dev slot ${slot} is up:"
    echo "  gateway-engine  http://localhost:${GATEWAY_ENGINE_PORT}/health"
    echo "  litellm UI  http://localhost:${LITELLM_PORT}"
    echo "  cliproxy    http://localhost:${CLIPROXY_PORT}/management.html"
}

cmd_stop() {
    local slot
    slot="$(require_slot "${1:-1}")"
    echo "stopping dev slot ${slot} ..."
    run_compose "$slot" down -v
    echo "dev slot ${slot} stopped and auth volume removed"
}

cmd_rebuild() {
    local slot
    slot="$(require_slot "${1:-1}")"
    echo "rebuilding gateway-engine for slot ${slot} ..."
    run_compose "$slot" build gateway-engine
    run_compose "$slot" up -d gateway-engine
}

cmd_rebuild_cliproxy() {
    local slot
    slot="$(require_slot "${1:-1}")"
    echo "rebuilding cliproxy for slot ${slot} (from /home/dev/repos/CLIProxyAPI) ..."
    run_compose "$slot" build cliproxy
    run_compose "$slot" up -d cliproxy
}

cmd_logs() {
    local slot
    slot="$(require_slot "${1:-1}")"
    run_compose "$slot" logs -f
}

cmd_sync_db() {
    local slot
    slot="$(require_slot "${1:-1}")"
    local stable_pg="ai-postgres-1"
    local dev_pg="aidev${slot}-postgres-1"

    # Verify stable postgres is running
    docker ps -q -f name="^/${stable_pg}$" >/dev/null || die "Stable database ${stable_pg} is not running."
    # Verify dev postgres is running
    docker ps -q -f name="^/${dev_pg}$" >/dev/null || die "Dev database ${dev_pg} is not running. Start the slot first."

    echo "Syncing stable LiteLLM database to Slot ${slot} ..."
    # Dump from stable postgres and restore to dev postgres
    docker exec "$stable_pg" pg_dump -U postgres -d litellm --clean --no-owner --no-privileges \
        | docker exec -i "$dev_pg" psql -U postgres -d litellm >/dev/null

    echo "✓ Database synced successfully to Slot ${slot}."
    echo "Restarting services to reload configurations ..."
    run_compose "$slot" restart litellm gateway-engine
    echo "✓ Slot ${slot} ready."
}

cmd_test() {
    local slot
    slot="$(require_slot "${1:-1}")"
    shift 1 2>/dev/null || true
    slot_ports "$slot"
    local gateway_url="http://localhost:${GATEWAY_ENGINE_PORT}"
    local master_key=""
    if [[ -f "$ENV_FILE" ]]; then
        master_key="$(grep -E '^LITELLM_MASTER_KEY=' "$ENV_FILE" | cut -d= -f2- | tr -d '"' || true)"
    fi

    local op_run_prefix=""
    if [ -f "$HOME/.op-token" ]; then
        export OP_SERVICE_ACCOUNT_TOKEN
        OP_SERVICE_ACCOUNT_TOKEN=$(cat "$HOME/.op-token")
        op_run_prefix="op run --"
    elif grep -q 'op://' "$ENV_FILE" 2>/dev/null; then
        die "Secrets in $ENV_FILE are 1Password references, but ~/.op-token is missing."
    fi

    echo "running integration tests against ${gateway_url} ..."
    # shellcheck disable=SC2086
    GATEWAY_URL="$gateway_url" LITELLM_MASTER_KEY="$master_key" \
        $op_run_prefix python3 -m pytest "${SCRIPT_DIR}/tests/integration/" -m integration -v "$@"
}

# --- Mock tier: real gateway-engine + litellm + canned upstream, no OAuth ---------

cmd_start_mock() {
    local slot
    slot="$(require_slot "${1:-9}")"
    slot_ports "$slot"
    echo "starting MOCK slot ${slot}: gateway-engine=:${GATEWAY_ENGINE_PORT} (no OAuth, canned upstream)"
    # No seed_auth_volume — the mock upstream needs no credentials.
    run_compose "$slot" -f "$MOCK_OVERLAY" up -d --remove-orphans --build postgres cliproxy litellm redis gateway-engine credential-prober
    echo ""
    echo "mock slot ${slot} is up: gateway-engine http://localhost:${GATEWAY_ENGINE_PORT}/health"
}

cmd_test_mock() {
    local slot
    slot="$(require_slot "${1:-9}")"
    shift 1 2>/dev/null || true
    slot_ports "$slot"
    local gateway_url="http://localhost:${GATEWAY_ENGINE_PORT}"
    local master_key="sk-ci-mock"
    if [[ -f "$ENV_FILE" ]]; then
        master_key="$(grep -E '^LITELLM_MASTER_KEY=' "$ENV_FILE" | cut -d= -f2- | tr -d '"' || echo sk-ci-mock)"
    fi
    echo "running MOCK-tier tests against ${gateway_url} (ALLOW_MODEL_SKIP=0) ..."
    # shellcheck disable=SC2086
    GATEWAY_URL="$gateway_url" LITELLM_MASTER_KEY="$master_key" ALLOW_MODEL_SKIP=0 \
        python3 -m pytest "${SCRIPT_DIR}/tests/integration/" -m mock -v "$@"
}

cmd_stop_mock() {
    local slot
    slot="$(require_slot "${1:-9}")"
    echo "stopping MOCK slot ${slot} ..."
    run_compose "$slot" -f "$MOCK_OVERLAY" down -v
    echo "mock slot ${slot} stopped"
}

cmd_list() {
    docker ps \
        --filter "label=com.docker.compose.project" \
        --format 'table {{.Names}}\t{{.Label "com.docker.compose.project"}}\t{{.Status}}\t{{.Ports}}' \
        | awk 'NR == 1 || $2 ~ /^aidev/'
}

cmd_cleanup() {
    echo "Purging all aidev containers and volumes..."
    docker ps -a \
        --filter "label=com.docker.compose.project" \
        --format '{{.ID}}\t{{.Label "com.docker.compose.project"}}' \
        | awk '$2 ~ /^aidev/ {print $1}' \
        | xargs -r docker rm -f
    docker volume ls --filter "name=aidev" --format "{{.Name}}" | xargs -r docker volume rm
    echo "Cleanup complete."
}


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------

CMD="${1:-}"
shift || true

case "$CMD" in
    start)             cmd_start "$@" ;;
    stop)              cmd_stop "$@" ;;
    rebuild)           cmd_rebuild "$@" ;;
    rebuild-cliproxy)  cmd_rebuild_cliproxy "$@" ;;
    logs)              cmd_logs "$@" ;;
    sync-db)           cmd_sync_db "$@" ;;
    test)              cmd_test "$@" ;;
    start-mock)        cmd_start_mock "$@" ;;
    test-mock)         cmd_test_mock "$@" ;;
    stop-mock)         cmd_stop_mock "$@" ;;
    list)              cmd_list ;;
    cleanup)           cmd_cleanup ;;
    *)
        echo "Usage: $0 {start|stop|rebuild|rebuild-cliproxy|logs|sync-db|test|start-mock|test-mock|stop-mock|list|cleanup} [slot]"
        echo ""
        echo "Slot 0 is reserved (stable stack). Default slot: 1"
        echo ""
        echo "Port layout for slot N:"
        echo "  gateway-engine  4000+N*10"
        echo "  litellm UI  4001+N*10"
        echo "  cliproxy    8317+N*10"
        exit 1
        ;;
esac
