# Admin Console Data Contract

> **Status:** Contract design (no runtime behavior change). Child issue for
> [#32 — Unified admin console](https://github.com/echoares-lab/ai-gateway/issues/32),
> based on [`docs/ADMIN_CONSOLE.md`](./ADMIN_CONSOLE.md). This document defines
> the read-only payload shape for the first admin console aggregator and UI.

---

## 1. Contract goals

The first admin console implementation should be read-only and deterministic. The
aggregator emits one JSON document made of panel payloads. Each panel declares:

- `status`: `ok`, `warning`, `error`, or `unknown`
- `generated_at`: ISO-8601 UTC timestamp
- `source`: source-of-truth identifier
- `freshness_seconds`: age of the data if known
- `errors`: bounded, redacted error list
- panel-specific `data`

The contract is intentionally source-oriented: every field names where it came
from so the UI can link operators back to LiteLLM, CLIProxy/CPA-Manager,
Langfuse, Prometheus, or repo config.

---

## 2. Top-level payload

```json
{
  "schema_version": "admin-console.v1",
  "generated_at": "2026-06-02T02:45:00Z",
  "environment": {
    "stack": "stable",
    "translator_base_url": "http://localhost:4000",
    "litellm_ui_url": "http://localhost:4001",
    "cliproxy_management_url": "http://localhost:8317/management.html",
    "cpa_manager_url": "http://localhost:18317/management.html"
  },
  "panels": {
    "health": {},
    "models": {},
    "providers": {},
    "routing": {},
    "config_drift": {}
  }
}
```

### Field rules

- `schema_version` changes only when a breaking contract change is introduced.
- `generated_at` is set by the aggregator, not by individual sources.
- URLs are operator-local URLs; never publish management links through the public
  Cloudflare tunnel without a separate access-control issue.
- Panel keys may be absent if a feature is disabled, but the aggregator should
  prefer present-with-`unknown` over silently omitting core panels.

---

## 3. Shared panel shape

```json
{
  "status": "ok",
  "source": "translator:/health",
  "freshness_seconds": 0,
  "errors": [],
  "data": {}
}
```

### Status semantics

| Status | Meaning |
|---|---|
| `ok` | Source was reachable and data is within expected thresholds. |
| `warning` | Source reachable but degraded, stale, partial, or near limit. |
| `error` | Source unreachable or reports a blocking failure. |
| `unknown` | Source not configured, unavailable by design, or dependency deferred. |

### Error object

```json
{
  "code": "source_unreachable",
  "message": "translator /metrics timed out after 2s",
  "source": "translator:/metrics",
  "redacted": true
}
```

Rules:

- `message` must be bounded (recommended max 500 chars).
- No raw tokens, bearer headers, OAuth refresh tokens, API keys, cookies, or full
  `.env` values.
- If an upstream error includes a secret-looking value, replace it with
  `[redacted]` and set `redacted: true`.

---

## 4. Health panel

### Source(s)

- Translator `GET /health`
- Docker/container state from `./cliproxy-setup.sh health` output or future API
- Optional: LiteLLM health endpoint and CLIProxy reachability

### Payload

```json
{
  "status": "ok",
  "source": "translator:/health + cliproxy-setup:health",
  "freshness_seconds": 0,
  "errors": [],
  "data": {
    "services": [
      {"name": "translator", "status": "ok", "endpoint": "http://localhost:4000/health"},
      {"name": "litellm", "status": "ok", "endpoint": "http://localhost:4001"},
      {"name": "cliproxy", "status": "ok", "endpoint": "http://localhost:8317"},
      {"name": "cpa-manager", "status": "unknown", "endpoint": "http://localhost:18317/management.html"}
    ]
  }
}
```

### Degraded fixture

```json
{
  "status": "warning",
  "source": "cliproxy-setup:health",
  "freshness_seconds": 0,
  "errors": [
    {"code": "provider_token_expiring", "message": "antigravity access token expires in 28m", "source": "cliproxy"}
  ],
  "data": {
    "services": [
      {"name": "translator", "status": "ok"},
      {"name": "cliproxy", "status": "warning"}
    ]
  }
}
```

---

## 5. Models panel

### Source(s)

- Client-visible models: `GET /v1/models` through translator, authorized with
  `LITELLM_MASTER_KEY` server-side only.
- Configured models: `litellm-config.yaml` `model_list`.

### Payload

```json
{
  "status": "ok",
  "source": "translator:/v1/models + repo:litellm-config.yaml",
  "freshness_seconds": 0,
  "errors": [],
  "data": {
    "visible_count": 32,
    "configured_count": 32,
    "prefix": "AI-Gateway:",
    "models": [
      {
        "id": "AI-Gateway:claude-sonnet-4-6",
        "config_alias": "claude-sonnet-4-6",
        "provider_family": "anthropic",
        "visible": true,
        "configured": true,
        "notes": []
      }
    ],
    "drift": []
  }
}
```

### Drift fixture

```json
{
  "status": "warning",
  "source": "translator:/v1/models + repo:litellm-config.yaml",
  "freshness_seconds": 0,
  "errors": [],
  "data": {
    "visible_count": 31,
    "configured_count": 32,
    "drift": [
      {"model": "gpt-5-3-codex", "kind": "configured_not_visible", "severity": "warning"}
    ]
  }
}
```

---

## 6. Providers panel

### Source(s)

- `./cliproxy-setup.sh health`
- `./cliproxy-setup.sh quota-summary`
- CPA-Manager usage service/UI

### Payload

```json
{
  "status": "ok",
  "source": "cliproxy-setup:health + cliproxy-setup:quota-summary",
  "freshness_seconds": 60,
  "errors": [],
  "data": {
    "providers": [
      {
        "name": "claude",
        "account_label": "firetvstream@gmail.com",
        "auth_status": "active",
        "token_expires_in_minutes": 268,
        "quota_status": "ok",
        "recent_requests": 120,
        "recent_errors": {"401": 0, "429": 0, "503": 0}
      },
      {
        "name": "codex",
        "account_label": "matthewgraypdx@gmail.com",
        "auth_status": "active",
        "token_expires_in_minutes": 13972,
        "quota_status": "ok",
        "recent_requests": 50,
        "recent_errors": {"401": 0, "429": 2, "503": 0}
      }
    ]
  }
}
```

### Redaction rules

- `account_label` may show an email if `cliproxy-setup.sh health` already prints
  it to operators; UI should support obfuscation later (`m***@example.com`).
- Never include OAuth access/refresh tokens, management keys, or `.env` values.
- If quota APIs return raw credential identifiers, hash or redact them.

---

## 7. Routing panel

### Source(s)

- `litellm-config.yaml`: `router_settings`, `litellm_settings.fallbacks`
- Translator `/metrics` provider signal series from #59:
  - `translator_provider_request_duration_seconds`
  - `translator_provider_requests_total`
  - `translator_provider_rate_limits_total`
- Optional bounded LiteLLM log source for cooldown/fallback events

### Payload

```json
{
  "status": "ok",
  "source": "repo:litellm-config.yaml + translator:/metrics",
  "freshness_seconds": 15,
  "errors": [],
  "data": {
    "router_settings": {
      "enable_pre_call_checks": true,
      "routing_strategy": "latency-based-routing",
      "cooldown_time": 60,
      "allowed_fails": 3,
      "num_retries": 2
    },
    "fallbacks": [
      {"model": "gpt-5-3-codex", "targets": ["claude-sonnet-4-6", "gemini-3-flash"]},
      {"model": "claude-sonnet-4-6", "targets": ["gpt-5-4", "gemini-3-flash"]}
    ],
    "provider_signals": [
      {"provider": "anthropic", "model": "claude-sonnet-4-6", "outcome": "success", "requests": 100},
      {"provider": "openai", "model": "gpt-5-3-codex", "outcome": "rate_limited", "requests": 2}
    ],
    "cooldown_events": [],
    "websocket_policy_bypass": true,
    "websocket_policy_evaluate_enabled": false,
    "policy_engine_enabled": false,
    "policy_engine": {
      "enabled": false,
      "trace_enabled": true,
      "policy_version": "v0-stub",
      "redis_connected": true,
      "last_evaluate_ms": 12.5,
      "last_decision": {
        "gate": "allow",
        "rules_applied": ["repo:affinity", "quota:deprioritize"],
        "policy_version": "v0-stub",
        "quota_aware_mode": true,
        "deprioritized_credentials": ["cred-low-headroom"],
        "session_key": "[redacted]"
      }
    }
  }
}
```

`websocket_policy_bypass` (issue 38-14): when `true`, `WS /v1/responses` skips
policy-engine evaluate and proxies directly to CLIProxy.

`policy_engine` (issue 38-15): nested under `panels.routing.data` when
`ADMIN_POLICY_TRACE_ENABLED=true` (default). Exposes `POLICY_ENGINE_ENABLED`,
`last_evaluate_ms`, bounded `last_decision` (`rules_applied`, `quota_aware_mode`,
`deprioritized_credentials` when quota-aware), Redis connectivity, and
`policy_version` from policy-engine health or last decision. `session_key` is
always `[redacted]` in operator views.

### Warning fixture

```json
{
  "status": "warning",
  "source": "repo:litellm-config.yaml + translator:/metrics",
  "freshness_seconds": 15,
  "errors": [],
  "data": {
    "provider_signals": [
      {"provider": "openai", "model": "gpt-5-3-codex", "outcome": "rate_limited", "requests": 8}
    ],
    "cooldown_events": [
      {"model": "gpt-5-3-codex", "provider": "openai", "seconds_remaining": 42}
    ]
  }
}
```

---

## 7.1 Policy engine panel (issue 38-15)

Operator-facing trace of policy-engine evaluate output. Mirrors
`RoutingDecision.to_metadata()` from `services/policy-engine/schemas.py` — the same
shape the translator injects as `metadata.routing_decision` on HTTP paths (issue
38-04). Design reference:
[`docs/POLICY_ENGINE_AND_ROUTING_REFACTOR.md`](./POLICY_ENGINE_AND_ROUTING_REFACTOR.md).

### Source(s)

- Translator env: `POLICY_ENGINE_ENABLED`, `POLICY_ENGINE_WS_EVALUATE`
- Policy-engine `GET /health` (optional reachability)
- Bounded recent rows from `routing_decisions_log` (issue 38-16, sampled audit)

### `policy_decision` object

Each trace row exposes a `policy_decision` object with these fields (all map 1:1 to
`RoutingDecision`; `debug` is never surfaced in admin payloads):

| Field | Type | Notes |
|---|---|---|
| `gate` | `allow` \| `deny` \| `throttle` | Hard gate outcome |
| `deny_reason` | string \| null | Present when `gate` is `deny` or `throttle` |
| `retry_after_seconds` | integer \| null | Throttle hint for clients |
| `allowed_models` | string[] | Post-capability-filter allowlist |
| `fallback_chain` | string[] | Ordered model fallbacks for this request |
| `ordered_deployments` | string[] | LiteLLM deployment ordering hint |
| `credential_tier_preference` | string \| null | e.g. `pro`, `max` |
| `preferred_credential_id` | string \| null | Redact or hash in UI (see below) |
| `session_key` | string \| null | CLIProxy session-affinity key; truncate in UI |
| `lock_model_family` | boolean | Affinity family lock |
| `cache_cold_start` | boolean | Cold-start routing hint |
| `quota_aware_mode` | boolean | CLIProxy quota-aware affinity active |
| `deprioritized_credentials` | string[] | Pre-emptive skip list; redact IDs |
| `policy_version` | string | Evaluator version stamp |
| `evaluated_at` | ISO-8601 UTC | Decision timestamp |
| `rules_applied` | string[] | Evaluator rule IDs, e.g. `rate_limit:cooldown` |

### Payload

```json
{
  "status": "ok",
  "source": "translator:env + policy-engine:/health + postgres:routing_decisions_log",
  "freshness_seconds": 30,
  "errors": [],
  "data": {
    "policy_engine_enabled": false,
    "websocket_policy_bypass": true,
    "websocket_policy_evaluate_enabled": false,
    "policy_engine_url": "http://policy-engine:8080",
    "policy_engine_reachable": true,
    "policy_version": "v0-stub",
    "recent_decisions": [
      {
        "request_id": "req-abc123",
        "tenant_id": "echoares",
        "team_id": "eng",
        "repo_name": "ai-gateway",
        "agent_id": null,
        "requested_model": "claude-sonnet-4-6",
        "gate": "allow",
        "evaluated_at": "2026-06-05T12:00:00Z",
        "policy_decision": {
          "gate": "allow",
          "deny_reason": null,
          "retry_after_seconds": null,
          "allowed_models": ["claude-sonnet-4-6"],
          "fallback_chain": ["claude-sonnet-4-6", "gpt-5-4", "gemini-3-flash"],
          "ordered_deployments": [],
          "credential_tier_preference": null,
          "preferred_credential_id": null,
          "session_key": "agent-abc",
          "lock_model_family": false,
          "cache_cold_start": false,
          "quota_aware_mode": true,
          "deprioritized_credentials": ["cred-…[redacted]"],
          "policy_version": "v0-stub",
          "evaluated_at": "2026-06-05T12:00:00Z",
          "rules_applied": ["repo_affinity:team-eng", "rate_limit:deprioritize"]
        }
      }
    ],
    "deny_throttle_count_1h": 0
  }
}
```

### Field rules

- `recent_decisions` is bounded (recommended max 20 rows), newest first. When
  `POLICY_ENGINE_ENABLED=false`, return an empty list with `status: unknown` rather
  than omitting the panel.
- `policy_decision` in list rows is the full `RoutingDecision.to_metadata()` shape;
  omit `debug` even when present in evaluate responses.
- `deny_throttle_count_1h` counts `gate` in (`deny`, `throttle`) from audit log or
  metrics; used for operator alerting.
- Duplicate routing-panel flags (`policy_engine_enabled`, `websocket_policy_bypass`,
  `websocket_policy_evaluate_enabled`) may appear here for a self-contained panel;
  values must match `panels.routing.data`.

### Redaction rules

- `preferred_credential_id` and entries in `deprioritized_credentials`: show
  truncated hash or `[redacted]`; never raw OAuth credential identifiers.
- `session_key`: show first 8 chars + `…` unless operator enables full display in a
  future audited action.
- No `debug` blob, no full `RoutingContext`, no API keys or bearer tokens.

### Disabled fixture

```json
{
  "status": "unknown",
  "source": "translator:env",
  "freshness_seconds": 0,
  "errors": [],
  "data": {
    "policy_engine_enabled": false,
    "websocket_policy_bypass": true,
    "websocket_policy_evaluate_enabled": false,
    "policy_engine_reachable": null,
    "recent_decisions": [],
    "deny_throttle_count_1h": null
  }
}
```

### Throttle fixture

```json
{
  "status": "warning",
  "source": "postgres:routing_decisions_log",
  "freshness_seconds": 15,
  "errors": [],
  "data": {
    "policy_engine_enabled": true,
    "recent_decisions": [
      {
        "request_id": "req-throttle-1",
        "requested_model": "gpt-5-3-codex",
        "gate": "throttle",
        "evaluated_at": "2026-06-05T12:05:00Z",
        "policy_decision": {
          "gate": "throttle",
          "deny_reason": "team budget 95% consumed",
          "retry_after_seconds": 60,
          "allowed_models": [],
          "fallback_chain": [],
          "quota_aware_mode": false,
          "deprioritized_credentials": [],
          "policy_version": "v0-stub",
          "evaluated_at": "2026-06-05T12:05:00Z",
          "rules_applied": ["budget:soft_gate"]
        }
      }
    ],
    "deny_throttle_count_1h": 3
  }
}
```

---

## 8. Config drift panel

### Source(s)

- Repo config files: `litellm-config.yaml`, `.env.example`, `docker-compose.yml`
- Runtime config: LiteLLM DB/API where available
- CI-equivalent syntax checks

### Payload

```json
{
  "status": "ok",
  "source": "repo:config + litellm:runtime",
  "freshness_seconds": 0,
  "errors": [],
  "data": {
    "checks": [
      {"name": "litellm_yaml_parse", "status": "ok"},
      {"name": "hardcoded_api_keys", "status": "ok"},
      {"name": "shell_syntax", "status": "ok"}
    ],
    "runtime_overrides": [],
    "missing_env_vars": []
  }
}
```

### Warning fixture

```json
{
  "status": "warning",
  "source": "repo:config + litellm:runtime",
  "freshness_seconds": 0,
  "errors": [],
  "data": {
    "runtime_overrides": [
      {"table": "LiteLLM_ToolTable", "item": "search_tools", "reason": "runtime DB config may override repo config"}
    ],
    "missing_env_vars": [
      {"name": "BRAVE_API_KEY", "referenced_by": "mcp-brave", "severity": "warning"}
    ]
  }
}
```

---

## 9. Tenant/team fields (pending)

Tenant-aware fields are reserved but must remain `unknown` or omitted until the
#30/#56 tenancy model is merged.

```json
{
  "status": "unknown",
  "source": "pending:#56",
  "freshness_seconds": null,
  "errors": [
    {"code": "dependency_pending", "message": "tenant/workspace model pending #56", "source": "github:#56"}
  ],
  "data": {
    "tenants": []
  }
}
```

---

## 10. Aggregator implementation requirements

Future aggregator issue (#69) must follow these contract rules:

1. **Read-only only** — no auth refreshes, config writes, DB writes, or model sync.
2. **Bounded calls** — short timeouts per source; unavailable sources degrade to
   `warning`/`unknown` rather than blocking the whole payload.
3. **Secret redaction** — redact obvious token/key patterns and never expose raw
   headers or `.env` values.
4. **Stable schema** — include `schema_version` and fixture tests.
5. **Deterministic tests** — unit tests mock all live sources; no provider OAuth
   required for contract tests.
6. **Operator-local by default** — first implementation should bind only to local
   or dev-stack networks.

---

## 11. References

- [`docs/ADMIN_CONSOLE.md`](./ADMIN_CONSOLE.md) — parent design and implementation plan.
- [`docs/POLICY_ENGINE_AND_ROUTING_REFACTOR.md`](./POLICY_ENGINE_AND_ROUTING_REFACTOR.md) — policy-engine architecture, `RoutingDecision` schema, translator injection, and admin trace (38-15).
- [`docs/ADAPTIVE_ROUTING.md`](./ADAPTIVE_ROUTING.md) — routing inputs and provider signals.
- [`docs/openapi/policy-engine.yaml`](./openapi/policy-engine.yaml) — OpenAPI schema for `RoutingDecision`.
- [`RUNBOOK.md`](../RUNBOOK.md) — operational command sources.
- [`litellm-config.yaml`](../litellm-config.yaml) — model, router, fallback, and MCP config.
- Child implementation issue: #69 (read-only status aggregator).
