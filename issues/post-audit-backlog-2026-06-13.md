---
work_type: type:coordination
summary: Deferred findings from main-branch codebase audit (2026-06-13) — not in the top-five security-hardening epics.
problem: |
  A full audit of origin/main identified ranked issues across security, architecture,
  docs, CI, and operations. The five highest-priority fix tracks (WebSocket auth,
  admin auth unification, doc path sweep, lint expansion, main.py modularization)
  are planned as security-hardening epics (see scripts/create-security-hardening-epics.sh).
  This file captures everything else for later GitHub issue creation or roadmap planning.
why_now: |
  Agents and operators need a single repo-local backlog so deferred work is not lost
  after the audit conversation. Items here are intentionally lower priority or depend
  on active roadmap epics (#29–#38).
scope: |
  Track deferred audit items with severity, category, suggested issue title, and
  dependencies. No implementation in this file.
non_goals:
  - Duplicating the five security-hardening epic scopes (305–309 when created on GitHub)
  - Replacing existing open issues (#30, #33, #34, etc.)
acceptance:
  - [ ] Each row reviewed when planning the next repo-improvement batch
  - [ ] High/medium items split into atomic GitHub issues before agent claim
  - [ ] ROADMAP.md references this file
dependencies:
  - docs/ROADMAP.md
  - scripts/create-security-hardening-epics.sh
claim_status: not-claimable
github_issue: null
audit_ref: origin/main @ 50da01c (2026-06-13)
---

# Post-Audit Backlog — Deferred Items (2026-06-13)

Audit baseline: **228 unit tests passing**, CI green on `main`, lint clean on
`services/gateway-engine/main.py` only.

**In-flight (separate epics — do not duplicate here):**

| Track | Scope | Creation script |
|-------|--------|-----------------|
| WebSocket auth hardening | Fail-closed, sk-* validation, log redaction | [#305](https://github.com/echoares-lab/ai-gateway/issues/305) · #306–#308 |
| Admin auth unification | Single admin key, optional read-auth gate | [#309](https://github.com/echoares-lab/ai-gateway/issues/309) · #310–#312 |
| Documentation path drift | `gateway-engine.py` → `main.py` sweep | [#313](https://github.com/echoares-lab/ai-gateway/issues/313) · #314–#316 |
| Lint coverage expansion | Ruff on full `services/gateway-engine/` | [#317](https://github.com/echoares-lab/ai-gateway/issues/317) · #318–#319 |
| main.py modularization | Extract ws/admin/proxy routers | [#320](https://github.com/echoares-lab/ai-gateway/issues/320) · #321–#323 |

Run `./scripts/create-security-hardening-epics.sh` to open GitHub epics if not yet created.

**Already on main:** `codex/1password-secrets-governance` merged via [#298](https://github.com/echoares-lab/ai-gateway/pull/298) (`docs/1password-secrets.md`, `.env.op`).

---

## Ranked deferred backlog

### Security & configuration

| Rank | Severity | Suggested issue | Problem | Notes / deps |
|------|----------|-----------------|---------|--------------|
| D-1 | Medium | `chore(compose): require explicit Langfuse secrets in production` | `docker-compose.yml` ships weak defaults (`NEXTAUTH_SECRET:-mysecret`, zero-filled `ENCRYPTION_KEY`, `REDIS_AUTH:-myredissecret`) | Fail CI or startup check when `ENVIRONMENT=production` and defaults detected; document in RUNBOOK |
| D-2 | Medium | `docs(security): document admin endpoint exposure model` | Read-only `/admin/*` endpoints are unauthenticated by design (“operator-local by convention”) but bind on public `:4000` | Complements Epic 306 read-auth gate; clarify tunnel/WAF expectations |
| D-3 | Low | `chore(lint): extend ruff to credential-prober and scripts/` | Epic 308 covers gateway-engine only; `services/credential-prober/`, `scripts/*.py` remain unchecked | After Epic 308 lands |

### Architecture & reliability

| Rank | Severity | Suggested issue | Problem | Notes / deps |
|------|----------|-----------------|---------|--------------|
| D-4 | Medium | `feat(policy): optional WebSocket policy evaluation parity` | `codex_ws_policy_bypass()` skips policy engine unless both `POLICY_ENGINE_ENABLED` and `POLICY_ENGINE_WS_EVALUATE` are set; HTTP and WS routing can diverge | Intentional today (see `test_gateway_engine_websocket_policy.py`); revisit for production enforcement — overlaps [#138](https://github.com/echoares-lab/ai-gateway/issues/138) / policy-engine-38-14 |
| D-5 | Medium | `docs(architecture): clarify policy-engine deployment model` | Roadmap/issues reference `services/policy-engine/` scaffold; on main, policy logic lives in `services/gateway-engine/core/policy/` | Update ARCHITECTURE.md; decide if separate service is still planned |
| D-6 | Medium | `refactor(gateway): narrow broad exception handlers in main.py` | 40+ `except Exception: pass` blocks can hide tenancy/policy/body-patch failures | Do after Epic 309 modularization; add structured logging per branch |
| D-7 | Low | `refactor(gateway): extract policy hooks from main.py` | Policy evaluation wiring mixed into proxy paths | Child of Epic 309 or Epic #38 follow-up |

### Testing & CI

| Rank | Severity | Suggested issue | Problem | Notes / deps |
|------|----------|-----------------|---------|--------------|
| D-8 | Low | `chore(ci): document Gate C opt-in E2E policy` | Real-provider E2E is label/`workflow_dispatch` only; hotspot auto-E2E paused | Already in TESTING_AND_PROMOTION_POLICY.md — add RUNBOOK operator checklist |
| D-9 | Low | `chore(tests): reduce mock integration clean-db overhead` | `make test-mock` runs `clean-db` and full mock stack every time | Consider optional `test-mock-fast` without volume wipe for local iteration |
| D-10 | Low | `test(gateway): add integration coverage for catch-all proxy edge cases` | Catch-all `proxy()` path has complex format translation; mostly unit-tested | Mock Gate B; fault injection for `/responses/compact` model mapping |

### Operations & configuration

| Rank | Severity | Suggested issue | Problem | Notes / deps |
|------|----------|-----------------|---------|--------------|
| D-11 | Medium | `docs(ops): LiteLLM Postgres overrides vs litellm-config.yaml` | UI/DB changes persist in Postgres and override YAML; common “config didn't apply” footgun | Expand RUNBOOK troubleshooting; optional drift detector in admin status panel |
| D-12 | Medium | `chore(dev-env): detect compose project name collisions across worktrees` | Compose project `ai` — two worktrees starting stacks conflict on container names | `./dev-env.sh start` preflight or per-slot project name |
| D-13 | Low | `chore(docs): sync test file naming in all entrypoints` | Residual `test_gateway-engine.py` references outside Epic 307 scope (e.g. test file header comments, packages/repo-improvement-kit) | Sweep after Epic 307 |

### Existing roadmap (already tracked — audit confirmation only)

These are **not new findings**; the audit confirmed they remain open gaps:

| GitHub | Title | Audit note |
|--------|-------|------------|
| [#30](https://github.com/echoares-lab/ai-gateway/issues/30) | Multi-tenant workspace management | Foundational; blocks full tenancy story |
| [#34](https://github.com/echoares-lab/ai-gateway/issues/34) | Self-service onboarding | Depends on #30 |
| [#36](https://github.com/echoares-lab/ai-gateway/issues/36) | Client compatibility profiles | Partial implementation on main |
| [#107](https://github.com/echoares-lab/ai-gateway/issues/107) | Tenancy API key naming alignment | In review |
| [#109](https://github.com/echoares-lab/ai-gateway/issues/109) | Admin tenant/team panel | Blocked |
| [api-doc-consolidation.md](./api-doc-consolidation.md) | Scalar / OpenAPI consolidation | Stale `gateway-engine.py` path in issue file |

---

## Suggested batch order (after security epics 305–309)

1. **D-11, D-12** — operator footguns (medium effort, high DX value)
2. **D-1, D-2** — production secret hygiene
3. **D-4, D-5** — policy/WebSocket architecture clarity
4. **D-6, D-7** — main.py reliability (post-modularization)
5. **D-3, D-8, D-9, D-10, D-13** — CI/DX polish

---

## Verification when picking up an item

```bash
# Baseline health on stable main worktree
git checkout main && git pull origin main
make test-fast

# For compose/ops items
./dev-env.sh list
./cliproxy-setup.sh health
```

---

## Related docs

- [docs/ROADMAP.md](../docs/ROADMAP.md)
- [TESTING_AND_PROMOTION_POLICY.md](../TESTING_AND_PROMOTION_POLICY.md)
- [issues/policy-engine-dispatch.md](./policy-engine-dispatch.md)
- [scripts/create-security-hardening-epics.sh](../scripts/create-security-hardening-epics.sh)
