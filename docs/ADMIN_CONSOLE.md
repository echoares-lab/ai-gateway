# Unified Admin Console — Use Cases, Data Sources, and Approach

> **Status:** Design (no runtime behavior change). Foundational design for
> [Roadmap Epic #32 — Unified admin console](https://github.com/echoares-lab/ai-gateway/issues/32).
> This document defines the target operator use cases, data sources, recommended
> control-plane approach, dependency boundaries, and child implementation plan.

---

## 1. Goal

Create a single operator surface that answers the questions gateway maintainers
ask during normal operations and incidents:

- Is the gateway healthy end-to-end?
- Which providers/accounts are usable right now?
- Which models are available to clients?
- Are we approaching quota/rate-limit pressure?
- Which routes/fallbacks/cooldowns are active or recently triggered?
- Did repo config drift from runtime state?
- What changed recently, and what should an operator do next?

The console should **unify visibility**, not become a second source of truth. It
must read from the existing systems that already own state: translator metrics,
LiteLLM, CLIProxy/CPA-Manager, Langfuse, repo config, and operational scripts.

---

## 2. Target users and use cases

### 2.1 Gateway operator / maintainer

Primary operator tasks:

1. **Health triage**
   - See translator, LiteLLM, CLIProxy, Redis, Postgres, and provider-token state.
   - Identify whether failures are local infrastructure, provider auth, model
     availability, or routing/cooldown behavior.

2. **Model availability**
   - Compare configured models (`litellm-config.yaml`) with models clients see
     via `/v1/models`.
   - Detect missing aliases, stale sync state, or models hidden by runtime errors.

3. **Quota and credential health**
   - Surface per-provider token status from `./cliproxy-setup.sh health`.
   - Surface CLIProxy/CPA-Manager usage and quota summaries.
   - Highlight providers close to rate limits or with repeated 401/429/503.

4. **Routing and fallback diagnosis**
   - Show the static fallback matrix from `litellm-config.yaml`.
   - Show adaptive routing controls (`routing_strategy`, `cooldown_time`,
     `allowed_fails`, `allowed_fails_policy`).
   - Show recent routing signals from `docs/ADAPTIVE_ROUTING.md` / issue #59:
     provider latency, request outcomes, and rate-limit counters.

5. **Config drift / warnings**
   - Validate YAML and expected env references.
   - Warn if runtime state in LiteLLM DB/UI is likely overriding repo config.
   - Warn if MCP server entries reference missing env vars.

6. **Runbook shortcuts**
   - Link or expose common actions from `RUNBOOK.md` / `cliproxy-setup.sh`:
     health, quota summary, model sync, model E2E tests, auth refresh commands.

### 2.2 Future tenant/workspace operator

Tenant/team views are valuable but depend on the tenant model tracked in
[#30](https://github.com/echoares-lab/ai-gateway/issues/30) and
[#56](https://github.com/echoares-lab/ai-gateway/issues/56). Until that model is
merged, the admin console should only reserve space for tenant-aware panels:

- tenant/workspace/team/repo hierarchy
- per-tenant virtual keys and teams
- per-tenant usage/quota attribution
- per-tenant routing preferences

These are **deferred** from the first implementation wave.

---

## 3. Data source inventory

| Panel | Source of truth | Access path | Freshness | Auth / permissions | Notes |
|---|---|---|---|---|---|
| Translator health | translator service | `GET /health` on port 4000 / dev slot | live | gateway-local | Public entry point for clients. |
| Translator metrics | translator Prometheus exporter | `GET /metrics` | live | gateway-local | Includes request counts/latency and provider routing signals. |
| Client-visible models | translator/LiteLLM | `GET /v1/models` with LiteLLM master key | live | `LITELLM_MASTER_KEY` | Translator adds `AI-Gateway:` prefix. |
| LiteLLM model config | repo config | `litellm-config.yaml` | commit-time | repo access | Source for model aliases, fallbacks, MCP registrations. |
| LiteLLM runtime state | LiteLLM DB/API/UI | LiteLLM API/UI, Postgres tables | live/persistent | LiteLLM admin key / DB access | UI/API changes can override config; drift panel should flag this. |
| Provider auth health | CLIProxy | `./cliproxy-setup.sh health`, CLIProxy management UI | live | host/operator access | Shows OAuth token/account status. |
| Quota/usage summary | CLIProxy/CPA-Manager | `./cliproxy-setup.sh quota-summary`, CPA-Manager | near-live | management key | CPA-Manager runs on port 18317. |
| Request traces | Langfuse | Langfuse UI/API | near-live | Langfuse credentials | Source for trace-level usage and debugging. |
| Routing/fallback events | LiteLLM logs + translator metrics | logs, `/metrics` | live/recent | gateway-local | Provider signal metrics from #59; cooldown logs from LiteLLM. |
| MCP tool config | LiteLLM config/DB | `litellm-config.yaml`, LiteLLM Tool tables | commit/live | repo + DB access | MCP config can also live in LiteLLM DB tables. |
| Config syntax | repo files | YAML parser, shell `bash -n`, CI | commit-time | repo access | Mirrors `lint-and-syntax` CI job. |

### Source-of-truth rule

The console reads and summarizes; it should not silently mutate runtime state.
Any write action (auth refresh, model sync, MCP registration, config promotion)
should be explicit, audited, and routed through an existing script or future
approved workflow.

---

## 4. Recommended approach

### Recommendation: dashboard wrapper over existing control planes

Build a small gateway-admin surface that **aggregates links, status, and metrics**
from existing systems instead of replacing them:

1. **Static/config layer**
   - Parse `litellm-config.yaml`, `.env.example`, and docs to display expected
     models, fallbacks, MCP servers, and env vars.
   - Run the same validation checks as CI (`yaml.safe_load`, shell syntax,
     hardcoded-key scan) for operator visibility.

2. **Live health layer**
   - Poll translator `/health`, `/v1/models`, `/metrics`.
   - Call or wrap `cliproxy-setup.sh health` / `quota-summary` for provider state.
   - Link to LiteLLM UI (`:4001`), CLIProxy management (`:8317`), CPA-Manager
     (`:18317`), and Langfuse.

3. **Routing intelligence layer**
   - Display fallback matrix and router settings from `litellm-config.yaml`.
   - Display provider signal metrics added by #59:
     `translator_provider_request_duration_seconds`,
     `translator_provider_requests_total`, and
     `translator_provider_rate_limits_total`.
   - Show recent provider cooldown/rate-limit warnings from LiteLLM logs once a
     safe log access path is defined.

4. **Action layer (future)**
   - Start read-only: links and copyable commands only.
   - Later, add guarded actions (sync models, run E2E, refresh auth guidance) with
     explicit confirmation and audit trail.

This approach keeps the console small, avoids duplicating CPA-Manager/LiteLLM UI,
and fits the repo's existing operator-script workflow.

### Alternatives considered

| Alternative | Pros | Cons | Recommendation |
|---|---|---|---|
| Extend LiteLLM UI only | Already part of stack; close to routing/config state | Does not own CLIProxy auth, CPA usage, translator metrics, repo drift | Link into it; do not depend solely on it. |
| Use CPA-Manager as primary admin UI | Strong CLIProxy/usage visibility | Not the source of translator/LiteLLM/MCP repo config | Link/embed as a panel. |
| Custom full admin app | Maximum control | Higher maintenance; risks duplicating existing UIs | Avoid until read-only dashboard proves value. |
| Static generated status page | Low risk, easy to host | Not live enough for incidents | Useful as first artifact or fallback mode. |

---

## 5. Dependency boundaries

### Can start now

- Health overview for translator/LiteLLM/CLIProxy.
- Model list and config drift checks.
- Provider token/quota summary.
- Routing/fallback/cooldown visibility using merged #58/#59/#60 artifacts.
- MCP server config summary.

### Wait for #30/#56

- Tenant/workspace/team hierarchy.
- Per-tenant usage, visibility, and permission boundaries.
- Tenant-specific routing preferences and config scopes.
- Tenant-aware admin actions.

### Write actions require separate approval

Any console action that changes auth, model config, database state, or routing
must be split into its own issue. The first console implementation should be
read-only.

---

## 6. Implementation plan — child issues

1. **docs/admin-console-data-contract**
   - Define JSON shapes for the read-only dashboard panels: health, models,
     provider auth/quota, routing, config drift.
   - No UI; just contract + fixtures.
   - Depends on this design.

2. **feat(admin): read-only status aggregator script/API**
   - Add a small script or FastAPI endpoint that gathers the contract from local
     sources (`/health`, `/metrics`, `/v1/models`, config parse, CLIProxy health).
   - Tests mock the sources; no external-provider calls in unit tests.
   - Depends on data contract.

3. **feat(admin): static/read-only dashboard page**
   - Render the aggregator output into a local operator page.
   - Link out to LiteLLM UI, CLIProxy management, CPA-Manager, and Langfuse.
   - No write actions.
   - Depends on aggregator.

4. **feat(admin): routing/fallback events panel**
   - Show router settings, fallback matrix, and provider signal metrics from #59.
   - Add cooldown/rate-limit log ingestion only if a safe bounded log source is
     defined.
   - Depends on aggregator + #59/#60 (already complete).

5. **feat(admin): tenant/team panel** *(deferred)*
   - Implement tenant/workspace/team views after #30/#56 defines the model.
   - Depends on #56 and follow-up tenancy implementation issues.

---

## 7. Safety and operational notes

- Do not expose the admin console publicly through the Cloudflare tunnel without a
  separate auth/access decision.
- Never display raw OAuth tokens, API keys, or `.env` secret values.
- Treat the LiteLLM master key and CLIProxy management key as privileged; prefer
  server-side checks over browser-exposed keys.
- For first implementation, expose only localhost / operator-network access.
- Keep write actions out of scope until audited separately.

---

## 8. References

- [`RUNBOOK.md`](../RUNBOOK.md) — health, model tests, auth, MCP operations.
- [`CLAUDE.md`](../CLAUDE.md) — stack architecture, ports, CPA-Manager notes.
- [`docs/ADAPTIVE_ROUTING.md`](./ADAPTIVE_ROUTING.md) — routing signals and fallback strategy.
- [`docs/ADMIN_CONSOLE_DATA_CONTRACT.md`](./ADMIN_CONSOLE_DATA_CONTRACT.md) — read-only panel schema for the first admin console aggregator/UI.
- [`litellm-config.yaml`](../litellm-config.yaml) — model aliases, fallbacks, router settings, MCP servers.
- [`cliproxy-setup.sh`](../cliproxy-setup.sh) — health, model sync, quota summary, E2E commands.
- Parent epic: [#32](https://github.com/echoares-lab/ai-gateway/issues/32).
