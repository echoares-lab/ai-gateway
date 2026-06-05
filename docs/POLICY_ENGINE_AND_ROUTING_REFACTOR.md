# Policy Engine and Routing Refactor

> **Status:** In progress (Epic [#38](https://github.com/echoares-lab/ai-gateway/issues/38)).
> Hybrid architecture: `policy-engine` evaluates rules; LiteLLM and CLIProxy execute routing.
> Fail-open to static `litellm-config.yaml` when policy-engine is unavailable.

Design companion: [ROUTING_AND_FAILOVER_STRATEGY.md](./ROUTING_AND_FAILOVER_STRATEGY.md) (CLIProxy
`fill-first` / `quota-aware` semantics).

---

## 1. Architecture

```text
Client → translator → policy-engine /v1/evaluate (optional, fail-open)
                    → LiteLLM (HTTP paths) → CLIProxy → Provider OAuth
                    → CLIProxy (Codex WS path, policy bypass — see §9)
```

| Component | Role |
|-----------|------|
| `translator` | Build `RoutingContext`, call evaluate, inject `metadata.routing_decision` |
| `policy-engine` | Evaluate rules, return `RoutingDecision` |
| LiteLLM | Model-level fallbacks, deployment ordering |
| CLIProxy | Credential pools, session-affinity, quota-aware routing |

---

## 2. Core schemas

Defined in `services/policy-engine/schemas.py` (issue 38-01):

- `RoutingContext` — tenancy, capabilities, rate limits, quota headroom
- `RoutingDecision` — gate, fallback chain, `session_key`, `quota_aware_mode`,
  `deprioritized_credentials`
- `RoutingDecision.to_metadata()` — serialized for LiteLLM request metadata

---

## 3. Translator integration (issue 38-04)

| Env var | Default | Purpose |
|---------|---------|---------|
| `POLICY_ENGINE_ENABLED` | `false` | When true, HTTP paths POST `/v1/evaluate` before LiteLLM forward |
| `POLICY_ENGINE_URL` | `http://policy-engine:8080` | Evaluate endpoint base |
| `POLICY_ENGINE_TIMEOUT_MS` | `100` | Fail-open timeout |

HTTP paths (`proxy`, `responses_proxy`, `claude_proxy`, `gemini_proxy`) build
`RoutingContext` from tenancy metadata and request shape, then inject
`metadata.routing_decision` via `RoutingDecision.to_metadata()`.

---

## 4. Evaluator layers

Implemented in `services/policy-engine/evaluator/`:

| Module | Issue | Scope |
|--------|-------|-------|
| `rate_limit.py` | 38-07 | Redis cooldown registry, pre-emptive deprioritization |
| `budget.py` | 38-09 | Soft gates via quota headroom % |
| `fallback.py` | 38-08 | Layered fallback ordering (§5.5) |
| `repo_affinity.py` | 38-05 | Postgres policy profiles |
| `agent_affinity.py` | 38-06 | Agent/session affinity |

---

## 5. Fallback rule ordering

### 5.5 Layered evaluation (issue 38-08)

Per-request fallback ordering in `evaluator/fallback.py`:

1. Capability hard filter
2. Policy allowlist
3. Affinity family lock
4. Rate-limit cooldown skip
5. Health-weighted order
6. Cost tier preference (budget pressure)
7. Static YAML baseline safety net

---

## 6. Quota-aware routing

First-class policy dimension (not optional). See
[ROUTING_AND_FAILOVER_STRATEGY.md §3](./ROUTING_AND_FAILOVER_STRATEGY.md#3-potential-improvements).

- `QuotaHeadroom` in `RoutingContext`
- `RoutingDecision.quota_aware_mode` and `deprioritized_credentials`
- `credential_pools.affinity_mode = quota-aware` (issue 38-10, 38-11)

---

## 7. Audit and observability

| Feature | Issue | Notes |
|---------|-------|-------|
| Audit log | 38-16 | Sampled writes to `routing_decisions_log` |
| Admin trace | 38-15 | `/admin/status` policy_engine section |
| Integration tests | 38-17 | End-to-end evaluate path |

---

## 8. HTTP path coverage

| Translator endpoint | Policy evaluate | Metadata injection |
|---------------------|-----------------|------------------|
| `POST /v1/chat/completions` (`proxy`) | When `POLICY_ENGINE_ENABLED` | LiteLLM metadata |
| `POST /v1/responses` (`responses_proxy`) | When `POLICY_ENGINE_ENABLED` | LiteLLM metadata |
| `POST /v1/messages` (`claude_proxy`) | When `POLICY_ENGINE_ENABLED` | LiteLLM metadata |
| `POST /v1beta/models/*` (`gemini_proxy`) | When `POLICY_ENGINE_ENABLED` | LiteLLM metadata |

---

## 9. WebSocket path — Codex bypass (issue 38-14)

| Translator endpoint | Policy evaluate | Routing metadata | Upstream |
|---------------------|-----------------|------------------|----------|
| `WS /v1/responses` (`responses_websocket`) | **Bypass** (default) | None at upgrade | CLIProxy direct (`CLIPROXY_WS_URL`) |

### Decision: explicit bypass (Option B)

Codex CLI multi-turn sessions use `WS /v1/responses`, which the translator proxies
**directly to CLIProxy** — not through LiteLLM. Policy evaluation on the HTTP path
injects `metadata.routing_decision` into LiteLLM requests; that injection point does
not exist on the WebSocket upgrade path.

**Rationale for bypass (not blocking):**

1. **Upstream shape:** WS traffic skips LiteLLM entirely; `RoutingDecision.to_metadata()`
   has no consumer on this path today.
2. **Model unknown at upgrade:** The requested model arrives in the first WebSocket
   frame, after the HTTP 101 upgrade completes. Evaluating at upgrade would require a
   second evaluate on first message or a model-agnostic stub decision.
3. **Latency budget:** Codex WS sessions are latency-sensitive; adding a 100ms evaluate
   round-trip on every reconnect would degrade multi-turn UX.
4. **CLIProxy routing still applies:** Session-affinity, `fill-first`, and
   `quota-aware` credential selection remain active in CLIProxy for WS traffic.

### Optional future parity

Set `POLICY_ENGINE_WS_EVALUATE=true` **and** `POLICY_ENGINE_ENABLED=true` (issue 38-04)
to attempt evaluate on WS upgrade using tenancy from the auth header. When a decision
is returned, the translator may forward `session_key` as `X-Session-ID` and
`quota_aware_mode` hints to CLIProxy upstream headers. **Default remains bypass** until
38-04 ships and Gate C Codex WS smoke passes.

| Env var | Default | Purpose |
|---------|---------|---------|
| `POLICY_ENGINE_WS_EVALUATE` | `false` | Opt-in evaluate on WS upgrade (requires 38-04) |

### Admin visibility

`/admin/status` → `panels.routing.data.websocket_policy_bypass` reports whether WS
traffic bypasses policy-engine (issue 38-15 extends with full `policy_engine` panel).

---

## 10. Issue breakdown

Atomic issues under `issues/policy-engine-38-*.md`. See
[issues/policy-engine-dispatch.md](../issues/policy-engine-dispatch.md) for phase order,
parallel lanes, and claim status.

| Phase | Issues |
|-------|--------|
| 0 | Phase 0 prerequisites |
| 1 | 38-01 … 38-04 |
| 2 | 38-05 … 38-09 |
| 3 | 38-10 … 38-14 |
| 4 | 38-15 … 38-18 |
| 5 | 38-19 … 38-21 (optional) |

---

## 11. Rollout stages

Production enablement is phased; do not set `POLICY_ENGINE_ENABLED=true` on stable
until admin trace (38-15) ships.

| Stage | Flag | Scope |
|-------|------|-------|
| 0 | `false` | Default — static YAML routing only |
| 1 | `true` dev slots | HTTP paths only; WS bypass documented |
| 2 | `true` stable | HTTP paths; monitor audit log (38-16) |
| 3 | Optional | `POLICY_ENGINE_WS_EVALUATE=true` after Gate C WS smoke |
