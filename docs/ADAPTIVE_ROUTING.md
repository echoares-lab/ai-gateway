# Adaptive Provider Routing — Design & Telemetry Plan

> **Status:** Design (no runtime behavior change). Foundational design for
> [Roadmap Epic #31 — Adaptive provider intelligence](https://github.com/echoares-lab/ai-gateway/issues/31).
> This document defines the routing inputs, the dynamic routing strategy, the
> telemetry required to drive it, and the broken-down implementation plan.
> Implementation lands in the child issues linked in §6.

---

## 1. Context & current baseline

Routing today is **static and hand-tuned**:

- **`litellm_settings.fallbacks`** in `litellm-config.yaml` is a per-model ordered
  list. When the primary model errors, LiteLLM walks the list in fixed order
  regardless of which alternative is currently healthy. Example:

  ```yaml
  fallbacks:
    - claude-sonnet-4-6: ["gpt-5-4", "gemini-3-flash"]
    - gpt-5-5:           ["claude-opus-4-7", "gemini-3-1-pro"]
  ```

- **`router_settings.enable_pre_call_checks: true`** lets LiteLLM skip deployments
  that fail a cheap pre-call check (e.g. context-window fit), but the ordering of
  healthy deployments is otherwise static.

- **Background health checks** are documented but **disabled by default**
  (`background_health_checks` commented out) because Gemini Pro models have strict
  per-minute limits; several models carry `disable_background_health_check: true`.

- **Gateway Engine-side retry** is narrow: `_post_with_retry()` in
  `services/gateway-engine/gateway-engine.py` retries only transient `502`/`503` from
  LiteLLM, with a fixed 1s sleep and 2 retries. It has no awareness of *which
  provider* failed or its recent error history.

**Consequence:** when a provider is degraded or rate-limited (429), the gateway
keeps sending traffic to it until it hard-fails, then walks a fixed fallback list
that may itself point at an equally-degraded alternative. There is no feedback
loop from observed provider behavior into routing decisions.

The goal of epic #31 is to evolve this into **adaptive routing**: ordering and
skipping providers based on observed health, latency, recent error/rate-limit
patterns, and capability fit.

---

## 1a. Two-tier Gemini failover (antigravity → gemini-cli)

Gemini models are served by **two independent OAuth credential pools** inside
CLIProxy, exposed under **different model ids**:

| Tier | CLIProxy provider | OAuth files | Example model ids it serves |
|---|---|---|---|
| 1 (primary) | `antigravity` | `antigravity-<email>.json` | `gemini-3-flash`, `gemini-3.1-pro-low`, `gemini-3-pro-high` |
| 2 (failover) | `gemini-cli` | `gemini-<email>-<project>.json` | `gemini-3-flash-preview`, `gemini-3.1-pro-preview`, `gemini-3-pro-preview` |

Because the two providers register **different model ids**, a request for an
antigravity id (`gemini-3-flash`) will **never** fall over to gemini-cli inside
CLIProxy on its own — when all antigravity credentials cool down, CLIProxy
returns `429 model_cooldown` with no alternative. The failover is therefore
wired explicitly at the **LiteLLM layer** (this is **failover, not
round-robin** — Tier 2 is only reached after Tier 1 errors):

1. **CLIProxy** `oauth-model-alias.gemini-cli` exposes each gemini-cli base
   model under a client-visible `-via-gcli` alias that routes **exclusively** to
   gemini-cli credentials.
2. **LiteLLM** defines a matching `*-via-gcli` model entry and inserts it as the
   first fallback for the corresponding antigravity model
   (e.g. `gemini-3-flash → [gemini-3-flash-via-gcli, claude-haiku-4-5, …]`).

### Required `~/.cliproxy/config.yaml` block

> ⚠️ **This file is not tracked in the repo** (it is bind-mounted live). Keep it
> in sync with this reference. The `name:` of each alias **must be a model the
> gemini-cli provider actually serves** — i.e. the `-preview` variant, **not**
> the antigravity model id. Using an antigravity id here silently produces no
> model (the alias never appears in `/v1/models`), which is the failure mode that
> originally broke the gemini-3 tier-2 routes.

```yaml
oauth-model-alias:
  gemini-cli:
  - name: gemini-3-flash-preview        # NOT gemini-3-flash (antigravity-only)
    alias: gemini-3-flash-via-gcli
  - name: gemini-3.1-pro-preview        # NOT gemini-3.1-pro-low
    alias: gemini-3-1-pro-via-gcli
  - name: gemini-3.1-flash-lite-preview # NOT gemini-3.1-flash-lite
    alias: gemini-3-1-flash-lite-via-gcli
  - name: gemini-2.5-flash
    alias: gemini-2-5-flash-via-gcli
  - name: gemini-2.5-flash-lite
    alias: gemini-2-5-flash-lite-via-gcli
  - name: gemini-3-pro-preview          # NOT gemini-3-pro-high
    alias: gemini-3-pro-high-via-gcli
  - name: gemini-2.5-pro
    alias: gemini-2-5-pro-via-gcli
```

After editing this file, **restart CLIProxy** (`docker compose restart cliproxy`)
— the auth-dir/config watcher does not reliably pick up in-place edits to the
single bind-mounted config file. Verify with:

```bash
source .env
curl -s http://localhost:8317/v1/models -H "Authorization: Bearer $CLIPROXY_API_KEY" \
  | python3 -c "import sys,json;[print(m['id']) for m in json.load(sys.stdin)['data'] if 'gcli' in m['id']]"
# Expect all 7 -via-gcli ids, including gemini-3-flash-via-gcli and gemini-3-1-pro-via-gcli.
```

---

## 2. Routing inputs

Adaptive routing decisions are driven by the following inputs. Each is defined
here; §3 describes how they combine, and §4 maps each to a concrete source.

| Input | Definition | Granularity | Time window |
|---|---|---|---|
| **Health** | Is the provider/model currently serving successful responses? | per model deployment | rolling (live) |
| **Latency** | Recent response latency (p50 / p95) | per model deployment | rolling 5–15 min |
| **Error pattern** | Recent rate of `5xx` and connection/timeout failures | per model deployment | rolling 5–15 min |
| **Rate-limit pattern** | Recent `429` (and provider-specific quota-exhaustion) frequency, plus active cooldown state | per provider + model | rolling + cooldown TTL |
| **Capability fit** | Does the model support what the request needs — tool calling, vision/image input, required context length? | per model (static caps) × per request (needs) | per request |
| **Tenant preference** *(optional)* | Per-tenant/workspace routing preferences and allow/deny lists | per tenant × request | config |

### Capability fit detail

Capability fit is a **hard filter**, applied before health/latency scoring:

- **Tools:** if the request carries `tools`, only tool-capable models are eligible.
  (The gateway-engine already has `_maybe_preview_fallback()` handling a tools-vs-preview
  case — adaptive routing generalizes this.)
- **Vision:** if the request carries image content (`input_image` / image parts),
  only vision-capable models are eligible.
- **Context length:** if the prompt token estimate exceeds a model's context
  window, that model is ineligible — this overlaps with `enable_pre_call_checks`.

### Health / latency / error scoring

The first three inputs combine into a per-deployment **routing score** used to
order eligible deployments. A reference scoring shape (final weights tuned in
implementation):

```
score = w_h * health_factor      # 1.0 healthy, →0 as recent errors rise
      - w_l * normalized_latency  # penalize slow deployments
      - w_e * recent_error_rate   # penalize recent 5xx / timeouts
      - w_r * rate_limit_penalty  # heavy penalty while in 429 cooldown
```

A deployment in an **active rate-limit cooldown** is deprioritized to the bottom
(or skipped) until its cooldown TTL expires, rather than removed permanently.

---

## 3. Dynamic routing strategy

The strategy evolves the static baseline in three layers, preferring
**LiteLLM-native controls** where they fit and adding **gateway-engine-side logic**
only where LiteLLM cannot express the decision. This respects the ADR mandate
(`docs/ARCHITECTURE.md` §2) that the gateway-engine stays a thin format/credential
layer — adaptive *routing* lives in LiteLLM/router config wherever possible;
the gateway-engine only contributes **signal capture** and request-shape-derived
**capability hints**.

### Layer A — LiteLLM-native router controls (preferred)

Lean on existing router features before writing custom logic:

- **`routing_strategy`** — adopt a latency/usage-aware strategy
  (e.g. `latency-based-routing` / lowest-latency) for model *groups* that have
  multiple deployments, instead of pure first-in-list ordering.
- **`cooldown_time` + `allowed_fails`** — let LiteLLM automatically cool down a
  deployment after N failures within a window, so 429/5xx bursts deprioritize a
  provider without manual intervention.
- **`enable_pre_call_checks: true`** — keep; it already covers context-window and
  basic capability pre-filtering.
- **`fallbacks`** — retained as the *capability-correct* candidate set per model;
  adaptive logic reorders/skips **within** these sets rather than replacing them.

### Layer B — Signal-informed ordering

The fallback candidate set for a model is **reordered** at decision time by the
routing score (§2). The static list defines *which* providers are
capability-valid alternatives; the score decides *what order* to try them in and
whether to skip ones currently in cooldown.

### Layer C — Gateway Engine-side capability hints (minimal)

The gateway-engine already inspects request shape (tools, image content) to make
`_maybe_preview_fallback()` decisions. Adaptive routing extends this only to
**annotate** requests with derived capability needs (tools / vision / token
estimate) passed as metadata, so LiteLLM's pre-call checks and the scorer can
filter correctly. **No tool-execution or routing dispatch logic is added to the
gateway-engine** (per ARCHITECTURE.md §2.2).

### Decision flow (per request)

```
request
  → derive capability needs (tools? vision? token estimate)      [gateway-engine]
  → eligible = models passing capability fit + pre-call checks    [LiteLLM]
  → order eligible by routing score (health/latency/error/429)    [LiteLLM router + signals]
  → skip deployments in active 429/5xx cooldown                   [LiteLLM cooldown]
  → try in order; on failure, record signal + advance             [LiteLLM fallbacks]
```

---

## 4. Telemetry — current vs. needed (gap analysis)

Adaptive decisions require signals. Below is what exists today and what must be
added (the **needed** rows become child issue #59).

### Available today

| Signal | Source | Granularity | Usable for routing as-is? |
|---|---|---|---|
| Request latency | `REQUEST_LATENCY` histogram (gateway-engine) | by HTTP method + path | ❌ not per-provider/model |
| Upstream errors | `UPSTREAM_ERRORS` counter (gateway-engine) | by path + status | ⚠️ path-level, not provider-attributed |
| Request counts | `REQUEST_COUNT` counter (gateway-engine) | method/path/status | ⚠️ no model dimension |
| Cache hit/miss | `CACHE_HITS` / `CACHE_MISSES` | by path/kind | n/a for routing |
| LiteLLM spend/usage | LiteLLM DB (`store_model_in_db`) + Langfuse traces | per model/key | ✅ but offline (not live routing input) |
| Model health page | LiteLLM background health checks | per model | ⚠️ disabled by default for quota reasons |

### Needed (gaps to close)

| Needed signal | Why | Proposed source |
|---|---|---|
| **Per-provider/model latency (p50/p95)** | latency-aware ordering | Prometheus histogram labeled by model/provider; LiteLLM router latency stats |
| **Per-provider/model error rate (5xx/timeout)** | health scoring | Prometheus counter labeled by model + error class |
| **Per-provider 429 / quota-exhaustion events + cooldown state** | rate-limit-aware skip | LiteLLM `allowed_fails`/cooldown state + CLIProxy quota signals (`cliproxy-setup.sh quota-summary`) |
| **Capability metadata on requests** | capability-fit filtering | gateway-engine request-shape annotation (tools/vision/tokens) |
| **Tenant attribution** *(optional)* | tenant-aware routing | tenant metadata from epic #30 model (#56) |

**Constraint:** signal capture must **not** rely on enabling background health
checks globally — Gemini Pro models have ~5 req/min limits and several already
set `disable_background_health_check: true`. Prefer **passive** signals captured
from real traffic over **active** probing.

---

## 5. Risks & constraints

- **Probing cost vs. quota:** active health probing can exhaust low-limit
  provider quotas. Prefer passive in-traffic signals; gate any active probe behind
  per-model opt-in.
- **Flapping:** naive scoring can oscillate. Use cooldown TTLs and rolling windows
  (not instantaneous state) to dampen.
- **Capability regressions:** reordering must never route a tool/vision request to
  an incapable model — capability fit is a hard filter applied *before* scoring.
- **No gateway-engine routing logic:** keep dispatch/routing in LiteLLM per ADR;
  gateway-engine only captures signals and annotates capability needs.
- **Tenant coupling:** tenant-aware routing depends on the tenancy model (#56 /
  epic #30); treat it as optional/last and do not block #59/#60 on it.

---

## 6. Implementation plan — child issues

This design breaks epic #31 into the following sequenced, individually-mergeable
child issues:

1. **#59 — feat(observability): capture per-provider health, latency, and error
   signals for routing** *(depends on this design)*
   Add per-provider/model Prometheus metrics (latency p50/p95, error rate, 429
   events + cooldown state), exposed in a form the router/scorer can consume.
   Passive (in-traffic) capture only; no global background health checks.

2. **#60 — feat(routing): adaptive fallback ordering from recent error/rate-limit
   patterns** *(depends on this design + #59)*
   Reorder/skip fallback candidates by routing score; adopt LiteLLM-native
   `routing_strategy` / `cooldown_time` / `allowed_fails`; keep capability fit as a
   hard pre-filter. Optional tenant-aware preferences coordinated with epic #30.

Each child issue carries its own acceptance criteria, tests (gateway-engine unit +
mock integration, plus real-provider integration for #60), and rollback notes.

---

## 7. References

- [`litellm-config.yaml`](../litellm-config.yaml) — `router_settings`,
  `litellm_settings.fallbacks`, background health-check notes.
- [`services/gateway-engine/gateway-engine.py`](../services/gateway-engine/gateway-engine.py) —
  `_post_with_retry()`, `_maybe_preview_fallback()`, Prometheus metrics
  (`REQUEST_LATENCY`, `UPSTREAM_ERRORS`, `REQUEST_COUNT`).
- [`docs/ARCHITECTURE.md`](./ARCHITECTURE.md) — control-plane ADR; gateway-engine
  isolation mandate.
- [Epic #31](https://github.com/echoares-lab/ai-gateway/issues/31),
  children [#59](https://github.com/echoares-lab/ai-gateway/issues/59) /
  [#60](https://github.com/echoares-lab/ai-gateway/issues/60).
