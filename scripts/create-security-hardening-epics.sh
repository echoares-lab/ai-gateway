#!/usr/bin/env bash
# Create epics + sub-issues for post-audit security/hardening work (2026-06-13).
set -euo pipefail

REPO="echoares-lab/ai-gateway"

create_epic() {
  local title="$1"
  local body="$2"
  local labels="$3"
  gh issue create --repo "$REPO" --title "$title" --body "$body" --label "$labels"
}

create_issue() {
  local title="$1"
  local body="$2"
  local labels="$3"
  gh issue create --repo "$REPO" --title "$title" --body "$body" --label "$labels"
}

# ── Epic 305: WebSocket auth hardening ───────────────────────────────────────
EPIC305=$(create_epic \
  "Roadmap Epic: Codex WebSocket authentication hardening" \
  "$(cat <<'EOF'
## Summary
Harden Codex WebSocket proxy authentication in gateway-engine. Audit found unauthenticated connections are accepted when no auth header/query is provided, and weak sk-* token validation.

## Problem
`responses_websocket` defaults `is_authorized = True` and only validates when `client_auth` is present. Missing credentials allow proxying to CLIProxy. Any `sk-*` string ≥10 chars passes without LiteLLM validation.

## Why now
Post-main audit (2026-06-13) ranked this Critical (#1). Public gateway on :4000 may expose WebSocket endpoint via tunnel.

## Scope
- Fail closed when no credentials provided
- Validate virtual keys against LiteLLM where applicable
- Regression tests for no-auth and invalid-token rejection
- Stop logging raw auth headers/query params

## Non-goals
- Changing HTTP chat-completions auth (separate LiteLLM path)
- WebSocket policy engine parity (Epic #38 sub-issues)

## Dependencies
- None (start immediately)

## Affected files
- `services/gateway-engine/main.py`
- `services/gateway-engine/test_gateway_engine_websocket_policy.py`
EOF
)" \
  "type:security,area:translator,priority:high,status:ready")

EPIC305_NUM="${EPIC305##*/}"
echo "Epic 305: #$EPIC305_NUM"

I305_1=$(create_issue \
  "fix(security): fail-closed Codex WebSocket when auth missing" \
  "$(cat <<EOF
## Summary
Change WebSocket auth to default \`is_authorized = False\` and require valid credentials before proxying to CLIProxy.

## Problem
\`responses_websocket\` sets \`is_authorized = True\` before checking \`client_auth\`. Empty auth bypasses all checks.

## Acceptance criteria
- [ ] Connection without Authorization/api-key/?key= is rejected with close code 1008
- [ ] Valid LITELLM_MASTER_KEY still accepted
- [ ] Unit test covers no-auth rejection

## Required tests
- Extend \`test_gateway_engine_websocket_policy.py\`

## Dependencies
- Parent epic: #$EPIC305_NUM

## Affected files
- \`services/gateway-engine/main.py\`
- \`services/gateway-engine/test_gateway_engine_websocket_policy.py\`
EOF
)" \
  "type:security,area:translator,priority:high,status:ready")

I305_2=$(create_issue \
  "fix(security): validate WebSocket sk-* tokens against LiteLLM" \
  "$(cat <<EOF
## Summary
Replace permissive \`sk-*\` length check with LiteLLM virtual-key validation (or shared auth helper used by HTTP routes).

## Problem
Any string matching \`sk-\` prefix and length ≥10 is accepted without verification.

## Acceptance criteria
- [ ] Invalid sk-* tokens rejected on WebSocket
- [ ] Valid virtual keys from LiteLLM accepted
- [ ] Tests for valid/invalid sk-* paths

## Dependencies
- Parent epic: #$EPIC305_NUM
- Depends on: ${I305_1##*/} (fail-closed baseline first)

## Affected files
- \`services/gateway-engine/main.py\`
- \`services/gateway-engine/test_gateway_engine_websocket_policy.py\`
EOF
)" \
  "type:security,area:translator,priority:high,status:ready")

I305_3=$(create_issue \
  "fix(security): redact WebSocket auth from logs" \
  "$(cat <<EOF
## Summary
Remove or redact logging of full WebSocket headers and query params that may contain API keys.

## Acceptance criteria
- [ ] No raw Authorization/api-key/key values in info logs
- [ ] Use existing \`_admin_redact\` or equivalent

## Dependencies
- Parent epic: #$EPIC305_NUM

## Affected files
- \`services/gateway-engine/main.py\`
EOF
)" \
  "type:security,area:translator,priority:medium,status:ready")

echo "  #${I305_1##*/} fail-closed"
echo "  #${I305_2##*/} validate sk-*"
echo "  #${I305_3##*/} redact logs"

# ── Epic 306: Admin auth unification ─────────────────────────────────────────
EPIC306=$(create_epic \
  "Roadmap Epic: Unified gateway admin authentication" \
  "$(cat <<'EOF'
## Summary
Consolidate split admin auth (`GATEWAY_ENGINE_ADMIN_KEY` vs `ADMIN_API_KEY`) and protect read-only admin endpoints when gateway is publicly exposed.

## Problem
Mutating admin routes in main.py use `GATEWAY_ENGINE_ADMIN_KEY`; admin_api.py uses `ADMIN_API_KEY`. Read-only `/admin/status`, `/admin/credentials`, etc. have no auth on port 4000.

## Scope
- Single env var + shared `_require_admin_key` in core/admin_shared.py
- Optional auth gate for read-only admin panels (env-controlled)
- RUNBOOK documentation

## Non-goals
- LiteLLM UI auth changes
- CPA-Manager auth

## Dependencies
- None (parallel with Epic WebSocket)

## Affected files
- `services/gateway-engine/main.py`
- `services/gateway-engine/core/admin_shared.py`
- `services/gateway-engine/admin_api.py`
- `RUNBOOK.md`
EOF
)" \
  "type:security,area:translator,priority:high,status:ready")

EPIC306_NUM="${EPIC306##*/}"
echo "Epic 306: #$EPIC306_NUM"

I306_1=$(create_issue \
  "refactor(admin): unify GATEWAY_ENGINE_ADMIN_KEY and ADMIN_API_KEY" \
  "$(cat <<EOF
## Summary
Single admin key env var and one \`_require_admin_key\` implementation used by main.py and admin_api.py.

## Acceptance criteria
- [ ] One canonical env var (prefer \`GATEWAY_ENGINE_ADMIN_KEY\`, alias \`ADMIN_API_KEY\` deprecated with log warning)
- [ ] Duplicate function removed from main.py; import from core/admin_shared.py
- [ ] All admin mutation tests pass

## Dependencies
- Parent epic: #$EPIC306_NUM

## Affected files
- \`services/gateway-engine/main.py\`
- \`services/gateway-engine/core/admin_shared.py\`
- \`services/gateway-engine/admin_api.py\`
EOF
)" \
  "type:code-health,area:translator,priority:high,status:ready")

I306_2=$(create_issue \
  "feat(security): optional auth for read-only admin status endpoints" \
  "$(cat <<EOF
## Summary
Add env-gated auth (\`GATEWAY_ENGINE_ADMIN_READ_AUTH=true\`) requiring x-admin-key for GET /admin/status, /admin/credentials, /admin/analytics/tokens, /admin/status/policy, /admin/dashboard.

## Acceptance criteria
- [ ] Default off (backward compatible for operator-local)
- [ ] When enabled, unauthenticated GET returns 403
- [ ] Tests for both modes

## Dependencies
- Parent epic: #$EPIC306_NUM
- Depends on: ${I306_1##*/}

## Affected files
- \`services/gateway-engine/main.py\`
- \`services/gateway-engine/test_gateway_engine_admin_api.py\`
EOF
)" \
  "type:security,area:translator,priority:medium,status:ready")

I306_3=$(create_issue \
  "docs: document unified admin auth in RUNBOOK" \
  "$(cat <<EOF
## Summary
Document canonical admin key env var, read-auth toggle, and header requirements in RUNBOOK.md.

## Dependencies
- Parent epic: #$EPIC306_NUM
- Depends on: ${I306_1##*/}

## Affected files
- \`RUNBOOK.md\`
- \`.env.example\`
EOF
)" \
  "type:docs,area:docs,priority:medium,status:ready")

echo "  #${I306_1##*/} unify keys"
echo "  #${I306_2##*/} read auth"
echo "  #${I306_3##*/} runbook"

# ── Epic 307: Documentation path sweep ───────────────────────────────────────
EPIC307=$(create_epic \
  "Roadmap Epic: Documentation path drift cleanup (gateway-engine.py → main.py)" \
  "$(cat <<'EOF'
## Summary
Replace stale `gateway-engine.py` and `test_gateway-engine.py` references across docs, scripts, and issue templates with current paths (`main.py`, `test_gateway_engine*.py`).

## Problem
~30+ references to renamed/removed files mislead agents and operators. AGENTS.md updated; CLAUDE.md, RUNBOOK.md, docs/, issue templates still stale.

## Scope
- CLAUDE.md, RUNBOOK.md, AGENT_DISPATCH.md, WORKTREES.md, dev-env.sh
- docs/ARCHITECTURE.md, CLIENT_COMPATIBILITY.md, CONFIG_PROMOTION.md, ADAPTIVE_ROUTING.md
- .github/ISSUE_TEMPLATE/repo-improvement.yml
- issues/*.md hotspot paths

## Non-goals
- Architecture changes
- OpenAPI regen (separate issue)

## Dependencies
- None (fully parallel)

## Affected files
- Multiple `*.md`, `dev-env.sh`, issue templates
EOF
)" \
  "type:docs,area:docs,priority:medium,status:ready")

EPIC307_NUM="${EPIC307##*/}"
echo "Epic 307: #$EPIC307_NUM"

I307_1=$(create_issue \
  "docs: update CLAUDE.md RUNBOOK AGENT_DISPATCH to main.py paths" \
  "$(cat <<EOF
## Summary
Fix stale \`gateway-engine.py\` and \`test_gateway-engine.py\` references in top-level agent/operator docs.

## Acceptance criteria
- [ ] Zero references to \`gateway-engine.py\` in CLAUDE.md, RUNBOOK.md, AGENT_DISPATCH.md, WORKTREES.md
- [ ] Test commands use \`test_gateway_engine*.py\`

## Dependencies
- Parent epic: #$EPIC307_NUM

## Affected files
- \`CLAUDE.md\`, \`RUNBOOK.md\`, \`AGENT_DISPATCH.md\`, \`WORKTREES.md\`, \`dev-env.sh\`
EOF
)" \
  "type:docs,area:docs,priority:medium,status:ready")

I307_2=$(create_issue \
  "docs: update docs/ architecture and compatibility path references" \
  "$(cat <<EOF
## Summary
Fix \`gateway-engine.py\` references in docs/ARCHITECTURE.md, CLIENT_COMPATIBILITY.md, CONFIG_PROMOTION.md, ADAPTIVE_ROUTING.md, MCP_TOOL_VISIBILITY.md, ROUTING_AND_FAILOVER_STRATEGY.md.

## Dependencies
- Parent epic: #$EPIC307_NUM

## Affected files
- \`docs/*.md\`
EOF
)" \
  "type:docs,area:docs,priority:medium,status:ready")

I307_3=$(create_issue \
  "docs: fix issue templates and issues/*.md hotspot paths" \
  "$(cat <<EOF
## Summary
Update .github/ISSUE_TEMPLATE/repo-improvement.yml and issues/*.md files referencing \`services/gateway-engine/gateway-engine.py\`.

## Dependencies
- Parent epic: #$EPIC307_NUM

## Affected files
- \`.github/ISSUE_TEMPLATE/repo-improvement.yml\`
- \`issues/*.md\`
EOF
)" \
  "type:docs,area:docs,priority:low,status:ready")

echo "  #${I307_1##*/} top-level docs"
echo "  #${I307_2##*/} docs/"
echo "  #${I307_3##*/} templates"

# ── Epic 308: Expand lint coverage ───────────────────────────────────────────
EPIC308=$(create_epic \
  "Roadmap Epic: Expand Python lint coverage beyond main.py" \
  "$(cat <<'EOF'
## Summary
Extend ruff lint/format checks from single-file `main.py` to full gateway-engine package and CI parity.

## Problem
`make lint` and CI only check `services/gateway-engine/main.py`. admin_api.py, core/**, credential-prober are unchecked.

## Scope
- Makefile + CI lint-and-syntax job
- Fix violations in gateway-engine package
- Optional: credential-prober in follow-up

## Dependencies
- None (parallel)

## Affected files
- `Makefile`, `.github/workflows/ci.yml`, `services/gateway-engine/**`
EOF
)" \
  "type:dx,area:tests,priority:medium,status:ready")

EPIC308_NUM="${EPIC308##*/}"
echo "Epic 308: #$EPIC308_NUM"

I308_1=$(create_issue \
  "chore(lint): expand Makefile and CI ruff to services/gateway-engine/" \
  "$(cat <<EOF
## Summary
Change \`make lint\` and CI \`lint-and-syntax\` to run ruff on entire \`services/gateway-engine/\` tree.

## Acceptance criteria
- [ ] \`make lint\` checks all \`services/gateway-engine/**/*.py\`
- [ ] CI job updated identically

## Dependencies
- Parent epic: #$EPIC308_NUM

## Affected files
- \`Makefile\`
- \`.github/workflows/ci.yml\`
EOF
)" \
  "type:dx,area:tests,priority:medium,status:ready")

I308_2=$(create_issue \
  "chore(lint): fix ruff violations in gateway-engine package" \
  "$(cat <<EOF
## Summary
Resolve all ruff check/format issues surfaced after expanding lint scope.

## Dependencies
- Parent epic: #$EPIC308_NUM
- Depends on: ${I308_1##*/}

## Affected files
- \`services/gateway-engine/**\`
EOF
)" \
  "type:code-health,area:tests,priority:medium,status:ready")

echo "  #${I308_1##*/} expand scope"
echo "  #${I308_2##*/} fix violations"

# ── Epic 309: Modularize main.py ─────────────────────────────────────────────
EPIC309=$(create_epic \
  "Roadmap Epic: Modularize gateway-engine main.py monolith" \
  "$(cat <<'EOF'
## Summary
Incremental extraction of ~4090-line main.py into focused routers/modules to reduce merge conflicts and improve testability.

## Problem
main.py mixes proxy, WebSocket, admin panels, policy hooks, metrics, and embedded HTML dashboard.

## Scope
- Extract WebSocket handler → api/ws_router.py
- Extract admin status/mutation routes → api/admin_routes.py (or extend admin_api.py)
- Extract catch-all proxy → api/proxy_router.py
- main.py becomes app factory + router mounts

## Non-goals
- Behavior changes (refactor only)
- Policy engine extraction

## Dependencies
- Depends on: Epic 305 (WebSocket auth) and Epic 306 (admin auth unification) before WebSocket/admin extractions

## Affected files
- `services/gateway-engine/main.py`
- New modules under `services/gateway-engine/api/`
EOF
)" \
  "type:code-health,area:translator,priority:medium,status:ready")

EPIC309_NUM="${EPIC309##*/}"
echo "Epic 309: #$EPIC309_NUM"

I309_1=$(create_issue \
  "refactor(gateway): extract WebSocket handler to api/ws_router.py" \
  "$(cat <<EOF
## Summary
Move \`responses_websocket\` and related helpers from main.py to \`api/ws_router.py\`.

## Acceptance criteria
- [ ] No behavior change; all websocket policy tests pass
- [ ] main.py mounts ws router

## Dependencies
- Parent epic: #$EPIC309_NUM
- Depends on: Epic #$EPIC305_NUM (WebSocket auth hardening merged first)

## Affected files
- \`services/gateway-engine/main.py\`
- \`services/gateway-engine/api/ws_router.py\` (new)
EOF
)" \
  "type:code-health,area:translator,priority:medium,status:blocked")

I309_2=$(create_issue \
  "refactor(gateway): extract admin routes from main.py to api/admin_routes.py" \
  "$(cat <<EOF
## Summary
Move /admin/* endpoints and admin panel helpers from main.py to dedicated module; consolidate with admin_api.py where sensible.

## Dependencies
- Parent epic: #$EPIC309_NUM
- Depends on: Epic #$EPIC306_NUM (admin auth unification merged first)

## Affected files
- \`services/gateway-engine/main.py\`
- \`services/gateway-engine/api/admin_routes.py\` (new)
EOF
)" \
  "type:code-health,area:translator,priority:medium,status:blocked")

I309_3=$(create_issue \
  "refactor(gateway): extract catch-all proxy to api/proxy_router.py" \
  "$(cat <<EOF
## Summary
Move catch-all \`proxy()\` route and format-translation helpers to api/proxy_router.py.

## Dependencies
- Parent epic: #$EPIC309_NUM
- Depends on: ${I309_1##*/}, ${I309_2##*/} (sequential after ws/admin extraction)

## Affected files
- \`services/gateway-engine/main.py\`
- \`services/gateway-engine/api/proxy_router.py\` (new)
EOF
)" \
  "type:code-health,area:translator,priority:medium,status:blocked")

echo "  #${I309_1##*/} ws extract"
echo "  #${I309_2##*/} admin extract"
echo "  #${I309_3##*/} proxy extract"

echo ""
echo "=== Created epics #$EPIC305_NUM #$EPIC306_NUM #$EPIC307_NUM #$EPIC308_NUM #$EPIC309_NUM ==="
