# Feature Candidates (Not Yet Approved)

Inventory of product and platform ideas that are **not** approved for the
active roadmap. Agents must **not** claim or implement work from this file.

Promotion path:

1. Explicitly move the item into [ROADMAP.md](./ROADMAP.md) under Now / Next /
   Parked as appropriate.
2. Open atomic GitHub child issues with acceptance criteria and
   `status:ready` / `status:approved`.
3. Only then may agents claim those issues under `docs/process/REPO_IMPROVEMENT_WORKFLOW.md`.

Scoring keys:

| Field | Scale |
|-------|--------|
| Effort | S (days) / M (1–2 weeks) / L (multi-week / multi-epic) |
| Risk | L / M / H (ops, contract, or blast-radius) |
| Need/fit | high / med / low / unclear — relative to current direction |
| Status | `candidate` until explicitly promoted and given atomic issues |

Last reviewed: 2026-07-31.

## Promoted to roadmap (active; not candidates)

These candidates were promoted into approved coordination epic
[#517](https://github.com/echoares-lab/ai-gateway/issues/517) and must be
tracked through its ready atomic children rather than claimed from this file.

| ID | Summary | Approved tracking issues |
|----|---------|--------------------------|
| C-AUD-1 | Require explicit Langfuse/Redis secrets in production | Epic [#517](https://github.com/echoares-lab/ai-gateway/issues/517); child [#518](https://github.com/echoares-lab/ai-gateway/issues/518) |
| C-AUD-2 | Document admin endpoint exposure model (tunnel/WAF) | Epic [#517](https://github.com/echoares-lab/ai-gateway/issues/517); child [#519](https://github.com/echoares-lab/ai-gateway/issues/519) |
| C-AUD-3 | LiteLLM Postgres vs YAML override / drift docs or detector | Epic [#517](https://github.com/echoares-lab/ai-gateway/issues/517); child [#520](https://github.com/echoares-lab/ai-gateway/issues/520) |
| C-AUD-4 | Dev-env compose project collision preflight and safe recovery | Epic [#525](https://github.com/echoares-lab/ai-gateway/issues/525); children [#526](https://github.com/echoares-lab/ai-gateway/issues/526), [#527](https://github.com/echoares-lab/ai-gateway/issues/527) |
| C-AUD-5 | Narrow broad gateway exception handlers with typed boundaries | Epic [#531](https://github.com/echoares-lab/ai-gateway/issues/531); children [#532](https://github.com/echoares-lab/ai-gateway/issues/532), [#533](https://github.com/echoares-lab/ai-gateway/issues/533) |
| C-SVC-1 | Evolve `cliproxy-setup.sh` into management API service | Epic [#609](https://github.com/echoares-lab/ai-gateway/issues/609); ready contract child [#610](https://github.com/echoares-lab/ai-gateway/issues/610) |

## Delivered / historical (not candidates)

These entries are retained only to prevent accidental re-creation. They are
not active candidates and are not claimable. References distinguish tracking
issues from implementation pull requests.

| ID | Summary | Delivered / tracking evidence |
|----|---------|-------------------------------|
| C-OPS-1 | CLIProxy upstream-patch migration and third-party dependency update/test/rollback loop | Closed [epic #413](https://github.com/echoares-lab/ai-gateway/issues/413) and children #414–#419; implementation includes [PR #420](https://github.com/echoares-lab/ai-gateway/pull/420) through [PR #425](https://github.com/echoares-lab/ai-gateway/pull/425) |
| C-BENCH-1 | Cross-model tool-use and protocol benchmark | [PR #440](https://github.com/echoares-lab/ai-gateway/pull/440) and [PR #484](https://github.com/echoares-lab/ai-gateway/pull/484); no approved benchmark epic/atomic issues were created |
| C-MDL-3 | External model metadata capability expansion | [PR #486](https://github.com/echoares-lab/ai-gateway/pull/486) |
| C-RT-6 | Cross-provider reasoning/thinking token normalization | [PR #486](https://github.com/echoares-lab/ai-gateway/pull/486) |
| C-RT-7 | Context-window-aware request normalization and message pruning | [PR #487](https://github.com/echoares-lab/ai-gateway/pull/487) |
| C-AUD-7 | Extend Ruff coverage to credential-prober and scripts | [PR #487](https://github.com/echoares-lab/ai-gateway/pull/487) |

---

## Ops and credential intelligence (beyond thin wave)

Thin approved work (quota unit tests / small polish) lives on the roadmap.
Everything below stays candidate until promoted.

| ID | Summary | Effort | Risk | Need/fit | Deps / links | Status |
|----|---------|--------|------|----------|--------------|--------|
| C-CRED-4 | Chargeback / budget attribution hooks from credential and tenant usage | L | H | unclear | [CHARGEBACK_ATTRIBUTION.md](./CHARGEBACK_ATTRIBUTION.md); tenancy decision | candidate |

---

## Tenancy and adoption

Tenancy epics (#30, #34, #109) were closed and dropped as out of scope for the single-tenant operator gateway architecture.

| ID | Summary | Effort | Risk | Need/fit | Deps / links | Status |
|----|---------|--------|------|----------|--------------|--------|
| C-TEN-1 | Full multi-tenant workspace lifecycle (org/workspace/team/repo) | L | H | low | Closed #30 | dropped |
| C-TEN-2 | Self-service onboarding for repos, apps, and AI clients | L | M | low | Closed #34 | dropped |
| C-TEN-3 | Admin tenant/team panel (usage, quota, credential health per tenant) | M | M | low | Closed #109 | dropped |
| C-TEN-4 | RBAC and identity integration | L | H | low | Control-plane contracts | candidate |

---

## Model lifecycle and config promotion

Cheap-drift check and `/model/new` / `/model/delete` hot-add shipped on `main`
(2026-07). Further automation is candidate.

| ID | Summary | Effort | Risk | Need/fit | Deps / links | Status |
|----|---------|--------|------|----------|--------------|--------|

---

## Routing, policy, and tools

| ID | Summary | Effort | Risk | Need/fit | Deps / links | Status |
|----|---------|--------|------|----------|--------------|--------|
| C-RT-2 | Evaluation-driven quality routing at request time | L | H | low | Closed [#37](https://github.com/echoares-lab/ai-gateway/issues/37); [EVAL_DRIVEN_ROUTING.md](./EVAL_DRIVEN_ROUTING.md) | candidate |
| C-RT-3 | Deeper policy engine (WS parity, stricter enforcement, separate service?) | L | H | med | Closed [#38](https://github.com/echoares-lab/ai-gateway/issues/38); [POLICY_ENGINE_AND_ROUTING_REFACTOR.md](./POLICY_ENGINE_AND_ROUTING_REFACTOR.md) | candidate |
| C-RT-4 | MCP visibility and deeper local tool hosting | M | M | med | Closed [#29](https://github.com/echoares-lab/ai-gateway/issues/29); [MCP_TOOL_VISIBILITY.md](./MCP_TOOL_VISIBILITY.md); [ARCHITECTURE.md](./ARCHITECTURE.md) | candidate |
| C-RT-5 | Codex WebSocket frame translation (Option B: translate WS frames to standard HTTP completions for provider-independent routing) | M | M | med | [CLIENT_COMPATIBILITY.md](./CLIENT_COMPATIBILITY.md); ws_router.py | candidate |
---

## Script-to-service and DX

| ID | Summary | Effort | Risk | Need/fit | Deps / links | Status |
|----|---------|--------|------|----------|--------------|--------|
| C-SVC-2 | `/v1/config/generate` from `gen-client-config.sh` | M | L | med | SCRIPT_TO_SERVICE_ROADMAP | candidate |
| C-SVC-3 | Team/key manager API from `setup_litellm_teams.py` | M | M | unclear | SCRIPT_TO_SERVICE_ROADMAP; tenancy | candidate |
| C-SVC-4 | Unified config admin API (re-implement vs stale `feat/unified-config`) | L | M | med | [UNMERGED_FEATURES.md](./UNMERGED_FEATURES.md) | candidate |

---

## Post-audit hardening leftovers (C-AUD-*)

Historical backlog:
[`issues/archive/post-audit-backlog-2026-06-13.md`](../issues/archive/post-audit-backlog-2026-06-13.md)
(archived). Promote individually; do not claim from the archive.

**Done / superseded (do not reopen):** D-5 (policy lives in
`services/gateway-engine/core/policy/`), D-8 (Gate C opt-in documented), D-13
(test naming sweep), security-hardening epics #305–#323, and
[Stability Foundation PR #377](https://github.com/echoares-lab/ai-gateway/pull/377).

| ID | Summary | Effort | Risk | Need/fit | Audit ref | Status |
|----|---------|--------|------|----------|-----------|--------|
| C-AUD-8 | Extract remaining policy hooks from request path / routers | M | M | med | D-7 | candidate |
| C-AUD-9 | Faster local mock iteration (optional skip of heavy clean-db) | S | L | low | D-9 | candidate |

---

## Related docs

- [ROADMAP.md](./ROADMAP.md) — approved Now / Next / Parked only
- [REPO_IMPROVEMENT_WORKFLOW.md](process/REPO_IMPROVEMENT_WORKFLOW.md)
- [UNMERGED_FEATURES.md](./UNMERGED_FEATURES.md)
- [SCRIPT_TO_SERVICE_ROADMAP.md](./SCRIPT_TO_SERVICE_ROADMAP.md)
- [tool-use-eval.md](./tool-use-eval.md) — benchmark reference; delivered benchmark work is recorded above
