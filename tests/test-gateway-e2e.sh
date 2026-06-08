#!/usr/bin/env bash
# tests/test-gateway-e2e.sh
# End-to-end smoke test: hit every CLI endpoint + spot-check models from each repo.
# Uses the API key loaded by direnv for each repo.
#
# CI mock mode (health + WebSocket only, no direnv/repos required):
#   GATEWAY_E2E_CI=1 GATEWAY_URL=http://localhost:4010 bash tests/test-gateway-e2e.sh

set -euo pipefail

PASS=0; FAIL=0; SKIP=0
GATEWAY="${GATEWAY_URL:-http://localhost:4000}"
TIMEOUT=30

# ── registry pull (optional) ───────────────────────────────────────────────

if [[ "${PULL_IMAGES:-}" == "1" ]]; then
    echo "Pulling images from registry..."
    docker compose pull --quiet || echo "Warning: docker compose pull failed"
fi

pass() { echo "  ✓ $1"; ((PASS++)) || true; }
fail() { echo "  ✗ $1"; ((FAIL++)) || true; }
skip() { echo "  ○ $1 (skipped — no key)"; ((SKIP++)) || true; }

# ── helpers ────────────────────────────────────────────────────────────────

call_responses() {
    local model="$1" key="$2" label="$3"
    local body
    body=$(printf '{"model":"%s","input":[{"role":"user","content":"Reply with one word: pong"}],"stream":false}' "$model")
    local out
    out=$(curl -sf --max-time $TIMEOUT "$GATEWAY/v1/responses" \
        -H "Authorization: Bearer $key" \
        -H "Content-Type: application/json" \
        -d "$body" 2>&1) || { fail "$label → curl error: $out"; return; }
    echo "$out" | python3 -c "
import sys,json
d=json.load(sys.stdin)
status=d.get('status','?')
text=''.join(p.get('text','') for o in d.get('output',[]) for p in o.get('content',[]) if p.get('type')=='output_text')
if status in ('completed','in_progress') and text:
    print('  ✓ $label → ' + repr(text[:60]))
else:
    print('  ✗ $label → status=' + status + ' output=' + repr(d)[:120])
    sys.exit(1)
" && ((PASS++)) || true || ((FAIL++)) || true
}

call_messages() {
    local model="$1" key="$2" label="$3"
    local body
    body=$(printf '{"model":"%s","max_tokens":20,"messages":[{"role":"user","content":"Reply with one word: pong"}]}' "$model")
    local out
    out=$(curl -sf --max-time $TIMEOUT "$GATEWAY/v1/messages" \
        -H "x-api-key: $key" \
        -H "anthropic-version: 2023-06-01" \
        -H "Content-Type: application/json" \
        -d "$body" 2>&1) || { fail "$label → curl error: $out"; return; }
    echo "$out" | python3 -c "
import sys,json
d=json.load(sys.stdin)
text=''.join(b.get('text','') for b in d.get('content',[]) if b.get('type')=='text')
if d.get('type')=='message' and text:
    print('  ✓ $label → ' + repr(text[:60]))
else:
    print('  ✗ $label → ' + repr(d)[:120])
    sys.exit(1)
" && ((PASS++)) || true || ((FAIL++)) || true
}

call_gemini() {
    local model="$1" key="$2" label="$3"
    local body='{"contents":[{"role":"user","parts":[{"text":"Reply with one word: pong"}]}]}'
    local out
    out=$(curl -sf --max-time $TIMEOUT "$GATEWAY/v1beta/models/${model}:generateContent?key=${key}" \
        -H "Content-Type: application/json" \
        -d "$body" 2>&1) || { fail "$label → curl error: $out"; return; }
    echo "$out" | python3 -c "
import sys,json
d=json.load(sys.stdin)
text=''.join(p.get('text','') for c in d.get('candidates',[]) for part in c.get('content',{}).get('parts',[]) for p in [part])
if text:
    print('  ✓ $label → ' + repr(text[:60]))
else:
    print('  ✗ $label → ' + repr(d)[:120])
    sys.exit(1)
" && ((PASS++)) || true || ((FAIL++)) || true
}

# ── per-repo tests ──────────────────────────────────────────────────────────

