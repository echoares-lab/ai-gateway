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
| Status | `candidate` until promoted |

Last reviewed: 2026-07-11.

---

## Ops and credential intelligence (beyond thin wave)

Thin approved work (quota unit tests / small polish) lives on the roadmap.
Everything below stays candidate until promoted.

| ID | Summary | Effort | Risk | Need/fit | Deps / links | Status |
|----|---------|--------|------|----------|--------------|--------|
| C-CRED-1 | Credential pool orchestration: inventory, health state machine, quarantine/cooldown, alerts | L | H | med | Closed epic [#33](https://github.com/echoares-lab/ai-gateway/issues/33); [CREDENTIAL_HEALTH.md](./CREDENTIAL_HEALTH.md) | candidate |
| C-CRED-2 | Multi-account load balancing / remapping across OAuth credentials | L | H | med | Builds on C-CRED-1; CLIProxy management APIs | candidate |
| C-CRED-3 | Operator remediation workflows (API/UI) for expired, rate-limited, or degraded credentials | M | M | med | Admin console + C-CRED-1 | candidate |
| C-CRED-4 | Chargeback / budget attribution hooks from credential and tenant usage | L | H | unclear | [CHARGEBACK_ATTRIBUTION.md](./CHARGEBACK_ATTRIBUTION.md); tenancy decision | candidate |

---

## Tenancy and adoption

Parked on the roadmap as coordination anchors; expanded scope remains candidate
until a multi-tenant decision is made.

| ID | Summary | Effort | Risk | Need/fit | Deps / links | Status |
|----|---------|--------|------|----------|--------------|--------|
| C-TEN-1 | Full multi-tenant workspace lifecycle (org/workspace/team/repo) | L | H | unclear | [#30](https://github.com/echoares-lab/ai-gateway/issues/30); [TENANCY.md](./TENANCY.md) | candidate |
| C-TEN-2 | Self-service onboarding for repos, apps, and AI clients | L | M | unclear | [#34](https://github.com/echoares-lab/ai-gateway/issues/34); depends on C-TEN-1 | candidate |
| C-TEN-3 | Admin tenant/team panel (usage, quota, credential health per tenant) | M | M | unclear | [#109](https://github.com/echoares-lab/ai-gateway/issues/109); depends on C-TEN-1 | candidate |
| C-TEN-4 | RBAC and identity integration | L | H | unclear | Tenancy + admin/control-plane contracts | candidate |

---

## Model lifecycle and config promotion

Cheap-drift check and `/model/new` / `/model/delete` hot-add shipped on `main`
(2026-07). Further automation is candidate.

| ID | Summary | Effort | Risk | Need/fit | Deps / links | Status |
|----|---------|--------|------|----------|--------------|--------|
| C-MDL-1 | Full discovery orchestration (probe → registry → LiteLLM reconcile loops) | L | M | med | Prior epic [#230](https://github.com/echoares-lab/ai-gateway/issues/230); [MODEL_MANAGEMENT_RESEARCH.md](./MODEL_MANAGEMENT_RESEARCH.md) | candidate |
| C-MDL-2 | Staging / config release channels for model and tool changes | L | H | med | Closed epic [#35](https://github.com/echoares-lab/ai-gateway/issues/35); [CONFIG_PROMOTION.md](./CONFIG_PROMOTION.md); [CICD_PHASE2_STAGING.md](./CICD_PHASE2_STAGING.md) | candidate |
| C-MDL-3 | External model metadata expansion in `config/model-registry.yaml` | M | M | low | [UNMERGED_FEATURES.md](./UNMERGED_FEATURES.md) | candidate |

---

## Routing, policy, and tools

| ID | Summary | Effort | Risk | Need/fit | Deps / links | Status |
|----|---------|--------|------|----------|--------------|--------|
| C-RT-1 | Adaptive routing runtime (health/latency/429-driven fallback) | L | H | med | Closed design [#31](https://github.com/echoares-lab/ai-gateway/issues/31); [ADAPTIVE_ROUTING.md](./ADAPTIVE_ROUTING.md) | candidate |
| C-RT-2 | Evaluation-driven quality routing at request time | L | H | low | Closed [#37](https://github.com/echoares-lab/ai-gateway/issues/37); [EVAL_DRIVEN_ROUTING.md](./EVAL_DRIVEN_ROUTING.md) | candidate |
| C-RT-3 | Deeper policy engine (WS parity, stricter enforcement, separate service?) | L | H | med | Closed [#38](https://github.com/echoares-lab/ai-gateway/issues/38); [POLICY_ENGINE_AND_ROUTING_REFACTOR.md](./POLICY_ENGINE_AND_ROUTING_REFACTOR.md) | candidate |
| C-RT-4 | MCP visibility and deeper local tool hosting | M | M | med | Closed [#29](https://github.com/echoares-lab/ai-gateway/issues/29); [MCP_TOOL_VISIBILITY.md](./MCP_TOOL_VISIBILITY.md); [ARCHITECTURE.md](./ARCHITECTURE.md) | candidate |

---

## Script-to-service and DX

| ID | Summary | Effort | Risk | Need/fit | Deps / links | Status |
|----|---------|--------|------|----------|--------------|--------|
| C-SVC-1 | Evolve `cliproxy-setup.sh` into management API service | L | M | med | [SCRIPT_TO_SERVICE_ROADMAP.md](./SCRIPT_TO_SERVICE_ROADMAP.md) | candidate |
| C-SVC-2 | `/v1/config/generate` from `gen-client-config.sh` | M | L | med | SCRIPT_TO_SERVICE_ROADMAP | candidate |
| C-SVC-3 | Team/key manager API from `setup_litellm_teams.py` | M | M | unclear | SCRIPT_TO_SERVICE_ROADMAP; tenancy | candidate |
| C-SVC-4 | Unified config admin API (re-implement vs stale `feat/unified-config`) | L | M | med | [UNMERGED_FEATURES.md](./UNMERGED_FEATURES.md) | candidate |

---

## Post-audit hardening leftovers

Notable open gaps from
[issues/post-audit-backlog-2026-06-13.md](../issues/post-audit-backlog-2026-06-13.md).
Promote individually; do not treat the backlog file as claimable work.

| ID | Summary | Effort | Risk | Need/fit | Audit ref | Status |
|----|---------|--------|------|----------|-----------|--------|
| C-AUD-1 | Require explicit Langfuse/Redis secrets in production | S | M | high | D-1 | candidate |
| C-AUD-2 | Document admin endpoint exposure model (tunnel/WAF) | S | L | high | D-2 | candidate |
| C-AUD-3 | LiteLLM Postgres vs YAML override / drift docs or detector | M | M | high | D-11 | candidate |
| C-AUD-4 | Dev-env compose project collision preflight | S | L | med | D-12 | candidate |
| C-AUD-5 | Narrow broad `except Exception` handlers in gateway-engine | M | M | med | D-6 | candidate |
| C-AUD-6 | Optional WebSocket policy evaluation parity | M | M | med | D-4 | candidate |

---

## Related docs

- [ROADMAP.md](./ROADMAP.md) — approved Now / Next / Parked only
- [REPO_IMPROVEMENT_WORKFLOW.md](process/REPO_IMPROVEMENT_WORKFLOW.md)
- [UNMERGED_FEATURES.md](./UNMERGED_FEATURES.md)
- [SCRIPT_TO_SERVICE_ROADMAP.md](./SCRIPT_TO_SERVICE_ROADMAP.md)
