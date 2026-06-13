#!/usr/bin/env bash
# Unit checks for dev-env.sh behavior that can run without Docker.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

fail() {
    echo "FAIL: $*" >&2
    exit 1
}

assert_contains() {
    local haystack="$1"
    local needle="$2"
    [[ "$haystack" == *"$needle"* ]] || fail "expected output to contain: $needle"
}

make_sandbox() {
    local tmp
    tmp="$(mktemp -d)"
    mkdir -p "$tmp/bin" "$tmp/home/.cli-proxy-api"
    cp "$REPO_ROOT/dev-env.sh" "$tmp/dev-env.sh"
    chmod +x "$tmp/dev-env.sh"
    printf '%s\n' "$tmp"
}

write_docker_stub() {
    local tmp="$1"
    cat >"$tmp/bin/docker" <<'STUB'
#!/usr/bin/env bash
set -euo pipefail

printf '%s\n' "$*" >>"${DOCKER_STUB_LOG:?}"

case "${1:-}" in
    ps)
        if [[ "$*" == *"label=com.docker.compose.project"* ]]; then
            if [[ "$*" == *"--format"* && "$*" != *"table"* ]]; then
                printf 'abc123\taidev1\n'
                printf 'def456\tother-project\n'
            else
                printf 'NAMES\tPROJECT\tSTATUS\tPORTS\n'
                printf 'TESTING-litellm-dev\taidev1\tUp 2 minutes (healthy)\t0.0.0.0:4011->4000/tcp\n'
                printf 'unrelated-service\tother-project\tUp 2 minutes\t\n'
            fi
        else
            printf 'NAMES\tSTATUS\tPORTS\n'
        fi
        ;;
    volume)
        if [[ "${2:-}" == "ls" ]]; then
            printf 'aidev1_dev_auth\n'
        fi
        ;;
    run)
        printf 'seeded 0 entries\n'
        ;;
    rm)
        ;;
    compose)
        if [[ "$*" == *" up -d --build"* ]]; then
            exit 1
        fi
        ;;
esac
STUB
    chmod +x "$tmp/bin/docker"
}

test_list_uses_compose_project_labels() {
    local tmp output
    tmp="$(make_sandbox)"
    export DOCKER_STUB_LOG="$tmp/docker.log"
    write_docker_stub "$tmp"

    output="$(PATH="$tmp/bin:$PATH" HOME="$tmp/home" "$tmp/dev-env.sh" list)"

    assert_contains "$output" "TESTING-litellm-dev"
    assert_contains "$output" "aidev1"
    [[ "$output" != *"unrelated-service"* ]] || fail "list included a non-aidev compose project"
    ! grep -q 'name=aidev' "$DOCKER_STUB_LOG" || fail "list used stale name=aidev filter"
}

test_start_retries_with_wait_after_initial_compose_failure() {
    local tmp output
    tmp="$(make_sandbox)"
    export DOCKER_STUB_LOG="$tmp/docker.log"
    write_docker_stub "$tmp"

    output="$(PATH="$tmp/bin:$PATH" HOME="$tmp/home" DEV_ENV_WAIT_TIMEOUT=600 "$tmp/dev-env.sh" start 1 2>&1)"

    assert_contains "$output" "initial compose wait failed"
    grep -q 'compose -f .* up -d --build --wait --wait-timeout 600' "$DOCKER_STUB_LOG" \
        || fail "start did not use an initial wait-enabled compose up"
    grep -q 'compose -f .* up -d --wait --wait-timeout 600' "$DOCKER_STUB_LOG" \
        || fail "start did not retry with a wait-only compose up"
}

test_cleanup_removes_aidev_project_labeled_containers() {
    local tmp
    tmp="$(make_sandbox)"
    export DOCKER_STUB_LOG="$tmp/docker.log"
    write_docker_stub "$tmp"

    PATH="$tmp/bin:$PATH" HOME="$tmp/home" "$tmp/dev-env.sh" cleanup >/dev/null

    grep -q 'rm -f abc123' "$DOCKER_STUB_LOG" || fail "cleanup did not remove aidev-labeled containers"
    ! grep -q 'rm -f def456' "$DOCKER_STUB_LOG" || fail "cleanup removed non-aidev containers"
}

test_list_uses_compose_project_labels
test_start_retries_with_wait_after_initial_compose_failure
test_cleanup_removes_aidev_project_labeled_containers

echo "dev-env shell tests passed"
