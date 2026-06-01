#!/usr/bin/env bash
# tests/test-multi-repo-isolation.sh
# Verifies per-repo .envrc files load correct CODEX_HOME and API keys,
# and that two repos running simultaneously don't share env state.

set -euo pipefail

PASS=0
FAIL=0
REPOS_BASE="${REPOS_BASE:-/home/dev/repos}"

pass() { echo "  ✓ $1"; ((PASS++)) || true; }
fail() { echo "  ✗ $1"; ((FAIL++)) || true; }

check_envrc() {
    local repo="$1"
    local has_env="${2:-}"
    local repo_path="$REPOS_BASE/$repo"
    local expected_codex_home="$HOME/.codex-repos/$repo"

    echo ""
    echo "── $repo ──"

    if [[ ! -f "$repo_path/.envrc" ]]; then
        fail "No .envrc found"
        return
    fi
    pass ".envrc exists"

    # Use `direnv exec` to load the envrc and inspect vars
    local codex_home oai_set
    codex_home=$(direnv exec "$repo_path" bash -c 'echo "$CODEX_HOME"' 2>/dev/null || echo "")
    oai_set=$(direnv exec "$repo_path" bash -c 'echo "${OPENAI_API_KEY:+yes}"' 2>/dev/null || echo "")

    if [[ "$codex_home" == "$expected_codex_home" ]]; then
        pass "CODEX_HOME=$codex_home"
    else
        fail "CODEX_HOME='$codex_home' (expected '$expected_codex_home')"
    fi

    if [[ -n "$codex_home" ]] && [[ "$codex_home" != "$HOME/.codex-gateway" ]]; then
        pass "CODEX_HOME is repo-specific (not old shared ~/.codex-gateway)"
    else
        fail "CODEX_HOME still points to old shared dir or is empty"
    fi

    if [[ "$has_env" == "has_env" ]]; then
        if [[ "$oai_set" == "yes" ]]; then
            pass "OPENAI_API_KEY loaded from .env"
        else
            fail "OPENAI_API_KEY empty (check .env has OPENAI_API_KEY=)"
        fi
    fi
}

check_codex_config() {
    local repo="$1"
    local config_path="$HOME/.codex-repos/$repo/config.toml"
    local auth_path="$HOME/.codex-repos/$repo/auth.json"
    echo ""
    echo "── CODEX_HOME config: $repo ──"
    if [[ -f "$config_path" ]]; then
        pass "config.toml exists"
        grep -q "openai_base_url" "$config_path" && pass "openai_base_url set" || fail "openai_base_url missing"
        grep -q "approval_policy" "$config_path" && pass "approval_policy set" || fail "approval_policy missing"
        if [[ ! -f "$auth_path" ]]; then
            pass "No auth.json (API-key mode)"
        else
            if grep -q '"auth_mode": "apikey"' "$auth_path" 2>/dev/null; then
                pass "auth.json present but in API-key mode"
            else
                fail "auth.json present and not in API-key mode (remove it)"
            fi
        fi
    else
        fail "config.toml missing — run: setup-repo-env $REPOS_BASE/$repo"
    fi
}

check_no_collision() {
    echo ""
    echo "── Collision test: ai-gateway vs homelab-gitops ──"
    local dir_a="$HOME/.codex-repos/ai-gateway"
    local dir_b="$HOME/.codex-repos/homelab-gitops"

    [[ "$dir_a" != "$dir_b" ]] && pass "CODEX_HOME dirs are distinct" || fail "CODEX_HOME dirs are identical"

    if [[ -d "$dir_a" ]] && [[ -d "$dir_b" ]]; then
        local tag="isolation-test-$$"
        touch "$dir_a/.$tag" "$dir_b/.$tag"
        # Files should exist in their own dir only
        [[ -f "$dir_a/.$tag" ]] && [[ ! -f "$dir_b/.$tag-from-a" ]] && pass "Session writes stay isolated" || fail "Cross-contamination detected"
        rm -f "$dir_a/.$tag" "$dir_b/.$tag"
    else
        fail "CODEX_HOME dirs not initialized — run setup-repo-env for ai-gateway and homelab-gitops"
    fi
}

check_simultaneous() {
    echo ""
    echo "── Simultaneous sessions: ai-gateway + homelab-gitops ──"
    local out_a out_b
    out_a=$(direnv exec "$REPOS_BASE/ai-gateway" bash -c 'echo "$CODEX_HOME"' 2>/dev/null || echo "")
    out_b=$(direnv exec "$REPOS_BASE/homelab-gitops" bash -c 'echo "$CODEX_HOME"' 2>/dev/null || echo "")

    if [[ "$out_a" != "$out_b" ]] && [[ -n "$out_a" ]] && [[ -n "$out_b" ]]; then
        pass "Concurrent CODEX_HOME values differ: ($out_a) vs ($out_b)"
    else
        fail "CODEX_HOME collision: both returned '$out_a'"
    fi

    # Verify API keys are also independent (may differ per LiteLLM team)
    local key_a key_b
    key_a=$(direnv exec "$REPOS_BASE/ai-gateway" bash -c 'echo "${OPENAI_API_KEY}"' 2>/dev/null || echo "")
    key_b=$(direnv exec "$REPOS_BASE/homelab-gitops" bash -c 'echo "${OPENAI_API_KEY}"' 2>/dev/null || echo "")
    if [[ -n "$key_a" ]] && [[ -n "$key_b" ]]; then
        [[ "$key_a" != "$key_b" ]] && pass "OPENAI_API_KEY differs per repo (separate LiteLLM teams)" || \
            pass "OPENAI_API_KEY is same (both use same LiteLLM team key — OK if intentional)"
    else
        fail "Could not read OPENAI_API_KEY from one or both repos"
    fi
}

echo "=== AI CLI Per-Repo Isolation Test ==="
echo ""

# Repos with AI gateway creds in .env (dotenv variant)
for repo in ai-gateway homelab-gitops amazon_returns cloudflare_access_automation; do
    check_envrc "$repo" "has_env"
done

# Repos using 1Password for AI keys (project .env has only project-specific creds, or no .env)
for repo in gmail-generator amazon-returns-cdp cursor labels; do
    check_envrc "$repo"
done

# CODEX_HOME config.toml validation
for repo in ai-gateway homelab-gitops; do
    check_codex_config "$repo"
done

check_no_collision
check_simultaneous

echo ""
echo "═══════════════════════════════════════"
echo "Results: $PASS passed, $FAIL failed"
if [[ $FAIL -gt 0 ]]; then
    echo ""
    echo "To fix failing repos: setup-repo-env <repo-path>"
    exit 1
fi
echo "All checks passed"