test_repo() {
    local repo="$1"; shift
    local repo_path="/home/dev/repos/$repo"
    echo ""
    echo "══ $repo ══"

    local oai_key claude_key gemini_key codex_home
    oai_key=$(direnv exec "$repo_path" bash -c 'echo "$OPENAI_API_KEY"' 2>/dev/null || echo "")
    claude_key=$(direnv exec "$repo_path" bash -c 'echo "$ANTHROPIC_API_KEY"' 2>/dev/null || echo "")
    gemini_key=$(direnv exec "$repo_path" bash -c 'echo "$GEMINI_API_KEY"' 2>/dev/null || echo "")
    codex_home=$(direnv exec "$repo_path" bash -c 'echo "$CODEX_HOME"' 2>/dev/null || echo "")

    echo "  CODEX_HOME: $codex_home"

    # Codex / Responses API
    if [[ -n "$oai_key" ]]; then
        call_responses "gpt-5-5"   "$oai_key" "codex gpt-5-5"
        call_responses "gpt-5-4"   "$oai_key" "codex gpt-5-4"
        call_responses "gpt-5-4-mini" "$oai_key" "codex gpt-5-4-mini"
    else
        skip "codex (no OPENAI_API_KEY)"
    fi

    # Claude / Messages API
    if [[ -n "$claude_key" ]]; then
        call_messages "claude-sonnet-4-6" "$claude_key" "claude claude-sonnet-4-6"
        call_messages "claude-haiku-4-5"  "$claude_key" "claude claude-haiku-4-5"
    else
        skip "claude (no ANTHROPIC_API_KEY)"
    fi

    # Gemini
    if [[ -n "$gemini_key" ]]; then
        call_gemini "gemini-3-flash"   "$gemini_key" "gemini gemini-3-flash"
        call_gemini "gemini-2-5-flash" "$gemini_key" "gemini gemini-2-5-flash"
    else
        skip "gemini (no GEMINI_API_KEY)"
    fi
}

# ── WebSocket endpoint check ────────────────────────────────────────────────

test_websocket() {
    echo ""
    echo "══ WebSocket /v1/responses (should return 101, not 403) ══"
    local http_code
    http_code=$(curl -so /dev/null -w "%{http_code}" --max-time 5 \
        -H "Connection: Upgrade" -H "Upgrade: websocket" \
        -H "Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==" \
        -H "Sec-WebSocket-Version: 13" \
        "$GATEWAY/v1/responses" 2>/dev/null || echo "000")
    if [[ "$http_code" == "101" ]]; then
        pass "WebSocket upgrade returns 101 → clean close frame (Codex falls back silently)"
    elif [[ "$http_code" == "403" ]]; then
        fail "WebSocket upgrade returns 403 — container needs rebuild with latest gateway-engine"
    else
        pass "WebSocket upgrade returns $http_code (fallback triggered)"
    fi
}

# ── gateway health ──────────────────────────────────────────────────────────

echo "=== Gateway E2E Test ==="
echo "Gateway: $GATEWAY"
health=$(curl -sf --max-time 5 "$GATEWAY/health" 2>/dev/null | python3 -c "import sys,json; print(json.load(sys.stdin).get('status','?'))" 2>/dev/null || echo "unreachable")
echo "Health: $health"
if [[ "$health" != "ok" ]]; then
    echo "Gateway unreachable — aborting"
    echo "Checking for failed containers..."
    docker ps -a --filter "status=exited"
    echo "Last 20 lines of logs for failed containers:"
    for container in $(docker ps -a --filter "status=exited" --format "{{.Names}}"); do
        echo "--- $container ---"
        docker logs "$container" | tail -n 20
    done
    exit 1
fi

test_websocket

if [[ "${GATEWAY_E2E_CI:-}" == "1" ]]; then
    echo ""
    echo "CI mock mode — skipping per-repo provider tests"
    echo "══════════════════════════════════════════"
    echo "Results: $PASS passed, $FAIL failed, $SKIP skipped"
    [[ $FAIL -eq 0 ]] && echo "All checks passed" || exit 1
fi

# Test key repos
for repo in ai-gateway homelab-gitops amazon_returns cloudflare_access_automation; do
    test_repo "$repo"
done

echo ""
echo "══════════════════════════════════════════"
echo "Results: $PASS passed, $FAIL failed, $SKIP skipped"
[[ $FAIL -eq 0 ]] && echo "All checks passed" || exit 1
