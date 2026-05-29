#!/usr/bin/env bash
# dev-env.sh — manage isolated dev gateway stacks for parallel feature development
#
# Usage:
#   ./dev-env.sh start   [slot]          build & start dev stack (default slot=1)
#   ./dev-env.sh stop    [slot]          stop & remove dev stack and its auth volume
#   ./dev-env.sh rebuild [slot]          rebuild translator only (fast after translator.py edit)
#   ./dev-env.sh rebuild-cliproxy [slot] rebuild cliproxy from fork source
#   ./dev-env.sh logs    [slot]          tail all dev logs
#   ./dev-env.sh test    [slot]          run integration tests against dev slot
#   ./dev-env.sh list                    show all running aidev* containers
#
# Port layout (slot N):
#   translator  4000+N*10   (e.g. slot 1 → 4010)
#   litellm UI  4001+N*10   (e.g. slot 1 → 4011)
#   cliproxy    8317+N*10   (e.g. slot 1 → 8327)
#
# Slot 0 is reserved for the stable stack.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
COMPOSE_FILE="${SCRIPT_DIR}/docker-compose.dev.yml"
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
    TRANSLATOR_PORT=$(( 4000 + slot * 10 ))
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
         "DEV_TRANSLATOR_PORT=${TRANSLATOR_PORT}" \
         "DEV_LITELLM_PORT=${LITELLM_PORT}" \
         "DEV_CLIPROXY_PORT=${CLIPROXY_PORT}" \
         $cfg_var
}

run_compose() {
    local slot="$1"; shift
    local env_vars
    env_vars="$(compose_env "$slot")"
    # Load .env for LITELLM_MASTER_KEY and CLIPROXY_API_KEY
    if [[ -f "$ENV_FILE" ]]; then
        set -o allexport
        # shellcheck disable=SC1090
        source "$ENV_FILE"
        set +o allexport
    fi
    env $env_vars docker compose -f "$COMPOSE_FILE" "$@"
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
    echo "starting dev slot ${slot}: translator=:${TRANSLATOR_PORT}  litellm=:${LITELLM_PORT}  cliproxy=:${CLIPROXY_PORT}"
    seed_auth_volume "$slot"
    run_compose "$slot" up -d --build
    echo ""
    echo "dev slot ${slot} is up:"
    echo "  translator  http://localhost:${TRANSLATOR_PORT}/health"
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
    echo "rebuilding translator for slot ${slot} ..."
    run_compose "$slot" build translator
    run_compose "$slot" up -d translator
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

cmd_test() {
    local slot
    slot="$(require_slot "${1:-1}")"
    shift 1 2>/dev/null || true
    slot_ports "$slot"
    local gateway_url="http://localhost:${TRANSLATOR_PORT}"
    local master_key=""
    if [[ -f "$ENV_FILE" ]]; then
        master_key="$(grep -E '^LITELLM_MASTER_KEY=' "$ENV_FILE" | cut -d= -f2- | tr -d '"' || true)"
    fi
    echo "running integration tests against ${gateway_url} ..."
    GATEWAY_URL="$gateway_url" LITELLM_MASTER_KEY="$master_key" \
        python3 -m pytest "${SCRIPT_DIR}/tests/integration/" -m integration -v "$@"
}

cmd_list() {
    docker ps --filter "name=aidev" --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"
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
    test)              cmd_test "$@" ;;
    list)              cmd_list ;;
    *)
        echo "Usage: $0 {start|stop|rebuild|rebuild-cliproxy|logs|test|list} [slot]"
        echo ""
        echo "Slot 0 is reserved (stable stack). Default slot: 1"
        echo ""
        echo "Port layout for slot N:"
        echo "  translator  4000+N*10"
        echo "  litellm UI  4001+N*10"
        echo "  cliproxy    8317+N*10"
        exit 1
        ;;
esac
