# Chargeback Attribution — Design Stub

> **Status:** Design only (no runtime behavior change). Implements the Phase 5
> optional scope for Epic #38 issue 38-21 ([#140](https://github.com/echoares-lab/ai-gateway/issues/140)).
> Builds on the routing decision audit log (38-16), budget gates (38-09), and
> tenancy telemetry plan ([TENANCY.md](./TENANCY.md) §3.1).

---

## 1. Problem

LiteLLM and Langfuse record **aggregate** spend and token usage per model, team,
and virtual key, but there is no **chargeback-ready** view that answers:

- How much did repo `ai-gateway` spend last week, broken down by agent session?
- Which credential pool drove the cost for a given team?
- What share of total gateway spend is attributable to each workspace?

Budget gates (38-09) enforce limits at the LiteLLM team level; they do not
produce finance-grade attribution reports. The `routing_decisions_log` table
(38-16) stores per-request policy context (`repo_name`, `agent_id`, `team_id`,
`requested_model`, `decision_json`) but is not yet joined to token/cost data from
Langfuse or LiteLLM spend tables.

---

## 2. Goal

Deliver **spend attribution by repo and agent** (and upstream tenancy dimensions)
by correlating policy routing decisions with Langfuse trace costs.

Non-goals for this stub:

- Invoice generation or external billing system integration.
- Real-time per-request cost enforcement (budget gates cover that).
- Evaluation-driven quality scoring (38-19).
- MCP tool visibility filters (38-20).

---

## 3. Attribution dimensions

Chargeback rolls up along the tenancy hierarchy defined in TENANCY.md:

| Dimension | Source | Chargeback use |
|-----------|--------|----------------|
| `tenant_id` (org) | `RoutingContext` / Langfuse `tenant_id` | Top-level cost center |
| `workspace_id` | Langfuse metadata | Department allocation |
| `team_id` | `routing_decisions_log.team_id` | Budget owner (LiteLLM team) |
| `repo_name` | `routing_decisions_log.repo_name` | Primary chargeback slice |
| `agent_id` | `routing_decisions_log.agent_id` | Cursor agent / automation attribution |
| `environment` | Langfuse metadata (`dev`/`staging`/`prod`) | Exclude non-prod from finance views |
| `requested_model` | Audit log + Langfuse | Model mix reporting |
| `credential_pool` | `decision_json` (38-11) | OAuth account cost attribution |

**Primary chargeback slice (v1):** `(team_id, repo_name, agent_id, period)`.

---

## 4. Data sources & join model

```text
routing_decisions_log (Postgres, 38-16)
  request_id, tenant_id, team_id, repo_name, agent_id,
  requested_model, gate, decision_json, evaluated_at
        │
        │  join on request_id (or trace_id when propagated)
        ▼
Langfuse traces API
  input_tokens, output_tokens, total_cost, model, metadata tags
        │
        │  optional reconcile
        ▼
LiteLLM spend logs / LiteLLM_SpendLogs table
  per-key token counts, response_cost (pricing snapshot)
```

| Source | Granularity | Strength | Gap |
|--------|-------------|----------|-----|
| `routing_decisions_log` | per evaluate() call | repo/agent/policy context | no token counts |
| Langfuse | per LLM trace | tokens, latency, metadata | sampling gaps if trace missing |
| LiteLLM DB | per completion | authoritative spend for billed keys | weaker agent_id unless tagged |

**Correlation key (design):** propagate `request_id` from translator through
LiteLLM into Langfuse trace metadata (`metadata.request_id`). Audit log already
stores the same `request_id`. Offline aggregation job joins on this field.

Fail-open: traces without `request_id` fall back to `(team_id, repo_name)` from
Langfuse metadata tags (TENANCY.md §3.1).

---

## 5. Cost model sketch

```yaml
# policy_profiles.policy_json.chargeback (illustrative)
chargeback:
  enabled: false           # default off until Phase 5 implementation
  currency: USD
  include_environments: [prod, staging]
  exclude_agents: []       # e.g. health-check bots
  cost_basis: langfuse     # langfuse | litellm | blended
  markup_pct: 0            # optional internal markup for shared infra
  rollup_schedule: daily   # daily | weekly
```

**Estimated cost per trace:**

```text
cost_usd = (input_tokens * input_price + output_tokens * output_price) / 1e6
```

Prices sourced from LiteLLM model info or a repo-managed `pricing_snapshot`
table (refreshed weekly). Langfuse `total_cost` used when present; otherwise
compute from token counts.

---

## 6. Aggregation & reporting

Offline job (not on request hot path):

```text
Nightly chargeback rollup
  → read routing_decisions_log (window = rollup_schedule)
  → fetch Langfuse traces by request_id + metadata filters
  → compute cost per (team_id, repo_name, agent_id, model)
  → write chargeback_daily_rollups table (new migration)
  → expose ADMIN_CONSOLE panel (deferred to 38-15)
```

**Rollup table sketch (follow-up migration):**

| Column | Type | Notes |
|--------|------|-------|
| `period_date` | date | UTC day |
| `team_id` | text | LiteLLM team slug |
| `repo_name` | text | Repository |
| `agent_id` | text | Nullable for non-agent clients |
| `model` | text | Resolved model alias |
| `input_tokens` | bigint | Sum |
| `output_tokens` | bigint | Sum |
| `cost_usd` | numeric(12,4) | Sum |
| `request_count` | int | Distinct traces |

Export formats (phase 2): CSV for finance, JSON API for admin console.

---

## 7. Phased implementation

| Phase | Issue slice | Deliverable |
|-------|-------------|-------------|
| **5a** (this stub) | 38-21 | Design doc + `policy_json.chargeback` schema + dispatch |
| **5b** | follow-up | `request_id` propagation into Langfuse metadata (translator) |
| **5c** | follow-up | `chargeback_daily_rollups` migration + nightly aggregation script |
| **5d** | follow-up | Admin console chargeback panel (per-repo/agent breakdown) |
| **5e** | follow-up | RUNBOOK operator guide + retention policy |

**Dependencies:** 38-16 audit log (done), TENANCY metadata in translator
([#79](https://github.com/echoares-lab/ai-gateway/pull/79)), Langfuse credentials
in RUNBOOK.md, [TOKEN_USAGE_ANALYTICS.md](./TOKEN_USAGE_ANALYTICS.md) panel schema.

**Blocked by:** none for design; runtime **5b** benefits from 38-04 translator
wire; **5c** requires stable `request_id` join path.

---

## 8. Acceptance criteria (38-21)

- [x] Repo/agent spend attribution model documented
- [x] Join path between `routing_decisions_log` and Langfuse identified
- [x] `policy_json.chargeback` schema sketched
- [x] Phased implementation breakdown (5a–5e)
- [ ] `request_id` propagated to Langfuse traces (runtime — follow-up 5b)
- [ ] Daily rollup job producing per-repo/agent cost (follow-up 5c)

---

## 9. References

- [TENANCY.md](./TENANCY.md) — §3.1 Langfuse metadata tags
- [TOKEN_USAGE_ANALYTICS.md](./TOKEN_USAGE_ANALYTICS.md) — admin console cost schema
- [ADMIN_CONSOLE.md](./ADMIN_CONSOLE.md) — per-tenant usage panels (deferred)
- `issues/policy-engine-38-16-audit-log.md` — `routing_decisions_log` writer
- `issues/policy-engine-38-21-chargeback-attribution.md` — issue tracker
